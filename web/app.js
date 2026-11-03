// SLATE live view: start a task, stream its events, render steps, receipts, egress and approvals.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { taskId: null, steps: new Map(), selected: null, egress: 0, es: null };

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const short = (h) => (h ? String(h).replace(/^ed25519:/, '').slice(0, 12) : '');

  function setStatus(msg, live) {
    $('status').textContent = msg;
    $('statusline').classList.toggle('live', !!live);
  }

  function alertBanner(level, title, detail) {
    const el = document.createElement('div');
    el.className = 'alert ' + (level === 'red' ? 'red' : 'amber');
    el.innerHTML = `<div class="icon">${level === 'red' ? '[!]' : '[?]'}</div><div><div class="t">${esc(title)}</div>${detail ? `<div class="d">${esc(detail)}</div>` : ''}</div>`;
    $('alerts').prepend(el);
  }

  // Pretty-print JSON with syntax colours; hash, prev_hash and sig lines are highlighted.
  function renderJSON(obj) {
    const json = JSON.stringify(obj, null, 2);
    const html = esc(json).replace(
      /(&quot;(?:\\.|[^&\\]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
      (m, str, colon, lit) => {
        if (str) return colon ? `<span class="k">${str}</span>${colon}` : `<span class="s">${str}</span>`;
        if (lit) return `<span class="b">${m}</span>`;
        return `<span class="n">${m}</span>`;
      }
    );
    return html
      .split('\n')
      .map((line) => (/<span class="k">&quot;(hash|prev_hash|sig|chain_root)&quot;<\/span>/.test(line) ? `<span class="hl">${line}</span>` : line))
      .join('\n');
  }

  function selectStep(n) {
    const s = state.steps.get(n);
    if (!s) return;
    state.selected = n;
    document.querySelectorAll('.card').forEach((c) => c.classList.toggle('selected', Number(c.dataset.step) === n));
    $('receipt').innerHTML = renderJSON(s.receipt);
    $('receipt-step').textContent = 'step ' + n;
  }

  function actionText(a) {
    if (!a) return '';
    const { type, ...rest } = a;
    const parts = Object.entries(rest).map(([k, v]) => `${k}=${typeof v === 'string' ? JSON.stringify(v) : JSON.stringify(v)}`);
    return `${type}(${parts.join(', ')})`;
  }

  function addStep(ev) {
    const r = ev.receipt || {};
    const n = r.step;
    $('empty')?.remove();
    state.steps.set(n, { receipt: r, screenshot: ev.screenshot_url });

    const v = r.verifier || {};
    const verdict = (v.verdict || '').toLowerCase();
    const badges = [];
    if (verdict === 'confirmed') badges.push(`<span class="badge green">VERIFIED ${v.confidence != null ? Math.round(v.confidence * 100) + '%' : ''}</span>`);
    else if (verdict === 'refuted') badges.push(`<span class="badge red">REFUTED ${v.confidence != null ? Math.round(v.confidence * 100) + '%' : ''}</span>`);
    else if (verdict) badges.push(`<span class="badge amber">${esc(verdict.toUpperCase())}</span>`);
    const flagged = r.safety && r.safety.injection_detected;
    if (flagged) badges.push('<span class="badge red">INJECTION FLAGGED</span>');
    const blocked = (r.containment && r.containment.egress_blocked) || [];
    if (blocked.length) badges.push(`<span class="badge red">EGRESS BLOCKED x${blocked.length}</span>`);
    if (r.hash) badges.push(`<span class="badge hash">#${esc(short(r.hash))}</span>`);

    const card = document.createElement('div');
    card.className = 'card' + (flagged || blocked.length ? ' flagged' : '');
    card.dataset.step = n;
    card.innerHTML = `
      <div class="num">${String(n).padStart(2, '0')}<small>STEP</small></div>
      <div>
        <div class="intent">${esc(r.intent || '')}</div>
        <div class="action">${esc(actionText(r.action))}</div>
        ${r.observation && r.observation.url ? `<div class="url">${esc(r.observation.url)}</div>` : ''}
        <div class="badges">${badges.join('')}</div>
      </div>
      ${ev.screenshot_url ? `<div class="thumb" style="background-image:url('${esc(ev.screenshot_url)}')" title="Click to enlarge"></div>` : '<div class="thumb none">no screenshot</div>'}`;
    card.addEventListener('click', (e) => {
      if (e.target.classList.contains('thumb') && ev.screenshot_url) openLightbox(ev.screenshot_url);
      selectStep(n);
    });
    $('feed').appendChild(card);
    $('stepcount').textContent = state.steps.size + (state.steps.size === 1 ? ' step' : ' steps');
    $('take').textContent = 'TAKE ' + String(n).padStart(2, '0');
    selectStep(n);
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function addEgress(ev) {
    const li = document.createElement('li');
    li.className = ev.allowed ? 'ok' : 'no';
    li.innerHTML = `<span class="m">${esc(ev.method || 'GET')}</span><span class="h">${esc(ev.host || '')}</span><span class="v">${ev.allowed ? 'ALLOWED' : 'BLOCKED'}</span>`;
    $('egress').prepend(li);
    state.egress += 1;
    $('egress-count').textContent = state.egress + (state.egress === 1 ? ' request' : ' requests');
  }

  function openLightbox(src) {
    $('lightbox-img').src = src;
    $('lightbox').classList.add('show');
  }
  $('lightbox').addEventListener('click', () => $('lightbox').classList.remove('show'));

  function showApproval(ev) {
    $('approval-summary').textContent = ev.summary || 'The agent wants to take a final action.';
    const img = $('approval-shot');
    if (ev.screenshot_url) { img.src = ev.screenshot_url; img.style.display = ''; } else { img.style.display = 'none'; }
    const v = ev.verifier || {};
    $('approval-verifier').innerHTML = `<b>Independent verifier:</b> ${esc(v.claim || '')} <span class="badge ${String(v.verdict).toLowerCase() === 'confirmed' ? 'green' : 'red'}">${esc(String(v.verdict || 'n/a').toUpperCase())}${v.confidence != null ? ' ' + Math.round(v.confidence * 100) + '%' : ''}</span>`;
    $('approval').classList.add('show');
    setStatus('Waiting for a human. The approval is signed into the receipt.', true);
  }

  async function decide(approved) {
    $('approve').disabled = $('reject').disabled = true;
    try {
      await fetch(`/api/tasks/${state.taskId}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approved }) });
      $('approval').classList.remove('show');
      setStatus(approved ? 'Approved. Executing the final action.' : 'Rejected. The agent will stop.', true);
    } catch (e) {
      alertBanner('red', 'Approval failed', e.message);
    } finally {
      $('approve').disabled = $('reject').disabled = false;
    }
  }
  $('approve').addEventListener('click', () => decide(true));
  $('reject').addEventListener('click', () => decide(false));

  function showFinal(ev) {
    const f = ev.final || {};
    const td = f.teardown || {};
    const rows = [
      ['Total steps', f.total_steps],
      ['Chain root', f.chain_root],
      ['Approval', f.approval ? (f.approval.approved ? 'approved' : 'rejected') + (f.approval.ts ? ' at ' + f.approval.ts : '') : 'none'],
      ['Sandbox', td.sandbox_id || f.sandbox_id],
      ['Teardown', td.destroyed === true ? 'destroyed, nothing left running' : td.destroyed === false ? 'NOT confirmed' : (td.status || '')],
      ['Signed by', f.pubkey],
    ].filter(([, v]) => v !== undefined && v !== null && v !== '');
    $('final-grid').innerHTML = rows.map(([k, v]) => `<div>${esc(k)}</div><div class="mono">${esc(v)}</div>`).join('');
    const url = ev.bundle_url || `/api/tasks/${state.taskId}/bundle`;
    $('dl-bundle').href = url;
    $('dl-bundle').setAttribute('download', `slate-receipt-${state.taskId}.json`);
    $('verify-link').href = `/verify?bundle=${encodeURIComponent(url)}`;
    $('final').classList.add('show');
    setStatus('Wrap. Sandbox destroyed. Receipt sealed and signed.', false);
    $('start').disabled = false;
  }

  function handle(ev) {
    switch (ev.type) {
      case 'status': setStatus(ev.message, true); break;
      case 'step': addStep(ev); break;
      case 'egress': addEgress(ev); break;
      case 'alert': alertBanner(ev.level, ev.title, ev.detail); break;
      case 'approval_required': showApproval(ev); break;
      case 'done': showFinal(ev); state.es && state.es.close(); break;
      case 'error':
        alertBanner('red', 'Error', ev.message);
        setStatus('Stopped: ' + ev.message, false);
        $('start').disabled = false;
        state.es && state.es.close();
        break;
    }
  }

  function reset() {
    state.steps.clear();
    state.selected = null;
    state.egress = 0;
    $('feed').innerHTML = '<div class="empty" id="empty">Rolling. Waiting for the first step.</div>';
    $('alerts').innerHTML = '';
    $('egress').innerHTML = '';
    $('receipt').textContent = '{}';
    $('receipt-step').textContent = 'select a step';
    $('egress-count').textContent = '0 requests';
    $('stepcount').textContent = '0 steps';
    $('final').classList.remove('show');
    $('take').textContent = 'TAKE 00';
  }

  $('task-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (state.es) state.es.close();
    reset();
    $('start').disabled = true;
    const safety = $('safety').checked;
    if (!safety) alertBanner('amber', 'Injection screen OFF', 'Turned off on purpose. The sandbox and egress proxy are now the only defenses.');
    setStatus('Starting a fresh sandbox...', true);
    try {
      const res = await fetch('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ goal: $('goal').value, safety }) });
      if (!res.ok) throw new Error('HTTP ' + res.status + ' ' + (await res.text()));
      const { task_id } = await res.json();
      state.taskId = task_id;
      const es = new EventSource(`/api/tasks/${task_id}/events`);
      state.es = es;
      es.onmessage = (m) => { try { handle(JSON.parse(m.data)); } catch (err) { console.error(err, m.data); } };
      es.onerror = () => { if (es.readyState === EventSource.CLOSED) setStatus('Stream closed.', false); };
    } catch (err) {
      alertBanner('red', 'Could not start the task', err.message);
      setStatus('Ready.', false);
      $('start').disabled = false;
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') $('lightbox').classList.remove('show');
  });
})();
