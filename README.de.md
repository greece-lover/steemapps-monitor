# steemapps.com — Steem-API-Monitor

> Kontinuierliches, unabhängiges, quelloffenes Monitoring aller bekannten Steem-API-Nodes. Öffentliche Accountability für die Zuverlässigkeit der Infrastruktur.

*English version: [README.md](README.md)*

## Warum das Projekt existiert

Frontend-Betreiber im Steem-Ökosystem hängen von öffentlichen API-Nodes ab. Wenn `api.steemit.com` — der faktisch zentrale Node — langsam oder nicht erreichbar wird, verlieren Nutzer den Zugang. Aktuell gibt es keine unabhängige, langlaufende, methodisch transparente Aufzeichnung darüber, wie zuverlässig jeder einzelne öffentliche Node tatsächlich ist.

Dieses Projekt schließt diese Lücke mit einem Python-Dienst, der jeden bekannten Steem-API-Node alle 60 Sekunden misst, die Ergebnisse in SQLite speichert, sie über ein öffentliches Dashboard unter `api.steemapps.com` sichtbar macht und einmal täglich eine strukturierte Zusammenfassung als Steemit-Post und `custom_json`-Operation auf der Chain veröffentlicht.

## Was es tut

1. **Überwachen** — fragt jeden konfigurierten Node alle 60 Sekunden ab, erfasst Latenz, HTTP-Status, Block-Rückstand und Fehler-Muster.
2. **Bewerten** — berechnet einen transparenten Gesundheits-Score pro Node (siehe [docs/MESSMETHODIK.md](docs/MESSMETHODIK.md)).
3. **Bereitstellen** — stellt JSON-Endpoints für externe Nutzer und ein Live-Dashboard bereit (spätere Phase).
4. **Berichten** — erstellt einmal täglich eine strukturierte Zusammenfassung, postet sie unter einem dedizierten Account auf Steemit und schreibt die Rohzahlen als `custom_json`-Operation unter der ID `steemapps_api_stats_daily` auf die Chain.

## Für wen es gedacht ist

- **Witnesses** — objektive Vergleichsbasis für die Bewertung von API-Node-Betreibern.
- **Frontend-Betreiber** — Datenquelle für automatisches Node-Switching (Welako, Condenser-Forks).
- **Node-Betreiber** — ehrliches Feedback zur eigenen Service-Qualität.
- **Normale Nutzer** — profitieren passiv durch stabilere Frontends.

## Status

Live im Produktivbetrieb. Der Monitor läuft kontinuierlich von einem europäischen Standort, mit öffentlichem Dashboard auf https://api.steemapps.com und täglicher Zusammenfassung auf Steemit durch @steem-api-health. Siehe [ROADMAP.de.md](ROADMAP.de.md) für die nächsten Schritte.

Mitmach-Möglichkeit für verteilte Messungen: siehe [docs/TEILNEHMEN.md](docs/TEILNEHMEN.md).

## Schnellstart

```bash
git clone git@github.com:greece-lover/steemapps-monitor.git
cd steemapps-monitor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python monitor.py                  # pollt alle 60 s, API auf 127.0.0.1:8110
```

Tests:

```bash
pip install -r requirements-dev.txt
pytest tests/
```

Für die VM-Installation (systemd-Unit, Datenpfad) siehe [deploy/README.md](deploy/README.md).

## Architektur im Überblick

```
 Monitor (Python, systemd) ──60s──► Steem-API-Nodes
          │
          └─► SQLite  ──► JSON-API  ──► Dashboard (api.steemapps.com)
                      │
                      └─► Tages-Report ──► Steemit-Post + custom_json
```

Details in [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md).

## Methodische Transparenz

Jede veröffentlichte Zahl ist nachvollziehbar. Score-Algorithmus, Uptime-Berechnung, Ausfall-Definition und Aggregations-Fenster sind in [docs/MESSMETHODIK.md](docs/MESSMETHODIK.md) dokumentiert. Die Roh-Minuten-Messungen werden auf die Chain geschrieben, damit jeder sie überprüfen oder neu aggregieren kann.

## Öffentliche API

Sobald das Dashboard live ist, wird eine JSON-API veröffentlicht. Das Schema wird in [docs/API.md](docs/API.md) gepflegt, damit externe Nutzer auf unseren Daten aufbauen können, ohne HTML zu scrapen.

## Sicherheit und Datenschutz

- Nur der Monitor-Server misst Steem-Nodes — keine Nutzerdaten, IPs oder Request-Muster werden erfasst oder veröffentlicht.
- Der Daily-Report-Steem-Account hat ausschließlich Posting-Rechte, kein Vermögen.
- Active- und Owner-Keys befinden sich niemals in diesem Repository. Siehe [docs/SECURITY.de.md](docs/SECURITY.de.md).

## Beiträge

Pull Requests sind willkommen, sobald das Repository öffentlich ist. Bis dahin bitte Issues und Konzept-Feedback direkt an @greece-lover. Siehe [docs/CONTRIBUTING.de.md](docs/CONTRIBUTING.de.md).

## Kontakt

- Maintainer: **@greece-lover**
- Verwandte Projekte: [Welako](https://welako.app), SARH (Steem Recovery Hub), SQV (Steemit Quantum Vault)
- Issues: werden aktiviert, sobald das Repo öffentlich ist.

## Lizenz

[MIT](LICENSE) — forken, selbst hosten, eigene Zahlen veröffentlichen. Einzige Bitte: Forks sollten sich klar als eigenständig kennzeichnen, damit Nutzer sie unterscheiden können.
