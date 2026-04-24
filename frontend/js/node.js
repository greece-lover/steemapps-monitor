// Per-node detail page logic: latency chart (with up-to-4-node compare
// overlay), percentile table, 30-day uptime calendar, outage table,
// block-lag chart. All state is round-tripped through URL parameters so
// a page can be shared verbatim.

(() => {
  const { API_BASE, el, getJson, showError, clearError, fmtLatency, fmtPct, fmtDuration } = window.SteemAPI;

  // Colour palette for the compare overlay. Index 0 is always the primary
  // node; compare-partners 1..3 take the remaining three slots.
  const PALETTE = ['#b7e34a', '#5b9bff', '#c48bff', '#f5a462'];
  const MAX_COMPARE = 3;

  // ---- URL state -----------------------------------------------------------
  // ?url=<node>&range=24h|7d|30d&compare=<node>,<node>,<node>&api=<dev override>
  function readState() {
    const q = new URL(window.location.href).searchParams;
    const url = q.get('url') || '';
    const range = ['24h', '7d', '30d'].includes(q.get('range')) ? q.get('range') : '24h';
    const compare = (q.get('compare') || '').split(',').map(s => s.trim()).filter(Boolean).slice(0, MAX_COMPARE);
    return { url, range, compare };
  }

  function writeState(state) {
    const u = new URL(window.location.href);
    const q = u.searchParams;
    const apiOverride = q.get('api');
    for (const k of ['url', 'range', 'compare', 'api']) q.delete(k);
    q.set('url', state.url);
    if (state.range && state.range !== '24h') q.set('range', state.range);
    if (state.compare && state.compare.length) q.set('compare', state.compare.join(','));
    if (apiOverride) q.set('api', apiOverride);
    history.replaceState(null, '', u.toString());
  }

  function shortName(url) { return url.replace(/^https?:\/\//, ''); }

  // Preserve ?api= when we link back to the overview.
  function wireBackLink() {
    const link = document.getElementById('back-link');
    const href = new URL('index.html', window.location.href);
    const apiOverride = new URL(window.location.href).searchParams.get('api');
    if (apiOverride) href.searchParams.set('api', apiOverride);
    link.setAttribute('href', href.pathname + href.search);
  }

  // ---- Range buttons -------------------------------------------------------
  function wireRange(state) {
    document.querySelectorAll('#range-toggle button').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.range === state.range);
      btn.addEventListener('click', () => {
        state.range = btn.dataset.range;
        writeState(state);
        renderAll(state);
      });
    });
  }

  // ---- Share button --------------------------------------------------------
  function wireShare() {
    const btn = document.getElementById('share-btn');
    btn.addEventListener('click', async () => {
      const before = btn.textContent;
      try {
        await navigator.clipboard.writeText(window.location.href);
        btn.textContent = '✓ Copied';
      } catch {
        btn.textContent = '✗ Copy failed';
      }
      setTimeout(() => { btn.textContent = before; }, 1600);
    });
  }

  // ---- Compare picker ------------------------------------------------------
  async function wireCompare(state, availableNodes) {
    const toggle = document.getElementById('compare-toggle');
    const picker = document.getElementById('compare-picker');
    const others = availableNodes.filter(n => n.url !== state.url);

    function render() {
      picker.innerHTML = '';
      for (const n of others) {
        const checked = state.compare.includes(n.url);
        const disabled = !checked && state.compare.length >= MAX_COMPARE;
        const cb = el('input', { type: 'checkbox', value: n.url });
        if (checked) cb.setAttribute('checked', '');
        if (disabled) cb.setAttribute('disabled', '');
        cb.addEventListener('change', () => {
          if (cb.checked) {
            if (state.compare.length >= MAX_COMPARE) return;
            state.compare = [...state.compare, n.url];
          } else {
            state.compare = state.compare.filter(u => u !== n.url);
          }
          writeState(state);
          render();
          renderAll(state);
        });
        picker.appendChild(el('label', { class: 'compare-option' }, [
          cb, ` ${shortName(n.url)}`,
          n.region ? el('span', { class: 'muted' }, ` · ${n.region}`) : null,
        ]));
      }
      toggle.textContent = state.compare.length
        ? `Compare: ${state.compare.length}/${MAX_COMPARE}`
        : '+ add node';
    }

    toggle.addEventListener('click', () => {
      const expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!expanded));
      picker.hidden = expanded;
    });

    render();
  }

  // ---- Data fetch ----------------------------------------------------------
  async function fetchDetail(url, range) {
    return getJson(`/api/v1/nodes/${encodeURIComponent(url)}/detail?range=${range}`);
  }

  // ---- Header --------------------------------------------------------------
  function renderHeader(state, primary, statusForNode) {
    document.getElementById('node-title').textContent = shortName(state.url);
    const sn = statusForNode(state.url);
    document.getElementById('node-region').textContent = sn?.region || '—';
    const pill = document.getElementById('node-status-pill');
    pill.dataset.status = sn?.status || 'unknown';
    document.getElementById('node-status-label').textContent = (sn?.status || 'unknown').toUpperCase();
    document.getElementById('node-score').textContent = sn?.score != null ? `score ${sn.score}` : 'score —';
  }

  // ---- Latency chart with compare overlay ----------------------------------
  let latencyChart = null;
  function renderLatencyChart(nodeDatasets, range) {
    const canvas = document.getElementById('latency-chart');
    const c = window.SteemAPI.chartColors();
    // Align X axis: the primary's point timestamps are the X reference.
    // Chart.js does fine with mismatched lengths per dataset as long as
    // each dataset provides its own labels via {x, y} pairs.
    const datasets = nodeDatasets.map((d, i) => ({
      label: shortName(d.url),
      data: d.points.map(p => ({ x: p.ts, y: p.success ? p.latency_ms : null })),
      borderColor: PALETTE[i % PALETTE.length],
      backgroundColor: PALETTE[i % PALETTE.length] + '22',
      borderWidth: 1.8,
      tension: 0.25,
      pointRadius: 0,
      spanGaps: false,
    }));

    if (latencyChart) { latencyChart.destroy(); latencyChart = null; }

    latencyChart = new Chart(canvas, {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        parsing: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            mode: 'index', intersect: false,
            callbacks: {
              title: items => items.length ? new Date(items[0].parsed.x).toISOString().replace('T', ' ').slice(0, 19) + ' UTC' : '',
              label: item => `${item.dataset.label}: ${item.parsed.y == null ? 'down' : item.parsed.y + ' ms'}`,
            },
          },
        },
        scales: {
          x: {
            type: 'time',
            time: { unit: range === '24h' ? 'hour' : 'day' },
            ticks: { color: c.tick, maxTicksLimit: 8 },
            grid: { color: c.grid },
          },
          y: {
            beginAtZero: true,
            ticks: { color: c.tick, callback: v => v + ' ms' },
            grid: { color: c.grid },
          },
        },
      },
    });

    // Custom legend so colour chips stay visible when the chart redraws.
    const legend = document.getElementById('latency-legend');
    legend.innerHTML = '';
    nodeDatasets.forEach((d, i) => {
      legend.appendChild(el('span', { class: 'legend-chip' }, [
        el('span', { class: 'chip-swatch', style: `background:${PALETTE[i % PALETTE.length]}` }),
        shortName(d.url),
      ]));
    });
  }

  // ---- Percentile table ----------------------------------------------------
  function renderPercentileTable(nodeDatasets, range) {
    const tbody = document.querySelector('#percentile-table tbody');
    tbody.innerHTML = '';
    nodeDatasets.forEach((d, i) => {
      const s = d.latency_stats || {};
      tbody.appendChild(el('tr', {}, [
        el('td', {}, [
          el('span', { class: 'chip-swatch small', style: `background:${PALETTE[i % PALETTE.length]}` }),
          ` ${shortName(d.url)}`,
        ]),
        el('td', {}, fmtLatency(s.min)),
        el('td', {}, s.avg == null ? '—' : String(s.avg)),
        el('td', {}, s.p50 == null ? '—' : String(s.p50)),
        el('td', {}, s.p95 == null ? '—' : String(s.p95)),
        el('td', {}, s.p99 == null ? '—' : String(s.p99)),
        el('td', {}, fmtLatency(s.max)),
        el('td', {}, String(s.sample_size ?? 0)),
        el('td', {}, `${fmtPct(d.uptime?.uptime_pct)}%`),
      ]));
    });
    document.getElementById('percentile-range').textContent = `last ${range}`;
  }

  // ---- Uptime calendar -----------------------------------------------------
  function uptimeColorClass(pct) {
    if (pct == null) return 'grey';
    if (pct >= 99) return 'green';
    if (pct >= 95) return 'yellow';
    return 'red';
  }

  function renderUptimeCalendar(daily) {
    const root = document.getElementById('uptime-calendar');
    root.innerHTML = '';
    for (const d of daily) {
      const cls = uptimeColorClass(d.uptime_pct);
      const cell = el('div', {
        class: `cal-cell ${cls}`,
        title: d.uptime_pct == null
          ? `${d.date} · no data`
          : `${d.date} · ${d.uptime_pct}% (${d.ok}/${d.total})`,
      });
      root.appendChild(cell);
    }
  }

  // ---- Outages table -------------------------------------------------------
  function renderOutages(outages) {
    const tbody = document.querySelector('#outages-table tbody');
    tbody.innerHTML = '';
    document.getElementById('outage-count').textContent =
      outages.length === 0 ? 'none in the last 30 days' : `${outages.length} outage(s) in the last 30 days`;
    if (outages.length === 0) {
      tbody.appendChild(el('tr', {}, el('td', { colspan: '5', class: 'loading' }, 'No outages on record — clean run.')));
      return;
    }
    for (const o of outages) {
      tbody.appendChild(el('tr', {}, [
        el('td', {}, o.start.replace('T', ' ').replace('Z', '')),
        el('td', {}, o.ongoing ? 'ongoing' : o.end.replace('T', ' ').replace('Z', '')),
        el('td', {}, fmtDuration(o.duration_s)),
        el('td', {}, el('span', { class: `sev-pill sev-${o.severity}` }, o.severity.toUpperCase())),
        el('td', { class: 'muted' }, o.error_sample || '—'),
      ]));
    }
  }

  // ---- Block-lag chart -----------------------------------------------------
  let blockLagChart = null;
  function renderBlockLagChart(points, range) {
    const canvas = document.getElementById('block-lag-chart');
    const c = window.SteemAPI.chartColors();
    const data = points.map(p => ({ x: p.ts, y: p.block_lag }));
    if (blockLagChart) { blockLagChart.destroy(); blockLagChart = null; }
    blockLagChart = new Chart(canvas, {
      type: 'line',
      data: {
        datasets: [{
          label: 'block_lag',
          data,
          borderColor: c.deg,
          backgroundColor: c.deg + '22',
          borderWidth: 1.4,
          pointRadius: 0,
          tension: 0.25,
          fill: true,
          spanGaps: false,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            type: 'time',
            time: { unit: range === '24h' ? 'hour' : 'day' },
            ticks: { color: c.tick, maxTicksLimit: 8 },
            grid: { color: c.grid },
          },
          y: {
            beginAtZero: true,
            ticks: { color: c.tick, precision: 0 },
            grid: { color: c.grid },
            title: { display: true, text: 'blocks behind', color: c.tick },
          },
        },
      },
    });
  }

  // ---- Orchestration -------------------------------------------------------
  async function renderAll(state) {
    const urls = [state.url, ...state.compare];
    try {
      const [detailPrimary, ...detailOthers] = await Promise.all(urls.map(u => fetchDetail(u, state.range)));
      const datasets = [{ url: state.url, ...detailPrimary }, ...detailOthers.map((d, i) => ({ url: state.compare[i], ...d }))];

      renderLatencyChart(datasets, state.range);
      renderPercentileTable(datasets, state.range);
      renderBlockLagChart(detailPrimary.block_lag_points, state.range);

      // Uptime calendar and outages are only fetched for the primary node
      // — comparing calendars for four nodes would drown the layout.
      const [daily, outages] = await Promise.all([
        getJson(`/api/v1/nodes/${encodeURIComponent(state.url)}/uptime-daily?days=30`),
        getJson(`/api/v1/nodes/${encodeURIComponent(state.url)}/outages?range=30d&limit=200`),
      ]);
      renderUptimeCalendar(daily.uptime);
      renderOutages(outages.outages);

      clearError();
    } catch (e) {
      console.error(e);
      showError(`Failed to load node data: ${e.message}`);
    }
  }

  // ---- Bootstrap -----------------------------------------------------------
  async function main() {
    const state = readState();
    if (!state.url) {
      showError('No node URL provided. Use ?url=… in the address bar.');
      return;
    }
    writeState(state);  // normalise URL (drop unknown params, keep shape)
    wireBackLink();
    wireShare();

    try {
      const status = await getJson('/api/v1/status');
      const node = status.nodes.find(n => n.url === state.url);
      if (!node) {
        showError(`Unknown node: ${state.url}. Check the URL or go back to the overview.`);
        return;
      }
      renderHeader(state, node, (u) => status.nodes.find(n => n.url === u));
      wireRange(state);
      wireCompare(state, status.nodes);
    } catch (e) {
      console.error(e);
      showError(`Failed to reach the monitor API: ${e.message}`);
      return;
    }

    await renderAll(state);
  }

  main();
})();
