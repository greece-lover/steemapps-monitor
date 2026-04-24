// Statistics overview: four rankings, chain availability stacked area,
// global latency multi-line chart, biggest outages, day-over-day table.
//
// One page-scoped IIFE like the other dashboard scripts. Depends on the
// shared `SteemAPI` global from common.js.

(() => {
  const { API_BASE, el, getJson, showError, clearError, fmtLatency, fmtPct, fmtDuration } = window.SteemAPI;

  // Ten visually-distinct hues for the 10-node overlay. The first four
  // match node.html's compare palette so the colours feel consistent
  // across pages.
  const PALETTE_10 = [
    '#b7e34a', '#5b9bff', '#c48bff', '#f5a462',
    '#5eea88', '#ef6a6a', '#e8c34a', '#56d0d0',
    '#ff8fc7', '#c0c0c0',
  ];

  // ---- Back-/nav-link api-override pass-through --------------------------
  function wireNav() {
    const apiOverride = new URL(window.location.href).searchParams.get('api');
    if (!apiOverride) return;
    for (const id of ['back-link', 'nav-overview']) {
      const a = document.getElementById(id);
      if (!a) continue;
      const href = new URL(a.getAttribute('href'), window.location.href);
      href.searchParams.set('api', apiOverride);
      a.setAttribute('href', href.pathname + href.search);
    }
  }

  function shortName(url) { return url.replace(/^https?:\/\//, ''); }

  // =========================================================================
  //  Rankings
  // =========================================================================
  function renderRankingCard(elementId, ranked, metricLabel, valueFn) {
    const card = document.getElementById(elementId);
    const list = card.querySelector('.ranking-list');
    list.innerHTML = '';
    if (ranked.length === 0) {
      list.appendChild(el('li', { class: 'loading' }, 'No data yet.'));
      return;
    }
    ranked.slice(0, 3).forEach((r, i) => {
      list.appendChild(el('li', {}, [
        el('span', { class: 'rank' }, `${i + 1}.`),
        el('span', { class: 'rank-name' }, shortName(r.node_url)),
        el('span', { class: 'rank-value' }, valueFn(r)),
      ]));
    });
  }

  async function loadRankings(range) {
    const [fastest, slowest, best, worst] = await Promise.all([
      getJson(`/api/v1/stats/top?metric=latency&range=${range}&limit=3`),
      getJson(`/api/v1/stats/top?metric=latency_worst&range=${range}&limit=3`),
      getJson(`/api/v1/stats/top?metric=uptime&range=${range}&limit=3`),
      getJson(`/api/v1/stats/top?metric=uptime_worst&range=${range}&limit=3`),
    ]);
    renderRankingCard('card-fastest', fastest.ranked, 'latency', r => `${r.avg_latency_ms ?? '—'} ms`);
    renderRankingCard('card-slowest', slowest.ranked, 'latency', r => `${r.avg_latency_ms ?? '—'} ms`);
    renderRankingCard('card-best-uptime', best.ranked, 'uptime', r => `${r.uptime_pct.toFixed(2)}%`);
    renderRankingCard('card-worst-uptime', worst.ranked, 'uptime', r => `${r.uptime_pct.toFixed(2)}%`);
  }

  // =========================================================================
  //  Chain availability
  // =========================================================================
  let availabilityChart = null;
  async function loadAvailability(range) {
    const data = await getJson(`/api/v1/stats/chain-availability?range=${range}`);
    const canvas = document.getElementById('availability-chart');
    const c = window.SteemAPI.chartColors();
    const labels = data.points.map(p => p.ts);
    const up = data.points.map(p => p.up);
    const down = data.points.map(p => p.down);
    if (availabilityChart) { availabilityChart.destroy(); availabilityChart = null; }
    availabilityChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'up', data: up, borderColor: c.ok, backgroundColor: c.ok + '55', fill: 'origin', stack: 'fleet', tension: 0.25, pointRadius: 0, borderWidth: 1.2 },
          { label: 'down', data: down, borderColor: c.down, backgroundColor: c.down + '55', fill: 'origin', stack: 'fleet', tension: 0.25, pointRadius: 0, borderWidth: 1.2 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: {
          legend: { labels: { color: c.tick } },
          tooltip: {
            mode: 'index', intersect: false,
            callbacks: {
              title: items => items.length ? String(items[0].label).replace('T', ' ').replace('Z', ' UTC') : '',
            },
          },
        },
        scales: {
          x: {
            type: 'time',
            time: { unit: range === '24h' ? 'hour' : 'day' },
            ticks: { color: c.tick, maxTicksLimit: 10 },
            grid: { color: c.grid },
          },
          y: {
            stacked: true,
            beginAtZero: true,
            ticks: { color: c.tick, precision: 0 },
            grid: { color: c.grid },
            title: { display: true, text: 'ticks / bucket', color: c.tick },
          },
        },
      },
    });
  }

  // =========================================================================
  //  Global latency multi-line
  // =========================================================================
  let globalLatencyChart = null;
  async function loadGlobalLatency(range) {
    // Pull /status for the node list, then /detail per node in parallel.
    // Cached server-side, so repeat loads in the same minute are cheap.
    const c = window.SteemAPI.chartColors();
    const status = await getJson('/api/v1/status');
    const details = await Promise.all(
      status.nodes.map(n => getJson(`/api/v1/nodes/${encodeURIComponent(n.url)}/detail?range=${range}`)
        .then(d => ({ url: n.url, region: n.region, points: d.points }))
        .catch(() => null))
    );
    const valid = details.filter(Boolean);

    const canvas = document.getElementById('global-latency-chart');
    const datasets = valid.map((d, i) => ({
      label: shortName(d.url),
      data: d.points.map(p => ({ x: p.ts, y: p.success ? p.latency_ms : null })),
      borderColor: PALETTE_10[i % PALETTE_10.length],
      borderWidth: 1.2,
      tension: 0.25,
      pointRadius: 0,
      spanGaps: false,
    }));
    if (globalLatencyChart) { globalLatencyChart.destroy(); globalLatencyChart = null; }
    globalLatencyChart = new Chart(canvas, {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
        plugins: {
          legend: { display: false },
          tooltip: { mode: 'index', intersect: false },
        },
        scales: {
          x: {
            type: 'time',
            time: { unit: range === '24h' ? 'hour' : 'day' },
            ticks: { color: c.tick, maxTicksLimit: 10 },
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

    const legend = document.getElementById('global-latency-legend');
    legend.innerHTML = '';
    valid.forEach((d, i) => {
      legend.appendChild(el('span', { class: 'legend-chip' }, [
        el('span', { class: 'chip-swatch', style: `background:${PALETTE_10[i % PALETTE_10.length]}` }),
        shortName(d.url),
      ]));
    });
  }

  // =========================================================================
  //  Biggest outages of the week
  // =========================================================================
  async function loadBiggestOutages() {
    const body = await getJson('/api/v1/outages?range=7d&severity=real&limit=200');
    const outages = body.outages.slice().sort((a, b) => b.duration_s - a.duration_s).slice(0, 10);
    const tbody = document.querySelector('#biggest-outages tbody');
    tbody.innerHTML = '';
    document.getElementById('biggest-count').textContent =
      outages.length === 0 ? 'none recorded this week — clean fleet.' : `top ${outages.length} of the week`;
    if (outages.length === 0) {
      tbody.appendChild(el('tr', {}, el('td', { colspan: '6', class: 'loading' }, 'No real outages in the last 7 days.')));
      return;
    }
    for (const o of outages) {
      tbody.appendChild(el('tr', {}, [
        el('td', {}, el('a', {
          href: `node.html?url=${encodeURIComponent(o.node_url)}${API_BASE ? `&api=${encodeURIComponent(API_BASE)}` : ''}`,
          class: 'inline-link',
        }, shortName(o.node_url))),
        el('td', {}, o.start.replace('T', ' ').replace('Z', '')),
        el('td', {}, o.ongoing ? 'ongoing' : o.end.replace('T', ' ').replace('Z', '')),
        el('td', {}, fmtDuration(o.duration_s)),
        el('td', {}, el('span', { class: `sev-pill sev-${o.severity}` }, o.severity.toUpperCase())),
        el('td', { class: 'muted' }, o.error_sample || '—'),
      ]));
    }
  }

  // =========================================================================
  //  Daily comparison
  // =========================================================================
  // Returns an object for rendering: value cell with trend arrow.
  // `higherIsBetter`=false for latency (higher = worse), true for uptime.
  function trendCell(current, previous, higherIsBetter, formatter) {
    if (current == null || previous == null) {
      return el('td', { class: 'muted' }, formatter(current));
    }
    const delta = current - previous;
    const pct = previous === 0 ? 0 : Math.abs(delta / previous) * 100;
    let arrow = '→', direction = 'flat';
    if (pct >= 3) {
      if (delta > 0) {
        arrow = '↑'; direction = higherIsBetter ? 'better' : 'worse';
      } else {
        arrow = '↓'; direction = higherIsBetter ? 'worse' : 'better';
      }
    }
    return el('td', {}, [
      el('span', { class: 'trend-val' }, formatter(current)),
      el('span', { class: `trend-arrow ${direction}`, title: `${delta > 0 ? '+' : ''}${delta.toFixed(1)} (${pct.toFixed(1)}%)` }, arrow),
    ]);
  }

  async function loadDailyComparison() {
    const data = await getJson('/api/v1/stats/daily-comparison');
    const tbody = document.querySelector('#daily-comparison tbody');
    tbody.innerHTML = '';
    if (data.nodes.length === 0) {
      tbody.appendChild(el('tr', {}, el('td', { colspan: '7', class: 'loading' }, 'No data.')));
      return;
    }
    const fmtMs = v => v == null ? '—' : `${v}`;
    const fmtUp = v => v == null ? '—' : `${v.toFixed(2)}%`;
    for (const row of data.nodes) {
      const tr = el('tr', {}, [
        el('td', {}, shortName(row.node_url)),
        el('td', {}, fmtMs(row.today.avg_latency_ms)),
        trendCell(row.today.avg_latency_ms, row.yesterday.avg_latency_ms, false, fmtMs),
        trendCell(row.today.avg_latency_ms, row.lastweek.avg_latency_ms, false, fmtMs),
        el('td', {}, fmtUp(row.today.uptime_pct)),
        trendCell(row.today.uptime_pct, row.yesterday.uptime_pct, true, fmtUp),
        trendCell(row.today.uptime_pct, row.lastweek.uptime_pct, true, fmtUp),
      ]);
      tbody.appendChild(tr);
    }
  }

  // =========================================================================
  //  Range-toggle wiring — each section has its own
  // =========================================================================
  function wireToggle(containerId, onChange, initial) {
    const c = document.getElementById(containerId);
    c.querySelectorAll('button').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.range === initial);
      btn.addEventListener('click', () => {
        c.querySelectorAll('button').forEach(b => b.classList.toggle('active', b === btn));
        onChange(btn.dataset.range);
      });
    });
  }

  // =========================================================================
  //  Bootstrap
  // =========================================================================
  async function main() {
    wireNav();
    try {
      wireToggle('ranking-range', r => loadRankings(r).catch(e => console.warn('rankings', e)), '24h');
      wireToggle('availability-range', r => loadAvailability(r).catch(e => console.warn('availability', e)), '24h');
      wireToggle('global-latency-range', r => loadGlobalLatency(r).catch(e => console.warn('global latency', e)), '24h');

      // Initial parallel load.
      await Promise.all([
        loadRankings('24h').catch(e => console.warn('rankings', e)),
        loadAvailability('24h').catch(e => console.warn('availability', e)),
        loadGlobalLatency('24h').catch(e => console.warn('global latency', e)),
        loadBiggestOutages().catch(e => console.warn('outages', e)),
        loadDailyComparison().catch(e => console.warn('daily', e)),
      ]);
      clearError();
    } catch (e) {
      console.error(e);
      showError(`Failed to load statistics: ${e.message}`);
    }
  }

  main();
})();
