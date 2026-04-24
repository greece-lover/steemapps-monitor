// Dashboard rendering logic.
//
// Polls /api/v1/status every 60 s for the headline numbers, and /history
// + /uptime once per node per render for the sparkline and the 24 h / 7 d
// uptime stats. The API base URL is auto-detected: when the page is
// served from the VM itself the request is loopback; when developed
// locally through an SSH tunnel it's http://localhost:8110. Override via
// `?api=` query param if you want to point at a different host.

(() => {
  const DEFAULT_API = 'http://localhost:8110';
  const API_BASE = (new URL(window.location.href).searchParams.get('api')) || DEFAULT_API;
  const REFRESH_MS = 60_000;

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

  async function refresh() {
    try {
      const status = await getJson('/api/v1/status');
      clearError();

      document.getElementById('meta-methodology').textContent = status.methodology_version;
      document.getElementById('meta-refblock').textContent =
        status.reference_block == null ? '—' : status.reference_block.toLocaleString('en-US');
      document.getElementById('meta-updated').textContent = status.generated_at;

      const container = document.getElementById('nodes');
      container.innerHTML = '';
      for (const n of status.nodes) container.appendChild(buildCard(n));

      // Fire hydration calls per node in parallel. They don't block the
      // next refresh — if one is slow we just update late.
      status.nodes.forEach(n => { hydrateNode(n).catch(e => console.warn('hydrate failed', n.url, e)); });
    } catch (e) {
      console.error(e);
      showError(`Failed to reach the monitor API at ${API_BASE}. Is the SSH tunnel up?`);
    }
  }

  // Kick off.
  refresh();
  setInterval(refresh, REFRESH_MS);
})();
