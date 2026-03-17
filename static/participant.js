  const LS_KEY = 'workshop_participant_name';
  const LS_VOTE_KEY = 'workshop_vote';
  let ws = null;
  let myName = '';
  let myVote = null;      // string (single) or Set of option_ids (multi)
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
    join();   // auto-join
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

  // ── Leave ──
  document.getElementById('leave-btn').addEventListener('click', () => {
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    localStorage.removeItem(LS_KEY);
    clearVote();
    myName = '';
    myVote = null;
    document.getElementById('main-screen').style.display = 'none';
    document.getElementById('join-screen').style.display = 'block';
    nameInput.value = '';
    fetchSuggestedName().then(name => nameInput.placeholder = name);
    updateClearBtn();
  });

  // ── Location ──
  async function resolveLocation() {
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        resolve({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
        return;
      }
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const { latitude: lat, longitude: lon } = pos.coords;
          try {
            const res = await fetch(
              `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`,
              { headers: { 'Accept-Language': 'en' } }
            );
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const city = data.address?.city || data.address?.town || data.address?.village || data.address?.county || '';
            const country = data.address?.country_code?.toUpperCase() || data.address?.country || '';
            const label = [city, country].filter(Boolean).join(', ');
            resolve({ location: label || `${lat.toFixed(2)}, ${lon.toFixed(2)}` });
          } catch {
            // Nominatim failed — send raw coords so host sees something
            resolve({ location: `${lat.toFixed(2)}, ${lon.toFixed(2)}` });
          }
        },
        () => {
          resolve({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
        },
        { timeout: 15000, maximumAge: 60000 }
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

  // ── Vote persistence ──
  function saveVote() {
    if (!currentPoll) return;
    const stored = {
      question: currentPoll.question,
      vote: currentPoll.multi ? [...myVote] : myVote,
    };
    localStorage.setItem(LS_VOTE_KEY, JSON.stringify(stored));
  }

  function restoreVote(poll) {
    if (!poll) return;
    try {
      const stored = JSON.parse(localStorage.getItem(LS_VOTE_KEY) || 'null');
      if (!stored || stored.question !== poll.question) return;
      if (poll.multi) {
        myVote = new Set(Array.isArray(stored.vote) ? stored.vote : []);
      } else {
        myVote = typeof stored.vote === 'string' ? stored.vote : null;
      }
    } catch { /* ignore */ }
  }

  function clearVote() {
    localStorage.removeItem(LS_VOTE_KEY);
  }

  // ── Message handler ──
  function handleMessage(msg) {
    switch (msg.type) {
      case 'state':
        if (msg.poll?.question !== currentPoll?.question) {
          myVote = msg.poll?.multi ? new Set() : null;
          restoreVote(msg.poll);
        }
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
    const multi = !!currentPoll.multi;
    const totalVotes = Object.values(voteCounts || {}).reduce((a, b) => a + b, 0);
    const hasVoted = multi ? myVote instanceof Set && myVote.size > 0 : myVote !== null;
    const showResults = hasVoted || !pollActive;

    let optionsHTML = currentPoll.options.map(opt => {
      const count = (voteCounts || {})[opt.id] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const selected = multi ? (myVote instanceof Set && myVote.has(opt.id) ? 'selected' : '')
                              : (myVote === opt.id ? 'selected' : '');
      const disabled = !pollActive ? 'disabled' : '';
      return `
        <button class="option-btn ${selected}" ${disabled} onclick="castVote('${opt.id}')">
          <div class="bar" style="width:${showResults ? pct : 0}%"></div>
          <span>${opt.text}</span>
          ${showResults ? `<span class="pct">${pct}%</span>` : ''}
        </button>`;
    }).join('');

    let footer = '';
    if (!pollActive) {
      footer = `<div class="closed-banner">Voting is closed — final results shown above</div>`;
    } else if (multi) {
      footer = `<div class="vote-msg">${myVote instanceof Set && myVote.size > 0
        ? `✅ ${myVote.size} option${myVote.size > 1 ? 's' : ''} selected — click to toggle.`
        : 'Select one or more options.'}</div>`;
    } else if (hasVoted) {
      footer = `<div class="vote-msg">✅ Vote registered! Click another option to change it.</div>`;
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
    if (!pollActive) return;

    if (currentPoll.multi) {
      if (!(myVote instanceof Set)) myVote = new Set();
      if (myVote.has(optionId)) myVote.delete(optionId);
      else myVote.add(optionId);
      ws.send(JSON.stringify({ type: 'multi_vote', option_ids: [...myVote] }));
    } else {
      if (myVote === optionId) return;
      myVote = optionId;
      ws.send(JSON.stringify({ type: 'vote', option_id: optionId }));
    }
    saveVote();
    updateSelectionUI();
  }

  // Update only selected state and footer after casting a vote — no bar animation flicker
  function updateSelectionUI() {
    const multi = !!currentPoll.multi;
    document.querySelectorAll('.option-btn').forEach((btn, i) => {
      const opt = currentPoll.options[i];
      if (!opt) return;
      const selected = multi
        ? (myVote instanceof Set && myVote.has(opt.id))
        : (myVote === opt.id);
      btn.classList.toggle('selected', selected);
    });

    const hasVoted = multi ? myVote instanceof Set && myVote.size > 0 : myVote !== null;
    let footerHTML = '';
    if (multi) {
      footerHTML = `<div class="vote-msg">${hasVoted
        ? `✅ ${myVote.size} option${myVote.size > 1 ? 's' : ''} selected — click to toggle.`
        : 'Select one or more options.'}</div>`;
    } else {
      footerHTML = `<div class="vote-msg">✅ Vote registered! Click another option to change it.</div>`;
    }
    const card = document.querySelector('.poll-card');
    if (card) {
      const existing = card.querySelector('.vote-msg');
      if (existing) existing.outerHTML = footerHTML;
      else card.insertAdjacentHTML('beforeend', footerHTML);
    }
  }
