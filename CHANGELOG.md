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
- **Knöpfe „Kopieren“ und „Einfügen“** im Beschriftungs-Panel, wie `⌘⇧C`/`⌘⇧V`.
- **„Inhalte überschreiben“** neben „Template auf Auswahl anwenden“ (voreingestellt an):
  setzt Titel, Stadt, Ort und Tags genau auf das Template und leert die Beschreibung. Ohne Haken
  bleibt die Beschreibung wie bisher erhalten.
- Lizenz: GPL-3.0 oder neuer; die Lizenztexte der mitgelieferten Software liegen bei.

### Behoben

- Ein unbeschriftetes Bild zeigte im Panel die Beschreibung des zuletzt gespeicherten Bildes;
  das Feld ist jetzt leer.
- „Template-Datei laden …“ und „Speichern unter …“ im Menü `⋯` taten nichts.
- Ein neues Template mit dem Namen eines vorhandenen überschrieb dessen Datei; es wird jetzt
  daneben gespeichert (`name-2.toml`).
