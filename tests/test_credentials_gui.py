"""Content Credentials in der Oberflaeche (ADR 0002): Warnung, Abzeichen, Filter, Info, Herkunft."""
import os

import pytest

from conftest import make_jpeg, requires_exiftool
from test_credentials import sign

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')

pytestmark = requires_exiftool


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app, tmp_path):
    from captioner import config
    from captioner.ui.main_window import MainWindow
    w = MainWindow(config.Settings(roster_sources=[]))
    yield w
    w.close()


@pytest.fixture
def folder(tmp_path):
    folder = tmp_path / 'fotos'
    folder.mkdir()
    sign(make_jpeg(tmp_path / 'src.jpg'), folder / 'signed.jpg', 'c2pa.created')
    make_jpeg(folder / 'plain.jpg')
    return folder


def open_and_wait(window, folder):
    window.open_folder(folder)
    window.scan_worker.wait(30000)
    QtWidgets.QApplication.processEvents()


def item_named(window, name):
    return next(i for i in window.all_items if i.name == name)


def select(window, *items):
    window.selected_keys = {i.key for i in items}
    window.apply_filter(False)


def answer(window, monkeypatch, choice):
    asked = []
    monkeypatch.setattr(window, '_ask_credentials', lambda risky: asked.append([i.name for i in risky]) or choice)
    return asked


def test_scan_reads_credentials_and_shows_filter(window, folder):
    from captioner import credentials
    open_and_wait(window, folder)
    assert credentials.level(item_named(window, 'signed.jpg').credentials) == credentials.LEVEL_VALID
    assert item_named(window, 'plain.jpg').credentials == []
    assert not window.credentials_filter.isHidden()

    window.credentials_filter.setCurrentIndex(window.credentials_filter.findData('any'))
    assert [i.name for i in window.filtered] == ['signed.jpg']
    window.credentials_filter.setCurrentIndex(window.credentials_filter.findData('none'))
    assert [i.name for i in window.filtered] == ['plain.jpg']


def test_tooltip_mentions_credentials(window, folder):
    from PySide6.QtCore import Qt
    open_and_wait(window, folder)
    model = window.model
    row = model.rows[item_named(window, 'signed.jpg').key]
    assert 'Content Credentials (signed.jpg)' in model.data(model.index(row), Qt.ItemDataRole.ToolTipRole)


def test_cancel_keeps_file_untouched(window, folder, monkeypatch):
    open_and_wait(window, folder)
    signed = item_named(window, 'signed.jpg')
    asked = answer(window, monkeypatch, 'cancel')
    select(window, signed, item_named(window, 'plain.jpg'))
    window.set_rating(4)
    assert asked == [['signed.jpg']]
    assert signed.meta.rating == 0 and window.writer.pending_count() == 0


def test_write_anyway_breaks_manifest_and_asks_once(window, folder, monkeypatch):
    from captioner import credentials
    open_and_wait(window, folder)
    signed = item_named(window, 'signed.jpg')
    asked = answer(window, monkeypatch, 'write')
    select(window, signed)
    window.set_rating(4)
    window.set_color_class(2)
    assert asked == [['signed.jpg']]
    window.writer.flush(30)
    assert credentials.level(signed.credentials) == credentials.LEVEL_INVALID
    window.credentials_filter.setCurrentIndex(window.credentials_filter.findData('invalid'))
    assert window.filtered == [signed]


def test_protect_writes_only_raw_sidecar(window, tmp_path, monkeypatch):
    from captioner import credentials
    folder = tmp_path / 'paar'
    folder.mkdir()
    (folder / 'DSC_0001.NEF').write_bytes(b'raw')
    sign(make_jpeg(tmp_path / 'src.jpg'), folder / 'DSC_0001.JPG', 'c2pa.created')
    open_and_wait(window, folder)
    item = window.all_items[0]
    answer(window, monkeypatch, 'protect')
    select(window, item)
    window.set_rating(5)
    window.writer.flush(30)
    assert item.protect_embedded
    assert (folder / 'DSC_0001.xmp').exists()
    assert credentials.read(folder / 'DSC_0001.JPG').state == credentials.VALID


def test_protect_offered_only_with_raw(window, folder, monkeypatch):
    open_and_wait(window, folder)
    shown = []

    def fake_exec(box):
        shown.append([b.text() for b in box.buttons()])
        return 0
    monkeypatch.setattr(QtWidgets.QMessageBox, 'exec', fake_exec)
    assert window._ask_credentials([item_named(window, 'signed.jpg')]) == 'cancel'
    assert not any('RAW' in text for text in shown[0])


def test_info_panel_section(folder):
    from captioner import credentials, details, scanner
    item = scanner.scan(folder)[1]
    item.credentials = credentials.read_item(item)
    sections = dict(details.sections({}, item.meta, (), item.credentials))
    rows = dict(sections['Content Credentials'])
    assert rows['Status'] == 'gültig, Unterzeichner unbekannt'
    assert rows['Unterzeichner'] == 'Test Fotograf (Captioner Tests)'
    assert rows['Aktionen'] == 'erstellt'


def test_provenance_dialog(app, folder):
    from PySide6.QtGui import QImage
    from captioner import credentials, scanner
    from captioner.ui.provenance import ProvenanceDialog
    item = next(i for i in scanner.scan(folder) if i.name == 'signed.jpg')
    item.credentials = credentials.read_item(item)
    dialog = ProvenanceDialog(item, QImage(str(item.primary)))
    page = dialog.pages[0]
    assert page.steps.count() == 1
    assert page.signed_box.image.pixmap() is not None and not page.signed_box.image.pixmap().isNull()
    assert not page.difference_box.image.pixmap().isNull()
    assert '%' in page.score.text()
    assert page.table.isHidden() and not page.no_metadata.isHidden()
