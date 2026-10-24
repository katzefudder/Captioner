"""Captioner: review, rate and caption photos before importing them into Lightroom."""
import plistlib
import sys
from pathlib import Path

WEBSITE = 'https://www.katzefudder.de/captioner'
# Links to the website with a Matomo campaign (shown without, target with parameters)
WEBSITE_LINK = WEBSITE + '?mtm_campaign=captioner&mtm_source=app'
# Manual per UI language; anything else gets the English one
MANUALS = {'de': 'Captioner-Anleitung.pdf', 'en': 'Captioner-Manual.pdf'}


def manual_path(language=None):
    """
    The manual (PDF) in the given language (default: the UI language): in the bundle under
    docs/ (both specs), otherwise docs/ in the source tree.
    """
    from .i18n import language as ui_language
    name = MANUALS.get(language or ui_language(), MANUALS['en'])
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', '')) / 'docs' / name
    return Path(__file__).resolve().parent.parent / 'docs' / name


def version():
    """
    Version number: in the bundled app the release version (CAPTIONER_VERSION in the
    spec): Windows from captioner/VERSION in the bundle, macOS from Info.plist; otherwise
    from the installed package.
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
