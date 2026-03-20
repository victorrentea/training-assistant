// Shared utility functions used by both host.js and participant.js

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escDebate(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

const WC_COLORS = ['#7ecef4','#a78bfa','#34d399','#fbbf24','#f472b6','#60a5fa','#fb923c'];

const DEBATE_PHASES = [
  { key: 'side_selection', num: 1, label: 'Pick Sides' },
  { key: 'arguments',      num: 2, label: 'Arguments' },
  { key: 'prep',           num: 3, label: 'Preparation' },
  { key: 'live_debate',    num: 4, label: 'Live Debate' },
];

function getDebateSubPhases(firstSide) {
  if (!firstSide) return [];
  const other = firstSide === 'for' ? 'against' : 'for';
  const fl = firstSide.toUpperCase(), ol = other.toUpperCase();
  return [
    {key: `opening_${firstSide}`,  label: `Opening — ${fl}`,  side: firstSide, defaultSeconds: 120},
    {key: `opening_${other}`,       label: `Opening — ${ol}`,  side: other,      defaultSeconds: 120},
    {key: `rebuttal_${firstSide}`, label: `Rebuttal — ${fl}`, side: firstSide, defaultSeconds: 90},
    {key: `rebuttal_${other}`,      label: `Rebuttal — ${ol}`, side: other,      defaultSeconds: 90},
  ];
}

function _playDebateChime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'sine';
    osc.frequency.value = 880;
    gain.gain.value = 0.3;
    osc.start();
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);
    osc.stop(ctx.currentTime + 0.8);
  } catch(e) {}
}

function renderDebatePhaseStepper(currentPhase) {
  const currentIdx = DEBATE_PHASES.findIndex(p => p.key === currentPhase);
  return '<div class="debate-stepper">' + DEBATE_PHASES.map((p, i) => {
    let cls = 'debate-step';
    if (i < currentIdx) cls += ' debate-step-done';
    else if (i === currentIdx) cls += ' debate-step-active';
    return `<div class="${cls}"><span class="debate-step-num">${p.num}</span><span class="debate-step-label">${p.label}</span></div>`;
  }).join('<span class="debate-step-sep">›</span>') + '</div>';
}
