"""
Code-Replacement wie in einem Workflow-Tool fuer die Auswahl von Fotos:

    "Zweikampf #bi99# gegen #bn23#"
    -> "Zweikampf -99- John Doe (Bietigheim Steelers) gegen -23- Marius Erk (EC Bad Nauheim)"

Aufgeloest wird beim Speichern; in die Datei kommt nie ein Code. Unbekannte
Codes blockieren das Speichern (ADR 0001, Punkt 5).
"""
import re
from dataclasses import dataclass, field

# "-99- John Doe (Bietigheim Steelers)" bzw. "Tim Kehler (Coach Bietigheim Steelers)"
PERSON_PATTERN = re.compile(r'^(?:-\d{1,3}-\s*)?(?P<name>[^()]+?)\s*\((?P<team>[^)]*)\)\s*$')


@dataclass
class Resolution:
    text: str
    unknown: list = field(default_factory=list)
    used: list = field(default_factory=list)  # Entry in Reihenfolge des Auftretens

    @property
    def ok(self):
        return not self.unknown

    @property
    def persons(self):
        """Personennamen aus den verwendeten Codes, ohne Doppelte."""
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
    """wrap(ersetzung) rahmt jede Ersetzung ein, z. B. zum Hervorheben in der Vorschau."""
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
    """Namen aus Personen im Text wie "-23- Max Muster (EC Bad Nauheim)", auch ohne Roster."""
    return [match.group(1).strip() for match in re.finditer(r'-\d{1,3}-\s*([^(),]+?)\s*\([^)]*\)', text or '')]


def open_code_prefix(text_before_cursor, delimiter='#'):
    """
    Der angefangene Code direkt vor dem Cursor, fuer die Autovervollstaendigung:
    "Zweikampf #bi" -> "bi". None, wenn der Cursor nicht in einem Code steht.
    """
    index = text_before_cursor.rfind(delimiter)
    if index < 0:
        return None
    # Eine gerade Anzahl Trennzeichen davor heisst: das letzte oeffnet einen Code
    if text_before_cursor[:index].count(delimiter) % 2 == 1:
        return None
    prefix = text_before_cursor[index + len(delimiter):]
    if re.fullmatch(r'[A-Za-z0-9_]*', prefix):
        return prefix
    return None


def persons_in(text, roster):
    """Personen, deren Roster-Ersetzung woertlich im (bereits aufgeloesten) Text steht."""
    if not text or not roster:
        return []
    names = []
    for entry in roster.entries.values():
        if entry.replacement in text:
            name = person_name(entry.replacement)
            if name and name not in names:
                names.append(name)
    return names
