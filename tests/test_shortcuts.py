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
# gilt immer, dazu entweder Galerie oder Panel; in der Grossansicht deren Kuerzel
# und das dorthin umgehaengte Panel
ACTIVE_TOGETHER = [{'gallery', 'window'}, {'editor', 'window'}, {'viewer', 'editor'}]


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


def test_platform_tables():
    mac = {b.command: b.keys for b in keymap._bindings(True)}
    win = {b.command: b.keys for b in keymap._bindings(False)}
    # Farbklasse: Cmd bzw. Strg + Ziffer; Sterne: Ziffer ohne Modifier
    assert mac['color_3'] == ('Ctrl+3',) and win['color_3'] == ('Ctrl+3',)
    assert mac['rating_4'] == ('4',) and win['rating_4'] == ('4',)
    assert mac['save_next'] == ('Ctrl+]', 'Ctrl+N') and win['save_next'] == ('Alt+]', 'Ctrl+M')
    assert mac['snapshot_take'] == win['snapshot_take'] == ('Ctrl+Shift+C',)
    assert mac['snapshot_paste'] == win['snapshot_paste'] == ('Ctrl+Shift+V',)
    assert mac['next_image'] == ('Ctrl+]', 'Ctrl+N') and mac['prev_image'] == ('Ctrl+[', 'Ctrl+B')


pytestmark_gui = requires_exiftool
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
    press(window.view, Qt.Key.Key_4)
    assert item.meta.rating == 4
    press(window.view, Qt.Key.Key_0)
    assert item.meta.rating == 0


@requires_exiftool
def test_digits_set_rating_only(window):
    item = window.filtered[0]
    press(window.view, Qt.Key.Key_3)
    assert item.meta.rating == 3 and item.meta.color_class == 0
    press(window.view, Qt.Key.Key_7)  # 6-9 ohne Modifier sind nicht belegt
    assert item.meta.rating == 3 and item.meta.color_class == 0
    press(window.view, Qt.Key.Key_5, Qt.KeyboardModifier.MetaModifier)  # Control-Ziffer setzt keine Sterne mehr
    assert item.meta.rating == 3


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
def test_keywords_field_wraps_and_enter_saves(window):
    item = window.filtered[0]
    tags = window.editor.keywords
    caption_height = window.editor.caption.minimumHeight()
    assert tags.lineWrapMode() == tags.LineWrapMode.WidgetWidth and tags.height() < caption_height
    tags.setPlainText('Eishockey, DEL2\n2026/27')  # eingefuegter Umbruch trennt wie ein Komma
    tags.setFocus()
    press(tags, Qt.Key.Key_Return)
    assert tags.toPlainText() == 'Eishockey, DEL2\n2026/27'  # Enter fuegt keinen Umbruch ein
    assert item.meta.keywords == ['Eishockey', 'DEL2', '2026/27']


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


SHIFT = Qt.KeyboardModifier.ShiftModifier


@requires_exiftool
def test_copy_next_paste_while_typing(window):
    """Beschriften, Cmd+Shift+C, Cmd+N (speichert, weiter), Cmd+Shift+V - alles im Panel."""
    from captioner.templates import MatchTemplate
    first, second = window.filtered[0], window.filtered[1]
    first.taken_at, second.taken_at = '2026:03:01 18:00:00', '2026:03:02 19:00:00'
    window.editor.template = MatchTemplate(headline='DEL 2 - A gegen B', caption_suffix=', {date}')
    window.editor.headline.setText('DEL 2 - A gegen B')
    window.editor.city.setText('Bad Nauheim')
    window.editor.keywords.setPlainText('Eishockey')
    caption = window.editor.caption
    caption.setFocus()
    QTest.keyClicks(caption, 'Jubel')
    press(caption, Qt.Key.Key_C, CMD | SHIFT)        # kopiert auch Ungespeichertes
    assert caption.toPlainText() == 'Jubel'
    press(caption, Qt.Key.Key_N if keymap.MAC else Qt.Key.Key_M, CMD)
    assert first.meta.caption == 'Jubel, 01.03.26' and window._selected_items() == [second]
    assert second.meta.caption == ''

    press(caption, Qt.Key.Key_V, CMD | SHIFT)
    # Anhang mit dem Datum des Zielbildes, nicht des kopierten
    assert second.meta.caption == 'Jubel, 02.03.26'
    assert (second.meta.headline, second.meta.city, second.meta.keywords) == (
        'DEL 2 - A gegen B', 'Bad Nauheim', ['Eishockey'])
    assert caption.toPlainText() == 'Jubel'  # Panel zeigt das eingefuegte Bild, als Rohtext


@requires_exiftool
def test_next_and_previous_image_in_gallery(window):
    window.view.setFocus()
    # Cmd+N/B auf macOS, Strg+M/Alt+B unter Windows
    nxt, prev = (QKeySequence(keymap.keys(command)[1])[0] for command in ('next_image', 'prev_image'))
    press(window.view, nxt.key(), nxt.keyboardModifiers())
    assert window._selected_items() == [window.filtered[1]]
    press(window.view, nxt.key(), nxt.keyboardModifiers())   # auf die naechste Seite (2 pro Seite)
    assert window._selected_items() == [window.filtered[2]] and window.page == 1
    press(window.view, prev.key(), prev.keyboardModifiers())
    assert window._selected_items() == [window.filtered[1]] and window.page == 0


@requires_exiftool
def test_caption_in_viewer_with_copy_paste(window):
    first, second = window.filtered[0], window.filtered[1]
    window.view.setCurrentIndex(window.model.index(0))
    window.open_viewer()
    QtWidgets.QApplication.processEvents()        # Grossansicht wird aktives Fenster
    viewer = window.viewer
    assert not window._editor_in_viewer()  # Standard: Panel bleibt im Hauptfenster

    press(viewer.zoom, Qt.Key.Key_I)              # Panel in die Grossansicht, Fokus in die Beschreibung
    assert window._editor_in_viewer() and viewer.caption_slot.isVisible()
    caption = window.editor.caption
    assert caption.hasFocus()

    # Tippen loest keine Grossansicht-Kuerzel aus (Ziffern, T, Z, +, -, Leertaste)
    QTest.keyClicks(caption, 'Tor 3 T+Z-')
    QtWidgets.QApplication.processEvents()
    assert caption.toPlainText() == 'Tor 3 T+Z-'
    assert viewer.isVisible() and first.meta.rating == 0 and not first.meta.tagged
    assert viewer.zoom.zoom is None

    window.editor.headline.setText('DEL 2 - A gegen B')
    press(caption, Qt.Key.Key_C, CMD | SHIFT)     # kopieren
    press(caption, Qt.Key.Key_N if keymap.MAC else Qt.Key.Key_M, CMD)   # speichern, weiter
    assert first.meta.caption == 'Tor 3 T+Z-'
    assert viewer.key == second.key                # Grossansicht zeigt das naechste Bild
    press(caption, Qt.Key.Key_V, CMD | SHIFT)     # einfuegen
    assert second.meta.caption == 'Tor 3 T+Z-' and second.meta.headline == 'DEL 2 - A gegen B'

    # Auf dem Bild wirken die Kuerzel wieder
    viewer.zoom.setFocus()
    press(viewer.zoom, Qt.Key.Key_4)
    assert second.meta.rating == 4
    assert window.settings.viewer_caption_panel

    # Schliessen: Panel zurueck ins Hauptfenster
    press(viewer.zoom, Qt.Key.Key_Escape)
    assert not viewer.isVisible() and not window._editor_in_viewer()
    assert window.main_splitter.indexOf(window.editor) == 1

    # Naechstes Oeffnen: Panel wieder dabei (Einstellung gemerkt)
    window.open_viewer()
    QtWidgets.QApplication.processEvents()
    assert window._editor_in_viewer() and viewer.zoom.hasFocus()
    viewer.caption_button.click()
    assert not window._editor_in_viewer() and not window.settings.viewer_caption_panel
    viewer.close()


@requires_exiftool
def test_template_without_teams_keeps_typed_headline(window, roster):
    from captioner.templates import MatchTemplate
    editor = window.editor
    editor.set_roster(roster, '#')
    editor.template = MatchTemplate(name='DEL2 Heim', city='Bad Nauheim', caption_suffix='')
    first, second = window.filtered[0], window.filtered[1]

    # Titel in falschem Format: Hinweis, Speichern geht trotzdem
    editor.headline.setText('Bad Nauheim gegen Bietigheim')
    assert editor.headline_hint.isVisibleTo(editor)
    editor.headline.setText('DEL 2 - Bietigheim Steelers gegen EC Bad Nauheim')
    assert not editor.headline_hint.isVisibleTo(editor)
    # Code-Vorschlaege: Teams aus dem Titel zuerst (Heim = Bietigheim)
    assert editor.caption.model.stringList()[0].startswith('bi')
    editor.caption.setPlainText('Jubel')
    editor.submit(1)                                   # speichern, weiter
    assert first.meta.headline == 'DEL 2 - Bietigheim Steelers gegen EC Bad Nauheim'
    # naechstes, noch unbeschriftetes Bild bekommt den Titel vorgeschlagen
    assert window._selected_items() == [second]
    assert editor.headline.text() == first.meta.headline
    # Beschreibung des naechsten Bildes ist markiert: Tippen ueberschreibt sie
    cursor = editor.caption.textCursor()
    assert cursor.selectedText() == editor.caption.toPlainText()
    assert cursor.selectionStart() == 0

    # Template anwenden ueberschreibt den Titel nicht mit einem leeren
    window.select_only(first)
    window.apply_template()
    assert first.meta.headline == 'DEL 2 - Bietigheim Steelers gegen EC Bad Nauheim'
    assert first.meta.city == 'Bad Nauheim'


@requires_exiftool
def test_saving_with_template_writes_rights(window):
    from captioner.templates import MatchTemplate
    editor = window.editor
    editor.template = MatchTemplate(name='Rechte', creator='Florian Dehn', copyright='© 2026 Florian Dehn',
                                    country='Deutschland', caption_suffix='')
    item = window.filtered[0]
    item.meta.source = 'vorher'
    editor.headline.setText('DEL 2 - A gegen B')
    editor.caption.setPlainText('Jubel')
    assert 'Fotograf Florian Dehn' in editor.rights_hint.text() and 'Land: Deutschland' in editor.rights_hint.toolTip()
    editor.submit(0)
    assert (item.meta.creator, item.meta.copyright, item.meta.country) == (
        'Florian Dehn', '© 2026 Florian Dehn', 'Deutschland')
    assert item.meta.source == 'vorher'  # leeres Template-Feld laesst den Wert stehen


def test_template_dialog_checks_lengths_and_headline(app):
    from captioner.templates import MatchTemplate
    from captioner.ui.dialogs import TemplateDialog
    from PySide6.QtWidgets import QDialogButtonBox
    dialog = TemplateDialog(MatchTemplate(name='X'))
    save = dialog.buttons.button(QDialogButtonBox.StandardButton.Save)
    assert save.isEnabled() and not dialog.headline_hint.isVisibleTo(dialog)
    dialog.headline.setText('Training')
    assert save.isEnabled() and 'Format' in dialog.headline_hint.text()   # warnt nur
    dialog.creator.setText('x' * 40)
    assert not save.isEnabled() and 'Fotograf' in dialog.headline_hint.text()
    dialog.creator.setText('Florian Dehn')
    dialog.headline.setText('DEL 2 - A gegen B')
    assert save.isEnabled()
    assert dialog.template() == MatchTemplate(name='X', headline='DEL 2 - A gegen B', creator='Florian Dehn')


@requires_exiftool
def test_undo_and_redo(window):
    from captioner import geo, metadata, scanner
    from captioner.exiftool import ExifTool, find_exiftool
    first, second = window.filtered[0], window.filtered[1]
    window.view.setFocus()
    press(window.view, Qt.Key.Key_4)
    window.select_only(second)
    window.view.setFocus()
    press(window.view, Qt.Key.Key_3, CMD)
    assert (first.meta.rating, second.meta.color_class) == (4, 3)
    assert window.undo_action.text() == 'Rückgängig: Farbklasse'

    press(window.view, Qt.Key.Key_Z, CMD)
    assert second.meta.color_class == 0 and first.meta.rating == 4
    press(window.view, Qt.Key.Key_Z, CMD)
    assert first.meta.rating == 0
    assert not window.undo_action.isEnabled() and window.redo_action.text() == 'Wiederholen: Bewertung'
    press(window.view, Qt.Key.Key_Z, CMD | Qt.KeyboardModifier.ShiftModifier)
    assert first.meta.rating == 4

    # Beschriftung mit GPS: Rueckgaengig nimmt Titel, Rohtext und das gesetzte GPS zurueck
    window.places.remember(geo.Place('Bad Nauheim', 'Halle', 50.37, 8.73))
    window.select_only(first)
    editor = window.editor
    editor.headline.setText('DEL 2 - A gegen B')
    editor.city.setText('Bad Nauheim')
    editor.sublocation.setText('Halle')
    editor.caption.setPlainText('Jubel')
    editor.submit(0)
    assert first.meta.latitude == 50.37 and window.raw_captions.get(first) == 'Jubel'
    window.undo()
    assert (first.meta.headline, first.meta.caption, first.meta.latitude) == ('', '', None)
    assert window.raw_captions.get(first) is None and first.meta.rating == 4
    assert window.writer.flush(30)
    tool = ExifTool(find_exiftool()).start()
    try:
        fresh = scanner.scan(first.primary.parent)[0]
        list(metadata.read_items(tool, [fresh]))
    finally:
        tool.close()
    assert (fresh.meta.rating, fresh.meta.headline, fresh.meta.latitude) == (4, '', None)


@requires_exiftool
def test_cmd_z_in_text_field_undoes_typing_not_metadata(window):
    item = window.filtered[0]
    window.view.setFocus()
    press(window.view, Qt.Key.Key_2)
    caption = window.editor.caption
    caption.setFocus()
    QTest.keyClicks(caption, 'abc')
    press(caption, Qt.Key.Key_Z, CMD)
    assert caption.toPlainText() == '' and item.meta.rating == 2


@requires_exiftool
def test_tag_suggestions_complete_the_current_tag(window):
    window.keyword_history.add(['Eishockey', 'EC Bad Nauheim', 'EC Kassel Huskies'])
    tags = window.editor.keywords
    tags.setFocus()
    QTest.keyClicks(tags, 'Eishockey, ec k')
    QtWidgets.QApplication.processEvents()
    assert tags.model.stringList() == ['EC Kassel Huskies']
    tags.completer.activated.emit('EC Kassel Huskies')
    assert tags.toPlainText() == 'Eishockey, EC Kassel Huskies, '
    assert window.editor.tags() == ['Eishockey', 'EC Kassel Huskies']


@requires_exiftool
def test_codes_in_headline(window):
    from captioner.roster import parse, Roster
    roster = Roster()
    for entry in parse('bn\tEC Bad Nauheim\nkh\tEC Kassel Huskies\nbn23\t-23- Marius Erk (EC Bad Nauheim)\n', 't'):
        roster.entries[entry.code] = entry
    editor = window.editor
    editor.set_roster(roster, '#')
    editor.headline.setText('DEL 2 - #bn# gegen #kh#')
    assert '→ DEL 2 - EC Bad Nauheim gegen EC Kassel Huskies' in editor.headline_preview.text()
    assert not editor.headline_hint.isVisibleTo(editor)          # aufgeloest im richtigen Format
    editor.caption.setPlainText('Tor #bn23#')
    editor.submit(0)
    item = window.filtered[0]
    assert item.meta.headline == 'DEL 2 - EC Bad Nauheim gegen EC Kassel Huskies'
    editor.headline.setText('DEL 2 - #bn# gegen #xx#')
    assert 'xx' in editor.headline_preview.text() and not editor.save_button.isEnabled()
