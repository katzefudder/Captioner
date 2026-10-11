"""
Rechtschreibpruefung der Beschreibung mit der von macOS (NSSpellChecker, per ctypes
wie folderdialog): dieselben Woerterbuecher wie Mail/Pages, gelernte Woerter gelten
in beiden Richtungen. Auf anderen Systemen gibt es keine Pruefung.

Nicht angestrichen: Codes (#bn23#) und Woerter aus den Roster-Ersetzungen (Namen).
Bereiche von NSSpellChecker sind UTF-16-Positionen, wie in QString/QSyntaxHighlighter.
"""
import ctypes
import logging
import re
import sys

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

from .folderdialog import _ObjC

logger = logging.getLogger(__name__)

WORD = re.compile(r'[^\W\d_]{2,}')


class _NSRange(ctypes.Structure):
    _fields_ = [('location', ctypes.c_ulong), ('length', ctypes.c_ulong)]


def utf16_slice(text, start, length):
    data = text.encode('utf-16-le')
    return data[start * 2:(start + length) * 2].decode('utf-16-le', errors='ignore')


def utf16_spans(text, pattern):
    """Treffer eines Musters als (Anfang, Ende) in UTF-16-Einheiten."""
    spans = []
    for match in pattern.finditer(text):
        start = len(text[:match.start()].encode('utf-16-le')) // 2
        end = start + len(match.group(0).encode('utf-16-le')) // 2
        spans.append((start, end))
    return spans


class MacSpellChecker:
    """Gerade genug NSSpellChecker: falsch geschriebene Woerter, Vorschlaege, lernen."""

    def __init__(self):
        self.objc = _ObjC()
        self.checker = self.objc.send(self.objc.cls('NSSpellChecker'), 'sharedSpellChecker')
        if not self.checker:
            raise OSError('NSSpellChecker nicht verfuegbar')

    def _language(self, language):
        return self.objc.string(language) if language else None

    def misspelled(self, text, language=None):
        """[(Anfang, Laenge)] in UTF-16-Einheiten."""
        objc = self.objc
        nstext = objc.string(text)
        total = len(text.encode('utf-16-le')) // 2
        found, start = [], 0
        while start < total:
            found_range = objc.send(
                self.checker, 'checkSpellingOfString:startingAt:language:wrap:inSpellDocumentWithTag:wordCount:',
                nstext, start, self._language(language), False, 0, None, restype=_NSRange,
                argtypes=[ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_bool, ctypes.c_long,
                          ctypes.c_void_p])
            if found_range.length == 0 or found_range.location >= total:
                break
            found.append((found_range.location, found_range.length))
            start = found_range.location + found_range.length
        return found

    def suggestions(self, text, start, length, language=None):
        objc = self.objc
        guesses = objc.send(
            self.checker, 'guessesForWordRange:inString:language:inSpellDocumentWithTag:',
            _NSRange(start, length), objc.string(text), self._language(language), 0,
            argtypes=[_NSRange, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long])
        if not guesses:
            return []
        count = objc.send(guesses, 'count', restype=ctypes.c_ulong)
        return [objc.to_str(objc.send(guesses, 'objectAtIndex:', i, argtypes=[ctypes.c_ulong]))
                for i in range(min(count, 8))]

    def languages(self):
        objc = self.objc
        items = objc.send(self.checker, 'availableLanguages')
        count = objc.send(items, 'count', restype=ctypes.c_ulong)
        return [objc.to_str(objc.send(items, 'objectAtIndex:', i, argtypes=[ctypes.c_ulong])) for i in range(count)]

    def learn(self, word):
        self.objc.send(self.checker, 'learnWord:', self.objc.string(word), restype=None,
                       argtypes=[ctypes.c_void_p])


_checker = None


def checker():
    """Der macOS-Pruefer, oder None (anderes System oder nicht ansprechbar)."""
    global _checker
    if _checker is None and sys.platform == 'darwin':
        try:
            _checker = MacSpellChecker()
        except (OSError, AttributeError, TypeError) as e:
            logger.warning('Rechtschreibpruefung nicht verfuegbar: %s', e)
            _checker = False
    return _checker or None


class SpellHighlighter(QSyntaxHighlighter):
    """Rot gewellt unterstreichen; Codes und bekannte Namen auslassen."""

    def __init__(self, document, spell_checker, delimiter='#'):
        super().__init__(document)
        self.spell_checker = spell_checker
        self.language = None        # None = macOS waehlt (automatisch)
        self.enabled = spell_checker is not None
        self.known = set()          # Woerter aus Roster-Ersetzungen, kleingeschrieben
        self.ignored = set()        # "Ignorieren" in dieser Sitzung
        self.set_delimiter(delimiter)
        self.format = QTextCharFormat()
        self.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        self.format.setUnderlineColor(QColor('#d64541'))

    def set_delimiter(self, delimiter):
        d = re.escape(delimiter or '#')
        self.code_pattern = re.compile(f'{d}[^{d}\\s]*{d}?')

    def set_known_words(self, texts):
        self.known = {w.casefold() for text in texts for w in WORD.findall(text)}
        self.rehighlight()

    def misspelled(self, text):
        """[(Anfang, Laenge, Wort)] nach Abzug von Codes und bekannten Woertern."""
        if not self.enabled or not text.strip():
            return []
        codes = utf16_spans(text, self.code_pattern)
        result = []
        for start, length in self.spell_checker.misspelled(text, self.language):
            if any(a <= start < b for a, b in codes):
                continue
            word = utf16_slice(text, start, length)
            if word.casefold() in self.known or word.casefold() in self.ignored:
                continue
            result.append((start, length, word))
        return result

    def highlightBlock(self, text):
        for start, length, _word in self.misspelled(text):
            self.setFormat(start, length, self.format)
