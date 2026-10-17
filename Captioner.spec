# PyInstaller-Spec fuer die macOS-App (arm64). Aufruf ueber `make bundle`.
#
# Umgebungsvariablen (optional):
#   CODESIGN_IDENTITY  "Developer ID Application: Name (TEAMID)". Ohne: ad-hoc signiert,
#                      laeuft auf dem eigenen Mac, auf fremden Macs blockt Gatekeeper.
#   CAPTIONER_VERSION  Versionsnummer statt der aus pyproject.toml (setzt der Release-Workflow).
#
# Info.plist: Version aus pyproject.toml, LSMinimumSystemVersion aus den tatsaechlich
# gebuendelten Binaries (hoechstes "minos" der arm64-Slices). Damit stimmt die Angabe
# auch, wenn sich Python oder PySide6 aendern (PySide6 6.12 verlangt macOS 26).
import os
import tomllib
from pathlib import Path

from macholib.MachO import MachO
from macholib.mach_o import LC_BUILD_VERSION, LC_VERSION_MIN_MACOSX

CPU_TYPE_ARM64 = 0x0100000C  # CPU_ARCH_ABI64 | CPU_TYPE_ARM, macholib hat keine Konstante dafuer

ROOT = Path(SPECPATH)
VERSION = os.environ.get('CAPTIONER_VERSION') or \
    tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
IDENTITY = os.environ.get('CODESIGN_IDENTITY') or None


def _minos(path):
    """Mindest-macOS des arm64-Teils einer Mach-O-Datei als (major, minor), sonst None."""
    try:
        macho = MachO(path)
    except Exception:
        return None
    for header in macho.headers:
        if header.header.cputype != CPU_TYPE_ARM64:
            continue
        for load_command, command, _ in header.commands:
            if load_command.cmd == LC_BUILD_VERSION:
                return command.minos >> 16, (command.minos >> 8) & 0xFF
            if load_command.cmd == LC_VERSION_MIN_MACOSX:
                return command.version >> 16, (command.version >> 8) & 0xFF
    return None


a = Analysis(
    ['run_captioner.py'],
    pathex=[],
    binaries=[],
    datas=[('vendor/exiftool', 'exiftool'), ('captioner/resources', 'captioner/resources'),
           ('captioner/locale', 'captioner/locale'),    # Uebersetzungen (gettext, siehe captioner/i18n.py)
           ('LICENSE', '.'), ('licenses', 'licenses'), ('docs/Captioner-Anleitung.pdf', 'docs')],  # GPL und Lizenzen der gebuendelten Teile
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
              'PySide6.Qt3DCore', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtPdf', 'tkinter'],
    noarchive=False,
)

# Zwei Qt-Plugins ziehen QtQuick/QtQml/QtPdf/QtVirtualKeyboard (~19 MB) nach, die
# die App nicht nutzt: PDF als Bildformat und die Bildschirmtastatur.
UNUSED = ('libqpdf.dylib', 'libqtvirtualkeyboardplugin.dylib', 'QtQuick', 'QtQml',
          'QtVirtualKeyboard', 'QtPdf')
a.binaries = [entry for entry in a.binaries if not any(name in entry[0] for name in UNUSED)]
a.datas = [entry for entry in a.datas if not any(name in entry[0] for name in UNUSED)]

versions = [v for v in (_minos(src) for _, src, _ in a.binaries) if v]
MIN_MACOS = '.'.join(str(n) for n in max(versions, default=(11, 0)))
print(f'Captioner {VERSION}: LSMinimumSystemVersion {MIN_MACOS} (aus {len(versions)} Binaries)')

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='Captioner',
    console=False,
    target_arch='arm64',          # universal2-Wheels werden auf arm64 ausgeduennt
    codesign_identity=IDENTITY,
    entitlements_file=str(ROOT / 'packaging' / 'entitlements.plist'),
)
coll = COLLECT(exe, a.binaries, a.datas, name='Captioner')
app = BUNDLE(
    coll,
    name='Captioner.app',
    icon='captioner/resources/captioner.icns',
    bundle_identifier='de.chuc.captioner',
    version=VERSION,
    info_plist={
        'CFBundleName': 'Captioner',
        'CFBundleDisplayName': 'Captioner',
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': VERSION,
        'LSMinimumSystemVersion': MIN_MACOS,
        'LSArchitecturePriority': ['arm64'],
        'LSApplicationCategoryType': 'public.app-category.photography',
        'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': 'Florian Dehn',
        'CFBundleDevelopmentRegion': 'de',
        # Ordner und Karten aus dem Finder: aufs Dock-Symbol ziehen, "Oeffnen mit".
        # Kommen als QFileOpenEvent an (main_window.OpenRequests), je Ordner ein Tab.
        'CFBundleDocumentTypes': [{
            'CFBundleTypeName': 'Ordner',
            'CFBundleTypeRole': 'Viewer',
            'LSHandlerRank': 'Alternate',
            'LSItemContentTypes': ['public.folder', 'public.volume'],
        }],
    },
)
