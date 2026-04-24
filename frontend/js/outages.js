// Outage log page: chronological list with filters and CSV/JSON
// download. The filter panel and the export links both talk to
// /api/v1/outages + /api/v1/export/outages.{csv,json}, so what you
// download is what you see on the page.

(() => {
  const { API_BASE, el, getJson, showError, clearError, fmtDuration } = window.SteemAPI;

  const STATE = {
    range: '30d',
    node: '',
    severity: '',
    min_duration_s: 0,
  };

  // ---- URL state ---------------------------------------------------------
  function readStateFromUrl() {
    const q = new URL(window.location.href).searchParams;
    if (q.has('range')) STATE.range = q.get('range');
    if (q.has('node')) STATE.node = q.get('node');
    if (q.has('severity')) STATE.severity = q.get('severity');
    if (q.has('min_duration_s')) STATE.min_duration_s = Math.max(0, Math.min(1800, +q.get('min_duration_s') || 0));
  }

  function writeStateToUrl() {
    const u = new URL(window.location.href);
    const q = u.searchParams;
    const apiOverride = q.get('api');
    ['range', 'node', 'severity', 'min_duration_s'].forEach(k => q.delete(k));
    if (STATE.range !== '30d') q.set('range', STATE.range);
    if (STATE.node) q.set('node', STATE.node);
    if (STATE.severity) q.set('severity', STATE.severity);
    if (STATE.min_duration_s > 0) q.set('min_duration_s', String(STATE.min_duration_s));
    if (apiOverride) q.set('api', apiOverride);
    history.replaceState(null, '', u.toString());
  }

  // Build a query string from current filters for server-side endpoints.
  function apiQueryString() {
    const p = new URLSearchParams();
    p.set('range', STATE.range);
    if (STATE.node) p.set('node', STATE.node);
    if (STATE.severity) p.set('severity', STATE.severity);
    if (STATE.min_duration_s > 0) p.set('min_duration_s', String(STATE.min_duration_s));
    p.set('limit', '5000');
    return p.toString();
  }

  function shortName(url) { return url.replace(/^https?:\/\//, ''); }

  // ---- Node dropdown pre-fill -------------------------------------------
  async function populateNodeDropdown() {
    const sel = document.getElementById('f-out-node');
    try {
      const status = await getJson('/api/v1/status');
      sel.innerHTML = '';
      sel.appendChild(el('option', { value: '' }, 'all'));
      for (const n of status.nodes.slice().sort((a, b) => a.url.localeCompare(b.url))) {
        sel.appendChild(el('option', { value: n.url }, shortName(n.url)));
      }
      sel.value = STATE.node;
    } catch (e) {
      console.warn('Could not populate node dropdown:', e);
    }
  }

  // ---- Table rendering --------------------------------------------------
  function renderTable(outages, total) {
    const tbody = document.querySelector('#outages-table tbody');
    tbody.innerHTML = '';
    document.getElementById('outages-count').textContent =
      total === 0 ? 'no outages match the filters' : `${outages.length} shown · ${total} matching`;

    if (outages.length === 0) {
      tbody.appendChild(el('tr', {}, el('td', { colspan: '6', class: 'loading' }, 'No outages.')));
      return;
    }

    for (const o of outages) {
      const nodeLink = el('a', {
        class: 'inline-link',
        href: `node.html?url=${encodeURIComponent(o.node_url)}${API_BASE ? `&api=${encodeURIComponent(API_BASE)}` : ''}`,
      }, shortName(o.node_url));
      tbody.appendChild(el('tr', {}, [
        el('td', {}, nodeLink),
        el('td', {}, o.start.replace('T', ' ').replace('Z', '')),
        el('td', {}, o.ongoing ? 'ongoing' : o.end.replace('T', ' ').replace('Z', '')),
        el('td', {}, fmtDuration(o.duration_s)),
        el('td', {}, el('span', { class: `sev-pill sev-${o.severity}` }, o.severity.toUpperCase())),
        el('td', { class: 'muted' }, o.error_sample || '—'),
      ]));
    }
  }

  // ---- Update download-link hrefs to match current filters --------------
  function updateExportLinks() {
    const qs = apiQueryString();
    // The `api` override points the frontend at a different host; for
    // downloads we want the *same* host so Content-Disposition works
    // (cross-origin downloads lose the attachment hint in some browsers).
    const csvHref = `${API_BASE || ''}/api/v1/export/outages.csv?${qs}`;
    const jsonHref = `${API_BASE || ''}/api/v1/export/outages.json?${qs}`;
    document.getElementById('export-csv').setAttribute('href', csvHref);
    document.getElementById('export-json').setAttribute('href', jsonHref);
  }

  // ---- Fetch + render ---------------------------------------------------
  async function load() {
    try {
      const body = await getJson(`/api/v1/outages?${apiQueryString()}`);
      renderTable(body.outages, body.total);
      updateExportLinks();
      clearError();
    } catch (e) {
      console.error(e);
      showError(`Failed to load outage log: ${e.message}`);
    }
  }

  // ---- Controls wiring --------------------------------------------------
  function syncControls() {
    document.getElementById('f-out-range').value = STATE.range;
    document.getElementById('f-out-node').value = STATE.node;
    document.getElementById('f-out-sev').value = STATE.severity;
    document.getElementById('f-out-min').value = String(STATE.min_duration_s);
    document.getElementById('f-out-min-val').textContent = `${STATE.min_duration_s}s`;
  }

  function bindControls() {
    const rangeSel = document.getElementById('f-out-range');
    rangeSel.addEventListener('change', () => { STATE.range = rangeSel.value; writeStateToUrl(); load(); });

    const nodeSel = document.getElementById('f-out-node');
    nodeSel.addEventListener('change', () => { STATE.node = nodeSel.value; writeStateToUrl(); load(); });

    const sevSel = document.getElementById('f-out-sev');
    sevSel.addEventListener('change', () => { STATE.severity = sevSel.value; writeStateToUrl(); load(); });

    const minRange = document.getElementById('f-out-min');
    const minVal = document.getElementById('f-out-min-val');
    minRange.addEventListener('input', () => { minVal.textContent = `${minRange.value}s`; });
    minRange.addEventListener('change', () => {
      STATE.min_duration_s = +minRange.value;
      writeStateToUrl();
      load();
    });

    document.getElementById('f-out-reset').addEventListener('click', () => {
      STATE.range = '30d'; STATE.node = ''; STATE.severity = ''; STATE.min_duration_s = 0;
      syncControls(); writeStateToUrl(); load();
    });
  }

  // ---- Bootstrap --------------------------------------------------------
  async function main() {
    readStateFromUrl();
    bindControls();
    syncControls();
    await populateNodeDropdown();
    // Re-apply the stored node selection now that options are in the DOM.
    document.getElementById('f-out-node').value = STATE.node;
    await load();
  }

  main();
})();
