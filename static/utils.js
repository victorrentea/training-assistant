/** HTML-escape a string */
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/** Send a typed message over WebSocket */
function sendWS(type, payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type, ...payload }));
  }
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
