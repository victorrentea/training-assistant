  const SESSION_ID = location.pathname.split('/')[2];
  const API = (path) => `/api/${SESSION_ID}/host${path}`;

  const UPLOAD_CLEANUP_MINUTES = 5; // hide download icon + delete file after this many minutes
  let ws = null;
  let currentPoll = null;
  let pollActive = false;
  let voteCounts = {};
  let totalVotes = 0;
  let totalParticipants = 0;
  let participantDataById = {};     // uuid -> participant payload
  let participantDebateSides = {};  // uuid -> "for"|"against"|undefined
  let _debateActive = false;
  const resolvedCities = {};   // raw "lat, lon" -> resolved city string cache
  let correctOptIds = new Set(); // host-marked correct options for current poll
  let scores = {};               // uuid -> score
  let cachedParticipantIds = []; // last known participant uuids
  let summaryPoints = [];
  let summaryUpdatedAt = null;
  let sessionMain = null;
  let sessionTalk = null;
  let _sessionName = null;  // from state.session_name (fallback title when sessionMain is null)
  let daemonLastSeen = null;
  let daemonSessionFolder = null;
  let _sessionIntervalsEditing = false;
  let _sessionIntervalsDraft = '';
  let _sessionIntervalsError = '';
  let _slidesCacheStatus = {};
  let _slidesCatalog = [];
  let _currentSessionId = null;
  let _joinBaseUrl = null;   // set from state.join_base_url (daemon config URL)
  let _slidesCatalogHideTimer = null;
  let _gitRepos = [];
  let _slidesLog = [];
  const _ZERO_WIDTH_RE = /[\u200B-\u200D\uFEFF]/g;

  let _hostWcDebounceTimer = null;
  let _hostWcLastDataKey = null;
  let currentMode = 'workshop';
  const versionReloadGuard = window.createVersionReloadGuard
    ? window.createVersionReloadGuard({ countdownSeconds: 5 })
    : null;
  window.__versionReloadGuard = versionReloadGuard;
  const WC_COLORS = ['#7ecef4','#a78bfa','#34d399','#fbbf24','#f472b6','#60a5fa','#fb923c'];

  // ── Poll history (persisted in localStorage, keyed by today's date) ──
  const TODAY_KEY = `host_polls_${new Date().toISOString().slice(0, 10)}`;
  const _FOOTER_BADGE_TOOLTIP_DEFAULTS = {
    'ws-badge': 'Server connection status',
'overlay-badge': 'Desktop Overlay app',
    'notes-badge': 'Session notes',
    'summary-badge': 'Key points summary',
    'btn-transcription-lang': 'Toggle transcription language',
    'token-cost': 'Token usage and cost',
    'git-repos-badge': 'Git repos activity',
    'slides-log-badge': 'Slides activity',
    'slides-catalog-icon': 'Slides catalog status',
  };

  function _ensureFooterBadgeTooltip(target) {
    if (!target) return null;
    let tip = target.querySelector('.footer-badge-tooltip');
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'footer-badge-tooltip';
      target.appendChild(tip);
    }
    return tip;
  }

  function _setFooterBadgeTooltip(targetOrId, text) {
    const target = typeof targetOrId === 'string'
      ? document.getElementById(targetOrId)
      : targetOrId;
    if (!target) return;
    const tip = _ensureFooterBadgeTooltip(target);
    const value = String(text || '').trim();
    target.removeAttribute('title');
    if (!tip) return;
    tip.textContent = value;
    tip.style.display = value ? '' : 'none';
  }

  function _initFooterBadgeTooltips() {
    Object.entries(_FOOTER_BADGE_TOOLTIP_DEFAULTS).forEach(([id, text]) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.classList.add('footer-tooltip-target');
      _setFooterBadgeTooltip(el, text);
    });
  }

  function ingestParticipants(participants) {
    participantDataById = {};
    participantDebateSides = {};
    scores = {};
    cachedParticipantIds = [];
    (participants || []).forEach(p => {
      if (!p || !p.uuid) return;
      participantDataById[p.uuid] = p;
      participantDebateSides[p.uuid] = p.debate_side;
      scores[p.uuid] = p.score || 0;
      cachedParticipantIds.push(p.uuid);
    });
  }

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
    const resp = await fetch(API('/poll/correct'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ correct_ids: [...correctOptIds] }),
    });
    if (!resp.ok) toast('Failed to save correct options');
  }

  // Set participant link
  const pLink = document.getElementById('participant-link');
  _initFooterBadgeTooltips();
  if (pLink) {
    pLink.innerHTML = _buildUrlHtml();
    pLink.title = 'Click to copy • Ctrl/Cmd+Click to open';
    pLink.addEventListener('click', onFooterJoinLinkClick);
  }
  _setupSlidesCatalogHover();
  _setupStopSessionHover();
  _setupActivityLogHovers();

  // ── WebSocket (host monitors state too) ──
  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/${SESSION_ID}/__host__`);

    let _kicked = false;
    ws.onopen = () => {
      setBadge(true);
      // Fetch initial state via REST (daemon no longer pushes state via WS)
      fetch(API('/state'))
        .then(r => r.json())
        .then(state => { state.type = 'state'; handleWSMessage(state); })
        .catch(err => console.error('Failed to fetch host state:', err));
      _refreshHostSlidesCatalog().catch(() => {});
    };
    ws.onclose = () => { setBadge(false); if (!_kicked) setTimeout(connectWS, 3000); };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'kicked') {
        _kicked = true;
        setKickedFavicon();
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
      handleWSMessage(msg);
    };
  }

  function handleWSMessage(msg) {
      if (msg.type === 'reload') {
        console.log('[static-sync] Reload requested by daemon');
        setTimeout(() => { window.location.reload(); }, 500);
        return;
      }
      if (msg.type === 'redirect') {
        window.location.href = msg.url;
        return;
      }
      if (msg.type === 'leaderboard' || msg.type === 'leaderboard_revealed') {
        renderLeaderboard(msg);
        return;
      }
      if (msg.type === 'poll_ai_generated') {
        currentPoll = msg.poll;
        pollActive = false;
        voteCounts = {};
        totalVotes = 0;
        loadCorrectOpts(currentPoll.question);
        updateCenterPanel('poll');
        renderPollDisplay();
        return;
      }
      if (msg.type === 'poll_opened') {
        currentPoll = msg.poll || currentPoll;
        pollActive = true;
        voteCounts = {};
        totalVotes = 0;
        updateCenterPanel('poll');
        renderPollDisplay();
        return;
      }
      if (msg.type === 'poll_closed') {
        pollActive = false;
        _clearTimer();
        voteCounts = msg.vote_counts || {};
        totalVotes = msg.total_votes || 0;
        renderPollDisplay();
        renderBars();
        return;
      }
      if (msg.type === 'poll_correct_revealed') {
        correctOptIds = new Set(msg.correct_ids || []);
        if (currentPoll) {
          saveCorrectOpts(currentPoll.question);
          recordPollInHistory(currentPoll, correctOptIds);
        }
        renderBars();
        return;
      }
      if (msg.type === 'poll_cleared') {
        currentPoll = null;
        pollActive = false;
        _clearTimer();
        voteCounts = {};
        totalVotes = 0;
        correctOptIds = new Set();
        renderPollDisplay();
        return;
      }
      if (msg.type === 'poll_timer_started') {
        _applyTimer(msg.seconds, msg.started_at);
        _startHostCountdown();
        return;
      }
      if (msg.type === 'scores_updated') {
        const updated = msg.scores || {};
        Object.assign(scores, updated);
        renderParticipantList(cachedParticipantIds);
        updateLeaderboardButton();
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
        _debateActive = msg.current_activity === 'debate' && !!msg.debate_phase;
        ingestParticipants(msg.participants || []);
        totalParticipants = msg.participant_count || 0;
        document.getElementById('pax-count').textContent = msg.participant_count;
        updatePaxBadge(msg.participant_count);
        renderParticipantList(cachedParticipantIds);
        updateLeaderboardButton();
        document.getElementById('restore-banner').style.display =
          (msg.needs_restore && !msg.daemon_connected) ? '' : 'none';
        updateTokenBadge(msg.token_usage);
        if (msg.slides_log_deep_count !== undefined || msg.slides_log_topic !== undefined) {
          const count = msg.slides_log_deep_count ?? 0;
          document.getElementById('slides-log-count').textContent = count;
        }
        if (msg.git_repos !== undefined) _gitRepos = msg.git_repos;
        if (msg.slides_log !== undefined) _slidesLog = msg.slides_log;
        const gitCount = _gitRepos.length > 0 ? (msg.git_repos_count ?? _gitRepos.length) : 0;
        const gitBadge = document.getElementById('git-repos-badge');
        if (gitBadge) {
          gitBadge.textContent = '⎇ ' + gitCount;
          _setFooterBadgeTooltip(gitBadge, 'Git repos activity');
        }
        renderTranscriptStatus(msg.transcript_line_count, msg.transcript_total_lines, msg.transcript_latest_ts, msg.transcript_last_content_at);
        renderOverlayStatus(msg.overlay_connected);
        renderPendingDeploy(msg.pending_deploy);
        daemonSessionFolder = msg.daemon_session_folder || null;
        renderNotesStatus(msg.daemon_session_folder, msg.daemon_session_notes);
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
        if (msg.session_main !== undefined) sessionMain = msg.session_main;
        if (msg.session_talk !== undefined) sessionTalk = msg.session_talk;
        if (msg.session_name !== undefined) _sessionName = msg.session_name || null;
        if (msg.daemon_last_seen !== undefined) daemonLastSeen = msg.daemon_last_seen;
        if (msg.join_base_url) _joinBaseUrl = msg.join_base_url;
        if (!msg.session_id && msg.needs_restore === false) {
          window.location = '/host';
          return;
        }
        updateSessionCodeBar(msg.session_id || null);
        renderSessionPanel();
        if (msg.mode) {
          currentMode = msg.mode;
          renderMode(msg.mode);
        }
        if (msg.transcription_language) {
          updateTranscriptionLangBtn(msg.transcription_language);
        }
      } else if (msg.type === 'notes') {
        updateHostNotes(msg.notes_content);
      } else if (msg.type === 'summary') {
        updateSummary(msg.points, msg.updated_at);
      } else if (msg.type === 'slides_cache_status') {
        const legacyMap = (msg.slides_cache_status && typeof msg.slides_cache_status === 'object')
          ? msg.slides_cache_status
          : {};
        const embeddedMap = _buildSlidesCacheStatusMapFromSlides(msg.slides || []);
        _slidesCacheStatus = { ...embeddedMap, ...legacyMap };
        if (Array.isArray(msg.slides) && msg.slides.length) {
          _slidesCatalog = msg.slides;
        }
        _renderSlidesCatalogPopover();
      } else if (msg.type === 'slides_updated') {
        _refreshHostSlidesCatalog().catch(() => {});
      } else if (msg.type === 'vote_update') {
        voteCounts = msg.vote_counts || {};
        totalVotes = msg.total_votes || 0;
        renderBars();
      } else if (msg.type === 'participant_list_updated') {
        ingestParticipants(msg.participants || []);
        totalParticipants = (msg.participants || []).length;
        document.getElementById('pax-count').textContent = totalParticipants;
        updatePaxBadge(totalParticipants);
        renderParticipantList(cachedParticipantIds);
        if (pollActive && currentPoll) renderBars();
        updateLeaderboardButton();
        // Re-render code review side panel with fresh scores
        if (window._lastCodereviewState && window._lastCodereviewState.phase !== 'idle') {
          // Update scores in cached line_participants
          const cr = window._lastCodereviewState;
          for (const key in cr.line_participants) {
            cr.line_participants[key].forEach(p => {
              if (scores[p.uuid] !== undefined) p.score = scores[p.uuid];
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
      } else if (msg.type === 'transcription_language') {
        updateTranscriptionLangBtn(msg.language);
      } else if (msg.type === 'transcription_language_pending') {
        updateTranscriptionLangBtn(msg.language, true);
      } else if (msg.type === 'quiz_status') {
        renderQuizStatus(msg.status, msg.message);
      } else if (msg.type === 'quiz_preview') {
        renderPreview(msg.quiz || null);
      } else if (msg.type === 'overlay_connected') {
        renderOverlayStatus(msg.overlay_connected);
      } else if (msg.type === 'emoji_reaction') {
        showHostEmoji(msg.emoji);
      } else if (msg.type === 'qa_updated') {
        renderQAList(msg.questions || []);
      }
  }

  function showHostEmoji(emoji) {
    if (emoji === '❤️' && _suppressHeartEcho) return;
    const el = document.createElement('div');
    const isScreen = emoji === '🖥️';
    el.className = 'host-emoji-float' + (isScreen ? ' host-emoji-float-screen' : '');
    el.textContent = emoji;
    document.body.appendChild(el);

    // Screen emoji: spawn from center; others: spawn from bottom-right corner (desktop overlay handles bottom-left)
    const startX = isScreen ? window.innerWidth / 2 : window.innerWidth - 100;
    const startY = isScreen ? window.innerHeight / 2 : window.innerHeight - 80;
    el.style.left = startX + 'px';
    el.style.top = startY + 'px';
    el.style.transform = 'translate(-50%, -50%)';

    const duration = 2500 + Math.random() * 1500;
    const riseHeight = 500;

    // Rise up with divergent drift (picks one random direction and goes)
    const driftX = (Math.random() * 2 - 1) * 50; // -50..+50 px total lateral drift at top
    const steps = 20;
    const keyframes = [];
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const y = -riseHeight * t;
      const wobble = t * driftX;
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

  function showHostHeartFullscreen() {
    const overlay = document.createElement('div');
    overlay.className = 'host-heart-fullscreen';
    overlay.innerHTML = '<div class="host-heart-fullscreen-emoji">❤️</div>';
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('host-heart-fullscreen-visible'));
    setTimeout(() => {
      overlay.classList.remove('host-heart-fullscreen-visible');
      setTimeout(() => overlay.remove(), 600);
    }, 2200);
  }

  // escHtml is now in utils.js

  function normalizeSlideDisplayName(name, slug) {
    const cleanedName = String(name || '').replace(_ZERO_WIDTH_RE, '').trim();
    const cleanedSlug = String(slug || '').replace(_ZERO_WIDTH_RE, '').trim();
    if (cleanedName && /[\p{L}\p{N}]/u.test(cleanedName)) return cleanedName;
    if (cleanedSlug && /[\p{L}\p{N}]/u.test(cleanedSlug)) return cleanedSlug;
    return 'Unnamed slide';
  }

  function _fmtSessionTime(dt) {
    return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  }

  function _isSessionPaused(session) {
    return Array.isArray(session?.paused_intervals) && session.paused_intervals.some(p => !p?.to);
  }

  function _computeSessionWindows(session) {
    if (!session?.started_at) return [];
    const startedAt = new Date(session.started_at);
    if (Number.isNaN(startedAt.getTime())) return [];

    const windows = [];
    let cursor = startedAt;
    const pauses = Array.isArray(session.paused_intervals)
      ? [...session.paused_intervals].sort((a, b) => {
          const aTs = new Date(a?.from || 0).getTime();
          const bTs = new Date(b?.from || 0).getTime();
          return aTs - bTs;
        })
      : [];

    for (const pause of pauses) {
      const pauseFrom = new Date(pause?.from || 0);
      if (Number.isNaN(pauseFrom.getTime())) continue;
      if (pauseFrom > cursor) windows.push([new Date(cursor), pauseFrom]);

      if (!pause?.to) return windows;
      const pauseTo = new Date(pause.to);
      if (Number.isNaN(pauseTo.getTime())) return windows;
      if (pauseTo > cursor) cursor = pauseTo;
    }

    let end = session.ended_at ? new Date(session.ended_at) : new Date();
    if (Number.isNaN(end.getTime())) end = new Date();
    if (cursor < end) windows.push([new Date(cursor), end]);
    return windows;
  }

  function _startOfDayLocal(dt) {
    return new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
  }

  function _dayOffset(baseDay, dt) {
    return Math.floor((_startOfDayLocal(dt) - baseDay) / 86400000) + 1;
  }

  function _minuteKey(dt) {
    return `${dt.getFullYear()}-${dt.getMonth()}-${dt.getDate()}-${dt.getHours()}-${dt.getMinutes()}`;
  }

  function _dayBaseFromSession(session) {
    const windows = _computeSessionWindows(session);
    if (windows.length) return _startOfDayLocal(windows[0][0]);
    const startedAt = new Date(session?.started_at || Date.now());
    return Number.isNaN(startedAt.getTime()) ? _startOfDayLocal(new Date()) : _startOfDayLocal(startedAt);
  }

  function _formatSessionWindows(session) {
    const windows = _computeSessionWindows(session);
    if (!windows.length) return '';

    const firstStart = windows[0][0];
    const firstDayStart = _startOfDayLocal(firstStart);
    const dayKeys = new Set(windows.map(([start]) => `${start.getFullYear()}-${start.getMonth()}-${start.getDate()}`));
    const isMultiDay = dayKeys.size > 1;
    const ongoing = !session?.ended_at && !_isSessionPaused(session);

    return windows.map(([start, end], idx) => {
      if (_minuteKey(start) === _minuteKey(end)) return null;
      const dayNum = _dayOffset(firstDayStart, start);
      const prefix = isMultiDay ? `Day${dayNum} ` : '';
      const endLabel = ongoing && idx === windows.length - 1 ? 'now' : _fmtSessionTime(end);
      return `${prefix}${_fmtSessionTime(start)}→${endLabel}`;
    }).filter(Boolean).join(', ');
  }

  function _sessionWindowsForDisplay(session) {
    const windows = _computeSessionWindows(session);
    if (!windows.length) return [];

    const firstStart = windows[0][0];
    const firstDayStart = _startOfDayLocal(firstStart);
    const ongoing = !session?.ended_at && !_isSessionPaused(session);

    return windows.map(([start, end], idx) => {
      const dayNum = _dayOffset(firstDayStart, start);
      const isOngoingWindow = ongoing && idx === windows.length - 1;
      const endLabel = isOngoingWindow ? 'now' : _fmtSessionTime(end);
      if (_minuteKey(start) === _minuteKey(end)) return null;
      return {
        dayNum,
        label: `${_fmtSessionTime(start)}→${endLabel}`,
        start: new Date(start),
        end: new Date(end),
        startIso: start.toISOString(),
        endIso: end.toISOString(),
        isOngoing: isOngoingWindow
      };
    }).filter(Boolean);
  }

  function openSessionIntervalLines(startIso, endIso) {
    if (!startIso || !endIso) return;
    const qs = new URLSearchParams({ start: startIso, end: endIso });
    const url = API(`/session/interval-lines.txt?${qs.toString()}`);
    window.open(url, '_blank', 'noopener');
  }

  function _groupSessionWindowsByDay(session) {
    const grouped = new Map();
    for (const w of _sessionWindowsForDisplay(session)) {
      if (!grouped.has(w.dayNum)) grouped.set(w.dayNum, []);
      grouped.get(w.dayNum).push(w);
    }
    return [...grouped.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([dayNum, windows]) => ({ dayNum, windows }));
  }

  function _sessionIntervalsToEditableText(session) {
    const rows = _groupSessionWindowsByDay(session);
    if (!rows.length) return '';
    return rows.map((row) => `Day${row.dayNum}: ${row.windows.map(w => w.label).join(', ')}`).join('\n');
  }

  function _parseHhMm(value) {
    const m = /^(\d{2}):(\d{2})$/.exec(value);
    if (!m) return null;
    const hh = Number(m[1]);
    const mm = Number(m[2]);
    if (hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
    return { hh, mm };
  }

  function _addDays(baseDay, daysToAdd) {
    const d = new Date(baseDay);
    d.setDate(d.getDate() + daysToAdd);
    return d;
  }

  function _atTime(baseDay, dayNum, hhmm) {
    const t = _parseHhMm(hhmm);
    if (!t) return null;
    const d = _addDays(baseDay, dayNum - 1);
    d.setHours(t.hh, t.mm, 0, 0);
    return d;
  }

  function _buildSessionFromIntervalsText(session, text) {
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
    if (!lines.length) return { ok: false, error: 'Add at least one DayN line.' };

    const segments = [];
    const dayNums = new Set();
    const baseDay = _dayBaseFromSession(session);

    for (const line of lines) {
      const m = /^Day\s*([0-9]+)\s*:\s*(.+)$/i.exec(line);
      if (!m) return { ok: false, error: `Invalid line: "${line}". Use "Day1: 09:30→12:40, 13:40→17:30".` };
      const dayNum = Number(m[1]);
      if (!Number.isInteger(dayNum) || dayNum < 1) return { ok: false, error: `Invalid day number in "${line}".` };
      dayNums.add(dayNum);

      const ranges = m[2].split(',').map(s => s.trim()).filter(Boolean);
      if (!ranges.length) return { ok: false, error: `No time ranges on Day${dayNum}.` };

      for (const range of ranges) {
        const r = /^(\d{2}:\d{2})\s*(?:→|->|-)\s*(\d{2}:\d{2}|now)$/i.exec(range);
        if (!r) return { ok: false, error: `Invalid range "${range}". Use HH:MM→HH:MM.` };
        const start = _atTime(baseDay, dayNum, r[1]);
        if (!start) return { ok: false, error: `Invalid start time "${r[1]}".` };

        const endRaw = r[2].toLowerCase();
        const end = endRaw === 'now' ? new Date() : _atTime(baseDay, dayNum, endRaw);
        if (!end) return { ok: false, error: `Invalid end time "${r[2]}".` };
        if (end <= start) return { ok: false, error: `End must be after start in "${range}".` };
        if (_minuteKey(start) === _minuteKey(end)) {
          return { ok: false, error: `End minute must be after start minute in "${range}".` };
        }
        segments.push({ dayNum, start, end, isNow: endRaw === 'now' });
      }
    }

    if (!dayNums.has(1)) return { ok: false, error: 'Day1 is required.' };
    const maxDay = Math.max(...dayNums);
    for (let d = 1; d <= maxDay; d += 1) {
      if (!dayNums.has(d)) return { ok: false, error: `Missing Day${d}. Use consecutive days.` };
    }

    segments.sort((a, b) => a.start - b.start);
    for (let i = 1; i < segments.length; i += 1) {
      if (segments[i].start < segments[i - 1].end) {
        return { ok: false, error: `Overlapping ranges near Day${segments[i].dayNum}.` };
      }
    }

    const nowSegments = segments.filter(s => s.isNow);
    if (nowSegments.length > 1) return { ok: false, error: 'Use "now" only once.' };
    if (nowSegments.length === 1 && !segments[segments.length - 1].isNow) {
      return { ok: false, error: '"now" can appear only in the last range.' };
    }

    const pauses = [];
    for (let i = 0; i < segments.length - 1; i += 1) {
      if (segments[i].end < segments[i + 1].start) {
        pauses.push({
          from: segments[i].end.toISOString(),
          to: segments[i + 1].start.toISOString(),
          reason: 'explicit',
        });
      }
    }

    const hasNow = !!segments[segments.length - 1].isNow;
    if (!hasNow) {
      pauses.push({
        from: segments[segments.length - 1].end.toISOString(),
        to: null,
        reason: 'explicit',
      });
    }

    return {
      ok: true,
      main: {
        ...session,
        started_at: segments[0].start.toISOString(),
        ended_at: null,
        paused_intervals: pauses,
        status: hasNow ? 'active' : 'paused',
      },
    };
  }

  async function _syncSessionMain(main) {
    const resp = await fetch(API('/session/sync'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ main, talk: sessionTalk }),
    });
    if (!resp.ok) throw new Error(`sync failed: ${resp.status}`);
  }

  function _renderSessionIntervalsEditor(container) {
    const val = _esc(_sessionIntervalsDraft);
    const err = _sessionIntervalsError ? `<div class="session-main-intervals-error">${_esc(_sessionIntervalsError)}</div>` : '';
    container.innerHTML = `<textarea id="session-intervals-editor" class="session-main-intervals-editor">${val}</textarea>${err}`;
    container.style.display = 'block';

    const input = document.getElementById('session-intervals-editor');
    if (!input) return;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    input.addEventListener('input', () => {
      _sessionIntervalsDraft = input.value;
      if (_sessionIntervalsError) {
        _sessionIntervalsError = '';
        renderSessionPanel();
      }
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        _sessionIntervalsEditing = false;
        _sessionIntervalsError = '';
        renderSessionPanel();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        input.blur();
      }
    });
    input.addEventListener('blur', async () => {
      if (!sessionMain) return;
      const parsed = _buildSessionFromIntervalsText(sessionMain, input.value);
      if (!parsed.ok) {
        _sessionIntervalsEditing = true;
        _sessionIntervalsDraft = input.value;
        _sessionIntervalsError = parsed.error;
        renderSessionPanel();
        return;
      }
      try {
        await _syncSessionMain(parsed.main);
        sessionMain = parsed.main;
        _sessionIntervalsEditing = false;
        _sessionIntervalsError = '';
        _sessionIntervalsDraft = '';
        renderSessionPanel();
      } catch {
        _sessionIntervalsEditing = true;
        _sessionIntervalsDraft = input.value;
        _sessionIntervalsError = 'Failed to save session intervals.';
        renderSessionPanel();
      }
    });
  }

  function renderSummarySessionWindows() {
    const el = document.getElementById('summary-session-windows');
    if (!el) return;
    const activeSession = sessionTalk || sessionMain;
    if (!activeSession) {
      el.textContent = '';
      el.style.display = 'none';
      el.title = '';
      return;
    }
    const windows = _formatSessionWindows(activeSession);
    if (!windows) {
      el.textContent = '';
      el.style.display = 'none';
      el.title = '';
      return;
    }
    el.textContent = `Frames: ${windows}`;
    el.style.display = '';
    el.title = `Transcript frames included in "Regenerate Entire Session": ${windows}`;
  }

  let _transcriptLineCount = 0;
  let _transcriptLastContentAt = null; // Date or null
  let _transcriptLatestTs = null;      // "HH:MM:SS" string or null

  function updateSummary(points, updatedAt) {
    summaryPoints = points || [];
    summaryUpdatedAt = updatedAt;
    renderSummaryBadge();
    renderSummaryList();
  }

  function renderSummaryBadge() {
    const badge = document.getElementById('summary-badge');
    if (!badge) return;

    // Transcription warning (used for tooltip only)
    let noTranscriptTitle = '';
    if (_transcriptLastContentAt === null) {
      noTranscriptTitle = 'No transcription today';
    } else {
      const minAgo = (Date.now() - _transcriptLastContentAt) / 60000;
      if (minAgo >= 5) noTranscriptTitle = `No transcription for ${Math.round(minAgo)} minutes`;
    }

    const _fmtSummaryTime = (iso) => {
      if (!iso) return '';
      const d = new Date(iso);
      if (isNaN(d)) return '';
      const hhmm = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false});
      const today = new Date();
      return d.toDateString() === today.toDateString() ? hhmm : '📅 ' + hhmm;
    };
    const timeLabel = _fmtSummaryTime(summaryUpdatedAt);
    if (summaryPoints.length) {
      badge.textContent = timeLabel ? `🧠 ${timeLabel} Key Points` : `🧠 Key Points`;
      badge.className = 'badge connected';
      badge.style.cssText = 'cursor:pointer;';
      _setFooterBadgeTooltip(
        badge,
        noTranscriptTitle || `Key points from ${timeLabel || 'session'} — click to view`,
      );
    } else {
      badge.textContent = `🧠 Key Points`;
      badge.className = 'badge empty';
      badge.style.cssText = 'cursor:pointer;';
      _setFooterBadgeTooltip(badge, noTranscriptTitle || 'No key points yet');
    }
  }
  setInterval(renderSummaryBadge, 30000); // keep tooltip accurate

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
    const dlBtn = document.getElementById('keypoints-download');
    if (dlBtn) dlBtn.style.display = summaryPoints.length ? '' : 'none';
  }

  function toggleSummaryModal() {
    const overlay = document.getElementById('summary-overlay');
    if (overlay) overlay.classList.toggle('open');
  }

  function closeSummaryModal() {
    closeModal('summary-overlay');
  }

  function setKickedFavicon() {
    const canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    const ctx = canvas.getContext('2d');
    ctx.filter = 'grayscale(1) opacity(0.45)';
    ctx.font = '24px serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('⚙️', 16, 17);
    ctx.filter = 'none';
    ctx.strokeStyle = '#e03030';
    ctx.lineWidth = 5;
    ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(5, 5);  ctx.lineTo(27, 27); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(27, 5); ctx.lineTo(5, 27);  ctx.stroke();
    const link = document.querySelector("link[rel='icon']");
    link.type = 'image/png';
    link.href = canvas.toDataURL();
  }

  let _unreachableTimer = null;

  function setBadge(ok) {
    const b = document.getElementById('ws-badge');
    b.textContent = ok ? '🟢' : '🟢';
    b.className = `badge ${ok ? 'connected' : 'disconnected'}`;
    _setFooterBadgeTooltip(b, ok ? 'Server connected' : 'Server disconnected — reconnecting');
    if (ok) {
      if (_unreachableTimer) { clearTimeout(_unreachableTimer); _unreachableTimer = null; }
      const el = document.getElementById('server-unreachable-overlay');
      if (el) el.remove();
    } else {
      if (!_unreachableTimer && !document.getElementById('server-unreachable-overlay')) {
        _unreachableTimer = setTimeout(() => {
          _unreachableTimer = null;
          if (!document.getElementById('server-unreachable-overlay')) {
            document.body.insertAdjacentHTML('beforeend', `
              <div id="server-unreachable-overlay" style="position:fixed;inset:0;background:rgba(0,0,0,.88);display:flex;
                align-items:center;justify-content:center;z-index:9998;flex-direction:column;gap:1.2rem;
                text-align:center;padding:2rem;">
                <div style="font-size:5rem;line-height:1">🛑</div>
                <div style="font-size:1.6rem;font-weight:700;color:#fff">Server not reachable</div>
                <div style="font-size:0.95rem;color:#aaa">Reconnecting…</div>
                <a href="/host" style="margin-top:.5rem;font-size:.9rem;color:#7ba7ff;text-decoration:underline">Go to landing page</a>
              </div>`);
          }
        }, 8000);
      }
    }
  }

  function updateTokenBadge(usage) {
    const el = document.getElementById('token-cost');
    if (!el || !usage) return;
    el.className = 'badge';
    const cost = usage.estimated_cost_usd || 0;
    el.textContent = '$' + cost.toFixed(2);
    const inp = (usage.input_tokens || 0).toLocaleString();
    const out = (usage.output_tokens || 0).toLocaleString();
    _setFooterBadgeTooltip(el, 'Tokens: ' + inp + ' in / ' + out + ' out');
    el.style.color = cost > 3 ? 'var(--danger)' : cost > 1 ? 'var(--warn)' : 'var(--muted)';
  }

  function _buildSlidesCacheStatusMapFromSlides(slides) {
    const map = {};
    for (const slide of (Array.isArray(slides) ? slides : [])) {
      if (!slide || typeof slide !== 'object') continue;
      const slug = String(slide.slug || '').trim();
      if (!slug) continue;
      const status = String(slide.status || '').trim() || 'not_cached';
      const entry = { status };
      if (slide.size_bytes != null) entry.size_bytes = slide.size_bytes;
      if (slide.downloaded_at) entry.downloaded_at = slide.downloaded_at;
      if (slide.error) entry.error = slide.error;
      if (slide.title) entry.title = slide.title;
      if (slide.name) entry.name = slide.name;
      map[slug] = entry;
    }
    return map;
  }

  async function _refreshHostSlidesCatalog() {
    try {
      const res = await fetch(`/${SESSION_ID}/api/slides`, { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      _slidesCatalog = Array.isArray(data.slides) ? data.slides : [];
      const embeddedMap = _buildSlidesCacheStatusMapFromSlides(_slidesCatalog);
      const legacyMap = (data.cache_status && typeof data.cache_status === 'object')
        ? data.cache_status
        : {};
      _slidesCacheStatus = { ...embeddedMap, ...legacyMap };
      _renderSlidesCatalogPopover();
    } catch (_) {
      // Keep previous host slides catalog state on transient fetch errors.
    }
  }

  function _renderSlidesCatalogPopover() {
    const el = document.getElementById('slides-catalog-content');
    if (!el) return;
    const baseEntries = Array.isArray(_slidesCatalog)
      ? _slidesCatalog.map((slide) => {
          const bySlug = _slidesCacheStatus[String(slide?.slug || '').trim()] || {};
          return { ...slide, ...bySlug };
        })
      : [];
    const entries = baseEntries.length ? baseEntries : Object.values(_slidesCacheStatus);

    const countEl = document.getElementById('slides-catalog-count');
    if (countEl) countEl.textContent = entries.length ? ' ' + entries.length : '';

    if (!entries.length) {
      el.innerHTML = '<div style="padding:8px;opacity:0.5">No slides in catalog</div>';
      return;
    }

    const statusConfig = {
      'cached':          { icon: '🟢', label: 'cached',     color: 'var(--ok, #4caf50)' },
      'downloading':     { icon: '🔄', label: 'syncing',    color: 'var(--info, #2196f3)' },
      'polling_drive':   { icon: '🔄', label: 'syncing',    color: 'var(--info, #2196f3)' },
      'stale':           { icon: '🟡', label: 'stale',      color: 'var(--warn, #ff9800)' },
      'not_cached':      { icon: '🔴', label: 'not cached', color: 'var(--danger, #f44336)' },
      'poll_timeout':    { icon: '⚠',  label: 'timeout',    color: 'var(--warn, #ff9800)' },
      'download_failed': { icon: '❌', label: 'failed',     color: 'var(--danger, #f44336)' },
    };

    entries.sort((a, b) => (a.title || '').localeCompare(b.title || ''));

    const cachedCount = entries.filter(e => e.status === 'cached').length;
    let html = '<div class="slides-catalog-header">' + cachedCount + '/' + entries.length + ' cached</div>';

    for (const entry of entries) {
      const cfg = statusConfig[entry.status] || statusConfig['not_cached'];
      const title = entry.title || entry.name || entry.slug || '';
      const sizePart = entry.size_bytes ? (entry.size_bytes / 1048576).toFixed(1) + ' MB' : '';
      const agePart = entry.downloaded_at ? _formatSlideAge(entry.downloaded_at)
                    : entry.updated_at    ? 'pptx ' + _formatSlideAge(entry.updated_at)
                    : '';
      const detail = [sizePart, agePart].filter(Boolean).join('  ');
      html += '<div class="slides-catalog-line">'
          + '<span class="slides-cache-icon">' + cfg.icon + '</span>'
          + '<span class="slides-cache-title truncate">' + escHtml(title) + '</span>'
          + '<span class="slides-cache-label" style="color:' + cfg.color + '">' + cfg.label + '</span>'
          + '<span class="slides-cache-detail">' + detail + '</span>'
          + '</div>';
    }
    el.innerHTML = html;
  }

  function _formatSlideAge(isoStr) {
    const ms = Date.now() - new Date(isoStr).getTime();
    if (ms < 60000) return 'just now';
    if (ms < 3600000) return Math.floor(ms / 60000) + 'm ago';
    return Math.floor(ms / 3600000) + 'h ago';
  }

  function _setupStopSessionHover() {
    const wrap = document.getElementById('stop-session-wrap-left');
    const bubble = document.getElementById('stop-confirm-bubble-left');
    if (!wrap || !bubble) return;
    let hideTimer;
    wrap.addEventListener('mouseenter', () => {
      clearTimeout(hideTimer);
      bubble.style.display = '';
    });
    wrap.addEventListener('mouseleave', () => {
      hideTimer = setTimeout(() => { bubble.style.display = 'none'; }, 150);
    });
  }

  function _setupSlidesCatalogHover() {
    const hover = document.getElementById('slides-catalog-hover');
    const popover = document.getElementById('slides-catalog-popover');
    if (!hover) return;
    const open = () => {
      clearTimeout(_slidesCatalogHideTimer);
      if (popover) popover.hidden = false;
      hover.classList.add('open');
      _renderSlidesCatalogPopover();
    };
    const close = () => {
      clearTimeout(_slidesCatalogHideTimer);
      _slidesCatalogHideTimer = setTimeout(() => {
        hover.classList.remove('open');
        if (popover) popover.hidden = true;
      }, 120);
    };
    hover.addEventListener('mouseenter', open);
    hover.addEventListener('mouseleave', close);
  }

  function _fmtSecs(s) {
    s = Math.round(s);
    if (s < 60) return s + 's';
    const m = Math.floor(s / 60), r = s % 60;
    return r > 0 ? m + 'm ' + r + 's' : m + 'm';
  }

  function _renderGitReposPopover() {
    const el = document.getElementById('git-repos-content');
    if (!el) return;
    if (!_gitRepos.length) { el.innerHTML = '<div style="padding:8px;opacity:0.5">No repos tracked yet</div>'; return; }
    const sorted = [..._gitRepos].sort((a, b) => (b.files?.length || 0) - (a.files?.length || 0));
    let html = '';
    for (const r of sorted) {
      const repoName = (r.url || '').replace(/.*\//, '') || r.url || '';
      const fileCount = (r.files || []).length;
      html += '<div class="slides-catalog-line">'
        + '<span class="slides-cache-title truncate">' + escHtml(repoName) + '</span>'
        + '<span class="slides-cache-label" style="color:var(--muted);font-family:monospace">@ ' + escHtml(r.branch || '') + '</span>'
        + '<span class="slides-cache-detail">' + fileCount + ' file' + (fileCount !== 1 ? 's' : '') + '</span>'
        + '</div>';
    }
    el.innerHTML = html;
  }

  function _renderSlidesLogPopover() {
    const el = document.getElementById('slides-log-content');
    if (!el) return;
    if (!_slidesLog.length) { el.innerHTML = '<div style="padding:8px;opacity:0.5">No slides viewed yet</div>'; return; }
    // Group by file: {slides: Set, totalSecs}
    const byFile = {};
    for (const e of _slidesLog) {
      const f = e.file || '';
      if (!byFile[f]) byFile[f] = { slides: new Set(), totalSecs: 0 };
      byFile[f].slides.add(e.slide);
      byFile[f].totalSecs += e.seconds_spent || 0;
    }
    const sorted = Object.entries(byFile).sort((a, b) => b[1].totalSecs - a[1].totalSecs);
    let html = '';
    for (const [file, data] of sorted) {
      const name = file.replace(/\.pptx?$/i, '') || file;
      html += '<div class="slides-catalog-line">'
        + '<span class="slides-cache-title truncate">' + escHtml(name) + '</span>'
        + '<span class="slides-cache-label" style="color:var(--muted)">' + data.slides.size + ' slides</span>'
        + '<span class="slides-cache-detail">' + _fmtSecs(data.totalSecs) + '</span>'
        + '</div>';
    }
    el.innerHTML = html;
  }

  function _setupActivityLogHovers() {
    function _makeHover(hoverId, popoverId, renderFn) {
      const hover = document.getElementById(hoverId);
      const popover = document.getElementById(popoverId);
      if (!hover) return;
      let hideTimer = null;
      const open = () => { clearTimeout(hideTimer); hover.classList.add('open'); renderFn(); };
      const close = () => { clearTimeout(hideTimer); hideTimer = setTimeout(() => { hover.classList.remove('open'); }, 120); };
      hover.addEventListener('mouseenter', open);
      hover.addEventListener('mouseleave', close);
    }
    _makeHover('git-repos-hover', 'git-repos-popover', _renderGitReposPopover);
    _makeHover('slides-log-hover', 'slides-log-popover', _renderSlidesLogPopover);
  }

  function renderMode(mode) {
    applyConferenceLayout(mode === 'conference');
  }

  function applyConferenceLayout(isConference) {
    const rightCol = document.querySelector('.host-col-right');
    const grid = document.querySelector('.host-columns');
    const confQR = document.getElementById('conference-qr');
    const debateTab = document.getElementById('tab-debate');
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
      if (tokenCost) tokenCost.style.display = 'none';
      if (notesBadge) notesBadge.style.display = 'none';
      // Make center QR bright for conference
      if (centerQR) centerQR.classList.add('conference-center-qr');
      // Regenerate all QR codes with session-scoped join URL
      requestAnimationFrame(() => _regenerateAllQRCodes());
    } else {
      rightCol.style.display = '';
      grid.style.gridTemplateColumns = '25% 1fr 25%';
      leftCol.classList.remove('conference-layout');
      confQR.style.display = 'none';
      if (debateTab) debateTab.style.display = '';
      if (tokenCost) tokenCost.style.display = '';
      if (notesBadge) notesBadge.style.display = '';
      // Restore muted center QR
      if (centerQR) centerQR.classList.remove('conference-center-qr');
      _regenerateAllQRCodes();
    }
  }


  function renderTranscriptStatus(lineCount, totalLines, latestTs, lastContentAt) {
    _transcriptLineCount = lineCount || 0;
    _transcriptLatestTs = latestTs || null;
    _transcriptLastContentAt = lastContentAt ? new Date(lastContentAt).getTime() : null;
    renderSummaryBadge();
  }


  function renderOverlayStatus(connected) {
    const el = document.getElementById('overlay-badge');
    if (!el) return;
    el.className = `badge ${connected ? 'connected' : 'disconnected'}`;
    _setFooterBadgeTooltip(
      el,
      connected ? 'Desktop Overlay connected — click to fire a heart' : 'Desktop Overlay not connected — click to fire a heart',
    );
  }

  let _suppressHeartEcho = false;
  function triggerHostHeart() {
    showHostHeartFullscreen();
    _suppressHeartEcho = true;
    setTimeout(() => { _suppressHeartEcho = false; }, 500);
    fetch(`/api/participant/emoji/reaction`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Participant-ID': '__host__',
      },
      body: JSON.stringify({ emoji: '❤️' }),
    })
      .then((resp) => {
        if (!resp.ok) {
          // Keep old WS path as best-effort fallback.
          sendWS('emoji_reaction', { emoji: '❤️' });
        }
      })
      .catch(() => {
        // Keep old WS path as best-effort fallback.
        sendWS('emoji_reaction', { emoji: '❤️' });
    });
  }

  function renderPendingDeploy(pendingDeploy) {
    window.__deployIncoming = !!pendingDeploy;
    if (window.__updateDeployAge) window.__updateDeployAge();
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
  let _notesSessionFolder = null;
  let _notesSessionNotes = null;

  function renderNotesStatus(sessionFolder, sessionNotes) {
    _notesSessionFolder = sessionFolder;
    _notesSessionNotes = sessionNotes;
    _renderNotesBadge();
  }

  function _renderNotesBadge() {
    const el = document.getElementById('notes-badge');
    if (!el) return;
    const nonEmptyLines = hostNotesContent
      ? hostNotesContent.split('\n').filter(l => l.trim()).length
      : 0;
    el.style.cssText = 'cursor:pointer;';
    if (_notesSessionFolder && _notesSessionNotes) {
      el.textContent = nonEmptyLines > 0 ? `📝 (${nonEmptyLines}) Notes.txt` : `📝 Notes.txt`;
      el.className = 'badge connected';
      _setFooterBadgeTooltip(
        el,
        `${_notesSessionFolder}/${_notesSessionNotes}${nonEmptyLines > 0 ? `\n${nonEmptyLines} non-empty lines` : ''}\nClick to view`,
      );
    } else if (_notesSessionFolder) {
      el.textContent = nonEmptyLines > 0 ? `📝 (${nonEmptyLines}) Notes.txt` : `📝 Notes.txt`;
      el.className = 'badge';
      el.style.cssText = 'cursor:pointer; color:var(--warn); border:1px solid var(--warn); --badge-fill:#ffd16644;';
      _setFooterBadgeTooltip(el, 'Session folder found but no notes file inside');
    } else {
      el.textContent = '📝 Notes.txt';
      el.className = 'badge empty';
      _setFooterBadgeTooltip(el, 'No session folder found for today');
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
    _renderNotesBadge();
  }

  function downloadKeyPoints() {
    if (!summaryPoints.length) return;
    const lines = summaryPoints.map(p => {
      const text = typeof p === 'string' ? p : p.text;
      return '• ' + text;
    });
    const content = 'Key Points\n' + '='.repeat(10) + '\n\n' + lines.join('\n');
    const blob = new Blob([content], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `key-points-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
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
    toggleModal('host-notes-overlay');
  }

  function closeHostNotesModal() {
    closeModal('host-notes-overlay');
  }

  function renderParticipantList(participantIds) {
    cachedParticipantIds = participantIds;
    const sorted = Object.keys(scores).length > 0
      ? [...participantIds].sort((a, b) => {
          const scoreDiff = (scores[b] || 0) - (scores[a] || 0);
          if (scoreDiff !== 0) return scoreDiff;
          const nameA = (participantDataById[a]?.name || '').toLowerCase();
          const nameB = (participantDataById[b]?.name || '').toLowerCase();
          return nameA.localeCompare(nameB);
        })
      : participantIds;
    const ul = document.getElementById('pax-list');
    ul.innerHTML = sorted.map(pid => {
      const participant = participantDataById[pid] || {};
      const name = participant.name || 'Unknown';
      const loc = participant.location || '';
      const pts = scores[pid] || 0;
      const scoreTag = pts > 0 ? `<span class="pax-score" title="Click to reset score" onclick="resetOneScore('${escHtml(pid)}','${escHtml(name)}',${pts})">⭐ ${pts} pts</span>` : '';
      const locLabel = loc ? resolvedCities[loc] || loc : null;
      const avatar = participant.avatar || '';
      let avatarHtml = '';
      if (avatar && avatar.startsWith('letter:')) {
          const parts = avatar.split(':');
          const lt = parts[1] || '??';
          const clr = parts.slice(2).join(':') || 'var(--muted)';
          avatarHtml = `<span class="avatar letter-avatar" style="width:28px;height:28px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:.65rem;line-height:1;color:#fff;background:${clr}">${lt}</span>`;
      } else if (avatar) {
          avatarHtml = `<img src="/static/avatars/${escHtml(avatar)}" class="avatar" style="width:28px;height:28px" onerror="this.style.display='none'">`;
      }
      const debateSide = participantDebateSides[pid];
      const debateIcon = _debateActive
          ? (debateSide === 'for' ? '<span title="FOR">👍</span> ' : debateSide === 'against' ? '<span title="AGAINST">👎</span> ' : '<span title="Undecided">⏳</span> ')
          : '';
      const ip = participant.ip || '';
      const online = participant.online !== false;
      const pasteTexts = participant.paste_texts || [];
      const pasteIcons = pasteTexts.map((entry, i) => {
        const preview = (entry.text.length > 100 ? entry.text.substring(0, 100) + '…' : entry.text).replace(/\n/g, ' ');
        return `<span class="paste-icon" title="${escHtml(preview)}" data-uuid="${escHtml(pid)}" data-paste-id="${entry.id}" onclick="copyAndDismissPaste(this)"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5.5" y="5.5" width="9" height="9" rx="2"/><path d="M3 10.5H2.5a1.5 1.5 0 0 1-1.5-1.5V2.5A1.5 1.5 0 0 1 2.5 1h6.5A1.5 1.5 0 0 1 11 2.5V3"/></svg></span>`;
      }).join('');
      const uploadedFiles = (participant.uploaded_files || []).filter(entry => {
        // Hide icons after UPLOAD_CLEANUP_MINUTES
        if (entry.downloaded_at != null) {
          const elapsed = Date.now() / 1000 - entry.downloaded_at;
          if (elapsed >= UPLOAD_CLEANUP_MINUTES * 60) return false;
        }
        return true;
      });
      const uploadIcons = uploadedFiles.map(entry => {
        const sizeMB = (entry.size / (1024 * 1024)).toFixed(1);
        const sizeStr = entry.size < 1024 * 1024 ? `${(entry.size / 1024).toFixed(0)} KB` : `${sizeMB} MB`;
        const downloaded = entry.downloaded_at != null;
        const title = downloaded ? `${entry.filename} (${sizeStr}) — downloaded` : `${entry.filename} (${sizeStr}) — click to download`;
        return `<span class="upload-icon${downloaded ? ' downloaded' : ''}" title="${escHtml(title)}" data-uuid="${escHtml(pid)}" data-upload-id="${entry.id}" onclick="downloadUploadedFile(this)"><svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 4v9"/><path d="M6 9.5L10 13.5L14 9.5"/><path d="M4.5 13.5v1a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-1"/></svg></span>`;
      }).join('');
      return `<li class="${online ? 'online' : 'offline'}"><span class="pax-name" title="${ip ? 'IP: ' + ip : ''}">${debateIcon}${avatarHtml}<span class="pax-name-text truncate">${escHtml(name)}</span>${pasteIcons}${uploadIcons}</span>${scoreTag}${locLabel ? `<span class="pax-location" onclick="openMap()">${escHtml(locLabel)}<div class="footer-badge-tooltip">View all on map</div></span>` : ''}</li>`;
    }).join('');

    // Lazily resolve any raw "lat, lon" strings to city names
    sorted.forEach(pid => {
      const loc = participantDataById[pid]?.location || '';
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
          renderParticipantList(cachedParticipantIds);
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
    const entries = cachedParticipantIds
      .map(pid => {
        const participant = participantDataById[pid] || {};
        return [participant.name || 'Unknown', participant.location || ''];
      })
      .filter(([, loc]) => !!loc);
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
  const joinUrl = _getJoinUrl();
  // Center QR: light gray (muted), click to brighten for 5s
  new QRCode(document.getElementById('qr-code'), {
    text: joinUrl,
    width: qrSize,
    height: qrSize,
    colorDark: '#888888',
    colorLight: 'transparent',
  });

  // Fullscreen QR overlay
  function _positionQROverlayBetweenHeaderAndFooter() {
    const overlay = document.getElementById('qr-overlay');
    const topBar = document.querySelector('.host-top-bar');
    const footer = document.querySelector('.host-footer');
    if (!overlay || !topBar || !footer) return;
    const top = Math.max(0, Math.ceil(topBar.getBoundingClientRect().bottom));
    const bottom = Math.max(0, Math.ceil(window.innerHeight - footer.getBoundingClientRect().top));
    overlay.style.top = `${top}px`;
    overlay.style.bottom = `${bottom}px`;
    overlay.style.left = '0';
    overlay.style.right = '0';
  }

  function renderFullscreenQR() {
    const joinUrl = _getJoinUrl();
    const qrFull = document.getElementById('qr-fullscreen');
    if (qrFull) {
      qrFull.innerHTML = '';
      const overlay = document.getElementById('qr-overlay');
      const availW = overlay && overlay.classList.contains('open') ? overlay.clientWidth : window.innerWidth;
      const availH = overlay && overlay.classList.contains('open') ? overlay.clientHeight : window.innerHeight;
      const qrFullSize = Math.max(120, Math.floor(Math.min(availW, availH) * 0.98));
      if (typeof QRCode !== 'undefined') {
        new QRCode(qrFull, { text: joinUrl, width: qrFullSize, height: qrFullSize, colorDark: '#000000', colorLight: '#ffffff' });
      }
    }
    const overlayUrl = document.getElementById('qr-overlay-url');
    if (overlayUrl) overlayUrl.textContent = joinUrl;
  }
  renderFullscreenQR();

  // Center QR: click to brighten for 5s then fade back
  let _qrBrightenTimer = null;
  document.getElementById('qr-code').addEventListener('click', () => {
    const el = document.getElementById('qr-code');
    el.classList.add('qr-bright');
    clearTimeout(_qrBrightenTimer);
    _qrBrightenTimer = setTimeout(() => el.classList.remove('qr-bright'), 5000);
  });

  function openQR() {
    const overlay = document.getElementById('qr-overlay');
    if (overlay) {
      overlay.classList.add('open');
      _positionQROverlayBetweenHeaderAndFooter();
      renderFullscreenQR();
    }
  }

  // Footer QR icon: open fullscreen join QR overlay
  const footerQrIcon = document.getElementById('footer-qr-icon');
  if (footerQrIcon) {
    footerQrIcon.addEventListener('click', (event) => {
      event.preventDefault();
      openQR();
    });
    footerQrIcon.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openQR();
      }
    });
  }

  const qrFullscreen = document.getElementById('qr-fullscreen');
  if (qrFullscreen) {
    qrFullscreen.addEventListener('click', (event) => {
      event.stopPropagation();
      closeQR();
    });
  }

  function closeQR() {
    closeModal('qr-overlay');
  }

  window.addEventListener('resize', () => {
    const overlay = document.getElementById('qr-overlay');
    if (overlay && overlay.classList.contains('open')) {
      _positionQROverlayBetweenHeaderAndFooter();
      renderFullscreenQR();
    }
  });


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
    const res = await fetch(API('/poll'), {
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
    const res = await fetch(API('/poll/timer'), {
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
    await fetch(API(open ? '/poll/open' : '/poll/close'), {
      method: 'POST',
    });
  }

  async function clearPoll() {
    await fetch(API('/poll'), { method: 'DELETE' });
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

    const votePct = totalParticipants > 0 ? Math.round((totalVotes / totalParticipants) * 100) : 0;
    const voteProgressSection = pollActive ? `
      <div class="vote-progress-overlay">
        <div class="vote-progress-fill" id="vote-progress-fill" style="width:${votePct}%"></div>
        <span class="vote-progress-label" id="vote-progress-label">${totalVotes} of ${totalParticipants} voted</span>
      </div>
      <p class="vote-anon-msg">🔒 Votes are anonymous — no wrong answers, just deeper understanding</p>` : '';

    const mainContent = pollActive
      ? `<div class="options-plain">${currentPoll.options.map(opt =>
          `<div class="option-text-only">${escHtml(opt.text)}</div>`).join('')}</div>
         ${voteProgressSection}`
      : `<div class="bars-container"><div class="bars-wrapper">${bars}</div></div>
         <p style="font-size:.8rem; color:var(--muted); margin-top:.5rem;">${totalVotes} total vote${totalVotes!==1?'s':''}`;

    el.innerHTML = `
      <p class="poll-question">${escHtml(currentPoll.question)}</p>
      ${mainContent}${pollActive ? '' : '</p>'}
      ${currentPoll.source ? `<p class="poll-source-ref">📖 ${escHtml(currentPoll.source)}${currentPoll.page ? `, p. ${escHtml(currentPoll.page)}` : ''}</p>` : ''}
      <div class="btn-row">
        <span class="badge status-pill ${statusLabel}">${statusText}</span>
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
    if (pollActive) {
      // During voting: update vote progress overlay only (results hidden)
      const fill = document.getElementById('vote-progress-fill');
      const label = document.getElementById('vote-progress-label');
      const pct = totalParticipants > 0 ? Math.round((totalVotes / totalParticipants) * 100) : 0;
      if (fill) fill.style.width = `${pct}%`;
      if (label) label.textContent = `${totalVotes} of ${totalParticipants} voted`;
      return;
    }
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
      await fetch(API('/quiz-request'), {
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
      const res = await fetch(API('/quiz-refine'), {
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
    const res = await fetch(API('/poll'), {
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
      await fetch(API('/quiz-preview'), { method: 'DELETE' });
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
    await fetch(API('/quiz-preview'), { method: 'DELETE' });
  }

  async function resetScores() {
    if (!confirm('Reset all participant scores to zero?')) return;
    await fetch(API('/scores'), { method: 'DELETE' });
    toast('Scores reset ✓');
  }

  async function resetOneScore(uuid, name, pts) {
    if (!confirm(`Reset ${name}'s score (${pts} pts) to zero?`)) return;
    await fetch(API(`/scores/${uuid}`), { method: 'DELETE' });
    toast(`${name}'s score reset ✓`);
  }

  const _LANG_FLAG = { ro: '🇷🇴', en: '🇬🇧', auto: '🌐' };

  function updateTranscriptionLangBtn(lang, pending = false) {
    const btn = document.getElementById('btn-transcription-lang');
    if (!btn) return;
    btn.textContent = `${_LANG_FLAG[lang] || lang} ${lang.toUpperCase()}`;
    _setFooterBadgeTooltip(btn, `Transcription: ${lang.toUpperCase()}${pending ? ' (applying…)' : ''} — click to toggle`);
    btn.style.opacity = pending ? '0.4' : '0.8';
    btn.dataset.lang = lang;
    btn.className = 'badge' + (pending ? ' disabled' : '');
  }

  async function toggleTranscriptionLanguage() {
    const btn = document.getElementById('btn-transcription-lang');
    const current = btn?.dataset.lang || 'ro';
    const next = current === 'ro' ? 'en' : 'ro';
    updateTranscriptionLangBtn(next, true);
    await fetch('/api/transcription-language', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: next }),
    });
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
    _resetInactivityTimer();
    const slidesTab = document.getElementById('tab-slides');
    if (slidesTab) slidesTab.classList.toggle('active', tab === 'none');
    ['poll', 'wordcloud', 'qa', 'codereview', 'debate'].forEach(t => {
      document.getElementById('tab-' + t).classList.toggle('active', tab === t);
      const contentEl = document.getElementById('tab-content-' + t);
      contentEl.style.display = tab === t ? (t === 'codereview' ? 'flex' : '') : 'none';
    });
    await fetch(API('/activity'), {
      method: 'PUT',
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
    _resetInactivityTimer();
    ['qr', 'poll', 'wordcloud', 'qa', 'debate', 'codereview'].forEach(id => {
      const el = document.getElementById('center-' + id);
      if (id === 'qr') {
        el.style.display = 'none';
      } else if (id === 'poll') {
        // Show poll panel when activity is 'poll' OR 'none' (for quiz gen controls)
        const show = currentActivity === 'poll' || currentActivity === 'none';
        el.style.display = show ? 'flex' : 'none';
        // Hide the poll results section when no poll is active
        const pollResults = document.getElementById('poll-results-section');
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
    // Sync slides tab active state
    const slidesTab = document.getElementById('tab-slides');
    if (slidesTab) slidesTab.classList.toggle('active', currentActivity === 'none');
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
    await fetch(API('/wordcloud/topic'), {
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
    if (!word) return;
    fetch(API('/wordcloud/word'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ word })
    });
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
    await fetch(API('/wordcloud/clear'), { method: 'POST' });
  }

  function renderHostWordCloud(wordsMap) {
    const canvas = document.getElementById('host-wc-canvas');
    if (!canvas) return;
    const key = JSON.stringify(wordsMap);
    if (key === _hostWcLastDataKey) return;
    _hostWcLastDataKey = key;
    clearTimeout(_hostWcDebounceTimer);
    _hostWcDebounceTimer = setTimeout(() => _drawHostCloud(canvas, wordsMap), 300);
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
    if (!text) return;
    fetch(API('/qa/submit'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
    });
    input.value = '';
    const btn = document.getElementById('host-qa-submit-btn');
    if (btn) btn.disabled = true;
    input.focus();
  }

  async function clearQA() {
    await fetch(API('/qa/clear'), { method: 'POST' });
  }

  async function toggleAnswered(qid, current) {
    await fetch(API(`/qa/question/${qid}/answered`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answered: !current }),
    });
  }

  async function deleteQuestion(qid) {
    await fetch(API(`/qa/question/${qid}`), { method: 'DELETE' });
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
        await fetch(API(`/qa/question/${qid}/text`), {
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
      await fetch(API('/codereview'), {
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
    await fetch(API('/codereview/status'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ open: false }),
    });
  }

  async function confirmCodeReviewLine(line) {
    await fetch(API('/codereview/confirm-line'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ line }),
    });
  }

  async function clearCodeReview() {
    codereviewSelectedLine = null;
    await fetch(API('/codereview'), {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });
    document.getElementById('codereview-snippet').value = '';
  }

  updateGenBtn();
  connectWS();

  document.getElementById('wc-host-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') hostSubmitWord();
  });
  document.getElementById('wc-topic-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') pushWordCloudTopic();
  });

  // escDebate replaced by escHtml from utils.js

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
  let _activeBeepContexts = [];

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
      _activeBeepContexts.push({ ctx, gain });
      setTimeout(() => { _activeBeepContexts = _activeBeepContexts.filter(a => a.ctx !== ctx); }, 500);
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
    const active = _activeBeepContexts.splice(0);
    for (const { ctx, gain } of active) {
      try {
        gain.gain.cancelScheduledValues(ctx.currentTime);
        gain.gain.setValueAtTime(gain.gain.value, ctx.currentTime);
        gain.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.3);
        setTimeout(() => { try { ctx.close(); } catch(e) {} }, 350);
      } catch(e) {}
    }
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
    await fetch(API('/debate/round-timer'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({round_index: index, seconds}),
    });
  }

  async function endDebateRound() {
    _stopBeeping();
    await fetch(API('/debate/end-round'), { method: 'POST' });
  }

  async function setDebateFirstSide(side) {
    await fetch(API('/debate/first-side'), {
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
    await fetch(API('/debate'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ statement }),
    });
  }

  async function debateCloseSelection() {
    await fetch(API('/debate/close-selection'), { method: 'POST' });
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
      await fetch(API('/debate/end-arguments'), { method: 'POST', signal: controller.signal });
    } catch(e) {
      // timeout or network error — state will update via WS anyway
    } finally {
      clearTimeout(timeout);
    }
  }

  async function debateForceAssign() {
    await fetch(API('/debate/force-assign'), { method: 'POST' });
  }

  async function debateReset() {
    await fetch(API('/debate/reset'), { method: 'POST' });
  }

  async function debateNextPhase(phase) {
    await fetch(API('/debate/phase'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phase }),
    });
  }

  async function debateSkipAI() {
    // Post empty result to advance past ai_cleanup if daemon is unavailable
    await fetch(API('/debate/ai-result'), {
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
      title.innerHTML = debateActive ? escHtml(msg.debate_statement) : '';
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
        ? `<span style="color:var(--accent);font-size:.8rem;">🏆 ${Object.entries(champions).map(([s,n]) => `${s==='for'?'👍':'👎'} ${escHtml(n)}`).join(', ')}</span>`
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
          <div class="spinner debate-ai-spinner"></div>
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
          <span class="debate-arg-author">${escHtml(a.author)}</span>
          <span class="debate-arg-votes">▲ ${a.upvote_count}</span>
        </div>
        <div class="debate-arg-text">${escHtml(a.text)}</div>
      </div>`;
    };

    const renderMerged = () => `<div class="debate-arg debate-arg-merged">
      <span style="color:var(--muted);font-size:.8rem;">🤖 duplicate, merged above</span>
    </div>`;

    const champFor = champions?.for ? `<div class="debate-champion">🏆 ${escHtml(champions.for)}</div>` : '';
    const champAgainst = champions?.against ? `<div class="debate-champion">🏆 ${escHtml(champions.against)}</div>` : '';

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
    if (!_leaderboardActive) {
        const scoredCount = Object.values(scores || {}).filter(s => s > 0).length;
        if (scoredCount < 1) {
            showLeaderboardError('No scores yet — run a poll first');
            return;
        }
        try {
            await fetch(API('/leaderboard/show'), { method: 'POST' });
        } catch (e) {
            console.error('Leaderboard show failed:', e);
        }
    } else {
        hideLeaderboard();
    }
}

let _leaderboardErrorTimer = null;
function showLeaderboardError(msg) {
    let el = document.getElementById('leaderboard-error');
    if (!el) {
        el = document.createElement('span');
        el.id = 'leaderboard-error';
        el.style.cssText = 'margin-left:8px;color:#f87171;font-size:12px;white-space:nowrap;';
        const btn = document.getElementById('btn-leaderboard');
        btn.parentNode.insertBefore(el, btn.nextSibling);
    }
    el.textContent = msg;
    clearTimeout(_leaderboardErrorTimer);
    _leaderboardErrorTimer = setTimeout(() => { el.textContent = ''; }, 3000);
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
    // Button is always enabled; error shown on click if no scores
}

let _currentActivity = 'none';

// ── Session management panel ──

function _esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function onSessionEmojiKey(event, action) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  if (typeof action === 'function') action();
}

function toggleStopConfirm() {
  const bubble = document.getElementById('stop-confirm-bubble-left');
  if (bubble) bubble.style.display = bubble.style.display === 'none' ? '' : 'none';
}
function hideStopConfirm() {
  const bubble = document.getElementById('stop-confirm-bubble-left');
  if (bubble) bubble.style.display = 'none';
}
function stopSessionConfirmed() {
  // Show full-screen blocker while ending session
  let blocker = document.getElementById('session-ending-blocker');
  if (!blocker) {
    blocker = document.createElement('div');
    blocker.id = 'session-ending-blocker';
    blocker.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.82);z-index:99999;display:flex;align-items:center;justify-content:center;color:#fff;font-size:1.4rem;font-weight:600;letter-spacing:.03em;flex-direction:column;gap:1rem;';
    blocker.innerHTML = '<span style="display:inline-block;width:32px;height:32px;border:3px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin .7s linear infinite;"></span><span>Ending session…</span>';
    document.body.appendChild(blocker);
  }
  fetch('/api/session/end', {method: 'POST'})
    .then(() => { window.location = '/host'; })
    .catch(e => console.error('stopSession failed:', e));
}

function updateSessionCodeBar(sessionId) {
  const changed = sessionId !== _currentSessionId;
  _currentSessionId = sessionId;
  const bar = document.getElementById('session-code-bar');
  const display = document.getElementById('session-code-display');
  if (bar) bar.style.display = sessionId ? 'flex' : 'none';
  if (display) display.textContent = sessionId || '';

  // Update participant link (full URL as uniform wave chars) and copy icon
  const suffix = document.getElementById('session-id-suffix');
  if (suffix) suffix.style.display = 'none'; // always hidden — full URL in wave chars
  const copyIcon = document.getElementById('copy-link-icon');
  if (copyIcon) copyIcon.style.display = sessionId ? '' : 'none';
  const pLink = document.getElementById('participant-link');
  if (pLink && changed) {
    pLink.innerHTML = _buildUrlHtml();
    pLink.title = 'Click to copy • Ctrl/Cmd+Click to open';
  }

  // Regenerate all QR codes with the session-scoped join URL
  _regenerateAllQRCodes();

  // Set cookie so participant page on same machine can auto-join
  if (sessionId) {
    document.cookie = `host_session_id=${sessionId}; path=/; SameSite=Lax; max-age=86400`;
  } else {
    document.cookie = 'host_session_id=; path=/; max-age=0';
  }
}

function copySessionLink() {
  if (!_currentSessionId) return;
  const link = `${location.origin}/${_currentSessionId}`;
  navigator.clipboard.writeText(link).then(() => {
    const icon = document.getElementById('copy-link-icon');
    if (icon) {
      icon.style.opacity = '1';
      setTimeout(() => { icon.style.opacity = ''; }, 1200);
      // Floating "Copied!" tooltip above icon
      const tip = document.createElement('span');
      tip.textContent = 'Copied!';
      tip.style.cssText = 'position:absolute; bottom:calc(100% + 6px); left:50%; transform:translateX(-50%); background:#222; color:#4f4; font-size:.75rem; padding:2px 8px; border-radius:4px; white-space:nowrap; pointer-events:none; opacity:1; transition:opacity .6s ease 0.8s;';
      icon.parentElement.style.position = 'relative';
      icon.parentElement.appendChild(tip);
      requestAnimationFrame(() => tip.style.opacity = '0');
      setTimeout(() => tip.remove(), 1600);
    }
  });
}

function copyCenterUrl(el) {
  const url = _getJoinUrl();
  navigator.clipboard.writeText(url).then(() => {
    toast('Link copied ✓');
    // "Copied!" tooltip above the element
    const tip = document.createElement('div');
    tip.textContent = 'Copied!';
    tip.style.cssText = 'position:absolute;top:-2rem;left:50%;transform:translateX(-50%);background:var(--accent2);color:#000;padding:.15rem .6rem;border-radius:6px;font-size:.85rem;font-weight:600;pointer-events:none;opacity:1;transition:opacity 1s;white-space:nowrap;';
    el.appendChild(tip);
    requestAnimationFrame(() => requestAnimationFrame(() => tip.style.opacity = '0'));
    setTimeout(() => tip.remove(), 1400);
  });
}

function _showFooterCopiedTooltip(el, message = 'Link Copied') {
  if (!el) return;
  const old = el.querySelector('.footer-copy-tip');
  if (old) old.remove();
  const tip = document.createElement('div');
  tip.className = 'footer-copy-tip';
  tip.textContent = message;
  tip.style.cssText = 'position:absolute; left:50%; bottom:calc(100% + 6px); transform:translateX(-50%); background:var(--surface2); color:var(--accent2); border:1px solid var(--border); padding:.12rem .45rem; border-radius:6px; font-size:.72rem; pointer-events:none; opacity:1; transition:opacity .35s ease 3s;';
  el.appendChild(tip);
  requestAnimationFrame(() => requestAnimationFrame(() => { tip.style.opacity = '0'; }));
  setTimeout(() => tip.remove(), 3400);
}

function onFooterJoinLinkClick(event) {
  const url = _getJoinUrl();
  if (event.ctrlKey || event.metaKey) {
    event.preventDefault();
    window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }
  event.preventDefault();
  _showFooterCopiedTooltip(document.querySelector('.host-footer-center'), 'Link Copied');
  void navigator.clipboard.writeText(url).catch(() => {});
}

function _getJoinUrl() {
  const base = _joinBaseUrl || location.origin;
  return _currentSessionId ? `${base}/${_currentSessionId}` : base;
}

function _buildUrlHtml() {
  const base = _joinBaseUrl || ('https://' + location.host);
  const full = _currentSessionId ? base + '/' + _currentSessionId : base;
  const yellowFrom = _currentSessionId ? base.length + 1 : full.length; // after the '/'
  return full.split('').map((ch, i) => {
    const yellow = i >= yellowFrom;
    const style = `animation-delay:${(i * 0.12).toFixed(2)}s${yellow ? '; --wave-dim:#f0c040aa; --wave-bright:#f0c040;' : ''}`;
    return `<span class="wave-char" style="${style}">${ch}</span>`;
  }).join('');
}

function _regenerateAllQRCodes() {
  const joinUrl = _getJoinUrl();
  const isLight = window.matchMedia('(prefers-color-scheme: light)').matches;

  // Center QR (muted in workshop, bright in conference)
  const centerPanel = document.getElementById('center-qr');
  const qrDiv = document.getElementById('qr-code');
  if (centerPanel && qrDiv) {
    qrDiv.innerHTML = '';
    const isConf = centerPanel.classList.contains('conference-center-qr');
    const sz = (Math.min(centerPanel.offsetWidth, centerPanel.offsetHeight) || 400) * (isConf ? 0.85 : 0.8);
    const dark = isConf ? (isLight ? '#1a1d2e' : '#ffffff') : (isLight ? '#aaaaaa' : '#888888');
    const light = isConf ? (isLight ? '#f4f5f9' : '#0f1117') : 'transparent';
    if (typeof QRCode !== 'undefined') new QRCode(qrDiv, { text: joinUrl, width: sz, height: sz, colorDark: dark, colorLight: light });
  }

  // Fullscreen QR overlay
  renderFullscreenQR();

  // Conference left QR
  const confQRCode = document.getElementById('conference-qr-code');
  if (confQRCode && confQRCode.offsetParent !== null) {
    confQRCode.innerHTML = '';
    const confQREl = document.getElementById('conference-qr');
    const availH = confQREl ? confQREl.clientHeight - 40 : 200;
    const availW = confQREl ? confQREl.clientWidth - 20 : 200;
    const qrSize = Math.max(120, Math.min(availH, availW, 400));
    confQRCode.style.width = qrSize + 'px';
    confQRCode.style.height = qrSize + 'px';
    if (typeof QRCode !== 'undefined') new QRCode(confQRCode, { text: joinUrl, width: qrSize, height: qrSize, colorDark: '#000', colorLight: '#fff' });
  }

  // Update URL labels with session path
  const confUrl = document.getElementById('conference-qr-url');
  if (confUrl && confUrl.offsetParent !== null) confUrl.innerHTML = _buildUrlHtml();
  const centerUrl = document.getElementById('center-qr-url');
  if (centerUrl) centerUrl.innerHTML = _buildUrlHtml();
}

function renderSessionPanel() {
  const main = sessionMain;
  const talk = sessionTalk;
  const daemonOnline = daemonLastSeen && (Date.now() - new Date(daemonLastSeen).getTime() < 30000);

  // FRAGILE: daemon connected, no main session folder
  const fragile = daemonOnline && !main;
  const fragileRow = document.getElementById('session-fragile-row');
  if (fragileRow) fragileRow.style.display = fragile ? 'flex' : 'none';
  if (fragile) {
    const prefix = document.getElementById('session-date-prefix');
    if (prefix && !prefix.textContent) {
      const today = new Date().toISOString().slice(0, 10);
      prefix.textContent = today + ' ';
    }
  }

  // Session title in top bar center
  const titleEl = document.getElementById('host-top-title');
  if (titleEl) {
    const rawName = main ? (main.name || '') : (_sessionName || '');
    titleEl.textContent = rawName.replace(/^\d{4}-\d{2}-\d{2}(?:\.\.\S+)?\s*/, '');
  }
  // Stop button is always enabled (host can always request session end).
  const stopBtn = document.getElementById('stop-session-btn-left');
  if (stopBtn) {
    stopBtn.disabled = false;
    stopBtn.style.pointerEvents = '';
    stopBtn.classList.remove('disabled');
  }

  // Main session row
  const mainRow = document.getElementById('session-main-row');
  if (mainRow) mainRow.style.display = main ? 'flex' : 'none';
  if (main) {
    const nameEl = document.getElementById('session-main-name');
    if (nameEl) nameEl.textContent = main.name;
    const paused = main.status === 'paused';
    const statusEl = document.getElementById('session-status');
    if (statusEl) {
      statusEl.textContent = paused ? 'paused' : 'running';
      statusEl.className = 'session-status-badge' + (paused ? ' session-status-paused' : ' wave-char');
    }
    const pauseBtn = document.getElementById('btn-pause-session');
    if (pauseBtn) {
      pauseBtn.textContent = paused ? '▶️' : '⏸️';
      pauseBtn.title = paused ? 'Resume transcription' : 'Pause transcription';
      pauseBtn.classList.toggle('session-pause-blinking', paused);
    }

    const intervalsEl = document.getElementById('session-main-intervals');
    if (intervalsEl) {
      if (_sessionIntervalsEditing) {
        _renderSessionIntervalsEditor(intervalsEl);
      } else {
        const rows = _groupSessionWindowsByDay(main);
        if (rows.length) {
          const parts = rows.map((row) => {
            const chips = row.windows
              .map((w) => (
                `<span class="session-main-interval-chip${w.isOngoing ? ' session-main-interval-chip-live' : ''}" ` +
                `data-start="${_esc(w.startIso)}" data-end="${_esc(w.endIso)}" ` +
                `title="Open normalized transcript lines for this interval in a new tab">${_esc(w.label)}</span>`
              ))
              .join('');
            return `<div class="session-main-interval-day-row"><span class="session-main-interval-day-label">Day${row.dayNum}:</span><span class="session-main-interval-day-chips">${chips}</span></div>`;
          });
          intervalsEl.innerHTML = parts.join('');
          intervalsEl.querySelectorAll('.session-main-interval-chip').forEach((chip) => {
            chip.addEventListener('click', (event) => {
              event.stopPropagation();
              openSessionIntervalLines(chip.dataset.start, chip.dataset.end);
            });
          });
          intervalsEl.style.display = 'flex';
          intervalsEl.classList.add('session-main-intervals-editable');
          intervalsEl.title = 'Click to edit intervals';
          intervalsEl.onclick = () => {
            _sessionIntervalsEditing = true;
            _sessionIntervalsDraft = _sessionIntervalsToEditableText(main);
            _sessionIntervalsError = '';
            renderSessionPanel();
          };
        } else {
          intervalsEl.innerHTML = '';
          intervalsEl.style.display = 'none';
          intervalsEl.onclick = null;
          intervalsEl.title = '';
        }
      }
    }
  } else {
    const intervalsEl = document.getElementById('session-main-intervals');
    if (intervalsEl) {
      intervalsEl.innerHTML = '';
      intervalsEl.style.display = 'none';
      intervalsEl.onclick = null;
      intervalsEl.title = '';
    }
  }

  // Talk row
  const talkRow = document.getElementById('session-talk-row');
  if (talkRow) talkRow.style.display = talk ? 'flex' : 'none';
  if (talk) {
    const nameEl = document.getElementById('session-talk-name');
    if (nameEl) nameEl.textContent = talk.name;
  }

  // START TALK: show inline only when main exists and no talk active
  const startTalkBtn = document.getElementById('btn-start-talk');
  const controlsSeparator = document.getElementById('session-controls-separator');
  const showStartTalk = !!(main && !talk);
  if (startTalkBtn) startTalkBtn.style.display = showStartTalk ? '' : 'none';
  if (controlsSeparator) controlsSeparator.style.display = showStartTalk ? '' : 'none';
  renderSummarySessionWindows();
}

function startTalk() {
  fetch('/api/session/start_talk', {method: 'POST'})
    .catch(e => console.error('startTalk failed:', e));
}

function endTalk() {
  fetch('/api/session/end_talk', {method: 'POST'})
    .catch(e => console.error('endTalk failed:', e));
}

function createSession() {
  const prefix = (document.getElementById('session-date-prefix')?.textContent || '');
  const suffix = document.getElementById('session-create-input').value.trim();
  if (!suffix) return;
  const name = prefix + suffix;
  fetch('/api/session/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name})
  }).catch(e => console.error('createSession failed:', e));
}

function updateCreateBtn() {
  const name = document.getElementById('session-create-input').value.trim();
  const btn = document.getElementById('btn-create-session');
  if (btn) btn.disabled = !name;
}


function copyAndDismissPaste(el) {
  const uuid = el.dataset.uuid;
  const pasteId = el.dataset.pasteId;
  const participant = participantDataById[uuid];
  const entry = (participant?.paste_texts || []).find(e => String(e.id) === pasteId);
  if (entry) {
    navigator.clipboard.writeText(entry.text).then(() => {
      // Show "Copied!" tooltip
      const tip = document.createElement('span');
      tip.textContent = 'Copied!';
      tip.className = 'paste-copied-tip';
      const rect = el.getBoundingClientRect();
      tip.style.left = rect.left + rect.width / 2 + 'px';
      tip.style.top = rect.top - 4 + 'px';
      document.body.appendChild(tip);
      setTimeout(() => tip.remove(), 1200);
      // Fade out icon
      el.style.transition = 'opacity .3s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    });
  }
}

function downloadUploadedFile(el) {
  const uploadId = parseInt(el.dataset.uploadId, 10);
  // Fetch with credentials (Basic Auth) then trigger browser download
  fetch(API(`/upload/${uploadId}`), { credentials: 'same-origin' })
    .then(resp => {
      if (!resp.ok) throw new Error('Download failed');
      const cd = resp.headers.get('content-disposition') || '';
      const match = cd.match(/filename="?([^";\n]+)"?/);
      const filename = match ? match[1] : 'file';
      return resp.blob().then(blob => ({ blob, filename }));
    })
    .then(({ blob, filename }) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      // Show "Downloaded!" tip
      const tip = document.createElement('span');
      tip.textContent = 'Downloaded!';
      tip.className = 'paste-copied-tip';
      const rect = el.getBoundingClientRect();
      tip.style.left = rect.left + rect.width / 2 + 'px';
      tip.style.top = rect.top - 4 + 'px';
      document.body.appendChild(tip);
      setTimeout(() => tip.remove(), 1200);
    })
    .catch(() => {
      const tip = document.createElement('span');
      tip.textContent = 'Failed!';
      tip.className = 'paste-copied-tip';
      tip.style.background = '#ef4444';
      const rect = el.getBoundingClientRect();
      tip.style.left = rect.left + rect.width / 2 + 'px';
      tip.style.top = rect.top - 4 + 'px';
      document.body.appendChild(tip);
      setTimeout(() => tip.remove(), 1200);
    });
}


// ── Host inactivity auto-return (all modes) ──
// After 3 min idle during an activity → show warning modal with 3-min countdown
// Any mouse/key activity resets the full 6-min timer
// After 6 min total idle → switchTab('none')

const INACTIVITY_WARN_MS  = 3 * 60 * 1000;  // 3 minutes → show modal
const INACTIVITY_TOTAL_MS = 6 * 60 * 1000;  // 6 minutes → auto-switch

let _inactivityWarnTimer   = null;
let _inactivitySwitchTimer = null;
let _inactivityModalVisible = false;
let _inactivityCountdownInterval = null;

function _showInactivityModal() {
  _inactivityModalVisible = true;
  const modal = document.getElementById('inactivity-modal');
  if (modal) modal.style.display = 'flex';
  _startModalCountdown();
}

function _hideInactivityModal() {
  _inactivityModalVisible = false;
  const modal = document.getElementById('inactivity-modal');
  if (modal) modal.style.display = 'none';
  clearInterval(_inactivityCountdownInterval);
  _inactivityCountdownInterval = null;
}

function _startModalCountdown() {
  const timerEl = document.getElementById('inactivity-timer');
  let remaining = INACTIVITY_WARN_MS; // 3 minutes in ms
  const tick = () => {
    const m = Math.floor(remaining / 60000);
    const s = Math.floor((remaining % 60000) / 1000);
    if (timerEl) timerEl.textContent = `${m}:${s.toString().padStart(2, '0')}`;
    remaining -= 1000;
    if (remaining < 0) remaining = 0;
  };
  tick();
  _inactivityCountdownInterval = setInterval(tick, 1000);
}

function _resetInactivityTimer() {
  // Called on any user activity
  clearTimeout(_inactivityWarnTimer);
  clearTimeout(_inactivitySwitchTimer);
  if (_inactivityModalVisible) _hideInactivityModal();

  if (_currentActivity === 'none') return; // not tracking when on Slides

  // Restart full 6-min cycle
  _inactivityWarnTimer = setTimeout(_showInactivityModal, INACTIVITY_WARN_MS);
  _inactivitySwitchTimer = setTimeout(() => {
    _hideInactivityModal();
    switchTab('none');
  }, INACTIVITY_TOTAL_MS);
}

function startInactivityTracking() {
  ['mousemove', 'click', 'keydown'].forEach(evt =>
    document.addEventListener(evt, _resetInactivityTimer, { passive: true })
  );
  _resetInactivityTimer(); // arm the timers immediately
}

function stopInactivityTracking() {
  clearTimeout(_inactivityWarnTimer);
  clearTimeout(_inactivitySwitchTimer);
  _hideInactivityModal();
  ['mousemove', 'click', 'keydown'].forEach(evt =>
    document.removeEventListener(evt, _resetInactivityTimer)
  );
}

startInactivityTracking();
