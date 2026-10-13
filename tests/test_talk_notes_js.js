// Tests for the pure helpers in static/talk-notes.js (the talk phones' Notes tab).
// Run with: node tests/test_talk_notes_js.js
const assert = require('assert');
const TN = require('../static/talk-notes.js');

let failed = 0;
function test(name, fn) {
  try { fn(); console.log('  ✓ ' + name); } catch (e) { failed++; console.log('  ✗ ' + name + '\n    ' + e.message); }
}

test('+ and - keep their colours, any other single character is blue', () => {
  assert.deepStrictEqual(TN.markerOf('+ pro'), { kind: 'plus', col: 0, ch: '+' });
  assert.deepStrictEqual(TN.markerOf('  - con'), { kind: 'minus', col: 2, ch: '-' });
  assert.strictEqual(TN.markerOf('i info').kind, 'info');
  assert.strictEqual(TN.markerOf('= burning tokens').kind, 'info');
  assert.strictEqual(TN.markerOf('* Chapter').kind, 'info');
  assert.strictEqual(TN.markerOf('+').kind, 'plus');
});

test('a word is not a marker', () => {
  assert.strictEqual(TN.markerOf('Token-Maxing'), null);
  assert.strictEqual(TN.markerOf('+1 Coin'), null);
  assert.strictEqual(TN.markerOf(''), null);
});

test('indentation folds like VS Code: header to the last deeper line, trailing blanks out', () => {
  const lines = ['A', '  a1', '', '  a2', '', 'B', 'C', '  c1', '    c11'];
  assert.deepStrictEqual(TN.foldRegions(lines), { 0: 3, 6: 8, 7: 8 });
});

test('a collapsed header hides its region, nested state kept', () => {
  const regions = { 0: 3, 1: 2 };
  const hidden = TN.hiddenLines(regions, (l) => l === 0, 5);
  assert.deepStrictEqual(hidden.map(Boolean), [false, true, true, true, false]);
  assert.strictEqual(TN.visibleLineFor(2, hidden), 0);
  assert.strictEqual(TN.visibleLineFor(4, hidden), 4);
});

test('cursor line and its parents are bright, the block dim, the rest faded', () => {
  const lines = ['Title', '', '* Chapter', '  + one', '    - deep', '  + two', '', 'Other'];
  assert.deepStrictEqual(TN.levels(lines, 4, null),
    ['fade', 'fade', 'bright', 'bright', 'bright', 'dim', 'fade', 'fade']);
});

test('a selection lights its own lines, not the cursor line below it', () => {
  const lines = ['* Chapter', '  + one', '  + two', '  + three'];
  const sel = { start_line: 1, start_char: 0, end_line: 2, end_char: 0 };  // line 1 whole, cursor at 2:0
  assert.deepStrictEqual(TN.levels(lines, 2, sel), ['bright', 'bright', 'dim', 'dim']);
  assert.deepStrictEqual(TN.selectedSpan(sel, 1, 7), [0, 7]);
  assert.strictEqual(TN.selectedSpan(sel, 2, 7), null);
});

test('on a blank line the block above stays grey with its chapter white', () => {
  const lines = ['* Chapter', '  + one', ''];
  assert.deepStrictEqual(TN.levels(lines, 2, null), ['bright', 'dim', 'fade']);
});

if (failed) { console.log(failed + ' failed'); process.exit(1); }
console.log('all passed');
