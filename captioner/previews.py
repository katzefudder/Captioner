"""
Previews from the files, without RAW development (ADR 0001, item 2).

* JPG: Pillow draft() decodes straight to 1/2..1/8 of the resolution; for tiles that is
  faster and sharper than the 160 px EXIF thumbnail.
* RAW/DNG: the matching embedded JPEG via ExifTool.

The orientation is read here from the file whose preview is shown - not from
item.orientation. Tiles are requested before the scan has read the metadata; with the
default 1 an unrotated tile would otherwise end up in the disk cache for good. Embedded
previews are often not rotated.
Results go into a disk cache (path + size + mtime).
"""
import hashlib
import io
import math
from pathlib import Path

from PIL import Image

from .scanner import Item, JPEG_EXTENSIONS

TILE_SIZE = 512  # big enough for the largest tiles (slider) on Retina
# increase when the rendering changes; old tiles in the disk cache then expire
CACHE_VERSION = 2

# order: smallest usable first for tiles, largest for the preview
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
    """First embedded JPEG from tags that reaches min_edge (otherwise the largest)."""
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
    records = tool.json('-n', '-fast2', '-Orientation', str(path))  # IFD0 is enough, no makernotes needed
    try:
        return int(records[0].get('Orientation') or 1) if records else 1
    except (TypeError, ValueError):
        return 1


def render_view(tool, item: Item, min_edge=None):
    """
    Preview: (PIL image, (width, height) of the original, oriented).

    With min_edge the JPEG is decoded downscaled in draft mode (1/2, 1/4, 1/8 directly
    while decompressing), but never below min_edge: fitted it is as sharp as at full size,
    two to three times faster at 45 MP. Without min_edge: full resolution for 100 %.
    """
    path = item.primary
    if path.suffix.lower() in JPEG_EXTENSIONS:
        source = path
    else:
        source = _embedded_jpeg(tool, path, FULL_TAGS, 10 ** 6)
    if source is None:
        image = Image.open(path).convert('RGB')  # TIFF/some DNGs: no embedded JPEG
        size = image.size
    else:
        image = Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)
        size = image.size
        if min_edge and max(size) > min_edge:
            scale = min_edge / max(size)
            image.draft('RGB', (math.ceil(size[0] * scale), math.ceil(size[1] * scale)))
        image = image.convert('RGB')
    orientation = orientation_of(tool, path)
    if orientation in (5, 6, 7, 8):
        size = (size[1], size[0])
    return orient(image, orientation), size


def render(tool, item: Item, max_edge):
    """PIL image for the tile (max_edge) or the preview (max_edge=None)."""
    path = item.primary
    if path.suffix.lower() in JPEG_EXTENSIONS:
        image = _open_jpeg(path, max_edge)
    else:
        tags = TILE_TAGS if max_edge else FULL_TAGS
        data = _embedded_jpeg(tool, path, tags, max_edge or 10 ** 6)
        if data is None:
            # last resort: Pillow can read TIFF/some DNGs directly
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
        """JPEG bytes of the tile, from the cache or freshly made."""
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
