  const LS_KEY = 'workshop_participant_name';
  const LS_UUID_KEY = 'workshop_participant_uuid';
  const LS_VOTE_KEY = 'workshop_vote';

  // Host cookie (is_host=1) → sessionStorage (per-tab UUID for multi-tab testing)
  // Normal participants → localStorage (same UUID across tabs/reloads)
  const uuidStorage = document.cookie.includes('is_host=1') ? sessionStorage : localStorage;
  const _isFirstVisit = !uuidStorage.getItem(LS_UUID_KEY);

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
  let rejectedAvatars = []; // avatars the participant has seen and didn't want
  let myVote = null;      // string (single) or Set of option_ids (multi)
  let currentPoll = null;
  let pollActive = false;
  let pollResult = null;  // {correct_ids, voted_ids} once host marks correct options
  let activeTimer = null; // {seconds, startedAt (ms)} or null
  let _timerInterval = null;
  let _multiWarnShown = false; // true once warning has been shown for current poll
  let focusedOptionIndex = -1;  // keyboard navigation index for poll options
  const LS_WC_SESSION_KEY = 'workshop_wc_session';
  let _lastWordcloudWords = {};
  let _lastWordcloudWordOrder = [];
  let _lastWordcloudTopic = '';
  const WC_COLORS = ['#7ecef4','#a78bfa','#34d399','#fbbf24','#f472b6','#60a5fa','#fb923c'];
  let _wcDebounceTimer = null;
  let _wcLastDataKey = null;
  const versionReloadGuard = window.createVersionReloadGuard
    ? window.createVersionReloadGuard({ countdownSeconds: 5 })
    : null;
  window.__versionReloadGuard = versionReloadGuard;
  const _QA_TOASTS = [
    "💬 Ask a question — earn points!",
    "👍 Upvote a great question — both you and the author earn points!",
    "🏆 The more you engage, the higher you rank!",
    "🤔 Got a burning question? Type it in!",
    "⬆️ See a question you like? Give it an upvote!",
  ];
  const _CR_TOASTS = [
    "🐛 You got this!",
    "👀 Look closer...",
    "🔥 Keep going!",
    "💪 Trust your instincts!",
    "🎯 Nice eye!",
  ];
  const _DEBATE_TOASTS = [
    "⚔️ Defend your position — back it up with evidence!",
    "🎯 Focus on the strongest counterargument",
    "💡 Real-world examples win debates",
    "🧠 Listen to the other side — find the weak spot",
    "🗣️ Be persuasive, not aggressive",
    "🔍 What trade-off are they ignoring?",
    "💪 Stand your ground — your experience matters",
    "🤝 Acknowledge the valid points, then counter",
    "📊 Data beats opinions — use concrete examples",
    "🏆 The best argument wins, not the loudest voice",
  ];
  let _debateToastIndex = 0;
  let _debateToastInterval = null;
  let _debateToastTimeout = null;
  let _crToastIndex = 0;
  let _crToastInterval = null;
  let _crToastTimeout = null;
  let _qaToastIndex = 0;
  let _qaToastInterval = null;
  let _qaToastTimeout = null;
  let _prevPollActive = false;
  let _prevActivity = null;
  let _stateInitialised = false;   // skip notifications on first state (join mid-session)
  let currentMode = 'workshop';
  let _notifBtnBound = false;      // prevent re-binding on reconnect
  let summaryPoints = [];
  let summaryUpdatedAt = null;
  const SLIDES_REFRESH_MS = 30000;
  const LS_SLIDE_PAGE_PREFIX = 'workshop_slide_page:';
  const LS_SLIDE_VIEW_PREFIX = 'workshop_slide_view:';
  const SLIDES_TEST_AUTO_SCROLL_ENABLED = true;
  const SLIDES_TEST_AUTO_SCROLL_PAGE = 2;
  const SLIDES_TEST_AUTO_SCROLL_DELAY_MS = 3000;
  const SLIDES_DISABLE_VIEW_PERSISTENCE = true;
  let slidesCatalog = [];
  let slidesSelectedSlug = null;
  let slidesSelectedId = null;
  let slidesLastFingerprint = null;
  let slidesRefreshTimer = null;
  let slidesPdfModulesPromise = null;
  let slidesPdfLib = null;
  let slidesPdfViewerModule = null;
  let slidesPdfViewer = null;
  let slidesPdfLinkService = null;
  let slidesPdfEventBus = null;
  let slidesPdfDoc = null;
  let slidesPdfLoadingTask = null;
  let slidesNativeFrame = null;
  let slidesAutoScrollTimer = null;

  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Onboarding tour ──
  const LS_TOUR_KEY = 'workshop_tour_shown';
  const LS_ONBOARDING_HIDDEN_KEY = 'workshop_onboarding_hidden';

  function isOnboardingChecklistHidden() {
    return localStorage.getItem(LS_ONBOARDING_HIDDEN_KEY) === '1';
  }

  function markOnboardingChecklistHidden() {
    localStorage.setItem(LS_ONBOARDING_HIDDEN_KEY, '1');
  }

  function runOnboardingTourIfNeeded() {
    if (!_isFirstVisit) return;
    if (localStorage.getItem(LS_TOUR_KEY)) return;
    localStorage.setItem(LS_TOUR_KEY, '1');

    const _ALL_EMOJI_STEPS = [
      { selector: '#emoji-bar button[onclick*="👍"]',  emoji: '👍', text: "Tap when the speaker nails it. Their ego needs the fuel." },
      { selector: '#emoji-bar button[onclick*="⚔️"]',  emoji: '⚔️', text: "Fight me on this. Intellectually." },
      { selector: '#emoji-bar button[onclick*="🤔"]',  emoji: '🤔', text: "Hmm... I'm not convinced yet." },
      { selector: '#emoji-bar button[onclick*="🎉"]',  emoji: '🎉', text: "THIS IS AMAZING!" },
      { selector: '#emoji-bar button[onclick*="❤️"]',  emoji: '❤️', text: "Genuinely love this." },
      { selector: '#emoji-bar button[onclick*="🔥"]',  emoji: '🔥', text: "This is absolute fire." },
      { selector: '#emoji-bar button[onclick*="👏"]',  emoji: '👏', text: "Standing ovation!" },
      { selector: '#emoji-bar button[onclick*="😂"]',  emoji: '😂', text: "I'm dead 💀" },
      { selector: '#emoji-bar button[onclick*="🤯"]',  emoji: '🤯', text: "My brain just exploded." },
      { selector: '#emoji-bar button[onclick*="💡"]',  emoji: '💡', text: "Wait, I have an idea!" },
      { selector: '#emoji-bar button[onclick*="☕"]',  emoji: '☕', text: "I need a break. Now." },
      { selector: '#emoji-bar button[onclick*="✅"]',  emoji: '✅', text: "Agreed. 100%." },
      { selector: '#emoji-bar button[onclick*="❌"]',  emoji: '❌', text: "Nope. Hard disagree." },
    ];
    const _shuffled = _ALL_EMOJI_STEPS.slice().sort(() => Math.random() - .5).slice(0, 4);
    const STEPS = [
      { selector: '#display-name',    emoji: '✏️', text: "That's your name. Tap it to rename yourself. Be creative." },
      { selector: '#summary-btn',     emoji: '🧠', text: 'AI recaps what you missed. Tap any time. Zero FOMO.' },
      { selector: '#location-prompt', emoji: '📍', text: "Tell us where you're from — for the world map. Totally optional." },
      ..._shuffled,
    ];

    const TOTAL = STEPS.length;
    let current = 0;
    let bubble = null;
    let glowEl = null;
    let autoTimer = null;

    function clearGlow() {
      if (glowEl) { glowEl.classList.remove('tour-glow'); glowEl = null; }
    }
    function removeBubble() {
      if (bubble) { bubble.remove(); bubble = null; }
    }
    function clearAutoTimer() {
      if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    }
    function finish() {
      clearAutoTimer();
      clearGlow();
      removeBubble();
    }

    function showStep(index) {
      clearAutoTimer();
      clearGlow();
      removeBubble();
      if (index >= TOTAL) { finish(); return; }

      const step = STEPS[index];
      const anchor = document.querySelector(step.selector);
      if (!anchor) { showStep(index + 1); return; }

      glowEl = anchor;
      glowEl.classList.add('tour-glow');

      bubble = document.createElement('div');
      bubble.className = 'tour-bubble';

      const emojiSpan = document.createElement('span');
      emojiSpan.className = 'tour-bubble-emoji';
      emojiSpan.textContent = step.emoji;

      const textSpan = document.createElement('span');
      textSpan.className = 'tour-bubble-text';
      textSpan.textContent = step.text;

      const footer = document.createElement('div');
      footer.className = 'tour-bubble-footer';

      const dots = document.createElement('div');
      dots.className = 'tour-dots';
      for (let i = 0; i < TOTAL; i++) {
        const dot = document.createElement('div');
        dot.className = 'tour-dot' + (i === index ? ' active' : '');
        dots.appendChild(dot);
      }

      const skipBtn = document.createElement('button');
      skipBtn.className = 'tour-skip';
      skipBtn.textContent = 'Skip';
      skipBtn.onclick = (e) => { e.stopPropagation(); finish(); };

      footer.appendChild(dots);
      footer.appendChild(skipBtn);
      bubble.appendChild(emojiSpan);
      bubble.appendChild(textSpan);
      bubble.appendChild(footer);
      document.body.appendChild(bubble);

      positionBubble(bubble, anchor);

      let advanced = false;
      function advance() {
        if (advanced) return;
        advanced = true;
        clearAutoTimer();
        document.removeEventListener('click', onTap, true);
        current++;
        showStep(current);
      }
      function onTap(e) {
        if (e.target === skipBtn || skipBtn.contains(e.target)) return;
        advance();
      }
      setTimeout(() => document.addEventListener('click', onTap, true), 200);
      autoTimer = setTimeout(advance, 3500);
    }

    function positionBubble(bub, anchor) {
      const rect = anchor.getBoundingClientRect();
      const bubW = 240;
      const spaceAbove = rect.top;
      const spaceBelow = window.innerHeight - rect.bottom;
      bub.style.left = Math.max(8, Math.min(window.innerWidth - bubW - 8, rect.left + rect.width / 2 - bubW / 2)) + 'px';
      if (spaceAbove > 140 || spaceAbove > spaceBelow) {
        bub.classList.remove('arrow-top');
        bub.style.top = '0px';
        requestAnimationFrame(() => {
          const bh = bub.getBoundingClientRect().height;
          bub.style.top = Math.max(8, rect.top - bh - 12) + 'px';
        });
      } else {
        bub.classList.add('arrow-top');
        bub.style.top = (rect.bottom + 12) + 'px';
      }
    }

    setTimeout(() => showStep(0), 800);
  }

  function avatarColorFromUuid(uuid) {
    const hash = parseInt((uuid || '').replace(/-/g, '').slice(0, 8), 16);
    const hue = hash % 360;
    return `hsl(${hue}, 60%, 40%)`;
  }

  function showAvatarModal(src) {
    // Remove existing modal if any
    const existing = document.getElementById('avatar-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'avatar-modal';
    modal.className = 'avatar-modal-overlay';

    const container = document.createElement('div');
    container.className = 'avatar-modal-container';

    const img = document.createElement('img');
    img.src = src;
    img.className = 'avatar-modal-img';

    const refreshBtn = document.createElement('button');
    refreshBtn.className = 'avatar-refresh-btn';
    refreshBtn.innerHTML = '\u{1F504}';
    refreshBtn.title = 'Get a new avatar';
    refreshBtn.onclick = function(e) {
        e.stopPropagation();
        // Track the current avatar as rejected
        const currentSrc = img.src;
        const filename = currentSrc.split('/').pop();
        if (filename && !rejectedAvatars.includes(filename)) {
            rejectedAvatars.push(filename);
        }
        if (ws) ws.send(JSON.stringify({ type: 'refresh_avatar', rejected: rejectedAvatars }));
        // Spin the refresh button
        refreshBtn.classList.add('spinning');
        setTimeout(function() { refreshBtn.classList.remove('spinning'); }, 600);
        // Keep modal open; timer starts when new avatar arrives via state broadcast
        window._avatarModalImg = img;
        window._avatarModal = modal;
    };

    container.appendChild(img);
    container.appendChild(refreshBtn);
    modal.appendChild(container);

    modal.addEventListener('click', function() { closeAvatarModal(); });
    container.addEventListener('click', function(e) { e.stopPropagation(); });

    document.body.appendChild(modal);
  }

  function showLetterAvatarModal(letters, bgColor) {
    const existing = document.getElementById('avatar-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'avatar-modal';
    modal.className = 'avatar-modal-overlay';

    const container = document.createElement('div');
    container.className = 'avatar-modal-container';

    const avatar = document.createElement('span');
    avatar.className = 'avatar-modal-letter';
    avatar.style.background = bgColor;
    avatar.textContent = letters;

    // No refresh button for letter avatars (conference mode)

    container.appendChild(avatar);
    modal.appendChild(container);

    modal.addEventListener('click', function() { closeAvatarModal(); });

    document.body.appendChild(modal);
  }

  function closeAvatarModal() {
    const modal = document.getElementById('avatar-modal');
    if (!modal) return;
    if (window._avatarModalCloseTimer) {
      clearTimeout(window._avatarModalCloseTimer);
      window._avatarModalCloseTimer = null;
    }
    window._avatarModalImg = null;
    window._avatarModal = null;
    modal.remove();
  }


  let notesContent = '';

  function updateNotes(content) {
    notesContent = content || '';
    const btn = document.getElementById('notes-btn');
    if (btn) btn.style.display = notesContent ? '' : 'none';
    const el = document.getElementById('notes-content');
    if (el) el.textContent = notesContent;
    const dlBtn = document.getElementById('participant-notes-download');
    if (dlBtn) dlBtn.style.display = notesContent ? '' : 'none';
  }

  function downloadParticipantNotes() {
    if (!notesContent) return;
    const blob = new Blob([notesContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'session-notes.txt';
    a.click();
    URL.revokeObjectURL(url);
  }

  function toggleNotesModal() {
    const overlay = document.getElementById('notes-overlay');
    if (overlay) overlay.classList.toggle('open');
  }

  function closeNotesModal() {
    const overlay = document.getElementById('notes-overlay');
    if (overlay) overlay.classList.remove('open');
  }

  function updateSummary(points, updatedAt) {
    const prevCount = summaryPoints.length;
    summaryPoints = points || [];
    summaryUpdatedAt = updatedAt;
    if (summaryPoints.length) {
      _summaryRequested = false;
      const btn = document.getElementById('summary-refresh-btn');
      if (btn) { btn.disabled = false; btn.style.opacity = ''; }
    }
    const countEl = document.getElementById('summary-count');
    if (countEl) countEl.textContent = summaryPoints.length > 0 ? summaryPoints.length : '';
    if (summaryPoints.length > prevCount) {
      const summaryBtn = document.getElementById('summary-btn');
      if (summaryBtn) {
        summaryBtn.classList.remove('summary-btn-flash');
        void summaryBtn.offsetWidth;
        summaryBtn.classList.add('summary-btn-flash');
      }
    }
    renderSummaryList();
  }

  function renderSummaryList() {
    const list = document.getElementById('summary-list');
    const timeEl = document.getElementById('summary-time');
    if (!list) return;
    if (!summaryPoints.length) {
      list.innerHTML = _summaryRequested
        ? '<li class="summary-empty">Generating key points… please wait.</li>'
        : '<li class="summary-empty">No key points yet. Tap to request.</li>';
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

  let _summaryRequested = false;
  function toggleSummaryModal() {
    const overlay = document.getElementById('summary-overlay');
    if (overlay) overlay.classList.toggle('open');
    // Request generation if no points yet
    if (!summaryPoints.length && !_summaryRequested) {
      _summaryRequested = true;
      const list = document.getElementById('summary-list');
      if (list) list.innerHTML = '<li class="summary-empty">Generating key points… please wait.</li>';
      fetch('/api/summary/force', { method: 'POST' }).catch(() => {});
    }
  }

  function closeSummaryModal() {
    const overlay = document.getElementById('summary-overlay');
    if (overlay) overlay.classList.remove('open');
  }

  function closeParticipantModals() {
    closeNotesModal();
    closeSummaryModal();
    closeSlidesModal();
    closeAvatarModal();
  }

  function requestSummaryRefresh() {
    _summaryRequested = true;
    if (summaryPoints.length === 0) {
      const list = document.getElementById('summary-list');
      if (list) list.innerHTML = '<li class="summary-empty">Generating key points… please wait.</li>';
    }
    const btn = document.getElementById('summary-refresh-btn');
    if (btn) { btn.disabled = true; btn.style.opacity = '0.4'; }
    fetch('/api/summary/force', { method: 'POST' }).catch(() => {});
  }

  function _slidePageKey(slug) {
    return `${LS_SLIDE_PAGE_PREFIX}${slug}`;
  }

  function _slideViewKey(slug) {
    return `${LS_SLIDE_VIEW_PREFIX}${slug}`;
  }

  function _getStoredSlidePage(slug) {
    const raw = Number.parseInt(localStorage.getItem(_slidePageKey(slug)) || '1', 10);
    return Number.isFinite(raw) && raw > 0 ? raw : 1;
  }

  function _setStoredSlidePage(slug, page) {
    if (!slug || !page || page < 1) return;
    localStorage.setItem(_slidePageKey(slug), String(page));
  }

  function _getStoredSlideView(slug) {
    if (SLIDES_DISABLE_VIEW_PERSISTENCE) return null;
    if (!slug) return null;
    try {
      const raw = localStorage.getItem(_slideViewKey(slug));
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      const page = Number(parsed?.page || 1);
      const scrollTop = Number(parsed?.scrollTop || 0);
      return {
        page: Number.isFinite(page) && page > 0 ? page : 1,
        scrollTop: Number.isFinite(scrollTop) && scrollTop >= 0 ? scrollTop : 0,
      };
    } catch (_) {
      return null;
    }
  }

  function _setStoredSlideView(slug, view) {
    if (SLIDES_DISABLE_VIEW_PERSISTENCE) return;
    if (!slug || !view || typeof view !== 'object') return;
    const payload = {
      page: Math.max(1, Number(view.page || 1)),
      scrollTop: Math.max(0, Number(view.scrollTop || 0)),
    };
    try {
      localStorage.setItem(_slideViewKey(slug), JSON.stringify(payload));
    } catch (_) {}
  }

  function _formatSlideUpdated(updatedAt) {
    if (!updatedAt) return 'time unavailable';
    const dt = new Date(updatedAt);
    if (Number.isNaN(dt.getTime())) return 'time unavailable';
    const sec = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 1000));
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hrs = Math.floor(min / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return dt.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function _buildSlideOptionLabel(slide) {
    if (!slide) return 'Select a slide';
    return slide.name;
  }

  function _markSelectedSlideInList() {
    const list = document.getElementById('slides-list');
    if (!list) return;
    for (const btn of Array.from(list.querySelectorAll('.slides-list-item'))) {
      const active = btn.getAttribute('data-slide-id') === slidesSelectedId;
      btn.classList.toggle('active', active);
    }
  }

  function _renderSlidesUpdatedLabel(slide) {
    const label = document.getElementById('slides-updated');
    if (!label) return;
    if (!slide) {
      label.textContent = '';
      return;
    }
    label.textContent = `updated ${_formatSlideUpdated(slide.updated_at)}`;
  }

  function _setSlidesError(message) {
    const err = document.getElementById('slides-error');
    if (!err) return;
    if (!message) {
      err.style.display = 'none';
      err.textContent = '';
      return;
    }
    err.style.display = '';
    err.textContent = message;
  }

  function _setSlidesDownload(url, disabled = false) {
    const btn = document.getElementById('slides-download-btn');
    if (!btn) return;
    if (disabled || !url) {
      btn.setAttribute('aria-disabled', 'true');
      btn.removeAttribute('href');
      return;
    }
    btn.removeAttribute('aria-disabled');
    btn.href = url;
  }

  async function _getSlidesPdfModules() {
    if (slidesPdfLib && slidesPdfViewerModule) {
      return { pdfjsLib: slidesPdfLib, pdfjsViewer: slidesPdfViewerModule };
    }
    if (!slidesPdfModulesPromise) {
      slidesPdfModulesPromise = Promise.all([
        import('https://cdn.jsdelivr.net/npm/pdfjs-dist@5.4.149/build/pdf.min.mjs'),
        import('https://cdn.jsdelivr.net/npm/pdfjs-dist@5.4.149/web/pdf_viewer.min.mjs'),
      ]).then(([pdfjsLib, pdfjsViewer]) => {
        pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@5.4.149/build/pdf.worker.min.mjs';
        slidesPdfLib = pdfjsLib;
        slidesPdfViewerModule = pdfjsViewer;
        return { pdfjsLib, pdfjsViewer };
      });
    }
    return slidesPdfModulesPromise;
  }

  async function _initSlidesViewer() {
    if (slidesPdfViewer) return;
    const { pdfjsViewer } = await _getSlidesPdfModules();
    const container = document.getElementById('slides-pdf-container');
    const viewer = document.getElementById('slides-pdf-viewer');
    if (!container || !viewer) return;

    slidesPdfEventBus = new pdfjsViewer.EventBus();
    slidesPdfLinkService = new pdfjsViewer.PDFLinkService({ eventBus: slidesPdfEventBus });
    slidesPdfViewer = new pdfjsViewer.PDFViewer({
      container,
      viewer,
      eventBus: slidesPdfEventBus,
      linkService: slidesPdfLinkService,
      textLayerMode: 1,
    });
    slidesPdfLinkService.setViewer(slidesPdfViewer);

    slidesPdfEventBus.on('pagechanging', (evt) => {
      if (slidesSelectedSlug && evt?.pageNumber) {
        _setStoredSlidePage(slidesSelectedSlug, evt.pageNumber);
        const container = document.getElementById('slides-pdf-container');
        _setStoredSlideView(slidesSelectedSlug, {
          page: evt.pageNumber,
          scrollTop: Number(container?.scrollTop || 0),
        });
        const slide = slidesCatalog.find(s => s.slug === slidesSelectedSlug);
        _renderSlidesMeta(slide || null);
      }
    });

    // Keep page controls synced while user scrolls through the PDF.
    slidesPdfEventBus.on('updateviewarea', (evt) => {
      const page = Number(evt?.location?.pageNumber || 0);
      if (!slidesSelectedSlug || !page) return;
      const container = document.getElementById('slides-pdf-container');
      _setStoredSlidePage(slidesSelectedSlug, page);
      _setStoredSlideView(slidesSelectedSlug, {
        page,
        scrollTop: Number(container?.scrollTop || 0),
      });
      const slide = slidesCatalog.find(s => s.slug === slidesSelectedSlug);
      _syncSlidesPageControls(slide || null);
    });
  }

  async function _clearSlidesDocument() {
    if (slidesAutoScrollTimer) {
      clearTimeout(slidesAutoScrollTimer);
      slidesAutoScrollTimer = null;
    }
    if (slidesPdfLoadingTask) {
      try { slidesPdfLoadingTask.destroy(); } catch (_) {}
      slidesPdfLoadingTask = null;
    }
    if (slidesPdfViewer) slidesPdfViewer.setDocument(null);
    if (slidesPdfLinkService) slidesPdfLinkService.setDocument(null, null);
    if (slidesPdfDoc) {
      try { await slidesPdfDoc.destroy(); } catch (_) {}
      slidesPdfDoc = null;
    }
    if (slidesNativeFrame) {
      slidesNativeFrame.src = 'about:blank';
      slidesNativeFrame.remove();
      slidesNativeFrame = null;
    }
    const viewer = document.getElementById('slides-pdf-viewer');
    if (viewer) viewer.innerHTML = '';
  }

  function _scheduleTestAutoScroll(slide) {
    if (!SLIDES_TEST_AUTO_SCROLL_ENABLED || !slide) return;
    if (slidesAutoScrollTimer) {
      clearTimeout(slidesAutoScrollTimer);
      slidesAutoScrollTimer = null;
    }
    const targetId = slide._id;
    slidesAutoScrollTimer = setTimeout(() => {
      if (slidesSelectedId !== targetId) return;
      const requestedPage = Math.max(1, Number(SLIDES_TEST_AUTO_SCROLL_PAGE || 1));
      if (slidesPdfDoc && slidesPdfViewer) {
        const numPages = Math.max(1, Number(slidesPdfDoc.numPages || 1));
        const targetPage = Math.min(numPages, requestedPage);
        try {
          if (slidesPdfLinkService?.goToPage) slidesPdfLinkService.goToPage(targetPage);
        } catch (_) {}
        slidesPdfViewer.currentPageNumber = targetPage;
        _setStoredSlidePage(slidesSelectedSlug, targetPage);
      } else if (slidesNativeFrame) {
        const raw = String(slidesNativeFrame.src || '');
        if (raw) {
          const base = raw.replace(/#page=\d+$/, '');
          slidesNativeFrame.src = `${base}#page=${requestedPage}`;
        }
      }
      _renderSlidesMeta(slide);
    }, SLIDES_TEST_AUTO_SCROLL_DELAY_MS);
  }

  function _showSlideInNativeFrame(url) {
    const container = document.getElementById('slides-pdf-container');
    const viewer = document.getElementById('slides-pdf-viewer');
    if (!container || !viewer) return false;
    viewer.innerHTML = '';
    if (!slidesNativeFrame) {
      slidesNativeFrame = document.createElement('iframe');
      slidesNativeFrame.className = 'slides-native-frame';
      slidesNativeFrame.setAttribute('title', 'Slides preview');
      slidesNativeFrame.setAttribute('loading', 'eager');
    }
    const joiner = url.includes('?') ? '&' : '?';
    slidesNativeFrame.src = `${url}${joiner}inline=1`;
    container.appendChild(slidesNativeFrame);
    return true;
  }

  function _setSlidesLoading({ visible = false, loaded = 0, total = 0, label = '' } = {}) {
    const box = document.getElementById('slides-loading');
    const text = document.getElementById('slides-loading-label');
    const fill = document.getElementById('slides-progress-fill');
    if (!box || !text || !fill) return;
    if (!visible) {
      box.style.display = 'none';
      fill.style.width = '0%';
      return;
    }
    box.style.display = '';
    const pct = total > 0 ? Math.max(2, Math.min(100, Math.round((loaded / total) * 100))) : 10;
    fill.style.width = `${pct}%`;
    if (label) {
      text.textContent = label;
    } else if (total > 0) {
      text.textContent = `Downloading slide... ${pct}%`;
    } else {
      text.textContent = 'Downloading slide...';
    }
  }

  async function _fetchSlideHeaders(url) {
    try {
      const resp = await fetch(url, { method: 'HEAD' });
      if (!resp.ok) return {};
      return {
        etag: resp.headers.get('ETag') || null,
        lastModified: resp.headers.get('Last-Modified') || null,
      };
    } catch (_) {
      return {};
    }
  }

  function _slideFingerprint(slide, headers) {
    return [
      slide.url || '',
      slide.updated_at || '',
      slide.etag || headers.etag || '',
      slide.last_modified || headers.lastModified || '',
    ].join('|');
  }

  function _isDisplayableSlideName(name) {
    const cleaned = (name || '').trim();
    if (!cleaned) return false;
    return /[\p{L}\p{N}]/u.test(cleaned);
  }

  function _normalizeSlidesCatalog(rawSlides) {
    const normalized = [];
    const seen = new Set();
    for (const raw of (Array.isArray(rawSlides) ? rawSlides : [])) {
      if (!raw || typeof raw !== 'object') continue;
      const name = String(raw.name || '').trim();
      const url = String(raw.url || '').trim();
      if (!_isDisplayableSlideName(name) || !url) continue;
      const slug = String(raw.slug || '').trim() || 'slide';
      const key = `${slug}|${url}`;
      if (seen.has(key)) continue;
      seen.add(key);
      normalized.push({ ...raw, name, url, slug, _id: key });
    }
    return normalized;
  }

  function _renderSlidesMeta(slide) {
    _syncSlidesPageControls(slide || null);
    _renderSlidesUpdatedLabel(slide || null);
    _markSelectedSlideInList();
  }

  function _syncSlidesPageControls(slide) {
    const page = document.getElementById('slides-page-inline');
    if (!page) return;
    const hasPdfjsDoc = Boolean(slide && slidesPdfDoc && slidesPdfViewer && slidesSelectedId === slide._id);
    if (!hasPdfjsDoc) {
      page.textContent = '';
      return;
    }
    const numPages = Math.max(1, Number(slidesPdfDoc?.numPages || 1));
    const current = Math.max(
      1,
      Math.min(numPages, Number(slidesPdfViewer?.currentPageNumber || _getStoredSlidePage(slide.slug))),
    );
    page.textContent = `Page ${current}/${numPages}`;
  }

  function _renderSlidesList(targetId) {
    const list = document.getElementById('slides-list');
    if (!list) return;
    list.innerHTML = '';

    for (const slide of slidesCatalog) {
      const item = document.createElement('div');
      item.className = 'slides-list-item';
      item.setAttribute('data-slide-id', slide._id);
      const openBtn = document.createElement('button');
      openBtn.type = 'button';
      openBtn.className = 'slides-list-open';
      openBtn.title = slide.name;
      openBtn.textContent = _buildSlideOptionLabel(slide);
      openBtn.addEventListener('click', async () => {
        await _loadSlideIntoViewer(slide, { forceReload: true });
      });
      const dl = document.createElement('a');
      dl.className = 'slides-list-download';
      dl.href = slide.url;
      dl.setAttribute('download', '');
      dl.textContent = '⬇';
      dl.title = `Download ${slide.name}`;
      dl.addEventListener('click', (evt) => evt.stopPropagation());
      if (slide._id === targetId) item.classList.add('active');
      item.appendChild(openBtn);
      item.appendChild(dl);
      list.appendChild(item);
    }
    _markSelectedSlideInList();
  }

  async function _loadSlideIntoViewer(slide, { forceReload = false } = {}) {
    if (!slide) return;
    _setSlidesError('');
    _setSlidesLoading({ visible: true, loaded: 0, total: 0, label: 'Checking cache...' });

    const shell = document.getElementById('slides-viewer-shell');
    const empty = document.getElementById('slides-empty');
    if (shell) shell.style.display = '';
    if (empty) empty.style.display = 'none';

    const headers = await _fetchSlideHeaders(slide.url);
    const effectiveUpdatedAt = slide.updated_at || headers.lastModified || null;
    if (effectiveUpdatedAt && !slide.updated_at) slide.updated_at = effectiveUpdatedAt;
    const fingerprint = _slideFingerprint(slide, headers);
    if (!forceReload && slidesSelectedId === slide._id && slidesLastFingerprint === fingerprint && slidesPdfDoc) {
      const saved = _getStoredSlideView(slide.slug);
      const maxPages = Math.max(1, Number(slidesPdfDoc.numPages || 1));
      const targetPage = Math.min(saved?.page || _getStoredSlidePage(slide.slug), maxPages);
      slidesPdfViewer.currentPageNumber = targetPage;
      const container = document.getElementById('slides-pdf-container');
      if (container && saved && Number.isFinite(saved.scrollTop)) {
        requestAnimationFrame(() => { container.scrollTop = saved.scrollTop; });
      }
      _setStoredSlidePage(slide.slug, targetPage);
      _renderSlidesMeta({ ...slide, updated_at: effectiveUpdatedAt });
      _setSlidesDownload(slide.url, false);
      _setSlidesLoading({ visible: false });
      _scheduleTestAutoScroll(slide);
      return;
    }

    await _clearSlidesDocument();

    try {
      await _getSlidesPdfModules();
      await _initSlidesViewer();
      const loadingTask = slidesPdfLib.getDocument({ url: slide.url });
      loadingTask.onProgress = (progress) => {
        _setSlidesLoading({
          visible: true,
          loaded: Number(progress?.loaded || 0),
          total: Number(progress?.total || 0),
        });
      };
      slidesPdfLoadingTask = loadingTask;
      const doc = await loadingTask.promise;
      if (slidesPdfLoadingTask !== loadingTask) {
        try { await doc.destroy(); } catch (_) {}
        return;
      }
      slidesPdfDoc = doc;
      slidesPdfViewer.setDocument(doc);
      slidesPdfLinkService.setDocument(doc, null);
      slidesPdfViewer.currentScaleValue = 'page-width';

      const saved = _getStoredSlideView(slide.slug);
      const maxPages = Math.max(1, Number(doc.numPages || 1));
      const savedPage = Math.min(saved?.page || _getStoredSlidePage(slide.slug), maxPages);
      slidesPdfViewer.currentPageNumber = savedPage;
      _setStoredSlidePage(slide.slug, savedPage);
      if (saved && Number.isFinite(saved.scrollTop)) {
        const container = document.getElementById('slides-pdf-container');
        if (container) requestAnimationFrame(() => { container.scrollTop = saved.scrollTop; });
      }

      slidesSelectedSlug = slide.slug;
      slidesSelectedId = slide._id;
      slidesLastFingerprint = fingerprint;
      _setSlidesDownload(slide.url, false);
      _renderSlidesMeta({ ...slide, updated_at: effectiveUpdatedAt });
      _setSlidesLoading({ visible: false });
      _scheduleTestAutoScroll(slide);
    } catch (err) {
      const fallbackOk = _showSlideInNativeFrame(slide.url);
      if (!fallbackOk) {
        _setSlidesError('Failed to load this PDF. Try download.');
        _setSlidesDownload('', true);
        _setSlidesLoading({ visible: false });
        return;
      }
      slidesSelectedSlug = slide.slug;
      slidesSelectedId = slide._id;
      slidesLastFingerprint = fingerprint;
      _setSlidesDownload(slide.url, false);
      _renderSlidesMeta({ ...slide, updated_at: effectiveUpdatedAt });
      _setSlidesError('');
      _setSlidesLoading({ visible: false });
      _scheduleTestAutoScroll(slide);
    }
  }

  async function _refreshSlidesCatalog({ forceReloadCurrent = false } = {}) {
    const empty = document.getElementById('slides-empty');
    const shell = document.getElementById('slides-viewer-shell');
    try {
      const res = await fetch('/api/slides', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      slidesCatalog = _normalizeSlidesCatalog(data.slides);
      if (!slidesCatalog.length) {
        _renderSlidesList(null);
        slidesSelectedSlug = null;
        slidesSelectedId = null;
        slidesLastFingerprint = null;
        await _clearSlidesDocument();
        _renderSlidesMeta(null);
        _setSlidesDownload('', true);
        _setSlidesError('');
        _setSlidesLoading({ visible: false });
        if (empty) {
          empty.style.display = '';
          empty.textContent = 'No slides published yet.';
        }
        if (shell) shell.style.display = 'none';
        return;
      }

      const selectedStillExists = slidesSelectedId && slidesCatalog.some(s => s._id === slidesSelectedId);
      const targetId = selectedStillExists ? slidesSelectedId : null;
      _renderSlidesList(targetId);
      if (selectedStillExists) {
        const slide = slidesCatalog.find(s => s._id === targetId);
        if (slide) {
          await _loadSlideIntoViewer(slide, { forceReload: forceReloadCurrent });
        }
      } else {
        slidesSelectedSlug = null;
        slidesSelectedId = null;
        slidesLastFingerprint = null;
        await _clearSlidesDocument();
        _setSlidesDownload('', true);
        _setSlidesError('');
        _setSlidesLoading({ visible: false });
        if (empty) {
          empty.style.display = '';
          empty.textContent = 'Select a slide to preview.';
        }
        if (shell) shell.style.display = 'none';
      }
    } catch (_) {
      _setSlidesError('Could not fetch slide list from server.');
      if (empty) {
        empty.style.display = '';
        empty.textContent = 'No slides published yet.';
      }
      if (shell) shell.style.display = 'none';
      _setSlidesDownload('', true);
      _setSlidesLoading({ visible: false });
      _renderSlidesMeta(null);
    }
  }

  function _startSlidesRefreshLoop() {
    _stopSlidesRefreshLoop();
    slidesRefreshTimer = setInterval(() => {
      const overlay = document.getElementById('slides-overlay');
      if (!overlay || !overlay.classList.contains('open')) return;
      _refreshSlidesCatalog().catch(() => {});
    }, SLIDES_REFRESH_MS);
  }

  function _stopSlidesRefreshLoop() {
    if (!slidesRefreshTimer) return;
    clearInterval(slidesRefreshTimer);
    slidesRefreshTimer = null;
  }

  function toggleSlidesModal() {
    const overlay = document.getElementById('slides-overlay');
    if (!overlay) return;
    if (overlay.classList.contains('open')) {
      closeSlidesModal();
      return;
    }
    overlay.classList.add('open');
    _refreshSlidesCatalog().catch(() => {});
    _startSlidesRefreshLoop();
  }

  function closeSlidesModal() {
    const overlay = document.getElementById('slides-overlay');
    if (overlay) overlay.classList.remove('open');
    _stopSlidesRefreshLoop();
    _setSlidesLoading({ visible: false });
  }

  function warmSlidesCatalog() {
    fetch('/api/slides', { cache: 'no-store' })
      .then(res => (res.ok ? res.json() : { slides: [] }))
      .then(data => { slidesCatalog = _normalizeSlidesCatalog(data.slides); })
      .catch(() => {});
  }

  async function requestNotificationPermission() {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'default') return;
    await Notification.requestPermission();
    const btn = document.getElementById('notif-btn');
    if (btn) btn.style.display = 'none';
    updateOnboardingChecklist();
  }

  function notifyIfHidden(title, body) {
    if (!document.hidden) return;
    if (Notification.permission !== 'granted') return;
    try { new Notification(title, { body }); } catch (_) {}
  }

  function showDeployPending() {
    const el = document.getElementById('version-tag');
    if (!el) return;
    if (!document.getElementById('_blink-style')) {
      const s = document.createElement('style');
      s.id = '_blink-style';
      s.textContent = '@keyframes _blink-warning{0%,100%{opacity:1}50%{opacity:.25}}';
      document.head.appendChild(s);
    }
    el.textContent = '⚠️ Deploy incoming';
    el.style.cssText = 'color:#f5a623;opacity:1;animation:_blink-warning 1s ease-in-out infinite;font-weight:600;';
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

  // ── Auto-join: always get fresh name from server ──
  // localStorage only stores names the user explicitly chose (via pencil edit).
  // Auto-suggested LOTR names are never persisted — each tab gets a fresh one.
  const LS_CUSTOM_NAME_KEY = 'workshop_custom_name'; // true if user explicitly renamed
  let _suggestedName = null; // tracks the auto-suggested name (for onboarding checklist)

  (async function autoJoin() {
    const isCustom = localStorage.getItem(LS_CUSTOM_NAME_KEY);
    const savedName = localStorage.getItem(LS_KEY);
    if (isCustom && savedName) {
      myName = savedName;
    } else {
      _suggestedName = await fetchSuggestedName();
      myName = _suggestedName;
    }
    connectWS(myName);
  })();
  warmSlidesCatalog();

  // ── Inline name editing ──
  function startNameEdit() {
    const display = document.getElementById('display-name');
    const editWrap = document.getElementById('name-edit-wrap');
    const editInput = document.getElementById('name-edit-input');
    editInput.value = myName;
    display.style.display = 'none';
    editWrap.style.display = '';
    editInput.focus();
    editInput.select();
  }

  document.getElementById('display-name').addEventListener('click', startNameEdit);

  function confirmNameEdit() {
    const newName = document.getElementById('name-edit-input').value.trim();
    if (newName && newName !== myName) {
        myName = newName;
        localStorage.setItem(LS_KEY, myName);
        localStorage.setItem(LS_CUSTOM_NAME_KEY, '1');
        document.getElementById('display-name').textContent = myName;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'set_name', name: myName }));
        }
    }
    document.getElementById('display-name').style.display = '';
    document.getElementById('name-edit-wrap').style.display = 'none';
    updateOnboardingChecklist();
  }

  document.getElementById('name-edit-input').addEventListener('blur', confirmNameEdit);
  document.getElementById('name-edit-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('name-edit-input').blur();
    if (e.key === 'Escape') {
        document.getElementById('name-edit-input').value = myName; // revert
        document.getElementById('name-edit-input').blur();
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

  function updateOnboardingChecklist() {
    const nameEl = document.getElementById('onboard-name');
    const locEl = document.getElementById('onboard-location');
    const notifEl = document.getElementById('onboard-notif');
    if (nameEl && !nameEl.classList.contains('done') && (_suggestedName === null || myName !== _suggestedName)) {
      nameEl.classList.add('done');
      nameEl.querySelector('input[type=checkbox]').checked = true;
      nameEl.style.cursor = 'default';
      nameEl.onclick = null;
    }
    if (locEl && !locEl.classList.contains('done') && localStorage.getItem(LS_LOCATION_KEY)) {
      locEl.classList.add('done');
      locEl.querySelector('input[type=checkbox]').checked = true;
      locEl.style.cursor = 'default';
      locEl.onclick = null;
    }
    const notifGranted = 'Notification' in window && Notification.permission === 'granted';
    if (notifEl && !notifEl.classList.contains('done') && notifGranted) {
      notifEl.classList.add('done');
      notifEl.querySelector('input[type=checkbox]').checked = true;
      notifEl.style.cursor = 'default';
      notifEl.onclick = null;
    }
    // Fade out entire checklist when all tasks are done
    const allDone = nameEl?.classList.contains('done') && locEl?.classList.contains('done') && notifEl?.classList.contains('done');
    if (allDone) {
      markOnboardingChecklistHidden();
      setTimeout(() => {
        const list = document.getElementById('onboarding-list');
        if (list) { list.style.transition = 'opacity 3s'; list.style.opacity = '0'; }
      }, 1500);
    }
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
        updateOnboardingChecklist();
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
      document.getElementById('main-screen').style.display = 'block';
      runOnboardingTourIfNeeded();
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
      case 'session_paused':
        const overlay = document.getElementById('session-paused-overlay');
        const msgEl = document.getElementById('session-paused-message');
        if (overlay) {
          if (msgEl && msg.message) msgEl.textContent = msg.message;
          overlay.style.display = 'flex';
        }
        return;
      case 'state':
        // Hide session-paused overlay on successful reconnect
        const pauseOverlay = document.getElementById('session-paused-overlay');
        if (pauseOverlay && pauseOverlay.style.display !== 'none') {
          pauseOverlay.style.display = 'none';
        }
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
          if (_prevActivity !== 'debate' && msg.current_activity === 'debate') {
            notifyIfHidden('⚔️ Debate started', 'Choose your side!');
          }
          if (_prevActivity !== 'codereview' && msg.current_activity === 'codereview') {
            notifyIfHidden('📝 Code Review', 'Spot bugs and earn points!');
          }
          _prevPollActive = msg.poll_active;
          _prevActivity   = msg.current_activity;
        }
        if (msg.mode && msg.mode !== currentMode) {
          currentMode = msg.mode;
          applyParticipantMode(msg.mode);
        }
        if (msg.mode) currentMode = msg.mode;
        // In conference mode, use the server-assigned name
        if (msg.my_name && currentMode === 'conference') {
          myName = msg.my_name;
          document.getElementById('display-name').textContent = myName;
          window._myName = myName;
        }
        if (msg.poll?.id !== currentPoll?.id) {
          myVote = msg.poll?.multi ? new Set() : null;
          pollResult = null;
          activeTimer = null;
          _multiWarnShown = false;
          focusedOptionIndex = -1;
          clearInterval(_timerInterval);
        }
        // Restore poll timer from server state (survives refresh)
        if (msg.poll_timer_seconds && msg.poll_timer_started_at) {
          activeTimer = { seconds: msg.poll_timer_seconds, startedAt: new Date(msg.poll_timer_started_at).getTime() };
          _startParticipantCountdown();
        } else {
          // Timer cleared on server (e.g. poll closed) — stop client countdown
          activeTimer = null;
          clearInterval(_timerInterval);
        }
        // Restore vote from server state (authoritative), falling back to localStorage
        if (msg.my_vote != null) {
          myVote = msg.poll?.multi ? new Set(msg.my_vote) : msg.my_vote;
        } else if (msg.poll?.id !== currentPoll?.id) {
          restoreVote(msg.poll);
        }
        // Restore poll result from server state (survives refresh)
        if (msg.poll_correct_ids != null && msg.my_voted_ids != null) {
          pollResult = { correct_ids: new Set(msg.poll_correct_ids), voted_ids: new Set(msg.my_voted_ids) };
        }
        currentPoll = msg.poll;
        pollActive = msg.poll_active;
        updateParticipantCount(msg.participant_count);
        updateHostDot(msg.host_connected);
        updateScore(msg.my_score);
        window._myScore = msg.my_score || 0;
        window._myUuid = myUUID;
        window._myName = myName;
        if (msg.my_avatar && msg.my_avatar.startsWith('letter:')) {
            const parts = msg.my_avatar.split(':');
            const lt = parts[1] || '??';
            const clr = parts.slice(2).join(':') || 'var(--muted)';
            const existing = document.getElementById('my-avatar');
            if (existing && existing.tagName === 'IMG') {
                const span = document.createElement('span');
                span.id = 'my-avatar';
                span.className = 'avatar letter-avatar';
                span.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;font-weight:800;font-size:.65rem;line-height:1;color:#fff;background:' + clr;
                span.textContent = lt;
                existing.replaceWith(span);
            } else if (existing) {
                existing.style.background = clr;
                existing.textContent = lt;
                existing.style.display = '';
            }
            // Also bind click-to-enlarge for letter avatars
            const letterEl = document.getElementById('my-avatar');
            if (letterEl && !letterEl._clickBound) {
                letterEl._clickBound = true;
                letterEl.style.cursor = 'pointer';
                letterEl.addEventListener('click', function() {
                    showLetterAvatarModal(this.textContent, this.style.background);
                });
            }
        } else if (msg.my_avatar) {
            const avatarEl = document.getElementById('my-avatar');
            const nextAvatarSrc = '/static/avatars/' + msg.my_avatar;
            const currentAvatarPath = avatarEl.getAttribute('src') || '';
            const shouldUpdateAvatarSrc = !currentAvatarPath || !currentAvatarPath.endsWith('/' + msg.my_avatar);
            if (shouldUpdateAvatarSrc) {
                avatarEl.src = nextAvatarSrc;
            }
            avatarEl.style.display = '';
            // Animate only when the avatar actually changed
            if (shouldUpdateAvatarSrc) {
                avatarEl.classList.remove('avatar-changed');
                void avatarEl.offsetWidth; // force reflow to restart animation
                avatarEl.classList.add('avatar-changed');
            }
            // Update avatar modal image if open (after refresh), then auto-close after 1.5s
            if (window._avatarModalImg) {
                const modalSrc = window._avatarModalImg.getAttribute('src') || '';
                const shouldUpdateModalSrc = !modalSrc || !modalSrc.endsWith('/' + msg.my_avatar);
                if (shouldUpdateModalSrc) {
                    window._avatarModalImg.src = nextAvatarSrc;
                    // Trigger swap animation on modal image
                    window._avatarModalImg.classList.remove('avatar-swap');
                    void window._avatarModalImg.offsetWidth;
                    window._avatarModalImg.classList.add('avatar-swap');
                    const modalRef = window._avatarModal;
                    if (window._avatarModalCloseTimer) clearTimeout(window._avatarModalCloseTimer);
                    window._avatarModalCloseTimer = setTimeout(function() {
                        if (modalRef) modalRef.remove();
                        window._avatarModalImg = null;
                        window._avatarModal = null;
                    }, 1500);
                }
            }
            avatarEl.onerror = function() {
                const fallback = document.createElement('span');
                fallback.className = 'avatar-fallback';
                fallback.textContent = (window._myName || '?')[0].toUpperCase();
                fallback.style.background = avatarColorFromUuid(window._myUuid);
                this.replaceWith(fallback);
            };
            // Click to enlarge avatar + optional refresh
            if (!avatarEl._clickBound) {
                avatarEl._clickBound = true;
                avatarEl.style.cursor = 'pointer';
                avatarEl.addEventListener('click', function() {
                    showAvatarModal(this.src);
                });
            }
        }
        window._qaQuestions = msg.qa_questions || [];
        if (msg.current_activity === 'wordcloud') {
          const confGrid = document.getElementById('conference-emoji-grid');
          if (confGrid) confGrid.style.display = 'none';
          renderWordCloudScreen(msg.wordcloud_words || {}, msg.wordcloud_word_order || [], msg.wordcloud_topic || '');
        } else if (msg.current_activity === 'qa') {
          const confGrid = document.getElementById('conference-emoji-grid');
          if (confGrid) confGrid.style.display = 'none';
          renderQAScreen(msg.qa_questions || []);
        } else if (msg.current_activity === 'debate') {
          const confGrid = document.getElementById('conference-emoji-grid');
          if (confGrid) confGrid.style.display = 'none';
          renderDebateScreen(msg);
        } else if (msg.current_activity === 'codereview') {
          const confGrid = document.getElementById('conference-emoji-grid');
          if (confGrid) confGrid.style.display = 'none';
          renderCodeReviewScreen(msg.codereview);
        } else {
          const content = document.getElementById('content');
          if (content) content.dataset.screen = '';
          renderQACleanup();
          _stopCRToasts();
          _stopDebateToasts();
          renderContent(msg.vote_counts);
        }
        updateScreenShareWarning(msg.screen_share_active);
        updateSummary(msg.summary_points, msg.summary_updated_at);
        updateNotes(msg.notes_content);
        // Restore leaderboard overlay if it was active
        if (msg.leaderboard_active && msg.leaderboard_data) {
          showParticipantLeaderboard(msg.leaderboard_data);
        }
        break;
      case 'vote_update':
        renderOptions(msg.vote_counts, msg.total_votes);
        break;
      case 'participant_count':
        updateParticipantCount(msg.count);
        updateHostDot(msg.host_connected);
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
      case 'debate_timer':
        _stopBeeping();
        _debateRoundTimer = { roundIndex: msg.round_index, seconds: msg.seconds, startedAt: new Date(msg.started_at).getTime() };
        if (_lastDebateMsg) renderDebateScreen(_lastDebateMsg);
        _startDebateParticipantCountdown();
        break;
      case 'debate_round_ended':
        _debateRoundTimer = null;
        clearInterval(_debateTimerInterval);
        _stopBeeping();
        if (_lastDebateMsg) {
          _lastDebateMsg.debate_round_timer_started_at = null;
          _lastDebateMsg.debate_round_timer_seconds = null;
          renderDebateScreen(_lastDebateMsg);
        }
        break;
      case 'summary':
        updateSummary(msg.points, msg.updated_at);
        break;
      case 'leaderboard':
        showParticipantLeaderboard(msg);
        break;
      case 'leaderboard_hide':
        hideParticipantLeaderboard();
        break;
      case 'deploy_pending':
        showDeployPending();
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
    document.getElementById('pax-count').textContent = `👥 ${n}`;
  }

  function updateHostDot(connected) {
    const dot = document.getElementById('host-dot');
    if (dot) dot.style.display = connected ? 'inline' : 'none';
  }

  function updateScreenShareWarning(active) {
    const el = document.getElementById('screen-share-warning');
    if (!el) return;
    el.style.display = (active === false) ? 'flex' : 'none';
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
  function renderWordCloudScreen(wordcloudWords, wordOrder, topic) {
    _lastWordcloudWords = wordcloudWords;
    _lastWordcloudWordOrder = wordOrder;
    _lastWordcloudTopic = topic || '';
    const content = document.getElementById('content');
    if (content.dataset.screen !== 'wordcloud') {
      content.dataset.screen = 'wordcloud';
      content.innerHTML = `
        <div class="wc-layout">
          <div class="wc-cloud-panel" style="position:relative;">
            <canvas id="wc-canvas"></canvas>
            <button id="wc-download" class="btn btn-secondary wc-download-overlay" style="display:none;">⬇</button>
          </div>
          <div class="wc-input-panel">
            <p class="wc-prompt" id="wc-prompt-text">What comes to mind?</p>
            <div class="activity-input-row wc-input-row">
              <input id="wc-input" type="text" maxlength="40" autocomplete="off" placeholder="Type a word…" list="wc-suggestions" />
              <datalist id="wc-suggestions"></datalist>
              <button id="wc-go" class="btn btn-primary" disabled>↵</button>
            </div>
            <div id="wc-my-words"></div>
          </div>
        </div>`;
      const wcGoBtn = document.getElementById('wc-go');
      wcGoBtn.onclick = submitWord;
      const wcInput = document.getElementById('wc-input');
      wcInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') submitWord();
      });
      wcInput.addEventListener('input', () => {
        wcGoBtn.disabled = !wcInput.value.trim();
      });
      wcInput.focus();
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
      if (topic) {
        promptEl.innerHTML = `What comes to mind about <span class="wc-topic-highlight">${escHtml(topic)}</span>?`;
      } else {
        promptEl.textContent = 'What comes to mind?';
      }
    }
    // Show/hide download button based on word count
    const dlBtn = document.getElementById('wc-download');
    if (dlBtn) dlBtn.style.display = Object.keys(wordcloudWords).length > 0 ? '' : 'none';
    renderWordCloud(wordcloudWords);
    renderMyWords();
    updateWordSuggestions(wordcloudWords);
  }

  function submitWord(existingWord) {
    const input = document.getElementById('wc-input');
    // When called from onclick, existingWord is an Event — ignore it
    const word = (typeof existingWord === 'string' && existingWord) || (input && input.value.trim());
    if (!word) return;
    ws.send(JSON.stringify({ type: 'wordcloud_word', word }));
    if (input && typeof existingWord !== 'string') {
      input.value = '';
      const goBtn = document.getElementById('wc-go');
      if (goBtn) goBtn.disabled = true;
    }
  }

  function renderMyWords() {
    const el = document.getElementById('wc-my-words');
    if (!el) return;
    const words = _lastWordcloudWords || {};
    const order = _lastWordcloudWordOrder || [];
    const sorted = Object.entries(words).sort((a, b) => {
      if (b[1] !== a[1]) return b[1] - a[1]; // higher count first
      const ai = order.indexOf(a[0]), bi = order.indexOf(b[0]);
      return (ai === -1 ? Infinity : ai) - (bi === -1 ? Infinity : bi); // newer first (lower index)
    });
    el.innerHTML = sorted.map(([w, count]) =>
      `<button class="wc-my-word" data-word="${escHtml(w)}">${escHtml(w)}<span class="wc-word-count">${count}</span></button>`
    ).join('');
    el.querySelectorAll('.wc-my-word').forEach(btn => {
      btn.addEventListener('click', () => submitWord(btn.dataset.word));
    });
  }

  function updateWordSuggestions(wordcloudWords) {
    const dl = document.getElementById('wc-suggestions');
    if (!dl) return;
    dl.innerHTML = Object.keys(wordcloudWords)
      .map(w => `<option value="${escHtml(w)}">`)
      .join('');
  }

  function renderWordCloud(words) {
    const canvas = document.getElementById('wc-canvas');
    if (!canvas) return;
    const key = JSON.stringify(words);
    if (key === _wcLastDataKey) return;
    _wcLastDataKey = key;
    clearTimeout(_wcDebounceTimer);
    _wcDebounceTimer = setTimeout(() => _drawCloud(canvas, words), 300);
  }

  function _drawCloud(canvas, wordsMap) {
    const entries = Object.entries(wordsMap);
    const TITLE_H = 0;
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

  // ── Debate toasts ──
  function _showDebateToast() {
    const el = document.getElementById('qa-toast');
    if (!el) return;
    el.textContent = _DEBATE_TOASTS[_debateToastIndex % _DEBATE_TOASTS.length];
    _debateToastIndex++;
    el.classList.add('visible');
    clearTimeout(_debateToastTimeout);
    _debateToastTimeout = setTimeout(() => el.classList.remove('visible'), 4400);
  }

  function _startDebateToasts() {
    _stopDebateToasts();
    _stopQAToasts();
    _showDebateToast();
    _debateToastInterval = setInterval(_showDebateToast, 15000);
  }

  function _stopDebateToasts() {
    clearInterval(_debateToastInterval);
    clearTimeout(_debateToastTimeout);
    _debateToastInterval = null;
    const el = document.getElementById('qa-toast');
    if (el) el.classList.remove('visible');
  }

  // ── Code Review toasts ──
  function _showCRToast() {
    const el = document.getElementById('cr-toast');
    if (!el) return;
    const idx = Math.floor(Math.random() * _CR_TOASTS.length);
    el.textContent = _CR_TOASTS[idx];
    el.classList.add('visible');
    clearTimeout(_crToastTimeout);
    _crToastTimeout = setTimeout(() => el.classList.remove('visible'), 5000);
  }

  function _scheduleCRToast() {
    const delay = 10000 + Math.random() * 4000; // 10-14 seconds
    _crToastInterval = setTimeout(() => {
      _showCRToast();
      _scheduleCRToast();
    }, delay);
  }

  function _startCRToasts() {
    if (_crToastInterval) return; // already running, don't restart
    _showCRToast();
    _scheduleCRToast();
  }

  function _stopCRToasts() {
    clearInterval(_crToastInterval);
    clearTimeout(_crToastTimeout);
    _crToastInterval = null;
    const el = document.getElementById('cr-toast');
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
        <div class="activity-input-row qa-input-row">
          <input id="qa-input" type="text" maxlength="280" autocomplete="off"
                 placeholder="Ask a question…" />
          <button id="qa-submit-btn" class="btn btn-primary" onclick="submitQuestion()" disabled>↵</button>
        </div>
        <div id="qa-question-list"></div>
      </div>
    `;
    const input = document.getElementById('qa-input');
    if (input) {
      const qaBtn = document.getElementById('qa-submit-btn');
      input.addEventListener('keydown', e => { if (e.key === 'Enter') submitQuestion(); });
      input.addEventListener('input', () => { if (qaBtn) qaBtn.disabled = !input.value.trim(); });
      input.focus();
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
      const avatarHtml = q.author_avatar
          ? `<img src="/static/avatars/${escHtml(q.author_avatar)}" class="avatar" style="width:24px;height:24px" onerror="this.style.display='none'">`
          : '';
      return `
        <div class="qa-card-p${q.answered ? ' qa-answered-p' : ''}${condensed ? ' qa-condensed' : ''}" data-id="${escHtml(q.id)}">
          <div class="qa-text-p">${escHtml(q.text)}</div>
          <div class="qa-footer-p">
            ${avatarHtml}<span class="qa-author-p">${escHtml(q.author)}${isOwn ? ' (you)' : ''}</span>
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

  function sendEmoji(emoji, ev) {
    if (!ws) return;
    ws.send(JSON.stringify({ type: 'emoji_reaction', emoji }));
    const btn = ev && ev.currentTarget;
    if (currentMode === 'conference' || window.innerWidth <= 600) {
      showMobileEmojiShake(emoji);
    } else {
      showDesktopEmojiFloat(emoji, btn);
    }
  }

  function showMobileEmojiShake(emoji) {
    const el = document.createElement('div');
    el.textContent = emoji;
    el.className = 'emoji-shake-overlay';
    document.body.appendChild(el);
    requestAnimationFrame(() => el.classList.add('emoji-shake-active'));
    setTimeout(() => {
      el.classList.add('emoji-shake-fade');
      setTimeout(() => el.remove(), 600);
    }, 1400);
  }

  function showDesktopEmojiFloat(emoji, btn) {
    const el = document.createElement('div');
    el.textContent = emoji;
    el.className = 'emoji-float';
    let startX, startY;
    if (btn) {
      const rect = btn.getBoundingClientRect();
      startX = rect.left + rect.width / 2;
      startY = rect.top;
    } else {
      startX = window.innerWidth / 2;
      startY = window.innerHeight - 100;
    }
    el.style.left = startX + 'px';
    el.style.top = startY + 'px';
    document.body.appendChild(el);
    requestAnimationFrame(() => el.classList.add('emoji-float-active'));
    setTimeout(() => el.remove(), 2600);
  }

  function submitQuestion() {
    const input = document.getElementById('qa-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text || !ws) return;
    ws.send(JSON.stringify({ type: 'qa_submit', text }));
    input.value = '';
    const qaBtn = document.getElementById('qa-submit-btn');
    if (qaBtn) qaBtn.disabled = true;
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

  // ── HTML escaping utility ──
  function escDebate(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  // ── Debate rendering ──
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

  let _debateRoundTimer = null;
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

  function _startDebateParticipantCountdown() {
    clearInterval(_debateTimerInterval);
    _debateChimePlayed = false;
    _debateTimerInterval = setInterval(() => {
      const el = document.getElementById('debate-pax-countdown');
      if (!el || !_debateRoundTimer) { clearInterval(_debateTimerInterval); return; }
      const elapsed = (Date.now() - _debateRoundTimer.startedAt) / 1000;
      const remaining = Math.max(0, _debateRoundTimer.seconds - elapsed);
      const mins = Math.floor(remaining / 60);
      const secs = Math.ceil(remaining % 60);
      if (remaining <= 0) {
        el.textContent = "TIME'S UP";
        el.className = 'debate-countdown-large debate-countdown-expired';
        if (!_debateChimePlayed) { _debateChimePlayed = true; _playEscalatingBeeps(); }
        clearInterval(_debateTimerInterval);
      } else {
        el.textContent = mins > 0 ? `${mins}:${String(secs).padStart(2, '0')}` : `${secs}s`;
        el.className = 'debate-countdown-large';
        el.style.color = remaining <= 10 ? 'var(--danger)' : remaining <= 30 ? 'var(--warn)' : 'var(--accent)';
      }
    }, 200);
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

  function renderDebateScreen(msg) {
    _lastDebateMsg = msg;
    const content = document.getElementById('content');
    if (!content) return;
    content.dataset.screen = 'debate';
    _stopQAToasts();

    const phase = msg.debate_phase;
    const displayPhase = phase;
    const mySide = msg.debate_my_side;
    const statement = msg.debate_statement || '';
    const sideCounts = msg.debate_side_counts || { for: 0, against: 0 };
    const args = (msg.debate_arguments || []).filter(a => !a.merged_into);
    const champions = msg.debate_champions || {};

    if (!statement) {
      content.innerHTML = '<div class="debate-waiting">Waiting for debate to start…</div>';
      return;
    }

    const sideIcon = mySide === 'for' ? '👍' : mySide === 'against' ? '👎' : '';

    let html = `<div class="debate-header">
      <div class="debate-title">⚔️ Debate</div>
    </div>`;
    html += renderDebatePhaseStepper(displayPhase);
    html += `<div class="debate-statement-row">
      <span class="debate-side-count debate-side-against">👎 ${sideCounts.against}</span>
      <span class="debate-statement-text">"${escDebate(statement)}"</span>
      <span class="debate-side-count debate-side-for">${sideCounts.for} 👍</span>
    </div>`;

    if (phase === 'side_selection') {
      if (mySide) {
        if (msg.debate_auto_assigned) {
          html += `<div class="debate-auto-assigned">You were automatically assigned to ${sideIcon}</div>`;
        } else {
          html += `<div class="debate-chosen">You chose ${sideIcon} ✓</div>`;
        }
        html += `<div class="debate-waiting">Waiting for others…</div>`;
      } else {
        html += `<div class="debate-pick">
          <button class="btn debate-btn-against" onclick="debatePickSide('against')">👎 ${sideCounts.against}</button>
          <button class="btn debate-btn-for" onclick="debatePickSide('for')">${sideCounts.for} 👍</button>
        </div>`;
      }
    } else if (phase === 'arguments') {
      html += renderDebateArgColumns(args, mySide, msg, false);
      if (mySide) {
        const placeholder = mySide === 'for'
          ? 'Add an argument for 👍…'
          : 'Add an argument against 👎…';
        const inputSideClass = mySide === 'for' ? 'debate-input-for' : 'debate-input-against';
        html += `<div class="debate-input-row">
          <input id="debate-arg-input" class="${inputSideClass}" type="text" maxlength="280" placeholder="${placeholder}"
            onkeydown="if(event.key==='Enter')debateSubmitArg()"
            oninput="document.getElementById('debate-arg-submit').disabled=!this.value.trim()" />
          <button id="debate-arg-submit" class="btn btn-primary" onclick="debateSubmitArg()" disabled>↵</button>
        </div>`;
      }
    } else if (phase === 'prep') {
      html += renderDebateArgColumns(args, mySide, msg, false);
      if (phase === 'ai_cleanup') {
        html += `<div class="debate-ai-loading">
          <div class="debate-ai-spinner"></div>
          <div>AI is enriching arguments…</div>
        </div>`;
      }
      html += renderDebateHints();
      if (mySide && !champions[mySide]) {
        html += `<button class="btn btn-warn debate-volunteer-btn" onclick="debateVolunteer()">🏆 I'll be our champion!</button>`;
      } else if (mySide && champions[mySide]) {
        const isMe = msg.debate_my_is_champion;
        html += `<div class="debate-champion-info">${isMe ? '🏆 You are your team\'s champion!' : '🏆 Champion: ' + escDebate(champions[mySide])}</div>`;
      }
    } else if (phase === 'live_debate') {
      const rounds = getDebateRounds(msg.debate_first_side);
      const roundIdx = msg.debate_round_index;
      const timerActive = !!msg.debate_round_timer_started_at;
      if (!msg.debate_first_side) {
        html += `<div style="text-align:center; margin:.5rem 0; color:var(--muted);">Host is picking who speaks first…</div>`;
      } else if (roundIdx != null && roundIdx >= 0 && roundIdx < rounds.length) {
        const sub = rounds[roundIdx];
        const sideClass = sub.side === 'for' ? 'debate-round-side-for' : sub.side === 'against' ? 'debate-round-side-against' : 'debate-round-side-both';
        const sideIcon = sub.side === 'for' ? '👍' : '👎';
        html += `<div style="text-align:center; margin:.5rem 0;">
          <span class="${sideClass}" style="font-weight:700; font-size:1.1rem;">${sideIcon} ${escDebate(sub.label)}</span>
        </div>`;
        if (timerActive) {
          html += `<div id="debate-pax-countdown" class="debate-countdown-large"></div>`;
        } else {
          html += `<div style="text-align:center; color:var(--muted); font-size:.9rem;">Phase ended</div>`;
        }
      } else {
        html += `<div style="text-align:center; margin:.5rem 0; color:var(--muted);">Waiting for host to start…</div>`;
      }
      const champNames = Object.entries(champions).map(([s, n]) => `${s === 'for' ? '👍' : '👎'} ${escDebate(n)}`).join(' vs ');
      if (champNames) html += `<div class="debate-live-info">🎤 ${champNames}</div>`;
      html += renderDebateArgColumns(args, mySide, msg, true);
      html += renderDebateHints();
    }

    content.innerHTML = html;

    // Debate toasts — show during arguments/prep/live phases
    if (phase === 'arguments' || phase === 'prep' || phase === 'live_debate') {
      _startDebateToasts();
    } else {
      _stopDebateToasts();
    }

    // Reconstruct timer on reconnect from state
    if (phase === 'live_debate' && msg.debate_round_timer_started_at && msg.debate_round_index != null) {
      if (!_debateRoundTimer || _debateRoundTimer.roundIndex !== msg.debate_round_index) {
        _debateRoundTimer = {
          roundIndex: msg.debate_round_index,
          seconds: msg.debate_round_timer_seconds,
          startedAt: new Date(msg.debate_round_timer_started_at).getTime()
        };
      }
      _startDebateParticipantCountdown();
    }
  }

  function renderDebateArgColumns(args, mySide, msg, readOnly) {
    const forArgs = args.filter(a => a.side === 'for').sort((a, b) => (b.upvote_count || 0) - (a.upvote_count || 0));
    const againstArgs = args.filter(a => a.side === 'against').sort((a, b) => (b.upvote_count || 0) - (a.upvote_count || 0));
    const mergedArgs = (msg.debate_arguments || []).filter(a => a.merged_into);
    const mergedForCount = mergedArgs.filter(a => a.side === 'for').length;
    const mergedAgainstCount = mergedArgs.filter(a => a.side === 'against').length;

    const renderArg = (a) => {
      const aiClass = a.ai_generated ? ' debate-arg-ai' : '';
      const ownClass = '';
      const upvotedClass = a.has_upvoted ? ' debate-arg-upvoted' : '';
      const isOwnSide = mySide && a.side === mySide;
      const canUpvote = !readOnly && isOwnSide && !a.is_own && !a.has_upvoted;
      const showVotes = isOwnSide;
      return `<div class="debate-arg${aiClass}${ownClass}${upvotedClass}" ${canUpvote ? `onclick="debateUpvote('${a.id}')"` : ''}>
        <div class="debate-arg-header">
          ${a.author_avatar ? `<img src="/static/avatars/${a.author_avatar}" class="debate-arg-avatar">` : ''}
          <span class="debate-arg-author">${escDebate(a.author)}</span>
          ${showVotes ? `<span class="debate-arg-votes">▲ ${a.upvote_count}</span>` : ''}
        </div>
        <div class="debate-arg-text">${escDebate(a.text)}</div>
      </div>`;
    };

    const renderMerged = () => `<div class="debate-arg debate-arg-merged">
      <span>🤖 duplicate, merged above</span>
    </div>`;

    return `<div class="debate-columns">
      <div class="debate-col debate-col-against">
        ${againstArgs.map(renderArg).join('')}
        ${Array(mergedAgainstCount).fill('').map(renderMerged).join('')}
      </div>
      <div class="debate-col debate-col-for">
        ${forArgs.map(renderArg).join('')}
        ${Array(mergedForCount).fill('').map(renderMerged).join('')}
      </div>
    </div>`;
  }

  function renderDebateHints() {
    return `<div class="debate-hints">
      <div class="debate-rules-title">📋 Debate Rules</div>
      <div class="debate-hint">• Present your strongest argument first</div>
      <div class="debate-hint">• Address the opposing argument directly</div>
      <div class="debate-hint">• Give specific examples from real projects</div>
      <div class="debate-hint">• In what context does this trade-off matter most?</div>
    </div>`;
  }

  // ── Debate WS senders ──
  function debatePickSide(side) {
    if (ws) ws.send(JSON.stringify({ type: 'debate_pick_side', side }));
  }

  function debateSubmitArg() {
    const input = document.getElementById('debate-arg-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text || !ws) return;
    ws.send(JSON.stringify({ type: 'debate_argument', text }));
    input.value = '';
    const btn = document.getElementById('debate-arg-submit');
    if (btn) btn.disabled = true;
  }

  function debateUpvote(argId) {
    if (ws) ws.send(JSON.stringify({ type: 'debate_upvote', argument_id: argId }));
  }

  function debateVolunteer() {
    if (ws) ws.send(JSON.stringify({ type: 'debate_volunteer' }));
  }

  // ── Render ──
  function applyParticipantMode(mode) {
    const isConference = mode === 'conference';
    // Hide/show status bar elements
    const statusLeft = document.querySelector('.status-left');
    if (statusLeft) statusLeft.style.display = '';
    const myScore = document.getElementById('my-score');
    if (myScore) myScore.style.display = isConference ? 'none' : '';
    const locPrompt = document.getElementById('location-prompt');
    if (locPrompt) locPrompt.style.display = isConference ? 'none' : '';
    const notifBtn = document.getElementById('notif-btn');
    if (notifBtn) notifBtn.style.display = isConference ? 'none' : '';

    // Toggle emoji displays
    const emojiBar = document.getElementById('emoji-bar');
    if (emojiBar) emojiBar.style.display = isConference ? 'none' : '';
    const confGrid = document.getElementById('conference-emoji-grid');
    if (confGrid) confGrid.style.display = isConference ? '' : 'none';
    const urlDisplay = document.getElementById('conference-url-display');
    if (urlDisplay) urlDisplay.textContent = 'https://' + location.host;

    // Version tag: sit above emoji bar in workshop mode, at bottom in conference mode
    const versionTag = document.getElementById('version-tag');
    if (versionTag) versionTag.style.bottom = isConference ? '.3rem' : '';
  }

  function renderContent(voteCounts) {
    const el = document.getElementById('content');
    const confGrid = document.getElementById('conference-emoji-grid');
    // Conference mode: show emoji grid when idle, hide when activity (poll) is active
    if (currentMode === 'conference') {
      if (!currentPoll) {
        el.innerHTML = '';
        if (confGrid) confGrid.style.display = '';
        return;
      } else {
        if (confGrid) confGrid.style.display = 'none';
      }
    }
    if (!currentPoll) {
      const nameSet = (_suggestedName === null || myName !== _suggestedName);
      const locationSet = !!localStorage.getItem(LS_LOCATION_KEY);
      const notifGranted = 'Notification' in window && Notification.permission === 'granted';
      const allDone = nameSet && locationSet && notifGranted;
      const checklistHidden = isOnboardingChecklistHidden();
      el.innerHTML = `<div class="waiting">
        <div class="icon">👋</div>
        <p class="welcome-text">Welcome!</p>
        <p style="margin-top:.5rem;">Your answers and ideas will shape this session!</p>
        ${checklistHidden ? '' : `<ul id="onboarding-list" class="onboarding-checklist"${allDone ? ' style="opacity:1"' : ''}>
          <li id="onboard-name" class="onboarding-item${nameSet ? ' done' : ''}" onclick="${nameSet ? '' : 'startNameEdit()'}" style="cursor:${nameSet ? 'default' : 'pointer'}">
            <input type="checkbox" disabled ${nameSet ? 'checked' : ''}> ✏️ Click on your name to set it
          </li>
          <li id="onboard-location" class="onboarding-item${locationSet ? ' done' : ''}" onclick="${locationSet ? '' : 'requestLocation()'}" style="cursor:${locationSet ? 'default' : 'pointer'}">
            <input type="checkbox" disabled ${locationSet ? 'checked' : ''}> 📍 Share your location
          </li>
          <li id="onboard-notif" class="onboarding-item${notifGranted ? ' done' : ''}" onclick="${notifGranted ? '' : 'requestNotificationPermission()'}" style="cursor:${notifGranted ? 'default' : 'pointer'}">
            <input type="checkbox" disabled ${notifGranted ? 'checked' : ''}> 🔔 Enable browser notifications
          </li>
        </ul>`}
      </div>`;
      if (allDone && !checklistHidden) {
        markOnboardingChecklistHidden();
        setTimeout(() => {
          const list = document.getElementById('onboarding-list');
          if (list) { list.style.transition = 'opacity 3s'; list.style.opacity = '0'; }
        }, 1500);
      }
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
    if (e.key === 'Escape') closeParticipantModals();
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

  let codereviewMySelections = new Set();

  function renderCodeReviewScreen(cr) {
    if (!cr) return;

    const content = document.getElementById('content');
    codereviewMySelections = new Set(cr.my_selections || []);
    const confirmed = new Set(cr.confirmed_lines || []);
    const isSelecting = cr.phase === 'selecting';
    const isReviewing = cr.phase === 'reviewing';
    const lines = cr.snippet.split('\n');
    const percentages = cr.line_percentages || {};

    let html = '<div class="codereview-screen">';
    html += '<div class="codereview-header" style="font-size:1.3rem;">Code Review</div>';
    if (isSelecting) {
      html += '<div class="codereview-subtitle">Tap every line that has a bug, smell, or risk</div>';
      html += '<div id="cr-toast" class="qa-toast"></div>';
    } else {
      html += '<div class="codereview-subtitle">Selection closed — reviewing results</div>';
    }

    html += '<div class="codereview-viewer">';
    lines.forEach((lineText, i) => {
      const lineNum = i + 1;
      const isMine = codereviewMySelections.has(lineNum);
      const isConfirmed = confirmed.has(lineNum);
      const pct = percentages[String(lineNum)];

      let lineClass = 'codereview-pline';
      let gutterContent = String(lineNum);
      let badge = '';

      if (isConfirmed && isMine) {
        lineClass += ' codereview-pline-correct';
        gutterContent = `✓ ${lineNum}`;
        badge = '<span class="codereview-badge codereview-badge-correct">+200</span>';
      } else if (isConfirmed && !isMine) {
        lineClass += ' codereview-pline-confirmed';
        gutterContent = `✓ ${lineNum}`;
      } else if (isMine) {
        lineClass += ' codereview-pline-selected';
      }

      if (isSelecting) {
        lineClass += ' codereview-pline-clickable';
      }

      const pctBadge = isReviewing && pct !== undefined ? `<span class="codereview-pct">${pct}%</span>` : '';

      html += `<div class="${lineClass}" onclick="toggleCodeReviewLine(${lineNum})">`;
      html += `<span class="codereview-pgutter">${gutterContent}</span>`;
      html += `<span class="codereview-pcode">${escHtml(lineText) || ' '}</span>`;
      html += badge;
      html += pctBadge;
      html += '</div>';
    });
    html += '</div>';

    if (isSelecting) {
      // no footer text needed
    } else if (isReviewing) {
      const pointsEarned = [...confirmed].filter(l => codereviewMySelections.has(l)).length * 200;
      if (pointsEarned > 0) {
        html += `<div class="codereview-footer codereview-footer-points"><span class="codereview-points-earned">+${pointsEarned}</span> points earned</div>`;
      }
    }

    html += '</div>';
    content.innerHTML = html;

    // Apply syntax highlighting as a single block for consistent tokens
    if (typeof hljs !== 'undefined') {
      const codeBlock = document.createElement('code');
      codeBlock.textContent = cr.snippet;
      if (cr.language) {
        codeBlock.className = `language-${cr.language}`;
      }
      const pre = document.createElement('pre');
      pre.appendChild(codeBlock);
      hljs.highlightElement(codeBlock);

      const highlightedLines = codeBlock.innerHTML.split('\n');
      content.querySelectorAll('.codereview-pcode').forEach((el, i) => {
        if (highlightedLines[i] !== undefined) {
          el.innerHTML = highlightedLines[i] || ' ';
        }
      });
    }

    if (isSelecting) {
      _startCRToasts();
    } else {
      _stopCRToasts();
    }
  }

  function toggleCodeReviewLine(lineNum) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (codereviewMySelections.has(lineNum)) {
      ws.send(JSON.stringify({ type: 'codereview_deselect', line: lineNum }));
    } else {
      ws.send(JSON.stringify({ type: 'codereview_select', line: lineNum }));
    }
  }

  // ── Leaderboard ──────────────────────────────────────
  function showParticipantLeaderboard(data) {
    const overlay = document.getElementById('leaderboard-overlay');
    const myRankEl = document.getElementById('leaderboard-my-rank');
    const top5El = document.getElementById('leaderboard-top5');
    overlay.style.display = 'flex';
    top5El.innerHTML = '';

    // Show personal rank immediately
    myRankEl.innerHTML = `
        <div class="rank-number">#${data.your_rank || '?'}</div>
        <div class="rank-total">out of ${data.total_participants}</div>
        <div class="rank-score">${data.your_score || 0} pts</div>
    `;

    // Sequential reveal: 5th first (bottom), 1st last (top)
    const entries = data.entries || [];
    entries.forEach((e, i) => {
        const isMe = data.your_name && data.your_name === e.name;
        const isFirst = e.rank === 1;

        const div = document.createElement('div');
        div.className = 'lb-entry' + (isMe ? ' is-me' : '') + (isFirst ? ' first-place' : '');

        const avatarStyle = e.avatar && e.avatar.startsWith('letter:')
            ? `background:${e.color}` : `background:var(--surface2)`;
        const avatarContent = e.avatar && e.avatar.startsWith('letter:')
            ? e.letter : '';
        const avatarImg = e.avatar && !e.avatar.startsWith('letter:')
            ? `<img src="/static/avatars/${e.avatar}" style="width:32px;height:32px;border-radius:50%" onerror="this.style.display='none'">`
            : '';
        const universe = e.universe ? ` <span class="lb-universe">(${e.universe})</span>` : '';

        div.innerHTML = `
            <span class="lb-rank">#${e.rank}</span>
            ${avatarImg || `<span class="lb-avatar" style="${avatarStyle}">${avatarContent}</span>`}
            <span class="lb-name">${escHtml(e.name)}${universe}</span>
            <span class="lb-score">${e.score} pts</span>
        `;

        if (!avatarImg) {
            const avatarSpan = div.querySelector('.lb-avatar');
            if (avatarSpan) avatarSpan.textContent = e.letter || '??';
        }

        top5El.appendChild(div);

        const revealDelay = (entries.length - 1 - i) * 800;
        setTimeout(() => div.classList.add('visible'), 500 + revealDelay);
    });
  }

  function hideParticipantLeaderboard() {
    document.getElementById('leaderboard-overlay').style.display = 'none';
  }

  // ── Emoji bar hover bubbles + dev-reset: need full DOM ──
  document.addEventListener('DOMContentLoaded', () => {

  // Emoji hover bubbles (reuse tour-bubble style)
  (function setupEmojiBubbles() {
    let activeBubble = null;
    let showTimer = null;

    function removeBubble() {
      if (activeBubble) { activeBubble.remove(); activeBubble = null; }
      if (showTimer) { clearTimeout(showTimer); showTimer = null; }
    }

    function showBubble(btn) {
      removeBubble();
      const text = btn.dataset.tooltip;
      const emoji = btn.textContent.trim();
      if (!text) return;

      const bub = document.createElement('div');
      bub.className = 'tour-bubble emoji-hover-bubble';

      const emojiSpan = document.createElement('span');
      emojiSpan.className = 'tour-bubble-emoji';
      emojiSpan.textContent = emoji;

      const textSpan = document.createElement('span');
      textSpan.className = 'tour-bubble-text';
      textSpan.textContent = text;

      bub.appendChild(emojiSpan);
      bub.appendChild(textSpan);
      document.body.appendChild(bub);
      activeBubble = bub;

      // Position above the button
      const rect = btn.getBoundingClientRect();
      const bubW = 180;
      bub.style.width = bubW + 'px';
      bub.style.left = Math.max(8, Math.min(window.innerWidth - bubW - 8, rect.left + rect.width / 2 - bubW / 2)) + 'px';
      bub.style.top = '0px';
      requestAnimationFrame(() => {
        const bh = bub.getBoundingClientRect().height;
        bub.style.top = Math.max(8, rect.top - bh - 12) + 'px';
      });
    }

    document.querySelectorAll('#emoji-bar .emoji-btn[data-tooltip]').forEach(btn => {
      btn.addEventListener('mouseenter', () => {
        showTimer = setTimeout(() => showBubble(btn), 100);
      });
      btn.addEventListener('mouseleave', removeBubble);
      btn.addEventListener('click', removeBubble);
    });
  })();

  // Hidden dev-reset: click version tag to wipe all local state
  (function setupDevReset() {
    const vt = document.getElementById('version-tag');
    if (!vt) return;
    vt.addEventListener('click', () => {
      if (!confirm('Are you sure you want to reset your identity?')) return;
      ['workshop_participant_uuid', 'workshop_participant_name', 'workshop_custom_name',
       'workshop_vote', 'workshop_participant_location', 'workshop_tour_shown', 'workshop_onboarding_hidden', 'workshop_wc_session']
        .forEach(k => localStorage.removeItem(k));
      sessionStorage.clear();
      document.cookie.split(';').forEach(c => {
        document.cookie = c.replace(/^ +/, '').replace(/=.*/, '=;expires=' + new Date(0).toUTCString() + ';path=/');
      });
      location.reload();
    });
  })();

  }); // DOMContentLoaded
