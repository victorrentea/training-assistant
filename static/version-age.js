(function () {
  function parseVersionTimestamp(raw) {
    if (!raw || typeof raw !== 'string') return null;
    const m = raw.trim().match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$/);
    if (!m) return null;
    const year = Number(m[1]);
    const month = Number(m[2]) - 1;
    const day = Number(m[3]);
    const hour = Number(m[4]);
    const minute = Number(m[5]);
    const dt = new Date(year, month, day, hour, minute, 0, 0);
    return Number.isNaN(dt.getTime()) ? null : dt;
  }

  function formatElapsed(deployDate, now) {
    const deltaSec = Math.max(0, Math.floor((now.getTime() - deployDate.getTime()) / 1000));
    if (deltaSec < 60) return 'deployed ' + deltaSec + 's ago';
    if (deltaSec < 3600) return 'deployed ' + Math.floor(deltaSec / 60) + 'm ago';
    if (deltaSec < 86400) return 'deployed ' + Math.floor(deltaSec / 3600) + 'h ago';
    return 'deployed ' + Math.floor(deltaSec / 86400) + 'd ago';
  }

  function formatBuiltAt(deployDate) {
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const hh = String(deployDate.getHours()).padStart(2, '0');
    const mm = String(deployDate.getMinutes()).padStart(2, '0');
    return 'built at ' + deployDate.getDate() + ' ' + months[deployDate.getMonth()] + ' ' + hh + ':' + mm;
  }

  function renderDeployAge(tagId) {
    const el = document.getElementById(tagId || 'version-tag');
    if (!el) return;

    const parsed = parseVersionTimestamp(window.APP_VERSION);
    if (!parsed) {
      el.textContent = window.APP_VERSION || 'dev';
      return;
    }

    const builtAt = ' | ' + formatBuiltAt(parsed);

    function update() {
      const prefix = window.__deployIncoming ? '\u26a0\ufe0f \uD83D\uDE80 | ' : '';
      el.textContent = prefix + formatElapsed(parsed, new Date()) + builtAt;
    }
    window.__updateDeployAge = update;
    update();
    const ageSec = Math.floor((Date.now() - parsed.getTime()) / 1000);
    if (ageSec < 86400) setInterval(update, 60000);
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
      popup.style.top = (rect.bottom + 4) + 'px';
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

  const _origRenderDeployAge = renderDeployAge;
  window.renderDeployAge = function(tagId) {
    _origRenderDeployAge(tagId);
    const el = document.getElementById(tagId || 'version-tag');
    _attachBranchTooltip(el);
  };
})();

