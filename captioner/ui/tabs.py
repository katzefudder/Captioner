"""
Ordner-Tabs: je Tab ein Ordner mit eigener Galerie, Seite, Auswahl und Scan.
Ziehen von Bildern auf einen anderen Tab (Reiter oder Galerie) kopiert sie dorthin.
"""
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QStackedWidget, QTabBar, QToolButton, QVBoxLayout, QWidget)

from .. import transfer
from ..i18n import _
from .gallery import GalleryModel, GalleryView, TileDelegate


def tab_title(folder):
    """'100NCZ_9' bzw. 'NIKON Z 9 › 100NCZ_9' fuer Ordner auf einem Wechseldatentraeger."""
    if not folder:
        return _('Neuer Tab')
    path = Path(folder)
    parts = path.parts
    if len(parts) > 2 and parts[1] == 'Volumes':  # macOS: /Volumes/<Karte>/...
        return f'{parts[2]} › {path.name}' if len(parts) > 3 else parts[2]
    return path.name or str(path)


class FolderTab(QWidget):
    """Zustand eines Ordners; die Logik dazu steckt im Hauptfenster."""

    def __init__(self, loader, writer, parent=None):
        super().__init__(parent)
        self.folder = None
        self.all_items = []
        self.by_key = {}
        self.filtered = []
        self.page = 0
        self.selected_keys = set()
        self.scan_worker = None
        self.scan_started = 0.0
        self.status_text = _('Kein Ordner geöffnet')

        self.model = GalleryModel(loader)
        self.view = GalleryView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(TileDelegate(loader, writer, self.view))

        pager = QHBoxLayout()
        self.prev_button = QToolButton(text='◀')
        self.next_page_button = QToolButton(text='▶')
        self.page_label = QLabel()
        pager.addWidget(self.prev_button)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next_page_button)
        pager.addStretch(1)
        drag_hint = QLabel(_('Auswahl in Lightroom ziehen, um sie zu importieren, '
                             'oder auf einen anderen Tab, um sie dorthin zu kopieren'))
        drag_hint.setStyleSheet('color: gray;')
        pager.addWidget(drag_hint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(self.view, 1)
        layout.addLayout(pager)

    def scanning(self):
        return bool(self.scan_worker and self.scan_worker.isRunning())

    def stop_scan(self):
        if self.scanning():
            self.scan_worker.cancel()
            self.scan_worker.wait(5000)


class FolderTabBar(QTabBar):
    """Reiter nehmen gezogene Bilder an; beim Darueberziehen wechselt der Tab."""
    files_dropped = Signal(int)   # Index des Ziel-Tabs

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setChangeCurrentOnDrag(True)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideMiddle)

    def dragEnterEvent(self, event):
        if isinstance(event.source(), GalleryView):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if isinstance(event.source(), GalleryView) and self.tabAt(event.position().toPoint()) >= 0:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        index = self.tabAt(event.position().toPoint())
        if isinstance(event.source(), GalleryView) and index >= 0:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.files_dropped.emit(index)
        else:
            super().dropEvent(event)


class FolderTabs(QObject):
    """
    Reiter und Galerien getrennt, damit die Reiter oben ueber die ganze Fensterbreite
    laufen koennen (QTabWidget klebt sie an die Galerie). API wie QTabWidget, soweit
    gebraucht.
    """
    currentChanged = Signal(int)
    tabCloseRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bar = FolderTabBar()
        self.stack = QStackedWidget()
        self.bar.currentChanged.connect(self._on_current_changed)
        self.bar.tabCloseRequested.connect(self.tabCloseRequested)
        self.bar.tabMoved.connect(self._on_tab_moved)

    def _on_current_changed(self, index):
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)
        self.currentChanged.emit(index)

    def _on_tab_moved(self, source, target):
        widget = self.stack.widget(source)
        current = self.stack.currentWidget()
        self.stack.removeWidget(widget)
        self.stack.insertWidget(target, widget)
        self.stack.setCurrentWidget(current)

    def addTab(self, widget, title):
        self.stack.addWidget(widget)
        return self.bar.addTab(title)

    def removeTab(self, index):
        widget = self.stack.widget(index)
        self.stack.removeWidget(widget)
        self.bar.removeTab(index)
        if self.bar.currentIndex() >= 0:
            self.stack.setCurrentIndex(self.bar.currentIndex())

    def count(self):
        return self.stack.count()

    def widget(self, index):
        return self.stack.widget(index)

    def currentWidget(self):
        return self.stack.widget(self.bar.currentIndex())

    def currentIndex(self):
        return self.bar.currentIndex()

    def indexOf(self, widget):
        return self.stack.indexOf(widget)

    def setCurrentIndex(self, index):
        self.bar.setCurrentIndex(index)

    def setCurrentWidget(self, widget):
        index = self.indexOf(widget)
        if index >= 0:
            self.bar.setCurrentIndex(index)

    def setTabText(self, index, text):
        self.bar.setTabText(index, text)

    def setTabToolTip(self, index, text):
        self.bar.setTabToolTip(index, text)

    def tabText(self, index):
        return self.bar.tabText(index)


class ConflictDialog(QDialog):
    """'DSC_0001.NEF gibt es schon': ueberspringen, umbenennen oder ersetzen."""

    def __init__(self, group, folder, remaining, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Datei existiert bereits'))
        self.decision = None
        names = ', '.join(target.name for target in group.conflicts(folder))
        rename_to = transfer.free_stem(group, folder)
        layout = QVBoxLayout(self)
        text = QLabel(_('<b>{names}</b> gibt es in <b>{folder}</b> bereits.<br><br>'
                        'Überspringen lässt die vorhandene Datei, Umbenennen kopiert als '
                        '<b>{new_name}</b>, Ersetzen überschreibt die vorhandene.').format(
                            names=names, folder=Path(folder).name, new_name=rename_to))
        text.setWordWrap(True)
        layout.addWidget(text)
        self.apply_all = QCheckBox(_('Für alle weiteren Konflikte übernehmen ({count})').format(count=remaining))
        self.apply_all.setVisible(remaining > 0)
        layout.addWidget(self.apply_all)
        buttons = QHBoxLayout()
        cancel = QPushButton(_('Abbrechen'))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        for label, decision in ((_('Überspringen'), transfer.SKIP), (_('Umbenennen'), transfer.RENAME),
                                (_('Ersetzen'), transfer.REPLACE)):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, d=decision: self._choose(d))
            if decision == transfer.RENAME:
                button.setDefault(True)
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def _choose(self, decision):
        if decision == transfer.REPLACE:
            answer = QMessageBox.question(self, _('Ersetzen'),
                                           _('Die vorhandene Datei wird überschrieben. Fortfahren?'))
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.decision = decision
        self.accept()


def ask_conflicts(groups, folder, parent):
    """
    Entscheidung pro Gruppe mit Konflikt, vor dem Kopieren. None bei Abbruch,
    sonst {id(group): decision}.
    """
    conflicting = [group for group in groups if group.conflicts(folder)]
    decisions, for_all = {}, None
    for position, group in enumerate(conflicting):
        if for_all is None:
            dialog = ConflictDialog(group, folder, len(conflicting) - position - 1, parent)
            if not dialog.exec():
                return None
            decision = dialog.decision
            if dialog.apply_all.isChecked():
                for_all = decision
        else:
            decision = for_all
        decisions[id(group)] = decision
    return decisions


class CopyWorker(QThread):
    progress = Signal(int, int)       # erledigt, gesamt
    done = Signal(int, int, list)     # kopierte Bilder, uebersprungene, Fehler

    def __init__(self, groups, folder, decisions):
        super().__init__()
        self.groups = groups
        self.folder = folder
        self.decisions = decisions
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        copied = skipped = 0
        errors = []
        for position, group in enumerate(self.groups):
            if self._cancel:
                errors.append(_('abgebrochen'))
                break
            try:
                if transfer.copy_group(group, self.folder, self.decisions.get(id(group))):
                    copied += 1
                else:
                    skipped += 1
            except (OSError, transfer.TransferError) as e:
                errors.append(f'{group.name}: {e}')
            self.progress.emit(position + 1, len(self.groups))
        self.done.emit(copied, skipped, errors)
