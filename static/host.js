  let ws = null;
  let currentPoll = null;
  let pollActive = false;
  let voteCounts = {};
  let totalVotes = 0;
  let participantLocations = {};

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
        currentPoll = msg.poll;
        pollActive = msg.poll_active;
        voteCounts = msg.vote_counts || {};
        totalVotes = Object.values(voteCounts).reduce((a,b)=>a+b,0);
        participantLocations = msg.participant_locations || {};
        document.getElementById('pax-count').textContent = msg.participant_count;
        renderParticipantList(msg.participant_names || []);
        renderPollDisplay();
      } else if (msg.type === 'vote_update') {
        voteCounts = msg.vote_counts || {};
        totalVotes = msg.total_votes || 0;
        renderBars();
      } else if (msg.type === 'participant_count') {
        document.getElementById('pax-count').textContent = msg.count;
        participantLocations = msg.locations || participantLocations;
        renderParticipantList(msg.names || []);
      } else if (msg.type === 'quiz_status') {
        renderQuizStatus(msg.status, msg.message);
      }
    };
  }

  function setBadge(ok) {
    const b = document.getElementById('ws-badge');
    b.textContent = ok ? '● Connected' : '● Disconnected';
    b.className = `badge ${ok ? 'connected' : 'disconnected'}`;
  }

  function renderParticipantList(names) {
    const ul = document.getElementById('pax-list');
    ul.innerHTML = names.map(n => {
      const loc = participantLocations[n];
      return `<li>${n}${loc ? `<span class="pax-location" onclick="openMap()" title="View all on map">📍 ${loc}</span>` : ''}</li>`;
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
    width: 200,
    height: 200,
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
    if (res.ok) {
      await setPollStatus(true);
      toast('Poll created & opened ✓');
      pollInput.innerHTML = '<div><br></div>';
      document.getElementById('multi-check').checked = false;
    } else {
      const err = await res.json();
      toast(err.detail || 'Error');
    }
  });

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

    const bars = currentPoll.options.map((opt, i) => {
      const count = voteCounts[opt.id] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const maxCount = Math.max(...Object.values(voteCounts));
      const leading = count === maxCount && count > 0 ? 'leading' : '';
      return `
        <div class="result-row" data-id="${opt.id}">
          <div class="result-label">
            <span>${opt.text}</span>
            <span class="pct">${count} vote${count!==1?'s':''} · ${pct}%</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill ${leading}" style="width:${pct}%"></div>
          </div>
        </div>`;
    }).join('');

    el.innerHTML = `
      <span class="status-pill ${statusLabel}">${statusText}</span>
      <span class="mode-pill">${currentPoll.multi ? '☑ Multi-select' : '◉ Single-select'}</span>
      <p class="poll-question">${currentPoll.question}</p>
      ${bars}
      <p style="font-size:.8rem; color:var(--muted); margin-top:.5rem;">${totalVotes} total vote${totalVotes!==1?'s':''}</p>
      <div class="btn-row">
        ${!pollActive
          ? `<button class="btn btn-success" onclick="setPollStatus(true)">▶ Open voting</button>`
          : `<button class="btn btn-warn"    onclick="setPollStatus(false)">⏹ Close voting</button>`}
        <button class="btn btn-danger" onclick="clearPoll()">🗑 Remove poll</button>
      </div>`;
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

  function renderQuizStatus(status, message) {
    const el = document.getElementById('quiz-status');
    if (!el) return;
    const colors = { requested: 'var(--muted)', generating: 'var(--warn)', done: 'var(--accent2)', error: 'var(--danger)' };
    const icons  = { requested: '⏳', generating: '⚙️', done: '✅', error: '❌' };
    el.style.color = colors[status] || 'var(--muted)';
    el.textContent = `${icons[status] || ''} ${message}`;
  }

  function toast(msg) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 2500);
  }


  connectWS();
