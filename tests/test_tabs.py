"""Ordner in Tabs, Kopieren per Drop auf einen anderen Tab (offscreen)."""
import os
import time

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
