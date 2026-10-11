"""
Metadaten lesen und schreiben (ADR 0001, Punkt 4).

* Proprietaere RAWs werden nie veraendert; alles geht ins XMP-Sidecar
  <basis>.xmp. Ein vorhandenes Sidecar (auch "DSC_0001.XMP" aus einem
  Workflow-Tool fuer die Auswahl von Fotos)
  wird fortgeschrieben, nicht ersetzt; Entwicklungseinstellungen darin bleiben.
* JPG/DNG/TIFF bekommen die Metadaten eingebettet: IPTC-IIM + XMP + EXIF.
  Geschrieben wird in eine neue Datei, die erst nach Pruefung der Bilddaten-
  Pruefsumme das Original ersetzt.

Feldnamen entsprechen der IPTC-Map in app/indexer/lib/indexer.py.
"""
import os
import re
import shutil
from pathlib import Path

from .i18n import _, N_
from .scanner import Item, Metadata, RAW_EXTENSIONS

# IPTC-IIM-Grenzen in Bytes
LIMITS = {
    'headline': 256,
    'caption': 2000,
    'keyword': 64,
    'city': 32,
    'sublocation': 32,
    'state': 32,
    'country': 64,
    'creator': 32,
    'authors_position': 32,
    'caption_writer': 32,
    'copyright': 128,
    'source': 32,
}

# Ort und Rechte: Metadata-Feld -> (XMP, IPTC, EXIF) zum Schreiben; gelesen wird ueber
# die Tag-Namen ohne Gruppe (READ_TAGS), erster nicht leerer gewinnt
RIGHTS_TAGS = {
    'state': ('XMP-photoshop:State', 'IPTC:Province-State', None),
    'country': ('XMP-photoshop:Country', 'IPTC:Country-PrimaryLocationName', None),
    'creator': ('XMP-dc:Creator', 'IPTC:By-line', 'EXIF:Artist'),
    'authors_position': ('XMP-photoshop:AuthorsPosition', 'IPTC:By-lineTitle', None),
    'caption_writer': ('XMP-photoshop:CaptionWriter', 'IPTC:Writer-Editor', None),
    'copyright': ('XMP-dc:Rights', 'IPTC:CopyrightNotice', 'EXIF:Copyright'),
    'web_statement': ('XMP-xmpRights:WebStatement', None, None),
    'source': ('XMP-photoshop:Source', 'IPTC:Source', None),
    'category': ('XMP-photoshop:Category', 'IPTC:Category', None),
}
# IPTC-IIM Category erlaubt nur 3 Zeichen ("SPO"). Laengeres ("Sport") steht nur im XMP,
# statt abgeschnitten ("Spo") im IIM
IPTC_CATEGORY_LIMIT = 3
RIGHTS_READ = {
    'state': ('State', 'Province-State'),
    'country': ('Country', 'Country-PrimaryLocationName'),
    'creator': ('Creator', 'By-line', 'Artist'),
    'authors_position': ('AuthorsPosition', 'By-lineTitle'),
    'caption_writer': ('CaptionWriter', 'Writer-Editor'),
    'copyright': ('Rights', 'CopyrightNotice', 'Copyright'),
    'web_statement': ('WebStatement',),
    'source': ('Source',),
    'category': ('Category',),
}
LABELS = {'state': N_('Bundesland'), 'country': N_('Land'), 'creator': N_('Fotograf'),
          'authors_position': N_('Position'), 'caption_writer': N_('Beschriftet von'),
          'copyright': N_('Copyright'), 'web_statement': N_('Copyright-URL'), 'source': N_('Quelle'),
          'category': N_('Kategorie')}
OBJECT_NAME_LIMIT = 64

READ_TAGS = [
    '-Headline', '-Title', '-ObjectName',
    '-Description', '-Caption-Abstract', '-ImageDescription',
    '-Subject', '-Keywords',
    '-City', '-Sub-location', '-Location',
    '-Rating', '-Label', '-XMP-photomech:ColorClass', '-XMP-photomech:Tagged',
    '-DateTimeOriginal', '-SubSecTimeOriginal', '-Orientation',
    '-GPSLatitude', '-GPSLongitude',
] + sorted({f'-{name}' for names in RIGHTS_READ.values() for name in names})


class WriteError(RuntimeError):
    pass


def single_line(text):
    """Bildunterschriften sind einzeilig."""
    return re.sub(r'\s+', ' ', text or '').strip()


def validate(meta: Metadata):
    problems = []

    def check(label, value, limit):
        size = len(value.encode('utf-8'))
        if size > limit:
            problems.append(_('{label}: {size} von max. {limit} Bytes').format(label=label, size=size, limit=limit))

    check(_('Titel'), meta.headline, LIMITS['headline'])
    check(_('Beschreibung'), meta.caption, LIMITS['caption'])
    check(_('Stadt'), meta.city, LIMITS['city'])
    check(_('Ort'), meta.sublocation, LIMITS['sublocation'])
    for name, label in LABELS.items():
        if name in LIMITS:
            check(_(label), getattr(meta, name), LIMITS[name])
    for keyword in meta.keywords:
        check(_('Tag "{keyword}"').format(keyword=keyword), keyword, LIMITS['keyword'])
    return problems


def truncate_bytes(text, limit):
    encoded = text.encode('utf-8')
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode('utf-8', 'ignore').rstrip()


# --- Lesen -------------------------------------------------------------------

def _as_list(value):
    if value is None or value == '':
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)]


def _first(record, *names):
    for name in names:
        value = record.get(name)
        if value not in (None, ''):
            return str(value)
    return ''


def meta_from_record(record):
    return Metadata(
        headline=_first(record, 'Headline', 'Title', 'ObjectName'),
        caption=_first(record, 'Description', 'Caption-Abstract', 'ImageDescription'),
        keywords=_as_list(record.get('Subject')) or _as_list(record.get('Keywords')),
        city=_first(record, 'City'),
        sublocation=_first(record, 'Location', 'Sub-location'),
        rating=int(record.get('Rating') or 0) if str(record.get('Rating') or '0').lstrip('-').isdigit() else 0,
        label=_first(record, 'Label'),
        color_class=_int(record.get('ColorClass'), 0, 8),
        tagged=record.get('Tagged') in (True, 'True', 'true', 1),
        **{name: _text(record, tags) for name, tags in RIGHTS_READ.items()},
    )


def _text(record, tags):
    """Erster nicht leerer Wert; Listen (dc:creator) mit '; ' verbunden."""
    for tag in tags:
        value = record.get(tag)
        if isinstance(value, list):
            value = '; '.join(str(v) for v in value if str(v).strip())
        if value not in (None, ''):
            return str(value).strip()
    return ''


def _gps(record):
    """(Breite, Laenge) mit Vorzeichen (-n liefert die Composite-Werte), sonst None."""
    lat, lon = record.get('GPSLatitude'), record.get('GPSLongitude')
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and not (lat == 0 and lon == 0):
        return float(lat), float(lon)
    return None


def _int(value, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if low <= number <= high else 0


def read_items(tool, items, chunk_size=200):
    """Liest Aufnahmezeit, Ausrichtung und Beschriftung fuer alle Items."""
    for start in range(0, len(items), chunk_size):
        chunk = items[start:start + chunk_size]
        paths = []
        for item in chunk:
            paths.extend(item.files)
            if item.sidecar:
                paths.append(item.sidecar)
        records = tool.json('-n', '-fast2', *READ_TAGS, *[str(p) for p in paths])
        by_path = {os.path.normcase(r.get('SourceFile', '')): r for r in records}
        for item in chunk:
            apply_records(item, by_path)
        yield chunk


def apply_records(item: Item, by_path):
    def record_for(path):
        return by_path.get(os.path.normcase(str(path))) if path else None

    main = record_for(item.raw or item.primary) or {}
    date = str(main.get('DateTimeOriginal') or '')
    subsec = str(main.get('SubSecTimeOriginal') or '')
    item.taken_at = f'{date}.{subsec.zfill(3)}' if date and subsec else date
    try:
        item.orientation = int(main.get('Orientation') or 1)
    except (TypeError, ValueError):
        item.orientation = 1

    # Vorrang: Sidecar > eingebettet > XMP in der RAW-Datei (Kamera-Bewertung)
    candidates = [record_for(item.sidecar)] + [record_for(p) for p in item.embedded] + [record_for(item.raw)]
    for record in candidates:
        if record:
            meta = meta_from_record(record)
            if (meta.is_captioned or meta.headline or meta.keywords or meta.rating or meta.label
                    or meta.color_class or meta.tagged):
                item.meta = meta
                break
    # GPS aus irgendeiner der Dateien, Sidecar zuerst: Kamera-GPS in der RAW zaehlt
    # auch, wenn die Beschriftung aus dem Sidecar kommt
    gps = next((g for g in (_gps(r) for r in candidates if r) if g), None)
    if gps:
        item.meta.latitude, item.meta.longitude = gps
    # Ebenso Ort und Rechte, z. B. Fotograf/Copyright, die die Kamera in RAW/JPG schreibt:
    # sonst wuerde das naechste Speichern sie im Sidecar/JPG leeren
    for name, tags in RIGHTS_READ.items():
        if not getattr(item.meta, name):
            value = next((v for v in (_text(r, tags) for r in candidates if r) if v), '')
            setattr(item.meta, name, value)
    item.meta_loaded = True


# --- Schreiben ---------------------------------------------------------------

def _xmp_args(meta: Metadata):
    args = [
        f'-XMP-photoshop:Headline={meta.headline}',
        f'-XMP-dc:Title={meta.headline}',
        f'-XMP-dc:Description={meta.caption}',
        f'-XMP-photoshop:City={meta.city}',
        f'-XMP-iptcCore:Location={meta.sublocation}',
        f'-XMP-xmp:Rating={meta.rating}',
        f'-XMP-xmp:Label={meta.label}',
        f'-XMP-photomech:ColorClass#={meta.color_class}' if meta.color_class else '-XMP-photomech:ColorClass=',
        f'-XMP-photomech:Tagged={"Yes" if meta.tagged else "No"}',
    ]
    args += [f'-XMP-dc:Subject={k}' for k in meta.keywords] or ['-XMP-dc:Subject=']
    if meta.gps_changed and meta.latitude is not None and meta.longitude is not None:
        args += [f'-XMP-exif:GPSLatitude={meta.latitude:.7f}', f'-XMP-exif:GPSLongitude={meta.longitude:.7f}']
    for name, (xmp, _, _) in RIGHTS_TAGS.items():
        args.append(f'-{xmp}={getattr(meta, name)}')
    if meta.copyright:
        args.append('-XMP-xmpRights:Marked=True')  # Lightroom: "Copyright-Status: Geschützt"
    return args


def _embedded_args(meta: Metadata):
    args = ['-charset', 'iptc=UTF8', '-IPTC:CodedCharacterSet=UTF8']
    args += _xmp_args(meta)
    args += [
        f'-IPTC:Headline={meta.headline}',
        f'-IPTC:ObjectName={truncate_bytes(meta.headline, OBJECT_NAME_LIMIT)}',
        f'-IPTC:Caption-Abstract={meta.caption}',
        f'-EXIF:ImageDescription={meta.caption}',
        f'-IPTC:City={meta.city}',
        f'-IPTC:Sub-location={meta.sublocation}',
    ]
    args += [f'-IPTC:Keywords={k}' for k in meta.keywords] or ['-IPTC:Keywords=']
    for name, (_, iptc, exif) in RIGHTS_TAGS.items():
        value = getattr(meta, name)
        if name == 'category':
            # zu lang: IIM leeren statt abschneiden, das XMP traegt den vollen Wert
            fits = len(value.encode('utf-8')) <= IPTC_CATEGORY_LIMIT
            args.append(f'-{iptc}={value if fits else ""}')
        elif iptc:
            args.append(f'-{iptc}={truncate_bytes(value, LIMITS[name])}')
        if exif:
            args.append(f'-{exif}={value}')
    if meta.gps_changed and meta.latitude is not None and meta.longitude is not None:
        args += [f'-EXIF:GPSLatitude={abs(meta.latitude):.7f}',
                 f'-EXIF:GPSLatitudeRef={"S" if meta.latitude < 0 else "N"}',
                 f'-EXIF:GPSLongitude={abs(meta.longitude):.7f}',
                 f'-EXIF:GPSLongitudeRef={"W" if meta.longitude < 0 else "E"}']
    return args


def _check(out_err, target):
    _, err = out_err
    errors = [line for line in err.splitlines() if line.startswith('Error')]
    if errors:
        raise WriteError(f'{target.name}: {"; ".join(errors)}')


def image_data_hash(tool, path):
    records = tool.json('-ImageDataHash', '-api', 'ImageHashType=MD5', str(path))
    return (records[0].get('ImageDataHash') if records else None) or None


def write_sidecar(tool, item: Item, meta: Metadata):
    target = item.sidecar_target
    if target is None:
        raise WriteError(_('{name}: keine RAW-Datei fuer ein Sidecar').format(name=item.name))
    if target.exists():
        _check(tool.execute('-overwrite_original', *_xmp_args(meta), str(target)), target)
    else:
        _check(tool.execute(*_xmp_args(meta), '-o', str(target)), target)
        if not target.exists():
            raise WriteError(_('{name}: Sidecar wurde nicht angelegt').format(name=target.name))
        item.sidecar = target
    return target


def write_embedded(tool, path: Path, meta: Metadata):
    temp = path.with_name(f'.{path.stem}.captioner-tmp{path.suffix}')
    if temp.exists():
        temp.unlink()
    before = image_data_hash(tool, path)
    try:
        _check(tool.execute(*_embedded_args(meta), '-o', str(temp), str(path)), path)
        if not temp.exists():
            raise WriteError(_('{name}: ExifTool hat keine Datei geschrieben').format(name=path.name))
        after = image_data_hash(tool, temp)
        if not before or before != after:
            raise WriteError(_('{name}: Bilddaten nach dem Schreiben veraendert, Original bleibt unangetastet')
                             .format(name=path.name))
        shutil.copymode(path, temp)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def write_item(tool, item: Item, meta: Metadata, sidecars_only=False):
    """
    Schreibt die Metadaten in alle Dateien des Items. Gibt die geschriebenen
    Pfade zurueck. sidecars_only: Schreibschutz-Modus fuer die Karte.
    """
    problems = validate(meta)
    if problems:
        raise WriteError(f'{item.name}: ' + '; '.join(problems))
    written = []
    if item.raw and item.raw.suffix.lower() in RAW_EXTENSIONS:
        written.append(write_sidecar(tool, item, meta))
    if not sidecars_only:
        for path in item.embedded:
            write_embedded(tool, path, meta)
            written.append(path)
    return written
