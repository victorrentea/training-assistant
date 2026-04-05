(function () {
  function formatElapsed(deployDate, now) {
    const deltaSec = Math.max(0, Math.floor((now.getTime() - deployDate.getTime()) / 1000));
    if (deltaSec < 60) return 'deployed ' + deltaSec + 's ago';
    if (deltaSec < 3600) return 'deployed ' + Math.floor(deltaSec / 60) + 'm ago';
    if (deltaSec < 86400) return 'deployed ' + Math.floor(deltaSec / 3600) + 'h ago';
    return 'deployed ' + Math.floor(deltaSec / 86400) + 'd ago';
  }

  function startUpdating(el, deployDate) {
    function update() {
      const prefix = window.__deployIncoming ? '\u26a0\ufe0f \uD83D\uDE80 | ' : '';
      el.textContent = prefix + formatElapsed(deployDate, new Date());
    }
    window.__updateDeployAge = update;
    update();

    // Tick every second while under 1h, then every minute while under 24h
    function schedule() {
      const ageSec = Math.floor((Date.now() - deployDate.getTime()) / 1000);
      if (ageSec >= 86400) return;
      const interval = ageSec < 3600 ? 1000 : 60000;
      setTimeout(() => { update(); schedule(); }, interval);
    }
    schedule();
  }

  function setTimestamp(el, isoTimestamp) {
    const d = new Date(isoTimestamp);
    if (isNaN(d.getTime())) return;
    startUpdating(el, d);
  }

  let _deployInfoCache = null;
  async function _fetchDeployInfo() {
    if (_deployInfoCache !== null) return _deployInfoCache;
    try {
      const r = await fetch('/static/deploy-info.json?_nc=' + Date.now());
      _deployInfoCache = await r.json();
    } catch (e) {
      _deployInfoCache = {};
    }
    return _deployInfoCache;
  }

  function _attachBranchTooltip(el) {
    if (!el || el._branchTipAttached) return;
    el._branchTipAttached = true;
    el.style.cursor = 'help';

    let popup = null;

    el.addEventListener('mouseenter', async () => {
      if (!popup) {
        popup = document.createElement('div');
        popup.style.cssText = [
          'position:fixed',
          'background:var(--surface2,#252840)',
          'border:1px solid var(--border,#2e3250)',
          'border-radius:8px',
          'padding:.55rem .8rem',
          'font:500 .75rem/1.6 Segoe UI,system-ui,sans-serif',
          'color:var(--text,#e8eaf0)',
          'z-index:9999',
          'box-shadow:0 4px 14px rgba(0,0,0,.45)',
          'pointer-events:none',
          'min-width:380px',
          'display:none',
        ].join(';');
        document.body.appendChild(popup);
      }

      const rect = el.getBoundingClientRect();
      popup.style.top = '';
      popup.style.bottom = (window.innerHeight - rect.top + 4) + 'px';
      popup.style.right = (window.innerWidth - rect.right) + 'px';

      const info = await _fetchDeployInfo();
      const commits = (info && info.commits) || [];
      const sha = info && info.sha ? info.sha.slice(0, 8) : '';
      if (!commits.length && !sha) return;

      const fmtAge = ts => {
        const sec = Math.max(0, Math.floor((Date.now() - new Date(ts).getTime()) / 1000));
        if (sec < 60) return sec + 's ago';
        if (sec < 3600) return Math.floor(sec / 60) + 'm ago';
        if (sec < 86400) return Math.floor(sec / 3600) + 'h ago';
        return Math.floor(sec / 86400) + 'd ago';
      };
      let html = sha
        ? `<div style="font-family:monospace;font-size:.7rem;color:var(--muted,#7b80a0);margin-bottom:.4rem;padding-bottom:.3rem;border-bottom:1px solid var(--border,#2e3250)">${sha}</div>`
        : '';
      html += commits.map(c =>
        `<div style="display:flex;justify-content:space-between;gap:1.2rem;align-items:baseline">` +
        `<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:280px" title="${c.msg.replace(/"/g,'&quot;')}">${c.msg}</span>` +
        `<span style="color:var(--muted,#7b80a0);flex-shrink:0;font-size:.7rem;font-family:monospace">${fmtAge(c.ts)}</span>` +
        `</div>`
      ).join('');

      popup.innerHTML = html;
      popup.style.display = 'block';
    });

    el.addEventListener('mouseleave', () => {
      if (popup) popup.style.display = 'none';
    });
  }

  /**
   * renderDeployAge(tagId, opts)
   *
   * Fetches daemon_code_timestamp from /api/status and renders "deployed Xm ago".
   * Falls back to window.APP_VERSION (Railway startup time) if no daemon timestamp available.
   *
   * opts.statusUrl — override the status endpoint (default: /api/status)
   */
  window.renderDeployAge = function(tagId, opts) {
    const el = document.getElementById(tagId || 'version-tag');
    if (!el) return;
    _attachBranchTooltip(el);

    const statusUrl = (opts && opts.statusUrl) || '/api/status';

    fetch(statusUrl + '?_nc=' + Date.now())
      .then(r => r.json())
      .then(data => {
        const ts = data.daemon_code_timestamp || data.code_timestamp;
        if (ts) {
          setTimestamp(el, ts);
        } else if (window.APP_VERSION) {
          el.textContent = window.APP_VERSION || 'dev';
        } else {
          el.textContent = 'dev';
        }
      })
      .catch(() => {
        el.textContent = window.APP_VERSION || 'dev';
      });
  };
})();
