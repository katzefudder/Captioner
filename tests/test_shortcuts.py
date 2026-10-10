"""Tastenkuerzel (keymap.py), mit echten Tastendruecken."""
import os

import pytest

from conftest import make_jpeg, requires_exiftool

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from captioner.ui import keymap  # noqa: E402


# Welche Kontexte gleichzeitig aktiv sein koennen: das Fenster-Kontext-Kuerzel
# gilt immer, dazu entweder Galerie oder Panel, oder die Grossansicht allein
ACTIVE_TOGETHER = [{'gallery', 'window'}, {'editor', 'window'}, {'viewer'}]


@pytest.mark.parametrize('mac', [True, False], ids=['macOS', 'Windows'])
def test_no_ambiguous_shortcuts(mac):
    bindings = keymap._bindings(mac)
    for contexts in ACTIVE_TOGETHER:
        seen = {}
        for binding in bindings:
            if binding.context not in contexts:
                continue
            for key in binding.keys:
                normalized = QKeySequence(key).toString()
                assert normalized, f'{key!r} ist keine gueltige Tastenfolge'
                assert normalized not in seen, f'{key} doppelt: {seen.get(normalized)} und {binding.command}'
                seen[normalized] = binding.command


def test_platform_tables_follow_camera_bits():
    mac = {b.command: b.keys for b in keymap._bindings(True)}
    win = {b.command: b.keys for b in keymap._bindings(False)}
    # Farbklasse: Cmd bzw. Strg + Ziffer; Sterne: Control (Mac) bzw. Alt (Windows)
    assert mac['color_3'] == ('Ctrl+3',) and win['color_3'] == ('Ctrl+3',)
    assert mac['rating_4'] == ('Meta+4',) and win['rating_4'] == ('Alt+4',)
    assert mac['save_next'] == ('Ctrl+]', 'Ctrl+N') and win['save_next'] == ('Alt+]', 'Ctrl+M')
    assert win['snapshot_take'] == ('Alt+C',) and mac['snapshot_take'] == ('Ctrl+Alt+C',)


def test_number_key_modes():
    assert keymap.number_key_action(3, 'off') is None
    assert keymap.number_key_action(3, 'rating') == ('rating', 3)
    assert keymap.number_key_action(7, 'rating') is None
    assert keymap.number_key_action(7, 'color') == ('color', 7)


pytestmark_gui = requires_exiftool
RATING = Qt.KeyboardModifier.MetaModifier if keymap.MAC else Qt.KeyboardModifier.AltModifier
CMD = Qt.KeyboardModifier.ControlModifier


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app, tmp_path):
    from captioner import config
    from captioner.ui.main_window import MainWindow
    folder = tmp_path / 'fotos'
    folder.mkdir()
    for n in range(5):
        make_jpeg(folder / f'{n}.jpg')
    w = MainWindow(config.Settings(roster_sources=[], page_size=2), str(folder))
    w.scan_worker.wait(30000)
    QtWidgets.QApplication.processEvents()
    w.show()
    w.activateWindow()
    w.select_only(w.filtered[0])
    w.view.setFocus()
    QtWidgets.QApplication.processEvents()
    yield w
    w.writer.flush(30)
    w.close()


def press(widget, key, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(widget, key, modifiers)
    QtWidgets.QApplication.processEvents()


@requires_exiftool
def test_tag_keys(window):
    item = window.filtered[0]
    press(window.view, Qt.Key.Key_T)
    assert item.meta.tagged
    press(window.view, Qt.Key.Key_T)
    assert not item.meta.tagged
    press(window.view, Qt.Key.Key_Plus)
    assert item.meta.tagged
    press(window.view, Qt.Key.Key_Minus)
    assert not item.meta.tagged


@requires_exiftool
def test_color_class_and_rating(window):
    item = window.filtered[0]
    press(window.view, Qt.Key.Key_3, CMD)
    assert item.meta.color_class == 3 and item.meta.label == 'Green'
    press(window.view, Qt.Key.Key_7, CMD)
    assert item.meta.color_class == 7 and item.meta.label == ''  # kein Lightroom-Label fuer Klasse 7
    press(window.view, Qt.Key.Key_0, CMD)
    assert item.meta.color_class == 0
    press(window.view, Qt.Key.Key_4, RATING)
    assert item.meta.rating == 4
    press(window.view, Qt.Key.Key_0, RATING)
    assert item.meta.rating == 0


@requires_exiftool
def test_single_digit_keys_follow_setting(window):
    item = window.filtered[0]
    press(window.view, Qt.Key.Key_3)
    assert item.meta.rating == 0 and item.meta.color_class == 0  # Default "aus"
    window.settings.number_keys = 'rating'
    press(window.view, Qt.Key.Key_3)
    assert item.meta.rating == 3
    window.settings.number_keys = 'color'
    press(window.view, Qt.Key.Key_2)
    assert item.meta.color_class == 2 and item.meta.rating == 3


@requires_exiftool
def test_selection_keys_work_across_pages(window):
    press(window.view, Qt.Key.Key_A, CMD)
    assert len(window._selected_items()) == 5  # alle, obwohl nur 2 pro Seite
    press(window.view, Qt.Key.Key_D, CMD)
    assert window._selected_items() == []
    window.select_only(window.filtered[3])
    press(window.view, Qt.Key.Key_T)
    window.select_only(window.filtered[0])
    press(window.view, Qt.Key.Key_T, CMD)
    assert [i.name for i in window._selected_items()] == [window.filtered[3].name]


@requires_exiftool
def test_view_tagged_untagged(window):
    press(window.view, Qt.Key.Key_T)
    press(window.view, Qt.Key.Key_F3)
    assert len(window.filtered) == 1
    press(window.view, Qt.Key.Key_F4)
    assert len(window.filtered) == 4
    press(window.view, Qt.Key.Key_F4)
    assert len(window.filtered) == 5


@requires_exiftool
def test_typing_in_caption_does_not_trigger_gallery_keys(window):
    item = window.filtered[0]
    window.editor.caption.setFocus()
    QTest.keyClicks(window.editor.caption, 'Tor + Jubel - Team')
    QtWidgets.QApplication.processEvents()
    assert window.editor.caption.toPlainText() == 'Tor + Jubel - Team'
    assert not item.meta.tagged


@requires_exiftool
def test_save_and_next_from_caption(window):
    first, second = window.filtered[0], window.filtered[1]
    window.editor.headline.setText('DEL 2 - A gegen B')
    window.editor.caption.setFocus()
    QTest.keyClicks(window.editor.caption, 'Jubel')
    if keymap.MAC:
        press(window.editor.caption, Qt.Key.Key_N, CMD)
    else:
        press(window.editor.caption, Qt.Key.Key_M, CMD)
    assert first.meta.caption == 'Jubel'
    assert window._selected_items() == [second]
    # ohne Speichern zurueck
    press(window.editor.caption, Qt.Key.Key_B, CMD | Qt.KeyboardModifier.ShiftModifier)
    assert window._selected_items() == [first]


@requires_exiftool
def test_snapshot_copy_paste(window):
    first, other = window.filtered[0], window.filtered[2]
    window.editor.headline.setText('DEL 2 - A gegen B')
    window.editor.caption.setPlainText('Jubel')
    window.editor.submit(0)
    window.view.setFocus()
    take = QKeySequence(keymap.keys('snapshot_take')[0])
    paste = QKeySequence(keymap.keys('snapshot_paste')[0])
    press(window.view, take[0].key(), take[0].keyboardModifiers())
    window.select_only(other)
    window.view.setFocus()
    press(window.view, paste[0].key(), paste[0].keyboardModifiers())
    assert other.meta.caption == 'Jubel' and other.meta.headline == 'DEL 2 - A gegen B'
