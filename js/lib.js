import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm';
import { SUPABASE_URL, SUPABASE_KEY } from './config.js';

export const sb = createClient(SUPABASE_URL, SUPABASE_KEY);
export const ctx = { user: null, profile: null, settings: null };

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function fmt(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
}
export const mins = sec => (sec / 60).toFixed(1) + ' min';

export function math(node, tries = 0) {
  if (window.renderMathInElement) {
    window.renderMathInElement(node, { throwOnError: false, delimiters: [
      { left: '$$', right: '$$', display: true }, { left: '\\[', right: '\\]', display: true },
      { left: '\\(', right: '\\)', display: false }, { left: '$', right: '$', display: false }] });
  } else if (tries < 20) setTimeout(() => math(node, tries + 1), 300);
}

export function toast(msg) {
  const t = document.createElement('div'); t.className = 'toast'; t.textContent = msg;
  document.body.append(t); setTimeout(() => t.remove(), 3500);
}

export function applyTheme(theme) {
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

export function errBox(e) { return `<div class="msg err">${esc(e?.message || e)}</div>`; }

/* ───────── UI helpers (markup only, no data access) ───────── */
export const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  questions: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  papers: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>',
  'create-test': '<circle cx="12" cy="12" r="10"/><path d="M12 8v8M8 12h8"/>',
  tests: '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
  analytics: '<path d="M3 3v18h18"/><path d="M7 16v-4M12 16V8M17 16v-7"/>',
  weak: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  coach: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  settings: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  admin: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  out: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  check: '<path d="m5 12 5 5L20 7"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
};
export const ico = (k, cls = 'ico') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[k] || ''}</svg>`;

/** Page header: title, optional one-line subtitle, optional action buttons (HTML). */
export const head = (title, sub = '', actions = '') =>
  `<header class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<p class="sub">${sub}</p>` : ''}</div>${actions ? `<div class="actions">${actions}</div>` : ''}</header>`;

/** Empty state with an optional call to action. `action` is trusted HTML. */
export const empty = (title, text, action = '', icon = 'inbox') =>
  `<div class="empty">${ico(icon)}<b>${esc(title)}</b><p>${esc(text)}</p>${action}</div>`;

export const loading = text => `<div class="loading"><span class="spin"></span>${esc(text)}</div>`;

/** Subject key used for colour: Physics / Chemistry / Mathematics. */
export const sk = n => ({ phy: 'phy', che: 'che', mat: 'mat' }[String(n || '').slice(0, 3).toLowerCase()] || '');
export const subjTag = n => `<span class="tag" data-s="${sk(n)}"><span class="dot"></span>${esc(n || 'Unclassified')}</span>`;

export const pct = (c, w) => (c + w ? Math.round(100 * c / (c + w)) : null);
/** Accuracy cell: thin bar plus number, coloured by level. */
export const bar = p => p == null ? '<span class="muted">—</span>'
  : `<span class="bar ${p >= 70 ? 'hi' : p >= 40 ? 'mid' : 'lo'}"><i style="--w:${p}%"></i><span>${p}%</span></span>`;

/** Styled replacement for window.confirm. Resolves true or false. */
export function confirmDialog(title, text, okLabel = 'Confirm', cancelLabel = 'Cancel') {
  return new Promise(resolve => {
    const d = document.createElement('dialog'); d.className = 'modal'; let result = false;
    d.innerHTML = `<h3>${esc(title)}</h3><p>${esc(text)}</p><div class="row"><button class="ghost" data-r="0">${esc(cancelLabel)}</button><button class="accent" data-r="1" autofocus>${esc(okLabel)}</button></div>`;
    d.addEventListener('click', e => { const b = e.target.closest('button[data-r]'); if (b) { result = b.dataset.r === '1'; d.close(); } });
    d.addEventListener('close', () => { d.remove(); resolve(result); });
    document.body.append(d); d.showModal();
  });
}

/** Creates a new attempt for a test. Resume logic lives in the caller. */
export async function startAttempt(testId) {
  const { data: test, error: e1 } = await sb.from('tests').select('duration_seconds').eq('id', testId).single();
  if (e1) throw e1;
  const { data: prev } = await sb.from('attempts').select('attempt_number').eq('test_id', testId).order('attempt_number', { ascending: false }).limit(1);
  const n = (prev?.[0]?.attempt_number || 0) + 1;
  const { data, error } = await sb.from('attempts').insert({
    test_id: testId, user_id: ctx.user.id, attempt_number: n, status: 'in_progress',
    remaining_seconds: test.duration_seconds, started_at: new Date().toISOString(),
  }).select('id').single();
  if (error) throw error;
  return data.id;
}

/** Form dialog. `fields` is trusted HTML. Resolves with an object of the submitted values, or null if cancelled. */
export function formDialog(title, fields, okLabel = 'Save', intro = '') {
  return new Promise(resolve => {
    const d = document.createElement('dialog'); d.className = 'modal wide'; let result = null;
    d.innerHTML = `<h3>${esc(title)}</h3>${intro ? `<p>${esc(intro)}</p>` : ''}<form method="dialog" class="stack">${fields}<div class="row"><button type="button" class="ghost" data-r="0">Cancel</button><button class="accent" value="ok">${esc(okLabel)}</button></div></form>`;
    d.querySelector('[data-r="0"]').onclick = () => d.close();
    d.querySelector('form').addEventListener('submit', () => { result = Object.fromEntries(new FormData(d.querySelector('form'))); });
    d.addEventListener('close', () => { d.remove(); resolve(result); });
    document.body.append(d); d.showModal();
  });
}

/** Signed URL for a private storage object (admins read source PDFs, every signed-in user reads question images). */
export async function signedUrl(bucket, path, seconds = 3600) {
  const { data } = await sb.storage.from(bucket).createSignedUrl(path, seconds);
  return data?.signedUrl || null;
}

/** Fills <div data-figs="[...]"> placeholders with the question's figures. Page snapshots are for admins and are never shown here. */
export async function fillFigures(root) {
  for (const el of $$('[data-figs]', root)) {
    let imgs = []; try { imgs = JSON.parse(el.dataset.figs); } catch { /* ignore malformed */ }
    el.removeAttribute('data-figs');
    for (const f of imgs.filter(i => i.kind === 'figure' && i.path)) {
      const url = await signedUrl(f.bucket || 'question-images', f.path);
      if (url) el.insertAdjacentHTML('beforeend', `<img src="${esc(url)}" alt="Figure for this question" loading="lazy">`);
    }
  }
}
export const figsAttr = images => `data-figs="${esc(JSON.stringify(images || []))}"`;
