# BGETech Modbus für Home Assistant

Native Home-Assistant-Integration für Stromzähler von B+G E-Tech, die über ein
Modbus-TCP-Gateway (RS485 ⇄ Ethernet) angebunden sind. Node-RED, MQTT oder
Hilfsskripte sind nicht nötig, die gesamte Einrichtung erfolgt in der
Home-Assistant-Oberfläche.

🇬🇧 [English documentation](README.md)

## Funktionen

- Mehrere Zähler (Slave-IDs) pro Gateway, mehrere Gateways pro Installation
- **Blockweises Lesen:** Alle Werte eines Zählers werden mit möglichst wenigen
  Anfragen gelesen (DRT428M: 2 Anfragen je Zähler, unabhängig von der Zahl
  aktivierter Entitäten)
- Ein Kommunikationsmanager pro Gateway: Anfragen laufen nacheinander, nie
  parallel auf dem RS485-Bus; automatische Wiederverbindung, Timeouts und
  Wiederholungen
- Ein Zähler, der nicht antwortet, beeinträchtigt nur seine eigenen Entitäten
  und wird mit wachsendem Abstand erneut versucht (bis 5 Minuten)
- Abfrageintervall pro Gateway (Standard 5 s), optional pro Zähler getrennt
  für Momentanwerte und Energiezähler
- Geeignet für das Energie-Dashboard (Bezug/Einspeisung als
  `total_increasing`)
- **Sicher:** Messwerte werden mit den Function Codes 03/04 gelesen. Der
  einzige Schreibzugriff ist die Auswahl *Modus Gesamtenergie* (Combined Code
  des DRT428M, FC06 auf Register 0x000B, nur die Werte 1/5/9, danach
  Kontroll-Lesen).
- Diagnose-Entitäten und Diagnose-Download ohne Hostnamen

## Unterstützte Geräte

| Modell | Status | Anfragen je Abfrage |
|---|---|---|
| B+G E-Tech DRT428M-3 | am Gerät verifiziert | 2 |
| B+G E-Tech DRT428M-2 | Registertabelle laut Herstellerhandbuch | 2 |

Die übrigen Modelle des [BGETech-Moduls für IP-Symcon](https://github.com/Nall-chan/BGETech)
(Eastron SDM, DRT710M, DRS210C, DRS458, Smart X96-5C) sind in
[docs/reference-analysis.md](docs/reference-analysis.md) analysiert und folgen
in einer späteren Version.

## Messwerte (DRT428M)

| Messwert | Entitäten | Standardmäßig aktiv |
|---|---|---|
| Spannung | L1, L2, L3 | ✔ |
| Strom | L1, L2, L3 | ✔ |
| Frequenz | | ✔ |
| Wirkleistung | gesamt, L1, L2, L3 | ✔ |
| Blindleistung | gesamt, L1–L3 | gesamt |
| Scheinleistung | gesamt, L1–L3 | gesamt |
| Leistungsfaktor | gesamt, L1–L3 | gesamt |
| Wirkenergie gesamt / Bezug / Einspeisung | gesamt, L1–L3 | Summen |
| Blindenergie gesamt / Bezug / Einspeisung | gesamt, L1–L3 | – |
| Tarifzähler T1–T4 (nur DRT428M-3) | Wirk-/Blindenergie, gesamt/Bezug/Einspeisung | – |
| Modus Gesamtenergie (Combined Code) | Auswahl (Konfiguration) | ✔ |
| Zählerverbindung | Diagnose | ✔ |

Der Zähler liefert Leistungen in kW/kvar/kVA, Home Assistant zeigt sie in
W/var/VA an. Deaktivierte Entitäten lassen sich in den Entitätseinstellungen
aktivieren und verursachen keine zusätzlichen Modbus-Anfragen.

Gateway-Diagnose: Gateway-Verbindung, letzter erfolgreicher Lesevorgang,
letzter Fehler, Fehlerzähler, Dauer des Abfragezyklus, Anfragen pro Zyklus,
erreichbare Zähler sowie (standardmäßig deaktiviert) durchschnittliche
Zyklusdauer, durchschnittliche Antwortzeit und Wiederverbindungen.

## Installation

### Über HACS

1. HACS → ⋮ → *Benutzerdefinierte Repositories* →
   `https://github.com/RcRaCk2k/ha_bgetech_modbus`, Typ *Integration*
2. **BGETech Modbus** installieren und Home Assistant neu starten

### Manuell

Den Ordner `custom_components/bgetech_modbus` nach
`<config>/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

### Gateway

*Einstellungen → Geräte & Dienste → Integration hinzufügen → BGETech Modbus*

| Einstellung | Standard |
|---|---|
| Name | BGETech Gateway |
| IP-Adresse / Hostname | – |
| Port | 502 |
| Abfrageintervall | 5 s |
| Timeout | 5 s |
| Wiederholungen | 2 |
| Maximale Register pro Anfrage | 0 = automatisch (125) |

Das Protokoll ist immer Modbus TCP.

Abfrageintervall, Timeout, Wiederholungen und Blockgröße lassen sich später
über **Konfigurieren** ändern, Name, Host und Port über **Neu konfigurieren**.
Änderungen werden sofort übernommen.

### Zähler hinzufügen, bearbeiten, entfernen

Am Gateway-Eintrag **Zähler hinzufügen** wählen:

- **Slave-ID**: 1–247, pro Gateway eindeutig
- **Name**: frei wählbar, z. B. *Hausanschluss*, *Wärmepumpe*, *Ladesäule 1*.
  Der Name kann jederzeit geändert werden, Geräte- und Entitäts-IDs bleiben
  dabei erhalten.
- **Modell**: *DRT428M (-2 / -3 automatisch erkennen)* liest Register 0x0130
  und unterscheidet so DRT428M-2 und DRT428M-3.
- **Aktiviert**: deaktivierte Zähler werden nicht abgefragt
- **Verbindung prüfen**: liest den Zähler vor dem Speichern einmal aus
- **Abfrageintervall Momentanwerte / Energiezähler** (optional): leer = Intervall des Gateways

Beispiel:

| Slave-ID | Name | Modell |
|---|---|---|
| 3 | Hausanschluss | DRT428M-3 |
| 4 | Wärmepumpe | DRT428M-3 |
| 5 | Ladesäule 1 | DRT428M-3 |
| 6 | Ladesäule 2 | DRT428M-3 |

Bearbeiten und Entfernen erfolgt über das ⋮-Menü des Zählers. Die Slave-ID
selbst lässt sich nicht ändern: Zähler entfernen und neu hinzufügen.

## Energie-Dashboard

- **Netzbezug:** *Wirkenergie Bezug*
- **Netzeinspeisung:** *Wirkenergie Einspeisung*

Beide Zähler steigen nur an (`total_increasing`, kWh).

*Wirkenergie gesamt* hängt vom *Combined Code* des Zählers ab (Register
0x000B, Auswahl-Entität *Modus Gesamtenergie* auf der Geräteseite des
Zählers):

| Option | Code | *Wirkenergie gesamt* |
|---|---|---|
| Nur Bezug | 1 | Bezug |
| Bezug + Einspeisung (Werkseinstellung) | 5 | Bezug + Einspeisung |
| Bezug − Einspeisung | 9 | Bezug − Einspeisung (kann sinken) |

Die Einstellung ändert auch die Anzeige im Display und die Zählweise des
S0-Impulsausgangs. Die Zähler für Bezug und Einspeisung bleiben unverändert.
Weil der Gesamtwert sinken kann, wird er mit `state_class: total`
bereitgestellt und eignet sich nicht als Verbrauchsquelle.

Der DRT428M bietet keinen Befehl zum Zurücksetzen der Energiezähler, daher
gibt es keinen Reset-Button.

## Leistung

Gemessen am Referenzsystem (4 × DRT428M-3, RS485 9600 bit/s 8E1,
Modbus-TCP-Gateway):

| | |
|---|---|
| Anfragen pro Zyklus | 8 (2 je Zähler) |
| Anfrage Momentanwerte (46 Register) | ≈ 190 ms |
| Anfrage Energiezähler inkl. Tarife (96 Register) | ≈ 340–385 ms |
| Durchschnittliche Zyklusdauer (4 Zähler) | 2,37 s |

Zyklen überlappen sich nie. Dauert ein Zyklus länger als das Intervall,
beginnt der nächste direkt im Anschluss. Bei vielen Zählern an einem
9600-bit/s-Bus die Energiezähler seltener abfragen (z. B. 30–60 s) oder die
Baudrate erhöhen.

## Fehlersuche

- **Gateway-Verbindung aus:** Host und Port prüfen. Prüfen, dass kein anderer
  Modbus-Master gleichzeitig auf das Gateway zugreift (z. B. ein altes
  Node.js-Skript).
- **Zählerverbindung aus:** Slave-ID, Verkabelung und Schnittstellenparameter
  prüfen (DRT428M Standard: 9600 bit/s, 8E1). Der DRT428M beantwortet
  Anfragen auf nicht belegte Adressen gar nicht – ein falsches Modell zeigt
  sich daher als Timeout.
- **Debug-Log:**
  ```yaml
  logger:
    logs:
      custom_components.bgetech_modbus: debug
  ```
- *Einstellungen → Geräte & Dienste → BGETech Modbus → ⋮ → Diagnose
  herunterladen* enthält Lesepläne, Zähler und die letzten Fehler.

## Bekannte Einschränkungen

- Nur Modbus TCP. RTU over TCP und serielles RTU werden nicht unterstützt.
- Bisher nur DRT428M-2/-3.
- Die Energiezähler des DRT428M lassen sich per Modbus nicht zurücksetzen.
- Die Seriennummer wird nur angezeigt, wenn der Zähler eine liefert (am
  Referenzsystem `00000000`).
- Voraussetzung: Home Assistant 2026.10 oder neuer.

## Quellen und Lizenz

Registerdefinitionen: Handbuch der B+G-E-Tech-DRT428M-Serie (Modbus-
Registertabelle), durch lesende Messungen bestätigt; Quervergleich mit
[Nall-chan/BGETech](https://github.com/Nall-chan/BGETech) (CC BY-NC-SA 4.0,
kein Code übernommen). Details: [docs/reference-analysis.md](docs/reference-analysis.md).

Lizenz: [MIT](LICENSE). Kein offizielles Produkt von B+G E-Tech.
