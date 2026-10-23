"""
"Bilder umbenennen …": ein Feld fuer den Namen (vorgeschlagen Datum + zuletzt benutzte Kuerzel),
dahinter haengt Captioner die Nummer an; Vorschau des ersten und letzten Namens. Gerechnet und
umbenannt wird in captioner.rename (MainWindow.rename_folder).
"""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from .. import rename
from ..i18n import _, ngettext


class RenameDialog(QDialog):
    def __init__(self, count, prefix='', parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Bilder umbenennen'))
        self.count = count

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)  # macOS: sonst schmal
        self.name = QLineEdit(prefix)
        self.name.setPlaceholderText(_('z. B. {example}').format(example=f'{rename.today()}_MEM_EPC'))
        form.addRow(_('Name'), self.name)
        hint = QLabel(_('Die Nummer (_001, _002, …) wird angehängt.'))
        hint.setEnabled(False)
        form.addRow('', hint)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_('Umbenennen'))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.preview)
        layout.addWidget(self.buttons)
        self.name.textChanged.connect(self._update)
        self.resize(460, self.sizeHint().height())
        self._update()

    def prefix(self):
        return self.name.text().strip()

    def _update(self):
        prefix = self.prefix()
        ok = rename.valid_prefix(prefix)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        if not ok:
            self.preview.setText(_('Namen eingeben, ohne / \\ : * ? " < > | und nicht mit einem Punkt vorn.')
                                 if prefix else '')
            return
        digits = rename.width(self.count)
        first = rename.stem(prefix, 1, digits)
        last = rename.stem(prefix, self.count, digits)
        names = first if self.count == 1 else f'{first} … {last}'
        self.preview.setText(ngettext('{count} Bild, nach Aufnahmezeit: {names}',
                                      '{count} Bilder, nach Aufnahmezeit: {names}',
                                      self.count).format(count=self.count, names=names)
                             + '\n' + _('RAW, JPG und Sidecar eines Bildes bekommen dieselbe Nummer.'))
