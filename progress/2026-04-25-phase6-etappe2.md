# 2026-04-25 — Phase 6 Etappe 2

Detail-Ansicht pro Node (`node.html`). Voller Umfang gebaut, wie
abgestimmt: Latenz-Chart mit Compare-Overlay bis 4 Nodes,
Perzentil-Tabelle, 30-Tage-Uptime-Kalender, Ausfall-Liste,
Block-Lag-Chart, Share-Link und Back-Link.

## Umgesetzt

### Backend — ein zusätzlicher Endpoint

`GET /api/v1/nodes/{url}/uptime-daily?days=1..90`

- Gruppiert Messungen per `date(timestamp)` und gibt pro Tag
  `{date, total, ok, uptime_pct}` zurück.
- Fehlende Tage werden durch den API-Layer mit
  `{uptime_pct: null}` aufgefüllt — der Kalender ist so immer
  kontinuierlich von `today - days + 1` bis `today`.
- TTL-Cache 5 Minuten.

Tests (2 neue, insgesamt 13 Phase-6-Tests, 67/67 Gesamt):

- Fehlende Tage werden als Null-Einträge aufgefüllt, Endpunkt-Datum ist
  heute, bestückte Tage geben korrekten Prozentwert.
- `days=0` / `days=91` liefern 422.

### Frontend — Architektur

Shared helpers ausgelagert in `frontend/js/common.js`:

- `SteemAPI.el` · `SteemAPI.getJson` · `SteemAPI.showError` ·
  `SteemAPI.clearError` · `SteemAPI.API_BASE`
- Zusätzlich `fmtLatency` / `fmtPct` / `fmtDuration` und
  `preserveApiOverride()` für Seiten-Links.

`main.js` (Übersicht) refactored auf dieses gemeinsame Module; die
Node-Karte ist jetzt ein `<a class="node-card">` auf
`node.html?url=…`, der `?api=`-Dev-Override wird bei jedem Link
weitergereicht.

### Frontend — neue Seite `node.html`

- **Header**: Back-Link zurück zur Übersicht (mit erhaltenem
  `?api=`-Override), Node-URL, Region, Status-Pill, Score,
  Range-Toggle `24h | 7d | 30d`, Copy-Link-Button. Copy-Link nutzt
  `navigator.clipboard` mit visuellem „✓ Copied"-Feedback.
- **Latency-Section**: großer Chart.js-Line-Chart (320 px hoch) mit
  Zeit-Achse (Stunden für 24 h, Tage für 7/30 d). Compare-Picker als
  Dropdown öffnet eine Checkbox-Liste aller anderen Nodes, max. 3
  auswählbar. Überlagerung im gleichen Chart mit 4 Farben
  (`#b7e34a` lime, `#5b9bff` blue, `#c48bff` purple, `#f5a462` orange).
  Custom-Legend unter dem Chart mit Farbchips.
- **Percentile-Table**: eine Zeile pro Node (bis 4), Spalten
  `Min / Avg / P50 / P95 / P99 / Max / Samples / Uptime`, mit
  Farbchip pro Node-Zeile.
- **Uptime-Calendar**: 30-Tage-Streifen als Grid (`aspect-ratio:1`),
  Farbe grün `≥99 %`, gelb `95–99 %`, rot `<95 %`, grau `keine Daten`.
  Tooltips zeigen Datum + Prozentwert + ok/total. Legende darunter.
  Auf Mobile umbricht das Grid auf 10 Spalten.
- **Outages-Section**: Tabelle mit Start / Ende / Dauer / Severity
  (`SHORT`/`REAL`-Pill, Ampelfarben) / Error-Sample. Lädt
  `/nodes/{url}/outages?range=30d&limit=200`.
- **Block-Lag-Chart**: eigener kleiner Chart (200 px), gelb, zeigt
  nur den Hauptnode (Compare wäre im Block-Lag-Kontext visuell
  nicht gut lesbar).

### URL-State / Deep-Links

`node.html?url=<node>&range=24h|7d|30d&compare=<node>,<node>,<node>&api=<dev>`

- `url`: Pflicht. Unbekannte Nodes zeigen klaren Hinweis.
- `range`: optional, Default 24 h.
- `compare`: optional, Komma-getrennt, max. 3 Nodes — mehr werden
  beim Parse abgeschnitten.
- `api`: Dev-Override, wird bei allen Nav-Links erhalten.

Alle Änderungen der Controls (Range-Toggle, Compare-Checkboxen) rufen
`history.replaceState` auf; die URL ist jederzeit kopierbar und
reproduziert exakt den gesehenen Zustand.

### Chart.js Time-Adapter

`chartjs-adapter-date-fns` via CDN nachgeladen — Chart.js braucht einen
Date-Adapter für `type: 'time'`-Achsen. Statt luxon (größer) ist
date-fns die schlankere Variante. Load via `<script defer>`, also kein
Render-Blocking.

### CSS-Ergänzungen (`main.css`)

- Detail-Page-Styles (`.back-link`, `.range-toggle`, `.share-btn`,
  `.detail-section`, `.chart-wrap.tall`).
- Compare-Picker als schwebendes Menü (`position:absolute`, Box-Shadow).
- `.data-table` generisch für Perzentil-Tabelle und Ausfall-Tabelle.
- `.uptime-calendar` Grid + `.cal-cell.{green,yellow,red,grey}`.
- `.sev-pill.{short,real}` mit gedeckten Ampelfarben.
- Mobile-Umbrüche: Kalender auf 10 Spalten, Compare-Picker linksbündig
  statt rechts.

## Smoke-Test lokal

```
node.html             → HTTP 200, 9 erwartete Anchor-IDs gefunden
common.js             → HTTP 200, 2.7 KB
node.js               → HTTP 200, 14.2 KB

GET /api/v1/status                                               200
GET /api/v1/nodes/api.steemit.com/detail?range=24h               200  (240 Pkt, uptime 99.58%)
GET /api/v1/nodes/api.steemit.com/detail?range=7d                200
GET /api/v1/nodes/api.steemit.com/uptime-daily?days=30           200  (30 Tage, 1 mit Daten)
GET /api/v1/nodes/api.steemit.com/outages?range=30d&limit=200    200  (1 × short, 60 s)
```

**Visuelle Verifikation:** Chrome-Extension war in dieser Session nicht
verbunden — keine Screenshot-Generation aus Claude heraus möglich.
Datenpfade sind strukturell verifiziert (alle Endpoints liefern
erwarteten JSON, HTML enthält alle Anchor-Elemente, die `node.js`
referenziert). Live-Test bitte kurz im Browser:

```
cd C:\tmp\steemapps
.venv\Scripts\python -m uvicorn api:app --host 127.0.0.1 --port 8112
# in einem zweiten Terminal:
cd C:\tmp\steemapps\frontend
python -m http.server 8113 --bind 127.0.0.1
# Browser: http://127.0.0.1:8113/index.html?api=http://127.0.0.1:8112
```

Kreuzworträtsel-Test:
1. Klick auf eine Node-Karte → landet auf `node.html?url=…`.
2. Range-Toggle `24h/7d/30d` → URL aktualisiert, Chart rebuilds.
3. Compare-Picker: bis 3 weitere Nodes wählen → Linien erscheinen.
4. Copy-Link → URL mit allen Filtern in der Zwischenablage.
5. Kalender: Hover zeigt `YYYY-MM-DD · XX.X% (ok/total)`.

## Offen

- Stats-Seite `stats.html` → Etappe 3.
- Regional-Karte `regions.html` → Etappe 4.
- Ausfall-Log mit Export `outages.html` → Etappe 5.
- Theme-Umschalter, Autorefresh-Steuerung → Etappe 6.
- Deploy auf production-server → Etappe 7.

## Nächster Schritt

Auf Freigabe warten; bei „weiter" starte ich Etappe 3 (Statistik-Übersicht).
