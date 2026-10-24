"""
"Customize keyboard shortcuts": change, add or remove any binding from keymap.py.

A new shortcut is recorded from the keyboard (KeyCaptureField): the field shows what is
currently pressed and is empty as soon as no key is held. At most keymap.MAX_KEYS keys
together (e.g. ⌘⇧K). If the combination is already taken, it is removed there (the dialog
says so beforehand).
"""
from PySide6.QtCore import QEvent, QKeyCombination, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..i18n import _
from . import keymap

MODIFIER_KEYS = {
    Qt.Key.Key_Control: Qt.KeyboardModifier.ControlModifier,
    Qt.Key.Key_Shift: Qt.KeyboardModifier.ShiftModifier,
    Qt.Key.Key_Alt: Qt.KeyboardModifier.AltModifier,
    Qt.Key.Key_Meta: Qt.KeyboardModifier.MetaModifier,
}
MODIFIER_MASK = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                 | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)
IGNORED_KEYS = {Qt.Key.Key_unknown, Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock}


def native(key):
    """Shortcut in the platform's notation (with ⌘ on the Mac)."""
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)


def modifier_text(modifiers):
    """Only the held modifiers, e.g. "⌘⇧" or "Ctrl+Shift+"."""
    if not modifiers:
        return ''
    text = QKeySequence(QKeyCombination(modifiers, Qt.Key.Key_A)).toString(QKeySequence.SequenceFormat.NativeText)
    return text[:-1]


def count_modifiers(modifiers):
    return sum(1 for flag in MODIFIER_KEYS.values() if modifiers & flag)


class KeyCaptureField(QLineEdit):
    """
    Shows the keys currently pressed, empty without a key press. Every combination with a
    key other than modifiers reports `captured` (Qt notation, PortableText), or
    `too_many` if more than keymap.MAX_KEYS keys are pressed.
    """
    captured = Signal(str)
    too_many = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        font = self.font()
        font.setPointSizeF(font.pointSizeF() * 1.6)
        self.setFont(font)
        self.setMinimumWidth(260)
        self._modifiers = Qt.KeyboardModifier.NoModifier
        self._key = None

    def event(self, event):
        # All keys belong to the field: no shortcuts, no tab focus change, no Esc/Enter for the dialog
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if event.type() == QEvent.Type.KeyPress:
            self._pressed(event)
            return True
        if event.type() == QEvent.Type.KeyRelease:
            self._released(event)
            return True
        return super().event(event)

    def _pressed(self, event):
        key = Qt.Key(event.key())
        if event.isAutoRepeat() or key in IGNORED_KEYS:
            return
        modifiers = event.modifiers() & MODIFIER_MASK
        if key in MODIFIER_KEYS:
            self._modifiers = modifiers | MODIFIER_KEYS[key]
            self._key = None
            self._show()
            return
        self._modifiers, self._key = modifiers, key
        self._show()
        if count_modifiers(modifiers) + 1 > keymap.MAX_KEYS:
            self.too_many.emit()
            return
        # Characters that need Shift (* + ? on a German keyboard) are remembered without Shift:
        # the character already says it, and that way Qt also triggers the shortcut
        if (modifiers & Qt.KeyboardModifier.ShiftModifier and 0x21 <= key <= 0x7e
                and not Qt.Key.Key_A <= key <= Qt.Key.Key_Z and not Qt.Key.Key_0 <= key <= Qt.Key.Key_9):
            modifiers &= ~Qt.KeyboardModifier.ShiftModifier
        self.captured.emit(QKeySequence(QKeyCombination(modifiers, key)).toString())

    def _released(self, event):
        key = Qt.Key(event.key())
        if event.isAutoRepeat():
            return
        if key in MODIFIER_KEYS:
            self._modifiers = event.modifiers() & MODIFIER_MASK & ~MODIFIER_KEYS[key]
            if not self._modifiers:
                self._key = None   # macOS doesn't always report releasing ⌘+key
        else:
            self._modifiers = event.modifiers() & MODIFIER_MASK
            self._key = None
        self._show()

    def _show(self):
        if self._key is None:
            self.setText(modifier_text(self._modifiers))
        else:
            self.setText(native(QKeySequence(QKeyCombination(self._modifiers, self._key)).toString()))

    def focusOutEvent(self, event):
        self._modifiers, self._key = Qt.KeyboardModifier.NoModifier, None
        self.clear()
        super().focusOutEvent(event)


class KeyCaptureDialog(QDialog):
    """Record a shortcut from the keyboard; `key` is then the Qt notation."""

    def __init__(self, command, keys_by_command, parent=None):
        super().__init__(parent)
        self.command = command
        self.keys_by_command = keys_by_command
        self.key = None
        self.clashing = []
        self.setWindowTitle(_('Kürzel aufnehmen'))
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_('Neues Kürzel für „{action}“:').format(action=_(keymap.BY_COMMAND[command].label))))
        hint = QLabel(_('Tasten gleichzeitig drücken, höchstens {count}.').format(count=keymap.MAX_KEYS))
        hint.setStyleSheet('color: gray;')
        layout.addWidget(hint)
        self.field = KeyCaptureField()
        self.field.captured.connect(self._captured)
        self.field.too_many.connect(self._too_many)
        layout.addWidget(self.field)
        self.result_label = QLabel(' ')
        self.result_label.setWordWrap(True)
        # room for "New: …" and the note about a clash, so nothing jumps
        self.result_label.setMinimumHeight(self.result_label.fontMetrics().lineSpacing() * 3)
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.result_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        # Mouse only: the keyboard belongs to the capture field (Esc and Enter are shortcuts too)
        for button in self.buttons.buttons():
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAutoDefault(False)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setEnabled(False)
        layout.addWidget(self.buttons)
        self.field.setFocus()

    def _captured(self, key):
        self.key = key
        self.clashing = keymap.clashes(self.keys_by_command, self.command, key)
        text = _('Neu: {keys}').format(keys=native(key))
        if self.clashing:
            names = ', '.join('„{}“'.format(_(keymap.BY_COMMAND[c].label)) for c in self.clashing)
            text += '\n' + _('Schon belegt für {actions}; dort wird es entfernt.').format(actions=names)
        self.result_label.setText(text)
        self.ok_button.setEnabled(True)

    def _too_many(self):
        self.key = None
        self.result_label.setText(_('Zu viele Tasten: höchstens {count} zusammen.').format(count=keymap.MAX_KEYS))
        self.ok_button.setEnabled(False)


class ShortcutEditorDialog(QDialog):
    """All commands by context; per command its shortcuts (the first is shown in menus and hints)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Tastenkürzel anpassen'))
        self.resize(720, 760)
        self.keys = {binding.command: list(binding.keys) for binding in keymap.BINDINGS}
        self.capture_dialog = None   # for tests: the capture dialog currently open

        layout = QVBoxLayout(self)
        self.search = QLineEdit(placeholderText=_('Aktion oder Kürzel suchen'))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_('Aktion'), _('Kürzel')])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.items = {}
        for context, title in keymap.CONTEXT_TITLES.items():
            group = QTreeWidgetItem(self.tree, [_(title)])
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group.setFirstColumnSpanned(True)
            for binding in keymap.DEFAULTS:
                if binding.context == context:
                    item = QTreeWidgetItem(group, [_(binding.label), ''])
                    item.setData(0, Qt.ItemDataRole.UserRole, binding.command)
                    self.items[binding.command] = item
        self.tree.expandAll()
        self.tree.setColumnWidth(0, 430)
        self.tree.currentItemChanged.connect(lambda *_: self._show_command())
        self.tree.itemDoubleClicked.connect(lambda item, column: self.command and self.change_key())
        layout.addWidget(self.tree, 1)

        self.command_label = QLabel()
        layout.addWidget(self.command_label)
        row = QHBoxLayout()
        self.key_list = QListWidget()
        self.key_list.setMaximumHeight(90)
        self.key_list.currentRowChanged.connect(lambda *_: self._update_buttons())
        self.key_list.itemDoubleClicked.connect(lambda item: self.change_key())
        row.addWidget(self.key_list, 1)
        side = QVBoxLayout()
        self.add_button = QPushButton(_('Hinzufügen …'), clicked=self.add_key)
        self.change_button = QPushButton(_('Ändern …'), clicked=self.change_key)
        self.remove_button = QPushButton(_('Entfernen'), clicked=self.remove_key)
        self.default_button = QPushButton(_('Standard'), clicked=self.reset_command)
        for button in (self.add_button, self.change_button, self.remove_button, self.default_button):
            side.addWidget(button)
        side.addStretch(1)
        row.addLayout(side)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.reset_all_button = buttons.addButton(_('Alle auf Standard'), QDialogButtonBox.ButtonRole.ResetRole)
        self.reset_all_button.clicked.connect(self.reset_all)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh()
        self._show_command()

    @property
    def command(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None

    def select(self, command):
        self.tree.setCurrentItem(self.items[command])

    def overrides(self):
        return keymap.overrides(self.keys)

    # --- Display -----------------------------------------------------------------

    def _refresh(self):
        for command, item in self.items.items():
            item.setText(1, _('  oder  ').join(native(k) for k in self.keys[command]))
            font = item.font(0)
            font.setBold(tuple(self.keys[command]) != keymap.DEFAULT_KEYS[command])  # changed
            item.setFont(0, font)
            item.setFont(1, font)
        self._filter(self.search.text())

    def _filter(self, text):
        needle = text.strip().casefold()
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            visible = 0
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                hit = not needle or needle in child.text(0).casefold() or needle in child.text(1).casefold()
                child.setHidden(not hit)
                visible += hit
            group.setHidden(not visible)

    def _show_command(self, row=0):
        command = self.command
        self.key_list.clear()
        if command is None:
            self.command_label.setText(_('Eine Aktion wählen, um ihre Kürzel zu ändern.'))
        else:
            self.command_label.setText(_('Kürzel für „{action}“:').format(action=_(keymap.BY_COMMAND[command].label)))
            for key in self.keys[command]:
                item = QListWidgetItem(native(key))
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.key_list.addItem(item)
            if self.key_list.count():
                self.key_list.setCurrentRow(min(row, self.key_list.count() - 1))
        self._update_buttons()

    def _update_buttons(self):
        command = self.command
        has_key = command is not None and self.key_list.currentRow() >= 0
        self.add_button.setEnabled(command is not None)
        self.change_button.setEnabled(command is not None)
        self.remove_button.setEnabled(has_key)
        self.default_button.setEnabled(command is not None and tuple(self.keys[command]) != keymap.DEFAULT_KEYS[command])

    # --- Changing ----------------------------------------------------------------

    def _capture(self):
        self.capture_dialog = KeyCaptureDialog(self.command, self.keys, self)
        try:
            if self.capture_dialog.exec() and self.capture_dialog.key:
                return self.capture_dialog.key, self.capture_dialog.clashing
            return None, []
        finally:
            self.capture_dialog = None

    def _take(self, key, clashing):
        """Remove the combination from the other commands (also a duplicate on the same one)."""
        for other in clashing:
            self.keys[other] = [k for k in self.keys[other] if keymap.normalized(k) != keymap.normalized(key)]

    def change_key(self):
        """Replace the selected shortcut (without a shortcut: add one)."""
        command, row = self.command, self.key_list.currentRow()
        if command is None:
            return
        if row < 0:
            self.add_key()
            return
        key, clashing = self._capture()
        if key is None:
            return
        self._take(key, clashing)
        keys = self.keys[command]
        keys[row] = key
        self.keys[command] = [k for i, k in enumerate(keys)
                              if i == row or keymap.normalized(k) != keymap.normalized(key)]
        self._refresh()
        self._show_command(row)

    def add_key(self):
        command = self.command
        if command is None:
            return
        key, clashing = self._capture()
        if key is None:
            return
        self._take(key, clashing)
        if all(keymap.normalized(k) != keymap.normalized(key) for k in self.keys[command]):
            self.keys[command].append(key)
        self._refresh()
        self._show_command(len(self.keys[command]) - 1)

    def remove_key(self):
        command, row = self.command, self.key_list.currentRow()
        if command is None or row < 0:
            return
        del self.keys[command][row]
        self._refresh()
        self._show_command(row)

    def reset_command(self):
        command = self.command
        if command is None:
            return
        for key in keymap.DEFAULT_KEYS[command]:
            self._take(key, keymap.clashes(self.keys, command, key))
        self.keys[command] = list(keymap.DEFAULT_KEYS[command])
        self._refresh()
        self._show_command()

    def reset_all(self):
        self.keys = {command: list(keys) for command, keys in keymap.DEFAULT_KEYS.items()}
        self._refresh()
        self._show_command()
