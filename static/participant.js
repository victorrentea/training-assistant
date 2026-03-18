  const LS_KEY = 'workshop_participant_name';
  const LS_VOTE_KEY = 'workshop_vote';
  let ws = null;
  let myName = '';
  let myVote = null;      // string (single) or Set of option_ids (multi)
  let currentPoll = null;
  let pollActive = false;
  let pollResult = null;  // {correct_ids, voted_ids} once host marks correct options
  let activeTimer = null; // {seconds, startedAt (ms)} or null
  let _timerInterval = null;
  let _multiWarnShown = false; // true once warning has been shown for current poll
  let myWords = [];  // participant's own submitted words (session-only, clears on reconnect)
  const WC_COLORS = ['#7ecef4','#a78bfa','#34d399','#fbbf24','#f472b6','#60a5fa','#fb923c'];
  let _wcDebounceTimer = null;

  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // Largest-remainder rounding: ensures integer percentages sum to exactly 100
  function largestRemainder(floats) {
    const floors = floats.map(Math.floor);
    const remainder = 100 - floors.reduce((a, b) => a + b, 0);
    const order = floats.map((v, i) => [v - Math.floor(v), i])
      .sort((a, b) => b[0] - a[0]);
    for (let i = 0; i < Math.min(remainder, order.length); i++) floors[order[i][1]]++;
    return floors;
  }

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
    fetchSuggestedName().then(name => {
      nameInput.placeholder = name;
      nameInput.focus();
    });
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
        (pos) => {
          const { latitude: lat, longitude: lon } = pos.coords;
          resolve({ location: `${lat.toFixed(5)}, ${lon.toFixed(5)}` });
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
          pollResult = null;
          activeTimer = null;
          _multiWarnShown = false;
          clearInterval(_timerInterval);
          restoreVote(msg.poll);
        }
        currentPoll = msg.poll;
        pollActive = msg.poll_active;
        updateParticipantCount(msg.participant_count);
        updateScore((msg.scores || {})[myName]);
        if (msg.current_activity === 'wordcloud') {
          renderWordCloudScreen(msg.wordcloud_words || {});
        } else {
          // Clear wordcloud screen state when leaving
          const content = document.getElementById('content');
          if (content) content.dataset.screen = '';
          myWords = [];
          renderContent(msg.vote_counts);
        }
        break;
      case 'vote_update':
        renderOptions(msg.vote_counts, msg.total_votes);
        break;
      case 'participant_count':
        updateParticipantCount(msg.count);
        break;
      case 'scores':
        updateScore((msg.scores || {})[myName]);
        break;
      case 'result':
        pollResult = { correct_ids: new Set(msg.correct_ids), voted_ids: new Set(msg.voted_ids) };
        if (msg.score !== undefined) updateScore(msg.score);
        applyResultColors();
        break;
      case 'timer':
        activeTimer = { seconds: msg.seconds, startedAt: new Date(msg.started_at).getTime() };
        _startParticipantCountdown();
        break;
    }
  }

  function _startParticipantCountdown() {
    clearInterval(_timerInterval);
    _timerInterval = setInterval(() => {
      const el = document.getElementById('pax-countdown');
      if (!el || !activeTimer) { clearInterval(_timerInterval); return; }
      const elapsed = (Date.now() - activeTimer.startedAt) / 1000;
      const remaining = Math.max(0, activeTimer.seconds - elapsed);
      el.textContent = `⏱ ${Math.ceil(remaining)}s`;
      el.style.color = remaining <= 5 ? 'var(--danger)' : 'var(--warn)';
      if (remaining <= 0) {
        clearInterval(_timerInterval);
        activeTimer = null;
        el.textContent = '';
      }
    }, 200);
  }

  function updateParticipantCount(n) {
    document.getElementById('pax-count').textContent = `👥 ${n} participant${n !== 1 ? 's' : ''}`;
  }

  function updateScore(pts) {
    const el = document.getElementById('my-score');
    if (!el) return;
    if (pts) {
      el.textContent = `⭐ ${pts} pt${pts !== 1 ? 's' : ''}`;
      el.style.display = '';
    } else {
      el.style.display = 'none';
    }
  }

  function applyResultColors() {
    if (!pollResult || !currentPoll) return;
    document.querySelectorAll('.option-btn').forEach((btn, i) => {
      const opt = currentPoll.options[i];
      if (!opt) return;
      const wasVoted = pollResult.voted_ids.has(opt.id);
      const isCorrect = pollResult.correct_ids.has(opt.id);
      btn.classList.remove('correct', 'incorrect', 'correct-missed');
      if (isCorrect && wasVoted) btn.classList.add('correct');
      else if (isCorrect && !wasVoted) btn.classList.add('correct-missed');
      else if (wasVoted && !isCorrect) btn.classList.add('incorrect');

      // Inject/update result icon
      let icon = btn.querySelector('.result-icon');
      if (!icon) {
        icon = document.createElement('span');
        icon.className = 'result-icon';
        btn.querySelector('span')?.insertAdjacentElement('afterend', icon);
      }
      if (isCorrect) icon.textContent = '✅';
      else if (wasVoted) icon.textContent = '❌';
      else icon.textContent = '';
    });
  }

  // ── Word Cloud ──
  function renderWordCloudScreen(wordcloudWords) {
    const content = document.getElementById('content');
    if (content.dataset.screen !== 'wordcloud') {
      myWords = [];  // reset on fresh entry
      content.dataset.screen = 'wordcloud';
      content.innerHTML = `
        <div class="wc-layout">
          <div class="wc-cloud-panel">
            <canvas id="wc-canvas"></canvas>
          </div>
          <div class="wc-input-panel">
            <p class="wc-prompt">What word comes to mind?</p>
            <div class="wc-input-row">
              <input id="wc-input" type="text" maxlength="40" autocomplete="off" placeholder="Type a word…" />
              <button id="wc-go" class="btn btn-primary">Go</button>
            </div>
            <ul id="wc-my-words"></ul>
          </div>
        </div>`;
      document.getElementById('wc-go').onclick = submitWord;
      document.getElementById('wc-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') submitWord();
      });
    }
    renderWordCloud(wordcloudWords);
    renderMyWords();
  }

  function submitWord() {
    const input = document.getElementById('wc-input');
    if (!input) return;
    const word = input.value.trim();
    if (!word) return;
    ws.send(JSON.stringify({ type: 'wordcloud_word', word }));
    myWords.unshift(word);
    input.value = '';
    renderMyWords();
  }

  function renderMyWords() {
    const ul = document.getElementById('wc-my-words');
    if (!ul) return;
    ul.innerHTML = myWords.map(w => `<li>${escHtml(w)}</li>`).join('');
  }

  function renderWordCloud(words) {
    const canvas = document.getElementById('wc-canvas');
    if (!canvas) return;
    clearTimeout(_wcDebounceTimer);
    _wcDebounceTimer = setTimeout(() => _drawCloud(canvas, words), 300);
  }

  function _drawCloud(canvas, wordsMap) {
    const entries = Object.entries(wordsMap);
    if (!entries.length) {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    const W = canvas.parentElement.clientWidth || 400;
    const H = canvas.parentElement.clientHeight || 300;
    canvas.width = W;
    canvas.height = H;

    const maxCount = Math.max(...entries.map(([,c]) => c));
    const minCount = Math.min(...entries.map(([,c]) => c));
    const sizeScale = d3.scaleLinear()
      .domain([minCount, maxCount])
      .range([14, 60]);

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
          ctx.translate(W / 2 + w.x, H / 2 + w.y);
          ctx.rotate((w.rotate * Math.PI) / 180);
          ctx.font = `bold ${w.size}px sans-serif`;
          ctx.fillStyle = WC_COLORS[i % WC_COLORS.length];
          ctx.fillText(w.text, 0, 0);
          ctx.restore();
        });
      })
      .start();
  }

  // ── Render ──
  function renderContent(voteCounts) {
    const el = document.getElementById('content');
    if (!currentPoll) {
      el.innerHTML = `<div class="waiting"><div class="icon">⏳</div><p>Waiting for the host to start a poll…</p></div>`;
      return;
    }
    renderPollCard(el, voteCounts);
    applyResultColors();
  }

  function renderPollCard(container, voteCounts) {
    const multi = !!currentPoll.multi;
    const totalVotes = Object.values(voteCounts || {}).reduce((a, b) => a + b, 0);
    const hasVoted = multi ? myVote instanceof Set && myVote.size > 0 : myVote !== null;
    const showResults = !pollActive;

    // Largest-remainder rounding so percentages always sum to exactly 100
    const pcts = largestRemainder(currentPoll.options.map(opt =>
      totalVotes > 0 ? ((voteCounts || {})[opt.id] || 0) / totalVotes * 100 : 0
    ));

    let optionsHTML = currentPoll.options.map((opt, idx) => {
      const pct = pcts[idx];
      const isSelected = multi ? (myVote instanceof Set && myVote.has(opt.id)) : (myVote === opt.id);
      const selected = isSelected ? 'selected' : '';
      const atLimit = multi && currentPoll.correct_count && myVote instanceof Set && myVote.size >= currentPoll.correct_count;
      const disabled = !pollActive || (atLimit && !isSelected) ? 'disabled' : '';
      let resultIcon = '';
      if (pollResult) {
        const wasVoted = pollResult.voted_ids.has(opt.id);
        const isCorrect = pollResult.correct_ids.has(opt.id);
        if (isCorrect) resultIcon = `<span class="result-icon">✅</span>`;
        else if (wasVoted) resultIcon = `<span class="result-icon">❌</span>`;
      }
      return `
        <button class="option-btn ${selected}" ${disabled} onclick="castVote('${opt.id}')">
          <div class="bar" style="width:${showResults ? pct : 0}%"></div>
          <span>${escHtml(opt.text)}</span>
          ${resultIcon}
          ${showResults ? `<span class="pct">${pct}%</span>` : ''}
        </button>`;
    }).join('');

    let footer = '';
    if (!pollActive) {
      footer = `<div class="closed-banner">Voting is closed — final results shown above</div>`;
    } else if (multi) {
      const selCount = myVote instanceof Set ? myVote.size : 0;
      let warning = '';
      const correctCount = currentPoll.correct_count;
      const multiHint = correctCount
        ? `Select exactly ${correctCount} answer${correctCount > 1 ? 's' : ''}`
        : 'Multiple answers may be correct';
      if (selCount > 0) {
        const blink = !_multiWarnShown ? ' blink' : '';
        if (!_multiWarnShown) _multiWarnShown = true;
        warning = `<div class="multi-warning${blink}">⚠️ ${multiHint}!</div>`;
      }
      const atLimit = correctCount && selCount >= correctCount;
      const selMsg = selCount > 0
        ? (atLimit
            ? `✅ ${selCount} of ${correctCount} selected — click to deselect.`
            : `✅ ${selCount} of ${correctCount ?? '?'} selected — click to toggle.`)
        : `<span class="multi-hint">⚠️ ${multiHint}.</span>`;
      footer = `<div class="vote-msg">${selMsg}</div>${warning}`;
    } else if (hasVoted) {
      footer = `<div class="vote-msg">✅ Vote registered! Click another option to change it.</div>`;
    } else {
      footer = `<div class="vote-msg">Choose an option to vote.</div>`;
    }

    const countdownEl = activeTimer
      ? `<div id="pax-countdown" class="pax-countdown" style="color:var(--warn);"></div>`
      : `<div id="pax-countdown" class="pax-countdown"></div>`;

    container.innerHTML = `
      <div class="poll-card">
        <h2>${escHtml(currentPoll.question)}</h2>
        ${optionsHTML}
        ${countdownEl}
        ${footer}
      </div>`;

    if (activeTimer) _startParticipantCountdown();
  }

  function renderOptions(voteCounts, totalVotes) {
    // Lightweight update — only refresh option bars/pcts without full re-render
    if (!currentPoll || pollActive) return;
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
      if (myVote.has(optionId)) {
        myVote.delete(optionId);
      } else {
        const limit = currentPoll.correct_count;
        if (limit && myVote.size >= limit) return; // cap at correct_count
        myVote.add(optionId);
      }
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
    const atLimit = multi && currentPoll.correct_count && myVote instanceof Set && myVote.size >= currentPoll.correct_count;
    document.querySelectorAll('.option-btn').forEach((btn, i) => {
      const opt = currentPoll.options[i];
      if (!opt) return;
      const selected = multi
        ? (myVote instanceof Set && myVote.has(opt.id))
        : (myVote === opt.id);
      btn.classList.toggle('selected', selected);
      if (multi) btn.disabled = atLimit && !selected;
    });

    const hasVoted = multi ? myVote instanceof Set && myVote.size > 0 : myVote !== null;
    let footerHTML = '';
    if (multi) {
      const selCount = myVote instanceof Set ? myVote.size : 0;
      const correctCount = currentPoll.correct_count;
      const multiHint = correctCount
        ? `Select exactly ${correctCount} answer${correctCount > 1 ? 's' : ''}`
        : 'Multiple answers may be correct';
      let warning = '';
      if (selCount > 0) {
        const blink = !_multiWarnShown ? ' blink' : '';
        if (!_multiWarnShown) _multiWarnShown = true;
        warning = `<div class="multi-warning${blink}">⚠️ ${multiHint}!</div>`;
      }
      const atLimit = correctCount && selCount >= correctCount;
      const selMsg = selCount > 0
        ? (atLimit
            ? `✅ ${selCount} of ${correctCount} selected — click to deselect.`
            : `✅ ${selCount} of ${correctCount ?? '?'} selected — click to toggle.`)
        : `<span class="multi-hint">⚠️ ${multiHint}.</span>`;
      footerHTML = `<div class="vote-msg">${selMsg}</div>${warning}`;
    } else {
      footerHTML = `<div class="vote-msg">✅ Vote registered! Click another option to change it.</div>`;
    }
    const card = document.querySelector('.poll-card');
    if (card) {
      // Replace both vote-msg and any existing warning
      const existing = card.querySelector('.vote-msg');
      const existingWarn = card.querySelector('.multi-warning');
      if (existing) existing.outerHTML = footerHTML;
      else card.insertAdjacentHTML('beforeend', footerHTML);
      if (existingWarn) existingWarn.remove();
    }
  }
