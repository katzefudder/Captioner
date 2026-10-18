"""
Release-Version in pyproject.toml eintragen, nur in der Arbeitskopie des Builds (Release-Workflow):
<major>.<minor> aus dem Repo + Laufnummer, z. B. 0.2.41. Danach sehen poetry install, Tests und
version() (Paket-Metadaten) dieselbe Nummer wie die Specs (CAPTIONER_VERSION). Ins Repo
zurueckgeschrieben wird nichts.

    python scripts/set_version.py 0.2.41     # oder ohne Argument: $CAPTIONER_VERSION
"""
import os
import re
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / 'pyproject.toml'


def set_version(text, version):
    """Nur die Zeile version = "..." im Abschnitt [project]."""
    match = re.search(r'(?ms)^\[project\]\n(.*?)(?=^\[|\Z)', text)
    if not match:
        raise ValueError('pyproject.toml: Abschnitt [project] fehlt')
    section, count = re.subn(r'(?m)^version\s*=\s*"[^"]*"', f'version = "{version}"', match.group(1), count=1)
    if not count:
        raise ValueError('pyproject.toml: version fehlt in [project]')
    return text[:match.start(1)] + section + text[match.end(1):]


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CAPTIONER_VERSION', '')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        sys.exit(f'Keine gueltige Version: {version!r} (erwartet z. B. 0.2.41)')
    PYPROJECT.write_text(set_version(PYPROJECT.read_text(encoding='utf-8'), version), encoding='utf-8')
    print(f'pyproject.toml: version = "{version}"')


if __name__ == '__main__':
    main()
