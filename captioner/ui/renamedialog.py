"""
"Bilder umbenennen …": Kuerzel Heim/Gast, Datum (leer = heute), Vorschau des ersten und
letzten Namens. Gerechnet und umbenannt wird in captioner.rename (MainWindow.rename_folder).
"""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from .. import rename
from ..i18n import _, ngettext


class RenameDialog(QDialog):
    def __init__(self, count, home='', away='', parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Bilder umbenennen'))
        self.count = count

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)  # macOS: sonst schmal
        self.home = QLineEdit(home)
        self.home.setPlaceholderText(_('z. B. MEM'))
        self.away = QLineEdit(away)
        self.away.setPlaceholderText(_('z. B. EPC'))
        self.date = QLineEdit()
        self.date.setPlaceholderText(rename.today())
        self.date.setMaxLength(8)
        form.addRow(_('Heimmannschaft'), self.home)
        form.addRow(_('Gastmannschaft'), self.away)
        form.addRow(_('Datum (JJJJMMTT)'), self.date)

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
        for field in (self.home, self.away, self.date):
            field.textChanged.connect(self._update)
        self.resize(460, self.sizeHint().height())
        self._update()

    def values(self):
        """(Datum, Heim, Gast); Kuerzel in Grossbuchstaben, leeres Datum = heute."""
        return (self.date.text().strip() or rename.today(), self.home.text().strip().upper(),
                self.away.text().strip().upper())

    def problem(self):
        date, home, away = self.values()
        if not home or not away:
            return _('Kürzel für Heim- und Gastmannschaft eingeben.')
        if not rename.valid_code(home) or not rename.valid_code(away):
            return _('Kürzel nur aus Buchstaben, Ziffern und Bindestrich.')
        if not rename.valid_date(date):
            return _('Datum als JJJJMMTT, z. B. {date}.').format(date=rename.today())
        return None

    def _update(self):
        problem = self.problem()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(problem is None)
        if problem:
            self.preview.setText(problem)
            return
        date, home, away = self.values()
        digits = rename.width(self.count)
        first = rename.stem(date, home, away, 1, digits)
        last = rename.stem(date, home, away, self.count, digits)
        names = first if self.count == 1 else f'{first} … {last}'
        self.preview.setText(ngettext('{count} Bild, nach Aufnahmezeit: {names}',
                                      '{count} Bilder, nach Aufnahmezeit: {names}',
                                      self.count).format(count=self.count, names=names)
                             + '\n' + _('RAW, JPG und Sidecar eines Bildes bekommen dieselbe Nummer.'))
