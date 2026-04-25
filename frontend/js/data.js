// Data downloads page — three forms (measurements, aggregates,
// outages), each builds the right `/api/v1/export/...` URL from the
// current filter selections and assigns it to the download <a> on
// every change. The user clicks the link → browser downloads via
// streaming HTTP with the right Content-Disposition.
//
// Code-snippet generators (curl / Python pandas / R) read the same
// filter state so what you copy is the exact request the page would
// send.

(() => {
  const { API_BASE, getJson, showError, clearError } = window.SteemAPI;

  const $ = (id) => document.getElementById(id);

  // -------- Helpers -------------------------------------------------------

  function shortName(url) { return url.replace(/^https?:\/\//, ''); }

  function querystring(params) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v == null || v === '') continue;
      p.set(k, v);
    }
    return p.toString();
  }

  function downloadUrl(path, params) {
    const qs = querystring(params);
    // Use the same host the page is on for downloads — Content-
    // Disposition behaves better than across the dev `?api=` override.
    return `${API_BASE || ''}${path}${qs ? '?' + qs : ''}`;
  }

  // Fill a <select> from a list of {value, label}; preserves any
  // already-selected value if present in the new options.
  function fillSelect(sel, items, prepend) {
    const previous = sel.value;
    sel.innerHTML = '';
    if (prepend) {
      const o = new Option(prepend.label, prepend.value);
      sel.appendChild(o);
    }
    for (const it of items) {
      const o = new Option(it.label, it.value);
      sel.appendChild(o);
    }
    if (previous && [...sel.options].some(o => o.value === previous)) {
      sel.value = previous;
    }
  }

  // -------- Dropdown population -------------------------------------------

  async function loadNodes() {
    try {
      const data = await getJson('/api/v1/nodes');
      const items = data.nodes
        .slice()
        .sort((a, b) => a.url.localeCompare(b.url))
        .map(n => ({ value: n.url, label: shortName(n.url) }));
      for (const id of ['m-node', 'a-node', 'o-node']) {
        const sel = $(id);
        if (sel) fillSelect(sel, items, { value: '', label: 'all nodes' });
      }
    } catch (e) {
      console.warn('node dropdown:', e);
    }
  }

  async function loadSources() {
    try {
      const data = await getJson('/api/v1/export/sources');
      const items = (data.sources || []).map(s => ({ value: s, label: s }));
      for (const id of ['m-source', 'a-source', 'o-source']) {
        const sel = $(id);
        if (sel) fillSelect(sel, items, { value: '', label: 'all sources' });
      }
    } catch (e) {
      console.warn('source dropdown:', e);
    }
  }

  // -------- Snippet generators --------------------------------------------

  function snippetsForUrl(url) {
    return [
      '# curl',
      `curl -fsSL "${url}" -o output`,
      '',
      '# Python (pandas)',
      'import pandas as pd',
      `df = pd.read_csv("${url}")`,
      'df.head()',
      '',
      '# R',
      `df <- read.csv("${url}")`,
      'head(df)',
    ].join('\n');
  }

  // -------- Form wiring ---------------------------------------------------

  function readForm(prefix, fields) {
    const out = {};
    for (const f of fields) {
      const el = $(`${prefix}-${f}`);
      if (el) out[f] = el.value;
    }
    return out;
  }

  function wireForm({ prefix, basePath, fields, csvOnly = false }) {
    const form = $(`${prefix}-form`);
    const link = $(`${prefix}-download`);
    const snippets = $(`${prefix}-snippets`);
    const toggle = $(`${prefix}-snippets-toggle`);

    function rebuild() {
      const state = readForm(prefix, fields);
      let path = basePath;
      // Outages live at /export/outages.{csv|json} — different shape
      // than measurements/aggregates which take ?format=. The csvOnly
      // flag tells us we have to switch path by extension.
      if (csvOnly) {
        const fmt = state.format || 'csv';
        delete state.format;
        path = `${basePath}.${fmt}`;
      }
      const url = downloadUrl(path, state);
      link.href = url;
      // Build a more meaningful filename hint via the link's "download"
      // attribute. Server's Content-Disposition takes precedence when
      // it's set, but having a fallback helps when the server response
      // is browser-cached.
      link.setAttribute('download', '');
      snippets.textContent = snippetsForUrl(url);
    }

    form.addEventListener('change', rebuild);
    toggle.addEventListener('click', () => {
      const showing = !snippets.hasAttribute('hidden');
      if (showing) {
        snippets.setAttribute('hidden', '');
        toggle.textContent = 'Show code snippets';
      } else {
        snippets.removeAttribute('hidden');
        toggle.textContent = 'Hide code snippets';
      }
    });
    rebuild();
  }

  // -------- Boot -----------------------------------------------------------

  document.addEventListener('DOMContentLoaded', async () => {
    try {
      await Promise.all([loadNodes(), loadSources()]);
      wireForm({
        prefix: 'm', basePath: '/api/v1/export/measurements',
        fields: ['range', 'node', 'source', 'format'],
      });
      wireForm({
        prefix: 'a', basePath: '/api/v1/export/aggregates',
        fields: ['range', 'granularity', 'node', 'source', 'format'],
      });
      wireForm({
        prefix: 'o', basePath: '/api/v1/export/outages',
        fields: ['range', 'severity', 'node', 'source', 'format'],
        csvOnly: true,
      });
      clearError();
    } catch (e) {
      console.error(e);
      showError(`Could not initialise the data page: ${e.message}`);
    }
  });
})();
