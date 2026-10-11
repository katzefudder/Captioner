"""Captioner: Fotos sichten, bewerten und beschriften, bevor sie in Lightroom importiert werden."""
import plistlib
import sys
from pathlib import Path

WEBSITE = 'https://www.katzefudder.de/captioner'


def version():
    """
    Versionsnummer: in der gebuendelten App aus deren Info.plist (die Release-Version,
    siehe CAPTIONER_VERSION in Captioner.spec), sonst aus dem installierten Paket.
    """
    if getattr(sys, 'frozen', False):
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
