"""Zoom in der Grossansicht (Z, *, +, -, Option/Alt+Pfeile)."""
import os

import pytest

from conftest import make_jpeg, requires_exiftool

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from captioner.ui.viewer import ZoomView  # noqa: E402


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def view(app):
    v = ZoomView()
    v.resize(800, 600)
    image = QImage(4000, 3000, QImage.Format.Format_RGB32)
    image.fill(QColor('gray'))
    v.set_image(image)
    return v


def dpr(v):
    return v.devicePixelRatioF() or 1.0


def test_starts_fitted(view):
    assert view.zoom is None
    assert view.fit_factor() == pytest.approx(0.2 * dpr(view))


def test_toggle_goes_to_100_percent_and_back(view):
    view.toggle()
    assert view.zoom == 1.0 and view.is_zoomed()
    view.toggle()
    assert view.zoom is None


def test_steps_up_and_down_to_fit(view):
    view.step(1)
    assert view.zoom == 0.5          # kleinste Stufe, eingepasst liegt darunter
    view.step(1)
    view.step(1)
    assert view.zoom == 1.0
    for _ in range(4):
        view.step(-1)
    assert view.zoom is None


def test_zoom_range_is_50_to_400_percent(view):
    view.zoom_to(0.1)
    assert view.zoom == 0.5
    view.zoom_to(10)
    assert view.zoom == 4.0
    view.center_on(QPointF(400, 300), 8.0)
    assert view.zoom == 4.0


def test_largest_step_is_a_ceiling(view):
    for _ in range(10):
        view.step(1)
    assert view.zoom == 4.0


def test_anchor_point_stays_under_the_mouse(view):
    anchor = QPointF(600, 150)
    before = view.image_point(anchor)
    view.zoom_to(1.0, anchor)
    after = view.image_point(anchor)
    assert after.x() == pytest.approx(before.x(), abs=0.01)
    assert after.y() == pytest.approx(before.y(), abs=0.01)


def test_panning_is_clamped_to_the_image(view):
    view.toggle()
    view.pan(100000, 100000)  # weit nach links oben schieben
    rect = view._image_rect()
    assert rect.left() == pytest.approx(0, abs=0.5) and rect.top() == pytest.approx(0, abs=0.5)
    view.pan(-100000, -100000)
    rect = view._image_rect()
    assert rect.right() == pytest.approx(800, abs=0.5) and rect.bottom() == pytest.approx(600, abs=0.5)


def test_tile_is_never_zoomed(view):
    view.toggle()
    small = QImage(320, 240, QImage.Format.Format_RGB32)
    view.set_image(small, provisional=True)
    assert not view.is_zoomed()      # Kachel bleibt eingepasst ...
    assert view.zoom == 1.0          # ... aber die Zoomstufe bleibt fuers Vollbild erhalten


@pytest.fixture
def window(app, tmp_path):
    from captioner import config
    from captioner.ui.main_window import MainWindow
    folder = tmp_path / 'fotos'
    folder.mkdir()
    for n in range(2):
        make_jpeg(folder / f'{n}.jpg', size=(3000, 2000))
    w = MainWindow(config.Settings(roster_sources=[]), str(folder))
    w.scan_worker.wait(30000)
    QtWidgets.QApplication.processEvents()
    w.show()
    w.select_only(w.filtered[0])
    w.view.setCurrentIndex(w.model.index(0))
    yield w
    w.close()


def wait_for_full_image(window):
    for _ in range(200):
        QtWidgets.QApplication.processEvents()
        if not window.viewer.zoom.provisional:
            return
        QTest.qWait(20)
    raise AssertionError('Vollbild kam nicht')


@requires_exiftool
def test_z_and_plus_minus_in_viewer(window):
    window.open_viewer()
    viewer = window.viewer
    viewer.activateWindow()
    wait_for_full_image(window)
    zoom = viewer.zoom

    QTest.keyClick(viewer, Qt.Key.Key_Z)
    assert zoom.zoom == 1.0
    QTest.keyClick(viewer, Qt.Key.Key_Plus)
    assert zoom.zoom == 1.5
    QTest.keyClick(viewer, Qt.Key.Key_Minus)
    assert zoom.zoom == 1.0
    QTest.keyClick(viewer, Qt.Key.Key_Z)
    assert zoom.zoom is None
    QTest.keyClick(viewer, Qt.Key.Key_Asterisk)
    assert zoom.zoom == 1.0


@requires_exiftool
def test_option_arrows_pan_and_plain_arrows_navigate(window):
    window.open_viewer()
    viewer = window.viewer
    wait_for_full_image(window)
    QTest.keyClick(viewer, Qt.Key.Key_Z)
    before = viewer.zoom.center
    QTest.keyClick(viewer, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier)
    assert viewer.zoom.center.x() > before.x()
    assert viewer.key == window.filtered[0].key

    QTest.keyClick(viewer, Qt.Key.Key_Right)
    assert viewer.key == window.filtered[1].key
    assert viewer.zoom.zoom == 1.0  # Zoom bleibt beim Blaettern


def test_drag_with_mouse_moves_the_visible_area(view):
    view.show()
    view.toggle()
    before = view.center
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPointF(400, 300).toPoint())
    assert view.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    QTest.mouseMove(view, QPointF(300, 250).toPoint())
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPointF(300, 250).toPoint())
    # Bild folgt der Maus: nach links oben gezogen -> mehr von rechts unten sichtbar
    assert view.center.x() > before.x() and view.center.y() > before.y()
    assert view.cursor().shape() == Qt.CursorShape.OpenHandCursor


def test_drag_does_nothing_when_fitted(view):
    view.show()
    before = view.center
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPointF(400, 300).toPoint())
    QTest.mouseMove(view, QPointF(100, 100).toPoint())
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPointF(100, 100).toPoint())
    assert view.center == before and view.zoom is None


@requires_exiftool
def test_slider_controls_zoom_and_follows_keys(window):
    window.open_viewer()
    viewer = window.viewer
    wait_for_full_image(window)
    slider = viewer.slider
    assert (slider.minimum(), slider.maximum()) == (50, 400)
    assert slider.focusPolicy() == Qt.FocusPolicy.NoFocus  # Pfeiltasten blaettern weiter

    slider.setValue(250)
    assert viewer.zoom.zoom == pytest.approx(2.5)
    assert viewer.fit_button.isEnabled()

    QTest.keyClick(viewer, Qt.Key.Key_Minus)
    assert viewer.zoom.zoom == 2.0 and slider.value() == 200

    viewer.fit_button.click()
    assert viewer.zoom.zoom is None and not viewer.fit_button.isEnabled()
    viewer.hundred_button.click()
    assert viewer.zoom.zoom == 1.0 and slider.value() == 100


def test_screen_stage_keeps_the_original_scale(app):
    """Bildschirmstufe (halbe Aufloesung): 100 % und Ausschnitt beziehen sich aufs Original."""
    v = ZoomView()
    v.resize(800, 600)
    half = QImage(2000, 1500, QImage.Format.Format_RGB32)
    half.fill(QColor('gray'))
    half.setText('full_size', '4000x3000')
    v.set_image(half)
    assert v.image_size() == (4000, 3000)
    assert v.fit_factor() == pytest.approx(0.2 * dpr(v))
    v.zoom_to(1.0, QPointF(200, 150))
    center = QPointF(v.center)
    full = QImage(4000, 3000, QImage.Format.Format_RGB32)
    full.fill(QColor('gray'))
    v.set_image(full)                      # volle Aufloesung kommt nach: nichts springt
    assert v.zoom == 1.0 and v.center == center
    v.grab()                               # zeichnet aus beiden Groessen ohne Fehler


@requires_exiftool
def test_render_view_decodes_at_screen_size(tmp_path):
    from captioner import previews
    from captioner.exiftool import ExifTool, find_exiftool
    from captioner.scanner import Item
    path = make_jpeg(tmp_path / 'gross.jpg', size=(4000, 3000))
    item = Item(key=str(path), embedded=[path])
    tool = ExifTool(find_exiftool()).start()
    try:
        image, size = previews.render_view(tool, item, 1500)
        assert size == (4000, 3000)
        assert 1500 <= max(image.size) < 4000      # Draft: verkleinert, aber nie unter die Bildschirmkante
        image, size = previews.render_view(tool, item, None)
        assert image.size == size == (4000, 3000)
    finally:
        tool.close()


def test_view_cache_prefetch_and_stages(app):
    from types import SimpleNamespace
    from captioner.ui.workers import ThumbnailLoader
    loader = ThumbnailLoader(None, None)
    started = []
    loader._start_view = lambda item, edge, priority: started.append((item.key, 'display' if edge else 'full'))
    shown = []
    loader.full_ready.connect(lambda key, image: shown.append((key, image.text('stage'))))

    def image(stage, pixels=10):
        result = QImage(pixels, pixels, QImage.Format.Format_RGB888)
        result.setText('stage', stage)
        return result

    a, b = SimpleNamespace(key='a'), SimpleNamespace(key='b')
    loader.request_full(a, [b])
    assert started == [('a', 'display'), ('a', 'full'), ('b', 'display')]
    loader._on_view('b', image('display'))             # vorgeladen: noch nicht gezeigt
    loader._on_view('a', image('full'))
    loader._on_view('a', image('display'))             # zu spaet: ersetzt das volle Bild nicht
    assert shown == [('a', 'full')] and loader.view_images['a'].text('stage') == 'full'

    started.clear()
    loader.request_full(b, [a])                         # weitergeblaettert: sofort aus dem Speicher
    assert shown[-1] == ('b', 'display') and started == [('b', 'full')]

    loader.VIEW_BYTES = image('display', 20).sizeInBytes()
    loader._on_view('c', image('display', 20))          # ueber dem Budget: aeltere gehen, das aktuelle bleibt
    assert 'b' in loader.view_images and 'a' not in loader.view_images
    loader.shutdown()
