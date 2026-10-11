"""Uebersetzungen: vollstaendig, Platzhalter gleich, .mo aktuell, keine f-Strings in _()."""
import ast
import re
import string
from pathlib import Path

import pytest
from babel.messages.extract import extract_from_dir
from babel.messages.pofile import read_po

from captioner import i18n

ROOT = Path(__file__).resolve().parent.parent
KEYWORDS = {'_': None, 'N_': None, 'ngettext': (1, 2)}


@pytest.fixture
def english():
    i18n.setup('en')
    yield
    i18n.setup('de')


def extracted():
    found = set()
    for _filename, _lineno, message, _comments, _context in extract_from_dir(
            ROOT / 'captioner', method_map=[('**.py', 'python')], keywords=KEYWORDS):
        found.add(message if isinstance(message, str) else tuple(message))
    return found


def catalog(language):
    with open(i18n.LOCALE_DIR / language / 'LC_MESSAGES' / 'captioner.po', 'rb') as handle:
        return read_po(handle, locale=language)


def placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.mark.parametrize('language', [code for code in i18n.LANGUAGES if code != i18n.SOURCE_LANGUAGE])
def test_catalog_is_complete_and_placeholders_match(language):
    cat = catalog(language)
    entries = {m.id if isinstance(m.id, str) else tuple(m.id): m for m in cat if m.id}
    missing = sorted(str(k) for k in extracted() - set(entries))
    assert not missing, f'Nicht im Katalog (make translations): {missing[:10]}'
    for key, message in entries.items():
        assert not message.fuzzy, f'unsicher (fuzzy): {key}'
        sources = key if isinstance(key, tuple) else (key,)
        targets = message.string if isinstance(message.string, (tuple, list)) else (message.string,)
        assert all(targets), f'nicht uebersetzt: {key}'
        for target in targets:
            assert placeholders(target) == placeholders(sources[0]), f'Platzhalter weichen ab: {key}'


def test_compiled_catalog_is_up_to_date(english):
    for message in catalog('en'):
        if not message.id or isinstance(message.id, (tuple, list)):
            continue
        assert i18n._(message.id) == message.string, f'.mo veraltet (make translations): {message.id}'


def test_no_formatted_strings_inside_translation_calls():
    """_(f'…') oder _('a' + b) findet gettext nicht: nur Literale."""
    for path in (ROOT / 'captioner').rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in KEYWORDS:
                count = 2 if node.func.id == 'ngettext' else 1
                for arg in node.args[:count]:
                    ok = isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                    # _(variable) ist erlaubt: uebersetzt Werte, die anderswo mit N_ markiert sind
                    ok = ok or (node.func.id == '_' and not isinstance(arg, (ast.JoinedStr, ast.BinOp)))
                    assert ok, f'{path.name}:{node.lineno}: {ast.unparse(node)}'


def test_resolve_language():
    assert i18n.resolve('', ['de-DE', 'en-US']) == 'de'
    assert i18n.resolve('', ['fr-FR', 'en-GB']) == 'en'
    assert i18n.resolve('', ['fr-FR']) == 'en'
    assert i18n.resolve('de', ['en-US']) == 'de'
    assert i18n.resolve('xx', []) == 'en'


def test_english_and_plurals(english):
    assert i18n.language() == 'en'
    assert i18n._('Speichern') == 'Save'
    assert i18n.ngettext('{count} Bild', '{count} Bilder', 1).format(count=1) == '1 image'
    assert i18n.ngettext('{count} Bild', '{count} Bilder', 3).format(count=3) == '3 images'
    from captioner import metadata
    from captioner.scanner import Metadata
    assert metadata.validate(Metadata(creator='x' * 40))[0].startswith('Photographer: 40 of max. 32 bytes')


def test_german_is_the_source(english):
    i18n.setup('de')
    assert i18n._('Speichern') == 'Speichern' and i18n.language() == 'de'


def test_english_ui_builds(english, tmp_path, monkeypatch):
    """Hauptfenster, Dialoge und Kuerzel-Uebersicht auf Englisch, ohne Fehler beim Formatieren."""
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    QtWidgets = pytest.importorskip('PySide6.QtWidgets')
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    import shutil
    if shutil.which('exiftool') is None:
        pytest.skip('ExifTool nicht installiert')
    from captioner import config
    from captioner.ui.dialogs import SettingsDialog, ShortcutsDialog, TemplateDialog
    from captioner.ui.main_window import MainWindow
    window = MainWindow(config.Settings(roster_sources=[]))
    try:
        menus = [a.text() for a in window.menuBar().actions()]
        assert menus == ['File', 'Edit', 'Template', 'Roster', 'Help']
        assert window.editor.save_button.text() == 'Save'
        ShortcutsDialog(window)
        SettingsDialog(window.settings, window)
        TemplateDialog(None, parent=window)
    finally:
        window.close()
