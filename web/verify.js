// SLATE verify page: load a receipt bundle, POST it to /api/verify, show per-step checks.
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const mark = (ok) => (ok ? '<span class="ok-mark">&#10003; ok</span>' : '<span class="bad-mark">&#10007; fail</span>');

  function setBundle(text) {
    try { $('bundle').value = JSON.stringify(JSON.parse(text), null, 2); }
    catch { $('bundle').value = text; }
  }

  async function verify() {
    let bundle;
    try { bundle = JSON.parse($('bundle').value); }
    catch (e) { return showVerdict(false, 'Not valid JSON: ' + e.message); }
    $('verify').disabled = true;
    try {
      const res = await fetch('/api/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bundle) });
      const r = await res.json();
      render(r);
    } catch (e) {
      showVerdict(false, 'Verify request failed: ' + e.message);
    } finally {
      $('verify').disabled = false;
    }
  }

  function showVerdict(ok, detail) {
    const v = $('verdict');
    v.className = 'verdict show ' + (ok ? 'ok' : 'bad');
    v.innerHTML = (ok ? 'CHAIN INTACT' : 'TAMPERED') + (detail ? `<small>${esc(detail)}</small>` : '');
  }

  function render(r) {
    const steps = r.steps || [];
    const failed = steps.filter((s) => !(s.hash_ok && s.chain_ok && s.sig_ok)).map((s) => s.step);
    let detail;
    if (r.ok) detail = `${steps.length} steps checked. Every hash, link and signature matches.`;
    else if (r.error) detail = r.error;
    else if (failed.length) detail = `Broken at step ${failed[0]}. ${failed.length} step${failed.length > 1 ? 's' : ''} failed.`;
    else if (r.final_ok === false) detail = 'The final record does not match the chain.';
    showVerdict(!!r.ok, detail);

    $('rows').innerHTML = steps.map((s) => `<tr><td>${String(s.step).padStart(2, '0')}</td><td>${mark(s.hash_ok)}</td><td>${mark(s.chain_ok)}</td><td>${mark(s.sig_ok)}</td></tr>`).join('')
      + (r.final_ok !== undefined ? `<tr><td>FINAL</td><td colspan="3">${mark(r.final_ok)}</td></tr>` : '');
    $('pubkey').textContent = r.pubkey ? 'Signer public key: ' + r.pubkey : '';
    $('results').style.display = '';
  }

  // Flip one character in step 1's intent, then verify again. For the demo video.
  function tamper() {
    let bundle;
    try { bundle = JSON.parse($('bundle').value); }
    catch { return showVerdict(false, 'Load a bundle first.'); }
    const steps = bundle.steps || bundle.receipts || [];
    if (!steps.length) return showVerdict(false, 'This bundle has no steps to tamper with.');
    const target = steps[0].receipt || steps[0];
    const before = String(target.intent || '');
    if (!before) return showVerdict(false, 'Step 1 has no intent text.');
    const i = Math.min(4, before.length - 1);
    const c = before[i];
    const flipped = c === 'e' ? 'a' : c === 'a' ? 'e' : c === c.toLowerCase() ? c.toUpperCase() : c.toLowerCase();
    target.intent = before.slice(0, i) + (flipped === c ? (c === 'x' ? 'y' : 'x') : flipped) + before.slice(i + 1);
    $('bundle').value = JSON.stringify(bundle, null, 2);
    $('tamper-note').innerHTML = `<span class="dot" style="background:var(--red)"></span><span>Changed one byte in step 1 intent: "${esc(before.slice(0, 40))}" to "${esc(target.intent.slice(0, 40))}"</span>`;
    verify();
  }

  function readFile(f) {
    const r = new FileReader();
    r.onload = () => { setBundle(r.result); $('tamper-note').innerHTML = ''; verify(); };
    r.readAsText(f);
  }

  const drop = $('drop');
  ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => { const f = e.dataTransfer.files[0]; if (f) readFile(f); });
  $('file').addEventListener('change', (e) => { const f = e.target.files[0]; if (f) readFile(f); });
  $('verify').addEventListener('click', verify);
  $('tamper').addEventListener('click', tamper);
  $('clear').addEventListener('click', () => {
    $('bundle').value = '';
    $('verdict').className = 'verdict';
    $('results').style.display = 'none';
    $('tamper-note').innerHTML = '';
  });

  // /verify?bundle=/api/tasks/<id>/bundle preloads and checks a bundle.
  const src = new URLSearchParams(location.search).get('bundle');
  if (src && src.startsWith('/')) {
    fetch(src).then((r) => r.text()).then((t) => { setBundle(t); verify(); }).catch((e) => showVerdict(false, 'Could not load bundle: ' + e.message));
  }
})();
