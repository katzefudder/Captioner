"""
Remembered keywords for suggestions in the tag field, without Qt.

Collected from what is saved and from what is in opened images and templates;
newest first, as JSON in the cache directory.
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
        """recent=False: only add, without changing the order (when reading images)."""
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
        """Words starting with prefix (or containing it), without those already entered."""
        prefix = prefix.strip().casefold()
        if len(prefix) < 2:
            return []
        excluded = {e.strip().casefold() for e in exclude}
        candidates = [w for w in self.words if w.casefold() not in excluded]
        starts = [w for w in candidates if w.casefold().startswith(prefix)]
        contains = [w for w in candidates if prefix in w.casefold() and w not in starts]
        return (starts + contains)[:limit]


def current_token(text, cursor):
    """(start, partial word) of the tag under the cursor; tags separated by comma/newline."""
    before = text[:cursor]
    start = max(before.rfind(','), before.rfind('\n')) + 1
    token = before[start:]
    return start + (len(token) - len(token.lstrip())), token.strip()
