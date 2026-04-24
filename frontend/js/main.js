// Dashboard rendering logic.
//
// Polls /api/v1/status every 60 s for the headline numbers, and /history
// + /uptime once per node per render for the sparkline and the 24 h / 7 d
// uptime stats. The API base URL is empty by default — the dashboard is
// served from the same origin as the API in production, so relative
// paths like `/api/v1/status` hit the right host without any hard-coded
// URL. For local development through an SSH tunnel, append
// `?api=http://localhost:8110` to the page URL.

(() => {
  const DEFAULT_API = '';
  const API_BASE = (new URL(window.location.href).searchParams.get('api')) || DEFAULT_API;
  const REFRESH_MS = 60_000;

  // --- UI state: filters + sorting, round-tripped through the URL ---------
  // The `api` param is reserved for the local-dev override and is not
  // something the filter form touches, so we pass through whatever was
  // already there when writing state back.
  const STATE = {
    region: '',
    status: new Set(['ok', 'warning', 'critical', 'down']),
    minScore: 0,
    sortBy: 'score',
    sortDir: 'desc',
  };
  let lastStatusResponse = null;

  function readStateFromUrl() {
    const q = new URL(window.location.href).searchParams;
    if (q.has('region')) STATE.region = q.get('region') || '';
    if (q.has('status')) {
      STATE.status = new Set(q.get('status').split(',').filter(Boolean));
    }
    const ms = q.get('minScore');
    if (ms != null && !Number.isNaN(+ms)) STATE.minScore = Math.max(0, Math.min(100, +ms));
    const sb = q.get('sortBy');
    if (sb) STATE.sortBy = sb;
    const sd = q.get('sortDir');
    if (sd === 'asc' || sd === 'desc') STATE.sortDir = sd;
  }

  function writeStateToUrl() {
    const u = new URL(window.location.href);
    const q = u.searchParams;
    // Preserve `api=` (developer override) if it was already set.
    const apiOverride = q.get('api');
    // Wipe our keys before re-writing, so clearing a filter removes its param.
    ['region', 'status', 'minScore', 'sortBy', 'sortDir'].forEach(k => q.delete(k));
    if (STATE.region) q.set('region', STATE.region);
    // Only serialise status when something is unselected — a full set is the default.
    if (STATE.status.size !== 4) q.set('status', [...STATE.status].join(','));
    if (STATE.minScore > 0) q.set('minScore', String(STATE.minScore));
    if (STATE.sortBy !== 'score') q.set('sortBy', STATE.sortBy);
    if (STATE.sortDir !== 'desc') q.set('sortDir', STATE.sortDir);
    if (apiOverride) q.set('api', apiOverride); else q.delete('api');
    // Restore api at the tail so it stays a developer affordance, not
    // mixed in with the user-visible filter params.
    if (apiOverride) { q.delete('api'); q.set('api', apiOverride); }
    history.replaceState(null, '', u.toString());
  }

  function applyFiltersAndSort(nodes) {
    const filtered = nodes.filter(n => {
      if (STATE.region && n.region !== STATE.region) return false;
      if (!STATE.status.has(n.status)) return false;
      // A node with null score fails a >0 threshold filter, as would any
      // strictly numeric rule — consistent with how `/status` emits it.
      if (STATE.minScore > 0) {
        if (n.score == null || n.score < STATE.minScore) return false;
      }
      return true;
    });

    // Sort keys map a node to a comparable value. Null-ish values sort to
    // the end regardless of direction, so broken nodes never hide rows.
    const keyFns = {
      name: n => n.url.replace(/^https?:\/\//, '').toLowerCase(),
      region: n => (n.region || 'zzz').toLowerCase(),
      latency: n => (n.latency_ms == null ? Number.POSITIVE_INFINITY : n.latency_ms),
      score: n => (n.score == null ? -1 : n.score),
      status: n => ({ ok: 0, warning: 1, critical: 2, down: 3, unknown: 4 }[n.status] ?? 9),
    };
    const key = keyFns[STATE.sortBy] || keyFns.score;
    const dir = STATE.sortDir === 'asc' ? 1 : -1;
    filtered.sort((a, b) => {
      const va = key(a); const vb = key(b);
      if (va === vb) return 0;
      return va < vb ? -dir : dir;
    });
    return filtered;
  }

  // One Chart.js instance per node, keyed by URL. Re-rendering re-uses the
  // instance and updates .data — full rebuild would leak listeners.
  const sparkCharts = new Map();

  const el = (tag, attrs = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
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

  const fmtLatency = ms => (ms == null ? '—' : String(ms));
  const fmtPct = pct => (pct == null ? '—' : pct.toFixed(pct < 99 ? 1 : 2));
  const fmtLag = lag => (lag == null ? '—' : String(lag));

  const showError = msg => {
    let banner = document.getElementById('error-banner');
    if (!banner) {
      banner = el('div', { id: 'error-banner', class: 'error-banner' });
      document.querySelector('.container').prepend(banner);
    }
    banner.textContent = msg;
  };
  const clearError = () => {
    const banner = document.getElementById('error-banner');
    if (banner) banner.remove();
  };

  async function getJson(path) {
    const url = `${API_BASE}${path}`;
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
    return r.json();
  }

  function renderSparkline(canvas, points) {
    // Chart.js is loaded via defer; this function is only called after
    // the initial fetch completes, by which point the script has run.
    const existing = sparkCharts.get(canvas);
    const latencies = points.map(p => (p.success ? p.latency_ms : null));
    const labels = points.map(() => '');
    if (existing) {
      existing.data.labels = labels;
      existing.data.datasets[0].data = latencies;
      existing.update('none');
      return;
    }
    const chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          data: latencies,
          borderColor: '#b7e34a',
          borderWidth: 1.5,
          tension: 0.3,
          pointRadius: 0,
          fill: false,
          spanGaps: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: { display: false },
          y: { display: false, beginAtZero: true },
        },
      },
    });
    sparkCharts.set(canvas, chart);
  }

  function buildCard(node) {
    const urlEnc = encodeURIComponent(node.url);

    const head = el('div', { class: 'node-head' }, [
      el('div', {}, [
        el('div', { class: 'node-url' }, node.url.replace(/^https?:\/\//, '')),
        el('div', { class: 'node-region' }, node.region ? `region: ${node.region}` : ''),
      ]),
      el('div', { class: 'status-pill', dataset: { status: node.status } }, [
        el('span', { class: 'dot' }),
        node.status.toUpperCase(),
      ]),
    ]);

    const scoreVal = node.score == null ? '—' : String(node.score);
    const scoreStat = el('div', { class: 'stat' }, [
      el('div', { class: 'stat-label' }, 'Score'),
      el('div', { class: 'stat-value' + (node.score == null ? ' muted' : '') }, scoreVal),
    ]);

    const latencyStat = el('div', { class: 'stat' }, [
      el('div', { class: 'stat-label' }, 'Latency'),
      el('div', { class: 'stat-value' + (node.latency_ms == null ? ' muted' : '') }, [
        fmtLatency(node.latency_ms),
        el('span', { class: 'stat-unit' }, 'ms'),
      ]),
    ]);

    const up24 = el('div', { class: 'stat' }, [
      el('div', { class: 'stat-label' }, 'Uptime 24h'),
      el('div', { class: 'stat-value muted', id: `up24-${urlEnc}` }, '…'),
    ]);
    const up7 = el('div', { class: 'stat' }, [
      el('div', { class: 'stat-label' }, 'Uptime 7d'),
      el('div', { class: 'stat-value muted', id: `up7-${urlEnc}` }, '…'),
    ]);

    const stats = el('div', { class: 'stat-row' }, [scoreStat, latencyStat, up24, up7]);

    const sparkCanvas = el('canvas', { id: `spark-${urlEnc}` });
    const spark = el('div', { class: 'spark-wrap' }, sparkCanvas);

    const children = [head, stats, spark];

    if (node.reasons && node.reasons.length > 0) {
      const ul = el('ul');
      for (const r of node.reasons) ul.appendChild(el('li', {}, r));
      children.push(el('div', { class: 'reasons' }, [
        el('span', { class: 'label' }, 'Penalties applied this tick'),
        ul,
      ]));
    }

    return el('div', { class: 'node-card' }, children);
  }

  async function hydrateNode(node) {
    const urlEnc = encodeURIComponent(node.url);
    const [history, uptime24, uptime7] = await Promise.all([
      getJson(`/api/v1/nodes/${urlEnc}/history?hours=1`),
      getJson(`/api/v1/nodes/${urlEnc}/uptime?days=1`),
      getJson(`/api/v1/nodes/${urlEnc}/uptime?days=7`),
    ]);

    const spark = document.getElementById(`spark-${urlEnc}`);
    if (spark) renderSparkline(spark, history.points);

    const up24 = document.getElementById(`up24-${urlEnc}`);
    if (up24) {
      up24.textContent = '';
      if (uptime24.total === 0) {
        up24.classList.add('muted');
        up24.textContent = '—';
      } else {
        up24.classList.remove('muted');
        up24.append(
          fmtPct(uptime24.uptime_pct),
          Object.assign(document.createElement('span'), { className: 'stat-unit', textContent: '%' }),
        );
      }
    }
    const up7 = document.getElementById(`up7-${urlEnc}`);
    if (up7) {
      up7.textContent = '';
      if (uptime7.total === 0) {
        up7.classList.add('muted');
        up7.textContent = '—';
      } else {
        up7.classList.remove('muted');
        up7.append(
          fmtPct(uptime7.uptime_pct),
          Object.assign(document.createElement('span'), { className: 'stat-unit', textContent: '%' }),
        );
      }
    }
  }

  function renderNodes() {
    if (!lastStatusResponse) return;
    const container = document.getElementById('nodes');
    const filtered = applyFiltersAndSort(lastStatusResponse.nodes);

    // Drop any outdated sparkline chart refs — their canvases are about to
    // disappear, so leaving stale entries around leaks memory over hours.
    sparkCharts.clear();

    container.innerHTML = '';
    if (filtered.length === 0) {
      container.appendChild(el('p', { class: 'loading' }, 'No nodes match the current filters.'));
    } else {
      for (const n of filtered) container.appendChild(buildCard(n));
    }

    const count = document.getElementById('match-count');
    if (count) {
      count.textContent = filtered.length === lastStatusResponse.nodes.length
        ? `${filtered.length} nodes`
        : `${filtered.length} / ${lastStatusResponse.nodes.length} nodes`;
    }

    // Hydration fires per visible card. We kick them off after paint so
    // the first render isn't gated on 10 extra network calls.
    filtered.forEach(n => { hydrateNode(n).catch(e => console.warn('hydrate failed', n.url, e)); });
  }

  function populateRegionOptions(nodes) {
    const sel = document.getElementById('f-region');
    if (!sel) return;
    const regions = [...new Set(nodes.map(n => n.region).filter(Boolean))].sort();
    // Keep the "all" entry, replace the rest on every refresh (cheap, idempotent).
    sel.innerHTML = '';
    sel.appendChild(el('option', { value: '' }, 'all'));
    for (const r of regions) sel.appendChild(el('option', { value: r }, r));
    sel.value = STATE.region;
  }

  function syncControlsFromState() {
    const q = sel => document.getElementById(sel);
    if (q('f-region')) q('f-region').value = STATE.region;
    document.querySelectorAll('.ctrl-status input[type=checkbox]').forEach(cb => {
      cb.checked = STATE.status.has(cb.value);
    });
    if (q('f-score')) { q('f-score').value = String(STATE.minScore); q('f-score-val').textContent = String(STATE.minScore); }
    if (q('f-sort')) q('f-sort').value = STATE.sortBy;
    if (q('f-sort-dir')) q('f-sort-dir').textContent = STATE.sortDir === 'asc' ? '↑' : '↓';
  }

  function bindControls() {
    const region = document.getElementById('f-region');
    region.addEventListener('change', () => { STATE.region = region.value; writeStateToUrl(); renderNodes(); });

    document.querySelectorAll('.ctrl-status input[type=checkbox]').forEach(cb => {
      cb.addEventListener('change', () => {
        if (cb.checked) STATE.status.add(cb.value); else STATE.status.delete(cb.value);
        writeStateToUrl(); renderNodes();
      });
    });

    const score = document.getElementById('f-score');
    const scoreVal = document.getElementById('f-score-val');
    score.addEventListener('input', () => { scoreVal.textContent = score.value; });
    score.addEventListener('change', () => { STATE.minScore = +score.value; writeStateToUrl(); renderNodes(); });

    document.getElementById('f-sort').addEventListener('change', (e) => {
      STATE.sortBy = e.target.value; writeStateToUrl(); renderNodes();
    });
    document.getElementById('f-sort-dir').addEventListener('click', () => {
      STATE.sortDir = STATE.sortDir === 'asc' ? 'desc' : 'asc';
      syncControlsFromState(); writeStateToUrl(); renderNodes();
    });

    document.getElementById('f-reset').addEventListener('click', () => {
      STATE.region = '';
      STATE.status = new Set(['ok', 'warning', 'critical', 'down']);
      STATE.minScore = 0;
      STATE.sortBy = 'score';
      STATE.sortDir = 'desc';
      syncControlsFromState(); writeStateToUrl(); renderNodes();
    });
  }

  async function refresh() {
    try {
      const status = await getJson('/api/v1/status');
      clearError();
      lastStatusResponse = status;

      document.getElementById('meta-methodology').textContent = status.methodology_version;
      document.getElementById('meta-refblock').textContent =
        status.reference_block == null ? '—' : status.reference_block.toLocaleString('en-US');
      document.getElementById('meta-updated').textContent = status.generated_at;

      populateRegionOptions(status.nodes);
      renderNodes();
    } catch (e) {
      console.error(e);
      const where = API_BASE || 'same origin';
      showError(`Failed to reach the monitor API at ${where}.`);
    }
  }

  // Kick off.
  readStateFromUrl();
  bindControls();
  syncControlsFromState();
  refresh();
  setInterval(refresh, REFRESH_MS);
})();
