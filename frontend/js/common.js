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

  // -----------------------------------------------------------------
  //  Theme (light/dark) — persisted in localStorage, applied on <html>.
  // -----------------------------------------------------------------
  const THEME_KEY = 'steemapps_theme';   // values: 'dark' | 'light'

  function loadTheme() {
    try {
      const v = localStorage.getItem(THEME_KEY);
      return v === 'light' ? 'light' : 'dark';
    } catch { return 'dark'; }
  }
  function applyTheme(theme) {
    if (theme === 'light') document.documentElement.setAttribute('data-theme', 'light');
    else document.documentElement.removeAttribute('data-theme');
  }
  // Apply immediately — *before* DOMContentLoaded — so there is no
  // "dark flash" when the saved theme is light. common.js is loaded
  // with `defer`, which still runs before DOMContentLoaded fires.
  applyTheme(loadTheme());

  function wireThemeButton() {
    const btn = document.querySelector('[data-theme-toggle]');
    if (!btn) return;
    function syncLabel() {
      const theme = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      btn.textContent = theme === 'light' ? '🌙 Dark' : '☀ Light';
      btn.setAttribute('aria-label', theme === 'light' ? 'switch to dark theme' : 'switch to light theme');
    }
    syncLabel();
    btn.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      try { localStorage.setItem(THEME_KEY, next); } catch {}
      // A hard reload is the simplest way to re-initialise Chart.js
      // instances with the new CSS-variable-derived grid/tick colours.
      location.reload();
    });
  }

  // -----------------------------------------------------------------
  //  Auto-refresh control — pub/sub with localStorage persistence.
  // -----------------------------------------------------------------
  // Semantic: pages register a callback with onAutoRefresh(fn); the
  // helper then fires fn at the active interval (or not at all when
  // the user picked "pause"). Changing the speed in the UI re-arms the
  // timer without a reload. Per-page, any number of callbacks OK.
  const REFRESH_KEY = 'steemapps_autorefresh';   // values: '10' | '60' | '300' | 'paused'
  const REFRESH_OPTIONS = [
    { value: '10',     label: 'live 10s' },
    { value: '60',     label: 'normal 60s' },
    { value: '300',    label: 'slow 5m' },
    { value: 'paused', label: 'paused' },
  ];

  let _refreshValue = 'paused';
  const _refreshCallbacks = new Set();
  let _refreshTimer = null;

  function loadRefresh() {
    try {
      const v = localStorage.getItem(REFRESH_KEY);
      if (REFRESH_OPTIONS.some(o => o.value === v)) return v;
    } catch {}
    return '60';  // sane default for fresh sessions
  }
  function saveRefresh(v) { try { localStorage.setItem(REFRESH_KEY, v); } catch {} }

  function armRefreshTimer() {
    if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
    if (_refreshValue === 'paused') return;
    const ms = parseInt(_refreshValue, 10) * 1000;
    _refreshTimer = setInterval(() => {
      _refreshCallbacks.forEach(fn => {
        try { fn(); } catch (e) { console.warn('autorefresh callback failed:', e); }
      });
    }, ms);
  }

  function setRefresh(v) {
    if (!REFRESH_OPTIONS.some(o => o.value === v)) return;
    _refreshValue = v;
    saveRefresh(v);
    armRefreshTimer();
  }

  function onAutoRefresh(fn) {
    _refreshCallbacks.add(fn);
    armRefreshTimer();
    return () => { _refreshCallbacks.delete(fn); };
  }

  _refreshValue = loadRefresh();

  function wireRefreshSelect() {
    const sel = document.querySelector('[data-refresh-select]');
    if (!sel) return;
    sel.innerHTML = '';
    for (const opt of REFRESH_OPTIONS) {
      const o = document.createElement('option');
      o.value = opt.value;
      o.textContent = opt.label;
      if (opt.value === _refreshValue) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener('change', () => setRefresh(sel.value));
  }

  // Auto-run on DOMContentLoaded: append the dev `?api=` override to any
  // header nav link so in-app navigation keeps pointing at the local API.
  function decorateNavLinks() {
    const override = API_BASE;
    if (!override) return;
    document.querySelectorAll('.nav-links a').forEach(a => {
      const u = new URL(a.getAttribute('href'), window.location.href);
      u.searchParams.set('api', override);
      a.setAttribute('href', u.pathname + u.search);
    });
  }
  function bootstrapControls() {
    decorateNavLinks();
    wireThemeButton();
    wireRefreshSelect();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapControls);
  } else {
    bootstrapControls();
  }

  // Current CSS-variable-derived palette for Chart.js configs. Each caller
  // reads this fresh at chart-build time so the colours match whichever
  // theme is active when the chart is created.
  function chartColors() {
    const cs = getComputedStyle(document.documentElement);
    return {
      tick: cs.getPropertyValue('--chart-tick').trim() || '#8c8c8c',
      grid: cs.getPropertyValue('--chart-grid').trim() || '#1e1e1e',
      accent: cs.getPropertyValue('--accent').trim() || '#b7e34a',
      ok: cs.getPropertyValue('--status-ok').trim() || '#5eea88',
      deg: cs.getPropertyValue('--status-deg').trim() || '#e8c34a',
      down: cs.getPropertyValue('--status-down').trim() || '#ef6a6a',
    };
  }

  window.SteemAPI = {
    API_BASE, el, getJson, showError, clearError,
    preserveApiOverride, fmtLatency, fmtPct, fmtDuration,
    decorateNavLinks,
    onAutoRefresh,
    getRefreshValue: () => _refreshValue,
    chartColors,
  };
})();
