# Backlog

Offene Vorhaben, grob nach Nutzen für den Spieltag sortiert. Erledigtes fliegt raus
(steht dann in der Git-Historie und in `readme.md`).

## Fehler

### Doppelter Anhang nach Template-Wechsel
Ein Bild, das mit Template A beschriftet wurde, trägt dessen Anhang in der Beschreibung
(„…, Butzbach, Innenstadt, 10.10.26“). Wird es mit Template B neu gespeichert, hängt B seinen
Anhang dahinter. Ursache: `CaptionEditor._strip_suffix` entfernt nur den Anhang des gerade
gewählten Templates. Idee: den Rohtext mit Codes (`RawCaptionStore`) bevorzugen, sonst
Anhänge aller bekannten Templates (und das Datumsmuster am Ende) erkennen.

## Funktionen

### Zwei Kameras zeitlich zusammenführen
Bei zwei Bodies (zwei Karten) die Bilder in Aufnahme-Reihenfolge sehen statt pro Karte:
eine Ansicht über mehrere Tabs, sortiert nach `taken_at`, dazu eine **Zeitkorrektur pro
Kamera** (Modell + Seriennummer, siehe Kamera-Filter), wenn die Uhren auseinanderliegen.
Die Korrektur entweder nur in der Ansicht oder auf Wunsch in `DateTimeOriginal` schreiben
(RAW: nur Sidecar).

### Ingest von der Karte
Kopieren mit Umbenennen nach Muster (z. B. `{datum}_{template}_{nummer}`), Zielordner nach
Datum, wahlweise auf zwei Ziele (Arbeit + Sicherung) mit Prüfsummen-Vergleich, Karte danach
als „übernommen“ markieren. Baut auf `transfer.py` auf (Gruppen, Zwischendatei, Konflikte).

### Ausspielen an Redaktion/Agentur
Verkleinerte JPEGs mit allen Metadaten exportieren (Größe/Qualität einstellbar) und per
FTP/SFTP hochladen, direkt aus der Auswahl. Zugangsdaten im Schlüsselbund, nicht in
`settings.toml`. Warteschlange mit Wiederholung, wenn das Netz in der Halle wegbricht.

### Vergleichsansicht und Serien
2 oder 4 Bilder nebeneinander (gleicher Zoom, gemeinsam verschieben) zum Auswählen aus
Serien; Serien automatisch gruppieren (Aufnahmen weniger als ~0,5 s auseinander) und in der
Galerie zusammenklappen.

### Content Credentials: Signieren und Vertrauensliste (ADR 0002, Schritte 5–6)
Lesen, Warnen und Anzeigen stehen. Offen: Signieren mit eigenem Zertifikat (Schlüssel im
Schlüsselbund, TSA-URL, zuerst beim Ausspielen; neu signieren mit dem Original als
`parentOf`-Zutat), C2PA-Vertrauensliste bündeln (erst dann „vertrauenswürdig“/grün).
Windows: Größe der DLL im Bundle prüfen. Lizenzen der Rust-Crates in `libc2pa_c` ergänzen.

## Verteilen

### Signieren und Notarisieren (macOS)
Apple Developer Program, Zertifikate *Developer ID Application* und *Installer*. Der Weg ist
in `readme.md` („Signieren und Notarisieren“) und `scripts/package_macos.py notarize`
beschrieben, aber ungetestet. In der GitHub Action dann über Secrets (Zertifikat als
base64-p12, `notarytool` mit App-spezifischem Passwort oder API-Key).

### Windows-Version: Rest
Gebaut und getestet wird sie in der GitHub Action (`windows-latest`), siehe `readme.md`.
Offen:
- Test auf echtem Windows mit Lightroom Classic (ADR 0001, Punkt 7): Sidecars, Drag & Drop
  in Lightroom, Kontextmenü „Mit Captioner öffnen“, Karte mit Laufwerksbezeichnung im Reiter.
- Code-Signing (Azure Trusted Signing oder OV-Zertifikat), sonst SmartScreen-Warnung.
- Rechtschreibprüfung unter Windows (Spell Checking API per COM, ca. ½–1 Tag).
- Nach vorn holen beim Weiterreichen an die laufende App: Windows verweigert
  `activateWindow` fremden Prozessen oft (blinkt nur in der Taskleiste);
  ggf. `AllowSetForegroundWindow` im zweiten Prozess.

## Prüfen

### Lightroom-Akzeptanztest (ADR 0001, Punkt 7)
Sidecars beim Kopier-Import, `.xmp`-URLs im Drop, GPS und Rechte-Felder in Lightroom sichtbar.
