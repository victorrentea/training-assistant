// Tests for pure helpers in static/participant.html
// Run with: node test_participant_js.js

const fs = require('fs');
const path = require('path');

// Pull a top-level `function name(...) { ... }` verbatim out of a source file,
// so the test exercises the SHIPPED code instead of a copy that can drift.
function extractFunction(file, name) {
  const src = fs.readFileSync(file, 'utf8');
  let start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('function not found: ' + name + ' in ' + file);
  // Keep the `async` keyword: slicing from `function` alone yields a body with
  // a bare `await` in it, which is a SyntaxError once re-parsed.
  const asyncPrefix = 'async ';
  if (src.slice(start - asyncPrefix.length, start) === asyncPrefix) {
    start -= asyncPrefix.length;
  }
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


// ── Files tab folder tree ───────────────────────────────────────────────────

const buildFileTree = new Function(
  extractFunction(PARTICIPANT_HTML, 'finalizeFileNode') + ';' +
  extractFunction(PARTICIPANT_HTML, 'buildFileTree') + '; return buildFileTree;'
)();
const parseFilesMd = new Function(
  extractFunction(PARTICIPANT_HTML, 'parseFilesMd') + '; return parseFilesMd;'
)();

console.log('buildFileTree()');

const SAMPLE = [
  'README.md',
  'src/main/java/victor/training/cleancode/ComplexIfs.java',
  'src/main/java/victor/training/cleancode/Immutability.java',
  'src/main/java/victor/training/cleancode/fp/Optionals.java',
  'src/main/java/victor/training/cleancode/fp/Streams.java',
  'src/test/java/victor/training/cleancode/ComplexIfsTest.java',
];
const tree = buildFileTree(SAMPLE);

assert('root keeps its own file', tree.files.map(f => f.name).join() === 'README.md');
assert('root is not collapsed into src', tree.folders.length === 1 && tree.folders[0].name === 'src');

const src = tree.folders[0];
assert('src stays a node because it branches',
  src.folders.map(f => f.name).join() === 'main/java/victor/training/cleancode,test/java/victor/training/cleancode');

const main = src.folders[0];
assert('single-child chain is collapsed into one node',
  main.name === 'main/java/victor/training/cleancode');
assert('folders come before files', main.folders.length === 1 && main.folders[0].name === 'fp');
assert('files of the collapsed node are kept',
  main.files.map(f => f.name).join() === 'ComplexIfs.java,Immutability.java');
assert('leaf folder holds its files sorted',
  main.folders[0].files.map(f => f.name).join() === 'Optionals.java,Streams.java');
assert('file entries keep their full path',
  main.files[0].path === 'src/main/java/victor/training/cleancode/ComplexIfs.java');

// A folder with a file of its own must NOT be collapsed into its single child,
// or that file would be orphaned.
const guard = buildFileTree(['a/b/c.java', 'a/d.java']);
assert('no collapse when the folder has files of its own',
  guard.folders[0].name === 'a' && guard.folders[0].files.map(f => f.name).join() === 'd.java');
assert('the single child still renders below it',
  guard.folders[0].folders[0].name === 'b');

const mixed = buildFileTree(['Zebra.java', 'alpha.java']);
assert('sorting is case-insensitive',
  mixed.files.map(f => f.name).join() === 'alpha.java,Zebra.java');

assert('empty input yields an empty root',
  buildFileTree([]).folders.length === 0 && buildFileTree([]).files.length === 0);

console.log('parseFilesMd()');

const MD = [
  '# Files opened this session',
  '',
  '## [clean-code-java](https://github.com/victorrentea/clean-code-java) — branch `master` ',
  '',
  '- [src/a/B.java](https://github.com/victorrentea/clean-code-java/blob/master/src/a/B.java) — 09:41 ',
  '- [src/a/C.java](https://github.com/victorrentea/clean-code-java/blob/solved/src/a/C.java) — 10:05 · branch `solved` ',
  '- src/a/Draft.java — 11:20 ',
].join('\n');
const repos = parseFilesMd(MD);

assert('one repo parsed', repos.length === 1);
assert('repo name and branch parsed',
  repos[0].name === 'clean-code-java' && repos[0].branch === 'master');
assert('three entries parsed', repos[0].entries.length === 3);
assert('linked entry keeps path and href',
  repos[0].entries[0].path === 'src/a/B.java' &&
  repos[0].entries[0].href.endsWith('/blob/master/src/a/B.java'));
assert('time parsed', repos[0].entries[0].time === '09:41');
assert('divergent branch chip parsed', repos[0].entries[1].branch === 'solved');
assert('same-branch entry has no chip', repos[0].entries[0].branch === '');
assert('unlinked entry has no href and keeps its path',
  repos[0].entries[2].href === null && repos[0].entries[2].path === 'src/a/Draft.java');

const dated = parseFilesMd([
  '## [r](https://github.com/o/r) — branch `main` ',
  '- [a.java](https://github.com/o/r/blob/main/a.java) — Aug 4 09:41 ',
].join('\n'));
assert('dated times parse', dated[0].entries[0].time === 'Aug 4 09:41');

// A path containing a space must not vanish from the tree. build_blob_url
// now percent-encodes it (%20), but the regex itself is widened from `\S+`
// to `[^)]+` so it survives even a literal, unencoded space defensively.
const percentEncoded = parseFilesMd([
  '## [r](https://github.com/o/r) — branch `main` ',
  '- [src/my folder/a.py](https://github.com/o/r/blob/main/src/my%20folder/a.py) — 09:41 ',
].join('\n'));
assert('href with a percent-encoded space is captured whole',
  percentEncoded[0].entries[0].href === 'https://github.com/o/r/blob/main/src/my%20folder/a.py');

const literalSpace = parseFilesMd([
  '## [r](https://github.com/o/r) — branch `main` ',
  '- [src/my folder/a.py](https://github.com/o/r/blob/main/src/my folder/a.py) — 09:41 ',
].join('\n'));
assert('href with a literal, unencoded space is still captured whole',
  literalSpace[0].entries[0].href === 'https://github.com/o/r/blob/main/src/my folder/a.py');

// A path containing parentheses degrades once build_blob_url percent-encodes
// them to %28/%29 — confirm the href group survives that shape too.
const withParens = parseFilesMd([
  '## [r](https://github.com/o/r) — branch `main` ',
  '- [src/a(1).java](https://github.com/o/r/blob/main/src/a%281%29.java) — 09:41 ',
].join('\n'));
assert('href with percent-encoded parens is captured whole',
  withParens[0].entries[0].href === 'https://github.com/o/r/blob/main/src/a%281%29.java');

// ── Files-unread decision ───────────────────────────────────────────────────
// Timestamps in opened-files.md move on every re-open, which rewrites the
// document and fires files_count_updated with an UNCHANGED count. Only a
// genuine increase in the count may flag the tab unread.

const shouldFlagFilesUnread = new Function(
  extractFunction(PARTICIPANT_HTML, 'shouldFlagFilesUnread') + '; return shouldFlagFilesUnread;'
)();

console.log('shouldFlagFilesUnread()');

assert('equal counts do not flag (a re-opened file)', shouldFlagFilesUnread(3, 3) === false);
assert('a higher count flags (a genuinely new file)', shouldFlagFilesUnread(4, 3) === true);
assert('a lower count does not flag', shouldFlagFilesUnread(2, 3) === false);

// ── Host-machine auto session switch ────────────────────────────────────────
// The security boundary is "can this browser reach the trainer's 127.0.0.1:1234".
// These tests pin the client half: no traffic at all without the cookie, no
// navigation when the session is unchanged, and a fresh UUID when it changes.

function runHostMachinePoll({ cookie, activeSessionId, currentSessionId }) {
  const calls = [];
  const removed = [];
  let navigatedTo = null;

  const sandbox = {
    document: { cookie },
    fetch: (url) => {
      calls.push(url);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ session_id: activeSessionId }),
      });
    },
    AbortSignal: { timeout: () => null },
    uuidStore: { removeItem: (k) => removed.push(k) },
    window: { get location() { return { set href(v) { navigatedTo = v; } }; } },
  };

  const src =
    'var _sessionId = ' + JSON.stringify(currentSessionId) + ';' +
    'var HOST_MACHINE_DAEMON = "http://127.0.0.1:1234";' +
    'var HOST_MACHINE_TIMEOUT_MS = 800;' +
    'var _uuidStore = uuidStore;' +
    extractFunction(PARTICIPANT_HTML, '_onHostMachine') + ';' +
    extractFunction(PARTICIPANT_HTML, '_pollForNewSession') + ';' +
    'return _pollForNewSession;';

  const fn = new Function('document', 'fetch', 'AbortSignal', 'uuidStore', 'window', src)(
    sandbox.document, sandbox.fetch, sandbox.AbortSignal, sandbox.uuidStore, sandbox.window
  );
  return fn().then(() => ({ calls, removed, navigatedTo }));
}

const hostMachineResults = [];
Promise.all([
  runHostMachinePoll({ cookie: '', activeSessionId: 'newone', currentSessionId: 'oldone' })
    .then((r) => hostMachineResults.push(['no cookie => never touches localhost', r.calls.length === 0 && r.navigatedTo === null])),
  runHostMachinePoll({ cookie: 'ON_HOST_MACHINE=true', activeSessionId: 'samest', currentSessionId: 'samest' })
    .then((r) => hostMachineResults.push(['unchanged session => no navigation', r.calls.length === 1 && r.navigatedTo === null && r.removed.length === 0])),
  runHostMachinePoll({ cookie: 'ON_HOST_MACHINE=true', activeSessionId: 'newone', currentSessionId: 'oldone' })
    .then((r) => hostMachineResults.push(['new session => fresh UUID, then navigate', r.navigatedTo === '/newone/' && r.removed.join() === 'workshop_participant_uuid'])),
]).then(() => {
  hostMachineResults.forEach(([desc, ok]) => assert(desc, ok));
  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
});
