"""Template-, Einstellungs- und Grossansicht-Dialog."""
import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import geo, i18n, metadata
from ..i18n import _, N_
from ..scanner import Metadata
from ..roster import is_url
from .placepicker import PlacePickerDialog, place_completer, place_for_completion
from . import keymap
from ..templates import DEFAULT_CAPTION_SUFFIX, MatchTemplate, parse_headline

ROSTER_FILE_FILTER = N_('Roster-Dateien (*.txt *.tsv *.csv);;Alle Dateien (*)')


def _split(text):
    return [part.strip() for part in text.split(',') if part.strip()]


class TemplateDialog(QDialog):
    """Template bearbeiten: Ort, Urheber und Rechte, Tags, Anhang, optional ein fester Titel."""

    def __init__(self, template: MatchTemplate, places=None, parent=None):
        super().__init__(parent)
        self.places = places if places is not None else geo.PlaceBook()
        self.places_changed = False
        self.setWindowTitle(_('Template'))
        self.setMinimumWidth(620)
        template = template or MatchTemplate()
        form = QFormLayout(self)
        # macOS-Standard laesst Felder auf Mindestbreite; hier sollen sie den Dialog fuellen
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        def field(value, placeholder=''):
            edit = QLineEdit(value)
            edit.setPlaceholderText(placeholder)
            return edit

        self.name = field(template.name, _('z. B. DEL 2 Heimspiele'))
        self.headline = field(template.headline, _('leer = im Panel eintragen, z. B. DEL 2 - EC Bad Nauheim gegen …'))
        self.headline_hint = QLabel()
        self.headline_hint.setWordWrap(True)
        self.city = field(template.city)
        self.city.setCompleter(place_completer(self.places, self))
        self.city.completer().activated.connect(self._known_place_chosen)
        self.sublocation = field(template.sublocation, _('Halle, Stadion'))
        self.state = field(template.state, _('Hessen'))
        self.country = field(template.country, _('Deutschland'))
        map_button = QPushButton(_('Karte …'))
        map_button.setToolTip(_('Ort auf der Karte oder per Adresssuche wählen (OpenStreetMap)'))
        map_button.clicked.connect(self.pick_place)
        city_row = QHBoxLayout()
        city_row.addWidget(self.city, 1)
        city_row.addWidget(map_button)
        # Koordinaten aus der Datei, solange Stadt/Ort nicht geaendert werden
        self._file_place = geo.Place(template.city, template.sublocation, template.latitude, template.longitude)
        self.creator = field(template.creator, _('Vor- und Nachname'))
        self.authors_position = field(template.authors_position, _('Fotograf'))
        self.caption_writer = field(template.caption_writer, _('wer beschriftet'))
        self.copyright = field(template.copyright, _('© 2026 Vor- und Nachname'))
        self.web_statement = field(template.web_statement, _('https://… (Nutzungsbedingungen, Lizenz)'))
        self.source = field(template.source, _('Agentur, Redaktion'))
        self.extra_tags = field(', '.join(template.extra_tags), _('Eishockey, DEL2, Saison 2026/27'))
        self.category = field(template.category, _('Sport'))
        self.suffix = field(template.caption_suffix, DEFAULT_CAPTION_SUFFIX)

        def section(title):
            label = QLabel(f'<b>{html.escape(title)}</b>')
            label.setContentsMargins(0, 10, 0, 0)
            form.addRow(label)

        form.addRow(_('Name'), self.name)
        form.addRow(_('Titel'), self.headline)
        form.addRow('', self.headline_hint)
        section(_('Ort'))
        form.addRow(_('Stadt'), city_row)
        form.addRow(_('Ort / Halle'), self.sublocation)
        form.addRow(_('Bundesland'), self.state)
        form.addRow(_('Land'), self.country)
        section(_('Urheber und Rechte'))
        form.addRow(_('Fotograf'), self.creator)
        form.addRow(_('Position'), self.authors_position)
        form.addRow(_('Beschriftet von'), self.caption_writer)
        form.addRow(_('Copyright'), self.copyright)
        form.addRow(_('Copyright-URL'), self.web_statement)
        form.addRow(_('Quelle'), self.source)
        section(_('Beschreibung und Tags'))
        form.addRow(_('Kategorie'), self.category)
        form.addRow(_('Zusatz-Tags'), self.extra_tags)
        form.addRow(_('Anhang'), self.suffix)
        form.addRow('', QLabel('<small>' + _('Platzhalter: {headline}, {city}, {sublocation}, {date}') + '</small>'))
        note = QLabel('<small>' + _('Gefüllte Felder gehen beim Speichern in jedes Bild, leere lassen den Wert '
                                  'des Bildes stehen. Heim und Gast stehen im Titel und ergeben sich aus den '
                                  'Codes in der Beschreibung.') + '</small>')
        note.setWordWrap(True)
        form.addRow('', note)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)

        for edit in self.findChildren(QLineEdit):
            edit.textChanged.connect(self._update)
        self._update()

    def pick_place(self):
        current = self.places.lookup(self.city.text(), self.sublocation.text()) or self._place()
        dialog = PlacePickerDialog(current, self.places, self)
        if dialog.exec():
            place = dialog.place()
            self.city.setText(place.city)
            self.sublocation.setText(place.sublocation)
            # Bundesland und Land liefert die Adresssuche gleich mit
            if place.state:
                self.state.setText(place.state)
            if place.country:
                self.country.setText(place.country)
            self.places.remember(place)
            self.places_changed = True

    def _known_place_chosen(self, text):
        place = place_for_completion(self.places, text)
        if place:
            self.city.setText(place.city)
            self.sublocation.setText(place.sublocation)

    def _place(self):
        """Stadt/Ort aus den Feldern, Koordinaten aus dem Ortsbuch oder der Datei."""
        city, sublocation = self.city.text().strip(), self.sublocation.text().strip()
        known = self.places.lookup(city, sublocation)
        if known and known.has_coordinates:
            return geo.Place(city, sublocation, known.latitude, known.longitude)
        if self._file_place.key() == geo.Place(city, sublocation).key():
            return geo.Place(city, sublocation, self._file_place.latitude, self._file_place.longitude)
        return geo.Place(city, sublocation)

    def _too_long(self):
        """Zu lange Felder (IPTC-Grenzen)."""
        template = self.template()
        return metadata.validate(Metadata(headline=template.headline, city=template.city,
                                          sublocation=template.sublocation, **template.fixed_values()))

    def problems(self):
        """Zu lange Felder (IPTC-Grenzen) und ein Titel im falschen Format."""
        problems = self._too_long()
        headline = self.headline.text().strip()
        if headline and parse_headline(headline) is None:
            problems.insert(0, _('Titel nicht im Format „<Anlass> - <Heim> gegen <Gast>“ – '
                                 'die Personenerkennung erkennt das Spiel dann nicht'))
        return problems

    def _update(self):
        problems = self.problems()
        self.headline_hint.setText('<small style="color:#d64541">' + html.escape('; '.join(problems)) + '</small>'
                                   if problems else '')
        self.headline_hint.setVisible(bool(problems))
        # Nur zu lange Felder blockieren; ein abweichender Titel ist erlaubt
        too_long = bool(self._too_long())
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(not too_long)

    def template(self):
        place = self._place()
        return MatchTemplate(
            name=self.name.text().strip(),
            headline=self.headline.text().strip(),
            city=self.city.text().strip(),
            sublocation=self.sublocation.text().strip(),
            state=self.state.text().strip(),
            country=self.country.text().strip(),
            extra_tags=_split(self.extra_tags.text()),
            caption_suffix=self.suffix.text(),
            creator=self.creator.text().strip(),
            authors_position=self.authors_position.text().strip(),
            caption_writer=self.caption_writer.text().strip(),
            copyright=self.copyright.text().strip(),
            web_statement=self.web_statement.text().strip(),
            source=self.source.text().strip(),
            category=self.category.text().strip(),
            latitude=place.latitude,
            longitude=place.longitude,
        )


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Einstellungen'))
        self.setMinimumWidth(620)
        self.settings = settings
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.sources = RosterSourceList(settings.roster_sources)
        self.ttl = QSpinBox(minimum=0, maximum=24 * 60, value=settings.roster_cache_ttl_minutes, suffix=_(' min'))
        self.delimiter = QLineEdit(settings.code_delimiter)
        self.delimiter.setMaxLength(3)
        self.page_size = QSpinBox(minimum=20, maximum=2000, singleStep=20, value=settings.page_size)
        self.recursive = QCheckBox(_('Unterordner mit einlesen'))
        self.recursive.setChecked(settings.recursive)
        self.labels = QLineEdit(', '.join(settings.labels))
        self.drag_sidecars = QCheckBox(_('XMP-Sidecars mit in den Drag legen'))
        self.drag_sidecars.setChecked(settings.drag_include_sidecars)
        self.exiftool = QLineEdit(settings.exiftool_path)
        self.exiftool.setPlaceholderText(_('leer = automatisch suchen'))
        self.language = QComboBox()
        self.language.addItem(_('Automatisch (Systemsprache)'), '')
        for code, name in i18n.LANGUAGES.items():
            self.language.addItem(name, code)   # in der eigenen Sprache, nicht uebersetzt
        self.language.setCurrentIndex(max(0, self.language.findData(getattr(settings, 'language', ''))))
        language_row = QHBoxLayout()
        language_row.addWidget(self.language)
        language_hint = QLabel('<small>' + _('Gilt nach einem Neustart.') + '</small>')
        language_hint.setStyleSheet('color: gray;')
        language_row.addWidget(language_hint, 1)

        form.addRow(_('Roster-Quellen'), self.sources)
        form.addRow(_('Cache für URLs'), self.ttl)
        form.addRow(_('Code-Trennzeichen'), self.delimiter)
        form.addRow(_('Bilder pro Seite'), self.page_size)
        form.addRow('', self.recursive)
        form.addRow(_('Lightroom-Label für Farbklasse 1, 2, 3, …'), self.labels)
        label_hint = QLabel('<small>' + _('Die Farbklasse wird zusätzlich als Label geschrieben, das Lightroom liest. '
                                        'Muss zum Label-Set in Lightroom passen: „Red“ (englisch) '
                                        'oder „Rot“ (deutsches Lightroom). Klassen ohne Eintrag bekommen '
                                        'kein Label.') + '</small>')
        label_hint.setWordWrap(True)
        form.addRow('', label_hint)
        form.addRow('', self.drag_sidecars)
        form.addRow('ExifTool', self.exiftool)
        form.addRow(_('Sprache'), language_row)

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
        s.drag_include_sidecars = self.drag_sidecars.isChecked()
        s.exiftool_path = self.exiftool.text().strip()
        s.language = self.language.currentData()
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
        for label, slot in ((_('Datei …'), self.add_file), (_('URL …'), self.add_url),
                            (_('Entfernen'), self.remove), ('▲', lambda: self.move(-1)), ('▼', lambda: self.move(1))):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addWidget(self.list)
        layout.addLayout(buttons)
        hint = QLabel('<small>' + _('Format: eine Zeile pro Code, Code und Ersetzung durch Tab getrennt, '
                                  'Abschnitte „- Team -“. Bei gleichem Code gewinnt die obere Quelle.')
                      + '</small>')
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _add(self, source):
        if source and source not in self.sources():
            self.list.addItem(source)
            item = self.list.item(self.list.count() - 1)
            kind = _('URL, wird bei Bedarf neu geladen') if is_url(source) else _('Datei auf diesem Rechner')
            item.setToolTip(f'{source}\n{kind}')

    def add_file(self, path=None):
        if not path:
            path, _filter = QFileDialog.getOpenFileName(self, _('Roster-Datei wählen'), '', _(ROSTER_FILE_FILTER))
        if path:
            self._add(path)

    def add_url(self, url=None):
        if not url:
            url, ok = QInputDialog.getText(self, _('Roster-URL'), _('URL (GitHub-Links wie im Browser gehen auch):'))
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Tastenkürzel'))
        self.resize(640, 720)
        layout = QVBoxLayout(self)
        rows = []
        for context, title in keymap.CONTEXT_TITLES.items():
            rows.append((_(title), None))
            for binding in keymap.BINDINGS:
                if binding.context != context:
                    continue
                text = _('  oder  ').join(QKeySequence(k).toString(QKeySequence.SequenceFormat.NativeText)
                                       for k in binding.keys)
                rows.append((_(binding.label), text))
        rows.append((_('Weitere'), None))
        rows.append((_('Großansicht blättern'), '←  →'))
        alt = QKeySequence('Alt+Left').toString(QKeySequence.SequenceFormat.NativeText).replace('←', '').strip()
        rows.append((_('Großansicht: Ausschnitt verschieben (mit ⇧ schneller)'),
                     _('{alt} + Pfeiltasten, mit der Maus ziehen').format(alt=alt)))
        rows.append((_('Großansicht: an der Maus zoomen'), _('{alt} + Mausrad, Doppelklick').format(alt=alt)))
        ctrl = QKeySequence('Ctrl+A').toString(QKeySequence.SequenceFormat.NativeText).replace('A', '').strip()
        rows.append((_('Großansicht: auf Stelle zoomen'), _('{ctrl} + Klick').format(ctrl=ctrl)))
        rows.append((_('Großansicht: Zoom stufenlos, 50–400 %'), _('Slider unten')))
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels([_('Aktion'), _('Taste')])
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
