# Referenzanalyse (Phase 1)

Stand: 2026-10-09

## Quellen und Lizenz

| Quelle | Verwendung |
|---|---|
| [Nall-chan/BGETech](https://github.com/Nall-chan/BGETech) v3.51, CC BY-NC-SA 4.0 | Nur Quervergleich der Registeradressen. **Kein Code übernommen.** |
| Eigene Node.js-Implementierung des Projektinhabers (nicht im Repository) | Validierung DRT428M: Startregister, Datenformat, Einheiten |
| [B+G E-Tech DRT428M-Serie Handbuch](https://xn--stromzhler-v5a.eu/media/14/df/30/1696582671/drt428m-serie_manual-register.pdf), S. 12–14 | Primärquelle DRT428M |
| Lesende Messungen am Referenzsystem (4 × DRT428M-3, FC03) | Verifikation der Registerbelegung, Energiesemantik, Antwortzeiten |

Registeradressen sind technische Fakten der Geräte. Diese Integration steht unter MIT-Lizenz.

## Modellübersicht (laut BGETech)

| Modell | Hersteller | Werte | FC | Datenformat | Status |
|---|---|---|---|---|---|
| DRT428M-2/-3 | B+G E-Tech | 47 (BGETech) / 71 inkl. Tarife (Handbuch) | 03 | Float32 BE | **Handbuch + am Gerät verifiziert** |
| DRT710M | B+G E-Tech | 26 | 03 | Integer, keine Skalierung bekannt | experimentell – Skalierung/Breite unklar |
| DRS210C | B+G E-Tech | 13 | 03 + 04 | Float32 BE, Tarif als Integer | experimentell |
| DRS458 | B+G E-Tech | 1 | 03 | Float32 BE | experimentell |
| SDM120C | Eastron | 10 | 04 | Float32 BE | aus BGETech |
| SDM120-Modbus | Eastron | 21 | 04 | Float32 BE | aus BGETech |
| SDM220 | Eastron | 14 | 04 | Float32 BE | aus BGETech |
| SDM230 | Eastron | 24 | 04 | Float32 BE | aus BGETech |
| SDM530 | Eastron | 68 | 04 | Float32 BE | aus BGETech |
| SDM630 | Eastron | 74 | 04 | Float32 BE | aus BGETech |
| SDM72D | Eastron | 9 | 04 | Float32 BE | aus BGETech |
| SDM72DM-V2 | Eastron | 41 | 04 | Float32 BE | aus BGETech |
| Smart X96-5C | Eastron | 84 | 04 | Float32 BE | aus BGETech |

### Auffälligkeiten in BGETech

- Jeder Wert wird mit einer eigenen Anfrage gelesen (danach 333 ms Pause). Es gibt dort keine Erkenntnisse über Blockreads.
- **DRT710M:** Werte als Integer ohne Skalierungsfaktor. Bei 2 Registern dekodiert BGETech nur 16 Bit (`unpack('n')`). Werte sind daher nicht vertrauenswürdig.
- **DRS210C:** Tarifregister wird wie beim DRT710M nur mit 16 Bit dekodiert.
- **SDM72D:** „Settable … energy“ ist vom Benutzer rücksetzbar → `state_class: total`.

## DRT428M-2 / DRT428M-3

Primärquelle: [B+G E-Tech, DRT428M-Serie Handbuch mit Registertabelle, S. 12–14](https://xn--stromzhler-v5a.eu/media/14/df/30/1696582671/drt428m-serie_manual-register.pdf).
Zusätzlich lesend am Referenzsystem gemessen (Gateway Modbus TCP, RS485 9600 bit/s, Slaves 3–6, nur FC03).

### Kommunikation laut Handbuch

- RS485, **8E1** (1 Start, 8 Daten, Even Parity, 1 Stop = 11 Bit/Byte), Standard 9600 bit/s, Standard-ID 01.
- Lesen ausschließlich **FC03**. FC04 wird nicht beantwortet (gemessen: Timeout).
- Fehlerantwort `0x83` + Code (01 Funktion ungültig, 02 Adresse existiert nicht, 03 Daten ungültig). **Aber:** „address error and CRC error no return“ – bei ungültigen Adressen antwortet der Zähler **gar nicht**. Gemessen: Lesen ab `0x004A` → Timeout.
- Schreibregister (FC06/FC16) existieren für ID, Baudrate, S0-Rate, Combined Code, Feiertag/Wochenende, Display-Zykluszeit, Uhrzeit und Tariftabellen. **Ein Register zum Zurücksetzen der Energiezähler gibt es nicht.** Die Integration schreibt ausschließlich den Combined Code (`0x000B`, FC06, nur 1/5/9).

### Registerbelegung (Handbuch, alle Float32 BE sofern nicht anders angegeben)

| Bereich | Inhalt | Variante | Verwendung in der Integration |
|---|---|---|---|
| `0x0000` (2 Reg., BCD) | Seriennummer, 8 Ziffern (Referenzsystem: `00000000`) | beide | Geräteinfo, wenn ≠ 0 |
| `0x0002` (1 Reg.) | Modbus-ID | beide | Plausibilitätsprüfung beim Einrichten |
| `0x0003` (1 Reg.) | Baudrate (`0x2580` = 9600) | beide | Diagnose |
| `0x0004` | Softwareversion (gemessen 1,02) | beide | `sw_version` |
| `0x0006` | Hardwareversion (gemessen 1,0) | beide | `hw_version` |
| `0x0009` | S0-Impulsrate (gemessen 1000) | beide | Diagnose |
| `0x000B` (1 Reg.) | **Combined Code**: 1 = nur Bezug, 5 = Bezug + Lieferung (Werkseinstellung), 9 = Bezug − Lieferung | beide | bestimmt die Semantik von „Total“ (s. u.) |
| `0x000C` (1 Reg.) | Feiertag/Wochenend-Tariftabelle | -3 | – |
| `0x000D` (1 Reg., BCD) | Display-Zykluszeit 1–30 s (gemessen 5) | beide | – |
| `0x000E–0x003B` | U L1–L3, f, I L1–L3, P/Q/S gesamt + L1–L3, PF gesamt + L1–L3 | beide | **Block „instant“** |
| `0x003C` (4 Reg., BCD) | Uhrzeit `SS MM HH WW DD MM YY 00` | -3 | optional Diagnose (Uhren am Referenzsystem nicht synchron) |
| `0x0040` (1 Reg.) | Sommer/Winterzeit-Umschaltung | -3 | – |
| `0x0041` (1 Reg.) | CRC-Code (Firmware-Prüfsumme, gemessen `0x75A3`) | beide | – |
| `0x0042–0x0049` | **nicht dokumentiert**; gemessen identisch mit `0x0100–0x0107` | – | nicht verwenden |
| `0x0100–0x012F` | Wirk-/Blindenergie: Total, Forward (Bezug), Reverse (Lieferung), jeweils gesamt + L1–L3 | beide | **Block „energy“** |
| `0x0130–0x015F` | Tarife T1–T4: je Total/Forward/Reverse Wirk- und Blindenergie | **-3** | Block „energy“ (nur -3) |
| `0x0300–0x036B` | Tarif-Zeittabellen und Zeitzonen (BCD) | -3 | – |

Damit lässt sich der gesamte Energiebereich des DRT428M-3 (`0x0100–0x015F`, 96 Register) mit **einer** Anfrage lesen (≤ 125 Register). Live bestätigt: 340–385 ms.

Plausibilität Tarife (Slave 3): T1 Total 2468,54 + T2 Total 1764,61 = 4233,15 ≈ Total 4233,13. T3/T4 sind am Referenzsystem unbenutzt (0).

### Combined Code und Energiesemantik

Am Referenzsystem steht der Combined Code auf **9 (Bezug − Lieferung)**, nicht auf der Werkseinstellung 5. Die Node.js-Referenz enthält einen auskommentierten Schreibbefehl auf `0x000B` mit Wert 9.

Gemessen an Slave 6 (mit Einspeisung):

| Register | Bedeutung | Beleg | state_class |
|---|---|---|---|
| `0x0108` Forward gesamt | Σ Bezug L1–L3 | 17776,2 | `total_increasing` |
| `0x0110` Reverse gesamt | Σ Lieferung L1–L3 | 9,62 = 1,77 + 7,85 + 0 | `total_increasing` |
| `0x0100` Total gesamt | bei Code 9: Bezug − Lieferung | 17776,2 − 9,62 = 17766,6 | `total` |
| `0x0102–0x0106` Total Lx | Bezug + Lieferung der Phase (unabhängig vom Code 9) | L1: 7486,02 + 1,77 = 7487,79 | `total_increasing` |
| `0x0118` Total Blindenergie | Code 9: Saldo, oft negativ | 248,22 − 1983,55 = −1735,33 | `total` |
| `0x011A–0x011E` Total Blindenergie Lx | gemessen bei Code 9: Bezug + Lieferung der Phase | L1: 87,86 + 1198,09 = 1285,95 | `total` |
| `0x0130` T1 Total | Code 9: Saldo | 13164,5 − 8,43 = 13156,07 | wie `0x0100` |

Konsequenz:
- Für das Energy Dashboard werden immer **Forward (`0x0108`)** und **Reverse (`0x0110`)** verwendet.
- Alle „Total“-Register (gesamt, je Phase, Tarife) werden unabhängig vom Code mit `state_class: total` bereitgestellt, weil sie je nach Code sinken können. Der Code selbst wird beim Start und nach jeder Wiederverbindung gelesen und als Select-Entität angezeigt.
- Der Combined Code kann über die Auswahl-Entität *Modus Gesamtenergie* geändert werden (FC06, Whitelist 1/5/9, Kontroll-Lesen). Er beeinflusst auch Display und S0-Ausgang, nicht aber die Forward-/Reverse-Zähler.

### Antwortzeiten (Modbus TCP → RS485 9600 bit/s, 8E1)

| Anfrage | Dauer |
|---|---|
| 14 Register | 80–240 ms |
| 48 Register (`0x0100`) | 200–310 ms |
| 60 Register (`0x000E`) | ca. 230 ms |
| 74 Register (`0x0000`) | ca. 275 ms |
| undefinierter Bereich | Timeout (keine Antwort) |

| 96 Register (`0x0100–0x015F`) | 340–385 ms |
| 46 Register (`0x000E–0x003B`) | ca. 190 ms |

Kompletter Abfragezyklus mit der Integration (4 Zähler, 8 Anfragen): **Ø 2,37 s**, Ø Antwortzeit 255 ms, 0 Fehler (6 Zyklen gemessen).

**Folgerung für die Blockplanung:** Blöcke dürfen nur aus explizit als lesbar definierten Registerbereichen gebildet werden. Der Zähler meldet ungültige Adressen nicht mit einer Exception, deshalb wird nicht automatisch sondiert. Ein Timeout wird nicht als „Block zu groß“ interpretiert.

## Registertabellen aller Modelle (aus BGETech, nur Fakten)

FC 03 = Read Holding Registers, FC 04 = Read Input Registers. „Regs“ = Anzahl 16-Bit-Register.

### DRS210C

13 Werte, FC 03, 04

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x2000` | 03 | float | 2 | Voltage | Volt.230 |
| `0x2020` | 03 | float | 2 | Frequency | Hertz.50 |
| `0x2060` | 03 | float | 2 | Current | Ampere |
| `0x2080` | 03 | float | 2 | Active power | Watt.14490 |
| `0x20A0` | 03 | float | 2 | Reactive power | VaR |
| `0x20C0` | 03 | float | 2 | Apparent power | VA |
| `0x20E0` | 03 | float | 2 | Power factor | – |
| `0x2200` | 03 | integer | 2 | Current tariff | – |
| `0x3000` | 03 | float | 2 | Total active energy | Electricity |
| `0x3020` | 04 | float | 2 | Total import energy | Electricity |
| `0x3040` | 04 | float | 2 | Total export energy | Electricity |
| `0x3140` | 03 | float | 2 | Active energy tariff 1 | Electricity |
| `0x3240` | 03 | float | 2 | Active energy tariff 2 | Electricity |

### DRS458

1 Werte, FC 03

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0000` | 03 | float | 2 | Total active energy | Electricity |

### DRT428M

47 Werte, FC 03

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x000E` | 03 | float | 2 | Voltage L1 | Volt.230 |
| `0x0010` | 03 | float | 2 | Voltage L2 | Volt.230 |
| `0x0012` | 03 | float | 2 | Voltage L3 | Volt.230 |
| `0x0014` | 03 | float | 2 | Frequency | Hertz.50 |
| `0x0016` | 03 | float | 2 | Current L1 | Ampere |
| `0x0018` | 03 | float | 2 | Current L2 | Ampere |
| `0x001A` | 03 | float | 2 | Current L3 | Ampere |
| `0x001C` | 03 | float | 2 | Total active power | Power |
| `0x001E` | 03 | float | 2 | Active power L1 | Power |
| `0x0020` | 03 | float | 2 | Active power L2 | Power |
| `0x0022` | 03 | float | 2 | Active power L3 | Power |
| `0x0024` | 03 | float | 2 | Total reactive power | VaR |
| `0x0026` | 03 | float | 2 | Reactive power L1 | VaR |
| `0x0028` | 03 | float | 2 | Reactive power L2 | VaR |
| `0x002A` | 03 | float | 2 | Reactive power L3 | VaR |
| `0x002C` | 03 | float | 2 | Total apparent power | VA |
| `0x002E` | 03 | float | 2 | Apparent power L1 | VA |
| `0x0030` | 03 | float | 2 | Apparent power L2 | VA |
| `0x0032` | 03 | float | 2 | Apparent power L3 | VA |
| `0x0034` | 03 | float | 2 | Total power factor | – |
| `0x0036` | 03 | float | 2 | Power factor L1 | – |
| `0x0038` | 03 | float | 2 | Power factor L2 | – |
| `0x003A` | 03 | float | 2 | Power factor L3 | – |
| `0x0100` | 03 | float | 2 | Total active energy | Electricity |
| `0x0102` | 03 | float | 2 | Total active energy L1 | Electricity |
| `0x0104` | 03 | float | 2 | Total active energy L2 | Electricity |
| `0x0106` | 03 | float | 2 | Total active energy L3 | Electricity |
| `0x0108` | 03 | float | 2 | Import active energy | Electricity |
| `0x010A` | 03 | float | 2 | Import active energy L1 | Electricity |
| `0x010C` | 03 | float | 2 | Import active energy L2 | Electricity |
| `0x010E` | 03 | float | 2 | Import active energy L3 | Electricity |
| `0x0110` | 03 | float | 2 | Export active energy | Electricity |
| `0x0112` | 03 | float | 2 | Export active energy L1 | Electricity |
| `0x0114` | 03 | float | 2 | Export active energy L2 | Electricity |
| `0x0116` | 03 | float | 2 | Export active energy L3 | Electricity |
| `0x0118` | 03 | float | 2 | Total reactive energy | kVArh |
| `0x011A` | 03 | float | 2 | Total reactive energy L1 | kVArh |
| `0x011C` | 03 | float | 2 | Total reactive energy L2 | kVArh |
| `0x011E` | 03 | float | 2 | Total reactive energy L3 | kVArh |
| `0x0120` | 03 | float | 2 | Import reactive energy | kVArh |
| `0x0122` | 03 | float | 2 | Import reactive energy L1 | kVArh |
| `0x0124` | 03 | float | 2 | Import reactive energy L2 | kVArh |
| `0x0126` | 03 | float | 2 | Import reactive energy L3 | kVArh |
| `0x0128` | 03 | float | 2 | Export reactive energy | kVArh |
| `0x012A` | 03 | float | 2 | Export reactive energy L1 | kVArh |
| `0x012C` | 03 | float | 2 | Export reactive energy L2 | kVArh |
| `0x012E` | 03 | float | 2 | Export reactive energy L3 | kVArh |

### DRT710M

26 Werte, FC 03

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0010` | 03 | integer | 2 | Voltage L1 | Volt.I |
| `0x0012` | 03 | integer | 2 | Voltage L2 | Volt.I |
| `0x0014` | 03 | integer | 2 | Voltage L3 | Volt.I |
| `0x004E` | 03 | integer | 2 | Frequency | Hertz.I |
| `0x0050` | 03 | integer | 2 | Current L1 | Ampere.I |
| `0x0052` | 03 | integer | 2 | Current L2 | Ampere.I |
| `0x0054` | 03 | integer | 2 | Current L3 | Ampere.I |
| `0x0056` | 03 | integer | 2 | Neutral current | Ampere.I |
| `0x0090` | 03 | integer | 2 | Active power L1 | Watt.I |
| `0x0092` | 03 | integer | 2 | Active power L2 | Watt.I |
| `0x0094` | 03 | integer | 2 | Active power L3 | Watt.I |
| `0x0096` | 03 | integer | 2 | Total system power | Watt.I |
| `0x00D0` | 03 | integer | 2 | Apparent power L1 | VA.I |
| `0x00D2` | 03 | integer | 2 | Apparent power L2 | VA.I |
| `0x00D4` | 03 | integer | 2 | Apparent power L3 | VA.I |
| `0x00D6` | 03 | integer | 2 | Total system apparent power | VA.I |
| `0x0110` | 03 | integer | 2 | Reactive power L1 | VaR.I |
| `0x0112` | 03 | integer | 2 | Reactive power L2 | VaR.I |
| `0x0114` | 03 | integer | 2 | Reactive power L3 | VaR.I |
| `0x0116` | 03 | integer | 2 | Total system reactive power | VaR.I |
| `0x0150` | 03 | integer | 2 | Power factor L1 | – |
| `0x0152` | 03 | integer | 2 | Power factor L2 | – |
| `0x0154` | 03 | integer | 2 | Power factor L3 | – |
| `0x0156` | 03 | integer | 2 | Total system power factor | – |
| `0x0160` | 03 | integer | 2 | Total import energy | Electricity.I |
| `0x0166` | 03 | integer | 2 | Total export energy | Electricity.I |

### SDM120C

10 Werte, FC 04

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0000` | 04 | float | 2 | Voltage | Volt.230 |
| `0x0006` | 04 | float | 2 | Current | Ampere |
| `0x000C` | 04 | float | 2 | Active power | Watt.14490 |
| `0x0012` | 04 | float | 2 | Apparent power | VA |
| `0x0018` | 04 | float | 2 | Reactive power | VaR |
| `0x001E` | 04 | float | 2 | Power factor | – |
| `0x0046` | 04 | float | 2 | Frequency | Hertz.50 |
| `0x0048` | 04 | float | 2 | Total import energy | Electricity |
| `0x004A` | 04 | float | 2 | Total export energy | Electricity |
| `0x0156` | 04 | float | 2 | Total active energy | Electricity |

### SDM120ModBus

21 Werte, FC 04

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0000` | 04 | float | 2 | Voltage | Volt.230 |
| `0x0006` | 04 | float | 2 | Current | Ampere |
| `0x000C` | 04 | float | 2 | Active power | Watt.14490 |
| `0x0012` | 04 | float | 2 | Apparent power | VA |
| `0x0018` | 04 | float | 2 | Reactive power | VaR |
| `0x001E` | 04 | float | 2 | Power factor | – |
| `0x0046` | 04 | float | 2 | Frequency | Hertz.50 |
| `0x0048` | 04 | float | 2 | Total import energy | Electricity |
| `0x004A` | 04 | float | 2 | Total export energy | Electricity |
| `0x004C` | 04 | float | 2 | Total import reactive energy | kVArh |
| `0x004E` | 04 | float | 2 | Total export reactive energy | kVArh |
| `0x0054` | 04 | float | 2 | Total system power demand | Watt.14490 |
| `0x0056` | 04 | float | 2 | Maximum total system power demand | Watt.14490 |
| `0x0058` | 04 | float | 2 | Current system positive power demand | Watt.14490 |
| `0x005A` | 04 | float | 2 | Maximum system positive power demand | Watt.14490 |
| `0x005C` | 04 | float | 2 | Current system reverse power demand | Watt.14490 |
| `0x005E` | 04 | float | 2 | Maximum system reverse power demand | Watt.14490 |
| `0x0102` | 04 | float | 2 | Current demand | Ampere |
| `0x0108` | 04 | float | 2 | Maximum current demand | Ampere |
| `0x0156` | 04 | float | 2 | Total active energy | Electricity |
| `0x0158` | 04 | float | 2 | Total reactive energy | kVArh |

### SDM220

14 Werte, FC 04

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0000` | 04 | float | 2 | Voltage | Volt.230 |
| `0x0006` | 04 | float | 2 | Current | Ampere |
| `0x000C` | 04 | float | 2 | Active power | Watt.14490 |
| `0x0012` | 04 | float | 2 | Apparent power | VA |
| `0x0018` | 04 | float | 2 | Reactive power | VaR |
| `0x001E` | 04 | float | 2 | Power factor | – |
| `0x0024` | 04 | float | 2 | Phase angle | PhaseAngle |
| `0x0046` | 04 | float | 2 | Frequency | Hertz.50 |
| `0x0048` | 04 | float | 2 | Total import energy | Electricity |
| `0x004A` | 04 | float | 2 | Total export energy | Electricity |
| `0x004C` | 04 | float | 2 | Total import reactive energy | kVArh |
| `0x004E` | 04 | float | 2 | Total export reactive energy | kVArh |
| `0x0156` | 04 | float | 2 | Total active energy | Electricity |
| `0x0158` | 04 | float | 2 | Total reactive energy | kVArh |

### SDM230

24 Werte, FC 04

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0000` | 04 | float | 2 | Voltage | Volt.230 |
| `0x0006` | 04 | float | 2 | Current | Ampere |
| `0x000C` | 04 | float | 2 | Active power | Watt.14490 |
| `0x0012` | 04 | float | 2 | Apparent power | VA |
| `0x0018` | 04 | float | 2 | Reactive power | VaR |
| `0x001E` | 04 | float | 2 | Power factor | – |
| `0x0024` | 04 | float | 2 | Phase angle | PhaseAngle |
| `0x0046` | 04 | float | 2 | Frequency | Hertz.50 |
| `0x0048` | 04 | float | 2 | Total import energy | Electricity |
| `0x004A` | 04 | float | 2 | Total export energy | Electricity |
| `0x004C` | 04 | float | 2 | Total import reactive energy | kVArh |
| `0x004E` | 04 | float | 2 | Total export reactive energy | kVArh |
| `0x0054` | 04 | float | 2 | Total system power demand | Watt.14490 |
| `0x0056` | 04 | float | 2 | Maximum total system power demand | Watt.14490 |
| `0x0058` | 04 | float | 2 | Current system positive power demand | Watt.14490 |
| `0x005A` | 04 | float | 2 | Maximum system positive power demand | Watt.14490 |
| `0x005C` | 04 | float | 2 | Current system reverse power demand | Watt.14490 |
| `0x005E` | 04 | float | 2 | Maximum system reverse power demand | Watt.14490 |
| `0x0102` | 04 | float | 2 | Current demand | Ampere |
| `0x0108` | 04 | float | 2 | Maximum current demand | Ampere |
| `0x0156` | 04 | float | 2 | Total active energy | Electricity |
| `0x0158` | 04 | float | 2 | Total reactive energy | kVArh |
| `0x0180` | 04 | float | 2 | Resettable total energy | Electricity |
| `0x0182` | 04 | float | 2 | Resettable total reactive energy | kVArh |

### SDM530

68 Werte, FC 04

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0000` | 04 | float | 2 | Voltage L1 | Volt.230 |
| `0x0002` | 04 | float | 2 | Voltage L2 | Volt.230 |
| `0x0004` | 04 | float | 2 | Voltage L3 | Volt.230 |
| `0x0006` | 04 | float | 2 | Current L1 | Ampere |
| `0x0008` | 04 | float | 2 | Current L2 | Ampere |
| `0x000A` | 04 | float | 2 | Current L3 | Ampere |
| `0x000C` | 04 | float | 2 | Active power L1 | Watt.14490 |
| `0x000E` | 04 | float | 2 | Active power L2 | Watt.14490 |
| `0x0010` | 04 | float | 2 | Active power L3 | Watt.14490 |
| `0x0012` | 04 | float | 2 | Apparent power L1 | VA |
| `0x0014` | 04 | float | 2 | Apparent power L2 | VA |
| `0x0016` | 04 | float | 2 | Apparent power L3 | VA |
| `0x0018` | 04 | float | 2 | Reactive power L1 | VaR |
| `0x001A` | 04 | float | 2 | Reactive power L2 | VaR |
| `0x001C` | 04 | float | 2 | Reactive power L3 | VaR |
| `0x001E` | 04 | float | 2 | Power factor L1 | – |
| `0x0020` | 04 | float | 2 | Power factor L2 | – |
| `0x0022` | 04 | float | 2 | Power factor L3 | – |
| `0x0024` | 04 | float | 2 | Phase angle L1 | PhaseAngle |
| `0x0026` | 04 | float | 2 | Phase angle L2 | PhaseAngle |
| `0x0028` | 04 | float | 2 | Phase angle L3 | PhaseAngle |
| `0x002A` | 04 | float | 2 | Average line to neutral voltage | Volt.230 |
| `0x002E` | 04 | float | 2 | Average line current | Ampere |
| `0x0030` | 04 | float | 2 | Sum of line currents | Ampere |
| `0x0034` | 04 | float | 2 | Total system power | Watt.14490 |
| `0x0038` | 04 | float | 2 | Total system apparent power | VA |
| `0x003C` | 04 | float | 2 | Total system reactive power | VaR |
| `0x003E` | 04 | float | 2 | Total system power factor | – |
| `0x0042` | 04 | float | 2 | Total system phase angle | PhaseAngle |
| `0x0046` | 04 | float | 2 | Frequency | Hertz.50 |
| `0x0048` | 04 | float | 2 | Total import energy | Electricity |
| `0x004A` | 04 | float | 2 | Total export energy | Electricity |
| `0x004C` | 04 | float | 2 | Total import reactive energy | kVArh |
| `0x004E` | 04 | float | 2 | Total export reactive energy | kVArh |
| `0x0050` | 04 | float | 2 | Reactive energy since last reset | Electricity |
| `0x0052` | 04 | float | 2 | Energy since last reset | Electricity |
| `0x0054` | 04 | float | 2 | Total system power demand | Watt.14490 |
| `0x0056` | 04 | float | 2 | Maximum total system power demand | Watt.14490 |
| `0x0064` | 04 | float | 2 | Total system apparent power demand | VA |
| `0x0066` | 04 | float | 2 | Maximum total system apparent power demand | VA |
| `0x0068` | 04 | float | 2 | Total neutral current demand | Ampere |
| `0x006A` | 04 | float | 2 | Maximum neutral current demand | Ampere |
| `0x00C8` | 04 | float | 2 | Line 1 to Line 2 voltage | Volt.230 |
| `0x00CA` | 04 | float | 2 | Line 2 to Line 3 voltage | Volt.230 |
| `0x00CC` | 04 | float | 2 | Line 3 to Line 1 voltage | Volt.230 |
| `0x00CE` | 04 | float | 2 | Average line to line voltage | Volt.230 |
| `0x00E0` | 04 | float | 2 | Neutral current | Ampere |
| `0x00EA` | 04 | float | 2 | Line 1 voltage THD | Intensity.F |
| `0x00EC` | 04 | float | 2 | Line 2 voltage THD | Intensity.F |
| `0x00EE` | 04 | float | 2 | Line 3 voltage THD | Intensity.F |
| `0x00F0` | 04 | float | 2 | Line 1 Current THD | Intensity.F |
| `0x00F2` | 04 | float | 2 | Line 2 Current THD | Intensity.F |
| `0x00F4` | 04 | float | 2 | Line 3 Current THD | Intensity.F |
| `0x00F8` | 04 | float | 2 | Average line to neutral voltage THD | Intensity.F |
| `0x00FA` | 04 | float | 2 | Average line current THD | Intensity.F |
| `0x00FE` | 04 | float | 2 | Total system power factor | PhaseAngle |
| `0x0102` | 04 | float | 2 | Line 1 current demand | Ampere |
| `0x0104` | 04 | float | 2 | Line 2 current demand | Ampere |
| `0x0106` | 04 | float | 2 | Line 3 current demand | Ampere |
| `0x0108` | 04 | float | 2 | Maximum line 1 current demand | Ampere |
| `0x010A` | 04 | float | 2 | Maximum line 2 current demand | Ampere |
| `0x010C` | 04 | float | 2 | Maximum line 3 current demand | Ampere |
| `0x014E` | 04 | float | 2 | Line 1 to line 2 voltage THD | Intensity.F |
| `0x0150` | 04 | float | 2 | Line 2 to line 3 voltage THD | Intensity.F |
| `0x0152` | 04 | float | 2 | Line 3 to line 1 voltage THD | Intensity.F |
| `0x0154` | 04 | float | 2 | Average line to line voltage THD | Intensity.F |
| `0x0156` | 04 | float | 2 | Total active energy | Electricity |
| `0x0158` | 04 | float | 2 | Total reactive energy | kVArh |

### SDM630

74 Werte, FC 04

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0000` | 04 | float | 2 | Voltage L1 | Volt.230 |
| `0x0002` | 04 | float | 2 | Voltage L2 | Volt.230 |
| `0x0004` | 04 | float | 2 | Voltage L3 | Volt.230 |
| `0x0006` | 04 | float | 2 | Current L1 | Ampere |
| `0x0008` | 04 | float | 2 | Current L2 | Ampere |
| `0x000A` | 04 | float | 2 | Current L3 | Ampere |
| `0x000C` | 04 | float | 2 | Active power L1 | Watt.14490 |
| `0x000E` | 04 | float | 2 | Active power L2 | Watt.14490 |
| `0x0010` | 04 | float | 2 | Active power L3 | Watt.14490 |
| `0x0012` | 04 | float | 2 | Apparent power L1 | VA |
| `0x0014` | 04 | float | 2 | Apparent power L2 | VA |
| `0x0016` | 04 | float | 2 | Apparent power L3 | VA |
| `0x0018` | 04 | float | 2 | Reactive power L1 | VaR |
| `0x001A` | 04 | float | 2 | Reactive power L2 | VaR |
| `0x001C` | 04 | float | 2 | Reactive power L3 | VaR |
| `0x001E` | 04 | float | 2 | Power factor L1 | – |
| `0x0020` | 04 | float | 2 | Power factor L2 | – |
| `0x0022` | 04 | float | 2 | Power factor L3 | – |
| `0x0024` | 04 | float | 2 | Phase angle L1 | PhaseAngle |
| `0x0026` | 04 | float | 2 | Phase angle L2 | PhaseAngle |
| `0x0028` | 04 | float | 2 | Phase angle L3 | PhaseAngle |
| `0x002A` | 04 | float | 2 | Average line to neutral voltage | Volt.230 |
| `0x002E` | 04 | float | 2 | Average line current | Ampere |
| `0x0030` | 04 | float | 2 | Sum of line currents | Ampere |
| `0x0034` | 04 | float | 2 | Total system power | Watt.14490 |
| `0x0038` | 04 | float | 2 | Total system apparent power | VA |
| `0x003C` | 04 | float | 2 | Total system reactive power | VaR |
| `0x003E` | 04 | float | 2 | Total system power factor | – |
| `0x0042` | 04 | float | 2 | Total system phase angle | PhaseAngle |
| `0x0046` | 04 | float | 2 | Frequency | Hertz.50 |
| `0x0048` | 04 | float | 2 | Total import energy | Electricity |
| `0x004A` | 04 | float | 2 | Total export energy | Electricity |
| `0x004C` | 04 | float | 2 | Total import reactive energy | kVArh |
| `0x004E` | 04 | float | 2 | Total export reactive energy | kVArh |
| `0x0050` | 04 | float | 2 | Reactive energy since last reset | Electricity |
| `0x0052` | 04 | float | 2 | Energy since last reset | Electricity |
| `0x0054` | 04 | float | 2 | Total system power demand | Watt.14490 |
| `0x0056` | 04 | float | 2 | Maximum total system power demand | Watt.14490 |
| `0x0064` | 04 | float | 2 | Total system apparent power demand | VA |
| `0x0066` | 04 | float | 2 | Maximum total system apparent power demand | VA |
| `0x0068` | 04 | float | 2 | Total neutral current demand | Ampere |
| `0x006A` | 04 | float | 2 | Maximum neutral current demand | Ampere |
| `0x00C8` | 04 | float | 2 | Line 1 to Line 2 voltage | Volt.230 |
| `0x00CA` | 04 | float | 2 | Line 2 to Line 3 voltage | Volt.230 |
| `0x00CC` | 04 | float | 2 | Line 3 to Line 1 voltage | Volt.230 |
| `0x00CE` | 04 | float | 2 | Average line to line voltage | Volt.230 |
| `0x00E0` | 04 | float | 2 | Neutral current | Ampere |
| `0x00EA` | 04 | float | 2 | Line 1 voltage THD | Intensity.F |
| `0x00EC` | 04 | float | 2 | Line 2 voltage THD | Intensity.F |
| `0x00EE` | 04 | float | 2 | Line 3 voltage THD | Intensity.F |
| `0x00F0` | 04 | float | 2 | Line 1 Current THD | Intensity.F |
| `0x00F2` | 04 | float | 2 | Line 2 Current THD | Intensity.F |
| `0x00F4` | 04 | float | 2 | Line 3 Current THD | Intensity.F |
| `0x00F8` | 04 | float | 2 | Average line to neutral voltage THD | Intensity.F |
| `0x00FA` | 04 | float | 2 | Average line current THD | Intensity.F |
| `0x00FE` | 04 | float | 2 | Total system power factor | PhaseAngle |
| `0x0102` | 04 | float | 2 | Line 1 current demand | Ampere |
| `0x0104` | 04 | float | 2 | Line 2 current demand | Ampere |
| `0x0106` | 04 | float | 2 | Line 3 current demand | Ampere |
| `0x0108` | 04 | float | 2 | Maximum line 1 current demand | Ampere |
| `0x010A` | 04 | float | 2 | Maximum line 2 current demand | Ampere |
| `0x010C` | 04 | float | 2 | Maximum line 3 current demand | Ampere |
| `0x014E` | 04 | float | 2 | Line 1 to line 2 voltage THD | Intensity.F |
| `0x0150` | 04 | float | 2 | Line 2 to line 3 voltage THD | Intensity.F |
| `0x0152` | 04 | float | 2 | Line 3 to line 1 voltage THD | Intensity.F |
| `0x0154` | 04 | float | 2 | Average line to line voltage THD | Intensity.F |
| `0x0156` | 04 | float | 2 | Total active energy | Electricity |
| `0x0158` | 04 | float | 2 | Total reactive energy | kVArh |
| `0x0166` | 04 | float | 2 | L1 total active energy | Electricity |
| `0x0168` | 04 | float | 2 | L2 total active energy | Electricity |
| `0x016A` | 04 | float | 2 | L3 total active energy | Electricity |
| `0x0178` | 04 | float | 2 | L1 total reactive energy | kVArh |
| `0x017A` | 04 | float | 2 | L2 total reactive energy | kVArh |
| `0x017C` | 04 | float | 2 | L3 total reactive energy | kVArh |

### SDM72D

9 Werte, FC 04

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0034` | 04 | float | 2 | Power | Watt.14490 |
| `0x0048` | 04 | float | 2 | Total import energy | Electricity |
| `0x004A` | 04 | float | 2 | Total export energy | Electricity |
| `0x0156` | 04 | float | 2 | Total active energy | Electricity |
| `0x0180` | 04 | float | 2 | Settable total energy | Electricity |
| `0x0184` | 04 | float | 2 | Settable import energy | Electricity |
| `0x0186` | 04 | float | 2 | Settable export energy | Electricity |
| `0x0500` | 04 | float | 2 | Import Power | Watt.14490 |
| `0x0502` | 04 | float | 2 | Export Power | Watt.14490 |

### SDM72DMV2

41 Werte, FC 04

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0000` | 04 | float | 2 | Voltage L1 | Volt.230 |
| `0x0002` | 04 | float | 2 | Voltage L2 | Volt.230 |
| `0x0004` | 04 | float | 2 | Voltage L3 | Volt.230 |
| `0x0006` | 04 | float | 2 | Current L1 | Ampere |
| `0x0008` | 04 | float | 2 | Current L2 | Ampere |
| `0x000A` | 04 | float | 2 | Current L3 | Ampere |
| `0x000C` | 04 | float | 2 | Active power L1 | Watt.14490 |
| `0x000E` | 04 | float | 2 | Active power L2 | Watt.14490 |
| `0x0010` | 04 | float | 2 | Active power L3 | Watt.14490 |
| `0x0012` | 04 | float | 2 | Apparent power L1 | VA |
| `0x0014` | 04 | float | 2 | Apparent power L2 | VA |
| `0x0016` | 04 | float | 2 | Apparent power L3 | VA |
| `0x0018` | 04 | float | 2 | Reactive power L1 | VaR |
| `0x001A` | 04 | float | 2 | Reactive power L2 | VaR |
| `0x001C` | 04 | float | 2 | Reactive power L3 | VaR |
| `0x001E` | 04 | float | 2 | Power factor L1 | – |
| `0x0020` | 04 | float | 2 | Power factor L2 | – |
| `0x0022` | 04 | float | 2 | Power factor L3 | – |
| `0x002A` | 04 | float | 2 | Average line to neutral voltage | Volt.230 |
| `0x002E` | 04 | float | 2 | Average line current | Ampere |
| `0x0030` | 04 | float | 2 | Sum of line currents | Ampere |
| `0x0034` | 04 | float | 2 | Total system power | Watt.14490 |
| `0x0038` | 04 | float | 2 | Total system apparent power | VA |
| `0x003C` | 04 | float | 2 | Total system reactive power | VaR |
| `0x003E` | 04 | float | 2 | Total system power factor | – |
| `0x0046` | 04 | float | 2 | Frequency | Hertz.50 |
| `0x0048` | 04 | float | 2 | Total import energy | Electricity |
| `0x004A` | 04 | float | 2 | Total export energy | Electricity |
| `0x00C8` | 04 | float | 2 | Line 1 to Line 2 voltage | Volt.230 |
| `0x00CA` | 04 | float | 2 | Line 2 to Line 3 voltage | Volt.230 |
| `0x00CC` | 04 | float | 2 | Line 3 to Line 1 voltage | Volt.230 |
| `0x00CE` | 04 | float | 2 | Average line to line voltage | Volt.230 |
| `0x00E0` | 04 | float | 2 | Neutral current | Ampere |
| `0x0156` | 04 | float | 2 | Total active energy | Electricity |
| `0x0158` | 04 | float | 2 | Total reactive energy | kVArh |
| `0x0180` | 04 | float | 2 | Resettable total active energy | Electricity |
| `0x0184` | 04 | float | 2 | Resettable import active energy | Electricity |
| `0x0186` | 04 | float | 2 | Resettable export active energy | Electricity |
| `0x018C` | 04 | float | 2 | Netto active energy | Electricity |
| `0x0500` | 04 | float | 2 | Import power | Watt.14490 |
| `0x0502` | 04 | float | 2 | Export power | Watt.14490 |

### SmartX965C

84 Werte, FC 04

| Register | FC | Typ | Regs | Name | BGETech-Profil |
|---|---|---|---|---|---|
| `0x0000` | 04 | float | 2 | Voltage L1 | Volt.230 |
| `0x0002` | 04 | float | 2 | Voltage L2 | Volt.230 |
| `0x0004` | 04 | float | 2 | Voltage L3 | Volt.230 |
| `0x0006` | 04 | float | 2 | Current L1 | Ampere |
| `0x0008` | 04 | float | 2 | Current L2 | Ampere |
| `0x000A` | 04 | float | 2 | Current L3 | Ampere |
| `0x000C` | 04 | float | 2 | Active power L1 | Watt.14490 |
| `0x000E` | 04 | float | 2 | Active power L2 | Watt.14490 |
| `0x0010` | 04 | float | 2 | Active power L3 | Watt.14490 |
| `0x0012` | 04 | float | 2 | Apparent power L1 | VA |
| `0x0014` | 04 | float | 2 | Apparent power L2 | VA |
| `0x0016` | 04 | float | 2 | Apparent power L3 | VA |
| `0x0018` | 04 | float | 2 | Reactive power L1 | VaR |
| `0x001A` | 04 | float | 2 | Reactive power L2 | VaR |
| `0x001C` | 04 | float | 2 | Reactive power L3 | VaR |
| `0x001E` | 04 | float | 2 | Power factor L1 | – |
| `0x0020` | 04 | float | 2 | Power factor L2 | – |
| `0x0022` | 04 | float | 2 | Power factor L3 | – |
| `0x0024` | 04 | float | 2 | Phase angle L1 | PhaseAngle |
| `0x0026` | 04 | float | 2 | Phase angle L2 | PhaseAngle |
| `0x0028` | 04 | float | 2 | Phase angle L3 | PhaseAngle |
| `0x002A` | 04 | float | 2 | Average line to neutral voltage | Volt.230 |
| `0x002E` | 04 | float | 2 | Average line current | Ampere |
| `0x0030` | 04 | float | 2 | Sum of line currents | Ampere |
| `0x0034` | 04 | float | 2 | Total system power | Watt.14490 |
| `0x0038` | 04 | float | 2 | Total system apparent power | VA |
| `0x003C` | 04 | float | 2 | Total system reactive power | VaR |
| `0x003E` | 04 | float | 2 | Total system power factor | – |
| `0x0042` | 04 | float | 2 | Total system phase angle | PhaseAngle |
| `0x0046` | 04 | float | 2 | Frequency | Hertz.50 |
| `0x0048` | 04 | float | 2 | Total import energy | Electricity |
| `0x004A` | 04 | float | 2 | Total export energy | Electricity |
| `0x004C` | 04 | float | 2 | Total import reactive energy | kVArh |
| `0x004E` | 04 | float | 2 | Total export reactive energy | kVArh |
| `0x0050` | 04 | float | 2 | Total apparent energy | Electricity |
| `0x0052` | 04 | float | 2 | Total energy | Electricity |
| `0x0054` | 04 | float | 2 | Total system power demand | Watt.14490 |
| `0x0056` | 04 | float | 2 | Maximum total system power demand | Watt.14490 |
| `0x0058` | 04 | float | 2 | Current system positive power demand | Watt.14490 |
| `0x005A` | 04 | float | 2 | Maximum system positive power demand | Watt.14490 |
| `0x005C` | 04 | float | 2 | Current system reverse power demand | Watt.14490 |
| `0x005E` | 04 | float | 2 | Maximum system reverse power demand | Watt.14490 |
| `0x0064` | 04 | float | 2 | Total system apparent power demand | VA |
| `0x0066` | 04 | float | 2 | Maximum total system apparent power demand | VA |
| `0x0068` | 04 | float | 2 | Total neutral current demand | Ampere |
| `0x006A` | 04 | float | 2 | Maximum neutral current demand | Ampere |
| `0x006C` | 04 | float | 2 | Total system reactive power demand | VaR |
| `0x006E` | 04 | float | 2 | Maximum total system reactive power demand | VaR |
| `0x0070` | 04 | float | 2 | Phase 1 displacement power factor | – |
| `0x0072` | 04 | float | 2 | Phase 2 displacement power factor | – |
| `0x0074` | 04 | float | 2 | Phase 3 displacement power factor | – |
| `0x0076` | 04 | float | 2 | Total displacement power factor | – |
| `0x00C8` | 04 | float | 2 | Line 1 to Line 2 voltage | Volt.230 |
| `0x00CA` | 04 | float | 2 | Line 2 to Line 3 voltage | Volt.230 |
| `0x00CC` | 04 | float | 2 | Line 3 to Line 1 voltage | Volt.230 |
| `0x00CE` | 04 | float | 2 | Average line to line voltage | Volt.230 |
| `0x00E0` | 04 | float | 2 | Neutral current | Ampere |
| `0x00EA` | 04 | float | 2 | Line 1 voltage THD | Intensity.F |
| `0x00EC` | 04 | float | 2 | Line 2 voltage THD | Intensity.F |
| `0x00EE` | 04 | float | 2 | Line 3 voltage THD | Intensity.F |
| `0x00F0` | 04 | float | 2 | Line 1 Current THD | Intensity.F |
| `0x00F2` | 04 | float | 2 | Line 2 Current THD | Intensity.F |
| `0x00F4` | 04 | float | 2 | Line 3 Current THD | Intensity.F |
| `0x00F8` | 04 | float | 2 | Average line to neutral voltage THD | Intensity.F |
| `0x00FA` | 04 | float | 2 | Average line current THD | Intensity.F |
| `0x00FE` | 04 | float | 2 | Total system power factor | PhaseAngle |
| `0x0102` | 04 | float | 2 | Line 1 current demand | Ampere |
| `0x0104` | 04 | float | 2 | Line 2 current demand | Ampere |
| `0x0106` | 04 | float | 2 | Line 3 current demand | Ampere |
| `0x0108` | 04 | float | 2 | Maximum line 1 current demand | Ampere |
| `0x010A` | 04 | float | 2 | Maximum line 2 current demand | Ampere |
| `0x010C` | 04 | float | 2 | Maximum line 3 current demand | Ampere |
| `0x014E` | 04 | float | 2 | Line 1 to line 2 voltage THD | Intensity.F |
| `0x0150` | 04 | float | 2 | Line 2 to line 3 voltage THD | Intensity.F |
| `0x0152` | 04 | float | 2 | Line 3 to line 1 voltage THD | Intensity.F |
| `0x0154` | 04 | float | 2 | Average line to line voltage THD | Intensity.F |
| `0x0156` | 04 | float | 2 | Total active energy | Electricity |
| `0x0158` | 04 | float | 2 | Total reactive energy | kVArh |
| `0x0166` | 04 | float | 2 | L1 total active energy | Electricity |
| `0x0168` | 04 | float | 2 | L2 total active energy | Electricity |
| `0x016A` | 04 | float | 2 | L3 total active energy | Electricity |
| `0x0178` | 04 | float | 2 | L1 total reactive energy | kVArh |
| `0x017A` | 04 | float | 2 | L2 total reactive energy | kVArh |
| `0x017C` | 04 | float | 2 | L3 total reactive energy | kVArh |

