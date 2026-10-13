# PyInstaller-Spec fuer Windows (x64, onedir). Aufruf ueber `python scripts/package_windows.py bundle`.
#
# Umgebungsvariablen (optional):
#   CAPTIONER_VERSION  Versionsnummer statt der aus pyproject.toml (setzt der Release-Workflow).
#
# Ergebnis: dist/Captioner/Captioner.exe mit ExifTool unter _internal/exiftool/ (exiftool.exe
# + exiftool_files/ mit eigenem Perl). Den Installer baut Inno Setup aus packaging/captioner.iss.
import os
import re
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = Path(SPECPATH)
VERSION = os.environ.get('CAPTIONER_VERSION') or \
    tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']

# captioner.version() liest im Bundle captioner/VERSION (Windows hat keine Info.plist)
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
    binaries=collect_dynamic_libs('c2pa'),   # libc2pa_c (Content Credentials, ADR 0002), ohne .rlib
    datas=[('vendor/exiftool-windows', 'exiftool'), ('captioner/resources', 'captioner/resources'),
           ('captioner/locale', 'captioner/locale'),   # Uebersetzungen (gettext, siehe captioner/i18n.py)
           ('LICENSE', '.'), ('licenses', 'licenses'),   # GPL und Lizenzen der gebuendelten Teile
           (str(version_file), 'captioner')],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
              'PySide6.Qt3DCore', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtPdf', 'tkinter'],
    noarchive=False,
)

# Wie auf macOS: PDF-Bildformat und Bildschirmtastatur ziehen QtQuick/QtQml/QtPdf nach,
# die die App nicht nutzt (Captioner.spec, UNUSED).
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
