"""
Read and write metadata (ADR 0001, item 4).

* Proprietary RAWs are never changed; everything goes into the XMP sidecar
  <base>.xmp. An existing sidecar (also "DSC_0001.XMP" from a photo culling
  workflow tool) is updated, not replaced; develop settings in it are kept.
* JPG/DNG/TIFF get the metadata embedded: IPTC-IIM + XMP + EXIF. It is written to
  a new file that only replaces the original after the image data checksum has
  been verified.

Field names match the IPTC map in app/indexer/lib/indexer.py.
"""
import os
import re
import shutil
from pathlib import Path

from .files import replace_file
from .i18n import _, N_
from .scanner import Item, Metadata, RAW_EXTENSIONS

# IPTC-IIM limits in bytes
LIMITS = {
    'headline': 256,
    'caption': 2000,
    'keyword': 64,
    'city': 32,
    'sublocation': 32,
    'state': 32,
    'country': 64,
    'country_code': 3,
    'creator': 32,
    'authors_position': 32,
    'credit': 32,
    'caption_writer': 32,
    'copyright': 128,
    'source': 32,
    'instructions': 256,
}

# Location and rights: Metadata field -> (XMP, IPTC, EXIF) for writing; reading goes
# by tag names without group (READ_TAGS), the first non-empty one wins
RIGHTS_TAGS = {
    'state': ('XMP-photoshop:State', 'IPTC:Province-State', None),
    'country': ('XMP-photoshop:Country', 'IPTC:Country-PrimaryLocationName', None),
    'country_code': ('XMP-iptcCore:CountryCode', 'IPTC:Country-PrimaryLocationCode', None),
    'creator': ('XMP-dc:Creator', 'IPTC:By-line', 'EXIF:Artist'),
    'contact_email': ('XMP-iptcCore:CreatorWorkEmail', None, None),
    'authors_position': ('XMP-photoshop:AuthorsPosition', 'IPTC:By-lineTitle', None),
    'credit': ('XMP-photoshop:Credit', 'IPTC:Credit', None),
    'caption_writer': ('XMP-photoshop:CaptionWriter', 'IPTC:Writer-Editor', None),
    'copyright': ('XMP-dc:Rights', 'IPTC:CopyrightNotice', 'EXIF:Copyright'),
    'web_statement': ('XMP-xmpRights:WebStatement', None, None),
    'source': ('XMP-photoshop:Source', 'IPTC:Source', None),
    'category': ('XMP-photoshop:Category', 'IPTC:Category', None),
    'instructions': ('XMP-photoshop:Instructions', 'IPTC:SpecialInstructions', None),
}
# IPTC-IIM Category allows only 3 characters ("SPO"). Anything longer ("Sport") is only
# in the XMP instead of being cut off ("Spo") in the IIM
IPTC_CATEGORY_LIMIT = 3
RIGHTS_READ = {
    'state': ('State', 'Province-State'),
    'country': ('Country', 'Country-PrimaryLocationName'),
    'country_code': ('CountryCode', 'Country-PrimaryLocationCode'),
    'creator': ('Creator', 'By-line', 'Artist'),
    'contact_email': ('CreatorWorkEmail',),
    'authors_position': ('AuthorsPosition', 'By-lineTitle'),
    'credit': ('Credit',),
    'caption_writer': ('CaptionWriter', 'Writer-Editor'),
    'copyright': ('Rights', 'CopyrightNotice', 'Copyright'),
    'web_statement': ('WebStatement',),
    'source': ('Source',),
    'category': ('Category',),
    'instructions': ('Instructions', 'SpecialInstructions'),
}
LABELS = {'state': N_('Bundesland'), 'country': N_('Land'), 'country_code': N_('Ländercode'),
          'creator': N_('Fotograf'), 'contact_email': N_('E-Mail'),
          'authors_position': N_('Position'), 'credit': N_('Credit'), 'caption_writer': N_('Beschriftet von'),
          'copyright': N_('Copyright'), 'web_statement': N_('Copyright-URL'), 'source': N_('Quelle'),
          'category': N_('Kategorie'), 'instructions': N_('Hinweise')}
OBJECT_NAME_LIMIT = 64

READ_TAGS = [
    '-Headline', '-Title', '-ObjectName',
    '-Description', '-Caption-Abstract', '-ImageDescription',
    '-Subject', '-Keywords',
    '-City', '-Sub-location', '-Location',
    '-Rating', '-Label', '-XMP-photomech:ColorClass', '-XMP-photomech:Tagged',
    '-DateTimeOriginal', '-SubSecTimeOriginal', '-Orientation', '-Model', '-SerialNumber',
    '-GPSLatitude', '-GPSLongitude',
] + sorted({f'-{name}' for names in RIGHTS_READ.values() for name in names})


class WriteError(RuntimeError):
    pass


def single_line(text):
    """Captions are single-line."""
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
            check(_(label), _rights_value(meta, name), LIMITS[name])  # as it goes into the image
    for keyword in meta.keywords:
        check(_('Tag "{keyword}"').format(keyword=keyword), keyword, LIMITS['keyword'])
    return problems


def truncate_bytes(text, limit):
    encoded = text.encode('utf-8')
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode('utf-8', 'ignore').rstrip()


# --- Reading -----------------------------------------------------------------

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
    """First non-empty value; lists (dc:creator) joined with '; '."""
    for tag in tags:
        value = record.get(tag)
        if isinstance(value, list):
            value = '; '.join(str(v) for v in value if str(v).strip())
        if value not in (None, ''):
            return str(value).strip()
    return ''


def _gps(record):
    """(latitude, longitude) with sign (-n returns the composite values), otherwise None."""
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
    """Reads capture time, orientation and caption for all items."""
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
    item.camera = str(main.get('Model') or '').strip()
    item.serial = str(main.get('SerialNumber') or '').strip()
    try:
        item.orientation = int(main.get('Orientation') or 1)
    except (TypeError, ValueError):
        item.orientation = 1

    # precedence: sidecar > embedded > XMP in the RAW file (camera rating)
    candidates = [record_for(item.sidecar)] + [record_for(p) for p in item.embedded] + [record_for(item.raw)]
    for record in candidates:
        if record:
            meta = meta_from_record(record)
            if (meta.is_captioned or meta.headline or meta.keywords or meta.rating or meta.label
                    or meta.color_class or meta.tagged):
                item.meta = meta
                break
    # GPS from any of the files, sidecar first: camera GPS in the RAW counts
    # even when the caption comes from the sidecar
    gps = next((g for g in (_gps(r) for r in candidates if r) if g), None)
    if gps:
        item.meta.latitude, item.meta.longitude = gps
    # Same for location and rights, e.g. photographer/copyright written by the camera into
    # RAW/JPG: otherwise the next save would clear them in the sidecar/JPG
    for name, tags in RIGHTS_READ.items():
        if not getattr(item.meta, name):
            value = next((v for v in (_text(r, tags) for r in candidates if r) if v), '')
            setattr(item.meta, name, value)
    item.meta_loaded = True


# --- Writing -----------------------------------------------------------------

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
    elif meta.gps_changed:
        # undo: remove GPS set by Captioner again
        args += ['-XMP-exif:GPSLatitude=', '-XMP-exif:GPSLongitude=']
    for name, (xmp, _, _) in RIGHTS_TAGS.items():
        args.append(f'-{xmp}={_rights_value(meta, name)}')
    if meta.copyright:
        args.append('-XMP-xmpRights:Marked=True')  # Lightroom: "Copyright Status: Copyrighted"
    return args


def _rights_value(meta, name):
    """
    Single-line: template files and foreign images may contain line breaks (address,
    bank details), arguments to ExifTool must not. The instructions are multi-line in
    the template; their lines stay recognizably separated by " · ".
    """
    value = getattr(meta, name)
    if name == 'instructions':
        value = ' · '.join(line.strip() for line in (value or '').splitlines() if line.strip())
    return single_line(value)


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
        value = _rights_value(meta, name)
        if name == 'category':
            # too long: clear the IIM instead of truncating, the XMP carries the full value
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
    elif meta.gps_changed:
        args += ['-EXIF:GPSLatitude=', '-EXIF:GPSLatitudeRef=', '-EXIF:GPSLongitude=', '-EXIF:GPSLongitudeRef=']
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
        try:
            replace_file(temp, path)
        except PermissionError:
            raise WriteError(_('{name}: Datei ist von einem anderen Programm geöffnet (z. B. Explorer-Vorschau, '
                               'Lightroom), Original bleibt unangetastet').format(name=path.name))
    finally:
        if temp.exists():
            temp.unlink()


def write_item(tool, item: Item, meta: Metadata, sidecars_only=False):
    """
    Writes the metadata into all files of the item. Returns the written paths.
    sidecars_only: write-protection mode for the card.
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
