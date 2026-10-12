import shutil
import sys

import pytest

from captioner import metadata, scanner
from captioner.exiftool import ExifTool, find_exiftool
from captioner.scanner import Metadata
from conftest import make_jpeg, requires_exiftool

pytestmark = requires_exiftool

META = Metadata(
    headline='DEL 2 - EC Bad Nauheim gegen Bietigheim Steelers',
    caption='Zweikampf -99- John Doe (Bietigheim Steelers) gegen -31- Dean Döge (EC Bad Nauheim)',
    keywords=['EC Bad Nauheim', 'Dean Döge'],
    city='Bad Nauheim', sublocation='Colonel-Knight-Stadion', rating=4, label='Green')


@pytest.fixture
def tool():
    t = ExifTool(find_exiftool()).start()
    yield t
    t.close()


def read(tool, path, *tags):
    return tool.json('-charset', 'iptc=UTF8', *tags, str(path))[0]


def test_jpeg_gets_iptc_xmp_and_exif(tool, tmp_path):
    path = make_jpeg(tmp_path / 'a.jpg')
    path.chmod(0o640)
    item = scanner.scan(tmp_path)[0]
    before = metadata.image_data_hash(tool, path)

    metadata.write_item(tool, item, META)

    record = read(tool, path, '-IPTC:all', '-XMP:all', '-EXIF:ImageDescription')
    assert record['Headline'] == META.headline
    assert record['Caption-Abstract'] == META.caption
    assert record['ImageDescription'] == META.caption
    assert record['Keywords'] == META.keywords
    assert record['Subject'] == META.keywords
    assert record['CodedCharacterSet'] == 'UTF8'
    assert record['Rating'] == 4
    assert record['Label'] == 'Green'
    assert metadata.image_data_hash(tool, path) == before
    if sys.platform != 'win32':  # Windows kennt keine POSIX-Rechte
        assert path.stat().st_mode & 0o777 == 0o640
    assert not list(tmp_path.glob('.*captioner-tmp*'))


def test_written_fields_are_read_back(tool, tmp_path):
    make_jpeg(tmp_path / 'a.jpg')
    item = scanner.scan(tmp_path)[0]
    metadata.write_item(tool, item, META)
    item = scanner.scan(tmp_path)[0]
    list(metadata.read_items(tool, [item]))
    assert item.meta == META


def test_raw_gets_sidecar_and_is_not_touched(tool, tmp_path):
    raw = tmp_path / 'DSC_0001.NEF'
    raw.write_bytes(b'not really a raw file')
    item = scanner.scan(tmp_path)[0]

    written = metadata.write_item(tool, item, META)

    assert [p.name for p in written] == ['DSC_0001.xmp']
    assert raw.read_bytes() == b'not really a raw file'
    record = read(tool, tmp_path / 'DSC_0001.xmp', '-XMP:all')
    assert record['Description'] == META.caption
    assert record['Subject'] == META.keywords
    assert record['Rating'] == 4


def test_existing_sidecar_keeps_its_name_and_other_content(tool, tmp_path):
    (tmp_path / 'DSC_0001.NEF').write_bytes(b'raw')
    sidecar = tmp_path / 'DSC_0001.XMP'
    tool.execute('-XMP-crs:Exposure2012=+0.50', '-o', str(sidecar))
    item = scanner.scan(tmp_path)[0]

    metadata.write_item(tool, item, META)

    assert sorted(p.name for p in tmp_path.iterdir()) == ['DSC_0001.NEF', 'DSC_0001.XMP']
    record = read(tool, sidecar, '-XMP:all')
    assert record['Exposure2012'] == '+0.50'
    assert record['Headline'] == META.headline


def test_raw_plus_jpeg_gets_both(tool, tmp_path):
    (tmp_path / 'DSC_0001.NEF').write_bytes(b'raw')
    make_jpeg(tmp_path / 'DSC_0001.JPG')
    item = scanner.scan(tmp_path)[0]
    written = metadata.write_item(tool, item, META)
    assert sorted(p.name for p in written) == ['DSC_0001.JPG', 'DSC_0001.xmp']


def test_clearing_keywords_and_label(tool, tmp_path):
    path = make_jpeg(tmp_path / 'a.jpg')
    item = scanner.scan(tmp_path)[0]
    metadata.write_item(tool, item, META)
    metadata.write_item(tool, item, Metadata(headline='x'))
    record = read(tool, path, '-IPTC:all', '-XMP:all')
    assert 'Keywords' not in record and 'Subject' not in record and 'Label' not in record


def test_limits_are_bytes_not_characters():
    meta = Metadata(city='Ö' * 17)  # 34 Bytes > 32
    assert metadata.validate(meta)
    assert not metadata.validate(Metadata(city='Ö' * 16))


def test_invalid_metadata_is_not_written(tool, tmp_path):
    path = make_jpeg(tmp_path / 'a.jpg')
    item = scanner.scan(tmp_path)[0]
    with pytest.raises(metadata.WriteError):
        metadata.write_item(tool, item, Metadata(keywords=['x' * 65]))
    assert 'Keywords' not in read(tool, path, '-IPTC:all')


def test_object_name_is_truncated_on_char_boundary():
    assert metadata.truncate_bytes('ä' * 40, 64) == 'ä' * 32


def test_tile_is_rotated_even_before_metadata_is_loaded(tool, tmp_path):
    """Regression: Kacheln entstanden vor dem Metadaten-Scan mit Ausrichtung 1."""
    from captioner import previews
    path = make_jpeg(tmp_path / 'a.jpg', size=(600, 400))
    tool.execute('-overwrite_original', '-n', '-Orientation=6', str(path))
    item = scanner.scan(tmp_path)[0]
    assert not item.meta_loaded and item.orientation == 1
    image = previews.render(tool, item, 320)
    assert image.size[0] < image.size[1]


def test_color_class_and_tag(tool, tmp_path):
    (tmp_path / 'DSC_0001.NEF').write_bytes(b'raw')
    item = scanner.scan(tmp_path)[0]
    meta = Metadata(color_class=2, label='Yellow', tagged=True)
    metadata.write_item(tool, item, meta)
    record = read(tool, tmp_path / 'DSC_0001.xmp', '-n', '-XMP:all')
    assert record['ColorClass'] == 2 and record['Label'] == 'Yellow' and record['Tagged'] is True

    item = scanner.scan(tmp_path)[0]
    list(metadata.read_items(tool, [item]))
    assert item.meta.color_class == 2 and item.meta.tagged

    metadata.write_item(tool, item, Metadata())
    record = read(tool, tmp_path / 'DSC_0001.xmp', '-n', '-XMP:all')
    assert 'ColorClass' not in record and record['Tagged'] is False


def test_gps_is_written_embedded_and_read_back_with_sign(tool, tmp_path):
    path = make_jpeg(tmp_path / 'a.jpg')
    item = scanner.scan(tmp_path)[0]
    meta = Metadata(city='Sydney', latitude=-33.8568, longitude=151.2153, gps_changed=True)
    metadata.write_item(tool, item, meta)
    record = read(tool, path, '-n', '-EXIF:GPSLatitudeRef', '-EXIF:GPSLongitudeRef', '-XMP-exif:all')
    assert record['GPSLatitudeRef'] == 'S' and record['GPSLongitudeRef'] == 'E'
    item = scanner.scan(tmp_path)[0]
    list(metadata.read_items(tool, [item]))
    assert (item.meta.latitude, item.meta.longitude) == pytest.approx((-33.8568, 151.2153))
    assert not item.meta.gps_changed


def test_gps_in_sidecar_and_camera_gps_in_raw_counts(tool, tmp_path):
    (tmp_path / 'DSC_0001.NEF').write_bytes(b'raw')
    item = scanner.scan(tmp_path)[0]
    metadata.write_item(tool, item, Metadata(headline='x', latitude=50.36335, longitude=-8.74107, gps_changed=True))
    record = read(tool, tmp_path / 'DSC_0001.xmp', '-n', '-GPSLatitude', '-GPSLongitude')
    assert (record['GPSLatitude'], record['GPSLongitude']) == pytest.approx((50.36335, -8.74107))

    # Kamera-GPS im JPG eines RAW+JPG-Paares, Beschriftung im Sidecar: GPS wird trotzdem erkannt
    make_jpeg(tmp_path / 'DSC_0002.JPG')
    tool.execute('-overwrite_original', '-EXIF:GPSLatitude=48.1', '-EXIF:GPSLatitudeRef=N',
                 '-EXIF:GPSLongitude=11.5', '-EXIF:GPSLongitudeRef=E', str(tmp_path / 'DSC_0002.JPG'))
    (tmp_path / 'DSC_0002.NEF').write_bytes(b'raw')
    tool.execute('-XMP-photoshop:Headline=Titel', '-o', str(tmp_path / 'DSC_0002.xmp'))
    item = next(i for i in scanner.scan(tmp_path) if i.name.startswith('DSC_0002'))
    list(metadata.read_items(tool, [item]))
    assert item.meta.headline == 'Titel'
    assert (item.meta.latitude, item.meta.longitude) == pytest.approx((48.1, 11.5))


def test_gps_is_not_rewritten_unless_changed(tool, tmp_path):
    path = make_jpeg(tmp_path / 'a.jpg')
    tool.execute('-overwrite_original', '-EXIF:GPSLatitude=48.123456789', '-EXIF:GPSLatitudeRef=N',
                 '-EXIF:GPSLongitude=11.5', '-EXIF:GPSLongitudeRef=E', str(path))
    before = read(tool, path, '-EXIF:GPSLatitude')['GPSLatitude']
    item = scanner.scan(tmp_path)[0]
    list(metadata.read_items(tool, [item]))
    metadata.write_item(tool, item, Metadata(headline='x', latitude=1.0, longitude=2.0))  # gps_changed=False
    assert read(tool, path, '-EXIF:GPSLatitude')['GPSLatitude'] == before
    assert 'GPSLatitude' not in read(tool, path, '-XMP-exif:all')


RIGHTS = dict(state='Hessen', country='Deutschland', creator='Florian Dehn', authors_position='Fotograf',
              caption_writer='Florian Dehn', copyright='© 2026 Florian Dehn',
              web_statement='https://example.org/lizenz', source='chuc.de', category='Sport')


def test_rights_go_into_xmp_iptc_and_exif(tool, tmp_path):
    import dataclasses
    path = make_jpeg(tmp_path / 'a.jpg')
    item = scanner.scan(tmp_path)[0]
    metadata.write_item(tool, item, dataclasses.replace(META, **RIGHTS))
    record = tool.json('-G', '-charset', 'iptc=UTF8', '-XMP:all', '-IPTC:all', '-EXIF:Artist', '-EXIF:Copyright',
                       str(path))[0]
    assert record['XMP:Creator'] == 'Florian Dehn' and record['IPTC:By-line'] == 'Florian Dehn'
    assert record['EXIF:Artist'] == 'Florian Dehn'
    assert record['XMP:Rights'] == record['IPTC:CopyrightNotice'] == record['EXIF:Copyright'] == '© 2026 Florian Dehn'
    assert record['XMP:WebStatement'] == 'https://example.org/lizenz' and record['XMP:Marked'] is True
    assert record['XMP:AuthorsPosition'] == record['IPTC:By-lineTitle'] == 'Fotograf'
    assert record['XMP:CaptionWriter'] == record['IPTC:Writer-Editor'] == 'Florian Dehn'
    assert record['XMP:Source'] == record['IPTC:Source'] == 'chuc.de'
    assert record['XMP:State'] == record['IPTC:Province-State'] == 'Hessen'
    assert record['XMP:Country'] == record['IPTC:Country-PrimaryLocationName'] == 'Deutschland'
    assert record['XMP:Category'] == 'Sport' and 'IPTC:Category' not in record  # IIM nur 3 Zeichen
    item = scanner.scan(tmp_path)[0]
    list(metadata.read_items(tool, [item]))
    assert {name: getattr(item.meta, name) for name in RIGHTS} == RIGHTS


def test_camera_artist_and_copyright_survive_saving(tool, tmp_path):
    """Kamera schreibt Artist/Copyright in RAW und JPG; Speichern ohne Template darf sie nicht leeren."""
    (tmp_path / 'DSC_0001.NEF').write_bytes(b'raw')
    jpg = make_jpeg(tmp_path / 'DSC_0001.JPG')
    tool.execute('-overwrite_original', '-EXIF:Artist=Kamera Fotograf', '-EXIF:Copyright=Kamera ©', str(jpg))
    item = scanner.scan(tmp_path)[0]
    list(metadata.read_items(tool, [item]))
    assert (item.meta.creator, item.meta.copyright) == ('Kamera Fotograf', 'Kamera ©')
    import dataclasses
    metadata.write_item(tool, item, dataclasses.replace(item.meta, headline='Titel'))
    assert read(tool, jpg, '-EXIF:Artist')['Artist'] == 'Kamera Fotograf'
    sidecar = read(tool, tmp_path / 'DSC_0001.xmp', '-XMP:all')
    assert sidecar['Creator'] == 'Kamera Fotograf' and sidecar['Rights'] == 'Kamera ©'


def test_rights_limits_are_checked():
    problems = metadata.validate(Metadata(creator='x' * 33, copyright='© ' + 'y' * 140))
    assert any(p.startswith('Fotograf') for p in problems) and any(p.startswith('Copyright') for p in problems)


def test_short_category_also_goes_into_iptc(tool, tmp_path):
    path = make_jpeg(tmp_path / 'a.jpg')
    item = scanner.scan(tmp_path)[0]
    metadata.write_item(tool, item, Metadata(headline='x', category='SPO'))
    record = tool.json('-G', '-XMP-photoshop:Category', '-IPTC:Category', str(path))[0]
    assert record['XMP:Category'] == record['IPTC:Category'] == 'SPO'


def test_locked_file_is_retried_then_reported(tool, tmp_path, monkeypatch):
    """Windows: Explorer/Virenscanner sperren kurz; erst nachfassen, dann klar melden."""
    from captioner import files
    path = make_jpeg(tmp_path / 'a.jpg')
    item = scanner.scan(tmp_path)[0]
    calls = []
    real_replace = files.os.replace

    def locked_twice(source, target):
        calls.append(target)
        if len(calls) <= 2:
            raise PermissionError(32, 'Der Prozess kann nicht auf die Datei zugreifen')
        real_replace(source, target)

    monkeypatch.setattr(files, 'ATTEMPTS', 3)
    monkeypatch.setattr(files, 'DELAY', 0)
    monkeypatch.setattr(files.os, 'replace', locked_twice)
    metadata.write_item(tool, item, META)
    assert len(calls) == 3 and read(tool, path, '-IPTC:Headline')['Headline'] == META.headline

    calls.clear()

    def always_locked(source, target):
        calls.append(target)
        raise PermissionError(32, 'gesperrt')

    monkeypatch.setattr(files.os, 'replace', always_locked)
    with pytest.raises(metadata.WriteError, match='anderen Programm'):
        metadata.write_item(tool, item, Metadata(headline='DEL 2 - X gegen Y'))
    assert len(calls) == 3
    assert read(tool, path, '-IPTC:Headline')['Headline'] == META.headline   # Original unangetastet
    assert not list(tmp_path.glob('.*captioner-tmp*'))
