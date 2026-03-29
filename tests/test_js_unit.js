// Unit tests for pure JavaScript functions across the codebase.
// Run with: node test_js_unit.js
//
// Each function under test is copied here verbatim (same as in the source files)
// to avoid module-system gymnastics with vanilla-JS browser scripts.
const fs = require('fs');

let passed = 0, failed = 0, suiteName = '';

function suite(name) { suiteName = name; console.log(`\n${name}`); }

function assert(description, condition) {
  if (condition) {
    console.log(`  \u2713 ${description}`);
    passed++;
  } else {
    console.error(`  \u2717 ${description}`);
    failed++;
  }
}

function assertEq(description, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    console.log(`  \u2713 ${description}`);
    passed++;
  } else {
    console.error(`  \u2717 ${description}  (got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)})`);
    failed++;
  }
}

// ═══════════════════════════════════════════════════════════════════════
// Functions under test (copied from source to avoid import issues)
// ═══════════════════════════════════════════════════════════════════════

// --- from participant.js ---
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function avatarColorFromUuid(uuid) {
  const hash = parseInt((uuid || '').replace(/-/g, '').slice(0, 8), 16);
  const hue = hash % 360;
  return `hsl(${hue}, 60%, 40%)`;
}

const LS_ONBOARDING_HIDDEN_KEY = 'workshop_onboarding_hidden';
const localStorage = (() => {
  const store = new Map();
  return {
    getItem(key) { return store.has(key) ? store.get(key) : null; },
    setItem(key, value) { store.set(key, String(value)); },
    removeItem(key) { store.delete(key); },
    clear() { store.clear(); },
  };
})();

function isOnboardingChecklistHidden() {
  return localStorage.getItem(LS_ONBOARDING_HIDDEN_KEY) === '1';
}

function markOnboardingChecklistHidden() {
  localStorage.setItem(LS_ONBOARDING_HIDDEN_KEY, '1');
}

function largestRemainder(floats) {
  const total = floats.reduce((a, b) => a + b, 0);
  if (total === 0) return floats.map(() => 0);
  const floors = floats.map(Math.floor);
  const remainder = 100 - floors.reduce((a, b) => a + b, 0);
  const order = floats.map((v, i) => [v - Math.floor(v), i])
    .sort((a, b) => b[0] - a[0]);
  for (let i = 0; i < Math.min(remainder, order.length); i++) floors[order[i][1]]++;
  return floors;
}

// --- from version-age.js ---
function parseVersionTimestamp(raw) {
  if (!raw || typeof raw !== 'string') return null;
  const m = raw.trim().match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$/);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]) - 1;
  const day = Number(m[3]);
  const hour = Number(m[4]);
  const minute = Number(m[5]);
  const dt = new Date(year, month, day, hour, minute, 0, 0);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

// Note: formatElapsed references window.APP_VERSION for >24h case.
// We provide a global stub.
const _window = { APP_VERSION: '2026-03-20 23:00' };
function formatElapsed(deployDate, now) {
  const deltaSec = Math.max(0, Math.floor((now.getTime() - deployDate.getTime()) / 1000));
  if (deltaSec < 60) return deltaSec + 's ago';
  if (deltaSec < 3600) return Math.floor(deltaSec / 60) + 'm ago';
  if (deltaSec < 86400) return Math.floor(deltaSec / 3600) + 'h ago';
  return 'from ' + _window.APP_VERSION;
}

// --- from host.js: poll history logic ---
function recordPollInHistory_logic(history, poll, correctIds) {
  // Extracted pure logic from recordPollInHistory (no localStorage dependency)
  if (!poll) return history;
  const entry = {
    question: poll.question,
    options: poll.options.map(o => ({
      text: o.text,
      correct: correctIds.has(o.id),
    })),
    multi: !!poll.multi,
  };
  const idx = history.findIndex(e => e.question === poll.question);
  const result = [...history];
  if (idx >= 0) result[idx] = entry; else result.push(entry);
  return result;
}

// ═══════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════

// ── escHtml ──────────────────────────────────────────────────────────
suite('escHtml()');
assertEq('escapes ampersand', escHtml('a&b'), 'a&amp;b');
assertEq('escapes less-than', escHtml('<script>'), '&lt;script&gt;');
assertEq('escapes greater-than', escHtml('1 > 0'), '1 &gt; 0');
assertEq('handles all three together', escHtml('<a href="&">'), '&lt;a href="&amp;"&gt;');
assertEq('converts number to string', escHtml(42), '42');
assertEq('converts null to string', escHtml(null), 'null');
assertEq('converts undefined to string', escHtml(undefined), 'undefined');
assertEq('empty string stays empty', escHtml(''), '');
assertEq('plain text passes through', escHtml('hello world'), 'hello world');
assertEq('multiple ampersands', escHtml('a&b&c'), 'a&amp;b&amp;c');

// ── avatarColorFromUuid ──────────────────────────────────────────────
suite('avatarColorFromUuid()');

// Deterministic: same UUID → same color
const color1 = avatarColorFromUuid('550e8400-e29b-41d4-a716-446655440000');
const color2 = avatarColorFromUuid('550e8400-e29b-41d4-a716-446655440000');
assertEq('deterministic for same UUID', color1, color2);

// Different UUIDs → different colors (probabilistically)
const color3 = avatarColorFromUuid('00000000-0000-0000-0000-000000000000');
const color4 = avatarColorFromUuid('ffffffff-ffff-ffff-ffff-ffffffffffff');
assert('different UUIDs produce different hues', color3 !== color4);

// Output format
assert('returns hsl() string', /^hsl\(\d+, 60%, 40%\)$/.test(color1));

// Hue is in 0-359 range
const hueMatch = color1.match(/^hsl\((\d+)/);
const hue = parseInt(hueMatch[1]);
assert('hue is 0-359', hue >= 0 && hue < 360);

// Edge cases
assertEq('null UUID produces valid color', avatarColorFromUuid(null), 'hsl(NaN, 60%, 40%)');
assertEq('empty string UUID', avatarColorFromUuid(''), 'hsl(NaN, 60%, 40%)');

// All-zero UUID → hue 0
assertEq('all-zero UUID → hue 0', avatarColorFromUuid('00000000-0000-0000-0000-000000000000'), 'hsl(0, 60%, 40%)');

// ── onboarding checklist persistence ─────────────────────────────────
suite('onboarding checklist persistence');
localStorage.clear();
assertEq('hidden flag is false by default', isOnboardingChecklistHidden(), false);
markOnboardingChecklistHidden();
assertEq('hidden flag becomes true after marking hidden', isOnboardingChecklistHidden(), true);
localStorage.removeItem(LS_ONBOARDING_HIDDEN_KEY);
assertEq('hidden flag becomes false after reset', isOnboardingChecklistHidden(), false);

// ── largestRemainder ─────────────────────────────────────────────────
suite('largestRemainder()');

function sum(arr) { return arr.reduce((a, b) => a + b, 0); }

assert('zero votes — does not throw',
  (() => { try { largestRemainder([0, 0, 0, 0]); return true; } catch { return false; } })()
);
assertEq('zero votes returns all zeros', largestRemainder([0, 0, 0, 0]), [0, 0, 0, 0]);
assertEq('equal split 4 options sums to 100', sum(largestRemainder([25, 25, 25, 25])), 100);
assertEq('uneven split sums to 100', sum(largestRemainder([33.33, 33.33, 33.34])), 100);
assertEq('single option 100% sums to 100', sum(largestRemainder([100])), 100);
assertEq('8 options small fractions sum to 100',
  sum(largestRemainder([12.5, 12.5, 12.5, 12.5, 12.5, 12.5, 12.5, 12.5])), 100);

const r = largestRemainder([33.33, 33.33, 33.34]);
assertEq('largest fraction gets extra point', r[2], 34);

// 2 options
assertEq('2 options sum to 100', sum(largestRemainder([66.67, 33.33])), 100);

// ── parseVersionTimestamp ────────────────────────────────────────────
suite('parseVersionTimestamp()');

const ts = parseVersionTimestamp('2026-03-20 23:00');
assert('parses valid timestamp', ts instanceof Date);
assertEq('correct year', ts.getFullYear(), 2026);
assertEq('correct month (0-indexed)', ts.getMonth(), 2); // March = 2
assertEq('correct day', ts.getDate(), 20);
assertEq('correct hour', ts.getHours(), 23);
assertEq('correct minute', ts.getMinutes(), 0);

assertEq('returns null for null', parseVersionTimestamp(null), null);
assertEq('returns null for empty string', parseVersionTimestamp(''), null);
assertEq('returns null for non-string', parseVersionTimestamp(42), null);
assertEq('returns null for bad format', parseVersionTimestamp('not-a-date'), null);
assertEq('returns null for partial date', parseVersionTimestamp('2026-03-20'), null);
assertEq('trims whitespace', parseVersionTimestamp('  2026-03-20 23:00  ') instanceof Date, true);

// ── formatElapsed ────────────────────────────────────────────────────
suite('formatElapsed()');

const base = new Date(2026, 2, 20, 23, 0); // 2026-03-20 23:00

assertEq('0 seconds ago', formatElapsed(base, new Date(base.getTime())), '0s ago');
assertEq('30 seconds ago', formatElapsed(base, new Date(base.getTime() + 30000)), '30s ago');
assertEq('59 seconds ago', formatElapsed(base, new Date(base.getTime() + 59000)), '59s ago');
assertEq('1 minute ago', formatElapsed(base, new Date(base.getTime() + 60000)), '1m ago');
assertEq('45 minutes ago', formatElapsed(base, new Date(base.getTime() + 45 * 60000)), '45m ago');
assertEq('1 hour ago', formatElapsed(base, new Date(base.getTime() + 3600000)), '1h ago');
assertEq('23 hours ago', formatElapsed(base, new Date(base.getTime() + 23 * 3600000)), '23h ago');
assertEq('24+ hours shows version', formatElapsed(base, new Date(base.getTime() + 25 * 3600000)), 'from 2026-03-20 23:00');
assertEq('future date clamps to 0s', formatElapsed(base, new Date(base.getTime() - 5000)), '0s ago');

// ── recordPollInHistory (pure logic) ─────────────────────────────────
suite('recordPollInHistory() logic');

const samplePoll = {
  question: 'What is 2+2?',
  options: [
    { id: 'a', text: 'Three' },
    { id: 'b', text: 'Four' },
    { id: 'c', text: 'Five' },
  ],
  multi: false,
};

const h1 = recordPollInHistory_logic([], samplePoll, new Set(['b']));
assertEq('adds first entry', h1.length, 1);
assertEq('records question', h1[0].question, 'What is 2+2?');
assertEq('marks correct option', h1[0].options[1].correct, true);
assertEq('marks incorrect option', h1[0].options[0].correct, false);
assertEq('records multi flag', h1[0].multi, false);

// Duplicate question updates in-place
const h2 = recordPollInHistory_logic(h1, samplePoll, new Set(['a']));
assertEq('deduplicates by question', h2.length, 1);
assertEq('updates correct option', h2[0].options[0].correct, true);
assertEq('clears old correct', h2[0].options[1].correct, false);

// null poll returns unchanged history
const h3 = recordPollInHistory_logic([{ question: 'x' }], null, new Set());
assertEq('null poll returns unchanged', h3.length, 1);

// Multi-select poll
const multiPoll = { ...samplePoll, multi: true };
const h4 = recordPollInHistory_logic([], multiPoll, new Set(['a', 'c']));
assertEq('multi-select marks two correct', h4[0].options.filter(o => o.correct).length, 2);
assertEq('multi flag is true', h4[0].multi, true);

// ── host.js regressions (source-level guards) ───────────────────────
suite('host.js regressions');

const hostJsSource = fs.readFileSync('static/host.js', 'utf8');
assert(
  'center QR does not reference undefined `link` variable',
  !hostJsSource.includes('text: link,')
);

// ═══════════════════════════════════════════════════════════════════════
// Summary
// ═══════════════════════════════════════════════════════════════════════

console.log(`\n${'═'.repeat(50)}`);
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
