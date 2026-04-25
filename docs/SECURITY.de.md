# Sicherheit

*English version: [SECURITY.md](SECURITY.md)*

## Bedrohungsmodell

Dieses Projekt betreibt einen schreibfähigen Dienst (den Monitor), eine nur-lesende HTTP-API und einen zeitgesteuerten Reporter, der genau einen Posting-Key hält. Angriffsflächen in der Reihenfolge der Relevanz:

1. **Diebstahl des Posting-Keys des Reporter-Accounts** — würde es einem Angreifer erlauben, unter einer wiedererkennbaren Identität irreführende „offizielle" Reports zu posten.
2. **Manipulation der Datenbank** — würde es einem Angreifer erlauben, falsche Uptime-Zahlen unterzuschieben.
3. **API-Oberfläche** — nur lesend; minimales Risiko, darf aber keine privaten Daten preisgeben.
4. **Supply-Chain des Quellcodes** — pip-Abhängigkeiten, Integrität der systemd-Unit.

Wir verwalten keine Nutzer-Gelder, Nutzer-Credentials oder personenbezogene Daten. Der Monitor nimmt überhaupt keine eingehenden Daten von Nutzern entgegen.

## Schlüssel und Geheimnisse

- **Niemals in Git.** Active- und Owner-Keys befinden sich nie in diesem Repository. CI hat keinen Zugriff auf sie. Pull Requests haben keinen Zugriff auf sie.
- **Posting-Key des Reporters** liegt in `/opt/steemapps-monitor/.env.local`, Modus `0600`, Eigentümer `steemapps-monitor:steemapps-monitor` (oder der Service-User). Nur der Reporter-Prozess liest ihn.
- **Keine Memos** — der Reporter signiert niemals Transfers, nur `comment` und `custom_json`.
- **Key-Umfang** — der dedizierte Reporter-Account hat ausschließlich eine Posting-Authority. Keine Active-Authority. Kein Vermögen auf dem Account über den Bandwidth-Bedarf hinaus.

Falls ein Key als kompromittiert verdächtigt wird, besteht die Abhilfe darin, den Posting-Key on-chain zu rotieren und neu zu deployen. Die Monitor-Logs und -Datenbank enthalten keine Geheimnisse, die ebenfalls rotiert werden müssten.

## Was wir erfassen und was nicht

Der Monitor erfasst Messungen, die er selbst gegen öffentliche Endpoints durchführt. Er erfasst **nicht**:

- Nutzer-IP-Adressen
- Nutzer-Accountnamen, die durch irgendein Frontend geflossen sind
- Request-Payloads, Cookies, Browser-Fingerprints
- Geo-IP, User-Agent-Strings oder jede Form von Browser-Telemetrie

Die Welako-Client-Switcher-Erweiterung (spätere Arbeit) wird aggregierte, anonymisierte Zähler senden, niemals nutzerbezogene Daten. Diese Integration wird separat dokumentiert und vor dem Einspielen geprüft.

## On-Chain-Daten

Die `custom_json`-Operationen unter den IDs `steemapps_api_stats_daily` und `steemapps_api_outage` enthalten ausschließlich aggregierte Zahlen auf Node-Ebene. Keine Nutzerdaten. Die Chain ist unveränderlich, daher können diese Daten nicht widerrufen werden — das ist so gewollt (Reproduzierbarkeit, Accountability).

## Repository-Privatsphäre

Das Repository ist bis Phase 7 privat. Während der privaten Phase:

- Collaborator-Zugriff beschränkt auf den Autor.
- Keine CI-Secrets konfiguriert.
- Keine Produktions-Credentials werden committet; die Datei `.env.example` im Repo zeigt ausschließlich die Variablennamen.

Wenn das Repository öffentlich wird, bestätigt ein Pre-Switch-Audit:

- Keine echten Keys in der Historie (inklusive Git-Historie — `git log -p | grep -iE 'key|secret|password|pass='`)
- Keine kundenspezifischen Server-Hostnames über die bereits öffentliche Server-Adresse hinaus
- Keine Entwicklungs-Reste oder interne VM-Bezeichner, die nicht öffentlich sein sollten

## Dienst-Härtung

Mindestniveau für das Produktions-Deployment:

- Nicht-Root-Service-User (`steemapps-monitor`)
- systemd-Härtungs-Direktiven: `PrivateTmp=yes`, `ProtectSystem=strict`, `ProtectHome=yes`, `NoNewPrivileges=yes`, `ReadWritePaths=/opt/steemapps-monitor/data /opt/steemapps-monitor/logs`
- UFW: nur der Reverse-Proxy-Port für die API öffentlich exponiert; der Monitor-Prozess spricht nur ausgehend
- Log-Rotation mit begrenzter Aufbewahrungsdauer

## Meldung einer Schwachstelle

Solange das Repository privat ist, bitte Bedenken direkt an @greece-lover auf Steemit oder via privatem Discord. Nach der Veröffentlichung wird ein Kontakt-Abschnitt im `SECURITY.md` mit bevorzugtem Meldekanal ergänzt.
