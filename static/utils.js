/** HTML-escape a string */
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/** HTML-escape a string and render `backticked` substrings as <code>…</code>. Unmatched backticks are kept literal. */
function escHtmlWithCode(s) {
  const str = String(s);
  const out = [];
  const re = /`([^`]+)`/g;
  let lastIdx = 0;
  let m;
  while ((m = re.exec(str)) !== null) {
    out.push(escHtml(str.slice(lastIdx, m.index)));
    out.push('<code>' + escHtml(m[1]) + '</code>');
    lastIdx = m.index + m[0].length;
  }
  out.push(escHtml(str.slice(lastIdx)));
  return out.join('');
}

/** Send a typed message over WebSocket */
function sendWS(type, payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type, ...payload }));
  }
}

/** POST to participant REST API (identity endpoints) */
function participantApi(path, body) {
  return fetch(`/${sessionId}/api/participant/${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Participant-ID': myUUID
    },
    body: JSON.stringify(body)
  });
}

/** Enable or disable a button with opacity feedback */
function setButtonEnabled(btn, enabled) {
  if (!btn) return;
  btn.disabled = !enabled;
  btn.style.opacity = enabled ? '' : '0.4';
}

/** Toggle a modal overlay open/closed */
function toggleModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('open');
}

/** Close a modal overlay */
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}

/** Open a modal overlay */
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}
