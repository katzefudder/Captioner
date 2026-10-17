# Änderungen

Je Version `<major>.<minor>` ein Abschnitt. Der Release-Workflow stellt ihn über die
Release-Notizen auf GitHub (die Laufnummer dahinter, z. B. 0.2.23, zählt die Builds).

## 0.2

### Neu

- **Neues Template aus diesem …** (unter `⋯` und im Menü Template): übernimmt alle Werte des
  gewählten Templates in eine Kopie, wechselt dorthin und öffnet sie zum Bearbeiten. Abbrechen
  verwirft die Kopie.
- **Template-Ordner im Finder öffnen** (Windows: im Explorer), unter `⋯` und im Menü Template.
- **Platzhalter für alle Felder im Anhang:** neben `{headline}`, `{city}`, `{sublocation}` und
  `{date}` jetzt auch `{state}`, `{country}`, `{creator}`, `{authors_position}`,
  `{caption_writer}`, `{copyright}`, `{web_statement}`, `{source}` und `{category}`. Ist ein
  Feld im Template leer, wird der Wert des Bildes eingesetzt.
- **Datum im Template:** ein fester Text für `{date}`, z. B. um ein Template schon vor dem
  Spieltag vorzubereiten. Leer bleibt es beim Aufnahmedatum. Passt das feste Datum nicht zum
  Bild, zeigt das Beschriftungs-Panel einen orangen Hinweis.
- **Template-Dialog zeigt, was angehängt wird:** farbige Platzhalter zum Anklicken, ein Punkt
  an jedem Feld, dessen Wert im Anhang landet, und ein „Ergebnis“ mit dem fertigen Anhang. Steht
  der Cursor im Anhang auf einem Platzhalter, wird das zugehörige Feld markiert. Auch im Dark Mode
  gut lesbar.
- **Großansicht per Doppelklick** auf eine Kachel (wie mit der Leertaste).
- **Galerie ohne Seiten:** alle Bilder eines Ordners in einer scrollbaren Galerie; Vorschauen
  werden beim Scrollen nachgeladen. Die Einstellung „Bilder pro Seite“ und die Seiten-Kürzel
  entfallen, `Bild↑`/`Bild↓` blättern jetzt wie gewohnt in der Galerie.
- **Beschriftungs-Panel kompakter:** Hinweise direkt unter ihren Feldern statt in eigenen Zeilen,
  Template-Datei im Tooltip, Roster in einer Zeile mit Menü (Bearbeiten, Neu laden, Datei
  hinzufügen; Probleme bleiben sichtbar), Bytezähler neben Kopieren/Einfügen.
- **Tastenkürzel anpassen** (Ablage): jedes Kürzel, auch die der Menüpunkte (Ordner öffnen,
  Neu einlesen, Einstellungen, Beenden), lässt sich ändern, ergänzen oder entfernen. Das neue
  Kürzel wird über die Tastatur aufgenommen, höchstens drei Tasten zusammen; schon belegte
  Kombinationen werden beim anderen Befehl entfernt. Wirkt sofort, ohne Neustart.
- **Kontextmenü an den Reitern:** Tab schließen, Andere Tabs schließen, Alle Tabs schließen
  (wie Finder, Safari, Explorer).
- **Doppelklick in die leere Galerie** (kein Ordner offen) öffnet den Ordner-Dialog wie `⌘O`.
- **Suchen und Ersetzen** (Bearbeiten, `⌘⌥F`) in Beschreibung, Titel, Tags, Stadt und Ort der
  Auswahl, mit Vorschau je Bild. Codes lassen sich tauschen (`#bn9#` → `#bn10#`), Personen-Tags
  und der Anhang des Templates passen sich an; ein Schritt für `⌘Z`.
- **Codes farbig:** In der Beschreibung sind bekannte Codes grün und unbekannte rot hinterlegt; die
  Vorschau darunter hinterlegt die eingesetzten Namen grün.
- **Hinweise im Template** (IPTC „Special Instructions“, Lightroom: Anweisungen): z. B.
  Kontaktdaten oder Kontoverbindung, geht wie Copyright & Co. in jedes Bild; auch als
  Platzhalter `{instructions}` im Anhang.
- **Großansicht deutlich schneller:** zuerst in Bildschirmauflösung (eingepasst sofort scharf),
  die volle Auflösung für 100 % kommt im Hintergrund nach. Nächstes und voriges Bild werden
  vorgeladen; die Großansicht wartet nicht mehr, während die Galerie Vorschauen erzeugt.
- **Größe der Vorschaubilder** per Regler in der Statusleiste (wird gemerkt). Die Vorschauen
  sind dafür schärfer (512 statt 320 px); beim ersten Öffnen eines Ordners werden sie neu erzeugt.
- **Roster-Editor:** Schriftgröße per Regler (wird gemerkt), Zeilennummern mit mehr Kontrast.
- **Tasten getauscht:** Ziffern `1`–`8` setzen die Farbklasse (`0` entfernt sie), `⌘1`–`⌘5`
  (Windows: `Strg+1`–`5`) die Sterne (`⌘0` entfernt sie).
- **Farbklasse als Rahmen ums Foto** in Galerie und Großansicht (statt des schmalen Streifens
  oben an der Kachel).
- **Knöpfe „Kopieren“ und „Einfügen“** im Beschriftungs-Panel, wie `⌘⇧C`/`⌘⇧V`.
- **„Inhalte überschreiben“** neben „Template auf Auswahl anwenden“ (voreingestellt an):
  setzt Titel, Stadt, Ort und Tags genau auf das Template und leert die Beschreibung. Ohne Haken
  bleibt die Beschreibung wie bisher erhalten.
- Lizenz: GPL-3.0 oder neuer; die Lizenztexte der mitgelieferten Software liegen bei.

### Behoben

- Bei wenig Höhe rutschte im Beschriftungs-Panel die Vorschau ins Beschreibungsfeld. Das Panel
  scrollt jetzt; Speichern, Kopieren und Einfügen stehen fest darunter.
- Zeilenumbrüche in Ort-/Rechte-Feldern (aus einer Template-Datei oder einem Bild) zerlegten den
  Aufruf von ExifTool; sie werden jetzt zu Leerzeichen.
- Ein unbeschriftetes Bild zeigte im Panel die Beschreibung des zuletzt gespeicherten Bildes;
  das Feld ist jetzt leer.
- „Template-Datei laden …“ und „Speichern unter …“ im Menü `⋯` taten nichts.
- Ein neues Template mit dem Namen eines vorhandenen überschrieb dessen Datei; es wird jetzt
  daneben gespeichert (`name-2.toml`).
