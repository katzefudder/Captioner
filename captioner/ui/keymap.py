"""
Tastenkuerzel wie in einem Workflow-Tool fuer die Auswahl von Fotos.

Farbklassen liegen auf den Ziffern 1-8 ohne Modifier (0 entfernt sie), Sterne auf
Cmd/Strg + 1-5 (Cmd/Strg + 0 entfernt sie). Die Windows-Belegung ist keine reine Uebersetzung von Cmd nach Strg
("Speichern und weiter" auf Alt+] bzw. Strg+M), deshalb zwei Tabellen.

Qt-Schreibweise: Auf macOS ist "Ctrl" die Command-Taste, "Meta" die Control-Taste
und "Alt" die Option-Taste. Auf Windows bedeuten sie, was draufsteht.

Kontexte:
  gallery  - nur wenn die Galerie den Fokus hat (Einzeltasten wie T, I, +, -
             duerfen beim Tippen im Beschreibungsfeld nicht ausloesen)
  editor   - im Beschriftungs-Panel
  window   - im ganzen Fenster
  viewer   - in der Grossansicht ("Preview Window")
  menu     - Kuerzel an Menuepunkten (Ordner oeffnen, Beenden, ...), wirken immer

Die Tabellen hier sind die Standardbelegung (DEFAULTS). Eigene Belegungen stehen in
Settings.shortcuts (nur Abweichungen) und werden mit apply() wirksam; alle anderen Module
lesen die wirksame Belegung ueber keys(), BINDINGS und BY_COMMAND.
"""
import sys
from dataclasses import dataclass, replace

from PySide6.QtGui import QKeySequence

from ..i18n import N_

MAC = sys.platform == 'darwin'

# Einzeln ausgeschrieben, damit pybabel jede Beschriftung findet; uebersetzt wird bei der Anzeige
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

    # Menue (Kuerzel stehen am Menuepunkt, auf dem Mac auch in der Menueleiste)
    add('open_folder', 'menu', ['Ctrl+O'], N_('Ordner öffnen …'))
    add('open_folder_tab', 'menu', [], N_('Ordner in neuem Tab öffnen …'))
    add('rescan', 'menu', ['F5'], N_('Neu einlesen'))
    add('preferences', 'menu', ['Ctrl+,'] if mac else [], N_('Einstellungen …'))
    add('customize_shortcuts', 'menu', [], N_('Tastenkürzel anpassen …'))
    add('quit', 'menu', ['Ctrl+Q'] if mac else [], N_('Beenden'))

    # Kontaktbogen / Galerie
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
    add('home', 'gallery', ['Home'], N_('Zum ersten Bild'))
    add('end', 'gallery', ['End'], N_('Zum letzten Bild'))
    # Wie im Panel, nur ohne Speichern (in der Galerie gibt es nichts zu speichern)
    add('next_image', 'gallery', ['Ctrl+]', 'Ctrl+N'] if mac else ['Alt+]', 'Ctrl+M'], N_('Nächstes Bild'))
    add('prev_image', 'gallery', ['Ctrl+[', 'Ctrl+B'] if mac else ['Alt+[', 'Alt+B'], N_('Vorheriges Bild'))
    # Unter Windows liegt "Set Code Replacements" auf Strg+Alt+C, das im Panel
    # "Template anwenden" ist; deshalb nur im Galerie-Kontext
    add('roster_settings', 'gallery', ['Ctrl+Meta+C' if mac else 'Ctrl+Alt+C'], N_('Roster-Quellen einstellen'))

    # Ansicht / Template / Datei
    add('view_tagged', 'window', ['F3'], N_('Nur getaggte zeigen'))
    add('view_untagged', 'window', ['F4'], N_('Nur nicht getaggte zeigen'))
    add('template_load', 'window', ['Ctrl+Alt+L'], N_('Template-Datei laden'))
    add('template_save', 'window', ['Ctrl+Alt+S'], N_('Template speichern unter'))
    add('template_apply', 'window', ['Ctrl+Alt+A'], N_('Template auf Auswahl anwenden'))
    add('roster_reload', 'window', ['Ctrl+Meta+Shift+C' if mac else 'Ctrl+Alt+Shift+C'], N_('Roster neu laden'))
    add('shortcuts', 'window', ['F1'], N_('Diese Übersicht'))
    # Beschriftung von Bild zu Bild: in der Galerie und beim Tippen im Panel
    add('snapshot_take', 'window', ['Ctrl+Shift+C'], N_('Beschriftung kopieren (IPTC-Snapshot)'))
    add('snapshot_paste', 'window', ['Ctrl+Shift+V'], N_('Beschriftung in Auswahl einfügen'))
    add('find_replace', 'window', ['Ctrl+Alt+F'], N_('Suchen und Ersetzen in der Auswahl'))
    # Bewertung/Beschriftung zuruecknehmen; im Textfeld gilt dessen eigenes Rueckgaengig
    add('undo', 'window', ['Ctrl+Z'], N_('Rückgängig'))
    add('redo', 'window', ['Ctrl+Shift+Z'], N_('Wiederholen'))

    # Ordner-Tabs
    add('close_tab', 'window', ['Ctrl+W'], N_('Tab schließen'))
    add('tab_next', 'window', ['Ctrl+Alt+Right'], N_('Nächster Tab'))
    add('tab_prev', 'window', ['Ctrl+Alt+Left'], N_('Vorheriger Tab'))

    # Beschriftungs-Panel (Metadata (IPTC) Info)
    add('save_next', 'editor', ['Ctrl+]', 'Ctrl+N'] if mac else ['Alt+]', 'Ctrl+M'], N_('Speichern und nächstes Bild'))
    add('save_prev', 'editor', ['Ctrl+[', 'Ctrl+B'] if mac else ['Alt+[', 'Alt+B'], N_('Speichern und vorheriges Bild'))
    add('save_close', 'editor', ['Ctrl+Return'], N_('Speichern und zurück zur Galerie'))
    add('next_nosave', 'editor', ['Ctrl+Shift+]', 'Ctrl+Shift+N'] if mac else ['Alt+Shift+]', 'Ctrl+Shift+N'],
        N_('Nächstes Bild ohne Speichern'))
    add('prev_nosave', 'editor', ['Ctrl+Shift+[', 'Ctrl+Shift+B'] if mac else ['Alt+Shift+[', 'Ctrl+Shift+B'],
        N_('Vorheriges Bild ohne Speichern'))
    add('editor_apply_template', 'editor', ['Ctrl+Alt+C'], N_('Template anwenden'))

    # Grossansicht (Preview Window)
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
    # Beschriften in der Grossansicht. Ziffern, T, Z, +, -, Leertaste loesen beim Tippen
    # nicht aus: Textfelder beanspruchen druckbare Tasten ohne Cmd/Strg (ShortcutOverride)
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

MAX_KEYS = 3  # eigene Kuerzel: hoechstens drei gleichzeitig gedrueckte Tasten

# Welche Kontexte gleichzeitig aktiv sein koennen: das Fenster-Kontext-Kuerzel gilt immer,
# dazu entweder Galerie oder Panel; in der Grossansicht deren Kuerzel und das dorthin
# umgehaengte Panel. Menue-Kuerzel gelten ueberall.
ACTIVE_TOGETHER = [{'gallery', 'window', 'menu'}, {'editor', 'window', 'menu'}, {'viewer', 'editor', 'menu'}]


def keys(command):
    return BY_COMMAND[command].keys


def apply(overrides):
    """Eigene Belegung wirksam machen: {Befehl: [Tasten, ...]}; unbekannte Befehle fallen weg."""
    global BINDINGS, BY_COMMAND
    overrides = overrides or {}
    BINDINGS = [replace(binding, keys=tuple(overrides[binding.command])) if binding.command in overrides else binding
                for binding in DEFAULTS]
    BY_COMMAND = {binding.command: binding for binding in BINDINGS}


def overrides(keys_by_command):
    """Nur die Abweichungen vom Standard, so wie sie in Settings.shortcuts stehen."""
    return {command: list(keys) for command, keys in keys_by_command.items()
            if command in DEFAULT_KEYS and tuple(keys) != DEFAULT_KEYS[command]}


def normalized(key):
    return QKeySequence(key).toString()


def clashes(keys_by_command, command, key):
    """Befehle, die `key` schon belegen und zugleich mit `command` aktiv sein koennen."""
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
