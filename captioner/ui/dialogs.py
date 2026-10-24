"""Template, settings and shortcuts dialogs."""
import html
import re

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import geo, i18n, metadata
from ..i18n import _, N_
from ..scanner import Metadata
from ..roster import is_url
from .placepicker import PlacePickerDialog, place_completer, place_for_completion
from . import keymap, spelling
from ..templates import DEFAULT_CAPTION_SUFFIX, MatchTemplate, parse_headline

ROSTER_FILE_FILTER = N_('Roster-Dateien (*.txt *.tsv *.csv);;Alle Dateien (*)')


# Placeholders in the suffix: the field the value comes from, and a color that connects
# legend, field name, preview and frame (readable on light and dark backgrounds)
SUFFIX_PLACEHOLDERS = [
    ('headline', N_('Titel'), '#3b7dd8'), ('city', N_('Stadt'), '#3fa34d'),
    ('sublocation', N_('Ort / Halle'), '#e67e22'), ('state', N_('Bundesland'), '#16a085'),
    ('country', N_('Land'), '#b8860b'), ('country_code', N_('Ländercode'), '#827717'),
    ('creator', N_('Fotograf'), '#d63384'), ('contact_email', N_('E-Mail'), '#ad1457'),
    ('authors_position', N_('Position'), '#20a8d8'), ('credit', N_('Credit'), '#6d4c41'),
    ('caption_writer', N_('Beschriftet von'), '#8d6e63'),
    ('copyright', N_('Copyright'), '#5c6bc0'), ('web_statement', N_('Copyright-URL'), '#9e9d24'),
    ('source', N_('Quelle'), '#00897b'), ('category', N_('Kategorie'), '#78909c'),
    ('instructions', N_('Hinweise'), '#c0392b'),
    ('date', N_('Datum'), '#a66bd6')]
PLACEHOLDER_COLORS = {key: color for key, _label, color in SUFFIX_PLACEHOLDERS}
PLACEHOLDER_PATTERN = re.compile(r'\{(\w+)\}')


class MultiLineField(QPlainTextEdit):
    """Multi-line field with the QLineEdit interface the dialog uses (text())."""

    def __init__(self, value='', placeholder='', lines=4, parent=None):
        super().__init__(value, parent)
        self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)   # Tab moves on, as in the single-line fields
        metrics = self.fontMetrics()
        self.setFixedHeight(metrics.lineSpacing() * lines + 2 * round(self.document().documentMargin()) + 8)

    def text(self):
        return self.toPlainText()


def _split(text):
    return [part.strip() for part in text.split(',') if part.strip()]


class TemplateDialog(QDialog):
    """Edit a template: location, creator and rights, tags, suffix, optionally a fixed headline."""

    def __init__(self, template: MatchTemplate, places=None, parent=None):
        super().__init__(parent)
        self.places = places if places is not None else geo.PlaceBook()
        self.places_changed = False
        self.setWindowTitle(_('Template'))
        self.setMinimumWidth(760)   # room for the legend of the placeholders in three columns
        template = template or MatchTemplate()
        # fields scroll (the dialog is taller than a small laptop screen), buttons fixed below
        content = QWidget()
        form = QFormLayout(content)
        # the macOS default keeps fields at minimum width; here they should fill the dialog
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        def field(value, placeholder=''):
            edit = QLineEdit(value)
            edit.setPlaceholderText(placeholder)
            return edit

        self.name = field(template.name, _('z. B. DEL 2 Heimspiele'))
        self.headline = field(template.headline, _('leer = im Panel eintragen, z. B. DEL 2 - EC Bad Nauheim gegen …'))
        self.headline_hint = QLabel()
        self.headline_hint.setWordWrap(True)
        self.date = field(template.date, _('leer = Aufnahmedatum des Bildes, z. B. 18.10.26'))
        self.date.setToolTip(_('Fester Text für {date} im Anhang, z. B. um ein Template für ein kommendes '
                               'Spiel vorzubereiten. Danach wieder leeren.'))
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
        # coordinates from the file, as long as city/location are not changed
        self._file_place = geo.Place(template.city, template.sublocation, template.latitude, template.longitude)
        self.country_code = field(template.country_code, _('DEU (drei Buchstaben, ISO 3166)'))
        self.creator = field(template.creator, _('Vor- und Nachname'))
        self.contact_email = field(template.contact_email, _('E-Mail des Fotografen'))
        self.authors_position = field(template.authors_position, _('Fotograf'))
        self.credit = field(template.credit, _('Bildnachweis, z. B. Name/Agentur'))
        self.credit.setToolTip(_('IPTC „Credit Line“: wie der Bildnachweis abgedruckt werden soll. '
                                 'Höchstens 32 Bytes.'))
        self.caption_writer = field(template.caption_writer, _('wer beschriftet'))
        self.copyright = field(template.copyright, _('© 2026 Vor- und Nachname'))
        self.web_statement = field(template.web_statement, _('https://… (Nutzungsbedingungen, Lizenz)'))
        self.source = field(template.source, _('Agentur, Redaktion'))
        self.instructions = MultiLineField(template.instructions, _('Kontakt, Kontoverbindung, Honorarhinweis'))
        self.instructions.setToolTip(_('IPTC „Special Instructions“ (Lightroom: Anweisungen), z. B. '
                                       'Kontaktdaten oder Kontoverbindung. Höchstens 256 Bytes. Zeilen '
                                       'stehen im Bild durch „ · “ getrennt.'))
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
        form.addRow(_('Datum'), self.date)
        section(_('Ort'))
        form.addRow(_('Stadt'), city_row)
        form.addRow(_('Ort / Halle'), self.sublocation)
        form.addRow(_('Bundesland'), self.state)
        form.addRow(_('Land'), self.country)
        form.addRow(_('Ländercode'), self.country_code)
        section(_('Urheber und Rechte'))
        form.addRow(_('Fotograf'), self.creator)
        form.addRow(_('E-Mail'), self.contact_email)
        form.addRow(_('Position'), self.authors_position)
        form.addRow(_('Credit'), self.credit)
        form.addRow(_('Beschriftet von'), self.caption_writer)
        form.addRow(_('Copyright'), self.copyright)
        form.addRow(_('Copyright-URL'), self.web_statement)
        form.addRow(_('Quelle'), self.source)
        form.addRow(_('Hinweise'), self.instructions)
        section(_('Beschreibung und Tags'))
        form.addRow(_('Kategorie'), self.category)
        form.addRow(_('Zusatz-Tags'), self.extra_tags)
        form.addRow(_('Anhang'), self.suffix)
        # legend: where each placeholder comes from; a click inserts it at the cursor position
        form.addRow('', self._placeholder_box())
        # field names whose value ends up in the suffix get a dot in the placeholder's color
        # The field widgets are named like the placeholders (self.city, self.creator, ...)
        self._suffix_sources = {key: getattr(self, key) for key, _label, _color in SUFFIX_PLACEHOLDERS}
        self._source_labels = {key: (form.labelForField(city_row if key == 'city' else edit), _(label))
                               for key, label, _color in SUFFIX_PLACEHOLDERS
                               for edit in (self._suffix_sources[key],)}
        self.suffix.cursorPositionChanged.connect(self._highlight_source)
        self.suffix.installEventFilter(self)
        note = QLabel('<small>' + _('Gefüllte Felder gehen beim Speichern in jedes Bild, leere lassen den Wert '
                                  'des Bildes stehen. Heim und Gast stehen im Titel und ergeben sich aus den '
                                  'Codes in der Beschreibung.') + '</small>')
        note.setWordWrap(True)
        note.setMinimumWidth(560)   # like suffix_preview: otherwise estimated too tall, gap above it
        note.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.addRow('', note)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.scroll = QScrollArea()
        self.scroll.setWidget(content)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer = QVBoxLayout(self)
        outer.addWidget(self.scroll, 1)
        outer.addWidget(self.buttons)
        # as tall as the content, at most 90 % of the screen
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        available = screen.availableGeometry().height() if screen is not None else 900
        content.adjustSize()
        height = content.sizeHint().height() + self.buttons.sizeHint().height() + 40
        self.resize(max(760, content.sizeHint().width() + 30), min(height, int(available * 0.9)))

        for edit in self.findChildren(QLineEdit) + self.findChildren(MultiLineField):
            edit.textChanged.connect(self._update)
        self._update()

    def _placeholder_box(self):
        """
        Box below the suffix: placeholders as colored chips (a click inserts) with the field
        the value comes from, below that the result.
        """
        box = QFrame()
        box.setObjectName('placeholderBox')
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        self._legend_heading = QLabel(_('Platzhalter – Klick fügt ihn an der Cursorposition ein'))
        layout.addWidget(self._legend_heading)
        self._chips = {}

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        columns = 3
        for index, (key, label, _color) in enumerate(SUFFIX_PLACEHOLDERS):
            chip = self._chips[key] = QPushButton('{' + key + '}')
            bold = chip.font()
            bold.setBold(True)
            chip.setFont(bold)   # as a font, not in the style sheet: otherwise the width is computed without bold
            chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)   # never squeeze
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # Tab moves on from field to field
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(_('Fügt {placeholder} in den Anhang ein').format(placeholder='{' + key + '}'))
            chip.clicked.connect(lambda _checked=False, key=key: self._insert_placeholder(key))
            name = QLabel(_(label))
            entry = QHBoxLayout()
            entry.setSpacing(6)
            entry.addWidget(chip)
            entry.addWidget(name)
            entry.addStretch(1)
            grid.addLayout(entry, index // columns, index % columns)
        for column in range(columns):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)

        self.suffix_preview = QLabel()
        self.suffix_preview.setWordWrap(True)
        # a wrapped label estimates its height for a narrow width: room below the box
        self.suffix_preview.setMinimumWidth(560)
        self.suffix_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.suffix_preview)
        box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.placeholder_legend = box
        self._style_placeholder_box()
        return box

    # Colors from the current appearance (macOS light/dark), not fixed: a fixed grey
    # and the darker placeholder colors are hard to read on a black background

    def _dark(self):
        return self.palette().window().color().lightness() < 128

    def _color(self, key):
        """Color of a placeholder, lightened in dark mode."""
        color = QColor(PLACEHOLDER_COLORS[key])
        return color.lighter(140).name() if self._dark() else color.name()

    def _muted(self):
        """Muted text color: text color with less opacity instead of a fixed grey."""
        # mixed instead of rgba(): Qt's HTML in QLabel doesn't know opacity
        text, window = self.palette().windowText().color(), self.palette().window().color()
        mix = [round(a * 0.6 + b * 0.4) for a, b in zip(text.getRgb()[:3], window.getRgb()[:3])]
        return QColor(*mix).name()

    def _style_placeholder_box(self):
        window = self.palette().window().color()
        dark = self._dark()
        background = window.lighter(135) if dark else window.darker(104)
        border = window.lighter(185) if dark else window.darker(115)
        self.placeholder_legend.setStyleSheet(
            f'#placeholderBox {{ background: {background.name()}; border: 1px solid {border.name()}; '
            f'border-radius: 6px; }}')
        self._legend_heading.setStyleSheet(f'color: {self._muted()};')
        fill, hover = (45, 90) if dark else (30, 70)
        for key, chip in self._chips.items():
            color = QColor(self._color(key))
            rgb = f'{color.red()}, {color.green()}, {color.blue()}'
            chip.setStyleSheet(
                f'QPushButton {{ color: {color.name()}; border: 1px solid {color.name()}; border-radius: 9px; '
                f'padding: 1px 6px; background: rgba({rgb}, {fill}); }}'
                f'QPushButton:hover {{ background: rgba({rgb}, {hover}); }}')

    def changeEvent(self, event):
        """Appearance switched while the dialog is open."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, '_chips'):
            self._style_placeholder_box()
            self._update()
            self._highlight_source()

    def _insert_placeholder(self, key):
        self.suffix.insert('{' + key + '}')
        self.suffix.setFocus()

    def eventFilter(self, watched, event):
        if watched is self.suffix and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._highlight_source()
        return super().eventFilter(watched, event)

    def placeholder_at_cursor(self):
        """Placeholder the cursor is on in the suffix, otherwise None."""
        position = self.suffix.cursorPosition()
        for match in PLACEHOLDER_PATTERN.finditer(self.suffix.text()):
            if match.start() <= position <= match.end() and match.group(1) in PLACEHOLDER_COLORS:
                return match.group(1)
        return None

    def _highlight_source(self):
        """If the cursor in the suffix is on {city}, the city field gets a colored outline."""
        key = self.placeholder_at_cursor() if self.suffix.hasFocus() else None
        for name, edit in self._suffix_sources.items():
            kind = 'QPlainTextEdit' if isinstance(edit, QPlainTextEdit) else 'QLineEdit'
            edit.setStyleSheet(f'{kind} {{ border: 2px solid {self._color(name)}; border-radius: 4px; }}'
                               if name == key else '')

    def suffix_preview_html(self):
        """Example: caption with suffix, inserted values in the color of their placeholder."""
        template = MatchTemplate(caption_suffix=self.suffix.text())
        values = {
            # empty in the template: when saving the value comes from the panel or the image
            'headline': self.headline.text().strip() or _('Titel aus dem Panel'),
            'city': self.city.text().strip() or _('Stadt aus dem Panel'),
            'sublocation': self.sublocation.text().strip() or _('Ort aus dem Panel'),
        }
        for key, (_label, text) in self._source_labels.items():
            if key not in values:
                values[key] = self._suffix_sources[key].text().strip() or _('{field} (vom Bild)').format(field=text)
        # control characters as markers: they survive the comma clean-up and html.escape
        text = template.compose_caption('\x05', mark=lambda key, value: f'\x01{key}\x02{value}\x03', **values)
        text = html.escape(text)
        text = re.sub('\x01(\\w+)\x02(.*?)\x03',
                      lambda m: f'<b style="color:{self._color(m.group(1))}">{m.group(2)}</b>', text)
        sample = f'<i style="color:{self._muted()}">' + html.escape(_('Beschreibung des Bildes')) + '</i>'
        return '<b>' + html.escape(_('Ergebnis:')) + '</b> ' + text.replace('\x05', sample)

    def pick_place(self):
        current = self.places.lookup(self.city.text(), self.sublocation.text()) or self._place()
        dialog = PlacePickerDialog(current, self.places, self)
        if dialog.exec():
            place = dialog.place()
            self.city.setText(place.city)
            self.sublocation.setText(place.sublocation)
            # the address search also returns state and country
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
        """City/location from the fields, coordinates from the place book or the file."""
        city, sublocation = self.city.text().strip(), self.sublocation.text().strip()
        known = self.places.lookup(city, sublocation)
        if known and known.has_coordinates:
            return geo.Place(city, sublocation, known.latitude, known.longitude)
        if self._file_place.key() == geo.Place(city, sublocation).key():
            return geo.Place(city, sublocation, self._file_place.latitude, self._file_place.longitude)
        return geo.Place(city, sublocation)

    def _too_long(self):
        """Fields that are too long (IPTC limits)."""
        template = self.template()
        return metadata.validate(Metadata(headline=template.headline, city=template.city,
                                          sublocation=template.sublocation, **template.fixed_values()))

    def problems(self):
        """Fields that are too long (IPTC limits) and a headline in the wrong format."""
        problems = self._too_long()
        headline = self.headline.text().strip()
        if headline and parse_headline(headline) is None:
            problems.insert(0, _('Titel nicht im Format „<Anlass> - <Heim> gegen <Gast>“ – '
                                 'die Personenerkennung erkennt das Spiel dann nicht'))
        return problems

    def _update(self):
        self.suffix_preview.setText(self.suffix_preview_html())
        suffix = self.suffix.text()
        for key, (label, text) in self._source_labels.items():
            used = '{' + key + '}' in suffix
            label.setText(f'<span style="color:{self._color(key)}">●</span> {html.escape(text)}'
                          if used else html.escape(text))
            label.setToolTip(_('Wird über {placeholder} an die Beschreibung angehängt').format(
                placeholder='{' + key + '}') if used else '')
        problems = self.problems()
        self.headline_hint.setText('<small style="color:#d64541">' + html.escape('; '.join(problems)) + '</small>'
                                   if problems else '')
        self.headline_hint.setVisible(bool(problems))
        # only fields that are too long block; a deviating headline is allowed
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
            country_code=self.country_code.text().strip().upper(),
            extra_tags=_split(self.extra_tags.text()),
            caption_suffix=self.suffix.text(),
            date=self.date.text().strip(),
            creator=self.creator.text().strip(),
            contact_email=self.contact_email.text().strip(),
            authors_position=self.authors_position.text().strip(),
            credit=self.credit.text().strip(),
            caption_writer=self.caption_writer.text().strip(),
            copyright=self.copyright.text().strip(),
            web_statement=self.web_statement.text().strip(),
            source=self.source.text().strip(),
            category=self.category.text().strip(),
            instructions=self.instructions.text().strip(),
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
            self.language.addItem(name, code)   # in their own language, not translated
        self.language.setCurrentIndex(max(0, self.language.findData(getattr(settings, 'language', ''))))
        language_row = QHBoxLayout()
        language_row.addWidget(self.language)
        language_hint = QLabel('<small>' + _('Gilt nach einem Neustart.') + '</small>')
        language_hint.setStyleSheet('color: gray;')
        language_row.addWidget(language_hint, 1)

        form.addRow(_('Roster-Quellen'), self.sources)
        form.addRow(_('Cache für URLs'), self.ttl)
        form.addRow(_('Code-Trennzeichen'), self.delimiter)
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
        self.spellcheck = QComboBox()
        for label, value in ((N_('Automatisch (macOS)'), 'auto'), (N_('Deutsch'), 'de'), (N_('Englisch'), 'en'),
                             (N_('Aus'), 'off')):
            self.spellcheck.addItem(_(label), value)
        self.spellcheck.setCurrentIndex(max(0, self.spellcheck.findData(getattr(settings, 'spellcheck', 'auto'))))
        if spelling.checker() is None:
            self.spellcheck.setEnabled(False)
            self.spellcheck.setToolTip(_('Nur unter macOS verfügbar'))
        form.addRow(_('Rechtschreibprüfung'), self.spellcheck)
        self.check_updates = QCheckBox(_('Beim Start nach Updates suchen (höchstens einmal am Tag, bei GitHub)'))
        self.check_updates.setChecked(getattr(settings, 'check_updates', True))
        form.addRow('', self.check_updates)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self):
        s = self.settings
        s.roster_sources = self.sources.sources()
        s.roster_cache_ttl_minutes = self.ttl.value()
        s.code_delimiter = self.delimiter.text().strip() or '#'
        s.recursive = self.recursive.isChecked()
        s.labels = _split(self.labels.text()) or s.labels
        s.drag_include_sidecars = self.drag_sidecars.isChecked()
        s.exiftool_path = self.exiftool.text().strip()
        s.language = self.language.currentData()
        s.spellcheck = self.spellcheck.currentData()
        s.check_updates = self.check_updates.isChecked()
        return s


class RosterSourceList(QWidget):
    """Roster sources: files on the computer and URLs. On conflicts the upper one wins."""

    def __init__(self, sources, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMinimumHeight(110)
        # shorten long paths in the middle, file name and beginning stay visible
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
    """Overview of all shortcuts, generated from keymap.BINDINGS - can't get out of date."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Tastenkürzel'))
        self.resize(640, 720)
        layout = QVBoxLayout(self)
        rows = []
        for context, title in keymap.CONTEXT_TITLES.items():
            rows.append((_(title), None))
            for binding in keymap.BINDINGS:
                if binding.context != context or not binding.keys:   # not shown without shortcuts (customized)
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
