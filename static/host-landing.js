'use strict';

async function loadPage() {
  try {
    const [activeRes, foldersRes] = await Promise.all([
      fetch('/api/session/active'),
      fetch('/api/session/folders'),
    ]);
    const active = await activeRes.json();
    const {folders} = await foldersRes.json();
    renderPage(active, folders);
  } catch (e) {
    document.getElementById('app').innerHTML =
      '<div style="color:var(--danger);text-align:center;padding:2rem;">Failed to load session info. Please reload.</div>';
  }
}

function renderPage(active, folders) {
  const app = document.getElementById('app');
  const today = new Date().toISOString().slice(0, 10);

  let rejoinHtml = '';
  if (active && active.active && active.session_id) {
    const name = active.session_name || active.session_id;
    rejoinHtml = `
      <div class="rejoin-section">
        <div class="rejoin-label">Active session</div>
        <button class="rejoin-btn" onclick="rejoinSession(${JSON.stringify(active.session_id)})">
          Rejoin: ${_esc(name)}
        </button>
      </div>`;
  }

  const todayFolders = (folders || []).filter(f => f.startsWith(today));
  let todayHtml = '';
  if (todayFolders.length > 0) {
    const btns = todayFolders.map(f => {
      const suffix = f.slice(today.length).replace(/^\s+/, '') || f;
      return `<button class="today-resume-btn" onclick="doResumeFolder(${JSON.stringify(f)})">▶ ${_esc(suffix)}</button>`;
    }).join('');
    todayHtml = `
      <div class="today-section">
        <div class="today-label">Resume today</div>
        ${btns}
      </div>`;
  }

  const folderListHtml = buildFolderList(folders);

  app.innerHTML = `
    <div class="landing-card">
      <div class="landing-title">Start Session</div>
      ${rejoinHtml}
      ${todayHtml}
      <div class="new-session-label">New session</div>
      <div class="session-name-row">
        <span class="session-date-prefix">${new Date().toISOString().slice(0, 10)}&nbsp;</span>
        <input id="session-name-input" class="session-name-input" type="text"
               placeholder="session name"
               autocomplete="off"
               oninput="onNameInput()"
               onkeydown="if(event.key==='Enter' && !document.getElementById('create-btn').disabled) doCreate();" />
      </div>
      <div class="create-btns-row">
        <button id="create-btn-workshop" class="create-btn" onclick="doCreate('workshop')" disabled>🎓 Start workshop</button>
        <button id="create-btn-talk" class="create-btn create-btn-talk" onclick="doCreate('talk')" disabled>🎙️ Start talk</button>
      </div>
      <div id="create-error" class="error-msg" style="display:none;"></div>
    </div>
    ${folderListHtml}
  `;

  // Focus the name input
  const input = document.getElementById('session-name-input');
  if (input) input.focus();
}

function buildFolderList(folders) {
  if (!folders || folders.length === 0) {
    return `
      <div class="folders-card">
        <div class="folders-header">Previous sessions</div>
        <div class="folders-empty">No previous sessions found.</div>
      </div>`;
  }

  const items = folders.map(f => {
    const m = f.match(/^(\d{4}-\d{2}-\d{2})\s+(.+)$/);
    const date = m ? m[1] : '';
    const topic = m ? m[2] : f;
    return `
    <li class="folder-row" onclick="doResumeFolder(${JSON.stringify(f)})">
      <span class="folder-date">${_esc(date)}</span>
      <span class="folder-topic">${_esc(topic)}</span>
      <button class="folder-play-btn" onclick="event.stopPropagation(); doResumeFolder(${JSON.stringify(f)})" title="Resume session">▶</button>
    </li>`;
  }).join('');

  return `
    <div class="folders-card">
      <div class="folders-header">Previous sessions</div>
      <ul class="folder-list">${items}</ul>
    </div>`;
}

function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function onNameInput() {
  const input = document.getElementById('session-name-input');
  const hasName = !!input.value.trim();
  document.getElementById('create-btn-workshop').disabled = !hasName;
  document.getElementById('create-btn-talk').disabled = !hasName;
}

function onSessionReady(session_id) {
  window.location = '/host/' + session_id;
}

function rejoinSession(session_id) {
  onSessionReady(session_id);
}

async function doCreate(type) {
  const input = document.getElementById('session-name-input');
  const prefixEl = document.querySelector('.session-date-prefix');
  const prefix = prefixEl ? prefixEl.textContent : '';
  const name = (prefix + input.value).trim();
  if (!name) return;

  const btn = document.getElementById('create-btn-' + type);
  btn.disabled = true;

  const errEl = document.getElementById('create-error');
  if (errEl) errEl.style.display = 'none';

  try {
    const r = await fetch('/api/session/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, type}),
    });
    const data = await r.json();
    if (r.ok && data.session_id) {
      onSessionReady(data.session_id);
    } else {
      const msg = data.detail || data.error || 'Failed to create session.';
      if (errEl) { errEl.textContent = msg; errEl.style.display = ''; }
      btn.disabled = false;
    }
  } catch (e) {
    if (errEl) { errEl.textContent = 'Network error — please retry.'; errEl.style.display = ''; }
    btn.disabled = false;
  }
}

async function doResumeFolder(folder_name) {
  try {
    const r = await fetch('/api/session/resume-folder', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({folder_name}),
    });
    const data = await r.json();
    if (r.ok && data.session_id) {
      onSessionReady(data.session_id);
    } else {
      alert('Failed to resume session: ' + (data.detail || data.error || 'unknown error'));
    }
  } catch (e) {
    alert('Network error resuming session.');
  }
}

loadPage();
