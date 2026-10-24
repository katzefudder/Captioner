"""
Undo/redo for metadata changes, without Qt.

A step is one user action (rating, color class, tag, caption, apply template, paste)
with before/after of all affected images, including the raw text with codes. Undo
writes the "before" back.
"""
import dataclasses
from dataclasses import dataclass, field

LIMIT = 50


@dataclass
class Change:
    item: object
    before: object        # scanner.Metadata
    after: object
    raw_before: str = None   # raw text with codes (RawCaptionStore), None = none
    raw_after: str = None


@dataclass
class Step:
    label: str            # text marked with N_, translated when displayed
    changes: list = field(default_factory=list)


def reverting(current, target):
    """
    Metadata that restores `target`. GPS must be written if it changes compared with
    `current` (also: removing it, which would otherwise never be written).
    """
    gps_differs = (current.latitude, current.longitude) != (target.latitude, target.longitude)
    return dataclasses.replace(target, gps_changed=gps_differs)


class UndoStack:
    def __init__(self, limit=LIMIT):
        self.limit = limit
        self.undo_steps = []
        self.redo_steps = []

    def push(self, step):
        if not step.changes:
            return
        self.undo_steps.append(step)
        del self.undo_steps[:-self.limit]
        self.redo_steps.clear()

    def undo(self):
        if not self.undo_steps:
            return None
        step = self.undo_steps.pop()
        self.redo_steps.append(step)
        return step

    def redo(self):
        if not self.redo_steps:
            return None
        step = self.redo_steps.pop()
        self.undo_steps.append(step)
        return step

    def forget(self, items):
        """Take deleted images out of all steps; steps left empty are dropped."""
        gone = {id(item) for item in items}
        for steps in (self.undo_steps, self.redo_steps):
            for step in steps:
                step.changes = [c for c in step.changes if id(c.item) not in gone]
            steps[:] = [step for step in steps if step.changes]

    @property
    def undo_label(self):
        return self.undo_steps[-1].label if self.undo_steps else None

    @property
    def redo_label(self):
        return self.redo_steps[-1].label if self.redo_steps else None
