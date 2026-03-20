  let ws = null;
  let currentPoll = null;
  let pollActive = false;
  let voteCounts = {};
  let totalVotes = 0;
  let participantLocations = {};
  let participantAvatars = {};
  let participantDebateSides = {};  // participant_name -> "for"|"against"|undefined
  let _debateActive = false;
  const resolvedCities = {};   // raw "lat, lon" -> resolved city string cache
  let correctOptIds = new Set(); // host-marked correct options for current poll
  let scores = {};               // participant_name -> score
  let cachedNames = [];          // last known participant names
  let summaryPoints = [];
  let summaryUpdatedAt = null;

  let hostWords = [];
  let _hostWcDebounceTimer = null;
  const versionReloadGuard = window.createVersionReloadGuard
    ? window.createVersionReloadGuard({ countdownSeconds: 5 })
    : null;
  window.__versionReloadGuard = versionReloadGuard;
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
      method: 'PUT',
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
        versionReloadGuard && versionReloadGuard.check(msg.backend_version);
        const prevQuestion = currentPoll?.question;
        currentPoll = msg.poll;
        if (!msg.poll_active && pollActive) _clearTimer(); // poll just closed
        pollActive = msg.poll_active;
        if (currentPoll && currentPoll.question !== prevQuestion) loadCorrectOpts(currentPoll.question);
        voteCounts = msg.vote_counts || {};
        totalVotes = Object.values(voteCounts).reduce((a,b)=>a+b,0);
        participantLocations = {};
        participantAvatars = {};
        participantDebateSides = {};
        scores = {};
        _debateActive = msg.current_activity === 'debate' && !!msg.debate_phase;
        const names = [];
        msg.participants.forEach(p => {
            names.push(p.name);
            participantLocations[p.name] = p.location;
            participantAvatars[p.name] = p.avatar;
            scores[p.name] = p.score;
            if (p.debate_side) participantDebateSides[p.name] = p.debate_side;
        });
        cachedNames = names;
        document.getElementById('pax-count').textContent = msg.participant_count;
        renderParticipantList(names);
        renderDaemonStatus(msg.daemon_connected, msg.daemon_last_seen);
        renderTranscriptStatus(msg.transcript_line_count, msg.transcript_total_lines, msg.transcript_latest_ts);
        renderNotesStatus(msg.daemon_session_folder, msg.daemon_session_notes);
        updateHostNotes(msg.notes_content);
        renderPreview(msg.quiz_preview || null);
        renderPollDisplay();
        const currentActivity = msg.current_activity || 'none';
        updateCenterPanel(currentActivity);
        renderDebateHost(msg);
        if (currentActivity === 'wordcloud') {
          renderHostWordCloud(msg.wordcloud_words || {});
        }
        if (currentActivity === 'qa') {
          renderQAList(msg.qa_questions || []);
        }
        if (currentActivity === 'codereview' && msg.codereview) {
          renderHostCodeReview(msg.codereview);
        }
        updateSummary(msg.summary_points, msg.summary_updated_at);
      } else if (msg.type === 'vote_update') {
        voteCounts = msg.vote_counts || {};
        totalVotes = msg.total_votes || 0;
        renderBars();
      } else if (msg.type === 'participant_count') {
        document.getElementById('pax-count').textContent = msg.count;
        participantLocations = {};
        participantAvatars = {};
        scores = {};
        const names = [];
        msg.participants.forEach(p => {
            names.push(p.name);
            participantLocations[p.name] = p.location;
            participantAvatars[p.name] = p.avatar;
            scores[p.name] = p.score;
        });
        cachedNames = names;
        renderParticipantList(names);
        // Re-render code review side panel with fresh scores
        if (window._lastCodereviewState && window._lastCodereviewState.phase !== 'idle') {
          // Update scores in cached line_participants
          const cr = window._lastCodereviewState;
          for (const key in cr.line_participants) {
            cr.line_participants[key].forEach(p => {
              if (scores[p.name] !== undefined) p.score = scores[p.name];
            });
          }
          _updateCodeReviewLayout(cr);
        }
      } else if (msg.type === 'timer') {
        _applyTimer(msg.seconds, msg.started_at);
      } else if (msg.type === 'quiz_status') {
        renderQuizStatus(msg.status, msg.message);
      } else if (msg.type === 'quiz_preview') {
        renderPreview(msg.quiz || null);
      } else if (msg.type === 'summary') {
        updateSummary(msg.points, msg.updated_at);
      }
    };
  }

  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  let _summaryGenerating = false;

  function updateSummary(points, updatedAt) {
    summaryPoints = points || [];
    summaryUpdatedAt = updatedAt;
    if (summaryPoints.length) _summaryGenerating = false;
    renderSummaryBadge();
    renderSummaryList();
  }

  function renderSummaryBadge() {
    const badge = document.getElementById('summary-badge');
    if (!badge) return;
    badge.style.cssText = 'cursor:pointer;';
    if (summaryPoints.length) {
      badge.textContent = `Points (${summaryPoints.length})`;
      badge.className = 'badge connected';
      badge.title = `${summaryPoints.length} key points — click to view`;
    } else if (_summaryGenerating) {
      badge.textContent = 'Generating...';
      badge.className = 'badge';
      badge.style.cssText = 'cursor:wait; color:var(--warn); border:1px solid var(--warn);';
      badge.title = 'Generating key points from transcript...';
    } else {
      badge.textContent = 'Points';
      badge.className = 'badge disconnected';
      badge.title = 'No key points yet — click to generate now';
    }
  }

  function renderSummaryList() {
    const list = document.getElementById('summary-list');
    const timeEl = document.getElementById('summary-time');
    if (!list) return;
    if (!summaryPoints.length) {
      list.innerHTML = '<li class="summary-empty">No key points yet — check back soon.</li>';
      if (timeEl) timeEl.textContent = '';
      return;
    }
    list.innerHTML = summaryPoints.map(p => {
      const text = typeof p === 'string' ? p : p.text;
      const source = typeof p === 'string' ? 'discussion' : (p.source || 'discussion');
      const icon = source === 'notes' ? '✏️' : '💬';
      return `<li>${icon} ${escHtml(text)}</li>`;
    }).join('');
    if (timeEl && summaryUpdatedAt) {
      const d = new Date(summaryUpdatedAt);
      timeEl.textContent = 'Updated ' + d.toLocaleTimeString();
    }
  }

  function toggleSummaryModal() {
    if (summaryPoints.length) {
      const overlay = document.getElementById('summary-overlay');
      if (overlay) overlay.classList.toggle('open');
    } else {
      _summaryGenerating = true;
      renderSummaryBadge();
      fetch('/api/summary/force', { method: 'POST' });
    }
  }

  function closeSummaryModal() {
    const overlay = document.getElementById('summary-overlay');
    if (overlay) overlay.classList.remove('open');
  }

  function setBadge(ok) {
    const b = document.getElementById('ws-badge');
    b.textContent = ok ? 'Server' : 'Server';
    b.className = `badge ${ok ? 'connected' : 'disconnected'}`;
  }

  function renderDaemonStatus(connected, lastSeenIso) {
    const el = document.getElementById('daemon-badge');
    if (!el) return;

    if (!lastSeenIso) {
      el.textContent = 'Agent';
      el.className = 'badge disconnected';
      el.title = 'Never connected — start with ./start-daemon.sh';
      return;
    }

    const ago = Math.round((Date.now() - new Date(lastSeenIso)) / 1000);
    const agoText = ago < 60 ? `${ago}s ago` : `${Math.round(ago/60)}m ago`;

    if (connected) {
      el.textContent = 'Agent';
      el.className = 'badge connected';
      el.title = `Connected (last seen ${agoText})`;
    } else {
      el.textContent = 'Agent';
      el.className = 'badge';
      el.style.cssText = 'color:var(--warn);border:1px solid var(--warn);';
      el.title = `Connection lost (last seen ${agoText})`;
    }
  }

  function renderTranscriptStatus(lineCount, totalLines, latestTs) {
    const el = document.getElementById('transcript-badge');
    if (!el) return;

    if (lineCount > 0) {
      el.textContent = '💬';
      el.className = 'badge connected';
      el.title = `${lineCount} lines in last 30 min / ${totalLines} today\nLatest at ${latestTs}`;
    } else {
      el.textContent = '💬';
      el.className = 'badge disconnected';
      el.title = latestTs
        ? `No transcription since ${latestTs}\n${totalLines} lines today`
        : 'No transcription data';
    }
  }

  let hostNotesContent = '';

  function renderNotesStatus(sessionFolder, sessionNotes) {
    const el = document.getElementById('notes-badge');
    if (!el) return;

    el.style.cssText = 'cursor:pointer;';
    if (sessionFolder && sessionNotes) {
      el.textContent = '.txt';
      el.className = 'badge connected';
      el.title = `${sessionFolder}/${sessionNotes}\nClick to view`;
    } else if (sessionFolder) {
      el.textContent = '.txt';
      el.className = 'badge';
      el.style.cssText = 'cursor:pointer; color:var(--warn); border:1px solid var(--warn);';
      el.title = 'Session folder found but no notes file inside';
    } else {
      el.textContent = '.txt';
      el.className = 'badge disconnected';
      el.title = 'No session folder found for today';
    }
  }

  function updateHostNotes(content) {
    hostNotesContent = content || '';
    const el = document.getElementById('host-notes-content');
    if (el) {
      if (hostNotesContent) {
        el.textContent = hostNotesContent;
        el.style.cssText = '';
      } else {
        el.textContent = 'No notes available yet.';
        el.style.cssText = 'color:var(--text-muted); font-style:italic;';
      }
    }
  }

  function toggleHostNotesModal() {
    const overlay = document.getElementById('host-notes-overlay');
    if (overlay) overlay.classList.toggle('open');
  }

  function closeHostNotesModal() {
    const overlay = document.getElementById('host-notes-overlay');
    if (overlay) overlay.classList.remove('open');
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
      const avatar = participantAvatars[n];
      const avatarHtml = avatar
          ? `<img src="/static/avatars/${escHtml(avatar)}" class="avatar" style="width:28px;height:28px" onerror="this.style.display='none'">`
          : '';
      const debateSide = participantDebateSides[n];
      const debateIcon = _debateActive
          ? (debateSide === 'for' ? '<span title="FOR">👍</span> ' : debateSide === 'against' ? '<span title="AGAINST">👎</span> ' : '<span title="Undecided">⏳</span> ')
          : '';
      return `<li><span class="pax-name">${debateIcon}${avatarHtml}${escHtml(n)}${scoreTag}</span>${locLabel ? `<span class="pax-location" onclick="openMap()" title="View all on map">📍 ${escHtml(locLabel)}</span>` : ''}</li>`;
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
      closeSummaryModal();
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
      method: 'PUT',
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
        <button class="btn btn-danger" onclick="clearPoll()">✕ Remove question</button>
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
  const GEN_LABEL_TRANSCRIPT = 'Generate from transcript ✨';
  const GEN_LABEL_TOPIC = 'Generate on topic ✨';

  function updateGenBtn() {
    const topic = document.getElementById('quiz-topic').value.trim();
    const btn = document.getElementById('gen-quiz-btn');
    btn.textContent = topic ? GEN_LABEL_TOPIC : GEN_LABEL_TRANSCRIPT;
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
    ['poll', 'wordcloud', 'qa', 'debate', 'codereview'].forEach(t => {
      document.getElementById('tab-' + t).classList.toggle('active', tab === t);
      document.getElementById('tab-content-' + t).style.display = tab === t ? '' : 'none';
    });
    await fetch('/api/activity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ activity: tab }),
    });
  }

  function updateCenterPanel(currentActivity) {
    ['qr', 'poll', 'wordcloud', 'qa', 'debate', 'codereview'].forEach(id => {
      const el = document.getElementById('center-' + id);
      if (id === 'qr') {
        el.style.display = currentActivity === 'none' ? '' : 'none';
      } else {
        el.style.display = currentActivity === id ? '' : 'none';
      }
    });
    if (currentActivity && currentActivity !== 'none') {
      ['poll', 'wordcloud', 'qa', 'debate', 'codereview'].forEach(t => {
        document.getElementById('tab-' + t).classList.toggle('active', currentActivity === t);
        document.getElementById('tab-content-' + t).style.display = currentActivity === t ? '' : 'none';
      });
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
    if (!text || !ws) return;
    ws.send(JSON.stringify({ type: 'qa_submit', text }));
    input.value = '';
    input.focus();
  }

  async function clearQA() {
    await fetch('/api/qa/clear', { method: 'POST' });
  }

  async function toggleAnswered(qid, current) {
    await fetch(`/api/qa/question/${qid}/answered`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answered: !current }),
    });
  }

  async function deleteQuestion(qid) {
    await fetch(`/api/qa/question/${qid}`, { method: 'DELETE' });
  }

  function editQuestion(qid) {
    const card = document.querySelector(`.qa-card[data-id="${qid}"]`);
    if (!card) return;
    const textEl = card.querySelector('.qa-text');
    if (textEl.querySelector('input')) return; // already editing

    const currentText = textEl.textContent.trim();

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
        await fetch(`/api/qa/question/${qid}/text`, {
          method: 'PUT',
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

    list.innerHTML = questions.map(q => {
      const avatarHtml = q.author_avatar
          ? `<img src="/static/avatars/${escHtml(q.author_avatar)}" class="avatar" style="width:24px;height:24px" onerror="this.style.display='none'">`
          : '';
      return `
      <div class="qa-card${q.answered ? ' qa-answered' : ''}" data-id="${escHtml(q.id)}">
        <div class="qa-text">${escHtml(q.text)}</div>
        <div class="qa-meta">
          ${avatarHtml}<span class="qa-author">${escHtml(q.author)}</span>
          <span class="qa-upvotes">▲ ${q.upvote_count}</span>
        </div>
        <div class="qa-actions">
          <button class="btn btn-sm ${q.answered ? 'btn-success' : ''}"
                  onclick="toggleAnswered('${escHtml(q.id)}', ${q.answered})">
            ✓ Answered
          </button>
          <button class="btn btn-sm btn-primary"
                  onclick="editQuestion('${escHtml(q.id)}')">✎ Edit</button>
          <button class="btn btn-sm btn-danger"
                  onclick="deleteQuestion('${escHtml(q.id)}')">🗑</button>
        </div>
      </div>
    `; }).join('');
  }

  // ── Code Review ──
  let codereviewSelectedLine = null;
  window._lastCodereviewState = null;

  function renderHostCodeReview(cr) {
    window._lastCodereviewState = cr;
    const createDiv = document.getElementById('codereview-create');
    const activeDiv = document.getElementById('codereview-active');

    if (cr.phase === 'idle') {
      createDiv.style.display = '';
      activeDiv.style.display = 'none';
      document.getElementById('codereview-code-panel').innerHTML = '';
      document.getElementById('codereview-side-panel').style.display = 'none';
      document.getElementById('codereview-side-panel').previousElementSibling.style.display = 'none';
      document.getElementById('codereview-code-panel').style.flex = '1';
      return;
    }

    createDiv.style.display = 'none';
    activeDiv.style.display = '';

    const closeBtn = document.getElementById('codereview-close-btn');
    const phaseLabel = document.getElementById('codereview-phase-label');

    if (cr.phase === 'selecting') {
      closeBtn.style.display = '';
      phaseLabel.innerHTML = '<span style="color:var(--accent2);">🐛 Bug Hunt Open</span>';
      codereviewSelectedLine = null;
    } else {
      closeBtn.style.display = 'none';
      const confirmedCount = cr.confirmed_lines ? cr.confirmed_lines.length : 0;
      phaseLabel.innerHTML = `<span style="color:var(--warn);">Review mode — ${confirmedCount} line(s) confirmed</span>`;
    }

    renderHostCodePanel(cr);
    _updateCodeReviewLayout(cr);
  }

  function renderHostCodePanel(cr) {
    const panel = document.getElementById('codereview-code-panel');
    const lines = cr.snippet.split('\n');
    const lineCounts = cr.line_counts || {};
    const confirmed = new Set(cr.confirmed_lines || []);
    const totalPax = cr.participant_count || 1;

    let html = '<div class="codereview-lines">';
    lines.forEach((lineText, i) => {
      const lineNum = i + 1;
      const count = lineCounts[String(lineNum)] || 0;
      const pct = Math.round(count * 100 / totalPax);
      const intensity = count / totalPax;
      const isConfirmed = confirmed.has(lineNum);
      const isSelected = codereviewSelectedLine === lineNum;

      let bgColor, borderColor, gutterText;
      if (isConfirmed) {
        bgColor = 'rgba(166,227,161,0.2)';
        borderColor = 'var(--accent2)';
        gutterText = `${lineNum} ✓`;
      } else if (isSelected) {
        bgColor = 'rgba(108,99,255,0.25)';
        borderColor = 'var(--accent)';
        gutterText = `${lineNum} ▶`;
      } else {
        bgColor = `rgba(108,99,255,${intensity * 0.5})`;
        borderColor = 'transparent';
        gutterText = String(lineNum);
      }

      const clickable = cr.phase === 'reviewing' && !isConfirmed ? 'codereview-line-clickable' : '';
      html += `<div class="codereview-line ${clickable}" style="background:${bgColor};border-left:3px solid ${borderColor};" onclick="selectCodeReviewLine(${lineNum})">`;
      html += `<span class="codereview-gutter">${gutterText}</span>`;
      html += `<span class="codereview-code">${escHtml(lineText) || ' '}</span>`;
      if (count > 0) {
        const countColor = isConfirmed ? 'var(--accent2)' : 'var(--accent)';
        html += `<span class="codereview-count" style="color:${countColor}">${pct}%</span>`;
      }
      html += '</div>';
    });
    html += '</div>';
    panel.innerHTML = html;
  }

  function selectCodeReviewLine(lineNum) {
    codereviewSelectedLine = lineNum;
    const lastState = window._lastCodereviewState;
    if (lastState) {
      renderHostCodePanel(lastState);
      _updateCodeReviewLayout(lastState);
    }
  }

  function _updateCodeReviewLayout(cr) {
    const codePanel = document.getElementById('codereview-code-panel');
    const sidePanel = document.getElementById('codereview-side-panel');
    const divider = sidePanel.previousElementSibling; // the 1px divider

    const showSide = cr.phase === 'reviewing' && codereviewSelectedLine !== null;
    sidePanel.style.display = showSide ? '' : 'none';
    divider.style.display = showSide ? '' : 'none';
    codePanel.style.flex = showSide ? '2' : '1';

    if (showSide) {
      renderHostSidePanel(cr);
    }
  }

  function renderHostSidePanel(cr) {
    const panel = document.getElementById('codereview-side-panel');
    const confirmed = new Set(cr.confirmed_lines || []);

    if (codereviewSelectedLine === null) {
      panel.innerHTML = '<div class="muted" style="text-align:center;margin-top:40px;">Click a line to see details</div>';
      return;
    }

    const lineNum = codereviewSelectedLine;
    const lineParticipants = (cr.line_participants || {})[String(lineNum)] || [];
    const isConfirmed = confirmed.has(lineNum);
    const count = (cr.line_counts || {})[String(lineNum)] || 0;

    let html = '';

    html += `<div style="font-size:.85rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem;">Line ${lineNum} — Users that selected this line</div>`;
    if (lineParticipants.length > 0) {
      const sorted = [...lineParticipants].sort((a, b) => {
        if (a.score !== b.score) return b.score - a.score;
        return a.name.localeCompare(b.name);
      });
      html += '<div class="codereview-participant-list">';
      sorted.forEach(p => {
        html += '<div class="codereview-participant-row">';
        html += `<span>• ${escHtml(p.name)}</span>`;
        if (p.score > 0) {
          html += `<span class="codereview-participant-score">⭐ ${p.score} pts</span>`;
        }
        html += '</div>';
      });
      html += '</div>';
    } else {
      html += '<div class="muted">No participants selected this line</div>';
    }

    if (cr.phase === 'reviewing' && !isConfirmed && count > 0) {
      html += `<button class="btn btn-success" style="width:100%;margin-top:12px;" onclick="confirmCodeReviewLine(${lineNum})">✓ Confirm Line (award 200 pts)</button>`;
    }
    if (isConfirmed) {
      html += '<div style="text-align:center;margin-top:12px;color:var(--accent2);font-weight:600;">✓ Confirmed</div>';
    }

    panel.innerHTML = html;
  }

  async function startCodeReview() {
    const snippet = document.getElementById('codereview-snippet').value;
    const langSelect = document.getElementById('codereview-language');
    const language = langSelect.value || null;
    if (!snippet.trim()) return alert('Please paste a code snippet');
    await fetch('/api/codereview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ snippet, language }),
    });
  }

  async function closeCodeReviewSelection() {
    await fetch('/api/codereview/status', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ open: false }),
    });
  }

  async function confirmCodeReviewLine(line) {
    await fetch('/api/codereview/confirm-line', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ line }),
    });
  }

  async function clearCodeReview() {
    codereviewSelectedLine = null;
    await fetch('/api/codereview', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });
  }

  updateGenBtn();
  connectWS();

  document.getElementById('wc-host-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') hostSubmitWord();
  });
  document.getElementById('wc-topic-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') pushWordCloudTopic();
  });

  // ── HTML escaping utility ──
  function escDebate(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  // ── Debate Phase Stepper ──

  const DEBATE_PHASES = [
    { key: 'side_selection', num: 1, label: 'Pick Sides' },
    { key: 'arguments',      num: 2, label: 'Arguments' },
    { key: 'prep',           num: 3, label: 'Preparation' },
    { key: 'live_debate',    num: 4, label: 'Live Debate' },
    { key: 'ended',          num: 5, label: 'Ended' },
  ];

  function renderDebatePhaseStepper(currentPhase) {
    const currentIdx = DEBATE_PHASES.findIndex(p => p.key === currentPhase);
    return '<div class="debate-stepper">' + DEBATE_PHASES.map((p, i) => {
      let cls = 'debate-step';
      if (i < currentIdx) cls += ' debate-step-done';
      else if (i === currentIdx) cls += ' debate-step-active';
      return `<div class="${cls}"><span class="debate-step-num">${p.num}</span><span class="debate-step-label">${p.label}</span></div>`;
    }).join('<span class="debate-step-sep">›</span>') + '</div>';
  }

  // ── Debate Host Functions ──

  async function launchDebate() {
    const input = document.getElementById('debate-statement-input');
    const statement = input.value.trim();
    if (!statement) return;
    await fetch('/api/debate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ statement }),
    });
  }

  async function debateCloseSelection() {
    await fetch('/api/debate/close-selection', { method: 'POST' });
  }

  async function debateEndArguments() {
    await fetch('/api/debate/end-arguments', { method: 'POST' });
  }

  async function debateForceAssign() {
    await fetch('/api/debate/force-assign', { method: 'POST' });
  }

  async function debateReset() {
    await fetch('/api/debate/reset', { method: 'POST' });
  }

  async function debateNextPhase(phase) {
    await fetch('/api/debate/phase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phase }),
    });
  }

  async function debateRunAI() {
    const btn = document.querySelector('#debate-host-actions .btn-ai');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Running AI…'; }
    try {
      await fetch('/api/debate/ai-cleanup', { method: 'POST' });
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✨ Run AI Cleanup'; }
    }
  }

  function renderDebateHost(msg) {
    const chapters = document.getElementById('debate-phase-chapters');
    const title = document.getElementById('debate-statement-display');
    const content = document.getElementById('debate-center-content');

    const debateActive = msg.current_activity === 'debate' && !!msg.debate_phase;
    const phase = msg.debate_phase || null;
    const sideCounts = msg.debate_side_counts || { for: 0, against: 0 };
    const champions = msg.debate_champions || {};

    // Update center panel title if debate is active
    if (title && debateActive) {
      title.innerHTML = escDebate(msg.debate_statement);
    }

    // Hide statement input once launched (scale out horizontally), show reset button
    const stmtWrapper = document.getElementById('debate-statement-wrapper');
    const resetWrapper = document.getElementById('debate-reset-wrapper');
    if (stmtWrapper) {
      if (debateActive) {
        stmtWrapper.style.transform = 'scaleX(0)';
        stmtWrapper.style.opacity = '0';
        stmtWrapper.style.height = '0';
        stmtWrapper.style.marginTop = '0';
        stmtWrapper.style.overflow = 'hidden';
      } else {
        stmtWrapper.style.transform = 'scaleX(1)';
        stmtWrapper.style.opacity = '1';
        stmtWrapper.style.height = '';
        stmtWrapper.style.marginTop = '.75rem';
        stmtWrapper.style.overflow = '';
      }
    }
    if (resetWrapper) resetWrapper.style.display = debateActive ? '' : 'none';

    // Phase chapters — always visible
    // ai_cleanup is implicit (not in visible list) — treat it as "between arguments and prep"
    const displayPhase = phase === 'ai_cleanup' ? 'prep' : phase;
    const currentIdx = debateActive ? DEBATE_PHASES.findIndex(p => p.key === displayPhase) : -1;
    const phaseActions = {
      side_selection: `<button class="btn btn-warn btn-sm" onclick="debateForceAssign()">🎲 Assign randomly</button>`,
      prep: champions.for || champions.against
        ? `<span style="color:var(--accent);font-size:.8rem;">🏆 ${Object.entries(champions).map(([s,n]) => `${s==='for'?'👍':'👎'} ${escDebate(n)}`).join(', ')}</span>`
        : '',
    };

    chapters.innerHTML = DEBATE_PHASES.map((p, i) => {
      const isDone = i < currentIdx;
      const isActive = i === currentIdx;
      const isFuture = currentIdx === -1 ? (i > 0) : (i > currentIdx + 1);
      const isReady = currentIdx === -1 && i === 0; // pre-launch: phase 1 is ready

      let cls = 'debate-chapter';
      if (isDone) cls += ' debate-chapter-done';
      else if (isActive) cls += ' debate-chapter-active';
      else if (isReady) cls += ' debate-chapter-ready';
      else if (isFuture) cls += ' debate-chapter-future';

      let actionHtml = '';
      if (isActive && phase === 'ai_cleanup' && p.key === 'prep') {
        actionHtml = `<div class="debate-chapter-extra"><span style="color:var(--accent);font-size:.8rem;">✨ AI enriching arguments…</span></div>`;
      } else if (isActive && phaseActions[p.key]) {
        actionHtml = `<div class="debate-chapter-extra">${phaseActions[p.key]}</div>`;
      }

      let launchBtn = '';
      if (isReady) {
        // Pre-launch: phase 1 gets a Launch button that starts the debate
        launchBtn = `<button class="btn btn-primary btn-sm" onclick="launchDebate()">Launch ⚔️</button>`;
      } else if (isActive && p.key === 'live_debate') {
        launchBtn = `<button class="btn btn-danger btn-sm" onclick="debateNextPhase('ended')">⏹ End</button>`;
      } else if (isActive && p.key === 'side_selection') {
        // No Next button — phase ends via Force Assign or auto-advance
      } else if (isActive && p.key === 'arguments') {
        launchBtn = `<button class="btn btn-primary btn-sm" onclick="debateEndArguments()">End Phase ✨</button>`;
      } else if (isActive && p.key !== 'ended') {
        const nextPhase = DEBATE_PHASES[i + 1];
        if (nextPhase) {
          launchBtn = `<button class="btn btn-primary btn-sm" onclick="debateNextPhase('${nextPhase.key}')">Next →</button>`;
        }
      } else if (isDone) {
        launchBtn = `<span class="debate-chapter-check">✓</span>`;
      }

      return `<div class="${cls}">
        <div class="debate-chapter-row">
          <span class="debate-chapter-num">${p.num}</span>
          <span class="debate-chapter-label">${p.label}</span>
          <span class="debate-chapter-action">${launchBtn}</span>
        </div>
        ${actionHtml}
      </div>`;
    }).join('');

    // Center panel: dual-column arguments
    const args = (msg.debate_arguments || []).filter(a => !a.merged_into);
    const forArgs = args.filter(a => a.side === 'for');
    const againstArgs = args.filter(a => a.side === 'against');
    const mergedArgs = (msg.debate_arguments || []).filter(a => a.merged_into);

    if (phase === 'side_selection') {
      content.innerHTML = `<div style="text-align:center; padding:3rem 2rem; color:var(--muted);">
        <div style="font-size:1.2rem;">Waiting for participants to choose sides…</div>
        <div style="font-size:4.5rem; margin-top:1rem; font-weight:700;">
          👎 ${sideCounts.against} &nbsp;|&nbsp; ${sideCounts.for} 👍
        </div>
      </div>`;
    } else {
      const phaseLabel = (DEBATE_PHASES.find(p => p.key === displayPhase) || {}).label || '';
      content.innerHTML = `<div style="text-align:center; margin-bottom:.75rem; font-size:.95rem; color:var(--muted); text-transform:uppercase; letter-spacing:.08em;">${phaseLabel}</div>` +
        renderDebateDualColumn(againstArgs, forArgs, mergedArgs, msg.debate_champions, phase);
    }
  }

  function renderDebateDualColumn(againstArgs, forArgs, mergedArgs, champions, phase) {
    const renderArg = (a) => {
      const aiClass = a.ai_generated ? ' debate-arg-ai' : '';
      return `<div class="debate-arg${aiClass}" data-id="${a.id}">
        <div class="debate-arg-header">
          ${a.author_avatar ? `<img src="/static/avatars/${a.author_avatar}" class="debate-arg-avatar">` : ''}
          <span class="debate-arg-author">${escDebate(a.author)}</span>
          <span class="debate-arg-votes">▲ ${a.upvote_count}</span>
        </div>
        <div class="debate-arg-text">${escDebate(a.text)}</div>
      </div>`;
    };

    const renderMerged = () => `<div class="debate-arg debate-arg-merged">
      <span style="color:var(--muted);font-size:.8rem;">✨ duplicate, merged above</span>
    </div>`;

    const champFor = champions?.for ? `<div class="debate-champion">🏆 ${escDebate(champions.for)}</div>` : '';
    const champAgainst = champions?.against ? `<div class="debate-champion">🏆 ${escDebate(champions.against)}</div>` : '';

    // Show hints in prep/live_debate
    let hints = '';
    if (phase === 'prep' || phase === 'live_debate') {
      hints = `<div class="debate-hints">
        <div class="debate-hint">💡 In what context does this trade-off matter most?</div>
        <div class="debate-hint">💡 What's the strongest counterargument?</div>
        <div class="debate-hint">💡 Give specific examples from real projects</div>
        <div class="debate-hint">💡 Present your strongest argument first</div>
      </div>`;
    }

    // Count merged args per side
    const mergedForCount = mergedArgs.filter(a => a.side === 'for').length;
    const mergedAgainstCount = mergedArgs.filter(a => a.side === 'against').length;

    return `<div class="debate-columns">
      <div class="debate-col debate-col-against">
        <h3 class="debate-col-header">👎</h3>
        ${champAgainst}
        ${againstArgs.map(renderArg).join('')}
        ${Array(mergedAgainstCount).fill('').map(renderMerged).join('')}
      </div>
      <div class="debate-col debate-col-for">
        <h3 class="debate-col-header">👍</h3>
        ${champFor}
        ${forArgs.map(renderArg).join('')}
        ${Array(mergedForCount).fill('').map(renderMerged).join('')}
      </div>
    </div>${hints}`;
  }
