  const SESSION_ID = location.pathname.split('/')[2];
  // Use absolute URL with location.origin so fetch() doesn't inherit
  // basic-auth credentials from the page URL (Chrome refuses to fetch
  // a URL with embedded credentials).
  const API = (path) => `${location.origin}/api/${SESSION_ID}/host${path}`;

  const UPLOAD_CLEANUP_MINUTES = 5; // hide download icon + delete file after this many minutes
  let ws = null;
  let currentQuiz = null;
  let quizActive = false;
  let voteCounts = [];
  let totalVotes = 0;
  let totalParticipants = 0;
  let activeParticipants = 0;
  let participantDataById = {};     // uuid -> participant payload
  let participantDebateSides = {};  // uuid -> "for"|"against"|undefined
  let _debateActive = false;
  let correctOptIds = new Set(); // host-marked correct options for current quiz
  let scores = {};               // uuid -> score
  let cachedParticipantIds = []; // last known participant uuids
  let summaryPoints = [];
  let summaryUpdatedAt = null;
  let daemonLastSeen = null;
  let daemonSessionFolder = null;
  let daemonSessionType = 'workshop';
  let _slidesCacheStatus = {};
  let _slidesCatalog = [];
  let _currentSessionId = null;
  let _joinBaseUrl = null;   // set from state.join_base_url (daemon config URL)
  let _slidesCatalogHideTimer = null;
  let _slidesLog = [];
  let _daemonLogLevel = 'info';
  let _logLevelBusy = false;
  const _ZERO_WIDTH_RE = /[\u200B-\u200D\uFEFF]/g;

  let _hostWcDebounceTimer = null;
  let _hostWcLastDataKey = null;
  let currentMode = 'workshop';
  const versionReloadGuard = window.createVersionReloadGuard
    ? window.createVersionReloadGuard({ countdownSeconds: 5 })
    : null;
  window.__versionReloadGuard = versionReloadGuard;
  const WC_COLORS = ['#7ecef4','#a78bfa','#34d399','#fbbf24','#f472b6','#60a5fa','#fb923c'];

  // ── Quiz history (persisted in localStorage, keyed by today's date) ──
  const TODAY_KEY = `host_quizzes_${new Date().toISOString().slice(0, 10)}`;
  const _FOOTER_BADGE_TOOLTIP_DEFAULTS = {
    'ws-badge': 'Railway',
    'gdrive-badge': 'Google Drive status',
    'summary-badge': 'Key points summary',
    'log-level-badge': 'Daemon log level (click to toggle)',
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

  function updateParticipantCountDisplay(participants) {
    const total = (participants || []).length;
    const active = (participants || []).filter((p) => p && p.online === true).length;
    const el = document.getElementById('pax-count');
    if (!el) return;
    el.innerHTML = `<span class="pax-active-count">${active}</span><span class="pax-count-sep">/</span><span class="pax-total-count">${total}</span>`;
  }

  function _extractTimezone(loc) {
    const match = String(loc || '').match(/^🕐\s+(.+)$/);
    return match ? match[1].trim() : '';
  }

  function _formatClockForTimezone(tz) {
    if (!tz) return '';
    try {
      const now = new Date();
      const hh = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', hour12: false, timeZone: tz }).format(now);
      const mm = new Intl.DateTimeFormat('en-GB', { minute: '2-digit', timeZone: tz }).format(now);
      return `<span style="font-family:monospace">${hh}<sup>${mm.padStart(2, '0')}</sup></span>`;
    } catch {
      return '';
    }
  }

  function _rawHhmmForTimezone(tz) {
    if (!tz) return '';
    try {
      return new Intl.DateTimeFormat('en-GB', {
        hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz,
      }).format(new Date());
    } catch {
      return '';
    }
  }

  function _offHoursClass(hhmm) {
    const m = String(hhmm || '').match(/^(\d{2}):(\d{2})$/);
    if (!m) return null;
    const totalMin = Number(m[1]) * 60 + Number(m[2]);
    // Night: 20:00–07:00
    if (totalMin >= 20 * 60 || totalMin < 7 * 60) return 'night';
    // Lunch: 12:00–13:00
    if (totalMin >= 12 * 60 && totalMin < 13 * 60) return 'lunch';
    // Twilight: 07:00–08:30 or 17:30–20:00
    if (totalMin < 8 * 60 + 30 || totalMin >= 17 * 60 + 30) return 'twilight';
    return null;
  }

  function _countryCodeToFlag(countryCode) {
    const cc = String(countryCode || '').trim().toUpperCase();
    if (!/^[A-Z]{2}$/.test(cc)) return '';
    return String.fromCodePoint(...cc.split('').map((ch) => 127397 + ch.charCodeAt(0)));
  }

  function _countryCodeToName(cc) {
    try { return new Intl.DisplayNames(['en'], { type: 'region' }).of(cc); } catch { return cc; }
  }

  function _formatParticipantLocation(participant) {
    const rawLoc = participant?.location || '';
    const tz = String(participant?.location_tz || _extractTimezone(rawLoc) || '').trim();
    const cc = String(participant?.location_country || '').trim().toUpperCase();
    if (!rawLoc && !tz && !cc) return '';
    const flagHtml = cc ? `<span title="${escHtml(_countryCodeToName(cc))}" style="cursor:default">${_countryCodeToFlag(cc)}</span>` : '';
    if (tz) {
      const hhmm = _formatClockForTimezone(tz);
      if (hhmm && flagHtml) return `${flagHtml} ⏱️${hhmm}`;
      if (hhmm) return `⏱️${hhmm}`;
      return escHtml(rawLoc);
    }
    if (flagHtml) return `${escHtml(rawLoc)} ${flagHtml}`;
    return escHtml(rawLoc);
  }

  function loadQuizHistory() {
    try { return JSON.parse(localStorage.getItem(TODAY_KEY) || '[]'); } catch { return []; }
  }

  function saveQuizHistory(history) {
    localStorage.setItem(TODAY_KEY, JSON.stringify(history));
  }

  function recordQuizInHistory(quiz, correctIds) {
    if (!quiz) return;
    const history = loadQuizHistory();
    const entry = {
      question: quiz.question,
      options: quiz.options.map((text, idx) => ({
        text,
        correct: correctIds.has(idx),
      })),
      multi: !!quiz.multi,
      recorded_at: new Date().toISOString(),
    };
    // Avoid duplicates by question
    const idx = history.findIndex(e => e.question === quiz.question);
    if (idx >= 0) history[idx] = entry; else history.push(entry);
    saveQuizHistory(history);
  }

  function downloadQuizHistory() {
    const history = loadQuizHistory();
    if (!history.length) { toast('No quizzes recorded today'); return; }
    const lines = history.map((e, n) => {
      const opts = e.options.map((o, i) => `  ${String.fromCharCode(65+i)}. ${o.text}${o.correct ? ' ✅' : ''}`).join('\n');
      return `${n+1}. ${e.question}\n${opts}`;
    }).join('\n\n');
    const blob = new Blob([lines], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `quizzes_${new Date().toISOString().slice(0, 10)}.txt`;
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
    if (!currentQuiz) return;
    if (correctOptIds.has(optId)) {
      correctOptIds.delete(optId);
    } else {
      if (!currentQuiz.multi && correctOptIds.size > 0) correctOptIds.clear(); // single-select: only one correct
      const cap = currentQuiz.correct_count;
      if (cap && correctOptIds.size >= cap) return; // multi-select: cap at correct_count
      correctOptIds.add(optId);
    }
    saveCorrectOpts(currentQuiz.question);
    renderBars();
    recordQuizInHistory(currentQuiz, correctOptIds);
    // Post to backend to award points
    const resp = await fetch(API('/quiz/correct'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ correct_indices: [...correctOptIds] }),
    });
    if (!resp.ok) toast('Failed to save correct options');
  }

  // Set participant link
  const pLink = document.getElementById('participant-link');
  _initFooterBadgeTooltips();
  if (pLink) {
    pLink.innerHTML = _currentSessionId ? _buildUrlHtml({ stripProtocol: true }) : '';
    if (_currentSessionId) {
      pLink.title = 'Click to copy • Ctrl/Cmd+Click to open';
    } else {
      pLink.removeAttribute('title');
    }
    pLink.addEventListener('click', onFooterJoinLinkClick);
  }
  _setupSlidesCatalogHover();
  _setupStopSessionHover();
  _setupActivityLogHovers();
  refreshLogLevelBadge();

  // ── WebSocket (host monitors state too) ──
  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/${SESSION_ID}/__host__`);

    let _kicked = false;
    ws.onopen = () => {
      setBadge(true);
      refreshLogLevelBadge();
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
      if (window._otelExtractWsTrace) window._otelExtractWsTrace(msg);
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
      if (Array.isArray(msg.participants)) _captureEngagement(msg.participants);
      if (msg.type === 'reload') {
        console.log('[static-sync] Reload requested by daemon');
        setTimeout(() => { window.location.reload(); }, 500);
        return;
      }
      if (msg.type === 'redirect') {
        window.location.href = msg.url;
        return;
      }
      if (msg.type === 'quiz_queue_updated') {
        if (_currentActivity === 'quiz') fetchQuizState();
        return;
      }
      if (msg.type === 'quiz_opened') {
        currentQuiz = msg.quiz || currentQuiz;
        // Clear any timer state from the *previous* quiz. Without this, the
        // stale activeTimer from a timer-closed prior quiz causes
        // renderQuizDisplay() below to start a new countdown that fires
        // endQuiz() immediately, ending the just-opened quiz.
        _clearTimer();
        quizActive = true;
        voteCounts = [];
        totalVotes = 0;
        updateCenterPanel('quiz');
        renderQuizDisplay();
        return;
      }
      if (msg.type === 'quiz_ended') {
        _clearTimer();
        quizActive = false;
        renderQuizDisplay();
        if (_currentActivity === 'quiz') fetchQuizState();
        return;
      }
      if (msg.type === 'quiz_correct_revealed') {
        correctOptIds = new Set(msg.correct_indices || []);
        if (currentQuiz) {
          saveCorrectOpts(currentQuiz.question);
          recordQuizInHistory(currentQuiz, correctOptIds);
        }
        renderBars();
        return;
      }
      if (msg.type === 'quiz_cleared') {
        currentQuiz = null;
        quizActive = false;
        _clearTimer();
        voteCounts = [];
        totalVotes = 0;
        correctOptIds = new Set();
        renderQuizDisplay();
        return;
      }
      if (msg.type === 'quiz_end_countdown_started') {
        _applyTimer(msg.seconds, msg.started_at);
        _startHostCountdown();
        return;
      }
      if (msg.type === 'scores_updated') {
        const updated = msg.scores || {};
        const flashPids = new Set(Object.keys(updated).filter(pid => (updated[pid] || 0) > (scores[pid] || 0)));
        Object.assign(scores, updated);
        renderParticipantList(cachedParticipantIds, flashPids);
        updateLeaderboardButton();
        return;
      }
      if (msg.type === 'state') {
        versionReloadGuard && versionReloadGuard.check(msg.backend_version);
        // Only refresh quiz state when the host is (or is being switched to)
        // the quiz tab — avoids two GET /quiz on every state snapshot.
        if (msg.current_activity === 'quiz') fetchQuizState();
        if (msg.current_activity === 'poll') fetchPollState();
        _debateActive = msg.current_activity === 'debate' && !!msg.debate_phase;
        ingestParticipants(msg.participants || []);
        totalParticipants = (msg.participants || []).length;
        activeParticipants = (msg.participants || []).filter(p => p && p.online === true).length;
        updateParticipantCountDisplay(msg.participants || []);
        updatePaxBadge(msg.participant_count);
        renderParticipantList(cachedParticipantIds);
        updateLeaderboardButton();
        applyEmojiMasterBadge(msg.emoji_global_enabled !== false);
        applyAttentionMasterBadge(msg.attention_enabled === true);
        document.getElementById('restore-banner').style.display =
          (msg.needs_restore && !msg.daemon_connected) ? '' : 'none';
        if (msg.slides_log_deep_count !== undefined || msg.slides_log_topic !== undefined) {
          const count = msg.slides_log_deep_count ?? 0;
          document.getElementById('slides-log-count').textContent = count;
        }
        if (msg.slides_log !== undefined) _slidesLog = msg.slides_log;
        renderTranscriptStatus(msg.transcript_line_count, msg.transcript_total_lines, msg.transcript_latest_ts, msg.transcript_last_content_at);
        if (msg.railway_connected !== undefined) {
          _railwayConnected = msg.railway_connected;
          setBadge(true);
        }
        renderGdriveStatus(msg.gdrive_running);
        renderPendingDeploy(msg.pending_deploy);
        daemonSessionFolder = msg.daemon_session_folder || null;
        if (msg.session_type !== undefined) daemonSessionType = msg.session_type || 'workshop';
        const currentActivity = msg.current_activity || 'none';
        updateCenterPanel(currentActivity);
        renderDebateHost(msg);
        if (currentActivity === 'wordcloud') {
          renderHostWordCloud(msg.wordcloud_words || {});
        }
        if (currentActivity === 'qa') {
          renderQAList(normalizeHostQAQuestions(msg.qa_questions || []));
        }
        if (currentActivity === 'codereview' && msg.codereview) {
          renderHostCodeReview(msg.codereview);
        }
        if (msg.daemon_last_seen !== undefined) daemonLastSeen = msg.daemon_last_seen;
        if (msg.join_base_url) _joinBaseUrl = msg.join_base_url;
        if (!msg.session_id && msg.needs_restore === false && !SESSION_ID) {
          window.location = '/host';
          return;
        }
        updateSessionCodeBar(msg.session_id || null);
        renderSessionPanel();
        if (msg.mode) {
          currentMode = msg.mode;
          renderMode(msg.mode);
        }
        if (msg.talk_presentation_name) {
          _setTalkPptxLabel(msg.talk_presentation_name, !!msg.talk_presentation_slug);
        }
        if (msg.summary_updated_at) summaryUpdatedAt = msg.summary_updated_at;
        if (msg.summary_count) updateSummaryLineCount(msg.summary_count);
      } else if (msg.type === 'summary_updated') {
        updateSummaryLineCount(msg.count);
      } else if (msg.type === 'summary') {
        updateSummary(msg.points, msg.updated_at);
      } else if (msg.type === 'talk_pdf_ready') {
        _setTalkPptxLabel(document.getElementById('talk-pptx-label')?.textContent?.replace(/^▶ /, '') || '', true);
      } else if (msg.type === 'talk_pdf_failed') {
        toast('Impossible to export PDF');
      } else if (msg.type === 'decks_updated') {
        _refreshHostSlidesCatalog();
      } else if (msg.type === 'vote_update') {
        totalVotes = msg.voted_count || 0;
        renderBars();
      } else if (msg.type === 'poll_host_update') {
        // Server is the authority for started + counts; mirror into composer state.
        if (msg.poll) {
          pollState.question = msg.poll.question;
          pollState.options = [...msg.poll.options, ''];   // trailing empty draft
          pollState.multi = msg.poll.multi;
          pollState.public = msg.poll.public;
        } else {
          // Cleared on the server — reset this tab's composer too.
          pollState.question = '';
          pollState.options = [''];
          pollState.multi = false;
          pollState.public = true;
        }
        _hostPollCountsState = msg.counts || [];
        _hostPollStarted = !!msg.started;
        _hostPollEnded = !!msg.ended;
        renderPoll();
      } else if (msg.type === 'poll_opened') {
        // Bare signal — snapshot follows via poll_host_update.
        fetchPollState();
      } else if (msg.type === 'participant_list_updated') {
        ingestParticipants(msg.participants || []);
        totalParticipants = (msg.participants || []).length;
        activeParticipants = (msg.participants || []).filter(p => p && p.online === true).length;
        updateParticipantCountDisplay(msg.participants || []);
        updatePaxBadge(totalParticipants);
        renderParticipantList(cachedParticipantIds);
        if (quizActive && currentQuiz) renderBars();
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
      } else if (msg.type === 'emoji_reaction') {
        showHostEmoji(msg.emoji);
      } else if (msg.type === 'bell_rung') {
        // Dual-render: the overlay shows the persistent card; the host browser
        // gets a light transient nudge too.
        showHostEmoji('🔔');
        toast(`🔔 ${msg.caller || 'Someone'} is calling you`);
      } else if (msg.type === 'paste_received') {
        const pid = msg.uuid;
        if (pid) {
          if (!participantDataById[pid]) {
            participantDataById[pid] = { uuid: pid, name: 'Unknown', score: 0 };
          }
          const entries = Array.isArray(participantDataById[pid].paste_texts)
            ? participantDataById[pid].paste_texts
            : [];
          const alreadyPresent = entries.some((e) => String(e.id) === String(msg.id));
          if (!alreadyPresent) {
            entries.push({ id: msg.id, text: msg.text || '' });
            participantDataById[pid].paste_texts = entries;
          }
          if (!cachedParticipantIds.includes(pid)) {
            cachedParticipantIds.push(pid);
          }
          renderParticipantList(cachedParticipantIds);
        }
      } else if (msg.type === 'file_uploaded') {
        const pid = msg.uuid;
        if (pid) {
          if (!participantDataById[pid]) {
            participantDataById[pid] = { uuid: pid, name: 'Unknown', score: 0 };
          }
          const existing = Array.isArray(participantDataById[pid].received_files)
            ? participantDataById[pid].received_files
            : [];
          const alreadyPresent = existing.some(e => String(e.id) === String(msg.id));
          if (!alreadyPresent) {
            existing.push({ id: String(msg.id), filename: msg.filename, disk_path: msg.disk_path });
            participantDataById[pid].received_files = existing;
          }
          if (!cachedParticipantIds.includes(pid)) {
            cachedParticipantIds.push(pid);
          }
          renderParticipantList(cachedParticipantIds);
        }
      } else if (msg.type === 'qa_updated') {
        renderQAList(normalizeHostQAQuestions(msg.questions || []));
      }
  }

  function normalizeHostQAQuestions(questions) {
    return (questions || []).map((q) => {
      const upvoteCount = (q.upvote_count !== undefined && q.upvote_count !== null)
        ? q.upvote_count
        : Array.isArray(q.upvoter_uuids)
          ? q.upvoter_uuids.length
          : Array.isArray(q.upvoters)
            ? q.upvoters.length
            : 0;
      return {
        ...q,
        author: q.author || q.author_name || 'Unknown',
        upvote_count: upvoteCount,
      };
    });
  }

  function showHostEmoji(emoji) {
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

  // escHtml is now in utils.js

  function normalizeSlideDisplayName(name, slug) {
    const cleanedName = String(name || '').replace(_ZERO_WIDTH_RE, '').trim();
    const cleanedSlug = String(slug || '').replace(_ZERO_WIDTH_RE, '').trim();
    if (cleanedName && /[\p{L}\p{N}]/u.test(cleanedName)) return cleanedName;
    if (cleanedSlug && /[\p{L}\p{N}]/u.test(cleanedSlug)) return cleanedSlug;
    return 'Unnamed slide';
  }

  function renderSummarySessionWindows() {
    const el = document.getElementById('summary-session-windows');
    if (!el) return;
    el.textContent = '';
    el.style.display = 'none';
    el.title = '';
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
    const keyPointCount = summaryPoints.length || _summaryLineCount || 0;
    if (keyPointCount > 0) {
      badge.textContent = `🧠 ${keyPointCount}`;
      badge.className = 'badge connected';
      badge.style.cssText = 'cursor:pointer;';
      _setFooterBadgeTooltip(
        badge,
        noTranscriptTitle || `Key points from ${timeLabel || 'session'} — click to view`,
      );
    } else {
      badge.textContent = '🧠';
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
    if (!overlay) return;
    const opening = !overlay.classList.contains('open');
    overlay.classList.toggle('open');
    if (opening) {
      fetch(API('/summary'))
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data) updateSummary(data.points, data.updated_at); })
        .catch(() => {});
    }
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
  let _railwayConnected = null;  // null = unknown (before first state message)

  function setBadge(wsOk) {
    const b = document.getElementById('ws-badge');
    let cls, tip;
    if (!wsOk) {
      cls = 'disconnected';
      tip = 'Daemon unreachable';
    } else if (_railwayConnected === false) {
      cls = 'warning';
      tip = 'Railway offline';
    } else {
      cls = 'connected';
      tip = 'Railway';
    }
    b.textContent = '🟢';
    b.className = `badge ${cls}`;
    _setFooterBadgeTooltip(b, tip);
    if (wsOk) {
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

  function applyEmojiMasterBadge(enabled) {
    const b = document.getElementById('emoji-master-badge');
    if (!b) return;
    b.className = `badge ${enabled ? 'connected' : 'disabled'} footer-tooltip-target`;
    _setFooterBadgeTooltip(b, enabled
      ? 'Emoji reactions ON — click to disable'
      : 'Emoji reactions OFF — click to enable');
  }

  async function toggleEmojiGlobal() {
    try {
      const r = await fetch(API('/emoji/global-toggle'), { method: 'POST' });
      const { emoji_global_enabled } = await r.json();
      applyEmojiMasterBadge(emoji_global_enabled);
    } catch (e) {
      console.error('emoji global toggle failed', e);
    }
  }

  // ── Attention master switch (bell + host notifications) ──────────────────
  function applyAttentionMasterBadge(enabled) {
    const b = document.getElementById('attention-master-badge');
    if (b) {
      b.className = `badge ${enabled ? 'connected' : 'disabled'} footer-tooltip-target`;
      _setFooterBadgeTooltip(b, enabled
        ? 'Attention ON — participants can ring the bell & receive notifications (click to disable)'
        : 'Attention OFF — click to enable the bell & host notifications');
    }
    // The "notify all participants" affordance only exists while attention is on.
    const wrap = document.getElementById('attention-notify-wrap');
    if (wrap) {
      wrap.style.display = enabled ? '' : 'none';
      if (!enabled) {
        const pop = document.getElementById('attention-notify-popover');
        if (pop) pop.style.display = 'none';
      }
    }
  }

  async function toggleAttentionGlobal() {
    try {
      const r = await fetch(API('/attention/global-toggle'), { method: 'POST' });
      const { attention_enabled } = await r.json();
      applyAttentionMasterBadge(attention_enabled);
    } catch (e) {
      console.error('attention global toggle failed', e);
    }
  }

  function toggleAttentionNotifyPopover(ev) {
    if (ev) ev.stopPropagation();
    const pop = document.getElementById('attention-notify-popover');
    if (!pop) return;
    const showing = pop.style.display !== 'none';
    pop.style.display = showing ? 'none' : 'block';
    if (!showing) {
      const inp = document.getElementById('attention-notify-input');
      if (inp) { inp.focus(); _syncAttentionNotifyBtn(); }
    }
  }

  function _syncAttentionNotifyBtn() {
    const inp = document.getElementById('attention-notify-input');
    const btn = document.getElementById('attention-notify-btn');
    if (inp && btn) btn.disabled = !inp.value.trim();
  }

  async function sendHostNotification() {
    const inp = document.getElementById('attention-notify-input');
    if (!inp) return;
    const text = inp.value.trim();
    if (!text) return;
    try {
      const r = await fetch(API('/attention/notify'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
      });
      if (!r.ok) throw new Error(r.status);
      inp.value = '';
      _syncAttentionNotifyBtn();
      const pop = document.getElementById('attention-notify-popover');
      if (pop) pop.style.display = 'none';
    } catch (e) {
      console.error('host notification send failed', e);
    }
  }

  function renderLogLevelBadge() {
    const badge = document.getElementById('log-level-badge');
    if (!badge) return;
    const level = (_daemonLogLevel === 'debug') ? 'debug' : 'info';
    badge.textContent = level.toUpperCase();
    badge.classList.remove('log-level-info', 'log-level-debug', 'log-level-pending');
    badge.classList.add(level === 'debug' ? 'log-level-debug' : 'log-level-info');
    if (level === 'info') {
      badge.style.color = '#9aa0b5';
      badge.style.borderColor = '#9aa0b5';
      badge.style.background = '#9aa0b522';
      badge.style.boxShadow = 'none';
      badge.style.animation = 'none';
    } else {
      badge.style.color = '#ff6b6b';
      badge.style.borderColor = '#ff6b6b';
      badge.style.background = '#ff6b6b22';
      badge.style.boxShadow = '0 0 12px rgba(255, 45, 45, 0.35)';
      badge.style.animation = 'log-debug-blink 1.8s ease-in-out infinite';
    }
    if (_logLevelBusy) badge.classList.add('log-level-pending');
    const verb = level === 'debug' ? 'high-volume debug logging is ON' : 'normal logging (info)';
    _setFooterBadgeTooltip(badge, `Daemon log level: ${level}\nClick to switch to ${level === 'debug' ? 'info' : 'debug'}\n${verb}`);
  }

  async function refreshLogLevelBadge() {
    try {
      const resp = await fetch('/api/log-level');
      if (!resp.ok) return;
      const data = await resp.json();
      const level = String(data.level || '').toLowerCase();
      if (level === 'info' || level === 'debug') _daemonLogLevel = level;
    } catch (_) {}
    renderLogLevelBadge();
  }

  async function toggleLogLevel() {
    if (_logLevelBusy) return;
    _logLevelBusy = true;
    renderLogLevelBadge();
    const target = _daemonLogLevel === 'debug' ? 'info' : 'debug';
    try {
      const resp = await fetch('/api/log-level', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level: target }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      _daemonLogLevel = target;
    } catch (err) {
      console.warn('Failed to change daemon log level', err);
      toast('Failed to change daemon log level');
    } finally {
      _logLevelBusy = false;
      renderLogLevelBadge();
    }
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
    const totalMin = Math.floor(s / 60);
    if (totalMin < 60) { const r = s % 60; return r > 0 ? totalMin + 'm ' + r + 's' : totalMin + 'm'; }
    const h = Math.floor(totalMin / 60), m = totalMin % 60;
    return m > 0 ? h + 'h ' + m + 'm' : h + 'h';
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

// ===== Participant engagement badge =====
var _engagementByPid = {};
var _engagementTotal = 0;
var ENGAGEMENT_FRESH_MS = 75000;  // 30s flush + 60s idle slack
var ENGAGEMENT_VIEW_LABELS = {
  slides: 'Slides', notes: 'Notes', summary: 'Summary', files: 'Files',
  agenda: 'Agenda', activity: 'Activity', 'upload-paste': 'Upload', feedback: 'Feedback'
};

function _captureEngagement(participants) {
  var map = {};
  for (var i = 0; i < participants.length; i++) {
    var p = participants[i];
    if (!p || !p.uuid) continue;
    map[p.uuid] = {
      engagement: p.engagement || {},
      last_active_at: p.last_active_at || 0,
      last_view: p.last_view || ''
    };
  }
  _engagementByPid = map;
  _engagementTotal = participants.length;
  renderEngagementBadge();
}

function _engagementAggregate() {
  var now = Date.now();
  var activeByView = {};
  var totals = {};
  var activeCount = 0;
  for (var pid in _engagementByPid) {
    var rec = _engagementByPid[pid];
    if (rec.last_active_at && (now - rec.last_active_at) < ENGAGEMENT_FRESH_MS) {
      activeCount++;
      if (rec.last_view) activeByView[rec.last_view] = (activeByView[rec.last_view] || 0) + 1;
    }
    var eng = rec.engagement || {};
    for (var v in eng) {
      var d = eng[v];
      if (!totals[v]) totals[v] = { seconds: 0, visits: 0, clicks: 0 };
      totals[v].seconds += d.seconds || 0;
      totals[v].visits += d.visits || 0;
      totals[v].clicks += d.clicks || 0;
    }
  }
  return { activeByView: activeByView, totals: totals, activeCount: activeCount };
}

function renderEngagementBadge() {
  var badge = document.getElementById('engagement-badge');
  var countEl = document.getElementById('engagement-count');
  if (!badge || !countEl) return;
  var agg = _engagementAggregate();
  if (agg.activeCount > 0) {
    countEl.textContent = agg.activeCount;
    badge.className = 'badge connected footer-tooltip-target';
    _setFooterBadgeTooltip(badge, agg.activeCount + ' of ' + _engagementTotal + ' active now');
  } else {
    countEl.textContent = '';
    badge.className = 'badge empty footer-tooltip-target';
    _setFooterBadgeTooltip(badge, 'No active participants');
  }
}

function _renderEngagementPopover() {
  var el = document.getElementById('engagement-content');
  if (!el) return;
  var agg = _engagementAggregate();
  var views = Object.keys(agg.totals).sort(function(a, b) {
    return agg.totals[b].seconds - agg.totals[a].seconds;
  });
  var html = '<div class="slides-catalog-line" style="opacity:.85;font-weight:600;">'
    + '<span>Live: ' + agg.activeCount + ' of ' + _engagementTotal + ' active now</span></div>';
  if (!views.length) {
    html += '<div style="padding:6px;opacity:0.5">No activity yet</div>';
  } else {
    for (var i = 0; i < views.length; i++) {
      var v = views[i], t = agg.totals[v];
      var label = ENGAGEMENT_VIEW_LABELS[v] || v;
      var liveOnView = agg.activeByView[v] ? ' · ' + agg.activeByView[v] + ' now' : '';
      html += '<div class="slides-catalog-line">'
        + '<span class="slides-cache-title truncate">' + escHtml(label) + liveOnView + '</span>'
        + '<span class="slides-cache-label" style="color:var(--muted)">' + t.visits + 'v · ' + t.clicks + 'c</span>'
        + '<span class="slides-cache-detail">' + _fmtSecs(t.seconds) + '</span>'
        + '</div>';
    }
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
    _makeHover('slides-log-hover', 'slides-log-popover', _renderSlidesLogPopover);
  _makeHover('engagement-hover', 'engagement-popover', _renderEngagementPopover);
  setInterval(renderEngagementBadge, 2000);
  renderEngagementBadge();
  }

  function renderMode(mode) {
    applyConferenceLayout(mode === 'talk');
  }

  function applyConferenceLayout(isConference) {
    const rightCol = document.querySelector('.host-col-right');
    const grid = document.querySelector('.host-columns');
    const confQR = document.getElementById('conference-qr');
    const debateTab = document.getElementById('tab-debate');
    const centerQR = document.getElementById('center-qr');
    const slidesLeftQR = document.getElementById('slides-left-qr');
    const leftTabsWrapper = document.querySelector('.left-tabs-wrapper');

    // Detect light/dark mode for QR color adaptation
    const isLight = window.matchMedia('(prefers-color-scheme: light)').matches;

    const pptxDrop = document.getElementById('talk-pptx-drop');
    const leftCol = document.querySelector('.host-col-left');
    if (isConference) {
      rightCol.style.display = 'none';
      grid.style.gridTemplateColumns = '25% 1fr';
      leftCol.classList.add('conference-layout');
      if (leftTabsWrapper) leftTabsWrapper.style.display = 'none';
      if (slidesLeftQR) slidesLeftQR.style.display = 'flex';
      if (pptxDrop) pptxDrop.style.display = 'inline-flex';
      confQR.style.display = 'none';
      if (debateTab) debateTab.style.display = 'none';
      // Make center QR bright for conference
      if (centerQR) centerQR.classList.add('conference-center-qr');
      // Regenerate all QR codes with session-scoped join URL
      requestAnimationFrame(() => _regenerateAllQRCodes());
    } else {
      rightCol.style.display = '';
      grid.style.gridTemplateColumns = '25% 1fr 250px';
      leftCol.classList.remove('conference-layout');
      if (leftTabsWrapper) leftTabsWrapper.style.display = _currentActivity === 'none' ? 'none' : 'flex';
      if (slidesLeftQR) slidesLeftQR.style.display = _currentActivity === 'none' ? 'flex' : 'none';
      if (pptxDrop) pptxDrop.style.display = 'none';
      confQR.style.display = 'none';
      if (debateTab) debateTab.style.display = '';
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


  function renderGdriveStatus(running) {
    const el = document.getElementById('gdrive-badge');
    if (!el) return;
    el.className = `badge ${running ? 'connected' : 'disconnected'}`;
    _setFooterBadgeTooltip(
      el,
      running ? 'Google Drive is running' : 'Google Drive is NOT running',
    );
  }

  function renderPendingDeploy(pendingDeploy) {
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

  let _summaryLineCount = 0;

  function updateSummaryLineCount(count) {
    _summaryLineCount = count || 0;
    renderSummaryBadge();
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

  function renderParticipantList(participantIds, flashPids) {
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
      const locLabel = _formatParticipantLocation(participant) || null;
      const tzForColor = String(participant?.location_tz || _extractTimezone(loc) || '').trim();
      const hhmmForColor = tzForColor ? _rawHhmmForTimezone(tzForColor) : '';
      const _ohc = _offHoursClass(hhmmForColor);
      const locClass = _ohc ? `pax-location offhours ${_ohc}` : 'pax-location';
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
      const online = participant.online === true;
      const pasteTexts = participant.paste_texts || [];
      const pasteIcons = pasteTexts.map((entry, i) => {
        const preview = (entry.text.length > 100 ? entry.text.substring(0, 100) + '…' : entry.text).replace(/\n/g, ' ');
        return `<span class="paste-icon" title="${escHtml(preview)}" data-uuid="${escHtml(pid)}" data-paste-id="${entry.id}" onclick="copyAndDismissPaste(this)"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5.5" y="5.5" width="9" height="9" rx="2"/><path d="M3 10.5H2.5a1.5 1.5 0 0 1-1.5-1.5V2.5A1.5 1.5 0 0 1 2.5 1h6.5A1.5 1.5 0 0 1 11 2.5V3"/></svg></span>`;
      }).join('');
      const receivedFiles = participant.received_files || [];
      const uploadIcons = receivedFiles.map(entry => {
        const copiedClass = (entry.copied || entry.seen_by_host) ? ' downloaded' : '';
        return `<span class="upload-icon${copiedClass}" title="${escHtml(entry.disk_path)}" data-uuid="${escHtml(pid)}" data-file-id="${escHtml(String(entry.id))}" onclick="copyDiskPath(this)"><svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 4v9"/><path d="M6 9.5L10 13.5L14 9.5"/><path d="M4.5 13.5v1a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-1"/></svg></span>`;
      }).join('');
      return `<li class="${online ? 'online' : 'offline'}" data-uuid="${escHtml(pid)}"><span class="pax-name" title="${ip ? 'IP: ' + ip : ''}">${debateIcon}${avatarHtml}<span class="pax-name-text truncate">${escHtml(name)}</span>${pasteIcons}${uploadIcons}</span>${scoreTag}${locLabel ? `<span class="${locClass}">${locLabel}</span>` : ''}</li>`;
    }).join('');

    if (flashPids && flashPids.size > 0) {
      flashPids.forEach(pid => {
        const li = ul.querySelector(`li[data-uuid="${pid}"]`);
        if (li) { li.classList.remove('score-flash'); void li.offsetWidth; li.classList.add('score-flash'); }
      });
    }
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
      const qrFullSize = Math.max(120, Math.floor(Math.min(availW, availH * 0.82)));
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
      renderFullscreenQR();
    }
  }

  // Header QR icon: open fullscreen join QR overlay
  const topQrIcon = document.getElementById('top-qr-icon');
  if (topQrIcon) {
    topQrIcon.addEventListener('click', (event) => {
      event.preventDefault();
      openQR();
    });
    topQrIcon.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openQR();
      }
    });
  }

  const mapIcon = document.getElementById('map-icon');
  if (mapIcon) {
    mapIcon.addEventListener('click', (event) => {
      event.preventDefault();
      openMap();
    });
    mapIcon.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openMap();
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

  let _qrResizeRaf = null;
  window.addEventListener('resize', () => {
    if (_qrResizeRaf) cancelAnimationFrame(_qrResizeRaf);
    _qrResizeRaf = requestAnimationFrame(() => {
      _positionQROverlayBetweenHeaderAndFooter();
      _regenerateAllQRCodes();
      _qrResizeRaf = null;
    });
  });


  // ── Quiz composer (contenteditable) ──
  const quizInput = document.getElementById('quiz-input');
  let selectedQueueIndex = null;   // index of queue item currently loaded into textarea
  let selectedQueueItem = null;    // full {question, options, correct_indices} of selected item

  // Read plain text lines from contenteditable div
  function getLines() {
    // innerText gives newline-separated lines reliably
    return (quizInput.innerText || '').split('\n');
  }

  function parseQuizInput() {
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
    const children = Array.from(quizInput.children);
    if (children.length === 0) return;

    let questionSeen = false;

    children.forEach(el => {
      const text = el.textContent.trim();
      if (!text) { el.className = 'blank-line'; return; }
      if (!questionSeen) { el.className = 'q-line'; questionSeen = true; }
      else el.className = 'opt-line';
    });

    const { question, options } = parseQuizInput();
    const sendBtn = document.getElementById('create-btn');
    if (sendBtn) sendBtn.disabled = !(question && options.length >= 2);
  }

  // Init with default content using divs (contenteditable line model)
  function initComposer(text) {
    const lines = text.split('\n');
    quizInput.innerHTML = lines.map(l => `<div>${l || '<br>'}</div>`).join('');
    reclassifyLines();
  }

  const RANDOM_QUIZZES = [
    'What does `List<String>` represent in Java?\n\nA generic list of `String` elements\nA raw array of strings\nA `Map<String,String>` alias\nA primitive type',
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
  let _testOneQuizClicks = 0;

  initComposer('Which is the primary benefit of the Circuit Breaker pattern?\n\nPrevents cascading failures across services\nImproves response time under normal load\nReduces the number of network calls\nEnables automatic service discovery');

  window.testOneQuiz = () => {
    let idx;
    if (_testOneQuizClicks === 0) {
      idx = 0;
    } else {
      do { idx = Math.floor(Math.random() * RANDOM_QUIZZES.length); } while (idx === _lastRandomIndex && RANDOM_QUIZZES.length > 1);
    }
    _testOneQuizClicks++;
    _lastRandomIndex = idx;
    initComposer(RANDOM_QUIZZES[idx]);
    const cc = document.getElementById('correct-count');
    cc.value = 1; cc.readOnly = false;
  };

  quizInput.addEventListener('input', () => {
    reclassifyLines();
  });

  // Intercept paste: always insert as plain text to avoid rich-HTML corruption
  quizInput.addEventListener('paste', e => {
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text/plain');
    // Insert at current cursor position using execCommand (works in all browsers for contenteditable)
    document.execCommand('insertText', false, text);
  });

  quizInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      document.getElementById('create-btn').click();
    }
  });

  // ── Create quiz ──
  document.getElementById('create-btn').addEventListener('click', async () => {
    const { question, options } = parseQuizInput();

    if (!question) { toast('Enter a question'); return; }
    if (options.length < 2) { toast('Add at least 2 options'); return; }

    const correctCountEl = document.getElementById('correct-count');
    const correct_count_val = parseInt(correctCountEl.value) || 1;
    const multi = correct_count_val > 1;
    const correct_count = multi ? correct_count_val : null;
    let res;
    try {
      res = await fetch(API('/quiz/manual/submit'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, options, multi, correct_count }),
      });
    } catch (e) {
      toast('Network error — daemon unreachable');
      return;
    }
    if (res.ok) {
      localStorage.removeItem('host_correct_' + question);
      localStorage.removeItem('host_llm_hints_' + question);
      correctOptIds = new Set();
      toast('Quiz created & opened ✓');
      if (selectedQueueIndex !== null) {
        if (selectedQueueItem?.correct_indices?.length)
          localStorage.setItem('host_queue_hints_' + question, JSON.stringify(selectedQueueItem.correct_indices));
        const deleteRes = await fetch(API(`/quiz/queue/${selectedQueueIndex}`), { method: 'DELETE' });
        if (!deleteRes.ok) toast('Queue item delete failed — queue may be out of sync');
        selectedQueueIndex = null;
        selectedQueueItem = null;
      }
      _resetBackstage();
    } else {
      const data = await res.json().catch(() => ({}));
      toast(data.detail || data.error || 'Error');
    }
  });

  function _resetBackstage() {
    quizInput.innerHTML = '<div><br></div>';
    reclassifyLines();
    const cc = document.getElementById('correct-count');
    if (cc) { cc.value = 1; cc.readOnly = false; }
  }

  window.clearBackstage = function() {
    selectedQueueIndex = null;
    selectedQueueItem = null;
    _resetBackstage();
    const list = document.getElementById('queue-list');
    if (list) list.querySelectorAll('li').forEach(li => { li.classList.remove('selected'); });
  };

  // ── Poll composer ──
  const POLL_PRESETS = {
    yesno:      { question: 'Had Coffee?', options: ['Yes', 'No'], multi: false },
    truefalse:  { question: '', options: ['True', 'False'], multi: false },
    rating15:   { question: '', options: ['1', '2', '3', '4', '5'], multi: false },
    hardness:   { question: 'How hard was it?',
                  options: ['1 Very easy', '2 OK', '3 Hard', '4 Extra hard', "5 I'm dead"], multi: false },
    energy:     { question: "How's the room feeling right now?",
                  options: ['🔥 Fire', '😐 OK', '😴 Sleepy', '💀 Need coffee'], multi: false },
  };

  // ── Poll option sort toggle (host-only presentation, persisted) ──
  const POLL_SORT_KEY = 'host_poll_sort_by_votes';
  function _loadPollSortByVotes() {
    const v = localStorage.getItem(POLL_SORT_KEY);
    return v === null ? true : v === '1';   // default: sort by votes
  }
  let _hostPollSortByVotes = _loadPollSortByVotes();

  const pollState = {
    question: '',
    options: [''],
    multi: false,
    public: true,
  };

  // Live state — set by /api/{sid}/host/poll fetch + poll_host_update WS pushes.
  let _hostPollStarted = false;
  let _hostPollEnded = false;      // true after Stop, until Clear: counts frozen, edits locked
  let _hostPollCountsState = [];   // per-option vote counts; aligned to pollState.options

  const pollQuestionEl  = document.getElementById('poll-question');
  const pollMultiEl     = document.getElementById('poll-multi');
  const pollPublicEl    = document.getElementById('poll-public');
  const pollStartBtn    = document.getElementById('poll-start-btn');
  const pollStopBtn     = document.getElementById('poll-stop-btn');
  const pollClearBtn    = document.getElementById('poll-clear-btn');
  const pollOptionsEl   = document.getElementById('poll-options-container');
  const pollQuickBtns   = document.querySelectorAll('.poll-quick-btn');

  function autoGrow(el) {
    el.style.height = 'auto';
    el.style.height = el.scrollHeight + 'px';
  }

  function _createPollCard(val, i) {
    const card = document.createElement('div');
    card.className = 'poll-option-card' + (_hostPollStarted ? ' started' : '');
    card.dataset.optIdx = String(i);

    const rowWrap = document.createElement('div');
    rowWrap.className = 'poll-option-card-rowwrap';

    const fill = document.createElement('div');
    fill.className = 'poll-option-card-fill';

    const row = document.createElement('textarea');
    row.className = 'poll-option-row' + (val.trim() ? ' filled' : '');
    row.rows = 1;
    row.value = val;
    row.tabIndex = 2 + i;
    row.placeholder = i === pollState.options.length - 1 ? 'Add option…' : '';
    row.addEventListener('input', () => onPollOptionInput(i, row));
    row.addEventListener('keydown', _onPollKeyDown);

    // Vote count overlay — vertically centered on the row, anchored to
    // the right edge of the colored fill via the `--fill-pct` CSS var.
    const count = document.createElement('span');
    count.className = 'poll-option-card-count';
    count.textContent = '';

    rowWrap.appendChild(fill);
    rowWrap.appendChild(row);
    rowWrap.appendChild(count);
    card.appendChild(rowWrap);
    return card;
  }

  function renderPoll() {
    pollQuestionEl.value = pollState.question;
    autoGrow(pollQuestionEl);
    pollQuestionEl.classList.toggle('filled', pollState.question.trim() !== '');
    pollMultiEl.checked = pollState.multi;
    pollPublicEl.checked = pollState.public;

    const desired = pollState.options.length;

    // Surgically add/remove cards by data-opt-idx — cards may have been
    // reordered for vote-count sorting, so removing "lastChild" would drop
    // the wrong card. Remove anything whose index is out of range, then
    // add any missing index.
    Array.from(pollOptionsEl.children).forEach(c => {
      if (Number(c.dataset.optIdx) >= desired) pollOptionsEl.removeChild(c);
    });
    for (let idx = 0; idx < desired; idx++) {
      if (!pollOptionsEl.querySelector(`[data-opt-idx="${idx}"]`)) {
        pollOptionsEl.appendChild(_createPollCard(pollState.options[idx], idx));
      }
    }
    pollState.options.forEach((val, i) => {
      const card = pollOptionsEl.querySelector(`[data-opt-idx="${i}"]`);
      if (!card) return;
      const row = card.querySelector('.poll-option-row');
      if (row && row.value !== val && document.activeElement !== row) {
        row.value = val;
        autoGrow(row);
        row.classList.toggle('filled', val.trim() !== '');
      }
      if (row) {
        row.placeholder = i === desired - 1 ? 'Add option…' : '';
        // Lock option text input once the poll is running or stopped-with-results.
        row.readOnly = _hostPollStarted || _hostPollEnded;
      }
      card.classList.toggle('started', _hostPollStarted || _hostPollEnded);
      card.classList.toggle('ended', _hostPollEnded);
    });

    pollQuestionEl.readOnly = _hostPollStarted || _hostPollEnded;
    pollMultiEl.disabled = _hostPollStarted || _hostPollEnded;
    pollPublicEl.disabled = _hostPollStarted || _hostPollEnded;

    pollStartBtn.tabIndex = 2 + desired;
    updatePollStartEnabled();
    applyPollLiveResults();
  }

  function applyPollLiveResults() {
    const counts = _hostPollCountsState;
    // Show counts while live OR after Stop (until Clear) so the host keeps
    // seeing the final tally. Only a fresh/draft poll wipes them.
    if (!_hostPollStarted && !_hostPollEnded) {
      pollOptionsEl.querySelectorAll('.poll-option-card').forEach(c => {
        c.classList.remove('started', 'has-votes');
        const countEl = c.querySelector('.poll-option-card-count');
        countEl.textContent = '';
        countEl.style.removeProperty('--fill-pct');
        c.querySelector('.poll-option-card-fill').style.width = '0%';
      });
      return;
    }
    const draftIdx = pollState.options.length - 1;
    const maxCount = counts.length ? Math.max(...counts, 0) : 0;
    pollState.options.forEach((val, i) => {
      const card = pollOptionsEl.querySelector(`[data-opt-idx="${i}"]`);
      if (!card) return;
      card.classList.add('started');
      const isTrailingDraft = (i === draftIdx && val.trim() === '');
      const c = counts[i] ?? 0;
      const hasVotes = !isTrailingDraft && c > 0;
      card.classList.toggle('has-votes', hasVotes);
      const pct = (hasVotes && maxCount > 0) ? (c / maxCount) * 100 : 0;
      card.querySelector('.poll-option-card-fill').style.width = pct + '%';
      const countEl = card.querySelector('.poll-option-card-count');
      countEl.textContent = hasVotes ? String(c) : '';
      countEl.style.setProperty('--fill-pct', pct + '%');
    });
    reorderPollCards();
  }

  function reorderPollCards() {
    const draftIdx = pollState.options.length - 1;
    // When sort-by-votes is OFF, restore insertion order (data-opt-idx
    // ascending) so options stay where the host typed them. Otherwise,
    // build realIdxs from CURRENT DOM order, then sort by count desc with
    // JS's stable sort. Ties preserve the existing position, so an option
    // only moves when its count strictly exceeds (or falls below) a
    // neighbor's — never on a tie.
    let realIdxs;
    if (_hostPollSortByVotes) {
      realIdxs = Array.from(pollOptionsEl.children)
        .map(c => Number(c.dataset.optIdx))
        .filter(i => !(i === draftIdx && pollState.options[i] === ''));
      realIdxs.sort((a, b) => (_hostPollCountsState[b] ?? 0) - (_hostPollCountsState[a] ?? 0));
    } else {
      realIdxs = pollState.options
        .map((_, i) => i)
        .filter(i => !(i === draftIdx && pollState.options[i] === ''));
    }
    const desiredOrder = realIdxs.slice();
    if (pollState.options[draftIdx] === '') desiredOrder.push(draftIdx);

    const current = Array.from(pollOptionsEl.children);
    const currentOrder = current.map(c => Number(c.dataset.optIdx));
    const sameOrder = currentOrder.length === desiredOrder.length &&
      currentOrder.every((idx, i) => idx === desiredOrder[i]);

    // appendChild on a card whose textarea is focused causes Chrome to
    // drop focus (textarea is nested two levels deep), so we must avoid
    // no-op moves. When a real reorder is needed, capture focus and
    // restore after the appendChild loop.
    if (!sameOrder) {
      const focusEl = document.activeElement;
      const wasInRow = focusEl && focusEl.classList && focusEl.classList.contains('poll-option-row');
      const savedSelStart = wasInRow ? focusEl.selectionStart : null;
      const savedSelEnd = wasInRow ? focusEl.selectionEnd : null;

      const first = new Map();
      current.forEach(c => first.set(c, c.getBoundingClientRect()));

      desiredOrder.forEach(idx => {
        const card = pollOptionsEl.querySelector(`[data-opt-idx="${idx}"]`);
        if (card) pollOptionsEl.appendChild(card);
      });

      if (wasInRow && document.activeElement !== focusEl) {
        focusEl.focus();
        if (savedSelStart !== null) focusEl.setSelectionRange(savedSelStart, savedSelEnd);
      }

      // FLIP
      current.forEach(c => {
        const last = c.getBoundingClientRect();
        const f = first.get(c);
        const dy = f.top - last.top;
        if (dy !== 0) {
          c.style.transition = 'none';
          c.style.transform = `translateY(${dy}px)`;
        }
      });
      requestAnimationFrame(() => {
        current.forEach(c => { c.style.transition = ''; c.style.transform = ''; });
      });
    }

    // Sync tab order to current DOM order so Tab follows the visible
    // top-to-bottom layout — question → first visible option → ... → Start.
    Array.from(pollOptionsEl.children).forEach((c, pos) => {
      const row = c.querySelector('.poll-option-row');
      if (row) row.tabIndex = 2 + pos;
    });
  }

  function updatePollStartEnabled() {
    pollStartBtn.textContent = 'Start';
    pollQuickBtns.forEach(b => { b.disabled = _hostPollStarted || _hostPollEnded; });
    pollStopBtn.disabled = !_hostPollStarted;
    if (_hostPollStarted || _hostPollEnded) {
      // While running, Stop is the only valid action. Once stopped, Clear is.
      pollStartBtn.disabled = true;
      return;
    }
    const validQ = pollState.question.trim() !== '';
    const nonEmpty = pollState.options.filter(s => s.trim() !== '').length;
    pollStartBtn.disabled = !(validQ && nonEmpty >= 2);
  }

  function applyPollPreset(name) {
    const preset = POLL_PRESETS[name];
    if (!preset) return;
    if (preset.question) pollState.question = preset.question;   // empty question → preserve existing
    pollState.options = [...preset.options, ''];   // trailing empty draft row
    pollState.multi = preset.multi;
    renderPoll();
    pollQuestionEl.focus();
    pollQuestionEl.select();
    flushPollUpdate();  // immediate, no debounce
  }

  function resetPollLocal() {
    pollState.question = '';
    pollState.options = [''];
    pollState.multi = false;
    pollState.public = false;
    renderPoll();
  }

  let _pollUpdateTimer = null;

  function pollPayload() {
    // Strip ONLY the trailing draft row (last entry if empty). Middle empties
    // are intentional — preserved both before-start (server stores them) and
    // after-start (sent to participants as empty voteable buttons).
    let opts = pollState.options.map(s => s.trim());
    if (opts.length > 0 && opts[opts.length - 1] === '') {
      opts = opts.slice(0, -1);
    }
    return {
      question: pollState.question,
      options: opts,
      multi: pollState.multi,
      public: pollState.public,
    };
  }

  async function sendPollUpdate() {
    try {
      await fetch(API('/poll/update'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pollPayload()),
      });
    } catch (e) {
      // Daemon may be momentarily unreachable; the next edit will retry.
    }
  }

  async function flushPollUpdate() {
    if (_pollUpdateTimer) { clearTimeout(_pollUpdateTimer); _pollUpdateTimer = null; }
    await sendPollUpdate();
  }

  function schedulePollUpdate() {
    if (_pollUpdateTimer) clearTimeout(_pollUpdateTimer);
    _pollUpdateTimer = setTimeout(() => { _pollUpdateTimer = null; sendPollUpdate(); }, 300);
  }

  function onPollOptionInput(i, row) {
    pollState.options[i] = row.value;
    row.classList.toggle('filled', row.value.trim() !== '');
    autoGrow(row);
    // Auto-spawn trailing draft row when the user types into the last (previously empty) row.
    const isLast = i === pollState.options.length - 1;
    if (isLast && row.value !== '') {
      pollState.options.push('');
      renderPoll();
      // After re-render, focus the row the user was typing in (data-opt-idx=i)
      const focusRow = pollOptionsEl.querySelector(`[data-opt-idx="${i}"] .poll-option-row`);
      if (focusRow) {
        focusRow.focus();
        const len = focusRow.value.length;
        focusRow.setSelectionRange(len, len);
      }
      flushPollUpdate();   // structural change → immediate
      return;
    }
    // Pre-start only: collapse trailing empties when the user clears the last
    // filled option. e.g. [F1, F2, F3, '' (draft)] → clear F3 → [F1, F2, '']
    // where the cleared row becomes the new draft.
    if (!_hostPollStarted && row.value === '' && i < pollState.options.length - 1) {
      const allTailEmpty = pollState.options.slice(i + 1).every(s => s.trim() === '');
      if (allTailEmpty) {
        pollState.options = pollState.options.slice(0, i + 1);
        while (pollOptionsEl.children.length > pollState.options.length) {
          pollOptionsEl.removeChild(pollOptionsEl.lastChild);
        }
        row.placeholder = 'Add option…';
      }
    }
    updatePollStartEnabled();
    schedulePollUpdate(); // text-only change → debounced
  }

  // Enter starts the poll (Shift+Enter is also blocked — no multi-line
  // content in question or options).
  function _onPollKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (!pollStartBtn.disabled) pollStartBtn.click();
    }
  }

  pollQuestionEl.addEventListener('input', () => {
    pollState.question = pollQuestionEl.value;
    autoGrow(pollQuestionEl);
    pollQuestionEl.classList.toggle('filled', pollQuestionEl.value.trim() !== '');
    updatePollStartEnabled();
    schedulePollUpdate();
  });
  pollQuestionEl.addEventListener('keydown', _onPollKeyDown);

  pollMultiEl.addEventListener('change', () => {
    pollState.multi = pollMultiEl.checked;
    flushPollUpdate();   // toggle is structural → immediate
  });

  pollPublicEl.addEventListener('change', () => {
    pollState.public = pollPublicEl.checked;
    flushPollUpdate();   // toggle is structural → immediate
  });

  const pollSortToggleEl   = document.getElementById('poll-sort-toggle');
  const pollSortEmojiEl    = document.getElementById('poll-sort-toggle-emoji');
  function _refreshPollSortToggleUI() {
    pollSortToggleEl.checked = _hostPollSortByVotes;
    pollSortEmojiEl.textContent = _hostPollSortByVotes ? '↕️' : '⬇️';
  }
  _refreshPollSortToggleUI();
  pollSortToggleEl.addEventListener('change', () => {
    _hostPollSortByVotes = pollSortToggleEl.checked;
    localStorage.setItem(POLL_SORT_KEY, _hostPollSortByVotes ? '1' : '0');
    _refreshPollSortToggleUI();
    reorderPollCards();   // host-only presentation → no server update
  });

  pollStartBtn.addEventListener('click', async () => {
    if (pollStartBtn.disabled) return;
    await flushPollUpdate();   // await so daemon has the latest draft before /start
    let res;
    try {
      res = await fetch(API('/poll/start'), { method: 'POST' });
    } catch (e) {
      toast('Network error — daemon unreachable');
      return;
    }
    if (res.ok) {
      _hostPollStarted = true;
      _hostPollEnded = false;
      _hostPollCountsState = pollState.options.map(() => 0);
      applyPollLiveResults();
      updatePollStartEnabled();
      toast('Poll started ✓');
    } else {
      const data = await res.json().catch(() => ({}));
      toast(data.error || 'Poll start failed');
    }
  });

  pollStopBtn.addEventListener('click', async () => {
    if (pollStopBtn.disabled) return;
    // Cancel any pending debounced update — we're about to stop the live run.
    if (_pollUpdateTimer) { clearTimeout(_pollUpdateTimer); _pollUpdateTimer = null; }
    // Optimistic local flip: live → ended. Counts are preserved; the WS
    // push from the daemon will reconcile any drift.
    _hostPollStarted = false;
    _hostPollEnded = true;
    renderPoll();
    try {
      await fetch(API('/poll/stop'), { method: 'POST' });
    } catch (e) {
      toast('Network error — daemon unreachable');
    }
  });

  pollClearBtn.addEventListener('click', async () => {
    // Cancel any pending debounced update — we're about to wipe.
    if (_pollUpdateTimer) { clearTimeout(_pollUpdateTimer); _pollUpdateTimer = null; }
    _hostPollStarted = false;
    _hostPollEnded = false;
    _hostPollCountsState = [];
    resetPollLocal();
    pollQuestionEl.focus();
    pollQuestionEl.select();
    try {
      await fetch(API('/poll/clear'), { method: 'POST' });
    } catch (e) {
      toast('Network error — daemon unreachable');
    }
  });

  // Initial render
  renderPoll();

  // Tab order: Question → option rows → Start. Everything else stays mouse-only.
  pollQuestionEl.tabIndex = 1;
  pollMultiEl.tabIndex   = -1;
  pollPublicEl.tabIndex  = -1;
  pollSortToggleEl.tabIndex = -1;
  pollClearBtn.tabIndex  = -1;
  pollStopBtn.tabIndex   = -1;
  pollQuickBtns.forEach(b => b.tabIndex = -1);

  // Wire Quick Question buttons (prepend "*" to ones that overwrite the question)
  pollQuickBtns.forEach(btn => {
    const preset = POLL_PRESETS[btn.dataset.preset];
    if (preset && preset.question) btn.textContent = '* ' + btn.textContent;
    btn.addEventListener('click', () => applyPollPreset(btn.dataset.preset));
  });

  // ── Timer ──
  let activeTimer = null;   // {seconds, started_at (ms)} or null
  let _timerInterval = null;

  async function startTimer(seconds) {
    const res = await fetch(API('/quiz/end/timer'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seconds }),
    });
    if (!res.ok) { const e = await res.json(); toast(e.detail || 'Error'); }
  }

  function _applyTimer(seconds, startedAtIso) {
    activeTimer = { seconds, startedAt: new Date(startedAtIso).getTime() };
    renderQuizDisplay();
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
        endQuiz();
      }
    }, 200);
  }

  // ── End / clear ──
  async function endQuiz() {
    const res = await fetch(API('/quiz/end'), { method: 'POST' });
    if (res.ok) fetchQuizState();
  }

  async function clearQuiz() {
    await fetch(API('/quiz'), { method: 'DELETE' });
  }

  async function fetchPollState() {
    try {
      const resp = await fetch(API('/poll'));
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.poll) {
        _hostPollStarted = false;
        _hostPollEnded = false;
        _hostPollCountsState = [];
        return;
      }
      pollState.question = data.poll.question;
      pollState.options = [...data.poll.options, ''];
      pollState.multi = data.poll.multi;
      pollState.public = data.poll.public;
      _hostPollStarted = !!data.started;
      _hostPollEnded = !!data.ended;
      _hostPollCountsState = data.counts || [];
      renderPoll();
    } catch (e) { /* silent */ }
  }

  async function fetchQuizState() {
    const resp = await fetch(API('/quiz'));
    if (!resp.ok) return;
    const data = await resp.json();
    const prevQuestion = currentQuiz?.question;
    const prevQuizActive = quizActive;
    currentQuiz = data.id ? {
      id: data.id, question: data.question, options: data.options,
      multi: data.multi, correct_count: data.correct_count,
      end_timer_seconds: data.end_timer_seconds, end_timer_started_at: data.end_timer_started_at,
      correct_indices: data.correct_indices,
    } : null;
    if (!data.quiz_running && prevQuizActive) _clearTimer();
    quizActive = data.quiz_running;
    if (data.end_timer_seconds && data.end_timer_started_at) {
      _applyTimer(data.end_timer_seconds, data.end_timer_started_at);
    }
    if (currentQuiz && currentQuiz.question !== prevQuestion) loadCorrectOpts(currentQuiz.question);
    const n = currentQuiz?.options?.length || 0;
    voteCounts = Array(n).fill(0);
    const allVotes = Object.values(data.votes || {});
    for (const v of allVotes) for (const idx of v.option_indices) if (idx < n) voteCounts[idx]++;
    totalVotes = allVotes.length;
    renderQuizDisplay();
    renderQuizQueuePanel(data.queue);
  }

  // ── Render ──
  function renderQuizDisplay() {
    const el = document.getElementById('quiz-display');
    if (!currentQuiz) {
      el.innerHTML = `<p class="no-quiz">No quiz yet.</p>`;
      const pillsEl = document.getElementById('quiz-pills');
      if (pillsEl) pillsEl.innerHTML = '';
      return;
    }

    const statusLabel = quizActive ? 'open' : (totalVotes > 0 ? 'closed' : 'draft');
    const statusText  = quizActive ? 'Voting open' : (totalVotes > 0 ? 'Voting closed' : 'Not started');

    const canMark = !quizActive && totalVotes > 0;
    const llmHints = canMark ? getLlmHints(currentQuiz.question) : null;
    const queueHints = canMark ? getQueueHints(currentQuiz.question) : null;
    const bars = currentQuiz.options.map((text, idx) => {
      const count = voteCounts[idx] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const maxCount = Math.max(...voteCounts, 0);
      const leading = count === maxCount && count > 0 ? 'leading' : '';
      const isCorrect = canMark && correctOptIds.has(idx);
      const correct = isCorrect ? 'correct' : '';
      const llmHint = llmHints && llmHints.includes(idx) && !isCorrect;
      const queueHint = queueHints && queueHints.includes(idx) && !isCorrect;
      const clickable = canMark ? `onclick="toggleCorrect(${idx})" title="Click to mark as correct"` : '';
      return `
        <div class="result-row ${correct} ${canMark ? 'markable' : ''}" data-id="${idx}" ${clickable}>
          <div class="result-label">
            <span>${escHtmlWithCode(text)}${isCorrect ? ' ✅' : ''}${queueHint ? ' <span class="queue-hint-check">✅</span>' : ''}${llmHint ? ' <span class="llm-hint" title="AI suggestion">✅ 🤔</span>' : ''}</span>
            <span class="pct">${count}</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill ${leading}" style="width:${pct}%"></div>
          </div>
        </div>`;
    }).join('');

    const timerBtns = quizActive && !activeTimer
      ? `<span class="timer-slider-wrap">
           <span id="timer-val" class="timer-val">15s</span>
           <input type="range" id="timer-slider" class="timer-slider" min="5" max="30" value="15"
             oninput="document.getElementById('timer-val').textContent=this.value+'s'"
             onmouseup="startTimer(+this.value)" ontouchend="startTimer(+this.value)" />
           <span class="timer-tip">Release to start countdown</span>
         </span>`
      : '';

    const modePillHtml = currentQuiz.multi
      ? `<span class="mode-pill mode-pill-multi">${currentQuiz.correct_count || ''} correct</span>`.replace(/  +/g, ' ')
      : `<span class="mode-pill">◉ Single-select</span>`;

    const pillsEl = document.getElementById('quiz-pills');
    if (pillsEl) pillsEl.innerHTML = '';

    el.className = quizActive ? 'voting-active' : '';

    const votePct = activeParticipants > 0 ? Math.round((totalVotes / activeParticipants) * 100) : 0;
    const voteProgressSection = quizActive ? `
      <div class="vote-progress-overlay">
        <div class="vote-progress-fill" id="vote-progress-fill" style="width:${votePct}%"></div>
        <span class="vote-progress-label" id="vote-progress-label">${totalVotes} of ${activeParticipants} voted</span>
      </div>
` : '';

    const mainContent = quizActive
      ? `<div class="options-plain">${currentQuiz.options.map(text =>
          `<div class="option-text-only">${escHtmlWithCode(text)}</div>`).join('')}</div>
         ${voteProgressSection}`
      : `<div class="bars-container"><div class="bars-wrapper">${bars}</div></div>
         <p style="font-size:.8rem; color:var(--muted); margin-top:.5rem;">${totalVotes} total vote${totalVotes!==1?'s':''}`;

    el.innerHTML = `
      <p class="quiz-question">${escHtmlWithCode(currentQuiz.question)}</p>
      ${mainContent}${quizActive ? '' : '</p>'}
      ${currentQuiz.source ? `<p class="quiz-source-ref">📖 ${escHtml(currentQuiz.source)}${currentQuiz.page ? `, p. ${escHtml(currentQuiz.page)}` : ''}</p>` : ''}
      <div class="btn-row quiz-controls" style="flex-wrap:nowrap;">
        ${modePillHtml}
        <span class="badge status-pill ${statusLabel}">${statusText}</span>
        ${quizActive && !activeTimer ? `<button class="btn btn-warn" onclick="endQuiz()">End</button>` : ''}
        ${quizActive && activeTimer ? `<div class="countdown-display" id="host-countdown"></div>` : ''}
        ${timerBtns}
        <button class="btn btn-danger" onclick="clearQuiz()" style="margin-left:auto;">Remove</button>
      </div>`;

    if (quizActive && activeTimer) _startHostCountdown();
  }

  function renderBars() {
    if (!currentQuiz) return;
    if (quizActive) {
      // During voting: update vote progress overlay only (results hidden)
      const fill = document.getElementById('vote-progress-fill');
      const label = document.getElementById('vote-progress-label');
      const pct = activeParticipants > 0 ? Math.round((totalVotes / activeParticipants) * 100) : 0;
      if (fill) fill.style.width = `${pct}%`;
      if (label) label.textContent = `${totalVotes} of ${activeParticipants} voted`;
      return;
    }
    const maxCount = Math.max(...voteCounts, 0);
    currentQuiz.options.forEach((text, idx) => {
      const row = document.querySelector(`.result-row[data-id="${idx}"]`);
      if (!row) return;
      const count = voteCounts[idx] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const fill = row.querySelector('.bar-fill');
      const pctEl = row.querySelector('.pct');
      const canMarkNow = !quizActive && totalVotes > 0;
      const isCorrect = canMarkNow && correctOptIds.has(idx);
      row.className = `result-row${isCorrect ? ' correct' : ''}${canMarkNow ? ' markable' : ''}`;
      const labelSpan = row.querySelector('.result-label span:first-child');
      if (labelSpan) {
        const hints = canMarkNow ? getLlmHints(currentQuiz.question) : null;
        const qHints = canMarkNow ? getQueueHints(currentQuiz.question) : null;
        const llmHint = hints && hints.includes(idx) && !isCorrect;
        const queueHint = qHints && qHints.includes(idx) && !isCorrect;
        labelSpan.innerHTML = escHtmlWithCode(text) + (isCorrect ? ' ✅' : '') +
          (queueHint ? ' <span class="queue-hint-check">✅</span>' : '') +
          (llmHint ? ' <span class="llm-hint" title="AI suggestion">✅ 🤔</span>' : '');
      }
      if (fill) {
        fill.style.width = `${pct}%`;
        fill.className = `bar-fill ${count === maxCount && count > 0 ? 'leading' : ''}`;
      }
      if (pctEl) pctEl.textContent = `${count}`;
    });
    const totalEl = document.querySelector('#quiz-display p[style]');
    if (totalEl) totalEl.textContent = `${totalVotes} total vote${totalVotes!==1?'s':''}`;
  }

  function getLlmHints(question) {
    try {
      return JSON.parse(localStorage.getItem('host_llm_hints_' + question) || 'null');
    } catch { return null; }
  }
  function getQueueHints(question) {
    try {
      return JSON.parse(localStorage.getItem('host_queue_hints_' + question) || 'null');
    } catch { return null; }
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

  // ── Quiz Queue ──────────────────────────────────────────────────────────────


  async function pushDummyQueue() {
    const questions = [
      {
        question: 'What is 2 + 2?',
        options: ['3', '4', '5', '6'],
        correct_indices: [1],
      },
      {
        question: 'Which of these are Java features?',
        options: ['Garbage Collection', 'Manual memory management', 'Object-oriented', 'Static typing'],
        correct_indices: [0, 2, 3],
      },
      {
        question: 'What does SOLID stand for?',
        options: ['Single Responsibility', 'Open/Closed', 'Liskov Substitution', 'Interface Segregation'],
        correct_indices: [0, 1, 2, 3],
      },
      {
        question: 'Which HTTP method is idempotent?',
        options: ['POST', 'PUT', 'PATCH', 'DELETE'],
        correct_indices: [1, 3],
      },
      {
        question: 'What is the time complexity of binary search?',
        options: ['O(1)', 'O(log n)', 'O(n)', 'O(n log n)'],
        correct_indices: [1],
      },
      {
        question: 'Which of these are creational design patterns?',
        options: ['Singleton', 'Observer', 'Factory', 'Decorator'],
        correct_indices: [0, 2],
      },
      {
        question: 'What does TDD stand for?',
        options: ['Test-Driven Development', 'Type-Driven Design', 'Test-Driven Design', 'Top-Down Development'],
        correct_indices: [0],
      },
      {
        question: 'Which of these are valid HTTP status codes for success?',
        options: ['200 OK', '201 Created', '301 Moved', '204 No Content'],
        correct_indices: [0, 1, 3],
      },
      {
        question: 'What is a pure function?',
        options: ['No side effects', 'Same output for same input', 'Uses global state', 'Always returns void'],
        correct_indices: [0, 1],
      },
      {
        question: 'Which SQL clause filters grouped results?',
        options: ['WHERE', 'HAVING', 'GROUP BY', 'ORDER BY'],
        correct_indices: [1],
      },
    ];
    const res = await fetch(API('/quiz/queue'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ questions }),
    });
    if (res.ok) {
      toast('Dummy queue pushed \u2713');
      await fetchQuizState();
    } else {
      const err = await res.json().catch(() => ({}));
      toast(err.detail || 'Failed to push queue');
    }
  }

  function renderQuizQueuePanel(queue) {
    const list = document.getElementById('queue-list');
    if (!list) return;
    const items = queue?.items || [];
    list.innerHTML = items.map((item, i) => {
      const multi = item.correct_indices.length > 1 ? ' <span style="color:#e55; font-size:.7rem;">#multi</span>' : '';
      return `<li data-idx="${i}" class="${i === selectedQueueIndex ? 'selected' : ''}">${escHtml(item.question)}${multi}<button class="queue-remove-btn" data-idx="${i}" aria-label="Remove from queue" title="Remove from queue">✕</button></li>`;
    }).join('');
    list.querySelectorAll('li').forEach(li => {
      li.addEventListener('click', (e) => {
        if (e.target.closest('.queue-remove-btn')) return;
        selectQueueItem(parseInt(li.dataset.idx), items);
      });
    });
    list.querySelectorAll('.queue-remove-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.idx);
        try {
          const res = await fetch(API(`/quiz/queue/${idx}`), { method: 'DELETE' });
          if (res.ok) {
            toast('Removed from queue ✓');
            if (selectedQueueIndex === idx) {
              selectedQueueIndex = -1;
              selectedQueueItem = null;
            } else if (selectedQueueIndex > idx) {
              selectedQueueIndex--;
            }
            await fetchQuizState();
          } else {
            toast('Queue remove failed');
          }
        } catch (err) {
          toast('Queue remove failed');
        }
      });
    });
  }

  function selectQueueItem(index, items) {
    const item = items[index];
    if (!item) return;
    selectedQueueIndex = index;
    selectedQueueItem = item;
    const text = item.question + '\n\n' + item.options.join('\n');
    initComposer(text);
    const cc = document.getElementById('correct-count');
    if (cc) { cc.value = item.correct_indices.length || 1; cc.readOnly = true; }
    const list = document.getElementById('queue-list');
    if (list) list.querySelectorAll('li').forEach((li, i) => {
      li.classList.toggle('selected', i === index);
    });
    quizInput.focus();
  }


  function toast(msg) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 2500);
  }


  async function switchTab(tab) {
    updateCenterPanel(tab);
    if (tab === 'quiz') fetchQuizState();
    await fetch(API('/activity'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ activity: tab }),
    });
    const focusTargets = {
      quiz: 'quiz-input',
      poll: 'poll-question',
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
    const centerQrPanel = document.getElementById('center-qr');
    if (centerQrPanel) centerQrPanel.classList.toggle('link-only', currentActivity === 'none');
    ['qr', 'quiz', 'poll', 'wordcloud', 'qa', 'debate', 'codereview'].forEach(id => {
      const el = document.getElementById('center-' + id);
      if (id === 'qr') {
        el.style.display = currentActivity === 'none' ? 'flex' : 'none';
      } else if (id === 'quiz') {
        // Show quiz panel only when quiz is the active participant activity.
        const show = currentActivity === 'quiz';
        el.style.display = show ? 'flex' : 'none';
        // Hide the quiz results section when no quiz is active.
        const quizResults = document.getElementById('quiz-results-section');
        if (quizResults) quizResults.style.display = currentActivity === 'quiz' ? '' : 'none';
        // Change divider text based on whether a quiz exists.
        const divider = el.querySelector('.or-divider span');
        if (divider) divider.textContent = currentActivity === 'quiz' ? 'generate next' : 'generate question';
      } else {
        const flexPanels = new Set(['codereview', 'poll']);
        const showVal = flexPanels.has(id) ? 'flex' : '';
        el.style.display = currentActivity === id ? showVal : 'none';
      }
    });
    // In conference mode: always show the left QR
    const leftCol = document.querySelector('.host-col-left');
    const leftTabsWrapper = document.querySelector('.left-tabs-wrapper');
    const slidesLeftQR = document.getElementById('slides-left-qr');
    const isConferenceLayout = !!(leftCol && leftCol.classList.contains('conference-layout'));
    if (leftTabsWrapper) {
      leftTabsWrapper.style.display = currentActivity === 'none' ? 'none' : 'flex';
    }
    if (slidesLeftQR) slidesLeftQR.style.display = currentActivity === 'none' ? 'flex' : 'none';
    // Sync slides tab active state
    const slidesTab = document.getElementById('tab-slides');
    if (slidesTab) slidesTab.classList.toggle('active', currentActivity === 'none');
    if (currentActivity && currentActivity !== 'none') {
      ['quiz', 'poll', 'wordcloud', 'qa', 'codereview', 'debate'].forEach(t => {
        document.getElementById('tab-' + t).classList.toggle('active', currentActivity === t);
        document.getElementById('tab-content-' + t).style.display = currentActivity === t ? (t === 'codereview' ? 'flex' : '') : 'none';
      });
    } else {
      // When activity is 'none', deactivate all other tabs
      ['quiz', 'poll', 'wordcloud', 'qa', 'codereview', 'debate'].forEach(t => {
        document.getElementById('tab-' + t).classList.remove('active');
        document.getElementById('tab-content-' + t).style.display = 'none';
      });
      requestAnimationFrame(() => _regenerateAllQRCodes());
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
      if (currentMode === 'talk') {
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
            showLeaderboardError('No scores yet — run a quiz first');
            return;
        }
        try {
            const res = await fetch(API('/leaderboard/show'), { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                renderLeaderboard(data);
            }
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
let _slidesCompileCloseHandler = null;

function toggleSlidesCompileConfirm(evt) {
  if (evt) evt.stopPropagation();
  const bubble = document.getElementById('slides-compile-confirm');
  const wrapper = document.getElementById('slides-log-hover');
  if (!bubble) return;
  const opening = bubble.style.display === 'none';
  // Always clean up any existing listener first
  if (_slidesCompileCloseHandler) {
    document.removeEventListener('click', _slidesCompileCloseHandler);
    _slidesCompileCloseHandler = null;
  }
  bubble.style.display = opening ? '' : 'none';
  if (wrapper) wrapper.classList.toggle('compile-confirm-open', opening);
  if (opening) {
    _slidesCompileCloseHandler = function(e) {
      if (!bubble.contains(e.target)) {
        bubble.style.display = 'none';
        if (wrapper) wrapper.classList.remove('compile-confirm-open');
        document.removeEventListener('click', _slidesCompileCloseHandler);
        _slidesCompileCloseHandler = null;
      }
    };
    setTimeout(() => document.addEventListener('click', _slidesCompileCloseHandler), 0);
  }
}
function triggerSlidesCompilationDownload() {
  document.getElementById('slides-compile-confirm').style.display = 'none';
  window.location = '/api/' + _currentSessionId + '/host/slides-compilation';
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
    if (sessionId) {
      pLink.innerHTML = _buildUrlHtml({ stripProtocol: true });
      pLink.title = 'Click to copy • Ctrl/Cmd+Click to open';
    } else {
      pLink.innerHTML = '';
      pLink.removeAttribute('title');
    }
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
  if (!_currentSessionId) return;
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

function _buildUrlHtml({ stripProtocol = false, plain = false } = {}) {
  const base = _joinBaseUrl || ('https://' + location.host);
  const displayBase = stripProtocol ? base.replace(/^https?:\/\//i, '') : base;
  const display = _currentSessionId ? `${displayBase}/${_currentSessionId}` : displayBase;
  if (plain) {
    return display
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
  const displayYellowFrom = _currentSessionId ? displayBase.length + 1 : display.length; // after the '/'
  return display.split('').map((ch, i) => {
    const yellow = i >= displayYellowFrom;
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
  // Slides left QR (workshop slides tab)
  const slidesLeftQRCode = document.getElementById('slides-left-qr-code');
  if (slidesLeftQRCode && slidesLeftQRCode.offsetParent !== null) {
    slidesLeftQRCode.innerHTML = '';
    const slidesQREl = document.getElementById('slides-left-qr');
    const availW = slidesQREl ? slidesQREl.clientWidth : 260;
    const availH = slidesQREl ? slidesQREl.clientHeight : 260;
    const qrSize = Math.max(1, Math.floor(Math.min(availW, availH)));
    if (slidesQREl) slidesQREl.style.position = 'absolute';
    if (slidesQREl) slidesQREl.style.inset = '0';
    slidesLeftQRCode.style.position = 'absolute';
    slidesLeftQRCode.style.left = '50%';
    slidesLeftQRCode.style.top = '50%';
    slidesLeftQRCode.style.transform = 'translate(-50%, -50%)';
    slidesLeftQRCode.style.width = qrSize + 'px';
    slidesLeftQRCode.style.height = qrSize + 'px';
    if (typeof QRCode !== 'undefined') new QRCode(slidesLeftQRCode, { text: joinUrl, width: qrSize, height: qrSize, colorDark: '#000', colorLight: '#fff' });
  }

  // Update URL labels with session path
  const confUrl = document.getElementById('conference-qr-url');
  if (confUrl && confUrl.offsetParent !== null) confUrl.innerHTML = _buildUrlHtml();
  const centerUrl = document.getElementById('center-qr-url');
  if (centerUrl) {
    const base = (_joinBaseUrl || location.origin).replace(/^https?:\/\//i, '');
    if (_currentSessionId) {
      centerUrl.innerHTML = `<span class="center-url-domain">${base}/</span><span class="center-url-code">${_currentSessionId}</span>`;
    } else {
      centerUrl.innerHTML = `<span class="center-url-domain">${base}</span>`;
    }
  }
}

function formatSessionTitle(name) {
  return (name || '').replace(/@/g, ' @ ').toUpperCase();
}

function formatHostTopTitleHtml(name) {
  const cleaned = String(name || '').replace(/^\d{4}-\d{2}-\d{2}[^\s]*\s*/, '');
  if (!cleaned.includes('@')) return _esc(cleaned);
  return _esc(cleaned).replace(/@/g, '<span class="host-top-title-at"> @ </span>');
}

function renderSessionPanel() {
  const daemonOnline = daemonLastSeen && (Date.now() - new Date(daemonLastSeen).getTime() < 30000);

  // FRAGILE: daemon connected but no session folder active
  const fragile = daemonOnline && !daemonSessionFolder;
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
    const typeEmoji = daemonSessionType === 'talk' ? '🎙️' : '👨‍🏫';
    const titleHtml = formatHostTopTitleHtml(daemonSessionFolder || '');
    titleEl.innerHTML = titleHtml ? `${typeEmoji} ${titleHtml}` : '';
  }

  // Stop button is always enabled (host can always request session end).
  const stopBtn = document.getElementById('stop-session-btn-left');
  if (stopBtn) {
    stopBtn.disabled = false;
    stopBtn.style.pointerEvents = '';
    stopBtn.classList.remove('disabled');
  }
}


async function createSession() {
  const prefix = (document.getElementById('session-date-prefix')?.textContent || '');
  const suffix = document.getElementById('session-create-input').value.trim();
  if (!suffix) return;
  const name = prefix + suffix;
  try {
    const resp = await fetch('/api/session/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, type: 'workshop'})
    });
    if (resp.status === 503) {
      const data = await resp.json().catch(() => ({}));
      if (data.error === 'gdrive_unavailable') {
        toast('Please start Google Drive');
        return;
      }
    }
  } catch (e) {
    console.error('createSession failed:', e);
  }
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

function copyDiskPath(el) {
  const uuid = el.dataset.uuid;
  const fileId = el.dataset.fileId;
  const participant = participantDataById[uuid];
  const entry = (participant?.received_files || []).find(e => String(e.id) === String(fileId));
  if (entry) {
    navigator.clipboard.writeText(entry.disk_path).then(() => {
      // Show copy confirmation tooltip
      const tip = document.createElement('span');
      tip.textContent = 'Path copied to clipboard';
      tip.className = 'paste-copied-tip';
      const rect = el.getBoundingClientRect();
      tip.style.left = rect.left + rect.width / 2 + 'px';
      tip.style.top = rect.top - 4 + 'px';
      document.body.appendChild(tip);
      setTimeout(() => tip.remove(), 1200);
      entry.copied = true;
      entry.seen_by_host = true;
      el.classList.add('downloaded');
      fetch(API('/uploads/seen'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uuid, file_id: String(fileId) }),
      }).catch(() => {
        toast('Path copied, but status sync failed');
      });
    });
  }
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

// ── Talk mode: PPTX file picker / drop zone ──
function _setTalkPptxLabel(name, slugReady) {
  const labelEl = document.getElementById('talk-pptx-label');
  if (!labelEl) return;
  labelEl.textContent = '▶ ' + name;
  const check = document.getElementById('talk-pptx-check');
  if (check) check.style.display = slugReady ? '' : 'none';
}

function onTalkPptxSelected(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';  // reset so same file can be re-selected
  _setTalkPptxLabel(file.name.replace(/\.pptx?$/i, ''), false);
  fetch('/api/session/talk-presentation-path', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: file.name}),
  }).then(r => {
    if (!r.ok) r.text().then(t => console.warn('talk-presentation-path failed:', r.status, t));
  });
}

startInactivityTracking();
