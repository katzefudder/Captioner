"""
Keyboard shortcuts as in a photo culling workflow tool.

Color classes are on the digits 1-8 without modifier (0 removes them), stars on
Cmd/Ctrl + 1-5 (Cmd/Ctrl + 0 removes them). The Windows bindings are not a plain
translation of Cmd to Ctrl ("save and next" on Alt+] or Ctrl+M), hence two tables.

Qt notation: on macOS "Ctrl" is the Command key, "Meta" the Control key and "Alt" the
Option key. On Windows they mean what is printed on them.

Contexts:
  gallery  - only when the gallery has the focus (single keys such as T, I, +, - must
             not trigger while typing in the caption field)
  editor   - in the caption panel
  window   - in the whole window
  viewer   - in the preview ("Preview Window")
  menu     - shortcuts on menu items (open folder, quit, ...), always active

The tables here are the default bindings (DEFAULTS). Custom bindings live in
Settings.shortcuts (deviations only) and take effect with apply(); all other modules
read the effective bindings via keys(), BINDINGS and BY_COMMAND.
"""
import sys
from dataclasses import dataclass, replace

from PySide6.QtGui import QKeySequence

from ..i18n import N_

MAC = sys.platform == 'darwin'

# written out one by one so pybabel finds every label; translated when displayed
COLOR_LABELS = (N_('Farbklasse 1'), N_('Farbklasse 2'), N_('Farbklasse 3'), N_('Farbklasse 4'),
                N_('Farbklasse 5'), N_('Farbklasse 6'), N_('Farbklasse 7'), N_('Farbklasse 8'))
RATING_LABELS = (N_('1 Stern'), N_('2 Sterne'), N_('3 Sterne'), N_('4 Sterne'), N_('5 Sterne'))


@dataclass(frozen=True)
class Binding:
    command: str
    context: str
    keys: tuple
    label: str


def _bindings(mac):
    b = []

    def add(command, context, keys, label):
        b.append(Binding(command, context, tuple(keys), label))

    # menu (shortcuts sit on the menu item, on the Mac also in the menu bar)
    add('open_folder', 'menu', ['Ctrl+O'], N_('Ordner öffnen …'))
    add('open_folder_tab', 'menu', [], N_('Ordner in neuem Tab öffnen …'))
    add('rescan', 'menu', ['F5'], N_('Neu einlesen'))
    add('preferences', 'menu', ['Ctrl+,'] if mac else [], N_('Einstellungen …'))
    add('customize_shortcuts', 'menu', [], N_('Tastenkürzel anpassen …'))
    add('quit', 'menu', ['Ctrl+Q'] if mac else [], N_('Beenden'))

    # contact sheet / gallery
    for n in range(1, 9):
        add(f'color_{n}', 'gallery', [f'{n}'], COLOR_LABELS[n - 1])
    add('color_0', 'gallery', ['0'], N_('Farbklasse entfernen'))
    for n in range(1, 6):
        add(f'rating_{n}', 'gallery', [f'Ctrl+{n}'], RATING_LABELS[n - 1])
    add('rating_0', 'gallery', ['Ctrl+0'], N_('Sterne entfernen'))
    add('tag_toggle', 'gallery', ['T'], N_('Tag an/aus'))
    add('tag_on', 'gallery', ['+'], N_('Tag an'))
    add('tag_off', 'gallery', ['-'], N_('Tag aus'))
    add('preview', 'gallery', ['Space'], N_('Großansicht'))
    add('info', 'gallery', ['I', 'Return'], N_('Beschriftung bearbeiten (IPTC Info)'))
    add('last_previewed', 'gallery', ['L'], N_('Zuletzt angesehenes Bild auswählen'))
    add('select_all', 'gallery', ['Ctrl+A'], N_('Alle auswählen'))
    add('deselect_all', 'gallery', ['Ctrl+D'], N_('Auswahl aufheben'))
    add('select_tagged', 'gallery', ['Ctrl+T'], N_('Getaggte auswählen'))
    add('trash', 'gallery', ['Ctrl+Backspace'] if mac else ['Del'], N_('In den Papierkorb legen'))
    add('reveal', 'gallery', ['Ctrl+Alt+R'], N_('Im Finder bzw. Explorer zeigen'))
    add('home', 'gallery', ['Home'], N_('Zum ersten Bild'))
    add('end', 'gallery', ['End'], N_('Zum letzten Bild'))
    # as in the panel, just without saving (there is nothing to save in the gallery)
    add('next_image', 'gallery', ['Ctrl+]', 'Ctrl+N'] if mac else ['Alt+]', 'Ctrl+M'], N_('Nächstes Bild'))
    add('prev_image', 'gallery', ['Ctrl+[', 'Ctrl+B'] if mac else ['Alt+[', 'Alt+B'], N_('Vorheriges Bild'))
    # On Windows "Set Code Replacements" is on Ctrl+Alt+C, which in the panel is
    # "apply template"; hence only in the gallery context
    add('roster_settings', 'gallery', ['Ctrl+Meta+C' if mac else 'Ctrl+Alt+C'], N_('Roster-Quellen einstellen'))

    # view / template / file
    add('view_tagged', 'window', ['F3'], N_('Nur getaggte zeigen'))
    add('view_untagged', 'window', ['F4'], N_('Nur nicht getaggte zeigen'))
    add('template_load', 'window', ['Ctrl+Alt+L'], N_('Template-Datei laden'))
    add('template_save', 'window', ['Ctrl+Alt+S'], N_('Template speichern unter'))
    add('template_apply', 'window', ['Ctrl+Alt+A'], N_('Template auf Auswahl anwenden'))
    add('roster_reload', 'window', ['Ctrl+Meta+Shift+C' if mac else 'Ctrl+Alt+Shift+C'], N_('Roster neu laden'))
    add('shortcuts', 'window', ['F1'], N_('Diese Übersicht'))
    # caption from image to image: in the gallery and while typing in the panel
    add('snapshot_take', 'window', ['Ctrl+Shift+C'], N_('Beschriftung kopieren (IPTC-Snapshot)'))
    add('snapshot_paste', 'window', ['Ctrl+Shift+V'], N_('Beschriftung in Auswahl einfügen'))
    add('find_replace', 'window', ['Ctrl+Alt+F'], N_('Suchen und Ersetzen in der Auswahl'))
    # undo rating/caption; in a text field its own undo applies
    add('undo', 'window', ['Ctrl+Z'], N_('Rückgängig'))
    add('redo', 'window', ['Ctrl+Shift+Z'], N_('Wiederholen'))

    # folder tabs
    add('close_tab', 'window', ['Ctrl+W'], N_('Tab schließen'))
    add('tab_next', 'window', ['Ctrl+Alt+Right'], N_('Nächster Tab'))
    add('tab_prev', 'window', ['Ctrl+Alt+Left'], N_('Vorheriger Tab'))

    # caption panel (Metadata (IPTC) Info)
    add('save_next', 'editor', ['Ctrl+]', 'Ctrl+N'] if mac else ['Alt+]', 'Ctrl+M'], N_('Speichern und nächstes Bild'))
    add('save_prev', 'editor', ['Ctrl+[', 'Ctrl+B'] if mac else ['Alt+[', 'Alt+B'], N_('Speichern und vorheriges Bild'))
    add('save_close', 'editor', ['Ctrl+Return'], N_('Speichern und zurück zur Galerie'))
    add('next_nosave', 'editor', ['Ctrl+Shift+]', 'Ctrl+Shift+N'] if mac else ['Alt+Shift+]', 'Ctrl+Shift+N'],
        N_('Nächstes Bild ohne Speichern'))
    add('prev_nosave', 'editor', ['Ctrl+Shift+[', 'Ctrl+Shift+B'] if mac else ['Alt+Shift+[', 'Ctrl+Shift+B'],
        N_('Vorheriges Bild ohne Speichern'))
    add('editor_apply_template', 'editor', ['Ctrl+Alt+C'], N_('Template anwenden'))

    # preview (Preview Window)
    add('viewer_close', 'viewer', ['Esc', 'Ctrl+W' if mac else 'Alt+W', 'Space'], N_('Großansicht schließen'))
    for n in range(1, 9):
        add(f'viewer_color_{n}', 'viewer', [f'{n}'], COLOR_LABELS[n - 1])
    add('viewer_color_0', 'viewer', ['0'], N_('Farbklasse entfernen'))
    for n in range(1, 6):
        add(f'viewer_rating_{n}', 'viewer', [f'Ctrl+{n}'], RATING_LABELS[n - 1])
    add('viewer_rating_0', 'viewer', ['Ctrl+0'], N_('Sterne entfernen'))
    add('viewer_tag_toggle', 'viewer', ['T'], N_('Tag an/aus'))
    add('viewer_zoom_toggle', 'viewer', ['Z', '*'], N_('Zoom an/aus (100 %)'))
    add('viewer_zoom_in', 'viewer', ['+'], N_('Heranzoomen'))
    add('viewer_zoom_out', 'viewer', ['-'], N_('Herauszoomen'))
    # Captioning in the preview. Digits, T, Z, +, -, space don't trigger while typing:
    # text fields claim printable keys without Cmd/Ctrl (ShortcutOverride)
    add('viewer_caption', 'viewer', ['I'], N_('Beschriften (Panel zeigen, in die Beschreibung)'))
    add('viewer_snapshot_take', 'viewer', ['Ctrl+Shift+C'], N_('Beschriftung kopieren (IPTC-Snapshot)'))
    add('viewer_snapshot_paste', 'viewer', ['Ctrl+Shift+V'], N_('Beschriftung einfügen'))
    add('viewer_undo', 'viewer', ['Ctrl+Z'], N_('Rückgängig'))
    add('viewer_redo', 'viewer', ['Ctrl+Shift+Z'], N_('Wiederholen'))
    return b


DEFAULTS = _bindings(MAC)
DEFAULT_KEYS = {binding.command: binding.keys for binding in DEFAULTS}
BINDINGS = list(DEFAULTS)
BY_COMMAND = {binding.command: binding for binding in BINDINGS}

MAX_KEYS = 3  # custom shortcuts: at most three keys pressed together

# Which contexts can be active at the same time: the window context shortcut always
# applies, plus either gallery or panel; in the preview its shortcuts and the panel
# moved there. Menu shortcuts apply everywhere.
ACTIVE_TOGETHER = [{'gallery', 'window', 'menu'}, {'editor', 'window', 'menu'}, {'viewer', 'editor', 'menu'}]


def keys(command):
    return BY_COMMAND[command].keys


def apply(overrides):
    """Make custom bindings effective: {command: [keys, ...]}; unknown commands are dropped."""
    global BINDINGS, BY_COMMAND
    overrides = overrides or {}
    BINDINGS = [replace(binding, keys=tuple(overrides[binding.command])) if binding.command in overrides else binding
                for binding in DEFAULTS]
    BY_COMMAND = {binding.command: binding for binding in BINDINGS}


def overrides(keys_by_command):
    """Only the deviations from the defaults, as stored in Settings.shortcuts."""
    return {command: list(keys) for command, keys in keys_by_command.items()
            if command in DEFAULT_KEYS and tuple(keys) != DEFAULT_KEYS[command]}


def normalized(key):
    return QKeySequence(key).toString()


def clashes(keys_by_command, command, key):
    """Commands that already use `key` and can be active together with `command`."""
    context = BY_COMMAND[command].context
    together = set().union(*(group for group in ACTIVE_TOGETHER if context in group))
    wanted = normalized(key)
    return [other for other, keys in keys_by_command.items()
            if other != command and BY_COMMAND[other].context in together
            and any(normalized(k) == wanted for k in keys)]


CONTEXT_TITLES = {
    'gallery': N_('Galerie (Kontaktbogen)'),
    'editor': N_('Beschriftung (IPTC Info)'),
    'window': N_('Überall'),
    'viewer': N_('Großansicht'),
    'menu': N_('Menü'),
}
