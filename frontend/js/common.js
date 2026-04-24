// Shared helpers used by every dashboard page.
//
// Attaches a single global `SteemAPI` so per-page scripts don't have to
// import-juggle in plain vanilla JS. Safe to load multiple times — the
// second IIFE invocation is a no-op because it overwrites the same object.

(() => {
  const DEFAULT_API = '';
  const API_BASE = (new URL(window.location.href).searchParams.get('api')) || DEFAULT_API;

  const el = (tag, attrs = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null) continue;
      if (k === 'class') node.className = v;
      else if (k === 'dataset') Object.assign(node.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const c of [].concat(children)) {
      if (c == null) continue;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
  };

  async function getJson(path) {
    const url = `${API_BASE}${path}`;
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
    return r.json();
  }

  function showError(msg) {
    let banner = document.getElementById('error-banner');
    if (!banner) {
      banner = el('div', { id: 'error-banner', class: 'error-banner' });
      const host = document.querySelector('.container') || document.body;
      host.prepend(banner);
    }
    banner.textContent = msg;
  }

  function clearError() {
    const banner = document.getElementById('error-banner');
    if (banner) banner.remove();
  }

  // Preserve a developer-supplied `?api=` override when rewriting the URL
  // so filter changes don't accidentally drop the dev-mode pointer.
  function preserveApiOverride(urlObj) {
    const current = new URL(window.location.href);
    const override = current.searchParams.get('api');
    if (override) urlObj.searchParams.set('api', override);
    return urlObj;
  }

  // Human-friendly number formatting.
  const fmtLatency = ms => (ms == null ? '—' : String(ms));
  const fmtPct = pct => (pct == null ? '—' : pct.toFixed(pct < 99 ? 1 : 2));
  const fmtDuration = seconds => {
    if (seconds == null) return '—';
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h}h ${m}m`;
  };

  window.SteemAPI = {
    API_BASE, el, getJson, showError, clearError,
    preserveApiOverride, fmtLatency, fmtPct, fmtDuration,
  };
})();
