// Safety net: a page nobody is touching stops animating.
//
// Every visible element with an endless CSS animation makes Chrome present a new frame up to 60
// times a second, and the OS compositor redraws the screen for each one. On the trainer's Mac,
// while screen-sharing, that alone kept WindowServer above 90% CPU and made the mouse cursor lag.
// The known offenders were made finite or stepped in the stylesheets; this catches the rest, and
// whatever gets added later.
//
// Rule: after IDLE_MS without input, an endless animation that has itself been running for IDLE_MS
// is paused; any input resumes it. So a blink that starts on an idle page still gets its minute to
// call somebody over before it freezes. Finite animations are never touched: an entry animation
// paused on its first frame (opacity 0) would leave content invisible on a projector.
(function () {
  'use strict';
  var IDLE_MS = 60000;
  var SCAN_MS = 10000;
  var lastInput = performance.now();
  var paused = [];

  function resume() {
    var list = paused;
    paused = [];
    list.forEach(function (a) {
      // Still 'paused' = still attached to its element. One whose element or class went away
      // meanwhile is 'idle', and play() would bring it back from the dead.
      if (a.playState === 'paused') a.play();
    });
  }

  function onInput() {
    lastInput = performance.now();
    if (paused.length) resume();
  }

  function scan() {
    if (document.hidden || performance.now() - lastInput < IDLE_MS) return;
    document.getAnimations().forEach(function (a) {
      if (a.playState !== 'running' || !a.effect) return;
      if (a.effect.getComputedTiming().iterations !== Infinity) return;
      if (a.currentTime < IDLE_MS) return;
      a.pause();
      paused.push(a);
    });
  }

  ['pointermove', 'pointerdown', 'keydown', 'touchstart', 'wheel'].forEach(function (type) {
    window.addEventListener(type, onInput, { capture: true, passive: true });
  });
  setInterval(scan, SCAN_MS);
})();
