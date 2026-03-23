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

  let _hostWcDebounceTimer = null;
  let _hostWcLastDataKey = null;
  let currentMode = 'workshop';
  let _autoReturnTimer = null;
  const AUTO_RETURN_DELAY = 30000; // 30 seconds
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
  const pLink = document.getElementById('participant-link');
  pLink.href = link;
  pLink.innerHTML = location.host.split('').map((ch, i) =>
    `<span class="wave-char" style="animation-delay:${(i * 0.12).toFixed(2)}s">${ch}</span>`
  ).join('');

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
      if (msg.type === 'leaderboard') {
        renderLeaderboard(msg);
        return;
      }
      if (msg.type === 'leaderboard_hide') {
        hideLeaderboard();
        return;
      }
      if (msg.type === 'state') {
        versionReloadGuard && versionReloadGuard.check(msg.backend_version);
        const prevQuestion = currentPoll?.question;
        currentPoll = msg.poll;
        if (!msg.poll_active && pollActive) _clearTimer(); // poll just closed
        pollActive = msg.poll_active;
        // Restore poll timer from server state (survives refresh)
        if (msg.poll_timer_seconds && msg.poll_timer_started_at) {
          _applyTimer(msg.poll_timer_seconds, msg.poll_timer_started_at);
        }
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
        updatePaxBadge(msg.participant_count);
        renderParticipantList(names);
        updateLeaderboardButton();
        renderDaemonStatus(msg.daemon_connected, msg.daemon_last_seen);
        updateTokenBadge(msg.token_usage);
        renderTranscriptStatus(msg.transcript_line_count, msg.transcript_total_lines, msg.transcript_latest_ts);
        renderOverlayStatus(msg.overlay_connected);
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
        if (msg.mode) {
          currentMode = msg.mode;
          renderMode(msg.mode);
        }
        // Restore leaderboard overlay if it was active
        if (msg.leaderboard_active && msg.leaderboard_data) {
          renderLeaderboard(msg.leaderboard_data);
        }
      } else if (msg.type === 'vote_update') {
        voteCounts = msg.vote_counts || {};
        totalVotes = msg.total_votes || 0;
        renderBars();
      } else if (msg.type === 'participant_count') {
        document.getElementById('pax-count').textContent = msg.count;
        updatePaxBadge(msg.count);
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
        updateLeaderboardButton();
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
      } else if (msg.type === 'debate_timer') {
        _stopBeeping();
        _debateRoundTimer = { roundIndex: msg.round_index, seconds: msg.seconds, startedAt: new Date(msg.started_at).getTime() };
        if (_lastDebateMsg) renderDebateHost(_lastDebateMsg);
        _startDebateCountdown();
      } else if (msg.type === 'debate_round_ended') {
        _debateRoundTimer = null;
        clearInterval(_debateTimerInterval);
        _stopBeeping();
        if (_lastDebateMsg) {
          _lastDebateMsg.debate_round_timer_started_at = null;
          _lastDebateMsg.debate_round_timer_seconds = null;
          renderDebateHost(_lastDebateMsg);
        }
      } else if (msg.type === 'quiz_status') {
        renderQuizStatus(msg.status, msg.message);
      } else if (msg.type === 'quiz_preview') {
        renderPreview(msg.quiz || null);
      } else if (msg.type === 'summary') {
        updateSummary(msg.points, msg.updated_at);
      } else if (msg.type === 'emoji_reaction') {
        showHostEmoji(msg.emoji);
      }
    };
  }

  function showHostEmoji(emoji) {
    const el = document.createElement('div');
    el.className = 'host-emoji-float';
    el.textContent = emoji;
    document.body.appendChild(el);

    // Spawn from bottom-right corner
    const startX = window.innerWidth - 120;
    const startY = window.innerHeight - 80;
    el.style.left = startX + 'px';
    el.style.top = startY + 'px';
    el.style.transform = 'translate(-50%, -50%)';

    const duration = 2500 + Math.random() * 1500;
    const riseHeight = 500;

    // Rise up with wobble (fâțâială)
    const wobbleAmp = 15 + Math.random() * 10; // px wobble amplitude
    const wobbleFreq = 3 + Math.random() * 2; // number of wobbles during rise
    const steps = 20;
    const keyframes = [];
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const y = -riseHeight * t;
      const wobble = Math.sin(t * wobbleFreq * Math.PI * 2) * wobbleAmp * (1 - t * 0.5);
      const scale = 1 + t * 0.3; // slight grow
      const opacity = t < 0.4 ? 1 : 1 - (t - 0.4) / 0.6;
      keyframes.push({
        transform: `translate(calc(-50% + ${wobble}px), calc(-50% + ${y}px)) scale(${scale})`,
        opacity: opacity,
        offset: t
      });
    }

    const anim = el.animate(keyframes, {
      duration: duration,
      easing: 'ease-out',
      fill: 'forwards'
    });
    anim.onfinish = () => el.remove();
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
      badge.textContent = summaryPoints.length > 0 ? `🧠 ${summaryPoints.length}` : '🧠';
      badge.className = 'badge connected';
      badge.title = `${summaryPoints.length} key points — click to view`;
    } else if (_summaryGenerating) {
      badge.textContent = '🧠';
      badge.className = 'badge';
      badge.style.cssText = 'cursor:wait; color:var(--warn); border:1px solid var(--warn); animation: pulse 1.2s ease-in-out infinite;';
      badge.title = 'Generating key points from transcript...';
    } else {
      badge.textContent = '🧠';
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
      if (!confirm('No summary cached for today.\nFeed the entire day\'s transcript to AI for summarization?')) return;
      _summaryGenerating = true;
      renderSummaryBadge();
      fetch('/api/summary/force', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_day: true }),
      });
    }
  }

  function closeSummaryModal() {
    const overlay = document.getElementById('summary-overlay');
    if (overlay) overlay.classList.remove('open');
  }

  function setBadge(ok) {
    const b = document.getElementById('ws-badge');
    b.textContent = ok ? '🟢' : '🟢';
    b.className = `badge ${ok ? 'connected' : 'disconnected'}`;
  }

  function updateTokenBadge(usage) {
    const el = document.getElementById('token-cost');
    if (!el || !usage) return;
    const cost = usage.estimated_cost_usd || 0;
    el.textContent = '$' + cost.toFixed(2);
    const inp = (usage.input_tokens || 0).toLocaleString();
    const out = (usage.output_tokens || 0).toLocaleString();
    el.title = 'Tokens: ' + inp + ' in / ' + out + ' out';
    el.style.color = cost > 3 ? 'var(--danger)' : cost > 1 ? 'var(--warn)' : 'var(--muted)';
  }

  async function toggleMode() {
    const newMode = (currentMode === 'workshop') ? 'conference' : 'workshop';
    await fetch('/api/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: newMode }),
    });
  }

  function renderMode(mode) {
    const badge = document.getElementById('mode-badge');
    if (!badge) return;
    badge.textContent = mode === 'conference' ? '🎤' : '🎓';
    badge.title = mode === 'conference' ? 'Conference mode — click to switch to Workshop' : 'Workshop mode — click to switch to Conference';
    badge.className = 'badge ' + (mode === 'conference' ? 'mode-badge-conference' : 'mode-badge-workshop');
    applyConferenceLayout(mode === 'conference');
  }

  function applyConferenceLayout(isConference) {
    const rightCol = document.querySelector('.host-col-right');
    const grid = document.querySelector('.host-columns');
    const confQR = document.getElementById('conference-qr');
    const debateTab = document.getElementById('tab-debate');
    const helloTab = document.getElementById('tab-hello');
    const tokenCost = document.getElementById('token-cost');
    const notesBadge = document.getElementById('notes-badge');
    const centerQR = document.getElementById('center-qr');

    // Detect light/dark mode for QR color adaptation
    const isLight = window.matchMedia('(prefers-color-scheme: light)').matches;

    const leftCol = document.querySelector('.host-col-left');
    if (isConference) {
      rightCol.style.display = 'none';
      grid.style.gridTemplateColumns = '25% 1fr';
      leftCol.classList.add('conference-layout');
      // Show left QR only when an activity is active (center QR not visible)
      const centerQRVisible = document.getElementById('center-qr').style.display !== 'none';
      confQR.style.display = centerQRVisible ? 'none' : 'flex';
      if (debateTab) debateTab.style.display = 'none';
      if (helloTab) helloTab.style.display = '';
      startAutoReturnTimer();
      if (tokenCost) tokenCost.style.display = 'none';
      if (notesBadge) notesBadge.style.display = 'none';
      // Generate left QR (hidden until needed) — sized to fill container height
      const qrContainer = document.getElementById('conference-qr-code');
      qrContainer.innerHTML = '';
      const pLink = document.getElementById('participant-link');
      if (pLink && pLink.href && typeof QRCode !== 'undefined') {
        // Defer QR generation to let grid layout settle
        requestAnimationFrame(() => {
          const confQREl = document.getElementById('conference-qr');
          const availH = confQREl ? confQREl.clientHeight - 40 : 200; // subtract padding + URL label
          const availW = confQREl ? confQREl.clientWidth - 20 : 200; // subtract horizontal padding
          const qrSize = Math.max(120, Math.min(availH, availW, 400));
          qrContainer.style.width = qrSize + 'px';
          qrContainer.style.height = qrSize + 'px';
          new QRCode(qrContainer, { text: pLink.href, width: qrSize, height: qrSize, colorDark: '#000', colorLight: '#fff' });
        });
      }
      // URL with https:// prefix and wave animation in left QR panel
      const urlEl = document.getElementById('conference-qr-url');
      if (urlEl) {
        const fullUrl = 'https://' + location.host;
        urlEl.innerHTML = fullUrl.split('').map((ch, i) =>
          `<span class="wave-char" style="animation-delay:${(i * 0.12).toFixed(2)}s">${ch}</span>`
        ).join('');
      }
      // Show URL above center QR in conference mode
      const centerQRUrl = document.getElementById('center-qr-url');
      if (centerQRUrl) {
        const fullUrl = 'https://' + location.host;
        centerQRUrl.innerHTML = fullUrl.split('').map((ch, i) =>
          `<span class="wave-char" style="animation-delay:${(i * 0.12).toFixed(2)}s">${ch}</span>`
        ).join('');
        centerQRUrl.style.display = '';
      }
      // Make center QR bright for conference — color adapts to theme
      if (centerQR) centerQR.classList.add('conference-center-qr');
      const centerQRDiv = document.getElementById('qr-code');
      if (centerQRDiv) {
        centerQRDiv.innerHTML = '';
        const sz = (Math.min(centerQR.offsetWidth, centerQR.offsetHeight) || 400) * 0.85;
        const qrDark = isLight ? '#1a1d2e' : '#ffffff';
        const qrLight = isLight ? '#f4f5f9' : '#0f1117';
        new QRCode(centerQRDiv, { text: pLink.href, width: sz, height: sz, colorDark: qrDark, colorLight: qrLight });
      }
    } else {
      rightCol.style.display = '';
      grid.style.gridTemplateColumns = '25% 1fr 25%';
      leftCol.classList.remove('conference-layout');
      confQR.style.display = 'none';
      if (debateTab) debateTab.style.display = '';
      if (helloTab) helloTab.style.display = 'none';
      if (tokenCost) tokenCost.style.display = '';
      if (notesBadge) notesBadge.style.display = '';
      stopAutoReturnTimer();
      // Hide center QR URL
      const centerQRUrl = document.getElementById('center-qr-url');
      if (centerQRUrl) centerQRUrl.style.display = 'none';
      // Restore muted center QR
      if (centerQR) centerQR.classList.remove('conference-center-qr');
      const centerQRDiv = document.getElementById('qr-code');
      if (centerQRDiv) {
        centerQRDiv.innerHTML = '';
        const sz = (Math.min(centerQR.offsetWidth, centerQR.offsetHeight) || 400) * 0.8;
        const mutedColor = isLight ? '#aaaaaa' : '#888888';
        new QRCode(centerQRDiv, { text: link, width: sz, height: sz, colorDark: mutedColor, colorLight: 'transparent' });
      }
    }
  }

  function renderDaemonStatus(connected, lastSeenIso) {
    const el = document.getElementById('daemon-badge');
    if (!el) return;

    if (!lastSeenIso) {
      el.textContent = '🤖';
      el.className = 'badge disconnected';
      el.title = 'Never connected — start with ./start.sh';
      return;
    }

    const ago = Math.round((Date.now() - new Date(lastSeenIso)) / 1000);
    const agoText = ago < 60 ? `${ago}s ago` : `${Math.round(ago/60)}m ago`;

    if (connected) {
      el.textContent = '🤖';
      el.className = 'badge connected';
      el.style.cssText = '';
      el.title = `Connected (last seen ${agoText})`;
    } else {
      el.textContent = '🤖';
      el.className = 'badge';
      el.style.cssText = 'color:var(--warn);border:1px solid var(--warn);';
      el.title = `Connection lost (last seen ${agoText})`;
    }
  }

  function renderTranscriptStatus(lineCount, totalLines, latestTs) {
    const el = document.getElementById('transcript-badge');
    if (!el) return;

    if (lineCount > 0) {
      el.textContent = `💬 ${lineCount}`;
      el.className = 'badge connected';
      el.title = `${lineCount} non-empty lines in last 30 min / ${totalLines} today\nLatest at ${latestTs}`;
    } else {
      el.textContent = '💬';
      el.className = 'badge disconnected';
      el.title = latestTs
        ? `No transcription since ${latestTs}\n${totalLines} lines today`
        : 'No transcription data';
    }
  }

  function renderOverlayStatus(connected) {
    const el = document.getElementById('overlay-badge');
    if (!el) return;
    el.className = `badge ${connected ? 'connected' : 'disconnected'}`;
    el.title = connected ? 'Emoji overlay connected' : 'Emoji overlay not connected';
  }

  let _prevPaxCount = 0;
  function updatePaxBadge(count) {
    const el = document.getElementById('pax-badge');
    if (!el) return;
    el.textContent = `👥 ${count}`;
    el.className = count > 0 ? 'badge connected' : 'badge disconnected';
    el.title = `${count} participant${count !== 1 ? 's' : ''} connected`;
    if (count > _prevPaxCount && _prevPaxCount >= 0) {
      el.classList.add('flash');
      requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove('flash')));
    }
    _prevPaxCount = count;
  }

  let hostNotesContent = '';

  function renderNotesStatus(sessionFolder, sessionNotes) {
    const el = document.getElementById('notes-badge');
    if (!el) return;

    el.style.cssText = 'cursor:pointer;';
    if (sessionFolder && sessionNotes) {
      el.textContent = '📝';
      el.className = 'badge connected';
      el.title = `${sessionFolder}/${sessionNotes}\nClick to view`;
    } else if (sessionFolder) {
      el.textContent = '📝';
      el.className = 'badge';
      el.style.cssText = 'cursor:pointer; color:var(--warn); border:1px solid var(--warn);';
      el.title = 'Session folder found but no notes file inside';
    } else {
      el.textContent = '📝';
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
        const dlBtn = document.getElementById('host-notes-download');
        if (dlBtn) dlBtn.style.display = '';
      } else {
        el.textContent = 'No notes available yet.';
        el.style.cssText = 'color:var(--text-muted);';
        const dlBtn = document.getElementById('host-notes-download');
        if (dlBtn) dlBtn.style.display = 'none';
      }
    }
  }

  function downloadHostNotes() {
    if (!hostNotesContent) return;
    const blob = new Blob([hostNotesContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'session-notes.txt';
    a.click();
    URL.revokeObjectURL(url);
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
      let avatarHtml = '';
      if (avatar && avatar.startsWith('letter:')) {
          const parts = avatar.split(':');
          const lt = parts[1] || '??';
          const clr = parts.slice(2).join(':') || 'var(--muted)';
          avatarHtml = `<span class="avatar letter-avatar" style="width:28px;height:28px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:.65rem;line-height:1;color:#fff;background:${clr}">${lt}</span>`;
      } else if (avatar) {
          avatarHtml = `<img src="/static/avatars/${escHtml(avatar)}" class="avatar" style="width:28px;height:28px" onerror="this.style.display='none'">`;
      }
      const debateSide = participantDebateSides[n];
      const debateIcon = _debateActive
          ? (debateSide === 'for' ? '<span title="FOR">👍</span> ' : debateSide === 'against' ? '<span title="AGAINST">👎</span> ' : '<span title="Undecided">⏳</span> ')
          : '';
      return `<li><span class="pax-name">${debateIcon}${avatarHtml}${escHtml(n)}${scoreTag}</span>${locLabel ? `<span class="pax-location" onclick="openMap()" title="View all on map">${escHtml(locLabel)}</span>` : ''}</li>`;
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

  const RANDOM_POLLS = [
    'What is the largest planet in our solar system?\n\nJupiter\nSaturn\nNeptune\nUranus',
    'Which element has the chemical symbol "Au"?\n\nGold\nSilver\nAluminum\nArgon',
    'How many bones does an adult human body have?\n\n206\n198\n212\n256',
    'What is the speed of light in km/s (approximately)?\n\n300,000\n150,000\n600,000\n1,000,000',
    'Which country has the most time zones?\n\nFrance\nRussia\nUSA\nChina',
    'What year was the first email sent?\n\n1971\n1965\n1980\n1989',
    'How many hearts does an octopus have?\n\n3\n1\n2\n5',
    'What is the smallest country in the world by area?\n\nVatican City\nMonaco\nSan Marino\nLiechtenstein',
    'Which planet has the most moons?\n\nSaturn\nJupiter\nUranus\nNeptune',
    'What percentage of the Earth\'s surface is covered by water?\n\n71%\n60%\n80%\n55%',
    'In what year did the Berlin Wall fall?\n\n1989\n1991\n1987\n1985',
    'What is the most spoken native language in the world?\n\nMandarin Chinese\nEnglish\nSpanish\nHindi',
    'How long is a marathon in kilometers?\n\n42.195\n40.000\n45.000\n38.500',
    'Which animal can sleep for up to 3 years?\n\nSnail\nSloth\nKoala\nCat',
    'What is the hardest natural substance on Earth?\n\nDiamond\nQuartz\nTopaz\nRuby',
    'How many strings does a standard guitar have?\n\n6\n4\n8\n5',
    'Which ocean is the deepest?\n\nPacific\nAtlantic\nIndian\nArctic',
    'What is the boiling point of water in Fahrenheit?\n\n212°F\n200°F\n220°F\n100°F',
    'How many players are on a soccer team on the field?\n\n11\n9\n10\n12',
    'What is the rarest blood type?\n\nAB negative\nO negative\nB negative\nA negative',
    'Which planet is known as the "Red Planet"?\n\nMars\nVenus\nMercury\nJupiter',
    'How many teeth does an adult human typically have?\n\n32\n28\n30\n36',
    'What is the longest river in the world?\n\nNile\nAmazon\nYangtze\nMississippi',
    'Which gas makes up most of Earth\'s atmosphere?\n\nNitrogen\nOxygen\nCarbon dioxide\nArgon',
    'In what year was the first iPhone released?\n\n2007\n2005\n2008\n2010',
  ];
  let _lastRandomIndex = -1;

  initComposer('Which is the primary benefit of the Circuit Breaker pattern?\n\nPrevents cascading failures across services\nImproves response time under normal load\nReduces the number of network calls\nEnables automatic service discovery');

  document.getElementById('random-poll-btn').addEventListener('click', () => {
    let idx;
    do { idx = Math.floor(Math.random() * RANDOM_POLLS.length); } while (idx === _lastRandomIndex && RANDOM_POLLS.length > 1);
    _lastRandomIndex = idx;
    initComposer(RANDOM_POLLS[idx]);
  });

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
      el.innerHTML = `<p class="no-poll">No poll yet.</p>`;
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
           <span id="timer-tip" class="timer-tip">Release to start countdown</span>
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
        <span style="flex:1"></span>
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
  const GEN_LABEL_TRANSCRIPT = 'Generate from transcript 🤖';
  const GEN_LABEL_TOPIC = 'Generate on topic 🤖';

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
    _currentActivity = tab;
    const helloTab = document.getElementById('tab-hello');
    if (helloTab) helloTab.classList.toggle('active', tab === 'none');
    ['poll', 'wordcloud', 'qa', 'codereview', 'debate'].forEach(t => {
      document.getElementById('tab-' + t).classList.toggle('active', tab === t);
      const contentEl = document.getElementById('tab-content-' + t);
      contentEl.style.display = tab === t ? (t === 'codereview' ? 'flex' : '') : 'none';
    });
    await fetch('/api/activity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ activity: tab }),
    });
    const focusTargets = {
      poll: 'poll-input',
      qa: 'host-qa-input',
      codereview: 'codereview-snippet',
      debate: 'debate-statement-input',
    };
    if (tab === 'wordcloud') {
      const topicInput = document.getElementById('wc-topic-input');
      const wordInput = document.getElementById('wc-host-input');
      if (topicInput && topicInput.value.trim()) {
        if (wordInput) wordInput.focus();
      } else if (topicInput) {
        topicInput.focus();
      }
    } else if (focusTargets[tab]) {
      const el = document.getElementById(focusTargets[tab]);
      if (el) el.focus();
    }
  }

  function updateCenterPanel(currentActivity) {
    _currentActivity = currentActivity;
    ['qr', 'poll', 'wordcloud', 'qa', 'debate', 'codereview'].forEach(id => {
      const el = document.getElementById('center-' + id);
      if (id === 'qr') {
        el.style.display = 'none';
      } else if (id === 'poll') {
        // Show poll panel when activity is 'poll' OR 'none' (for quiz gen controls)
        const show = currentActivity === 'poll' || currentActivity === 'none';
        el.style.display = show ? 'flex' : 'none';
        // Hide the poll results section when no poll is active
        const pollResults = el.querySelector(':scope > div:first-child');
        if (pollResults) pollResults.style.display = currentActivity === 'poll' ? '' : 'none';
        // Change divider text based on whether a poll exists
        const divider = el.querySelector('.or-divider span');
        if (divider) divider.textContent = currentActivity === 'poll' ? 'generate next' : 'generate question';
      } else {
        const showVal = id === 'codereview' ? 'flex' : '';
        el.style.display = currentActivity === id ? showVal : 'none';
      }
    });
    // In conference mode: always show the left QR
    const leftCol = document.querySelector('.host-col-left');
    if (leftCol && leftCol.classList.contains('conference-layout')) {
      const confQR = document.getElementById('conference-qr');
      confQR.style.display = 'flex';
    }
    // Sync hello tab active state
    const helloTab = document.getElementById('tab-hello');
    if (helloTab) helloTab.classList.toggle('active', currentActivity === 'none');
    if (currentActivity && currentActivity !== 'none') {
      ['poll', 'wordcloud', 'qa', 'codereview', 'debate'].forEach(t => {
        document.getElementById('tab-' + t).classList.toggle('active', currentActivity === t);
        document.getElementById('tab-content-' + t).style.display = currentActivity === t ? (t === 'codereview' ? 'flex' : '') : 'none';
      });
    } else {
      // When activity is 'none', deactivate all other tabs
      ['poll', 'wordcloud', 'qa', 'codereview', 'debate'].forEach(t => {
        document.getElementById('tab-' + t).classList.remove('active');
        document.getElementById('tab-content-' + t).style.display = 'none';
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
    const wordInput = document.getElementById('wc-host-input');
    if (wordInput) wordInput.focus();
  }

  function hostSubmitWord() {
    const input = document.getElementById('wc-host-input');
    if (!input) return;
    const word = input.value.trim();
    if (!word || !ws) return;
    ws.send(JSON.stringify({ type: 'wordcloud_word', word }));
    input.value = '';
    const btn = document.getElementById('wc-host-submit');
    if (btn) btn.disabled = true;
    const dlWrap = document.getElementById('wc-download-wrap');
    if (dlWrap) dlWrap.style.display = '';
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
    const dlWrap = document.getElementById('wc-download-wrap');
    if (dlWrap) dlWrap.style.display = 'none';
    await fetch('/api/wordcloud/clear', { method: 'POST' });
  }

  function renderHostWordCloud(wordsMap) {
    const canvas = document.getElementById('host-wc-canvas');
    if (!canvas) return;
    const key = JSON.stringify(wordsMap);
    if (key === _hostWcLastDataKey) return;
    _hostWcLastDataKey = key;
    clearTimeout(_hostWcDebounceTimer);
    _hostWcDebounceTimer = setTimeout(() => _drawHostCloud(canvas, wordsMap), 300);
    const dl = document.getElementById('wc-host-suggestions');
    if (dl) {
      dl.innerHTML = Object.keys(wordsMap).sort()
        .map(w => `<option value="${escHtml(w)}"></option>`).join('');
    }
    const dlWrap = document.getElementById('wc-download-wrap');
    if (dlWrap) dlWrap.style.display = Object.keys(wordsMap).length ? '' : 'none';
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
    const btn = document.getElementById('host-qa-submit-btn');
    if (btn) btn.disabled = true;
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

  window.copyQuestionText = function(btn, qid) {
    const card = btn.closest('.qa-card');
    const text = card.querySelector('.qa-text').textContent;
    navigator.clipboard.writeText(text).then(() => {
      const orig = btn.innerHTML;
      btn.textContent = '✓';
      setTimeout(() => { btn.innerHTML = orig; }, 1200);
    });
  };

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
          <button class="btn btn-sm"
                  onclick="copyQuestionText(this, '${escHtml(q.id)}')" title="Copy text"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5.5" y="5.5" width="9" height="9" rx="1.5"/><path d="M10.5 5.5V3a1.5 1.5 0 0 0-1.5-1.5H3A1.5 1.5 0 0 0 1.5 3v6A1.5 1.5 0 0 0 3 10.5h2.5"/></svg></button>
          <button class="btn btn-sm ${q.answered ? 'btn-success' : ''}"
                  onclick="toggleAnswered('${escHtml(q.id)}', ${q.answered})">
            ✓ Answer
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

    // Update language dropdown when server detects language via smart paste
    if (cr.language) {
      const langSelect = document.getElementById('codereview-language');
      if (langSelect) langSelect.value = cr.language;
    }

    renderHostCodePanel(cr);
    _updateCodeReviewLayout(cr);
  }

  function renderHostCodePanel(cr) {
    const panel = document.getElementById('codereview-code-panel');
    const rawLines = cr.snippet.split('\n');
    const lineCounts = cr.line_counts || {};
    const confirmed = new Set(cr.confirmed_lines || []);
    const totalPax = cr.participant_count || 1;

    // Syntax highlight the entire snippet, then split into lines
    let highlightedLines;
    const lang = cr.language || '';
    if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
      const result = hljs.highlight(cr.snippet, { language: lang });
      highlightedLines = result.value.split('\n');
    } else if (typeof hljs !== 'undefined') {
      const result = hljs.highlightAuto(cr.snippet);
      highlightedLines = result.value.split('\n');
    } else {
      highlightedLines = rawLines.map(l => escHtml(l));
    }

    let html = '<div class="codereview-lines">';
    rawLines.forEach((lineText, i) => {
      const lineNum = i + 1;
      const count = lineCounts[String(lineNum)] || 0;
      const pct = Math.round(count * 100 / totalPax);
      const intensity = count / totalPax;
      const isConfirmed = confirmed.has(lineNum);
      const isSelected = codereviewSelectedLine === lineNum;

      const bgColor = `rgba(108,99,255,${intensity * 0.5})`;
      const confirmedClass = isConfirmed ? 'codereview-line-confirmed' : '';
      const selectedClass = isSelected ? 'codereview-line-selected' : '';
      const clickable = cr.phase === 'reviewing' && !isConfirmed ? 'codereview-line-clickable' : '';
      html += `<div class="codereview-line ${clickable} ${confirmedClass} ${selectedClass}" style="background:${bgColor};" onclick="selectCodeReviewLine(${lineNum})">`;
      html += `<span class="codereview-gutter">${lineNum}</span>`;
      html += `<span class="codereview-code">${highlightedLines[i] || ' '}</span>`;
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
    const lastState = window._lastCodereviewState;
    if (!lastState || lastState.phase !== 'reviewing') return; // no-op during selecting
    codereviewSelectedLine = lineNum;
    renderHostCodePanel(lastState);
    _updateCodeReviewLayout(lastState);
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

    html += `<div style="font-size:.85rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem;">Users that selected this line</div>`;
    if (lineParticipants.length > 0) {
      if (currentMode === 'conference') {
        html += `<div style="font-size:2rem;font-weight:700;color:var(--accent);text-align:center;margin:.5rem 0;">${lineParticipants.length}</div>`;
      } else {
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
      }
    } else {
      html += '<div style="color:var(--muted);font-size:.85rem;">no one</div>';
    }

    if (cr.phase === 'reviewing' && !isConfirmed) {
      const label = count > 0 ? '✓ Confirm Line (award 200 pts)' : '✓ Mark as problematic';
      html += `<button class="btn btn-success" style="width:100%;margin-top:12px;" onclick="confirmCodeReviewLine(${lineNum})">${label}</button>`;
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
    const smartPaste = document.getElementById('codereview-smart-paste').checked;
    if (!snippet.trim()) return alert('Please paste a code snippet');

    const btn = document.querySelector('#codereview-create .btn-success');
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = smartPaste ? 'Extracting code...' : 'Starting...';

    try {
      await fetch('/api/codereview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snippet, language, smart_paste: smartPaste }),
      });
    } finally {
      btn.disabled = false;
      btn.textContent = origText;
    }
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
    { key: 'side_selection', num: 1, label: 'Pick a Side' },
    { key: 'arguments',      num: 2, label: 'Arguments' },
    { key: 'prep',           num: 3, label: 'Preparation' },
    { key: 'live_debate',    num: 4, label: 'Live Debate' },
  ];

  function getDebateRounds(firstSide) {
    if (!firstSide) return [];
    const other = firstSide === 'for' ? 'against' : 'for';
    const fl = firstSide.toUpperCase(), ol = other.toUpperCase();
    return [
        {key: `opening_${firstSide}`,  label: `Opening — ${fl}`,  side: firstSide, defaultSeconds: 120},
        {key: `opening_${other}`,       label: `Opening — ${ol}`,  side: other,      defaultSeconds: 120},
        {key: `rebuttal_${firstSide}`, label: `Rebuttal — ${fl}`, side: firstSide, defaultSeconds: 90},
        {key: `rebuttal_${other}`,      label: `Rebuttal — ${ol}`, side: other,      defaultSeconds: 90},
    ];
  }

  let _debateRoundTimer = null; // {roundIndex, seconds, startedAt (ms)}
  let _debateTimerInterval = null;
  let _lastDebateMsg = null;
  let _debateChimePlayed = false;

  let _debateBeepTimeouts = [];

  function _playBeep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.value = 880;
      gain.gain.value = 0.3;
      osc.start();
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
      osc.stop(ctx.currentTime + 0.4);
    } catch(e) {}
  }

  function _playEscalatingBeeps() {
    _stopBeeping();
    // 1 beep now, 2 beeps after 3s, 3 beeps after 6s
    const pattern = [
      { delay: 0, count: 1 },
      { delay: 3000, count: 2 },
      { delay: 6000, count: 3 },
    ];
    for (const step of pattern) {
      for (let i = 0; i < step.count; i++) {
        _debateBeepTimeouts.push(setTimeout(_playBeep, step.delay + i * 300));
      }
    }
  }

  function _stopBeeping() {
    _debateBeepTimeouts.forEach(t => clearTimeout(t));
    _debateBeepTimeouts = [];
  }

  function _startDebateCountdown() {
    clearInterval(_debateTimerInterval);
    _debateChimePlayed = false;
    _debateTimerInterval = setInterval(() => {
      const el = document.getElementById('debate-round-countdown');
      if (!el || !_debateRoundTimer) { clearInterval(_debateTimerInterval); return; }
      const elapsed = (Date.now() - _debateRoundTimer.startedAt) / 1000;
      const remaining = Math.max(0, _debateRoundTimer.seconds - elapsed);
      const mins = Math.floor(remaining / 60);
      const secs = Math.ceil(remaining % 60);
      const timeText = mins > 0 ? `${mins}:${String(secs).padStart(2, '0')}` : `${secs}s`;
      // Update end button countdown if present
      const endBtn = document.querySelector('[id^="debate-round-end-btn-"]');
      if (endBtn && remaining > 0) endBtn.textContent = `End (${timeText})`;
      if (remaining <= 0) {
        el.textContent = "TIME'S UP";
        el.className = 'debate-countdown-large debate-countdown-expired';
        if (!_debateChimePlayed) { _playEscalatingBeeps(); _debateChimePlayed = true; }
        clearInterval(_debateTimerInterval);
        if (endBtn) endBtn.textContent = 'End';
      } else {
        el.textContent = timeText;
        el.className = 'debate-countdown-large';
        el.style.color = remaining <= 10 ? 'var(--danger)' : remaining <= 30 ? 'var(--warn)' : 'var(--accent)';
      }
    }, 200);
  }

  async function startDebateRound(index) {
    const phases = getDebateRounds(_lastDebateMsg?.debate_first_side);
    const input = document.getElementById(`debate-round-dur-${index}`);
    let seconds = phases[index]?.defaultSeconds || 120;
    if (input) {
      const parts = input.value.split(':');
      seconds = parts.length === 2 ? parseInt(parts[0],10) * 60 + parseInt(parts[1],10) : parseInt(parts[0],10);
    }
    _debateChimePlayed = false;
    _stopBeeping();
    await fetch('/api/debate/round-timer', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({round_index: index, seconds}),
    });
  }

  async function endDebateRound() {
    await fetch('/api/debate/end-round', { method: 'POST' });
  }

  async function setDebateFirstSide(side) {
    await fetch('/api/debate/first-side', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({side}),
    });
  }

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
    const btn = document.getElementById('debate-end-args-btn');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span style="animation:spin .8s linear infinite;display:inline-block;">⏳</span> AI…';
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      await fetch('/api/debate/end-arguments', { method: 'POST', signal: controller.signal });
    } catch(e) {
      // timeout or network error — state will update via WS anyway
    } finally {
      clearTimeout(timeout);
    }
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

  async function debateSkipAI() {
    // Post empty result to advance past ai_cleanup if daemon is unavailable
    await fetch('/api/debate/ai-result', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ merges: [], cleaned: [], new_arguments: [] }),
    });
  }

  function renderDebateHost(msg) {
    _lastDebateMsg = msg;
    const chapters = document.getElementById('debate-phase-chapters');
    const title = document.getElementById('debate-statement-display');
    const content = document.getElementById('debate-center-content');

    const debateActive = msg.current_activity === 'debate' && !!msg.debate_phase;
    const phase = msg.debate_phase || null;
    const sideCounts = msg.debate_side_counts || { for: 0, against: 0 };
    const champions = msg.debate_champions || {};
    const roundIdx = msg.debate_round_index;

    // Reconstruct timer from state on reconnect
    if (phase === 'live_debate' && msg.debate_round_timer_started_at && !_debateRoundTimer) {
      _debateRoundTimer = {
        roundIndex: roundIdx,
        seconds: msg.debate_round_timer_seconds,
        startedAt: new Date(msg.debate_round_timer_started_at).getTime(),
      };
      const remaining = _debateRoundTimer.seconds - (Date.now() - _debateRoundTimer.startedAt) / 1000;
      if (remaining > 0) _startDebateCountdown();
    }

    // Update center panel title if debate is active
    if (title) {
      title.innerHTML = debateActive ? escDebate(msg.debate_statement) : '';
    }

    // Hide statement input once launched (shrink vertically upward), show reset button
    const stmtWrapper = document.getElementById('debate-statement-wrapper');
    const resetWrapper = document.getElementById('debate-reset-wrapper');
    if (stmtWrapper) {
      if (debateActive) {
        // Animate collapse only if wrapper is currently expanded (user just launched)
        const isExpanded = parseInt(stmtWrapper.style.maxHeight) > 0;
        stmtWrapper.style.transition = isExpanded ? 'max-height 1.2s linear, margin 1.2s linear, padding 1.2s linear' : 'none';
        stmtWrapper.style.maxHeight = '0';
        stmtWrapper.style.marginTop = '0';
        stmtWrapper.style.padding = '0';
      } else {
        stmtWrapper.style.transition = 'none';
        stmtWrapper.style.maxHeight = '200px';
        stmtWrapper.style.marginTop = '.75rem';
        stmtWrapper.style.padding = '';
        // Restore default topic
        const input = document.getElementById('debate-statement-input');
        if (input) input.value = input.defaultValue;
      }
    }
    if (resetWrapper) resetWrapper.style.display = debateActive ? '' : 'none';

    // Phase chapters — always visible
    // ai_cleanup is implicit (not in visible list) — treat it as "between arguments and prep"
    const displayPhase = phase === 'ai_cleanup' ? 'prep' : phase;
    const currentIdx = debateActive ? DEBATE_PHASES.findIndex(p => p.key === displayPhase) : -1;
    const phaseActions = {
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
        actionHtml = `<div class="debate-chapter-extra"><span style="color:var(--accent);font-size:.8rem;">🤖 AI enriching arguments…</span> <button class="btn btn-sm" onclick="debateSkipAI()" style="margin-left:.5rem;font-size:.7rem;">Skip AI</button></div>`;
      } else if (isActive && phaseActions[p.key]) {
        actionHtml = `<div class="debate-chapter-extra">${phaseActions[p.key]}</div>`;
      }

      // Render rounds for live_debate
      if (isActive && p.key === 'live_debate') {
        if (!msg.debate_first_side) {
          actionHtml += `<div style="text-align:center; padding:.5rem;">
            <div style="color:var(--muted); margin-bottom:.4rem;">Who speaks first?</div>
            <button class="btn btn-sm" style="background:#2ecc71;color:#fff;margin-right:.5rem;" onclick="setDebateFirstSide('for')">👍</button>
            <button class="btn btn-sm" style="background:#e74c3c;color:#fff;" onclick="setDebateFirstSide('against')">👎</button>
          </div>`;
        } else {
          const rounds = getDebateRounds(msg.debate_first_side);
          actionHtml += '<div class="debate-rounds">';
          // Determine which rounds are done/active/next
          const anyTimerActive = !!msg.debate_round_timer_started_at;
          let foundNext = false;
          actionHtml += rounds.map((sp, si) => {
            const spDone = (roundIdx !== null && si < roundIdx) || (si === roundIdx && !msg.debate_round_timer_started_at);
            const spActive = roundIdx !== null && si === roundIdx && !!msg.debate_round_timer_started_at;
            let spNext = false;
            if (!foundNext && !spDone && !spActive && !anyTimerActive) { spNext = true; foundNext = true; }

            let spCls = 'debate-round';
            if (spDone) spCls += ' debate-round-done';
            else if (spActive) spCls += ' debate-round-active';
            else if (spNext) spCls += ' debate-round-next';

            const sideClass = `debate-round-side-${sp.side}`;
            const sideIcon = sp.side === 'for' ? '👍' : '👎';
            const mins = Math.floor(sp.defaultSeconds / 60);
            const secs = sp.defaultSeconds % 60;
            const durVal = mins > 0 && secs > 0 ? `${mins}:${String(secs).padStart(2,'0')}` : mins > 0 ? `${mins}:00` : `0:${String(secs).padStart(2,'0')}`;

            let statusHtml = '';
            if (spDone) {
              statusHtml = '<span class="debate-round-check">✓</span>';
            } else if (spActive) {
              statusHtml = `<button class="btn btn-warn btn-sm" id="debate-round-end-btn-${si}" onclick="endDebateRound()">End</button>`;
            } else if (spNext) {
              statusHtml = `<input type="text" class="debate-round-duration" id="debate-round-dur-${si}" value="${durVal}" title="Duration (m:ss)" /><button class="btn btn-primary btn-sm" onclick="startDebateRound(${si})">▶ Start</button>`;
            }

            return `<div class="${spCls}">
              <div class="debate-round-row">
                <span class="debate-round-label ${sideClass}">${sideIcon} ${sp.label}</span>
                ${statusHtml}
              </div>
            </div>`;
          }).join('');
          actionHtml += '</div>';
        }
      }

      let launchBtn = '';
      if (isReady) {
        // Pre-launch: phase 1 gets a Launch button that starts the debate
        launchBtn = `<button class="btn btn-primary btn-sm" onclick="launchDebate()">Launch ⚔️</button>`;
      } else if (isActive && p.key === 'live_debate') {
        // No end button — debate stays in live_debate; use Reset to clear
      } else if (isActive && p.key === 'side_selection') {
        launchBtn = `<button class="btn btn-warn btn-sm" onclick="debateForceAssign()">🎲 Random Assign</button>`;
      } else if (isActive && p.key === 'arguments') {
        launchBtn = `<button class="btn btn-primary btn-sm" id="debate-end-args-btn" onclick="debateEndArguments()">End</button>`;
      } else if (isActive) {
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
      let centerHeader = `<div style="text-align:center; margin-bottom:.75rem; font-size:.95rem; color:var(--muted); text-transform:uppercase; letter-spacing:.08em;">${phaseLabel}</div>`;

      // Add round info + countdown for live_debate
      if (phase === 'live_debate') {
        if (!msg.debate_first_side) {
          // "Who speaks first?" controls are in the left pane
        } else if (roundIdx !== null) {
          const rounds = getDebateRounds(msg.debate_first_side);
          const sp = rounds[roundIdx];
          if (sp) {
            const sideColor = sp.side === 'for' ? '#2ecc71' : sp.side === 'against' ? '#e74c3c' : 'var(--warn)';
            const sideIcon = sp.side === 'for' ? '👍' : '👎';
            centerHeader += `<div style="text-align:center; margin-bottom:.5rem;">
              <div style="font-size:1.1rem; color:${sideColor}; font-weight:600;">${sideIcon} ${sp.label}</div>
              <div id="debate-round-countdown" class="debate-countdown-large"></div>
            </div>`;
          }
        }
      }

      content.innerHTML = centerHeader +
        renderDebateDualColumn(againstArgs, forArgs, mergedArgs, msg.debate_champions, phase);

      // Restart countdown rendering if timer is active
      if (phase === 'live_debate' && _debateRoundTimer) _startDebateCountdown();
      if (phase === 'ai_cleanup') {
        content.innerHTML += `<div class="debate-ai-loading">
          <div class="debate-ai-spinner"></div>
          <div>AI is enriching arguments…</div>
        </div>`;
      }
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
      <span style="color:var(--muted);font-size:.8rem;">🤖 duplicate, merged above</span>
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
        ${champAgainst}
        ${againstArgs.map(renderArg).join('')}
        ${Array(mergedAgainstCount).fill('').map(renderMerged).join('')}
      </div>
      <div class="debate-col debate-col-for">
        ${champFor}
        ${forArgs.map(renderArg).join('')}
        ${Array(mergedForCount).fill('').map(renderMerged).join('')}
      </div>
    </div>${hints}`;
  }

// ── Leaderboard ──────────────────────────────────────
let _leaderboardActive = false;

async function toggleLeaderboard() {
    try {
        if (_leaderboardActive) {
            await fetch('/api/leaderboard/hide', { method: 'POST' });
        } else {
            await fetch('/api/leaderboard/show', { method: 'POST' });
        }
    } catch (e) {
        console.error('Leaderboard toggle failed:', e);
    }
}

let _leaderboardAutoHideTimer = null;

function renderLeaderboard(data) {
    _leaderboardActive = true;
    clearTimeout(_leaderboardAutoHideTimer);
    _leaderboardAutoHideTimer = setTimeout(() => { if (_leaderboardActive) toggleLeaderboard(); }, 7000);
    const overlay = document.getElementById('leaderboard-overlay');
    const entriesEl = document.getElementById('leaderboard-entries');
    overlay.style.display = 'flex';
    entriesEl.innerHTML = '';

    const btn = document.getElementById('btn-leaderboard');
    if (btn) btn.classList.add('active');

    // Render entries bottom-to-top with sequential animation
    const entries = data.entries || [];
    entries.forEach((entry, i) => {
        const div = document.createElement('div');
        div.className = 'leaderboard-entry' + (entry.rank === 1 ? ' first-place' : '');

        const avatarStyle = entry.avatar && entry.avatar.startsWith('letter:')
            ? `background:${entry.color}`
            : `background:var(--surface2)`;
        const avatarContent = entry.avatar && entry.avatar.startsWith('letter:')
            ? entry.letter
            : '';
        const avatarImg = entry.avatar && !entry.avatar.startsWith('letter:')
            ? `<img src="/static/avatars/${entry.avatar}" style="width:48px;height:48px;border-radius:50%" onerror="this.style.display='none'">`
            : '';

        const universeTag = entry.universe
            ? ` <span class="leaderboard-universe">(${entry.universe})</span>`
            : '';

        div.innerHTML = `
            <span class="leaderboard-rank">#${entry.rank}</span>
            ${avatarImg || `<span class="leaderboard-avatar" style="${avatarStyle}">${escHtml(entry.name)}${universeTag}</span>`}
            <span class="leaderboard-name">${escHtml(entry.name)}${universeTag}</span>
            <span class="leaderboard-score">${entry.score} pts</span>
        `;

        // IMPORTANT: Fix the avatar — if using letter avatar, show letters not name
        if (!avatarImg) {
            const avatarSpan = div.querySelector('.leaderboard-avatar');
            if (avatarSpan) avatarSpan.textContent = entry.letter || '??';
        }

        entriesEl.appendChild(div);

        // Sequential reveal: 5th first (bottom), 1st last (top)
        const revealDelay = (entries.length - 1 - i) * 800;
        setTimeout(() => div.classList.add('visible'), 500 + revealDelay);
    });
}

function hideLeaderboard() {
    _leaderboardActive = false;
    clearTimeout(_leaderboardAutoHideTimer);
    const overlay = document.getElementById('leaderboard-overlay');
    overlay.style.display = 'none';
    const btn = document.getElementById('btn-leaderboard');
    if (btn) btn.classList.remove('active');
}

function updateLeaderboardButton() {
    const btn = document.getElementById('btn-leaderboard');
    if (!btn) return;
    // Enable only when there are participants with scores
    const scoredCount = Object.values(scores || {}).filter(s => s > 0).length;
    btn.disabled = scoredCount < 1;
}

// ── Auto-return to Hello tab (conference mode only) ──

let _currentActivity = 'none';

function _resetAutoReturn() {
  if (currentMode !== 'conference') return;
  clearTimeout(_autoReturnTimer);
  if (_currentActivity !== 'none') {
    _autoReturnTimer = setTimeout(() => switchTab('none'), AUTO_RETURN_DELAY);
  }
}

function startAutoReturnTimer() {
  ['click', 'keypress', 'mousemove'].forEach(evt =>
    document.addEventListener(evt, _resetAutoReturn, { passive: true })
  );
  _resetAutoReturn();
}

function stopAutoReturnTimer() {
  clearTimeout(_autoReturnTimer);
  _autoReturnTimer = null;
  ['click', 'keypress', 'mousemove'].forEach(evt =>
    document.removeEventListener(evt, _resetAutoReturn)
  );
}
