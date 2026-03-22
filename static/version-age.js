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
    const hh = String(deployDate.getHours()).padStart(2, '0');
    const mm = String(deployDate.getMinutes()).padStart(2, '0');
    const sameDay = deployDate.getFullYear() === now.getFullYear()
      && deployDate.getMonth() === now.getMonth()
      && deployDate.getDate() === now.getDate();
    if (sameDay) return 'deployed ' + hh + ':' + mm;
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return 'deployed on ' + deployDate.getDate() + ' ' + months[deployDate.getMonth()] + ' ' + hh + ':' + mm;
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
    el.textContent = formatElapsed(parsed, new Date()) + workSuffix;
  }

  window.renderDeployAge = renderDeployAge;
})();

