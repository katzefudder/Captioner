<p align="center">
  <img src="captioner/resources/logo.svg" alt="Captioner-Logo" width="200">
</p>

<h1 align="center">Captioner</h1>

<p align="center">Fotos sichten, bewerten und beschriften, bevor sie in Lightroom importiert werden.</p>

Workflow-Tool für die Auswahl von Fotos, mit Code-Replacement aus den Roster-Dateien.
Entscheidungen und Begründung: [ADR 0001](../../docs/adr/0001-bildbeschriftung-mit-code-replacement.md).

## Starten

```bash
make install                 # einmalig, legt .venv an
make run                     # oder: make run FOLDER=/Volumes/NIKON\ Z\ 9/DCIM/100NCZ_9
make test
make bundle                  # dist/Captioner.app, ExifTool ist eingebaut
make installer               # zusätzlich DMG und PKG, siehe „Installer"
```

`make icons` erzeugt alle Icons (PNG, `.icns`, `.ico`) neu aus `captioner/resources/logo.svg`;
das Ergebnis ist eingecheckt, nötig ist das nur nach einer Änderung am Logo.

Für `make run` muss ExifTool installiert sein (`brew install exiftool`). Die gebündelte
App bringt ihr eigenes mit.

## Installer (macOS, Apple Silicon)

```bash
make installer        # baut die App und daraus beide Installer
make dmg              # nur Disk-Image: dist/Captioner-<version>-arm64.dmg
make pkg              # nur Installer-Paket: dist/Captioner-<version>-arm64.pkg
make verify           # prüft dist/Captioner.app: arm64, Signatur, Info.plist
```

* **DMG:** öffnen, `Captioner` auf „Programme" ziehen. Der übliche Weg auf dem Mac.
* **PKG:** Doppelklick, Installer-Assistent, installiert nach `/Programme`. Verweigert die
  Installation auf Intel-Macs und auf zu alten macOS-Versionen.
* Die App ist reines **arm64**; universelle Bibliotheken werden beim Bauen ausgedünnt.
* Die **Mindestversion** (`LSMinimumSystemVersion`, im PKG als Installationsbedingung)
  ermittelt `Captioner.spec` aus den gebündelten Bibliotheken. Derzeit **macOS 26**,
  weil PySide6 6.12 und das Homebrew-Python 3.11 dafür gebaut sind. Für ältere Macs:
  Python von python.org (läuft ab macOS 11) und PySide6 6.8 LTS (ab macOS 12) verwenden,
  dann sinkt die Angabe automatisch.
* Die **Version** kommt aus `pyproject.toml` (`version = …`).

### Releases auf GitHub

`.github/workflows/release.yml` baut bei jedem Push auf `main` (außer reinen
Markdown-Änderungen) auf einem macOS-26-Runner, führt die Tests aus und veröffentlicht
DMG und PKG als Release. Die Version ist `<major>.<minor>` aus `pyproject.toml` plus die
fortlaufende Laufnummer des Workflows, z. B. `0.1.17` mit Tag `v0.1.17`. Für eine neue
Minor-Version `pyproject.toml` hochsetzen. Manuell: Actions → Release → „Run workflow".
Die Releases sind ad-hoc signiert (siehe unten).

### Signieren und Notarisieren

Ohne Apple-Zertifikat ist die App nur ad-hoc signiert. Auf dem eigenen Mac läuft sie, auf
einem anderen Mac blockt Gatekeeper sie nach dem Download („kann nicht geöffnet
werden"). Für ein paar eigene Macs reicht: einmal **Systemeinstellungen → Datenschutz &
Sicherheit → „Dennoch öffnen"**, oder im Terminal
`xattr -dr com.apple.quarantine /Applications/Captioner.app`.

Für die Weitergabe an andere braucht es das **Apple Developer Program** (99 €/Jahr) mit
zwei Zertifikaten aus developer.apple.com → Certificates: *Developer ID Application*
(App, DMG) und *Developer ID Installer* (PKG). Dann:

```bash
# einmalig: Zugangsdaten für die Notarisierung im Schlüsselbund ablegen
xcrun notarytool store-credentials captioner \
    --apple-id <apple-id> --team-id <TEAMID> --password <app-spezifisches-passwort>

export CODESIGN_IDENTITY="Developer ID Application: Florian Dehn (TEAMID)"
export INSTALLER_IDENTITY="Developer ID Installer: Florian Dehn (TEAMID)"
export NOTARY_PROFILE=captioner
make installer        # signiert mit Hardened Runtime und Zeitstempel
make notarize         # lädt DMG und PKG zu Apple, wartet, heftet das Ticket an
```

Danach öffnen sich DMG und PKG auf jedem Apple-Silicon-Mac mit passender macOS-Version
ohne Warnung. `packaging/entitlements.plist` enthält das eine Recht, das Python mit
Hardened Runtime braucht.

## Arbeitsablauf

1. **Ordner öffnen** (`⌘O`, oder Ordner aufs Fenster ziehen). JPG, NEF und andere RAWs,
   DNG, TIFF. RAW+JPG mit gleichem Namen sind eine Kachel. Jeder Ordner bekommt einen
   eigenen **Tab**, siehe „Mehrere Ordner“.
2. **Template** wählen; **„Bearbeiten …“** daneben zeigt und ändert es, unter `⋯` gibt es
   „Neues Template …“ und **„Template-Datei laden …“** für eine Datei vom Rechner. Ein Template trägt: Ort, Urheber und Rechte (Fotograf, Copyright, …),
   Zusatz-Tags, Anhang und optional ein fester Titel (siehe „Templates als Dateien“).
   Ohne festen Titel taugt ein Template für jedes Spiel: den **Titel**
   (`DEL 2 - EC Bad Nauheim gegen Eisbären Regensburg`) trägst du im Panel ein, die
   folgenden Bilder übernehmen ihn, und die Code-Vorschläge zeigen die Spieler dieser
   beiden Teams zuerst. Weicht der Titel vom Format ab, warnt das Panel.
3. Bilder auswählen und **„Template auf Auswahl anwenden"**: Titel, Ort und Tags für alle.
4. Bild für Bild beschreiben. `#bi` öffnet die Liste der Bietigheim-Codes:

   ```
   Zweikampf #bi99# gegen #bn23#
   → Zweikampf -99- John Doe (Bietigheim Steelers) gegen -23- Marius Erk (EC Bad Nauheim),
     DEL 2 - EC Bad Nauheim gegen Bietigheim Steelers, Bad Nauheim, Colonel-Knight-Stadion, 09.10.26
   ```

   `Enter` speichert, `⌘N` bzw. `⌘]` speichert und springt weiter, `⌘B` bzw. `⌘[` zurück.
   Unbekannte Codes sind rot und verhindern das Speichern. Die Namen der Personen kommen
   automatisch in die Tags.

   **Von Foto zu Foto übertragen:** `⌘⇧C` kopiert Titel, Beschreibung, Tags, Stadt und Ort
   aus dem Panel (auch noch nicht Gespeichertes), `⌘N` weiter, `⌘⇧V` fügt ein und speichert.
   Die Beschreibung wird mit den Codes kopiert und je Foto neu aufgelöst; das Datum im Anhang
   ist das des Zielfotos. Mit mehreren ausgewählten Fotos fügt `⌘⇧V` in alle ein.
5. **Bewerten und taggen:** `⌘1`–`⌘8` Farbklasse, `1`–`5`
   Sterne, `T` Tag. Filter oben (oder `F3`/`F4`) zeigen nur die Auswahl.
6. **In Lightroom ziehen.** Die Auswahl (auch über mehrere Seiten) per Drag & Drop
   ins Lightroom-Raster; Lightroom öffnet den Import-Dialog.

## Menüs

Die Menüs stehen auf dem Mac oben in der Menüleiste des Bildschirms: **Captioner** (Über
Captioner, Einstellungen `⌘,`, Beenden `⌘Q`), **Ablage** (Ordner öffnen `⌘O`, in neuem
Tab, Neu einlesen `F5`, Tab schließen), **Template**, **Roster** und **Hilfe**
(Tastenkürzel, [Captioner-Website](https://www.katzefudder.de/captioner)).

## Mehrere Ordner (Tabs)

Jeder geöffnete Ordner bekommt einen Tab, z. B. je Ordner auf zwei Speicherkarten
(„NIKON Z 9 › 100NCZ_9“). Neuer Tab: `+` rechts neben den Reitern oder `⌘O`. Mehrere
Ordner auf einmal: im Dialog „Ordner öffnen“ mit `⌘`-Klick (oder `⇧`-Klick) mehrere
markieren, im Finder markieren und aufs Fenster ziehen, oder auf der Kommandozeile
`python -m captioner <ordner> <ordner> …`.

**Ganze Karte öffnen:** Enthält der gewählte oder gezogene Ordner selbst keine Bilder,
aber Unterordner mit Bildern (die Karte oder `DCIM`), öffnet jeder dieser Unterordner einen
eigenen Tab. Zwei Karten aus dem Finder aufs Fenster ziehen öffnet also alle Bildordner
beider Karten. Ab mehr als 8 Ordnern fragt die App vorher. Ist „Unterordner mit einlesen“
eingeschaltet, wird der Ordner stattdessen als ein Tab mit allen Unterordnern geöffnet.
Ein schon offener Ordner wird nur in den Vordergrund geholt.

**Aus dem Finder öffnen** (gebündelte App): Ordner oder Karten im Finder markieren und aufs
Captioner-Symbol im Dock ziehen, oder Rechtsklick → „Öffnen mit“ → Captioner. Läuft die App
schon, kommen die Ordner als neue Tabs dazu. macOS kennt diese Fähigkeit erst, nachdem die
App einmal aus `/Programme` gestartet wurde. Jeder Tab hat eigene Seite und Auswahl; Filter und Beschriftungs-Panel
gelten für den aktiven Tab.

**Kopieren zwischen Tabs:** Bilder aus der Galerie auf den Reiter eines anderen Tabs ziehen
(kurz darüber halten wechselt hinein, dann auch in dessen Galerie fallen lassen). Kopiert
werden RAW, JPG und Sidecar zusammen, mit allen gespeicherten Metadaten; die Quelle bleibt
unverändert. Gibt es eine Datei schon, fragt die App: **Überspringen**, **Umbenennen**
(`DSC_0001-2.NEF` + `-2.JPG` + `-2.xmp`) oder **Ersetzen**, auf Wunsch für alle weiteren.
Kopiert wird über eine Zwischendatei, ein Abbruch hinterlässt keine halben Bilder.

## Tastenkürzel

Belegung wie in einem Workflow-Tool für die Auswahl von Fotos. `F1` (oder
Hilfe → „Tastenkürzel“) zeigt alle Kürzel für das aktuelle System.

| Aktion | macOS | Windows |
|---|---|---|
| Farbklasse 1–8 / entfernen | `⌘1`–`⌘8` / `⌘0` | `Strg+1`–`8` / `Strg+0` |
| Sterne 1–5 / entfernen | `1`–`5` / `0` | `1`–`5` / `0` |
| Tag an/aus · an · aus | `T` · `+` · `-` | `T` · `+` · `-` |
| Großansicht | `Leertaste` | `Leertaste` |
| Beschriftung bearbeiten | `I` oder `Enter` | `I` oder `Enter` |
| Alle auswählen (alle Seiten) · Auswahl aufheben · Getaggte auswählen | `⌘A` · `⌘D` · `⌘T` | `Strg+A` · `Strg+D` · `Strg+T` |
| Nur getaggte · nur nicht getaggte (nochmal: alle) | `F3` · `F4` | `F3` · `F4` |
| Beschriftung kopieren · in Auswahl einfügen (auch im Panel) | `⌘⇧C` · `⌘⇧V` | `Strg+⇧C` · `Strg+⇧V` |
| Nächstes · vorheriges Bild | `⌘N`/`⌘]` · `⌘B`/`⌘[` | `Strg+M`/`Alt+]` · `Alt+B`/`Alt+[` |
| Template-Datei laden · speichern unter · anwenden | `⌘⌥L` · `⌘⌥S` · `⌘⌥A` | `Strg+Alt+L` · `S` · `A` |
| Seite zurück/vor | `Bild↑`/`Bild↓`, `⌘⇧[`/`⌘⇧]` | `Bild↑`/`Bild↓`, `Strg+←`/`→` |
| Erstes/letztes Bild · zuletzt angesehenes | `Pos1`/`Ende` · `L` | `Pos1`/`Ende` · `L` |
| Roster einstellen · neu laden | `⌘Control-C` · `⇧⌘Control-C` | `Strg+Alt+C` · `⇧Strg+Alt+C` |
| Tab schließen · nächster · vorheriger | `⌘W` · `⌘⌥→` · `⌘⌥←` | `Strg+W` · `Strg+Alt+→` · `Strg+Alt+←` |

Im Beschriftungs-Panel:

| Aktion | macOS | Windows |
|---|---|---|
| Speichern | `Enter` | `Enter` |
| Speichern und nächstes · vorheriges Bild | `⌘]`/`⌘N` · `⌘[`/`⌘B` | `Alt+]`/`Strg+M` · `Alt+[`/`Alt+B` |
| Speichern und zurück zur Galerie | `⌘Enter` | `Strg+Enter` |
| Nächstes · vorheriges ohne Speichern | `⌘⇧]`/`⌘⇧N` · `⌘⇧[`/`⌘⇧B` | `Alt+⇧]`/`Strg+⇧N` · `Alt+⇧[`/`Strg+⇧B` |
| Template anwenden | `⌘⌥C` | `Strg+Alt+C` |

In der Großansicht: `←`/`→` blättern, `T`, Farbklassen und Sterne wie oben, `Esc`/`⌘W`
schließt.

**Beschriften in der Großansicht:** `I` (oder „Beschriften“ unten) holt das
Beschriftungs-Panel neben das Bild und setzt den Cursor in die Beschreibung. Es ist dasselbe
Panel wie im Hauptfenster, mit Template, Code-Vervollständigung und Karte. `Enter` speichert,
`⌘N`/`⌘B` speichern und zeigen das nächste/vorige Foto groß, `⌘⇧C`/`⌘⇧V` kopieren und
fügen die Beschriftung ein. Beim Tippen lösen Ziffern, `T`, `Z`, `+`, `-` und die Leertaste
nichts aus; ein Klick aufs Bild (oder `⌘Enter`) gibt die Tasten wieder an die Großansicht.
Ob das Panel beim Öffnen dabei ist, merkt sich die App. **Zoom:** `Z` oder `*` schaltet zwischen eingepasst und 100 % um, `+`/`-` zoomen
stufenweise (50, 75, 100, 150, 200, 300, 400 %), der **Slider** unten stufenlos von 50 % bis
400 %; daneben „Einpassen" und „100 %". `⌥`+Mausrad oder Doppelklick zoomt an der
Mausposition, `⌘`+Klick zoomt auf die Stelle und holt sie in die Mitte. Im Zoom wird der
Ausschnitt **mit gedrückter Maustaste gezogen** (Hand-Cursor), alternativ Mausrad oder
`⌥`+Pfeiltasten (mit `⇧` schneller). Zoom und Ausschnitt bleiben beim Blättern
erhalten, so lässt sich die Schärfe einer Serie an derselben Stelle vergleichen.

Rechts in der Großansicht steht ein **Info-Panel** mit EXIF und IPTC des Bildes: Aufnahmezeit
(mit Hundertsteln), Kamera, Seriennummer, Auslösungen, Objektiv, Brennweite, Blende, Zeit,
ISO, Programm, Messung, Fokus, Weißabgleich, Auflösung, GPS; Titel, Beschreibung, Tags, Ort,
Fotograf, Copyright; Sterne, Farbklasse, Tag und die zugehörigen Dateien. Der Text ist
markierbar. „Infos" unten rechts blendet das Panel aus, die App merkt sich das. Kamerawerte
kommen bei RAW+JPG aus der RAW-Datei; die Beschriftung zeigt immer den aktuellen Stand,
auch direkt nach dem Speichern. 100 % ist
die volle Auflösung des eingebetteten JPEGs, bei Nikon-NEFs die volle Sensorauflösung.

Auf deutschen Tastaturen liegen `[` und `]` auf `⌥5`/`⌥6`; dafür gibt es die
Alternativen mit Buchstaben (`⌘N`, `⌘B`).

**Farbklassen und Tags** schreibt die App in die XMP-Felder `XMP-photomech:ColorClass` und
`XMP-photomech:Tagged`. Die Farbklasse geht zusätzlich als Lightroom-Label in die Datei,
Klasse 1–5 → `Red`, `Yellow`, `Green`, `Blue`, `Purple` (einstellbar). Lightroom kennt
keine Tags; die dienen zum Auswählen vor dem Drag.

## Wo die Metadaten landen

| Datei | wohin |
|---|---|
| NEF, CR2, ARW, … | `<name>.xmp` daneben. Die RAW-Datei wird nie verändert; ein vorhandenes Sidecar (auch `.XMP` aus einem Workflow-Tool für die Auswahl von Fotos) wird fortgeschrieben. |
| JPG, DNG, TIFF | in die Datei (IPTC + XMP + EXIF). Geschrieben wird in eine Kopie, die nur ersetzt, wenn die Bilddaten-Prüfsumme gleich bleibt. |

Lightroom übernimmt beim Import Titel, Beschreibung, Stichwörter, Sterne und Farbe. Die
Farbnamen müssen zum Label-Set in Lightroom passen, siehe Einstellungen.

## Ort und Karte

**Karte …** neben „Stadt“ (im Beschriftungs-Panel und im Template-Dialog) öffnet eine
OpenStreetMap-Karte:

* **Suchen:** Adresse, PLZ oder Halle eintippen, z. B. `61231 Bad Nauheim` oder
  `Colonel-Knight-Stadion`, Enter. Die Karte springt hin und füllt Stadt und Ort/Halle.
  Bei mehreren Treffern den passenden in der Liste wählen.
* **Klicken:** Ein Klick auf die Karte setzt den Punkt; Stadt und Ort/Halle werden dazu
  nachgeschlagen. Ziehen verschiebt, Mausrad oder `+`/`−` zoomt.
* Stadt und Ort/Halle bleiben editierbar, bevor man mit OK übernimmt.

Jeder gewählte Ort wird gemerkt. Beim Tippen in „Stadt“ schlägt die App gemerkte Orte vor
(„Bad Nauheim – Colonel-Knight-Stadion“), auch **offline**. Ohne Internet zeigt der Dialog
statt der Karte den Hinweis „Diese Karte kann nur bei Verbindung mit dem Internet angezeigt
werden“; Stadt und Ort lassen sich dann trotzdem eintragen. Schon einmal angesehene
Kartenausschnitte kommen aus dem Cache.

**GPS:** Hat der Ort Koordinaten, schreibt die App sie beim Speichern als GPS-Position
(EXIF + XMP bzw. ins Sidecar), sichtbar im Karten-Modul von Lightroom. Nur in Bilder ohne
GPS: Hat die Kamera selbst GPS aufgezeichnet, bleibt es unangetastet. GPS, das von einem
gemerkten Ort stammt, wird beim Wechsel des Ortes ersetzt. Der Hinweis unter „Ort“ zeigt,
was passiert. Templates speichern die Koordinaten mit (`latitude`, `longitude`).

Die Karte nutzt die Dienste der OpenStreetMap Foundation (Kacheln und Nominatim) nach
deren Nutzungsregeln: höchstens eine Suche pro Sekunde, gesucht wird erst auf Enter.
Dabei gehen der Suchtext bzw. der angeklickte Punkt an openstreetmap.org.

## Templates als Dateien

Ein Template ist eine kleine TOML-Datei, lesbar und von Hand editierbar:

```toml
# Captioner Spiel-Template (siehe docs/adr/0001-*.md)
format = "captioner-template"
version = 2
name = "DEL 2 Heimspiele"
headline = ""                     # optional fester Titel, sonst im Panel
city = "Bad Nauheim"
sublocation = "Colonel-Knight-Stadion"
state = "Hessen"
country = "Deutschland"
extra_tags = ["Eishockey", "DEL2", "Saison 2026/27"]
caption_suffix = ", {headline}, {city}, {sublocation}, {date}"
creator = "Florian Dehn"
authors_position = "Fotograf"
caption_writer = "Florian Dehn"
copyright = "© 2026 Florian Dehn"
web_statement = "https://example.org/lizenz"
source = "chuc.de"
category = "Sport"
```

Gefüllte Felder schreibt die App beim Speichern in jedes Bild; leere lassen den Wert des
Bildes stehen (z. B. Fotograf/Copyright, die die Kamera schon eingetragen hat). Heim und
Gast gibt es im Template nicht: sie stehen im Titel und ergeben sich aus den Codes in der
Beschreibung. Bundesland und Land füllt „Karte …“ beim Wählen des Ortes mit.

| Template-Feld | XMP | IPTC | EXIF |
|---|---|---|---|
| `headline` (Titel) | `photoshop:Headline`, `dc:title` | `Headline`, `ObjectName` | |
| `city` · `sublocation` | `photoshop:City` · `Iptc4xmpCore:Location` | `City` · `Sub-location` | |
| `state` · `country` | `photoshop:State` · `photoshop:Country` | `Province-State` · `Country-PrimaryLocationName` | |
| `creator` (Fotograf) | `dc:creator` | `By-line` | `Artist` |
| `authors_position` | `photoshop:AuthorsPosition` | `By-lineTitle` | |
| `caption_writer` | `photoshop:CaptionWriter` | `Writer-Editor` | |
| `copyright` | `dc:rights`, dazu `xmpRights:Marked` | `CopyrightNotice` | `Copyright` |
| `web_statement` | `xmpRights:WebStatement` | | |
| `source` | `photoshop:Source` | `Source` | |
| `category` | `photoshop:Category` | `Category` (nur bis 3 Zeichen, z. B. `SPO`) | |

Bei RAW-Dateien geht alles nur ins XMP-Sidecar. Dateien der Version 1 (mit `occasion`,
`home`, `away`) werden weiter gelesen; daraus wird der Titel, beim nächsten Speichern
schreibt die App Version 2.

Im Panel neben der Template-Auswahl (dieselben Befehle im Menü „Template“):

* **Bearbeiten …** zeigt das gewählte Template und speichert Änderungen zurück in seine Datei.
* `⋯` → **Template-Datei laden …** lädt eine solche Datei von irgendwo auf dem Rechner (oder
  die Datei aufs Fenster ziehen). Sie bleibt verknüpft: Änderungen landen wieder in genau
  dieser Datei, und sie steht beim nächsten Start wieder in der Liste. Unter der Auswahl
  steht ihr Dateiname, der volle Pfad als Tooltip.
* `⋯` → **Speichern unter …** schreibt das aktuelle Template in eine neue Datei, z. B. zum
  Weitergeben. Danach wird mit der neuen Datei gearbeitet.
* `⋯` → **Neues Template …** legt eines im Konfigurationsordner an (siehe unten).
* `⋯` → **Aus der Liste entfernen** nimmt ein Template aus der Liste. Dateien außerhalb des Konfigurationsordners
  werden dabei **nie gelöscht**, nur Templates im Konfigurationsordner (mit Rückfrage).

## Roster-Dateien

Roster kommen aus URLs, aus Dateien auf dem Rechner oder aus beidem. **„Roster-Datei
hinzufügen …"** im Panel (oder die `.txt` aufs Fenster ziehen) nimmt eine Datei dazu; in
den Einstellungen lassen sich Quellen hinzufügen, entfernen und sortieren. Bei gleichem
Code mit unterschiedlicher Ersetzung gewinnt die obere Quelle, und der Konflikt wird
angezeigt.

Format: eine Zeile pro Code, Code und Ersetzung durch **Tab**
getrennt, Abschnittsköpfe `- Team -`. Dateien dürfen UTF-8, UTF-16 oder Windows-1252
sein. Lokale Dateien werden bei jedem Laden frisch gelesen.

**Roster bearbeiten …** (Menü „Roster“ oder Panel) öffnet einen Editor für die lokalen
Roster-Dateien, mit Zeilennummern. Tabs sind blau hinterlegt, Abschnittsköpfe und Codes hervorgehoben.
Zeilen, die beim Laden ignoriert würden (Leerzeichen statt Tab, fehlende Ersetzung), und
widersprüchliche doppelte Codes sind rot markiert und unten aufgelistet; ein Klick springt
zur Zeile. `⌘F` sucht, `⌘S` speichert. Gespeichert wird in der Kodierung und mit den
Zeilenenden der Datei (wichtig für unter Windows gespeicherte Roster); fehlt ein Zeichen in
Windows-1252, bietet der Editor UTF-8 an. Danach wird der Roster neu geladen. URL-Quellen
zeigt der Editor nur an (zuletzt geladene Fassung).

## Einstellungen

`⌘,` öffnet den Dialog; gespeichert als `settings.toml` unter
`~/Library/Application Support/captioner/`. Templates liegen daneben in `templates/`.

* **Roster-Quellen:** Dateien (`Datei …`) und URLs (`URL …`), Reihenfolge mit ▲/▼.
  GitHub-Links können so eingetragen werden, wie sie im Browser stehen. Ohne Netz wird
  die zuletzt geladene Fassung einer URL benutzt.
* **Sprache:** Automatisch (Systemsprache: Deutsch, sonst Englisch), Deutsch oder English.
  Gilt nach einem Neustart.
* **Code-Trennzeichen:** Default `#`.
* **Farbmarkierungen:** Default `Red, Yellow, Green, Blue, Purple`.
  Für ein deutsches Lightroom `Rot, Gelb, Grün, Blau, Lila`.
* **XMP-Sidecars mit in den Drag legen:** an, solange Lightroom das akzeptiert.

## Übersetzungen

Die App gibt es auf Deutsch (Ausgangssprache im Code) und Englisch. Die Texte stehen in
`captioner/locale/<sprache>/LC_MESSAGES/captioner.po` (bearbeitbar, z. B. mit Poedit);
`make translations` zieht neue Texte aus dem Code, aktualisiert die Kataloge und
kompiliert sie (`.mo`, eingecheckt). Die Tests schlagen fehl, solange ein Text keine
Übersetzung hat oder Platzhalter wie `{name}` nicht übereinstimmen. Eine neue Sprache:
`pybabel init -i captioner/locale/captioner.pot -d captioner/locale -D captioner -l fr`,
übersetzen, in `captioner/i18n.py` bei `LANGUAGES` eintragen.
