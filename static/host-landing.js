'use strict';

async function loadPage() {
  try {
    const [activeRes, foldersRes] = await Promise.all([
      fetch('/api/session/active'),
      fetch('/api/session/folders', {credentials: 'include'}),
    ]);
    const active = await activeRes.json();
    const {folders} = await foldersRes.json();
    if (active && active.session_id) {
      onSessionReady(active.session_id);
      return;
    }
    renderPage(folders);
  } catch (e) {
    document.getElementById('app').innerHTML =
      '<div style="color:var(--danger);text-align:center;padding:2rem;">Failed to load session info. Please reload.</div>';
  }
}

function renderPage(folders) {
  const app = document.getElementById('app');
  const today = new Date().toISOString().slice(0, 10);

  const folderListHtml = buildFolderList(folders, today);

  app.innerHTML = `
    <div class="landing-card">
      <div class="new-session-label">NEW WORKSHOP</div>
      <div class="session-name-row">
        <input id="session-date-input" class="session-date-prefix" type="text"
               value="${new Date().toISOString().slice(0, 10)}"
               autocomplete="off" spellcheck="false" />
        <input id="session-name-input" class="session-name-input" type="text"
               placeholder="Workshop name at company"
               autocomplete="off"
               oninput="onNameInput()"
               onkeydown="if(event.key==='Enter' && !document.getElementById('create-btn-workshop').disabled) doCreate('workshop');" />
        <button id="create-btn-workshop" class="create-btn create-btn-workshop" onclick="doCreate('workshop')" disabled data-tip="New workshop">▶</button>
      </div>
      <div id="create-error" class="error-msg" style="display:none;"></div>
    </div>
    ${folderListHtml}
  `;

  // Focus the name input
  const input = document.getElementById('session-name-input');
  if (input) input.focus();
}

function buildFolderList(folders, today) {
  if (!folders || folders.length === 0) {
    return `
      <div class="folders-card">
        <div class="folders-header">RESUME WORKSHOP</div>
        <div class="folders-empty">No previous sessions found.</div>
      </div>`;
  }

  const items = folders.map(f => {
    const folderName = f.name || f;
    const sessionType = f.session_type || null;
    const typeIcon = sessionType === 'talk' ? '🎙️' : '👨‍🏫';
    const {dateStr, dates, topic} = parseFolderDates(folderName);
    const isToday = today && dates.includes(today);
    const todayTag = isToday ? `<span class="folder-today-tag">TODAY</span>` : '';
    return `
    <li class="folder-row${isToday ? ' folder-row-today' : ''}" onclick='doResumeFolder(${JSON.stringify(folderName)})'>
      <span class="folder-date">${_esc(dateStr)}</span>
      <span class="folder-topic">${_esc(topic)}${todayTag}</span>
      <span class="folder-type-icon">${typeIcon}</span>
      <button class="folder-play-btn" onclick='event.stopPropagation(); doResumeFolder(${JSON.stringify(folderName)})' data-tip="Resume session">▶</button>
    </li>`;
  }).join('');

  return `
    <div class="folders-card">
      <div class="folders-header">RESUME WORKSHOP</div>
      <ul class="folder-list">${items}</ul>
    </div>`;
}

// Folder names start with a date prefix, then the topic:
//   2026-09-15 T | 2026-09-14..15 T | 2026-08-31..1 T (rolls into next month)
//   2026-09-4+9 T (two separate days) | 2026-08-31..09-01 T | 2026-12-31..2027-01-02 T
// Days may have one or two digits. Mirrors daemon/config.py::parse_session_folder_dates.
const FOLDER_DATE_RE = /^((\d{4})-(\d{2})-(\d{1,2})(?:(\.\.|\+)(?:(\d{4})-(\d{2})-(\d{1,2})|(\d{2})-(\d{1,2})|(\d{1,2})))?)(?:\s+(.+))?$/;

function parseFolderDates(f) {
  const m = f.match(FOLDER_DATE_RE);
  if (!m) return {dateStr: '', dates: [], topic: f};
  const [, dateStr, y, mo, d, sep, ey, em, ed, em2, ed2, ed3, topic] = m;
  const start = Date.UTC(+y, +mo - 1, +d);
  let end = start;
  if (ey) {
    end = Date.UTC(+ey, +em - 1, +ed);
  } else if (em2) {
    end = Date.UTC(+y, +em2 - 1, +ed2);
    if (end < start) end = Date.UTC(+y + 1, +em2 - 1, +ed2);
  } else if (ed3) {
    end = Date.UTC(+y, +mo - 1, +ed3);
    if (end <= start) end = Date.UTC(+y, +mo, +ed3);  // bare day ≤ start day: next month
  }
  const DAY = 86400000;
  const iso = t => new Date(t).toISOString().slice(0, 10);
  const dates = [];
  if (sep === '+' || end < start) {
    dates.push(iso(start), iso(end));
  } else {
    for (let t = start; t <= end && dates.length < 62; t += DAY) dates.push(iso(t));
  }
  return {dateStr, dates, topic: topic || ''};
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
}

function showSessionBlocker(message) {
  let el = document.getElementById('session-blocker');
  if (!el) {
    el = document.createElement('div');
    el.id = 'session-blocker';
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.style.display = 'flex';
}

function onSessionReady(session_id) {
  window.location = '/host/' + session_id;
}

async function doCreate(type) {
  const input = document.getElementById('session-name-input');
  const dateInput = document.getElementById('session-date-input');
  const dateVal = dateInput ? dateInput.value.trim() : '';
  const name = (dateVal ? dateVal + ' ' : '') + input.value.trim();
  if (!name) return;

  const btn = document.getElementById('create-btn-' + type);
  btn.disabled = true;
  showSessionBlocker('Starting workshop…');

  const errEl = document.getElementById('create-error');
  if (errEl) errEl.style.display = 'none';

  try {
    const r = await fetch('/api/session/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'include',
      body: JSON.stringify({name, type}),
    });
    const data = await r.json();
    if (r.ok && data.session_id) {
      onSessionReady(data.session_id);
    } else {
      const msg = data.detail || data.error || 'Failed to create session.';
      if (errEl) { errEl.textContent = msg; errEl.style.display = ''; }
      btn.disabled = false;
      const blocker = document.getElementById('session-blocker');
      if (blocker) blocker.style.display = 'none';
    }
  } catch (e) {
    if (errEl) { errEl.textContent = 'Network error — please retry.'; errEl.style.display = ''; }
    btn.disabled = false;
    const blocker = document.getElementById('session-blocker');
    if (blocker) blocker.style.display = 'none';
  }
}

async function doResumeFolder(folder_name) {
  showSessionBlocker('Resuming session…');
  try {
    const r = await fetch('/api/session/resume', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'include',
      body: JSON.stringify({folder: folder_name}),
    });
    const data = await r.json();
    if (r.ok && data.session_id) {
      onSessionReady(data.session_id);
    } else {
      const blocker = document.getElementById('session-blocker');
      if (blocker) blocker.style.display = 'none';
      const msg = data.message || data.detail || data.error || 'unknown error';
      alert('Failed to resume session: ' + msg);
    }
  } catch (e) {
    const blocker = document.getElementById('session-blocker');
    if (blocker) blocker.style.display = 'none';
    alert('Network error resuming session.');
  }
}

loadPage();
