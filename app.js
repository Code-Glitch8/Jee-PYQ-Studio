import { sb, ctx, esc, $, $$, fmt, math, toast, errBox, applyTheme, startAttempt, ico, head, empty, loading, subjTag, pct, bar } from './lib.js';
import { examView, resultsView } from './exam.js';

const NAV = [
  [null, [['dashboard', 'Dashboard']]],
  ['Practice', [['questions', 'PYQ question bank'], ['papers', 'Previous year papers'], ['create-test', 'Create custom test']]],
  ['Review', [['tests', 'My tests'], ['analytics', 'Performance analytics'], ['weak', 'Weak chapters'], ['coach', 'AI study coach']]],
  ['Account', [['settings', 'Settings']]],
];
const BRAND = `<div class="brand"><svg class="mark" width="30" height="30" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" style="fill:var(--mark-bg,var(--ink))"/><g style="fill:none;stroke:var(--mark-fg,var(--surface));stroke-width:1.6"><circle cx="11" cy="11" r="3.6"/><circle cx="11" cy="21" r="3.6"/><circle cx="21" cy="21" r="3.6"/></g><circle cx="21" cy="11" r="3.6" fill="#6c64ec"/></svg><span>JEE PYQ Studio</span></div>`;
// A decorative OMR answer sheet for the sign-in page.
const SHEET = (() => {
  const fill = [1, 3, 0, 2, 2, 1, 0, 3, 1]; let o = '<svg class="sheet" width="380" height="520" viewBox="0 0 380 520" aria-hidden="true">';
  'ABCD'.split('').forEach((l, c) => { o += `<text x="${96 + c * 70}" y="22" text-anchor="middle">${l}</text>`; });
  fill.forEach((f, r) => { o += `<text x="42" y="${68 + r * 52}" text-anchor="end">${r + 1}</text>`; for (let c = 0; c < 4; c++) o += `<circle class="${f === c ? 'f' : ''}" cx="${96 + c * 70}" cy="${64 + r * 52}" r="16"/>`; });
  return o + '</svg>';
})();
const app = $('#app');

async function route() {
  const { data: { session } } = await sb.auth.getSession();
  if (!session) return authView();
  if (ctx.user?.id !== session.user.id) {
    ctx.user = session.user;
    ctx.profile = (await sb.from('profiles').select('*').eq('id', session.user.id).single()).data;
    ctx.settings = (await sb.from('user_settings').select('*').eq('user_id', session.user.id).single()).data;
    applyTheme(ctx.settings?.theme);
  }
  const [name, arg] = (location.hash.replace(/^#\//, '') || 'dashboard').split('/');
  if (name === 'test') return examView(app, arg);
  const groups = NAV.map(([g, items]) => [g, g === 'Account' && ctx.profile?.role === 'admin' ? [...items, ['admin', 'Admin']] : items]);
  const link = ([k, l]) => `<a href="#/${k}" class="${k === name ? 'on' : ''}"${k === name ? ' aria-current="page"' : ''}>${ico(k)}<span>${l}</span></a>`;
  const who = ctx.profile?.display_name || ctx.user.email, initials = who.trim().split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();
  app.innerHTML = `<div class="layout"><aside class="side nav" id="side" aria-label="Main">${BRAND}
    <div class="nav-links">${groups.map(([g, items]) => `${g ? `<div class="nav-label">${g}</div>` : ''}${items.map(link).join('')}`).join('')}</div>
    <div class="account"><span class="avatar" aria-hidden="true">${esc(initials)}</span><div class="who"><b>${esc(who)}</b><span>${esc(ctx.profile?.role || '')}</span></div>
      <a href="#" id="out" class="out" title="Sign out" aria-label="Sign out">${ico('out')}</a></div></aside>
    <div class="content"><div class="topbar"><button class="ghost" id="menu" aria-label="Open menu">${ico('menu')}</button>${BRAND}</div><main id="main">${loading('Loading…')}</main></div></div><div class="scrim" id="scrim"></div>`;
  const toggleSide = open => { $('#side').classList.toggle('open', open); $('#scrim').classList.toggle('show', open); };
  $('#menu').onclick = () => toggleSide(!$('#side').classList.contains('open'));
  $('#scrim').onclick = () => toggleSide(false);
  $('#side').onclick = e => { if (e.target.closest('a[href^="#/"]')) toggleSide(false); };
  $('#out').onclick = async e => { e.preventDefault(); await sb.auth.signOut(); ctx.user = null; location.hash = '#/'; route(); };
  const main = $('#main'), v = VIEWS[name];
  if (name === 'results') return resultsView(main, arg);
  if (name === 'coach') return coach(main, arg);
  try { await (v || VIEWS.dashboard)(main, arg); } catch (e) { main.innerHTML = '' + head('Something went wrong') + errBox(e); }
}

function authView() {
  const tick = `<li>${ico('check')}`;
  app.innerHTML = `<div class="auth-wrap"><section class="auth-hero">${BRAND}${SHEET}<h2>Practise every PYQ. Understand every mistake.</h2>
    <p>Previous-year JEE Main and Advanced questions, timed like the real exam, with analytics that show where marks are being lost.</p>
    <ul>${tick}<span>Build custom tests by chapter, topic, year and difficulty</span></li>${tick}<span>Exam-style interface with per-question timing</span></li>${tick}<span>Weak-topic detection from your results, plus an AI study coach</span></li></ul></section>
    <section class="auth-panel"><div class="auth"><div class="m-brand">${BRAND}</div><h1 id="ah">Welcome back</h1><p class="sub" id="as">Sign in to pick up where you left off.</p>
    <div class="card"><div class="tabs full" id="mode" role="tablist"><button class="on" data-m="in">Sign in</button><button data-m="up">Create account</button></div>
    <label for="em">Email</label><input id="em" type="email" autocomplete="email" placeholder="you@example.com">
    <div id="pwrow"><div class="field-row"><label for="pw">Password</label><button type="button" class="link" data-m="reset" id="forgot">Forgot password?</button></div><input id="pw" type="password" minlength="8" autocomplete="current-password"></div>
    <div id="nmrow" hidden><label for="nm">Display name</label><input id="nm" autocomplete="name"></div>
    <p style="margin:1.2rem 0 0"><button id="go" class="accent" style="width:100%">Sign in</button></p><div id="amsg" aria-live="polite"></div></div></div></section></div>`;
  let mode = 'in'; const msg = (t, c = 'err') => $('#amsg').innerHTML = `<div class="msg ${c}">${esc(t)}</div>`;
  const COPY = { in: ['Welcome back', 'Sign in to pick up where you left off.'], up: ['Create your account', 'Start practising previous-year questions in a few minutes.'], reset: ['Reset your password', 'Enter your email and we will send you a reset link.'] };
  $$('[data-m]').forEach(b => b.onclick = () => { mode = b.dataset.m; $$('#mode button').forEach(x => x.classList.toggle('on', x.dataset.m === mode)); $('#amsg').innerHTML = '';
    $('#pwrow').hidden = mode === 'reset'; $('#nmrow').hidden = mode !== 'up'; $('#go').textContent = { in: 'Sign in', up: 'Create account', reset: 'Send reset link' }[mode];
    $('#ah').textContent = COPY[mode][0]; $('#as').textContent = COPY[mode][1]; $('#pw').autocomplete = mode === 'up' ? 'new-password' : 'current-password'; });
  $('#go').onclick = async () => {
    const email = $('#em').value.trim(), password = $('#pw').value; $('#go').disabled = true;
    try {
      if (mode === 'in') { const { error } = await sb.auth.signInWithPassword({ email, password }); if (error) throw error; location.hash = '#/dashboard'; route(); }
      else if (mode === 'up') { const { data, error } = await sb.auth.signUp({ email, password, options: { data: { display_name: $('#nm').value.trim() || undefined }, emailRedirectTo: location.origin + location.pathname } });
        if (error) throw error; if (data.session) route(); else msg('Check your email to confirm your account, then sign in.', 'good'); }
      else { const { error } = await sb.auth.resetPasswordForEmail(email, { redirectTo: location.origin + location.pathname + '#/settings' }); if (error) throw error; msg('If that email has an account, a reset link is on its way.', 'good'); }
    } catch (e) { msg(e.message); } finally { $('#go').disabled = false; }
  };
}
sb.auth.onAuthStateChange(ev => { if (ev === 'PASSWORD_RECOVERY') location.hash = '#/settings'; });

const lookups = async () => { const [s, c, t, e] = await Promise.all([sb.from('subjects').select('*'), sb.from('chapters').select('*').order('sort_order'), sb.from('topics').select('*').order('sort_order'), sb.from('exams').select('*')]);
  return { subjects: s.data, chapters: c.data, topics: t.data, exams: e.data }; };
const opt = (arr, v = 'id', l = 'name') => arr.map(x => `<option value="${x[v]}">${esc(x[l])}</option>`).join('');

const VIEWS = {
  async dashboard(main) {
    const [q, p, a, last] = await Promise.all([
      sb.from('questions').select('id', { count: 'exact', head: true }).eq('is_published', true),
      sb.from('papers').select('id', { count: 'exact', head: true }),
      sb.from('attempts').select('id', { count: 'exact', head: true }).eq('status', 'submitted'),
      sb.from('attempts').select('id,score,max_score,submitted_at,tests(name)').eq('status', 'submitted').order('submitted_at', { ascending: false }).limit(5)]);
    const open = await sb.from('attempts').select('id,tests(name)').neq('status', 'submitted').order('updated_at', { ascending: false }).limit(3);
    const hr = new Date().getHours(), greet = hr < 12 ? 'Good morning' : hr < 17 ? 'Good afternoon' : 'Good evening', first = (ctx.profile?.display_name || '').trim().split(/\s+/)[0];
    const qc = q.count ?? 0, done = a.count ?? 0;
    main.innerHTML = head(first ? `${greet}, ${esc(first)}` : greet, 'Pick up where you left off, or start something new.', '<a class="btn" href="#/create-test">Create custom test</a>')
      + (open.data?.length ? open.data.map(x => `<div class="card resume"><div><h3>${esc(x.tests?.name)}</h3><div class="meta">Unfinished. Your timer and answers are saved.</div></div><a class="btn accent" href="#/test/${x.id}">Resume test</a></div>`).join('') : '')
      + `<div class="stats"><div class="stat"><b>${qc.toLocaleString()}</b>Published questions</div><div class="stat"><b>${p.count ?? 0}</b>Papers</div><div class="stat"><b>${done}</b>Tests completed</div></div>`
      + (qc === 0 ? empty('The question bank is empty', 'Import papers from the Admin page, or add PDFs manually. Published questions will appear here.') : '')
      + (done === 0 && qc > 0 ? `<h2>Start here</h2><div class="quick"><a href="#/questions">${ico('questions')}<div><b>Browse the question bank</b><span>Filter by subject, chapter, difficulty and exam.</span></div></a>
          <a href="#/create-test">${ico('create-test')}<div><b>Build a timed test</b><span>Pick chapters and years, then sit it like the real thing.</span></div></a>
          <a href="#/papers">${ico('papers')}<div><b>See available papers</b><span>Every paper with a link to its official source.</span></div></a></div>` : '')
      + (done > 0 ? `<h2>Recent results</h2>${last.data?.length ? `<div class="card flush"><div class="list">${last.data.map(x => `<a class="item" href="#/results/${x.id}"><span class="name">${esc(x.tests?.name)}</span><span class="when">${new Date(x.submitted_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}</span><span class="score">${x.score ?? '—'} <small>/ ${x.max_score ?? '—'}</small></span></a>`).join('')}</div></div>` : empty('No completed tests yet', 'Results appear here after you submit a test.', '<a class="btn" href="#/create-test">Create a custom test</a>')}` : '');
  },

  async questions(main) {
    const L = await lookups(); let page = 0; const PS = 15;
    main.innerHTML = head('PYQ question bank', 'Previous-year questions from JEE Main and Advanced. Open any question to see options, the solution and how others did.')
      + `<div class="card filters"><div class="grid form"><div><label for="fs">Subject</label><select id="fs"><option value="">All</option>${opt(L.subjects)}</select></div>
      <div><label for="fc">Chapter</label><select id="fc"><option value="">All</option></select></div><div><label for="fd">Difficulty</label><select id="fd"><option value="">Any</option><option>easy</option><option>medium</option><option>hard</option></select></div>
      <div><label for="fe">Exam</label><select id="fe"><option value="">Both</option>${opt(L.exams)}</select></div></div></div><div id="list">${loading('Loading questions…')}</div><div class="pager"><button class="ghost" id="pv">Previous</button><span id="pg" class="muted"></span><button class="ghost" id="nx">Next</button></div>`;
    const fill = () => { const s = $('#fs').value; $('#fc').innerHTML = '<option value="">All</option>' + opt(L.chapters.filter(c => !s || c.subject_id == s)); };
    async function load() {
      let q = sb.from('questions').select('id,statement,difficulty,question_type,answer_verified,subject_id,subjects(name),papers!inner(exam_id,exam_year,session,shift),chapters(name),topics(name)', { count: 'exact' }).eq('is_published', true);
      if ($('#fs').value) q = q.eq('subject_id', $('#fs').value); if ($('#fc').value) q = q.eq('chapter_id', $('#fc').value);
      if ($('#fd').value) q = q.eq('difficulty', $('#fd').value); if ($('#fe').value) q = q.eq('papers.exam_id', $('#fe').value);
      const { data, count, error } = await q.order('created_at', { ascending: false }).range(page * PS, page * PS + PS - 1);
      if (error) return $('#list').innerHTML = errBox(error);
      $('#pg').textContent = count ? `${page * PS + 1}–${Math.min((page + 1) * PS, count)} of ${count}` : '';
      $('#list').innerHTML = data.length ? data.map(x => `<details class="card q-item" data-id="${x.id}"><summary><div class="q-meta">${subjTag(x.subjects?.name)}<span class="tag">${esc(x.chapters?.name || 'Unclassified')}</span><span class="tag">${x.papers.exam_year}${x.papers.session ? ' ' + esc(x.papers.session) : ''}</span><span class="tag" title="Difficulty is estimated, not official">${esc(x.difficulty || 'unrated')} · estimated</span></div>
        <div class="q-snippet">${esc(x.statement)}</div></summary><div class="more muted">Loading…</div></details>`).join('')
        : empty('No questions match these filters', 'The bank only contains questions that were imported and published. Try removing a filter.');
      $$('#list details').forEach(d => d.addEventListener('toggle', async () => { if (!d.open || d.dataset.loaded) return; d.dataset.loaded = 1; const id = d.dataset.id;
        const [{ data: q1 }, { data: o }, { data: s }, { data: st }] = await Promise.all([sb.from('questions').select('statement,answer_verified,answer_source,source_status').eq('id', id).single(), sb.from('question_options').select('*').eq('question_id', id).order('sort_order'),
          sb.from('solutions').select('origin,steps').eq('question_id', id).eq('is_published', true).limit(1), sb.from('question_stats').select('*').eq('question_id', id).limit(1)]);
        d.querySelector('.more').classList.remove('muted'); d.querySelector('.more').innerHTML = `<div class="q-statement">${esc(q1.statement)}</div><div class="opts">${o.map(x => `<div class="opt plain"><span class="key">${esc(x.label)}</span><span class="txt">${esc(x.content)}</span></div>`).join('')}</div>
          <p><span class="tag">source: ${esc(String(q1.source_status).replace(/_/g, ' '))}</span><span class="tag ${q1.answer_verified ? 'ok' : 'warn'}">${q1.answer_verified ? 'answer verified' : 'answer not verified'}</span></p>
          ${s?.[0] ? `<div class="solution"><span class="tag ${s[0].origin === 'ai_generated' ? 'warn' : 'ok'}">${s[0].origin === 'ai_generated' ? 'AI-generated solution' : esc(s[0].origin)}</span><div style="white-space:pre-wrap">${esc(s[0].steps)}</div></div>` : '<p class="muted">No solution yet.</p>'}
          <p class="muted small" style="margin:.9rem 0 0">${st?.[0] ? `${st[0].percent_correct}% answered correctly (${st[0].response_count} responses). Source: ${esc(st[0].source_note || st[0].source_url)}` : 'Historical response statistics unavailable.'}</p>`; math(d); }));
      math($('#list'));
    }
    $('#fs').onchange = () => { fill(); page = 0; load(); }; ['fc', 'fd', 'fe'].forEach(i => $('#' + i).onchange = () => { page = 0; load(); });
    $('#pv').onclick = () => { if (page) { page--; load(); } }; $('#nx').onclick = () => { page++; load(); }; fill(); load();
  },

  async papers(main) {
    const { data, error } = await sb.from('papers').select('id,exam_year,session,shift,paper_number,source_status,source_url,exams(name)').eq('is_published', true).order('exam_year', { ascending: false });
    if (error) throw error;
    main.innerHTML = head('Previous year papers', 'Every published paper, with a link back to the official source where we have one.') + (data.length ? `<div class="card flush table-wrap"><table><thead><tr><th>Exam</th><th>Year</th><th>Session</th><th>Shift</th><th>Source</th></tr></thead><tbody>${data.map(p => `<tr><td>${esc(p.exams.name)}</td><td>${p.exam_year}</td><td>${esc(p.session || '')}</td><td>${esc(p.shift || '')}</td><td><span class="tag">${esc(String(p.source_status).replace(/_/g, ' '))}</span>${p.source_url ? `<a href="${esc(p.source_url)}" rel="noopener" target="_blank">View original</a>` : ''}</td></tr>`).join('')}</tbody></table></div>` : empty('No papers published yet', 'Papers show up here once they are imported and published.'));
  },

  async 'create-test'(main) {
    const L = await lookups(); const pre = JSON.parse(sessionStorage.getItem('prefill') || '{}'); sessionStorage.removeItem('prefill');
    main.innerHTML = head('Create custom test', 'Choose what to practise. Check availability first, then start when the numbers look right.') + `<div class="card">
      <div class="sec"><h3>Test details</h3><label for="nm">Test name</label><input id="nm" value="Custom test"></div>
      <div class="sec"><h3>What to include</h3><p class="hint">Leave a field empty to include everything.</p>
      <div class="grid form"><div><label for="ex">Exam</label><select id="ex"><option value="">Both</option>${L.exams.map(e => `<option value="${e.code}">${esc(e.name)}</option>`).join('')}</select></div>
      <div><label for="su">Subject</label><select id="su"><option value="">All subjects</option>${L.subjects.map(e => `<option value="${e.code}" data-id="${e.id}">${esc(e.name)}</option>`).join('')}</select></div>
      <div><label for="ty">Question type</label><select id="ty"><option value="">Any</option><option value="single_mcq">Single correct</option><option value="multi_mcq">Multiple correct</option><option value="numerical">Numerical</option><option value="integer">Integer</option></select></div>
      <div><label for="yf">Year from</label><input id="yf" type="number" min="1990" max="2100" placeholder="e.g. 2015"></div><div><label for="yt">Year to</label><input id="yt" type="number" min="1990" max="2100" placeholder="e.g. 2024"></div>
      <div><label for="af">Previous attempts</label><select id="af"><option value="any">Include everything</option><option value="exclude_attempted">Exclude attempted</option><option value="only_incorrect">Only previously incorrect</option><option value="only_unattempted">Only previously unattempted</option></select></div></div>
      <div class="grid two form"><div><label for="ch">Chapters</label><select id="ch" multiple size="6"></select></div><div><label for="tp">Topics</label><select id="tp" multiple size="6"></select></div></div></div>
      <div class="sec"><h3>Size and difficulty</h3><div class="grid form"><div><label for="df">Difficulty</label><select id="df"><option value="">Mixed</option><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option><option value="custom">Custom split</option></select></div>
      <div id="cnt"><label for="n">Number of questions</label><input id="n" type="number" min="1" value="20"></div></div>
      <div id="dist" class="grid form" hidden><div><label for="de">Easy</label><input id="de" type="number" min="0" value="5"></div><div><label for="dm">Medium</label><input id="dm" type="number" min="0" value="10"></div><div><label for="dh">Hard</label><input id="dh" type="number" min="0" value="5"></div></div></div>
      <div class="sec"><h3>Timing</h3><div class="grid form"><div><label for="du">Duration in minutes</label><input id="du" type="number" min="1" placeholder="Recommended"></div></div><p class="hint">Optional. Leave empty to use the recommended duration.</p></div>
      <div id="out"></div><div class="row sec"><button class="ghost" id="chk">Check availability</button><button class="accent" id="mk">Create and start</button></div></div>`;
    if (pre.attempt_filter) $('#af').value = pre.attempt_filter;
    const fill = () => { const sid = $('#su').selectedOptions[0]?.dataset.id; const chs = L.chapters.filter(c => !sid || c.subject_id == sid);
      $('#ch').innerHTML = opt(chs); const sel = [...$('#ch').selectedOptions].map(o => +o.value); fillTopics(chs); };
    const fillTopics = chs => { const ids = [...$('#ch').selectedOptions].map(o => +o.value); const pool = ids.length ? ids : chs.map(c => c.id); $('#tp').innerHTML = opt(L.topics.filter(t => pool.includes(t.chapter_id))); };
    $('#su').onchange = fill; $('#ch').onchange = () => fillTopics(L.chapters); $('#df').onchange = () => { const c = $('#df').value === 'custom'; $('#dist').hidden = !c; $('#cnt').hidden = c; }; fill();
    const config = () => { const v = id => $('#' + id).value, sel = id => [...$('#' + id).selectedOptions].map(o => +o.value); const c = {};
      if (v('ex')) c.exams = [v('ex')]; if (v('su')) c.subjects = [v('su')]; if (v('ty')) c.question_types = [v('ty')];
      if (sel('ch').length) c.chapter_ids = sel('ch'); if (sel('tp').length) c.topic_ids = sel('tp');
      if (v('yf')) c.year_from = +v('yf'); if (v('yt')) c.year_to = +v('yt'); c.attempt_filter = v('af');
      if (v('df') === 'custom') c.distribution = { easy: +v('de'), medium: +v('dm'), hard: +v('dh') }; else { c.count = +v('n'); if (v('df')) c.difficulties = [v('df')]; }
      if (v('du')) c.duration_minutes = +v('du'); return c; };
    $('#chk').onclick = async () => { const { data, error } = await sb.rpc('create_test', { p_name: $('#nm').value, p_config: config(), p_dry_run: true });
      if (error) return $('#out').innerHTML = errBox(error); if (!data.ok) return $('#out').innerHTML = `<div class="msg err">${esc(data.message)}</div>`;
      const d = data.distribution; $('#out').innerHTML = `<div class="msg good">${data.selected_count} questions available. Easy ${d.easy} · Medium ${d.medium} · Hard ${d.hard}.<br>Recommended duration: ${fmt(data.recommended_seconds)} (practice estimate, not the official exam limit). About ${data.seconds_per_question}s per question.</div>`; };
    $('#mk').onclick = async () => { $('#mk').disabled = true; const { data, error } = await sb.rpc('create_test', { p_name: $('#nm').value, p_config: config(), p_dry_run: false });
      if (error) { $('#mk').disabled = false; return $('#out').innerHTML = errBox(error); }
      try { location.hash = '#/test/' + await startAttempt(data.test_id); } catch (e) { $('#out').innerHTML = errBox(e); $('#mk').disabled = false; } };
  },

  async tests(main) {
    const { data, error } = await sb.from('tests').select('id,name,question_count,duration_seconds,created_at,attempts(id,attempt_number,status,score,max_score,submitted_at)').order('created_at', { ascending: false });
    if (error) throw error;
    main.innerHTML = head('My tests', 'Every test you have created, with all of its attempts.', '<a class="btn" href="#/create-test">Create custom test</a>') + (data.length ? data.map(t => `<div class="card flush"><div class="card-head"><div><h3>${esc(t.name)}</h3><span class="muted small">${t.question_count} questions · ${fmt(t.duration_seconds)}</span></div><button class="ghost sm" data-t="${t.id}">Start new attempt</button></div>
      <ul class="list">${t.attempts.sort((a, b) => a.attempt_number - b.attempt_number).map(a => `<li><span class="name">Attempt ${a.attempt_number}</span>${a.status === 'submitted' ? `<span class="tag ok">Submitted</span><span class="score">${a.score ?? '—'} <small>/ ${a.max_score ?? '—'}</small></span><a href="#/results/${a.id}">View results</a>` : `<span class="tag warn">In progress</span><a class="btn accent sm" href="#/test/${a.id}">Resume</a>`}</li>`).join('') || '<li class="muted">No attempts yet.</li>'}</ul></div>`).join('') : empty('No tests yet', 'Create a custom test to start practising.', '<a class="btn" href="#/create-test">Create custom test</a>'));
    $$('button[data-t]', main).forEach(b => b.onclick = async () => { try { location.hash = '#/test/' + await startAttempt(b.dataset.t); } catch (e) { toast(e.message); } });
  },

  async analytics(main) {
    const rows = await submittedData(); if (!rows) return main.innerHTML = head('Performance analytics', 'How your accuracy, marks and speed change over time.') + empty('No data yet', 'Complete a test to see analytics.', '<a class="btn" href="#/create-test">Create custom test</a>', 'analytics');
    const byDay = {}; for (const r of rows) { const d = r.attempts.submitted_at.slice(0, 10); const g = (byDay[d] ||= { c: 0, w: 0, m: 0, t: 0, n: 0 }); g.n++; g.t += +r.active_seconds || 0; g.m += +r.marks_awarded || 0; if (r.is_correct === true) g.c++; if (r.is_correct === false) g.w++; }
    const days = Object.keys(byDay).sort(); const agg = k => { const m = {}; for (const r of rows) { const n = k(r) || 'Unclassified'; const g = (m[n] ||= { c: 0, w: 0, t: 0, n: 0 }); g.n++; g.t += +r.active_seconds || 0; if (r.is_correct === true) g.c++; if (r.is_correct === false) g.w++; } return m; };
    const acc = g => g.c + g.w ? Math.round(100 * g.c / (g.c + g.w)) : 0;
    main.innerHTML = head('Performance analytics', 'How your accuracy, marks and speed change over time.') + `<div class="grid two"><div class="card chart-card"><h3>Accuracy over time (%)</h3><canvas id="c1"></canvas></div><div class="card chart-card"><h3>Marks over time</h3><canvas id="c2"></canvas></div>
      <div class="card chart-card"><h3>Accuracy by subject (%)</h3><canvas id="c3"></canvas></div><div class="card chart-card"><h3>Accuracy by difficulty (%)</h3><canvas id="c4"></canvas></div><div class="card chart-card"><h3>Average seconds per question</h3><canvas id="c5"></canvas></div></div>
      <h2>Chapters</h2><div class="card flush table-wrap"><table><thead><tr><th>Chapter</th><th class="num">Attempted</th><th>Accuracy</th><th class="num">Avg time</th></tr></thead><tbody>${Object.entries(agg(r => r.questions.chapters?.name)).map(([k, g]) => `<tr><td>${esc(k)}</td><td class="num">${g.c + g.w}/${g.n}</td><td>${bar(g.c + g.w ? acc(g) : null)}</td><td class="num">${fmt(g.t / g.n)}</td></tr>`).join('')}</tbody></table></div>`;
    const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    const chart = (id, type, labels, data, label) => { if (!window.Chart) return; const ac = css('--accent-solid'), grid = css('--line'), tx = css('--muted');
      new window.Chart($('#' + id), { type, data: { labels, datasets: [{ label, data, borderColor: ac, backgroundColor: type === 'bar' ? ac + 'cc' : ac + '1f', fill: type === 'line', tension: .3, borderWidth: 2, borderRadius: 6, pointRadius: 3, pointBackgroundColor: ac }] },
        options: { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { color: tx } }, y: { beginAtZero: true, grid: { color: grid }, ticks: { color: tx } } } } }); };
    const sub = agg(r => r.questions.subjects?.name), dif = agg(r => r.questions.difficulty);
    chart('c1', 'line', days, days.map(d => acc(byDay[d])), 'Accuracy'); chart('c2', 'line', days, days.map(d => byDay[d].m), 'Marks');
    chart('c3', 'bar', Object.keys(sub), Object.values(sub).map(acc), 'Accuracy'); chart('c4', 'bar', Object.keys(dif), Object.values(dif).map(acc), 'Accuracy');
    chart('c5', 'line', days, days.map(d => Math.round(byDay[d].t / byDay[d].n)), 'Seconds');
  },

  async weak(main) {
    const rows = await submittedData(); main.innerHTML = head('Weak chapters', 'Topics where your results show a pattern, with the evidence behind each flag.');
    if (!rows) return main.innerHTML += empty('Not enough data yet', 'Complete at least two tests to see weakness analysis.', '<a class="btn" href="#/create-test">Create custom test</a>', 'weak');
    const MIN_Q = 5, MIN_TESTS = 2, avgAll = rows.reduce((s, r) => s + (+r.active_seconds || 0), 0) / rows.length;
    const topics = {}; for (const r of rows) { const k = r.questions.topics?.name || r.questions.chapters?.name; if (!k) continue; const g = (topics[k] ||= { c: 0, w: 0, t: 0, n: 0, per: {} });
      g.n++; g.t += +r.active_seconds || 0; const p = (g.per[r.attempt_id] ||= { c: 0, w: 0 }); if (r.is_correct === true) { g.c++; p.c++; } if (r.is_correct === false) { g.w++; p.w++; } }
    const out = [], thin = [];
    for (const [k, g] of Object.entries(topics)) { const att = g.c + g.w, tests = Object.keys(g.per).length; if (att < MIN_Q || tests < MIN_TESTS) { thin.push(k); continue; }
      const a = g.c / att, why = [], per = Object.values(g.per).filter(p => p.c + p.w).map(p => p.c / (p.c + p.w));
      if (a <= 0.4) why.push(['Conceptual gap (tentative)', `accuracy ${Math.round(a * 100)}% over ${att} attempted questions in ${tests} tests`]);
      if (g.t / g.n > 1.5 * avgAll && a < 0.6) why.push(['Time management', `average ${fmt(g.t / g.n)} per question vs ${fmt(avgAll)} overall`]);
      if (per.length >= 2 && Math.max(...per) - Math.min(...per) >= 0.4) why.push(['Inconsistent performance', `accuracy ranged ${Math.round(Math.min(...per) * 100)}%–${Math.round(Math.max(...per) * 100)}% across tests`]);
      if (why.length) out.push([k, why]); }
    main.innerHTML += out.length ? out.map(([k, w]) => `<div class="card weak"><h3>${esc(k)}</h3>${w.map(([t, e]) => `<div class="why"><span class="tag warn">${t}</span><span>${esc(e)}</span></div>`).join('')}</div>`).join('') : empty('No topic meets the evidence threshold yet', 'Keep practising. A topic is flagged only when there is enough data to judge it fairly.', '', 'check');
    main.innerHTML += `<p class="muted small" style="margin-top:1.2rem;max-width:72ch">A topic is only flagged with at least ${MIN_Q} attempted questions across ${MIN_TESTS} tests. ${thin.length} topics have too little data to judge. Formula-recall, calculation and interpretation mistakes cannot be told apart from results alone; they need mistake tags, which are not recorded yet.</p>`;
  },

  async settings(main) {
    const s = ctx.settings || {};
    let reg = ''; if (ctx.profile?.role === 'admin') { const { data } = await sb.from('app_settings').select('value').eq('key', 'registration_mode').single(); reg = data?.value; }
    main.innerHTML = head('Settings', 'Your profile, theme and practice defaults.') + `<div class="card"><div class="sec"><h3>Profile</h3><div class="grid form"><div><label for="dn">Display name</label><input id="dn" value="${esc(ctx.profile?.display_name)}"></div><div><label for="th">Theme</label><select id="th">${['system', 'light', 'dark'].map(x => `<option ${s.theme === x ? 'selected' : ''}>${x}</option>`).join('')}</select></div></div></div>
      <div class="sec"><h3>Time estimates</h3><p class="hint">Minutes per question. These set the recommended practice duration only. They are not official JEE time limits.</p><div class="grid form"><div><label for="te">Easy</label><input id="te" type="number" step="0.1" min="0.1" value="${s.time_easy ?? 1.5}"></div><div><label for="tm">Medium</label><input id="tm" type="number" step="0.1" min="0.1" value="${s.time_medium ?? 2.5}"></div><div><label for="tx">Hard</label><input id="tx" type="number" step="0.1" min="0.1" value="${s.time_hard ?? 4}"></div></div></div>
      <div class="sec"><h3>AI study coach</h3><div class="grid form"><div><label for="ap">Provider</label><select id="ap">${['gemini', 'openrouter', 'openai_compatible'].map(x => `<option ${s.ai_provider === x ? 'selected' : ''}>${x}</option>`).join('')}</select></div></div></div>
      <div class="row sec"><button id="sv">Save settings</button></div></div>
      <div class="card"><div class="sec"><h3>Change password</h3><div class="grid form"><div><label for="np">New password</label><input id="np" type="password" minlength="8" autocomplete="new-password"></div></div></div><div class="row sec"><button class="ghost" id="cp">Update password</button></div></div>`;
    $('#sv').onclick = async () => { const row = { user_id: ctx.user.id, theme: $('#th').value, time_easy: +$('#te').value, time_medium: +$('#tm').value, time_hard: +$('#tx').value, ai_provider: $('#ap').value };
      const [a, b] = await Promise.all([sb.from('user_settings').upsert(row), sb.from('profiles').update({ display_name: $('#dn').value.trim() }).eq('id', ctx.user.id)]);
      if (a.error || b.error) return toast((a.error || b.error).message); Object.assign(ctx.settings ||= {}, row); ctx.profile.display_name = $('#dn').value.trim(); applyTheme(row.theme); toast('Settings saved'); };
    $('#cp').onclick = async () => { const { error } = await sb.auth.updateUser({ password: $('#np').value }); toast(error ? error.message : 'Password updated'); };
  },

  async admin(main) {
    if (ctx.profile?.role !== 'admin') return main.innerHTML = head('Admin') + '<div class="msg err">Administrators only.</div>';
    const g = async k => (await sb.from('app_settings').select('value').eq('key', k).single()).data?.value;
    const [mode, paused, inv, review, runs, jobs, logs, dups] = await Promise.all([g('registration_mode'), g('import_paused'), sb.from('invited_emails').select('email'),
      sb.from('questions').select('id,statement,classification_confidence,answer_verified').or('needs_review.eq.true,answer_verified.eq.false').limit(20),
      sb.from('import_runs').select('*').order('created_at', { ascending: false }).limit(10), sb.from('import_jobs').select('id,status,last_error,source_documents:document_id(source_url)').eq('status', 'failed').limit(20),
      sb.from('import_logs').select('level,message,created_at').order('created_at', { ascending: false }).limit(25), sb.from('duplicate_candidates').select('id,similarity,status').eq('status', 'pending').limit(20)]);
    main.innerHTML = head('Admin', 'Access, imports and review queues.') + `<div class="card"><div class="card-head"><h3>Access</h3></div><div class="row"><select id="rg" style="width:auto;min-width:260px"><option value="private" ${mode === 'private' ? 'selected' : ''}>Private (invited emails only)</option><option value="public" ${mode === 'public' ? 'selected' : ''}>Public registration</option></select><button id="rgs">Save</button></div>
      <label for="ie">Invite an email address</label><div class="row"><input id="ie" type="email" style="max-width:320px" placeholder="student@example.com"><button class="ghost" id="ia">Invite</button></div><p class="muted small" style="margin:.8rem 0 0">Invited: ${(inv.data || []).map(x => esc(x.email)).join(', ') || 'none'}</p></div>
      <div class="card"><div class="card-head"><h3>Import engine</h3></div><p class="muted">Imports run in GitHub Actions on a schedule. Buttons here queue or pause work; they do not run Python in your browser.</p>
      <div class="row"><button id="chk">Check sources</button><button id="go">Start import</button><button class="ghost" id="pz">${paused ? 'Resume imports' : 'Pause imports'}</button><button class="ghost" id="rt">Retry failed documents (${jobs.data?.length || 0})</button></div>
      <div class="sec"><h3>History</h3>${(runs.data || []).map(r => `<div>${new Date(r.created_at).toLocaleString()} · ${esc(r.trigger)} · <span class="tag">${esc(r.status)}</span></div>`).join('') || '<p class="muted">No runs yet.</p>'}</div>
      <div class="sec"><h3>Failed documents</h3>${(jobs.data || []).map(j => `<div>${esc(j.source_documents?.source_url || j.id)}: <span class="bad">${esc(j.last_error || '')}</span></div>`).join('') || '<p class="muted">None.</p>'}</div>
      <div class="sec"><h3>Error log</h3>${(logs.data || []).map(l => `<div class="${l.level === 'error' ? 'bad' : ''}">${esc(l.level)} · ${esc(l.message)}</div>`).join('') || '<p class="muted">Empty.</p>'}</div>
      <div class="sec"><h3>Possible duplicates</h3><p class="muted">${dups.data?.length || 0} pending review.</p></div></div>
      <div class="card"><div class="card-head"><h3>Questions needing review (${review.data?.length || 0})</h3></div>${(review.data || []).map(q => `<div class="row between" style="padding:.5rem 0;border-top:1px solid var(--line)"><span style="flex:1;min-width:200px">${esc(q.statement.slice(0, 110))}…</span><button class="ghost sm" data-v="${q.id}">Verify and publish</button></div>`).join('')}
      <p class="muted small" style="margin:.8rem 0 0">Check the answer against the official key before verifying; verifying also publishes the question. Chapter and difficulty corrections can be made in the Supabase table editor for now.</p></div>`;
    const set = async (k, v) => { const { error } = await sb.from('app_settings').upsert({ key: k, value: v, updated_by: ctx.user.id }); toast(error ? error.message : 'Saved'); };
    $('#rgs').onclick = () => set('registration_mode', $('#rg').value); $('#pz').onclick = async () => { await set('import_paused', !paused); route(); };
    $('#ia').onclick = async () => { const { error } = await sb.from('invited_emails').insert({ email: $('#ie').value.trim().toLowerCase(), invited_by: ctx.user.id }); toast(error ? error.message : 'Invited'); if (!error) route(); };
    const queue = async () => { const { error } = await sb.from('import_runs').insert({ trigger: 'manual', status: 'queued', requested_by: ctx.user.id }); toast(error ? error.message : 'Queued. The next scheduled workflow run will pick it up, or start the Import workflow from GitHub.'); if (!error) route(); };
    $('#chk').onclick = queue; $('#go').onclick = queue;
    $('#rt').onclick = async () => { const { error } = await sb.from('import_jobs').update({ status: 'pending', last_error: null }).eq('status', 'failed'); toast(error ? error.message : 'Failed documents re-queued'); route(); };
    $$('button[data-v]', main).forEach(b => b.onclick = async () => {
      const a = prompt('Enter the correct answer from the OFFICIAL answer key (for example B, or A,C, or 12.5). Cancel to leave it unverified.'); if (!a || !a.trim()) return;
      const t = a.trim(), correct = t !== '' && !isNaN(Number(t)) ? Number(t) : t.toUpperCase().split(/[\s,]+/).filter(Boolean);
      const { error } = await sb.from('questions').update({ correct_answer: correct, answer_source: 'official', answer_verified: true, answer_verified_by: ctx.user.id, answer_verified_at: new Date().toISOString(), needs_review: false, is_published: true }).eq('id', b.dataset.v);
      if (!error) { const { data: qq } = await sb.from('questions').select('paper_id').eq('id', b.dataset.v).single(); if (qq) await sb.from('papers').update({ is_published: true }).eq('id', qq.paper_id); }
      toast(error ? error.message : 'Verified and published'); route(); });
  },
};

async function submittedData() {
  const { data, error } = await sb.from('attempt_responses').select('attempt_id,question_id,active_seconds,is_correct,marks_awarded,attempts!inner(status,submitted_at),questions(difficulty,subjects(name),chapters(name),topics(name))').eq('attempts.status', 'submitted').limit(5000);
  if (error) throw error; return data.length ? data : null;
}

async function coach(main, attemptId) {
  const { data: reps } = await sb.from('ai_reports').select('id,attempt_id,provider,created_at,report_markdown').order('created_at', { ascending: false }).limit(10);
  const { data: atts } = await sb.from('attempts').select('id,submitted_at,tests(name)').eq('status', 'submitted').order('submitted_at', { ascending: false }).limit(20);
  main.innerHTML = head('AI study coach', 'A written review of one completed test, based only on your recorded results.') + `<div class="card"><label for="at">Completed attempt</label><select id="at">${(atts || []).map(a => `<option value="${a.id}" ${a.id === attemptId ? 'selected' : ''}>${esc(a.tests?.name)} · ${new Date(a.submitted_at).toLocaleDateString()}</option>`).join('')}</select>
    <p style="margin:1rem 0 0"><button class="accent" id="gen" ${atts?.length ? '' : 'disabled'}>Generate report</button></p><div id="o" aria-live="polite"></div><p class="muted small" style="margin:1rem 0 0">Reports run in a Supabase Edge Function, so the AI key stays on the server.</p></div>
    <h2>Saved reports</h2>${(reps || []).map(r => `<details class="card q-item"><summary><div class="q-meta"><span class="tag">${new Date(r.created_at).toLocaleString()}</span><span class="tag">${esc(r.provider)}</span></div></summary><div class="more prose" style="white-space:pre-wrap;padding-top:1rem">${esc(r.report_markdown)}</div></details>`).join('') || empty('No saved reports yet', 'Generate a report above and it will be kept here.', '', 'coach')}`;
  $('#gen').onclick = async () => { $('#gen').disabled = true; $('#o').innerHTML = loading('Generating your report…');
    const { data, error } = await sb.functions.invoke('ai-coach', { body: { attempt_id: $('#at').value } });
    $('#gen').disabled = false; if (error) return $('#o').innerHTML = errBox(error.message + ' (is the ai-coach function deployed and an AI key set? See the README.)');
    $('#o').innerHTML = `<div class="solution prose" style="white-space:pre-wrap;margin-top:1rem">${esc(data.report)}</div>`; };
}

window.addEventListener('hashchange', route); route();
