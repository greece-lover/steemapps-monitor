# Messmethodik

*English version: [MEASUREMENT-METHODOLOGY.md](MEASUREMENT-METHODOLOGY.md)*

Jede veröffentlichte Zahl in diesem Projekt ist aus den Rohdaten reproduzierbar. Dieses Dokument beschreibt exakt, wie jede Zahl gemessen, normalisiert und aggregiert wird.

## Was pro Tick gemessen wird

Alle 60 Sekunden führt der Monitor für jeden konfigurierten Steem-API-Node einen JSON-RPC-Call durch:

- **Methode:** `condenser_api.get_dynamic_global_properties`
- **Transport:** HTTPS POST, `Content-Type: application/json`
- **Timeout:** 8 Sekunden (connect + read)

Dieser Call ist gewählt, weil er günstig ist, denselben Codepfad nutzt wie reguläre Frontends, und die aktuelle head-block-Nummer zurückgibt — die einzige Information, die nötig ist, um einen zurückhängenden Node zu erkennen.

## Rohfelder pro Messung

| Feld | Typ | Anmerkung |
|---|---|---|
| `tick_ts` | UTC-Zeitstempel | auf 60-Sekunden-Grenze gerundet |
| `node_id` | Zeichenkette | stabile Kennung aus der `nodes`-Tabelle |
| `http_status` | ganzzahlig oder NULL | NULL bei Netzwerkfehler (Timeout, DNS, TLS) |
| `latency_ms` | ganzzahlig oder NULL | vollständige clientseitig beobachtete Round-Trip-Zeit in Millisekunden; NULL bei Netzwerkfehler |
| `head_block` | ganzzahlig oder NULL | Wert aus der Antwort, oder NULL wenn die Antwort nicht geparst werden konnte |
| `error_class` | Zeichenkette | `ok`, `timeout`, `dns`, `tls`, `http_5xx`, `http_4xx`, `body_invalid`, `body_stale` |

## Abgeleitete Felder pro Tick

- **`block_lag`** — `max(head_block über alle erreichbaren Nodes in diesem Tick) − head_block dieses Node`. Kann 0 oder positiv sein. Undefiniert (NULL), wenn kein Node im Tick einen gültigen head-block geliefert hat.
- **`ok_flag`** — wahr genau dann, wenn `error_class == "ok"` und `block_lag ≤ 10`.

## Gesundheits-Score

Score wird pro Tick pro Node berechnet; höher ist besser, maximal 100, minimal 0.

| Regel | Abzug (kumulativ) |
|---|---|
| Startwert | +100 |
| `latency_ms > 500` | −20 |
| `latency_ms > 2000` | −50 (zusätzlich zu den −20) |
| `block_lag > 3` | −30 |
| `block_lag > 10` | −70 (zusätzlich zu den −30) |
| `error_class != "ok"` in den letzten 20 Ticks dieses Nodes, Rate > 20 % | −40 |
| Keine Antwort in diesem Tick (Timeout oder Verbindungsfehler) | −100 (untere Grenze 0) |

Regeln werden in Reihenfolge angewendet und sind additiv; Scores können nicht unter 0 sinken. Die Abzüge sind bewusste Design-Entscheidungen, die beobachtbaren Nutzer-Schmerz widerspiegeln sollen — ein einzelner langsamer Tick senkt den Score sanft, ein klar defekter Node kollabiert sofort.

## Uptime

Pro Tag: `uptime_pct_day = 100 * anzahl(ok_flag=wahr) / anzahl(*)` für diesen Node an diesem UTC-Tag. Ticks, in denen der Node nicht antwortete, zählen als nicht-ok.

Pro Woche: einfacher Mittelwert der sieben Tages-Uptime-Prozente. Pro Monat: Mittelwert der Tageswerte (28 bis 31 je nach Monat). Keine Gewichtung nach Traffic — wir messen den Node, nicht unsere Nutzung davon.

## Ausfall-Definition

Ein **Ausfall** ist eine zusammenhängende Folge von Ticks, in denen `ok_flag = falsch`. Ein Ausfall hat:

- `started_at` — Zeitstempel des ersten fehlschlagenden Ticks
- `ended_at` — Zeitstempel des ersten darauffolgenden ok-Ticks (exklusiv), oder `NULL`, wenn noch laufend
- `duration_s` — Differenz; wird beim Schließen gespeichert
- `classification`:
  - `< 120 s` → **kurze Störung**
  - `≥ 120 s` → **echter Ausfall**

Kurze Störungen werden in Tages-Reports separat gezählt und ziehen den in der öffentlichen Zusammenfassung verwendeten „Ausfälle heute"-Zähler nicht nach unten, werden aber weiterhin in der Datenbank erfasst und auf der Detailseite sichtbar gemacht.

## Aggregations-Fenster

| Fenster | Verwendung |
|---|---|
| 1 Tick | Live-Status-Endpoint, aktueller Gesundheits-Score |
| 5 Min | Dashboard-„Jetzt"-Ampel (farbige Ampel) |
| 1 Stunde | Latenz-Diagramm-Auflösung |
| 1 Tag | Tages-Report, Uptime-Diagramm |
| 7 Tage | Wochen-Vergleich |
| 30 Tage | Monats-Trend, derzeit nur informativ |

## Explizite Nicht-Ziele

- Wir messen nicht die gesamte Condenser-API-Oberfläche; der Aufruf der Dynamic Global Properties ist ein Proxy für Liveness, kein vollständiger Health-Check.
- Wir messen JUSSI-Cache-Verhalten nicht separat vom darunterliegenden Node; sie werden als eine Einheit gemessen, weil Frontends genau das sehen.
- Wir testen keine Schreib-Operationen — dies ist ein Lese-Pfad-Monitor.
- Wir versuchen nicht, Nutzer zu geolokalisieren oder die Last auf Betreiberseite zu erschließen; wir messen nur, was der öffentliche Endpoint an unseren Monitor zurückgibt.

## Versionierung dieser Methodik

Wenn sich der Algorithmus ändert (neuer Abzug, neue Metrik), wird die Änderung:

1. In einem datierten Abschnitt am Ende dieser Datei beschrieben.
2. Mit einer Methodik-Versionsnummer versehen: `mv1`, `mv2`, usw.
3. Pro Messung gespeichert, damit historische Scores neu berechnet oder unverändert belassen werden können.

Aktuelle Version: **`mv1`** (initial, in Kraft seit Phase-3-Start).

## Zugriff auf Rohdaten

Jede Tick-Rohzeile wird in SQLite geschrieben und in aggregierter Form als `custom_json` mit der ID `steemapps_api_stats_daily` auf die Chain. Jeder kann aus den Rohdaten selbst aggregieren und zu denselben Zahlen kommen — genau das ist der Punkt.
