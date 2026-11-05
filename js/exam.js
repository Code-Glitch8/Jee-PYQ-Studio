import { sb, ctx, esc, $, $$, fmt, math, toast, errBox, startAttempt } from './lib.js';
import { marksFor } from './marking.js';

const QSEL = 'id,statement,question_type,difficulty,correct_answer,subject_id,chapter_id,topic_id,marks_scheme_id,question_number,papers(exam_id,exam_year,session,shift,exams(name)),subjects(name),chapters(name),topics(name)';

export async function examView(root, attemptId) {
  root.innerHTML = '<p class="muted" style="padding:2rem">Loading test…</p>';
  try {
    const { data: att, error } = await sb.from('attempts').select('*, tests(name,duration_seconds)').eq('id', attemptId).single();
    if (error) throw error;
    if (att.status === 'submitted') { location.hash = '#/results/' + attemptId; return; }
    const { data: tq } = await sb.from('test_questions').select('question_id,position').eq('test_id', att.test_id).order('position');
    const ids = tq.map(x => x.question_id);
    const [{ data: qs }, { data: opts }, { data: resp }, { data: schemes }] = await Promise.all([
      sb.from('questions').select(QSEL).in('id', ids),
      sb.from('question_options').select('*').in('question_id', ids).order('sort_order'),
      sb.from('attempt_responses').select('*').eq('attempt_id', attemptId),
      sb.from('marking_schemes').select('*'),
    ]);
    const byId = Object.fromEntries(qs.map(q => [q.id, q]));
    const questions = ids.map(id => byId[id]).filter(Boolean);
    const R = {};
    for (const q of questions) {
      const r = resp.find(x => x.question_id === q.id);
      R[q.id] = r ? { ...r, dirty: false } : { question_id: q.id, first_opened_at: null, active_seconds: 0, visit_count: 0, answer_events: [], final_answer: null, marked_for_review: false, dirty: false };
    }
    run({ root, att, questions, opts, R, schemes });
  } catch (e) { root.innerHTML = '<div style="padding:2rem">' + errBox(e) + '<a href="#/tests">Back to My Tests</a></div>'; }
}

function run(S) {
  const { root, att, questions, opts, R, schemes } = S;
  let cur = Math.max(0, questions.findIndex(q => q.id === att.current_question_id));
  let remaining = att.remaining_seconds ?? att.tests.duration_seconds;
  let activeTotal = att.active_seconds || 0, elapsedTotal = att.total_elapsed_seconds || 0;
  let paused = false, visit = null, last = Date.now(), done = false;

  const isActive = () => !paused && document.visibilityState === 'visible' && document.hasFocus();

  function openQ() {
    const q = questions[cur], r = R[q.id];
    r.visit_count += 1; r.dirty = true;
    if (!r.first_opened_at) r.first_opened_at = new Date().toISOString();
    if (r.visit_count > 1) r.was_revisited = true;
    visit = { q: q.id, started: new Date().toISOString(), ms: 0 };
  }
  async function closeVisit() {
    if (!visit) return;
    const v = visit; visit = null;
    if (v.ms < 300) return;
    const r = R[v.q];
    if (!r.id) return; // saved row needed for FK; flushed below after first save
    await sb.from('question_visits').insert({ response_id: r.id, user_id: ctx.user.id, started_at: v.started, ended_at: new Date().toISOString(), active_ms: Math.round(v.ms) });
  }
  async function save() {
    const rows = Object.values(R).filter(r => r.dirty || r.id === undefined && r.visit_count).map(r => ({
      ...(r.id ? { id: r.id } : {}), attempt_id: att.id, user_id: ctx.user.id, question_id: r.question_id,
      first_opened_at: r.first_opened_at, active_seconds: Math.round(r.active_seconds * 100) / 100, visit_count: r.visit_count,
      answer_events: r.answer_events, final_answer: r.final_answer, marked_for_review: r.marked_for_review, was_revisited: !!r.was_revisited,
    }));
    if (rows.length) {
      const { data, error } = await sb.from('attempt_responses').upsert(rows, { onConflict: 'attempt_id,question_id' }).select('id,question_id');
      if (error) return toast('Could not save: ' + error.message);
      for (const d of data) { R[d.question_id].id = d.id; R[d.question_id].dirty = false; }
    }
    await sb.from('attempts').update({ remaining_seconds: remaining, active_seconds: Math.round(activeTotal), total_elapsed_seconds: Math.round(elapsedTotal),
      current_question_id: questions[cur].id, status: paused ? 'paused' : 'in_progress' }).eq('id', att.id);
  }
  async function go(i) { await closeVisit(); await save(); cur = Math.min(Math.max(i, 0), questions.length - 1); openQ(); draw(); await save(); }

  function setAnswer(a) {
    const r = R[questions[cur].id];
    r.final_answer = a; r.dirty = true; r.answer_events.push({ t: new Date().toISOString(), a });
    drawPalette();
  }
  function status(q, i) {
    const r = R[q.id];
    return (i === cur ? 'cur ' : '') + (r.marked_for_review ? 'review' : r.final_answer != null && r.final_answer !== '' && !(Array.isArray(r.final_answer) && !r.final_answer.length) ? 'answered' : r.visit_count ? 'visited' : '');
  }
  function drawPalette() {
    $('#pal', root).innerHTML = questions.map((q, i) => `<button class="pal ${status(q, i)}" data-i="${i}" title="${esc(q.subjects?.name)}">${i + 1}</button>`).join('');
    $$('#pal .pal', root).forEach(b => b.onclick = () => go(+b.dataset.i));
    const subs = [...new Map(questions.map((q, i) => [q.subject_id, { n: q.subjects?.name, i }])).values()];
    $('#subs', root).innerHTML = subs.map(s => `<button data-i="${s.i}" class="${questions[cur].subjects?.name === s.n ? 'on' : ''}">${esc(s.n)}</button>`).join('');
    $$('#subs button', root).forEach(b => b.onclick = () => go(+b.dataset.i));
  }
  function draw() {
    const q = questions[cur], r = R[q.id], qo = opts.filter(o => o.question_id === q.id);
    const a = r.final_answer;
    let input;
    if (q.question_type === 'single_mcq' || q.question_type === 'multi_mcq') {
      const multi = q.question_type === 'multi_mcq';
      input = qo.map(o => { const sel = multi ? (a || []).includes(o.label) : a === o.label;
        return `<label class="opt ${sel ? 'sel' : ''}"><input type="${multi ? 'checkbox' : 'radio'}" name="o" value="${esc(o.label)}" ${sel ? 'checked' : ''}><span><b>${esc(o.label)}.</b> ${esc(o.content)}</span></label>`; }).join('');
    } else input = `<label for="num">Your answer</label><input id="num" inputmode="decimal" autocomplete="off" value="${esc(a ?? '')}">`;
    $('#qbox', root).innerHTML = `<div class="muted">Question ${cur + 1} of ${questions.length} · ${esc(q.subjects?.name)} · ${esc(q.chapters?.name || '')} · ${esc(q.question_type.replace('_', ' '))}</div>
      <div class="q-statement">${esc(q.statement)}</div>${input}`;
    $$('#qbox input[name=o]', root).forEach(el => el.onchange = () => {
      if (q.question_type === 'multi_mcq') setAnswer($$('#qbox input[name=o]:checked', root).map(x => x.value)); else setAnswer(el.value);
      $$('#qbox .opt', root).forEach(o => o.classList.toggle('sel', o.querySelector('input').checked));
    });
    const num = $('#num', root); if (num) num.oninput = () => setAnswer(num.value.trim() === '' ? null : num.value.trim());
    $('#rev', root).textContent = r.marked_for_review ? 'Unmark review' : 'Mark for review';
    drawPalette(); math($('#qbox', root));
  }

  root.innerHTML = `<div class="exam">
    <div class="exam-top card" style="margin:0"><div><b>${esc(att.tests.name)}</b><div class="muted">Attempt ${att.attempt_number} · your own practice clock, not the official exam limit</div></div>
      <div class="timer" id="timer" aria-live="off"></div>
      <div class="row"><button class="ghost" id="pause">Pause</button><button id="submit">Submit test</button></div></div>
    <div><div class="tabs" id="subs"></div><div class="card" id="qbox" style="margin-top:.8rem"></div>
      <div class="row"><button class="ghost" id="prev">Previous</button><button id="next">Save &amp; next</button><button class="ghost" id="rev">Mark for review</button><button class="ghost" id="clear">Clear response</button></div></div>
    <aside class="card"><b>Question palette</b><div class="palette" id="pal" style="margin-top:.6rem"></div>
      <p class="muted" style="font-size:.8rem">Green answered · red visited, no answer · amber marked for review</p></aside>
    <div id="overlay" hidden class="card" style="grid-column:1/-1"><b>Paused.</b> Time is not counting. <button id="resume">Resume</button></div></div>`;

  $('#prev', root).onclick = () => go(cur - 1);
  $('#next', root).onclick = () => go(cur + 1);
  $('#rev', root).onclick = () => { const r = R[questions[cur].id]; r.marked_for_review = !r.marked_for_review; r.dirty = true; draw(); };
  $('#clear', root).onclick = () => { setAnswer(null); draw(); };
  const setPause = async p => { paused = p; $('#overlay', root).hidden = !p; $('#qbox', root).style.visibility = p ? 'hidden' : 'visible'; await save(); };
  $('#pause', root).onclick = () => setPause(true); $('#resume', root).onclick = () => setPause(false);
  $('#submit', root).onclick = () => { const un = questions.filter(q => R[q.id].final_answer == null).length;
    if (confirm(`Submit now? ${un} of ${questions.length} questions are unanswered.`)) finish(); };

  async function finish() {
    if (done) return; done = true; clearInterval(timerId);
    await closeVisit(); await save();
    let score = 0, max = 0, unscored = 0;
    const rows = questions.map(q => { const r = R[q.id]; const m = marksFor(q, r.final_answer, schemes);
      if (m.marks == null) unscored++; else { score += m.marks; max += m.max; }
      return { id: r.id, attempt_id: att.id, user_id: ctx.user.id, question_id: q.id, final_answer: r.final_answer, is_correct: m.correct, marks_awarded: m.marks,
        was_skipped: r.final_answer == null && r.visit_count > 0, visit_count: r.visit_count, active_seconds: r.active_seconds }; });
    // Rows that were never opened have no id yet, so upsert by (attempt_id, question_id).
    rows.forEach(r => { if (!r.id) delete r.id; });
    const { error } = await sb.from('attempt_responses').upsert(rows, { onConflict: 'attempt_id,question_id' });
    if (error) { done = false; return toast('Could not submit: ' + error.message); }
    await sb.from('attempts').update({ status: 'submitted', submitted_at: new Date().toISOString(), remaining_seconds: remaining, active_seconds: Math.round(activeTotal),
      total_elapsed_seconds: Math.round(elapsedTotal), score, max_score: max }).eq('id', att.id);
    if (unscored) toast(`${unscored} question(s) had no marking scheme and were not scored.`);
    location.hash = '#/results/' + att.id;
  }

  const timerId = setInterval(() => {
    const now = Date.now(), dt = Math.min((now - last) / 1000, 2); last = now;
    if (paused || done) return;
    remaining -= dt; elapsedTotal += dt;
    if (isActive() && visit) { const r = R[visit.q]; r.active_seconds += dt; visit.ms += dt * 1000; activeTotal += dt; r.dirty = true; }
    $('#timer', root).textContent = fmt(remaining);
    if (remaining <= 0) { toast('Time is up. Submitting.'); finish(); }
  }, 1000);
  const autosave = setInterval(() => { if (!done) save(); }, 10000);
  window.addEventListener('beforeunload', () => { if (!done) save(); });
  window.addEventListener('hashchange', () => { clearInterval(timerId); clearInterval(autosave); }, { once: true });

  openQ(); draw(); save();
}

export async function resultsView(main, attemptId) {
  main.innerHTML = '<p class="muted">Loading results…</p>';
  try {
    const { data: att, error } = await sb.from('attempts').select('*, tests(id,name,question_count,duration_seconds)').eq('id', attemptId).single();
    if (error) throw error;
    const { data: resp } = await sb.from('attempt_responses').select(`*, questions(statement,question_type,correct_answer,answer_verified,answer_source,difficulty,subjects(name),chapters(name),topics(name))`).eq('attempt_id', attemptId);
    const qids = resp.map(r => r.question_id);
    const [{ data: sols }, { data: stats }, { data: opts }] = await Promise.all([
      sb.from('solutions').select('*').in('question_id', qids).eq('is_published', true),
      sb.from('question_stats').select('*').in('question_id', qids),
      sb.from('question_options').select('question_id,label,content').in('question_id', qids).order('sort_order'),
    ]);
    const n = resp.length, correct = resp.filter(r => r.is_correct === true).length, wrong = resp.filter(r => r.is_correct === false).length;
    const unatt = resp.filter(r => r.is_correct === null).length, attempted = correct + wrong;
    const grp = key => { const m = {}; for (const r of resp) { const k = key(r) || 'Unclassified'; const g = (m[k] ||= { n: 0, c: 0, w: 0, t: 0, marks: 0 });
      g.n++; g.t += +r.active_seconds || 0; g.marks += +r.marks_awarded || 0; if (r.is_correct === true) g.c++; if (r.is_correct === false) g.w++; } return m; };
    const table = (m, title) => `<h2>${title}</h2><div class="card" style="overflow-x:auto"><table><tr><th></th><th>Questions</th><th>Correct</th><th>Wrong</th><th>Accuracy</th><th>Avg time</th></tr>` +
      Object.entries(m).map(([k, g]) => `<tr><td>${esc(k)}</td><td>${g.n}</td><td>${g.c}</td><td>${g.w}</td><td>${g.c + g.w ? Math.round(100 * g.c / (g.c + g.w)) + '%' : '—'}</td><td>${fmt(g.t / g.n)}</td></tr>`).join('') + '</table></div>';
    const timed = resp.filter(r => r.visit_count > 0).sort((a, b) => a.active_seconds - b.active_seconds);
    const label = r => `Q${resp.indexOf(r) + 1} (${fmt(r.active_seconds)})`;
    main.innerHTML = `<h1>Results: ${esc(att.tests.name)}</h1>
      <div class="grid">
        <div class="card stat"><b>${att.score ?? '—'} / ${att.max_score ?? '—'}</b>Marks</div>
        <div class="card stat"><b class="ok">${correct}</b>Correct</div><div class="card stat"><b class="bad">${wrong}</b>Incorrect</div><div class="card stat"><b>${unatt}</b>Unattempted</div>
        <div class="card stat"><b>${attempted ? Math.round(100 * correct / attempted) : 0}%</b>Accuracy</div>
        <div class="card stat"><b>${fmt(att.total_elapsed_seconds)}</b>Total duration</div><div class="card stat"><b>${fmt(att.active_seconds)}</b>Active time</div>
        <div class="card stat"><b>${fmt((att.active_seconds || 0) / Math.max(n, 1))}</b>Avg per question</div></div>
      ${timed.length ? `<p class="muted">Fastest: ${label(timed[0])} · Slowest: ${label(timed[timed.length - 1])}</p>` : ''}
      <div class="row"><a class="btn" href="#/coach/${att.id}">AI Study Coach report</a><button class="ghost" id="re">Reattempt this test</button><button class="ghost" id="wrongTest">Test from incorrect questions</button></div>
      ${table(grp(r => r.questions?.subjects?.name), 'Subject-wise')}${table(grp(r => r.questions?.chapters?.name), 'Chapter-wise')}${table(grp(r => r.questions?.topics?.name), 'Topic-wise')}
      <h2>Review and solutions</h2><div id="rev"></div>`;
    $('#re', main).onclick = async () => { try { location.hash = '#/test/' + await startAttempt(att.tests.id); } catch (e) { toast(e.message); } };
    $('#wrongTest', main).onclick = () => { sessionStorage.setItem('prefill', JSON.stringify({ attempt_filter: 'only_incorrect' })); location.hash = '#/create-test'; };
    $('#rev', main).innerHTML = resp.map((r, i) => {
      const q = r.questions, so = sols.find(s => s.question_id === r.question_id), st = stats.find(s => s.question_id === r.question_id);
      const o = opts.filter(x => x.question_id === r.question_id);
      const fa = v => v == null ? '<i>none</i>' : esc(Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : v);
      return `<details class="card"><summary><b>Q${i + 1}</b> <span class="tag">${r.is_correct === true ? '✓ correct' : r.is_correct === false ? '✗ incorrect' : 'unattempted'}</span><span class="tag">${esc(q.chapters?.name || 'Unclassified')}</span><span class="tag">${esc(q.difficulty || 'unrated')}</span> ${fmt(r.active_seconds)}</summary>
        <div class="q-statement">${esc(q.statement)}</div>${o.map(x => `<div><b>${esc(x.label)}.</b> ${esc(x.content)}</div>`).join('')}
        <p>Your answer: ${fa(r.final_answer)} · Correct answer: ${fa(q.correct_answer)} <span class="tag">${q.answer_verified ? 'verified' : 'not yet verified'}</span><span class="tag">source: ${esc(q.answer_source || 'unknown')}</span></p>
        ${so ? `<p><span class="tag">${so.origin === 'ai_generated' ? 'AI-generated solution' : esc(so.origin)}</span>${so.origin === 'ai_generated' && !so.checked_against_official ? '<span class="tag warn">not checked against an official answer</span>' : ''}</p><div style="white-space:pre-wrap">${esc(so.steps)}</div>` : '<p class="muted">No solution available for this question yet.</p>'}
        <p class="muted">${st ? `${st.percent_correct ?? '—'}% answered correctly (${st.response_count ?? '?'} responses). Source: ${esc(st.source_note || st.source_url || 'not recorded')}` : 'Historical response statistics unavailable.'}</p></details>`; }).join('');
    math($('#rev', main));
  } catch (e) { main.innerHTML = errBox(e); }
}
