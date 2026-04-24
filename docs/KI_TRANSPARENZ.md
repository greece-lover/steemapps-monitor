# KI-Transparenz

*Internes Dokument, analog zu SQV und SARH.*

## Einordnung

Dieses Projekt wird mit Unterstützung eines KI-Assistenten (Claude Code, Anthropic) entwickelt. Der Assistent schreibt Code, Dokumentation und Commit-Messages nach Anweisung von @greece-lover.

## Arbeitsweise

- Menschliche Steuerung: Ideen, Architektur-Entscheidungen, Prioritäten, finale Freigabe von Commits, Pushes und dem Wechsel des Repositories auf öffentlich.
- KI-Ausführung: Code-Erstellung, Boilerplate, Übersetzungen, Tests, Doku-Entwürfe, Server-Administration unter Anweisung.
- Sicherheitskritische Entscheidungen (Key-Handling, Chain-Operationen, Deployment-Konfiguration, Methodik-Änderungen) werden vom Menschen geprüft, bevor sie wirksam werden.

## Was die KI explizit nicht tut

- Keine Chain-Operationen mit echten Keys im Rahmen der Entwicklung. Der Reporter-Account-Key wird ausschließlich durch den Autor in `.env.local` hinterlegt; die KI sieht ihn nicht und benutzt ihn nicht.
- Keine eigenmächtige Veröffentlichung des Repositories (Privat-Switch zu Public bleibt menschliche Entscheidung).
- Keine Installation oder Konfigurations-Änderung auf Produktions-Servern ohne explizite Freigabe. Das galt besonders in Phase 1, als der Status des IONOS-Servers noch nicht geklärt war.
- Keine Änderungen an der Messmethodik ohne dokumentierte Begründung und vorherige Abstimmung.
- Keine Übertragung von Nutzer-Daten an Anthropic oder Dritte — die KI sieht nur den Projekt-Code und vom Autor bereitgestellten Kontext.

## Messmethodik und KI

Die Messmethodik ist bewusst so gestaltet, dass sie ohne KI reproduzierbar ist. Jede von der KI geschriebene Score-Berechnung muss durch einen Test und durch die in [MESSMETHODIK.md](MESSMETHODIK.md) dokumentierten Formeln gedeckt sein. Die Rohdaten werden auf die Chain geschrieben — damit ist unabhängig von der KI nachprüfbar, ob die veröffentlichten Zahlen mit den Rohdaten konsistent sind.

## Progress-Log

Jede Entwicklungsphase wird in `progress/YYYY-MM-DD-phase-*.md` dokumentiert. Zeitstempel, Schritte, Entscheidungen und offene Punkte werden dort festgehalten, damit der Arbeitsverlauf auch nachträglich nachvollziehbar ist.
