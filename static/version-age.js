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

    const workHours = window.WORK_HOURS;
    const workSuffix = workHours ? ' | total: ' + workHours + 'h with Santa \uD83C\uDF85' : '';
    const builtAt = ' | ' + formatBuiltAt(parsed);

    function update() {
      const prefix = window.__deployIncoming ? '\u26a0\ufe0f \uD83D\uDE80 | ' : '';
      el.textContent = prefix + formatElapsed(parsed, new Date()) + builtAt + workSuffix;
    }
    window.__updateDeployAge = update;
    update();
    const ageSec = Math.floor((Date.now() - parsed.getTime()) / 1000);
    if (ageSec < 86400) setInterval(update, 60000);
  }

  window.renderDeployAge = renderDeployAge;
})();

