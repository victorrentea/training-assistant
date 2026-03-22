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
    if (deltaSec < 60) return deltaSec + 's ago';
    if (deltaSec < 3600) return Math.floor(deltaSec / 60) + 'm ago';
    if (deltaSec < 86400) return Math.floor(deltaSec / 3600) + 'h ago';
    return 'from ' + window.APP_VERSION;
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
    const workSuffix = workHours ? ' | built in ' + workHours + ' hours' : '';

    function update() {
      const now = new Date();
      el.textContent = formatElapsed(parsed, now) + workSuffix;
      const ageSec = Math.floor((now.getTime() - parsed.getTime()) / 1000);
      if (ageSec >= 86400 && timer) {
        clearInterval(timer);
        timer = null;
      }
    }

    let timer = null;
    update();
    const initialAgeSec = Math.floor((Date.now() - parsed.getTime()) / 1000);
    if (initialAgeSec < 86400) {
      timer = setInterval(update, 1000);
    }
  }

  window.renderDeployAge = renderDeployAge;
})();

