"""Suchen und Ersetzen ueber mehrere Bilder (captioner.replace, ohne Qt)."""
from pathlib import Path

from captioner import replace
from captioner.replace import MARK_END, MARK_START, Options
from captioner.scanner import Item, Metadata
from captioner.templates import MatchTemplate

TEMPLATE = MatchTemplate(name='Heim', caption_suffix=', {headline}, {city}, {date}')
SUFFIX = ', DEL 2 - A gegen B, Bad Nauheim, 01.03.26'


def item(name, caption='', raw=None, keywords=(), headline='DEL 2 - A gegen B', city='Bad Nauheim'):
    result = Item(key=name, embedded=[Path(f'/x/{name}.jpg')], taken_at='2026:03:01 18:00:00',
                  meta=Metadata(headline=headline, caption=caption, keywords=list(keywords), city=city))
    result.raw = raw
    return result


def plan(items, find, replacement, fields=('caption',), **kwargs):
    return replace.plan(items, find, replacement, fields, kwargs.pop('roster'), '#',
                        raw_lookup=lambda i: i.raw, template=TEMPLATE, **kwargs)


def test_swapping_a_code_fixes_caption_person_tags_and_suffix(roster):
    photo = item('a', 'Tor -23- Marius Erk (EC Bad Nauheim)' + SUFFIX, raw='Tor #bn23#',
                 keywords=['Eishockey', 'Marius Erk'])
    [change] = plan([photo], '#bn23#', '#bn31#', roster=roster)
    assert change.ok and change.count == 1 and change.raw == 'Tor #bn31#'
    assert change.meta.caption == 'Tor -31- Dean Döge (EC Bad Nauheim)' + SUFFIX
    assert change.meta.keywords == ['Eishockey', 'Dean Döge']
    assert change.diffs == [('caption', f'Tor {MARK_START}#bn23#{MARK_END}', f'Tor {MARK_START}#bn31#{MARK_END}')]
    assert photo.meta.caption.startswith('Tor -23-')       # erst geplant, nichts geaendert


def test_name_is_found_although_the_raw_text_has_the_code(roster):
    photo = item('a', 'Tor -23- Marius Erk (EC Bad Nauheim)' + SUFFIX, raw='Tor #bn23#',
                 keywords=['Marius Erk'])
    [change] = plan([photo], 'Marius Erk', 'M. Erk', roster=roster)
    assert change.raw == 'Tor -23- M. Erk (EC Bad Nauheim)'
    assert change.meta.caption == 'Tor -23- M. Erk (EC Bad Nauheim)' + SUFFIX
    assert change.meta.keywords == []                       # kein Roster-Name mehr in der Beschreibung


def test_changing_the_headline_renews_the_template_suffix(roster):
    photo = item('a', 'Jubel' + SUFFIX)                      # ohne gemerkten Rohtext
    [change] = plan([photo], 'A gegen B', 'C gegen D', fields=('caption', 'headline'), roster=roster)
    assert change.meta.headline == 'DEL 2 - C gegen D'
    assert change.meta.caption == 'Jubel, DEL 2 - C gegen D, Bad Nauheim, 01.03.26'
    assert [field for field, _before, _after in change.diffs] == ['headline']   # im Anhang wird nicht gesucht


def test_case_and_whole_words(roster):
    photos = [item('a', 'Tor und Torwart'), item('b', 'TOR')]
    assert [c.meta.caption for c in plan(photos, 'tor', 'Treffer', roster=roster)] == [
        'Treffer und Trefferwart', 'Treffer']
    assert [c.meta.caption for c in plan(photos, 'tor', 'Treffer', roster=roster,
                                         options=Options(whole_words=True))] == ['Treffer und Torwart', 'Treffer']
    assert [c.item.key for c in plan(photos, 'Tor', 'Treffer', roster=roster,
                                     options=Options(case_sensitive=True))] == ['a']


def test_unknown_code_blocks_only_that_photo(roster):
    good, bad = item('a', 'Tor X', raw='Tor X'), item('b', 'Tor #bnX#', raw='Tor #bnX#')
    changes = plan([good, bad], 'X', '#bn23#', roster=roster)
    assert [(c.item.key, c.ok) for c in changes] == [('a', True), ('b', False)]
    assert changes[0].meta.caption.startswith('Tor -23- Marius Erk') and changes[1].unknown == ['bn']


def test_tags_city_and_untouched_photos(roster):
    photos = [item('a', keywords=['Eishokey', 'DEL2', 'Eishockey']), item('b', keywords=['Fussball'])]
    [change] = plan(photos, 'Eishokey', 'Eishockey', fields=('keywords',), roster=roster)
    assert change.item.key == 'a' and change.meta.keywords == ['Eishockey', 'DEL2']   # doppelte zusammengelegt
    [moved] = plan([item('c', city='Bad Nauhiem')], 'Nauhiem', 'Nauheim', fields=('city',), roster=roster)
    assert moved.meta.city == 'Bad Nauheim'
    assert plan(photos, '', 'x', roster=roster) == []


def test_foreign_suffix_stays_and_replacement_is_literal(roster):
    photo = item('a', 'Jubel, Foto: Agentur')               # kein Anhang dieses Templates
    [change] = plan([photo], 'Agentur', r'\1 & Co', roster=roster)
    assert change.meta.caption == r'Jubel, Foto: \1 & Co'
