// Pure functions (no browser or network access) so they can be unit-tested with `node --test`.
export function correctValue(q) {
  const c = q.correct_answer;
  if (c && typeof c === 'object' && !Array.isArray(c)) return c.value ?? c.answer ?? c.options ?? null;
  return c ?? null;
}
const isEmpty = a => a == null || a === '' || (Array.isArray(a) && a.length === 0);

/** Returns true, false, or null (not attempted or no answer on file). */
export function isCorrect(q, answer) {
  if (isEmpty(answer)) return null;
  const cv = correctValue(q);
  if (cv == null) return null;
  if (q.question_type === 'numerical' || q.question_type === 'integer') {
    const tol = q.correct_answer && !Array.isArray(q.correct_answer) && typeof q.correct_answer === 'object' ? Number(q.correct_answer.tolerance ?? 0) : 0;
    const a = Number(answer), b = Number(Array.isArray(cv) ? cv[0] : cv);
    if (Number.isNaN(a) || Number.isNaN(b)) return null;
    return Math.abs(a - b) <= tol + 1e-9;
  }
  const norm = x => (Array.isArray(x) ? x : [x]).map(s => String(s).trim().toUpperCase()).sort().join(',');
  return norm(answer) === norm(cv);
}

/** Picks the marking scheme for a question: its own scheme first, then exam + type + year range. */
export function pickScheme(q, schemes) {
  if (q.marks_scheme_id) { const s = schemes.find(x => x.id === q.marks_scheme_id); if (s) return s; }
  const exam = q.papers?.exam_id, year = q.papers?.exam_year;
  return schemes.find(s => s.exam_id === exam && s.question_type === q.question_type &&
    (s.year_from == null || year >= s.year_from) && (s.year_to == null || year <= s.year_to)) || null;
}

/** Marks for one response. Partial marking is not applied; a scheme with allows_partial is scored all-or-nothing. */
export function marksFor(q, answer, schemes) {
  const ok = isCorrect(q, answer);
  const s = pickScheme(q, schemes);
  if (!s) return { correct: ok, marks: null, max: null };
  const marks = ok === null ? Number(s.marks_unattempted) : ok ? Number(s.marks_correct) : Number(s.marks_incorrect);
  return { correct: ok, marks, max: Number(s.marks_correct) };
}

/** Recommended seconds from difficulty counts and per-question minutes. */
export function recommendedSeconds(d, t = { easy: 1.5, medium: 2.5, hard: 4 }) {
  return Math.round(((d.easy || 0) * t.easy + (d.medium || 0) * t.medium + (d.hard || 0) * t.hard) * 60);
}
