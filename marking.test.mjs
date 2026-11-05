import test from 'node:test';
import assert from 'node:assert/strict';
import { isCorrect, marksFor, recommendedSeconds, pickScheme } from '../js/marking.js';

test('single correct MCQ', () => {
  const q = { question_type: 'single_mcq', correct_answer: ['B'] };
  assert.equal(isCorrect(q, 'B'), true);
  assert.equal(isCorrect(q, 'A'), false);
  assert.equal(isCorrect(q, null), null);
});
test('multiple correct needs the exact set', () => {
  const q = { question_type: 'multi_mcq', correct_answer: ['A', 'C'] };
  assert.equal(isCorrect(q, ['C', 'A']), true);
  assert.equal(isCorrect(q, ['A']), false);
});
test('numerical honours tolerance', () => {
  const q = { question_type: 'numerical', correct_answer: { value: 3.14, tolerance: 0.01 } };
  assert.equal(isCorrect(q, '3.145'), true);
  assert.equal(isCorrect(q, '3.2'), false);
});
test('missing answer key is never marked wrong', () => {
  assert.equal(isCorrect({ question_type: 'single_mcq', correct_answer: null }, 'A'), null);
});
test('no marking scheme means no invented marks', () => {
  const r = marksFor({ question_type: 'single_mcq', correct_answer: ['A'] }, 'A', []);
  assert.equal(r.marks, null);
});
test('scheme selection by exam, type and year', () => {
  const schemes = [{ id: 1, exam_id: 1, question_type: 'single_mcq', year_from: 2019, year_to: null, marks_correct: 4, marks_incorrect: -1, marks_unattempted: 0 }];
  const q = { question_type: 'single_mcq', papers: { exam_id: 1, exam_year: 2022 } };
  assert.equal(pickScheme(q, schemes).id, 1);
});
test('recommended time formula', () => {
  assert.equal(recommendedSeconds({ easy: 5, medium: 10, hard: 5 }), (5 * 1.5 + 10 * 2.5 + 5 * 4) * 60);
});
