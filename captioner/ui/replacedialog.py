"""
Find and replace across several images: input, preview per image (before/after),
individual images can be deselected. Computed in captioner.replace; written only once
the dialog is confirmed (MainWindow.find_replace).
"""
import html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..i18n import N_, _, ngettext
from ..replace import MARK_END, MARK_START, Options
from .editor import shortcut_text

FIELD_LABELS = {'caption': N_('Beschreibung'), 'headline': N_('Titel'), 'keywords': N_('Tags'),
                'city': N_('Stadt'), 'sublocation': N_('Ort')}


class ReplaceDialog(QDialog):
    def __init__(self, scope_text, planner, parent=None):
        """planner(find, replacement, fields, options) -> [replace.Change]"""
        super().__init__(parent)
        self.setWindowTitle(_('Suchen und Ersetzen'))
        self.resize(820, 600)
        self.planner = planner
        self.changes = []

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)  # macOS: otherwise narrow
        self.find = QLineEdit()
        self.find.setPlaceholderText(_('Text oder Code, z. B. #bn9# oder Mcpherson'))
        self.replacement = QLineEdit()
        self.replacement.setPlaceholderText(_('leer = Fundstelle löschen'))
        form.addRow(_('Suchen'), self.find)
        form.addRow(_('Ersetzen'), self.replacement)
        fields_row = QHBoxLayout()
        self.fields = {}
        for name, label in FIELD_LABELS.items():
            box = QCheckBox(_(label))
            box.setChecked(name == 'caption')
            self.fields[name] = box
            fields_row.addWidget(box)
        fields_row.addStretch(1)
        form.addRow(_('In'), fields_row)
        options_row = QHBoxLayout()
        self.case_sensitive = QCheckBox(_('Groß/klein beachten'))
        self.whole_words = QCheckBox(_('Nur ganze Wörter'))
        options_row.addWidget(self.case_sensitive)
        options_row.addWidget(self.whole_words)
        options_row.addStretch(1)
        form.addRow('', options_row)

        self.summary = QLabel(scope_text)
        self.summary.setWordWrap(True)
        # One row per image: checkbox with file name, next to it before -> after (wrapping;
        # in a list with item widgets Qt estimated the height of such texts wrongly)
        self.list = QScrollArea()
        self.list.setWidgetResizable(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows = []   # QCheckBox per change, same order as self.changes
        note = QLabel('<small>' + _('In der Beschreibung wird im Text mit Codes gesucht; der Anhang des '
                                  'Templates (Titel, Ort, Datum) wird danach neu gebildet. Personen-Tags '
                                  'passen sich an. Rückgängig mit {undo}.').format(undo=shortcut_text('undo')) + '</small>')
        note.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(_('Abbrechen'))
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton()
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.apply_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.summary)
        layout.addWidget(self.list, 1)
        layout.addWidget(note)
        layout.addLayout(buttons)

        self._scope_text = scope_text
        self._timer = QTimer(self, singleShot=True, interval=200)
        self._timer.timeout.connect(self.refresh)
        for edit in (self.find, self.replacement):
            edit.textChanged.connect(self._timer.start)
        for box in (*self.fields.values(), self.case_sensitive, self.whole_words):
            box.toggled.connect(self.refresh)
        self.refresh()

    def options(self):
        return Options(case_sensitive=self.case_sensitive.isChecked(), whole_words=self.whole_words.isChecked())

    def selected_fields(self):
        return tuple(name for name, box in self.fields.items() if box.isChecked())

    def refresh(self):
        """Recompute the preview (after a short pause while typing)."""
        self.changes = self.planner(self.find.text(), self.replacement.text(), self.selected_fields(), self.options())
        # rebuilt every time; setWidget deletes the old list
        rows = QWidget()
        outer = QVBoxLayout(rows)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(10)
        outer.addLayout(grid)
        outer.addStretch(1)
        self.rows = []
        top = Qt.AlignmentFlag.AlignTop
        for index, change in enumerate(self.changes):
            box = QCheckBox(change.item.name)
            box.setChecked(change.ok)
            box.setEnabled(change.ok)          # with unknown code or too long: locked
            box.toggled.connect(self._update_button)
            label = QLabel(self._describe(change))
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(box, index * 2, 0, top)
            grid.addWidget(label, index * 2, 1, top)
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setStyleSheet('color: palette(mid);')
            grid.addWidget(line, index * 2 + 1, 0, 1, 2)
            self.rows.append(box)
        self.list.setWidget(rows)
        if not self.find.text():
            self.summary.setText(self._scope_text)
        else:
            hits = sum(change.count for change in self.changes)
            self.summary.setText(ngettext('{hits} Treffer in {photos} Bild', '{hits} Treffer in {photos} Bildern',
                                          len(self.changes)).format(hits=hits, photos=len(self.changes))
                                 + ' · ' + self._scope_text)
        self._update_button()

    def _describe(self, change):
        before, after = self._colors()
        lines = []
        for name, old, new in change.diffs:
            lines.append(f'<b>{html.escape(_(FIELD_LABELS[name]))}:</b> {self._marked(old, before)} '
                         f'<span style="color:gray">→</span> {self._marked(new, after)}')
        if change.unknown:
            lines.append('<span style="color:#d64541">' + html.escape(_('Unbekannte Codes: {codes}').format(
                codes=', '.join(change.unknown))) + '</span>')
        if change.problems:
            lines.append('<span style="color:#d64541">' + html.escape('; '.join(change.problems)) + '</span>')
        if not change.diffs:
            # e.g. only the suffix was rebuilt
            lines.append(f'<b>{html.escape(_("Beschreibung"))}:</b> {html.escape(change.meta.caption)}')
        return '<br>'.join(lines)

    @staticmethod
    def _marked(text, color):
        shown = html.escape(text)
        return shown.replace(MARK_START, f'<span style="background-color:{color}">').replace(MARK_END, '</span>')

    def _colors(self):
        """Background for match (red) and replacement (green), readable on light and dark."""
        dark = self.palette().window().color().lightness() < 128
        return ('#5c2624', '#24502e') if dark else ('#f6cfcd', '#cdeccf')

    def chosen(self):
        """Checked changes without errors."""
        return [change for change, box in zip(self.changes, self.rows) if change.ok and box.isChecked()]

    def _update_button(self, *args):
        count = len(self.chosen())
        self.apply_button.setText(ngettext('{count} Bild ändern', '{count} Bilder ändern', count).format(count=count))
        self.apply_button.setEnabled(count > 0)
