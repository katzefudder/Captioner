import pytest

from captioner.templates import MatchTemplate, TemplateStore, format_date


def template(**kwargs):
    values = dict(name='BN-BI', occasion='DEL 2', home='EC Bad Nauheim', away='Bietigheim Steelers',
                  city='Bad Nauheim', sublocation='Colonel-Knight-Stadion', extra_tags=['Eishockey', 'DEL2'])
    values.update(kwargs)
    return MatchTemplate(**values)


def test_headline_has_the_format_recognition_parses():
    import re
    # Muster aus app/recognition/lib/matches.py
    pattern = re.compile(r'^(?P<occasion>.+?)\s+-\s+(?P<home>.+?)\s+gegen\s+(?P<away>.+?)$')
    match = pattern.match(template().headline)
    assert match.group('home') == 'EC Bad Nauheim'
    assert match.group('away') == 'Bietigheim Steelers'


def test_headline_empty_until_complete():
    assert template(away='').headline == ''


def test_keywords():
    assert template().keywords == ['EC Bad Nauheim', 'Bietigheim Steelers', 'Bad Nauheim', 'Eishockey', 'DEL2']


def test_caption_suffix():
    caption = template().compose_caption('-31- Dean Döge (EC Bad Nauheim)', '2026:03:01 17:17:28.087')
    assert caption == ('-31- Dean Döge (EC Bad Nauheim), DEL 2 - EC Bad Nauheim gegen Bietigheim Steelers, '
                       'Bad Nauheim, Colonel-Knight-Stadion, 01.03.26')


def test_caption_suffix_is_not_appended_twice():
    t = template()
    once = t.compose_caption('Jubel', '2026:03:01 17:17:28')
    assert t.compose_caption(once, '2026:03:01 17:17:28') == once


def test_caption_suffix_uses_saved_values_over_template():
    caption = template().compose_caption('Jubel', '', headline='Testspiel - A gegen B', city='Kassel', sublocation='')
    assert caption == 'Jubel, Testspiel - A gegen B, Kassel'


def test_empty_suffix_and_empty_caption():
    assert template(caption_suffix='').compose_caption('Jubel') == 'Jubel'
    assert template().compose_caption('') == ''


def test_format_date():
    assert format_date('2026:10:09 19:30:00.12') == '09.10.26'
    assert format_date('') == ''


def test_file_roundtrip(tmp_path):
    from captioner import templates
    path = templates.save_file(template(), tmp_path / 'bn-bi.toml')
    text = path.read_text(encoding='utf-8')
    assert 'format = "captioner-template"' in text
    assert 'path' not in text.split('\n', 1)[1]
    loaded = templates.load_file(path)
    assert loaded == template()
    assert loaded.path == str(path)


def test_file_with_umlauts_and_without_name(tmp_path):
    from captioner import templates
    path = tmp_path / 'Regensburg.toml'
    path.write_text('occasion = "DEL 2"\nhome = "EC Bad Nauheim"\naway = "Eisbären Regensburg"\n', encoding='utf-8')
    loaded = templates.load_file(path)
    assert loaded.away == 'Eisbären Regensburg'
    assert loaded.name == 'Regensburg'


def test_foreign_or_broken_files_are_rejected(tmp_path):
    import pytest
    from captioner import templates
    cases = {
        'other.toml': 'format = "something-else"\noccasion = "x"\nhome = "a"\naway = "b"\n',
        'broken.toml': 'occasion = \n',
        'incomplete.toml': 'occasion = "DEL 2"\n',
        'types.toml': 'occasion = "DEL 2"\nhome = "a"\naway = "b"\nextra_tags = "Eishockey"\n',
        'future.toml': 'version = 99\noccasion = "DEL 2"\nhome = "a"\naway = "b"\n',
    }
    for name, content in cases.items():
        (tmp_path / name).write_text(content, encoding='utf-8')
        with pytest.raises(templates.TemplateError):
            templates.load_file(tmp_path / name)
    with pytest.raises(templates.TemplateError):
        templates.load_file(tmp_path / 'missing.toml')


def test_store_lists_internal_and_external_files(tmp_path):
    from captioner import templates
    store = TemplateStore(tmp_path / 'store')
    store.save(template(name='Intern'))
    external = templates.save_file(template(name='Extern'), tmp_path / 'elsewhere' / 'extern.toml')
    (tmp_path / 'store' / 'kaputt.toml').write_text('nope = ', encoding='utf-8')

    found, errors = store.list([str(external), str(external)])
    assert [t.name for t in found] == ['Intern', 'Extern']
    assert len(errors) == 1 and 'kaputt.toml' in errors[0]
    assert store.is_internal(found[0]) and not store.is_internal(found[1])


def test_store_saves_back_to_external_file_and_never_deletes_it(tmp_path):
    from captioner import templates
    store = TemplateStore(tmp_path / 'store')
    external = templates.save_file(template(), tmp_path / 'extern.toml')
    loaded = templates.load_file(external)
    loaded.city = 'Kassel'
    store.save(loaded)
    assert templates.load_file(external).city == 'Kassel'
    assert list((tmp_path / 'store').iterdir()) == []
    store.delete(loaded)
    assert external.exists()


def test_coordinates_roundtrip_and_are_omitted_when_unset(tmp_path):
    from captioner import templates
    path = templates.save_file(template(latitude=50.3725500, longitude=8.7384500), tmp_path / 'a.toml')
    loaded = templates.load_file(path)
    assert (loaded.latitude, loaded.longitude) == (50.3725500, 8.7384500)
    path = templates.save_file(template(), tmp_path / 'b.toml')
    assert 'latitude' not in path.read_text()
    assert templates.load_file(path).latitude is None


@pytest.mark.parametrize('lines', ['latitude = "50"\nlongitude = 8.7', 'latitude = 50.3', 'latitude = 91.0\nlongitude = 8.7',
                                   'latitude = true\nlongitude = 8.7'])
def test_bad_coordinates_are_rejected(tmp_path, lines):
    from captioner import templates
    path = tmp_path / 'bad.toml'
    path.write_text('occasion = "DEL 2"\nhome = "A"\naway = "B"\n' + lines + '\n', encoding='utf-8')
    with pytest.raises(templates.TemplateError):
        templates.load_file(path)
