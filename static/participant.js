  const LS_KEY = 'workshop_participant_name';
  let ws = null;
  let myName = '';
  let myVote = null;      // option_id I voted for
  let currentPoll = null;
  let pollActive = false;

  async function fetchSuggestedName() {
    const res = await fetch('/api/suggest-name');
    const data = await res.json();
    return data.name;
  }

  // ── Restore name from localStorage ──
  const nameInput = document.getElementById('name-input');
  const clearBtn = document.getElementById('clear-name');
  const savedName = localStorage.getItem(LS_KEY);
  if (savedName) {
    nameInput.value = savedName;
  } else {
    fetchSuggestedName().then(name => nameInput.placeholder = name);
  }
  updateClearBtn();

  nameInput.addEventListener('input', updateClearBtn);

  function updateClearBtn() {
    clearBtn.style.display = nameInput.value ? 'block' : 'none';
  }

  clearBtn.addEventListener('click', async () => {
    localStorage.removeItem(LS_KEY);
    nameInput.value = '';
    nameInput.placeholder = await fetchSuggestedName();
    updateClearBtn();
    nameInput.focus();
  });

  // ── Join ──
  document.getElementById('join-btn').addEventListener('click', join);
  nameInput.addEventListener('keydown', e => { if (e.key === 'Enter') join(); });

  function join() {
    const input = document.getElementById('name-input');
    const name = input.value.trim() || input.placeholder;
    if (!name) { input.focus(); return; }
    myName = name;
    localStorage.setItem(LS_KEY, name);
    connectWS(name);
  }

  // ── Location ──
  async function resolveLocation() {
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        resolve({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
        return;
      }
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          try {
            const { latitude: lat, longitude: lon } = pos.coords;
            const res = await fetch(
              `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`
            );
            const data = await res.json();
            const city = data.address?.city || data.address?.town || data.address?.village || data.address?.county || '';
            const country = data.address?.country || '';
            resolve({ location: [city, country].filter(Boolean).join(', ') || 'Unknown' });
          } catch {
            resolve({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
          }
        },
        () => {
          resolve({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
        },
        { timeout: 8000 }
      );
    });
  }

  // ── WebSocket ──
  function connectWS(name) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/ws/${encodeURIComponent(name)}`;
    ws = new WebSocket(url);

    ws.onopen = async () => {
      document.getElementById('join-screen').style.display = 'none';
      document.getElementById('main-screen').style.display = 'block';
      document.getElementById('display-name').textContent = myName;

      const loc = await resolveLocation();
      const locationStr = loc.location || `🕐 ${loc.timezone}`;
      ws.send(JSON.stringify({ type: 'location', location: locationStr }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      handleMessage(msg);
    };

    ws.onclose = () => {
      setTimeout(() => connectWS(myName), 3000);   // auto-reconnect
    };
  }

  // ── Message handler ──
  function handleMessage(msg) {
    switch (msg.type) {
      case 'state':
        if (msg.poll?.question !== currentPoll?.question) myVote = null;
        currentPoll = msg.poll;
        pollActive = msg.poll_active;
        updateParticipantCount(msg.participant_count);
        renderContent(msg.vote_counts);
        break;
      case 'vote_update':
        renderOptions(msg.vote_counts, msg.total_votes);
        break;
      case 'participant_count':
        updateParticipantCount(msg.count);
        break;
    }
  }

  function updateParticipantCount(n) {
    document.getElementById('pax-count').textContent = `👥 ${n} participant${n !== 1 ? 's' : ''}`;
  }

  // ── Render ──
  function renderContent(voteCounts) {
    const el = document.getElementById('content');
    if (!currentPoll) {
      el.innerHTML = `<div class="waiting"><div class="icon">⏳</div><p>Waiting for the host to start a poll…</p></div>`;
      return;
    }
    renderPollCard(el, voteCounts);
  }

  function renderPollCard(container, voteCounts) {
    const totalVotes = Object.values(voteCounts || {}).reduce((a, b) => a + b, 0);
    const alreadyVoted = myVote !== null;

    let optionsHTML = currentPoll.options.map(opt => {
      const count = (voteCounts || {})[opt.id] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const selected = myVote === opt.id ? 'selected' : '';
      const disabled = (!pollActive || alreadyVoted) ? 'disabled' : '';
      return `
        <button class="option-btn ${selected}" ${disabled} onclick="castVote('${opt.id}')">
          <div class="bar" style="width:${alreadyVoted || !pollActive ? pct : 0}%"></div>
          <span>${opt.text}</span>
          ${alreadyVoted || !pollActive ? `<span class="pct">${pct}%</span>` : ''}
        </button>`;
    }).join('');

    let footer = '';
    if (!pollActive && currentPoll) {
      footer = `<div class="closed-banner">Voting is closed — final results shown above</div>`;
    } else if (alreadyVoted) {
      footer = `<div class="vote-msg">✅ Vote registered! Results update live.</div>`;
    } else {
      footer = `<div class="vote-msg">Choose an option to vote.</div>`;
    }

    container.innerHTML = `
      <div class="poll-card">
        <h2>${currentPoll.question}</h2>
        ${optionsHTML}
        ${footer}
      </div>`;
  }

  function renderOptions(voteCounts, totalVotes) {
    // Lightweight update — only refresh option bars/pcts without full re-render
    if (!currentPoll) return;
    document.querySelectorAll('.option-btn').forEach((btn, i) => {
      const opt = currentPoll.options[i];
      if (!opt) return;
      const count = (voteCounts || {})[opt.id] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const bar = btn.querySelector('.bar');
      let pctEl = btn.querySelector('.pct');
      if (bar) bar.style.width = `${pct}%`;
      if (!pctEl) {
        pctEl = document.createElement('span');
        pctEl.className = 'pct';
        btn.appendChild(pctEl);
      }
      pctEl.textContent = `${pct}%`;
    });
  }

  function castVote(optionId) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!pollActive || myVote !== null) return;
    myVote = optionId;
    ws.send(JSON.stringify({ type: 'vote', option_id: optionId }));
    renderContent({});   // re-render to show "voted" state
  }
