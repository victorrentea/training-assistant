(function () {
  function createBanner(countdownSeconds, onStop, onReload) {
    const existing = document.getElementById('version-reload-banner');
    if (existing) return existing;

    const banner = document.createElement('div');
    banner.id = 'version-reload-banner';
    banner.style.cssText = [
      'position:fixed',
      'top:1.4rem',
      'right:.4rem',
      'z-index:10000',
      'background:#1f2338',
      'color:#e8eaf0',
      'border:1px solid #ffd166',
      'border-radius:8px',
      'padding:.45rem .65rem',
      'box-shadow:0 4px 14px rgba(0,0,0,.4)',
      'display:flex',
      'align-items:center',
      'gap:.5rem',
      'font:500 .78rem/1.2 Segoe UI, system-ui, sans-serif',
    ].join(';');

    const msg = document.createElement('span');
    msg.id = 'version-reload-message';
    msg.textContent = `New version detected. Reloading in ${countdownSeconds}s...`;

    const stopBtn = document.createElement('button');
    stopBtn.id = 'version-reload-stop';
    stopBtn.textContent = 'Stop';
    stopBtn.style.cssText = 'height:30px;padding:0 .65rem;border:1px solid #7b80a0;border-radius:7px;background:#252840;color:#e8eaf0;cursor:pointer;';
    stopBtn.onclick = onStop;

    const reloadBtn = document.createElement('button');
    reloadBtn.id = 'version-reload-now';
    reloadBtn.textContent = 'Reload now';
    reloadBtn.style.cssText = 'height:30px;padding:0 .65rem;border:0;border-radius:7px;background:#6c63ff;color:#fff;cursor:pointer;';
    reloadBtn.onclick = onReload;

    banner.appendChild(msg);
    banner.appendChild(stopBtn);
    banner.appendChild(reloadBtn);
    document.body.appendChild(banner);
    return banner;
  }

  function createVersionReloadGuard(opts) {
    const options = opts || {};
    const countdownStart = Number(options.countdownSeconds || 10);
    const doReload = typeof options.onReload === 'function'
      ? options.onReload
      : function () {
          // Force cache-busting so version.js is re-fetched
          var url = new URL(window.location.href);
          url.searchParams.set('_v', Date.now());
          window.location.replace(url.toString());
        };

    let active = false;
    let stopped = false;
    let remaining = countdownStart;
    let timer = null;

    function setMessage(text) {
      const el = document.getElementById('version-reload-message');
      if (el) el.textContent = text;
    }

    function clearTimer() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }

    function stopAutoReload() {
      stopped = true;
      clearTimer();
      setMessage('New version detected. Auto-reload paused.');
      const stopBtn = document.getElementById('version-reload-stop');
      if (stopBtn) stopBtn.disabled = true;
    }

    function startCountdown() {
      clearTimer();
      remaining = countdownStart;
      setMessage(`New version detected. Reloading in ${remaining}s...`);
      timer = setInterval(function () {
        remaining -= 1;
        if (remaining <= 0) {
          clearTimer();
          if (!stopped) doReload();
          return;
        }
        setMessage(`New version detected. Reloading in ${remaining}s...`);
      }, 1000);
    }

    function check(serverVersion) {
      if (!serverVersion || !window.APP_VERSION) return;
      if (String(serverVersion).trim() === String(window.APP_VERSION).trim()) return;
      if (active) return;

      active = true;
      window.__deployIncoming = true;
      window.__updateDeployAge && window.__updateDeployAge();
      var vt = document.getElementById('version-tag');
      if (vt) vt.classList.add('deploy-incoming');
      createBanner(countdownStart, stopAutoReload, doReload);
      startCountdown();
    }

    return { check };
  }

  window.createVersionReloadGuard = createVersionReloadGuard;
})();

