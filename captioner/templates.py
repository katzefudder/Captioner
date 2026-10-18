"""
Spiel-Templates, der Ersatz fuer das "IPTC Stationery Pad" (ADR 0001, Punkt 6).

Ein Template traegt, was fuer viele Bilder gleich ist: Ort (Stadt, Halle,
Bundesland, Land), Urheber und Rechte, Zusatz-Tags, den Anhang an die
Beschreibung und optional einen festen Titel. Heim und Gast stehen im Titel
bzw. ergeben sich aus den Codes in der Beschreibung.

Die Headline hat das feste Format "<Anlass> - <Heim> gegen <Gast>", weil
recognition/lib/matches.py den Spielkontext genau daraus liest; parse_headline
liest die Teams daraus (Reihenfolge der Code-Vorschlaege).
"""
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w

from .geo import valid_coordinates
from .i18n import _


DEFAULT_CAPTION_SUFFIX = ', {headline}, {city}, {sublocation}, {date}'

# Wie in app/recognition/lib/matches.py
HEADLINE_PATTERN = re.compile(r'^(?P<occasion>.+?)\s+-\s+(?P<home>.+?)\s+gegen\s+(?P<away>.+?)$')


def parse_headline(text):
    """'DEL 2 - EC Bad Nauheim gegen Eisbaeren Regensburg' -> (Anlass, Heim, Gast), sonst None."""
    match = HEADLINE_PATTERN.match((text or '').strip())
    return (match.group('occasion'), match.group('home'), match.group('away')) if match else None


# Felder, die das Template beim Speichern in jedes Bild schreibt, sofern sie gefuellt
# sind (Namen wie in scanner.Metadata); leere lassen den Wert des Bildes stehen
FIXED_FIELDS = ('state', 'country', 'country_code', 'creator', 'contact_email', 'authors_position', 'credit',
                'caption_writer', 'copyright', 'web_statement', 'source', 'category', 'instructions')

# Platzhalter im Anhang ({city} usw.): Feldnamen wie in scanner.Metadata, dazu {date}
SUFFIX_FIELDS = ('headline', 'city', 'sublocation') + FIXED_FIELDS


@dataclass
class MatchTemplate:
    name: str = ''
    # Optional fester Titel "<Anlass> - <Heim> gegen <Gast>"; leer = im Panel eintragen
    headline: str = ''
    city: str = ''
    sublocation: str = ''
    state: str = ''             # Bundesland
    country: str = ''
    country_code: str = ''      # ISO 3166 mit drei Buchstaben, z. B. "DEU"
    extra_tags: list = field(default_factory=list)  # "Eishockey", "DEL2", "2026/27"
    # Urheber und Rechte (Lightroom: "IPTC-Copyright" / "IPTC-Ersteller")
    creator: str = ''           # Fotograf, dc:creator
    contact_email: str = ''     # E-Mail des Fotografen (IPTC Creator Contact Info)
    authors_position: str = ''  # "Fotograf", "Pressefotograf"
    credit: str = ''            # Bildnachweis ("Credit Line"), z. B. "Florian Dehn/chuc.de"
    caption_writer: str = ''    # wer beschriftet
    copyright: str = ''         # "© 2026 Florian Dehn"
    web_statement: str = ''     # URL zu Nutzungsbedingungen/Lizenz
    source: str = ''            # Quelle/Agentur
    category: str = ''          # photoshop:Category, z. B. "Sport"
    instructions: str = ''      # Hinweise (IPTC Special Instructions): Kontakt, Kontoverbindung
    # Wird an jede Bildunterschrift gehaengt, wie bisher im Workflow-Tool fuer die Auswahl von Fotos:
    # "..., DEL 2 - EC Bad Nauheim gegen Eisbaeren Regensburg, Bad Nauheim, Colonel-Knight-Stadion, 01.03.26"
    caption_suffix: str = DEFAULT_CAPTION_SUFFIX
    # Fester Text fuer {date}, z. B. "18.10.26" fuer ein Spiel, das erst kommt; leer = Aufnahmedatum
    date: str = ''
    # Koordinaten des Ortes (Karten-Picker), damit sie mit der Datei weitergegeben
    # werden; fehlen in der Datei, solange keine gesetzt sind
    latitude: float = None
    longitude: float = None
    # Woher das Template stammt; wird nicht in die Datei geschrieben
    path: str = field(default='', compare=False, repr=False)

    @property
    def keywords(self):
        """Galerie-Tags ohne Personen; Personen kommen pro Bild dazu."""
        return unique([*self.teams, self.city, *self.extra_tags])

    @property
    def teams(self):
        """Heim und Gast aus dem festen Titel, sonst leer."""
        parsed = parse_headline(self.headline)
        return list(parsed[1:]) if parsed else []

    def fixed_values(self):
        """Gefuellte Ort-/Rechte-Felder, die beim Speichern in jedes Bild gehen."""
        return {name: getattr(self, name) for name in FIXED_FIELDS if getattr(self, name)}

    def date_mismatch(self, taken_at):
        """Festes Datum, das nicht zum Aufnahmedatum passt: (Template, Bild), sonst None."""
        fixed, taken = self.date.strip(), format_date(taken_at)
        return (fixed, taken) if fixed and taken and fixed != taken else None

    def display_name(self):
        return self.name or self.headline or 'Unbenannt'

    def field_values(self, meta):
        """Ort/Rechte, wie sie nach dem Speichern im Bild stehen: Template, sonst Wert des Bildes."""
        return {name: getattr(self, name) or getattr(meta, name, '') or '' for name in FIXED_FIELDS}

    def suffix_for(self, taken_at='', date=None, mark=None, **fields):
        """
        Suffix mit eingesetzten Werten ({headline}, {city}, ... aus SUFFIX_FIELDS, {date});
        leere Platzhalter fallen samt Komma weg. Uebergebene Felder (die tatsaechlich
        gespeicherten Werte, siehe field_values) haben Vorrang vor denen des Templates.
        date: fertiger Text; sonst das feste Datum des Templates, sonst aus taken_at.
        mark(key, value): umhuellt jeden eingesetzten Wert (Vorschau im Template-Dialog).
        """
        if not self.caption_suffix:
            return ''
        values = {name: getattr(self, name) if fields.get(name) is None else fields[name] for name in SUFFIX_FIELDS}
        values['date'] = date if date is not None else (self.date.strip() or format_date(taken_at))
        text = self.caption_suffix
        for key, value in values.items():
            text = text.replace('{' + key + '}', mark(key, value) if mark and value else value)
        text = re.sub(r'(,\s*)+,', ',', text)
        return re.sub(r',\s*$', '', text)

    def compose_caption(self, caption, taken_at='', **values):
        """Haengt das Suffix an, sofern es nicht schon dasteht."""
        caption = (caption or '').strip()
        suffix = self.suffix_for(taken_at, **values)
        if not caption or not suffix or caption.endswith(suffix.strip()):
            return caption
        if suffix.startswith(',') or suffix.startswith(' '):
            return caption.rstrip(',') + suffix
        return f'{caption} {suffix}'


# Reihenfolge, wenn mehrere Felder denselben Wert haben (Fotograf = Beschriftet von)
_SUFFIX_PRIORITY = ('headline', 'city', 'sublocation', 'date', 'state', 'country') + \
    tuple(name for name in FIXED_FIELDS if name not in ('state', 'country'))


def derive_suffix(caption, values):
    """
    Anhang einer fertigen Beschreibung als Platzhalter: "Jubel, DEL 2 - A gegen B, Bad Nauheim, ,
    20.02.24" mit den Werten des Bildes -> ", {headline}, {city}, {sublocation}, {date}". Gesucht
    wird von hinten nach Segmenten (durch Komma getrennt), die genau einem Wert entsprechen; ein
    leeres Segment nach {city} wird zu {sublocation} (leere Platzhalter fallen ohnehin weg).
    Ohne erkennbaren Anhang: ''.
    """
    by_value = {}
    for key in _SUFFIX_PRIORITY:
        value = (values.get(key) or '').strip()
        if value and value not in by_value:
            by_value[value] = key
    candidates = sorted(by_value, key=len, reverse=True)
    rest, parts = (caption or '').rstrip(), []
    while rest:
        value = next((v for v in candidates if rest.endswith(v)
                      and (len(rest) == len(v) or re.search(r',\s*$', rest[:-len(v)]))), None)
        if value is not None:
            parts.insert(0, by_value[value])
            rest = re.sub(r',\s*$', '', rest[:-len(value)], count=1)
        elif parts and re.search(r',\s*$', rest):
            parts.insert(0, None)            # leeres Segment ", ,"
            rest = re.sub(r',\s*$', '', rest, count=1)
        else:
            break
    while parts and parts[0] is None:
        parts.pop(0)
    placeholders = []
    for index, key in enumerate(parts):
        if key is None:
            if index and parts[index - 1] == 'city' and 'sublocation' not in parts:
                key = 'sublocation'
            else:
                continue
        placeholders.append('{' + key + '}')
    return ''.join(', ' + p for p in placeholders)


def from_metadata(meta, taken_at='', name='', persons=()):
    """
    Template, das der Beschriftung eines Bildes moeglichst nahe kommt: Titel, Ort, Urheber und
    Rechte wie im Bild, Zusatz-Tags = Stichwoerter ohne Personen, Stadt und Teams (die kommen
    ohnehin dazu), Anhang aus dem Ende der Beschreibung (derive_suffix), GPS als Ort.
    persons: Namen, die nicht in die Zusatz-Tags sollen (Personen-Tags aus Codes).
    """
    template = MatchTemplate(
        name=name or meta.headline,
        headline=meta.headline,
        city=meta.city, sublocation=meta.sublocation,
        **{field_name: getattr(meta, field_name) for field_name in FIXED_FIELDS},
        caption_suffix='', latitude=meta.latitude, longitude=meta.longitude)
    values = {key: getattr(meta, key, '') for key in SUFFIX_FIELDS}
    values['date'] = format_date(taken_at)
    template.caption_suffix = derive_suffix(meta.caption, values)
    skip = {tag.casefold() for tag in [*persons, *template.teams, meta.city] if tag}
    template.extra_tags = unique(tag for tag in meta.keywords if tag.casefold() not in skip)
    return template


def format_date(taken_at):
    """'2026:03:01 18:52:31.035' -> '01.03.26'"""
    match = re.match(r'(\d{4})[:-](\d{2})[:-](\d{2})', taken_at or '')
    if not match:
        return ''
    year, month, day = match.groups()
    return f'{day}.{month}.{year[2:]}'


def unique(values):
    result = []
    for value in values:
        value = (value or '').strip()
        if value and value not in result:
            result.append(value)
    return result


def slug(name):
    return re.sub(r'[^A-Za-z0-9_-]+', '_', name).strip('_') or 'template'


# Dateiformat: TOML mit Kennung, damit beim Oeffnen nicht jede beliebige
# TOML-Datei als Template durchgeht. Beispiel:
#
#     format = "captioner-template"
#     version = 2
#     name = "DEL 2 Heimspiele"
#     headline = ""              # optional fester Titel
#     city = "Bad Nauheim"
#     sublocation = "Colonel-Knight-Stadion"
#     state = "Hessen"
#     country = "Deutschland"
#     extra_tags = ["Eishockey", "DEL2"]
#     caption_suffix = ", {headline}, {city}, {sublocation}, {date}"
#     date = ""                  # optional fester Text fuer {date}, sonst Aufnahmedatum
#     creator = "Florian Dehn"
#     authors_position = "Fotograf"
#     caption_writer = "Florian Dehn"
#     copyright = "© 2026 Florian Dehn"
#     web_statement = "https://example.org/lizenz"
#     source = "chuc.de"
#     category = "Sport"
#     instructions = "Honorarpflichtig. Kontakt: … · IBAN DE…"
#     latitude = 50.37255        # optional, vom Karten-Picker
#     longitude = 8.73845
#
# Version 1 hatte occasion/home/away statt headline; load_file rechnet sie um.
FORMAT_ID = 'captioner-template'
FORMAT_VERSION = 2
FILE_SUFFIX = '.toml'
SERIALIZED_FIELDS = [name for name in MatchTemplate.__dataclass_fields__ if name != 'path']


class TemplateError(ValueError):
    pass


def load_file(path):
    """Liest ein Template aus einer Datei. TemplateError bei falschem Inhalt."""
    path = Path(path).expanduser()
    try:
        with open(path, 'rb') as handle:
            data = tomllib.load(handle)
    except OSError as e:
        raise TemplateError(_('{name}: nicht lesbar ({error})').format(name=path.name, error=e.strerror or e))
    except tomllib.TOMLDecodeError as e:
        raise TemplateError(_('{name}: kein gültiges TOML ({error})').format(name=path.name, error=e))
    # Dateien ohne Kennung stammen aus der ersten Version und sind gueltig
    if data.get('format', FORMAT_ID) != FORMAT_ID:
        raise TemplateError(_('{name}: kein Captioner-Template (format = {format})')
                            .format(name=path.name, format=repr(data.get('format'))))
    if int(data.get('version', 1)) > FORMAT_VERSION:
        raise TemplateError(_('{name}: Template-Version {version} ist neuer als diese App')
                            .format(name=path.name, version=data['version']))
    _upgrade_v1(data)
    values = {key: data[key] for key in SERIALIZED_FIELDS if key in data}
    for key, value in values.items():
        expected = {'extra_tags': list, 'latitude': (int, float), 'longitude': (int, float)}.get(key, str)
        if not isinstance(value, expected) or isinstance(value, bool):
            raise TemplateError(_('{name}: Feld {field} hat den falschen Typ').format(name=path.name, field=repr(key)))
    if ('latitude' in values) != ('longitude' in values) or \
            ('latitude' in values and not valid_coordinates(values['latitude'], values['longitude'])):
        raise TemplateError(_('{name}: latitude/longitude unvollständig oder außerhalb des gültigen Bereichs')
                            .format(name=path.name))
    template = MatchTemplate(**values)
    if not template.name:
        template.name = path.stem
    template.path = str(path)
    return template


def _upgrade_v1(data):
    """Version 1: Titel aus occasion/home/away (nur wenn alle drei da sind)."""
    legacy = [data.pop(key, '') for key in ('occasion', 'home', 'away')]
    if not data.get('headline') and all(isinstance(v, str) and v.strip() for v in legacy):
        occasion, home, away = (v.strip() for v in legacy)
        data['headline'] = f'{occasion} - {home} gegen {away}'


def save_file(template, path):
    """Schreibt das Template in eine Datei und verknuepft es mit ihr."""
    path = Path(path).expanduser()
    if not template.name:
        template.name = template.headline or path.stem
    data = {'format': FORMAT_ID, 'version': FORMAT_VERSION}
    # TOML kennt kein None: fehlende Koordinaten werden weggelassen
    data.update({key: getattr(template, key) for key in SERIALIZED_FIELDS if getattr(template, key) is not None})
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.tmp')
    temp.write_text('# Captioner Spiel-Template (siehe docs/adr/0001-*.md)\n' + tomli_w.dumps(data),
                    encoding='utf-8')
    temp.replace(path)
    template.path = str(path)
    return path


def default_filename(template):
    return slug(template.name or template.headline or 'template') + FILE_SUFFIX


class TemplateStore:
    """
    Templates im Konfigurationsverzeichnis plus beliebige Dateien vom Rechner,
    die geoeffnet wurden (Pfade in Settings.template_files).
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def is_internal(self, template):
        return bool(template.path) and Path(template.path).parent == self.directory

    def list(self, external_paths=()):
        """Alle Templates; zweiter Rueckgabewert: Fehlermeldungen zu unlesbaren Dateien."""
        templates, errors = [], []
        paths = sorted(self.directory.glob('*' + FILE_SUFFIX))
        paths += [Path(p).expanduser() for p in external_paths]
        seen = set()
        for path in paths:
            key = str(path.resolve()) if path.exists() else str(path)
            if key in seen:
                continue
            seen.add(key)
            try:
                templates.append(load_file(path))
            except TemplateError as e:
                errors.append(str(e))
        return templates, errors

    def save(self, template: MatchTemplate):
        """Speichert an Ort und Stelle; neue Templates landen im Konfigurationsverzeichnis."""
        if template.path:
            return save_file(template, template.path)
        if not template.name:
            template.name = template.headline or 'Unbenannt'
        return save_file(template, self._free_path(default_filename(template)))

    def _free_path(self, filename):
        """Neues Template nie ueber ein vorhandenes gleichen Namens schreiben: name-2.toml usw."""
        path = self.directory / filename
        stem, number = path.stem, 2
        while path.exists():
            path = self.directory / f'{stem}-{number}{FILE_SUFFIX}'
            number += 1
        return path

    def delete(self, template: MatchTemplate):
        """Loescht nur Templates im Konfigurationsverzeichnis, nie fremde Dateien."""
        if self.is_internal(template) and Path(template.path).exists():
            Path(template.path).unlink()
