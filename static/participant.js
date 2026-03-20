  const LS_KEY = 'workshop_participant_name';
  const LS_UUID_KEY = 'workshop_participant_uuid';
  const LS_VOTE_KEY = 'workshop_vote';

  const isHost = document.cookie.includes('is_host=1');
  const uuidStorage = isHost ? sessionStorage : localStorage;

  function getOrCreateUUID() {
      let uid = uuidStorage.getItem(LS_UUID_KEY);
      if (!uid) {
          uid = crypto.randomUUID();
          uuidStorage.setItem(LS_UUID_KEY, uid);
      }
      return uid;
  }

  let myUUID = getOrCreateUUID();
  let ws = null;
  let myName = '';
  let myVote = null;      // string (single) or Set of option_ids (multi)
  let currentPoll = null;
  let pollActive = false;
  let pollResult = null;  // {correct_ids, voted_ids} once host marks correct options
  let activeTimer = null; // {seconds, startedAt (ms)} or null
  let _timerInterval = null;
  let _multiWarnShown = false; // true once warning has been shown for current poll
  let focusedOptionIndex = -1;  // keyboard navigation index for poll options
let myWords = [];  // participant's own submitted words (persisted in localStorage per word cloud session)
  const LS_WC_KEY = 'workshop_wc_words';
  const LS_WC_SESSION_KEY = 'workshop_wc_session';
  let _lastWordcloudWords = {};
  let _lastWordcloudTopic = '';
  const WC_COLORS = ['#7ecef4','#a78bfa','#34d399','#fbbf24','#f472b6','#60a5fa','#fb923c'];
  let _wcDebounceTimer = null;
  const versionReloadGuard = window.createVersionReloadGuard
    ? window.createVersionReloadGuard({ countdownSeconds: 10 })
    : null;
  window.__versionReloadGuard = versionReloadGuard;
  const _QA_TOASTS = [
    "💬 Ask a question — earn points!",
    "👍 Upvote a great question — both you and the author earn points!",
    "🏆 The more you engage, the higher you rank!",
    "🤔 Got a burning question? Type it in!",
    "⬆️ See a question you like? Give it an upvote!",
  ];
  let _qaToastIndex = 0;
  let _qaToastInterval = null;
  let _qaToastTimeout = null;
  let _prevPollActive = false;
  let _prevActivity = null;
  let _stateInitialised = false;   // skip notifications on first state (join mid-session)
  let _notifBtnBound = false;      // prevent re-binding on reconnect
  let summaryPoints = [];
  let summaryUpdatedAt = null;

  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function updateSummary(points, updatedAt) {
    summaryPoints = points || [];
    summaryUpdatedAt = updatedAt;
    const btn = document.getElementById('summary-btn');
    if (btn) btn.style.display = summaryPoints.length ? '' : 'none';
    renderSummaryList();
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
    list.innerHTML = summaryPoints.map(p => `<li>${escHtml(p)}</li>`).join('');
    if (timeEl && summaryUpdatedAt) {
      const d = new Date(summaryUpdatedAt);
      timeEl.textContent = 'Updated ' + d.toLocaleTimeString();
    }
  }

  function toggleSummaryModal() {
    const overlay = document.getElementById('summary-overlay');
    if (overlay) overlay.classList.toggle('open');
  }

  function closeSummaryModal() {
    const overlay = document.getElementById('summary-overlay');
    if (overlay) overlay.classList.remove('open');
  }

  async function requestNotificationPermission() {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'default') return;
    await Notification.requestPermission();
    const btn = document.getElementById('notif-btn');
    if (btn) btn.style.display = 'none';
  }

  function notifyIfHidden(title, body) {
    if (!document.hidden) return;
    if (Notification.permission !== 'granted') return;
    try { new Notification(title, { body }); } catch (_) {}
  }

  // Largest-remainder rounding: ensures integer percentages sum to exactly 100
  function largestRemainder(floats) {
    const total = floats.reduce((a, b) => a + b, 0);
    if (total === 0) return floats.map(() => 0);
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
  let suggestedName = '';
  let _joinedWithSuggestion = false;
  const savedName = localStorage.getItem(LS_KEY);
  if (savedName) {
    nameInput.value = savedName;
    join();   // auto-join — permission requested via 🔔 button in ws.onopen (no user gesture here)
  } else {
    fetchSuggestedName().then(name => {
      suggestedName = name;
      nameInput.placeholder = name;
      nameInput.focus();
    });
  }
  updateClearBtn();

  nameInput.addEventListener('input', () => {
    updateClearBtn();
    const errEl = document.getElementById('join-error');
    if (errEl) errEl.style.display = 'none';
  });

  function updateClearBtn() {
    clearBtn.style.display = nameInput.value ? 'block' : 'none';
  }

  clearBtn.addEventListener('click', async () => {
    localStorage.removeItem(LS_KEY);
    nameInput.value = '';
    suggestedName = await fetchSuggestedName();
    nameInput.placeholder = suggestedName;
    updateClearBtn();
    nameInput.focus();
  });

  // ── Join ──
  document.getElementById('join-btn').addEventListener('click', () => { join(); requestNotificationPermission(); });
  nameInput.addEventListener('keydown', e => { if (e.key === 'Enter') { join(); requestNotificationPermission(); } });

  function join() {
    const input = document.getElementById('name-input');
    const name = input.value.trim() || suggestedName;
    if (!name) { input.focus(); return; }
    _joinedWithSuggestion = !input.value.trim();
    myName = name;
    localStorage.setItem(LS_KEY, name);
    connectWS(name);
  }

  // ── Inline name editing ──
  document.getElementById('edit-name-btn').addEventListener('click', () => {
    const display = document.getElementById('display-name');
    const editWrap = document.getElementById('name-edit-wrap');
    const editInput = document.getElementById('name-edit-input');
    const editBtn = document.getElementById('edit-name-btn');
    editInput.value = myName;
    display.style.display = 'none';
    editBtn.style.display = 'none';
    editWrap.style.display = '';
    editInput.focus();
    editInput.select();
  });

  function confirmNameEdit() {
    const newName = document.getElementById('name-edit-input').value.trim();
    if (newName && newName !== myName) {
        myName = newName;
        localStorage.setItem(LS_KEY, myName);
        document.getElementById('display-name').textContent = myName;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'set_name', name: myName }));
        }
    }
    document.getElementById('display-name').style.display = '';
    document.getElementById('edit-name-btn').style.display = '';
    document.getElementById('name-edit-wrap').style.display = 'none';
  }

  document.getElementById('name-edit-ok').addEventListener('click', confirmNameEdit);
  document.getElementById('name-edit-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') confirmNameEdit();
    if (e.key === 'Escape') {
        document.getElementById('display-name').style.display = '';
        document.getElementById('edit-name-btn').style.display = '';
        document.getElementById('name-edit-wrap').style.display = 'none';
    }
  });

  // ── Location ──
  const LS_LOCATION_KEY = 'workshop_participant_location';

  function getTimezoneLocation() {
    return `🕐 ${Intl.DateTimeFormat().resolvedOptions().timeZone}`;
  }

  function sendLocation(locationStr) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'location', location: locationStr }));
    }
  }

  function updateLocationPrompt() {
    const el = document.getElementById('location-prompt');
    if (!el) return;
    el.style.display = localStorage.getItem(LS_LOCATION_KEY) ? 'none' : '';
  }

  function requestLocation() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude: lat, longitude: lon } = pos.coords;
        const locationStr = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
        localStorage.setItem(LS_LOCATION_KEY, locationStr);
        sendLocation(locationStr);
        updateLocationPrompt();
      },
      () => { /* user denied — prompt stays visible, they can retry */ },
      { timeout: 15000, maximumAge: 60000 }
    );
  }

  // ── WebSocket ──
  function connectWS(name) {
    _stateInitialised = false;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/ws/${encodeURIComponent(myUUID)}`;
    ws = new WebSocket(url);

    ws.onopen = () => {
      document.getElementById('join-screen').style.display = 'none';
      document.getElementById('main-screen').style.display = 'block';
      document.getElementById('display-name').textContent = myName;

      // Send name as first message
      ws.send(JSON.stringify({ type: 'set_name', name: myName }));

      // Show 🔔 button for auto-joiners who haven't been asked for permission yet
      if ('Notification' in window && Notification.permission === 'default' && !_notifBtnBound) {
        _notifBtnBound = true;
        const btn = document.getElementById('notif-btn');
        if (btn) { btn.style.display = ''; btn.onclick = requestNotificationPermission; }
      }

      // Send stored GPS location if available, otherwise silent timezone fallback
      const storedLocation = localStorage.getItem(LS_LOCATION_KEY);
      sendLocation(storedLocation || getTimezoneLocation());
      updateLocationPrompt();
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      handleMessage(msg);
    };

    ws.onclose = () => {
      setTimeout(() => connectWS(myName), 3000);
    };
  }

  // ── Vote persistence ──
  function saveVote() {
    if (!currentPoll) return;
    const stored = {
      pollId: currentPoll.id,
      vote: currentPoll.multi ? [...myVote] : myVote,
    };
    localStorage.setItem(LS_VOTE_KEY, JSON.stringify(stored));
  }

  function restoreVote(poll) {
    if (!poll) return;
    try {
      const stored = JSON.parse(localStorage.getItem(LS_VOTE_KEY) || 'null');
      if (!stored || stored.pollId !== poll.id) return;
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
        versionReloadGuard && versionReloadGuard.check(msg.backend_version);
        if (!_stateInitialised) {
          // First message after connect: seed tracking state, fire no notification
          _prevPollActive = msg.poll_active;
          _prevActivity   = msg.current_activity;
          _stateInitialised = true;
        } else {
          if (!_prevPollActive && msg.poll_active && msg.poll) {
            notifyIfHidden('🗳️ New poll!', msg.poll.question);
          }
          if (_prevActivity !== 'qa' && msg.current_activity === 'qa') {
            notifyIfHidden('❓ Q&A is open', 'Tap to ask or upvote questions');
          }
          if (_prevActivity !== 'wordcloud' && msg.current_activity === 'wordcloud') {
            notifyIfHidden('☁️ Word cloud is open', 'Tap to share your thoughts');
          }
          _prevPollActive = msg.poll_active;
          _prevActivity   = msg.current_activity;
        }
        if (msg.poll?.id !== currentPoll?.id) {
          myVote = msg.poll?.multi ? new Set() : null;
          pollResult = null;
          activeTimer = null;
          _multiWarnShown = false;
          focusedOptionIndex = -1;
          clearInterval(_timerInterval);
          restoreVote(msg.poll);
        }
        currentPoll = msg.poll;
        pollActive = msg.poll_active;
        updateParticipantCount(msg.participant_count);
        updateScore(msg.my_score);
        window._myScore = msg.my_score || 0;
        window._qaQuestions = msg.qa_questions || [];
        if (msg.current_activity === 'wordcloud') {
          renderWordCloudScreen(msg.wordcloud_words || {}, msg.wordcloud_topic || '');
        } else if (msg.current_activity === 'qa') {
          renderQAScreen(msg.qa_questions || []);
        } else {
          const content = document.getElementById('content');
          if (content) content.dataset.screen = '';
          myWords = [];
          renderQACleanup();
          renderContent(msg.vote_counts);
        }
        updateSummary(msg.summary_points, msg.summary_updated_at);
        break;
      case 'vote_update':
        renderOptions(msg.vote_counts, msg.total_votes);
        break;
      case 'participant_count':
        updateParticipantCount(msg.count);
        break;
      case 'scores':
        break;
      case 'result':
        pollResult = { correct_ids: new Set(msg.correct_ids), voted_ids: new Set(msg.voted_ids) };
        if (msg.score !== undefined) {
          const gained = msg.score - _displayedScore;
          updateScore(msg.score);
          if (gained > 0) launchConfetti(gained);
        }
        applyResultColors();
        break;
      case 'timer':
        activeTimer = { seconds: msg.seconds, startedAt: new Date(msg.started_at).getTime() };
        _startParticipantCountdown();
        break;
      case 'summary':
        updateSummary(msg.points, msg.updated_at);
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

  let _displayedScore = 0;
  let _scoreRollTimer = null;

  function updateScore(pts) {
    const el = document.getElementById('my-score');
    if (!el) return;
    if (!pts) { el.style.display = 'none'; _displayedScore = 0; return; }
    el.style.display = '';
    const from = _displayedScore;
    const to = pts;
    if (from === to) return;
    if (_scoreRollTimer) clearInterval(_scoreRollTimer);
    if (to > from) {
      // Re-trigger flash animation by removing and re-adding the class
      el.classList.remove('score-flash');
      void el.offsetWidth; // force reflow
      el.classList.add('score-flash');
    }
    const duration = 800; // ms
    const steps = 30;
    const interval = duration / steps;
    let step = 0;
    _scoreRollTimer = setInterval(() => {
      step++;
      const t = step / steps;
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      const current = Math.round(from + (to - from) * eased);
      el.textContent = `⭐ ${current} pts`;
      if (step >= steps) {
        clearInterval(_scoreRollTimer);
        _scoreRollTimer = null;
        _displayedScore = to;
        el.textContent = `⭐ ${to} pts`;
      }
    }, interval);
  }

  function launchConfetti(pts) {
    // Logarithmic scale: 0 particles at 0pts, ~80 at 1000pts (max)
    const MAX_PTS = 1000;
    const MAX_PARTICLES = 80;
    const count = Math.round(MAX_PARTICLES * Math.log1p(pts) / Math.log1p(MAX_PTS));
    if (count <= 0) return;

    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999';
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    document.body.appendChild(canvas);
    const ctx = canvas.getContext('2d');

    const colors = ['#6c63ff','#ff6584','#43e97b','#f7971e','#38f9d7','#ffd700'];
    const particles = Array.from({length: count}, () => ({
      x: Math.random() * canvas.width,
      y: -10 - Math.random() * 40,
      vx: (Math.random() - 0.5) * 4,
      vy: 2 + Math.random() * 4,
      size: 6 + Math.random() * 6,
      color: colors[Math.floor(Math.random() * colors.length)],
      rot: Math.random() * Math.PI * 2,
      rotV: (Math.random() - 0.5) * 0.2,
    }));

    let frame;
    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      let alive = false;
      for (const p of particles) {
        p.x += p.vx; p.y += p.vy; p.rot += p.rotV; p.vy += 0.12;
        if (p.y < canvas.height + 20) alive = true;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot);
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
        ctx.restore();
      }
      if (alive) { frame = requestAnimationFrame(draw); }
      else { canvas.remove(); }
    }
    draw();
    // Safety cleanup after 4s
    setTimeout(() => { cancelAnimationFrame(frame); canvas.remove(); }, 4000);
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
  function renderWordCloudScreen(wordcloudWords, topic) {
    _lastWordcloudWords = wordcloudWords;
    _lastWordcloudTopic = topic || '';
    const content = document.getElementById('content');
    // If server word cloud is empty, host cleared it — wipe local words too
    if (Object.keys(wordcloudWords).length === 0) {
      myWords = [];
      localStorage.removeItem(LS_WC_KEY);
    }
    if (content.dataset.screen !== 'wordcloud') {
      // Restore words from localStorage on screen entry (e.g. page refresh)
      try { myWords = JSON.parse(localStorage.getItem(LS_WC_KEY) || '[]'); } catch { myWords = []; }
      content.dataset.screen = 'wordcloud';
      content.innerHTML = `
        <div class="wc-layout">
          <div class="wc-cloud-panel">
            <canvas id="wc-canvas"></canvas>
          </div>
          <div class="wc-input-panel">
            <p class="wc-prompt" id="wc-prompt-text">What comes to mind? <span style="font-size:.9em; opacity:.75; font-weight:normal">(pts++)</span></p>
            <div class="wc-input-row">
              <input id="wc-input" type="text" maxlength="40" autocomplete="off" placeholder="Type a word…" list="wc-suggestions" />
              <datalist id="wc-suggestions"></datalist>
              <button id="wc-go" class="btn btn-primary">🚀</button>
            </div>
            <button id="wc-download" class="btn btn-secondary wc-download-btn">⬇ Download Image</button>
            <div id="wc-my-words"></div>
          </div>
        </div>`;
      document.getElementById('wc-go').onclick = submitWord;
      document.getElementById('wc-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') submitWord();
      });
      document.getElementById('wc-download').onclick = () => {
        const canvas = document.getElementById('wc-canvas');
        if (!canvas) return;
        const a = document.createElement('a');
        a.href = canvas.toDataURL('image/png');
        a.download = `wordcloud-${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.png`;
        a.click();
      };
    }
    // Update prompt with topic (may change after screen is shown)
    const promptEl = document.getElementById('wc-prompt-text');
    if (promptEl) {
      // Topic is shown on the canvas image, so keep prompt simple
      promptEl.innerHTML = `What comes to mind? <span style="font-size:.9em; opacity:.75; font-weight:normal">(pts++)</span>`;
    }
    renderWordCloud(wordcloudWords);
    renderMyWords();
    updateWordSuggestions(wordcloudWords);
  }

  function submitWord() {
    const input = document.getElementById('wc-input');
    if (!input) return;
    const word = input.value.trim();
    if (!word) return;
    ws.send(JSON.stringify({ type: 'wordcloud_word', word }));
    myWords.unshift(word);
    localStorage.setItem(LS_WC_KEY, JSON.stringify(myWords));
    input.value = '';
    renderMyWords();
    updateWordSuggestions(_lastWordcloudWords || {});
  }

  function renderMyWords() {
    const el = document.getElementById('wc-my-words');
    if (!el) return;
    el.innerHTML = myWords.map(w => `<div class="wc-my-word">${escHtml(w)}</div>`).join('');
  }

  function updateWordSuggestions(wordcloudWords) {
    const dl = document.getElementById('wc-suggestions');
    if (!dl) return;
    const mySet = new Set(myWords.map(w => w.toLowerCase()));
    dl.innerHTML = Object.keys(wordcloudWords)
      .filter(w => !mySet.has(w.toLowerCase()))
      .map(w => `<option value="${escHtml(w)}">`)
      .join('');
  }

  function renderWordCloud(words) {
    const canvas = document.getElementById('wc-canvas');
    if (!canvas) return;
    clearTimeout(_wcDebounceTimer);
    _wcDebounceTimer = setTimeout(() => _drawCloud(canvas, words), 300);
  }

  function _drawCloud(canvas, wordsMap) {
    const entries = Object.entries(wordsMap);
    const TITLE_H = _lastWordcloudTopic ? 40 : 0;
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

    const cloudH = H - TITLE_H;
    d3.layout.cloud()
      .size([W, cloudH])
      .words(entries.map(([text, count]) => ({ text, size: sizeScale(count) })))
      .padding(4)
      .rotate(() => (Math.random() > 0.5 ? 90 : 0))
      .font('sans-serif')
      .fontSize(d => d.size)
      .on('end', (placed) => {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, W, H);
        // Draw topic title
        if (_lastWordcloudTopic) {
          ctx.textAlign = 'center';
          ctx.font = 'bold 20px sans-serif';
          ctx.fillStyle = 'rgba(255,255,255,0.75)';
          ctx.fillText(_lastWordcloudTopic, W / 2, 28);
        }
        // Draw words offset below the title
        ctx.textAlign = 'center';
        placed.forEach((w, i) => {
          ctx.save();
          ctx.translate(W / 2 + w.x, TITLE_H + cloudH / 2 + w.y);
          ctx.rotate((w.rotate * Math.PI) / 180);
          ctx.font = `bold ${w.size}px sans-serif`;
          ctx.fillStyle = WC_COLORS[i % WC_COLORS.length];
          ctx.fillText(w.text, 0, 0);
          ctx.restore();
        });
      })
      .start();
  }

  // ── Q&A ──
  function _showQAToast() {
    const el = document.getElementById('qa-toast');
    if (!el) return;
    el.textContent = _QA_TOASTS[_qaToastIndex % _QA_TOASTS.length];
    _qaToastIndex++;
    el.classList.add('visible');
    clearTimeout(_qaToastTimeout);
    _qaToastTimeout = setTimeout(() => el.classList.remove('visible'), 4400);
  }

  function _startQAToasts(questions) {
    _stopQAToasts();
    if (!questions || questions.length === 0) _showQAToast();
    _qaToastInterval = setInterval(_showQAToast, 15000);
  }

  function _stopQAToasts() {
    clearInterval(_qaToastInterval);
    clearTimeout(_qaToastTimeout);
    _qaToastInterval = null;
    const el = document.getElementById('qa-toast');
    if (el) el.classList.remove('visible');
  }

  function renderQAScreen(questions) {
    const content = document.getElementById('content');
    if (!content) return;
    if (content.dataset.screen === 'qa') {
      // Already on Q&A screen — just refresh the list
      updateQAList(questions);
      return;
    }
    content.dataset.screen = 'qa';
    content.innerHTML = `
      <div class="qa-screen">
        <div class="qa-input-row">
          <input id="qa-input" type="text" maxlength="280" autocomplete="off"
                 placeholder="Ask a question…" />
          <button id="qa-submit-btn" class="btn btn-primary" onclick="submitQuestion()">↵</button>
        </div>
        <div id="qa-question-list"></div>
      </div>
    `;
    const input = document.getElementById('qa-input');
    if (input) {
      input.addEventListener('keydown', e => { if (e.key === 'Enter') submitQuestion(); });
    }
    updateQAList(questions);
    _startQAToasts(questions);
  }

  function updateQAList(questions) {
    const list = document.getElementById('qa-question-list');
    if (!list) return;
    const condensed = questions.length >= 6;

    if (!questions.length) {
      list.innerHTML = '<p style="text-align:center;color:var(--muted);margin-top:1.5rem;font-size:.9rem;">No questions yet. Be the first!</p>';
      return;
    }

    list.innerHTML = questions.map(q => {
      const isOwn = q.is_own;
      const hasUpvoted = q.has_upvoted;
      const canUpvote = !isOwn && !hasUpvoted;
      return `
        <div class="qa-card-p${q.answered ? ' qa-answered-p' : ''}${condensed ? ' qa-condensed' : ''}" data-id="${escHtml(q.id)}">
          <div class="qa-text-p">${escHtml(q.text)}</div>
          <div class="qa-footer-p">
            <span class="qa-author-p">${escHtml(q.author)}${isOwn ? ' (you)' : ''}</span>
            <button class="qa-upvote-btn${hasUpvoted ? ' qa-upvoted' : ''}"
                    data-qid="${escHtml(q.id)}"
                    ${canUpvote ? `onclick="upvoteQuestion('${escHtml(q.id)}')"` : 'disabled'}
                    title="${canUpvote ? 'Upvote' : (isOwn ? 'Your question' : 'Already upvoted')}">
              ▲ ${q.upvote_count}
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  function submitQuestion() {
    const input = document.getElementById('qa-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text || !ws) return;
    ws.send(JSON.stringify({ type: 'qa_submit', text }));
    input.value = '';
    input.focus();
  }

  function upvoteQuestion(questionId) {
    if (!ws) return;
    ws.send(JSON.stringify({ type: 'qa_upvote', question_id: questionId }));
  }

  function renderQACleanup() {
    _stopQAToasts();
    // Q&A DOM is inside #content which gets replaced when switching activities
  }

  // ── Render ──
  function renderContent(voteCounts) {
    const el = document.getElementById('content');
    if (!currentPoll) {
      el.innerHTML = `<div class="waiting"><div class="icon">⏳</div><p>Waiting for host…</p></div>`;
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
      const focused = idx === focusedOptionIndex ? 'focused' : '';
      const checkbox = multi ? `<span class="multi-check">${isSelected ? '☑' : '☐'}</span> ` : '';
      return `
        <button class="option-btn ${selected} ${focused}" ${disabled} onclick="castVote('${opt.id}')">
          <div class="bar" style="width:${showResults ? pct : 0}%"></div>
          <span>${checkbox}${escHtml(opt.text)}</span>
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
      const atLimit = correctCount && selCount >= correctCount;
      if (selCount > 0 && !atLimit) {
        const blink = !_multiWarnShown ? ' blink' : '';
        if (!_multiWarnShown) _multiWarnShown = true;
        warning = `<div class="multi-warning${blink}">⚠️ ${multiHint}!</div>`;
      }
      const selMsg = selCount > 0
        ? (atLimit
            ? `✅ ${selCount} of ${correctCount} selected — click to deselect.`
            : `✅ ${selCount} of ${correctCount ?? '?'} selected — click to toggle.`)
        : `<span class="multi-hint">⚠️ ${multiHint}.</span>`;
      footer = `<div class="vote-msg">${selMsg}</div>${atLimit ? '' : warning}`;
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

  // ── Keyboard navigation for polls ──
  document.addEventListener('keydown', (e) => {
    if (!currentPoll || !pollActive) return;
    // Don't capture keys if user is typing in an input/textarea
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;

    const options = document.querySelectorAll('.option-btn');
    if (!options.length) return;

    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (e.key === 'ArrowDown') {
        focusedOptionIndex = focusedOptionIndex < options.length - 1 ? focusedOptionIndex + 1 : 0;
      } else {
        focusedOptionIndex = focusedOptionIndex > 0 ? focusedOptionIndex - 1 : options.length - 1;
      }
      updateFocusedOption(options);
    } else if (e.key === 'Enter' && !currentPoll.multi) {
      // Single-select: Enter submits the focused option
      if (focusedOptionIndex >= 0 && focusedOptionIndex < currentPoll.options.length) {
        e.preventDefault();
        castVote(currentPoll.options[focusedOptionIndex].id);
      }
    } else if (e.key === ' ' && currentPoll.multi) {
      // Multi-select: Space toggles the focused option
      if (focusedOptionIndex >= 0 && focusedOptionIndex < currentPoll.options.length) {
        e.preventDefault();
        castVote(currentPoll.options[focusedOptionIndex].id);
      }
    }
  });

  function updateFocusedOption(options) {
    options.forEach((btn, i) => {
      btn.classList.toggle('focused', i === focusedOptionIndex);
    });
    if (focusedOptionIndex >= 0 && options[focusedOptionIndex]) {
      options[focusedOptionIndex].scrollIntoView({ block: 'nearest' });
    }
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
      if (multi) {
        btn.disabled = atLimit && !selected;
        const checkEl = btn.querySelector('.multi-check');
        if (checkEl) checkEl.textContent = selected ? '☑' : '☐';
      }
    });

    const hasVoted = multi ? myVote instanceof Set && myVote.size > 0 : myVote !== null;
    let footerHTML = '';
    if (multi) {
      const selCount = myVote instanceof Set ? myVote.size : 0;
      const correctCount = currentPoll.correct_count;
      const multiHint = correctCount
        ? `Select exactly ${correctCount} answer${correctCount > 1 ? 's' : ''}`
        : 'Multiple answers may be correct';
      const atLimit = correctCount && selCount >= correctCount;
      let warning = '';
      if (selCount > 0 && !atLimit) {
        const blink = !_multiWarnShown ? ' blink' : '';
        if (!_multiWarnShown) _multiWarnShown = true;
        warning = `<div class="multi-warning${blink}">⚠️ ${multiHint}!</div>`;
      }
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
