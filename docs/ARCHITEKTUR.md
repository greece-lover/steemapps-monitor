# Architektur

*English version: [ARCHITECTURE.md](ARCHITECTURE.md)*

## Komponenten

```
┌──────────────────┐
│ systemd-Timer /  │   läuft alle 60 s, ein Messzyklus pro Tick
│ interne Schleife │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐    JSON-RPC über HTTPS
│ Poller (Python)  │──────────────────────────► Steem-API-Nodes
│ httpx, asyncio   │◄──────────────────────────── Antwort, Latenz, Block-Nummer
└────────┬─────────┘
         │ schreibt eine Zeile pro (Node, Tick)
         ▼
┌──────────────────┐
│ SQLite           │
│ measurements,    │
│ outages, nodes   │
└────────┬─────────┘
         │
         ├──► Aggregator (periodisch) ──► Tageszusammenfassung, Scores
         │
         ├──► JSON-API (FastAPI) ──────► api.steemapps.com-Konsumenten
         │
         └──► Daily-Reporter (Cron) ───► Steemit-Post + custom_json auf der Chain
```

Der Monitor ist ein einziger Python-Prozess; zusätzliche Komponenten (API-Server, Daily-Reporter) sind separate Prozesse, die dieselbe SQLite-Datei teilen. SQLite im WAL-Modus bewältigt dieses Nebenläufigkeits-Muster (ein Schreiber, viele Leser) bei den erwarteten Datenmengen problemlos (einstellige Node-Zahl, eine Messung pro Minute pro Node → < 15 000 Zeilen pro Node pro Woche).

## Prozesse

| Prozess | Unit-Name | Frequenz | Zweck |
|---|---|---|---|
| Monitor | `steemapps-monitor.service` | kontinuierlich | alle Nodes alle 60 s abfragen, Messungen schreiben |
| API-Server | `steemapps-api.service` | kontinuierlich | Nur-Lese-JSON-Endpoints bereitstellen |
| Daily-Reporter | Cron `@daily 02:00` | einmal täglich | aggregieren, auf Steemit posten, custom_json schreiben |

## Datenverzeichnisse

- `/opt/steemapps-monitor/` — Quellcode, virtualenv, Konfiguration
- `/opt/steemapps-monitor/data/` — SQLite-Datenbanken (gitignore; separat gesichert)
- `/opt/steemapps-monitor/logs/` — rotierte Log-Dateien
- `/etc/systemd/system/steemapps-monitor.service` — Service-Definition

## Messzyklus

Jeder Tick:

1. Für jeden konfigurierten Node einen `condenser_api.get_dynamic_global_properties`-JSON-RPC-Call absetzen.
2. Erfassen: HTTP-Status, gesamte Round-Trip-Zeit, zurückgegebene `head_block_number`, ggf. Fehler.
3. Abgeleitete Felder berechnen: Block-Rückstand (Referenz = maximale head-block über alle Nodes in diesem Tick), Score-Komponenten.
4. Eine Zeile in `measurements` einfügen.
5. Wenn ein Node von gesund nach ungesund wechselt oder umgekehrt, einen `outages`-Eintrag öffnen oder schließen.

## Referenz-Block-Auflösung

Der „Block-Rückstand" wird immer gegen die maximale `head_block_number` berechnet, die in diesem Tick über den Node-Pool beobachtet wurde. Wenn alle Nodes gleichermaßen zurückhängen, gibt es keine Referenz — dieser Zustand wird geloggt und als „degraded" behandelt, nicht als Ausfall einzelner Nodes.

## Scoring und Ausfall-Erkennung

Implementiert gemäß [MESSMETHODIK.md](MESSMETHODIK.md). Der Algorithmus ist in einem Modul (`monitor/scoring.py`) zentralisiert und umfassend getestet, damit jede Änderung an der Formel explizit, überprüfbar und versioniert ist.

## Öffentliche API

Der FastAPI-Server stellt Nur-Lese-Endpoints bereit — Schema in [API.md](API.md). Keine Schreib-Endpoints, keine Authentifizierung, kein Rate-Limiting auf App-Ebene (wird später von nginx erzwungen).

## Täglicher Chain-Report

Zwei Artefakte pro Tag:

1. Ein Steemit-Post (HTML-Body), veröffentlicht durch den dedizierten Reporter-Account. Enthält eine menschenlesbare Tabelle, Vergleich zur Vorwoche und Links zu den Rohdaten.
2. Eine `custom_json`-Operation unter `steemapps_api_stats_daily` mit den vollständigen aggregierten Zahlen. Dies ist die maßgebliche Quelle — der Post stellt die Daten lediglich dar.

## Sicherheits-Grenzen

- Der Reporter-Account hat ausschließlich Posting-Rechte.
- Sein Posting-Key liegt in `/opt/steemapps-monitor/.env.local`, nur lesbar für den Service-User, niemals im Git.
- API-Server und Dashboard sind schreibfrei; jede Ausführungs-Oberfläche (Deployment-Skripte, DB-Migrationen) liegt außerhalb der Service-Grenze und erfordert einen manuellen Login.

## Erweiterbarkeit

- Neue Nodes: eine Zeile in der `nodes`-Tabelle, Konfigurations-Reload triggert den Poller.
- Neue Metriken: additiv — alte Zeilen haben für neue Spalten einfach `NULL`.
- Neue Aggregations-Fenster: im Reporter umgesetzt, benötigen keine Schema-Änderungen.
