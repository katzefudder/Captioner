"""Template-, Einstellungs- und Grossansicht-Dialog."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..roster import is_url
from . import keymap
from ..templates import DEFAULT_CAPTION_SUFFIX, MatchTemplate

ROSTER_FILE_FILTER = 'Roster-Dateien (*.txt *.tsv *.csv);;Alle Dateien (*)'


def _split(text):
    return [part.strip() for part in text.split(',') if part.strip()]


class TemplateDialog(QDialog):
    def __init__(self, template: MatchTemplate, teams, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Spiel-Template')
        self.setMinimumWidth(520)
        template = template or MatchTemplate()
        form = QFormLayout(self)

        self.name = QLineEdit(template.name)
        self.name.setPlaceholderText('leer = Titel')
        self.occasion = QLineEdit(template.occasion)
        self.occasion.setPlaceholderText('DEL 2')
        self.home = self._team_box(teams, template.home)
        self.away = self._team_box(teams, template.away)
        self.city = QLineEdit(template.city)
        self.sublocation = QLineEdit(template.sublocation)
        self.extra_tags = QLineEdit(', '.join(template.extra_tags))
        self.extra_tags.setPlaceholderText('Eishockey, DEL2, Saison 2026/27')
        self.suffix = QLineEdit(template.caption_suffix)
        self.suffix.setPlaceholderText(DEFAULT_CAPTION_SUFFIX)
        self.headline_preview = QLabel()
        self.headline_preview.setWordWrap(True)

        form.addRow('Name', self.name)
        form.addRow('Anlass / Liga', self.occasion)
        form.addRow('Heim', self.home)
        form.addRow('Gast', self.away)
        form.addRow('Stadt', self.city)
        form.addRow('Ort / Halle', self.sublocation)
        form.addRow('Zusatz-Tags', self.extra_tags)
        form.addRow('Anhang an Beschreibung', self.suffix)
        form.addRow('', QLabel('<small>Platzhalter: {headline}, {city}, {sublocation}, {date}</small>'))
        form.addRow('Titel', self.headline_preview)
        note = QLabel('<small>Titel-Format „&lt;Anlass&gt; - &lt;Heim&gt; gegen &lt;Gast&gt;“ ist fest: '
                      'die Personenerkennung liest den Spielkontext daraus.</small>')
        note.setWordWrap(True)
        form.addRow('', note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        for widget in (self.occasion, self.home.lineEdit(), self.away.lineEdit()):
            widget.textChanged.connect(self._update)
        self._update()

    @staticmethod
    def _team_box(teams, value):
        box = QComboBox()
        box.setEditable(True)
        box.addItems(teams)
        box.setCurrentText(value)
        return box

    def _update(self):
        self.headline_preview.setText(self.template().headline or '<i>Anlass, Heim und Gast ausfüllen</i>')

    def template(self):
        return MatchTemplate(
            name=self.name.text().strip(),
            occasion=self.occasion.text().strip(),
            home=self.home.currentText().strip(),
            away=self.away.currentText().strip(),
            city=self.city.text().strip(),
            sublocation=self.sublocation.text().strip(),
            extra_tags=_split(self.extra_tags.text()),
            caption_suffix=self.suffix.text(),
        )


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Einstellungen')
        self.setMinimumWidth(620)
        self.settings = settings
        form = QFormLayout(self)

        self.sources = RosterSourceList(settings.roster_sources)
        self.ttl = QSpinBox(minimum=0, maximum=24 * 60, value=settings.roster_cache_ttl_minutes, suffix=' min')
        self.delimiter = QLineEdit(settings.code_delimiter)
        self.delimiter.setMaxLength(3)
        self.page_size = QSpinBox(minimum=20, maximum=2000, singleStep=20, value=settings.page_size)
        self.recursive = QCheckBox('Unterordner mit einlesen')
        self.recursive.setChecked(settings.recursive)
        self.labels = QLineEdit(', '.join(settings.labels))
        self.number_keys = QComboBox()
        for value, text in keymap.NUMBER_KEY_MODES.items():
            self.number_keys.addItem(text, value)
        self.number_keys.setCurrentIndex(max(0, self.number_keys.findData(settings.number_keys)))
        self.drag_sidecars = QCheckBox('XMP-Sidecars mit in den Drag legen')
        self.drag_sidecars.setChecked(settings.drag_include_sidecars)
        self.exiftool = QLineEdit(settings.exiftool_path)
        self.exiftool.setPlaceholderText('leer = automatisch suchen')

        form.addRow('Roster-Quellen', self.sources)
        form.addRow('Cache für URLs', self.ttl)
        form.addRow('Code-Trennzeichen', self.delimiter)
        form.addRow('Bilder pro Seite', self.page_size)
        form.addRow('', self.recursive)
        form.addRow('Lightroom-Label für Farbklasse 1, 2, 3, …', self.labels)
        label_hint = QLabel('<small>Die Farbklasse wird zusätzlich als Label geschrieben, das Lightroom liest. '
                            'Muss zum Label-Set in Lightroom passen: „Red“ (englisch) '
                            'oder „Rot“ (deutsches Lightroom). Klassen ohne Eintrag bekommen kein Label.</small>')
        label_hint.setWordWrap(True)
        form.addRow('', label_hint)
        form.addRow('Ziffern ohne Modifier setzen', self.number_keys)
        form.addRow('', self.drag_sidecars)
        form.addRow('ExifTool', self.exiftool)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self):
        s = self.settings
        s.roster_sources = self.sources.sources()
        s.roster_cache_ttl_minutes = self.ttl.value()
        s.code_delimiter = self.delimiter.text().strip() or '#'
        s.page_size = self.page_size.value()
        s.recursive = self.recursive.isChecked()
        s.labels = _split(self.labels.text()) or s.labels
        s.number_keys = self.number_keys.currentData()
        s.drag_include_sidecars = self.drag_sidecars.isChecked()
        s.exiftool_path = self.exiftool.text().strip()
        return s


class RosterSourceList(QWidget):
    """Roster-Quellen: Dateien vom Rechner und URLs. Bei Konflikten gewinnt die obere."""

    def __init__(self, sources, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMinimumHeight(110)
        # Lange Pfade in der Mitte kuerzen, Dateiname und Anfang bleiben sichtbar
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for source in sources:
            self._add(source)
        buttons = QHBoxLayout()
        for label, slot in (('Datei …', self.add_file), ('URL …', self.add_url),
                            ('Entfernen', self.remove), ('▲', lambda: self.move(-1)), ('▼', lambda: self.move(1))):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addWidget(self.list)
        layout.addLayout(buttons)
        hint = QLabel('<small>Format: eine Zeile pro Code, Code und Ersetzung durch Tab getrennt, '
                      'Abschnitte „- Team -“. Bei gleichem Code gewinnt die obere Quelle.</small>')
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _add(self, source):
        if source and source not in self.sources():
            self.list.addItem(source)
            item = self.list.item(self.list.count() - 1)
            kind = 'URL, wird bei Bedarf neu geladen' if is_url(source) else 'Datei auf diesem Rechner'
            item.setToolTip(f'{source}\n{kind}')

    def add_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Roster-Datei wählen', '', ROSTER_FILE_FILTER)
        if path:
            self._add(path)

    def add_url(self, url=None):
        if not url:
            url, ok = QInputDialog.getText(self, 'Roster-URL', 'URL (GitHub-Links wie im Browser gehen auch):')
            if not ok:
                return
        url = (url or '').strip()
        if is_url(url):
            self._add(url)

    def remove(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def move(self, step):
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)

    def sources(self):
        return [self.list.item(i).text() for i in range(self.list.count())]


class ShortcutsDialog(QDialog):
    """Uebersicht aller Kuerzel, erzeugt aus keymap.BINDINGS - kann nicht veralten."""

    def __init__(self, number_keys, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Tastenkürzel')
        self.resize(640, 720)
        layout = QVBoxLayout(self)
        rows = []
        for context, title in keymap.CONTEXT_TITLES.items():
            rows.append((title, None))
            for binding in keymap.BINDINGS:
                if binding.context != context:
                    continue
                text = '  oder  '.join(QKeySequence(k).toString(QKeySequence.SequenceFormat.NativeText)
                                       for k in binding.keys)
                rows.append((binding.label, text))
        mode = keymap.NUMBER_KEY_MODES.get(number_keys, 'aus')
        rows.append(('Ziffern ohne Modifier', None))
        rows.append((f'0–8 in Galerie und Großansicht: {mode}', 'Einstellungen'))
        rows.append(('Großansicht blättern', '←  →'))
        alt = QKeySequence('Alt+Left').toString(QKeySequence.SequenceFormat.NativeText).replace('←', '').strip()
        rows.append(('Großansicht: Ausschnitt verschieben (mit ⇧ schneller)',
                     f'{alt} + Pfeiltasten, mit der Maus ziehen'))
        rows.append(('Großansicht: an der Maus zoomen', f'{alt} + Mausrad, Doppelklick'))
        ctrl = QKeySequence('Ctrl+A').toString(QKeySequence.SequenceFormat.NativeText).replace('A', '').strip()
        rows.append(('Großansicht: auf Stelle zoomen', f'{ctrl} + Klick'))
        rows.append(('Großansicht: Zoom 50–400 % stufenlos', 'Slider unten'))
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(['Aktion', 'Taste'])
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, (label, text) in enumerate(rows):
            item = QTableWidgetItem(label)
            if text is None:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                table.setSpan(row, 0, 1, 2)
            table.setItem(row, 0, item)
            if text is not None:
                table.setItem(row, 1, QTableWidgetItem(text))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
