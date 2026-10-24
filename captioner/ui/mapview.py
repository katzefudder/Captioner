"""
Small OpenStreetMap map as a QWidget, without WebEngine/QtLocation (those would pull
QtQuick/QML or ~100 MB of Chromium into the bundle).

* Tiles from tile.openstreetmap.org via QNetworkAccessManager, with a QNetworkDiskCache
  in the cache directory (PreferCache: known areas work offline too).
* Dragging pans, scroll wheel/+/- zoom, a click without dragging sets the marker.
* online_changed(False) as soon as a tile comes neither from the network nor from the
  cache and not a single one has been loaded yet.
"""
import json
import time

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QToolButton, QWidget

from .. import config, geo, i18n
from ..i18n import _

CACHE_BYTES = 300 * 1024 * 1024
DEFAULT_CENTER = (51.1, 10.4)  # Germany
DEFAULT_ZOOM = 6
CLICK_TOLERANCE = 4  # px, beyond that it is a drag


def network_manager(parent):
    manager = QNetworkAccessManager(parent)
    cache = QNetworkDiskCache(manager)
    cache.setCacheDirectory(str(config.cache_dir() / 'map'))
    cache.setMaximumCacheSize(CACHE_BYTES)
    manager.setCache(cache)
    return manager


def _request(url, prefer_cache=False):
    request = QNetworkRequest(QUrl(url))
    request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, geo.USER_AGENT)
    request.setRawHeader(b'Accept-Language', i18n.language().encode())  # place names in the app language
    request.setTransferTimeout(15000)
    if prefer_cache:
        request.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                             QNetworkRequest.CacheLoadControl.PreferCache)
    return request


class MapView(QWidget):
    clicked = Signal(float, float)   # latitude, longitude
    online_changed = Signal(bool)

    tile_url = staticmethod(geo.tile_url)  # replaceable in tests

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 300)
        self.setMouseTracking(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.network = network_manager(self)
        self.zoom = DEFAULT_ZOOM
        self.center = geo.to_pixels(*DEFAULT_CENTER, self.zoom)  # world pixels
        self.marker = None   # (lat, lon)
        self.tiles = {}      # (z, x, y) -> QPixmap
        self.pending = {}    # (z, x, y) -> QNetworkReply
        self.failed = set()
        self.loaded_any = False
        self.online = True
        self._press = None
        self._press_center = None
        self._wheel = 0
        for text, step, tip in (('+', 1, _('Heranzoomen')), ('−', -1, _('Herauszoomen'))):
            button = QToolButton(self)
            button.setText(text)
            button.setToolTip(tip)
            button.setFixedSize(28, 28)
            button.clicked.connect(lambda _=False, s=step: self.zoom_by(s))
            setattr(self, 'zoom_in_button' if step > 0 else 'zoom_out_button', button)
        self._place_buttons()

    # --- Control --------------------------------------------------------------

    def set_view(self, lat, lon, zoom=None):
        if zoom is not None:
            self.zoom = max(geo.MIN_ZOOM, min(geo.MAX_ZOOM, int(zoom)))
        self.center = geo.to_pixels(lat, lon, self.zoom)
        self.update()

    def set_marker(self, lat, lon):
        self.marker = (lat, lon) if lat is not None and lon is not None else None
        self.update()

    def center_coordinates(self):
        return geo.to_coordinates(*self.center, self.zoom)

    def zoom_by(self, step, anchor=None):
        new_zoom = max(geo.MIN_ZOOM, min(geo.MAX_ZOOM, self.zoom + step))
        if new_zoom == self.zoom:
            return
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        # the point under the anchor stays put
        world = self._to_world(anchor)
        factor = 2 ** (new_zoom - self.zoom)
        offset = (anchor.x() - self.width() / 2, anchor.y() - self.height() / 2)
        self.zoom = new_zoom
        self.center = (world[0] * factor - offset[0], world[1] * factor - offset[1])
        self.update()

    def retry(self):
        self.failed.clear()
        self.online = True  # so that another failure sends online_changed(False) again
        self.update()

    # --- Coordinates ----------------------------------------------------------

    def _to_world(self, point):
        return (self.center[0] + point.x() - self.width() / 2,
                self.center[1] + point.y() - self.height() / 2)

    def _to_screen(self, lat, lon):
        x, y = geo.to_pixels(lat, lon, self.zoom)
        return QPointF(x - self.center[0] + self.width() / 2, y - self.center[1] + self.height() / 2)

    # --- Tiles ----------------------------------------------------------------

    def _tile(self, z, x, y):
        key = (z, x, y)
        if key in self.tiles:
            return self.tiles[key]
        if key not in self.pending and key not in self.failed:
            reply = self.network.get(_request(self.tile_url(z, x, y), prefer_cache=True))
            reply.finished.connect(lambda k=key, r=reply: self._tile_finished(k, r))
            self.pending[key] = reply
        return None

    def _tile_finished(self, key, reply):
        self.pending.pop(key, None)
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        pixmap = QPixmap()
        if ok and pixmap.loadFromData(reply.readAll()):
            if len(self.tiles) > 600:
                self.tiles.clear()
            self.tiles[key] = pixmap
            self.loaded_any = True
            self._set_online(True)
        else:
            self.failed.add(key)
            if not self.loaded_any:
                self._set_online(False)
        reply.deleteLater()
        self.update()

    def _set_online(self, online):
        if online != self.online:
            self.online = online
            self.online_changed.emit(online)

    # --- Painting -------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#e8e4dc'))
        size = geo.TILE_SIZE
        count = 2 ** self.zoom
        left = self.center[0] - self.width() / 2
        top = self.center[1] - self.height() / 2
        first_x, first_y = int(left // size), int(top // size)
        last_x, last_y = int((left + self.width()) // size), int((top + self.height()) // size)
        for ty in range(max(0, first_y), min(count - 1, last_y) + 1):
            for tx in range(first_x, last_x + 1):
                pixmap = self._tile(self.zoom, tx % count, ty)
                if pixmap is not None:
                    painter.drawPixmap(QPoint(int(tx * size - left), int(ty * size - top)), pixmap)
        if self.marker:
            self._draw_marker(painter, self._to_screen(*self.marker))
        self._draw_attribution(painter)

    @staticmethod
    def _draw_marker(painter, point):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('white'), 3))
        painter.setBrush(QColor('#d64541'))
        painter.drawEllipse(point, 9, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('white'))
        painter.drawEllipse(point, 3, 3)

    def _draw_attribution(self, painter):
        metrics = painter.fontMetrics()
        text = _(geo.ATTRIBUTION)
        rect = QRect(0, 0, metrics.horizontalAdvance(text) + 10, metrics.height() + 4)
        rect.moveBottomRight(self.rect().bottomRight())
        painter.fillRect(rect, QColor(255, 255, 255, 200))
        painter.setPen(QColor('#333'))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_buttons()

    def _place_buttons(self):
        self.zoom_in_button.move(8, 8)
        self.zoom_out_button.move(8, 40)

    # --- Mouse and keys -------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position()
            self._press_center = self.center
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._press is None:
            return
        delta = event.position() - self._press
        self.center = (self._press_center[0] - delta.x(), self._press_center[1] - delta.y())
        self.update()

    def mouseReleaseEvent(self, event):
        if self._press is None or event.button() != Qt.MouseButton.LeftButton:
            return
        delta = event.position() - self._press
        self._press = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if abs(delta.x()) <= CLICK_TOLERANCE and abs(delta.y()) <= CLICK_TOLERANCE:
            self.center = self._press_center
            lat, lon = geo.to_coordinates(*self._to_world(event.position()), self.zoom)
            self.set_marker(lat, lon)
            self.clicked.emit(lat, lon)

    def mouseDoubleClickEvent(self, event):
        self.zoom_by(1, event.position())

    def wheelEvent(self, event):
        self._wheel += event.angleDelta().y()
        while abs(self._wheel) >= 120:
            step = 1 if self._wheel > 0 else -1
            self._wheel -= step * 120
            self.zoom_by(step, event.position())

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_by(1)
        elif key == Qt.Key.Key_Minus:
            self.zoom_by(-1)
        else:
            step = 80
            moves = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
                     Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step)}
            if key not in moves:
                super().keyPressEvent(event)
                return
            dx, dy = moves[key]
            self.center = (self.center[0] + dx, self.center[1] + dy)
            self.update()


class Geocoder(QObject):
    """Nominatim search and reverse search, at most one request per second."""
    found = Signal(list)            # [geo.Place] for search()
    resolved = Signal(object)       # geo.Place or None for reverse()
    failed = Signal(str)

    MIN_INTERVAL = 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self._last = 0.0
        self._queued = None   # (url, handler); only the newest waiting request counts
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._send_queued)
        self._reply = None

    def search(self, query):
        query = query.strip()
        if query:
            self._enqueue(geo.search_url(query), self._on_search)

    def reverse(self, lat, lon):
        self._enqueue(geo.reverse_url(lat, lon), self._on_reverse)

    def _enqueue(self, url, handler):
        self._queued = (url, handler)
        wait = self.MIN_INTERVAL - (time.monotonic() - self._last)
        self._timer.start(max(0, int(wait * 1000)))

    def _send_queued(self):
        if self._queued is None:
            return
        url, handler = self._queued
        self._queued = None
        if self._reply is not None:
            self._reply.abort()
        self._last = time.monotonic()
        reply = self.network.get(_request(url))
        self._reply = reply
        reply.finished.connect(lambda r=reply, h=handler: self._finished(r, h))

    def _finished(self, reply, handler):
        if self._reply is reply:
            self._reply = None
        error = reply.error()
        data = bytes(reply.readAll())
        reply.deleteLater()
        if error == QNetworkReply.NetworkError.OperationCanceledError:
            return
        if error != QNetworkReply.NetworkError.NoError:
            self.failed.emit(_('Suche nicht möglich: keine Verbindung zum Kartendienst'))
            return
        try:
            handler(json.loads(data.decode('utf-8')))
        except ValueError:
            self.failed.emit(_('Unerwartete Antwort vom Kartendienst'))

    def _on_search(self, data):
        self.found.emit(geo.places_from_search(data))

    def _on_reverse(self, data):
        self.resolved.emit(geo.place_from_result(data) if isinstance(data, dict) and 'error' not in data else None)
