"""Logo und Icons (make icons) sind vorhanden und in der App gesetzt."""
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')

from captioner.ui.resources import ICON_SIZES, RESOURCES, app_icon, logo_pixmap  # noqa: E402


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_svg_is_valid_and_font_independent(app):
    from PySide6.QtSvg import QSvgRenderer
    svg = (RESOURCES / 'logo.svg').read_text(encoding='utf-8')
    assert QSvgRenderer(str(RESOURCES / 'logo.svg')).isValid()
    assert '<text' not in svg  # ".dng" ist ein Pfad, sieht ohne die Schrift gleich aus


def test_generated_icons_exist(app):
    for size in ICON_SIZES:
        assert logo_pixmap(size).width() == size
    assert (RESOURCES / 'captioner.icns').stat().st_size > 10_000
    assert (RESOURCES / 'captioner.ico').stat().st_size > 1_000


def test_app_icon_has_all_sizes(app):
    icon = app_icon()
    assert not icon.isNull()
    assert {s.width() for s in icon.availableSizes()} >= {16, 32, 256, 512}


def test_empty_gallery_shows_hint(app, tmp_path):
    from captioner import config
    from captioner.ui.main_window import MainWindow
    w = MainWindow(config.Settings(roster_sources=[]))
    try:
        assert 'Ordner öffnen' in w.view.empty_text
        empty = tmp_path / 'leer'
        empty.mkdir()
        w.open_folder(empty)
        w.scan_worker.wait(10000)
        QtWidgets.QApplication.processEvents()
        assert w.view.empty_text.startswith('Keine Bilder')
    finally:
        w.close()
