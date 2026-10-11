"""
Gemerkte Stichwoerter fuer Vorschlaege im Tag-Feld, ohne Qt.

Gesammelt wird, was gespeichert wird und was in geoeffneten Bildern und Templates
steht; neueste zuerst, als JSON im Cache-Verzeichnis.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LIMIT = 1000


class KeywordHistory:
    def __init__(self, path: Path = None):
        self.path = Path(path) if path else None
        self.words = []
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                self.words = [w for w in data if isinstance(w, str) and w.strip()]
            except (OSError, ValueError):
                self.words = []

    def add(self, keywords, recent=True):
        """recent=False: nur ergaenzen, ohne die Reihenfolge zu aendern (beim Einlesen)."""
        known = {w.casefold() for w in self.words}
        new = []
        for word in keywords:
            word = (word or '').strip()
            if word and word.casefold() not in known and word not in new:
                new.append(word)
        if recent:
            lowered = {w.strip().casefold() for w in keywords if w and w.strip()}
            moved = [w for w in self.words if w.casefold() in lowered]
            rest = [w for w in self.words if w.casefold() not in lowered]
            self.words = new + moved + rest
        else:
            self.words = self.words + new
        del self.words[LIMIT:]
        return bool(new) or recent

    def save(self):
        if not self.path:
            return
        try:
            self.path.write_text(json.dumps(self.words, ensure_ascii=False), encoding='utf-8')
        except OSError as e:
            logger.warning('Stichwoerter nicht gespeichert: %s', e)

    def suggestions(self, prefix, exclude=(), limit=12):
        """Woerter, die mit prefix beginnen (oder es enthalten), ohne die schon eingetragenen."""
        prefix = prefix.strip().casefold()
        if len(prefix) < 2:
            return []
        excluded = {e.strip().casefold() for e in exclude}
        candidates = [w for w in self.words if w.casefold() not in excluded]
        starts = [w for w in candidates if w.casefold().startswith(prefix)]
        contains = [w for w in candidates if prefix in w.casefold() and w not in starts]
        return (starts + contains)[:limit]


def current_token(text, cursor):
    """(Anfang, angefangenes Wort) des Tags unter dem Cursor; Tags durch Komma/Zeilenumbruch getrennt."""
    before = text[:cursor]
    start = max(before.rfind(','), before.rfind('\n')) + 1
    token = before[start:]
    return start + (len(token) - len(token.lstrip())), token.strip()
