"""
Find and replace across several images (without Qt).

Each image is computed as when saving: in the caption, the raw text with codes is
replaced (so #bn9# becomes #bn10# and the person tags match afterwards), elsewhere the
resolved text. The template's suffix is not searched but rebuilt with the new values;
foreign suffixes stay.
"""
import dataclasses
import re
from dataclasses import dataclass, field

from . import codes, geo, metadata
from .templates import unique

FIELDS = ('caption', 'headline', 'keywords', 'city', 'sublocation')
# marks matches for the preview (characters from the private use area, never in the text)
MARK_START, MARK_END = '', ''


@dataclass
class Options:
    case_sensitive: bool = False
    whole_words: bool = False


def compile_pattern(find, options=Options()):
    """Regular expression for the search text (always literal), None for an empty search."""
    if not find:
        return None
    text = re.escape(find)
    if options.whole_words:
        text = rf'(?<!\w){text}(?!\w)'
    return re.compile(text, 0 if options.case_sensitive else re.IGNORECASE)


def replace_text(text, pattern, replacement):
    """(new text, count); the replacement is literal, even with backslashes."""
    return pattern.subn(lambda _match: replacement, text or '')


def mark(text, pattern, replacement=None):
    """Matches framed; with replacement, the replacement instead of them (preview "after")."""
    return pattern.sub(lambda m: MARK_START + (m.group(0) if replacement is None else replacement) + MARK_END,
                       text or '')


@dataclass
class Change:
    item: object
    meta: object                 # new metadata
    raw: str = None              # new raw text of the caption (None = unchanged)
    count: int = 0               # matches
    diffs: list = field(default_factory=list)   # (field, before marked, after marked)
    unknown: list = field(default_factory=list)   # unknown codes after replacing
    problems: list = field(default_factory=list)  # fields that are too long (metadata.validate)

    @property
    def ok(self):
        return self.count > 0 and not self.unknown and not self.problems


def plan(items, find, replacement, fields, roster, delimiter='#', options=Options(),
         raw_lookup=None, template=None, places=None):
    """
    Changes per image, not written yet. Images without matches are missing.
    raw_lookup(item): raw text with codes (without suffix), otherwise None.
    """
    pattern = compile_pattern(find, options)
    if pattern is None:
        return []
    changes = []
    for item in items:
        change = _plan_item(item, pattern, replacement, fields, roster, delimiter, raw_lookup, template, places)
        if change.count:
            changes.append(change)
    return changes


def _plan_item(item, pattern, replacement, fields, roster, delimiter, raw_lookup, template, places):
    meta = item.meta
    values = {name: getattr(meta, name) for name in ('headline', 'city', 'sublocation')}
    change = Change(item=item, meta=meta)

    for name in ('headline', 'city', 'sublocation'):
        if name in fields:
            new, count = replace_text(values[name], pattern, replacement)
            if count:
                change.count += count
                change.diffs.append((name, mark(values[name], pattern), mark(values[name], pattern, replacement)))
                values[name] = metadata.single_line(new)

    keywords = list(meta.keywords)
    if 'keywords' in fields:
        replaced = []
        for keyword in keywords:
            new, count = replace_text(keyword, pattern, replacement)
            change.count += count
            replaced.append(new.strip())
        if replaced != keywords:
            change.diffs.append(('keywords', mark(', '.join(keywords), pattern),
                                 mark(', '.join(keywords), pattern, replacement)))
        keywords = [k for k in unique(replaced) if k]

    caption = meta.caption
    if caption:
        body, tail, from_template = _split_caption(item, caption, roster, delimiter, raw_lookup, template)
        count = 0
        if 'caption' in fields:
            new_body, count = replace_text(body, pattern, replacement)
            if not count:
                # searching for a name, but the raw text has the code: replace in the resolved text
                resolved = codes.resolve(body, roster, delimiter).text
                if resolved != body:
                    new_body, count = replace_text(resolved, pattern, replacement)
                    if count:
                        body = resolved
        if count:
            change.count += count
            change.diffs.append(('caption', mark(body, pattern), mark(body, pattern, replacement)))
            change.raw = body = new_body
        # Recompose on matches in the caption, and when headline/city/location appear in the
        # template's suffix and have changed
        values_changed = any(values[name] != getattr(meta, name) for name in values)
        if count or (from_template and values_changed):
            resolution = codes.resolve(body, roster, delimiter)
            change.unknown = resolution.unknown
            caption = metadata.single_line(resolution.text)
            if caption and from_template:
                caption = template.compose_caption(caption, item.taken_at, **values,
                                                   **template.field_values(meta))
            elif caption:
                caption += tail
            # person tags: those of the old caption out, those of the new one in
            old_persons = set(codes.persons_in(meta.caption, roster))
            new_persons = unique(resolution.persons + codes.persons_in(caption, roster))
            keywords = unique([k for k in keywords if k not in old_persons or k in new_persons] + new_persons)

    new_meta = dataclasses.replace(meta, caption=caption, keywords=keywords, **values)
    if places is not None and (values['city'], values['sublocation']) != (meta.city, meta.sublocation):
        new_meta = geo.apply_gps(new_meta, places)
    change.meta = new_meta
    change.problems += metadata.validate(new_meta)
    return change


def _split_caption(item, caption, roster, delimiter, raw_lookup, template):
    """
    (text to search, remaining suffix, suffix from the template?). With a remembered raw
    text the search runs on that; otherwise on the caption without the template's suffix.
    """
    meta = item.meta
    suffix = ''
    if template:
        suffix = template.suffix_for(item.taken_at, headline=meta.headline, city=meta.city,
                                     sublocation=meta.sublocation, **template.field_values(meta))
    raw = raw_lookup(item) if raw_lookup else None
    resolved = metadata.single_line(codes.resolve(raw, roster, delimiter).text) if raw is not None else None
    # raw text only as long as it matches the caption (otherwise it was changed elsewhere)
    if raw is not None and resolved and caption.startswith(resolved):
        tail = caption[len(resolved):]
        return raw, tail, bool(suffix) and tail.strip() == suffix.strip()
    if suffix and caption.endswith(suffix):
        return caption[:-len(suffix)], '', True
    return caption, '', False
