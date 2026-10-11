"""
Uebersetzungen (gettext), ohne Qt.

* Ausgangssprache im Code ist Deutsch: _('Speichern') liefert ohne Katalog den
  deutschen Text. Weitere Sprachen liegen als captioner/locale/<sprache>/LC_MESSAGES/
  captioner.po (Quelle, bearbeitbar) und captioner.mo (kompiliert, eingecheckt).
* `make translations` zieht die Texte heraus (pybabel extract), aktualisiert die
  Kataloge und kompiliert sie. tests/test_i18n.py prueft Vollstaendigkeit und Platzhalter.
* Texte mit Werten: _('{count} Bilder kopiert').format(count=n), nie f-Strings in _()
  (gettext findet sie nicht). Mengen: ngettext('{n} Bild', '{n} Bilder', n).format(n=n).
* Texte auf Modulebene (Tabellen, Labels) mit N_() markieren und erst bei der Anzeige
  mit _() uebersetzen: beim Import ist die Sprache noch nicht gesetzt.
"""
import gettext as _gettext
from pathlib import Path

DOMAIN = 'captioner'
LOCALE_DIR = Path(__file__).resolve().parent / 'locale'
SOURCE_LANGUAGE = 'de'
LANGUAGES = {'de': 'Deutsch', 'en': 'English'}   # Anzeige in der eigenen Sprache

_translation = _gettext.NullTranslations()
_language = SOURCE_LANGUAGE


def _(message):
    return _translation.gettext(message)


def ngettext(singular, plural, count):
    return _translation.ngettext(singular, plural, count)


def N_(message):
    """Nur markieren (fuer pybabel extract); uebersetzt wird spaeter mit _()."""
    return message


def language():
    return _language


def resolve(setting, preferred=()):
    """
    Sprache aus der Einstellung ('' = automatisch) und den bevorzugten Sprachen des
    Systems (z. B. QLocale.system().uiLanguages(): 'de-DE', 'en-US'). Unbekannt -> Englisch.
    """
    if setting in LANGUAGES:
        return setting
    for tag in preferred:
        code = str(tag).replace('_', '-').split('-')[0].lower()
        if code in LANGUAGES:
            return code
    return 'en'


def setup(language):
    """Sprache fuer alle folgenden _()-Aufrufe setzen."""
    global _translation, _language
    _language = language if language in LANGUAGES else SOURCE_LANGUAGE
    if _language == SOURCE_LANGUAGE:
        _translation = _gettext.NullTranslations()
    else:
        _translation = _gettext.translation(DOMAIN, LOCALE_DIR, languages=[_language], fallback=True)
    return _language
