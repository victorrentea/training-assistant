// Tests for largestRemainder() in participant.js
// Run with: node test_participant_js.js

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

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
