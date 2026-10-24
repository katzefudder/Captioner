"""
Rename all images of a folder by a scheme, without Qt.

* Name `<free>_<NNN>`: the user chooses the front part (suggested: date + abbreviations,
  e.g. 20261023_MEM_EPC), Captioner appends the number. Counting starts at 1, zero-padded
  to three digits (more if there are over 999 images).
* A group (RAW, JPG/DNG, sidecar) gets one number; the extensions stay as they are.
* First all files to temporary names (".<name>.captioner-rename"), then to the target
  names: that way a target name may be the old name of another image (renaming twice).
  If a step fails, everything renamed so far is renamed back.
* Target names that belong to a file outside the renaming block it up front (conflicts).
"""
import datetime
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .files import replace_file
from .i18n import _

TEMP_SUFFIX = '.captioner-rename'
# not allowed in file names on Windows or macOS (plus control characters)
FORBIDDEN = set('/\\:*?"<>|')
DATE_PREFIX = re.compile(r'^\d{8}(?=_|$)')


class RenameError(RuntimeError):
    pass


@dataclass
class Move:
    source: Path
    target: Path


def today():
    return datetime.date.today().strftime('%Y%m%d')


def default_prefix(last=''):
    """Suggestion for the field: the last name with today's date in front, else "<today>_"."""
    if DATE_PREFIX.match(last):
        return DATE_PREFIX.sub(today(), last)
    return f'{today()}_'


def valid_prefix(text):
    """Not empty, no forbidden characters, no leading dot (hidden file)."""
    return (bool(text) and not text.startswith('.') and text == text.strip()
            and not any(c in FORBIDDEN or ord(c) < 32 for c in text))


def stem(prefix, number, width=3):
    """Underscore as separator before the number, unless the name already ends with one."""
    separator = '' if prefix.endswith(('_', '-')) else '_'
    return f'{prefix}{separator}{number:0{width}d}'


def width(count):
    return max(3, len(str(count)))


def item_files(item):
    """All files of an image: RAW, embedded ones, existing sidecar."""
    paths = list(item.files)
    if item.sidecar and item.sidecar.exists():
        paths.append(item.sidecar)
    return paths


def plan(items, prefix):
    """Renames in the order of items; files that already have the right name are left out."""
    digits = width(len(items))
    moves = []
    for number, item in enumerate(items, start=1):
        new_stem = stem(prefix, number, digits)
        for path in item_files(item):
            target = path.with_name(new_stem + path.suffix)
            if target.name != path.name:
                moves.append(Move(path, target))
    return moves


def conflicts(moves):
    """Target names that already exist and are not renamed themselves."""
    sources = {_key(move.source) for move in moves}
    return [move.target for move in moves if _key(move.target) not in sources and move.target.exists()]


def apply(moves):
    """Rename in two steps; on an error everything goes back and RenameError is raised."""
    if conflicts(moves):
        raise RenameError(_('Zieldateien existieren schon.'))
    done = []    # (from, to) in order, for renaming back
    try:
        temps = []
        for move in moves:
            temp = move.source.with_name(f'.{move.source.name}{TEMP_SUFFIX}')
            _rename(move.source, temp)
            done.append((move.source, temp))
            temps.append(temp)
        for move, temp in zip(moves, temps):
            _rename(temp, move.target)
            done.append((temp, move.target))
    except OSError as error:
        for source, target in reversed(done):
            try:
                replace_file(target, source)
            except OSError:
                pass
        raise RenameError(str(error)) from error


def _rename(source, target):
    try:
        replace_file(source, target)
    except PermissionError:
        raise PermissionError(_('{name}: von einem anderen Programm geöffnet').format(name=Path(source).name))


def _key(path):
    # macOS/Windows: file names are case-insensitive (DSC_0001.xmp == DSC_0001.XMP)
    return os.path.normcase(str(path)).casefold()

