"""
Tastenkuerzel wie in einem Workflow-Tool fuer die Auswahl von Fotos.

Sterne liegen auf den Ziffern 1-5 ohne Modifier (0 entfernt sie), Farbklassen auf
Cmd/Strg + 1-8. Die Windows-Belegung ist keine reine Uebersetzung von Cmd nach Strg
("Speichern und weiter" auf Alt+] bzw. Strg+M), deshalb zwei Tabellen.

Qt-Schreibweise: Auf macOS ist "Ctrl" die Command-Taste, "Meta" die Control-Taste
und "Alt" die Option-Taste. Auf Windows bedeuten sie, was draufsteht.

Kontexte:
  gallery  - nur wenn die Galerie den Fokus hat (Einzeltasten wie T, I, +, -
             duerfen beim Tippen im Beschreibungsfeld nicht ausloesen)
  editor   - im Beschriftungs-Panel
  window   - im ganzen Fenster
  viewer   - in der Grossansicht ("Preview Window")
"""
import sys
from dataclasses import dataclass

MAC = sys.platform == 'darwin'


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

    # Kontaktbogen / Galerie
    for n in range(1, 9):
        add(f'color_{n}', 'gallery', [f'Ctrl+{n}'], f'Farbklasse {n}')
    add('color_0', 'gallery', ['Ctrl+0'], 'Farbklasse entfernen')
    for n in range(1, 6):
        add(f'rating_{n}', 'gallery', [f'{n}'], f'{n} Stern' + ('e' if n > 1 else ''))
    add('rating_0', 'gallery', ['0'], 'Sterne entfernen')
    add('tag_toggle', 'gallery', ['T'], 'Tag an/aus')
    add('tag_on', 'gallery', ['+'], 'Tag an')
    add('tag_off', 'gallery', ['-'], 'Tag aus')
    add('preview', 'gallery', ['Space'], 'Großansicht')
    add('info', 'gallery', ['I', 'Return'], 'Beschriftung bearbeiten (IPTC Info)')
    add('last_previewed', 'gallery', ['L'], 'Zuletzt angesehenes Bild auswählen')
    add('select_all', 'gallery', ['Ctrl+A'], 'Alle auswählen (alle Seiten)')
    add('deselect_all', 'gallery', ['Ctrl+D'], 'Auswahl aufheben')
    add('select_tagged', 'gallery', ['Ctrl+T'], 'Getaggte auswählen')
    add('home', 'gallery', ['Home'], 'Zum ersten Bild')
    add('end', 'gallery', ['End'], 'Zum letzten Bild')
    add('page_prev', 'gallery', ['PgUp', 'Ctrl+Shift+[' if mac else 'Ctrl+Left'], 'Vorherige Seite')
    add('page_next', 'gallery', ['PgDown', 'Ctrl+Shift+]' if mac else 'Ctrl+Right'], 'Nächste Seite')
    # Wie im Panel, nur ohne Speichern (in der Galerie gibt es nichts zu speichern)
    add('next_image', 'gallery', ['Ctrl+]', 'Ctrl+N'] if mac else ['Alt+]', 'Ctrl+M'], 'Nächstes Bild')
    add('prev_image', 'gallery', ['Ctrl+[', 'Ctrl+B'] if mac else ['Alt+[', 'Alt+B'], 'Vorheriges Bild')
    # Unter Windows liegt "Set Code Replacements" auf Strg+Alt+C, das im Panel
    # "Template anwenden" ist; deshalb nur im Galerie-Kontext
    add('roster_settings', 'gallery', ['Ctrl+Meta+C' if mac else 'Ctrl+Alt+C'], 'Roster-Quellen einstellen')

    # Ansicht / Template / Datei
    add('view_tagged', 'window', ['F3'], 'Nur getaggte zeigen')
    add('view_untagged', 'window', ['F4'], 'Nur nicht getaggte zeigen')
    add('template_load', 'window', ['Ctrl+Alt+L'], 'Template-Datei laden')
    add('template_save', 'window', ['Ctrl+Alt+S'], 'Template speichern unter')
    add('template_apply', 'window', ['Ctrl+Alt+A'], 'Template auf Auswahl anwenden')
    add('roster_reload', 'window', ['Ctrl+Meta+Shift+C' if mac else 'Ctrl+Alt+Shift+C'], 'Roster neu laden')
    add('shortcuts', 'window', ['F1'], 'Diese Übersicht')
    # Beschriftung von Bild zu Bild: in der Galerie und beim Tippen im Panel
    add('snapshot_take', 'window', ['Ctrl+Shift+C'], 'Beschriftung kopieren (IPTC-Snapshot)')
    add('snapshot_paste', 'window', ['Ctrl+Shift+V'], 'Beschriftung in Auswahl einfügen')

    # Ordner-Tabs
    add('close_tab', 'window', ['Ctrl+W'], 'Tab schließen')
    add('tab_next', 'window', ['Ctrl+Alt+Right'], 'Nächster Tab')
    add('tab_prev', 'window', ['Ctrl+Alt+Left'], 'Vorheriger Tab')

    # Beschriftungs-Panel (Metadata (IPTC) Info)
    add('save_next', 'editor', ['Ctrl+]', 'Ctrl+N'] if mac else ['Alt+]', 'Ctrl+M'], 'Speichern und nächstes Bild')
    add('save_prev', 'editor', ['Ctrl+[', 'Ctrl+B'] if mac else ['Alt+[', 'Alt+B'], 'Speichern und vorheriges Bild')
    add('save_close', 'editor', ['Ctrl+Return'], 'Speichern und zurück zur Galerie')
    add('next_nosave', 'editor', ['Ctrl+Shift+]', 'Ctrl+Shift+N'] if mac else ['Alt+Shift+]', 'Ctrl+Shift+N'],
        'Nächstes Bild ohne Speichern')
    add('prev_nosave', 'editor', ['Ctrl+Shift+[', 'Ctrl+Shift+B'] if mac else ['Alt+Shift+[', 'Ctrl+Shift+B'],
        'Vorheriges Bild ohne Speichern')
    add('editor_apply_template', 'editor', ['Ctrl+Alt+C'], 'Template anwenden')

    # Grossansicht (Preview Window)
    add('viewer_close', 'viewer', ['Esc', 'Ctrl+W' if mac else 'Alt+W', 'Space'], 'Großansicht schließen')
    for n in range(1, 9):
        add(f'viewer_color_{n}', 'viewer', [f'Ctrl+{n}'], f'Farbklasse {n}')
    add('viewer_color_0', 'viewer', ['Ctrl+0'], 'Farbklasse entfernen')
    for n in range(1, 6):
        add(f'viewer_rating_{n}', 'viewer', [f'{n}'], f'{n} Stern' + ('e' if n > 1 else ''))
    add('viewer_rating_0', 'viewer', ['0'], 'Sterne entfernen')
    add('viewer_tag_toggle', 'viewer', ['T'], 'Tag an/aus')
    add('viewer_zoom_toggle', 'viewer', ['Z', '*'], 'Zoom an/aus (100 %)')
    add('viewer_zoom_in', 'viewer', ['+'], 'Heranzoomen')
    add('viewer_zoom_out', 'viewer', ['-'], 'Herauszoomen')
    # Beschriften in der Grossansicht. Ziffern, T, Z, +, -, Leertaste loesen beim Tippen
    # nicht aus: Textfelder beanspruchen druckbare Tasten ohne Cmd/Strg (ShortcutOverride)
    add('viewer_caption', 'viewer', ['I'], 'Beschriften (Panel zeigen, in die Beschreibung)')
    add('viewer_snapshot_take', 'viewer', ['Ctrl+Shift+C'], 'Beschriftung kopieren (IPTC-Snapshot)')
    add('viewer_snapshot_paste', 'viewer', ['Ctrl+Shift+V'], 'Beschriftung einfügen')
    return b


BINDINGS = _bindings(MAC)
BY_COMMAND = {binding.command: binding for binding in BINDINGS}


def keys(command):
    return BY_COMMAND[command].keys


CONTEXT_TITLES = {
    'gallery': 'Galerie (Kontaktbogen)',
    'editor': 'Beschriftung (IPTC Info)',
    'window': 'Überall',
    'viewer': 'Großansicht',
}
