# steemapps.com — Portfolio-Plattform und API-Monitor-Infrastruktur

**Projekt-Dokument · Stand: 24. April 2026**

---

## Projekt-Identität

**Name:** steemapps.com (Portfolio-Dach) plus zugehörige Subdomains
**Typ:** Öffentliche Plattform für Steem-Ökosystem-Projekte des Autors, kombiniert mit einer eigenständigen API-Monitor-Infrastruktur
**Positionierung:** Dach für alle Community-Beiträge des Autors zur Steem-Blockchain; gleichzeitig öffentliche Accountability-Infrastruktur für API-Node-Zuverlässigkeit
**Status:** Konzeptionsphase, Start der Umsetzung April 2026

## Ausgangslage

### Die ursprüngliche Idee

Im Steem-Witness-Discord wurde die mangelhafte Zuverlässigkeit der zentralen API-Infrastruktur, insbesondere von api.steemit.com, thematisiert. Der Autor entwickelte daraus die Idee eines automatischen API-Node-Switchers — ein JavaScript-Modul, das bei Ausfall eines Nodes transparent auf einen funktionierenden wechselt.

### Die strategische Erweiterung

Im Laufe der Diskussion kristallisierten sich weitere Ebenen heraus:

- Nicht nur ein Switcher, sondern eine vollständige Monitor-Infrastruktur mit aggregierten Statistiken
- Nicht nur lokale Browser-Messungen, sondern unabhängige Server-seitige Messungen von mehreren Standorten
- Nicht nur private Statistiken, sondern öffentliche Chain-basierte Tages-Berichte als Accountability-Instrument
- Nicht nur eine Subdomain, sondern eine komplette Neuausrichtung von steemapps.com als Portfolio-Dach für alle Projekte des Autors

### Motivation

Das Projekt erfüllt mehrere Ziele gleichzeitig:

**Praktischer Nutzen:** Welako wird durch den Switcher unabhängiger von api.steemit.com-Ausfällen. Das ist besonders wichtig für den Launch am 1. Mai 2026, bei dem maximale Stabilität erforderlich ist.

**Community-Beitrag:** Andere Frontend-Betreiber (insbesondere Condenser-Forks) können denselben Switcher einsetzen. Die öffentlichen Statistiken helfen allen Community-Mitgliedern bei der Bewertung von Node-Zuverlässigkeit.

**Öffentliche Accountability:** Die automatisierten Tages-Reports schaffen eine objektive Grundlage für die Bewertung von API-Node-Betreibern. Das setzt positiven Druck auf Steemit Inc. und unterzuverlässige Betreiber.

**Strategische Positionierung:** Der Autor positioniert sich als aktiver Infrastruktur-Beitragender im Steem-Ökosystem. Das ist insbesondere für eine mögliche Top-20-Witness-Position relevant (Phantom-Vote-Strategie).

**Portfolio-Konsolidierung:** Alle Projekte des Autors (SQV, SARH, Welako, API-Monitor) werden unter einem professionellen Dach sichtbar. Das verstärkt die Wahrnehmung eines zusammenhängenden Gesamtwerks.

## Projekt-Gliederung

Das Gesamtprojekt zerfällt in vier logische Teilprojekte, die nacheinander umgesetzt werden:

### Teilprojekt 1: Neuausrichtung steemapps.com (Hauptseite)

**Zweck:** Portfolio-Seite für alle Projekte des Autors, zwölfsprachig, professionell.

**Umfang:**
- Komplette Neugestaltung der aktuellen Seite (die noch SteemSnap, SteemYum bewirbt — diese sind in Welako aufgegangen; NEON BLOCKS bleibt eigenständig als Spiel unter neonblocks.steemapps.com, wird zu einem späteren Zeitpunkt weiterentwickelt)
- Klare Zweiteilung: Abschnitt für Endnutzer (Welako), Abschnitt für Entwickler/Witnesses (SARH, SQV, API-Monitor)
- Zwölfsprachige Umsetzung in voller Qualität: Englisch, Deutsch, Spanisch, Französisch, Italienisch, Portugiesisch, Niederländisch, Polnisch, Russisch, Türkisch, Koreanisch, Chinesisch
- Hochwertige Screenshots aller Projekte
- Halb-automatisierte Pflege: Statischer redaktioneller Inhalt, aber dynamische Live-Elemente (API-Monitor-Status, letzte Steemit-Posts)

**Technologie:**
- Statische HTML-Seite mit CSS und minimalem JavaScript
- i18n-System zur Sprachumschaltung (einfacher Vanilla-JS-Ansatz, keine großen Frameworks)
- Hosting auf bestehendem Webserver (IONOS oder Contabo, je nach Kapazität)

### Teilprojekt 2: API-Monitor-Server

**Zweck:** Kontinuierliche, objektive Messung aller bekannten Steem-API-Nodes rund um die Uhr.

**Umfang:**
- Python-basiertes Monitor-Skript, läuft als systemd-Service
- Messung alle 60 Sekunden pro Node
- Gemessene Metriken: Erreichbarkeit, Latenz, Block-Aktualität, Fehlerrate, Konsistenz
- Speicherung in SQLite-Datenbank (später ggf. MariaDB-Migration bei Wachstum)
- Optional: Messung von mehreren Server-Standorten (Contabo Deutschland, IONOS Deutschland, Backup-Server, ggf. kleine VPS in USA und Asien)

**Zu überwachende Nodes (initial):**
- api.steemit.com (Steemit Inc.)
- steemd.steemworld.org (Steemchiller)
- api.justyy.com (Justyy)
- steem.dfw.world
- api.campingclub.me (ety001)
- api.steem.fans (ety001)
- Weitere werden ergänzt, sobald sie bekannt werden

**Hosting:** IONOS-Server (REDACTED-IP). Alreco-Projekt läuft dort mit geringer Last weiter, Kapazitäten sind ausreichend.

### Teilprojekt 3: Öffentliche Statistik-Webseite (api.steemapps.com)

**Zweck:** Live-Dashboard aller überwachten API-Nodes mit historischen Daten und regionaler Visualisierung.

**Umfang:**
- Übersichtsseite mit Ampel-Status aller Nodes
- Detailseite pro Node: Uptime-Kurven, Latenz-Historie, Ausfall-Liste mit Zeitstempeln
- Regionale Heatmap: Latenz-Karten aus verschiedenen Messstandorten
- Archiv der täglichen Chain-Reports
- Automatische Aktualisierung alle 60 Sekunden
- Zwölfsprachig wie Hauptseite

**Technologie:**
- Frontend: Statisches HTML + Chart.js für Diagramme + Leaflet für Karten
- Backend: Kleines Python/Flask-API, das Datenbank-Abfragen als JSON zurückliefert
- Hosting: Gleicher IONOS-Server wie Monitor

### Teilprojekt 4: Automatisierter Daily-Report-Generator

**Zweck:** Täglicher, automatischer Steemit-Post mit zusammengefasster Statistik aller API-Nodes.

**Umfang:**
- Cron-Job, läuft einmal täglich um 2 Uhr nachts deutscher Zeit (für den Vortag)
- Aggregiert Monitor-Daten des Vortags
- Rendert regionale Karte als PNG-Bild
- Generiert strukturierten Steemit-Post-Text (HTML-Format)
- Postet automatisch auf Steemit über dedizierten Account (Vorschlag: @steem-api-health oder von @greece-lover)
- Zusätzlich: Strukturierte custom_json-Operation mit Rohdaten auf der Chain

**Post-Inhalt:**
- Zusammenfassung: Bester Node des Tages, schlechtester, größter Ausfall
- Vollständige Tabelle aller Nodes mit Uptime, Latenz, Fehlerzahl
- Historischer Vergleich zur Vorwoche
- Regionale Karte
- Analyse: Worauf ist zurückzuführen, was auffällig ist
- Links: Zu api.steemapps.com für Detail-Ansicht, zur custom_json-Operation für Rohdaten

**Sprach-Strategie für Posts:** Zweisprachig Deutsch/Englisch im selben Post. Später ggf. separate Posts in anderen Sprachen, wenn sinnvoll.

## Technische Architektur

### Datenfluss

```
  ┌─────────────────┐
  │ Monitor-Server  │   (IONOS, läuft 24/7)
  │ (Python/cron)   │
  └────────┬────────┘
           │ alle 60s
           ↓
  ┌─────────────────┐
  │ Steem API-Nodes │   (api.steemit.com, steemd.steemworld.org, ...)
  └────────┬────────┘
           │ Antworten
           ↓
  ┌─────────────────┐
  │ SQLite-DB       │   (auf IONOS-Server)
  │ (Messwerte)     │
  └────────┬────────┘
           │
           ├─→ ┌─────────────────────┐
           │   │ api.steemapps.com   │   (Live-Dashboard)
           │   └─────────────────────┘
           │
           └─→ ┌─────────────────────┐
               │ Daily-Report-Cron   │   (einmal täglich)
               │ (Python)            │
               └──────────┬──────────┘
                          │
                          ├─→ Steemit-Post (via RPC)
                          └─→ custom_json auf Chain
```

### Ergänzende Datenquelle: Client-Switcher

Zusätzlich zu den Server-Monitoring-Daten sammelt der Client-Switcher (Teil von the production server und später SARH) anonymisierte Messwerte aus echten Nutzer-Sessions:

- Browser-Frontend misst bei jedem API-Call Latenz und Erfolg
- Aggregierte Werte (keine persönlichen Daten) werden stündlich an ein Backend-Endpoint gesendet
- Dieses Endpoint leitet die Daten an den IONOS-Monitor-Server weiter
- Datenpunkt-Typ wird markiert ("server_monitor" vs. "client_aggregate")

Das schafft zwei komplementäre Datenquellen:
- **Server-Monitor:** Objektive, kontinuierliche Messung aus festen Standorten
- **Client-Switcher:** Echte Nutzungsrealität aus verschiedenen Weltregionen

### Datenschutz und Sicherheit

**Was öffentlich und auf der Chain liegt:**
- Aggregierte Zählwerte pro Zeitraum und Node
- Durchschnittliche Latenzen, Uptime-Prozente, Fehlersummen
- Grobe regionale Kategorisierung (Europa, Asien, Amerika) ohne Personenbezug

**Was niemals gespeichert oder veröffentlicht wird:**
- IP-Adressen von Nutzern
- Individuelle Nutzer-IDs
- Einzelne Request-Patterns
- Geo-IP-Daten
- Cookies oder Tracker

**Authentifizierung:**
- Der Daily-Report-Generator postet mit einem dedizierten Steem-Account
- Active-Key wird sicher auf dem Server gespeichert (root-only, verschlüsselte Konfiguration)
- Der Account hat keine anderen Rechte außer Posting

## Messgrößen und Algorithmen

### Gesundheits-Score pro Node

Der Score wird pro Messzyklus (60 Sekunden) neu berechnet:

```
Score = 100 Punkte Startwert
  - Latenz über 500ms:        minus 20
  - Latenz über 2000ms:       minus 50 (zusätzlich)
  - Block-Rückstand > 3:      minus 30
  - Block-Rückstand > 10:     minus 70 (zusätzlich)
  - Fehlerrate > 20% (20 letzte Calls): minus 40
  - Keine Antwort in 60s:     minus 100 (komplett tot)
```

Nodes mit Score unter 60 werden im Client-Switcher ausgeschlossen.

### Uptime-Berechnung

- Pro Tag: Prozent aller Messungen, die erfolgreich waren (Erreichbar + gültige Antwort + Block nicht zu alt)
- Pro Woche und Monat: Durchschnitt der Tagesuptime-Werte

### Ausfall-Definition

Ein "Ausfall" ist ein zusammenhängender Zeitraum, in dem der Node entweder:
- Nicht erreichbar ist (Timeout oder Verbindungsfehler)
- HTTP-Fehler zurückgibt
- Mehr als 10 Blöcke hinter der Chain-Realität liegt

Ausfälle unter 2 Minuten werden als "kurze Störung" markiert, ab 2 Minuten als "echter Ausfall".

## Zeitplan und Meilensteine

### Woche 1 (24.-30. April 2026)

**Tag 1 (heute):**
- Konzept-Dokument (dieses Dokument) fertigstellen
- steemapps.com-Hauptseiten-Textentwurf auf Englisch
- Entscheidung zu Screenshots und Projekt-Vorstellungen

**Tag 2:**
- Claude Code: Monitor-Skript auf IONOS-Server einrichten
- Monitor startet, erste Messungen werden erfasst
- Nginx-Konfiguration für api.steemapps.com

**Tag 3-4:**
- Claude Code: Statistik-Frontend für api.steemapps.com bauen
- Erste sichtbare Live-Daten
- Zwölfsprachigkeit der Hauptseite steemapps.com

**Tag 5-7:**
- Frontend-Integration des Client-Switchers
- Testlauf
- Daily-Report-Generator programmieren, initial ohne automatisches Posten

### Woche 2 (ab 1. Mai 2026)

**1. Mai:** Hauptprojekt-Launch (ohnehin geplant, Switcher ist dann schon integriert)

**2.-3. Mai:** Erster manueller Daily-Report-Test, Prüfung der Qualität

**4. Mai:** Erster automatisierter Daily-Report auf Steemit

**5.-7. Mai:** Beobachtung, Feintuning, Community-Reaktionen abwarten

### Woche 3 und darüber hinaus

- Monitor-Standorte erweitern (USA, Asien), wenn finanziell sinnvoll
- Condenser-Anpassung des Switchers für öffentlichen Pull Request
- Öffentlichkeitsarbeit: Steemit-Post zur Ankündigung des Projekts

## Arbeitsumgebung und Zuständigkeiten

### Windows-Host des Autors

- Arbeitsverzeichnis: `C:\tmp\steemapps\` (neu, separat von SARH und SQV)
- Konsole: Separate Claude-Code-Instanz, damit Kontexte nicht kollidieren

### IONOS-Server (REDACTED-IP)

- Projekt-Verzeichnis: `/opt/steemapps/`
- Monitor-Dienst: `/opt/steemapps/monitor/`
- Frontend-Dateien: `/var/www/api.steemapps.com/`
- Datenbank: `/opt/steemapps/data/monitor.db`
- Logs: `/var/log/steemapps/`

### production-server (REDACTED-IP) — unberührt

- Der production-server ist produktive Basis mit Monaten Entwicklungsaufwand
- Hauptprojekt-Launch 1. Mai 2026 hat absolute Priorität
- **Für das Monitor-Projekt wird dieser Server nicht angefasst**
- Die bestehende statische Site `/opt/steemapps/` und die dort konfigurierten Subdomains (neonblocks.steemapps.com, steemglory.steemapps.com) bleiben wie sie sind
- Die Hauptseite steemapps.com wird später redaktionell aktualisiert (nur HTML-Austausch, keine Infrastruktur-Änderung)

### Zuständigkeiten

**Autor (Holger Jacob / @greece-lover):**
- Strategische Entscheidungen
- Review der Inhalte und Screenshots
- Account-Keys und Server-Zugänge
- Freigabe vor öffentlicher Veröffentlichung

**Claude (dieser Assistent):**
- Konzeption und Dokumentation
- Textentwürfe und Übersetzungs-Qualitätskontrolle
- Screenshot-Begutachtung (Bildanalyse)
- Strategische Beratung

**Claude Code:**
- Technische Umsetzung auf Servern
- Screenshot-Erstellung per Playwright
- Code-Implementierung in allen Teilprojekten
- Automatische Bildbearbeitung mit Pillow

## Lizenz- und Veröffentlichungsstrategie

### Kernregeln

**Monitor-Code wird Open Source sein.** MIT-Lizenz. Der Zweck ist maximale Transparenz der Methodik. Jeder soll den Code prüfen, forken und selbst hosten können.

**Hauptseite steemapps.com bleibt redaktionell gepflegt.** Kein Open Source, keine Forks erwünscht.

**Chain-Reports sind öffentlich.** Die custom_json-Operationen mit Rohdaten sind für alle einsehbar und wiederverwendbar.

**Welako-Client-Switcher-Integration bleibt zunächst closed source**, solange Welako selbst closed source bleibt. Nach Hauptprojekt-Launch kann der Switcher-Teil separat als Library veröffentlicht werden.

### Veröffentlichungs-Entscheidungen

- Das Monitor-Projekt wird **privat** auf GitHub entwickelt, bis der erste automatisierte Daily-Report erfolgreich läuft
- Gleichzeitig mit dem ersten Report wird das Repository **öffentlich** geschaltet
- Ein Ankündigungs-Post auf Steemit erklärt Konzept, Methodik und Zugang zu Rohdaten

## Namens-Konventionen

### Subdomains

- steemapps.com — Portfolio-Hauptseite
- api.steemapps.com — API-Monitor-Dashboard
- vault.steemapps.com — SQV Demo (später)
- recovery.steemapps.com — SARH (später)

### Steem-Accounts

- @greece-lover — Haupt-Account für Community-Kommunikation
- @steem-api-health oder @steemapps — Vorschlag für automatisierte Daily-Reports (noch zu entscheiden)

### custom_json-IDs

- `steemapps_api_stats_daily` — Tägliche Zusammenfassung
- `steemapps_api_outage` — Ausfall-Meldungen (bei schwerwiegenden Ereignissen sofort)

## Kommunikationsregeln für Claude und Claude Code

Die bestehenden Kommunikationsregeln aus den SQV- und SARH-Projekt-Dokumenten gelten analog:

1. Deutsch als Primärsprache für Chat und interne Doku
2. Englisch als Primärsprache für öffentliche Inhalte
3. Kurz und präzise, keine Abschweifungen
4. Konkrete Anweisungen statt Options-Listen
5. Nur eine Frage pro Nachricht bei Rückfragen
6. Keine Bestätigungen vor offensichtlichen Standardhandlungen
7. Ehrlich bei Problemen, ohne Drama
8. Strategische Ebene beachten

### Zusätzliche Regeln für dieses Projekt

**Keine Erwähnung anderer Chains im öffentlichen Code oder in der Dokumentation.** Gleiche Regel wie bei SARH.

**Tabellen und Statistiken müssen methodisch transparent sein.** Jede veröffentlichte Zahl muss nachvollziehbar sein: Wie gemessen, wie aggregiert, welche Ausschlüsse. Das schützt vor Vorwürfen der Manipulation.

**Keine Häme oder Schadenfreude bei schlechten Node-Ergebnissen.** Die Tages-Reports sind sachlich, fakten-orientiert, ohne wertende Kommentare. Die Zahlen sprechen für sich.

## Dokumentation und Transparenz

### Öffentliche Dokumente

- **README.md** auf GitHub mit Methodik-Erklärung
- **ARCHITECTURE.md** mit technischem Aufbau
- **MEASUREMENT-METHODOLOGY.md** mit detaillierter Beschreibung aller Messgrößen und Algorithmen
- **API.md** mit Beschreibung der öffentlichen Endpoints (für Wiederverwendung der Daten)

### Interne Dokumente

- `progress/YYYY-MM-DD-titel.md` für jeden Arbeitstag
- `docs/KI_TRANSPARENZ.md` nach SQV/SARH-Vorbild
- Chain-Keys und Passwörter nur in `.env.local`, über `.gitignore` ausgeschlossen

## Zielgruppen der Veröffentlichung

### Primäre Zielgruppen

**Steem-Witnesses:** Profitieren von objektiven Daten zur Bewertung von API-Betreibern. Politisch einflussreich.

**Frontend-Betreiber:** Können den Switcher integrieren, profitieren von Ausfall-Warnungen.

**Steem-Stakeholder (insbesondere Phantom und große Account-Inhaber):** Profitieren von verbesserter Infrastruktur-Qualität, die direkten Einfluss auf Nutzungs-Aktivität hat.

### Sekundäre Zielgruppen

**Normale Steem-Nutzer:** Profitieren passiv durch stabilere Frontends.

**Entwickler anderer Steem-Forks:** Können Monitor-Daten nutzen, ohne selbst messen zu müssen.

**Journalisten oder Analysten über Crypto-Ökosysteme:** Nutzen die öffentlichen Daten für Analysen und Berichte.

## Offene Entscheidungen

Diese Punkte sind im Konzept enthalten, aber noch nicht final entschieden:

1. **Account für Daily-Reports:** Neuer Account @steem-api-health oder bestehender @greece-lover?
2. **Anzahl der Monitor-Standorte zu Beginn:** Nur Deutschland (IONOS) oder gleich mit USA und Asien?
3. **Wann Repository öffentlich machen:** Direkt beim ersten Monitor-Start oder erst beim ersten Daily-Report?
4. **Domain für reine Statistik-Seite:** api.steemapps.com oder eigenständige Domain wie steem-status.info?
5. **Umgang mit Betreibern, die ihre Nodes offline nehmen:** Automatische Entfernung aus Monitor oder weiter als "permanent offline" listen?

Diese Fragen werden im Laufe der Umsetzung beantwortet und im Konzept aktualisiert.

## Strategische Wirkung (langfristige Perspektive)

Das Projekt schafft mehrere Hebel gleichzeitig:

**Für den Autor als Witness:**
- Sichtbarkeit als aktiver Infrastruktur-Beiträger
- Konkrete Leistung vorzeigbar (nicht nur Versprechen)
- Mögliche Basis für Phantom-Vote in die Top 20

**Für das Steem-Ökosystem:**
- Höhere Frontend-Zuverlässigkeit durch Client-Switcher
- Öffentlicher Druck auf schlechte Node-Betreiber
- Anerkennung für gute Node-Betreiber
- Grundlage für datenbasierte Diskussionen über Infrastruktur-Qualität

**Für Welako:**
- Stabilität zum Launch und darüber hinaus
- Referenz-Use-Case für alle anderen Community-Beiträge
- Eingebaute Glaubwürdigkeit ("hier wird selbst genutzt, was entwickelt wird")

## Anhang: Referenzen und verwandte Dokumente

- **SQV_PROJEKT_KONTEXT.md** — Kontext des Quantum-Vault-Projekts
- **SARH_AUFTRAG.md** — Kontext des Recovery-Hub-Projekts
- **Bestehende interne Dokumentation** (intern)
- **Recherche-Bericht API-Switcher** unter `C:\tmp\api-switcher-research\RECHERCHE.md`

Diese Dokumente beschreiben das breitere Projekt-Portfolio des Autors und den Kontext, in den dieses steemapps.com-Projekt eingebettet ist.

---

*Dieses Dokument wird aktualisiert, sobald sich Projektumfang, Zeitplan oder Entscheidungen ändern. Letzte Aktualisierung: 24. April 2026, 10:30 Uhr MESZ.*
