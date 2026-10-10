"""
Spiel-Templates, der Ersatz fuer das "IPTC Stationery Pad" (ADR 0001, Punkt 6).

Die Headline hat das feste Format "<Anlass> - <Heim> gegen <Gast>", weil
recognition/lib/matches.py den Spielkontext genau daraus liest.
"""
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w


DEFAULT_CAPTION_SUFFIX = ', {headline}, {city}, {sublocation}, {date}'


@dataclass
class MatchTemplate:
    name: str = ''
    occasion: str = ''  # "in der DEL 2"
    home: str = ''      # Abschnitt im Roster, z. B. "EC Bad Nauheim"
    away: str = ''
    city: str = ''
    sublocation: str = ''
    extra_tags: list = field(default_factory=list)  # "Eishockey", "DEL2", "2026/27"
    # Wird an jede Bildunterschrift gehaengt, wie bisher im Workflow-Tool fuer die Auswahl von Fotos:
    # "..., DEL 2 - EC Bad Nauheim gegen Eisbaeren Regensburg, Bad Nauheim, Colonel-Knight-Stadion, 01.03.26"
    caption_suffix: str = DEFAULT_CAPTION_SUFFIX
    # Woher das Template stammt; wird nicht in die Datei geschrieben
    path: str = field(default='', compare=False, repr=False)

    @property
    def headline(self):
        if not (self.occasion and self.home and self.away):
            return ''
        return f'{self.occasion} - {self.home} gegen {self.away}'

    @property
    def keywords(self):
        """Galerie-Tags ohne Personen; Personen kommen pro Bild dazu."""
        return unique([self.home, self.away, self.city, *self.extra_tags])

    @property
    def teams(self):
        return [team for team in (self.home, self.away) if team]

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
#     version = 1
#     name = "BN-BI"
#     occasion = "DEL 2"
#     home = "EC Bad Nauheim"
#     away = "Bietigheim Steelers"
#     city = "Bad Nauheim"
#     sublocation = "Colonel-Knight-Stadion"
#     extra_tags = ["Eishockey", "DEL2"]
#     caption_suffix = ", {headline}, {city}, {sublocation}, {date}"
FORMAT_ID = 'captioner-template'
FORMAT_VERSION = 1
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
        raise TemplateError(f'{path.name}: nicht lesbar ({e.strerror or e})')
    except tomllib.TOMLDecodeError as e:
        raise TemplateError(f'{path.name}: kein gültiges TOML ({e})')
    # Dateien ohne Kennung stammen aus der ersten Version und sind gueltig
    if data.get('format', FORMAT_ID) != FORMAT_ID:
        raise TemplateError(f'{path.name}: kein Captioner-Template (format = {data.get("format")!r})')
    if int(data.get('version', 1)) > FORMAT_VERSION:
        raise TemplateError(f'{path.name}: Template-Version {data["version"]} ist neuer als diese App')
    values = {key: data[key] for key in SERIALIZED_FIELDS if key in data}
    for key, value in values.items():
        expected = list if key == 'extra_tags' else str
        if not isinstance(value, expected):
            raise TemplateError(f'{path.name}: Feld {key!r} hat den falschen Typ')
    template = MatchTemplate(**values)
    if not template.headline:
        raise TemplateError(f'{path.name}: Anlass, Heim und Gast fehlen')
    if not template.name:
        template.name = path.stem
    template.path = str(path)
    return template


def save_file(template, path):
    """Schreibt das Template in eine Datei und verknuepft es mit ihr."""
    path = Path(path).expanduser()
    if not template.name:
        template.name = template.headline or path.stem
    data = {'format': FORMAT_ID, 'version': FORMAT_VERSION}
    data.update({key: getattr(template, key) for key in SERIALIZED_FIELDS})
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
        return save_file(template, self.directory / default_filename(template))

    def delete(self, template: MatchTemplate):
        """Loescht nur Templates im Konfigurationsverzeichnis, nie fremde Dateien."""
        if self.is_internal(template) and Path(template.path).exists():
            Path(template.path).unlink()
