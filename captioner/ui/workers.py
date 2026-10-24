"""
Background work. The UI never waits for a file (ADR 0001, item 2).

* ScanWorker: read a folder, load metadata in chunks
* ThumbnailLoader: tiles in the QThreadPool, only for wanted items
* MetadataWriter: one write queue; per item the latest state wins.
  flush() blocks until everything is written - the drag start needs that.
* RosterWorker: load rosters (network) without blocking the UI
"""
import collections
import logging
import threading

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal
from PySide6.QtGui import QImage

from .. import details, metadata, previews, scanner
from ..exiftool import ExifTool

logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    scanned = Signal(list)        # all items, by file name
    chunk_loaded = Signal(list)   # items with freshly read metadata
    failed = Signal(str)

    def __init__(self, pool, folder, recursive):
        super().__init__()
        self.pool = pool
        self.folder = folder
        self.recursive = recursive
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        # Own instance instead of the pool: every scan runs in a new thread, a pool
        # instance would stay around until the program ends
        tool = ExifTool(self.pool.executable)
        try:
            items = scanner.scan(self.folder, self.recursive)
            self.scanned.emit(items)
            for chunk in metadata.read_items(tool, items, chunk_size=100):
                if self._cancel:
                    return
                self.chunk_loaded.emit(chunk)
        except Exception as e:
            logger.exception('Scan fehlgeschlagen')
            self.failed.emit(str(e))
        finally:
            tool.close()


class _Signals(QObject):
    ready = Signal(str, QImage)       # item.key, image
    failed = Signal(str, str)
    details = Signal(str, object)     # item.key, raw values for the info panel
    view = Signal(str, QImage)        # item.key, preview image (text 'stage', 'full_size')


class _DetailsTask(QRunnable):
    def __init__(self, loader, item):
        super().__init__()
        self.loader = loader
        self.item = item

    def run(self):
        try:
            data = details.read(self.loader.pool.get(), self.item)
        except Exception as e:
            logger.warning('EXIF/IPTC fuer %s nicht lesbar: %s', self.item.name, e)
            data = {'_error': str(e)}
        self.loader.signals.details.emit(self.item.key, data)


class _ViewTask(QRunnable):
    """Preview: screen resolution (edge) or full resolution (edge=None)."""

    def __init__(self, loader, item, edge):
        super().__init__()
        self.loader = loader
        self.item = item
        self.edge = edge

    def run(self):
        key, stage = self.item.key, 'display' if self.edge else 'full'
        try:
            # moved on: don't decode outdated jobs any more
            if not self.loader._view_wanted(key, stage):
                return
            image, size = previews.render_view(self.loader.pool.get(), self.item, self.edge)
            qimage = QImage(image.tobytes(), image.width, image.height, image.width * 3,
                            QImage.Format.Format_RGB888).copy()
            # size of the original: 100 % means pixels of the original, even for the smaller stage
            qimage.setText('full_size', f'{size[0]}x{size[1]}')
            # draft returns at most the original size: then it already is the full image
            qimage.setText('stage', 'full' if (image.width, image.height) == size else stage)
            self.loader.signals.view.emit(key, qimage)
        except Exception as e:
            logger.warning('Großansicht für %s fehlgeschlagen: %s', self.item.name, e)
        finally:
            self.loader.view_pending.discard((key, stage))


def full_size(image):
    """(width, height) of the original for a preview image; without the text, its own size."""
    text = image.text('full_size') if image is not None else ''
    if text:
        width, height = text.split('x')
        return int(width), int(height)
    return (image.width(), image.height()) if image is not None else (0, 0)


class _ThumbnailTask(QRunnable):
    def __init__(self, loader, item, size):
        super().__init__()
        self.loader = loader
        self.item = item
        self.size = size

    def run(self):
        key = self.item.key
        if key not in self.loader.wanted:
            self.loader.pending.discard(key)
            return
        try:
            data = self.loader.cache.tile(self.loader.pool.get(), self.item, self.size)
            qimage = QImage()
            qimage.loadFromData(data, 'JPEG')
            self.loader.signals.ready.emit(key, qimage)
        except Exception as e:
            logger.warning('Vorschau fuer %s fehlgeschlagen: %s', self.item.name, e)
            self.loader.signals.failed.emit(key, str(e))
        finally:
            self.loader.pending.discard(key)


class ThumbnailLoader(QObject):
    """Load tiles and keep them in memory (LRU)."""
    ready = Signal(str)
    full_ready = Signal(str, QImage)
    details_ready = Signal(str, object)

    # by bytes, not by count: tiles have been larger since the size slider (previews.TILE_SIZE)
    MEMORY_BYTES = 400 * 1024 * 1024

    def __init__(self, pool, cache):
        super().__init__()
        self.pool = pool
        self.cache = cache
        self.threads = QThreadPool()
        self.threads.setMaxThreadCount(4)
        # don't let threads expire: every new thread would get a new ExifTool process
        self.threads.setExpiryTimeout(-1)
        self.images = collections.OrderedDict()
        self.memory = 0  # bytes in images
        self.wanted = set()
        self.pending = set()
        self.signals = _Signals()
        self.signals.ready.connect(self._on_ready)
        self.signals.details.connect(self._on_details)
        self.signals.view.connect(self._on_view)
        self.details = {}
        # preview in its own threads: never waits behind generating tiles
        self.view_threads = QThreadPool()
        self.view_threads.setMaxThreadCount(2)
        self.view_threads.setExpiryTimeout(-1)
        self.display_edge = 3840       # longest screen edge in pixels, set by the main window
        self.view_current = None       # key of the image in the preview
        self.view_prefetch = set()     # neighbours whose screen stage is being prepared
        self.view_pending = set()      # (key, stage)
        self.view_images = collections.OrderedDict()   # key -> QImage (best available stage)

    def image(self, key):
        image = self.images.get(key)
        if image is not None:
            self.images.move_to_end(key)
        return image

    def request(self, items):
        """Only these items are wanted; old jobs still waiting expire."""
        self.wanted = {item.key for item in items}
        for item in items:
            if item.key in self.images or item.key in self.pending:
                continue
            self.pending.add(item.key)
            self.threads.start(_ThumbnailTask(self, item, previews.TILE_SIZE))

    def request_details(self, item):
        """Camera and IPTC values; from memory if already read."""
        if item.key in self.details:
            self.details_ready.emit(item.key, self.details[item.key])
            return
        self.view_threads.start(_DetailsTask(self, item), priority=5)

    def invalidate_details(self, key):
        self.details.pop(key, None)

    def _on_details(self, key, data):
        if '_error' not in data:
            self.details[key] = data
        self.details_ready.emit(key, data)

    # preview in memory: current image (full 45 MP ~ 136 MB), neighbours and recently viewed
    VIEW_BYTES = 600 * 1024 * 1024

    def request_full(self, item, neighbours=()):
        """
        Preview: first at screen resolution (sharp right away when fitted), then at full
        resolution for 100 %. The neighbours are prepared at screen resolution.
        """
        self.view_current = item.key
        self.view_prefetch = {n.key for n in neighbours}
        cached = self.view_images.get(item.key)
        if cached is not None:
            self.view_images.move_to_end(item.key)
            self.full_ready.emit(item.key, cached)
        stage = cached.text('stage') if cached is not None else None
        if stage is None:
            self._start_view(item, self.display_edge, priority=30)
        if stage != 'full':
            self._start_view(item, None, priority=20)
        for neighbour in neighbours:
            if neighbour.key not in self.view_images:
                self._start_view(neighbour, self.display_edge, priority=10)

    def _start_view(self, item, edge, priority):
        task = (item.key, 'display' if edge else 'full')
        if task not in self.view_pending:
            self.view_pending.add(task)
            self.view_threads.start(_ViewTask(self, item, edge), priority=priority)

    def _view_wanted(self, key, stage):
        if key == self.view_current:
            return True
        return stage == 'display' and key in self.view_prefetch

    def _on_view(self, key, image):
        cached = self.view_images.get(key)
        if cached is not None and cached.text('stage') == 'full' and image.text('stage') != 'full':
            return  # never replace a full image with the smaller stage
        self.view_images[key] = image
        self.view_images.move_to_end(key)
        total = sum(kept.sizeInBytes() for kept in self.view_images.values())
        for other in list(self.view_images):   # oldest first, never the current one
            if total <= self.VIEW_BYTES:
                break
            if other != self.view_current:
                total -= self.view_images.pop(other).sizeInBytes()
        if key == self.view_current:
            self.full_ready.emit(key, image)

    def invalidate_view(self, key):
        self.view_images.pop(key, None)

    def invalidate(self, key):
        image = self.images.pop(key, None)
        if image is not None:
            self.memory -= image.sizeInBytes()

    def _on_ready(self, key, image):
        old = self.images.pop(key, None)
        self.memory += image.sizeInBytes() - (old.sizeInBytes() if old is not None else 0)
        self.images[key] = image
        self._trim()
        self.ready.emit(key)

    def _trim(self):
        """Drop the oldest first, but never tiles that are wanted right now (visible)."""
        if self.memory <= self.MEMORY_BYTES:
            return
        for key in list(self.images):
            if self.memory <= self.MEMORY_BYTES:
                break
            if key not in self.wanted:
                self.memory -= self.images.pop(key).sizeInBytes()

    def shutdown(self):
        self.wanted = set()
        self.view_current, self.view_prefetch = None, set()
        self.threads.clear()
        self.view_threads.clear()
        self.threads.waitForDone(5000)
        self.view_threads.waitForDone(5000)


class MetadataWriter(QThread):
    written = Signal(str, bool, str)  # item.key, ok, message
    idle_changed = Signal(bool)

    def __init__(self, pool):
        super().__init__()
        self.pool = pool
        self.sidecars_only = False
        self._jobs = collections.OrderedDict()  # key -> (item, meta)
        self._busy = None
        self._cond = threading.Condition()
        self._stop = False

    def enqueue(self, item, meta):
        with self._cond:
            self._jobs[item.key] = (item, meta)
            self._jobs.move_to_end(item.key)
            self._cond.notify_all()
        self.idle_changed.emit(False)

    def is_pending(self, key):
        with self._cond:
            return key in self._jobs or self._busy == key

    def pending_count(self):
        with self._cond:
            return len(self._jobs) + (1 if self._busy else 0)

    def flush(self, timeout=60):
        """Waits until all write jobs are done. False on timeout."""
        with self._cond:
            return self._cond.wait_for(lambda: not self._jobs and self._busy is None, timeout)

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        self.wait(10000)

    def run(self):
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._jobs or self._stop)
                if self._stop and not self._jobs:
                    return
                key, (item, meta) = self._jobs.popitem(last=False)
                self._busy = key
            ok, message = True, ''
            try:
                metadata.write_item(self.pool.get(), item, meta, self.sidecars_only)
            except Exception as e:
                ok, message = False, str(e)
                logger.warning('Schreiben fehlgeschlagen: %s', e)
            with self._cond:
                self._busy = None
                idle = not self._jobs
                self._cond.notify_all()
            self.written.emit(key, ok, message)
            if idle:
                self.idle_changed.emit(True)


class RosterWorker(QThread):
    loaded = Signal(object)

    def __init__(self, loader, sources, force=False):
        super().__init__()
        self.loader = loader
        self.sources = sources
        self.force = force

    def run(self):
        self.loaded.emit(self.loader.load(self.sources, self.force))
