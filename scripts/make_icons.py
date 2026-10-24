"""
Generates all icons from captioner/resources/logo.svg:

    captioner/resources/logo_<n>.png   window/Dock icon (QIcon with several sizes)
    captioner/resources/captioner.icns macOS app (PyInstaller --icon)
    captioner/resources/captioner.ico  Windows app

Run: make icons (needs macOS for iconutil; .png and .ico work anywhere).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

RESOURCES = Path(__file__).resolve().parent.parent / 'captioner' / 'resources'
PNG_SIZES = [16, 32, 64, 128, 256, 512]
ICONSET = {  # file name in the .iconset -> edge length
    'icon_16x16.png': 16, 'icon_16x16@2x.png': 32, 'icon_32x32.png': 32, 'icon_32x32@2x.png': 64,
    'icon_128x128.png': 128, 'icon_128x128@2x.png': 256, 'icon_256x256.png': 256,
    'icon_256x256@2x.png': 512, 'icon_512x512.png': 512, 'icon_512x512@2x.png': 1024,
}


def render(renderer, size):
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return image


def main():
    QGuiApplication(sys.argv[:1] + ['-platform', 'offscreen'])
    renderer = QSvgRenderer(str(RESOURCES / 'logo.svg'))
    if not renderer.isValid():
        sys.exit('logo.svg ist kein gueltiges SVG')

    for size in PNG_SIZES:
        render(renderer, size).save(str(RESOURCES / f'logo_{size}.png'))

    with tempfile.TemporaryDirectory() as tmp:
        big = Path(tmp) / 'logo_1024.png'
        render(renderer, 1024).save(str(big))
        Image.open(big).save(RESOURCES / 'captioner.ico',
                             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        if shutil.which('iconutil'):
            iconset = Path(tmp) / 'captioner.iconset'
            iconset.mkdir()
            for name, size in ICONSET.items():
                render(renderer, size).save(str(iconset / name))
            subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(RESOURCES / 'captioner.icns')],
                           check=True)
        else:
            print('iconutil fehlt (kein macOS): captioner.icns nicht erneuert')
    print('Icons erzeugt in', RESOURCES)


if __name__ == '__main__':
    main()
