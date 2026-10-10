# Claude.md – app/captioner

Desktop-Werkzeug (Python 3.11, PySide6) zum Sichten, Bewerten und Beschriften vor dem
Lightroom-Import. Warum so und nicht anders: `docs/adr/0001-bildbeschriftung-mit-code-replacement.md`.
Bedienung: `readme.md`.

## Aufbau

| Modul | Rolle |
|---|---|
| `config.py` | `Settings` (TOML), Konfig-/Cache-Verzeichnisse. `CAPTIONER_HOME` lenkt beide um. |
| `roster.py` | Roster-Format parsen, Quellen laden (URL/Datei), Cache + letzte gute Version, Konflikte |
| `geo.py` | `Place`, `PlaceBook` (gemerkte Orte = einzige Quelle für Koordinaten), GPS-Regel `apply_gps`, Nominatim-URLs/-Auswertung, Kachel-Mathematik |
| `codes.py` | `#code#` auflösen, unbekannte Codes, Personennamen aus Ersetzungen |
| `templates.py` | `MatchTemplate`: Headline, Tags, Anhang an die Beschreibung; Dateiformat (`load_file`/`save_file`), `TemplateStore` |
| `scanner.py` | Ordner → `Item` (RAW+JPG-Paar, vorhandenes Sidecar), `Metadata` |
| `metadata.py` | Lesen (Sidecar > eingebettet > RAW) und Schreiben (Sidecar bzw. eingebettet) |
| `details.py` | EXIF/IPTC fürs Info-Panel: `read()` (Kamera aus RAW, IPTC Sidecar > eingebettet), `sections()` formatiert |
| `previews.py` | Kacheln/Großansicht aus eingebetteten JPEGs, Plattencache |
| `exiftool.py` | `-stay_open`-Prozess, Pool pro OS-Thread, Aufräumen verwaister Prozesse |
| `ui/viewer.py` | Großansicht mit Zoom (`ZoomView`): eingepasst/100 %/Stufen, Ankerpunkt, Begrenzung des Ausschnitts |
| `ui/resources.py`, `resources/` | Logo (`logo.svg` = Quelle) und daraus erzeugte Icons; `make icons` / `scripts/make_icons.py` |
| `ui/mapview.py` | OSM-Karte als QWidget (Kacheln, `QNetworkDiskCache`), `Geocoder` (Nominatim, 1 Anfrage/s) |
| `ui/placepicker.py` | Dialog „Ort wählen“: Suche, Klick, Offline-Hinweis; Vorschläge aus dem `PlaceBook` |
| `ui/keymap.py` | Tastenkürzel wie in einem Workflow-Tool für die Auswahl von Fotos, je eine Tabelle macOS/Windows, Kontexte |
| `ui/` | Hauptfenster, Galerie (Model/Delegate/View), Editor, Dialoge, Worker-Threads |

Kern (`roster`, `codes`, `geo`, `templates`, `scanner`, `metadata`, `previews`) importiert kein Qt.

## Regeln, die nicht verletzt werden dürfen

- **RAW-Dateien nie schreiben.** Alles für NEF & Co. geht ins Sidecar `<basis>.xmp`;
  ein vorhandenes Sidecar wird in seiner Schreibweise (`.XMP`) fortgeschrieben.
- **Eingebettet immer über eine Kopie** (`-o tmp`), `ImageDataHash` vorher/nachher
  vergleichen, Dateirechte übernehmen, dann `os.replace`. Nie `-overwrite_original` auf
  JPG/DNG.
- **Kein Code in die Datei.** Aufgelöst wird beim Speichern; unbekannte Codes blockieren.
- **Headline-Format** `<Anlass> - <Heim> gegen <Gast>`: `app/recognition/lib/matches.py`
  liest daraus den Spielkontext. Personen als `-23- Name (Team)`.
- **Feldnamen** müssen zur IPTC-Map in `app/indexer/lib/indexer.py` passen
  (`Headline`, `ObjectName`, `Caption-Abstract`, `Keywords`, `City`, `Sub-location`).
- **Drag erst nach `writer.flush()`.** Eine bearbeitete RAW-Datei ohne Sidecar oder ein
  Bild mit Schreibfehler wird nicht gezogen.

## Orte, Karte, GPS

- **GPS nur, wo keins ist.** `geo.apply_gps` setzt Koordinaten aus dem `PlaceBook` (über
  Stadt + Ort), wenn das Bild kein GPS hat oder sein GPS selbst von einem gemerkten Ort
  stammt. Kamera-GPS nie überschreiben. Geschrieben wird GPS nur bei `Metadata.gps_changed`.
- GPS wird aus Sidecar, eingebetteter Datei **und** RAW gelesen (`-n` → Composite-Werte mit
  Vorzeichen); auch wenn die Beschriftung aus dem Sidecar kommt.
- Karte ohne WebEngine/QtLocation (beides zöge QtQuick/QML bzw. Chromium ins Bundle).
- OSM-Nutzungsregeln: `geo.USER_AGENT`, höchstens 1 Nominatim-Anfrage/s, Suche nur auf
  Enter, Kacheln mit Plattencache (`<cache>/map`), Attribution sichtbar. Tests gehen nie
  ins Netz (`tests/test_places_gui.py` lenkt beides auf einen geschlossenen Port).
- Offline: Dialog zeigt den Hinweis statt der Karte, sobald eine Kachel weder aus Netz noch
  Cache kommt; Stadt/Ort und Vorschläge funktionieren weiter.
- Templates: `latitude`/`longitude` optional, ohne Wert nicht in der Datei (TOML hat kein None).

## Templates und Roster als Dateien

- Template-Format: TOML mit `format = "captioner-template"` und `version`. Dateien ohne
  `format` (erste Version) sind gültig; fremdes `format`, neuere `version`, falsche Typen
  oder fehlendes Anlass/Heim/Gast → `TemplateError`. `path` wird nie serialisiert.
- Templates werden über ihren **Pfad** identifiziert (`Settings.last_template`), nicht
  über den Namen. Externe Dateien stehen in `Settings.template_files`, werden beim
  Bearbeiten in dieselbe Datei zurückgeschrieben und **nie gelöscht**; `TemplateStore.delete`
  löscht nur im Konfigurationsverzeichnis.
- Roster-Dateien: `roster.decode()` erkennt UTF-16 (BOM), UTF-8 (auch mit BOM) und fällt
  auf Windows-1252 zurück. Eine lokale Datei ohne einen einzigen Code gilt als Fehler.

## Tastenkürzel

- Einzige Quelle ist `ui/keymap.py`. Daraus entstehen
  die `QShortcut`s und die F1-Übersicht; nie Kürzel anderswo fest verdrahten.
- Qt-Schreibweise: auf macOS ist `Ctrl` = ⌘, `Meta` = Control, `Alt` = Option.
- Kontexte: `gallery` (nur bei Fokus auf der Galerie, damit `T`, `I`, `+`, `-` beim Tippen
  nicht auslösen), `editor`, `window`, `viewer`. Zwei gleichzeitig aktive gleiche Kürzel
  löst Qt gar nicht aus; `tests/test_shortcuts.py::test_no_ambiguous_shortcuts` prüft das
  für beide Plattform-Tabellen.
- Sterne auf `1`–`5` ohne Modifier (`0` entfernt), in Galerie und Großansicht; keine
  Einstellung dafür. Farbklassen auf `⌘1`–`⌘8` bzw. `Strg+1`–`8`.
- Farbklasse 1–8 → `XMP-photomech:ColorClass` + `xmp:Label` aus `Settings.labels`; Tag →
  `XMP-photomech:Tagged` (`Yes`/`No`). Lightroom liest nur das Label.

## Logo

- `captioner/resources/logo.svg` ist die einzige Quelle: Leinwand mit „.dng" hinter einer
  Schreibmaschine. „.dng" ist ein Pfad (American Typewriter Bold), kein `<text>`, damit das
  Logo ohne die Schrift gleich aussieht.
- Nach Änderungen `make icons`: erzeugt `logo_<n>.png`, `captioner.icns` (macOS, braucht
  `iconutil`) und `captioner.ico`. Die erzeugten Dateien sind eingecheckt; `make bundle`
  nutzt sie nur.

## Paketierung (macOS, arm64)

- `Captioner.spec` ist Quelltext (nicht mehr generiert): `target_arch='arm64'`, Info.plist,
  Signatur über `CODESIGN_IDENTITY`. `LSMinimumSystemVersion` wird aus dem höchsten `minos`
  der arm64-Slices aller gebündelten Binaries berechnet, nie von Hand setzen.
- Derzeit **macOS 26**: shiboken6 6.12 (Wheel beschriftet „macosx_14_0", Binary aber
  `minos 26.0`) und Homebrew-Python. PySide6 6.8 LTS + python.org-Python ergäben macOS 12.
- `UNUSED` in der Spec wirft das PDF-Bildformat-Plugin und die Bildschirmtastatur raus; sie
  zogen QtQuick/QtQml/QtPdf/QtVirtualKeyboard (~19 MB) mit. Nach einem PySide6-Update mit
  `otool -L` prüfen, ob neue Plugins Ähnliches tun.
- `scripts/package_macos.py`: `verify`, `dmg`, `pkg`, `notarize`. Im PKG ist
  `BundleIsRelocatable=false` Pflicht, sonst „aktualisiert" der Installer eine zufällig
  anderswo liegende Captioner.app (z. B. `dist/`) statt nach `/Applications` zu installieren.
- `pkgbuild` meldet in der Claude-Code-Sandbox `write: Permission denied`; das Paket ist
  trotzdem vollständig (Dateiliste und Signatur geprüft).
- Notarisierung ist ungetestet (kein Developer-ID-Zertifikat vorhanden).
- Release-Workflow `.github/workflows/release.yml` (Push auf `main`, `macos-26`): Version
  `<major>.<minor>` aus `pyproject.toml` + `github.run_number`, über `CAPTIONER_VERSION`
  an die Spec. Lädt DMG und PKG als Release `v<version>` hoch, ad-hoc signiert.

## Fallstricke

- **`threading.local` funktioniert im `QThreadPool` nicht**: PySide legt dort pro Aufruf
  einen neuen Python-Thread-Zustand an. Deshalb ist `ExifToolPool` nach
  `threading.get_ident()` geschlüsselt, und die Pool-Threads laufen nicht ab
  (`setExpiryTimeout(-1)`). Sonst startet jede Kachel einen Perl-Prozess.
- **ExifTool beendet sich nicht bei stdin-EOF.** Prozesse tragen `-userParam
  captioner_parent=<pid>`; `reap_orphans()` beim Start beendet die verwaisten.
- **Ausrichtung** liest `previews.render()` selbst aus der Vorschau-Datei. Kacheln werden
  angefordert, bevor der Scan `item.orientation` kennt. Ändert sich die Darstellung,
  `previews.CACHE_VERSION` erhöhen.
- **Argumente an ExifTool dürfen keine Zeilenumbrüche enthalten** (`-@ -` ist
  zeilenbasiert). Bildunterschriften werden mit `metadata.single_line()` einzeilig.
- **Mehrfachauswahl:** Die Beschreibung wird nur übernommen, wenn sie im Feld geändert
  wurde (`caption_modified`), sonst würde die des ersten Bildes alle überschreiben.
- `Item` ist `@dataclass(eq=False)`: Vergleich über Identität, sonst sind `in`/`index()`
  über tausende Items mit tiefem Feldvergleich langsam.
- **Poetry-Venv:** In einer Shell mit aktivem Indexer-Venv installiert `poetry install`
  dorthin. Das `Makefile` ruft Poetry deshalb mit `env -u VIRTUAL_ENV` auf.

## Entwicklung

```bash
make install && make test            # 118 Tests, ExifTool nötig (brew install exiftool)
make run FOLDER=~/Pictures/2026/03-01
CAPTIONER_HOME=/tmp/cap make run     # ohne die echten Einstellungen/Caches
make bundle                          # dist/Captioner.app mit ExifTool 13.59 (arm64)
make installer                       # dazu DMG + PKG in dist/
```

Mit echten Fotos nur auf **Kopien** testen. `tests/test_gui.py` läuft offscreen
(`QT_QPA_PLATFORM=offscreen`).

## Offen

- Lightroom-Akzeptanztest aus ADR 0001, Punkt 7 (Sidecars beim Kopier-Import, `.xmp` im Drop).
- Windows-Build (ExifTool als `exiftool.exe`), Signierung/Notarisierung für macOS.
- Kein Kopieren von der Karte („Ingest"), kein direkter Upload.
