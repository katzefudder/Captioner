import pytest

from captioner.roster import RosterLoader, parse, raw_url
from conftest import ROSTER_TEXT


def test_parse_assigns_sections_and_skips_lines_without_tab():
    entries = parse(ROSTER_TEXT)
    assert [e.code for e in entries] == ['bi99', 'bi100', 'bn23', 'bn31']
    assert entries[0].team == 'Bietigheim Steelers'
    assert entries[2].team == 'EC Bad Nauheim'
    assert entries[1].replacement == 'Tim Kehler (Coach Bietigheim Steelers)'


def test_parse_handles_crlf():
    entries = parse('- A -\r\n\r\nx1\t-1- Foo Bar (A)\r\n')
    assert entries[0].replacement == '-1- Foo Bar (A)'
    assert entries[0].team == 'A'


def test_github_blob_url_is_rewritten_to_raw():
    assert raw_url('https://github.com/katzefudder/del2_roster/blob/main/roster_del2.txt') == \
        'https://raw.githubusercontent.com/katzefudder/del2_roster/main/roster_del2.txt'
    assert raw_url('https://example.org/roster.txt') == 'https://example.org/roster.txt'


def test_local_file_source(tmp_path):
    path = tmp_path / 'roster.txt'
    path.write_text(ROSTER_TEXT, encoding='utf-8')
    roster = RosterLoader(tmp_path).load([str(path)])
    assert roster.lookup('bn31').replacement == '-31- Dean Döge (EC Bad Nauheim)'
    assert roster.status[0].origin == 'datei'
    assert roster.teams == ['Bietigheim Steelers', 'EC Bad Nauheim']


def test_zero_ttl_never_uses_the_cache_even_with_a_future_mtime(tmp_path):
    import os
    import time
    texts = iter([ROSTER_TEXT, ROSTER_TEXT.replace('John Doe', 'Jane Doe')])
    loader = RosterLoader(tmp_path, ttl_minutes=0, fetch=lambda url: next(texts))
    loader.load(['https://example.org/r.txt'])
    for cached in tmp_path.rglob('*'):
        if cached.is_file():
            os.utime(cached, (time.time() + 1, time.time() + 1))   # Dateizeit knapp vor der Uhr
    second = loader.load(['https://example.org/r.txt'])
    assert second.status[0].origin == 'netz' and 'Jane Doe' in second.entries['bi99'].replacement


def test_url_falls_back_to_last_good_version(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        if len(calls) > 1:
            raise OSError('offline')
        return ROSTER_TEXT

    loader = RosterLoader(tmp_path, ttl_minutes=0, fetch=fetch)
    first = loader.load(['https://example.org/r.txt'])
    assert first.status[0].origin == 'netz'
    second = loader.load(['https://example.org/r.txt'])
    assert second.status[0].origin == 'letzte gute Version'
    assert 'offline' in second.status[0].message
    assert second.lookup('bi99')


def test_url_within_ttl_uses_cache(tmp_path):
    calls = []
    loader = RosterLoader(tmp_path, ttl_minutes=60, fetch=lambda url: calls.append(url) or ROSTER_TEXT)
    loader.load(['https://example.org/r.txt'])
    roster = loader.load(['https://example.org/r.txt'])
    assert len(calls) == 1
    assert roster.status[0].origin == 'cache'
    loader.load(['https://example.org/r.txt'], force=True)
    assert len(calls) == 2


def test_html_instead_of_roster_is_an_error(tmp_path):
    loader = RosterLoader(tmp_path, fetch=lambda url: '<html><body>nope</body></html>')
    roster = loader.load(['https://example.org/r.txt'])
    assert not roster.status[0].ok
    assert not roster.is_usable


def test_conflicting_codes_are_reported_not_silently_merged(tmp_path):
    a = tmp_path / 'a.txt'
    b = tmp_path / 'b.txt'
    a.write_text('x1\t-1- Foo (A)\n', encoding='utf-8')
    b.write_text('x1\t-1- Bar (B)\nx2\t-2- Baz (B)\n', encoding='utf-8')
    roster = RosterLoader(tmp_path).load([str(a), str(b)])
    assert [c[0] for c in roster.conflicts] == ['x1']
    assert roster.lookup('x1').replacement == '-1- Foo (A)'
    assert roster.lookup('x2')


def test_duplicate_code_within_one_file_is_a_conflict(tmp_path):
    # So steht es aktuell in roster_del2.txt: zweimal "bn" fuer Spieler ohne Nummer
    path = tmp_path / 'r.txt'
    path.write_text('bn\t- Julius Schulte (EC Bad Nauheim)\nbn\t- Ramon Hupf (EC Bad Nauheim)\n', encoding='utf-8')
    roster = RosterLoader(tmp_path).load([str(path)])
    assert [c[0] for c in roster.conflicts] == ['bn']


def test_identical_duplicates_are_fine(tmp_path):
    a = tmp_path / 'a.txt'
    a.write_text('x1\t-1- Foo (A)\n', encoding='utf-8')
    roster = RosterLoader(tmp_path).load([str(a), str(a)])
    assert roster.conflicts == []


def test_local_files_in_windows_encodings(tmp_path):
    text = '- Eisbären Regensburg -\n\nrg9\t-9- Jöns Müller (Eisbären Regensburg)\n'
    encodings = {'utf8.txt': text.encode('utf-8'), 'bom.txt': text.encode('utf-8-sig'),
                 'utf16.txt': text.encode('utf-16'), 'cp1252.txt': text.encode('cp1252')}
    for name, data in encodings.items():
        (tmp_path / name).write_bytes(data)
        roster = RosterLoader(tmp_path / 'cache').load([str(tmp_path / name)])
        entry = roster.lookup('rg9')
        assert entry.replacement == '-9- Jöns Müller (Eisbären Regensburg)', name
        assert entry.team == 'Eisbären Regensburg', name


def test_local_file_without_codes_is_reported(tmp_path):
    path = tmp_path / 'leer.txt'
    path.write_text('nur Text, keine Tabs\n', encoding='utf-8')
    roster = RosterLoader(tmp_path).load([str(path)])
    assert not roster.status[0].ok
    assert 'keine Codes' in roster.status[0].message


def test_files_and_urls_combined(tmp_path):
    path = tmp_path / 'oberliga.txt'
    path.write_text('ecn17\t-17- Patrick Strauch (Eisbären Nordhorn)\n', encoding='utf-8')
    loader = RosterLoader(tmp_path / 'cache', fetch=lambda url: ROSTER_TEXT)
    roster = loader.load(['https://example.org/del2.txt', str(path)])
    assert roster.lookup('bi99') and roster.lookup('ecn17')
    assert [s.origin for s in roster.status] == ['netz', 'datei']


ROSTER_SOURCE = '- EC Bad Nauheim -\n\nbn23\t-23- Marius Erk (EC Bad Nauheim)\nbn31\t-31- Dean Döge (EC Bad Nauheim)\n'


@pytest.mark.parametrize('encoding, newline', [('utf-8', '\n'), ('utf-8-sig', '\r\n'), ('utf-16', '\r\n'),
                                               ('cp1252', '\r\n')])
def test_roster_file_keeps_encoding_and_line_endings(tmp_path, encoding, newline):
    from captioner import roster
    path = tmp_path / 'r.txt'
    path.write_bytes(ROSTER_SOURCE.replace('\n', newline).encode(encoding))
    loaded = roster.read_file(path)
    assert (loaded.encoding, loaded.newline) == (encoding, newline)
    assert loaded.text == ROSTER_SOURCE  # im Editor immer \n
    roster.write_file(loaded, loaded.text + 'bn99\t-99- Jörg Öhler (EC Bad Nauheim)\n')
    data = path.read_bytes()
    expected = (ROSTER_SOURCE + 'bn99\t-99- Jörg Öhler (EC Bad Nauheim)\n').replace('\n', newline).encode(encoding)
    assert data == expected
    assert not list(tmp_path.glob('.*captioner-tmp'))


def test_roster_check_finds_ignored_and_conflicting_lines():
    from captioner import roster
    text = ('- EC Bad Nauheim -\n'
            'bn23\t-23- Marius Erk (EC Bad Nauheim)\n'
            'bn31 -31- Dean Döge (EC Bad Nauheim)\n'       # Leerzeichen statt Tab
            'bn40\t\n'                                      # Ersetzung fehlt
            'bn23\t-23- Jemand anders (EC Bad Nauheim)\n'  # widerspruechlich
            'bn23\t-23- Marius Erk (EC Bad Nauheim)\n'     # nur doppelt
            '\n')
    problems = roster.check(text)
    assert [(p.line, p.serious) for p in problems] == [(3, True), (4, True), (5, True), (6, False)]
    assert 'kein Tab' in problems[0].message and 'Zeile 2' in problems[2].message
