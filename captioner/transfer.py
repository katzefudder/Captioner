"""
Bilder zwischen Ordnern kopieren (Drag & Drop zwischen Tabs), ohne Qt.

* Eine Gruppe sind alle Dateien eines Bildes: RAW, JPG/DNG und Sidecar mit gleichem
  Basisnamen. Sie werden immer zusammen kopiert und zusammen umbenannt, damit das
  Paar und das Sidecar zusammenpassen.
* Kopiert wird nie direkt auf den Zielnamen: erst in ".<name>.captioner-part", Groesse
  pruefen, dann os.replace. Ein Abbruch hinterlaesst nie eine halbe Datei unter dem
  echten Namen.
* Die Quelle wird nie veraendert (immer kopieren, nie verschieben).
* Konflikte (Zielname existiert schon) entscheidet der Aufrufer pro Gruppe:
  SKIP, RENAME (DSC_0001-2.NEF + -2.JPG + -2.xmp) oder REPLACE.
"""
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import _

SKIP, RENAME, REPLACE = 'skip', 'rename', 'replace'
PART_SUFFIX = '.captioner-part'


class TransferError(RuntimeError):
    pass


@dataclass
class Group:
    stem: str
    files: list = field(default_factory=list)   # Quellpfade

    @property
    def name(self):
        """Fuer Meldungen: die erste Datei (RAW vor JPG, siehe group_files)."""
        return self.files[0].name if self.files else self.stem

    def targets(self, folder, stem=None):
        stem = stem or self.stem
        return [Path(folder) / f'{stem}{path.suffix}' for path in self.files]

    def conflicts(self, folder):
        return [target for target in self.targets(folder) if target.exists()]


def group_files(paths):
    """Quelldateien nach Bild gruppieren (Ordner + Basisname, ohne Gross-/Kleinschreibung)."""
    groups = {}
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        key = (os.path.normcase(str(path.parent)), path.stem.casefold())
        group = groups.setdefault(key, Group(path.stem))
        if path not in group.files:
            group.files.append(path)
    for group in groups.values():
        # RAW zuerst, Sidecar zuletzt: nur fuer stabile Reihenfolge und Meldungen
        group.files.sort(key=lambda p: (p.suffix.lower() == '.xmp', p.suffix.lower() in ('.jpg', '.jpeg'), p.name))
    return list(groups.values())


def same_folder(group, folder):
    return all(_same_dir(path.parent, folder) for path in group.files)


def _same_dir(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def free_stem(group, folder):
    """Erster Basisname stem-2, stem-3, ..., unter dem keine Datei der Gruppe existiert."""
    n = 2
    while True:
        stem = f'{group.stem}-{n}'
        if not any(target.exists() for target in group.targets(folder, stem)):
            return stem
        n += 1


def copy_file(source, target):
    target = Path(target)
    part = target.with_name(f'.{target.name}{PART_SUFFIX}')
    try:
        shutil.copy2(source, part)
        if part.stat().st_size != Path(source).stat().st_size:
            raise TransferError(_('{name}: Kopie unvollständig').format(name=target.name))
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink()


def copy_group(group, folder, decision=None):
    """
    Kopiert eine Gruppe. decision gilt nur bei Konflikten (SKIP, RENAME, REPLACE).
    Rueckgabe: kopierte Zielpfade (leer bei SKIP).
    """
    folder = Path(folder)
    stem = group.stem
    if group.conflicts(folder):
        if decision == SKIP:
            return []
        if decision == RENAME:
            stem = free_stem(group, folder)
        elif decision != REPLACE:
            raise TransferError(_('{name}: existiert schon in {folder}').format(name=group.name, folder=folder))
    copied = []
    for source, target in zip(group.files, group.targets(folder, stem)):
        if target.exists() and _same_file(source, target):
            continue
        copy_file(source, target)
        copied.append(target)
    return copied


def _same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False
