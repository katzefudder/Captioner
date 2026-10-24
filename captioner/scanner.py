"""
Read a folder: find image files, pair up RAW+JPG and assign existing sidecars.

An "Item" is a tile in the gallery. For RAW+JPG with the same base name that is
both files (ADR 0001, item 2).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

JPEG_EXTENSIONS = {'.jpg', '.jpeg'}
# formats whose metadata is embedded, not written to a sidecar (ADR 0001, item 4)
EMBEDDED_EXTENSIONS = JPEG_EXTENSIONS | {'.dng', '.tif', '.tiff'}
RAW_EXTENSIONS = {'.nef', '.nrw', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.sr2', '.raf',
                  '.orf', '.rw2', '.pef', '.srw', '.3fr', '.iiq', '.rwl', '.erf', '.mrw', '.x3f'}
IMAGE_EXTENSIONS = EMBEDDED_EXTENSIONS | RAW_EXTENSIONS


@dataclass
class Metadata:
    headline: str = ''
    caption: str = ''
    keywords: list = field(default_factory=list)
    city: str = ''
    sublocation: str = ''
    state: str = ''              # state/province (photoshop:State / IPTC Province-State)
    country: str = ''            # photoshop:Country / IPTC Country-PrimaryLocationName
    country_code: str = ''       # Iptc4xmpCore:CountryCode / IPTC Country-PrimaryLocationCode ("DEU")
    # creator and rights (see metadata.RIGHTS_TAGS)
    creator: str = ''            # dc:creator / IPTC By-line / EXIF Artist
    contact_email: str = ''      # Iptc4xmpCore:CreatorContactInfo/CiEmailWork (Lightroom: contact email)
    authors_position: str = ''   # photoshop:AuthorsPosition / IPTC By-lineTitle
    credit: str = ''             # photoshop:Credit / IPTC Credit ("credit line")
    caption_writer: str = ''     # photoshop:CaptionWriter / IPTC Writer-Editor
    copyright: str = ''          # dc:rights / IPTC CopyrightNotice / EXIF Copyright
    web_statement: str = ''      # xmpRights:WebStatement (URL of the terms of use)
    source: str = ''             # photoshop:Source / IPTC Source
    category: str = ''           # photoshop:Category ("Sport"); IPTC Category only up to 3 characters
    instructions: str = ''       # photoshop:Instructions / IPTC SpecialInstructions (contact, bank account)
    rating: int = 0
    label: str = ''
    # Color class 1-8 (XMP-photomech:ColorClass) and tag (XMP-photomech:Tagged), as a photo
    # culling workflow tool writes them. The color class is also written as xmp:Label,
    # because Lightroom only knows the label.
    color_class: int = 0
    tagged: bool = False
    # GPS with sign (south/west negative), from sidecar, embedded or RAW.
    # gps_changed: set by Captioner (geo.apply_gps), must be written;
    # otherwise GPS is never touched, camera GPS stays as it is.
    latitude: float = None
    longitude: float = None
    gps_changed: bool = False

    @property
    def is_captioned(self):
        return bool(self.caption.strip())


@dataclass(eq=False)
class Item:
    key: str                  # directory + base name, lower case
    raw: Path = None          # proprietary RAW file
    embedded: list = field(default_factory=list)  # JPG/DNG/TIFF with the same base name
    sidecar: Path = None      # existing <base>.xmp (spelled as on disk)
    taken_at: str = ''        # DateTimeOriginal + SubSec, sortable
    orientation: int = 1
    camera: str = ''          # model, e.g. "NIKON Z 9"
    serial: str = ''          # serial number: tells two bodies of the same model apart
    meta: Metadata = field(default_factory=Metadata)
    meta_loaded: bool = False
    error: str = None         # last write error

    @property
    def name(self):
        return self.primary.name

    @property
    def primary(self) -> Path:
        """The file whose preview is shown: JPG before RAW, because it is faster."""
        for path in self.embedded:
            if path.suffix.lower() in JPEG_EXTENSIONS:
                return path
        return self.raw or self.embedded[0]

    @property
    def files(self):
        return ([self.raw] if self.raw else []) + list(self.embedded)

    @property
    def sidecar_target(self) -> Path:
        """Where the sidecar is written: existing file or <base>.xmp."""
        if self.sidecar:
            return self.sidecar
        return self.raw.with_suffix('.xmp') if self.raw else None

    @property
    def kind(self):
        exts = [p.suffix.upper().lstrip('.') for p in self.files]
        return '+'.join(exts)


def scan(folder, recursive=False):
    folder = Path(folder)
    groups = {}
    sidecars = {}

    def visit(directory):
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith('.'):
                continue
            if entry.is_dir(follow_symlinks=False):
                if recursive:
                    visit(entry.path)
                continue
            path = Path(entry.path)
            ext = path.suffix.lower()
            key = str(path.with_suffix('')).lower()
            if ext == '.xmp':
                sidecars[key] = path
            elif ext in IMAGE_EXTENSIONS:
                item = groups.setdefault(key, Item(key=key))
                if ext in RAW_EXTENSIONS:
                    item.raw = path
                else:
                    item.embedded.append(path)

    visit(folder)
    items = list(groups.values())
    for item in items:
        item.embedded.sort(key=lambda p: (p.suffix.lower() not in JPEG_EXTENSIONS, p.name))
        if item.raw:
            item.sidecar = sidecars.get(item.key)
    items.sort(key=lambda i: i.name.lower())
    return items


def camera_labels(items):
    """
    (model, serial number) -> label. With two bodies of the same model, with the last
    digits of the serial number, otherwise just the model.
    """
    keys = sorted({(item.camera, item.serial) for item in items if item.camera})
    models = [model for model, _serial in keys]
    labels = {}
    for model, serial in keys:
        if models.count(model) > 1 and serial:
            labels[(model, serial)] = f'{model} · …{serial[-4:]}'
        else:
            labels[(model, serial)] = model
    return labels


def matches_text(item, query):
    """All words of the search occur in the file name or the caption (case-insensitive)."""
    terms = query.casefold().split()
    if not terms:
        return True
    meta = item.meta
    haystack = ' '.join([item.name, meta.headline, meta.caption, ' '.join(meta.keywords),
                         meta.city, meta.sublocation]).casefold()
    return all(term in haystack for term in terms)


def time_of_day(item):
    """'HH:MM' of the capture, '' if unknown."""
    return item.taken_at[11:16] if len(item.taken_at) >= 16 else ''


def has_images(folder):
    """Is there at least one image file directly in this folder?"""
    try:
        with os.scandir(folder) as entries:
            return any(not e.name.startswith('.') and e.is_file()
                       and os.path.splitext(e.name)[1].lower() in IMAGE_EXTENSIONS for e in entries)
    except OSError:
        return False


def image_folders(root, max_depth=3):
    """
    Folders with images below root: root itself if it contains images, otherwise the
    subfolders with images (e.g. card -> DCIM/100NCZ_9, DCIM/101NCZ_9), sorted.
    Hidden folders (.Trashes, .Spotlight-V100) are skipped.
    """
    root = Path(root)
    if has_images(root):
        return [root]
    found = []

    def walk(directory, depth):
        if depth > max_depth:
            return
        try:
            with os.scandir(directory) as entries:
                subdirs = sorted((e.path for e in entries if e.is_dir() and not e.name.startswith('.')),
                                 key=str.casefold)
        except OSError:
            return
        for path in subdirs:
            if has_images(path):
                found.append(Path(path))
            else:
                walk(path, depth + 1)

    walk(root, 1)
    return found


def sort_items(items):
    """By capture time including subseconds; without a time at the end, then by name."""
    items.sort(key=lambda i: (i.taken_at == '', i.taken_at, i.name.lower()))
