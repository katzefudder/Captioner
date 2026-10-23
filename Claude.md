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
| `transfer.py` | Kopieren zwischen Ordnern: Gruppen (RAW+JPG+Sidecar), Konflikte (überspringen/umbenennen/ersetzen) |
| `keywords.py` | Gemerkte Stichwörter (`<cache>/keywords.json`) und Vorschläge fürs Tag-Feld |
| `updates.py` | Versionsvergleich und GitHub-Release-Antwort (ohne Qt); `ui/updatecheck.py` fragt ab |
| `rename.py` | Ordner umbenennen `<JJJJMMTT>_<HEIM>_<GAST>_<NNN>`: `plan()` je Bild (Gruppe) eine Nummer, `apply()` über Zwischennamen, bei Fehler zurück |
| `replace.py` | Suchen und Ersetzen über mehrere Bilder: `plan()` rechnet je Bild wie Speichern (Rohtext mit Codes, Anhang neu, Personen-Tags) |
| `undo.py` | Rückgängig/Wiederholen: Schritte mit Vorher/Nachher je Bild (Metadaten + Rohtext) |
| `previews.py` | Kacheln/Großansicht aus eingebetteten JPEGs, Plattencache |
| `exiftool.py` | `-stay_open`-Prozess, Pool pro OS-Thread, Aufräumen verwaister Prozesse |
| `files.py` | `replace_file`: `os.replace` mit Wiederholung, wenn Windows die Datei sperrt |
| `ui/viewer.py` | Großansicht mit Zoom (`ZoomView`): eingepasst/100 %/Stufen, Ankerpunkt, Begrenzung des Ausschnitts |
| `ui/resources.py`, `resources/` | Logo (`logo.svg` = Quelle) und daraus erzeugte Icons; `make icons` / `scripts/make_icons.py` |
| `ui/mapview.py` | OSM-Karte als QWidget (Kacheln, `QNetworkDiskCache`), `Geocoder` (Nominatim, 1 Anfrage/s) |
| `ui/placepicker.py` | Dialog „Ort wählen“: Suche, Klick, Offline-Hinweis; Vorschläge aus dem `PlaceBook` |
| `ui/tabs.py` | `FolderTab` (Zustand je Ordner), `FolderTabBar` (Drop auf Reiter), Konfliktdialog, `CopyWorker` |
| `ui/instance.py` | Windows: eine App je Benutzer, weitere Starts reichen Ordner per `QLocalServer` weiter |
| `ui/folderdialog.py` | „Ordner öffnen“ mit Mehrfachauswahl: macOS `NSOpenPanel` per ctypes, sonst Qt-Dialog |
| `ui/renamedialog.py` | „Bilder umbenennen“: Kürzel Heim/Gast (gemerkt in `Settings.rename_home`/`rename_away`), Datum (leer = heute); `MainWindow.rename_folder` benennt um |
| `ui/replacedialog.py` | „Suchen und Ersetzen“: Eingabe, Vorschau je Bild (vorher/nachher), abwählbar; `MainWindow.find_replace` schreibt |
| `ui/rostereditor.py` | „Roster bearbeiten“: lokale Roster-Dateien mit Prüfung (`roster.check`), Speichern über `roster.write_file` |
| `ui/about.py` | „Über Captioner“: Logo, `captioner.version()`, Link `captioner.WEBSITE_LINK` (mit `mtm_campaign`/`mtm_source`) |
| `i18n.py` | gettext: `_`, `ngettext`, `N_`, Sprache wählen (`resolve`, `setup`) |
| `ui/spelling.py` | Rechtschreibprüfung der Beschreibung über macOS `NSSpellChecker` (ctypes) |
| `ui/keymap.py` | Tastenkürzel wie in einem Workflow-Tool für die Auswahl von Fotos, je eine Tabelle macOS/Windows, Kontexte |
| `ui/filemanager.py` | Finder/Explorer: `reveal` (Datei markieren), `move_to_trash` (`QFile.moveToTrash`) |
| `ui/shortcuteditor.py` | „Tastenkürzel anpassen“: `KeyCaptureField` nimmt Kombinationen auf (≤ `keymap.MAX_KEYS` Tasten) |
| `ui/` | Hauptfenster, Galerie (Model/Delegate/View), Editor, Dialoge, Worker-Threads |

Kern (`roster`, `codes`, `geo`, `templates`, `scanner`, `metadata`, `previews`, `transfer`, `files`, `replace`, `rename`) importiert kein Qt.

## Regeln, die nicht verletzt werden dürfen

- **RAW-Dateien nie schreiben.** Alles für NEF & Co. geht ins Sidecar `<basis>.xmp`;
  ein vorhandenes Sidecar wird in seiner Schreibweise (`.XMP`) fortgeschrieben.
- **Eingebettet immer über eine Kopie** (`-o tmp`), `ImageDataHash` vorher/nachher
  vergleichen, Dateirechte übernehmen, dann `os.replace`. Nie `-overwrite_original` auf
  JPG/DNG.
- **Kein Code in die Datei.** Aufgelöst wird beim Speichern; unbekannte Codes blockieren.
- **Headline-Format** `<Anlass> - <Heim> gegen <Gast>`: `app/recognition/lib/matches.py`
  liest daraus den Spielkontext. Das Panel warnt bei abweichendem Titel, blockiert aber nicht. Personen als `-23- Name (Team)`.
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

## Tags und Titel

- Tag-Feld `TagTextEdit` schlägt aus `KeywordHistory` vor (angefangenes Wort nach dem letzten Komma).
  Gefüttert beim Speichern (nach vorn), beim Einlesen und aus Templates (nur ergänzen).
- Codes im Titel: `editor.resolve_headline()`; unbekannte blockieren wie in der Beschreibung.
  Gespeichert wird der aufgelöste Titel (kein Rohtext); das Format wird am aufgelösten geprüft.

## Updates

- `UpdateChecker` fragt `api.github.com/repos/katzefudder/Captioner/releases/latest`; automatisch nur
  gebündelt (`sys.frozen`), höchstens einmal am Tag (`Settings.last_update_check`). Ein privates
  Repository liefert 404: automatisch still, von Hand mit Hinweis. Versionen numerisch vergleichen.

## Rechtschreibung

- `NSSpellChecker` per ctypes (wie `folderdialog`); anderswo keine Prüfung. Bereiche sind UTF-16
  (wie QString): nie mit Python-Indizes mischen, `utf16_slice`/`utf16_spans` benutzen.
- Nicht angestrichen: Codes und Wörter aus Roster-Ersetzungen (`set_known_words` in `set_roster`).
- Abgeschlossene Codes hinterlegt derselbe Highlighter: bekannt grün, unbekannt rot (`set_lookup`,
  `code_spans` in UTF-16). Die Vorschau hinterlegt Ersetzungen grün (`codes.resolve(wrap=…)` mit
  `MARK_START`/`MARK_END`, erst nach `compose` in HTML umgesetzt).
- „Ins Wörterbuch aufnehmen“ ruft `learnWord:` auf, wirkt systemweit.

## Rückgängig

- Jede Aktion, die Metadaten ändert, läuft in `with self._undoable(N_('…'))`; `_enqueue` zeichnet
  darin Vorher/Nachher auf (verschachtelt zählt der äußere Schritt, z. B. Einfügen → Speichern).
  Neue Aktionen ebenso einpacken, sonst sind sie nicht rückgängig zu machen.
- `undo.reverting` setzt `gps_changed`, wenn sich GPS ändert; mit `latitude=None` löscht der
  Writer GPS (nur so wird von Captioner gesetztes GPS wieder entfernt).
- `⌘Z` ist ein Window-Kürzel; Textfelder beanspruchen es per ShortcutOverride selbst.

## Großansicht mit Beschriftung

- Scrollflächen des Panels (`CaptionEditor.scroll`, `Viewer.caption_slot`) sind `editor.VerticalScrollArea`:
  nur senkrecht, Mindestbreite = die des Inhalts. Nie `setMinimumWidth` aufs Panel (überschreibt das),
  sonst ragt der Inhalt bei schmalem Fenster rechts heraus (unter Windows breiter als auf dem Mac).
- Das Panel scrollt (`CaptionEditor.scroll`), Bytezähler, Kopieren/Einfügen und Speichern stehen
  fest darunter (Fußzeile): sonst überlappten die Felder bei wenig Höhe bzw. Speichern war weg.
- Das `CaptionEditor` gibt es nur einmal. Es wird in `Viewer.caption_slot` umgehängt und beim
  Schließen (`finished`) bzw. Ausblenden zurück in `main_splitter` (`_move_editor`). Inhalt,
  Template und die am Panel hängenden Kürzel wandern mit.
- Viewer-Kürzel sind `WindowShortcut`. Beim Tippen lösen sie nicht aus, weil Textfelder
  druckbare Tasten ohne Cmd/Strg per `ShortcutOverride` beanspruchen; deshalb dürfen
  Viewer- und Panel-Kürzel sich nicht überschneiden (`keymap.ACTIVE_TOGETHER`).
- Panel-Kürzel (`save_next` …) sind im Hauptfenster `WidgetWithChildrenShortcut` (die Galerie belegt
  `⌘N` selbst), im Viewer `WindowShortcut`, damit `⌘N`/`⌘B` auch mit Fokus auf dem Bild wirken:
  `_editor_shortcut_context`, umgestellt in `_move_editor`. `_advance` lässt den Fokus dann auf dem Bild.
- Laden in zwei Stufen, eigene Threads (`ThumbnailLoader.view_threads`, nie hinter Kacheln):
  `previews.render_view` dekodiert erst per JPEG-Draft auf `display_edge` (Bildschirmkante in
  Pixeln), dann voll. Das `QImage` trägt `stage` und `full_size` als Text; `ZoomView` rechnet immer
  in Pixeln des Originals (`image_size()`), damit 100 % stimmt und der Wechsel nicht springt.
  Nachbarn (`_viewer_neighbours`) werden vorgeladen; Cache `view_images` nach Bytes, aktuelles nie verdrängt.
- `ZoomView` hat `StrongFocus` und bekommt beim Öffnen den Fokus, sonst landeten Ziffern im Panel.
- `select_only` zeigt das Bild auch in der offenen Großansicht (Cmd+N/B aus dem Panel).

## Tabs und Kopieren

- Ordner-Zustand (`folder`, `all_items`, `filtered`, `selected_keys`, `model`, `view`, …)
  liegt in `FolderTab`; `MainWindow` reicht diese Namen per Property an den aktiven Tab
  durch (`_tab_attribute`). Scan-Signale gehen an den Tab des sendenden Workers
  (`_scanning_tab`), nie an den aktiven.
- `open_folders()` ist der Einstieg für Dialog, Drop und Kommandozeile: ein Ordner ohne eigene
  Bilder wird über `scanner.image_folders()` in seine Bild-Unterordner aufgelöst (Karte →
  `DCIM/100…`), außer bei `Settings.recursive`. Mehr als `MANY_FOLDERS` nur nach Rückfrage.
- Reiter (`FolderTabs.bar`) laufen oben über die ganze Fensterbreite, die Galerien liegen im
  `FolderTabs.stack` darunter; `FolderTabs` bietet die nötige `QTabWidget`-API.
- Kontextmenü am Reiter (`FolderTabBar.contextMenuEvent` → `close_requested` → `close_tabs`): dieser,
  andere, alle; Schließen über die Widgets, weil sich Indizes verschieben. Doppelklick neben die
  Kacheln (`GalleryView.background_double_clicked`) öffnet ohne Ordner den Dialog wie `⌘O`.
- Offene Tabs: `Settings.open_tabs`/`active_tab`, gepflegt von `_remember_tabs` (Öffnen, Schließen,
  Wechseln, Verschieben), beim Start `_restore_tabs` (fehlende Ordner fallen weg).
- Filter: Suche (`scanner.matches_text`), Kamera (Modell + Seriennummer aus der RAW bzw. dem
  Hauptbild, `scanner.camera_labels`), Uhrzeit (`scanner.time_of_day`); Combo-Daten als Text
  (`camera_key`), Tupel vergleicht Qt in `findData` nicht zuverlässig.
- Keine Seiten: die Galerie zeigt alle gefilterten Bilder. `GalleryModel.set_items` baut nur neu
  auf, wenn sich die Liste ändert (Reset springt nach oben); Kacheln lädt `_request_thumbnails` für
  den sichtbaren Bereich (`GalleryView.visible_rows`, aus dem Raster gerechnet) plus je einen
  Bildschirm davor/danach, angestoßen von `visible_changed` (Scrollen, Größe, Reset).
- Kachelgröße: Regler in der Statusleiste → `Settings.thumbnail_size` (Breite), `gallery.tile_size`
  rechnet Höhe und Bildhöhe. `GalleryView.set_tile_width` muss `setUniformItemSizes` aus/an
  schalten, sonst behält Qt die alte Größe. Vorschauen haben `previews.TILE_SIZE` = 512 px;
  `ThumbnailLoader` begrenzt nach Bytes (`MEMORY_BYTES`) und verwirft nie `wanted`.
- Kontextmenü der Kacheln: `GalleryView.contextMenuEvent` passt die Auswahl an (Finder-Art) und
  meldet `context_menu_requested`; `MainWindow.gallery_menu` baut das Menü aus denselben Methoden
  wie die Kürzel (Kürzeltext nach `\t` aus der Keymap, kein eigenes `QAction`-Kürzel).
- Papierkorb (`trash_selected`): nur nach Rückfrage, erst `writer.flush`, dann alle Dateien des
  Bildes einzeln (`filemanager.move_to_trash`, nie endgültig löschen). Gelöschte Items fliegen aus
  dem Tab und per `UndoStack.forget` aus Rückgängig; schlägt eine Datei fehl, wird neu eingelesen.
  Tests ersetzen `move_to_trash`/`reveal` immer (sonst landen Testdateien im echten Papierkorb).
- Galerie-Kürzel hängen am `FolderTabs.stack` (gelten in jedem Tab), nicht an einer Galerie.
- Ordner-Dialog: Qts nativer macOS-Dialog kann für Ordner nur Einzelauswahl.
  `folderdialog.choose_folders` ruft deshalb `NSOpenPanel` direkt über die Objective-C-Laufzeit
  (ctypes, jede Nachricht mit exakter Signatur, arm64); Rückfall: Qt-Dialog mit `ExtendedSelection`.
- Finder → App: Ordner aufs Dock-Symbol bzw. „Öffnen mit“ kommen als `QFileOpenEvent`
  (`main_window.OpenRequests`, vor dem Fenster installiert, sammelt 250 ms) und gehen an
  `open_paths()`. Dafür `CFBundleDocumentTypes` (`public.folder`, `public.volume`) in der Spec.
- **Kopieren, nie verschieben.** Drop auf Reiter oder Galerie eines anderen Tabs kopiert die
  beim Drag-Start gemerkten Items (`_drag_items`, nach `build_drag_mime`, also nach
  `writer.flush()`), immer mit Sidecar. Über `.<name>.captioner-part` + `os.replace`.
- Umbenennen (`rename_folder`, Menü Ablage, Windows „Datei“): alle Items des Tabs in Scan-Reihenfolge
  (Aufnahmezeit), erst nach Scan-Ende und `writer.flush()`. Fremde Datei mit Zielname → nichts
  passiert. Danach `raw_captions.move`, `undo_stack.forget`, alle Tabs desselben Ordners neu einlesen.
- Konflikte werden vor dem Kopieren im UI-Thread entschieden, kopiert wird im `CopyWorker`;
  danach liest der Ziel-Tab neu ein.

## Templates und Roster als Dateien

- Template-Format: TOML mit `format = "captioner-template"` und `version` (derzeit 2). Dateien
  ohne `format` sind gültig; fremdes `format`, neuere `version` oder falsche Typen →
  `TemplateError`. `path` wird nie serialisiert. Version 1 hatte `occasion`/`home`/`away`:
  `_upgrade_v1` macht daraus `headline` (nur wenn alle drei da sind).
- Kein Heim/Gast im Template: `headline` ist ein optionaler fester Titel, `teams` kommt per
  `parse_headline` daraus. Ohne Titel kommt er aus dem Panel und `apply_template` lässt den
  Titel des Bildes stehen.
- Ort/Rechte (`templates.FIXED_FIELDS`: state, country, country_code, creator, contact_email,
  authors_position, credit, caption_writer, copyright, web_statement, source, category, instructions) schreibt das Template beim Speichern,
  Einfügen und Anwenden in jedes Bild, aber nur gefüllte (`fixed_values()`). Zuordnung zu
  XMP/IPTC/EXIF in `metadata.RIGHTS_TAGS`; beim Schreiben einzeilig (`_rights_value`;
  Hinweise sind im Dialog mehrzeilig (`MultiLineField`), ihre Zeilen werden mit „ · “ verbunden, geprüft wird diese Länge). Gelesen werden sie aus **allen** Dateien eines
  Bildes (wie GPS), damit Kamera-Artist/Copyright beim Speichern nicht verloren gehen.
- `category` (photoshop:Category): IPTC-IIM `Category` hat nur 3 Zeichen; Längeres steht nur
  im XMP, das IIM-Feld wird dann geleert statt abgeschnitten. Ohne Titel im Template übernimmt ein unbeschriftetes Bild den
  zuletzt gespeicherten (`last_headline`); Code-Vorschläge nehmen die Teams dann aus dem
  Titel (`templates.parse_headline`, gleiches Muster wie `matches.py`).
- Anhang (`caption_suffix`): Platzhalter = `templates.SUFFIX_FIELDS` (Titel, Stadt, Ort + `FIXED_FIELDS`)
  und `{date}` (`MatchTemplate.date` als fester Text, sonst Aufnahmedatum; `date_mismatch` → Hinweis
  `date_hint` im Panel). Ort/Rechte setzen Aufrufer über `template.field_values(item.meta)` ein (Template,
  sonst Wert des Bildes), überall gleich: Speichern, Template anwenden, Vorschau, `_strip_suffix`.
  Farben/Legende im Dialog: `dialogs.SUFFIX_PLACEHOLDERS` (Feld-Widgets heißen wie die Platzhalter).
- „Template aus Foto erzeugen“ (`MainWindow.template_from_photo` → `templates.from_metadata`): Felder
  wie im Bild, Zusatz-Tags ohne Personen (`codes.persons_in` + `codes.person_names_in`), Teams und
  Stadt; Anhang per `templates.derive_suffix` (von hinten Komma-Segmente, die genau einem Wert
  entsprechen; leeres Segment nach `{city}` = `{sublocation}`). Dialog mit `path=''`: erst OK speichert.
- „Neues Template aus diesem“ (`MainWindow.copy_template`): Kopie speichern, wählen, `edit_template`
  öffnen; Abbrechen löscht die Kopie wieder. Neue Templates überschreiben nie ein gleichnamiges
  (`TemplateStore._free_path` → `name-2.toml`).
- Templates werden über ihren **Pfad** identifiziert (`Settings.last_template`), nicht
  über den Namen. Externe Dateien stehen in `Settings.template_files`, werden beim
  Bearbeiten in dieselbe Datei zurückgeschrieben und **nie gelöscht**; `TemplateStore.delete`
  löscht nur im Konfigurationsverzeichnis.
- Roster-Dateien: `roster.decode()` erkennt UTF-16 (BOM), UTF-8 (auch mit BOM) und fällt
  auf Windows-1252 zurück. Eine lokale Datei ohne einen einzigen Code gilt als Fehler.
- Roster-Editor: `roster.read_file` merkt sich Kodierung (inkl. BOM) und Zeilenenden,
  `write_file` schreibt genau so zurück (Zwischendatei + replace). Speichern einer Datei ohne
  Code wird abgelehnt; außerhalb geänderte Dateien nur nach Rückfrage überschreiben.
  `roster.check` spiegelt `parse`: was dort ignoriert würde, ist ein Problem. Schriftgröße per
  Regler (`Settings.roster_font_size`, 0 = System), Tab-Abstand und Nummernbreite wachsen mit.

## Übersetzungen (i18n)

- gettext, `captioner/i18n.py`: Ausgangssprache **Deutsch** im Code, Katalog
  `captioner/locale/en/LC_MESSAGES/captioner.po` (+ `.mo`, eingecheckt, gebündelt).
- Jeder sichtbare Text in `_()`; mit Werten `_('… {name} …').format(name=…)` (nie f-Strings in
  `_()`, `test_i18n` prüft das per AST); Mengen mit `ngettext`. Texte auf Modulebene (Keymap-
  Labels, Filterlisten, `metadata.LABELS`, `geo.ATTRIBUTION`, Roster-`origin`) mit `N_()` markieren
  und erst bei der Anzeige `_()`: beim Import ist die Sprache noch nicht gesetzt.
- Werte, die im Code verglichen werden (Roster-`origin`), bleiben deutsche Schlüssel.
- Neue/geänderte Texte: `make translations`, dann `.po` übersetzen, nochmal `make translations`.
  `test_i18n` scheitert bei fehlender Übersetzung, abweichenden Platzhaltern, veralteter `.mo`.
- „% s“ im Text hält Babel für einen C-Platzhalter: Prozentzeichen nicht vor Buchstaben.
- Sprache: `Settings.language` ('' = System via `QLocale.system().uiLanguages()`), gesetzt in
  `run()` vor dem Hauptfenster; Qt-eigene Texte (qtbase) in derselben Sprache. Tests laufen deutsch.
- Im Titel-Format bleibt „gegen“ auch auf Englisch: die Personenerkennung liest genau das.

## Tastenkürzel

- Menüleiste statt Werkzeugleiste (`_build_menus`; macOS: oben am Bildschirm, About/
  Preferences/Quit per `MenuRole` im App-Menü). Menüpunkte zu Keymap-Befehlen bekommen **kein**
  eigenes Kürzel, sonst Doppelbelegung (`test_menus_replace_the_toolbar` prüft das).
- `captioner.version()`: gebündelt aus `Info.plist` (Release-Version), sonst Paket-Metadaten.

- Einzige Quelle ist `ui/keymap.py`. Daraus entstehen
  die `QShortcut`s, die Kürzel der Menüpunkte (Kontext `menu`, `_menu_actions`) und die
  F1-Übersicht; nie Kürzel anderswo fest verdrahten.
- Anpassbar: `keymap.DEFAULTS` ist die Standardbelegung, `Settings.shortcuts` hält nur Abweichungen
  (`keymap.overrides`), `keymap.apply` macht sie wirksam (`BINDINGS`/`BY_COMMAND` neu, also immer
  über `keymap.…` bzw. `keys()` lesen, nie Kopien halten). `MainWindow._bind` merkt sich Handler,
  `_rebind_shortcuts` legt nach dem Dialog alle `QShortcut`s neu an (auch die der Großansicht) und
  aktualisiert die Texte im Panel (`CaptionEditor.update_shortcut_texts`). Doppelbelegung prüft
  `keymap.clashes` über `keymap.ACTIVE_TOGETHER`; der Dialog entfernt die Taste beim anderen Befehl.
- Aufnahme (`KeyCaptureField`): das Feld beansprucht alle Tasten (auch Esc, Tab, Enter), die Knöpfe
  im Aufnahme-Dialog nur per Maus. Shift bei Zeichen, die Shift brauchen (`*`, `+`), fällt weg.
- Qt-Schreibweise: auf macOS ist `Ctrl` = ⌘, `Meta` = Control, `Alt` = Option.
- Kontexte: `gallery` (nur bei Fokus auf der Galerie, damit `T`, `I`, `+`, `-` beim Tippen
  nicht auslösen), `editor`, `window`, `viewer`. Zwei gleichzeitig aktive gleiche Kürzel
  löst Qt gar nicht aus; `tests/test_shortcuts.py::test_no_ambiguous_shortcuts` prüft das
  für beide Plattform-Tabellen.
- Farbklassen auf `1`–`8` ohne Modifier (`0` entfernt), in Galerie und Großansicht; keine
  Einstellung dafür. Sterne auf `⌘1`–`⌘5` bzw. `Strg+1`–`5` (`⌘0`/`Strg+0` entfernt).
- Farbklasse 1–8 → `XMP-photomech:ColorClass` + `xmp:Label` aus `Settings.labels`; Tag →
  `XMP-photomech:Tagged` (`Yes`/`No`). Lightroom liest nur das Label.

## Anleitung

- Quelle `docs/manual/anleitung.html` + `anleitung.css` (Druck-CSS für WeasyPrint), Ergebnis
  `docs/Captioner-Anleitung.pdf` (eingecheckt): `make manual`. Für Anwender geschrieben (du-Form,
  kein Bauen/Paketieren). Screenshots in `docs/manual/img/` erzeugt `make manual-screenshots`
  offscreen aus der echten App (`scripts/manual_screenshots.py`: Beispielbilder, Roster mit
  erfundenen Namen, Template, eigenes `CAPTIONER_HOME`). Neue Funktion mit sichtbarer Bedienung →
  Anleitung mitziehen.
- Mitgeliefert: beide Specs bündeln das PDF nach `docs/`, `captioner.manual_path()` findet es (Bundle
  bzw. Quellbaum), *Hilfe → Anleitung (PDF)* öffnet es. Dazu liegt es als `Anleitung.pdf` im DMG und
  im Windows-Startmenü; `verify` beider Paket-Skripte prüft, dass es im Bundle ist.

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
- Release-Workflow `.github/workflows/release.yml`: Jobs `version`, `macos` (`macos-26`),
  `windows` (`windows-latest`), `release` (nur Push/Dispatch auf `main`; PRs bauen und
  testen nur). Version `<major>.<minor>` aus `pyproject.toml` + `github.run_number`, über
  `CAPTIONER_VERSION` an beide Specs; `scripts/set_version.py` trägt sie in den Build-Jobs vor
  `poetry install` auch in deren `pyproject.toml` ein (nur Arbeitskopie, nie zurück ins Repo). Lädt DMG, PKG und `setup.exe` als Release `v<version>` hoch.
  Release-Notizen: Abschnitt `## <major>.<minor>` aus `CHANGELOG.md` (awk im Job `release`),
  dahinter Installationshinweise und `--generate-notes`. Neue Minor-Version: `pyproject.toml`
  hochsetzen und den Abschnitt in `CHANGELOG.md` anlegen.
- Dependabot (`.github/dependabot.yml`): montags pip (Poetry) und Actions; kleine Updates
  gruppiert, PySide6/shiboken6/PyInstaller einzeln (Mindest-macOS, `UNUSED`). ExifTool deckt
  Dependabot nicht ab: Version/Prüfsumme im `Makefile` und in `scripts/package_windows.py`.

## Windows (x64)

- Gebaut und getestet nur in der Action (`windows-latest`); lokal gibt es kein Windows.
  Tastenkürzel der Windows-Tabelle lassen sich auf dem Mac prüfen, indem man vor den Tests
  `keymap.MAC`, `BINDINGS` und `BY_COMMAND` auf `_bindings(False)` umstellt. Tests, die
  Kürzel drücken, lesen die Tasten aus `keymap.keys()` oder fragen `keymap.MAC`.
- ExifTool: `CREATE_NO_WINDOW`, Prozesse in einem Job Object (`KILL_ON_JOB_CLOSE`) statt
  `reap_orphans()`. Pipes werden von je einem Lese-Thread gelesen (`_pump`), weil `selectors`
  unter Windows keine Pipes kann; das gilt für alle Plattformen.
- Gebündelt: offizielles `exiftool-<ver>_64.zip`, `exiftool(-k).exe` → `exiftool.exe` +
  `exiftool_files/`. Version/Prüfsumme in `scripts/package_windows.py` (Mac: `Makefile`).
- Ersetzen von Dateien immer über `files.replace_file` (Sperren durch Explorer/Virenscanner).
- `captioner/VERSION` im Bundle liefert `version()` (keine `Info.plist`).
- Explorer übergibt `"E:\"` als `E:"` (Backslash escapt das Anführungszeichen):
  `main_window.command_line_path` repariert das.
- Reiter: Laufwerk ≠ Systemlaufwerk → Laufwerksbezeichnung (`tabs.volume_label`, `QStorageInfo`).
- Installer: Inno Setup, `packaging/captioner.iss`; `AppId` nie ändern (Updates).

## Lizenz

- GPL-3.0-or-later (`LICENSE`, `pyproject.toml`). Fremdlizenzen in `licenses/` (Übersicht
  `licenses/README.md`), von beiden Specs gebündelt. Neue gebündelte Abhängigkeit → Lizenztext
  dort ergänzen. Das „.dng“ im Logo stammt aus Apples American Typewriter (Pfade); Schriftlizenz
  ungeklärt, ggf. durch eine freie Schrift ersetzen.

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
make install && make test            # 258 Tests, ExifTool nötig (brew install exiftool)
make run FOLDER=~/Pictures/2026/03-01
CAPTIONER_HOME=/tmp/cap make run     # ohne die echten Einstellungen/Caches
make bundle                          # dist/Captioner.app mit ExifTool 13.59 (arm64)
make installer                       # dazu DMG + PKG in dist/
```

Mit echten Fotos nur auf **Kopien** testen. `tests/test_gui.py` läuft offscreen
(`QT_QPA_PLATFORM=offscreen`).

## Offen

Siehe `BACKLOG.md` (Fehler, Funktionen, Windows-Version, Signieren, Lightroom-Akzeptanztest).
