# PyInstaller spec for Windows (x64, onedir). Run via `python scripts/package_windows.py bundle`.
#
# Environment variables (optional):
#   CAPTIONER_VERSION  version number instead of the one from pyproject.toml (set by the release workflow).
#
# Result: dist/Captioner/Captioner.exe with ExifTool under _internal/exiftool/ (exiftool.exe
# + exiftool_files/ with its own Perl). Inno Setup builds the installer from packaging/captioner.iss.
import os
import re
import tomllib
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = Path(SPECPATH)
VERSION = os.environ.get('CAPTIONER_VERSION') or \
    tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']

# captioner.version() reads captioner/VERSION in the bundle (Windows has no Info.plist)
version_file = ROOT / 'build' / 'windows' / 'VERSION'
version_file.parent.mkdir(parents=True, exist_ok=True)
version_file.write_text(VERSION, encoding='utf-8')

numbers = tuple(int(n) for n in re.findall(r'\d+', VERSION)[:4])
numbers += (0,) * (4 - len(numbers))
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([StringTable('040704B0', [
            StringStruct('CompanyName', 'Florian Dehn'),
            StringStruct('FileDescription', 'Captioner'),
            StringStruct('FileVersion', VERSION),
            StringStruct('InternalName', 'Captioner'),
            StringStruct('LegalCopyright', 'Florian Dehn'),
            StringStruct('OriginalFilename', 'Captioner.exe'),
            StringStruct('ProductName', 'Captioner'),
            StringStruct('ProductVersion', VERSION),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0407, 1200])]),
    ],
)

a = Analysis(
    ['run_captioner.py'],
    pathex=[],
    binaries=[],
    datas=[('vendor/exiftool-windows', 'exiftool'), ('captioner/resources', 'captioner/resources'),
           ('captioner/locale', 'captioner/locale'),   # translations (gettext, see captioner/i18n.py)
           ('LICENSE', '.'), ('licenses', 'licenses'), ('docs/Captioner-Anleitung.pdf', 'docs'),
           ('docs/Captioner-Manual.pdf', 'docs'),   # GPL and licenses of the bundled parts
           (str(version_file), 'captioner')],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
              'PySide6.Qt3DCore', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtPdf', 'tkinter'],
    noarchive=False,
)

# As on macOS: the PDF image format and the on-screen keyboard pull in QtQuick/QtQml/QtPdf,
# which the app doesn't use (Captioner.spec, UNUSED).
UNUSED = ('qpdf.dll', 'qtvirtualkeyboardplugin.dll', 'Qt6Quick', 'Qt6Qml', 'Qt6VirtualKeyboard', 'Qt6Pdf')
a.binaries = [entry for entry in a.binaries if not any(name.lower() in entry[0].lower() for name in UNUSED)]
a.datas = [entry for entry in a.datas if not any(name.lower() in entry[0].lower() for name in UNUSED)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='Captioner',
    console=False,
    icon='captioner/resources/captioner.ico',
    version=version_info,
)
coll = COLLECT(exe, a.binaries, a.datas, name='Captioner')
