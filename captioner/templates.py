"""
Game templates, the replacement for the "IPTC Stationery Pad" (ADR 0001, item 6).

A template carries what is the same for many images: location (city, arena,
state, country), creator and rights, extra tags, the suffix appended to the caption
and optionally a fixed headline. Home and away are in the headline or follow from
the codes in the caption.

The headline has the fixed format "<occasion> - <home> gegen <away>", because
recognition/lib/matches.py reads the game context from exactly that; parse_headline
reads the teams from it (order of the code suggestions).
"""
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w

from .geo import valid_coordinates
from .i18n import _


DEFAULT_CAPTION_SUFFIX = ', {headline}, {city}, {sublocation}, {date}'

# as in app/recognition/lib/matches.py
HEADLINE_PATTERN = re.compile(r'^(?P<occasion>.+?)\s+-\s+(?P<home>.+?)\s+gegen\s+(?P<away>.+?)$')


def parse_headline(text):
    """'DEL 2 - EC Bad Nauheim gegen Eisbaeren Regensburg' -> (occasion, home, away), otherwise None."""
    match = HEADLINE_PATTERN.match((text or '').strip())
    return (match.group('occasion'), match.group('home'), match.group('away')) if match else None


# Fields the template writes into every image when saving, if they are filled
# (names as in scanner.Metadata); empty ones keep the image's value
FIXED_FIELDS = ('state', 'country', 'country_code', 'creator', 'contact_email', 'authors_position', 'credit',
                'caption_writer', 'copyright', 'web_statement', 'source', 'category', 'instructions')

# placeholders in the suffix ({city} etc.): field names as in scanner.Metadata, plus {date}
SUFFIX_FIELDS = ('headline', 'city', 'sublocation') + FIXED_FIELDS


@dataclass
class MatchTemplate:
    name: str = ''
    # optional fixed headline "<occasion> - <home> gegen <away>"; empty = enter it in the panel
    headline: str = ''
    city: str = ''
    sublocation: str = ''
    state: str = ''             # state/province
    country: str = ''
    country_code: str = ''      # ISO 3166 with three letters, e.g. "DEU"
    extra_tags: list = field(default_factory=list)  # "Eishockey", "DEL2", "2026/27"
    # creator and rights (Lightroom: "IPTC Copyright" / "IPTC Creator")
    creator: str = ''           # photographer, dc:creator
    contact_email: str = ''     # photographer's email (IPTC Creator Contact Info)
    authors_position: str = ''  # "Fotograf", "Pressefotograf"
    credit: str = ''            # credit line, e.g. "Florian Dehn/chuc.de"
    caption_writer: str = ''    # who writes the captions
    copyright: str = ''         # "© 2026 Florian Dehn"
    web_statement: str = ''     # URL of the terms of use/license
    source: str = ''            # source/agency
    category: str = ''          # photoshop:Category, e.g. "Sport"
    instructions: str = ''      # instructions (IPTC Special Instructions): contact, bank details
    # Appended to every caption, as before in the photo culling workflow tool:
    # "..., DEL 2 - EC Bad Nauheim gegen Eisbaeren Regensburg, Bad Nauheim, Colonel-Knight-Stadion, 01.03.26"
    caption_suffix: str = DEFAULT_CAPTION_SUFFIX
    # fixed text for {date}, e.g. "18.10.26" for an upcoming game; empty = capture date
    date: str = ''
    # Coordinates of the place (map picker), so they are passed on with the file;
    # missing from the file as long as none are set
    latitude: float = None
    longitude: float = None
    # where the template comes from; not written to the file
    path: str = field(default='', compare=False, repr=False)

    @property
    def keywords(self):
        """Gallery tags without people; people are added per image."""
        return unique([*self.teams, self.city, *self.extra_tags])

    @property
    def teams(self):
        """Home and away from the fixed headline, otherwise empty."""
        parsed = parse_headline(self.headline)
        return list(parsed[1:]) if parsed else []

    def fixed_values(self):
        """Filled location/rights fields that go into every image when saving."""
        return {name: getattr(self, name) for name in FIXED_FIELDS if getattr(self, name)}

    def date_mismatch(self, taken_at):
        """Fixed date that doesn't match the capture date: (template, image), otherwise None."""
        fixed, taken = self.date.strip(), format_date(taken_at)
        return (fixed, taken) if fixed and taken and fixed != taken else None

    def display_name(self):
        return self.name or self.headline or 'Unbenannt'

    def field_values(self, meta):
        """Location/rights as they will be in the image after saving: template, else the image's value."""
        return {name: getattr(self, name) or getattr(meta, name, '') or '' for name in FIXED_FIELDS}

    def suffix_for(self, taken_at='', date=None, mark=None, **fields):
        """
        Suffix with values filled in ({headline}, {city}, ... from SUFFIX_FIELDS, {date});
        empty placeholders are dropped together with their comma. Fields passed in (the
        values actually saved, see field_values) take precedence over the template's.
        date: finished text; otherwise the template's fixed date, otherwise from taken_at.
        mark(key, value): wraps every inserted value (preview in the template dialog).
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
        """Appends the suffix unless it is already there."""
        caption = (caption or '').strip()
        suffix = self.suffix_for(taken_at, **values)
        if not caption or not suffix or caption.endswith(suffix.strip()):
            return caption
        if suffix.startswith(',') or suffix.startswith(' '):
            return caption.rstrip(',') + suffix
        return f'{caption} {suffix}'


# order when several fields have the same value (photographer = caption writer)
_SUFFIX_PRIORITY = ('headline', 'city', 'sublocation', 'date', 'state', 'country') + \
    tuple(name for name in FIXED_FIELDS if name not in ('state', 'country'))


def derive_suffix(caption, values):
    """
    Suffix of a finished caption as placeholders: "Jubel, DEL 2 - A gegen B, Bad Nauheim, ,
    20.02.24" with the image's values -> ", {headline}, {city}, {sublocation}, {date}". Searches
    from the end for segments (separated by commas) that match exactly one value; an empty
    segment after {city} becomes {sublocation} (empty placeholders are dropped anyway).
    Without a recognizable suffix: ''.
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
            parts.insert(0, None)            # empty segment ", ,"
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
    Template that comes as close as possible to an image's caption: headline, location,
    creator and rights as in the image, extra tags = keywords without people, city and teams
    (those are added anyway), suffix from the end of the caption (derive_suffix), GPS as place.
    persons: names that must not go into the extra tags (person tags from codes).
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


# File format: TOML with an identifier, so that not just any TOML file passes as a
# template when opened. Example:
#
#     format = "captioner-template"
#     version = 2
#     name = "DEL 2 Heimspiele"
#     headline = ""              # optional fixed headline
#     city = "Bad Nauheim"
#     sublocation = "Colonel-Knight-Stadion"
#     state = "Hessen"
#     country = "Deutschland"
#     extra_tags = ["Eishockey", "DEL2"]
#     caption_suffix = ", {headline}, {city}, {sublocation}, {date}"
#     date = ""                  # optional fixed text for {date}, otherwise capture date
#     creator = "Florian Dehn"
#     authors_position = "Fotograf"
#     caption_writer = "Florian Dehn"
#     copyright = "© 2026 Florian Dehn"
#     web_statement = "https://example.org/lizenz"
#     source = "chuc.de"
#     category = "Sport"
#     instructions = "Honorarpflichtig. Kontakt: … · IBAN DE…"
#     latitude = 50.37255        # optional, from the map picker
#     longitude = 8.73845
#
# Version 1 had occasion/home/away instead of headline; load_file converts them.
FORMAT_ID = 'captioner-template'
FORMAT_VERSION = 2
FILE_SUFFIX = '.toml'
SERIALIZED_FIELDS = [name for name in MatchTemplate.__dataclass_fields__ if name != 'path']


class TemplateError(ValueError):
    pass


def load_file(path):
    """Reads a template from a file. TemplateError for wrong content."""
    path = Path(path).expanduser()
    try:
        with open(path, 'rb') as handle:
            data = tomllib.load(handle)
    except OSError as e:
        raise TemplateError(_('{name}: nicht lesbar ({error})').format(name=path.name, error=e.strerror or e))
    except tomllib.TOMLDecodeError as e:
        raise TemplateError(_('{name}: kein gültiges TOML ({error})').format(name=path.name, error=e))
    # files without an identifier come from the first version and are valid
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
    """Version 1: headline from occasion/home/away (only if all three are present)."""
    legacy = [data.pop(key, '') for key in ('occasion', 'home', 'away')]
    if not data.get('headline') and all(isinstance(v, str) and v.strip() for v in legacy):
        occasion, home, away = (v.strip() for v in legacy)
        data['headline'] = f'{occasion} - {home} gegen {away}'


def save_file(template, path):
    """Writes the template to a file and links it to that file."""
    path = Path(path).expanduser()
    if not template.name:
        template.name = template.headline or path.stem
    data = {'format': FORMAT_ID, 'version': FORMAT_VERSION}
    # TOML has no None: missing coordinates are left out
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
    Templates in the configuration directory plus any files from the computer that
    were opened (paths in Settings.template_files).
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def is_internal(self, template):
        return bool(template.path) and Path(template.path).parent == self.directory

    def list(self, external_paths=()):
        """All templates; second return value: error messages for unreadable files."""
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
        """Saves in place; new templates go into the configuration directory."""
        if template.path:
            return save_file(template, template.path)
        if not template.name:
            template.name = template.headline or 'Unbenannt'
        return save_file(template, self._free_path(default_filename(template)))

    def _free_path(self, filename):
        """Never write a new template over an existing one with the same name: name-2.toml etc."""
        path = self.directory / filename
        stem, number = path.stem, 2
        while path.exists():
            path = self.directory / f'{stem}-{number}{FILE_SUFFIX}'
            number += 1
        return path

    def delete(self, template: MatchTemplate):
        """Only deletes templates in the configuration directory, never foreign files."""
        if self.is_internal(template) and Path(template.path).exists():
            Path(template.path).unlink()
