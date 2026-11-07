import { sb, ctx, esc, $, $$, fmt, math, toast, errBox, startAttempt, ico, head, empty, loading, subjTag, sk, pct, bar, confirmDialog, figsAttr, fillFigures } from './lib.js';
import { marksFor, correctValue } from './marking.js';

const TYPE_LABEL = { single_mcq: 'Single correct', multi_mcq: 'One or more correct', numerical: 'Numerical', integer: 'Integer' };
const asList = v => (Array.isArray(v) ? v : v == null || v === '' ? [] : [v]).map(x => String(x).trim().toUpperCase());

const QSEL = 'id,statement,images,question_type,difficulty,correct_answer,subject_id,chapter_id,topic_id,marks_scheme_id,question_number,papers(exam_id,exam_year,session,shift,exams(name)),subjects(name),chapters(name),topics(name)';

export async function examView(root, attemptId) {
  root.innerHTML = `<div style="padding:3rem 2rem">${loading('Loading test…')}</div>`;
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
  } catch (e) { root.innerHTML = '<div style="padding:2rem;max-width:560px;margin:0 auto">' + errBox(e) + '<a class="btn ghost" href="#/tests">Back to my tests</a></div>'; }
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
    const cnt = { answered: 0, visited: 0, review: 0, none: 0 };
    $('#pal', root).innerHTML = questions.map((q, i) => { const st = status(q, i); cnt[st.replace('cur ', '').trim() || 'none']++;
      return `<button class="pal ${st}" data-i="${i}" title="${esc(q.subjects?.name)}" aria-label="Question ${i + 1}${st.includes('answered') ? ', answered' : st.includes('review') ? ', marked for review' : st.includes('visited') ? ', not answered' : ', not visited'}"${i === cur ? ' aria-current="true"' : ''}>${i + 1}</button>`; }).join('');
    $$('#pal .pal', root).forEach(b => b.onclick = () => go(+b.dataset.i));
    $('#legend', root).innerHTML = `<span><i class="a"></i>Answered<b>${cnt.answered}</b></span><span><i class="v"></i>Not answered<b>${cnt.visited}</b></span><span><i class="r"></i>For review<b>${cnt.review}</b></span><span><i></i>Not visited<b>${cnt.none}</b></span>`;
    const subs = [...new Map(questions.map((q, i) => [q.subject_id, { n: q.subjects?.name, i }])).values()];
    $('#subs', root).innerHTML = subs.map(s => `<button data-s="${sk(s.n)}" data-i="${s.i}" class="${questions[cur].subjects?.name === s.n ? 'on' : ''}"><span class="dot"></span>${esc(s.n)}</button>`).join('');
    $$('#subs button', root).forEach(b => b.onclick = () => go(+b.dataset.i));
  }
  function draw() {
    const q = questions[cur], r = R[q.id], qo = opts.filter(o => o.question_id === q.id);
    const a = r.final_answer;
    let input;
    if (q.question_type === 'single_mcq' || q.question_type === 'multi_mcq') {
      const multi = q.question_type === 'multi_mcq';
      input = `<div class="opts" role="${multi ? 'group' : 'radiogroup'}" aria-label="Answer options">` + qo.map(o => { const sel = multi ? (a || []).includes(o.label) : a === o.label;
        return `<label class="opt ${multi ? 'multi' : ''} ${sel ? 'sel' : ''}"><input type="${multi ? 'checkbox' : 'radio'}" name="o" value="${esc(o.label)}" ${sel ? 'checked' : ''}><span class="key">${esc(o.label)}</span><span class="txt">${esc(o.content)}</span></label>`; }).join('') + '</div>';
    } else input = `<label for="num">Your answer</label><input id="num" class="num-input" inputmode="decimal" autocomplete="off" value="${esc(a ?? '')}">`;
    $('#qbox', root).innerHTML = `<div class="q-meta"><span class="qn">Q${cur + 1} <span class="muted">of ${questions.length}</span></span>${subjTag(q.subjects?.name)}${q.chapters?.name ? `<span class="tag">${esc(q.chapters.name)}</span>` : ''}<span class="tag">${esc(TYPE_LABEL[q.question_type] || q.question_type)}</span></div>
      <div class="q-statement">${esc(q.statement)}</div><div class="q-figs" ${figsAttr(q.images)}></div>${input}`;
    $$('#qbox input[name=o]', root).forEach(el => el.onchange = () => {
      if (q.question_type === 'multi_mcq') setAnswer($$('#qbox input[name=o]:checked', root).map(x => x.value)); else setAnswer(el.value);
      $$('#qbox .opt', root).forEach(o => o.classList.toggle('sel', o.querySelector('input').checked));
    });
    const num = $('#num', root); if (num) num.oninput = () => setAnswer(num.value.trim() === '' ? null : num.value.trim());
    $('#rev', root).textContent = r.marked_for_review ? 'Unmark review' : 'Mark for review';
    drawPalette(); math($('#qbox', root)); fillFigures($('#qbox', root));
  }

  root.innerHTML = `<div class="exam">
    <div class="exam-top card"><div class="title"><b>${esc(att.tests.name)}</b><span>Attempt ${att.attempt_number} · your own practice clock, not the official exam limit</span></div>
      <div class="timer" id="timer" role="timer" aria-live="off">${ico('clock')}<span id="tt">${fmt(remaining)}</span></div>
      <div class="actions"><button class="ghost" id="pause">${ico('pause')}Pause</button><button class="accent" id="submit">Submit test</button></div></div>
    <div class="exam-main"><div class="tabs" id="subs"></div><div class="card paper" id="qbox"></div>
      <div class="exam-actions"><button class="ghost" id="prev">Previous</button><button class="ghost" id="rev">Mark for review</button><button class="ghost" id="clear">Clear response</button><span class="spacer"></span><button class="accent" id="next">Save &amp; next</button></div></div>
    <aside class="card exam-side"><h3>Question palette</h3><div class="palette" id="pal"></div><div class="legend" id="legend"></div></aside>
    <div class="paused" id="overlay" role="dialog" aria-modal="true" aria-label="Test paused"><div class="card"><h3>Test paused</h3><p class="muted">Your timer has stopped and your answers are saved.</p><button class="accent" id="resume">Resume test</button></div></div></div>`;

  $('#prev', root).onclick = () => go(cur - 1);
  $('#next', root).onclick = () => go(cur + 1);
  $('#rev', root).onclick = () => { const r = R[questions[cur].id]; r.marked_for_review = !r.marked_for_review; r.dirty = true; draw(); };
  $('#clear', root).onclick = () => { setAnswer(null); draw(); };
  const setPause = async p => { paused = p; $('#overlay', root).classList.toggle('show', p); $('#qbox', root).style.visibility = p ? 'hidden' : 'visible'; if (p) $('#resume', root).focus(); await save(); };
  $('#pause', root).onclick = () => setPause(true); $('#resume', root).onclick = () => setPause(false);
  $('#submit', root).onclick = async () => { const un = questions.filter(q => R[q.id].final_answer == null).length;
    if (await confirmDialog('Submit this test?', un ? `${un} of ${questions.length} questions are unanswered. You cannot change answers after submitting.` : 'All questions are answered. You cannot change answers after submitting.', 'Submit test', 'Keep working')) finish(); };

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

  const showTime = () => { $('#tt', root).textContent = fmt(remaining); $('#timer', root).classList.toggle('low', remaining <= 300); };
  showTime();
  const timerId = setInterval(() => {
    const now = Date.now(), dt = Math.min((now - last) / 1000, 2); last = now;
    if (paused || done) return;
    remaining -= dt; elapsedTotal += dt;
    if (isActive() && visit) { const r = R[visit.q]; r.active_seconds += dt; visit.ms += dt * 1000; activeTotal += dt; r.dirty = true; }
    showTime();
    if (remaining <= 0) { toast('Time is up. Submitting.'); finish(); }
  }, 1000);
  const autosave = setInterval(() => { if (!done) save(); }, 10000);
  window.addEventListener('beforeunload', () => { if (!done) save(); });
  window.addEventListener('hashchange', () => { clearInterval(timerId); clearInterval(autosave); }, { once: true });

  openQ(); draw(); save();
}

export async function resultsView(main, attemptId) {
  main.innerHTML = loading('Loading results…');
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
    const table = (m, title, col) => `<h2>${title}</h2><div class="card flush table-wrap"><table><thead><tr><th>${col}</th><th class="num">Questions</th><th class="num">Correct</th><th class="num">Wrong</th><th>Accuracy</th><th class="num">Avg time</th></tr></thead><tbody>` +
      Object.entries(m).map(([k, g]) => `<tr><td>${esc(k)}</td><td class="num">${g.n}</td><td class="num">${g.c}</td><td class="num">${g.w}</td><td>${bar(pct(g.c, g.w))}</td><td class="num">${fmt(g.t / g.n)}</td></tr>`).join('') + '</tbody></table></div>';
    const timed = resp.filter(r => r.visit_count > 0).sort((a, b) => a.active_seconds - b.active_seconds);
    const qno = r => resp.indexOf(r) + 1;
    const accPct = pct(correct, wrong) ?? 0;
    const when = att.submitted_at ? new Date(att.submitted_at).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' }) : '';
    const verdict = r => r.is_correct === true ? 'Correct' : r.is_correct === false ? 'Incorrect' : 'Unattempted';
    main.innerHTML = head(att.tests.name, `Attempt ${att.attempt_number}${when ? ' · ' + esc(when) : ''}`,
        `<a class="btn accent" href="#/coach/${att.id}">${ico('coach')}AI study coach report</a><button class="ghost" id="re">Reattempt this test</button><button class="ghost" id="wrongTest">Test from incorrect questions</button>`)
      + `<div class="card result-hero"><div class="score-big"><div><div class="lbl">Your score</div><div class="n">${att.score ?? '—'}<small>/ ${att.max_score ?? '—'}</small></div></div>
          <div class="row" style="flex-wrap:nowrap;gap:.9rem"><div class="ring" id="ring" role="img" aria-label="Accuracy ${accPct} percent"><svg width="84" height="84" viewBox="0 0 84 84"><circle class="bg" cx="42" cy="42" r="34"/><circle class="fg" cx="42" cy="42" r="34" style="--d:0"/></svg><b>${accPct}%</b></div>
          <div><div class="lbl" style="margin:0">Accuracy</div><div class="small muted">${correct} of ${attempted} attempted</div></div></div></div>
        <div class="strip-wrap"><div class="head"><span>Question by question</span><span class="small">Select a block to jump to its review</span></div>
          <div class="strip">${resp.map((r, i) => `<button class="${r.is_correct === true ? 'c' : r.is_correct === false ? 'w' : 's'}" style="--i:${i}" data-i="${i}" title="Q${i + 1}: ${verdict(r)}" aria-label="Q${i + 1}, ${verdict(r)}. Jump to review"></button>`).join('')}</div>
          <div class="strip-legend"><span><i style="background:var(--ok)"></i><b>${correct}</b> correct</span><span><i style="background:var(--bad)"></i><b>${wrong}</b> incorrect</span><span><i style="background:var(--line-strong)"></i><b>${unatt}</b> unattempted</span></div></div></div>
      <div class="stats"><div class="stat"><b>${fmt(att.total_elapsed_seconds)}</b>Total duration</div><div class="stat"><b>${fmt(att.active_seconds)}</b>Active time</div><div class="stat"><b>${fmt((att.active_seconds || 0) / Math.max(n, 1))}</b>Average per question</div>
        ${timed.length ? `<div class="stat"><b>${fmt(timed[0].active_seconds)}</b>Fastest, Q${qno(timed[0])}</div><div class="stat"><b>${fmt(timed[timed.length - 1].active_seconds)}</b>Slowest, Q${qno(timed[timed.length - 1])}</div>` : ''}</div>
      ${table(grp(r => r.questions?.subjects?.name), 'Subject-wise', 'Subject')}${table(grp(r => r.questions?.chapters?.name), 'Chapter-wise', 'Chapter')}${table(grp(r => r.questions?.topics?.name), 'Topic-wise', 'Topic')}
      <h2>Review and solutions</h2><div id="rev"></div>`;
    requestAnimationFrame(() => requestAnimationFrame(() => $('#ring .fg', main)?.style.setProperty('--d', (213.6 * accPct / 100).toFixed(1))));
    $('#re', main).onclick = async () => { try { location.hash = '#/test/' + await startAttempt(att.tests.id); } catch (e) { toast(e.message); } };
    $('#wrongTest', main).onclick = () => { sessionStorage.setItem('prefill', JSON.stringify({ attempt_filter: 'only_incorrect' })); location.hash = '#/create-test'; };
    $$('.strip button', main).forEach(b => b.onclick = () => { const d = $$('#rev details', main)[+b.dataset.i]; if (!d) return; d.open = true;
      d.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }); d.classList.remove('flash'); void d.offsetWidth; d.classList.add('flash'); });
    $('#rev', main).innerHTML = resp.map((r, i) => {
      const q = r.questions, so = sols.find(s => s.question_id === r.question_id), st = stats.find(s => s.question_id === r.question_id);
      const o = opts.filter(x => x.question_id === r.question_id);
      const fa = v => v == null ? '<i>none</i>' : esc(Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : v);
      const right = asList(correctValue({ correct_answer: q.correct_answer })), mine = asList(r.final_answer);
      const optRow = x => { const L = String(x.label).trim().toUpperCase(), isR = right.includes(L), isM = mine.includes(L);
        return `<div class="opt plain ${isR ? 'is-correct' : isM ? 'is-wrong' : ''}"><span class="key">${esc(x.label)}</span><span class="txt">${esc(x.content)}</span>${isR || isM ? `<span class="tagline">${isR && isM ? 'Your answer, correct' : isR ? 'Correct answer' : 'Your answer'}</span>` : ''}</div>`; };
      return `<details class="card rv ${r.is_correct === true ? 'c' : r.is_correct === false ? 'w' : ''}" id="rv-${i}"><summary><span class="qn">Q${i + 1}</span><span class="tag ${r.is_correct === true ? 'ok' : r.is_correct === false ? 'bad' : ''}">${verdict(r)}</span>${subjTag(q.subjects?.name)}<span class="tag">${esc(q.chapters?.name || 'Unclassified')}</span><span class="tag">${esc(q.difficulty || 'unrated')}</span><span class="t">${fmt(r.active_seconds)}</span></summary>
        <div class="body"><div class="q-statement">${esc(q.statement)}</div>${o.length ? `<div class="opts">${o.map(optRow).join('')}</div>` : ''}
        <div class="answers"><span><b>Your answer</b>${fa(r.final_answer)}</span><span><b>Correct answer</b>${fa(q.correct_answer)}</span></div>
        <p><span class="tag ${q.answer_verified ? 'ok' : 'warn'}">${q.answer_verified ? 'answer verified' : 'answer not yet verified'}</span><span class="tag">source: ${esc(q.answer_source || 'unknown')}</span></p>
        ${so ? `<div class="solution"><span class="tag ${so.origin === 'ai_generated' ? 'warn' : 'ok'}">${so.origin === 'ai_generated' ? 'AI-generated solution' : esc(so.origin)}</span>${so.origin === 'ai_generated' && !so.checked_against_official ? '<span class="tag warn">not checked against an official answer</span>' : ''}<div style="white-space:pre-wrap">${esc(so.steps)}</div></div>` : '<p class="muted">No solution available for this question yet.</p>'}
        <p class="muted small" style="margin:.9rem 0 0">${st ? `${st.percent_correct ?? '—'}% answered correctly (${st.response_count ?? '?'} responses). Source: ${esc(st.source_note || st.source_url || 'not recorded')}` : 'Historical response statistics unavailable.'}</p></div></details>`; }).join('');
    math($('#rev', main));
  } catch (e) { main.innerHTML = errBox(e); }
}
