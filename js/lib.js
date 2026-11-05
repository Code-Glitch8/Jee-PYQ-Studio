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
