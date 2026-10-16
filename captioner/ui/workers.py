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
    view = Signal(str, QImage)        # item.key, Bild der Grossansicht (Text 'stage', 'full_size')


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
    """Grossansicht: Bildschirmaufloesung (edge) oder volle Aufloesung (edge=None)."""

    def __init__(self, loader, item, edge):
        super().__init__()
        self.loader = loader
        self.item = item
        self.edge = edge

    def run(self):
        key, stage = self.item.key, 'display' if self.edge else 'full'
        try:
            # Weitergeblaettert: veraltete Auftraege nicht mehr dekodieren
            if not self.loader._view_wanted(key, stage):
                return
            image, size = previews.render_view(self.loader.pool.get(), self.item, self.edge)
            qimage = QImage(image.tobytes(), image.width, image.height, image.width * 3,
                            QImage.Format.Format_RGB888).copy()
            # Groesse des Originals: 100 % meinen Pixel des Originals, auch bei der kleineren Stufe
            qimage.setText('full_size', f'{size[0]}x{size[1]}')
            # Draft liefert hoechstens die Originalgroesse: dann ist es schon das volle Bild
            qimage.setText('stage', 'full' if (image.width, image.height) == size else stage)
            self.loader.signals.view.emit(key, qimage)
        except Exception as e:
            logger.warning('Großansicht für %s fehlgeschlagen: %s', self.item.name, e)
        finally:
            self.loader.view_pending.discard((key, stage))


def full_size(image):
    """(Breite, Hoehe) des Originals zu einem Bild der Grossansicht; ohne Angabe die eigene."""
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
    """Kacheln laden und im Speicher halten (LRU)."""
    ready = Signal(str)
    full_ready = Signal(str, QImage)
    details_ready = Signal(str, object)

    # Nach Bytes, nicht nach Anzahl: Kacheln sind seit dem Groessen-Regler groesser (previews.TILE_SIZE)
    MEMORY_BYTES = 400 * 1024 * 1024

    def __init__(self, pool, cache):
        super().__init__()
        self.pool = pool
        self.cache = cache
        self.threads = QThreadPool()
        self.threads.setMaxThreadCount(4)
        # Threads nicht ablaufen lassen: jeder neue Thread bekaeme einen neuen ExifTool-Prozess
        self.threads.setExpiryTimeout(-1)
        self.images = collections.OrderedDict()
        self.memory = 0  # Bytes in images
        self.wanted = set()
        self.pending = set()
        self.signals = _Signals()
        self.signals.ready.connect(self._on_ready)
        self.signals.details.connect(self._on_details)
        self.signals.view.connect(self._on_view)
        self.details = {}
        # Grossansicht in eigenen Threads: wartet nie hinter dem Erzeugen von Kacheln
        self.view_threads = QThreadPool()
        self.view_threads.setMaxThreadCount(2)
        self.view_threads.setExpiryTimeout(-1)
        self.display_edge = 3840       # laengste Bildschirmkante in Pixeln, setzt das Hauptfenster
        self.view_current = None       # Key des Bildes in der Grossansicht
        self.view_prefetch = set()     # Nachbarn, deren Bildschirmstufe vorbereitet wird
        self.view_pending = set()      # (key, stage)
        self.view_images = collections.OrderedDict()   # key -> QImage (beste vorhandene Stufe)

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
            self.threads.start(_ThumbnailTask(self, item, previews.TILE_SIZE))

    def request_details(self, item):
        """Kamera- und IPTC-Werte; aus dem Speicher, wenn schon gelesen."""
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

    # Grossansicht im Speicher: aktuelles Bild (voll 45 MP ~ 136 MB), Nachbarn und zuletzt gesehene
    VIEW_BYTES = 600 * 1024 * 1024

    def request_full(self, item, neighbours=()):
        """
        Grossansicht: zuerst in Bildschirmaufloesung (eingepasst sofort scharf), dann in voller
        Aufloesung fuer 100 %. Die Nachbarn werden in Bildschirmaufloesung vorbereitet.
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
            return  # nie ein volles Bild durch die kleinere Stufe ersetzen
        self.view_images[key] = image
        self.view_images.move_to_end(key)
        total = sum(kept.sizeInBytes() for kept in self.view_images.values())
        for other in list(self.view_images):   # aelteste zuerst, das aktuelle nie
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
        """Aelteste zuerst verwerfen, aber nie gerade gewuenschte (sichtbare) Kacheln."""
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
