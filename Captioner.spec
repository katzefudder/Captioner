# PyInstaller spec for the macOS app (arm64). Run via `make bundle`.
#
# Environment variables (optional):
#   CODESIGN_IDENTITY  "Developer ID Application: Name (TEAMID)". Without it: ad-hoc signed,
#                      runs on your own Mac, Gatekeeper blocks it on other Macs.
#   CAPTIONER_VERSION  version number instead of the one from pyproject.toml (set by the release workflow).
#
# Info.plist: version from pyproject.toml, LSMinimumSystemVersion from the binaries actually
# bundled (highest "minos" of the arm64 slices). That way the value stays right even when
# Python or PySide6 change (PySide6 6.12 requires macOS 26).
import os
import tomllib
from pathlib import Path

from macholib.MachO import MachO
from macholib.mach_o import LC_BUILD_VERSION, LC_VERSION_MIN_MACOSX

CPU_TYPE_ARM64 = 0x0100000C  # CPU_ARCH_ABI64 | CPU_TYPE_ARM, macholib has no constant for it

ROOT = Path(SPECPATH)
VERSION = os.environ.get('CAPTIONER_VERSION') or \
    tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
IDENTITY = os.environ.get('CODESIGN_IDENTITY') or None


def _minos(path):
    """Minimum macOS of the arm64 part of a Mach-O file as (major, minor), otherwise None."""
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
           ('captioner/locale', 'captioner/locale'),    # translations (gettext, see captioner/i18n.py)
           ('LICENSE', '.'), ('licenses', 'licenses'), ('docs/Captioner-Anleitung.pdf', 'docs'),
           ('docs/Captioner-Manual.pdf', 'docs')],  # GPL and licenses of the bundled parts
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
              'PySide6.Qt3DCore', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtPdf', 'tkinter'],
    noarchive=False,
)

# Two Qt plugins pull in QtQuick/QtQml/QtPdf/QtVirtualKeyboard (~19 MB), which the app
# doesn't use: PDF as an image format and the on-screen keyboard.
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
    target_arch='arm64',          # universal2 wheels are thinned to arm64
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
        # Folders and cards from Finder: drop on the Dock icon, "Open With".
        # They arrive as QFileOpenEvent (main_window.OpenRequests), one tab per folder.
        'CFBundleDocumentTypes': [{
            'CFBundleTypeName': 'Ordner',
            'CFBundleTypeRole': 'Viewer',
            'LSHandlerRank': 'Alternate',
            'LSItemContentTypes': ['public.folder', 'public.volume'],
        }],
    },
)
