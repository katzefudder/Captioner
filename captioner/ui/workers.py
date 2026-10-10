"""
Hintergrundarbeit. Die UI wartet nie auf eine Datei (ADR 0001, Punkt 2).

* ScanWorker: Ordner einlesen, Metadaten in Bloecken nachladen
* ThumbnailLoader: Kacheln im QThreadPool, nur fuer gewuenschte Items
* MetadataWriter: eine Schreib-Warteschlange; pro Item gewinnt der letzte Stand.
  flush() blockiert, bis alles geschrieben ist - das braucht der Drag-Start.
* RosterWorker: Roster laden (Netz) ohne die UI anzuhalten
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
    scanned = Signal(list)        # alle Items, nach Dateiname
    chunk_loaded = Signal(list)   # Items mit frisch gelesenen Metadaten
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
        # Eigene Instanz statt Pool: jeder Scan laeuft in einem neuen Thread, eine
        # Pool-Instanz bliebe danach bis zum Programmende liegen
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
    ready = Signal(str, QImage)       # item.key, Bild
    failed = Signal(str, str)
    details = Signal(str, object)     # item.key, Rohwerte fuer das Info-Panel


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


class _ThumbnailTask(QRunnable):
    def __init__(self, loader, item, size, full):
        super().__init__()
        self.loader = loader
        self.item = item
        self.size = size
        self.full = full

    def run(self):
        key = self.item.key
        if not self.full and key not in self.loader.wanted:
            self.loader.pending.discard(key)
            return
        try:
            tool = self.loader.pool.get()
            if self.full:
                image = previews.render(tool, self.item, None)
                data = None
            else:
                data = self.loader.cache.tile(tool, self.item, self.size)
            qimage = QImage()
            if data is not None:
                qimage.loadFromData(data, 'JPEG')
            else:
                rgb = image.convert('RGB')
                qimage = QImage(rgb.tobytes(), rgb.width, rgb.height, rgb.width * 3,
                                QImage.Format.Format_RGB888).copy()
            self.loader.signals.ready.emit(('full:' if self.full else '') + key, qimage)
        except Exception as e:
            logger.warning('Vorschau fuer %s fehlgeschlagen: %s', self.item.name, e)
            self.loader.signals.failed.emit(key, str(e))
        finally:
            self.loader.pending.discard(key)


class ThumbnailLoader(QObject):
    """Kacheln laden und im Speicher halten (LRU)."""
    ready = Signal(str)
    full_ready = Signal(str, QImage)
    details_ready = Signal(str, object)

    MEMORY_LIMIT = 500

    def __init__(self, pool, cache):
        super().__init__()
        self.pool = pool
        self.cache = cache
        self.threads = QThreadPool()
        self.threads.setMaxThreadCount(4)
        # Threads nicht ablaufen lassen: jeder neue Thread bekaeme einen neuen ExifTool-Prozess
        self.threads.setExpiryTimeout(-1)
        self.images = collections.OrderedDict()
        self.wanted = set()
        self.pending = set()
        self.signals = _Signals()
        self.signals.ready.connect(self._on_ready)
        self.signals.details.connect(self._on_details)
        self.details = {}

    def image(self, key):
        image = self.images.get(key)
        if image is not None:
            self.images.move_to_end(key)
        return image

    def request(self, items):
        """Nur diese Items sind gewuenscht; alte, noch wartende Auftraege verfallen."""
        self.wanted = {item.key for item in items}
        for item in items:
            if item.key in self.images or item.key in self.pending:
                continue
            self.pending.add(item.key)
            self.threads.start(_ThumbnailTask(self, item, previews.TILE_SIZE, False))

    def request_details(self, item):
        """Kamera- und IPTC-Werte; aus dem Speicher, wenn schon gelesen."""
        if item.key in self.details:
            self.details_ready.emit(item.key, self.details[item.key])
            return
        self.threads.start(_DetailsTask(self, item), priority=5)

    def invalidate_details(self, key):
        self.details.pop(key, None)

    def _on_details(self, key, data):
        if '_error' not in data:
            self.details[key] = data
        self.details_ready.emit(key, data)

    def request_full(self, item):
        self.threads.start(_ThumbnailTask(self, item, None, True), priority=10)

    def invalidate(self, key):
        self.images.pop(key, None)

    def _on_ready(self, key, image):
        if key.startswith('full:'):
            self.full_ready.emit(key[5:], image)
            return
        self.images[key] = image
        self.images.move_to_end(key)
        while len(self.images) > self.MEMORY_LIMIT:
            self.images.popitem(last=False)
        self.ready.emit(key)

    def shutdown(self):
        self.wanted = set()
        self.threads.clear()
        self.threads.waitForDone(5000)


class MetadataWriter(QThread):
    written = Signal(str, bool, str)  # item.key, ok, Meldung
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
        """Wartet, bis alle Schreibauftraege erledigt sind. False bei Zeitueberschreitung."""
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
