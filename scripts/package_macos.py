"""
Installers for macOS (Apple silicon) from dist/Captioner.app.

    python scripts/package_macos.py verify      check the app: arm64, signature, Info.plist
    python scripts/package_macos.py dmg         disk image with the app and a link to /Applications
    python scripts/package_macos.py pkg         installer (.pkg) to /Applications, arm64 only
    python scripts/package_macos.py notarize    notarize DMG and PKG with Apple and staple them

Environment variables:
    CODESIGN_IDENTITY   "Developer ID Application: …"  signs the DMG
    INSTALLER_IDENTITY  "Developer ID Installer: …"    signs the PKG
    NOTARY_PROFILE      name from `xcrun notarytool store-credentials`
Without identities the packages are unsigned: usable on your own Mac, Gatekeeper blocks
them on other Macs (see readme.md, "Installer").
"""
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
APP = DIST / 'Captioner.app'
IDENTIFIER = 'de.chuc.captioner'


def run(*args, **kwargs):
    print('$', ' '.join(str(a) for a in args))
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def info():
    with open(APP / 'Contents' / 'Info.plist', 'rb') as handle:
        return plistlib.load(handle)


def artifact(suffix):
    return DIST / f'Captioner-{info()["CFBundleShortVersionString"]}-arm64.{suffix}'


def require_app():
    if not APP.exists():
        sys.exit('dist/Captioner.app fehlt - erst `make bundle`')


def macho_files():
    result = subprocess.run(['find', str(APP), '-type', 'f', '-exec', 'file', '{}', '+'],
                            capture_output=True, text=True, check=True).stdout
    return [line for line in result.splitlines() if 'Mach-O' in line]


def verify():
    require_app()
    plist = info()
    problems = []
    machos = macho_files()
    foreign = [line for line in machos if 'arm64' not in line or 'x86_64' in line]
    if foreign:
        problems.append(f'{len(foreign)} Binaries nicht reines arm64, z. B. {foreign[0]}')
    for manual in ('Captioner-Anleitung.pdf', 'Captioner-Manual.pdf'):
        if not any(APP.rglob(manual)):
            problems.append(f'{manual} fehlt im Bundle')
    for key in ('CFBundleShortVersionString', 'LSMinimumSystemVersion', 'CFBundleIconFile'):
        if not plist.get(key) or plist.get(key) == '0.0.0':
            problems.append(f'Info.plist: {key} fehlt')
    check = subprocess.run(['codesign', '--verify', '--deep', '--strict', str(APP)], capture_output=True, text=True)
    if check.returncode:
        problems.append('Signatur ungueltig: ' + check.stderr.strip())
    details = subprocess.run(['codesign', '-dv', str(APP)], capture_output=True, text=True).stderr
    signed_by = 'ad-hoc (nur fuer diesen Mac)' if 'Signature=adhoc' in details else \
        next((l.split('=', 1)[1] for l in details.splitlines() if l.startswith('Authority=')), '?')
    runtime = 'runtime' in next((l for l in details.splitlines() if l.startswith('CodeDirectory')), '')

    print(f'Captioner {plist["CFBundleShortVersionString"]}, ab macOS {plist["LSMinimumSystemVersion"]}')
    print(f'{len(machos)} Binaries, alle arm64' if not foreign else f'{len(foreign)} Binaries mit fremder Architektur')
    print(f'Signatur: {signed_by}; Hardened Runtime: {"ja" if runtime else "nein"}')
    if problems:
        sys.exit('\n'.join('FEHLER: ' + p for p in problems))
    print('OK')


def dmg():
    require_app()
    target = artifact('dmg')
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / 'Captioner'
        staging.mkdir()
        # ditto keeps symlinks, permissions and the app's signature attributes
        run('ditto', APP, staging / 'Captioner.app')
        (staging / 'Programme').symlink_to('/Applications')
        shutil.copy2(ROOT / 'docs' / 'Captioner-Anleitung.pdf', staging / 'Anleitung.pdf')
        shutil.copy2(ROOT / 'docs' / 'Captioner-Manual.pdf', staging / 'Manual.pdf')
        if target.exists():
            target.unlink()
        run('hdiutil', 'create', '-volname', 'Captioner', '-srcfolder', staging,
            '-fs', 'HFS+', '-format', 'ULFO', '-ov', target)
    identity = os.environ.get('CODESIGN_IDENTITY')
    if identity:
        run('codesign', '--sign', identity, '--timestamp', target)
    print('DMG:', target)
    return target


DISTRIBUTION = """<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>Captioner {version}</title>
    <!-- Nur Apple Silicon; auf Intel-Macs verweigert der Installer -->
    <options customize="never" require-scripts="false" hostArchitectures="arm64"/>
    <volume-check>
        <allowed-os-versions>
            <os-version min="{min_os}"/>
        </allowed-os-versions>
    </volume-check>
    <domains enable_localSystem="true" enable_currentUserHome="false" enable_anywhere="false"/>
    <welcome file="welcome.html" mime-type="text/html"/>
    <choices-outline>
        <line choice="default">
            <line choice="{identifier}"/>
        </line>
    </choices-outline>
    <choice id="default"/>
    <choice id="{identifier}" visible="false">
        <pkg-ref id="{identifier}"/>
    </choice>
    <pkg-ref id="{identifier}" version="{version}" onConclusion="none">component.pkg</pkg-ref>
</installer-gui-script>
"""

WELCOME = """<html><body style="font-family: -apple-system; font-size: 13px">
<h2>Captioner {version}</h2>
<p>Fotos sichten, bewerten und beschriften, bevor sie in Lightroom importiert werden.</p>
<p>Captioner wird nach <b>Programme</b> installiert. Voraussetzung: Mac mit Apple Silicon
und macOS {min_os} oder neuer.</p>
</body></html>
"""


def pkg():
    require_app()
    plist = info()
    version, min_os = plist['CFBundleShortVersionString'], plist['LSMinimumSystemVersion']
    target = artifact('pkg')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        root = tmp / 'root'
        root.mkdir()
        run('ditto', APP, root / 'Captioner.app')
        # Without this the installer "relocates" an update to wherever a Captioner.app happens to
        # be (e.g. dist/ on the build machine) instead of /Applications
        component_plist = tmp / 'component.plist'
        run('pkgbuild', '--analyze', '--root', root, component_plist)
        with open(component_plist, 'rb') as handle:
            components = plistlib.load(handle)
        for component in components:
            component['BundleIsRelocatable'] = False
            component['BundleIsVersionChecked'] = True
        with open(component_plist, 'wb') as handle:
            plistlib.dump(components, handle)
        run('pkgbuild', '--root', root, '--component-plist', component_plist,
            '--install-location', '/Applications', '--identifier', IDENTIFIER,
            '--version', version, tmp / 'component.pkg')

        resources = tmp / 'resources'
        resources.mkdir()
        (resources / 'welcome.html').write_text(WELCOME.format(version=version, min_os=min_os), encoding='utf-8')
        distribution = tmp / 'distribution.xml'
        distribution.write_text(DISTRIBUTION.format(version=version, min_os=min_os, identifier=IDENTIFIER),
                                encoding='utf-8')
        args = ['productbuild', '--distribution', distribution, '--resources', resources,
                '--package-path', tmp]
        identity = os.environ.get('INSTALLER_IDENTITY')
        if identity:
            args += ['--sign', identity, '--timestamp']
        if target.exists():
            target.unlink()
        run(*args, target)
    print('PKG:', target)
    return target


def notarize():
    profile = os.environ.get('NOTARY_PROFILE')
    if not profile:
        sys.exit('NOTARY_PROFILE fehlt. Einmalig: xcrun notarytool store-credentials <name> '
                 '--apple-id <mail> --team-id <TEAMID> (App-spezifisches Passwort)')
    details = subprocess.run(['codesign', '-dv', str(APP)], capture_output=True, text=True).stderr
    if 'Signature=adhoc' in details or 'Developer ID Application' not in details:
        sys.exit('Die App ist nicht mit "Developer ID Application" signiert - '
                 'CODESIGN_IDENTITY setzen und `make bundle` neu ausfuehren')
    for target in (artifact('dmg'), artifact('pkg')):
        if not target.exists():
            print('uebersprungen, fehlt:', target)
            continue
        run('xcrun', 'notarytool', 'submit', target, '--keychain-profile', profile, '--wait')
        run('xcrun', 'stapler', 'staple', target)
        run('spctl', '--assess', '--type', 'open' if target.suffix == '.dmg' else 'install',
            '--context', 'context:primary-signature', '-v', target)


COMMANDS = {'verify': verify, 'dmg': dmg, 'pkg': pkg, 'notarize': notarize}

if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    if shutil.which('hdiutil') is None:
        sys.exit('Nur auf macOS')
    COMMANDS[sys.argv[1]]()
