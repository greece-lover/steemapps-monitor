// Regions page: Leaflet map with pins per region + aggregate table.
//
// Pin colour tracks the region's aggregated status (green/yellow/red/grey).
// Popup lists all nodes in the region with latency + 7-day uptime and a
// link to their detail page. Regions without a geographic anchor
// (global / unknown) are absent from the map but still shown in the
// table underneath.

(() => {
  const { API_BASE, el, getJson, showError, clearError, fmtPct } = window.SteemAPI;

  const STATUS_COLORS = {
    ok: '#5eea88',
    warning: '#e8c34a',
    critical: '#e8c34a',
    down: '#ef6a6a',
    unknown: '#4b4b4b',
  };

  function shortName(url) { return url.replace(/^https?:\/\//, ''); }

  function detailHref(url) {
    const p = new URLSearchParams({ url });
    if (API_BASE) p.set('api', API_BASE);
    return `node.html?${p.toString()}`;
  }

  // ---- Map setup ---------------------------------------------------------
  function initMap() {
    // CartoDB Dark Matter fits the dashboard's dark palette without
    // requiring an API key.
    const map = L.map('region-map', {
      center: [25, 10],
      zoom: 2,
      minZoom: 1,
      worldCopyJump: true,
      attributionControl: true,
    });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(map);
    return map;
  }

  // ---- Pin popup ---------------------------------------------------------
  function popupHtml(region) {
    const header = `<div class="popup-region">${region.label}</div>
      <div class="popup-sub">${region.node_count} node(s) · status: <span class="popup-status" data-status="${region.status}">${region.status.toUpperCase()}</span></div>`;
    const rows = region.nodes.map(n => {
      const lat = n.latency_ms == null ? '—' : `${n.latency_ms} ms`;
      const up = n.uptime_pct_7d == null ? '—' : `${n.uptime_pct_7d}%`;
      return `<li><a class="popup-node" href="${detailHref(n.url)}">${shortName(n.url)}</a><span class="popup-lat">${lat}</span><span class="popup-up">${up} / 7d</span></li>`;
    }).join('');
    return `${header}<ul class="popup-nodes">${rows}</ul>`;
  }

  // ---- Pins --------------------------------------------------------------
  function addRegionPins(map, regions) {
    const bounds = [];
    for (const r of regions) {
      if (r.lat == null || r.lng == null) continue;
      const color = STATUS_COLORS[r.status] || STATUS_COLORS.unknown;
      const marker = L.circleMarker([r.lat, r.lng], {
        radius: 8 + Math.min(6, r.node_count * 2),
        color: color,
        weight: 2,
        fillColor: color,
        fillOpacity: 0.6,
      }).bindPopup(popupHtml(r), { className: 'region-popup', maxWidth: 320 });
      marker.addTo(map);
      bounds.push([r.lat, r.lng]);
    }
    if (bounds.length > 1) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 3 });
    }
  }

  // ---- Regional aggregate table -----------------------------------------
  function renderTable(regions) {
    const tbody = document.querySelector('#regions-table tbody');
    tbody.innerHTML = '';
    if (regions.length === 0) {
      tbody.appendChild(el('tr', {}, el('td', { colspan: '6', class: 'loading' }, 'No regions.')));
      return;
    }
    for (const r of regions) {
      const lat = r.avg_latency_ms == null ? '—' : `${r.avg_latency_ms} ms`;
      const up = r.avg_uptime_pct_24h == null ? '—' : `${fmtPct(r.avg_uptime_pct_24h)}%`;
      const coords = (r.lat == null || r.lng == null)
        ? '—'
        : `${r.lat.toFixed(2)}, ${r.lng.toFixed(2)}`;
      tbody.appendChild(el('tr', {}, [
        el('td', {}, r.label),
        el('td', {}, String(r.node_count)),
        el('td', {}, lat),
        el('td', {}, up),
        el('td', {}, el('span', { class: 'status-pill small', dataset: { status: r.status } }, [
          el('span', { class: 'dot' }),
          r.status.toUpperCase(),
        ])),
        el('td', { class: 'muted' }, coords),
      ]));
    }
  }

  // ---- Bootstrap ---------------------------------------------------------
  async function main() {
    const map = initMap();
    try {
      const body = await getJson('/api/v1/regions');
      addRegionPins(map, body.regions);
      renderTable(body.regions);
      clearError();
    } catch (e) {
      console.error(e);
      showError(`Failed to load regions: ${e.message}`);
    }
  }

  main();
})();
