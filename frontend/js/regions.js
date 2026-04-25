// Regions page: Leaflet map with two marker layers — monitored nodes
// (per-region circles, colour by status) and measurement sources
// (lime diamonds, one per active source).
//
// Both layers live in their own LayerGroup so the auto-refresh hook
// can wipe and redraw without clobbering tile layers or duplicating
// pins. Anchorless regions / sources (lat=null) are filtered out at
// render time but still appear in the table underneath.

(() => {
  const { API_BASE, el, getJson, showError, clearError, fmtPct, fmtDuration, onAutoRefresh } = window.SteemAPI;

  const STATUS_COLORS = {
    ok: '#5eea88',
    warning: '#e8c34a',
    critical: '#e8c34a',
    down: '#ef6a6a',
    unknown: '#4b4b4b',
  };

  // Lime; matches --accent in the dark theme. Bright enough to read
  // against the CartoDB dark-matter tile layer without competing with
  // the green "ok" status circles.
  const SOURCE_COLOR = '#b7e34a';

  function shortName(url) { return url.replace(/^https?:\/\//, ''); }

  function detailHref(url) {
    const p = new URLSearchParams({ url });
    if (API_BASE) p.set('api', API_BASE);
    return `node.html?${p.toString()}`;
  }

  function ago(iso) {
    if (!iso) return 'never';
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }

  // ---- Map setup ---------------------------------------------------------
  function initMap() {
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

  // ---- Region (node) pins ------------------------------------------------
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

  function renderRegionPins(layer, regions) {
    layer.clearLayers();
    const bounds = [];
    for (const r of regions) {
      if (r.lat == null || r.lng == null) continue;
      const color = STATUS_COLORS[r.status] || STATUS_COLORS.unknown;
      L.circleMarker([r.lat, r.lng], {
        radius: 8 + Math.min(6, r.node_count * 2),
        color: color,
        weight: 2,
        fillColor: color,
        fillOpacity: 0.6,
      })
        .bindPopup(popupHtml(r), { className: 'region-popup', maxWidth: 320 })
        .addTo(layer);
      bounds.push([r.lat, r.lng]);
    }
    return bounds;
  }

  // ---- Source markers (lime diamonds) -----------------------------------
  // SVG-driven divIcon so we get a real diamond shape (Leaflet's default
  // CircleMarker would not look distinct enough next to the node circles).
  // Multiple sources at the same anchor get stacked with a small angular
  // jitter so they do not overlap pixel-perfectly.
  function sourceIcon() {
    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14" width="14" height="14">
        <rect x="2" y="2" width="10" height="10" transform="rotate(45 7 7)"
              fill="${SOURCE_COLOR}" stroke="#0a0a0a" stroke-width="1.5"/>
      </svg>`;
    return L.divIcon({
      html: svg,
      className: 'source-marker',
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
  }

  function sourcePopupHtml(s) {
    const role = s.primary ? 'Primary monitor' : 'Community contributor';
    const account = `<a href="https://steemit.com/@${encodeURIComponent(s.steem_account)}" target="_blank" rel="noopener">@${s.steem_account}</a>`;
    return `<div class="popup-region">${s.display_label}</div>
      <div class="popup-sub">${role} · ${account}</div>
      <ul class="popup-nodes">
        <li><span class="popup-lat">Region</span><span class="popup-up">${s.region_label}</span></li>
        <li><span class="popup-lat">24h measurements</span><span class="popup-up">${s.measurements_24h}</span></li>
        <li><span class="popup-lat">Last seen</span><span class="popup-up">${ago(s.last_seen)}</span></li>
      </ul>
      <div class="popup-sub" style="margin-top:6px"><a class="popup-node" href="sources.html">All sources →</a></div>`;
  }

  // Fan out duplicate-anchor sources around their region centre. Offsets
  // are computed in degrees (~110 km / degree at the equator); 0.6° puts
  // markers visually distinct without leaving the country.
  function offsetForIndex(i, total) {
    if (total <= 1) return [0, 0];
    const angle = (2 * Math.PI * i) / total;
    return [Math.sin(angle) * 0.6, Math.cos(angle) * 0.6];
  }

  function renderSourceMarkers(layer, sources) {
    layer.clearLayers();
    // Group by exact anchor coords so we know how many to fan out.
    const groups = new Map();
    for (const s of sources) {
      if (s.lat == null || s.lng == null) continue;
      const key = `${s.lat},${s.lng}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(s);
    }
    const icon = sourceIcon();
    for (const arr of groups.values()) {
      arr.forEach((s, i) => {
        const [dlat, dlng] = offsetForIndex(i, arr.length);
        L.marker([s.lat + dlat, s.lng + dlng], { icon, riseOnHover: true })
          .bindPopup(sourcePopupHtml(s), { className: 'region-popup', maxWidth: 320 })
          .addTo(layer);
      });
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
  // Map and the two layer groups are constructed once; reload() repaints
  // them. fitBounds runs only on first paint so the user's pan/zoom
  // survives auto-refresh.
  let firstPaint = true;

  async function reload(map, regionLayer, sourceLayer) {
    try {
      const [regionsBody, sourcesBody] = await Promise.all([
        getJson('/api/v1/regions'),
        getJson('/api/v1/sources/locations'),
      ]);
      const bounds = renderRegionPins(regionLayer, regionsBody.regions);
      renderSourceMarkers(sourceLayer, sourcesBody.sources);
      renderTable(regionsBody.regions);
      if (firstPaint && bounds.length > 1) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 3 });
      }
      firstPaint = false;
      clearError();
    } catch (e) {
      console.error(e);
      showError(`Failed to load regions: ${e.message}`);
    }
  }

  async function main() {
    const map = initMap();
    const regionLayer = L.layerGroup().addTo(map);
    const sourceLayer = L.layerGroup().addTo(map);
    await reload(map, regionLayer, sourceLayer);
    onAutoRefresh(() => reload(map, regionLayer, sourceLayer));
  }

  main();
})();
