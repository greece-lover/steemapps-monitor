# 2026-04-25 — Phase 6 Etappe 6

Theme-Umschalter (Dark/Light), Autorefresh-Steuerung, Mobile-Breakpoints
768/480 und 1-M-Messwerte-Benchmark-Skript. Als Bonus: eine Optimierung
von `get_per_node_aggregates`, die durch den Benchmark gefunden wurde
und Fleet-Aggregates von ~700 ms auf ~7 ms beschleunigt hat.

## Umgesetzt

### Theme-Umschalter

- CSS-Variablen in zwei Themes: `:root` (dark, unverändert) und
  `[data-theme="light"]` (neu).
- Light-Palette: Lime → Olive (#5a7d0f) für Kontrast auf Weiß, Status-
  grün/rot/gelb ebenfalls dunkler gezogen; `--chart-grid` und
  `--chart-tick` neu als explizite Variable für Chart-Achsen/Grid.
- `common.js`:
  - Liest `localStorage["steemapps_theme"]` beim allerersten Einlesen
    (vor DOMContentLoaded), setzt `data-theme="light"` auf `<html>`
    falls angegeben — kein Dark-Flash.
  - `wireThemeButton()` bindet `[data-theme-toggle]`-Button. Klick
    speichert das neue Theme in localStorage und macht `location.reload()`.
    Reload statt live-Switch, weil alle Chart.js-Instanzen beim Mount
    ihre Farben festschreiben — Neu-Init ist einfacher und fehlerärmer.
  - Neuer Helper `chartColors()` liest die aktuellen CSS-Variablen aus
    `getComputedStyle(document.documentElement)`, damit Chart-Configs
    keine Hex-Werte mehr hardcoden.
  - `main.js`, `node.js`, `stats.js` auf `chartColors()` umgestellt —
    alle Grids, Ticks, Legend- und Title-Farben nutzen jetzt das
    aktive Theme.

### Autorefresh-Steuerung

- Toolbar-`<select>` mit Optionen `live 10s / normal 60s / slow 5m /
  paused`. Auswahl persistiert in `localStorage["steemapps_autorefresh"]`.
- `common.js` exponiert `SteemAPI.onAutoRefresh(fn)` — Pages melden ihre
  Refresh-Callback an, der Helper armt einen gemeinsamen `setInterval`
  passend zum aktiven Wert und ruft die Callback synchron auf.
- Bei Wechsel wird der Timer zerstört und neu gestellt; bei `paused`
  wird gar nichts gefeuert.
- `main.js` (Overview) ersetzt den früheren hardcoded `60_000`-setInterval
  durch `onAutoRefresh(refresh)`. Andere Seiten sind statische Snapshots;
  ein ebenso einfacher Aufruf kann später jederzeit ergänzt werden.

### Toolbar auf allen fünf Seiten

Alle HTML-Seiten haben einen `.toolbar`-Block im `.header-right`-Wrapper:
Auto-Refresh-Select und Theme-Button nebeneinander. Konsistent über
`index.html`, `node.html`, `stats.html`, `regions.html`, `outages.html`.

CSS: `.toolbar-btn` und `.toolbar-select` im Dark-Card-Stil mit
Accent-Hover.

### Mobile-Feintuning — Breakpoints 768 + 480

- Alter Breakpoint `600 px` durch `768 px` (Tablet) und zusätzlich
  `480 px` (Phone) ersetzt.
- `@media (max-width: 768px)`: Header stackt vertikal (brand oben,
  `.header-right` darunter), `.meta` bekommt volle Breite, Kalender auf
  15 Spalten, Rankings-Grid zweispaltig, Touch-Targets min-height 40 px.
- `@media (max-width: 480px)`: Rankings einspaltig, Kalender auf 10
  Spalten, Chart-Höhe reduziert (220 px tall, 160 px compact),
  Filter-Panels einspaltig-stretch mit vollbreite Controls,
  Touch-Targets min-height 44 px (Apple HIG), Daten-Tabellen auf 11 px
  verkleinert mit kleinerem Zellen-Padding.

### Benchmark-Skript `scripts/bench_load.py`

- Argparse: `--rows` (Default 1 M), `--nodes` (Default 10), `--keep`
  (tempDB nicht löschen).
- Bulk-Insert via `executemany` in einer Transaktion; 1 M Rows in
  6 Sekunden (≈ 165 k rows/s auf der Dev-Maschine).
- 14 Timing-Läufe über alle Phase-6-Helper, Ergebnis als Markdown-
  Tabelle gedruckt — direkt paste-fertig.

### Performance-Entdeckung (Bonus)

Der erste Bench-Lauf zeigte `get_per_node_aggregates(24h|7d|30d)` bei
**~700 ms**, während `get_per_node_aggregates_between(yday)` bei
8 ms lag — derselbe GROUP BY, ähnliches Fenster. SQLite's Planner
wählt bei `WHERE timestamp >= ?` (nur untere Schranke) den
`node_url`-Index und scannt 1 M Rows; mit **beiden** Grenzen
range-seeked er den Composite-Index (`node_url, timestamp`).

Fix: `get_per_node_aggregates(lookback)` delegiert jetzt auf
`get_per_node_aggregates_between(lookback, 0)`. Upper-bound bei
`offset_to=0` liegt 60 s in der Zukunft (sonst fällt der aktuelle
Tick durch das halboffene `[start, end)`-Intervall). Tests decken
beide Wege ab.

Resultat:

| Query | vorher | nachher |
|---|---:|---:|
| `get_per_node_aggregates(24h)` | 679 ms | 7 ms |
| `get_per_node_aggregates(7d)` | 711 ms | 52 ms |
| `get_per_node_aggregates(30d)` | 710 ms | 212 ms |

`docs/PERFORMANCE.md` mit der Baseline-Tabelle + Notiz zum Re-Run,
wenn die Produktions-DB 5 M+ Rows erreicht.

### Tests

**78 / 78 grün**. Keine neuen Tests in Etappe 6 — der Query-Fix
wurde vom bestehenden `stats_top_errors_sorts_descending`-Test
indirekt gefangen (der fiel nach dem ersten Delegation-Commit auf
und half, die `offset_to=0`-Edge im `between`-Helper zu korrigieren).

### Dateien

Neu:
- `scripts/bench_load.py`
- `docs/PERFORMANCE.md`
- `progress/2026-04-25-phase6-etappe6.md`

Verändert:
- `frontend/css/main.css` (Themes + Toolbar + Breakpoints)
- `frontend/js/common.js` (Theme, Autorefresh, chartColors)
- `frontend/js/main.js` (onAutoRefresh)
- `frontend/js/node.js` (chartColors)
- `frontend/js/stats.js` (chartColors)
- `frontend/{index,node,stats,regions,outages}.html` (Toolbar)
- `database.py` (get_per_node_aggregates-Delegation + offset_to=0-Fix)

## Smoke-Test lokal

```
Alle 5 HTML-Seiten enthalten die Toolbar-Marker:
  index.html     2
  stats.html     2
  regions.html   2
  outages.html   2
  node.html      2

common.js bindet 10× auf theme/refresh/chartColors-Hooks

Alle 6 Kern-Endpoints weiterhin HTTP 200.
Benchmark erfolgreich (1 M Rows, alle Queries < 300 ms).
```

## Offen

- Deploy auf production-server → Etappe 7 (Finale).
- Visueller Browser-Smoke-Test aller fünf Seiten in beiden Themes →
  Ende Phase 6.

## Nächster Schritt

Etappe 7: Deployment auf den Produktions-Server. Neues
Frontend + Backend-Update einspielen, ohne dass der laufende
Monitor-Service Downtime hat.
