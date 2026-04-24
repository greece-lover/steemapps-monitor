# Nutzer-Handbuch

*English version: [USER-GUIDE.md](USER-GUIDE.md)*

Dieses Handbuch richtet sich an drei Zielgruppen: Endnutzer, die das Dashboard lesen, Frontend-Betreiber, die die Daten integrieren, und Node-Betreiber, die ihre eigene Bilanz prüfen.

## Dashboard lesen

Die Startseite unter `api.steemapps.com` zeigt eine Tabelle mit einer Zeile pro überwachtem Node und vier Ampel-Spalten:

- **Jetzt** — aktueller 5-Minuten-Status (grün / gelb / rot / grau).
- **24 h** — Uptime-Prozent der letzten 24 Stunden.
- **7 d** — durchschnittliche Tages-Uptime über die letzten sieben Tage.
- **Score** — aktueller Gesundheits-Score (0–100), siehe [MESSMETHODIK.md](MESSMETHODIK.md).

Ein Klick auf eine Zeile führt zur Detailseite des Nodes: Latenz-Kurve, Uptime-Diagramm, Ausfall-Liste mit Zeitstempeln.

Die angezeigten Zahlen sind aus den Rohdaten reproduzierbar. Wer überprüfen möchte, zieht für den betreffenden Tag das `custom_json` mit der ID `steemapps_api_stats_daily` und rechnet nach.

## Tages-Reports auf Steemit lesen

Der Reporter-Account veröffentlicht täglich einen Post mit dem Titel „Steem API-Node-Report — YYYY-MM-DD" (zweisprachig DE/EN). Der Post enthält:

- Zusammenfassung: bester Node, schlechtester Node, größter Ausfall.
- Vollständige Tabelle: Uptime, Latenz, Fehlerzahl pro Node.
- Wochen-Vergleich.
- Regionale Latenz-Karte (sobald Mehr-Regionen live sind).
- Link zur zugehörigen `custom_json`-Operation mit den Rohdaten.

Der Post ist stets sachlich. Keine Häme, keine Schuldzuweisungen. Wer eine Zahl für falsch hält, kontaktiert den Reporter-Account oder @greece-lover mit dem Zeitstempel — wir veröffentlichen eine Korrektur und protokollieren die Änderung hier.

## Daten integrieren (Frontend-Betreiber)

Die in [API.md](API.md) dokumentierte JSON-API nutzen. Empfohlenes Muster:

- `/nodes` einmal pro Minute abfragen, um die Fallback-Liste zu aktualisieren.
- Nodes mit `status = "down"` aus der Rotation ausschließen.
- Nodes mit `score_now >= 80` bevorzugen.
- Antworten lokal cachen; nicht bei jeder Nutzer-Aktion die API hämmern.

Alternativ den Chain-Stream abonnieren und auf `steemapps_api_outage`-Operationen achten — diese werden sofort bei Ausfall-Erkennung geschrieben, üblicherweise unter zwei Minuten Verzögerung.

## Eigenen Node prüfen (Node-Betreiber)

Wer einen der überwachten Nodes betreibt und seine Bilanz prüfen möchte:

1. Im Dashboard nachschlagen — die dort angezeigte Zahl ist dieselbe, die wir überall verwenden.
2. Bei Überraschung gibt der Endpoint `/nodes/{id}/history` die Minutenwerte.
3. Da die Messungen extern zu deinem Dienst sind, kann sich unsere Sicht von deiner internen Überwachung unterscheiden — besonders bei Netzwerk-Problemen stromaufwärts deines Servers. Die Rohdaten erlauben, die Schicht der Abweichung zu diagnostizieren.

## Node zur Überwachung aufnehmen

Anfrage über den Kanal in [CONTRIBUTING.de.md](CONTRIBUTING.de.md) stellen. Voraussetzungen: der Node muss öffentlich erreichbar sein, unter einer stabilen URL laufen und eine unmodifizierte oder kompatibel modifizierte Steem-API-Oberfläche bieten (`condenser_api.get_dynamic_global_properties` ist das Minimum).
