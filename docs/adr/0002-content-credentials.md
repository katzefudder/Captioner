# ADR 0002: Content Credentials (C2PA) lesen, schützen, später signieren

- Status: angenommen; Lesen, Schützen und Anzeigen umgesetzt, Signieren und Vertrauensliste offen
- Datum: 2026-10-13
- Bibliothek: [c2pa-python](https://opensource.contentauthenticity.org/docs/sdk-repos/c2pa-python/) 0.38 (c2pa-rs 0.91)

## Kontext

Content Credentials (Standard C2PA) sind ein signiertes Manifest in der Bilddatei oder
daneben (`<basis>.c2pa`). Es hält fest, wer ein Bild mit welchem Gerät oder Programm
erstellt und was danach geändert wurde. Jede Bearbeitung hängt ein neues Manifest an,
das alte bleibt als Zutat (Ingredient) erhalten. So entsteht eine prüfbare Kette.
Einige Kameras signieren schon beim Auslösen (Leica, Sony, Canon). Bei Nikon wurden die
Zertifikate der Z6 III im September 2025 zurückgezogen, der Dienst ruht seitdem.
Lightroom Classic kann beim JPEG-Export eigene Credentials anhängen.

Gefragt war:

1. Content Credentials lesen und anzeigen.
2. Vorschläge für die Anzeige, auch dafür, wie sich Änderungen darstellen lassen.
3. Content Credentials an Bilder anhängen, die noch keine haben.
4. Den Fotografen als Urheber ausweisen („dieses Foto stammt von mir“), etwa über Adobe.

## Befunde aus dem Spike

Ausprobiert mit c2pa-python 0.38 auf macOS arm64. Die Tests in `tests/test_credentials.py`
halten das fest.

- **Formate:** JPEG, DNG, TIFF, HEIC, PNG und auch **NEF** und **ARW** (TIFF-basiert)
  werden gelesen. Ein Manifest als Sidecar (`.c2pa`, `manifest_data=`) lässt sich ebenfalls
  lesen und schreiben (`Builder.set_no_embed()`).
- **Prüfstatus:** `Trusted` (Zertifikat auf der Vertrauensliste), `Valid` (Signatur und
  Hashes stimmen, aber der Unterzeichner ist unbekannt, `signingCredential.untrusted`),
  `Invalid`. Mit einem eigenen Zertifikat ohne Vertrauensanker kommt höchstens `Valid` heraus.
- **Metadaten schreiben bricht das Manifest.** Nach dem Signieren eines JPGs genügte
  `exiftool -IPTC:Headline=…`, und der Status war `Invalid` (`assertion.dataHash.mismatch`).
  Der Hash deckt die ganze Datei ab, nur das Manifest selbst ist ausgenommen, also auch
  XMP und IPTC. **Das betrifft Captioner schon heute:** Ein JPG oder DNG mit Kamera-Manifest
  verliert beim ersten Speichern einer Beschriftung seine Gültigkeit, ohne dass jemand es merkt.
  Bei RAW-Dateien gilt das nicht, weil Captioner nur ins `.xmp`-Sidecar schreibt.
- **Signieren:** Das geht mit `Signer.from_info` (Zertifikatskette als PEM und privater
  Schlüssel) oder mit `Signer.from_callback`. Über den Callback kann ein Schlüssel signieren,
  der im Schlüsselbund, im Windows-Zertifikatsspeicher oder auf einem Token bleibt. Mögliche
  Algorithmen sind ES256/384/512, PS256/384/512 und Ed25519. Mit `C2paBuilderIntent.EDIT`
  wird die Quelldatei automatisch zur `parentOf`-Zutat, die Kette bleibt also erhalten.
- **Zeitstempel:** Ohne Zeitstempeldienst (TSA, `ta_url`) gilt die Signatur nur so lange
  wie das Zertifikat. Ein Zeitstempel braucht Netz, das in der Halle oft fehlt.
- **Bündelung:** Die native Bibliothek `libc2pa_c.dylib` ist auf arm64 rund 20 MB groß,
  `minos 11.1`. Sie hebt die Mindestversion von macOS also nicht an. Für Windows gibt es
  Wheels (`win_amd64`). Die mitinstallierten `requests`, `cryptography` und `toml` braucht
  nur das Build-Skript des Pakets. Sie landen nicht im Bundle. Lizenz: MIT OR Apache-2.0.
- **Adobe/Identität:** Ein öffentliches Verfahren, mit dem ein fremdes Programm im Namen
  eines Adobe-Kontos signiert, habe ich nicht gefunden. Die Bestätigung über LinkedIn
  („Verified on LinkedIn“) und verknüpfte Profile gibt es nur in Adobes App
  *Content Authenticity* (Web, Beta), angewendet auf fertige Dateien.

## Entscheidung

Content Credentials werden in Phasen eingeführt. Das Lesen kommt zuerst, das Signieren zuletzt.

1. **Lesen** (Kern, ohne Qt): `captioner/credentials.py` liest eingebettete Manifeste und
   Sidecar-Manifeste. Es prüft nur lokal (kein Abruf entfernter Manifeste, kein OCSP; Tests
   gehen nie ins Netz) und liefert Status, Fehlercodes und die Kette (`history`).
   `at_risk(item)` nennt die Dateien, deren Manifest beim Speichern bräche.
2. **Schützen:** Bevor Captioner in eine Datei mit eingebettetem Manifest schreibt, warnt
   das Panel. Ein vorhandenes Manifest wird nie stillschweigend ungültig.
3. **Anzeigen** wie unten beschrieben.
4. **Signieren** ist optional und nur mit einem eigenen Zertifikat möglich. Am meisten
   bringt es beim Ausspielen an Redaktionen (siehe `BACKLOG.md`), denn dort verlässt
   Captioners Datei das Haus unverändert.
5. **Vertrauensliste:** Die C2PA-Vertrauensliste (Wurzelzertifikate als PEM) wird gebündelt
   und mit den Releases aktualisiert. Erst damit erscheint ein Status `Trusted`.

Grenzen, die feststehen:

- **RAW-Dateien werden nie beschrieben.** Das gilt auch für Manifeste. Für NEF & Co. gibt es
  höchstens ein Sidecar `<basis>.c2pa`, und das wird nur geschrieben, wenn jemand es
  ausdrücklich will (Lightroom liest es vermutlich nicht, siehe unten).
- **Eingebettet nur über die Kopie** wie in ADR 0001: Metadaten in die Kopie schreiben,
  dann signieren, dann `files.replace_file`. Das Signieren ist der letzte Schritt, danach
  wird nichts mehr geschrieben.
- **Private Schlüssel** gehören nie in `settings.toml`, sondern in den Schlüsselbund bzw.
  den Windows-Zertifikatsspeicher.

## Vorschläge für die Anzeige

**Galerie.** Ein kleines „CR“-Abzeichen erscheint in der Ecke jeder Kachel, deren Bild
Credentials hat. Seine Farbe zeigt den Status: grün für `Trusted`, neutral für `Valid`
(„unbekannter Unterzeichner“), rot für `Invalid` bzw. `tampered` (seit dem Signieren
verändert). Dazu kommt ein Filter „Content Credentials: alle / mit / gültig / verändert“.
Gelesen wird im Scan-Worker. Ein Manifest zu lesen dauert pro Datei Millisekunden.

**Info-Panel der Großansicht** (`details.sections`). Ein neuer Abschnitt
„Content Credentials“ zeigt Status, Unterzeichner (CN) und Aussteller (O), Signierzeit,
Programm bzw. Kamera, Urheber (`CreativeWork.author`) und die Aktionen im Klartext
(„aufgenommen“, „Metadaten bearbeitet“, „zugeschnitten“, „Farbe angepasst“ …).

**Dialog „Herkunft“.** Er zeigt die Kette als senkrechte Zeitleiste, das neueste Manifest
oben. Je Schritt stehen dort Programm, Unterzeichner, Zeit, Aktionen und das Vorschaubild
aus dem Manifest. Ein Link „Bei contentcredentials.org prüfen“ öffnet nur die Seite. Die
Datei lädt der Nutzer selbst hoch, Captioner sendet nichts.

### Lassen sich Änderungen darstellen?

Teilweise. Was C2PA hergibt:

| Was | Woher | Anzeige |
|---|---|---|
| *Dass* nach dem Signieren etwas geändert wurde | `assertion.dataHash.mismatch` | roter Status, Hinweis „seit dem Signieren verändert“. **Wo** in der Datei, verrät der Hash nicht. |
| Welche Bearbeitungen deklariert wurden | `c2pa.actions` (je Schritt, mit Programm) | Zeitleiste mit Aktionen |
| Wie das Bild vorher aussah | Vorschaubilder der Zutaten bzw. des Manifests (`resource_to_stream`) | vorher/nachher nebeneinander oder per Schieberegler; Differenzbild der Vorschauen (grob, Vorschaugröße) |
| Welche Metadaten sich geändert haben | `c2pa.metadata`-Assertion (IPTC/EXIF zum Zeitpunkt der Signatur) gegen die aktuellen Werte | Tabelle Feld / damals / jetzt. Funktioniert nur, wenn der Signierende die Assertion mitgeschrieben hat; Captioner würde das tun |
| Bereiche einer Bearbeitung | `changes`/Regionen in Aktionen (C2PA 2.x) | Rahmen über der Großansicht. Selten befüllt, nur zeigen, wenn vorhanden |

Pixelgenau lässt sich eine Manipulation nicht verorten. Das Differenzbild der Vorschauen
ist nur ein Anhaltspunkt und muss in der Oberfläche so benannt werden.

## Signieren und Identität

Ohne eigenes Zertifikat kann Captioner nicht signieren. Ein Login bei Adobe ersetzt es
nicht, denn eine Schnittstelle dafür gibt es nach heutigem Stand nicht. Die Wege:

| Weg | Ergebnis in Prüfprogrammen | Aufwand |
|---|---|---|
| **A. Selbst erzeugtes Zertifikat** | `Valid`, „unbekannter Unterzeichner“. Belegt Unversehrtheit seit dem Signieren, aber nicht die Person | kostenlos; reicht fürs eigene Archiv |
| **B. Zertifikat einer C2PA-konformen CA** (z. B. SSL.com, DigiCert; Vertrauensliste seit 01.01.2026) | `Trusted`, Name aus dem Zertifikat | kostenpflichtig, Identitätsprüfung durch die CA |
| **C. CAWG-Identitäts-Assertion mit X.509** (Übergangsregel: individuell geprüfte S/MIME-Zertifikate bis 31.03.2027) | Urheber als eigene, geprüfte Aussage neben der Signatur des Programms | wie B; Unterstützung in c2pa-rs noch im Fluss |
| **D. Adobe Content Authenticity (Web-App)** | „Verified on LinkedIn“, verknüpfte Profile | außerhalb von Captioner, je fertige Datei von Hand |

Empfehlung: Weg D bleibt außerhalb von Captioner und funktioniert sofort. In Captioner
lohnt sich Signieren erst mit Weg B bzw. C, beim Ausspielen an Redaktionen. Weg A taugt für
Tests und das eigene Archiv.

**Lightroom-Weg:** Beim Export rendert Lightroom das Bild neu. Ein von Captioner signiertes
JPG verliert dabei die Signatur. Ob Lightroom Classic ein importiertes Manifest als Zutat
übernimmt, ist nicht dokumentiert. Ein Bericht in der Adobe-Community nennt Fehler beim
Export von Kamera-signierten Bildern. Vor jeder Signier-Funktion für Bilder, die nach
Lightroom gehen, steht deshalb ein Akzeptanztest (vgl. ADR 0001, Punkt 7).

## Folgen

- Neue Abhängigkeit `c2pa-python` mit Bibliothek in Rust: rund 20 MB im macOS-Bundle,
  unter Windows größer (zu prüfen). Die Version ist auf `0.38.*` festgelegt, weil die API
  vor 1.0 noch wandert. Dependabot sollte sie einzeln vorschlagen, wie PySide6.
- `licenses/c2pa.txt` (MIT). Offen: die Lizenzen der in `libc2pa_c` statisch gelinkten
  Rust-Crates (z. B. mit `cargo about` aus c2pa-rs erzeugen) in `licenses/` aufnehmen.
- Kein Netz beim Lesen. Ein Manifest, das nur im Netz liegt (`remote_url`), wird angezeigt,
  aber nicht geladen.
- Das Schreiben wird in Phase 2 eingeschränkt (Warnung). Ab Phase 4 wird es länger
  (Signieren nach den Metadaten).

## Schritte

1. ✅ `credentials.py` (lesen, Kette, `at_risk`), Abhängigkeit, Bündelung beider Specs,
   Lizenz, Tests mit Test-CA (`tests/fixtures/c2pa`).
2. ✅ Rückfrage vor dem Schreiben (Speichern, Einfügen, Template anwenden, Sterne, Farben,
   Tag), einmal je Bild. Bei RAW+JPG/DNG wahlweise nur ins RAW-Sidecar
   (`Item.protect_embedded`), dann bleibt das Manifest gültig.
3. ✅ „CR“-Abzeichen in der Galerie (Farbe nach Status), Tooltip, Filter, Abschnitt im
   Info-Panel. Geprüft wird im Scan-Worker nach den Metadaten, nach dem Schreiben neu.
4. ✅ Dialog „Herkunft“: Kette, Vorschaubild beim Signieren gegen jetzt mit Differenzbild,
   Beschriftung damals/jetzt (aus `c2pa.metadata` bzw. `stds.iptc`), Link zur Prüfseite.
5. Signieren: Einstellungen (Zertifikat und Schlüssel aus dem Schlüsselbund, TSA-URL),
   Warteschlange bei fehlendem Netz, zuerst beim Ausspielen. Neu signieren nach dem
   Beschriften, wobei das ursprüngliche Manifest `parentOf`-Zutat wird (Originalbytes vor
   `replace_file` sichern).
6. C2PA-Vertrauensliste bündeln und aktualisieren.

## Offene Fragen

- Welche Kameras im Einsatz signieren schon (C2PA-Firmware)? Davon hängt ab, wie dringend
  Schritt 2 ist.
- Gibt es ein Zertifikat (Weg B/C), und wer bezahlt es (selbst, Verein, Agentur)?
- Verhalten von Lightroom Classic beim Import und Export von Bildern mit Manifest (Test).
