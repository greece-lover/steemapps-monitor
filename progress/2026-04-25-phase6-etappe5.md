# 2026-04-25 — Phase 6 Etappe 5

Ausfall-Log `outages.html` mit vollem Filter-Panel (Node, Zeitraum,
Severity, Dauer-Schwelle) und CSV/JSON-Export. URL-State
round-getripped, Filter teilbar per Link.

## Umgesetzt

### Backend — Range erweitern, Min-Duration-Filter, Export

- `_RANGE_TO_MINUTES` um `90d` erweitert. `/outages`,
  `/nodes/{url}/outages` und `/stats/top` akzeptieren jetzt
  `24h|7d|30d|90d`. `/stats/chain-availability` bleibt bei 24h|7d
  (größere Fenster würden die Bucket-Zahl unpraktisch hoch treiben).
- `/api/v1/outages` bekommt `min_duration_s` (0..86400,
  Default 0). Filter-Reihenfolge: Node → Severity → Min-Duration,
  danach Limit. Response trägt `total` (vor limit) und die
  (gekürzte) `outages`-Liste.
- Neuer Helper `_filtered_global_outages(range, node, severity,
  min_duration_s)` abstrahiert den Filter-Pipe, damit Export und
  Listing-Endpoint das exakt gleiche Result-Set produzieren.

### Backend — Export-Endpoints

- `GET /api/v1/export/outages.csv?range&node&severity&min_duration_s`
  liefert RFC-4180-CSV mit Content-Disposition-Attachment. Filename
  wird aus den aktiven Filtern gebildet:
  `outages-30d-api.steemit.com-real.csv` usw.
- `GET /api/v1/export/outages.json?...` liefert JSON-Pretty-Print
  mit Envelope (range, filter, total, severity_threshold_s,
  outages) — gleicher Filename-Konventionssatz.
- Interne CSV-Schreiberei zero-dependency, RFC-4180-Escapes für `"`,
  `,` und `\n` auf dem `error_sample`-Feld korrekt.

Tests — 4 neue Fälle (78 / 78 grün):

- `min_duration_s=120` filtert 60-s-Run weg, behält 300-s-Run.
- Validierung: `min_duration_s=-1` und `=86401` → 422.
- CSV-Response: `Content-Type: text/csv`, `Content-Disposition:
  attachment`, Header-Row korrekt, Row-Count passt.
- JSON-Response: `Content-Type: application/json`, Envelope mit
  `severity_filter=real`, `total=1`.

### Frontend — neue Seite `outages.html`

Filter-Panel oben:

- **Range**-Dropdown (24h/7d/30d/90d, Default 30d).
- **Node**-Dropdown (dynamisch aus `/api/v1/status` befüllt, Option
  „all"). Nach `url.localeCompare` sortiert.
- **Severity**-Dropdown (real ≥120 s / short <120 s / all).
- **Min duration**-Slider (0..1800 s, 30-s-Schritt). Live-Anzeige
  `Xs`.
- **Reset**-Button setzt alles zurück.
- **Export**-Buttons rechts: CSV ⤓ / JSON ⤓ mit
  `download`-Attribut. Die Hrefs werden bei jeder Filter-Änderung
  neu berechnet, damit der Download genau das enthält, was in der
  Tabelle steht.

Tabelle: Node (Link zur Detail-Seite) · Start · End · Duration
(human-friendly: `5m 30s`) · Severity-Pill (SHORT gelb / REAL rot)
· Error-Sample (gedimmt).

Gerenderte Zeilen zeigen oben `<n> shown · <total> matching`, damit
sichtbar ist, wenn das Limit greift. Aktuell begrenzt der Client
den Ruf auf `limit=5000` (API-Cap), Live-Server mit zwei Jahren
Betrieb landet locker darunter.

### URL-State

```
outages.html?range=30d&node=<url>&severity=real&min_duration_s=120
```

Jede Änderung schreibt via `history.replaceState` zurück. Nicht-
Default-Werte werden serialisiert, der Reset entleert die URL
wieder auf den nackten Pfad.

### Navigation

Alle fünf HTML-Seiten (`index`, `node`, `stats`, `regions`,
`outages`) tragen jetzt den Nav-Block **Overview · Stats · Regions
· Outages**, aktive Seite via `.active`. `decorateNavLinks()` in
`common.js` hängt den `?api=`-Dev-Override weiter durch.

### CSS

- Neues `.ctrl-export` (margin-left:auto, klein-gruppe mit
  CSV/JSON-Download-Buttons rechts im Filter-Panel).
- Bestehende `.sev-pill`-Styles und `.data-table`-Styles aus
  Etappe 2 werden auf dieser Seite wiederverwendet — keine
  Duplikate.

## Smoke-Test (curl)

```
outages.html                                           HTTP 200, 3.4 KB (13 IDs)
outages.js                                             HTTP 200, 6.8 KB

GET /api/v1/outages?range=30d                          HTTP 200  (2 outages)
GET /api/v1/outages?range=30d&min_duration_s=120       HTTP 200  (1 outage — real 300s)
GET /api/v1/export/outages.csv?range=30d               → CSV body korrekt
GET /api/v1/export/outages.json?range=30d&severity=real → JSON envelope korrekt
```

CSV-Auszug (gekürzt):
```
node_url,start,end,duration_s,severity,error_sample,ongoing
https://api.justyy.com,2026-04-24T18:04:31Z,2026-04-24T18:09:31Z,300,real,HTTP 502,false
https://api.steemit.com,2026-04-24T16:44:31Z,2026-04-24T16:45:31Z,60,short,timeout,false
```

Nav-Konsistenz: alle fünf Seiten enthalten dieselben vier Nav-Ziele.

## Offen

- Theme-Umschalter (Dark/Light), Autorefresh-Steuerung,
  Mobile-Feintuning → Etappe 6.
- 1-M-Messwerte-Benchmark-Skript → Etappe 6/7.
- Deploy auf production-server → Etappe 7.
- Visueller Browser-Smoke-Test aller fünf Seiten → Ende Phase 6.

## Nächster Schritt

Freigabe auf Etappe 6 (Theme-Umschalter, Autorefresh, Mobile) oder
Pause.
