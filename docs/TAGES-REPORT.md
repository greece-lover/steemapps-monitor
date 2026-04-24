# Tages-Report

*English version: [DAILY-REPORT.md](DAILY-REPORT.md)*

Einmal pro UTC-Tag veröffentlicht der SteemApps API Monitor einen Steem-Post
und parallel dazu eine `custom_json`-Operation mit den aggregierten Messwerten
des Vortages. Der Post ist zweisprachig (Deutsch/Englisch) und für Leser
gemacht; die `custom_json` ist die maschinenlesbare Rohaggregation, auf die
nachgelagerte Konsumenten (Dashboards, Drittanbieter-Tools) aufbauen können.

## Zeitplan

- **Timer:** `deploy/steemapps-reporter.timer`, feuert täglich um **02:30 UTC**.
- **Berichtetes Fenster:** der UTC-Tag, der 2,5 Stunden vorher endete. Ein
  Lauf um `2026-04-25 02:30:00 UTC` berichtet über `2026-04-24 00:00:00Z –
  2026-04-25 00:00:00Z`.
- **Absender-Account:** `@steem-api-health` (dedizierter Reporter-Account,
  getrennt vom Witness-Account `@greece-lover`).

## Operationen

Jeder Lauf erzeugt zwei Chain-Operationen, in dieser Reihenfolge:

1. **`custom_json`** mit ID `steemapps_api_stats_daily` — die aggregierte
   Payload, signiert mit dem Posting-Key des Reporter-Accounts. Wird zuerst
   gesendet, damit der Post auf die Transaktion verweisen kann.
2. **`comment`** — der zweisprachige Report. Im Body ist ein Verweis auf
   Transaktions-Hash und Block der vorangegangenen `custom_json`.

Retry-Policy: drei Versuche pro Operation mit je 60 Sekunden Abstand.
Permanente Fehler (doppelter Permlink, ungültige Signatur, zu wenig RC)
werden sofort ausgelöst — ein Retry würde denselben Fehler nur dreimal
loggen. Transient auftretende Fehler (Netzwerk-Timeout, RPC nicht
erreichbar) werden wiederholt.

## `custom_json`-Payload-Schema

Die Payload ist ein stabiles öffentliches Schema. Ein Breaking Change
verlangt eine neue Operations-ID, keinen stillen Formatwechsel.

```json
{
  "version": "mv1",
  "day": "2026-04-24",
  "window": {
    "start": "2026-04-24T00:00:00Z",
    "end":   "2026-04-25T00:00:00Z"
  },
  "source_location": "contabo-de-1",
  "summary": {
    "total_measurements": 14400,
    "total_ok": 14281,
    "uptime_pct": 99.17,
    "best_node": "https://api.moecki.online",
    "worst_node": "https://steem.justyy.com",
    "longest_outage_node": "https://steem.justyy.com",
    "longest_outage_ticks": 7
  },
  "nodes": [
    {
      "url": "https://api.steemit.com",
      "region": "us-east",
      "total": 1440,
      "ok": 1421,
      "uptime_pct": 98.68,
      "errors": 19,
      "latency_ms": {"avg": 712, "min": 340, "max": 4210, "p95": 1520},
      "error_classes": {"timeout": 11, "http_5xx": 8}
    }
    // … ein Eintrag pro konfiguriertem Node
  ]
}
```

### Feld-Semantik

- `version` — spiegelt die Methodik-Version aus
  `docs/MESSMETHODIK.md`. Konsumenten sollten diesen Wert prüfen,
  bevor sie abgeleitete Felder vertrauen.
- `window` — halb-offen `[start, end)` in ISO-8601 Z. Zwei aufeinander-
  folgende Reports teilen keine Ticks.
- `source_location` — Bezeichner der Monitor-Instanz, die die Rohdaten
  erzeugt hat. Heute gibt es eine (`contabo-de-1` auf der Dev-VM); eine
  Multi-Location-Erweiterung steht auf der Phase-6+-Roadmap.
- `summary.best_node` / `worst_node` — sortiert nach Uptime, bei
  Gleichstand niedrigere Durchschnittslatenz besser.
- `summary.longest_outage_ticks` — Anzahl aufeinanderfolgender
  fehlgeschlagener 60-Sekunden-Ticks auf dem schlechtesten Node; jeder
  Tick entspricht einer Minute.
- `nodes[].errors` — Gesamtzahl der fehlgeschlagenen Ticks im Fenster.
- `nodes[].error_classes` — grobe Klassifikation (`timeout`,
  `connect_error`, `http_4xx`, `http_5xx`, `rpc_error`, `body_invalid`,
  `body_stale`, `other`); die einzelnen Freitext-`error_message`-Zeilen
  des Monitors werden nicht auf die Chain gebracht, um die Payload
  kompakt zu halten.

## Rohdaten abfragen

Jede Tages-`custom_json` ist dauerhaft auf der Steem-Chain. Um die
letzten N Tage Aggregate ohne Scraping der Posts zu holen, mit einem
beliebigen Block-Explorer oder einem `condenser_api.get_account_history`-
Aufruf nach `required_posting_auths=@steem-api-health` mit ID
`steemapps_api_stats_daily` filtern. Der Post-Body jedes Tages verlinkt
auf die exakte Transaktion und den Block der zugehörigen `custom_json`
— das ist der schnellste Weg für einen menschlichen Prüfer.

## Post-Format

Der Comment-Body enthält:

1. **Englischer Abschnitt** — Executive Summary, Node-Tabelle (Uptime,
   Ø Latenz, p95-Latenz, Fehler, Fehlerklassen), Wochenvergleich,
   Methodik-Link.
2. **Deutscher Abschnitt** — identische Struktur, deutsche Texte.
3. **Über diesen Report** — wortwörtliche Footer-Absätze in Englisch und
   Deutsch (Attribution an `@greece-lover` als Betreiber, Dashboard-
   Link, GitHub-Link, Witness-Hinweis).

Der Footer-Text ist durch einen Test gepinnt
(`tests/test_template.py`); Änderungen benötigen eine explizite Edit.

## Betriebsmodi

Zwei env-gesteuerte Modi:

- **`STEEMAPPS_REPORTER_MODE=prod`** — signiert und sendet beide
  Operationen. Benötigt `STEEMAPPS_REPORTER_POSTING_KEY` mit einem
  validen Posting-Key für den Account.
- **`STEEMAPPS_REPORTER_MODE=dev`** — rendert den Post und die
  `custom_json`-Payload auf stdout und beendet sich. Keine Chain-
  Interaktion, kein Key nötig. Für lokale Entwicklung, Smoke-Tests und
  den ersten Phase-5-Lauf vor dem Produktions-Schwenk.

`--dry-run` auf der CLI erzwingt Dev-Modus unabhängig vom ENV.

## Fehlerbehandlung

- **Kein Datenpunkt im Fenster** — Exit-Code 2, kein Broadcast. Schutz
  gegen Leerer-Report-Publikation, wenn der Monitor offline war.
- **`custom_json`-Broadcast schlägt fehl** — Exit-Code 3, der Comment
  wird nicht versucht. Der Tag wird übersprungen; `Persistent=true` des
  Timers wiederholt denselben Tag nicht automatisch (VM an ist nicht
  genug — der RPC-Endpoint muss ebenfalls erreichbar sein), ein
  manuelles `systemctl start steemapps-reporter.service` kann den Tag
  nachholen, sobald die Ursache behoben ist.
- **Comment-Broadcast schlägt fehl, nachdem `custom_json` geklappt hat**
  — Exit-Code 4. Die Rohaggregation ist bereits auf der Chain, also
  sind die nachgelagerten Konsumenten nicht betroffen; nur der
  lesbare Post fehlt für diesen Tag. Der Permlink ist stabil
  (`steemapps-api-daily-report-YYYY-MM-DD`), ein erneuter Versuch
  kollidiert mit dem fehlgeschlagenen Comment nur, wenn der erste
  Versuch tatsächlich im Block landete; dieser Fall meldet
  „duplicate permlink" und wird als permanenter Fehler klar geloggt.

## Manuell ausführen

```bash
# Lokaler Dry-Run gegen die Projekt-SQLite (vorher seeden):
python -m reporter.daily_report --seed-synthetic
python -m reporter.daily_report --dry-run

# Auf der VM, Dry-Run gegen die Live-DB:
sudo -u steemapps-reporter STEEMAPPS_REPORTER_MODE=dev \
    /opt/steemapps-monitor/.venv/bin/python -m reporter.daily_report --dry-run

# Auf der VM, expliziter Tag (nach einem Fehlschlag nachholen):
sudo -u steemapps-reporter \
    /opt/steemapps-monitor/.venv/bin/python -m reporter.daily_report \
    --date 2026-04-24
```
