# 2026-04-25 — Phase 6 Etappe 3

Statistik-Übersicht `stats.html` mit allen Sektionen: Rankings (Top-3
fastest/slowest, Best/Worst Uptime), Chain-Availability Stacked Area,
globaler Latenz-Multi-Line-Chart, größte Ausfälle der Woche, Day-over-
Day-Vergleich mit Trend-Pfeilen. Header-Navigation über alle drei
Seiten hinweg. Ein subtiler Time-Comparison-Bug in SQL wurde nebenbei
gefixt.

## Umgesetzt

### Backend — 3 neue Endpoints

- `GET /api/v1/stats/chain-availability?range=24h|7d` — gebucketete
  up/down-Counts über Zeit. 24 h nutzt 10-Minuten-Buckets (144 Punkte),
  7 d nutzt 60-Minuten-Buckets (168 Punkte). Jeder Bucket gibt absolute
  Zählwerte statt Prozente zurück, die Aggregation zum
  „wie-viele-Nodes-antworten"-Anzeige macht der Client.
- `GET /api/v1/stats/daily-comparison` — pro Node drei 24-Stunden-
  Fenster (today / yesterday / same slice last week) mit
  `avg_latency_ms` und `uptime_pct`. Basis für die Trend-Pfeil-Tabelle.
- `GET /api/v1/stats/top` erweitert um `metric=latency_worst` und
  `uptime_worst` (reverse-sort) — so reicht ein Endpoint für alle vier
  Ranking-Karten.

Alle mit TTL-Cache 60 s.

### Backend — Helper-Erweiterungen in `database.py`

- `get_chain_availability(lookback_minutes, bucket_seconds, db_path)` —
  SQLite `strftime('%s', timestamp)` + Integer-Division erzeugt die
  Bucket-Grenzen. Nutzt `idx_measurements_timestamp` für den
  Range-Filter.
- `get_per_node_aggregates_between(offset_from_minutes,
  offset_to_minutes, db_path)` — Rückwärts-relatives Zeitfenster, Basis
  für yesterday/lastweek im Daily-Comparison-Endpoint.

### Fix: Time-Comparison-Bug in allen Zeit-Range-Queries

Beim Bauen des `daily-comparison`-Tests trat ein Symptom auf, das den
grundsätzlichen Filter-Fehler in *allen* Queries mit Zeit-Range
offengelegt hat:

**Reproduktion:** `datetime('2026-04-24T19:28:30Z', '-1440 minutes')`
gibt SQLite-seitig `'2026-04-23 19:28:30'` zurück — **Space** statt
`T`, **kein `Z`**. Der Monitor speichert Timestamps aber als
`2026-04-24T19:28:30Z`. Die lexikographische Vergleichsordnung unter
gleichem Datum:

```
'2026-04-23T07:28:30Z'  >  '2026-04-23 19:28:30'
           ^                       ^
          'T' (ASCII 84)      ' ' (ASCII 32)
```

Folge: Zeilen mehrere Stunden *vor* dem Cutoff rutschen durch das
`WHERE timestamp >= datetime(?, ?)`. Betroffen war jede Query mit
diesem Pattern — `get_uptime_stats`, `get_measurements_range`,
`get_all_measurements_range`, `get_per_node_aggregates`, neuer
`get_chain_availability`, neuer `get_per_node_aggregates_between`,
`get_uptime_daily`. Die bestehenden Tests haben den Bug nicht
getriggert, weil sie keine Messungen im selben Tag wie der Cutoff
*unterhalb* des Cutoffs platziert hatten.

**Fix:** neuer Helper `_utc_iso_minus_minutes(minutes)` baut den
Cutoff in Python im exakt gleichen `YYYY-MM-DDTHH:MM:SSZ`-Format, das
der Monitor schreibt. Alle Queries wurden auf `WHERE timestamp >= ?`
(String-Vergleich direkt) umgestellt — kein SQLite-`datetime()`-Call
mehr für Cutoffs.

5 neue pytest-Tests für Etappe 3 (insgesamt 72 / 72 grün):

- `latency_worst` / `uptime_worst`: absteigende Sortierung.
- `chain-availability` bucketed korrekt, `up + down == total`.
- `chain-availability` 30d-Range: 422.
- `daily-comparison` partitioniert die drei Zeitfenster sauber
  — **dieser Test hätte den Time-Bug nie entdeckt, wenn wir ihn
  nicht geschrieben hätten.**

### Frontend

Neue Seite `stats.html` mit 5 Sektionen:

- **Rankings** — vier Karten nebeneinander mit je Top-3-Liste. Ein
  gemeinsamer Range-Toggle 24h/7d/30d über allen vier Karten. Karten
  hübsch im Dark-Card-Style mit Dashed-Separator zwischen Zeilen,
  Accent-Farbe für Werte.
- **Chain availability** — Stacked-Area-Chart mit zwei Datasets
  (`up` grün, `down` rot), stacked auf gemeinsamer Zeitachse. Range-
  Toggle 24h/7d.
- **Global latency** — Multi-Line-Chart mit allen zehn Nodes. 10-Farben-
  Palette baut auf dem Compare-Palette der Detail-Seite auf, ergänzt um
  sechs weitere Hues. Eigene Legende mit Farbchips unter dem Chart.
  Range-Toggle 24h/7d.
- **Biggest outages this week** — `/outages?range=7d&severity=real`-
  Ergebnis nach `duration_s` sortiert, Top-10. Node-Name ist Link auf
  die Detail-Seite.
- **Day-over-day comparison** — Tabelle pro Node: Latenz (heute /
  yesterday / lastweek) + Uptime (heute / yesterday / lastweek). Jede
  Vergleichszelle zeigt den aktuellen Wert und einen Trend-Pfeil. Bei
  Änderung ≥ 3 %: Pfeil ↑ oder ↓. Farbsemantik trennt sauber zwischen
  *Änderungs*-Richtung und *Bewertung*: Pfeil-Richtung = Wert gestiegen
  / gesunken, Farbe = besser (grün) / schlechter (rot) / flat (grau).
  Tooltip zeigt absoluten Delta-Wert.

### Architektur / Navigation

- `frontend/js/common.js` um `decorateNavLinks()` erweitert — hängt
  automatisch den `?api=`-Dev-Override an jeden `.nav-links a` beim
  DOMContentLoaded. Damit bleibt die Nav-Navigation in Dev-Sessions
  automatisch auf dem lokalen API-Server.
- `index.html` und `node.html` bekommen einen neuen `.header-right`-
  Wrapper, der nav-links (Overview / Stats) obenrechts und die
  bestehende meta- / range-Zeile darunter layoutet. Die aktive Seite
  wird per `.active`-Klasse hervorgehoben.
- `stats.html` verlinkt zurück auf `index.html` via `.back-link` und
  stellt auch die `.nav-links` bereit.

### CSS-Ergänzungen

- `.header-right`, `.nav-links`, `.nav-links a.active` (Accent-Farbe
  mit bottom-Border).
- `.rankings-grid` (auto-fit mit 240 px min), `.ranking-card`,
  `.ranking-list` mit gestapelten Zeilen und Mono-Font.
- `.compare-table .group-head` für verschachtelte Column-Header im
  Daily-Comparison-Table.
- `.trend-val` + `.trend-arrow.better/worse/flat` mit gedeckten
  Ampelfarben.
- Mobile: `.rankings-grid` wird einspaltig, `.nav-links` gap kleiner.

## Smoke-Test lokal (curl)

```
stats.html                                                         HTTP 200, 5.6 KB
stats.js                                                           HTTP 200, 12.8 KB

GET /api/v1/stats/top?metric=latency&range=24h&limit=3             HTTP 200
GET /api/v1/stats/top?metric=latency_worst&range=24h&limit=3       HTTP 200
GET /api/v1/stats/top?metric=uptime&range=24h&limit=3              HTTP 200
GET /api/v1/stats/top?metric=uptime_worst&range=24h&limit=3        HTTP 200
GET /api/v1/stats/chain-availability?range=24h                     HTTP 200  (25 Buckets)
GET /api/v1/stats/chain-availability?range=7d                      HTTP 200
GET /api/v1/stats/daily-comparison                                 HTTP 200
GET /api/v1/outages?range=7d&severity=real&limit=200               HTTP 200
```

Ranking-Top-3 (Mock-Daten):
- fastest: campingclub 190 ms · api2.steemyy 228 ms · senior.workers 235 ms
- slowest: moecki 647 ms · steem.justyy 628 ms · steem.fans 387 ms

## Offen

- Regional-Karte `regions.html` → Etappe 4.
- Ausfall-Log mit Export `outages.html` → Etappe 5.
- Theme-Umschalter, Autorefresh-Steuerung, Mobile-Feintuning → Etappe 6.
- Deploy auf production-server → Etappe 7.
- Visueller Browser-Smoke-Test aller drei Seiten (inkl. neuer
  stats.html) steht zusammenhängend am Ende der Phase aus.

## Nächster Schritt

Freigabe auf Etappe 4 (Regional-Karte mit Leaflet) oder Pause.
