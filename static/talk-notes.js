// The trainer's notes file, as the talk phones show it (talk.html › Notes).
//
// A mirror of "Vic Presentation" in the trainer's VS Code (victor-vsc:
// presentation.js + bullets.js): the same circles on the leading marker, the
// same folding by indentation, and the same three brightness levels — white on
// what he is saying now (his line and its parents, or the text he selected),
// grey on the rest of its block, barely visible elsewhere.
//
// Pure functions first (tested by tests/test_talk_notes_js.js under node), then
// `render`, which builds the DOM. No dependencies.
(function (root) {
  'use strict';

  var TAB = 4;

  function indentOf(text) {
    var width = 0;
    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      if (ch === ' ') width++;
      else if (ch === '\t') width += TAB - (width % TAB);
      else break;
    }
    return width;
  }

  function isBlank(text) { return text.trim() === ''; }

  // The marker: the first non-blank character, when a space and then more text
  // follow it (a lone character is just a word being typed). `+` green, `-` red, any other single character blue.
  // Returns {kind, col} or null. Same rule as bullets.js in victor-vsc.
  var MARKER_RE = /^([ \t]*)(\S)(?=[ \t]+\S)/u;
  function markerOf(text) {
    var m = MARKER_RE.exec(text);
    if (!m) return null;
    var kind = m[2] === '+' ? 'plus' : m[2] === '-' ? 'minus' : 'info';
    return { kind: kind, col: m[1].length, ch: m[2] };
  }

  // Indentation folding, as VS Code does it for plain text: a non-blank line
  // folds when the next non-blank line is indented deeper; the region runs to
  // the last non-blank line indented deeper than the header. Returns
  // {header: end} (0-based, end inclusive).
  function foldRegions(lines) {
    var out = {};
    var n = lines.length;
    for (var i = 0; i < n; i++) {
      if (isBlank(lines[i])) continue;
      var own = indentOf(lines[i]);
      var end = -1;
      for (var j = i + 1; j < n; j++) {
        if (isBlank(lines[j])) continue;
        if (indentOf(lines[j]) <= own) break;
        end = j;
      }
      if (end > i) out[i] = end;
    }
    return out;
  }

  function sectionAround(line, lines) {
    if (line < 0 || line >= lines.length || isBlank(lines[line])) return null;
    var start = line, end = line;
    while (start > 0 && !isBlank(lines[start - 1])) start--;
    while (end < lines.length - 1 && !isBlank(lines[end + 1])) end++;
    return [start, end];
  }

  function sectionAbove(line, lines) {
    for (var i = Math.min(line, lines.length) - 1; i >= 0; i--) {
      if (!isBlank(lines[i])) return sectionAround(i, lines);
    }
    return null;
  }

  // The line plus its parents in the section (each line less indented than the
  // last one found, going up), top to bottom.
  function lineWithParents(line, sectionStart, lines) {
    var out = [line];
    var indent = indentOf(lines[line]);
    for (var i = line - 1; i >= sectionStart && indent > 0; i--) {
      var own = indentOf(lines[i]);
      if (own < indent) { out.unshift(i); indent = own; }
    }
    return out;
  }

  // Brightness of every line: 'bright' | 'dim' | 'fade'. A non-empty selection
  // lights its own lines (and the parents of its first one); otherwise the
  // cursor line and its parents. On a blank line the block above stays grey,
  // with its chapter (topmost parent of its last line) white.
  function levels(lines, line, selection) {
    var n = lines.length;
    var out = new Array(n);
    for (var i = 0; i < n; i++) out[i] = 'fade';
    if (!n) return out;
    var bright = [];
    var span = null;
    if (selection) {
      var first = selection.start_line, last = selection.end_line;
      if (selection.end_char === 0 && last > first) last--;
      var a = sectionAround(first, lines) || [first, first];
      var b = sectionAround(last, lines) || [last, last];
      span = [Math.min(a[0], first), Math.max(b[1], last)];
      for (var s = first; s <= last; s++) bright.push(s);
      bright = bright.concat(lineWithParents(first, span[0], lines));
    } else {
      var cur = Math.min(Math.max(0, line || 0), n - 1);
      span = sectionAround(cur, lines);
      if (span) {
        bright = lineWithParents(cur, span[0], lines);
      } else {
        span = sectionAbove(cur, lines);
        if (span) bright = [lineWithParents(span[1], span[0], lines)[0]];
      }
    }
    if (span) for (var d = span[0]; d <= span[1]; d++) out[d] = 'dim';
    bright.forEach(function (l) { if (l >= 0 && l < n) out[l] = 'bright'; });
    return out;
  }

  // Which lines show, given the header lines that are collapsed: the lines of a
  // collapsed region are hidden, the header stays.
  function hiddenLines(regions, isCollapsed, n) {
    var hidden = [];
    for (var k = 0; k < n; k++) hidden.push(false);
    for (var i = 0; i < n; i++) {
      if (hidden[i] || !(i in regions) || !isCollapsed(i)) continue;
      for (var j = i + 1; j <= regions[i]; j++) hidden[j] = true;
    }
    return hidden;
  }

  // The line to scroll to for `line`: itself, or the visible header whose
  // collapsed region hides it.
  function visibleLineFor(line, hidden) {
    var l = line;
    while (l > 0 && hidden[l]) l--;
    return l;
  }

  // ── DOM ──────────────────────────────────────────────────────────────────────

  var URL_RE = /\bhttps?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]]/g;

  function appendText(parent, text) {
    var last = 0, m;
    URL_RE.lastIndex = 0;
    while ((m = URL_RE.exec(text))) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      var a = document.createElement('a');
      a.href = m[0];
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = m[0];
      parent.appendChild(a);
      last = m.index + m[0].length;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }

  // [from, to) of line `l` that the selection covers, or null.
  function selectedSpan(selection, l, length) {
    if (!selection || l < selection.start_line || l > selection.end_line) return null;
    var from = l === selection.start_line ? selection.start_char : 0;
    var to = l === selection.end_line ? selection.end_char : length;
    from = Math.min(from, length); to = Math.min(to, length);
    return to > from ? [from, to] : null;
  }

  // Draw the notes into `container`. `opts`:
  //   text, line, selection   — the trainer's notes and where he is
  //   isCollapsed(header, text) — folded state of a header line (trainer's, or
  //                               the reader's own choice)
  //   onToggle(header, text, collapsedNow) — the reader tapped a chevron
  // Returns {lineEl(l)}: the element to scroll to for line l.
  function render(container, opts) {
    var lines = String(opts.text || '').replace(/\r\n?/g, '\n').split('\n');
    var n = lines.length;
    var regions = foldRegions(lines);
    var collapsed = function (i) { return opts.isCollapsed(i, lines[i].trim()); };
    var hidden = hiddenLines(regions, collapsed, n);
    var lv = levels(lines, opts.line, opts.selection);
    var frag = document.createDocumentFragment();
    var els = new Array(n);
    for (var i = 0; i < n; i++) {
      if (hidden[i]) continue;
      var text = lines[i];
      var row = document.createElement('div');
      row.className = 'nl nl-' + lv[i] + (i === opts.line && !opts.selection ? ' nl-cur' : '');
      row.dataset.line = String(i);
      els[i] = row;
      if (isBlank(text)) {
        row.classList.add('nl-blank');
        frag.appendChild(row);
        continue;
      }
      var indent = indentOf(text);
      row.style.setProperty('--ind', String(indent));
      if (i in regions) {
        var isColl = collapsed(i);
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'nl-fold' + (isColl ? ' nl-fold-collapsed' : '');
        btn.setAttribute('aria-label', isColl ? 'Expand' : 'Collapse');
        btn.setAttribute('aria-expanded', isColl ? 'false' : 'true');
        btn.innerHTML = '<span class="material-symbols-outlined">chevron_right</span>';
        btn.addEventListener('click', (function (h, t, c) {
          return function (e) { e.stopPropagation(); opts.onToggle(h, t, !c); };
        })(i, text.trim(), isColl));
        row.appendChild(btn);
      }
      var body = document.createElement('span');
      body.className = 'nl-body';
      var rest = text.replace(/^[ \t]+/, '');
      var offset = text.length - rest.length;
      var mk = markerOf(text);
      if (mk) {
        row.classList.add('nl-has-mark');
        var dot = document.createElement('span');
        dot.className = 'nl-mark nl-mark-' + mk.kind;
        dot.textContent = mk.ch;
        body.appendChild(dot);
        // The gap after the circle is its margin, so wrapped lines line up
        // with the text, not with the space.
        var gap = /^[ \t]*/.exec(rest.slice(mk.ch.length))[0].length;
        rest = rest.slice(mk.ch.length + gap);
        offset += mk.ch.length + gap;
      }
      var sel = selectedSpan(opts.selection, i, text.length);
      if (sel) {
        var a = Math.max(sel[0] - offset, 0), b = Math.max(sel[1] - offset, 0);
        appendText(body, rest.slice(0, a));
        var mark = document.createElement('span');
        mark.className = 'nl-sel';
        appendText(mark, rest.slice(a, b));
        if (b > a) body.appendChild(mark);
        appendText(body, rest.slice(b));
      } else {
        appendText(body, rest);
      }
      if ((i in regions) && collapsed(i)) {
        var more = document.createElement('span');
        more.className = 'nl-more';
        more.innerHTML = '<i></i><i></i><i></i>';
        more.addEventListener('click', (function (h, t) {
          return function (e) { e.stopPropagation(); opts.onToggle(h, t, false); };
        })(i, text.trim()));
        body.appendChild(more);
      }
      row.appendChild(body);
      frag.appendChild(row);
    }
    container.replaceChildren(frag);
    return {
      lineEl: function (l) {
        if (!n) return null;
        return els[visibleLineFor(Math.min(Math.max(0, l || 0), n - 1), hidden)] || null;
      }
    };
  }

  var api = {
    indentOf: indentOf, markerOf: markerOf, foldRegions: foldRegions, levels: levels,
    hiddenLines: hiddenLines, visibleLineFor: visibleLineFor, selectedSpan: selectedSpan,
    render: render
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.TalkNotes = api;
})(this);
