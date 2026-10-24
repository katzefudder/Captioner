"""
Translations (gettext), without Qt.

* The source language in the code is German: _('Speichern') returns the German text
  without a catalogue. Other languages live in captioner/locale/<language>/LC_MESSAGES/
  captioner.po (source, editable) and captioner.mo (compiled, checked in).
* `make translations` extracts the texts (pybabel extract), updates the catalogues and
  compiles them. tests/test_i18n.py checks completeness and placeholders.
* Texts with values: _('{count} Bilder kopiert').format(count=n), never f-strings inside _()
  (gettext can't find them). Plurals: ngettext('{n} Bild', '{n} Bilder', n).format(n=n).
* Mark module-level texts (tables, labels) with N_() and translate them with _() only when
  displayed: the language is not set yet at import time.
"""
import gettext as _gettext
from pathlib import Path

DOMAIN = 'captioner'
LOCALE_DIR = Path(__file__).resolve().parent / 'locale'
SOURCE_LANGUAGE = 'de'
LANGUAGES = {'de': 'Deutsch', 'en': 'English'}   # shown in their own language

_translation = _gettext.NullTranslations()
_language = SOURCE_LANGUAGE


def _(message):
    return _translation.gettext(message)


def ngettext(singular, plural, count):
    return _translation.ngettext(singular, plural, count)


def N_(message):
    """Only mark (for pybabel extract); translated later with _()."""
    return message


def language():
    return _language


def resolve(setting, preferred=()):
    """
    Language from the setting ('' = automatic) and the system's preferred languages
    (e.g. QLocale.system().uiLanguages(): 'de-DE', 'en-US'). Unknown -> English.
    """
    if setting in LANGUAGES:
        return setting
    for tag in preferred:
        code = str(tag).replace('_', '-').split('-')[0].lower()
        if code in LANGUAGES:
            return code
    return 'en'


def setup(language):
    """Set the language for all following _() calls."""
    global _translation, _language
    _language = language if language in LANGUAGES else SOURCE_LANGUAGE
    if _language == SOURCE_LANGUAGE:
        _translation = _gettext.NullTranslations()
    else:
        _translation = _gettext.translation(DOMAIN, LOCALE_DIR, languages=[_language], fallback=True)
    return _language
