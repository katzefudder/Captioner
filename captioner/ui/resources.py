"""Logo und Icons aus captioner/resources (erzeugt mit `make icons` aus logo.svg)."""
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

RESOURCES = Path(__file__).resolve().parent.parent / 'resources'
ICON_SIZES = [16, 32, 64, 128, 256, 512]


def app_icon():
    icon = QIcon()
    for size in ICON_SIZES:
        path = RESOURCES / f'logo_{size}.png'
        if path.exists():
            icon.addFile(str(path))
    return icon


def logo_pixmap(size):
    """Logo in passender Groesse; nimmt die naechstgroessere PNG und skaliert herunter."""
    for candidate in ICON_SIZES:
        if candidate >= size:
            break
    pixmap = QPixmap(str(RESOURCES / f'logo_{candidate}.png'))
    return pixmap
