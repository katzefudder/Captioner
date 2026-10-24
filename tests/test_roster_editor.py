"""Roster editor (offscreen): loading, checking, saving in the file's encoding."""
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')
QtGui = pytest.importorskip("PySide6.QtGui")

from captioner.ui.rostereditor import RosterEditorDialog  # noqa: E402

TEXT = '- EC Bad Nauheim -\r\n\r\nbn23\t-23- Marius Erk (EC Bad Nauheim)\r\nbn40\t-40- Jörg Öhler (EC Bad Nauheim)\r\n'


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def roster_file(tmp_path):
    path = tmp_path / 'DEL-2.txt'
    path.write_bytes(TEXT.encode('cp1252'))
    return path


def test_edit_check_and_save(app, roster_file):
    dialog = RosterEditorDialog(['https://example.org/roster.txt', str(roster_file)])
    assert dialog.source == str(roster_file)          # local file first, URL read-only
    assert not dialog.text.isReadOnly()
    assert '2 Codes, 1 Team' in dialog.status.text() and 'Windows-1252' in dialog.status.text()

    dialog.text.appendPlainText('bn31 -31- Dean Döge (EC Bad Nauheim)')
    dialog._check()
    assert dialog.problems.count() == 1 and 'kein Tab' in dialog.problems.item(0).text()
    assert dialog.highlighter.problem_lines == {6}  # file ends with a newline, appended = line 6

    dialog.text.setPlainText(dialog.text.toPlainText().replace('bn31 -31-', 'bn31\t-31-'))
    saved = []
    dialog.saved.connect(saved.append)
    assert dialog.save()
    assert saved == [str(roster_file)]
    # appendPlainText puts a new line after the final empty line
    assert roster_file.read_bytes() == (TEXT + '\r\nbn31\t-31- Dean Döge (EC Bad Nauheim)').encode('cp1252')
    assert not dialog.text.document().isModified()


def test_character_missing_in_encoding_offers_utf8(app, roster_file, monkeypatch):
    dialog = RosterEditorDialog([str(roster_file)])
    dialog.text.appendPlainText('bn7\t-7- Łukasz Nowak (EC Bad Nauheim)')   # Ł doesn't exist in cp1252
    monkeypatch.setattr(QtWidgets.QMessageBox, 'question', lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)
    assert dialog.save()
    assert roster_file.read_bytes().decode('utf-8').endswith('Łukasz Nowak (EC Bad Nauheim)')


def test_file_without_codes_is_not_saved(app, roster_file, monkeypatch):
    dialog = RosterEditorDialog([str(roster_file)])
    dialog.text.setPlainText('- nur ein Kopf -')
    warned = []
    monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', lambda *a: warned.append(a[2]))
    assert not dialog.save()
    assert warned and roster_file.read_bytes() == TEXT.encode('cp1252')


def test_changed_outside_asks_before_overwriting(app, roster_file, monkeypatch):
    dialog = RosterEditorDialog([str(roster_file)])
    os.utime(roster_file, (1, 1))
    monkeypatch.setattr(QtWidgets.QMessageBox, 'question', lambda *a, **k: QtWidgets.QMessageBox.StandardButton.No)
    dialog.text.appendPlainText('bn31\t-31- Dean Döge (EC Bad Nauheim)')
    assert not dialog.save()


def test_url_source_is_read_only(app):
    dialog = RosterEditorDialog(['https://example.org/roster.txt'], cached_text=lambda url: TEXT.replace('\r', ''))
    assert dialog.text.isReadOnly() and not dialog.save_button.isEnabled()
    assert 'Marius Erk' in dialog.text.toPlainText() and 'nur lesbar' in dialog.status.text()


def test_line_numbers(app, roster_file):
    dialog = RosterEditorDialog([str(roster_file)])
    dialog.resize(700, 400)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    gutter = dialog.text.numbers
    assert gutter.isVisible() and gutter.width() == dialog.text.line_number_width() > 0
    assert dialog.text.viewportMargins().left() == gutter.width()
    dialog.text.appendPlainText('kaputt ohne tab')
    dialog._check()
    assert dialog.text.problem_lines == {6}
    gutter.grab()   # paints without errors
    dialog.text.document().setModified(False)  # otherwise closing asks about saving
    dialog.close()


def test_current_line_is_highlighted(app, roster_file):
    dialog = RosterEditorDialog([str(roster_file)])
    editor = dialog.text
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().findBlockByNumber(2).position() + 2)
    editor.setTextCursor(cursor)
    selections = editor.extraSelections()
    assert len(selections) == 1 and selections[0].cursor.blockNumber() == 2
    assert selections[0].format.property(QtGui.QTextFormat.Property.FullWidthSelection)


def test_font_size_slider_and_line_number_contrast(app, roster_file):
    dialog = RosterEditorDialog([str(roster_file)], font_size=12)
    assert dialog.text.font().pointSize() == 12 and dialog.font_size.value() == 12
    narrow = dialog.text.line_number_width()
    dialog.font_size.setValue(20)
    assert dialog.text.font().pointSize() == 20 and dialog.font_size_label.text() == '20 pt'
    assert dialog.text.line_number_width() > narrow       # numbers grow with it
    assert dialog.text.tabStopDistance() == dialog.text.fontMetrics().horizontalAdvance(' ') * 10

    # line numbers closer to the text color than to the background color
    def distance(a, b):
        return sum(abs(x - y) for x, y in zip(a.getRgb()[:3], b.getRgb()[:3]))
    palette = dialog.text.palette()
    number = dialog.text.number_color()
    assert distance(number, palette.text().color()) < distance(number, palette.alternateBase().color())
