/* AI-share distribution chart — shared by host.html and participant.html.
 *
 * AiShareChart.render(parts, points, opts)
 *   parts.plot   element above the axis: the bell curve is drawn here
 *   parts.names  element below the axis: names hang diagonally from it
 *   points       [{name, value}]  value 0 (all by hand) … 100 (all by AI)
 *   opts.me      name to highlight (the viewing participant)
 *   opts.inset   px from each edge of the plot to x=0 / x=100 — on the
 *                participant page this is the slider thumb radius, so the
 *                curve sits exactly over the slider that acts as its axis
 *   opts.axis    true → draw an axis line (host, which has no slider)
 *   opts.height  plot height in px
 *   opts.stickFrom  px above the names box where the leaders start (the axis)
 *   opts.names   false → no names under the axis; hovering a dot names it
 *
 * A smoothed density (Gaussian KDE, reflected at 0/100 so the bell does not
 * leak past the axis), one dot per answer sitting on the curve, the average
 * as an unlabelled dashed line, and optionally every name hanging diagonally
 * below the axis ("sticks"), spread apart just enough to stay legible. Tweened: on first render the plot grows open
 * and the bell rises; later answers morph it.
 *
 * Colors come from CSS custom properties set by the embedding page:
 *   --aishare-accent, --aishare-text, --aishare-muted, --aishare-me, --aishare-bg
 *   --aishare-future  (optional) the 95%+ slice of the curve — Simon Willison's
 *                     prophecy that by the end of 2026 half of developers will
 *                     have AI generate more than 95% of their code
 */
(function () {
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var GRID = 101;                 // density samples, one per percent
  var TOP = 26;                   // headroom above the tallest peak
  var STICK = 16;                 // leader from the axis down to the label
  var FONT = 13;
  var MAX_NAME = 22;
  var FUTURE = 95;                // from here on the curve is drawn green
  var FUTURE_COLOR = 'var(--aishare-future, #2f9e44)';

  function el(tag, attrs, parent) {
    var n = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  function shortName(name) {
    name = String(name || '?');
    return name.length > MAX_NAME ? name.slice(0, MAX_NAME - 1) + '…' : name;
  }

  function density(values) {
    var ys = new Array(GRID).fill(0);
    var n = values.length;
    if (!n) return ys;
    var mean = values.reduce(function (a, b) { return a + b; }, 0) / n;
    var sd = Math.sqrt(values.reduce(function (a, v) { return a + (v - mean) * (v - mean); }, 0) / n);
    // Silverman's rule, clamped: floored so one or two answers still make a
    // readable bell, capped so opposite camps stay two humps, not a flat line.
    var h = Math.min(12, Math.max(6, 1.06 * sd * Math.pow(n, -0.2)));
    for (var i = 0; i < GRID; i++) {
      var s = 0;
      for (var j = 0; j < n; j++) {
        // Reflect around both ends so the mass stays inside 0..100.
        [values[j], -values[j], 200 - values[j]].forEach(function (c) {
          var z = (i - c) / h;
          s += Math.exp(-0.5 * z * z);
        });
      }
      ys[i] = s / (n * h * Math.sqrt(2 * Math.PI));
    }
    return ys;
  }

  // Spread label anchors so neighbours are at least `gap` apart, staying as
  // close as possible to their true x and inside [lo, hi].
  function spread(xs, gap, lo, hi) {
    var out = xs.slice();
    for (var i = 1; i < out.length; i++) out[i] = Math.max(out[i], out[i - 1] + gap);
    if (out.length) {
      var shift = (out.reduce(function (a, b) { return a + b; }, 0) - xs.reduce(function (a, b) { return a + b; }, 0)) / out.length;
      for (var k = 0; k < out.length; k++) out[k] -= shift;
    }
    for (var a = 0; a < out.length; a++) out[a] = Math.max(out[a], a ? out[a - 1] + gap : lo);
    for (var b = out.length - 1; b >= 0; b--) out[b] = Math.min(out[b], b < out.length - 1 ? out[b + 1] - gap : hi);
    return out;
  }

  function ease(t) { return 1 - Math.pow(1 - t, 3); }

  function render(parts, points, opts) {
    var plot = parts.plot;
    points = (points || []).slice().sort(function (a, b) { return a.value - b.value || String(a.name).localeCompare(String(b.name)); });
    var st = plot._aishare || (plot._aishare = { ys: null, dots: {}, seen: {} });
    st.parts = parts; st.points = points; st.opts = opts || {};
    if (!st.ro && window.ResizeObserver) {
      st.ro = new ResizeObserver(function () {
        if (plot.clientWidth !== st.width) draw(plot, false);
      });
      st.ro.observe(plot);
    }
    draw(plot, true);
  }

  function draw(plot, animate) {
    var st = plot._aishare;
    var points = st.points, opts = st.opts, me = opts.me, names = st.parts.names;
    var W = Math.max(240, plot.clientWidth || 600);
    st.width = plot.clientWidth;
    var plotH = opts.height || 220;
    var inset = opts.inset || 12;
    var pw = W - 2 * inset;
    var X = function (v) { return inset + (v / 100) * pw; };
    var H = TOP + plotH;
    var y0 = H;                    // baseline = bottom edge of the plot = the axis
    var first = !st.ys;

    var target = density(points.map(function (p) { return p.value; }));
    var peak = Math.max.apply(null, target.concat([1e-9]));
    // Scale against a floor so a lone answer is a bump, not a spike.
    var scale = (plotH * 0.9) / Math.max(peak, 0.012);
    var targetPx = target.map(function (d) { return d * scale; });
    var fromPx = st.ys || new Array(GRID).fill(0);

    // ── Plot (above the axis) ──
    plot.innerHTML = '';
    plot.style.height = H + 'px';            // CSS transition turns this into "rising open"
    var svg = el('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, class: 'aishare-svg', role: 'img',
      'aria-label': 'Distribution of how much code is generated by AI' }, plot);
    var defs = el('defs', {}, svg);
    var grad = el('linearGradient', { id: 'aishare-fill-' + (opts.id || 'x'), x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el('stop', { offset: '0%', 'stop-color': 'var(--aishare-accent)', 'stop-opacity': 0.55 }, grad);
    el('stop', { offset: '100%', 'stop-color': 'var(--aishare-accent)', 'stop-opacity': 0.06 }, grad);
    var fgrad = el('linearGradient', { id: 'aishare-future-' + (opts.id || 'x'), x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el('stop', { offset: '0%', 'stop-color': FUTURE_COLOR, 'stop-opacity': 0.6 }, fgrad);
    el('stop', { offset: '100%', 'stop-color': FUTURE_COLOR, 'stop-opacity': 0.1 }, fgrad);

    [0, 25, 50, 75, 100].forEach(function (t) {
      // The % labels live in the page's scale bar above the plot.
      el('line', { x1: X(t), x2: X(t), y1: 0, y2: y0, stroke: 'var(--aishare-muted)', 'stroke-opacity': 0.2, 'stroke-dasharray': '2 4' }, svg);
    });

    var area = el('path', { fill: 'url(#aishare-fill-' + (opts.id || 'x') + ')' }, svg);
    var line = el('path', { fill: 'none', stroke: 'var(--aishare-accent)', 'stroke-width': 2.5, 'stroke-linejoin': 'round' }, svg);
    // The 95%+ slice, painted over the accent curve in green.
    var futureArea = el('path', { fill: 'url(#aishare-future-' + (opts.id || 'x') + ')' }, svg);
    var futureLine = el('path', { fill: 'none', stroke: FUTURE_COLOR, 'stroke-width': 2.5, 'stroke-linejoin': 'round' }, svg);
    if (opts.axis) el('line', { x1: X(0), x2: X(100), y1: y0 - 0.75, y2: y0 - 0.75, stroke: 'var(--aishare-muted)', 'stroke-width': 1.5 }, svg);

    var n = points.length;
    if (n) {
      var avg = points.reduce(function (a, p) { return a + p.value; }, 0) / n;
      var avgG = el('g', { class: animate && first ? 'aishare-avg' : '' }, svg);
      el('line', { x1: X(avg), x2: X(avg), y1: 4, y2: y0, stroke: 'var(--aishare-text)', 'stroke-width': 1.2, 'stroke-dasharray': '5 4', 'stroke-opacity': 0.7 }, avgG);
    }
    var dotsG = el('g', {}, svg);

    // ── Names (below the axis): diagonal sticks, spread so all of them fit ──
    var gap = Math.min(FONT + 6, n > 1 ? pw / (n - 1) : pw);
    var fontSize = Math.max(8, Math.min(FONT, gap - 3));
    var longest = points.reduce(function (m, p) { return Math.max(m, shortName(p.name).length); }, 0);
    var NH = STICK + longest * fontSize * 0.6 * Math.SQRT1_2 + fontSize + 6;
    var showNames = opts.names !== false;
    if (!showNames) NH = 0;
    names.innerHTML = '';
    names.style.height = NH + 'px';
    var nsvg = el('svg', { width: W, height: NH, viewBox: '0 0 ' + W + ' ' + NH, class: 'aishare-svg' }, names);
    // Leaders may start above the names box (e.g. from the slider, across the
    // "All by hand / All by AI" row) so each name still points at its answer.
    var stickFrom = opts.stickFrom || 0;
    var lx = spread(points.map(function (p) { return X(p.value); }), gap, X(0), X(100));

    var stackAt = {};
    var dots = points.map(function (p, i) {
      var isMe = me && p.name === me;
      var fresh = !st.seen[p.name];
      var ax = X(p.value);
      if (showNames) {
        var gi = el('g', { class: 'aishare-label' + (fresh && animate ? ' aishare-fresh' : '') + (isMe ? ' aishare-me' : ''),
          style: 'animation-delay:' + (fresh ? 300 + i * 35 : 0) + 'ms' }, nsvg);
        el('path', { d: 'M' + ax + ' ' + (-stickFrom) + ' L' + ax + ' 0 L' + lx[i] + ' ' + STICK, fill: 'none',
          stroke: isMe ? 'var(--aishare-me)' : 'var(--aishare-muted)', 'stroke-opacity': isMe ? 0.9 : 0.45, 'stroke-width': 1 }, gi);
        var ty = STICK + 4;
        var t = el('text', { x: lx[i], y: ty, 'text-anchor': 'end', 'font-size': fontSize,
          'font-weight': isMe ? 800 : 500, fill: isMe ? 'var(--aishare-me)' : 'var(--aishare-text)',
          transform: 'rotate(-45 ' + lx[i] + ' ' + ty + ')' }, gi);
        t.textContent = shortName(p.name);
      }

      var stack = stackAt[p.value] = (stackAt[p.value] || 0) + 1;
      // Hover names the dot (shared tooltip.js, no delay; the name only, the
      // position already says the %); a transparent
      // halo makes the 5px dot easy to hit.
      var dg = el('g', { class: 'aishare-dot', 'data-tip': p.name, 'data-tip-instant': '', 'data-value': p.value }, dotsG);
      el('circle', { r: 12, fill: 'transparent' }, dg);
      el('circle', { r: isMe ? 7 : 5, fill: isMe ? 'var(--aishare-me)' : 'var(--aishare-accent)',
        stroke: 'var(--aishare-bg, #fff)', 'stroke-width': 1.5 }, dg);
      var prev = st.dots[p.name];
      return { el: dg, fromX: prev ? prev.x : ax, toX: ax, value: p.value, stack: stack - 1,
        fromY: prev ? prev.y : null, delay: fresh && animate ? 250 + i * 35 : 0 };
    });
    st.seen = {}; points.forEach(function (p) { st.seen[p.name] = true; });

    function curveAt(ys, v) {
      return y0 - ys[Math.max(0, Math.min(GRID - 1, Math.round(v)))];
    }
    function paint(ys, t, elapsed) {
      var d = '';
      for (var i = 0; i < GRID; i++) d += (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + (y0 - ys[i]).toFixed(1);
      line.setAttribute('d', d);
      area.setAttribute('d', d + 'L' + X(100) + ' ' + y0 + 'L' + X(0) + ' ' + y0 + 'Z');
      var f = '';
      for (var k = FUTURE; k < GRID; k++) f += (k > FUTURE ? 'L' : 'M') + X(k).toFixed(1) + ' ' + (y0 - ys[k]).toFixed(1);
      futureLine.setAttribute('d', f);
      futureArea.setAttribute('d', f + 'L' + X(100) + ' ' + y0 + 'L' + X(FUTURE) + ' ' + y0 + 'Z');
      dots.forEach(function (o) {
        var local = Math.max(0, Math.min(1, (elapsed - o.delay) / 500));
        var x = o.fromX + (o.toX - o.fromX) * ease(local);
        var yOn = curveAt(ys, o.value) - o.stack * 10;
        // A new dot drops in from the top; a known one glides to its new spot.
        var y = o.fromY == null ? 6 + (yOn - 6) * ease(local) : o.fromY + (yOn - o.fromY) * ease(t);
        o.el.setAttribute('transform', 'translate(' + x.toFixed(1) + ' ' + y.toFixed(1) + ')');
        o.el.style.opacity = o.fromY == null && local === 0 ? 0 : 1;
        o.x = x; o.y = y;
      });
    }

    cancelAnimationFrame(st.raf);
    var duration = !animate ? 0 : (first ? 1100 : 450);
    var extra = dots.reduce(function (m, o) { return Math.max(m, o.delay + 500); }, 0);
    var start = performance.now();
    function frame(now) {
      var elapsed = now - start;
      var t = duration ? Math.min(1, elapsed / duration) : 1;
      var e = ease(t);
      var ys = targetPx.map(function (y, i) { return fromPx[i] + (y - fromPx[i]) * e; });
      st.ys = ys;
      paint(ys, t, animate ? elapsed : 1e9);
      if (t < 1 || (animate && elapsed < extra)) st.raf = requestAnimationFrame(frame);
      else st.dots = dots.reduce(function (m, o, i) { m[points[i].name] = { x: o.x, y: o.y }; return m; }, {});
    }
    if (animate) st.raf = requestAnimationFrame(frame);
    else frame(start + 1e6);
  }

  function reset(parts) {
    var plot = parts && parts.plot;
    var st = plot && plot._aishare;
    if (st) {
      cancelAnimationFrame(st.raf);
      if (st.ro) st.ro.disconnect();
      plot._aishare = null;
    }
    if (plot) { plot.innerHTML = ''; plot.style.height = '0px'; }
    if (parts && parts.names) { parts.names.innerHTML = ''; parts.names.style.height = '0px'; }
  }

  if (!document.getElementById('aishare-chart-style')) {
    var css = document.createElement('style');
    css.id = 'aishare-chart-style';
    css.textContent =
      '.aishare-svg{display:block;overflow:visible;font-family:inherit}' +
      '.aishare-dot{cursor:pointer}.aishare-dot circle:last-child{transition:r .12s}.aishare-dot:hover circle:last-child{r:8}' +
      '.aishare-fresh{opacity:0;animation:aishare-in .45s ease-out forwards}' +
      '.aishare-avg{animation:aishare-fade .6s ease-out .9s both}' +
      '@keyframes aishare-in{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}' +
      '@keyframes aishare-fade{from{opacity:0}to{opacity:1}}' +
      '@media (prefers-reduced-motion: reduce){.aishare-fresh,.aishare-avg{animation:none;opacity:1}}';
    document.head.appendChild(css);
  }

  window.AiShareChart = { render: render, reset: reset };
})();
