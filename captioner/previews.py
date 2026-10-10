"""
Vorschauen aus den Dateien, ohne RAW-Entwicklung (ADR 0001, Punkt 2).

* JPG: Pillow draft() dekodiert direkt in 1/2..1/8 der Aufloesung, das ist fuer
  Kacheln schneller und schaerfer als das 160-px-EXIF-Thumbnail.
* RAW/DNG: das passende eingebettete JPEG per ExifTool.

Die Ausrichtung wird hier aus der Datei gelesen, deren Vorschau gezeigt wird -
nicht aus item.orientation. Kacheln werden angefordert, bevor der Scan die
Metadaten gelesen hat; mit dem Default 1 landete sonst eine ungedrehte Kachel
dauerhaft im Plattencache. Eingebettete Vorschauen sind oft nicht gedreht.
Ergebnisse landen in einem Plattencache (Pfad + Groesse + mtime).
"""
import hashlib
import io
from pathlib import Path

from PIL import Image

from .scanner import Item, JPEG_EXTENSIONS

TILE_SIZE = 320
# Erhoehen, wenn sich die Darstellung aendert; alte Kacheln im Plattencache verfallen dann
CACHE_VERSION = 2

# Reihenfolge: kleinste brauchbare zuerst fuer Kacheln, groesste fuer die Grossansicht
TILE_TAGS = ['PreviewImage', 'OtherImage', 'JpgFromRaw', 'ThumbnailImage']
FULL_TAGS = ['JpgFromRaw', 'OtherImage', 'PreviewImage', 'ThumbnailImage']
MIN_TILE_EDGE = 300

ORIENTATION_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def cache_key(path: Path, size):
    stat = path.stat()
    raw = f'{CACHE_VERSION}|{path}|{stat.st_size}|{stat.st_mtime_ns}|{size}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def orient(image, orientation):
    transpose = ORIENTATION_TRANSPOSE.get(orientation)
    return image.transpose(transpose) if transpose else image


def _open_jpeg(data_or_path, max_edge):
    image = Image.open(io.BytesIO(data_or_path) if isinstance(data_or_path, bytes) else data_or_path)
    if max_edge:
        image.draft('RGB', (max_edge, max_edge))
    image = image.convert('RGB')
    if max_edge:
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return image


def _embedded_jpeg(tool, path, tags, min_edge):
    """Erstes eingebettetes JPEG aus tags, das min_edge erreicht (sonst das groesste)."""
    best = None
    for tag in tags:
        data = tool.binary(tag, path)
        if not data or not data.startswith(b'\xff\xd8'):
            continue
        try:
            with Image.open(io.BytesIO(data)) as probe:
                edge = max(probe.size)
        except Exception:
            continue
        if edge >= min_edge:
            return data
        if best is None or edge > best[0]:
            best = (edge, data)
    return best[1] if best else None


def orientation_of(tool, path):
    records = tool.json('-n', '-Orientation', str(path))
    try:
        return int(records[0].get('Orientation') or 1) if records else 1
    except (TypeError, ValueError):
        return 1


def render(tool, item: Item, max_edge):
    """PIL-Image fuer die Kachel (max_edge) bzw. Grossansicht (max_edge=None)."""
    path = item.primary
    if path.suffix.lower() in JPEG_EXTENSIONS:
        image = _open_jpeg(path, max_edge)
    else:
        tags = TILE_TAGS if max_edge else FULL_TAGS
        data = _embedded_jpeg(tool, path, tags, max_edge or 10 ** 6)
        if data is None:
            # Letzter Versuch: Pillow kann TIFF/manche DNGs direkt lesen
            image = Image.open(path).convert('RGB')
            if max_edge:
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        else:
            image = _open_jpeg(data, max_edge)
    return orient(image, orientation_of(tool, path))


class PreviewCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory) / 'previews'
        self.directory.mkdir(parents=True, exist_ok=True)

    def tile(self, tool, item: Item, size=TILE_SIZE):
        """JPEG-Bytes der Kachel, aus dem Cache oder frisch erzeugt."""
        key = cache_key(item.primary, size)
        cached = self.directory / key[:2] / f'{key}.jpg'
        if cached.exists():
            return cached.read_bytes()
        image = render(tool, item, size)
        buffer = io.BytesIO()
        image.save(buffer, 'JPEG', quality=85)
        data = buffer.getvalue()
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
        return data
