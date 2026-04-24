# 2026-04-25 — Phase 6 Etappe 4

Regional-Karte `regions.html` mit Leaflet.js: Weltkarte im Dark-Theme,
Pins pro Region nach aktuellem Status, Popup mit Node-Liste inkl.
Link auf die Detail-Seite, regionale Aggregat-Tabelle darunter.

## Umgesetzt

### Backend

**Neuer Endpoint** `GET /api/v1/regions` — pro Region:

- `label` (menschenlesbar, aus `REGION_COORDINATES`)
- `lat` / `lng` (`None` für nicht-geografische Regionen)
- `node_count`, `avg_latency_ms`, `avg_uptime_pct_24h`
- aggregierter `status` (down, wenn ≥1 Node down; warning, wenn ≥1
  degraded; sonst ok; unknown, wenn keine Daten)
- Liste `nodes` mit `{url, status, score, latency_ms,
  uptime_pct_24h, uptime_pct_7d}`

Die Regionen werden sortiert: verankerte Regionen zuerst (alphabetisch
nach Label), danach `lat is None`-Einträge (global, unknown). TTL-Cache 60 s.

**Neue Konstante** `config.REGION_COORDINATES` mappt jede Region aus
`nodes.json` auf ein ungefähres geografisches Zentrum:

| Region | Label | lat, lng |
|---|---|---|
| us-east | US East | 40.71, -74.01 (NYC) |
| us-west | US West | 37.77, -122.42 (Bay) |
| us-central | US Central | 32.78, -96.80 (Dallas) |
| asia | Asia | 1.35, 103.82 (Singapore) |
| eu-central | Europe Central | 50.11, 8.68 (Frankfurt) |
| global | Global / CDN | null / null |
| unknown | Unknown | null / null |

**Tests** — 2 neue Fälle (74 / 74 grün):

- `regions`-Aggregation pro Region rechnet `avg_latency_ms` und
  `uptime_pct` pro Gruppe; getrennte Regionen bekommen getrennte Werte.
- Anchorless-Regionen (`global`) behalten `lat`/`lng`=None und sortieren
  hinter verankerte Regionen.

### Frontend — neue Seite `regions.html` + `js/regions.js`

**Leaflet 1.9.4** via CDN (`leaflet.css` + `leaflet.js`, mit SRI-
Integrity-Hashes).

**Tile-Provider:** CartoDB Dark Matter (passt zum Dark-Dashboard, kein
API-Key nötig, Attribution eingeblendet). Fallback-Strategie ist nicht
nötig — Open-Data-Tiles sind sehr stabil.

**Pins** als `L.circleMarker`:

- Farbe nach `region.status`: grün (ok), gelb (warning/critical),
  rot (down), grau (unknown).
- Radius skaliert mit `node_count` (8 px + 2 px pro Node, max 14 px),
  damit Regionen mit mehr Nodes visuell präsenter sind.
- Regionen ohne Koordinaten (`lat is None`) werden nicht gezeichnet,
  erscheinen aber in der Tabelle.

**Popup** öffnet bei Pin-Klick:

- Header mit Region-Label, Node-Count und farbigem Status-String.
- Liste aller Nodes der Region: Node-Name (Mono-Font, Link zur
  Detail-Seite mit `?api=`-Override-Passthrough), aktuelle Latenz,
  7-Tage-Uptime.

**Regionale Aggregate-Tabelle** unter der Karte:

| Region | Nodes | Avg latency | Avg uptime | Status | Coordinates |
|---|---|---|---|---|---|

Koordinaten werden mit `.toFixed(2)` angezeigt oder als `—` für
anchorless.

**CSS-Overrides** für Leaflet:

- `.leaflet-container`-Hintergrund auf `--bg-card`, Schriftfamilie auf
  `--body`.
- Zoom-Steuerung und Attribution in dunkle Hülle (`rgba(20,20,20,0.85)`),
  Link-Akzent in `--accent`.
- Popup-Container in `--bg-raised` mit Border, damit der Stil nahtlos zum
  Rest des Dashboards passt.
- `.status-pill.small`-Variante für die kompakte Tabellen-Darstellung
  mit Border statt Hintergrund.

### Navigation-Konsistenz

Alle vier HTML-Seiten (`index.html`, `node.html`, `stats.html`,
`regions.html`) führen denselben Nav-Block **Overview · Stats · Regions**.
Die aktive Seite markiert ihre eigene `<a>` mit `.active`. Der
`decorateNavLinks()`-Helper aus `common.js` hängt den `?api=`-Dev-
Override auf allen Nav-Links an.

## Smoke-Test lokal (curl)

```
regions.html                                     HTTP 200, 2.8 KB (5 IDs)
regions.js                                       HTTP 200, 4.6 KB
/api/v1/regions                                  HTTP 200
```

Regions-Output (Mock-DB, 10 Nodes, 6 Regionen):

```
Asia             ANCHOR     count=2  lat=288.9ms up=100.0%  status=ok
Europe Central   ANCHOR     count=2  lat=480.9ms up=100.0%  status=ok
US Central       ANCHOR     count=1  lat=628.4ms up=100.0%  status=ok
US East          ANCHOR     count=1  lat=348.3ms up=99.58%  status=ok
US West          ANCHOR     count=1  lat=307.4ms up=97.92%  status=ok
Global / CDN     no-anchor  count=2  lat=231.9ms up=100.0%  status=ok
Unknown          no-anchor  count=1  lat=387.4ms up=100.0%  status=ok
```

(Die Asia-2-Nodes-Zelle enthält `api.steem.fans` + `api.campingclub.me`,
Europe Central hat `steemd.steemworld.org` + `api.moecki.online`.)

Nav-Konsistenz: alle vier Seiten verlinken auf `index.html`,
`stats.html`, `regions.html` in der Kopfzeile.

## Offen

- Ausfall-Log `outages.html` mit Export → Etappe 5.
- Theme-Umschalter, Autorefresh-Steuerung, Mobile-Feintuning → Etappe 6.
- 1-M-Messwerte-Benchmark-Skript → Etappe 6/7.
- Deployment auf production-server → Etappe 7.
- Visueller Browser-Smoke-Test aller vier Seiten → Ende Phase 6.

## Nächster Schritt

Freigabe auf Etappe 5 (Ausfall-Log + Export) oder Pause.
