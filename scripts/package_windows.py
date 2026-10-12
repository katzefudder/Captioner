"""
Windows-Version (x64): ExifTool holen, App bauen, pruefen, Installer erzeugen.

    python scripts/package_windows.py exiftool    ExifTool fuer Windows nach vendor/exiftool-windows
    python scripts/package_windows.py bundle      dist/Captioner/ (PyInstaller, Captioner-windows.spec)
    python scripts/package_windows.py verify      Bundle pruefen: Exe, ExifTool laeuft, Version
    python scripts/package_windows.py installer   dist/Captioner-<version>-x64-setup.exe (Inno Setup)
    python scripts/package_windows.py all         alles der Reihe nach

Statt Makefile, weil auf Windows kein make vorausgesetzt wird. Aufruf mit dem Python
der Poetry-Umgebung (`poetry run python scripts/package_windows.py all`).

Umgebungsvariablen:
    CAPTIONER_VERSION  Versionsnummer (setzt der Release-Workflow), sonst pyproject.toml
    ISCC               Pfad zu ISCC.exe, sonst PATH bzw. der Standard-Installationsort
Unsigniert: Windows SmartScreen warnt beim ersten Start (siehe BACKLOG.md, Code-Signing).
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
APP = DIST / 'Captioner'
EXIFTOOL_DIR = ROOT / 'vendor' / 'exiftool-windows'

# Wie im Makefile: Version und Pruefsumme fest (exiftool.org/checksums.txt)
EXIFTOOL_VERSION = '13.59'
EXIFTOOL_SHA256 = '44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec'
EXIFTOOL_URL = f'https://sourceforge.net/projects/exiftool/files/exiftool-{EXIFTOOL_VERSION}_64.zip/download'


def run(*args, **kwargs):
    print('$', ' '.join(str(a) for a in args), flush=True)
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def version():
    return os.environ.get('CAPTIONER_VERSION') or \
        tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']


def exiftool():
    """exiftool.exe + exiftool_files/ (eigenes Perl) aus dem offiziellen Windows-Paket."""
    exe = EXIFTOOL_DIR / 'exiftool.exe'
    if exe.exists() and (EXIFTOOL_DIR / 'VERSION').read_text().strip() == EXIFTOOL_VERSION:
        print(f'ExifTool {EXIFTOOL_VERSION} schon da: {exe}')
        return exe
    shutil.rmtree(EXIFTOOL_DIR, ignore_errors=True)
    EXIFTOOL_DIR.parent.mkdir(parents=True, exist_ok=True)
    archive = EXIFTOOL_DIR.parent / f'exiftool-{EXIFTOOL_VERSION}_64.zip'
    print(f'Lade {EXIFTOOL_URL}', flush=True)
    request = urllib.request.Request(EXIFTOOL_URL, headers={'User-Agent': 'curl/8'})  # SourceForge leitet sonst auf HTML
    with urllib.request.urlopen(request, timeout=120) as response, open(archive, 'wb') as handle:
        shutil.copyfileobj(response, handle)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != EXIFTOOL_SHA256:
        archive.unlink()
        sys.exit(f'Pruefsumme falsch: {digest}, erwartet {EXIFTOOL_SHA256}')
    top = f'exiftool-{EXIFTOOL_VERSION}_64/'
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if not info.filename.startswith(top) or info.is_dir():
                continue
            relative = info.filename[len(top):]
            # "exiftool(-k).exe" wartet am Ende auf eine Taste; umbenannt nicht mehr
            if relative == 'exiftool(-k).exe':
                relative = 'exiftool.exe'
            target = EXIFTOOL_DIR / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, open(target, 'wb') as handle:
                shutil.copyfileobj(source, handle)
    archive.unlink()
    if not exe.exists():
        sys.exit(f'{exe} fehlt nach dem Entpacken')
    (EXIFTOOL_DIR / 'VERSION').write_text(EXIFTOOL_VERSION)
    print(f'ExifTool {EXIFTOOL_VERSION} nach {EXIFTOOL_DIR}')
    return exe


def bundle():
    exiftool()
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', ROOT / 'Captioner-windows.spec', cwd=ROOT)
    verify()


def verify():
    exe = APP / 'Captioner.exe'
    problems = []
    if not exe.exists():
        sys.exit(f'{exe} fehlt - erst `bundle`')
    internal = APP / '_internal'
    bundled_exiftool = internal / 'exiftool' / 'exiftool.exe'
    if not bundled_exiftool.exists():
        problems.append('ExifTool fehlt im Bundle')
    else:
        result = subprocess.run([str(bundled_exiftool), '-ver'], capture_output=True, text=True, timeout=60,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.stdout.strip() != EXIFTOOL_VERSION:
            problems.append(f'ExifTool im Bundle meldet {result.stdout.strip()!r}: {result.stderr.strip()}')
    bundled_version = internal / 'captioner' / 'VERSION'
    if not bundled_version.exists() or bundled_version.read_text().strip() != version():
        problems.append(f'captioner/VERSION fehlt oder passt nicht zu {version()}')
    if not (internal / 'captioner' / 'locale' / 'en' / 'LC_MESSAGES' / 'captioner.mo').exists():
        problems.append('Englische Uebersetzung fehlt')
    unused = [p.name for p in internal.rglob('*') if p.name.lower().startswith(('qt6quick', 'qt6qml', 'qt6pdf'))]
    if unused:
        problems.append(f'Unnoetige Qt-Teile gebuendelt: {", ".join(sorted(unused)[:5])}')
    size = sum(p.stat().st_size for p in APP.rglob('*') if p.is_file()) / 1e6
    print(f'Captioner {version()} unter {APP}, {size:.0f} MB')
    if problems:
        sys.exit('\n'.join('FEHLER: ' + p for p in problems))
    print('OK')


def find_iscc():
    candidates = [os.environ.get('ISCC'), shutil.which('ISCC'), shutil.which('iscc')]
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'),
                 str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs')):
        if base:
            candidates.append(str(Path(base) / 'Inno Setup 6' / 'ISCC.exe'))
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit('Inno Setup (ISCC.exe) nicht gefunden: `choco install innosetup` oder ISCC setzen')


def installer():
    if not (APP / 'Captioner.exe').exists():
        sys.exit('dist/Captioner fehlt - erst `bundle`')
    run(find_iscc(), f'/DAppVersion={version()}', f'/DSourceDir={APP}', f'/DOutputDir={DIST}',
        ROOT / 'packaging' / 'captioner.iss')
    setup = DIST / f'Captioner-{version()}-x64-setup.exe'
    if not setup.exists():
        sys.exit(f'{setup} fehlt')
    print(f'{setup} ({setup.stat().st_size / 1e6:.0f} MB)')


COMMANDS = {'exiftool': exiftool, 'bundle': bundle, 'verify': verify, 'installer': installer,
            'all': lambda: (bundle(), installer())}

if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]]()
