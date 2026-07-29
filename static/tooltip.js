/**
 * Shared tooltip component — the single tooltip implementation for every surface.
 *
 * Usage: put data-tip="some text" on any element. Nothing to initialize.
 *
 * Why a component: this app accumulated three tooltip systems (native title=,
 * a dead .has-tooltip CSS block, and a JS bubble wired only to the emoji bar).
 * They looked different because there was nothing to be consistent with. This
 * file carries both the behavior and the style so a page cannot pick up one
 * without the other, and tests/test_no_native_title.py fails the build if a
 * native title= comes back.
 *
 * Listeners are delegated on `document`, not on a host container — that was the
 * flaw that limited the original to #floating-reactions and kept it at two
 * usages. Markup injected later (host.js builds most of its UI from template
 * strings) works with no registration step.
 */
(function () {
  'use strict';

  var SHOW_DELAY_MS = 150;   // ~3x faster than the browser's native title delay
  var EDGE_MARGIN = 8;       // keep the bubble this far from the viewport edges
  var GAP = 10;              // distance between trigger and bubble

  var STYLE = [
    '#app-tooltip {',
    '  position: fixed;',
    '  left: 0; top: 0;',
    '  z-index: 60;',
    '  pointer-events: none;',
    '  background: rgba(20, 20, 22, 0.96);',
    '  color: #fff;',
    '  font-size: 1.25rem;',
    '  font-weight: 600;',
    '  line-height: 1.25;',
    '  padding: 0.6rem 0.9rem;',
    '  border-radius: 0.6rem;',
    '  max-width: 22rem;',
    '  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);',
    '  opacity: 0;',
    '  transform: translateY(4px);',
    '  transition: opacity 120ms ease, transform 120ms ease;',
    '}',
    /* The peek-in: sliding up while fading is what separates a tooltip that
       feels responsive from one that merely appears. */
    '#app-tooltip.visible { opacity: 1; transform: translateY(0); }'
  ].join('\n');

  var el = null;
  var timer = null;
  var current = null;

  function injectStyle() {
    var style = document.createElement('style');
    style.id = 'app-tooltip-style';
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  function bubble() {
    if (!el) {
      el = document.createElement('div');
      el.id = 'app-tooltip';
      el.setAttribute('role', 'tooltip');
      document.body.appendChild(el);
    }
    return el;
  }

  function show(target) {
    var text = target.getAttribute('data-tip');
    if (!text) return;  // conditional call sites legitimately render an empty tip

    var tip = bubble();
    tip.textContent = text;

    var r = target.getBoundingClientRect();
    var left = r.left + r.width / 2 - tip.offsetWidth / 2;
    left = Math.max(EDGE_MARGIN, Math.min(left, window.innerWidth - tip.offsetWidth - EDGE_MARGIN));

    var top = r.top - tip.offsetHeight - GAP;       // above the trigger…
    if (top < EDGE_MARGIN) top = r.bottom + GAP;    // …or below when there's no room

    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
    tip.classList.add('visible');
    current = target;
  }

  function hide() {
    clearTimeout(timer);
    current = null;
    if (el) el.classList.remove('visible');
  }

  function scheduleShow(target) {
    clearTimeout(timer);
    timer = setTimeout(function () { show(target); }, SHOW_DELAY_MS);
  }

  function targetFrom(event) {
    var node = event.target;
    if (!node || typeof node.closest !== 'function') return null;
    return node.closest('[data-tip]');
  }

  /**
   * Give the element an accessible name only when it lacks one. Buttons that
   * already read correctly (visible text, aria-label, aria-labelledby) must not
   * be overwritten — that would degrade them, not help.
   */
  function ensureAccessibleName(target) {
    if (target.getAttribute('aria-label') || target.getAttribute('aria-labelledby')) return;
    if ((target.textContent || '').trim()) return;
    var text = target.getAttribute('data-tip');
    if (text) target.setAttribute('aria-label', text);
  }

  document.addEventListener('mouseover', function (event) {
    var target = targetFrom(event);
    if (!target) return;
    ensureAccessibleName(target);
    scheduleShow(target);
  });

  document.addEventListener('mouseout', function (event) {
    var target = targetFrom(event);
    if (!target) return;
    // Moving between children of the same trigger is not a real exit.
    if (event.relatedTarget && target.contains(event.relatedTarget)) return;
    hide();
  });

  // Keyboard users get the same hint. focusin/focusout bubble; focus/blur do not.
  document.addEventListener('focusin', function (event) {
    var target = targetFrom(event);
    if (!target) return;
    ensureAccessibleName(target);
    scheduleShow(target);
  });
  document.addEventListener('focusout', function (event) {
    if (targetFrom(event)) hide();
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') hide();
  });

  // The bubble is position:fixed and positioned once, so a scroll would leave it
  // floating away from its trigger.
  window.addEventListener('scroll', function () { if (current) hide(); }, true);
  window.addEventListener('resize', function () { if (current) hide(); });

  // Mobile is out of scope, but a tooltip stuck open after a tap is a bug worth
  // not shipping.
  document.addEventListener('touchstart', hide, { passive: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectStyle);
  } else {
    injectStyle();
  }
})();
