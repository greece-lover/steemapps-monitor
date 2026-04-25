// Self-service onboarding flow.
//
// One submit. The form panel hides on success and the result panel
// (with the freshly-issued API key + a copy button) takes its place.
// On failure the error line below the button shows the server's
// detail.message and the form stays interactive so the user can fix
// and retry.

(() => {
  const { getJson } = window.SteemAPI;

  const $ = (id) => document.getElementById(id);

  // POST helper. SteemAPI.getJson is GET-only; we mirror its `?api=`
  // override so a developer can point the form at a local backend with
  // the same trick the dashboard uses.
  async function postJson(path, body) {
    const apiBase = (new URL(window.location.href).searchParams.get('api')) || '';
    const r = await fetch(apiBase + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    });
    let payload = null;
    try { payload = await r.json(); } catch {}
    if (!r.ok) {
      const detail = payload && payload.detail;
      const msg = (detail && detail.message) || (typeof detail === 'string' ? detail : `HTTP ${r.status}`);
      const err = new Error(msg);
      err.code = (detail && detail.code) || `http_${r.status}`;
      err.status = r.status;
      throw err;
    }
    return payload;
  }

  // -------- Region dropdown ------------------------------------------------

  async function loadRegions() {
    const sel = $('f-region');
    try {
      const data = await getJson('/api/v1/join/regions');
      sel.innerHTML = '';
      sel.appendChild(new Option('— choose a region —', ''));
      for (const r of data.regions) {
        sel.appendChild(new Option(r.label, r.id));
      }
    } catch (e) {
      sel.innerHTML = '';
      sel.appendChild(new Option('failed to load regions', ''));
      $('form-error').textContent = `Could not load region list: ${e.message}`;
    }
  }

  // -------- Form submit ----------------------------------------------------

  async function onSubmit(ev) {
    ev.preventDefault();
    $('form-error').textContent = '';
    const btn = $('btn-register');
    btn.disabled = true;
    const account = $('f-account').value.trim().toLowerCase();
    const label = $('f-label').value.trim();
    const region = $('f-region').value;
    try {
      const out = await postJson('/api/v1/join/register', {
        steem_account: account,
        display_label: label,
        region: region,
      });
      // Swap panels: hide the form, reveal the result.
      $('form-panel').hidden = true;
      $('api-key').textContent = out.api_key;
      $('result-panel').hidden = false;
      $('result-panel').classList.add('is-active');
    } catch (e) {
      $('form-error').textContent = e.message || 'Registration failed.';
    } finally {
      btn.disabled = false;
    }
  }

  // -------- Copy button ----------------------------------------------------

  function bindCopy() {
    const btn = $('btn-copy-key');
    btn.addEventListener('click', async () => {
      const value = $('api-key').textContent;
      if (!value || value === '—') return;
      try {
        await navigator.clipboard.writeText(value);
        const prev = btn.textContent;
        btn.textContent = 'Copied ✓';
        setTimeout(() => { btn.textContent = prev; }, 1500);
      } catch {
        // Older browsers without async clipboard: fall back to the
        // execCommand("copy") path on a hidden textarea.
        const tmp = document.createElement('textarea');
        tmp.value = value;
        document.body.appendChild(tmp);
        tmp.select();
        try { document.execCommand('copy'); } catch {}
        document.body.removeChild(tmp);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    loadRegions();
    $('join-form').addEventListener('submit', onSubmit);
    bindCopy();
  });
})();
