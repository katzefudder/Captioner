"""
Galerie: alle Kacheln eines Ordners, Tastaturbedienung wie in einem
Workflow-Tool fuer die Auswahl von Fotos,
Drag & Drop nach Lightroom (ADR 0001, Punkte 3 und 7).
"""
from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from ..i18n import _

ItemRole = Qt.ItemDataRole.UserRole + 1

TILE_W, TILE_H = 220, 210
IMAGE_H = 150

LABEL_COLORS = {
    'red': '#d64541', 'rot': '#d64541',
    'yellow': '#e6b800', 'gelb': '#e6b800',
    'green': '#3fa34d', 'grün': '#3fa34d', 'gruen': '#3fa34d',
    'blue': '#3b7dd8', 'blau': '#3b7dd8',
    'purple': '#8e5bc8', 'lila': '#8e5bc8', 'violett': '#8e5bc8',
}


# Farbklassen 1-8; 1-3 entsprechen den vorhandenen Sidecars
# im Archiv (1 Winner = Red, 2 Winner alt = Yellow, 3 Superior = Green)
CLASS_COLORS = {1: '#d64541', 2: '#e6b800', 3: '#3fa34d', 4: '#3b7dd8', 5: '#8e5bc8',
                6: '#e67e22', 7: '#16a085', 8: '#7f8c8d'}


def label_color(label):
    return QColor(LABEL_COLORS.get((label or '').strip().lower(), '#888888'))


def item_color(meta):
    """Farbe der Kachel: Farbklasse, sonst Lightroom-Label, sonst None."""
    if meta.color_class:
        return QColor(CLASS_COLORS[meta.color_class])
    if meta.label:
        return label_color(meta.label)
    return None


class GalleryModel(QAbstractListModel):
    def __init__(self, loader):
        super().__init__()
        self.loader = loader
        self.items = []
        self.rows = {}
        loader.ready.connect(self._thumbnail_ready)

    def set_items(self, items):
        """Neu aufbauen nur, wenn sich die Liste aendert (ein Reset springt nach oben)."""
        items = list(items)
        if items == self.items:
            return False
        self.beginResetModel()
        self.items = items
        self.rows = {item.key: row for row, item in enumerate(self.items)}
        self.endResetModel()
        return True

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == ItemRole:
            return item
        if role == Qt.ItemDataRole.DisplayRole:
            return item.name
        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [item.kind + ': ' + ', '.join(p.name for p in item.files)]
            if item.meta.caption:
                lines.append(item.meta.caption)
            if getattr(item, 'error', None):
                lines.append(_('Fehler: {error}').format(error=item.error))
            return '\n'.join(lines)
        return None

    def flags(self, index):
        base = super().flags(index)
        return base | Qt.ItemFlag.ItemIsDragEnabled if index.isValid() else base

    def refresh(self, keys=None):
        if not self.items:
            return
        if keys is None:
            self.dataChanged.emit(self.index(0), self.index(len(self.items) - 1))
            return
        for key in keys:
            row = self.rows.get(key)
            if row is not None:
                index = self.index(row)
                self.dataChanged.emit(index, index)

    def _thumbnail_ready(self, key):
        self.refresh([key])


class TileDelegate(QStyledItemDelegate):
    def __init__(self, loader, writer, parent=None):
        super().__init__(parent)
        self.loader = loader
        self.writer = writer

    def sizeHint(self, option, index):
        return QSize(TILE_W, TILE_H)

    def paint(self, painter: QPainter, option, index):
        item = index.data(ItemRole)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(4, 4, -4, -4)
        palette = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        background = palette.highlight().color() if selected else palette.alternateBase().color()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 6, 6)

        color = item_color(item.meta)
        if color is not None:
            painter.setBrush(color)
            painter.drawRoundedRect(QRect(rect.left(), rect.top(), rect.width(), 6), 3, 3)

        image_rect = QRect(rect.left() + 8, rect.top() + 12, rect.width() - 16, IMAGE_H)
        image = self.loader.image(item.key)
        if image is not None and not image.isNull():
            scaled = image.scaled(image_rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            x = image_rect.left() + (image_rect.width() - scaled.width()) // 2
            y = image_rect.top() + (image_rect.height() - scaled.height()) // 2
            painter.drawImage(x, y, scaled)
        else:
            painter.setBrush(palette.mid().color())
            painter.drawRect(image_rect)

        text_color = palette.highlightedText().color() if selected else palette.text().color()
        painter.setPen(text_color)
        font = QFont(option.font)
        font.setPointSizeF(max(8.0, font.pointSizeF() - 1))
        painter.setFont(font)
        line_y = image_rect.bottom() + 6
        name_rect = QRect(rect.left() + 8, line_y, rect.width() - 16, 16)
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(item.name, Qt.TextElideMode.ElideMiddle, name_rect.width() - 50))
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, item.kind)

        status_rect = QRect(rect.left() + 8, line_y + 16, rect.width() - 16, 16)
        # Tag-Kaestchen, davor die Sterne
        tag = '☑' if item.meta.tagged else '☐'
        stars = '★' * item.meta.rating + '☆' * (5 - item.meta.rating)
        painter.drawText(status_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f'{tag} {stars}')

        markers = []
        if getattr(item, 'error', None):
            markers.append(('!', QColor('#d64541')))
        elif self.writer.is_pending(item.key):
            markers.append(('…', text_color))
        if item.meta.is_captioned:
            markers.append(('✎', text_color))
        x = status_rect.right()
        for marker, color in reversed(markers):
            painter.setPen(QPen(color))
            width = painter.fontMetrics().horizontalAdvance(marker) + 6
            painter.drawText(QRect(x - width, status_rect.top(), width, status_rect.height()),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, marker)
            x -= width
        painter.restore()


class GalleryView(QListView):
    # Alle Kuerzel haengen als QShortcut am View, siehe keymap.py.
    files_dropped = Signal()  # Bilder aus der Galerie eines anderen Tabs hierher gezogen
    visible_changed = Signal()  # gescrollt, Groesse oder Inhalt geaendert: Kacheln nachladen

    FALLBACK_ROWS = 100  # solange das Layout noch nicht steht

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        # Drops nur aus anderen Galerien (Tabs), siehe dragEnterEvent
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.mime_factory = None  # liefert QMimeData fuer die gesamte Auswahl, oder None
        self.empty_text = ''      # Hinweis mit Logo, solange die Galerie leer ist
        # Beim Scrollen nicht fuer jedes Pixel Kacheln anfordern
        self._visible_timer = QTimer(self, singleShot=True, interval=40)
        self._visible_timer.timeout.connect(self.visible_changed)
        self.verticalScrollBar().valueChanged.connect(self.schedule_visible)

    def setModel(self, model):
        super().setModel(model)
        model.modelReset.connect(self.schedule_visible)

    def schedule_visible(self, *args):
        self._visible_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.schedule_visible()

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_visible()

    def visible_rows(self):
        """
        (erste, letzte) Zeile im sichtbaren Bereich, aus dem Raster gerechnet (gleich grosse
        Kacheln, zeilenweise): kein Durchlaufen tausender Kacheln beim Scrollen.
        """
        model = self.model()
        count = model.rowCount() if model is not None else 0
        if not count:
            return None
        first_rect = self.visualRect(model.index(0))
        if first_rect.isEmpty():
            return 0, min(count, self.FALLBACK_ROWS) - 1
        columns = 1
        while columns < count and self.visualRect(model.index(columns)).top() == first_rect.top():
            columns += 1
        line_height = (self.visualRect(model.index(columns)).top() - first_rect.top()) if columns < count else 0
        if line_height <= 0:
            return 0, count - 1  # nur eine Zeile
        area = self.viewport().rect()
        first_line = max(0, (area.top() - first_rect.top()) // line_height)
        last_line = max(first_line, (area.bottom() - first_rect.top()) // line_height)
        return min(count - 1, first_line * columns), min(count - 1, (last_line + 1) * columns - 1)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.model() is None or self.model().rowCount() or not self.empty_text:
            return
        from .resources import logo_pixmap
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.viewport().rect()
        size = max(64, min(256, rect.height() // 3, rect.width() // 3))
        logo = logo_pixmap(size)
        if not logo.isNull():
            target = QRect(rect.center().x() - size // 2, rect.center().y() - size // 2 - 40, size, size)
            painter.drawPixmap(target, logo)
            text_top = target.bottom() + 16
        else:
            text_top = rect.center().y()
        painter.setPen(self.palette().placeholderText().color())
        painter.drawText(QRect(rect.left() + 20, text_top, rect.width() - 40, 80),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                         self.empty_text)

    def _accepts(self, event):
        source = event.source()
        return isinstance(source, GalleryView) and source is not self

    def dragEnterEvent(self, event):
        if self._accepts(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()  # Ordner, Templates usw. nimmt das Hauptfenster

    def dragMoveEvent(self, event):
        if self._accepts(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self._accepts(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.files_dropped.emit()
        else:
            event.ignore()

    def startDrag(self, supported_actions):
        if self.mime_factory is None:
            return
        mime = self.mime_factory()
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        index = self.currentIndex()
        item = index.data(ItemRole) if index.isValid() else None
        image = self.model().loader.image(item.key) if item else None
        if image is not None and not image.isNull():
            from PySide6.QtGui import QPixmap
            drag.setPixmap(QPixmap.fromImage(image.scaled(
                120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
