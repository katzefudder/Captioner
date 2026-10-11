"""
Roster-Dateien (Code-Replacement-Format) laden und zusammenfuehren.

Format (UTF-8): eine Zeile pro Code, Code und Ersetzung durch Tab getrennt.
Zeilen ohne Tab sind Leerzeilen oder Abschnittskoepfe "- <Team> -", die die
folgenden Codes einem Team zuordnen.

    - Bietigheim Steelers -

    bi99	-99- John Doe (Bietigheim Steelers)

Quellen sind URLs oder lokale Dateien. Jede erfolgreich geladene URL wird als
"letzte gute Version" abgelegt, damit in der Halle ohne Netz weitergearbeitet
werden kann (ADR 0001, Punkt 5).
"""
import hashlib
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SECTION_PATTERN = re.compile(r'^-\s*(?P<team>.+?)\s*-$')
GITHUB_BLOB_PATTERN = re.compile(
    r'^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/blob/(?P<rest>.+)$')

FETCH_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Entry:
    code: str
    replacement: str
    team: str  # Abschnittskopf, None wenn die Datei keine Abschnitte hat
    source: str


@dataclass
class SourceStatus:
    source: str
    ok: bool
    origin: str  # 'datei', 'netz', 'cache', 'letzte gute Version', 'fehlt'
    message: str = ''
    fetched_at: float = None


@dataclass
class Roster:
    entries: dict = field(default_factory=dict)  # code -> Entry
    conflicts: list = field(default_factory=list)  # (code, Entry, Entry)
    status: list = field(default_factory=list)  # SourceStatus je Quelle
    digest: str = ''

    def lookup(self, code):
        return self.entries.get(code) or self.entries.get(code.lower())

    @property
    def teams(self):
        seen = []
        for entry in self.entries.values():
            if entry.team and entry.team not in seen:
                seen.append(entry.team)
        return seen

    def codes_for_team(self, team):
        return [entry for entry in self.entries.values() if entry.team == team]

    @property
    def is_usable(self):
        return bool(self.entries)


def parse(text, source=''):
    """Liest eine Roster-Datei. Gibt eine Liste von Entry zurueck."""
    entries = []
    team = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip('\r\n')
        if '\t' not in line:
            match = SECTION_PATTERN.match(line.strip())
            if match:
                team = match.group('team')
            continue
        code, replacement = line.split('\t', 1)
        code, replacement = code.strip(), replacement.strip()
        if code and replacement:
            entries.append(Entry(code=code, replacement=replacement, team=team, source=source))
    return entries


def decode(data: bytes):
    """
    Roster-Dateien kommen nicht immer als UTF-8: unter Windows gespeicherte
    Roster-Dateien sind oft UTF-16 (mit BOM) oder Windows-1252.
    """
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16')
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('cp1252', errors='replace')


# --- Bearbeiten (Roster-Editor) ------------------------------------------------

@dataclass
class RosterFile:
    """Eine lokale Roster-Datei mit allem, was zum unveraenderten Zurueckschreiben noetig ist."""
    path: Path
    text: str
    encoding: str        # 'utf-8', 'utf-8-sig' (mit BOM), 'utf-16' (mit BOM), 'cp1252'
    newline: str         # '\n' oder '\r\n', wie in der Datei
    mtime: float
    lossy: bool = False  # cp1252 mit unbekannten Bytes: Speichern veraendert sie


def read_file(path):
    path = Path(path).expanduser()
    data = path.read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        text, encoding, lossy = data.decode('utf-16'), 'utf-16', False
    elif data.startswith(b'\xef\xbb\xbf'):
        text, encoding, lossy = data.decode('utf-8-sig'), 'utf-8-sig', False
    else:
        try:
            text, encoding, lossy = data.decode('utf-8'), 'utf-8', False
        except UnicodeDecodeError:
            text = data.decode('cp1252', errors='replace')
            encoding, lossy = 'cp1252', '\ufffd' in text
    newline = '\r\n' if '\r\n' in text else '\n'
    return RosterFile(path, text.replace('\r\n', '\n'), encoding, newline, path.stat().st_mtime, lossy)


def write_file(roster_file, text, encoding=None):
    """
    Schreibt in Kodierung und Zeilenenden der Datei (oder encoding), ueber eine
    Zwischendatei. UnicodeEncodeError, wenn ein Zeichen in der Kodierung fehlt.
    """
    encoding = encoding or roster_file.encoding
    data = text.replace('\r\n', '\n').replace('\n', roster_file.newline).encode(encoding)
    path = roster_file.path
    temp = path.with_name(f'.{path.name}.captioner-tmp')
    try:
        temp.write_bytes(data)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()
    roster_file.text, roster_file.encoding = text, encoding
    roster_file.mtime = path.stat().st_mtime
    roster_file.lossy = False


@dataclass(frozen=True)
class Problem:
    line: int       # 1-basiert
    message: str
    serious: bool   # wirkt sich aus (Zeile ignoriert, Widerspruch); sonst nur Hinweis


def check(text):
    """Zeilen, die parse() ignoriert oder die sich widersprechen, mit Zeilennummer."""
    problems = []
    seen = {}  # code -> (Zeile, Ersetzung)
    for number, line in enumerate(text.split('\n'), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if '\t' not in line:
            if not SECTION_PATTERN.match(stripped):
                problems.append(Problem(number, 'kein Tab zwischen Code und Ersetzung (und kein '
                                                '„- Team -“): Zeile wird ignoriert', True))
            continue
        code, replacement = (part.strip() for part in line.split('\t', 1))
        if not code or not replacement:
            problems.append(Problem(number, 'Code fehlt' if not code else 'Ersetzung fehlt', True))
            continue
        if code in seen:
            first, previous = seen[code]
            if previous != replacement:
                problems.append(Problem(number, f'„{code}“ steht schon in Zeile {first} mit anderer Ersetzung '
                                                '(widersprüchlich, wird nicht verwendet)', True))
            else:
                problems.append(Problem(number, f'„{code}“ doppelt (wie Zeile {first})', False))
            continue
        seen[code] = (number, replacement)
    return problems


def raw_url(url):
    """GitHub-blob-URLs liefern HTML. Umschreiben auf raw.githubusercontent.com."""
    match = GITHUB_BLOB_PATTERN.match(url)
    if not match:
        return url
    return 'https://raw.githubusercontent.com/{owner}/{repo}/{rest}'.format(**match.groupdict())


def is_url(source):
    return source.startswith('http://') or source.startswith('https://')


class RosterLoader:
    """Laedt alle Quellen, mit Cache und Rueckfall auf die letzte gute Version."""

    def __init__(self, cache_dir: Path, ttl_minutes=60, fetch=None):
        self.cache_dir = Path(cache_dir) / 'rosters'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = max(0, int(ttl_minutes)) * 60
        self._fetch = fetch or _http_get

    def cached_text(self, source):
        """Zuletzt geladene Fassung einer URL-Quelle, oder None."""
        cached = self._cache_file(source)
        return cached.read_text(encoding='utf-8') if cached.exists() else None

    def _cache_file(self, source):
        name = hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]
        return self.cache_dir / f'{name}.txt'

    def _load_source(self, source, force):
        if not is_url(source):
            path = Path(source).expanduser()
            try:
                text = decode(path.read_bytes())
            except OSError as e:
                return None, SourceStatus(source, False, 'fehlt', str(e))
            if not parse(text):
                return None, SourceStatus(source, False, 'fehlt', 'keine Codes gefunden (Code und Ersetzung durch Tab getrennt?)')
            return text, SourceStatus(source, True, 'datei', fetched_at=path.stat().st_mtime)

        cached = self._cache_file(source)
        if not force and cached.exists() and time.time() - cached.stat().st_mtime < self.ttl_seconds:
            return (cached.read_text(encoding='utf-8'),
                    SourceStatus(source, True, 'cache', fetched_at=cached.stat().st_mtime))

        try:
            text = self._fetch(raw_url(source))
            if not parse(text):
                raise ValueError('keine Codes gefunden (falsche URL oder HTML statt Textdatei?)')
        except Exception as e:
            if cached.exists():
                return (cached.read_text(encoding='utf-8'),
                        SourceStatus(source, True, 'letzte gute Version',
                                     f'nicht erreichbar: {e}', cached.stat().st_mtime))
            return None, SourceStatus(source, False, 'fehlt', f'nicht erreichbar: {e}')

        cached.write_text(text, encoding='utf-8')
        return text, SourceStatus(source, True, 'netz', fetched_at=time.time())

    def load(self, sources, force=False):
        roster = Roster()
        texts = []
        for source in [s.strip() for s in sources if s and s.strip()]:
            text, status = self._load_source(source, force)
            roster.status.append(status)
            if text is None:
                continue
            texts.append(text)
            for entry in parse(text, source):
                existing = roster.entries.get(entry.code)
                if existing and existing.replacement != entry.replacement:
                    # Bewusst kein "letzte Quelle gewinnt" (ADR 0001, Punkt 5)
                    roster.conflicts.append((entry.code, existing, entry))
                    continue
                roster.entries.setdefault(entry.code, entry)
        roster.digest = hashlib.sha256('\n'.join(texts).encode('utf-8')).hexdigest()[:12]
        return roster


def _http_get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'captioner'})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        return decode(response.read())
