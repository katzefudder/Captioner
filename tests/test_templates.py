import pytest

from captioner.templates import MatchTemplate, TemplateStore, format_date


def template(**kwargs):
    values = dict(name='BN-BI', headline='DEL 2 - EC Bad Nauheim gegen Bietigheim Steelers',
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


def test_teams_come_from_the_headline():
    assert template().teams == ['EC Bad Nauheim', 'Bietigheim Steelers']
    assert template(headline='').teams == [] and template(headline='Training').teams == []


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
    assert loaded.headline == 'DEL 2 - EC Bad Nauheim gegen Eisbären Regensburg'  # Version 1 umgerechnet
    assert loaded.name == 'Regensburg'


def test_foreign_or_broken_files_are_rejected(tmp_path):
    import pytest
    from captioner import templates
    cases = {
        'other.toml': 'format = "something-else"\noccasion = "x"\nhome = "a"\naway = "b"\n',
        'broken.toml': 'occasion = \n',
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


def test_version_1_without_teams_has_no_headline(tmp_path):
    from captioner import templates
    path = tmp_path / 'DEL2 Heimspiele.toml'
    path.write_text('occasion = "DEL 2"\ncity = "Bad Nauheim"\nextra_tags = ["Eishockey"]\n', encoding='utf-8')
    loaded = templates.load_file(path)
    assert loaded.headline == '' and loaded.teams == [] and loaded.name == 'DEL2 Heimspiele'
    assert loaded.keywords == ['Bad Nauheim', 'Eishockey']
    # Anhang mit dem Titel des Bildes statt eines festen
    assert loaded.compose_caption('Jubel', '', headline='DEL 2 - A gegen B', city='Bad Nauheim') == \
        'Jubel, DEL 2 - A gegen B, Bad Nauheim'


def test_parse_headline():
    from captioner.templates import parse_headline
    assert parse_headline('DEL 2 - EC Bad Nauheim gegen Eisbären Regensburg') == (
        'DEL 2', 'EC Bad Nauheim', 'Eisbären Regensburg')
    assert parse_headline(template().headline) == ('DEL 2', 'EC Bad Nauheim', 'Bietigheim Steelers')
    assert parse_headline('Training EC Bad Nauheim') is None
    assert parse_headline('') is None


RIGHTS = dict(state='Hessen', country='Deutschland', creator='Florian Dehn', authors_position='Fotograf',
              caption_writer='Florian Dehn', copyright='© 2026 Florian Dehn',
              web_statement='https://example.org/lizenz', source='chuc.de', category='Sport',
              instructions='Honorarpflichtig. Kontakt: foto@example.org · IBAN DE00 1234')


def test_rights_and_location_roundtrip(tmp_path):
    from captioner import templates
    saved = template(**RIGHTS)
    path = templates.save_file(saved, tmp_path / 'rechte.toml')
    text = path.read_text(encoding='utf-8')
    assert 'version = 2' in text and 'copyright = "© 2026 Florian Dehn"' in text
    assert 'home' not in text and 'occasion' not in text
    assert templates.load_file(path) == saved
    assert saved.fixed_values() == RIGHTS
    assert template(creator='X').fixed_values() == {'creator': 'X'}  # leere Felder fehlen


def test_the_users_version_1_file(tmp_path):
    """Datei aus Version 1, wie sie im Umlauf ist."""
    from captioner import templates
    path = tmp_path / 'EC_Bad_Nauheim_gegen_Kassel_Huskies.toml'
    path.write_text('''# Captioner Spiel-Template (siehe docs/adr/0001-*.md)
format = "captioner-template"
version = 1
name = "EC Bad Nauheim gegen Kassel Huskies"
occasion = "DEL 2"
home = "EC Bad Nauheim"
away = "EC Kassel Huskies"
city = "Bad Nauheim"
sublocation = "Colonel-Knight-Stadion"
extra_tags = ["del2", "kassel"]
caption_suffix = ", {headline}, {city}, {sublocation}, {date}"
''', encoding='utf-8')
    loaded = templates.load_file(path)
    assert loaded.headline == 'DEL 2 - EC Bad Nauheim gegen EC Kassel Huskies'
    assert loaded.teams == ['EC Bad Nauheim', 'EC Kassel Huskies']
    assert loaded.keywords == ['EC Bad Nauheim', 'EC Kassel Huskies', 'Bad Nauheim', 'del2', 'kassel']
    # Wieder gespeichert: Version 2 ohne occasion/home/away
    templates.save_file(loaded, path)
    text = path.read_text(encoding='utf-8')
    assert 'version = 2' in text and 'home' not in text
    assert templates.load_file(path) == loaded


def test_suffix_with_rights_fields_uses_image_value_when_template_is_empty():
    from captioner.scanner import Metadata
    from captioner.templates import MatchTemplate
    t = MatchTemplate(headline='DEL 2 - A gegen B', creator='Florian Dehn',
                      caption_suffix=', {headline}, Foto: {creator}, {copyright}, {source}')
    meta = Metadata(creator='Kamera-Artist', copyright='© 2026 Bild')
    values = t.field_values(meta)
    assert values['creator'] == 'Florian Dehn'        # Template gefuellt: gewinnt
    assert values['copyright'] == '© 2026 Bild'       # Template leer: Wert des Bildes
    assert t.compose_caption('Jubel', **values) == 'Jubel, DEL 2 - A gegen B, Foto: Florian Dehn, © 2026 Bild'


def test_fixed_date_replaces_capture_date(tmp_path):
    from captioner.templates import MatchTemplate, load_file, save_file
    t = MatchTemplate(name='Sonntag', headline='DEL 2 - A gegen B', caption_suffix=', {headline}, {date}', date='18.10.26')
    assert t.compose_caption('Jubel', '2026:10:13 19:30:00') == 'Jubel, DEL 2 - A gegen B, 18.10.26'
    assert t.date_mismatch('2026:10:13 19:30:00') == ('18.10.26', '13.10.26')
    assert t.date_mismatch('2026:10:18 19:30:00') is None
    save_file(t, tmp_path / 'sonntag.toml')
    assert load_file(tmp_path / 'sonntag.toml').date == '18.10.26'
    t.date = ''
    assert t.compose_caption('Jubel', '2026:10:13 19:30:00') == 'Jubel, DEL 2 - A gegen B, 13.10.26'
    assert t.date_mismatch('2026:10:13 19:30:00') is None


# --- Template aus einem beschrifteten Foto ---------------------------------------------

def test_derive_suffix_from_a_captioned_photo():
    from captioner.templates import derive_suffix
    values = {'headline': 'DEL 2 - EC Bad Nauheim gegen ESV Kaufbeuren', 'city': 'Bad Nauheim',
              'date': '20.02.24', 'creator': 'Florian Dehn', 'caption_writer': 'Florian Dehn'}
    caption = 'Hellvis (Maskottchen), DEL 2 - EC Bad Nauheim gegen ESV Kaufbeuren, Bad Nauheim, , 20.02.24'
    # leeres Segment nach der Stadt: dort stand der (leere) Ort
    assert derive_suffix(caption, values) == ', {headline}, {city}, {sublocation}, {date}'
    assert derive_suffix('Jubel, Florian Dehn', values) == ', {creator}'          # Vorrang: Fotograf
    assert derive_suffix('Jubel in Bad Nauheim', values) == ''                   # kein eigenes Segment
    assert derive_suffix('Jubel', values) == '' and derive_suffix('', values) == ''


def test_template_from_photo_metadata():
    from captioner.scanner import Metadata
    from captioner.templates import from_metadata
    meta = Metadata(
        headline='Impressionen aus der DEL 2 - EC Bad Nauheim gegen ESV Kaufbeuren',
        caption='-23- Max Muster (EC Bad Nauheim) jubelt, Impressionen aus der DEL 2 - EC Bad Nauheim gegen '
                'ESV Kaufbeuren, Bad Nauheim, , 20.02.24',
        keywords=['DEL2', 'EC Bad Nauheim', 'ESV Kaufbeuren', 'Eishockey', 'Max Muster', 'Bad Nauheim', 'Rote Teufel'],
        city='Bad Nauheim', country='Deutschland', creator='Florian Dehn', caption_writer='Florian Dehn',
        source='https://chuc.de', web_statement='https://chuc.de', category='Eishockey')
    template = from_metadata(meta, taken_at='2024:02:20 19:20:19', persons=['Max Muster'])
    assert template.name == template.headline == meta.headline
    assert (template.city, template.country, template.creator, template.category) == (
        'Bad Nauheim', 'Deutschland', 'Florian Dehn', 'Eishockey')
    assert template.caption_suffix == ', {headline}, {city}, {sublocation}, {date}'
    # Teams, Stadt und Personen kommen ohnehin dazu, sie gehoeren nicht in die Zusatz-Tags
    assert template.extra_tags == ['DEL2', 'Eishockey', 'Rote Teufel']
    assert template.date == '' and template.latitude is None
    # derselbe Anhang wie im Bild
    assert template.compose_caption('-23- Max Muster (EC Bad Nauheim) jubelt', '2024:02:20 19:20:19') == \
        meta.caption.replace(', , ', ', ')
