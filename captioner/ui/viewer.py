"""
Preview with zoom.

Z or * switches between fitted and 100 %, + and - zoom in steps, the slider at the
bottom sets anything between 50 % and 400 %, Option/Alt+scroll wheel zooms at the
mouse position, Cmd/Ctrl+click zooms to the clicked spot, Option/Alt+arrow keys pan
(faster with Shift), and when zoomed the visible area can be dragged with the mouse
button held (hand cursor).

100 % means: one image pixel per screen pixel (Retina taken into account).
Zoom level and visible area are kept when moving to another image, so the sharpness
of a burst can be compared at the same spot.
"""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
import html

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QSplitter,
                               QTextBrowser, QVBoxLayout, QWidget)

from .. import details as details_module
from ..i18n import _
from .editor import VerticalScrollArea
from .gallery import item_color
from .workers import full_size

# Range of the zoom; "fitted" is usually below it (Z9 image ~13 %) and is a state of
# its own, not a zoom level
ZOOM_MIN = 0.5
ZOOM_MAX = 4.0
ZOOM_STEPS = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]
PAN_STEP = 60          # logical pixels per arrow key
PAN_STEP_FAST = 300

# Buttons of the bottom bar: on a dark background, active toggles (Caption, Info) clearly
# highlighted. Set only on these buttons so the caption panel moved in keeps its
# normal look.
BAR_BUTTON_STYLE = '''
QPushButton { background: #222; color: #ddd; border: 1px solid #444; border-radius: 5px; padding: 3px 12px; }
QPushButton:hover { border-color: #777; }
QPushButton:disabled { color: #666; border-color: #333; }
QPushButton:checked { background: #2f7de1; color: white; border-color: #5a9cf0; }
QPushButton:checked:hover { background: #3b8af0; }
'''


def clamp_zoom(factor):
    return min(max(factor, ZOOM_MIN), ZOOM_MAX)


class ZoomView(QWidget):
    zoom_changed = Signal(str)
    zoom_state = Signal(bool, float)   # zoomed?, factor (when fitted: the fit factor)
    FRAME_W = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 150)
        self._pixmap = None
        self._full_size = (0, 0)
        self.provisional = False   # tile instead of full image: only show fitted
        self.zoom = None           # None = fitted, otherwise factor (1.0 = 100 %)
        self.center = QPointF(0.5, 0.5)  # center of the visible area, relative (0..1)
        self._drag_from = None
        self.frame_color = None    # color class/label of the image: frame around the photo

    # --- State -------------------------------------------------------------

    def set_image(self, image, provisional=False):
        """
        image may be smaller than the original (screen stage, text 'full_size'): all
        computing is in pixels of the original, so 100 % is right and switching to full
        resolution doesn't move the visible area.
        """
        self._pixmap = QPixmap.fromImage(image) if image is not None and not image.isNull() else None
        self._full_size = full_size(image) if self._pixmap else (0, 0)
        self.provisional = provisional
        self._clamp()
        self.update()
        self._announce()

    def image_size(self):
        """Size of the original in pixels (not necessarily that of the loaded image)."""
        return self._full_size if self._pixmap else (0, 0)

    def _dpr(self):
        return self.devicePixelRatioF() or 1.0

    def fit_factor(self):
        """Factor (in screen pixels) at which the image fits exactly."""
        iw, ih = self.image_size()
        if not iw or not ih:
            return 1.0
        return min(self.width() / iw, self.height() / ih) * self._dpr()

    def is_zoomed(self):
        return self.zoom is not None and not self.provisional

    def factor(self):
        return self.zoom if self.is_zoomed() else self.fit_factor()

    def _scale(self):
        """Logical pixels per image pixel."""
        return self.factor() / self._dpr()

    # --- Zoom and panning --------------------------------------------------------

    def toggle(self, anchor=None):
        if self.zoom is None:
            self.zoom_to(1.0, anchor)
        else:
            self.zoom = None
            self.update()
            self._announce()

    def step(self, direction, anchor=None):
        current = self.factor()
        if direction > 0:
            larger = [z for z in ZOOM_STEPS if z > current * 1.001]
            if larger:
                self.zoom_to(larger[0], anchor)
        else:
            smaller = [z for z in ZOOM_STEPS if z < current * 0.999]
            if smaller and smaller[-1] > self.fit_factor():
                self.zoom_to(smaller[-1], anchor)
            else:
                self.zoom = None
                self.update()
                self._announce()

    def fit(self):
        self.zoom = None
        self.update()
        self._announce()

    def zoom_to(self, factor, anchor=None):
        """Zooms so that the image point under anchor (widget coordinates) stays put."""
        factor = clamp_zoom(factor)
        if not self._pixmap:
            self.zoom = factor
            self._announce()
            return
        anchor = QPointF(anchor) if anchor is not None else QPointF(self.width() / 2, self.height() / 2)
        point = self.image_point(anchor)
        self.zoom = factor
        iw, ih = self.image_size()
        s = self._scale()
        offset = anchor - QPointF(self.width() / 2, self.height() / 2)
        self.center = QPointF(point.x() - offset.x() / (iw * s), point.y() - offset.y() / (ih * s))
        self._clamp()
        self.update()
        self._announce()

    def center_on(self, widget_pos, factor):
        """Cmd/Ctrl+click: zoom to the spot and bring it to the center."""
        point = self.image_point(QPointF(widget_pos))
        self.zoom = clamp_zoom(factor)
        self.center = point
        self._clamp()
        self.update()
        self._announce()

    def pan(self, dx, dy):
        if not self.is_zoomed():
            return
        iw, ih = self.image_size()
        s = self._scale()
        self.center = QPointF(self.center.x() - dx / (iw * s), self.center.y() - dy / (ih * s))
        self._clamp()
        self.update()

    def image_point(self, widget_pos):
        """Relative image coordinate (0..1) under a widget position."""
        rect = self._image_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return QPointF(0.5, 0.5)
        x = (widget_pos.x() - rect.left()) / rect.width()
        y = (widget_pos.y() - rect.top()) / rect.height()
        return QPointF(min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))

    def _clamp(self):
        """No empty margin as long as the image is larger than the window."""
        iw, ih = self.image_size()
        if not iw or not ih or not self.is_zoomed():
            # When fitted (also the tile while switching images) center doesn't count: don't touch
            # it, otherwise the visible area for the next full image would be lost.
            return
        s = self._scale()
        cx, cy = self.center.x(), self.center.y()
        half_w = self.width() / 2 / (iw * s)
        half_h = self.height() / 2 / (ih * s)
        cx = 0.5 if half_w >= 0.5 else min(max(cx, half_w), 1 - half_w)
        cy = 0.5 if half_h >= 0.5 else min(max(cy, half_h), 1 - half_h)
        self.center = QPointF(cx, cy)

    def _image_rect(self):
        iw, ih = self.image_size()
        s = self._scale()
        w, h = iw * s, ih * s
        if self.is_zoomed():
            x = self.width() / 2 - self.center.x() * w
            y = self.height() / 2 - self.center.y() * h
        else:
            x = (self.width() - w) / 2
            y = (self.height() - h) / 2
        return QRectF(x, y, w, h)

    def _announce(self):
        if self.provisional:
            text = _('lädt Vollbild …')
        elif self.is_zoomed():
            text = f'{self.zoom * 100:.0f} %'
        else:
            text = _('eingepasst ({percent} %)').format(percent=f'{self.fit_factor() * 100:.0f}') if self._pixmap else ''
        self.zoom_changed.emit(text)
        self.zoom_state.emit(self.is_zoomed(), self.factor())
        if self._drag_from is None:
            # hand cursor right away, so you see the visible area can be dragged
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.is_zoomed() else Qt.CursorShape.ArrowCursor)

    # --- Painting ----------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#111111'))
        if not self._pixmap:
            painter.setPen(QColor('#aaaaaa'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _('lädt …'))
            return
        rect = self._image_rect()
        visible = rect.intersected(QRectF(self.rect()))
        if visible.isEmpty():
            return
        # visible area in pixels of the loaded image (may be smaller than the original)
        s = self._scale() * self._full_size[0] / self._pixmap.width()
        source = QRectF((visible.left() - rect.left()) / s, (visible.top() - rect.top()) / s,
                        visible.width() / s, visible.height() / s)
        # from 100 % hard pixels so sharpness can be judged; smooth below that
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.factor() < 1.0)
        painter.drawPixmap(visible, self._pixmap, source)
        if self.frame_color is not None:
            # outside around the image where there is room; at the window edge inside on the image edge
            half = self.FRAME_W / 2
            frame = visible.adjusted(-half, -half, half, half).intersected(
                QRectF(self.rect()).adjusted(half, half, -half, -half))
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(self.frame_color, self.FRAME_W, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap,
                                Qt.PenJoinStyle.MiterJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(frame)

    def set_frame_color(self, color):
        if color != self.frame_color:
            self.frame_color = color
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._clamp()
        self._announce()

    # --- Mouse -------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:   # Cmd on the Mac
            target = max(1.0, self.factor() * 2) if self.is_zoomed() else 1.0
            self.center_on(event.position(), target)
        elif self.is_zoomed():
            self._drag_from = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag_from is not None:
            delta = event.position() - self._drag_from
            self._drag_from = event.position()
            self.pan(delta.x(), delta.y())
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.is_zoomed() else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self._drag_from = None
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.is_zoomed() else Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event):
        self.toggle(event.position())

    def wheelEvent(self, event):
        delta = event.angleDelta()
        amount = delta.y() or delta.x()   # Qt sometimes turns Alt+wheel into a horizontal wheel
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            if amount:
                self.step(1 if amount > 0 else -1, event.position())
            return
        if self.is_zoomed():
            pixels = event.pixelDelta()
            if pixels.isNull():
                pixels = delta / 8
            self.pan(pixels.x(), pixels.y())
            return
        super().wheelEvent(event)

    def cursor_anchor(self):
        """Mouse position if it is over the widget; otherwise None (= center)."""
        pos = self.mapFromGlobal(self.cursor().pos())
        return QPointF(pos) if self.rect().contains(pos) else None


class InfoPanel(QTextBrowser):
    """EXIF/IPTC of the image shown, to the right of the image. Text is selectable."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # arrow keys keep moving between images
        self.setMinimumWidth(260)
        self.setStyleSheet('QTextBrowser { background: #1b1b1b; color: #ddd; border: none; padding: 8px; }')

    def show_sections(self, sections, loading=False):
        parts = ['<style>td { padding: 2px 6px 2px 0; vertical-align: top; } '
                 'td.k { color: #8a8a8a; white-space: nowrap; } h4 { margin: 12px 0 4px 0; color: #fff; }</style>']
        for title, rows in sections:
            parts.append(f'<h4>{html.escape(title)}</h4><table width="100%">')
            for key, value in rows:
                parts.append(f'<tr><td class="k">{html.escape(key)}</td><td>{html.escape(value)}</td></tr>')
            parts.append('</table>')
        if loading:
            parts.append('<p style="color:#8a8a8a">' + html.escape(_('EXIF wird gelesen …')) + '</p>')
        self.setHtml(''.join(parts))


class Viewer(QDialog):
    """
    Preview. Arrow keys move between images, Option/Alt+arrows pan; the main window attaches
    the remaining shortcuts as QShortcut. On the right the info panel with EXIF/IPTC.
    """
    navigate = Signal(int)
    info_toggled = Signal(bool)
    caption_toggled = Signal(bool)   # caption panel on/off; the main window moves it in

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Vorschau'))
        self.resize(1400, 950)
        self.setStyleSheet('background: #111; color: #ddd;')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.zoom = ZoomView()
        # Focus on the image, otherwise the panel's first field would get it and digits
        # would end up there instead of as stars
        self.zoom.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setContentsMargins(12, 6, 12, 10)
        self.info_panel = InfoPanel()
        # room for the main window's caption panel (moved here).
        # a scroll bar instead of squeezing: the panel is often taller than the preview
        self.caption_slot = VerticalScrollArea(min_width=420)
        self.caption_slot.setStyleSheet('background: palette(window); color: palette(window-text);')
        self.caption_slot.hide()
        self.splitter = QSplitter()
        self.splitter.addWidget(self.zoom)
        self.splitter.addWidget(self.caption_slot)
        self.splitter.addWidget(self.info_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setSizes([1000, 480, 340])
        layout.addWidget(self.splitter, 1)
        layout.addLayout(self._zoom_bar())
        layout.addWidget(self.info)
        self.key = None
        self._image = None
        self._item = None
        self._raw_details = None
        self.labels = ()

    def _zoom_bar(self):
        """Fit | slider 50-400 % | display. Takes no keyboard focus, so the arrow keys
        keep moving between images instead of moving the slider."""
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 4, 12, 0)
        self.fit_button = QPushButton(_('Einpassen'))
        self.fit_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fit_button.clicked.connect(self.zoom.fit)
        self.hundred_button = QPushButton('100 %')
        self.hundred_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hundred_button.clicked.connect(lambda: self.zoom.zoom_to(1.0))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(ZOOM_MIN * 100), int(ZOOM_MAX * 100))
        self.slider.setSingleStep(10)
        self.slider.setPageStep(50)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(50)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.setToolTip(_('Zoom 50–400 %'))
        self.slider.valueChanged.connect(self._slider_moved)
        self.zoom_label = QLabel()
        self.zoom_label.setMinimumWidth(150)
        # current level set off from the scale label "400 %" next to it
        self.zoom_label.setStyleSheet('font-weight: bold; padding-left: 16px;')
        self.zoom.zoom_changed.connect(self.zoom_label.setText)
        self.zoom.zoom_state.connect(self._sync_slider)
        bar.addWidget(self.fit_button)
        bar.addWidget(self.hundred_button)
        bar.addWidget(QLabel('50 %'))
        bar.addWidget(self.slider, 1)
        bar.addWidget(QLabel('400 %'))
        bar.addWidget(self.zoom_label)
        self.info_button = QPushButton(_('Infos'))
        self.info_button.setCheckable(True)
        self.info_button.setChecked(True)
        self.info_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.info_button.setToolTip(_('EXIF/IPTC rechts ein-/ausblenden'))
        self.info_button.toggled.connect(self.set_info_visible)
        self.caption_button = QPushButton(_('Beschriften'))
        self.caption_button.setCheckable(True)
        self.caption_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.caption_button.setToolTip(_('Beschriftungs-Panel ein-/ausblenden (I)'))
        self.caption_button.toggled.connect(self.set_caption_visible)
        bar.addWidget(self.caption_button)
        bar.addWidget(self.info_button)
        for button in (self.fit_button, self.hundred_button, self.caption_button, self.info_button):
            button.setStyleSheet(BAR_BUTTON_STYLE)
        return bar

    def set_caption_visible(self, visible):
        self.caption_slot.setVisible(visible)
        if self.caption_button.isChecked() != visible:
            self.caption_button.setChecked(visible)
        if not visible:
            self.zoom.setFocus()
        self.caption_toggled.emit(visible)

    def caption_visible(self):
        return self.caption_button.isChecked()

    def set_info_visible(self, visible):
        self.info_panel.setVisible(visible)
        if self.info_button.isChecked() != visible:
            self.info_button.setChecked(visible)
        if self._item is not None:
            self.show_item(self._item)
        self.info_toggled.emit(visible)

    def set_details(self, key, raw):
        if key != self.key:
            return
        self._raw_details = raw
        self._render_details()
        self._render_info()

    def _render_info(self):
        """Bottom: file, stars, color (caption if needed), at the very bottom camera, lens, exposure."""
        line = getattr(self, '_info_line', '')
        exposure = details_module.summary(self._raw_details) if self._raw_details else ''
        # The line is always there, even while the details are still being read: otherwise the
        # bar grew the first time an image was shown and the image jumped
        line += f'<br><span style="color: #9a9a9a">{html.escape(exposure) or "&nbsp;"}</span>'
        self.info.setText(line)

    def _render_details(self):
        if self._item is None:
            return
        sections = details_module.sections(self._raw_details or {}, self._item.meta, self.labels)
        loading = self._raw_details is None
        if self._raw_details and '_error' in self._raw_details:
            sections.append((_('Fehler'), [('ExifTool', self._raw_details['_error'])]))
        self.info_panel.show_sections(sections, loading)

    def _slider_moved(self, value):
        if getattr(self, '_syncing', False):
            return
        # zooms around the window center
        self.zoom.zoom_to(value / 100)

    def _sync_slider(self, zoomed, factor):
        self._syncing = True
        self.slider.setValue(round(clamp_zoom(factor) * 100))
        self._syncing = False
        self.fit_button.setEnabled(zoomed)

    def show_item(self, item, image=None, provisional=True):
        """image is the tile at first (provisional), set_image() delivers the full image later."""
        changed = item.key != self.key
        self.key = item.key
        stars = '★' * item.meta.rating + '☆' * (5 - item.meta.rating)
        tag = '☑' if item.meta.tagged else '☐'
        color = ' · ' + _('Farbklasse {number}').format(number=item.meta.color_class) if item.meta.color_class else ''
        label = f' ({item.meta.label})' if item.meta.label else ''
        self._info_line = f'<b>{item.name}</b> ({item.kind}) {tag} {stars}{color}{label}'
        # the caption is in the info panel; at the bottom only if the panel is off
        if not self.info_button.isChecked() and item.meta.caption:
            self._info_line += f'<br>{html.escape(item.meta.caption)}'
        self._item = item
        self.zoom.set_frame_color(item_color(item.meta))
        if changed:
            self._image = image
            self._raw_details = None
            self.zoom.set_image(image, provisional=provisional)
        self._render_info()
        # repaint even without a change: stars, color class, caption may have changed
        self._render_details()

    def set_image(self, key, image):
        if key == self.key:
            self._image = image
            self.zoom.set_image(image, provisional=False)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down) \
                and modifiers & Qt.KeyboardModifier.AltModifier:
            step = PAN_STEP_FAST if modifiers & Qt.KeyboardModifier.ShiftModifier else PAN_STEP
            # arrow right shows more of the right side: move the image left
            dx = {Qt.Key.Key_Left: step, Qt.Key.Key_Right: -step}.get(key, 0)
            dy = {Qt.Key.Key_Up: step, Qt.Key.Key_Down: -step}.get(key, 0)
            self.zoom.pan(dx, dy)
            return
        if key == Qt.Key.Key_Right:
            self.navigate.emit(1)
        elif key == Qt.Key.Key_Left:
            self.navigate.emit(-1)
        else:
            super().keyPressEvent(event)
