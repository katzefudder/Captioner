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
FIXED_FIELDS = ('state', 'country', 'creator', 'authors_position', 'caption_writer',
                'copyright', 'web_statement', 'source', 'category')


@dataclass
class MatchTemplate:
    name: str = ''
    # Optional fester Titel "<Anlass> - <Heim> gegen <Gast>"; leer = im Panel eintragen
    headline: str = ''
    city: str = ''
    sublocation: str = ''
    state: str = ''             # Bundesland
    country: str = ''
    extra_tags: list = field(default_factory=list)  # "Eishockey", "DEL2", "2026/27"
    # Urheber und Rechte (Lightroom: "IPTC-Copyright" / "IPTC-Ersteller")
    creator: str = ''           # Fotograf, dc:creator
    authors_position: str = ''  # "Fotograf", "Pressefotograf"
    caption_writer: str = ''    # wer beschriftet
    copyright: str = ''         # "© 2026 Florian Dehn"
    web_statement: str = ''     # URL zu Nutzungsbedingungen/Lizenz
    source: str = ''            # Quelle/Agentur
    category: str = ''          # photoshop:Category, z. B. "Sport"
    # Wird an jede Bildunterschrift gehaengt, wie bisher im Workflow-Tool fuer die Auswahl von Fotos:
    # "..., DEL 2 - EC Bad Nauheim gegen Eisbaeren Regensburg, Bad Nauheim, Colonel-Knight-Stadion, 01.03.26"
    caption_suffix: str = DEFAULT_CAPTION_SUFFIX
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

    def display_name(self):
        return self.name or self.headline or 'Unbenannt'

    def suffix_for(self, taken_at='', headline=None, city=None, sublocation=None):
        """
        Suffix mit eingesetzten Werten; leere Platzhalter fallen samt Komma weg.
        Uebergebene Werte (die tatsaechlich gespeicherten Felder) haben Vorrang
        vor denen des Templates.
        """
        if not self.caption_suffix:
            return ''
        values = {
            'headline': self.headline if headline is None else headline,
            'city': self.city if city is None else city,
            'sublocation': self.sublocation if sublocation is None else sublocation,
            'date': format_date(taken_at),
        }
        text = self.caption_suffix
        for key, value in values.items():
            text = text.replace('{' + key + '}', value)
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
#     creator = "Florian Dehn"
#     authors_position = "Fotograf"
#     caption_writer = "Florian Dehn"
#     copyright = "© 2026 Florian Dehn"
#     web_statement = "https://example.org/lizenz"
#     source = "chuc.de"
#     category = "Sport"
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
