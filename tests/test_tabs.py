"""Ordner in Tabs, Kopieren per Drop auf einen anderen Tab (offscreen)."""
import os
import time
from pathlib import Path

import pytest

from conftest import make_jpeg, requires_exiftool

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')

from captioner import transfer  # noqa: E402
from captioner.ui import tabs  # noqa: E402

pytestmark = requires_exiftool


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait_until(condition, timeout=30.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)
    return condition()


def scanned(tab):
    return wait_until(lambda: not tab.scanning()) and wait_until(lambda: all(i.meta_loaded for i in tab.all_items))


@pytest.fixture
def cards(tmp_path):
    a, b = tmp_path / 'karte1' / '100NCZ_9', tmp_path / 'karte2' / '100NCZ_9'
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / 'DSC_0001.NEF').write_bytes(b'raw1')
    make_jpeg(a / 'DSC_0001.JPG')
    make_jpeg(a / 'DSC_0002.JPG', color='blue')
    make_jpeg(b / 'DSC_0005.JPG', color='green')
    return a, b


@pytest.fixture
def window(app):
    from captioner import config
    from captioner.ui.main_window import MainWindow
    w = MainWindow(config.Settings(roster_sources=[]))
    yield w
    w.writer.flush(30)
    if w.copy_worker:
        w.copy_worker.wait(30000)
    w.close()


def test_tab_titles():
    assert tabs.tab_title('/Volumes/NIKON Z 9/DCIM/100NCZ_9') == 'NIKON Z 9 › 100NCZ_9'
    assert tabs.tab_title('/Volumes/NIKON Z 9') == 'NIKON Z 9'
    assert tabs.tab_title('/Users/flo/Pictures/2026') == '2026'
    assert tabs.tab_title(None) == 'Neuer Tab'


def test_tab_titles_on_windows(monkeypatch):
    monkeypatch.setattr(tabs, 'WINDOWS', True)
    monkeypatch.setenv('SystemDrive', 'C:')
    monkeypatch.setattr(tabs, 'volume_label', lambda root: {'E:\\': 'NIKON Z 9'}.get(root, ''))
    assert tabs.tab_title('E:\\DCIM\\100NCZ_9') == 'NIKON Z 9 › 100NCZ_9'
    assert tabs.tab_title('E:\\') == 'NIKON Z 9'
    assert tabs.tab_title('F:\\Fotos') == 'F: › Fotos'           # ohne Bezeichnung: Buchstabe
    assert tabs.tab_title('C:\\Users\\flo\\Pictures\\2026') == '2026'


def test_each_folder_gets_a_tab_and_keeps_its_own_state(window, cards):
    a, b = cards
    first = window.open_folder(a)
    assert window.tabs.count() == 1  # leerer Start-Tab wird benutzt
    second = window.open_folder(b)
    assert window.tabs.count() == 2 and window.tab is second
    assert scanned(first) and scanned(second)
    assert [i.name for i in first.all_items] == ['DSC_0001.JPG', 'DSC_0002.JPG']
    assert [i.name for i in window.filtered] == ['DSC_0005.JPG']

    window.tabs.setCurrentWidget(first)
    window.select_only(window.filtered[1])
    window.set_rating(4)
    window.tabs.setCurrentWidget(second)
    assert window.selected_keys == set() and window.filtered[0].meta.rating == 0
    window.tabs.setCurrentWidget(first)
    assert [i.name for i in window._selected_items()] == ['DSC_0002.JPG']

    # schon offen: nur wechseln
    window.tabs.setCurrentWidget(second)
    assert window.open_folder(a) is first and window.tab is first and window.tabs.count() == 2


def test_closing_the_last_tab_leaves_an_empty_one(window, cards):
    window.open_folder(cards[0])
    window.close_tab(0)
    assert window.tabs.count() == 1 and window.folder is None


def test_drop_on_other_tab_copies_raw_jpeg_and_sidecar(window, cards):
    a, b = cards
    source = window.open_folder(a)
    target = window.open_folder(b)
    assert scanned(source) and scanned(target)
    window.tabs.setCurrentWidget(source)
    window.select_only(window.filtered[0])          # DSC_0001 (NEF + JPG)
    window.set_rating(3)                              # erzeugt das Sidecar
    assert window.build_drag_mime() is not None      # schreibt vorher alles
    window.copy_dragged_to(target)
    assert wait_until(lambda: not window.copy_worker.isRunning())
    assert sorted(p.name for p in b.iterdir()) == ['DSC_0001.JPG', 'DSC_0001.NEF', 'DSC_0001.xmp', 'DSC_0005.JPG']
    assert (b / 'DSC_0001.NEF').read_bytes() == b'raw1'
    assert sorted(p.name for p in a.iterdir()) == ['DSC_0001.JPG', 'DSC_0001.NEF', 'DSC_0001.xmp', 'DSC_0002.JPG']
    # danach liest der Ziel-Tab neu ein
    assert wait_until(lambda: any(i.name == 'DSC_0001.JPG' for i in target.all_items)) and scanned(target)
    copied = next(i for i in target.all_items if i.name == 'DSC_0001.JPG')
    assert copied.meta.rating == 3


def test_conflict_is_asked_and_rename_keeps_both(window, cards, monkeypatch):
    a, b = cards
    make_jpeg(b / 'DSC_0002.JPG', color='white')
    source = window.open_folder(a)
    target = window.open_folder(b)
    assert scanned(source) and scanned(target)
    asked = []

    def answer(dialog):
        asked.append(dialog.windowTitle())
        dialog.decision = transfer.RENAME
        return True

    monkeypatch.setattr(tabs.ConflictDialog, 'exec', answer)
    window.tabs.setCurrentWidget(source)
    window.select_only(next(i for i in window.filtered if i.name == 'DSC_0002.JPG'))
    window.build_drag_mime()
    window.copy_dragged_to(target)
    assert wait_until(lambda: not window.copy_worker.isRunning())
    assert asked == ['Datei existiert bereits']
    assert sorted(p.name for p in b.iterdir()) == ['DSC_0002-2.JPG', 'DSC_0002.JPG', 'DSC_0005.JPG']


def test_cancelled_conflict_copies_nothing(window, cards, monkeypatch):
    a, b = cards
    make_jpeg(b / 'DSC_0002.JPG', color='white')
    source = window.open_folder(a)
    target = window.open_folder(b)
    assert scanned(source) and scanned(target)
    monkeypatch.setattr(tabs.ConflictDialog, 'exec', lambda dialog: False)
    window.tabs.setCurrentWidget(source)
    window.select_all_filtered()
    window.build_drag_mime()
    window.copy_dragged_to(target)
    assert window.copy_worker is None
    assert sorted(p.name for p in b.iterdir()) == ['DSC_0002.JPG', 'DSC_0005.JPG']


def test_drop_on_own_folder_does_nothing(window, cards):
    source = window.open_folder(cards[0])
    assert scanned(source)
    window.select_all_filtered()
    window.build_drag_mime()
    window.copy_dragged_to(source)
    assert window.copy_worker is None


def two_cards(tmp_path):
    cards = []
    for card, subs in (('NIKON Z 9', ('100NCZ_9', '101NCZ_9')), ('NIKON Z 8', ('100NCZ_8',))):
        for sub in subs:
            folder = tmp_path / card / 'DCIM' / sub
            folder.mkdir(parents=True)
            make_jpeg(folder / 'DSC_0001.JPG')
        cards.append(tmp_path / card)
    return cards


def drop_folders(window, widget, folders):
    from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(f)) for f in folders])
    point = widget.rect().center()
    enter = QDragEnterEvent(point, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    QtWidgets.QApplication.sendEvent(widget, enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPointF(point), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
    window.dropEvent(drop)


def test_dropping_two_cards_opens_their_image_folders(window, tmp_path):
    cards = two_cards(tmp_path)
    window.show()
    # auf die Galerie fallen gelassen: die reicht Ordner ans Fenster weiter
    drop_folders(window, window.view.viewport(), cards)
    folders = [Path(window.tabs.widget(i).folder) for i in range(window.tabs.count())]
    # je Bildordner ein Tab, kein leerer Tab bleibt stehen, der erste ist aktiv
    assert [(f.parent.parent.name, f.name) for f in folders] == [
        ('NIKON Z 9', '100NCZ_9'), ('NIKON Z 9', '101NCZ_9'), ('NIKON Z 8', '100NCZ_8')]
    assert window.tab.folder == str(folders[0])


def test_recursive_setting_opens_the_card_as_one_tab(window, tmp_path):
    cards = two_cards(tmp_path)
    window.settings.recursive = True
    window.open_folders(cards[:1])
    assert window.tabs.count() == 1 and window.folder == str(cards[0])
    assert scanned(window.tab) and len(window.all_items) == 2


def test_many_folders_ask_first(window, tmp_path, monkeypatch):
    root = tmp_path / 'Bilder'
    for n in range(window.MANY_FOLDERS + 1):
        (root / f'{n:02d}').mkdir(parents=True)
        make_jpeg(root / f'{n:02d}' / 'a.jpg')
    asked = []
    monkeypatch.setattr(QtWidgets.QMessageBox, 'question',
                        lambda *args: asked.append(args[2]) or QtWidgets.QMessageBox.StandardButton.No)
    assert window.open_folders([root]) == []
    assert asked and window.tabs.count() == 1 and window.folder is None


def test_folders_from_finder_open_as_tabs(window, cards, app):
    """Finder/Dock schicken je Ordner ein QFileOpenEvent an die Application."""
    from PySide6.QtGui import QFileOpenEvent
    from captioner.ui.main_window import OpenRequests
    requests = OpenRequests(app)
    try:
        for folder in cards:  # kommen vor dem Fenster an: werden gepuffert
            QtWidgets.QApplication.sendEvent(app, QFileOpenEvent(str(folder)))
        assert window.tabs.count() == 1 and window.folder is None
        requests.set_handler(window.open_paths)
        assert wait_until(lambda: window.tabs.count() == 2, timeout=5)
        assert [window.tabs.widget(i).folder for i in range(2)] == [str(f) for f in cards]
        assert window.tabs.tabText(1) == '100NCZ_9'

        # ein Bild statt eines Ordners: dessen Ordner, schon offen -> kein neuer Tab
        QtWidgets.QApplication.sendEvent(app, QFileOpenEvent(str(cards[1] / 'DSC_0005.JPG')))
        assert wait_until(lambda: window.tab is window.tabs.widget(1), timeout=5)
        assert window.tabs.count() == 2
    finally:
        app.removeEventFilter(requests)
        requests.deleteLater()


def test_open_dialog_takes_several_folders(window, cards, monkeypatch):
    from captioner.ui import folderdialog
    monkeypatch.setattr(folderdialog, 'choose_folders', lambda parent, title, start='': [str(f) for f in cards])
    window.choose_folder()
    assert [window.tabs.widget(i).folder for i in range(window.tabs.count())] == [str(f) for f in cards]
    monkeypatch.setattr(folderdialog, 'choose_folders', lambda parent, title, start='': [])
    window.choose_folder()  # abgebrochen
    assert window.tabs.count() == 2


def test_qt_fallback_dialog_allows_multiple_folders(app, monkeypatch):
    from captioner.ui import folderdialog
    seen = {}

    def fake_exec(dialog):
        views = dialog.findChildren(QtWidgets.QListView) + dialog.findChildren(QtWidgets.QTreeView)
        seen['modes'] = {v.selectionMode() for v in views}
        return False

    monkeypatch.setattr(QtWidgets.QFileDialog, 'exec', fake_exec)
    assert folderdialog._choose_qt(None, 'Ordner öffnen', '/tmp') == []
    assert seen['modes'] == {QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection}


def test_tabs_are_restored_after_restart(app, cards, tmp_path):
    from captioner import config
    from captioner.ui.main_window import MainWindow
    a, b = cards
    first = MainWindow(config.Settings(roster_sources=[]))
    first.open_folder(a)
    first.open_folder(b)
    first.tabs.setCurrentWidget(first.tab_for_folder(str(b)))
    assert first.settings.open_tabs == [str(a), str(b)] and first.settings.active_tab == str(b)
    first.close()

    settings = config.Settings.load()
    settings.open_tabs.append(str(tmp_path / 'nicht-eingesteckt'))   # Karte fehlt beim Start
    second = MainWindow(settings)
    try:
        assert [second.tabs.widget(i).folder for i in range(second.tabs.count())] == [str(a), str(b)]
        assert second.tab.folder == str(b)
        assert second.settings.open_tabs == [str(a), str(b)]   # fehlende fallen raus
    finally:
        second.close()


def test_search_camera_and_time_filters(window, tmp_path):
    from captioner.exiftool import ExifTool, find_exiftool
    from PySide6.QtCore import QTime
    folder = tmp_path / 'fotos'
    folder.mkdir()
    tool = ExifTool(find_exiftool()).start()
    try:
        for name, serial, when in (('a.jpg', '3001234', '2026:10:11 19:05:00'), ('b.jpg', '3005678', '2026:10:11 20:10:00'),
                                   ('c.jpg', '3005678', '2026:10:11 21:30:00')):
            make_jpeg(folder / name)
            tool.execute('-overwrite_original', '-EXIF:Model=NIKON Z 9', f'-EXIF:SerialNumber={serial}',
                         f'-EXIF:DateTimeOriginal={when}', str(folder / name))
    finally:
        tool.close()
    window.open_folder(folder)
    assert scanned(window.tab)
    names = lambda: [i.name for i in window.filtered]
    assert names() == ['a.jpg', 'b.jpg', 'c.jpg']

    assert wait_until(lambda: window.camera_filter.count() > 1)   # gefuellt, wenn der Scan fertig ist
    cameras = [window.camera_filter.itemText(i) for i in range(window.camera_filter.count())]
    assert cameras == ['Alle Kameras', 'NIKON Z 9 · …1234', 'NIKON Z 9 · …5678']
    window.camera_filter.setCurrentIndex(2)
    assert names() == ['b.jpg', 'c.jpg']
    window.camera_filter.setCurrentIndex(0)

    window.time_filter.setChecked(True)                 # schlaegt den Zeitraum der Bilder vor
    assert window.time_from.time() == QTime(19, 5) and window.time_to.time() == QTime(21, 30)
    window.time_from.setTime(QTime(20, 0))
    assert names() == ['b.jpg', 'c.jpg']
    window.time_to.setTime(QTime(21, 0))
    assert names() == ['b.jpg']
    window.time_filter.setChecked(False)

    window.select_only(window.filtered[0])
    window.editor.headline.setText('DEL 2 - A gegen B')
    window.editor.caption.setPlainText('Torjubel Erk')
    window.editor.submit(0)
    window.search.setText('jubel')
    window._search_timer.timeout.emit()
    assert names() == ['a.jpg']
