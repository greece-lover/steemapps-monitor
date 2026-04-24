# Roadmap

*English version: [ROADMAP.md](ROADMAP.md)*

Meilenstein-Phasen statt datumgebundener Releases. Die untenstehenden Daten sind Ziele, keine Zusagen.

## Phase 1 — Server-Audit ✅ (2026-04-24)

Reines Lesen der Entwicklungs-VM. Bestätigung, dass laufende Workloads (Steem-Fork-Witness-Node, SQV-Indexer, SQV-Frontend) unberührt bleiben und alle initial vorgesehenen Ziel-API-Nodes erreichbar sind.

## Phase 2 — Gerüst ✅ (2026-04-24)

Repository, Dokumentations-Basis, SSH-Alias, Server-Arbeitsverzeichnis. Kein Monitor-Code. Zweisprachig DE/EN, wo erforderlich.

## Phase 3 — Monitor-Kern 🟡 (2026-04-24, Code fertig)

- Python-Poll-Schleife, JSON-RPC-Client, Minuten-Messung ✅
- SQLite-Schema (Nodes, Messungen) ✅
- Gesundheits-Score nach Methodik `mv1` ✅
- systemd-Service, Logging, Fehlerbehandlung ✅
- Lokale Tests: 18/18 grün; Live-Smoke-Test gegen alle vier Nodes OK ✅
- **Offen:** VM-Deploy + 30-Minuten-Laufzeit-Verifikation (Entwicklungs-VM war am Ende der Code-Session nicht erreichbar; folgt, sobald die VM wieder hochgefahren ist)
- `outages`-Tabelle in Phase 4 verschoben — Phase 3 persistiert Rohmessungen und berechnet Ausfall-Strecken on-the-fly aus `/api/v1/status`; eine materialisierte Tabelle lohnt sich erst, wenn der Aggregator schnellere Tages-übergreifende Abfragen braucht

## Phase 4 — Öffentliche JSON-API (Ziel: 2026-04-27)

- Nur-Lese-JSON-Endpoints für Status, Verlauf und Ausfälle
- Stabiles Schema, dokumentiert in `docs/API.md`
- Reverse-Proxy-Ziel `api.steemapps.com` (nginx auf dem IONOS-Server, spätere Phase)

## Phase 5 — Dashboard (Ziel: 2026-04-28 bis 2026-04-30)

- Statisches HTML + Chart.js + Leaflet, ohne Build-Schritt, ohne Framework
- Detailseiten pro Node: Uptime-Kurve, Latenz-Historie, Ausfall-Liste
- Regionale Heatmap, sobald Mehr-Standort-Messungen live sind

## Phase 6 — Täglicher Chain-Report (Ziel: 2026-05-04)

- Aggregator erzeugt die Tages-Zusammenfassung
- Postet auf Steemit unter einem dedizierten Account (Accountname noch zu entscheiden)
- Schreibt die aggregierten Rohzahlen als `custom_json` mit der ID `steemapps_api_stats_daily`
- Erster Lauf manuell, danach vollautomatisch per Cron um 02:00 Uhr MESZ

## Phase 7 — Repository wird öffentlich, Ankündigung (Ziel: 2026-05-04)

- Umschaltung von privat auf öffentlich am selben Tag wie der erste erfolgreiche automatisierte Report
- Ankündigungs-Post auf Steemit mit Erklärung von Methodik und Datenzugang

## Phase 8 — Mehr-Regionen-Messungen (offen)

- Zusätzliche Monitor-Instanzen in anderen Regionen (USA, Asien), wenn finanziell vertretbar
- Punkt-Typ wird pro Messung gespeichert, damit lokale und regionale Daten unterschieden werden können

## Phase 9 — Welako-Client-Switcher-Integration (offen)

- Welako-Frontend schickt anonymisierte Messwerte an einen Erfassungs-Endpoint
- Daten werden mit dem Server-Monitoring zusammengeführt für ein realistischeres Bild
- Datenschutz: keine IPs, keine Nutzer-IDs, keine individuellen Request-Muster

## Offene Entscheidungen

Werden in `STEEMAPPS_PROJEKT_KONZEPT.md` unter „Offene Entscheidungen" verfolgt. Werden im Laufe der Umsetzung geschlossen.
