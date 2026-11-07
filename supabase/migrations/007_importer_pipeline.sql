-- 007_importer_pipeline.sql
-- ADDITIVE ONLY. Nothing is dropped and no row is deleted. The only existing object that is replaced is the CHECK
-- constraint on import_jobs.status, which is widened (every old value stays valid).
--
-- Adds:
--   * source_documents: pipeline status + reason, discovery provenance, exam date, extraction facts
--   * answer_key_entries: one row per answer parsed from an official key, with match state (admin-only, RLS on)
--   * import_jobs / import_runs: richer counters and run mode
--   * questions / papers: extraction flags, page span, exam date
--   * admin RPCs: retry_documents, confirm_answer_entry, bulk_confirm_proposed, reject_answer_entry, publish_paper

-- ---------------------------------------------------------------------------------------------------------------
-- 1. source_documents
-- ---------------------------------------------------------------------------------------------------------------
alter table public.source_documents
  add column if not exists import_status   text        not null default 'discovered',
  add column if not exists status_reason   text,
  add column if not exists link_text       text,
  add column if not exists discovery_depth smallint,
  add column if not exists exam_date       date,
  add column if not exists file_size_bytes bigint,
  add column if not exists page_count      integer,
  add column if not exists ocr_used        boolean     not null default false,
  add column if not exists detected        jsonb       not null default '{}'::jsonb,
  add column if not exists last_run_id     uuid references public.import_runs(id) on delete set null,
  add column if not exists updated_at      timestamptz not null default now();

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'source_documents_import_status_check') then
    alter table public.source_documents add constraint source_documents_import_status_check
      check (import_status in ('discovered','downloaded','extracted','classified','awaiting_review','completed','skipped','failed'));
  end if;
end $$;

-- Rows that already have a stored file are "downloaded"; they have not been extracted yet.
update public.source_documents set import_status = 'downloaded',
       status_reason = 'Stored by the previous importer; will be re-processed by the new pipeline.'
 where storage_path is not null and import_status = 'discovered';

create unique index if not exists source_documents_source_url_uidx on public.source_documents (source_url) where source_url is not null;
create index if not exists source_documents_import_status_idx on public.source_documents (import_status);
create index if not exists source_documents_last_run_idx on public.source_documents (last_run_id);
create index if not exists source_documents_exam_idx on public.source_documents (exam_id);

drop trigger if exists source_documents_set_updated_at on public.source_documents;
create trigger source_documents_set_updated_at before update on public.source_documents
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------------------------------------------
-- 2. import_jobs / import_runs
-- ---------------------------------------------------------------------------------------------------------------
alter table public.import_jobs drop constraint if exists import_jobs_status_check;
alter table public.import_jobs add constraint import_jobs_status_check
  check (status in ('pending','running','done',
                    'discovered','downloaded','extracted','classified','awaiting_review','completed','skipped','failed'));

alter table public.import_jobs
  add column if not exists questions_classified      integer not null default 0,
  add column if not exists questions_needing_review  integer not null default 0,
  add column if not exists answer_rows               integer not null default 0;

-- The previous importer parsed answer keys and then marked the job "skipped". Queue those again so the new
-- pipeline stores their entries. Jobs that failed or were skipped for another reason are left alone.
update public.import_jobs j set status = 'pending'
  from public.source_documents d
 where d.id = j.document_id and d.doc_kind = 'answer_key' and j.status = 'skipped' and j.last_error is null;

alter table public.import_runs
  add column if not exists mode text not null default 'full';
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'import_runs_mode_check') then
    alter table public.import_runs add constraint import_runs_mode_check
      check (mode in ('full','discover_only','process_only','retry_failed'));
  end if;
end $$;

-- ---------------------------------------------------------------------------------------------------------------
-- 3. questions / papers
-- ---------------------------------------------------------------------------------------------------------------
alter table public.questions
  add column if not exists extraction_flags jsonb   not null default '{}'::jsonb,
  add column if not exists source_page_end  integer;

alter table public.papers
  add column if not exists exam_date    date,
  add column if not exists import_notes text;

-- ---------------------------------------------------------------------------------------------------------------
-- 4. answer_key_entries
-- ---------------------------------------------------------------------------------------------------------------
create table if not exists public.answer_key_entries (
  id                    uuid primary key default gen_random_uuid(),
  source_document_id    uuid not null references public.source_documents(id) on delete cascade,
  exam_id               smallint references public.exams(id),
  exam_year             smallint,
  session               text,
  shift                 text,
  paper_number          smallint,
  subject_code          text,                      -- physics / chemistry / mathematics when the key is sectioned by subject
  question_number       integer,
  original_question_id  text,                      -- official question id when the key is id-based
  raw_answer            text not null,             -- exactly what the PDF said
  answer                jsonb,                     -- normalised for the matched question: ["A","C"] or 12.5; null if unparseable
  answer_kind           text not null default 'unknown'
                        check (answer_kind in ('single','multiple','numerical','unknown','dropped')),
  source_page           integer,
  paper_id              uuid references public.papers(id) on delete set null,
  match_status          text not null default 'unmatched'
                        check (match_status in ('unmatched','proposed','ambiguous','confirmed','rejected')),
  matched_question_id   uuid references public.questions(id) on delete set null,
  candidate_question_ids uuid[] not null default '{}',
  match_note            text,
  confirmed_by          uuid references auth.users(id),
  confirmed_at          timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  constraint answer_key_entries_identity_key
    unique nulls not distinct (source_document_id, subject_code, question_number, original_question_id)
);

create index if not exists answer_key_entries_document_idx on public.answer_key_entries (source_document_id);
create index if not exists answer_key_entries_paper_idx    on public.answer_key_entries (paper_id);
create index if not exists answer_key_entries_question_idx on public.answer_key_entries (matched_question_id);
create index if not exists answer_key_entries_exam_idx     on public.answer_key_entries (exam_id);
create index if not exists answer_key_entries_status_idx   on public.answer_key_entries (match_status);
create index if not exists answer_key_entries_confirmed_by_idx on public.answer_key_entries (confirmed_by);

create trigger answer_key_entries_set_updated_at before update on public.answer_key_entries
  for each row execute function public.set_updated_at();

alter table public.answer_key_entries enable row level security;
create policy "answer_key_entries admin only" on public.answer_key_entries
  for all to authenticated using (private.is_admin()) with check (private.is_admin());
revoke all on public.answer_key_entries from anon;

-- ---------------------------------------------------------------------------------------------------------------
-- 5. Admin RPCs. SECURITY INVOKER: RLS still applies, and each function also checks private.is_admin().
-- ---------------------------------------------------------------------------------------------------------------

-- Re-queue documents. Documents with a stored file restart at "downloaded"; others at "discovered".
create or replace function public.retry_documents(p_document_ids uuid[], p_queue_run boolean default true)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare v_id uuid; v_n int := 0; v_run uuid;
begin
  if not private.is_admin() then raise exception 'Administrators only.' using errcode = '42501'; end if;
  foreach v_id in array coalesce(p_document_ids, '{}') loop
    update public.source_documents
       set import_status = case when storage_path is not null then 'downloaded' else 'discovered' end,
           status_reason = 'Re-queued by an administrator.'
     where id = v_id;
    if not found then continue; end if;
    update public.import_jobs set status = 'pending', last_error = null, updated_at = now() where document_id = v_id;
    if not found then insert into public.import_jobs (document_id, status) values (v_id, 'pending'); end if;
    v_n := v_n + 1;
  end loop;
  if p_queue_run and v_n > 0 then
    insert into public.import_runs (trigger, status, mode, requested_by) values ('retry', 'queued', 'retry_failed', (select auth.uid()))
    returning id into v_run;
  end if;
  return jsonb_build_object('requeued', v_n, 'run_id', v_run);
end $$;

-- Copy one official answer onto its question. Never guesses: the entry must have a parsed answer, a question, a
-- document marked official/verified, and an answer shape that fits the question type.
create or replace function public.confirm_answer_entry(p_entry_id uuid, p_question_id uuid default null)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare e public.answer_key_entries; d public.source_documents; q public.questions; v_ok boolean;
begin
  if not private.is_admin() then raise exception 'Administrators only.' using errcode = '42501'; end if;
  select * into e from public.answer_key_entries where id = p_entry_id for update;
  if not found then raise exception 'Answer-key entry not found.'; end if;
  if e.answer is null or e.answer_kind in ('unknown','dropped') then
    raise exception 'This entry has no usable answer (%). Enter the answer by hand on the question.', e.answer_kind;
  end if;
  select * into q from public.questions where id = coalesce(p_question_id, e.matched_question_id) for update;
  if not found then raise exception 'Choose the question this answer belongs to first.'; end if;
  select * into d from public.source_documents where id = e.source_document_id;
  if d.status not in ('official','verified_archive') then
    raise exception 'The answer-key document is not marked official or verified.';
  end if;
  v_ok := case q.question_type
            when 'single_mcq' then jsonb_typeof(e.answer) = 'array' and jsonb_array_length(e.answer) = 1
            when 'multi_mcq'  then jsonb_typeof(e.answer) = 'array' and jsonb_array_length(e.answer) >= 1
            when 'numerical'  then jsonb_typeof(e.answer) = 'number' or (jsonb_typeof(e.answer) = 'object' and e.answer ? 'value')
            when 'integer'    then jsonb_typeof(e.answer) = 'number'
            else false end;
  if not v_ok then raise exception 'Answer % does not fit a % question.', e.answer, q.question_type; end if;
  if q.answer_verified and q.correct_answer is distinct from e.answer then
    raise exception 'This question already has a different verified answer (%). Review it manually.', q.correct_answer;
  end if;
  update public.questions set correct_answer = e.answer, answer_source = d.status::public.source_status,
         answer_verified = true, answer_verified_by = (select auth.uid()), answer_verified_at = now()
   where id = q.id;
  update public.answer_key_entries set match_status = 'confirmed', matched_question_id = q.id,
         confirmed_by = (select auth.uid()), confirmed_at = now() where id = e.id;
  update public.papers set answer_key_document_id = coalesce(answer_key_document_id, e.source_document_id) where id = q.paper_id;
  return jsonb_build_object('question_id', q.id, 'answer', e.answer);
end $$;

-- Confirm every "proposed" (unambiguous) entry that passes confirm_answer_entry, optionally for one paper. Questions
-- are also marked reviewed ONLY when the extraction is clean: confident classification, a chapter, no OCR, no warnings.
create or replace function public.bulk_confirm_proposed(p_paper_id uuid default null)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare r record; v_conf int := 0; v_fail int := 0; v_clean int := 0;
begin
  if not private.is_admin() then raise exception 'Administrators only.' using errcode = '42501'; end if;
  for r in select e.id, e.matched_question_id from public.answer_key_entries e
            where e.match_status = 'proposed' and e.matched_question_id is not null
              and (p_paper_id is null or e.paper_id = p_paper_id) loop
    begin
      perform public.confirm_answer_entry(r.id, r.matched_question_id);
      v_conf := v_conf + 1;
      update public.questions set needs_review = false
       where id = r.matched_question_id and needs_review
         and chapter_id is not null and coalesce(classification_confidence, 0) >= 0.75
         and coalesce((extraction_flags ->> 'ocr')::boolean, false) = false
         and coalesce(jsonb_array_length(extraction_flags -> 'warnings'), 0) = 0;
      if found then v_clean := v_clean + 1; end if;
    exception when others then v_fail := v_fail + 1;
    end;
  end loop;
  return jsonb_build_object('confirmed', v_conf, 'marked_reviewed', v_clean, 'left_for_manual', v_fail);
end $$;

create or replace function public.reject_answer_entry(p_entry_id uuid)
returns void language plpgsql security invoker set search_path = '' as $$
begin
  if not private.is_admin() then raise exception 'Administrators only.' using errcode = '42501'; end if;
  update public.answer_key_entries set match_status = 'rejected' where id = p_entry_id and match_status <> 'confirmed';
end $$;

-- Publish or unpublish a whole paper. Publishing only releases questions that are verified AND reviewed; the rest stay
-- hidden and are counted in the result. Unpublishing hides the paper and all its questions from students.
create or replace function public.publish_paper(p_paper_id uuid, p_publish boolean)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare v_pub int := 0; v_held int := 0;
begin
  if not private.is_admin() then raise exception 'Administrators only.' using errcode = '42501'; end if;
  if p_publish then
    update public.questions set is_published = true
     where paper_id = p_paper_id and answer_verified and correct_answer is not null and not needs_review and not is_published;
    select count(*) filter (where is_published), count(*) filter (where not is_published)
      into v_pub, v_held from public.questions where paper_id = p_paper_id;
    if v_pub = 0 then
      raise exception 'Nothing to publish: no question in this paper is both answer-verified and reviewed.';
    end if;
    update public.papers set is_published = true where id = p_paper_id;
    update public.source_documents set import_status = 'completed', status_reason = 'Paper published.'
     where id = (select source_document_id from public.papers where id = p_paper_id) and import_status = 'awaiting_review';
  else
    update public.questions set is_published = false where paper_id = p_paper_id and is_published;
    update public.papers set is_published = false where id = p_paper_id;
    update public.source_documents set import_status = 'awaiting_review', status_reason = 'Paper unpublished.'
     where id = (select source_document_id from public.papers where id = p_paper_id) and import_status = 'completed';
  end if;
  return jsonb_build_object('published_questions', v_pub, 'held_back', v_held, 'paper_published', p_publish);
end $$;

revoke execute on function public.retry_documents(uuid[], boolean), public.confirm_answer_entry(uuid, uuid),
  public.bulk_confirm_proposed(uuid), public.reject_answer_entry(uuid), public.publish_paper(uuid, boolean) from public, anon;
grant execute on function public.retry_documents(uuid[], boolean), public.confirm_answer_entry(uuid, uuid),
  public.bulk_confirm_proposed(uuid), public.reject_answer_entry(uuid), public.publish_paper(uuid, boolean) to authenticated;
