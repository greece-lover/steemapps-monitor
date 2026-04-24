# Beitragen

*English version: [CONTRIBUTING.md](CONTRIBUTING.md)*

Danke für dein Interesse. Das Projekt wird bis Phase 7 (erster automatisierter Tages-Report) privat entwickelt. Ab diesem Zeitpunkt gilt dieses Dokument.

## Was wir gerne sehen

- **Bug-Reports** zur Messlogik, falsche Scores, übersehene Ausfälle.
- **Vorschläge neuer Nodes.** Bitte Node-URL, Betreiber und einen groben Hinweis auf den erwarteten Traffic-Anteil angeben.
- **Methodik-Verbesserungen** — klar argumentiert in einem Issue, bevor ein PR kommt.
- **Übersetzungen** von Nutzer-sichtbaren Texten (das Dashboard ist mehrsprachig; die Repo-Doku ist zweisprachig DE/EN).
- **Dashboard-Verbesserungen** — Barrierefreiheit, Internationalisierung, Performance.

## Was außerhalb des Umfangs liegt

- **Steem-Core-Client-Patches** — dieses Repository überwacht Nodes, es forkt nicht `steemd`. Solche Änderungen bitte stromaufwärts einreichen.
- **Schreib-Endpoints zur API hinzufügen.** Die API ist nur-lesend und bleibt es.
- **SQLite ersetzen**, solange die Datenbank in der Produktion nicht tatsächlich Stress zeigt. Vorzeitige Datenbank-Migrationen bringen hier nichts.
- **Alles, was Reporter-Keys betrifft.** Key-Handling ist Aufgabe des Autors.

## Ablauf

1. Issue öffnen, das Problem oder den Vorschlag beschreibt. Für nicht-triviale Änderungen vor dem Coden Bestätigung abwarten.
2. Fork, Branch, implementieren, testen.
3. PR einreichen. Kurze Beschreibung, Issue referenzieren, Mess- oder Score-Formel-Änderungen getrennt von Infrastruktur listen.
4. Review erfolgt innerhalb einer Woche. Wenn eine Änderung veröffentlichte Zahlen berührt, deckt das Review auch methodische Implikationen ab.

## Code-Stil

- Python 3.12, Type-Hints auf öffentlichen Funktionen, black-Formatierung, ruff für Lint.
- Module klein halten. Die Komplexität des Projekts liegt in der Methodik, nicht in der Plumbing-Schicht — der Code soll das widerspiegeln.
- Tests für Änderungen an der Score-Formel sind Pflicht. Eine Änderung, die veröffentlichte Zahlen ändert, ohne Tests, wird abgelehnt.
- Kommentare sollen das Warum erklären, nicht das Was. Im Zweifel gilt die Projekt-Grundanweisung im Root.

## Commit-Messages

- Kopfzeile im Imperativ („Node X zur Initial-Liste hinzufügen", nicht „Node X hinzugefügt").
- Ein Issue referenzieren, falls vorhanden.
- Der Body erklärt die Begründung nicht offensichtlicher Änderungen.

## Daten und Datenschutz

Niemals Code hinzufügen, der Nutzer-Daten erfasst — siehe [SECURITY.de.md](SECURITY.de.md). Diese Regel hat keine Ausnahmen und wird im Review durchgesetzt.

## Kommunikation

- Technische Diskussionen: GitHub-Issues und PRs.
- Konzept-Diskussionen: Steemit oder Discord via @greece-lover.
- Dringende Sicherheitsprobleme: privater Kanal zu @greece-lover.
