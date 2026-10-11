"""
Rueckgaengig/Wiederholen fuer Metadaten-Aenderungen, ohne Qt.

Ein Schritt ist eine Aktion des Nutzers (Bewertung, Farbklasse, Tag, Beschriftung,
Template anwenden, Einfuegen) mit dem Vorher/Nachher aller betroffenen Bilder,
einschliesslich des Rohtexts mit Codes. Rueckgaengig schreibt das Vorher zurueck.
"""
import dataclasses
from dataclasses import dataclass, field

LIMIT = 50


@dataclass
class Change:
    item: object
    before: object        # scanner.Metadata
    after: object
    raw_before: str = None   # Rohtext mit Codes (RawCaptionStore), None = keiner
    raw_after: str = None


@dataclass
class Step:
    label: str            # mit N_ markierter Text, uebersetzt wird bei der Anzeige
    changes: list = field(default_factory=list)


def reverting(current, target):
    """
    Metadaten, die `target` wiederherstellen. GPS muss geschrieben werden, wenn es sich
    gegenueber `current` aendert (auch: entfernen, das sonst nie geschrieben wuerde).
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

    @property
    def undo_label(self):
        return self.undo_steps[-1].label if self.undo_steps else None

    @property
    def redo_label(self):
        return self.redo_steps[-1].label if self.redo_steps else None
