"""
EXIF/IPTC-Werte fuer das Info-Panel der Grossansicht.

Kamera-Werte kommen aus der Hauptdatei (bei RAW+JPG aus der RAW-Datei),
weitere IPTC/XMP-Felder (Fotograf, Copyright, ...) aus Sidecar > eingebettet >
Hauptdatei. Die Beschriftungsfelder selbst (Titel, Beschreibung, Tags, Ort,
Bewertung) kommen aus dem aktuellen Stand in der App (item.meta), damit sie
auch direkt nach dem Speichern stimmen, bevor die Datei geschrieben ist.
"""
import os
import re

from .i18n import _
from .scanner import Item, Metadata

CAMERA_TAGS = [
    'SubSecDateTimeOriginal', 'DateTimeOriginal', 'OffsetTimeOriginal',
    'Make', 'Model', 'SerialNumber', 'ShutterCount',
    'LensID', 'LensModel', 'FocalLength', 'FocalLengthIn35mmFormat',
    'Aperture', 'ShutterSpeed', 'ISO', 'ExposureCompensation', 'ExposureProgram',
    'MeteringMode', 'Flash', 'WhiteBalance', 'FocusMode', 'AFAreaMode',
    'ImageSize', 'Megapixels', 'GPSPosition', 'GPSAltitude',
]
IPTC_TAGS = [
    'Province-State', 'State', 'Country-PrimaryLocationName', 'Country',
    'Country-PrimaryLocationCode', 'CountryCode', 'CreatorWorkEmail',
    'By-line', 'Creator', 'Artist', 'Credit', 'CopyrightNotice', 'Rights', 'Copyright',
    'Source', 'Writer-Editor', 'CaptionWriter', 'Instructions', 'SpecialInstructions',
]


def read(tool, item: Item):
    """Rohwerte (formatiert wie ExifTool sie ausgibt) fuer ein Item."""
    main = item.raw or item.primary
    others = [p for p in item.embedded if p != main]
    if item.sidecar and item.sidecar.exists():
        others.append(item.sidecar)
    paths = [main] + others
    records = tool.json(*[f'-{t}' for t in CAMERA_TAGS + IPTC_TAGS], *[str(p) for p in paths])
    by_path = {os.path.normcase(r.get('SourceFile', '')): r for r in records}
    main_record = by_path.get(os.path.normcase(str(main)), {})

    merged = {key: main_record[key] for key in CAMERA_TAGS if key in main_record}
    # IPTC/XMP: Sidecar zuletzt, gewinnt also
    for path in [main] + others:
        record = by_path.get(os.path.normcase(str(path)), {})
        for key in IPTC_TAGS:
            if record.get(key) not in (None, ''):
                merged[key] = record[key]
    merged['_files'] = [(p.name, _size(p)) for p in paths if p.exists()]
    return merged


def _size(path):
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _text(value):
    if value is None:
        return ''
    if isinstance(value, list):
        return ', '.join(str(v) for v in value if str(v).strip())
    return str(value).strip()


def _first(raw, *keys):
    for key in keys:
        value = _text(raw.get(key))
        if value:
            return value
    return ''


def format_datetime(value):
    """'2026:03:01 17:17:55.40+02:00' -> '01.03.2026 17:17:55,40'"""
    match = re.match(r'(\d{4}):(\d{2}):(\d{2}) (\d{2}:\d{2}:\d{2})(?:\.(\d+))?', value or '')
    if not match:
        return value or ''
    year, month, day, time, sub = match.groups()
    return f'{day}.{month}.{year} {time}' + (f',{sub}' if sub else '')


def format_size(size):
    for unit in ('B', 'kB', 'MB', 'GB'):
        if size < 1000 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'.replace('.', ',')
        size /= 1000
    return ''


def camera_name(make, model):
    """'NIKON CORPORATION' + 'NIKON Z 9' -> 'NIKON Z 9'"""
    if not make:
        return model
    if not model:
        return make
    if model.lower().startswith(make.split()[0].lower()):
        return model
    return f'{make} {model}'


def summary(raw):
    """
    Eine Zeile unter dem Bild: Kamera, Objektiv, Brennweite, Belichtung, Dateien, z. B.
    "NIKON Z 9 · NIKKOR Z 70-200mm f/2.8 VR S · 200 mm · 1/500 s · f/2.8 · ISO 64 · DSC_0001.NEF, DSC_0001.JPG".
    Fehlende Werte fallen weg.
    """
    raw = raw or {}
    focal = re.sub(r'\.0\b', '', _first(raw, 'FocalLength'))
    aperture, shutter, iso = _first(raw, 'Aperture'), _first(raw, 'ShutterSpeed'), _first(raw, 'ISO')
    parts = [camera_name(_first(raw, 'Make'), _first(raw, 'Model')), _first(raw, 'LensID', 'LensModel'), focal,
             f'{shutter} s' if shutter else '', f'f/{aperture}' if aperture else '', f'ISO {iso}' if iso else '',
             ', '.join(name for name, _size in raw.get('_files', []) if not name.lower().endswith('.xmp'))]
    return ' · '.join(part for part in parts if part)


def sections(raw, meta: Metadata, labels=()):
    """[(Titel, [(Feld, Wert), ...]), ...] - nur Felder mit Inhalt."""
    raw = raw or {}

    focal = _first(raw, 'FocalLength')
    focal35 = _first(raw, 'FocalLengthIn35mmFormat')
    if focal and focal35 and focal35.split()[0] != focal.split()[0].split('.')[0]:
        focal = _('{focal} (KB {focal35})').format(focal=focal, focal35=focal35)
    aperture = _first(raw, 'Aperture')
    shutter = _first(raw, 'ShutterSpeed')
    size = _first(raw, 'ImageSize').replace('x', ' × ')
    if size and _first(raw, 'Megapixels'):
        size += f' ({_first(raw, "Megapixels").replace(".", ",")} MP)'
    focus = ' · '.join(v for v in (_first(raw, 'FocusMode'), _first(raw, 'AFAreaMode')) if v)
    exposure_comp = _first(raw, 'ExposureCompensation')
    if exposure_comp in ('0', '+0'):
        exposure_comp = ''

    camera = [
        (_('Aufgenommen'), format_datetime(_first(raw, 'SubSecDateTimeOriginal', 'DateTimeOriginal'))),
        (_('Kamera'), camera_name(_first(raw, 'Make'), _first(raw, 'Model'))),
        (_('Seriennummer'), _first(raw, 'SerialNumber')),
        (_('Auslösungen'), _first(raw, 'ShutterCount')),
        (_('Objektiv'), _first(raw, 'LensID', 'LensModel')),
        (_('Brennweite'), focal),
        (_('Blende'), f'f/{aperture}' if aperture else ''),
        (_('Belichtungszeit'), f'{shutter} s' if shutter else ''),
        ('ISO', _first(raw, 'ISO')),
        (_('Belichtungskorrektur'), exposure_comp),
        (_('Programm'), _first(raw, 'ExposureProgram')),
        (_('Messung'), _first(raw, 'MeteringMode')),
        (_('Fokus'), focus),
        (_('Weißabgleich'), _first(raw, 'WhiteBalance')),
        (_('Blitz'), _first(raw, 'Flash')),
        (_('Auflösung'), size),
        ('GPS', _first(raw, 'GPSPosition')),
    ]
    iptc = [
        (_('Titel'), meta.headline),
        (_('Beschreibung'), meta.caption),
        (_('Tags'), ', '.join(meta.keywords)),
        (_('Stadt'), meta.city),
        (_('Ort'), meta.sublocation),
        # Ort und Rechte aus den Metadaten des Bildes: nach dem Speichern sofort aktuell
        (_('Bundesland'), meta.state or _first(raw, 'Province-State', 'State')),
        (_('Land'), meta.country or _first(raw, 'Country-PrimaryLocationName', 'Country')),
        (_('Ländercode'), meta.country_code or _first(raw, 'Country-PrimaryLocationCode', 'CountryCode')),
        (_('Fotograf'), meta.creator or _first(raw, 'By-line', 'Creator', 'Artist')),
        (_('E-Mail'), meta.contact_email or _first(raw, 'CreatorWorkEmail')),
        (_('Position'), meta.authors_position),
        (_('Credit'), meta.credit or _first(raw, 'Credit')),
        (_('Copyright'), meta.copyright or _first(raw, 'CopyrightNotice', 'Rights', 'Copyright')),
        (_('Copyright-URL'), meta.web_statement),
        (_('Quelle'), meta.source or _first(raw, 'Source')),
        (_('Kategorie'), meta.category),
        (_('Beschriftet von'), meta.caption_writer or _first(raw, 'Writer-Editor', 'CaptionWriter')),
        (_('Hinweise'), meta.instructions or _first(raw, 'SpecialInstructions', 'Instructions')),
    ]
    label = meta.label
    if meta.color_class:
        label = f'{meta.color_class}' + (f' ({meta.label})' if meta.label else '')
    rating = [
        (_('Sterne'), '★' * meta.rating + '☆' * (5 - meta.rating)),
        (_('Farbklasse'), label),
        (_('Tag'), _('ja') if meta.tagged else _('nein')),
    ]
    files = [(_('Datei') if i == 0 else '', f'{name} · {format_size(size)}')
             for i, (name, size) in enumerate(raw.get('_files', []))]

    result = []
    for title, rows in ((_('Aufnahme'), camera), ('IPTC / XMP', iptc), (_('Bewertung'), rating),
                        (_('Dateien'), files)):
        rows = [(k, v) for k, v in rows if v]
        if rows:
            result.append((title, rows))
    return result
