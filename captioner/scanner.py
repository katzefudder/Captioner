"""
Ordner einlesen: Bilddateien finden, RAW+JPG-Paare und vorhandene Sidecars zuordnen.

Ein "Item" ist eine Kachel in der Galerie. Bei RAW+JPG mit gleichem Basisnamen
sind das beide Dateien (ADR 0001, Punkt 2).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

JPEG_EXTENSIONS = {'.jpg', '.jpeg'}
# Formate, bei denen Metadaten eingebettet werden, nicht im Sidecar (ADR 0001, Punkt 4)
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
    rating: int = 0
    label: str = ''
    # Farbklasse 1-8 (XMP-photomech:ColorClass) und Tag (XMP-photomech:Tagged),
    # wie sie ein Workflow-Tool fuer die Auswahl von Fotos schreibt. Die Farbklasse wird zusaetzlich als xmp:Label
    # geschrieben, weil Lightroom nur das Label kennt.
    color_class: int = 0
    tagged: bool = False
    # GPS mit Vorzeichen (Sued/West negativ), aus Sidecar, eingebettet oder RAW.
    # gps_changed: von Captioner gesetzt (geo.apply_gps), muss geschrieben werden;
    # sonst wird GPS nie angefasst, Kamera-GPS bleibt, wie es ist.
    latitude: float = None
    longitude: float = None
    gps_changed: bool = False

    @property
    def is_captioned(self):
        return bool(self.caption.strip())


@dataclass(eq=False)
class Item:
    key: str                  # Verzeichnis + Basisname, kleingeschrieben
    raw: Path = None          # proprietaere RAW-Datei
    embedded: list = field(default_factory=list)  # JPG/DNG/TIFF mit gleichem Basisnamen
    sidecar: Path = None      # vorhandenes <basis>.xmp (Schreibweise wie auf der Platte)
    taken_at: str = ''        # DateTimeOriginal + SubSec, sortierbar
    orientation: int = 1
    meta: Metadata = field(default_factory=Metadata)
    meta_loaded: bool = False
    error: str = None         # letzter Schreibfehler

    @property
    def name(self):
        return self.primary.name

    @property
    def primary(self) -> Path:
        """Die Datei, deren Vorschau gezeigt wird: JPG vor RAW, weil schneller."""
        for path in self.embedded:
            if path.suffix.lower() in JPEG_EXTENSIONS:
                return path
        return self.raw or self.embedded[0]

    @property
    def files(self):
        return ([self.raw] if self.raw else []) + list(self.embedded)

    @property
    def sidecar_target(self) -> Path:
        """Wohin das Sidecar geschrieben wird: vorhandene Datei oder <basis>.xmp."""
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


def has_images(folder):
    """Liegt direkt in diesem Ordner mindestens eine Bilddatei?"""
    try:
        with os.scandir(folder) as entries:
            return any(not e.name.startswith('.') and e.is_file()
                       and os.path.splitext(e.name)[1].lower() in IMAGE_EXTENSIONS for e in entries)
    except OSError:
        return False


def image_folders(root, max_depth=3):
    """
    Ordner mit Bildern unter root: root selbst, wenn es Bilder enthaelt, sonst die
    Unterordner mit Bildern (z. B. Karte -> DCIM/100NCZ_9, DCIM/101NCZ_9), sortiert.
    Versteckte Ordner (.Trashes, .Spotlight-V100) werden uebersprungen.
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
    """Nach Aufnahmezeit inkl. Subsekunden; ohne Zeit ans Ende, dann nach Name."""
    items.sort(key=lambda i: (i.taken_at == '', i.taken_at, i.name.lower()))
