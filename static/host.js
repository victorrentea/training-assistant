  let ws = null;
  let currentPoll = null;
  let pollActive = false;
  let voteCounts = {};
  let totalVotes = 0;
  let participantLocations = {};

  // Set participant link
  const link = `${location.protocol}//${location.host}/`;
  document.getElementById('participant-link').href = link;
  document.getElementById('participant-link').textContent = link;

  // ── WebSocket (host monitors state too) ──
  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/__host__`);

    ws.onopen = () => setBadge(true);
    ws.onclose = () => { setBadge(false); setTimeout(connectWS, 3000); };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'state') {
        currentPoll = msg.poll;
        pollActive = msg.poll_active;
        voteCounts = msg.vote_counts || {};
        totalVotes = Object.values(voteCounts).reduce((a,b)=>a+b,0);
        participantLocations = msg.participant_locations || {};
        document.getElementById('pax-count').textContent = msg.participant_count;
        renderParticipantList(msg.participant_names || []);
        renderPollDisplay();
      } else if (msg.type === 'vote_update') {
        voteCounts = msg.vote_counts || {};
        totalVotes = msg.total_votes || 0;
        renderBars();
      } else if (msg.type === 'participant_count') {
        document.getElementById('pax-count').textContent = msg.count;
        participantLocations = msg.locations || participantLocations;
        renderParticipantList(msg.names || []);
      }
    };
  }

  function setBadge(ok) {
    const b = document.getElementById('ws-badge');
    b.textContent = ok ? '● Connected' : '● Disconnected';
    b.className = `badge ${ok ? 'connected' : 'disconnected'}`;
  }

  function renderParticipantList(names) {
    const ul = document.getElementById('pax-list');
    ul.innerHTML = names.map(n => {
      const loc = participantLocations[n];
      return `<li>${n}${loc ? `<span class="pax-location">${loc}</span>` : ''}</li>`;
    }).join('');
  }

  // ── QR code ──
  const style = getComputedStyle(document.documentElement);
  new QRCode(document.getElementById('qr-code'), {
    text: link,
    width: 200,
    height: 200,
    colorDark: style.getPropertyValue('--text').trim(),
    colorLight: style.getPropertyValue('--surface').trim(),
  });

  // Fullscreen QR overlay
  const qrSize = Math.min(window.innerWidth, window.innerHeight) * 0.8;
  new QRCode(document.getElementById('qr-fullscreen'), {
    text: link,
    width: qrSize,
    height: qrSize,
    colorDark: '#000000',
    colorLight: '#ffffff',
  });
  document.getElementById('qr-overlay-url').textContent = link;

  document.getElementById('qr-code').addEventListener('click', () => {
    document.getElementById('qr-overlay').classList.add('open');
  });

  function closeQR() {
    document.getElementById('qr-overlay').classList.remove('open');
  }

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeQR();
  });

  // ── Create poll ──
  document.getElementById('create-btn').addEventListener('click', async () => {
    const question = document.getElementById('q-input').value.trim();
    const options = document.getElementById('opts-input').value
      .split('\n').map(s => s.trim()).filter(Boolean);

    if (!question) { toast('Enter a question'); return; }
    if (options.length < 2) { toast('Add at least 2 options'); return; }

    const multi = document.getElementById('multi-check').checked;
    const res = await fetch('/api/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, options, multi }),
    });
    if (res.ok) {
      await setPollStatus(true);
      toast('Poll created & opened ✓');
      document.getElementById('q-input').value = '';
      document.getElementById('opts-input').value = '';
      document.getElementById('multi-check').checked = false;
      autoResize();
    } else {
      const err = await res.json();
      toast(err.detail || 'Error');
    }
  });

  // ── Open / close / clear ──
  async function setPollStatus(open) {
    await fetch('/api/poll/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ open }),
    });
  }

  async function clearPoll() {
    if (!confirm('Remove current poll?')) return;
    await fetch('/api/poll', { method: 'DELETE' });
  }

  // ── Render ──
  function renderPollDisplay() {
    const el = document.getElementById('poll-display');
    if (!currentPoll) {
      el.innerHTML = `<p class="no-poll">No poll yet — create one above.</p>`;
      return;
    }

    const statusLabel = pollActive ? 'open' : (totalVotes > 0 ? 'closed' : 'draft');
    const statusText  = pollActive ? 'Voting open' : (totalVotes > 0 ? 'Voting closed' : 'Not started');

    const bars = currentPoll.options.map((opt, i) => {
      const count = voteCounts[opt.id] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const maxCount = Math.max(...Object.values(voteCounts));
      const leading = count === maxCount && count > 0 ? 'leading' : '';
      return `
        <div class="result-row" data-id="${opt.id}">
          <div class="result-label">
            <span>${opt.text}</span>
            <span class="pct">${count} vote${count!==1?'s':''} · ${pct}%</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill ${leading}" style="width:${pct}%"></div>
          </div>
        </div>`;
    }).join('');

    el.innerHTML = `
      <span class="status-pill ${statusLabel}">${statusText}</span>
      <p class="poll-question">${currentPoll.question}</p>
      ${bars}
      <p style="font-size:.8rem; color:var(--muted); margin-top:.5rem;">${totalVotes} total vote${totalVotes!==1?'s':''}</p>
      <div class="btn-row">
        ${!pollActive
          ? `<button class="btn btn-success" onclick="setPollStatus(true)">▶ Open voting</button>`
          : `<button class="btn btn-warn"    onclick="setPollStatus(false)">⏹ Close voting</button>`}
        <button class="btn btn-danger" onclick="clearPoll()">🗑 Remove poll</button>
      </div>`;
  }

  function renderBars() {
    if (!currentPoll) return;
    const maxCount = Math.max(...Object.values(voteCounts), 0);
    currentPoll.options.forEach(opt => {
      const row = document.querySelector(`.result-row[data-id="${opt.id}"]`);
      if (!row) return;
      const count = voteCounts[opt.id] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const fill = row.querySelector('.bar-fill');
      const pctEl = row.querySelector('.pct');
      if (fill) {
        fill.style.width = `${pct}%`;
        fill.className = `bar-fill ${count === maxCount && count > 0 ? 'leading' : ''}`;
      }
      if (pctEl) pctEl.textContent = `${count} vote${count!==1?'s':''} · ${pct}%`;
    });
    const totalEl = document.querySelector('#poll-display p[style]');
    if (totalEl) totalEl.textContent = `${totalVotes} total vote${totalVotes!==1?'s':''}`;
  }

  function toast(msg) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 2500);
  }

  // ── Auto-resize options textarea ──
  const optsInput = document.getElementById('opts-input');
  function autoResize() {
    optsInput.style.height = 'auto';
    optsInput.style.height = optsInput.scrollHeight + 'px';
  }
  optsInput.addEventListener('input', autoResize);
  optsInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      document.getElementById('create-btn').click();
    }
  });
  autoResize();

  connectWS();
