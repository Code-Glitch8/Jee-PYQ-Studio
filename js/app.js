import { sb, ctx, esc, $, $$, fmt, math, toast, errBox, applyTheme, startAttempt } from './lib.js';
import { examView, resultsView } from './exam.js';

const NAV = [['dashboard', 'Dashboard'], ['questions', 'PYQ Question Bank'], ['papers', 'Previous Year Papers'], ['create-test', 'Create Custom Test'],
  ['tests', 'My Tests'], ['analytics', 'Performance Analytics'], ['weak', 'Weak Chapters'], ['coach', 'AI Study Coach'], ['settings', 'Settings']];
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
  const nav = [...NAV, ...(ctx.profile?.role === 'admin' ? [['admin', 'Admin']] : [])];
  app.innerHTML = `<div class="layout"><nav class="side" id="side"><div class="brand">JEE PYQ Studio</div>
    ${nav.map(([k, l]) => `<a href="#/${k}" class="${k === name ? 'on' : ''}">${l}</a>`).join('')}
    <div class="account">${esc(ctx.profile?.display_name || ctx.user.email)}<br><span class="muted">${esc(ctx.profile?.role || '')}</span><br><a href="#/settings">Profile and settings</a><br><a href="#" id="out">Sign out</a></div></nav>
    <div><button class="ghost menu-btn" id="menu">Menu</button><main id="main"></main></div></div>`;
  $('#menu').onclick = () => $('#side').classList.toggle('open');
  $('#side').onclick = e => { if (e.target.tagName === 'A') $('#side').classList.remove('open'); };
  $('#out').onclick = async e => { e.preventDefault(); await sb.auth.signOut(); ctx.user = null; location.hash = '#/'; route(); };
  const main = $('#main'), v = VIEWS[name];
  if (name === 'results') return resultsView(main, arg);
  if (name === 'coach') return coach(main, arg);
  try { await (v || VIEWS.dashboard)(main, arg); } catch (e) { main.innerHTML = '<h1>Something went wrong</h1>' + errBox(e); }
}

function authView() {
  app.innerHTML = `<div class="auth"><h1>JEE PYQ Studio</h1><div class="card"><div class="tabs" id="mode"><button class="on" data-m="in">Sign in</button><button data-m="up">Create account</button><button data-m="reset">Forgot password</button></div>
    <label for="em">Email</label><input id="em" type="email" autocomplete="email"><div id="pwrow"><label for="pw">Password</label><input id="pw" type="password" minlength="8" autocomplete="current-password"></div>
    <div id="nmrow" hidden><label for="nm">Display name</label><input id="nm"></div><p><button id="go">Sign in</button></p><div id="amsg"></div></div></div>`;
  let mode = 'in'; const msg = (t, c = 'err') => $('#amsg').innerHTML = `<div class="msg ${c}">${esc(t)}</div>`;
  $$('#mode button').forEach(b => b.onclick = () => { mode = b.dataset.m; $$('#mode button').forEach(x => x.classList.toggle('on', x === b));
    $('#pwrow').hidden = mode === 'reset'; $('#nmrow').hidden = mode !== 'up'; $('#go').textContent = { in: 'Sign in', up: 'Create account', reset: 'Send reset link' }[mode]; });
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
    main.innerHTML = `<h1>Dashboard</h1><div class="grid"><div class="card stat"><b>${q.count ?? 0}</b>Published questions</div><div class="card stat"><b>${p.count ?? 0}</b>Papers</div><div class="card stat"><b>${a.count ?? 0}</b>Tests completed</div></div>
      ${(q.count ?? 0) === 0 ? '<div class="msg">The question bank is empty. Import papers from the Admin page, or add PDFs manually, then published questions will appear here.</div>' : ''}
      ${open.data?.length ? `<h2>Unfinished tests</h2>${open.data.map(x => `<div class="card"><a href="#/test/${x.id}">Resume ${esc(x.tests?.name)}</a></div>`).join('')}` : ''}
      <h2>Recent results</h2>${last.data?.length ? last.data.map(x => `<div class="card"><a href="#/results/${x.id}">${esc(x.tests?.name)}</a> · ${x.score ?? '—'} / ${x.max_score ?? '—'} · ${new Date(x.submitted_at).toLocaleDateString()}</div>`).join('') : '<p class="muted">No completed tests yet. <a href="#/create-test">Create a custom test</a>.</p>'}`;
  },

  async questions(main) {
    const L = await lookups(); let page = 0; const PS = 15;
    main.innerHTML = `<h1>PYQ Question Bank</h1><div class="card"><div class="grid"><div><label>Subject</label><select id="fs"><option value="">All</option>${opt(L.subjects)}</select></div>
      <div><label>Chapter</label><select id="fc"><option value="">All</option></select></div><div><label>Difficulty</label><select id="fd"><option value="">Any</option><option>easy</option><option>medium</option><option>hard</option></select></div>
      <div><label>Exam</label><select id="fe"><option value="">Both</option>${opt(L.exams)}</select></div></div></div><div id="list"></div><div class="row"><button class="ghost" id="pv">Previous</button><span id="pg" class="muted"></span><button class="ghost" id="nx">Next</button></div>`;
    const fill = () => { const s = $('#fs').value; $('#fc').innerHTML = '<option value="">All</option>' + opt(L.chapters.filter(c => !s || c.subject_id == s)); };
    async function load() {
      let q = sb.from('questions').select('id,statement,difficulty,question_type,answer_verified,subject_id,papers!inner(exam_id,exam_year,session,shift),chapters(name),topics(name)', { count: 'exact' }).eq('is_published', true);
      if ($('#fs').value) q = q.eq('subject_id', $('#fs').value); if ($('#fc').value) q = q.eq('chapter_id', $('#fc').value);
      if ($('#fd').value) q = q.eq('difficulty', $('#fd').value); if ($('#fe').value) q = q.eq('papers.exam_id', $('#fe').value);
      const { data, count, error } = await q.order('created_at', { ascending: false }).range(page * PS, page * PS + PS - 1);
      if (error) return $('#list').innerHTML = errBox(error);
      $('#pg').textContent = count ? `${page * PS + 1}–${Math.min((page + 1) * PS, count)} of ${count}` : '';
      $('#list').innerHTML = data.length ? data.map(x => `<details class="card" data-id="${x.id}"><summary>${esc(x.statement.slice(0, 140))}${x.statement.length > 140 ? '…' : ''}
        <div class="muted"><span class="tag">${x.papers.exam_year} ${esc(x.papers.session || '')}</span><span class="tag">${esc(x.chapters?.name || 'Unclassified')}</span><span class="tag">${esc(x.difficulty || 'unrated')} (estimated)</span></div></summary><div class="more muted">Loading…</div></details>`).join('')
        : '<div class="msg">No questions match these filters. The bank only contains questions that were imported and published.</div>';
      $$('#list details').forEach(d => d.addEventListener('toggle', async () => { if (!d.open || d.dataset.loaded) return; d.dataset.loaded = 1; const id = d.dataset.id;
        const [{ data: q1 }, { data: o }, { data: s }, { data: st }] = await Promise.all([sb.from('questions').select('statement,answer_verified,answer_source,source_status').eq('id', id).single(), sb.from('question_options').select('*').eq('question_id', id).order('sort_order'),
          sb.from('solutions').select('origin,steps').eq('question_id', id).eq('is_published', true).limit(1), sb.from('question_stats').select('*').eq('question_id', id).limit(1)]);
        d.querySelector('.more').innerHTML = `<div class="q-statement">${esc(q1.statement)}</div>${o.map(x => `<div><b>${esc(x.label)}.</b> ${esc(x.content)}</div>`).join('')}
          <p><span class="tag">source: ${esc(q1.source_status)}</span><span class="tag">${q1.answer_verified ? 'answer verified' : 'answer not verified'}</span></p>
          ${s?.[0] ? `<p><span class="tag">${s[0].origin === 'ai_generated' ? 'AI-generated solution' : esc(s[0].origin)}</span></p><div style="white-space:pre-wrap">${esc(s[0].steps)}</div>` : '<p class="muted">No solution yet.</p>'}
          <p class="muted">${st?.[0] ? `${st[0].percent_correct}% answered correctly (${st[0].response_count} responses). Source: ${esc(st[0].source_note || st[0].source_url)}` : 'Historical response statistics unavailable.'}</p>`; math(d); }));
      math($('#list'));
    }
    $('#fs').onchange = () => { fill(); page = 0; load(); }; ['fc', 'fd', 'fe'].forEach(i => $('#' + i).onchange = () => { page = 0; load(); });
    $('#pv').onclick = () => { if (page) { page--; load(); } }; $('#nx').onclick = () => { page++; load(); }; fill(); load();
  },

  async papers(main) {
    const { data, error } = await sb.from('papers').select('id,exam_year,session,shift,paper_number,source_status,source_url,exams(name)').eq('is_published', true).order('exam_year', { ascending: false });
    if (error) throw error;
    main.innerHTML = `<h1>Previous Year Papers</h1>` + (data.length ? `<div class="card" style="overflow-x:auto"><table><tr><th>Exam</th><th>Year</th><th>Session</th><th>Shift</th><th>Source status</th></tr>${data.map(p => `<tr><td>${esc(p.exams.name)}</td><td>${p.exam_year}</td><td>${esc(p.session || '')}</td><td>${esc(p.shift || '')}</td><td><span class="tag">${esc(p.source_status)}</span>${p.source_url ? `<a href="${esc(p.source_url)}" rel="noopener" target="_blank">original</a>` : ''}</td></tr>`).join('')}</table></div>` : '<div class="msg">No papers have been published yet.</div>');
  },

  async 'create-test'(main) {
    const L = await lookups(); const pre = JSON.parse(sessionStorage.getItem('prefill') || '{}'); sessionStorage.removeItem('prefill');
    main.innerHTML = `<h1>Create Custom Test</h1><div class="card"><label>Test name</label><input id="nm" value="Custom test">
      <div class="grid"><div><label>Exam</label><select id="ex"><option value="">Both</option>${L.exams.map(e => `<option value="${e.code}">${esc(e.name)}</option>`).join('')}</select></div>
      <div><label>Subject</label><select id="su"><option value="">All subjects</option>${L.subjects.map(e => `<option value="${e.code}" data-id="${e.id}">${esc(e.name)}</option>`).join('')}</select></div>
      <div><label>Question type</label><select id="ty"><option value="">Any</option><option value="single_mcq">Single correct</option><option value="multi_mcq">Multiple correct</option><option value="numerical">Numerical</option><option value="integer">Integer</option></select></div>
      <div><label>Year from</label><input id="yf" type="number" min="1990" max="2100"></div><div><label>Year to</label><input id="yt" type="number" min="1990" max="2100"></div>
      <div><label>Previous attempts</label><select id="af"><option value="any">Include everything</option><option value="exclude_attempted">Exclude attempted</option><option value="only_incorrect">Only previously incorrect</option><option value="only_unattempted">Only previously unattempted</option></select></div></div>
      <label>Chapters (leave empty for all)</label><select id="ch" multiple size="6"></select><label>Topics (leave empty for all)</label><select id="tp" multiple size="6"></select>
      <label>Difficulty</label><select id="df"><option value="">Mixed</option><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option><option value="custom">Custom split</option></select>
      <div id="cnt"><label>Number of questions</label><input id="n" type="number" min="1" value="20"></div>
      <div id="dist" class="grid" hidden><div><label>Easy</label><input id="de" type="number" min="0" value="5"></div><div><label>Medium</label><input id="dm" type="number" min="0" value="10"></div><div><label>Hard</label><input id="dh" type="number" min="0" value="5"></div></div>
      <label>Duration override in minutes (optional; the recommendation is used if empty)</label><input id="du" type="number" min="1">
      <p class="row"><button class="ghost" id="chk">Check availability</button><button id="mk">Create and start</button></p><div id="out"></div></div>`;
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
    main.innerHTML = `<h1>My Tests</h1>` + (data.length ? data.map(t => `<div class="card"><b>${esc(t.name)}</b> <span class="muted">${t.question_count} questions · ${fmt(t.duration_seconds)}</span>
      ${t.attempts.sort((a, b) => a.attempt_number - b.attempt_number).map(a => `<div>Attempt ${a.attempt_number}: ${a.status === 'submitted' ? `<a href="#/results/${a.id}">${a.score ?? '—'} / ${a.max_score ?? '—'}</a>` : `<a href="#/test/${a.id}">Resume</a>`}</div>`).join('')}
      <p><button class="ghost" data-t="${t.id}">Start new attempt</button></p></div>`).join('') : '<div class="msg">No tests yet. <a href="#/create-test">Create one</a>.</div>');
    $$('button[data-t]', main).forEach(b => b.onclick = async () => { try { location.hash = '#/test/' + await startAttempt(b.dataset.t); } catch (e) { toast(e.message); } });
  },

  async analytics(main) {
    const rows = await submittedData(); if (!rows) return main.innerHTML = '<h1>Performance Analytics</h1><div class="msg">Complete a test to see analytics.</div>';
    const byDay = {}; for (const r of rows) { const d = r.attempts.submitted_at.slice(0, 10); const g = (byDay[d] ||= { c: 0, w: 0, m: 0, t: 0, n: 0 }); g.n++; g.t += +r.active_seconds || 0; g.m += +r.marks_awarded || 0; if (r.is_correct === true) g.c++; if (r.is_correct === false) g.w++; }
    const days = Object.keys(byDay).sort(); const agg = k => { const m = {}; for (const r of rows) { const n = k(r) || 'Unclassified'; const g = (m[n] ||= { c: 0, w: 0, t: 0, n: 0 }); g.n++; g.t += +r.active_seconds || 0; if (r.is_correct === true) g.c++; if (r.is_correct === false) g.w++; } return m; };
    const acc = g => g.c + g.w ? Math.round(100 * g.c / (g.c + g.w)) : 0;
    main.innerHTML = `<h1>Performance Analytics</h1><div class="grid"><div class="card"><b>Accuracy over time (%)</b><canvas id="c1"></canvas></div><div class="card"><b>Marks over time</b><canvas id="c2"></canvas></div>
      <div class="card"><b>Accuracy by subject (%)</b><canvas id="c3"></canvas></div><div class="card"><b>Accuracy by difficulty (%)</b><canvas id="c4"></canvas></div><div class="card"><b>Average seconds per question</b><canvas id="c5"></canvas></div></div>
      <h2>Chapters</h2><div class="card" style="overflow-x:auto"><table><tr><th>Chapter</th><th>Attempted</th><th>Accuracy</th><th>Avg time</th></tr>${Object.entries(agg(r => r.questions.chapters?.name)).map(([k, g]) => `<tr><td>${esc(k)}</td><td>${g.c + g.w}/${g.n}</td><td>${acc(g)}%</td><td>${fmt(g.t / g.n)}</td></tr>`).join('')}</table></div>`;
    const chart = (id, type, labels, data, label) => window.Chart && new window.Chart($('#' + id), { type, data: { labels, datasets: [{ label, data, borderColor: '#4f8bff', backgroundColor: '#4f8bff88' }] }, options: { plugins: { legend: { display: false } } } });
    const sub = agg(r => r.questions.subjects?.name), dif = agg(r => r.questions.difficulty);
    chart('c1', 'line', days, days.map(d => acc(byDay[d])), 'Accuracy'); chart('c2', 'line', days, days.map(d => byDay[d].m), 'Marks');
    chart('c3', 'bar', Object.keys(sub), Object.values(sub).map(acc), 'Accuracy'); chart('c4', 'bar', Object.keys(dif), Object.values(dif).map(acc), 'Accuracy');
    chart('c5', 'line', days, days.map(d => Math.round(byDay[d].t / byDay[d].n)), 'Seconds');
  },

  async weak(main) {
    const rows = await submittedData(); main.innerHTML = '<h1>Weak Chapters</h1>';
    if (!rows) return main.innerHTML += '<div class="msg">Complete at least two tests to see weakness analysis.</div>';
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
    main.innerHTML += out.length ? out.map(([k, w]) => `<div class="card"><b>${esc(k)}</b>${w.map(([t, e]) => `<div><span class="tag warn">${t}</span> ${esc(e)}</div>`).join('')}</div>`).join('') : '<div class="msg">No topic meets the evidence threshold yet.</div>';
    main.innerHTML += `<p class="muted">A topic is only flagged with at least ${MIN_Q} attempted questions across ${MIN_TESTS} tests. ${thin.length} topics have too little data to judge. Formula-recall, calculation and interpretation mistakes cannot be told apart from results alone; they need mistake tags, which are not recorded yet.</p>`;
  },

  async settings(main) {
    const s = ctx.settings || {};
    let reg = ''; if (ctx.profile?.role === 'admin') { const { data } = await sb.from('app_settings').select('value').eq('key', 'registration_mode').single(); reg = data?.value; }
    main.innerHTML = `<h1>Settings</h1><div class="card"><label>Display name</label><input id="dn" value="${esc(ctx.profile?.display_name)}"><label>Theme</label><select id="th">${['system', 'light', 'dark'].map(x => `<option ${s.theme === x ? 'selected' : ''}>${x}</option>`).join('')}</select>
      <h2>Time estimates (minutes per question)</h2><div class="grid"><div><label>Easy</label><input id="te" type="number" step="0.1" min="0.1" value="${s.time_easy ?? 1.5}"></div><div><label>Medium</label><input id="tm" type="number" step="0.1" min="0.1" value="${s.time_medium ?? 2.5}"></div><div><label>Hard</label><input id="tx" type="number" step="0.1" min="0.1" value="${s.time_hard ?? 4}"></div></div>
      <p class="muted">These set the recommended practice duration only. They are not official JEE time limits.</p>
      <label>AI provider for the Study Coach</label><select id="ap">${['gemini', 'openrouter', 'openai_compatible'].map(x => `<option ${s.ai_provider === x ? 'selected' : ''}>${x}</option>`).join('')}</select>
      <p><button id="sv">Save settings</button></p></div>
      <div class="card"><h2 style="margin-top:0">Change password</h2><label>New password</label><input id="np" type="password" minlength="8"><p><button class="ghost" id="cp">Update password</button></p></div>`;
    $('#sv').onclick = async () => { const row = { user_id: ctx.user.id, theme: $('#th').value, time_easy: +$('#te').value, time_medium: +$('#tm').value, time_hard: +$('#tx').value, ai_provider: $('#ap').value };
      const [a, b] = await Promise.all([sb.from('user_settings').upsert(row), sb.from('profiles').update({ display_name: $('#dn').value.trim() }).eq('id', ctx.user.id)]);
      if (a.error || b.error) return toast((a.error || b.error).message); Object.assign(ctx.settings ||= {}, row); ctx.profile.display_name = $('#dn').value.trim(); applyTheme(row.theme); toast('Settings saved'); };
    $('#cp').onclick = async () => { const { error } = await sb.auth.updateUser({ password: $('#np').value }); toast(error ? error.message : 'Password updated'); };
  },

  async admin(main) {
    if (ctx.profile?.role !== 'admin') return main.innerHTML = '<h1>Admin</h1><div class="msg err">Administrators only.</div>';
    const g = async k => (await sb.from('app_settings').select('value').eq('key', k).single()).data?.value;
    const [mode, paused, inv, review, runs, jobs, logs, dups] = await Promise.all([g('registration_mode'), g('import_paused'), sb.from('invited_emails').select('email'),
      sb.from('questions').select('id,statement,classification_confidence,answer_verified').or('needs_review.eq.true,answer_verified.eq.false').limit(20),
      sb.from('import_runs').select('*').order('created_at', { ascending: false }).limit(10), sb.from('import_jobs').select('id,status,last_error,source_documents:document_id(source_url)').eq('status', 'failed').limit(20),
      sb.from('import_logs').select('level,message,created_at').order('created_at', { ascending: false }).limit(25), sb.from('duplicate_candidates').select('id,similarity,status').eq('status', 'pending').limit(20)]);
    main.innerHTML = `<h1>Admin</h1><div class="card"><b>Access</b><div class="row"><select id="rg"><option value="private" ${mode === 'private' ? 'selected' : ''}>Private (invited emails only)</option><option value="public" ${mode === 'public' ? 'selected' : ''}>Public registration</option></select><button id="rgs">Save</button></div>
      <label>Invite an email address</label><div class="row"><input id="ie" type="email" style="max-width:300px"><button class="ghost" id="ia">Invite</button></div><p class="muted">Invited: ${(inv.data || []).map(x => esc(x.email)).join(', ') || 'none'}</p></div>
      <div class="card"><b>Import engine</b><p class="muted">Imports run in GitHub Actions on a schedule. Buttons here queue or pause work; they do not run Python in your browser.</p>
      <div class="row"><button id="chk">Check sources</button><button id="go">Start import</button><button class="ghost" id="pz">${paused ? 'Resume imports' : 'Pause imports'}</button><button class="ghost" id="rt">Retry failed documents (${jobs.data?.length || 0})</button></div>
      <h2>History</h2>${(runs.data || []).map(r => `<div>${new Date(r.created_at).toLocaleString()} · ${esc(r.trigger)} · <span class="tag">${esc(r.status)}</span></div>`).join('') || '<p class="muted">No runs yet.</p>'}
      <h2>Failed documents</h2>${(jobs.data || []).map(j => `<div>${esc(j.source_documents?.source_url || j.id)}: <span class="bad">${esc(j.last_error || '')}</span></div>`).join('') || '<p class="muted">None.</p>'}
      <h2>Error log</h2>${(logs.data || []).map(l => `<div class="${l.level === 'error' ? 'bad' : ''}">${esc(l.level)} · ${esc(l.message)}</div>`).join('') || '<p class="muted">Empty.</p>'}
      <h2>Possible duplicates</h2><p class="muted">${dups.data?.length || 0} pending review.</p></div>
      <div class="card"><b>Questions needing review (${review.data?.length || 0})</b>${(review.data || []).map(q => `<div class="row" style="justify-content:space-between"><span>${esc(q.statement.slice(0, 110))}…</span><button class="ghost" data-v="${q.id}">Verify and publish</button></div>`).join('')}
      <p class="muted">Check the answer against the official key before verifying; verifying also publishes the question. Chapter and difficulty corrections can be made in the Supabase table editor for now.</p></div>`;
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
  main.innerHTML = `<h1>AI Study Coach</h1><div class="card"><label>Completed attempt</label><select id="at">${(atts || []).map(a => `<option value="${a.id}" ${a.id === attemptId ? 'selected' : ''}>${esc(a.tests?.name)} · ${new Date(a.submitted_at).toLocaleDateString()}</option>`).join('')}</select>
    <p><button id="gen" ${atts?.length ? '' : 'disabled'}>Generate report</button></p><div id="o"></div><p class="muted">The report is written from your recorded results only. It runs in a Supabase Edge Function so the AI key stays on the server.</p></div>
    <h2>Saved reports</h2>${(reps || []).map(r => `<details class="card"><summary>${new Date(r.created_at).toLocaleString()} · ${esc(r.provider)}</summary><div style="white-space:pre-wrap">${esc(r.report_markdown)}</div></details>`).join('') || '<p class="muted">None yet.</p>'}`;
  $('#gen').onclick = async () => { $('#gen').disabled = true; $('#o').innerHTML = '<p class="muted">Generating…</p>';
    const { data, error } = await sb.functions.invoke('ai-coach', { body: { attempt_id: $('#at').value } });
    $('#gen').disabled = false; if (error) return $('#o').innerHTML = errBox(error.message + ' (is the ai-coach function deployed and an AI key set? See the README.)');
    $('#o').innerHTML = `<div class="card" style="white-space:pre-wrap">${esc(data.report)}</div>`; };
}

window.addEventListener('hashchange', route); route();
