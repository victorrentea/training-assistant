  let ws = null;
  let currentPoll = null;
  let pollActive = false;
  let voteCounts = {};
  let totalVotes = 0;
  let participantLocations = {};
  const resolvedCities = {};   // raw "lat, lon" -> resolved city string cache
  let correctOptIds = new Set(); // host-marked correct options for current poll
  let scores = {};               // participant_name -> score
  let cachedNames = [];          // last known participant names

  let hostWords = [];
  let _hostWcDebounceTimer = null;
  const WC_COLORS = ['#7ecef4','#a78bfa','#34d399','#fbbf24','#f472b6','#60a5fa','#fb923c'];

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
    if (correctOptIds.has(optId)) {
      correctOptIds.delete(optId);
    } else {
      if (!currentPoll.multi && correctOptIds.size > 0) correctOptIds.clear(); // single-select: only one correct
      const cap = currentPoll.correct_count;
      if (cap && correctOptIds.size >= cap) return; // multi-select: cap at correct_count
      correctOptIds.add(optId);
    }
    saveCorrectOpts(currentPoll.question);
    renderBars();
    recordPollInHistory(currentPoll, correctOptIds);
    // Post to backend to award points
    const resp = await fetch('/api/poll/correct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ correct_ids: [...correctOptIds] }),
    });
    if (!resp.ok) toast('Failed to save correct options');
  }

  // Set participant link
  const link = `${location.protocol}//${location.host}/`;
  document.getElementById('participant-link').href = link;
  document.getElementById('participant-link').textContent = location.host;

  // ── WebSocket (host monitors state too) ──
  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/__host__`);

    let _kicked = false;
    ws.onopen = () => setBadge(true);
    ws.onclose = () => { setBadge(false); if (!_kicked) setTimeout(connectWS, 3000); };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'kicked') {
        _kicked = true;
        document.body.insertAdjacentHTML('beforeend', `
          <div id="kicked-overlay" style="position:fixed;inset:0;background:rgba(0,0,0,.92);display:flex;
            align-items:center;justify-content:center;z-index:9999;font-size:1.4rem;color:#fff;
            text-align:center;padding:2rem;flex-direction:column;gap:1rem;">
            <div>This session is being taken over by another tab.</div>
            <div style="font-size:1rem;color:#aaa;">This tab will close in <span id="kicked-count">5</span>s…</div>
          </div>`);
        let n = 5;
        const tick = setInterval(() => {
          n--;
          const el = document.getElementById('kicked-count');
          if (el) el.textContent = n;
          if (n <= 0) {
            clearInterval(tick);
            try { window.close(); } catch(e) {}
            // fallback: navigate away if window.close() was blocked
            document.getElementById('kicked-overlay').innerHTML =
              '<div>Session taken over.<br>You may close this tab.</div>';
          }
        }, 1000);
        return;
      }
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
        const currentActivity = msg.current_activity || 'none';
        updateCenterPanel(currentActivity);
        if (currentActivity === 'wordcloud') {
          renderHostWordCloud(msg.wordcloud_words || {});
        }
        if (currentActivity === 'qa') {
          renderQAList(msg.qa_questions || []);
        }
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
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function setBadge(ok) {
    const b = document.getElementById('ws-badge');
    b.textContent = ok ? '● Server' : '● Server';
    b.className = `badge ${ok ? 'connected' : 'disconnected'}`;
  }

  function renderDaemonStatus(connected, lastSeenIso) {
    const el = document.getElementById('daemon-badge');
    if (!el) return;
    if (!lastSeenIso) {
      el.textContent = '● Agent';
      el.className = 'badge disconnected';
      el.style.cssText = '';
      el.title = 'Agent: never connected';
      return;
    }
    const ago = Math.round((Date.now() - new Date(lastSeenIso)) / 1000);
    const agoText = ago < 60 ? `${ago}s` : `${Math.round(ago/60)}m`;
    if (connected) {
      el.textContent = '● Agent';
      el.className = 'badge connected';
      el.style.cssText = '';
      el.title = `Agent active (last seen ${agoText} ago)`;
    } else {
      el.textContent = '● Agent';
      el.className = 'badge';
      el.style.cssText = 'color:var(--warn);border:1px solid var(--warn);';
      el.title = `Agent idle (last seen ${agoText} ago)`;
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
      const scoreTag = pts ? `<span class="pax-score">⭐ ${pts} pts</span>` : '';
      const locLabel = loc ? resolvedCities[loc] || loc : null;
      return `<li>${escHtml(n)}${scoreTag}${locLabel ? `<span class="pax-location" onclick="openMap()" title="View all on map">📍 ${escHtml(locLabel)}</span>` : ''}</li>`;
    }).join('');

    // Lazily resolve any raw "lat, lon" strings to city names
    sorted.forEach(n => {
      const loc = participantLocations[n];
      if (!loc || resolvedCities[loc]) return;
      const coordMatch = loc.match(/^(-?\d+\.?\d*),\s*(-?\d+\.?\d*)$/);
      if (!coordMatch) return;
      resolvedCities[loc] = loc; // placeholder to avoid duplicate requests
      fetch(`https://nominatim.openstreetmap.org/reverse?lat=${coordMatch[1]}&lon=${coordMatch[2]}&format=json`,
        { headers: { 'Accept-Language': 'en' } })
        .then(r => r.json())
        .then(data => {
          const city = data.address?.city || data.address?.town || data.address?.village || data.address?.county || '';
          const country = data.address?.country_code?.toUpperCase() || data.address?.country || '';
          resolvedCities[loc] = [city, country].filter(Boolean).join(', ') || loc;
          renderParticipantList(cachedNames);
        })
        .catch(() => { resolvedCities[loc] = loc; });
    });
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
  const centerPanel = document.getElementById('center-qr');
  const qrSize = (Math.min(centerPanel.offsetWidth, centerPanel.offsetHeight) || 400) * 0.8;
  // Center QR: light gray (muted), click to brighten for 5s
  new QRCode(document.getElementById('qr-code'), {
    text: link,
    width: qrSize,
    height: qrSize,
    colorDark: '#888888',
    colorLight: 'transparent',
  });

  // Fullscreen QR overlay (opened from bottom-right icon)
  const qrFullSize = Math.min(window.innerWidth, window.innerHeight) * 0.8;
  new QRCode(document.getElementById('qr-fullscreen'), {
    text: link,
    width: qrFullSize,
    height: qrFullSize,
    colorDark: '#000000',
    colorLight: '#ffffff',
  });
  document.getElementById('qr-overlay-url').textContent = link;

  // Center QR: click to brighten for 5s then fade back
  let _qrBrightenTimer = null;
  document.getElementById('qr-code').addEventListener('click', () => {
    const el = document.getElementById('qr-code');
    el.classList.add('qr-bright');
    clearTimeout(_qrBrightenTimer);
    _qrBrightenTimer = setTimeout(() => el.classList.remove('qr-bright'), 5000);
  });

  // Bottom-right icon: click to open fullscreen overlay
  document.getElementById('qr-icon').addEventListener('click', () => {
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

  initComposer('Which is the primary benefit of the Circuit Breaker pattern?\n\nPrevents cascading failures across services\nImproves response time under normal load\nReduces the number of network calls\nEnables automatic service discovery');

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

  // ── Multi-check: show/hide correct-count spinner ──
  document.getElementById('multi-check').addEventListener('change', function () {
    document.getElementById('correct-count-label').style.display = this.checked ? 'flex' : 'none';
  });

  // ── Create poll ──
  document.getElementById('create-btn').addEventListener('click', async () => {
    const { question, options } = parsePollInput();

    if (!question) { toast('Enter a question'); return; }
    if (options.length < 2) { toast('Add at least 2 options'); return; }

    const multi = document.getElementById('multi-check').checked;
    const correctCountEl = document.getElementById('correct-count');
    const correct_count = multi ? (parseInt(correctCountEl.value) || null) : null;
    const res = await fetch('/api/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, options, multi, correct_count }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      // Erase stale correct-opts and LLM hints for this question
      localStorage.removeItem('host_correct_' + question);
      localStorage.removeItem('host_llm_hints_' + question);
      correctOptIds = new Set();
      await setPollStatus(true);
      toast('Poll created & opened ✓');
      pollInput.innerHTML = '<div><br></div>';
      document.getElementById('multi-check').checked = false;
      document.getElementById('correct-count-label').style.display = 'none';
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
      el.textContent = `⏱ Closing in ${Math.ceil(remaining)}s`;
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
      const pillsEl = document.getElementById('poll-pills');
      if (pillsEl) pillsEl.innerHTML = '';
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
      const isCorrect = canMark && correctOptIds.has(opt.id);
      const correct = isCorrect ? 'correct' : '';
      const llmHint = llmHints && llmHints.includes(i) && !isCorrect;
      const clickable = canMark ? `onclick="toggleCorrect('${opt.id}')" title="Click to mark as correct"` : '';
      return `
        <div class="result-row ${correct} ${canMark ? 'markable' : ''}" data-id="${opt.id}" ${clickable}>
          <div class="result-label">
            <span>${escHtml(opt.text)}${isCorrect ? ' ✅' : ''}${llmHint ? ' <span class="llm-hint" title="AI suggestion">✅ 🤔</span>' : ''}</span>
            <span class="pct">${count} vote${count!==1?'s':''} · ${pct}%</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill ${leading}" style="width:${pct}%"></div>
          </div>
        </div>`;
    }).join('');

    const timerBtns = pollActive && !activeTimer
      ? `<span class="timer-slider-wrap">
           <span id="timer-val" class="timer-val">15s</span>
           <input type="range" id="timer-slider" class="timer-slider" min="5" max="30" value="15"
             oninput="document.getElementById('timer-val').textContent=this.value+'s'; document.getElementById('timer-tip').style.opacity='1'"
             onmouseup="startTimer(+this.value)" ontouchend="startTimer(+this.value)" />
           <span id="timer-tip" class="timer-tip">Drop to set the time left</span>
         </span>`
      : '';

    const pillsEl = document.getElementById('poll-pills');
    if (pillsEl) {
      const countHint = currentPoll.multi && currentPoll.correct_count
        ? ` · ${currentPoll.correct_count} correct` : '';
      pillsEl.innerHTML =
        `<span class="mode-pill">${currentPoll.multi ? '☑ Multi-select' : '◉ Single-select'}${countHint}</span>`;
    }

    el.className = pollActive ? 'voting-active' : '';
    el.innerHTML = `
      <p class="poll-question">${escHtml(currentPoll.question)}</p>
      <div class="bars-container">
        <div class="bars-wrapper">${bars}</div>
        ${pollActive ? `<div class="voting-dots"><div class="voting-dots-row"><span></span><span></span><span></span></div><div class="voting-dots-label">voting in progress</div></div>` : ''}
      </div>
      <p style="font-size:.8rem; color:var(--muted); margin-top:.5rem;">${totalVotes} total vote${totalVotes!==1?'s':''}</p>
      ${currentPoll.source ? `<p class="poll-source-ref">📖 ${escHtml(currentPoll.source)}${currentPoll.page ? `, p. ${escHtml(currentPoll.page)}` : ''}</p>` : ''}
      <div class="btn-row">
        <span class="status-pill ${statusLabel}">${statusText}</span>
        ${!pollActive
          ? `<button class="btn btn-success" onclick="setPollStatus(true)">${totalVotes > 0 ? '↺ Re-open' : '▶ Open voting'}</button>`
          : !activeTimer ? `<button class="btn btn-warn" onclick="setPollStatus(false)">⏹ Close voting</button>` : ''}
        ${pollActive && activeTimer ? `<div class="countdown-display" id="host-countdown"></div>` : ''}
        ${timerBtns}
        <button class="btn btn-danger" onclick="clearPoll()">✕ Close poll</button>
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
      const canMarkNow = !pollActive && totalVotes > 0;
      const isCorrect = canMarkNow && correctOptIds.has(opt.id);
      row.className = `result-row${isCorrect ? ' correct' : ''}${canMarkNow ? ' markable' : ''}`;
      const labelSpan = row.querySelector('.result-label span:first-child');
      if (labelSpan) {
        const hints = canMarkNow ? getLlmHints(currentPoll.question) : null;
        const llmHint = hints && hints.includes(currentPoll.options.indexOf(opt)) && !isCorrect;
        labelSpan.innerHTML = escHtml(opt.text) + (isCorrect ? ' ✅' : '') +
          (llmHint ? ' <span class="llm-hint" title="AI suggestion">✅ 🤔</span>' : '');
      }
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
  function updateGenBtn() {
    const topic = document.getElementById('quiz-topic').value.trim();
    const btn = document.getElementById('gen-quiz-btn');
    btn.textContent = topic ? '🔍 Generate from topic' : '💬 Generate from transcript';
  }

  async function requestQuiz() {
    const topic = document.getElementById('quiz-topic').value.trim();
    const btn = document.getElementById('gen-quiz-btn');
    btn.disabled = true;
    let body, statusMsg;
    if (topic) {
      body = { topic };
      statusMsg = `Waiting… (topic: ${topic})`;
    } else {
      const minutes = parseInt(document.getElementById('quiz-minutes').value, 10);
      body = { minutes };
      statusMsg = `Waiting… (${minutes}m)`;
    }
    renderQuizStatus('requested', statusMsg);
    try {
      await fetch('/api/quiz-request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
    const sourceRef = quiz.source
      ? `<p class="poll-source-ref">📖 ${escHtml(quiz.source)}${quiz.page ? `, p. ${escHtml(quiz.page)}` : ''}</p>`
      : '';
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
      ).join('') +
      sourceRef;

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
    const payload = { ...pendingPreview };
    if (payload.multi && payload.correct_indices?.length) {
      payload.correct_count = payload.correct_indices.length;
    }
    const res = await fetch('/api/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
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
    const icons  = { requested: '⏳', generating: '⚙️', done: '', error: '❌' };
    el.style.color = colors[status] || 'var(--muted)';
    el.textContent = `${icons[status] || ''} ${message}`;
    el.title = message;
  }

  function toast(msg) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 2500);
  }


  async function switchTab(tab) {
    document.getElementById('tab-poll').classList.toggle('active', tab === 'poll');
    document.getElementById('tab-wordcloud').classList.toggle('active', tab === 'wordcloud');
    document.getElementById('tab-qa').classList.toggle('active', tab === 'qa');
    document.getElementById('tab-content-poll').style.display = tab === 'poll' ? '' : 'none';
    document.getElementById('tab-content-wordcloud').style.display = tab === 'wordcloud' ? '' : 'none';
    document.getElementById('tab-content-qa').style.display = tab === 'qa' ? '' : 'none';

    // Tell server — participants follow the active tab
    await fetch('/api/activity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ activity: tab }),
    });
  }

  function updateCenterPanel(currentActivity) {
    document.getElementById('center-qr').style.display = currentActivity === 'none' ? '' : 'none';
    document.getElementById('center-poll').style.display = currentActivity === 'poll' ? '' : 'none';
    document.getElementById('center-wordcloud').style.display = currentActivity === 'wordcloud' ? '' : 'none';
    document.getElementById('center-qa').style.display = currentActivity === 'qa' ? '' : 'none';
    // Sync left-column tab buttons to match server-side active activity
    if (currentActivity && currentActivity !== 'none') {
      document.getElementById('tab-poll').classList.toggle('active', currentActivity === 'poll');
      document.getElementById('tab-wordcloud').classList.toggle('active', currentActivity === 'wordcloud');
      document.getElementById('tab-qa').classList.toggle('active', currentActivity === 'qa');
      document.getElementById('tab-content-poll').style.display = currentActivity === 'poll' ? '' : 'none';
      document.getElementById('tab-content-wordcloud').style.display = currentActivity === 'wordcloud' ? '' : 'none';
      document.getElementById('tab-content-qa').style.display = currentActivity === 'qa' ? '' : 'none';
    }
  }

  async function pushWordCloudTopic() {
    const input = document.getElementById('wc-topic-input');
    if (!input) return;
    const topic = input.value.trim();
    await fetch('/api/wordcloud/topic', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic }),
    });
  }

  function hostSubmitWord() {
    const input = document.getElementById('wc-host-input');
    if (!input) return;
    const word = input.value.trim();
    if (!word || !ws) return;
    ws.send(JSON.stringify({ type: 'wordcloud_word', word }));
    hostWords.unshift(word);
    input.value = '';
    renderHostWordList();
  }

  function renderHostWordList() {
    const ul = document.getElementById('wc-host-words');
    if (!ul) return;
    ul.innerHTML = hostWords.map(w => `<li>${escHtml(w)}</li>`).join('');
  }

  async function downloadAndClearWordCloud() {
    const canvas = document.getElementById('host-wc-canvas');
    if (canvas) {
      const a = document.createElement('a');
      a.href = canvas.toDataURL('image/png');
      a.download = `wordcloud-${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.png`;
      a.click();
    }
    await clearWordCloud();
  }

  async function clearWordCloud() {
    hostWords = [];
    renderHostWordList();
    await fetch('/api/wordcloud/clear', { method: 'POST' });
  }

  function renderHostWordCloud(wordsMap) {
    const canvas = document.getElementById('host-wc-canvas');
    if (!canvas) return;
    clearTimeout(_hostWcDebounceTimer);
    _hostWcDebounceTimer = setTimeout(() => _drawHostCloud(canvas, wordsMap), 300);
    const dl = document.getElementById('wc-host-suggestions');
    if (dl) {
      dl.innerHTML = Object.keys(wordsMap).sort()
        .map(w => `<option value="${escHtml(w)}"></option>`).join('');
    }
  }

  function _drawHostCloud(canvas, wordsMap) {
    const entries = Object.entries(wordsMap);
    const container = canvas.parentElement;
    const W = container.clientWidth || 500;
    const H = container.clientHeight || 400;
    canvas.width = W;
    canvas.height = H;
    if (!entries.length) {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, W, H);
      return;
    }
    const maxCount = Math.max(...entries.map(([,c]) => c));
    const minCount = Math.min(...entries.map(([,c]) => c));
    const sizeScale = d3.scaleLinear().domain([minCount, maxCount]).range([16, 72]);
    d3.layout.cloud()
      .size([W, H])
      .words(entries.map(([text, count]) => ({ text, size: sizeScale(count) })))
      .padding(4)
      .rotate(() => (Math.random() > 0.5 ? 90 : 0))
      .font('sans-serif')
      .fontSize(d => d.size)
      .on('end', (placed) => {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, W, H);
        ctx.textAlign = 'center';
        placed.forEach((w, i) => {
          ctx.save();
          ctx.translate(W/2 + w.x, H/2 + w.y);
          ctx.rotate((w.rotate * Math.PI) / 180);
          ctx.font = `bold ${w.size}px sans-serif`;
          ctx.fillStyle = WC_COLORS[i % WC_COLORS.length];
          ctx.fillText(w.text, 0, 0);
          ctx.restore();
        });
      })
      .start();
  }

  async function hostSubmitQA() {
    const input = document.getElementById('host-qa-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;
    const resp = await fetch('/api/qa/question', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Host', text }),
    });
    if (resp.ok) { input.value = ''; input.focus(); }
  }

  async function clearQA() {
    await fetch('/api/qa/clear', { method: 'POST' });
  }

  async function toggleAnswered(qid, current) {
    await fetch(`/api/qa/answer/${qid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answered: !current }),
    });
  }

  async function deleteQuestion(qid) {
    await fetch(`/api/qa/question/${qid}`, { method: 'DELETE' });
  }

  function editQuestion(qid, currentText) {
    const card = document.querySelector(`.qa-card[data-id="${qid}"]`);
    if (!card) return;
    const textEl = card.querySelector('.qa-text');
    if (textEl.querySelector('input')) return; // already editing

    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentText;
    input.className = 'qa-edit-input';
    textEl.innerHTML = '';
    textEl.appendChild(input);
    input.focus();
    input.select();

    let _committed = false;
    async function commit() {
      if (_committed) return;
      _committed = true;
      const newText = input.value.trim();
      if (newText && newText !== currentText) {
        textEl.textContent = newText; // optimistic update (WS will confirm)
        await fetch(`/api/qa/question/${qid}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: newText }),
        });
      } else {
        textEl.textContent = currentText; // restore on cancel
      }
    }

    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      if (e.key === 'Escape') { input.value = currentText; commit(); }
    });
    input.addEventListener('blur', commit, { once: true });
  }

  function renderQAList(questions) {
    const list = document.getElementById('qa-list');
    const countEl = document.getElementById('qa-count');
    if (!list) return;
    if (countEl) countEl.textContent = questions.length;

    if (!questions.length) {
      list.innerHTML = '<p style="color:var(--muted);font-size:.9rem;text-align:center;margin-top:2rem;">No questions yet.</p>';
      return;
    }

    // If any card is currently being edited, skip re-render to avoid losing the edit input
    if (list.querySelector('.qa-edit-input')) return;

    list.innerHTML = questions.map(q => `
      <div class="qa-card${q.answered ? ' qa-answered' : ''}" data-id="${escHtml(q.id)}">
        <div class="qa-text">${escHtml(q.text)}</div>
        <div class="qa-meta">
          <span class="qa-author">${escHtml(q.author)}</span>
          <span class="qa-upvotes">▲ ${q.upvote_count}</span>
        </div>
        <div class="qa-actions">
          <button class="btn btn-sm ${q.answered ? 'btn-success' : ''}"
                  onclick="toggleAnswered('${escHtml(q.id)}', ${q.answered})">
            ✓ ${q.answered ? 'Answered' : 'Answer'}
          </button>
          <button class="btn btn-sm btn-primary"
                  onclick="editQuestion('${escHtml(q.id)}', ${JSON.stringify(q.text)})">✎ Edit</button>
          <button class="btn btn-sm btn-danger"
                  onclick="deleteQuestion('${escHtml(q.id)}')">✕</button>
        </div>
      </div>
    `).join('');
  }

  connectWS();

  document.getElementById('wc-host-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') hostSubmitWord();
  });
  document.getElementById('wc-topic-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') pushWordCloudTopic();
  });
