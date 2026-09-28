/* AI-share distribution chart — shared by host.html and participant.html.
 *
 * AiShareChart.render(container, points, opts)
 *   points: [{name, value}]  value 0 (all by hand) … 100 (all by AI)
 *   opts.me: name to highlight (the viewing participant)
 *
 * Draws a smoothed density curve (Gaussian KDE, reflected at 0/100 so the
 * bell does not leak past the axis), one dot per answer sitting on the curve,
 * and every name hanging diagonally below the axis ("sticks"), spread apart
 * just enough to stay legible. Transitions are tweened: the bell rises from
 * the axis the first time and morphs as answers move.
 *
 * Colors come from CSS custom properties set by the embedding page:
 *   --aishare-accent, --aishare-text, --aishare-muted, --aishare-me
 */
(function () {
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var GRID = 101;                 // density samples, one per percent
  var PLOT_H = 190;               // curve area height (px)
  var TOP = 34;                   // room for the end captions
  var STICK = 14;                 // leader from the axis down to the label
  var FONT = 12;
  var MAX_NAME = 16;

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

  function render(container, points, opts) {
    opts = opts || {};
    points = (points || []).slice().sort(function (a, b) { return a.value - b.value || String(a.name).localeCompare(String(b.name)); });
    var st = container._aishare || (container._aishare = { ys: null, dots: {}, seen: {} });
    st.points = points; st.opts = opts;
    if (!st.ro && window.ResizeObserver) {
      st.ro = new ResizeObserver(function () {
        if (container.clientWidth !== st.width) draw(container, false);
      });
      st.ro.observe(container);
    }
    draw(container, true);
  }

  function draw(container, animate) {
    var st = container._aishare;
    var points = st.points, me = st.opts.me;
    var W = Math.max(280, container.clientWidth || 600);
    st.width = container.clientWidth;

    var n = points.length;
    var longest = points.reduce(function (m, p) { return Math.max(m, shortName(p.name).length); }, 0);
    var labelDiag = longest * FONT * 0.58 * Math.SQRT1_2;      // projected size of a 45° label
    var ml = Math.max(18, Math.min(labelDiag, 110) + 6);         // labels hang down-left
    var mr = 18;
    var pw = W - ml - mr;
    var y0 = TOP + PLOT_H;
    var H = y0 + STICK + labelDiag + FONT + 8;
    var X = function (v) { return ml + (v / 100) * pw; };

    var target = density(points.map(function (p) { return p.value; }));
    var peak = Math.max.apply(null, target.concat([1e-9]));
    // Keep a single answer from filling the whole height: scale against a
    // floor so small groups look like a bump rather than a spike.
    var scale = (PLOT_H * 0.88) / Math.max(peak, 0.012);
    var targetPx = target.map(function (d) { return d * scale; });
    var fromPx = st.ys || new Array(GRID).fill(0);

    container.innerHTML = '';
    var svg = el('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, class: 'aishare-svg', role: 'img',
      'aria-label': 'Distribution of how much code is generated by AI' }, container);
    var defs = el('defs', {}, svg);
    var grad = el('linearGradient', { id: 'aishare-fill', x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el('stop', { offset: '0%', 'stop-color': 'var(--aishare-accent)', 'stop-opacity': 0.55 }, grad);
    el('stop', { offset: '100%', 'stop-color': 'var(--aishare-accent)', 'stop-opacity': 0.05 }, grad);

    // Captions + grid
    var cap = { 'font-size': 13, 'font-weight': 600, fill: 'var(--aishare-text)' };
    el('text', Object.assign({ x: ml, y: 18, 'text-anchor': 'start' }, cap), svg).textContent = '✍️ All by hand';
    el('text', Object.assign({ x: ml + pw, y: 18, 'text-anchor': 'end' }, cap), svg).textContent = 'All by AI 🤖';
    [0, 25, 50, 75, 100].forEach(function (t) {
      el('line', { x1: X(t), x2: X(t), y1: TOP, y2: y0, stroke: 'var(--aishare-muted)', 'stroke-opacity': 0.18, 'stroke-dasharray': '2 4' }, svg);
    });

    var area = el('path', { fill: 'url(#aishare-fill)' }, svg);
    var line = el('path', { fill: 'none', stroke: 'var(--aishare-accent)', 'stroke-width': 2.5, 'stroke-linejoin': 'round' }, svg);
    el('line', { x1: ml, x2: ml + pw, y1: y0, y2: y0, stroke: 'var(--aishare-muted)', 'stroke-width': 1.5 }, svg);
    [0, 25, 50, 75, 100].forEach(function (t) {
      el('text', { x: X(t), y: y0 - 5, 'text-anchor': t === 0 ? 'start' : t === 100 ? 'end' : 'middle',
        'font-size': 10, fill: 'var(--aishare-muted)' }, svg).textContent = t + '%';
    });

    // Average marker
    var avgG = null;
    if (n) {
      var avg = points.reduce(function (a, p) { return a + p.value; }, 0) / n;
      avgG = el('g', { class: animate && !st.ys ? 'aishare-avg' : '' }, svg);
      el('line', { x1: X(avg), x2: X(avg), y1: TOP + 6, y2: y0, stroke: 'var(--aishare-text)', 'stroke-width': 1.2, 'stroke-dasharray': '5 4', 'stroke-opacity': 0.7 }, avgG);
      el('text', { x: X(avg), y: TOP + 2, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700, fill: 'var(--aishare-text)' }, avgG)
        .textContent = 'avg ' + Math.round(avg) + '%';
    }

    // Names: diagonal sticks under the axis, spread so all of them fit.
    var gap = Math.min(FONT + 5, n > 1 ? pw / (n - 1) : pw);
    var fontSize = Math.max(8, Math.min(FONT, gap - 3));
    var lx = spread(points.map(function (p) { return X(p.value); }), gap, ml, ml + pw);
    var labelsG = el('g', {}, svg);
    var dotsG = el('g', {}, svg);
    var stackAt = {};
    var dots = points.map(function (p, i) {
      var isMe = me && p.name === me;
      var fresh = !st.seen[p.name];
      var gi = el('g', { class: 'aishare-label' + (fresh && animate ? ' aishare-fresh' : '') + (isMe ? ' aishare-me' : ''),
        style: 'animation-delay:' + (fresh ? 250 + i * 35 : 0) + 'ms' }, labelsG);
      var ax = X(p.value), ly = y0 + STICK;
      el('path', { d: 'M' + ax + ' ' + y0 + ' L' + lx[i] + ' ' + ly, fill: 'none',
        stroke: isMe ? 'var(--aishare-me)' : 'var(--aishare-muted)', 'stroke-opacity': isMe ? 0.9 : 0.45, 'stroke-width': 1 }, gi);
      var t = el('text', { x: lx[i], y: ly + 4, 'text-anchor': 'end', 'font-size': fontSize,
        'font-weight': isMe ? 800 : 500, fill: isMe ? 'var(--aishare-me)' : 'var(--aishare-text)',
        transform: 'rotate(-45 ' + lx[i] + ' ' + (ly + 4) + ')' }, gi);
      t.textContent = shortName(p.name) + ' · ' + p.value + '%';
      var ttl = el('title', {}, gi); ttl.textContent = p.name + ': ' + p.value + '% by AI';

      var k = p.value;
      var stack = stackAt[k] = (stackAt[k] || 0) + 1;
      var c = el('circle', { r: isMe ? 6.5 : 4.5, cx: ax, fill: isMe ? 'var(--aishare-me)' : 'var(--aishare-accent)',
        stroke: 'var(--aishare-bg, #fff)', 'stroke-width': 1.5 }, dotsG);
      var prev = st.dots[p.name];
      return { el: c, fromX: prev ? prev.x : ax, toX: ax, value: p.value, stack: stack - 1,
        fromY: prev ? prev.y : null, delay: fresh && animate ? 200 + i * 35 : 0 };
    });
    st.seen = {}; points.forEach(function (p) { st.seen[p.name] = true; });

    function curveAt(ys, v) {
      var i = Math.max(0, Math.min(GRID - 1, Math.round(v)));
      return y0 - ys[i];
    }
    function paint(ys, t, elapsed) {
      var d = '';
      for (var i = 0; i < GRID; i++) d += (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + (y0 - ys[i]).toFixed(1);
      line.setAttribute('d', d);
      area.setAttribute('d', d + 'L' + X(100) + ' ' + y0 + 'L' + X(0) + ' ' + y0 + 'Z');
      dots.forEach(function (o) {
        var local = Math.max(0, Math.min(1, (elapsed - o.delay) / 500));
        var e = ease(local);
        var x = o.fromX + (o.toX - o.fromX) * e;
        var yOn = curveAt(ys, o.value) - o.stack * 9;
        var y = o.fromY == null ? (TOP - 10) + (yOn - TOP + 10) * e : o.fromY + (yOn - o.fromY) * ease(t);
        if (o.fromY == null && local === 0) y = -20;
        o.el.setAttribute('cx', x.toFixed(1));
        o.el.setAttribute('cy', y.toFixed(1));
        o.x = x; o.y = y;
      });
    }

    cancelAnimationFrame(st.raf);
    var duration = !animate ? 0 : (st.ys ? 450 : 1100);
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
    st.raf = requestAnimationFrame(frame);
    if (!animate) frame(performance.now() + 1e6);
  }

  function reset(container) {
    var st = container && container._aishare;
    if (!st) return;
    cancelAnimationFrame(st.raf);
    if (st.ro) st.ro.disconnect();
    container._aishare = null;
    container.innerHTML = '';
  }

  if (!document.getElementById('aishare-chart-style')) {
    var css = document.createElement('style');
    css.id = 'aishare-chart-style';
    css.textContent =
      '.aishare-svg{display:block;overflow:visible;font-family:inherit}' +
      '.aishare-fresh{opacity:0;animation:aishare-in .45s ease-out forwards}' +
      '.aishare-avg{animation:aishare-fade .6s ease-out .9s both}' +
      '@keyframes aishare-in{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}' +
      '@keyframes aishare-fade{from{opacity:0}to{opacity:1}}' +
      '@media (prefers-reduced-motion: reduce){.aishare-fresh,.aishare-avg{animation:none;opacity:1}}';
    document.head.appendChild(css);
  }

  window.AiShareChart = { render: render, reset: reset };
})();
