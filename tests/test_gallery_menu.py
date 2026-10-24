"""Gallery context menu: rating, color, tag, trash, Finder."""
import os
import time

import pytest

from conftest import make_jpeg, requires_exiftool

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QContextMenuEvent  # noqa: E402

from captioner import undo  # noqa: E402

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


@pytest.fixture
def window(app, tmp_path):
    from captioner import config
    from captioner.ui.main_window import MainWindow
    folder = tmp_path / 'fotos'
    folder.mkdir()
    (folder / 'DSC_0001.NEF').write_bytes(b'raw1')
    make_jpeg(folder / 'DSC_0001.JPG')
    make_jpeg(folder / 'DSC_0002.JPG', color='blue')
    w = MainWindow(config.Settings(roster_sources=[]), str(folder))
    assert wait_until(lambda: not w.tab.scanning() and len(w.filtered) == 2
                      and all(i.meta_loaded for i in w.all_items))
    w.show()
    yield w
    w.writer.flush(30)
    w.close()


def actions(menu):
    """Text before the tab (the shortcut is after it) -> action, submenus as 'menu/item'."""
    found = {}
    for action in menu.actions():
        if action.isSeparator():
            continue
        text = action.text().split('\t')[0]
        found[text] = action
        if action.menu():
            for sub, sub_action in actions(action.menu()).items():
                found[f'{text}/{sub}'] = sub_action
    return found


def test_menu_sets_rating_color_and_tag_for_the_selection(window):
    first, second = window.filtered
    window.selected_keys = {first.key, second.key}
    window.show_gallery()
    from captioner.ui import filemanager
    widget = window.gallery_menu(window)      # with a parent, otherwise Python cleans the menu up
    menu = actions(widget)
    for name in ('Bewertung/★★★', 'Farbklasse/Farbklasse 2 (Yellow)', 'Getaggt', 'Großansicht',
                 'Beschriftung kopieren', filemanager.reveal_label(), 'Pfade kopieren',
                 'In den Papierkorb legen …'):
        assert name in menu, name
    assert not menu['Beschriftung einfügen'].isEnabled()           # nothing copied yet
    assert menu['Bewertung/★★★'].text().endswith('3')             # shortcut next to it (⌘3 or Ctrl+3)
    menu['Bewertung/★★★'].trigger()
    menu['Farbklasse/Farbklasse 2 (Yellow)'].trigger()
    menu['Getaggt'].trigger()
    assert all(i.meta.rating == 3 and i.meta.color_class == 2 and i.meta.tagged for i in (first, second))
    again_widget = window.gallery_menu(window)
    again = actions(again_widget)
    assert again['Bewertung/★★★'].isChecked() and again['Farbklasse/Farbklasse 2 (Yellow)'].isChecked()
    assert again['Getaggt'].isChecked()
    window.undo()                                                  # one step per menu item
    assert not first.meta.tagged and first.meta.rating == 3


def test_right_click_on_unselected_tile_selects_only_it(window, monkeypatch):
    first, second = window.filtered
    window.select_only(first)
    shown = []
    monkeypatch.setattr(window, 'show_gallery_menu', shown.append)
    rect = window.view.visualRect(window.model.index(1))
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, rect.center(), window.view.viewport().mapToGlobal(rect.center()))
    QtWidgets.QApplication.sendEvent(window.view.viewport(), event)
    QtWidgets.QApplication.processEvents()
    assert shown and window.selected_keys == {second.key}


def test_trash_moves_all_files_after_asking(window, monkeypatch):
    from captioner.ui import filemanager
    from PySide6.QtWidgets import QMessageBox
    raw_item = next(i for i in window.filtered if i.raw)
    window.select_only(raw_item)
    window.set_rating(4)                                           # writes a sidecar
    assert window.writer.flush(30) and raw_item.sidecar.exists()
    trashed = []
    monkeypatch.setattr(filemanager, 'move_to_trash', lambda path: trashed.append(path.name) or True)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Cancel)
    window.trash_selected()
    assert trashed == [] and raw_item in window.filtered
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.trash_selected()
    assert sorted(trashed) == ['DSC_0001.JPG', 'DSC_0001.NEF', 'DSC_0001.xmp']
    assert raw_item not in window.filtered and raw_item not in window.all_items and not window.selected_keys
    assert window.undo_stack.undo_label is None                   # rating of the deleted image forgotten


def test_reveal_and_copy_paths(window, monkeypatch):
    from captioner.ui import filemanager
    revealed = []
    monkeypatch.setattr(filemanager, 'reveal', lambda path: revealed.append(path) or True)
    item = next(i for i in window.filtered if i.raw)
    window.select_only(item)
    window.reveal_current()
    assert revealed == [item.primary]
    window.copy_paths()
    assert QtWidgets.QApplication.clipboard().text().splitlines() == [str(p) for p in item.files]


def test_undo_forgets_deleted_items():
    a, b = object(), object()
    stack = undo.UndoStack()
    stack.push(undo.Step('x', [undo.Change(a, None, None), undo.Change(b, None, None)]))
    stack.push(undo.Step('y', [undo.Change(a, None, None)]))
    stack.forget([a])
    assert [s.label for s in stack.undo_steps] == ['x'] and [c.item for c in stack.undo_steps[0].changes] == [b]
