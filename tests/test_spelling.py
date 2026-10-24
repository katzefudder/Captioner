"""Spell checking of the caption (macOS NSSpellChecker)."""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')

from captioner.ui import spelling  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='nur macOS')


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_utf16_positions():
    text = 'a 🏒 Jubbel'
    assert spelling.utf16_slice(text, 5, 6) == 'Jubbel'          # 🏒 is two UTF-16 units
    import re
    assert spelling.utf16_spans('x #bn23# 🏒 #kh7#', re.compile(r'#\w+#')) == [(2, 8), (12, 17)]


def test_codes_and_roster_names_are_not_flagged(app):
    from PySide6.QtGui import QTextDocument
    checker = spelling.checker()
    assert checker is not None
    if 'de' not in checker.languages():
        pytest.skip('kein deutsches Woerterbuch auf diesem Mac')
    document = QTextDocument()   # keep a reference: the highlighter hangs on the document
    highlighter = spelling.SpellHighlighter(document, checker)
    highlighter.language = 'de'
    highlighter.set_known_words(['-23- Marius Erk (EC Bad Nauheim)'])
    text = 'Zweikampf #bn23# vor dem Tor, Jubbel 🏒 nach Ausgleich von Marius Erk'
    assert [word for _s, _l, word in highlighter.misspelled(text)] == ['Jubbel']
    start, length, _word = highlighter.misspelled(text)[0]
    assert 'Jubel' in checker.suggestions(text, start, length, 'de')
    highlighter.ignored.add('jubbel')
    assert highlighter.misspelled(text) == []
    highlighter.enabled = False
    assert highlighter.misspelled('Jubbel') == []


def test_editor_follows_setting(app):
    from captioner.ui.editor import CaptionEditor
    editor = CaptionEditor()
    editor.set_spellcheck('off')
    assert not editor.caption.spelling.enabled
    editor.set_spellcheck('en')
    assert editor.caption.spelling.enabled and editor.caption.spelling.language == 'en'
    editor.set_spellcheck('auto')
    assert editor.caption.spelling.language is None
