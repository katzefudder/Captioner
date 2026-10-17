"""Captioner: Fotos sichten, bewerten und beschriften, bevor sie in Lightroom importiert werden."""
import plistlib
import sys
from pathlib import Path

WEBSITE = 'https://www.katzefudder.de/captioner'
# Links zur Website mit Matomo-Kampagne (Anzeige ohne, Ziel mit Parametern)
WEBSITE_LINK = WEBSITE + '?mtm_campaign=captioner&mtm_source=app'
MANUAL_NAME = 'Captioner-Anleitung.pdf'


def manual_path():
    """Die Anleitung (PDF): im Bundle unter docs/ (beide Specs), sonst docs/ im Quellbaum."""
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', '')) / 'docs' / MANUAL_NAME
    return Path(__file__).resolve().parent.parent / 'docs' / MANUAL_NAME


def version():
    """
    Versionsnummer: in der gebuendelten App die Release-Version (CAPTIONER_VERSION in der
    Spec): Windows aus captioner/VERSION im Bundle, macOS aus der Info.plist; sonst aus dem
    installierten Paket.
    """
    if getattr(sys, 'frozen', False):
        try:
            return (Path(getattr(sys, '_MEIPASS', '')) / 'captioner' / 'VERSION').read_text(encoding='utf-8').strip()
        except OSError:
            pass
        plist = Path(sys.executable).resolve().parent.parent / 'Info.plist'  # Contents/MacOS/..
        try:
            with open(plist, 'rb') as handle:
                return plistlib.load(handle)['CFBundleShortVersionString']
        except (OSError, KeyError, plistlib.InvalidFileException):
            pass
    try:
        from importlib.metadata import version as package_version
        return package_version('captioner')
    except Exception:
        return 'dev'
