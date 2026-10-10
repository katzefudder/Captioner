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

from .scanner import Item, Metadata, RAW_EXTENSIONS

# IPTC-IIM-Grenzen in Bytes
LIMITS = {
    'headline': 256,
    'caption': 2000,
    'keyword': 64,
    'city': 32,
    'sublocation': 32,
}
OBJECT_NAME_LIMIT = 64

READ_TAGS = [
    '-Headline', '-Title', '-ObjectName',
    '-Description', '-Caption-Abstract', '-ImageDescription',
    '-Subject', '-Keywords',
    '-City', '-Sub-location', '-Location',
    '-Rating', '-Label', '-XMP-photomech:ColorClass', '-XMP-photomech:Tagged',
    '-DateTimeOriginal', '-SubSecTimeOriginal', '-Orientation',
]


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
            problems.append(f'{label}: {size} von max. {limit} Bytes')

    check('Titel', meta.headline, LIMITS['headline'])
    check('Beschreibung', meta.caption, LIMITS['caption'])
    check('Stadt', meta.city, LIMITS['city'])
    check('Ort', meta.sublocation, LIMITS['sublocation'])
    for keyword in meta.keywords:
        check(f'Tag "{keyword}"', keyword, LIMITS['keyword'])
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
    )


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
        raise WriteError(f'{item.name}: keine RAW-Datei fuer ein Sidecar')
    if target.exists():
        _check(tool.execute('-overwrite_original', *_xmp_args(meta), str(target)), target)
    else:
        _check(tool.execute(*_xmp_args(meta), '-o', str(target)), target)
        if not target.exists():
            raise WriteError(f'{target.name}: Sidecar wurde nicht angelegt')
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
            raise WriteError(f'{path.name}: ExifTool hat keine Datei geschrieben')
        after = image_data_hash(tool, temp)
        if not before or before != after:
            raise WriteError(f'{path.name}: Bilddaten nach dem Schreiben veraendert, Original bleibt unangetastet')
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
