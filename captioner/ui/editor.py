"""
Beschriftungs-Panel: Template, Titel, Beschreibung mit Code-Replacement, Tags, Ort.

Die Beschreibung zeigt live, was aus den Codes wird; unbekannte Codes sind rot
und blockieren das Speichern (ADR 0001, Punkt 5).
"""
import html
import re
from pathlib import Path

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (QComboBox, QCompleter, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from .. import codes, metadata
from .keymap import keys as binding_keys
from ..templates import unique


def shortcut_text(command):
    """Erstes Kuerzel eines Befehls in der Schreibweise der Plattform (auf dem Mac mit ⌘)."""
    return QKeySequence(binding_keys(command)[0]).toString(QKeySequence.SequenceFormat.NativeText)


class WrappingLineEdit(QPlainTextEdit):
    """Einzeiliger Text, in der Anzeige umgebrochen. Enter speichert, nie ein Zeilenumbruch."""
    submit = Signal()  # Enter: speichern, beim Bild bleiben

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
            # Mit Modifier gehoert die Taste den Kuerzeln (z. B. Cmd/Strg+Enter)
            if event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
                event.ignore()
            else:
                self.submit.emit()
            return
        super().keyPressEvent(event)


class CodeTextEdit(WrappingLineEdit):
    """Beschreibung: umbrechender Einzeiler mit Autovervollstaendigung nach '#'."""

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
    save_requested = Signal(dict, int)    # Felder, danach: +1 naechstes, -1 vorheriges, 0 bleiben
    navigate_requested = Signal(int)      # ohne Speichern zum naechsten/vorherigen Bild
    apply_template_requested = Signal()
    template_changed = Signal(object)
    edit_template_requested = Signal(object)   # None = neues Template
    open_template_requested = Signal()
    save_template_as_requested = Signal()
    remove_template_requested = Signal(object)
    reload_roster_requested = Signal()
    add_roster_file_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.roster = None
        self.template = None
        self.templates = []
        self.delimiter = '#'
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)

        template_row = QHBoxLayout()
        self.template_box = QComboBox()
        self.template_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.template_box.currentIndexChanged.connect(self._template_selected)
        new_button = QToolButton(text='+')
        new_button.setToolTip('Neues Template')
        new_button.clicked.connect(lambda: self.edit_template_requested.emit(None))
        edit_button = QToolButton(text='…')
        edit_button.setToolTip('Template bearbeiten')
        edit_button.clicked.connect(lambda: self.edit_template_requested.emit(self.template))
        remove_button = QToolButton(text='−')
        remove_button.setToolTip('Template aus der Liste entfernen')
        remove_button.clicked.connect(lambda: self.template and self.remove_template_requested.emit(self.template))
        template_row.addWidget(QLabel('Spiel:'))
        template_row.addWidget(self.template_box, 1)
        template_row.addWidget(new_button)
        template_row.addWidget(edit_button)
        template_row.addWidget(remove_button)
        layout.addLayout(template_row)

        file_row = QHBoxLayout()
        open_button = QPushButton('Template öffnen …')
        open_button.setToolTip('Template-Datei (.toml) vom Rechner laden')
        open_button.clicked.connect(self.open_template_requested)
        self.save_as_button = QPushButton('Speichern unter …')
        self.save_as_button.setToolTip('Aktuelles Template als Datei speichern, z. B. zum Weitergeben')
        self.save_as_button.clicked.connect(self.save_template_as_requested)
        file_row.addWidget(open_button)
        file_row.addWidget(self.save_as_button)
        layout.addLayout(file_row)
        self.template_source = QLabel()
        self.template_source.setStyleSheet('color: gray;')
        self.template_source.setWordWrap(True)
        layout.addWidget(self.template_source)

        self.apply_button = QPushButton('Template auf Auswahl anwenden')
        self.apply_button.setToolTip('Titel, Ort und Tags des Templates in alle ausgewählten Bilder schreiben; '
                                     'Beschreibungen bleiben erhalten')
        self.apply_button.clicked.connect(self.apply_template_requested)
        layout.addWidget(self.apply_button)

        form = QFormLayout()
        self.headline = QLineEdit()
        self.caption = CodeTextEdit()
        self.caption.setPlaceholderText('Zweikampf #bi99# gegen #bn23#')
        self.caption.setMinimumHeight(90)
        self.caption.textChanged.connect(self._update_preview)
        self.caption.submit.connect(lambda: self.submit(0))
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        # Tags wie die Beschreibung umgebrochen, aber niedriger
        self.keywords = WrappingLineEdit(lines=3)
        self.keywords.setPlaceholderText('Tags, kommagetrennt')
        self.keywords.textChanged.connect(self._update_preview)
        self.keywords.submit.connect(lambda: self.submit(0))
        self.city = QLineEdit()
        self.sublocation = QLineEdit()
        for field in (self.headline, self.city, self.sublocation):
            field.textChanged.connect(self._update_preview)
            field.returnPressed.connect(lambda: self.submit(0))

        form.addRow('Titel', self.headline)
        form.addRow('Beschreibung', self.caption)
        form.addRow('', self.preview)
        form.addRow('Tags', self.keywords)
        form.addRow('Stadt', self.city)
        form.addRow('Ort', self.sublocation)
        layout.addLayout(form)

        self.limits = QLabel()
        self.limits.setWordWrap(True)
        layout.addWidget(self.limits)

        buttons = QHBoxLayout()
        self.save_button = QPushButton('Speichern')
        self.save_button.clicked.connect(lambda: self.submit(0))
        self.next_button = QPushButton('Speichern && weiter')
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(lambda: self.submit(1))
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        hint = QLabel(f'Enter speichert · {shortcut_text("save_next")} speichert und weiter · '
                      f'{shortcut_text("save_close")} speichert und zurück zur Galerie · '
                      f'{shortcut_text("shortcuts")} alle Tastenkürzel')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: gray;')
        layout.addWidget(hint)

        self.roster_status = QLabel()
        self.roster_status.setWordWrap(True)
        reload_button = QPushButton('Roster neu laden')
        reload_button.clicked.connect(self.reload_roster_requested)
        add_roster_button = QPushButton('Roster-Datei hinzufügen …')
        add_roster_button.setToolTip('Roster-Datei (Code<Tab>Ersetzung) vom Rechner zusätzlich verwenden')
        add_roster_button.clicked.connect(self.add_roster_file_requested)
        roster_buttons = QHBoxLayout()
        roster_buttons.addWidget(reload_button)
        roster_buttons.addWidget(add_roster_button)
        layout.addStretch(1)
        layout.addWidget(self.roster_status)
        layout.addLayout(roster_buttons)

        self.selection_info = QLabel()
        layout.insertWidget(0, self.selection_info)

        self.set_enabled(False)

    # --- Zustand von aussen ---------------------------------------------------

    def set_enabled(self, enabled):
        for widget in (self.headline, self.caption, self.keywords, self.city, self.sublocation,
                       self.save_button, self.next_button, self.apply_button):
            widget.setEnabled(enabled)

    def set_roster(self, roster, delimiter):
        self.roster = roster
        self.delimiter = delimiter
        self.caption.delimiter = delimiter
        self._update_completions()
        self._update_preview()

    def set_roster_status(self, html_text):
        self.roster_status.setText(html_text)

    def set_templates(self, templates, active_path=''):
        """Templates werden ueber ihren Dateipfad identifiziert, Namen koennen doppelt sein."""
        self.templates = templates
        self.template_box.blockSignals(True)
        self.template_box.clear()
        self.template_box.addItem('— kein Template —', None)
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
        self.template_source.setText(f'Datei: {self.template.path}' if self.template else '')
        self.save_as_button.setEnabled(self.template is not None)
        self._update_completions()
        self.template_changed.emit(self.template)

    def _update_completions(self):
        if not self.roster:
            self.caption.set_completions([])
            return
        teams = self.template.teams if self.template else []
        first = [e for team in teams for e in self.roster.codes_for_team(team)]
        rest = [e for e in self.roster.entries.values() if e not in first]
        self.caption.set_completions(first + rest)

    def show_items(self, items, carry_over_raw=None, raw_lookup=None):
        """Felder aus dem ersten ausgewaehlten Item fuellen."""
        self.set_enabled(bool(items))
        if not items:
            self.selection_info.setText('Keine Auswahl')
            for field in (self.headline, self.keywords, self.city, self.sublocation):
                field.clear()
            self.caption.setPlainText('')
            return
        item = items[0]
        count = len(items)
        self.selection_info.setText(
            f'<b>{html.escape(item.name)}</b>' if count == 1
            else f'<b>{count} Bilder ausgewählt</b> – Speichern schreibt in alle')
        meta = item.meta
        headline = meta.headline or (self.template.headline if self.template else '')
        city = meta.city or (self.template.city if self.template else '')
        sublocation = meta.sublocation or (self.template.sublocation if self.template else '')
        keywords = meta.keywords or (self.template.keywords if self.template else [])
        raw = raw_lookup(item) if raw_lookup else None
        if raw is None:
            raw = self._strip_suffix(meta.caption, item) if meta.caption else (carry_over_raw or '')
        self.headline.setText(headline)
        self.city.setText(city)
        self.sublocation.setText(sublocation)
        self.keywords.setText(', '.join(self._without_persons(keywords, meta.caption)))
        self.caption.setPlainText(raw)
        self._current_item = item
        self._shown_caption = raw
        self._update_preview()

    def _strip_suffix(self, caption, item):
        if self.template:
            meta = item.meta
            suffix = self.template.suffix_for(item.taken_at, headline=meta.headline,
                                              city=meta.city, sublocation=meta.sublocation)
            if suffix and caption.endswith(suffix):
                return caption[:-len(suffix)]
        return caption

    def _without_persons(self, keywords, caption):
        """Personen-Tags werden beim Speichern aus der Beschreibung neu erzeugt."""
        persons = set(codes.persons_in(caption, self.roster))
        return [k for k in keywords if k not in persons]

    def focus_caption(self):
        self.caption.setFocus()
        cursor = self.caption.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.caption.setTextCursor(cursor)

    # --- Vorschau und Speichern -----------------------------------------------

    def resolve(self):
        return codes.resolve(self.caption.toPlainText(), self.roster, self.delimiter)

    def tags(self):
        # Eingefuegter Text kann Zeilenumbrueche enthalten; sie trennen wie Kommas
        return [t.strip() for t in re.split(r'[,\n]', self.keywords.text()) if t.strip()]

    def _update_preview(self):
        raw = self.caption.toPlainText()
        resolution = self.resolve()
        text = metadata.single_line(resolution.text)
        item = getattr(self, '_current_item', None)
        if self.template and text:
            text = self.template.compose_caption(
                text, item.taken_at if item else '', headline=self.headline.text().strip(),
                city=self.city.text().strip(), sublocation=self.sublocation.text().strip())
        shown = html.escape(text)
        for code in resolution.unknown:
            token = html.escape(f'{self.delimiter}{code}{self.delimiter}')
            shown = shown.replace(token, f'<span style="color:#d64541;font-weight:bold">{token}</span>')
        parts = [f'<span style="color:gray">→</span> {shown}' if raw.strip() else '']
        if resolution.unknown:
            parts.append('<span style="color:#d64541">Unbekannte Codes: '
                         + ', '.join(html.escape(c) for c in resolution.unknown) + '</span>')
        if resolution.persons:
            parts.append('<span style="color:gray">Personen-Tags: '
                         + html.escape(', '.join(resolution.persons)) + '</span>')
        self.preview.setText('<br>'.join(p for p in parts if p))

        meta = metadata.Metadata(headline=self.headline.text(), caption=text,
                                 keywords=unique(self.tags() + resolution.persons),
                                 city=self.city.text(), sublocation=self.sublocation.text())
        problems = metadata.validate(meta)
        size = len(text.encode('utf-8'))
        info = f'Beschreibung {size}/{metadata.LIMITS["caption"]} Bytes'
        if problems:
            info += '<br><span style="color:#d64541">' + html.escape('; '.join(problems)) + '</span>'
        self.limits.setText(info)
        blocked = bool(resolution.unknown or problems)
        self.save_button.setEnabled(not blocked and self.headline.isEnabled())
        self.next_button.setEnabled(not blocked and self.headline.isEnabled())

    def submit(self, step):
        """Speichern; step +1/-1 springt danach weiter, 0 bleibt. False, wenn blockiert."""
        if not self.save_button.isEnabled():
            return False
        resolution = self.resolve()
        if resolution.unknown:
            return False
        self.save_requested.emit({
            'raw_caption': self.caption.toPlainText(),
            'caption_modified': self.caption.toPlainText() != getattr(self, '_shown_caption', None),
            'resolution': resolution,
            'headline': self.headline.text().strip(),
            'keywords': self.tags(),
            'city': self.city.text().strip(),
            'sublocation': self.sublocation.text().strip(),
        }, step)
        return True
