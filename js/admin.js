// Admin area: import control, source documents, logs, manual upload, answer-key review, question review, paper publishing.
// Every write goes through Supabase with the signed-in admin's session; RLS and the admin-only RPCs enforce the rules.
import { sb, ctx, esc, $, $$, toast, errBox, head, empty, loading, math, confirmDialog, formDialog, signedUrl, subjTag } from './lib.js';

export const STATUSES = ['discovered', 'downloaded', 'extracted', 'classified', 'awaiting_review', 'completed', 'skipped', 'failed'];
const TONE = { failed: 'bad', skipped: 'warn', completed: 'ok', awaiting_review: 'accent', classified: 'accent' };
const STATUS_HELP = {
  discovered: 'Found on an official page, not downloaded yet', downloaded: 'PDF stored, not read yet', extracted: 'Text read and parsed',
  classified: 'Chapter and difficulty assigned', awaiting_review: 'Waiting for you in Question review / Answer keys', completed: 'Finished: published, or every key entry decided',
  skipped: 'Deliberately not imported (reason shown)', failed: 'Something went wrong (reason shown); fix and retry',
};
const TABS = [['overview', 'Overview'], ['documents', 'Documents'], ['papers', 'Papers and publishing'], ['review', 'Question review'], ['keys', 'Answer keys'], ['logs', 'Import logs'], ['upload', 'Manual upload'], ['access', 'Access']];
const RUN_COUNTERS = [['pdfs_discovered', 'PDFs discovered'], ['question_papers_downloaded', 'Question papers downloaded'], ['answer_keys_downloaded', 'Answer keys downloaded'],
  ['questions_extracted', 'Questions extracted'], ['questions_classified', 'Questions classified'], ['questions_requiring_review', 'Questions requiring review'],
  ['documents_skipped', 'Documents skipped'], ['documents_failed', 'Documents failed']];

const S = { tab: 'overview', doc: { status: '', kind: '', exam: '', q: '', page: 0 }, paper: null, rfilter: 'all', key: { status: 'proposed', doc: '', page: 0 }, log: { level: '', run: '', doc: '', q: '', page: 0 }, selected: new Set() };
let M, rerouter, LK;                       // main element, app-level re-render, lookups

const tag = (text, tone = '') => `<span class="tag ${tone}">${esc(String(text).replace(/_/g, ' '))}</span>`;
const stTag = s => `<span class="tag ${TONE[s] || ''}" title="${esc(STATUS_HELP[s] || '')}">${esc(String(s).replace(/_/g, ' '))}</span>`;
const when = t => (t ? new Date(t).toLocaleString() : '');
const docName = d => (d.source_url ? decodeURIComponent(d.source_url.split('?')[0].split('/').pop() || d.source_url) : (d.storage_path || d.id).split('/').pop());
const fmtAns = a => (a == null ? '—' : Array.isArray(a) ? a.join(', ') : typeof a === 'object' ? `${a.value} ± ${a.tolerance ?? 0}` : String(a));
const paperLabel = p => `${p.exams?.name || ''} ${p.exam_year}${p.session ? ' · session ' + p.session : ''}${p.shift ? ' · shift ' + p.shift : ''} · paper ${p.paper_number}`;
const opts = (items, sel, all) => (all ? `<option value="">${esc(all)}</option>` : '') + items.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(sel) ? 'selected' : ''}>${esc(l)}</option>`).join('');

async function fetchAll(build, page = 1000) {            // PostgREST returns at most 1000 rows per request
  const out = []; for (let from = 0; ; from += page) { const { data, error } = await build().range(from, from + page - 1); if (error) throw error; out.push(...data); if (data.length < page) return out; }
}
async function rpc(name, args) { const { data, error } = await sb.rpc(name, args); if (error) throw error; return data; }
const guard = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message || String(e)); } };

async function lookups() {
  if (LK) return LK;
  const [exams, subjects, chapters, runs] = await Promise.all([sb.from('exams').select('id,code,name'), sb.from('subjects').select('id,code,name'), sb.from('chapters').select('id,name,subject_id').order('sort_order'),
    sb.from('import_runs').select('id,created_at,trigger,mode').order('created_at', { ascending: false }).limit(20)]);
  return (LK = { exams: exams.data || [], subjects: subjects.data || [], chapters: chapters.data || [], runs: runs.data || [] });
}

export async function adminView(main, rerender) {
  M = main; rerouter = rerender; LK = null;
  if (ctx.profile?.role !== 'admin') return main.innerHTML = head('Admin') + '<div class="msg err">Administrators only.</div>';
  const probe = await sb.from('source_documents').select('import_status').limit(1);
  S.ready = !probe.error;
  await render();
}

async function render() {
  const tabs = `<div class="tabs" role="tablist" style="margin-bottom:1rem">${TABS.map(([k, l]) => `<button role="tab" data-tab="${k}" class="${S.tab === k ? 'on' : ''}" aria-selected="${S.tab === k}">${l}</button>`).join('')}</div>`;
  M.innerHTML = head('Admin', 'Imports, source documents, answer keys and publishing.') + tabs + (S.ready || S.tab === 'access' ? '' : migrationBanner()) + '<div id="adm">' + loading('Loading…') + '</div>';
  $$('[data-tab]', M).forEach(b => b.onclick = () => { S.tab = b.dataset.tab; S.selected.clear(); render(); });
  const box = $('#adm', M);
  if (!S.ready && S.tab !== 'access') { box.innerHTML = ''; return; }
  try { await ({ overview, documents, papers, review, keys, logs, upload, access }[S.tab])(box); } catch (e) { box.innerHTML = errBox(e); }
}

const migrationBanner = () => `<div class="msg err"><div><b>Database migration 007 has not been applied.</b><br>The new importer tables and admin functions are missing. Apply <code>supabase/migrations/007_importer_pipeline.sql</code> (SQL editor or <code>supabase db push</code>), then reload. Nothing else in the app is affected.</div></div>`;

const go = (tab, patch = {}) => { S.tab = tab; Object.assign(S, patch); S.selected.clear(); render(); };

// ───────────────────────────────────────────────────────────── Overview
async function overview(box) {
  const [docs, runs, paused, queued, entries, review, dups] = await Promise.all([
    fetchAll(() => sb.from('source_documents').select('import_status').order('id')), sb.from('import_runs').select('*').order('created_at', { ascending: false }).limit(6),
    sb.from('app_settings').select('value').eq('key', 'import_paused').single(), sb.from('import_runs').select('id', { count: 'exact', head: true }).eq('status', 'queued'),
    fetchAll(() => sb.from('answer_key_entries').select('match_status').order('id')), sb.from('questions').select('id', { count: 'exact', head: true }).eq('needs_review', true),
    sb.from('duplicate_candidates').select('id', { count: 'exact', head: true }).eq('status', 'open')]);
  const by = {}; docs.forEach(d => by[d.import_status] = (by[d.import_status] || 0) + 1);
  const ek = {}; entries.forEach(e => ek[e.match_status] = (ek[e.match_status] || 0) + 1);
  const isPaused = paused.data?.value === true, failed = by.failed || 0;
  box.innerHTML = `
    <div class="adm-grid">${STATUSES.map(s => `<button class="adm-chip ${TONE[s] || ''}" data-st="${s}" title="${esc(STATUS_HELP[s])}"><b>${by[s] || 0}</b><span>${s.replace('_', ' ')}</span></button>`).join('')}</div>
    <div class="card"><div class="card-head"><h3>Import engine</h3></div>
      <p class="muted">Imports run in GitHub Actions, not in your browser. Buttons here queue a run; the workflow checks for queued runs every 6 hours, or start <b>Import PYQs</b> from GitHub to run it now. ${queued.count ? `<b>${queued.count} run(s) queued.</b>` : 'Nothing queued.'}</p>
      <div class="row"><button id="chk">Check sources only</button><button id="go" class="accent">Start full import</button><button class="ghost" id="po">Process uploaded / downloaded PDFs</button>
      <button class="ghost" id="rt" ${failed ? '' : 'disabled'}>Retry all failed (${failed})</button><button class="ghost" id="pz">${isPaused ? 'Resume imports' : 'Pause imports'}</button></div>
      ${isPaused ? '<div class="msg err">Imports are paused. Queued runs will not start until you resume.</div>' : ''}</div>
    <div class="card"><div class="card-head"><h3>Waiting for you</h3></div><div class="row">
      <button class="ghost" data-go="review">${review.count || 0} question(s) need review</button><button class="ghost" data-go="keys" data-k="proposed">${ek.proposed || 0} matched answer(s) to confirm</button>
      <button class="ghost" data-go="keys" data-k="ambiguous">${ek.ambiguous || 0} ambiguous</button><button class="ghost" data-go="keys" data-k="unmatched">${ek.unmatched || 0} unmatched</button>
      <span class="tag">${dups.count || 0} possible duplicate(s)</span></div></div>
    <div class="card"><div class="card-head"><h3>Recent runs</h3></div>${(runs.data || []).map(runCard).join('') || '<p class="muted">No runs yet.</p>'}</div>`;
  $$('[data-st]', box).forEach(b => b.onclick = () => go('documents', { doc: { ...S.doc, status: b.dataset.st, page: 0 } }));
  $$('[data-go]', box).forEach(b => b.onclick = () => go(b.dataset.go, b.dataset.k ? { key: { ...S.key, status: b.dataset.k, page: 0 } } : {}));
  const queue = (mode, msg) => guard(async () => { const { error } = await sb.from('import_runs').insert({ trigger: 'manual', status: 'queued', mode, requested_by: ctx.user.id }); if (error) throw error; toast(msg); render(); });
  $('#chk').onclick = queue('discover_only', 'Queued: find PDFs only.'); $('#go').onclick = queue('full', 'Queued: full import.'); $('#po').onclick = queue('process_only', 'Queued: process stored PDFs.');
  $('#rt').onclick = guard(async () => { const ids = (await fetchAll(() => sb.from('source_documents').select('id').eq('import_status', 'failed').order('id'))).map(d => d.id); const r = await rpc('retry_documents', { p_document_ids: ids, p_queue_run: true }); toast(`${r.requeued} document(s) re-queued.`); render(); });
  $('#pz').onclick = guard(async () => { const { error } = await sb.from('app_settings').upsert({ key: 'import_paused', value: !isPaused, updated_by: ctx.user.id }); if (error) throw error; render(); });
}

function runCard(r) {
  const st = r.stats || {}, bad = ['sources_unreachable', 'partial_failures', 'nothing_discovered'].includes(st.outcome);
  return `<div style="padding:.7rem 0;border-top:1px solid var(--line)"><div class="row between"><span>${when(r.created_at)} · ${esc(r.trigger)} · ${esc(r.mode || 'full')}</span><span>${tag(r.status, r.status === 'failed' ? 'bad' : r.status === 'completed' ? 'ok' : '')}${st.outcome ? tag(String(st.outcome).replace(/_/g, ' '), bad ? 'warn' : 'ok') : ''}</span></div>
    ${r.status === 'queued' ? '<p class="muted small">Waiting for the next workflow run.</p>' : `<div class="row small" style="margin-top:.4rem">${RUN_COUNTERS.map(([k, l]) => `<span class="tag ${(k === 'documents_failed' && st[k]) ? 'bad' : ''}">${esc(l)}: ${st[k] ?? 0}</span>`).join('')}</div>`}
    ${st.explanation ? `<p class="small ${bad ? 'warn' : 'muted'}" style="margin:.3rem 0 0">${esc(st.explanation)}</p>` : ''}</div>`;
}

// ───────────────────────────────────────────────────────────── Documents
async function documents(box) {
  const L = await lookups(), f = S.doc, PS = 25;
  let q = sb.from('source_documents').select('*', { count: 'exact' });
  if (f.status) q = q.eq('import_status', f.status); if (f.kind) q = q.eq('doc_kind', f.kind); if (f.exam) q = q.eq('exam_id', f.exam);
  if (f.q) { const t = f.q.replace(/[%,()]/g, ' '); q = q.or(`source_url.ilike.%${t}%,link_text.ilike.%${t}%,storage_path.ilike.%${t}%`); }
  const { data, count, error } = await q.order('discovered_at', { ascending: false }).range(f.page * PS, f.page * PS + PS - 1);
  if (error) throw error;
  const exName = id => L.exams.find(e => e.id === id)?.name || '—';
  box.innerHTML = `<div class="card"><div class="adm-filters">
      <div><label for="fst">Status</label><select id="fst">${opts(STATUSES.map(s => [s, s.replace('_', ' ')]), f.status, 'All')}</select></div>
      <div><label for="fk">Kind</label><select id="fk">${opts([['question_paper', 'Question paper'], ['answer_key', 'Answer key'], ['solution', 'Solution'], ['other', 'Other']], f.kind, 'All')}</select></div>
      <div><label for="fe">Exam</label><select id="fe">${opts(L.exams.map(e => [e.id, e.name]), f.exam, 'Both')}</select></div>
      <div style="flex:1"><label for="fq">Search</label><input id="fq" value="${esc(f.q)}" placeholder="file name, link text"></div><button class="ghost" id="fgo">Apply</button>
      <button class="ghost" id="bretry">Retry selected</button></div>
    ${data.length ? `<div class="table-wrap"><table><thead><tr><th></th><th>Document</th><th>Kind</th><th>Identified as</th><th>Status</th><th>Reason</th><th></th></tr></thead><tbody>${data.map(d => `<tr>
      <td><input type="checkbox" data-sel="${d.id}" ${S.selected.has(d.id) ? 'checked' : ''} aria-label="Select"></td>
      <td><b>${esc(docName(d))}</b><div class="small muted">${esc(d.link_text || '')}</div><div class="small">${d.source_url ? `<a href="${esc(d.source_url)}" target="_blank" rel="noopener">PDF</a>` : ''} ${d.source_page_url ? `· <a href="${esc(d.source_page_url)}" target="_blank" rel="noopener">source page</a>` : ''} ${d.storage_path ? `· <a href="#" data-open="${esc(d.storage_path)}">stored copy</a>` : ''}</div>
        <div class="small muted">${tag(d.origin.replace('_', ' '))}${d.discovery_depth != null ? `depth ${d.discovery_depth} · ` : ''}${when(d.discovered_at)}</div></td>
      <td>${tag(d.doc_kind)}${d.detected?.key_version ? tag(d.detected.key_version) : ''}</td>
      <td class="small">${esc(exName(d.exam_id))}<br>${d.exam_year ?? '<span class="bad">year ?</span>'}${d.session ? ' · session ' + esc(d.session) : ''}${d.shift ? ' · shift ' + esc(d.shift) : ''}${d.paper_number ? ' · paper ' + d.paper_number : ''}${d.page_count ? `<br>${d.page_count} pp${d.ocr_used ? ' · OCR' : ''}` : ''}</td>
      <td>${stTag(d.import_status)}</td><td class="adm-reason ${d.import_status === 'failed' ? 'bad' : d.import_status === 'skipped' ? 'warn' : 'muted'}">${esc(d.status_reason || '')}${(d.detected?.evidence || []).length ? `<details class="adm-log-d"><summary>how it was identified</summary>${esc(d.detected.evidence.join('; '))}</details>` : ''}</td>
      <td><div class="row"><button class="ghost sm" data-edit="${d.id}">Edit</button>${['failed', 'skipped', 'discovered', 'downloaded'].includes(d.import_status) ? `<button class="ghost sm" data-retry="${d.id}">Retry</button>` : ''}<button class="ghost sm" data-log="${d.id}">Logs</button></div></td></tr>`).join('')}</tbody></table></div>`
      : empty('No documents match', f.status || f.kind || f.q ? 'Try clearing the filters.' : 'Nothing has been discovered yet. Queue "Check sources only" on the Overview tab, or upload a PDF manually.')}
    <div class="row between" style="margin-top:.8rem"><button class="ghost sm" id="dp" ${f.page ? '' : 'disabled'}>Previous</button><span class="muted small">${count ? `${f.page * PS + 1}–${Math.min((f.page + 1) * PS, count)} of ${count}` : ''}</span><button class="ghost sm" id="dn" ${(f.page + 1) * PS < (count || 0) ? '' : 'disabled'}>Next</button></div></div>`;
  $('#fgo', box).onclick = () => { S.doc = { status: $('#fst', box).value, kind: $('#fk', box).value, exam: $('#fe', box).value, q: $('#fq', box).value.trim(), page: 0 }; render(); };
  $('#dp', box).onclick = () => { S.doc.page--; render(); }; $('#dn', box).onclick = () => { S.doc.page++; render(); };
  $$('[data-sel]', box).forEach(c => c.onchange = () => c.checked ? S.selected.add(c.dataset.sel) : S.selected.delete(c.dataset.sel));
  const retry = guard(async ids => { const r = await rpc('retry_documents', { p_document_ids: ids, p_queue_run: true }); toast(`${r.requeued} document(s) re-queued; a run is queued.`); S.selected.clear(); render(); });
  $$('[data-retry]', box).forEach(b => b.onclick = () => retry([b.dataset.retry]));
  $('#bretry', box).onclick = () => S.selected.size ? retry([...S.selected]) : toast('Tick the documents to retry first.');
  $$('[data-open]', box).forEach(a => a.onclick = guard(async e => { e.preventDefault(); const u = await signedUrl('source-documents', a.dataset.open); if (u) window.open(u, '_blank', 'noopener'); else toast('Could not open the stored file.'); }));
  $$('[data-log]', box).forEach(b => b.onclick = () => go('logs', { log: { level: '', run: '', doc: b.dataset.log, q: '', page: 0 } }));
  $$('[data-edit]', box).forEach(b => b.onclick = guard(() => editDocument(data.find(d => d.id === b.dataset.edit), L)));
}

async function editDocument(d, L) {
  const v = await formDialog('Edit document details', `
    <div><label>Kind</label><select name="doc_kind">${opts([['question_paper', 'Question paper'], ['answer_key', 'Answer key'], ['solution', 'Solution (never imported)'], ['other', 'Other']], d.doc_kind)}</select></div>
    <div><label>Exam</label><select name="exam_id">${opts(L.exams.map(e => [e.id, e.name]), d.exam_id)}</select></div>
    <div class="row"><div><label>Year</label><input name="exam_year" type="number" min="2002" max="2100" value="${d.exam_year ?? ''}"></div><div><label>Session</label><input name="session" value="${esc(d.session ?? '')}" size="4"></div>
    <div><label>Shift</label><input name="shift" value="${esc(d.shift ?? '')}" size="10" placeholder="1, 2 or 2021-02-24 S1"></div><div><label>Paper</label><input name="paper_number" type="number" min="1" max="2" value="${d.paper_number ?? ''}" style="width:5rem"></div></div>
    <div><label>Exam date (optional)</label><input name="exam_date" type="date" value="${d.exam_date || ''}"></div>
    <div><label>Answer key version</label><select name="key_version">${opts([['provisional', 'Provisional'], ['final', 'Final']], d.detected?.key_version, 'Not stated')}</select></div>
    <label class="row"><input type="checkbox" name="retry" checked> Re-run the import for this document after saving</label>`, 'Save',
    'Correct anything the importer could not read. Only change values you can see on the document itself.');
  if (!v) return;
  const upd = { doc_kind: v.doc_kind, exam_id: Number(v.exam_id), exam_year: v.exam_year ? Number(v.exam_year) : null, session: v.session.trim() || null, shift: v.shift.trim() || null,
    paper_number: v.paper_number ? Number(v.paper_number) : null, exam_date: v.exam_date || null, detected: { ...(d.detected || {}), key_version: v.key_version || null, edited_by_admin: true } };
  const { error } = await sb.from('source_documents').update(upd).eq('id', d.id); if (error) throw error;
  if (v.retry) await rpc('retry_documents', { p_document_ids: [d.id], p_queue_run: true });
  toast('Saved'); render();
}

// ───────────────────────────────────────────────────────────── Papers and publishing
async function loadPapers() {
  const [papers, qs] = await Promise.all([sb.from('papers').select('*,exams(name)').order('exam_year', { ascending: false }), fetchAll(() => sb.from('questions').select('paper_id,answer_verified,needs_review,is_published').order('id'))]);
  if (papers.error) throw papers.error;
  const c = {}; qs.forEach(q => { const x = c[q.paper_id] ||= { total: 0, verified: 0, reviewed: 0, published: 0, ready: 0 }; x.total++; if (q.answer_verified) x.verified++; if (!q.needs_review) x.reviewed++; if (q.is_published) x.published++; if (q.answer_verified && !q.needs_review) x.ready++; });
  return papers.data.map(p => ({ ...p, c: c[p.id] || { total: 0, verified: 0, reviewed: 0, published: 0, ready: 0 } }));
}

async function papers(box) {
  const ps = await loadPapers();
  box.innerHTML = `<div class="card flush table-wrap"><div class="card-head"><h3>Papers</h3><span class="muted small">Publishing releases only questions that are answer-verified and reviewed. Everything else stays hidden from students.</span></div>
    ${ps.length ? `<table><thead><tr><th>Paper</th><th>Source</th><th>Questions</th><th>Answer verified</th><th>Reviewed</th><th>Ready</th><th>Published</th><th></th></tr></thead><tbody>${ps.map(p => `<tr>
      <td><b>${esc(paperLabel(p))}</b>${p.exam_date ? `<div class="small muted">${esc(p.exam_date)}</div>` : ''}</td>
      <td>${p.source_url ? `<a href="${esc(p.source_url)}" target="_blank" rel="noopener">original</a>` : '—'}<div class="small">${tag(p.source_status)}</div></td>
      <td>${p.c.total}</td><td>${p.c.verified}/${p.c.total}</td><td>${p.c.reviewed}/${p.c.total}</td><td>${p.c.ready}</td>
      <td>${p.is_published ? tag('published', 'ok') : tag('hidden', 'warn')} ${p.c.published}/${p.c.total}</td>
      <td><div class="row"><button class="ghost sm" data-rev="${p.id}">Review</button><button class="ghost sm" data-bulk="${p.id}" title="Confirm every unambiguous matched answer in this paper">Verify safe matches</button>
        ${p.is_published ? `<button class="ghost sm" data-unpub="${p.id}">Unpublish</button>` : `<button class="accent sm" data-pub="${p.id}" ${p.c.ready ? '' : 'disabled title="No question is both answer-verified and reviewed yet"'}>Publish ${p.c.ready}</button>`}
        ${p.is_published && p.c.ready > p.c.published ? `<button class="accent sm" data-pub="${p.id}">Publish ${p.c.ready - p.c.published} more</button>` : ''}</div></td></tr>`).join('')}</tbody></table>`
      : empty('No papers yet', 'Papers appear after a question-paper PDF has been extracted.')}</div>`;
  $$('[data-rev]', box).forEach(b => b.onclick = () => go('review', { paper: b.dataset.rev, rfilter: 'all' }));
  $$('[data-bulk]', box).forEach(b => b.onclick = guard(() => bulkVerify(b.dataset.bulk)));
  $$('[data-pub]', box).forEach(b => b.onclick = guard(async () => { const p = ps.find(x => x.id === b.dataset.pub); if (!await confirmDialog('Publish this paper?', `${p.c.ready} verified and reviewed question(s) become visible to students. The other ${p.c.total - p.c.ready} stay hidden.`, 'Publish')) return; const r = await rpc('publish_paper', { p_paper_id: p.id, p_publish: true }); toast(`Published ${r.published_questions}; ${r.held_back} held back.`); render(); }));
  $$('[data-unpub]', box).forEach(b => b.onclick = guard(async () => { if (!await confirmDialog('Unpublish this paper?', 'All its questions disappear for students, including from their old test results.', 'Unpublish')) return; await rpc('publish_paper', { p_paper_id: b.dataset.unpub, p_publish: false }); toast('Unpublished'); render(); }));
}

async function bulkVerify(paperId) {
  if (!await confirmDialog('Verify all safe matches?', 'Confirms every answer-key entry that matched exactly one question with the right answer shape. Ambiguous and unmatched entries are left for you. A question is marked reviewed only if it has a chapter, a confident classification, no OCR and no extraction warnings.', 'Verify')) return;
  const r = await rpc('bulk_confirm_proposed', { p_paper_id: paperId || null });
  toast(`${r.confirmed} answer(s) confirmed, ${r.marked_reviewed} question(s) marked reviewed, ${r.left_for_manual} left for manual check.`); render();
}

// ───────────────────────────────────────────────────────────── Question review
async function review(box) {
  const L = await lookups(), ps = await loadPapers();
  if (!S.paper && ps.length) S.paper = (ps.find(p => !p.is_published && p.c.total) || ps[0]).id;
  const paper = ps.find(p => p.id === S.paper);
  const bar = `<div class="card"><div class="adm-filters"><div style="flex:1;min-width:260px"><label for="rp">Paper</label><select id="rp">${opts(ps.map(p => [p.id, `${paperLabel(p)} — ${p.c.total} questions${p.is_published ? ' (published)' : ''}`]), S.paper, ps.length ? '' : 'No papers')}</select></div>
    <div><label for="rf">Show</label><select id="rf">${opts([['all', 'All'], ['needs_answer', 'No verified answer'], ['proposed', 'Has a matched official answer'], ['needs_review', 'Needs review'], ['warnings', 'Extraction warnings'], ['unpublished', 'Unpublished']], S.rfilter)}</select></div></div></div>`;
  if (!paper) { box.innerHTML = bar + empty('Nothing to review', 'Import a question paper first, or upload one manually.'); return; }
  const [qr, er] = await Promise.all([fetchAll(() => sb.from('questions').select('id,question_number,question_type,statement,subject_id,chapter_id,difficulty,classification_confidence,classification_source,needs_review,answer_verified,correct_answer,answer_source,is_published,images,extraction_flags,source_page,source_page_end,subjects(name,code),chapters(name),question_options(label,content,sort_order)').eq('paper_id', paper.id).order('question_number')),
    fetchAll(() => sb.from('answer_key_entries').select('id,matched_question_id,candidate_question_ids,match_status,answer,raw_answer,match_note,subject_code,question_number,source_document_id,source_documents(source_url,link_text,detected)').eq('paper_id', paper.id).order('id'))]);
  const eq = {}; er.forEach(e => { if (e.matched_question_id && e.match_status !== 'rejected') (eq[e.matched_question_id] ||= []).push(e); });
  const keep = q => { const w = (q.extraction_flags?.warnings || []).length || q.extraction_flags?.ocr, pr = (eq[q.id] || []).some(e => e.match_status === 'proposed');
    return { all: true, needs_answer: !q.answer_verified, proposed: pr, needs_review: q.needs_review, warnings: !!w, unpublished: !q.is_published }[S.rfilter]; };
  const list = qr.sort((a, b) => (a.subjects?.code || '').localeCompare(b.subjects?.code || '') || a.question_number - b.question_number).filter(keep);
  box.innerHTML = bar + `<div class="card"><div class="adm-tools"><div class="row between"><div class="row"><b>${esc(paperLabel(paper))}</b>${paper.is_published ? tag('published', 'ok') : tag('hidden', 'warn')}<span class="muted small">${paper.c.verified}/${paper.c.total} answers verified · ${paper.c.reviewed}/${paper.c.total} reviewed · ${paper.c.published} published</span></div>
      <div class="row"><button class="ghost sm" id="bv">Verify all safe matches</button><button class="ghost sm" id="bsel">Confirm answers for selected</button><button class="ghost sm" id="brev">Mark selected reviewed</button>
      ${paper.is_published ? '<button class="ghost sm" id="bun">Unpublish paper</button>' : ''}<button class="accent sm" id="bpub" ${paper.c.ready ? '' : 'disabled'}>Publish ${paper.c.ready} ready</button></div></div></div>
    ${list.length ? list.map(q => qCard(q, eq[q.id] || [], L)).join('') : '<p class="muted">No questions match this filter.</p>'}</div>`;
  $('#rp', box).onchange = e => { S.paper = e.target.value; render(); }; $('#rf', box).onchange = e => { S.rfilter = e.target.value; render(); };
  $('#bv', box).onclick = guard(() => bulkVerify(paper.id));
  $('#bpub', box).onclick = guard(async () => { if (!await confirmDialog('Publish this paper?', `${paper.c.ready} question(s) that are answer-verified and reviewed will become visible to students.`, 'Publish')) return; const r = await rpc('publish_paper', { p_paper_id: paper.id, p_publish: true }); toast(`Published ${r.published_questions}; ${r.held_back} held back.`); render(); });
  if ($('#bun', box)) $('#bun', box).onclick = guard(async () => { if (!await confirmDialog('Unpublish this paper?', 'All its questions disappear for students.', 'Unpublish')) return; await rpc('publish_paper', { p_paper_id: paper.id, p_publish: false }); render(); });
  const chosen = () => $$('[data-pick]:checked', box).map(c => c.dataset.pick);
  $('#bsel', box).onclick = guard(async () => { const ids = chosen(); if (!ids.length) return toast('Tick some questions first.'); let ok = 0, skip = 0;
    for (const id of ids) { const e = (eq[id] || []).filter(x => x.match_status === 'proposed'); if (e.length !== 1) { skip++; continue; } try { await rpc('confirm_answer_entry', { p_entry_id: e[0].id, p_question_id: id }); ok++; } catch { skip++; } }
    toast(`${ok} answer(s) confirmed; ${skip} skipped (no single matched answer, or it did not fit).`); render(); });
  $('#brev', box).onclick = guard(async () => { const ids = chosen(); if (!ids.length) return toast('Tick some questions first.'); const safe = ids.filter(id => { const q = qr.find(x => x.id === id); return q.chapter_id && !(q.extraction_flags?.warnings || []).length && !q.extraction_flags?.ocr; });
    if (safe.length) { const { error } = await sb.from('questions').update({ needs_review: false }).in('id', safe); if (error) throw error; }
    toast(`${safe.length} marked reviewed; ${ids.length - safe.length} skipped (no chapter, OCR text or extraction warnings: open them and review individually).`); render(); });
  bindQuestionCards(box, qr, eq, L);
  math(box);
  fillThumbs(box);
}

function qCard(q, entries, L) {
  const fl = q.extraction_flags || {}, warn = fl.warnings || [], opts_ = (q.question_options || []).sort((a, b) => a.sort_order - b.sort_order);
  const chs = L.chapters.filter(c => c.subject_id === q.subject_id);
  const keys = entries.length ? entries.map(e => `<div class="adm-key"><div class="row between"><span><b>Official key:</b> ${esc(fmtAns(e.answer))} <span class="muted">(raw "${esc(e.raw_answer)}")</span> · ${esc(docLabel(e.source_documents))} ${tag(e.match_status, e.match_status === 'confirmed' ? 'ok' : 'accent')}</span>
      ${e.match_status === 'proposed' ? `<span class="row"><button class="accent sm" data-confirm="${e.id}" data-q="${q.id}">Confirm answer</button><button class="ghost sm" data-reject="${e.id}">Reject</button></span>` : ''}</div>${e.match_note ? `<div class="small muted">${esc(e.match_note)}</div>` : ''}</div>`).join('')
    : `<div class="adm-key none">No official answer matched this question. Check the Answer keys tab, or enter the answer from the official key yourself.</div>`;
  return `<div class="adm-q" id="q-${q.id}"><div class="row between"><div class="row"><input type="checkbox" data-pick="${q.id}" aria-label="Select question ${q.question_number}"><b>Q${q.question_number}</b>${subjTag(q.subjects?.name)}${tag(q.question_type)}
      ${q.answer_verified ? tag('answer verified', 'ok') : tag('answer not verified', 'warn')}${q.needs_review ? tag('needs review', 'warn') : tag('reviewed', 'ok')}${q.is_published ? tag('published', 'ok') : ''}
      ${fl.ocr ? tag('OCR text', 'warn') : ''}${fl.math_heavy ? tag('maths-heavy: compare with the page image', 'warn') : ''}${warn.map(w => tag(w, 'warn')).join('')}</div>
      <span class="muted small">p.${q.source_page ?? '?'}${q.source_page_end && q.source_page_end !== q.source_page ? '–' + q.source_page_end : ''}${q.classification_source === 'ai' && q.classification_confidence != null ? ` · AI confidence ${Math.round(q.classification_confidence * 100)}%` : ''}</span></div>
    <div class="q-statement">${esc(q.statement)}</div>
    ${opts_.length ? `<div class="opts">${opts_.map(o => `<div class="opt plain"><span class="key">${esc(o.label)}</span><span class="txt">${esc(o.content)}</span></div>`).join('')}</div>` : ''}
    <div class="adm-thumbs" data-imgs="${esc(JSON.stringify(q.images || []))}"></div>
    ${q.answer_verified ? `<div class="adm-key"><b>Verified answer:</b> ${esc(fmtAns(q.correct_answer))} ${tag(q.answer_source)}</div>` : ''}${q.answer_verified ? '' : keys}
    <div class="row" style="margin-top:.5rem"><select data-chap="${q.id}" aria-label="Chapter" style="width:auto;max-width:240px"><option value="">Chapter: none</option>${opts(chs.map(c => [c.id, c.name]), q.chapter_id)}</select>
      <select data-diff="${q.id}" aria-label="Difficulty" style="width:auto"><option value="">Difficulty: none</option>${opts(['easy', 'medium', 'hard'].map(x => [x, x]), q.difficulty)}</select>
      <button class="ghost sm" data-save="${q.id}">Save classification</button><button class="ghost sm" data-edit="${q.id}">Edit text</button>
      <button class="ghost sm" data-manual="${q.id}">Enter answer by hand</button><button class="ghost sm" data-toggle="${q.id}">${q.needs_review ? 'Mark reviewed' : 'Needs review again'}</button></div></div>`;
}
const docLabel = d => (d ? (d.link_text || (d.source_url || '').split('/').pop() || 'answer key') + (d.detected?.key_version ? ` (${d.detected.key_version})` : '') : 'answer key');

function bindQuestionCards(box, qr, eq, L) {
  const get = id => qr.find(q => q.id === id);
  $$('[data-confirm]', box).forEach(b => b.onclick = guard(async () => { await rpc('confirm_answer_entry', { p_entry_id: b.dataset.confirm, p_question_id: b.dataset.q }); toast('Answer confirmed'); render(); }));
  $$('[data-reject]', box).forEach(b => b.onclick = guard(async () => { await rpc('reject_answer_entry', { p_entry_id: b.dataset.reject }); render(); }));
  $$('[data-save]', box).forEach(b => b.onclick = guard(async () => { const id = b.dataset.save, ch = $(`[data-chap="${id}"]`, box).value, df = $(`[data-diff="${id}"]`, box).value;
    const { error } = await sb.from('questions').update({ chapter_id: ch ? Number(ch) : null, difficulty: df || null, classification_source: 'manual', difficulty_is_estimated: !df }).eq('id', id); if (error) throw error; toast('Classification saved'); }));
  $$('[data-toggle]', box).forEach(b => b.onclick = guard(async () => { const q = get(b.dataset.toggle); const { error } = await sb.from('questions').update({ needs_review: !q.needs_review }).eq('id', q.id); if (error) throw error; render(); }));
  $$('[data-edit]', box).forEach(b => b.onclick = guard(async () => { const q = get(b.dataset.edit), os = (q.question_options || []).sort((a, c) => a.sort_order - c.sort_order);
    const v = await formDialog(`Edit Q${q.question_number}`, `<div><label>Question text (use $…$ for maths)</label><textarea name="statement" rows="7">${esc(q.statement)}</textarea></div>
      <div><label>Type</label><select name="qt">${opts([['single_mcq', 'Single correct'], ['multi_mcq', 'One or more correct'], ['integer', 'Integer'], ['numerical', 'Numerical'], ['matrix_match', 'Matrix match'], ['paragraph', 'Paragraph'], ['other', 'Other']], q.question_type)}</select></div>
      ${os.map(o => `<div><label>Option ${esc(o.label)}</label><input name="o_${esc(o.label)}" value="${esc(o.content)}"></div>`).join('')}`, 'Save', 'Fix extraction mistakes by comparing with the page image. Editing does not change the verified answer.');
    if (!v) return;
    let r = await sb.from('questions').update({ statement: v.statement.trim(), question_type: v.qt }).eq('id', q.id); if (r.error) throw r.error;
    for (const o of os) { r = await sb.from('question_options').update({ content: v['o_' + o.label] ?? o.content }).eq('question_id', q.id).eq('label', o.label); if (r.error) throw r.error; }
    toast('Saved'); render(); }));
  $$('[data-manual]', box).forEach(b => b.onclick = guard(async () => { const q = get(b.dataset.manual);
    const v = await formDialog(`Answer for Q${q.question_number}`, `<div><label>Answer (letters like B or A,C for options; a number for numerical/integer)</label><input name="a" autocomplete="off" required></div>
      <div><label>Where does this answer come from?</label><select name="src"><option value="official">The official answer key (I checked it)</option><option value="verified_archive">A verified archive / other trusted source</option></select></div>`, 'Verify answer', 'Never type an answer you have not checked against a published key.');
    if (!v) return; const t = v.a.trim(), isNum = !isNaN(Number(t)) && t !== '' && !/^[A-Za-z]$/.test(t);
    const correct = isNum ? Number(t) : t.toUpperCase().split(/[\s,;]+/).filter(Boolean);
    if (!isNum && !correct.every(x => /^[A-D1-4]$/.test(x))) return toast('Use option letters A–D (or 1–4), separated by commas, or a number.');
    const ty = q.question_type; if ((ty === 'numerical' || ty === 'integer') !== isNum) return toast(`This is a ${ty} question: the answer must be ${isNum ? 'option letters' : 'a number'}.`);
    if (ty === 'single_mcq' && correct.length !== 1) return toast('A single-correct question needs exactly one option.');
    const { error } = await sb.from('questions').update({ correct_answer: correct, answer_source: v.src, answer_verified: true, answer_verified_by: ctx.user.id, answer_verified_at: new Date().toISOString() }).eq('id', q.id); if (error) throw error; toast('Answer verified'); render(); }));
}

async function fillThumbs(root) {
  for (const el of $$('[data-imgs]', root)) {
    let imgs = []; try { imgs = JSON.parse(el.dataset.imgs); } catch { /* ignore */ }
    for (const i of imgs) { const u = await signedUrl(i.bucket || 'question-images', i.path); if (u) el.insertAdjacentHTML('beforeend', `<figure><img src="${esc(u)}" alt="${i.kind} from page ${i.page}" loading="lazy"><figcaption>${i.kind === 'snapshot' ? 'Page snapshot (check the text against this)' : 'Figure'} · p.${i.page}</figcaption></figure>`); }
  }
}

// ───────────────────────────────────────────────────────────── Answer keys
async function keys(box) {
  const f = S.key, PS = 50;
  const docs = await fetchAll(() => sb.from('source_documents').select('id,source_url,link_text,exam_year,session,shift,paper_number,detected').eq('doc_kind', 'answer_key').order('id'));
  let q = sb.from('answer_key_entries').select('*,questions:matched_question_id(question_number,statement),source_documents(source_url,link_text,detected)', { count: 'exact' });
  if (f.status) q = q.eq('match_status', f.status); if (f.doc) q = q.eq('source_document_id', f.doc);
  const { data, count, error } = await q.order('source_document_id').order('subject_code', { nullsFirst: true }).order('question_number').range(f.page * PS, f.page * PS + PS - 1); if (error) throw error;
  box.innerHTML = `<div class="card"><p class="muted" style="margin-top:0">Entries come from official answer-key PDFs. The importer only <b>proposes</b> an answer when exactly one paper and one question fit; nothing is written to a question until you confirm it.</p>
    <div class="adm-filters"><div><label for="ks">Match status</label><select id="ks">${opts(['proposed', 'ambiguous', 'unmatched', 'confirmed', 'rejected'].map(x => [x, x]), f.status, 'All')}</select></div>
      <div style="flex:1"><label for="kd">Key document</label><select id="kd">${opts(docs.map(d => [d.id, `${docLabel(d)} · ${d.exam_year ?? '?'}${d.session ? ' s' + d.session : ''}${d.shift ? ' shift ' + d.shift : ''}`]), f.doc, 'All')}</select></div>
      <button class="ghost" id="kgo">Apply</button><button class="accent" id="kall" ${f.status === 'proposed' && data.length ? '' : 'disabled'} title="Confirm every proposed entry on this page">Confirm proposed on this page</button></div>
    ${data.length ? `<div class="table-wrap"><table><thead><tr><th>Key</th><th>Subject</th><th>Q</th><th>Key says</th><th>Status</th><th>Matched question</th><th></th></tr></thead><tbody>${data.map(e => `<tr>
      <td class="small">${esc(docLabel(e.source_documents))}</td><td>${esc(e.subject_code || '—')}</td><td>${e.question_number ?? '—'}${e.original_question_id ? `<div class="small muted">id ${esc(e.original_question_id)}</div>` : ''}</td>
      <td><b>${esc(fmtAns(e.answer))}</b> <span class="muted small">raw "${esc(e.raw_answer)}"</span></td><td>${tag(e.match_status, e.match_status === 'confirmed' ? 'ok' : e.match_status === 'proposed' ? 'accent' : e.match_status === 'rejected' ? '' : 'warn')}</td>
      <td class="adm-reason">${e.questions ? `Q${e.questions.question_number}: ${esc(e.questions.statement.slice(0, 90))}…` : ''}${e.match_note ? `<div class="warn">${esc(e.match_note)}</div>` : ''}</td>
      <td><div class="row">${e.match_status === 'proposed' ? `<button class="accent sm" data-c="${e.id}">Confirm</button>` : ''}${e.match_status === 'ambiguous' && (e.candidate_question_ids || []).length && e.answer != null ? `<button class="ghost sm" data-a="${e.id}">Choose question</button>` : ''}${['proposed', 'ambiguous', 'unmatched'].includes(e.match_status) ? `<button class="ghost sm" data-r="${e.id}">Reject</button>` : ''}</div></td></tr>`).join('')}</tbody></table></div>`
      : empty('No entries here', f.status === 'proposed' ? 'No unambiguous matches are waiting. Check Ambiguous and Unmatched, or import a question paper first.' : 'No entries match this filter.')}
    <div class="row between" style="margin-top:.8rem"><button class="ghost sm" id="kp" ${f.page ? '' : 'disabled'}>Previous</button><span class="muted small">${count ? `${f.page * PS + 1}–${Math.min((f.page + 1) * PS, count)} of ${count}` : ''}</span><button class="ghost sm" id="kn" ${(f.page + 1) * PS < (count || 0) ? '' : 'disabled'}>Next</button></div></div>`;
  $('#kgo', box).onclick = () => { S.key = { status: $('#ks', box).value, doc: $('#kd', box).value, page: 0 }; render(); };
  $('#kp', box).onclick = () => { S.key.page--; render(); }; $('#kn', box).onclick = () => { S.key.page++; render(); };
  $$('[data-c]', box).forEach(b => b.onclick = guard(async () => { await rpc('confirm_answer_entry', { p_entry_id: b.dataset.c }); toast('Confirmed'); render(); }));
  $$('[data-r]', box).forEach(b => b.onclick = guard(async () => { await rpc('reject_answer_entry', { p_entry_id: b.dataset.r }); render(); }));
  $('#kall', box).onclick = guard(async () => { let ok = 0, bad = 0; for (const e of data.filter(x => x.match_status === 'proposed')) { try { await rpc('confirm_answer_entry', { p_entry_id: e.id }); ok++; } catch { bad++; } } toast(`${ok} confirmed, ${bad} could not be confirmed.`); render(); });
  $$('[data-a]', box).forEach(b => b.onclick = guard(async () => { const e = data.find(x => x.id === b.dataset.a);
    const { data: cands, error: ce } = await sb.from('questions').select('id,question_number,statement,subjects(name)').in('id', e.candidate_question_ids); if (ce) throw ce;
    const v = await formDialog('Which question is this answer for?', `<div><label>Key says <b>${esc(fmtAns(e.answer))}</b> for ${esc(e.subject_code || '')} question ${e.question_number}</label><select name="q">${opts(cands.map(c => [c.id, `${c.subjects?.name || ''} Q${c.question_number}: ${c.statement.slice(0, 70)}…`]), '')}</select></div>`, 'Confirm answer', e.match_note || '');
    if (!v) return; await rpc('confirm_answer_entry', { p_entry_id: e.id, p_question_id: v.q }); toast('Confirmed'); render(); }));
}

// ───────────────────────────────────────────────────────────── Import logs
async function logs(box) {
  const L = await lookups(), f = S.log, PS = 100;
  let q = sb.from('import_logs').select('*', { count: 'exact' });
  if (f.level) q = q.eq('level', f.level); if (f.run) q = q.eq('run_id', f.run); if (f.doc) q = q.eq('document_id', f.doc); if (f.q) q = q.ilike('message', `%${f.q.replace(/[%,]/g, ' ')}%`);
  const { data, count, error } = await q.order('created_at', { ascending: false }).order('id', { ascending: false }).range(f.page * PS, f.page * PS + PS - 1); if (error) throw error;
  box.innerHTML = `<div class="card"><div class="adm-filters"><div><label for="ll">Level</label><select id="ll">${opts(['error', 'warn', 'info', 'debug'].map(x => [x, x]), f.level, 'All')}</select></div>
    <div><label for="lr">Run</label><select id="lr">${opts(L.runs.map(r => [r.id, `${when(r.created_at)} · ${r.mode || 'full'}`]), f.run, 'All runs')}</select></div>
    <div style="flex:1"><label for="lq">Message contains</label><input id="lq" value="${esc(f.q)}" placeholder="blocked, robots, duplicate…"></div><button class="ghost" id="lgo">Apply</button>${f.doc ? '<button class="ghost" id="lclr">Clear document filter</button>' : ''}</div>
    ${f.doc ? '<p class="muted small">Showing log lines for one document.</p>' : ''}
    ${data.length ? `<div class="table-wrap"><table><thead><tr><th>Time</th><th>Level</th><th>Message</th></tr></thead><tbody>${data.map(l => `<tr><td class="small" style="white-space:nowrap">${when(l.created_at)}</td><td>${tag(l.level, l.level === 'error' ? 'bad' : l.level === 'warn' ? 'warn' : '')}</td>
      <td class="adm-reason" style="max-width:none">${esc(l.message)}${l.document_id ? ` <a href="#" data-d="${l.document_id}" class="small">this document</a>` : ''}${l.details && Object.keys(l.details).length ? `<details class="adm-log-d"><summary>details</summary><pre>${esc(JSON.stringify(l.details, null, 1))}</pre></details>` : ''}</td></tr>`).join('')}</tbody></table></div>` : empty('No log lines', 'Nothing matches these filters yet.')}
    <div class="row between" style="margin-top:.8rem"><button class="ghost sm" id="lp" ${f.page ? '' : 'disabled'}>Newer</button><span class="muted small">${count ? `${f.page * PS + 1}–${Math.min((f.page + 1) * PS, count)} of ${count}` : ''}</span><button class="ghost sm" id="ln" ${(f.page + 1) * PS < (count || 0) ? '' : 'disabled'}>Older</button></div></div>`;
  $('#lgo', box).onclick = () => { S.log = { ...S.log, level: $('#ll', box).value, run: $('#lr', box).value, q: $('#lq', box).value.trim(), page: 0 }; render(); };
  if ($('#lclr', box)) $('#lclr', box).onclick = () => { S.log.doc = ''; S.log.page = 0; render(); };
  $('#lp', box).onclick = () => { S.log.page--; render(); }; $('#ln', box).onclick = () => { S.log.page++; render(); };
  $$('[data-d]', box).forEach(a => a.onclick = e => { e.preventDefault(); S.log.doc = a.dataset.d; S.log.page = 0; render(); });
}

// ───────────────────────────────────────────────────────────── Manual upload
async function upload(box) {
  const L = await lookups();
  box.innerHTML = `<div class="card"><h3 style="margin-top:0">Upload a PDF yourself</h3><p class="muted">Use this when a site blocks automated downloads (HTTP 403, CAPTCHA, login) or the importer could not find a paper. Download the PDF from the official site in your own browser, then upload it here. The importer reads it on its next run; nothing is imported until it runs.</p>
    <form id="uf" class="stack" style="display:grid;gap:.8rem;max-width:640px">
      <div><label for="uffile">PDF file (max 50 MB)</label><input id="uffile" type="file" accept="application/pdf,.pdf" required></div>
      <div class="row"><div><label for="ufe">Exam</label><select id="ufe">${opts(L.exams.map(e => [e.id, e.name]), '')}</select></div><div><label for="ufk">This file is</label><select id="ufk"><option value="question_paper">A question paper</option><option value="answer_key">An answer key</option></select></div></div>
      <div class="row"><div><label for="ufy">Year</label><input id="ufy" type="number" min="2002" max="2100" placeholder="2023" style="width:6rem"></div><div><label for="ufs">Session</label><input id="ufs" size="4" placeholder="1"></div>
        <div><label for="ufh">Shift</label><input id="ufh" size="8" placeholder="1 or 2"></div><div><label for="ufp">Paper</label><input id="ufp" type="number" min="1" max="2" style="width:5rem" placeholder="1"></div></div>
      <div class="row"><div><label for="ufd">Exam date (if the paper shows one)</label><input id="ufd" type="date"></div><div><label for="ufv">Key version</label><select id="ufv"><option value="">Not stated</option><option>provisional</option><option>final</option></select></div></div>
      <div><label for="ufo">Where did it come from?</label><select id="ufo"><option value="official">The official site (jeemain.nta.nic.in, nta.ac.in, jeeadv.ac.in)</option><option value="verified_archive">A trusted archive I have verified</option></select></div>
      <div><label for="ufn">Notes (optional: link or source)</label><input id="ufn" maxlength="300"></div>
      <div class="row"><button class="accent" id="ufg">Upload</button><span id="ufm" class="muted small" aria-live="polite"></span></div></form></div>`;
  $('#uf', box).onsubmit = guard(async e => {
    e.preventDefault(); const file = $('#uffile', box).files[0], msg = t => $('#ufm', box).textContent = t;
    if (!file) return; if (file.size > 50 * 1024 * 1024) return msg('That file is over 50 MB.');
    const buf = await file.arrayBuffer(); if (new TextDecoder().decode(buf.slice(0, 5)) !== '%PDF-') return msg('That does not look like a PDF.');
    $('#ufg', box).disabled = true; msg('Checking…');
    try {
      const sha = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buf))].map(b => b.toString(16).padStart(2, '0')).join('');
      const dup = await sb.from('source_documents').select('id,source_url,storage_path,import_status').eq('sha256', sha).limit(1);
      if (dup.data?.length) return msg(`Already stored (${dup.data[0].import_status}). Find it under Documents and use Retry if needed.`);
      const exam = L.exams.find(x => x.id === Number($('#ufe', box).value)), path = `${exam.code}/${sha.slice(0, 16)}.pdf`;
      msg('Uploading…'); const up = await sb.storage.from('source-documents').upload(path, new Blob([buf], { type: 'application/pdf' }), { upsert: true, contentType: 'application/pdf' }); if (up.error) throw up.error;
      const year = $('#ufy', box).value, row = { exam_id: exam.id, doc_kind: $('#ufk', box).value, storage_path: path, sha256: sha, origin: 'manual_upload', status: $('#ufo', box).value, import_status: 'downloaded', status_reason: 'Uploaded manually; waiting for the importer.',
        exam_year: year ? Number(year) : null, session: $('#ufs', box).value.trim() || null, shift: $('#ufh', box).value.trim() || null, paper_number: $('#ufp', box).value ? Number($('#ufp', box).value) : null, exam_date: $('#ufd', box).value || null,
        file_size_bytes: file.size, link_text: file.name, notes: $('#ufn', box).value.trim() || null, detected: { uploaded_by: ctx.user.id, key_version: $('#ufv', box).value || null } };
      const ins = await sb.from('source_documents').insert(row).select('id').single(); if (ins.error) throw ins.error;
      const job = await sb.from('import_jobs').insert({ document_id: ins.data.id, status: 'pending' }); if (job.error) throw job.error;
      const run = await sb.from('import_runs').insert({ trigger: 'manual', status: 'queued', mode: 'process_only', requested_by: ctx.user.id }); if (run.error) throw run.error;
      toast('Uploaded and queued. The importer will read it on its next run.'); S.doc = { status: 'downloaded', kind: '', exam: '', q: '', page: 0 }; go('documents');
    } finally { $('#ufg', box) && ($('#ufg', box).disabled = false); }
  });
}

// ───────────────────────────────────────────────────────────── Access
async function access(box) {
  const g = async k => (await sb.from('app_settings').select('value').eq('key', k).single()).data?.value;
  const [mode, inv] = await Promise.all([g('registration_mode'), sb.from('invited_emails').select('email')]);
  box.innerHTML = `<div class="card"><div class="card-head"><h3>Access</h3></div><div class="row"><select id="rg" style="width:auto;min-width:260px"><option value="private" ${mode === 'private' ? 'selected' : ''}>Private (invited emails only)</option><option value="public" ${mode === 'public' ? 'selected' : ''}>Public registration</option></select><button id="rgs">Save</button></div>
    <label for="ie">Invite an email address</label><div class="row"><input id="ie" type="email" style="max-width:320px" placeholder="student@example.com"><button class="ghost" id="ia">Invite</button></div><p class="muted small" style="margin:.8rem 0 0">Invited: ${(inv.data || []).map(x => esc(x.email)).join(', ') || 'none'}</p></div>`;
  $('#rgs', box).onclick = guard(async () => { const { error } = await sb.from('app_settings').upsert({ key: 'registration_mode', value: $('#rg', box).value, updated_by: ctx.user.id }); toast(error ? error.message : 'Saved'); });
  $('#ia', box).onclick = guard(async () => { const { error } = await sb.from('invited_emails').insert({ email: $('#ie', box).value.trim().toLowerCase(), invited_by: ctx.user.id }); toast(error ? error.message : 'Invited'); if (!error) render(); });
}
