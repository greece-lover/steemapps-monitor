# Dashboard (Phase 4)

Single-page, vanilla-JS dashboard. Polls the monitor API every 60 seconds
and renders one card per node with live score, latency, 24-hour / 7-day
uptime, and a 60-minute latency sparkline.

The dashboard does **not** ship with the production service yet — Phase 4
keeps it local-only. Phase 5+ will deploy the static files to the production
server so `api.steemapps.com` can serve them publicly.

## Development

The monitor API binds to `127.0.0.1:8110` on the VM and UFW does not
expose it. Forward the port through SSH:

```bash
ssh -L 8110:127.0.0.1:8110 your-monitor-host
```

Then open `frontend/index.html` in any browser. The fetch calls default
to `http://localhost:8110`, which the tunnel forwards to the VM.

To point at a different host, use the query string:

```
file:///.../frontend/index.html?api=http://other-host:8110
```

## File layout

- `index.html` — markup only
- `css/main.css` — dark theme, Inter Tight + Fraunces, mobile breakpoint at 600 px
- `js/main.js` — fetch, render, Chart.js sparklines
- No build step. Chart.js loads from jsdelivr CDN.

## Production-ready?

Not yet. Before deploying to the production server:

- Switch the CDN import to a pinned SRI-hashed URL or self-host Chart.js
- Add a CSP header
- Replace the loopback default with an explicit `window.API_BASE` set at
  build time or by a tiny config-loader
- Decide whether the dashboard lives at `/api.steemapps.com/` or
  `steemapps.com/api/` and bake that into the fetch URLs
