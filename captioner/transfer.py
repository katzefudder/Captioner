"""
Copy images between folders (drag & drop between tabs), without Qt.

* A group is all files of one image: RAW, JPG/DNG and sidecar with the same base name.
  They are always copied and renamed together so that the pair and the sidecar stay
  matched.
* Never copied straight to the target name: first to ".<name>.captioner-part", check the
  size, then os.replace. An abort never leaves a half file under the real name.
* The source is never changed (always copy, never move).
* The caller decides conflicts (target name already exists) per group:
  SKIP, RENAME (DSC_0001-2.NEF + -2.JPG + -2.xmp) or REPLACE.
"""
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .files import replace_file
from .i18n import _

SKIP, RENAME, REPLACE = 'skip', 'rename', 'replace'
PART_SUFFIX = '.captioner-part'


class TransferError(RuntimeError):
    pass


@dataclass
class Group:
    stem: str
    files: list = field(default_factory=list)   # source paths

    @property
    def name(self):
        """For messages: the first file (RAW before JPG, see group_files)."""
        return self.files[0].name if self.files else self.stem

    def targets(self, folder, stem=None):
        stem = stem or self.stem
        return [Path(folder) / f'{stem}{path.suffix}' for path in self.files]

    def conflicts(self, folder):
        return [target for target in self.targets(folder) if target.exists()]


def group_files(paths):
    """Group source files by image (folder + base name, case-insensitive)."""
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
        # RAW first, sidecar last: only for a stable order and messages
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
    """First base name stem-2, stem-3, ... under which no file of the group exists."""
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
        try:
            replace_file(part, target)
        except PermissionError:
            raise TransferError(_('{name}: Ziel ist von einem anderen Programm geöffnet').format(name=target.name))
    finally:
        if part.exists():
            part.unlink()


def copy_group(group, folder, decision=None):
    """
    Copies a group. decision only applies to conflicts (SKIP, RENAME, REPLACE).
    Returns the copied target paths (empty for SKIP).
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
