  let ws = null;
  let currentPoll = null;
  let pollActive = false;
  let voteCounts = {};
  let totalVotes = 0;
  let participantLocations = {};
  let correctOptIds = new Set(); // host-marked correct options for current poll
  let scores = {};               // participant_name -> score
  let cachedNames = [];          // last known participant names

  // ── Poll history (persisted in localStorage, keyed by today's date) ──
  const TODAY_KEY = `host_polls_${new Date().toISOString().slice(0, 10)}`;

  function loadPollHistory() {
    try { return JSON.parse(localStorage.getItem(TODAY_KEY) || '[]'); } catch { return []; }
  }

  function savePollHistory(history) {
    localStorage.setItem(TODAY_KEY, JSON.stringify(history));
  }

  function recordPollInHistory(poll, correctIds) {
    if (!poll) return;
    const history = loadPollHistory();
    const entry = {
      question: poll.question,
      options: poll.options.map(o => ({
        text: o.text,
        correct: correctIds.has(o.id),
      })),
      multi: !!poll.multi,
      recorded_at: new Date().toISOString(),
    };
    // Avoid duplicates by question
    const idx = history.findIndex(e => e.question === poll.question);
    if (idx >= 0) history[idx] = entry; else history.push(entry);
    savePollHistory(history);
  }

  function downloadPollHistory() {
    const history = loadPollHistory();
    if (!history.length) { toast('No polls recorded today'); return; }
    const lines = history.map((e, n) => {
      const opts = e.options.map((o, i) => `  ${String.fromCharCode(65+i)}. ${o.text}${o.correct ? ' ✅' : ''}`).join('\n');
      return `${n+1}. ${e.question}\n${opts}`;
    }).join('\n\n');
    const blob = new Blob([lines], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `polls_${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function loadCorrectOpts(question) {
    try {
      const saved = JSON.parse(localStorage.getItem('host_correct_' + question) || '[]');
      correctOptIds = new Set(saved);
    } catch { correctOptIds = new Set(); }
  }
  function saveCorrectOpts(question) {
    localStorage.setItem('host_correct_' + question, JSON.stringify([...correctOptIds]));
  }
  async function toggleCorrect(optId) {
    if (!currentPoll) return;
    if (correctOptIds.has(optId)) correctOptIds.delete(optId);
    else correctOptIds.add(optId);
    saveCorrectOpts(currentPoll.question);
    renderBars();
    recordPollInHistory(currentPoll, correctOptIds);
    // Post to backend to award points
    await fetch('/api/poll/correct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ correct_ids: [...correctOptIds] }),
    });
  }

  // Set participant link
  const link = `${location.protocol}//${location.host}/`;
  document.getElementById('participant-link').href = link;
  document.getElementById('participant-link').textContent = link;

  // ── WebSocket (host monitors state too) ──
  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/__host__`);

    ws.onopen = () => setBadge(true);
    ws.onclose = () => { setBadge(false); setTimeout(connectWS, 3000); };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'state') {
        const prevQuestion = currentPoll?.question;
        currentPoll = msg.poll;
        if (!msg.poll_active && pollActive) _clearTimer(); // poll just closed
        pollActive = msg.poll_active;
        if (currentPoll && currentPoll.question !== prevQuestion) loadCorrectOpts(currentPoll.question);
        voteCounts = msg.vote_counts || {};
        totalVotes = Object.values(voteCounts).reduce((a,b)=>a+b,0);
        participantLocations = msg.participant_locations || {};
        scores = msg.scores || {};
        document.getElementById('pax-count').textContent = msg.participant_count;
        renderParticipantList(msg.participant_names || []);
        renderDaemonStatus(msg.daemon_connected, msg.daemon_last_seen);
        renderPreview(msg.quiz_preview || null);
        renderPollDisplay();
      } else if (msg.type === 'vote_update') {
        voteCounts = msg.vote_counts || {};
        totalVotes = msg.total_votes || 0;
        renderBars();
      } else if (msg.type === 'participant_count') {
        document.getElementById('pax-count').textContent = msg.count;
        participantLocations = msg.locations || participantLocations;
        renderParticipantList(msg.names || []);
      } else if (msg.type === 'scores') {
        scores = msg.scores || {};
        renderParticipantList(cachedNames);
      } else if (msg.type === 'timer') {
        _applyTimer(msg.seconds, msg.started_at);
      } else if (msg.type === 'quiz_status') {
        renderQuizStatus(msg.status, msg.message);
      } else if (msg.type === 'quiz_preview') {
        renderPreview(msg.quiz || null);
      }
    };
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function setBadge(ok) {
    const b = document.getElementById('ws-badge');
    b.textContent = ok ? '● Connected' : '● Disconnected';
    b.className = `badge ${ok ? 'connected' : 'disconnected'}`;
  }

  function renderDaemonStatus(connected, lastSeenIso) {
    const el = document.getElementById('daemon-badge');
    if (!el) return;
    if (!lastSeenIso) {
      el.textContent = '🤖 Never';
      el.className = 'badge disconnected';
      el.title = 'Conversation access: never connected';
      return;
    }
    const ago = Math.round((Date.now() - new Date(lastSeenIso)) / 1000);
    const agoText = ago < 60 ? `${ago}s ago` : `${Math.round(ago/60)}m ago`;
    if (connected) {
      el.textContent = `🤖 ● ${agoText}`;
      el.className = 'badge connected';
      el.title = `Conversation access: active (last seen ${agoText})`;
    } else {
      el.textContent = `🤖 ${agoText}`;
      el.className = 'badge';
      el.style.cssText = 'background:#ffaa0022;color:var(--warn);border:1px solid var(--warn);';
      el.title = `Conversation access: idle (last seen ${agoText})`;
    }
  }

  function renderParticipantList(names) {
    cachedNames = names;
    const sorted = Object.keys(scores).length > 0
      ? [...names].sort((a, b) => (scores[b] || 0) - (scores[a] || 0))
      : names;
    const ul = document.getElementById('pax-list');
    ul.innerHTML = sorted.map(n => {
      const loc = participantLocations[n];
      const pts = scores[n];
      const scoreTag = pts ? `<span class="pax-score">⭐ ${pts}</span>` : '';
      return `<li>${n}${scoreTag}${loc ? `<span class="pax-location" onclick="openMap()" title="View all on map">📍 ${loc}</span>` : ''}</li>`;
    }).join('');
  }

  // ── Participant map ──
  let leafletMap = null;

  async function geocode(locationStr) {
    // If already "lat, lon" — parse directly
    const coordMatch = locationStr.match(/^(-?\d+\.?\d*),\s*(-?\d+\.?\d*)$/);
    if (coordMatch) return [parseFloat(coordMatch[1]), parseFloat(coordMatch[2])];

    // Strip timezone prefix if present
    const label = locationStr.replace(/^🕐\s*/, '');
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(label)}&format=json&limit=1`,
        { headers: { 'Accept-Language': 'en' } }
      );
      const data = await res.json();
      if (data.length > 0) return [parseFloat(data[0].lat), parseFloat(data[0].lon)];
    } catch { /* ignore */ }
    return null;
  }

  async function openMap() {
    document.getElementById('map-overlay').classList.add('open');

    // Init map lazily
    if (!leafletMap) {
      leafletMap = L.map('map-container').setView([20, 10], 2);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 18,
      }).addTo(leafletMap);
    }

    // Clear existing markers
    leafletMap.eachLayer(layer => { if (layer instanceof L.Marker) leafletMap.removeLayer(layer); });

    // Geocode each participant with a location and add markers
    const entries = Object.entries(participantLocations).filter(([, loc]) => loc);
    const points = [];

    await Promise.all(entries.map(async ([name, loc]) => {
      const coords = await geocode(loc);
      if (!coords) return;
      points.push(coords);
      L.marker(coords)
        .addTo(leafletMap)
        .bindPopup(`<strong>${name}</strong><br>${loc}`);
    }));

    // Fit map to markers
    if (points.length === 1) {
      leafletMap.setView(points[0], 6);
    } else if (points.length > 1) {
      leafletMap.fitBounds(L.latLngBounds(points), { padding: [40, 40] });
    }

    // Leaflet needs a size hint after the modal becomes visible
    setTimeout(() => leafletMap.invalidateSize(), 50);

    const count = points.length;
    document.getElementById('map-title').textContent =
      `Participant Locations (${count} of ${entries.length} mapped)`;
  }

  function closeMap(event) {
    if (event && event.target !== document.getElementById('map-overlay')) return;
    document.getElementById('map-overlay').classList.remove('open');
  }

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      closeMap();
      closeQR();
    }
  });

  // ── QR code ──
  const style = getComputedStyle(document.documentElement);
  new QRCode(document.getElementById('qr-code'), {
    text: link,
    width: 120,
    height: 120,
    colorDark: style.getPropertyValue('--text').trim(),
    colorLight: style.getPropertyValue('--surface').trim(),
  });

  // Fullscreen QR overlay
  const qrSize = Math.min(window.innerWidth, window.innerHeight) * 0.8;
  new QRCode(document.getElementById('qr-fullscreen'), {
    text: link,
    width: qrSize,
    height: qrSize,
    colorDark: '#000000',
    colorLight: '#ffffff',
  });
  document.getElementById('qr-overlay-url').textContent = link;

  document.getElementById('qr-code').addEventListener('click', () => {
    document.getElementById('qr-overlay').classList.add('open');
  });

  function closeQR() {
    document.getElementById('qr-overlay').classList.remove('open');
  }


  // ── Poll composer (contenteditable) ──
  const pollInput = document.getElementById('poll-input');

  // Read plain text lines from contenteditable div
  function getLines() {
    // innerText gives newline-separated lines reliably
    return (pollInput.innerText || '').split('\n');
  }

  function parsePollInput() {
    const lines = getLines();
    let question = '';
    const options = [];
    for (const line of lines) {
      const t = line.trim();
      if (!t) continue;
      if (!question) { question = t; continue; }
      options.push(t);
    }
    return { question, options };
  }

  // Reclassify child divs (lines) without touching their content
  function reclassifyLines() {
    const children = Array.from(pollInput.children);
    if (children.length === 0) return;

    let questionSeen = false;

    children.forEach(el => {
      const text = el.textContent.trim();
      if (!text) { el.className = 'blank-line'; return; }
      if (!questionSeen) { el.className = 'q-line'; questionSeen = true; }
      else el.className = 'opt-line';
    });
  }

  // Init with default content using divs (contenteditable line model)
  function initComposer(text) {
    const lines = text.split('\n');
    pollInput.innerHTML = lines.map(l => `<div>${l || '<br>'}</div>`).join('');
    reclassifyLines();
  }

  initComposer('How are you feeling today?\nEnergized\nGood enough\nA bit tired\nNeed coffee');

  pollInput.addEventListener('input', reclassifyLines);

  // Intercept paste: always insert as plain text to avoid rich-HTML corruption
  pollInput.addEventListener('paste', e => {
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text/plain');
    // Insert at current cursor position using execCommand (works in all browsers for contenteditable)
    document.execCommand('insertText', false, text);
  });

  pollInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      document.getElementById('create-btn').click();
    }
  });

  // ── Create poll ──
  document.getElementById('create-btn').addEventListener('click', async () => {
    const { question, options } = parsePollInput();

    if (!question) { toast('Enter a question'); return; }
    if (options.length < 2) { toast('Add at least 2 options'); return; }

    const multi = document.getElementById('multi-check').checked;
    const res = await fetch('/api/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, options, multi }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      await setPollStatus(true);
      toast('Poll created & opened ✓');
      pollInput.innerHTML = '<div><br></div>';
      document.getElementById('multi-check').checked = false;
      // Record poll in history (correct answers will be updated later via toggleCorrect)
      if (data.poll) recordPollInHistory(data.poll, new Set());
    } else {
      toast(data.detail || 'Error');
    }
  });

  // ── Timer ──
  let activeTimer = null;   // {seconds, started_at (ms)} or null
  let _timerInterval = null;

  async function startTimer(seconds) {
    const res = await fetch('/api/poll/timer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seconds }),
    });
    if (!res.ok) { const e = await res.json(); toast(e.detail || 'Error'); }
  }

  function _applyTimer(seconds, startedAtIso) {
    activeTimer = { seconds, startedAt: new Date(startedAtIso).getTime() };
    renderPollDisplay();
  }

  function _clearTimer() {
    activeTimer = null;
    clearInterval(_timerInterval);
    _timerInterval = null;
  }

  function _startHostCountdown() {
    clearInterval(_timerInterval);
    _timerInterval = setInterval(() => {
      const el = document.getElementById('host-countdown');
      if (!el || !activeTimer) { clearInterval(_timerInterval); return; }
      const elapsed = (Date.now() - activeTimer.startedAt) / 1000;
      const remaining = Math.max(0, activeTimer.seconds - elapsed);
      el.textContent = `⏱ ${Math.ceil(remaining)}s`;
      if (remaining <= 0) {
        _clearTimer();
        setPollStatus(false);
      }
    }, 200);
  }

  // ── Open / close / clear ──
  async function setPollStatus(open) {
    await fetch('/api/poll/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ open }),
    });
  }

  async function clearPoll() {
    await fetch('/api/poll', { method: 'DELETE' });
  }

  // ── Render ──
  function renderPollDisplay() {
    const el = document.getElementById('poll-display');
    if (!currentPoll) {
      el.innerHTML = `<p class="no-poll">No poll yet — create one above.</p>`;
      return;
    }

    const statusLabel = pollActive ? 'open' : (totalVotes > 0 ? 'closed' : 'draft');
    const statusText  = pollActive ? 'Voting open' : (totalVotes > 0 ? 'Voting closed' : 'Not started');

    const canMark = !pollActive && totalVotes > 0;
    const llmHints = canMark ? getLlmHints(currentPoll.question) : null;
    const bars = currentPoll.options.map((opt, i) => {
      const count = voteCounts[opt.id] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const maxCount = Math.max(...Object.values(voteCounts));
      const leading = count === maxCount && count > 0 ? 'leading' : '';
      const correct = correctOptIds.has(opt.id) ? 'correct' : '';
      const llmHint = llmHints && llmHints.includes(i) && !correct;
      const clickable = canMark ? `onclick="toggleCorrect('${opt.id}')" title="Click to mark as correct"` : '';
      return `
        <div class="result-row ${correct} ${canMark ? 'markable' : ''}" data-id="${opt.id}" ${clickable}>
          <div class="result-label">
            <span>${opt.text}${correct ? ' ✅' : ''}${llmHint ? ' <span class="llm-hint" title="LLM suggestion">☑</span>' : ''}</span>
            <span class="pct">${count} vote${count!==1?'s':''} · ${pct}%</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill ${leading}" style="width:${pct}%"></div>
          </div>
        </div>`;
    }).join('');

    const timerSection = pollActive ? `
      <div id="host-timer-area">
        ${activeTimer
          ? `<div class="countdown-display" id="host-countdown"></div>`
          : `<div class="timer-btns">
               <span style="font-size:.8rem;color:var(--muted);">Close in:</span>
               ${[5,10,15,20].map(s =>
                 `<button class="btn btn-warn" style="padding:.35rem .7rem;font-size:.82rem;min-height:unset;" onclick="startTimer(${s})">${s}s</button>`
               ).join('')}
             </div>`
        }
      </div>` : '';

    el.innerHTML = `
      <span class="status-pill ${statusLabel}">${statusText}</span>
      <span class="mode-pill">${currentPoll.multi ? '☑ Multi-select' : '◉ Single-select'}</span>
      <p class="poll-question">${currentPoll.question}</p>
      ${bars}
      <p style="font-size:.8rem; color:var(--muted); margin-top:.5rem;">${totalVotes} total vote${totalVotes!==1?'s':''}</p>
      ${timerSection}
      <div class="btn-row">
        ${!pollActive
          ? `<button class="btn btn-success" onclick="setPollStatus(true)">▶ Open voting</button>`
          : `<button class="btn btn-warn"    onclick="setPollStatus(false)">⏹ Close voting</button>`}
        <button class="btn btn-danger" onclick="clearPoll()">🗑 Remove poll</button>
      </div>`;

    if (pollActive && activeTimer) _startHostCountdown();
  }

  function renderBars() {
    if (!currentPoll) return;
    const maxCount = Math.max(...Object.values(voteCounts), 0);
    currentPoll.options.forEach(opt => {
      const row = document.querySelector(`.result-row[data-id="${opt.id}"]`);
      if (!row) return;
      const count = voteCounts[opt.id] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const fill = row.querySelector('.bar-fill');
      const pctEl = row.querySelector('.pct');
      const correct = correctOptIds.has(opt.id);
      row.className = `result-row${correct ? ' correct' : ''}${!pollActive && totalVotes > 0 ? ' markable' : ''}`;
      const labelSpan = row.querySelector('.result-label span:first-child');
      if (labelSpan) labelSpan.textContent = opt.text + (correct ? ' ✅' : '');
      if (fill) {
        fill.style.width = `${pct}%`;
        fill.className = `bar-fill ${count === maxCount && count > 0 ? 'leading' : ''}`;
      }
      if (pctEl) pctEl.textContent = `${count} vote${count!==1?'s':''} · ${pct}%`;
    });
    const totalEl = document.querySelector('#poll-display p[style]');
    if (totalEl) totalEl.textContent = `${totalVotes} total vote${totalVotes!==1?'s':''}`;
  }

  // ── Quiz generator ──
  async function requestQuiz() {
    const minutes = parseInt(document.getElementById('quiz-minutes').value, 10);
    const btn = document.getElementById('gen-quiz-btn');
    btn.disabled = true;
    renderQuizStatus('requested', `Waiting for daemon (last ${minutes} min)…`);
    try {
      await fetch('/api/quiz-request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ minutes }),
      });
    } catch (e) {
      renderQuizStatus('error', 'Failed to reach server.');
    }
    setTimeout(() => { btn.disabled = false; }, 5000);
  }

  let pendingPreview = null;
  let refiningTarget = null; // 'question' | 'opt0' | null

  function renderPreview(quiz) {
    const oldPreview = pendingPreview;
    pendingPreview = quiz;
    const card = document.getElementById('preview-card');
    const el = document.getElementById('preview-display');
    if (!quiz) { card.style.display = 'none'; refiningTarget = null; return; }
    card.style.display = '';
    el.innerHTML =
      `<div class="preview-question-row">` +
      `<p class="poll-question" style="margin:0; flex:1;">${escHtml(quiz.question)}</p>` +
      `<button class="refresh-btn" title="Generate new question" onclick="refinePreview('question')">↻</button>` +
      `</div>` +
      `<span class="mode-pill" style="margin-left:0; margin-bottom:.75rem;">${quiz.multi ? '☑ Multi-select' : '◉ Single-select'}</span>` +
      quiz.options.map((o, i) =>
        `<div class="preview-option">` +
        `<span>${escHtml(o)}</span>` +
        `<button class="refresh-btn" title="Regenerate this option" onclick="refinePreview('opt${i}')">↻</button>` +
        `</div>`
      ).join('');

    // Flash changed element after DOM update
    if (oldPreview && refiningTarget) {
      const target = refiningTarget;
      refiningTarget = null;
      requestAnimationFrame(() => _flashChanged(target, oldPreview, quiz));
    }
  }

  function _flashChanged(target, oldQuiz, newQuiz) {
    let el = null;
    if (target === 'question') {
      if (oldQuiz.question !== newQuiz.question) {
        el = document.querySelector('#preview-display .poll-question');
      }
    } else {
      const idx = parseInt(target.slice(3));
      if ((oldQuiz.options[idx] || '') !== (newQuiz.options[idx] || '')) {
        const opts = document.querySelectorAll('#preview-display .preview-option span');
        el = opts[idx] || null;
      }
    }
    if (!el) return;
    el.classList.add('preview-flash');
    setTimeout(() => el.classList.remove('preview-flash'), 1200);
  }

  async function refinePreview(target) {
    refiningTarget = target;
    _applyRefineGrayOut(target);
    try {
      const res = await fetch('/api/quiz-refine', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target }),
      });
      if (!res.ok) {
        refiningTarget = null;
        const err = await res.json();
        toast(err.detail || 'Error requesting refine');
      }
    } catch (e) {
      refiningTarget = null;
      toast('Failed to reach server');
    }
  }

  function _applyRefineGrayOut(target) {
    // Gray out the specific element being regenerated
    if (target === 'question') {
      const q = document.querySelector('#preview-display .poll-question');
      if (q) q.style.opacity = '.35';
    } else {
      const idx = parseInt(target.slice(3));
      const opts = document.querySelectorAll('#preview-display .preview-option');
      const span = opts[idx]?.querySelector('span');
      if (span) span.style.opacity = '.35';
    }
    // Disable ALL refresh buttons while in-flight
    document.querySelectorAll('#preview-display .refresh-btn').forEach(btn => {
      btn.disabled = true;
      btn.style.opacity = '.35';
    });
  }

  async function firePreview() {
    if (!pendingPreview) return;
    const res = await fetch('/api/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(pendingPreview),
    });
    if (res.ok) {
      // Store LLM's correct_indices hint keyed by question for post-close display
      if (pendingPreview.correct_indices?.length) {
        localStorage.setItem(
          'host_llm_hints_' + pendingPreview.question,
          JSON.stringify(pendingPreview.correct_indices)
        );
      }
      await setPollStatus(true);
      await fetch('/api/quiz-preview', { method: 'DELETE' });
      toast('Poll fired ✓');
    } else {
      const err = await res.json();
      toast(err.detail || 'Error firing poll');
    }
  }

  function getLlmHints(question) {
    try {
      return JSON.parse(localStorage.getItem('host_llm_hints_' + question) || 'null');
    } catch { return null; }
  }

  async function dismissPreview() {
    await fetch('/api/quiz-preview', { method: 'DELETE' });
  }

  async function resetScores() {
    if (!confirm('Reset all participant scores to zero?')) return;
    await fetch('/api/scores', { method: 'DELETE' });
    toast('Scores reset ✓');
  }

  function renderQuizStatus(status, message) {
    const el = document.getElementById('quiz-status');
    if (!el) return;
    const colors = { requested: 'var(--muted)', generating: 'var(--warn)', done: 'var(--accent2)', error: 'var(--danger)' };
    const icons  = { requested: '⏳', generating: '⚙️', done: '✅', error: '❌' };
    el.style.color = colors[status] || 'var(--muted)';
    // Keep it short for the inline position
    el.textContent = `${icons[status] || ''} ${message}`;
    el.title = message;
  }

  function toast(msg) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 2500);
  }


  connectWS();
