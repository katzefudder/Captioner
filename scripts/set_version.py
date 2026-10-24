"""
Write the release version into pyproject.toml, only in the build's working copy (release
workflow): <major>.<minor> from the repo + run number, e.g. 0.2.41. Afterwards poetry install,
tests and version() (package metadata) see the same number as the specs (CAPTIONER_VERSION).
Nothing is written back to the repo.

    python scripts/set_version.py 0.2.41     # or without argument: $CAPTIONER_VERSION
"""
import os
import re
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / 'pyproject.toml'


def set_version(text, version):
    """Only the line version = "..." in the [project] section."""
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
