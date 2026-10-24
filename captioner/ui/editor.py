"""
Caption panel: template, headline, caption with code replacement, tags, location.

The caption shows live what the codes turn into; unknown codes are red and block
saving (ADR 0001, item 5).
"""
import dataclasses
import html
import re
import sys
from pathlib import Path

from PySide6.QtCore import QSize, QStringListModel, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from .. import codes, geo, keywords, metadata
from . import spelling
from ..i18n import _, ngettext
from .keymap import keys as binding_keys
from .placepicker import PlacePickerDialog, place_completer, place_for_completion
from ..templates import parse_headline, unique


def template_folder_label():
    """Menu item with the system's file manager."""
    if sys.platform == 'darwin':
        return _('Template-Ordner im Finder öffnen')
    if sys.platform == 'win32':
        return _('Template-Ordner im Explorer öffnen')
    return _('Template-Ordner öffnen')


# marks replacements on their way into the preview (characters from the private use area, never in the text)
MARK_START, MARK_END = '\ue000', '\ue001'


def shortcut_text(command):
    """First shortcut of a command in the platform's notation (with ⌘ on the Mac), '–' without one."""
    keys = binding_keys(command)
    return QKeySequence(keys[0]).toString(QKeySequence.SequenceFormat.NativeText) if keys else '–'


class WrappingLineEdit(QPlainTextEdit):
    """Single-line text, wrapped for display. Enter saves, never a line break."""
    submit = Signal()  # Enter: save, stay on the image

    def __init__(self, lines=None, parent=None):
        super().__init__(parent)
        self.setTabChangesFocus(True)
        if lines:
            margins = self.contentsMargins()
            height = (self.fontMetrics().lineSpacing() * lines + 2 * self.document().documentMargin()
                      + margins.top() + margins.bottom() + 2 * self.frameWidth())
            self.setFixedHeight(int(height))

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(text)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # with a modifier the key belongs to the shortcuts (e.g. Cmd/Ctrl+Enter)
            if event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
                event.ignore()
            else:
                self.submit.emit()
            return
        super().keyPressEvent(event)


class TagTextEdit(WrappingLineEdit):
    """Tag field: suggests remembered keywords for the tag being typed."""

    def __init__(self, lines=None, parent=None):
        super().__init__(lines=lines, parent=parent)
        self.history = None   # keywords.KeywordHistory
        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setMaxVisibleItems(10)
        self.completer.activated.connect(self._insert_completion)
        self.model = QStringListModel(self)
        self.completer.setModel(self.model)

    def _tags(self):
        return [t.strip() for t in re.split(r'[,\n]', self.toPlainText()) if t.strip()]

    def _insert_completion(self, word):
        cursor = self.textCursor()
        start, token = keywords.current_token(self.toPlainText(), cursor.position())
        cursor.setPosition(start)
        cursor.setPosition(self.textCursor().position(), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(word + ', ')
        self.setTextCursor(cursor)
        self.completer.popup().hide()

    def keyPressEvent(self, event):
        popup = self.completer.popup()
        if popup.isVisible() and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab,
                                                 Qt.Key.Key_Escape, Qt.Key.Key_Backtab):
            event.ignore()
            return
        super().keyPressEvent(event)
        if self.history is None or event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        _start, token = keywords.current_token(self.toPlainText(), self.textCursor().position())
        others = [t for t in self._tags() if t != token]
        words = self.history.suggestions(token, exclude=others)
        if not words or (len(words) == 1 and words[0].casefold() == token.casefold()):
            popup.hide()
            return
        self.model.setStringList(words)
        popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(min(360, self.width()))
        self.completer.complete(rect)


class VerticalScrollArea(QScrollArea):
    """
    Scrolls only vertically and is at least as wide as the content needs (plus scroll bar).
    QScrollArea otherwise reports a tiny minimum width: with a narrow window the content stuck
    out on the right (roster button, field edges gone), by different amounts per style/font.
    """

    def __init__(self, min_width=0, parent=None):
        super().__init__(parent)
        self.min_width = min_width
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def setWidget(self, widget):
        # No event filter on the content: the panel moves between main window and preview,
        # a filter of the old area crashed Python on teardown (macOS action)
        super().setWidget(widget)
        self.updateGeometry()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        width = self.min_width
        widget = self.widget()
        if widget is not None:
            needed = max(widget.minimumSizeHint().width(), widget.minimumWidth())
            width = max(width, needed + self.verticalScrollBar().sizeHint().width() + 2 * self.frameWidth())
        return QSize(max(hint.width(), width), hint.height())


class CodeTextEdit(WrappingLineEdit):
    """Caption: wrapping single-line field with autocompletion after '#'."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.delimiter = '#'
        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setModelSorting(QCompleter.ModelSorting.UnsortedModel)
        self.completer.setMaxVisibleItems(12)
        self.completer.activated.connect(self._insert_completion)
        self.model = QStringListModel(self)
        self.completer.setModel(self.model)
        self.spelling = spelling.SpellHighlighter(self.document(), spelling.checker(), self.delimiter)

    def contextMenuEvent(self, event):
        """Right-click on an underlined word: suggestions, learn, ignore."""
        menu = self.createStandardContextMenu(event.pos())
        cursor = self.cursorForPosition(event.pos())
        block = cursor.block()
        position = cursor.positionInBlock()
        hit = next(((start, length, word) for start, length, word in self.spelling.misspelled(block.text())
                    if start <= position <= start + length), None)
        if hit is not None:
            start, length, word = hit
            first = menu.actions()[0] if menu.actions() else None
            checker = self.spelling.spell_checker
            suggestions = checker.suggestions(block.text(), start, length, self.spelling.language)
            for suggestion in suggestions:
                action = QAction(suggestion, menu)
                action.triggered.connect(lambda _=False, s=suggestion: self._replace(block, start, length, s))
                menu.insertAction(first, action)
            if not suggestions:
                none = QAction(_('Keine Vorschläge'), menu)
                none.setEnabled(False)
                menu.insertAction(first, none)
            learn = QAction(_('Ins Wörterbuch aufnehmen'), menu)
            learn.triggered.connect(lambda: (checker.learn(word), self.spelling.rehighlight()))
            ignore = QAction(_('Ignorieren'), menu)
            ignore.triggered.connect(lambda: (self.spelling.ignored.add(word.casefold()), self.spelling.rehighlight()))
            menu.insertAction(first, learn)
            menu.insertAction(first, ignore)
            menu.insertSeparator(first)
        menu.exec(event.globalPos())

    def _replace(self, block, start, length, text):
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + start)
        cursor.setPosition(block.position() + start + length, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)

    def set_completions(self, entries):
        self.model.setStringList([f'{e.code}\t{e.replacement}' for e in entries])

    def _prefix(self):
        cursor = self.textCursor()
        before = self.toPlainText()[:cursor.position()]
        return codes.open_code_prefix(before, self.delimiter)

    def _insert_completion(self, completion):
        code = completion.split('\t', 1)[0]
        prefix = self._prefix() or ''
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, len(prefix))
        cursor.insertText(code + self.delimiter)
        self.setTextCursor(cursor)

    def keyPressEvent(self, event):
        popup = self.completer.popup()
        if popup.isVisible() and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab,
                                                 Qt.Key.Key_Escape, Qt.Key.Key_Backtab):
            event.ignore()
            return
        super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        prefix = self._prefix()
        if prefix is None:
            popup.hide()
            return
        self.completer.setCompletionPrefix(prefix)
        if self.completer.completionCount() == 0:
            popup.hide()
            return
        popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(min(520, self.width() + 160))
        self.completer.complete(rect)


class CaptionEditor(QWidget):
    save_requested = Signal(dict, int)    # fields, then: +1 next, -1 previous, 0 stay
    navigate_requested = Signal(int)      # to the next/previous image without saving
    snapshot_take_requested = Signal()    # "Copy" button, like snapshot_take
    snapshot_paste_requested = Signal()   # "Paste" button, like snapshot_paste
    apply_template_requested = Signal()
    template_changed = Signal(object)
    edit_template_requested = Signal(object)   # None = new template
    copy_template_requested = Signal(object)   # new template with the values of this one
    template_from_photo_requested = Signal()   # new template from the image's caption
    open_template_folder_requested = Signal()  # configuration folder of the templates in the file manager
    open_template_requested = Signal()
    save_template_as_requested = Signal()
    remove_template_requested = Signal(object)
    reload_roster_requested = Signal()
    place_chosen = Signal(object)         # geo.Place from the map or a suggestion: remember it
    add_roster_file_requested = Signal()
    edit_roster_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.roster = None
        self.template = None
        self.templates = []
        self.delimiter = '#'
        self._build()

    def _build(self):
        # A scroll bar instead of squeezing: if the height isn't enough (small window, preview),
        # the fields keep their minimum height, otherwise the preview slid into the caption field.
        # Byte counter and buttons stay fixed below (footer), always reachable
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = VerticalScrollArea(min_width=380)
        content = QWidget()
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll, 1)
        layout = QVBoxLayout(content)
        footer = QVBoxLayout()
        footer.setContentsMargins(layout.contentsMargins().left(), 4, layout.contentsMargins().right(),
                                  layout.contentsMargins().bottom())
        outer.addLayout(footer)

        # template: selection, one visible button (Edit), the rest in the "⋯" menu
        template_row = QHBoxLayout()
        self.template_box = QComboBox()
        self.template_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Not as wide as the longest name: otherwise the panel (preview, narrow window) sticks
        # out of the scroll area on the right and takes the roster button and field edges with it
        self.template_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.template_box.setMinimumContentsLength(12)
        self.template_box.currentIndexChanged.connect(self._template_selected)
        self.edit_template_button = QPushButton(_('Bearbeiten …'))
        self.edit_template_button.setToolTip(_('Gewähltes Template anzeigen und ändern'))
        self.edit_template_button.clicked.connect(lambda: self.edit_template_requested.emit(self.template))
        self.template_menu = QMenu(self)
        self.template_menu.addAction(_('Neues Template …'), lambda: self.edit_template_requested.emit(None))
        self.copy_action = self.template_menu.addAction(
            _('Neues Template aus diesem …'), lambda: self.template and self.copy_template_requested.emit(self.template))
        self.template_menu.addAction(_('Template aus Foto erzeugen …'), self.template_from_photo_requested.emit)
        self.template_menu.addAction(_('Template-Datei laden …'), self.open_template_requested.emit)
        self.template_menu.addSeparator()
        self.save_as_action = self.template_menu.addAction(_('Speichern unter …'), self.save_template_as_requested.emit)
        self.remove_action = self.template_menu.addAction(
            _('Aus der Liste entfernen'), lambda: self.template and self.remove_template_requested.emit(self.template))
        self.template_menu.addSeparator()
        self.template_menu.addAction(template_folder_label(), self.open_template_folder_requested.emit)
        more_button = QToolButton(text='⋯')
        more_button.setToolTip(_('Neues Template, aus diesem, aus Foto, Datei laden, speichern unter, entfernen, '
                                 'Ordner öffnen'))
        more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_button.setMenu(self.template_menu)
        more_button.setStyleSheet('QToolButton::menu-indicator { image: none; width: 0; }')
        template_row.addWidget(QLabel(_('Template:')))
        template_row.addWidget(self.template_box, 1)
        template_row.addWidget(self.edit_template_button)
        template_row.addWidget(more_button)
        layout.addLayout(template_row)

        self.apply_button = QPushButton(_('Template auf Auswahl anwenden'))
        self.apply_button.setToolTip(_('Titel, Ort und Tags des Templates in alle ausgewählten Bilder schreiben; '
                                       'Beschreibungen bleiben erhalten, außer bei „Inhalte überschreiben“'))
        self.apply_button.clicked.connect(self.apply_template_requested)
        # checked, applying resets everything to the template (the caption too)
        self.overwrite_box = QCheckBox(_('Inhalte überschreiben'))
        self.overwrite_box.setChecked(True)
        self.overwrite_box.setToolTip(_('Beim Anwenden Titel, Ort und Tags genau auf die Werte des Templates setzen '
                                        'und die Beschreibung leeren; bisherige Änderungen gehen verloren'))
        apply_row = QHBoxLayout()
        apply_row.addWidget(self.apply_button, 1)
        apply_row.addWidget(self.overwrite_box)
        layout.addLayout(apply_row)

        form = QFormLayout()
        # macOS otherwise keeps fields at minimum width (headline, city, location were cut off)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.headline = QLineEdit()
        self.headline.setPlaceholderText('DEL 2 - EC Bad Nauheim gegen Eisbären Regensburg')
        # teams for the code suggestions if the template doesn't define any
        self.headline.textChanged.connect(self._update_completions)
        self.headline_hint = QLabel('<small>' + html.escape(
            _('Format „<Anlass> - <Heim> gegen <Gast>“, sonst erkennt die Personenerkennung das Spiel nicht'),
            quote=False) + '</small>')
        self.headline_hint.setStyleSheet('color: #d64541;')
        self.headline_hint.setWordWrap(True)
        self.headline_hint.hide()
        self.headline_preview = QLabel()
        self.headline_preview.setWordWrap(True)
        self.headline_preview.hide()
        self.caption = CodeTextEdit()
        self.caption.setPlaceholderText(_('Zweikampf #bi99# gegen #bn23#'))
        self.caption.setMinimumHeight(90)
        self.caption.textChanged.connect(self._update_preview)
        self.caption.submit.connect(lambda: self.submit(0))
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        # tags wrapped like the caption, but lower
        self.keywords = TagTextEdit(lines=3)
        self.keywords.setPlaceholderText(_('Tags, kommagetrennt'))
        self.keywords.textChanged.connect(self._update_preview)
        self.keywords.submit.connect(lambda: self.submit(0))
        self.city = QLineEdit()
        self.city.setPlaceholderText(_('tippen für gemerkte Orte'))
        self.sublocation = QLineEdit()
        for field in (self.headline, self.city, self.sublocation):
            field.textChanged.connect(self._update_preview)
            field.returnPressed.connect(lambda: self.submit(0))
        self.map_button = QPushButton(_('Karte …'))
        self.map_button.setToolTip(_('Ort auf der Karte oder per Adresssuche wählen (OpenStreetMap)'))
        self.map_button.clicked.connect(self.pick_place)
        city_row = QHBoxLayout()
        city_row.setContentsMargins(0, 0, 0, 0)
        city_row.addWidget(self.city, 1)
        city_row.addWidget(self.map_button)
        self.gps_hint = QLabel()
        self.gps_hint.setStyleSheet('color: gray;')
        # what the template writes into every image for location/creator/rights
        self.rights_hint = QLabel()
        self.rights_hint.setWordWrap(True)
        self.rights_hint.setStyleSheet('color: gray;')
        # fixed date in the template that doesn't match the image (prepared and forgot to clear it?)
        self.date_hint = QLabel()
        self.date_hint.setWordWrap(True)
        self.date_hint.hide()

        def column(*widgets):
            # Field with its hints below; hidden hints take no space
            # (as separate form rows they left gaps)
            box = QVBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(3)
            for widget in widgets:
                box.addWidget(widget)
            return box

        form.setVerticalSpacing(8)
        form.addRow(_('Titel'), column(self.headline, self.headline_preview, self.headline_hint))
        form.addRow(_('Beschreibung'), column(self.caption, self.preview, self.date_hint))
        form.addRow(_('Tags'), self.keywords)
        form.addRow(_('Stadt'), city_row)
        form.addRow(_('Ort'), column(self.sublocation, self.gps_hint, self.rights_hint))
        layout.addLayout(form)

        self.limits = QLabel()
        self.limits.setWordWrap(True)

        # caption from image to image, like the shortcuts snapshot_take/snapshot_paste
        snapshot_buttons = QHBoxLayout()
        snapshot_buttons.addWidget(self.limits, 1)
        self.snapshot_take_button = QPushButton(_('Kopieren'))
        self.snapshot_take_button.clicked.connect(self.snapshot_take_requested)
        self.snapshot_paste_button = QPushButton(_('Einfügen'))
        self.snapshot_paste_button.clicked.connect(self.snapshot_paste_requested)
        snapshot_buttons.addWidget(self.snapshot_take_button)
        snapshot_buttons.addWidget(self.snapshot_paste_button)
        footer.addLayout(snapshot_buttons)
        self.has_snapshot = False

        buttons = QHBoxLayout()
        self.save_button = QPushButton(_('Speichern'))
        self.save_button.clicked.connect(lambda: self.submit(0))
        self.next_button = QPushButton(_('Speichern && weiter'))
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(lambda: self.submit(1))
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.next_button)
        footer.addLayout(buttons)

        self.shortcut_hint = QLabel()
        self.shortcut_hint.setWordWrap(True)
        self.shortcut_hint.setStyleSheet('color: gray; font-size: 11px;')
        layout.addWidget(self.shortcut_hint)
        self.update_shortcut_texts()

        # roster: one status line (sources in the tooltip, problems visible), commands in the menu
        self.roster_status = QLabel()
        self.roster_status.setWordWrap(True)
        self.roster_menu = QMenu(self)
        self.roster_menu.addAction(_('Roster bearbeiten …'), self.edit_roster_requested.emit)
        self.roster_menu.addAction(_('Roster neu laden'), self.reload_roster_requested.emit)
        self.roster_menu.addAction(_('Roster-Datei hinzufügen …'), self.add_roster_file_requested.emit)
        roster_button = QPushButton(_('Roster'))
        roster_button.setToolTip(_('Roster bearbeiten, neu laden oder eine Roster-Datei (Code ⇥ Ersetzung) '
                                   'vom Rechner hinzufügen'))
        roster_button.setMenu(self.roster_menu)
        roster_row = QHBoxLayout()
        roster_row.addWidget(self.roster_status, 1)
        roster_row.addWidget(roster_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)
        layout.addLayout(roster_row)

        self.selection_info = QLabel()
        layout.insertWidget(0, self.selection_info)

        self.set_enabled(False)

    # --- State from outside ---------------------------------------------------

    def set_enabled(self, enabled):
        for widget in (self.headline, self.caption, self.keywords, self.city, self.sublocation,
                       self.map_button, self.save_button, self.next_button, self.apply_button,
                       self.overwrite_box, self.snapshot_take_button):
            widget.setEnabled(enabled)
        self.snapshot_paste_button.setEnabled(enabled and self.has_snapshot)

    def set_has_snapshot(self, present):
        """Paste only once something has been copied."""
        self.has_snapshot = present
        self.snapshot_paste_button.setEnabled(present and self.snapshot_take_button.isEnabled())

    def set_place_book(self, book):
        """Remembered places: suggestions for the city and coordinates for the GPS note."""
        self.place_book = book
        completer = place_completer(book, self)
        completer.activated.connect(self._known_place_chosen)
        self.city.setCompleter(completer)
        self._update_preview()

    def _known_place_chosen(self, text):
        place = place_for_completion(self.place_book, text)
        if place:
            self.city.setText(place.city)
            self.sublocation.setText(place.sublocation)
            self.place_chosen.emit(place)

    def pick_place(self):
        book = getattr(self, 'place_book', None) or geo.PlaceBook()
        current = book.lookup(self.city.text(), self.sublocation.text()) or \
            geo.Place(self.city.text().strip(), self.sublocation.text().strip())
        dialog = PlacePickerDialog(current, book, self)
        if not dialog.exec():
            return
        place = dialog.place()
        self.city.setText(place.city)
        self.sublocation.setText(place.sublocation)
        self.place_chosen.emit(place)
        self._update_preview()

    def set_roster(self, roster, delimiter):
        self.roster = roster
        self.delimiter = delimiter
        self.caption.delimiter = delimiter
        # names from the roster are not typos; codes neither
        self.caption.spelling.set_delimiter(delimiter)
        self.caption.spelling.set_known_words(
            [e.replacement for e in roster.entries.values()] + list(roster.teams) if roster else [])
        # codes in the field: known ones green, unknown ones red background
        self.caption.spelling.set_lookup(roster.lookup if roster else None)
        self._update_completions()
        self._update_preview()

    def set_spellcheck(self, language):
        """'auto' (macOS chooses), 'de', 'en' or 'off'."""
        highlighter = self.caption.spelling
        highlighter.enabled = highlighter.spell_checker is not None and language != 'off'
        highlighter.language = language if language in ('de', 'en') else None
        highlighter.rehighlight()

    def set_roster_status(self, summary, details=(), problems=()):
        """Summary (HTML) and problems visible, sources and state in the tooltip."""
        self.roster_status.setText('<br>'.join([summary, *problems]))
        self.roster_status.setToolTip('<br>'.join(details))

    def set_templates(self, templates, active_path=''):
        """Templates are identified by their file path, names can be duplicated."""
        self.templates = templates
        self.template_box.blockSignals(True)
        self.template_box.clear()
        self.template_box.addItem(_('— kein Template —'), None)
        selected = 0
        names = [t.display_name() for t in templates]
        for index, template in enumerate(templates, start=1):
            label = template.display_name()
            if names.count(label) > 1:
                label += f'  ({Path(template.path).name})'
            self.template_box.addItem(label, template)
            self.template_box.setItemData(index, template.path, Qt.ItemDataRole.ToolTipRole)
            if template.path and template.path == active_path:
                selected = index
        self.template_box.setCurrentIndex(selected)
        self.template_box.blockSignals(False)
        self._template_selected(selected)

    def _template_selected(self, index):
        self.template = self.template_box.itemData(index)
        path = self.template.path if self.template else ''
        # file only in the tooltip (used to be a separate line below)
        self.template_box.setToolTip(path)
        for widget in (self.copy_action, self.save_as_action, self.remove_action, self.edit_template_button):
            widget.setEnabled(self.template is not None)
        self._update_completions()
        self.template_changed.emit(self.template)

    def _update_completions(self):
        if not self.roster:
            self.caption.set_completions([])
            return
        teams = self.template.teams if self.template else []
        if not teams:
            parsed = parse_headline(self.resolve_headline().text if self.roster else self.headline.text())
            teams = list(parsed[1:]) if parsed else []
        if teams == getattr(self, '_completion_teams', None) and self.roster is getattr(self, '_completion_roster', None):
            return
        self._completion_teams, self._completion_roster = teams, self.roster
        first = [e for team in teams for e in self.roster.codes_for_team(team)]
        rest = [e for e in self.roster.entries.values() if e not in first]
        self.caption.set_completions(first + rest)

    def show_items(self, items, raw_lookup=None, carry_over_headline=None):
        """Fill the fields from the first selected item."""
        self.set_enabled(bool(items))
        if not items:
            self.selection_info.setText(_('Keine Auswahl'))
            for field in (self.headline, self.keywords, self.city, self.sublocation):
                field.clear()
            self.caption.setPlainText('')
            return
        item = items[0]
        count = len(items)
        self.selection_info.setText(
            f'<b>{html.escape(item.name)}</b>' if count == 1
            else _('<b>{count} Bilder ausgewählt</b> – Speichern schreibt in alle').format(count=count))
        meta = item.meta
        # without a fixed headline in the template: the one saved last, so it isn't typed per image
        headline = meta.headline or (self.template.headline if self.template else '') or carry_over_headline or ''
        city = meta.city or (self.template.city if self.template else '')
        sublocation = meta.sublocation or (self.template.sublocation if self.template else '')
        keywords = meta.keywords or (self.template.keywords if self.template else [])
        raw = raw_lookup(item) if raw_lookup else None
        if raw is None:
            # uncaptioned: empty, never the caption of the previous image
            raw = self._strip_suffix(meta.caption, item) if meta.caption else ''
        self.headline.setText(headline)
        self.city.setText(city)
        self.sublocation.setText(sublocation)
        # show long headlines from the start, not scrolled to the end ("L 2 - EC Bad …")
        for field in (self.headline, self.city, self.sublocation):
            field.setCursorPosition(0)
        self.keywords.setText(', '.join(self._without_persons(keywords, meta.caption)))
        self.caption.setPlainText(raw)
        self._current_item = item
        self._shown_caption = raw
        self._update_preview()

    def _replacement_color(self):
        """Green background for replacements, readable on light and dark backgrounds."""
        dark = self.palette().window().color().lightness() < 128
        return '#24502e' if dark else '#cdeccf'

    def _strip_suffix(self, caption, item):
        if self.template:
            meta = item.meta
            suffix = self.template.suffix_for(item.taken_at, headline=meta.headline, city=meta.city,
                                              sublocation=meta.sublocation, **self.template.field_values(meta))
            if suffix and caption.endswith(suffix):
                return caption[:-len(suffix)]
        return caption

    def _without_persons(self, keywords, caption):
        """Person tags are recreated from the caption when saving."""
        persons = set(codes.persons_in(caption, self.roster))
        return [k for k in keywords if k not in persons]

    def update_shortcut_texts(self):
        """Shortcuts in tooltips and the hint; refreshed after "Customize keyboard shortcuts"."""
        self.snapshot_take_button.setToolTip(_('Beschriftung dieses Bildes kopieren ({keys})').format(
            keys=shortcut_text('snapshot_take')))
        self.snapshot_paste_button.setToolTip(_('Kopierte Beschriftung in die Auswahl einfügen und speichern ({keys})').format(
            keys=shortcut_text('snapshot_paste')))
        self.shortcut_hint.setText(_('Enter speichert · {save_next} speichert und weiter · '
                                     '{save_close} speichert und zurück zur Galerie · {shortcuts} alle Tastenkürzel').format(
            save_next=shortcut_text('save_next'), save_close=shortcut_text('save_close'),
            shortcuts=shortcut_text('shortcuts')))

    def focus_caption(self):
        """Caption selected, so typing replaces it."""
        self.caption.setFocus()
        cursor = self.caption.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self.caption.setTextCursor(cursor)

    # --- Preview and saving ---------------------------------------------------

    def resolve(self):
        return codes.resolve(self.caption.toPlainText(), self.roster, self.delimiter)

    def resolve_headline(self):
        """Codes in the headline too, e.g. 'DEL 2 - #bn# gegen #kh#' with team codes in the roster."""
        return codes.resolve(self.headline.text().strip(), self.roster, self.delimiter)

    def set_keyword_history(self, history):
        self.keywords.history = history

    def tags(self):
        # pasted text may contain line breaks; they separate like commas
        return [t.strip() for t in re.split(r'[,\n]', self.keywords.text()) if t.strip()]

    def _update_preview(self):
        headline_resolution = self.resolve_headline()
        headline = metadata.single_line(headline_resolution.text)
        self.headline_hint.setVisible(bool(headline) and not headline_resolution.unknown
                                      and parse_headline(headline) is None)
        if headline_resolution.unknown:
            self.headline_preview.setText('<span style="color:#d64541">' + html.escape(
                _('Unbekannte Codes im Titel: {codes}').format(codes=', '.join(headline_resolution.unknown)))
                + '</span>')
        elif headline != self.headline.text().strip():
            self.headline_preview.setText('<span style="color:gray">→ ' + html.escape(headline) + '</span>')
        self.headline_preview.setVisible(bool(headline_resolution.unknown) or headline != self.headline.text().strip())
        raw = self.caption.toPlainText()
        resolution = self.resolve()
        item = getattr(self, '_current_item', None)

        def compose(text):
            text = metadata.single_line(text)
            if self.template and text:
                text = self.template.compose_caption(
                    text, item.taken_at if item else '', headline=headline,
                    city=self.city.text().strip(), sublocation=self.sublocation.text().strip(),
                    **(self.template.field_values(item.meta) if item else {}))
            return text

        text = compose(resolution.text)
        # replacements highlighted green in the preview: you see what came from the roster
        marked = codes.resolve(raw, self.roster, self.delimiter,
                               wrap=lambda replacement: f'{MARK_START}{replacement}{MARK_END}')
        shown = html.escape(compose(marked.text))
        shown = shown.replace(MARK_START, f'<span style="background-color:{self._replacement_color()}">')
        shown = shown.replace(MARK_END, '</span>')
        for code in resolution.unknown:
            token = html.escape(f'{self.delimiter}{code}{self.delimiter}')
            shown = shown.replace(token, f'<span style="color:#d64541;font-weight:bold">{token}</span>')
        parts = [f'<span style="color:gray">→</span> {shown}' if raw.strip() else '']
        if resolution.unknown:
            parts.append('<span style="color:#d64541">' + html.escape(_('Unbekannte Codes: {codes}').format(
                codes=', '.join(resolution.unknown))) + '</span>')
        if resolution.persons:
            parts.append('<span style="color:gray">' + html.escape(_('Personen-Tags: {persons}').format(
                persons=', '.join(resolution.persons))) + '</span>')
        self.preview.setText('<br>'.join(p for p in parts if p))

        meta = metadata.Metadata(headline=headline, caption=text,
                                 keywords=unique(self.tags() + resolution.persons),
                                 city=self.city.text(), sublocation=self.sublocation.text())
        problems = metadata.validate(meta)
        size = len(text.encode('utf-8'))
        info = _('Beschreibung {size}/{limit} Bytes').format(size=size, limit=metadata.LIMITS['caption'])
        if problems:
            info += '<br><span style="color:#d64541">' + html.escape('; '.join(problems)) + '</span>'
        self.limits.setText(info)
        blocked = bool(resolution.unknown or headline_resolution.unknown or problems)
        self.save_button.setEnabled(not blocked and self.headline.isEnabled())
        self.next_button.setEnabled(not blocked and self.headline.isEnabled())
        self._update_gps_hint(item)
        self._update_rights_hint()
        self._update_date_hint(item)

    def _update_date_hint(self, item):
        mismatch = self.template.date_mismatch(item.taken_at) if self.template and item else None
        if mismatch:
            self.date_hint.setText('<small style="color:#e67e22">' + html.escape(
                _('Datum aus dem Template: {fixed} – aufgenommen am {taken}').format(
                    fixed=mismatch[0], taken=mismatch[1])) + '</small>')
        self.date_hint.setVisible(bool(mismatch))

    # in the short text first what you most likely want to check
    RIGHTS_SUMMARY = ('creator', 'copyright')

    def _update_rights_hint(self):
        """One line with photographer and copyright, the rest as a count; everything in the tooltip."""
        values = self.template.fixed_values() if self.template else {}
        shown = [f'{_(metadata.LABELS[n])} {values[n]}' if n != 'copyright' else values[n]
                 for n in self.RIGHTS_SUMMARY if n in values]
        rest = len(values) - len(shown)
        if rest:
            shown.append(ngettext('{count} weiteres', '{count} weitere', rest).format(count=rest) if shown
                         else ngettext('{count} Feld', '{count} Felder', rest).format(count=rest))
        self.rights_hint.setText('<small>' + html.escape(_('Aus dem Template: {values}').format(
            values=' · '.join(shown))) + '</small>' if values else '')
        self.rights_hint.setToolTip('\n'.join(f'{_(metadata.LABELS[n])}: {v}' for n, v in values.items()))
        self.rights_hint.setVisible(bool(values))

    def _update_gps_hint(self, item):
        book = getattr(self, 'place_book', None)
        place = book.lookup(self.city.text(), self.sublocation.text()) if book else None
        if place is None or not place.has_coordinates:
            self.gps_hint.setText('')
            return
        meta = item.meta if item else metadata.Metadata()
        result = geo.apply_gps(dataclasses.replace(meta, city=place.city, sublocation=place.sublocation), book)
        if result.gps_changed:
            self.gps_hint.setText(_('GPS wird gesetzt: {latitude}, {longitude}').format(
                latitude=f'{place.latitude:.5f}', longitude=f'{place.longitude:.5f}'))
        elif meta.latitude is not None and book.is_ours(meta.latitude, meta.longitude):
            self.gps_hint.setText(_('GPS des Ortes ist gesetzt'))
        else:
            self.gps_hint.setText(_('GPS der Kamera bleibt erhalten'))

    def current_fields(self):
        """What is in the panel right now; the caption as raw text with codes."""
        return {
            'raw_caption': self.caption.toPlainText(),
            'headline': self.headline.text().strip(),
            'keywords': self.tags(),
            'city': self.city.text().strip(),
            'sublocation': self.sublocation.text().strip(),
        }

    def submit(self, step):
        """Save; step +1/-1 moves on afterwards, 0 stays. False if blocked."""
        if not self.save_button.isEnabled():
            return False
        resolution = self.resolve()
        headline = self.resolve_headline()
        if resolution.unknown or headline.unknown:
            return False
        self.save_requested.emit(dict(
            self.current_fields(), resolution=resolution, headline=metadata.single_line(headline.text),
            caption_modified=self.caption.toPlainText() != getattr(self, '_shown_caption', None)), step)
        return True
