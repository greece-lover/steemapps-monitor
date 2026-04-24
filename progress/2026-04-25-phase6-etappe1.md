# 2026-04-25 — Phase 6 Etappe 1

Neue API-Endpoints + Dashboard-Sortierung/Filter/URL-State. Kein
Deployment in dieser Etappe — läuft noch lokal auf der VM/Entwickler-
Maschine.

## Entscheidungen (abgestimmt)

- **Multi-Page** statt SPA: separate HTML-Dateien pro Unterseite sind
  einfacher zu debuggen, deep-linkbar ohne Router, Nginx serviert sie
  out-of-the-box. Etappe 1 ergänzt nur die bestehende `index.html`; die
  Seiten `node.html` / `stats.html` / `regions.html` / `outages.html`
  folgen in Etappen 2–5.
- **Kein Visual-Regression-Setup.** Puppeteer/Playwright-Dependency
  lohnt sich für Vanilla-JS-Dashboard nicht. Manuelle Browser-Tests
  durch den Nutzer und eine Screenshot-Galerie via
  `claude-in-chrome`-Tool am Ende von Phase 6.
- **TTL-Cache in-process, keine neue Dep.** `cache.py` mit 23 Zeilen,
  `@ttl_cache(seconds)`-Decorator, `cache_clear()` / `cache_info()`
  exponiert.
- **Ausfall-Definition** nach Konzept-Dokument: ab 120 s =
  `severity='real'`, darunter `'short'`. Als Konstante
  `database.OUTAGE_SEVERITY_THRESHOLD_S` exportiert, damit der
  Daily-Report-Generator aus Phase 5 denselben Wert nutzen kann.

## Umgesetzt

### Neue Datei `cache.py`

In-Memory-TTL-Cache als Decorator. Key = `(args, tuple(sorted(kwargs)))`,
expiry pro Key. `wrapper.cache_clear()` und `wrapper.cache_info()` für
Tests und spätere `/health`-Erweiterung. Nicht strikt thread-safe — die
FastAPI-Event-Loop serialisiert Aufrufe, worst case zwei Clients
berechnen einmal denselben Wert.

### Erweiterung `database.py`

- `get_measurements_range(node_url, lookback_minutes, db_path)` —
  zeitgeordnete Messungen eines Nodes im Fenster. Nutzt
  `idx_measurements_node_ts` laut EXPLAIN QUERY PLAN (`SEARCH USING
  INDEX`).
- `get_all_measurements_range(lookback_minutes, db_path)` — globale
  Variante, sortiert nach `node_url, timestamp` für die globale
  Outage-Aggregation. `SCAN USING INDEX idx_measurements_node_ts`
  (indexed, kein Full-Table).
- `OUTAGE_SEVERITY_THRESHOLD_S = 120` — Konstante für alle
  Outage-Konsumenten.
- `compute_outages(measurements, now_iso=None, severity_threshold_s=120)`
  — reiner In-Memory-Aggregator. Durchläuft die chronologische Liste,
  gruppiert `success=0`-Runs, annotiert `{start, end, duration_s,
  severity, error_sample, ongoing}`. Noch nicht wiederhergestellte
  Ausfälle erhalten `ongoing=True` und `end=now_iso`.
- `get_per_node_aggregates(lookback_minutes, db_path)` — Ein-Pass-SQL
  für avg_latency / success-Zähler / Gesamtzahl / uptime_pct pro Node.
  Basis für `/stats/top`.

### Erweiterung `api.py`

Neue Module-Helpers:

- `_range_minutes(range_str)` — `24h|7d|30d` → Minuten, mappt 422 auf
  unbekannte Werte.
- `_percentile(values, p)` — Linear-Interpolation-Perzentil. Stdlib-only.
- `_downsample(points, max_points=1500)` — Bucket-Mittelwert-Downsampling
  für Latenzpunkte. Outage-Marker bleiben erhalten: wenn in einem Bucket
  **irgendeine** Messung fehlgeschlagen ist, wird der aggregierte Punkt
  als `success=False` markiert, damit Ausfälle nicht wegmittelt werden.

Vier neue Routes (alle mit `@ttl_cache` auf Helper-Ebene — Helpers sind
innerhalb `build_app()` definiert, damit Tests pro App-Build einen
frischen Cache bekommen):

- `GET /api/v1/nodes/{url}/detail?range=24h|7d|30d` — Latenzpunkte,
  Block-Lag-Punkte, Uptime, Latenz-Stats mit min/max/avg/P50/P95/P99,
  Outage-Summary. TTL 30 s.
- `GET /api/v1/nodes/{url}/outages?range=24h|7d|30d&severity=short|real`
  — Ausfallliste pro Node. TTL 60 s.
- `GET /api/v1/outages?range=...&node=...&severity=...&limit=100` —
  globale Ausfall-Suche mit Filtern. TTL 60 s.
- `GET /api/v1/stats/top?metric=latency|uptime|errors&limit=10&range=24h`
  — Top-N-Ranking. TTL 60 s.

Alle Query-Parameter validiert (FastAPI `Query(..., pattern=...)`,
`ge/le`), FastAPI-422 bei ungültigen Werten.

### Frontend (`frontend/index.html`, `frontend/js/main.js`,
`frontend/css/main.css`)

Neues Filter-/Sort-Panel über dem Node-Grid:

- Region-Dropdown (dynamisch aus Status-Antwort gefüllt).
- Status-Checkboxen (ok/warning/critical/down, default alle an).
- Score-Schieberegler 0–100.
- Sort-Dropdown (name, region, latency, score, status) + Richtungs-
  Toggle-Button.
- Reset-Button.

URL-State via `URLSearchParams` + `history.replaceState` —
Filter-Einstellungen sind bookmarkbar. Der `?api=`-Dev-Override bleibt
unangetastet.

`renderNodes()` ist vom Fetch-Zyklus entkoppelt: ein neuer Fetch cached
`lastStatusResponse`, Filter-Änderungen rendern ohne erneuten
Netzwerk-Call. `sparkCharts`-Map wird bei jedem Render geleert, damit
Chart.js-Instanzen keine Listener über Stunden akkumulieren.

Kleine Mobile-Nachbesserung (bei 600 px bricht das Control-Panel um,
Reset-Button wandert ans Ende statt rechts außen).

### Tests

`tests/test_api_phase6.py` mit 11 Tests:

- `/detail` liefert korrekte Perzentile auf bekannten Latenzen
  (100..1000, P50 = 550, Avg = 550, sample_size = 10).
- 404 auf unbekannte Node, 422 auf ungültiges `range=`.
- Downsampling bei 2000 → ≤1500 Punkten.
- Outage-Detektor trennt `short` (60 s) von `real` (300 s).
- `severity=real`-Filter pro Node.
- Globaler Outage-Filter nach Node.
- `/stats/top` sortiert aufsteigend (latency), absteigend (uptime,
  errors).
- 422 auf unbekannte Metrik.

Ergebnis: **65 / 65 Tests grün** (54 bestand + 11 neu).

## Smoke-Test lokal (Port 8112)

2400 Mock-Messungen für 10 Nodes, 4 h Fenster, darin ein short outage
(Node 0, 60 s) und ein real outage (Node 1, 300 s).

```
detail (Node 0)
  points=240  uptime=99.58%  outages={1 short, 0 real}
  latency_stats={min:275, max:424, avg:348.3, p50:348, p95:416.1, p99:422.6}

node 0 outages     → 1 × short, 60 s        ✓
node 1 outages     → 1 × real, 300 s        ✓
global severity=real → 1 × justyy.com, 300 s ✓

top latency asc    → campingclub 190 ms, api2.steemyy 228 ms, …
top uptime desc    → drei Nodes 100 %
top errors desc    → justyy 5, steemit 1, rest 0
```

## Offen (folgt in späteren Etappen)

- Dashboard-Seiten `node.html`, `stats.html`, `regions.html`,
  `outages.html` → Etappen 2–5.
- Globaler Status-Indikator, Theme-Umschalter, Autorefresh-Steuerung →
  Etappe 6.
- 1 M-Messwerte-Benchmark-Skript → Etappe 6/7.
- Deployment auf den Produktionsserver → Etappe 7.

## Nächster Schritt

Auf Freigabe warten; bei „weiter" starte ich Etappe 2 (Detail-Ansicht
pro Node mit Charts).
