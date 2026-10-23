"""
Alle Bilder eines Ordners nach Schema umbenennen, ohne Qt.

* Schema `<JJJJMMTT>_<HEIM>_<GAST>_<NNN>`, z. B. 20261023_MEM_EPC_001. Gezaehlt wird ab 1,
  mit Nullen auf drei Stellen (mehr, wenn es ueber 999 Bilder sind).
* Eine Gruppe (RAW, JPG/DNG, Sidecar) bekommt eine Nummer; die Endungen bleiben, wie sie sind.
* Erst alle Dateien auf Zwischennamen (".<name>.captioner-rename"), dann auf die Zielnamen:
  so darf ein Zielname der alte Name eines anderen Bildes sein (zweimal umbenennen).
  Schlaegt ein Schritt fehl, wird alles bisher Umbenannte zurueckbenannt.
* Zielnamen, die einer Datei ausserhalb der Umbenennung gehoeren, blockieren vorher (conflicts).
"""
import datetime
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .files import replace_file
from .i18n import _

TEMP_SUFFIX = '.captioner-rename'
# Kuerzel landen im Dateinamen: nur Buchstaben, Ziffern und Bindestrich
CODE_PATTERN = re.compile(r'[A-Za-z0-9-]+')


class RenameError(RuntimeError):
    pass


@dataclass
class Move:
    source: Path
    target: Path


def today():
    return datetime.date.today().strftime('%Y%m%d')


def valid_date(text):
    """JJJJMMTT und ein echtes Datum."""
    if not re.fullmatch(r'\d{8}', text):
        return False
    try:
        datetime.datetime.strptime(text, '%Y%m%d')
    except ValueError:
        return False
    return True


def valid_code(text):
    return bool(CODE_PATTERN.fullmatch(text))


def stem(date, home, away, number, width=3):
    return f'{date}_{home}_{away}_{number:0{width}d}'


def width(count):
    return max(3, len(str(count)))


def item_files(item):
    """Alle Dateien eines Bildes: RAW, eingebettete, vorhandenes Sidecar."""
    paths = list(item.files)
    if item.sidecar and item.sidecar.exists():
        paths.append(item.sidecar)
    return paths


def plan(items, date, home, away):
    """Umbenennungen in der Reihenfolge von items; Dateien, die schon richtig heissen, fallen weg."""
    digits = width(len(items))
    moves = []
    for number, item in enumerate(items, start=1):
        new_stem = stem(date, home, away, number, digits)
        for path in item_files(item):
            target = path.with_name(new_stem + path.suffix)
            if target.name != path.name:
                moves.append(Move(path, target))
    return moves


def conflicts(moves):
    """Zielnamen, die schon existieren und nicht selbst umbenannt werden."""
    sources = {_key(move.source) for move in moves}
    return [move.target for move in moves if _key(move.target) not in sources and move.target.exists()]


def apply(moves):
    """Umbenennen in zwei Schritten; bei einem Fehler alles zurueck und RenameError."""
    if conflicts(moves):
        raise RenameError(_('Zieldateien existieren schon.'))
    done = []    # (von, nach) in Reihenfolge, fuers Zurueckbenennen
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
    # macOS/Windows: Dateinamen ohne Gross-/Kleinschreibung (DSC_0001.xmp == DSC_0001.XMP)
    return os.path.normcase(str(path)).casefold()

