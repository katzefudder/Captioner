"""Map picker and places in the caption panel, offscreen and without a real network."""
import os
import time

import pytest

from conftest import make_jpeg, requires_exiftool

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from captioner import geo  # noqa: E402

BN = geo.Place('Bad Nauheim', 'Colonel-Knight-Stadion', 50.3725500, 8.7384500)
UNREACHABLE = 'http://127.0.0.1:9'


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def no_internet(monkeypatch):
    """Tiles and Nominatim on a closed port: like offline, never into the real network."""
    from captioner.ui import mapview
    monkeypatch.setattr(mapview.MapView, 'tile_url', staticmethod(lambda z, x, y: f'{UNREACHABLE}/{z}/{x}/{y}.png'))
    monkeypatch.setattr(geo, 'NOMINATIM_URL', UNREACHABLE)


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)
    return condition()


def test_offline_shows_hint_instead_of_map_and_fields_stay_usable(app):
    from captioner.ui.placepicker import OFFLINE_TEXT, PlacePickerDialog
    dialog = PlacePickerDialog(geo.Place('Bad Nauheim'), geo.PlaceBook(), None)
    dialog.show()
    assert wait_until(lambda: dialog.stack.currentIndex() == 1)
    assert dialog.offline_label.text() == OFFLINE_TEXT
    assert not dialog.search_button.isEnabled()
    dialog.sublocation.setText('Colonel-Knight-Stadion')
    assert dialog.place() == geo.Place('Bad Nauheim', 'Colonel-Knight-Stadion')
    dialog.close()


def test_click_on_map_sets_point_and_asks_for_the_address(app):
    from captioner.ui.placepicker import PlacePickerDialog
    dialog = PlacePickerDialog(BN, geo.PlaceBook([BN.to_dict()]), None)
    dialog.resize(800, 700)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    view = dialog.map
    center = QPoint(view.width() // 2, view.height() // 2)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center + QPoint(40, 0))
    assert dialog.latitude == pytest.approx(BN.latitude, abs=1e-4)
    assert dialog.longitude > BN.longitude  # to the right of the old point
    # reverse search fails without network, with a notice; fields stay
    assert wait_until(lambda: 'keine Verbindung' in dialog.status.text())
    assert (dialog.city.text(), dialog.sublocation.text()) == (BN.city, BN.sublocation)
    dialog.close()


def test_found_places_fill_the_fields(app):
    from captioner.ui.placepicker import PlacePickerDialog
    dialog = PlacePickerDialog(None, geo.PlaceBook(), None)
    stadium = geo.Place('Bad Nauheim', 'Colonel-Knight-Stadion', 50.3725500, 8.7384500, label='Stadion')
    postcode = geo.Place('Bad Nauheim', '', 50.3667, 8.75, label='61231, Bad Nauheim')
    dialog._found([postcode, stadium])
    assert dialog.results.count() == 2 and dialog.place() == geo.Place('Bad Nauheim', '', 50.3667, 8.75)
    dialog._result_chosen(dialog.results.item(1))
    assert dialog.place() == geo.Place('Bad Nauheim', 'Colonel-Knight-Stadion', 50.3725500, 8.7384500)
    dialog.close()


@pytest.fixture
def window(app, tmp_path):
    from captioner import config
    from captioner.ui.main_window import MainWindow
    folder = tmp_path / 'fotos'
    folder.mkdir()
    make_jpeg(folder / 'a.jpg')
    w = MainWindow(config.Settings(roster_sources=[], places=[BN.to_dict()]), str(folder))
    w.scan_worker.wait(30000)
    QtWidgets.QApplication.processEvents()
    w.select_only(w.filtered[0])
    yield w
    w.writer.flush(30)
    w.close()


@requires_exiftool
def test_known_place_is_suggested_and_saving_sets_gps(window):
    editor = window.editor
    completer = editor.city.completer()
    completer.setCompletionPrefix('knight')
    assert completer.currentCompletion() == 'Bad Nauheim – Colonel-Knight-Stadion'
    completer.activated.emit(completer.currentCompletion())
    assert (editor.city.text(), editor.sublocation.text()) == (BN.city, BN.sublocation)
    assert editor.gps_hint.text().startswith('GPS wird gesetzt')

    editor.headline.setText('DEL 2 - A gegen B')
    editor.submit(0)
    item = window.filtered[0]
    assert (item.meta.latitude, item.meta.longitude) == (BN.latitude, BN.longitude)
    assert window.writer.flush(30)

    from captioner import metadata, scanner
    from captioner.exiftool import ExifTool, find_exiftool
    tool = ExifTool(find_exiftool()).start()
    try:
        fresh = scanner.scan(item.primary.parent)[0]
        list(metadata.read_items(tool, [fresh]))
    finally:
        tool.close()
    assert (fresh.meta.latitude, fresh.meta.longitude) == pytest.approx((BN.latitude, BN.longitude))


@requires_exiftool
def test_chosen_place_is_remembered_in_settings(window):
    window.remember_place(geo.Place('Regensburg', 'Donau-Arena', 49.01, 12.12))
    assert window.settings.places[0] == {'city': 'Regensburg', 'sublocation': 'Donau-Arena',
                                         'latitude': 49.01, 'longitude': 12.12}
    from captioner import config
    assert config.Settings.load().places[0]['city'] == 'Regensburg'
