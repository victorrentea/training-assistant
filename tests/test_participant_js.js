// Tests for pure helpers in static/participant.html
// Run with: node test_participant_js.js

const fs = require('fs');
const path = require('path');

// Pull a top-level `function name(...) { ... }` verbatim out of a source file,
// so the test exercises the SHIPPED code instead of a copy that can drift.
function extractFunction(file, name) {
  const src = fs.readFileSync(file, 'utf8');
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('function not found: ' + name + ' in ' + file);
  let depth = 0, end = -1;
  for (let i = src.indexOf('{', start); i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) { end = i + 1; break; }
  }
  if (end < 0) throw new Error('unterminated function: ' + name);
  return src.slice(start, end);
}

const PARTICIPANT_HTML = path.join(__dirname, '..', 'static', 'participant.html');
const restoreMarkTagsInCode = new Function(
  extractFunction(PARTICIPANT_HTML, 'restoreMarkTagsInCode') + '; return restoreMarkTagsInCode;'
)();

function largestRemainder(floats) {
  const floors = floats.map(Math.floor);
  const remainder = 100 - floors.reduce((a, b) => a + b, 0);
  const order = floats.map((v, i) => [v - Math.floor(v), i])
    .sort((a, b) => b[0] - a[0]);
  for (let i = 0; i < Math.min(remainder, order.length); i++) floors[order[i][1]]++;
  return floors;
}

let passed = 0, failed = 0;

function assert(description, condition) {
  if (condition) {
    console.log(`  ✓ ${description}`);
    passed++;
  } else {
    console.error(`  ✗ ${description}`);
    failed++;
  }
}

function sum(arr) { return arr.reduce((a, b) => a + b, 0); }

console.log('largestRemainder()');

// Bug regression: all-zero input (totalVotes=0) must not throw
// (bars are hidden when totalVotes=0 so the actual values don't matter, just no crash)
assert('zero votes — does not throw',
  (() => { try { largestRemainder([0, 0, 0, 0]); return true; } catch { return false; } })()
);

// Percentages always sum to 100
assert('equal split 4 options sums to 100',
  sum(largestRemainder([25, 25, 25, 25])) === 100
);
assert('uneven split sums to 100',
  sum(largestRemainder([33.33, 33.33, 33.34])) === 100
);
assert('single option 100% sums to 100',
  sum(largestRemainder([100])) === 100
);
assert('8 options small fractions sum to 100',
  sum(largestRemainder([12.5, 12.5, 12.5, 12.5, 12.5, 12.5, 12.5, 12.5])) === 100
);

// Largest remainder goes to the highest fractional part
const r = largestRemainder([33.33, 33.33, 33.34]);
assert('largest fraction gets the extra point (index 2 = 34)',
  r[2] === 34
);

// ── restoreMarkTagsInCode() — host highlights inside code spans ──────────────
// Regression: the host highlighted `proposal` inside `` `proposal.md` `` and the
// summary rendered the literal text "<mark>proposal</mark>.md" in monospace,
// because markdown does not parse HTML inside code. The summary renderer now
// revives the highlighter's own <mark> sentinels after marked escaped them.
console.log('\nrestoreMarkTagsInCode()');

assert('code with no marks is returned untouched',
  restoreMarkTagsInCode('npm i -g foo') === 'npm i -g foo'
);
assert('the reported bug: `<mark>proposal</mark>.md` becomes a real highlight',
  restoreMarkTagsInCode('&lt;mark&gt;proposal&lt;/mark&gt;.md') === '<mark>proposal</mark>.md'
);
assert('other escaped angle brackets stay escaped (text unchanged)',
  restoreMarkTagsInCode('npm i&lt;mark&gt; -g &lt;anythin&lt;/mark&gt;g&gt;')
    === 'npm i<mark> -g &lt;anythin</mark>g&gt;'
);
assert('several marks in one span are all revived',
  restoreMarkTagsInCode('a&lt;mark&gt;b&lt;/mark&gt;c&lt;mark&gt;d&lt;/mark&gt;')
    === 'a<mark>b</mark>c<mark>d</mark>'
);
assert('unbalanced open tag is dropped, never printed literally',
  restoreMarkTagsInCode('foo&lt;mark&gt;bar') === 'foobar'
);
assert('stray close tag is dropped, never printed literally',
  restoreMarkTagsInCode('foo&lt;/mark&gt;bar') === 'foobar'
);
assert('out-of-order tags are dropped',
  restoreMarkTagsInCode('&lt;/mark&gt;a&lt;mark&gt;') === 'a'
);
assert('nested opens are dropped (never emit invalid nesting)',
  restoreMarkTagsInCode('&lt;mark&gt;a&lt;mark&gt;b&lt;/mark&gt;c&lt;/mark&gt;') === 'abc'
);

// Regression: the profile-card name editor snapped shut on its own. The initial
// state load is async, so a participant could open the crayon editor before the
// deferred activity-view preselect fired; that focus() blurred the editor and
// the blur handler committed and closed it. The preselect now yields to any
// edit already in progress.
console.log('\n_ensureNameInputPreselected()');

function runPreselect(activeElement) {
  const focused = [];
  const input = {tagName: 'INPUT', value: 'Auto Name',
                 focus: () => focused.push('focus'), select: () => focused.push('select')};
  const scheduled = [];
  const sandbox = {
    document: {
      getElementById: (id) => (id === 'activity-name-input' ? input : null),
      get activeElement() { return activeElement; },
    },
    setTimeout: (fn) => scheduled.push(fn),
  };
  const fn = new Function('document', 'setTimeout',
    'var _namePreselected = false;' +
    extractFunction(PARTICIPANT_HTML, '_ensureNameInputPreselected') +
    '; return _ensureNameInputPreselected;'
  )(sandbox.document, sandbox.setTimeout);
  fn();
  scheduled.forEach((cb) => cb());
  return focused;
}

assert('preselects the name field when nothing else is focused',
  runPreselect({tagName: 'BODY'}).join() === 'focus,select'
);
assert('the reported bug: does NOT steal focus from the open name editor',
  runPreselect({tagName: 'INPUT', id: 'name-edit-input'}).length === 0
);
assert('does not steal focus from a textarea the participant is typing in',
  runPreselect({tagName: 'TEXTAREA'}).length === 0
);
assert('does not steal focus from a contenteditable',
  runPreselect({tagName: 'DIV', isContentEditable: true}).length === 0
);

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
