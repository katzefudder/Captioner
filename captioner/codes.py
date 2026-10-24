"""
Code replacement as in a photo culling workflow tool:

    "Zweikampf #bi99# gegen #bn23#"
    -> "Zweikampf -99- John Doe (Bietigheim Steelers) gegen -23- Marius Erk (EC Bad Nauheim)"

Codes are resolved when saving; a code never ends up in the file. Unknown codes
block saving (ADR 0001, item 5).
"""
import re
from dataclasses import dataclass, field

# "-99- John Doe (Bietigheim Steelers)" or "Tim Kehler (Coach Bietigheim Steelers)"
PERSON_PATTERN = re.compile(r'^(?:-\d{1,3}-\s*)?(?P<name>[^()]+?)\s*\((?P<team>[^)]*)\)\s*$')


@dataclass
class Resolution:
    text: str
    unknown: list = field(default_factory=list)
    used: list = field(default_factory=list)  # entries in order of appearance

    @property
    def ok(self):
        return not self.unknown

    @property
    def persons(self):
        """Person names from the codes used, without duplicates."""
        names = []
        for entry in self.used:
            name = person_name(entry.replacement)
            if name and name not in names:
                names.append(name)
        return names


def code_pattern(delimiter):
    d = re.escape(delimiter)
    return re.compile(d + r'(?P<code>[A-Za-z0-9_]+)' + d)


def resolve(text, roster, delimiter='#', wrap=None):
    """wrap(replacement) frames every replacement, e.g. for highlighting in the preview."""
    used, unknown = [], []

    def replace(match):
        code = match.group('code')
        entry = roster.lookup(code) if roster else None
        if entry is None:
            if code not in unknown:
                unknown.append(code)
            return match.group(0)
        used.append(entry)
        return wrap(entry.replacement) if wrap else entry.replacement

    resolved = code_pattern(delimiter).sub(replace, text or '')
    return Resolution(text=resolved, unknown=unknown, used=used)


def person_name(replacement):
    match = PERSON_PATTERN.match(replacement or '')
    return match.group('name').strip() if match else None


def person_names_in(text):
    """Names of people in the text such as "-23- Max Muster (EC Bad Nauheim)", even without a roster."""
    return [match.group(1).strip() for match in re.finditer(r'-\d{1,3}-\s*([^(),]+?)\s*\([^)]*\)', text or '')]


def open_code_prefix(text_before_cursor, delimiter='#'):
    """
    The partial code right before the cursor, for autocompletion:
    "Zweikampf #bi" -> "bi". None if the cursor is not inside a code.
    """
    index = text_before_cursor.rfind(delimiter)
    if index < 0:
        return None
    # An even number of delimiters before it means: the last one opens a code
    if text_before_cursor[:index].count(delimiter) % 2 == 1:
        return None
    prefix = text_before_cursor[index + len(delimiter):]
    if re.fullmatch(r'[A-Za-z0-9_]*', prefix):
        return prefix
    return None


def persons_in(text, roster):
    """People whose roster replacement appears literally in the (already resolved) text."""
    if not text or not roster:
        return []
    names = []
    for entry in roster.entries.values():
        if entry.replacement in text:
            name = person_name(entry.replacement)
            if name and name not in names:
                names.append(name)
    return names
