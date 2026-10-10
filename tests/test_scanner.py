from captioner import scanner
from conftest import make_jpeg


def touch(path):
    path.write_bytes(b'x')
    return path


def test_pairs_raw_and_jpeg_and_finds_uppercase_sidecar(tmp_path):
    touch(tmp_path / 'DSC_0001.NEF')
    make_jpeg(tmp_path / 'DSC_0001.JPG')
    touch(tmp_path / 'DSC_0001.XMP')
    touch(tmp_path / 'DSC_0002.NEF')
    make_jpeg(tmp_path / 'other.jpg')
    touch(tmp_path / 'notes.txt')
    touch(tmp_path / '.hidden.jpg')

    items = {i.name: i for i in scanner.scan(tmp_path)}
    assert set(items) == {'DSC_0001.JPG', 'DSC_0002.NEF', 'other.jpg'}

    pair = items['DSC_0001.JPG']
    assert pair.raw.name == 'DSC_0001.NEF'
    assert pair.kind == 'NEF+JPG'
    # vorhandenes Sidecar wird in seiner Schreibweise weiterbenutzt
    assert pair.sidecar_target.name == 'DSC_0001.XMP'

    # neues Sidecar: <basis>.xmp, nicht <basis>.NEF.xmp
    assert items['DSC_0002.NEF'].sidecar_target.name == 'DSC_0002.xmp'
    assert items['other.jpg'].sidecar_target is None


def test_dng_is_embedded_not_raw(tmp_path):
    touch(tmp_path / 'L100.DNG')
    item = scanner.scan(tmp_path)[0]
    assert item.raw is None
    assert item.embedded[0].name == 'L100.DNG'


def test_recursive(tmp_path):
    (tmp_path / 'sub').mkdir()
    make_jpeg(tmp_path / 'sub' / 'a.jpg')
    assert scanner.scan(tmp_path) == []
    assert len(scanner.scan(tmp_path, recursive=True)) == 1


def test_sort_by_capture_time_with_subseconds():
    a = scanner.Item(key='a', embedded=[], taken_at='2026:03:01 18:52:31.350')
    b = scanner.Item(key='b', embedded=[], taken_at='2026:03:01 18:52:31.035')
    c = scanner.Item(key='c', embedded=[], taken_at='')
    from pathlib import Path
    for item in (a, b, c):
        item.embedded = [Path(f'{item.key}.jpg')]
    items = [a, c, b]
    scanner.sort_items(items)
    assert [i.key for i in items] == ['b', 'a', 'c']


def test_image_folders_on_a_card(tmp_path):
    card = tmp_path / 'NIKON Z 9'
    for sub in ('DCIM/101NCZ_9', 'DCIM/100NCZ_9', '.Trashes/501'):
        (card / sub).mkdir(parents=True)
        make_jpeg(card / sub / 'DSC_0001.JPG')
    (card / 'MISC').mkdir()
    (card / 'MISC' / 'readme.txt').write_text('x')
    (card / 'DCIM' / '100NCZ_9' / 'DSC_0002.NEF').write_bytes(b'raw')
    assert scanner.image_folders(card) == [card / 'DCIM' / '100NCZ_9', card / 'DCIM' / '101NCZ_9']
    assert scanner.image_folders(card / 'DCIM' / '100NCZ_9') == [card / 'DCIM' / '100NCZ_9']
    assert scanner.image_folders(card / 'MISC') == []
    assert scanner.image_folders(tmp_path / 'fehlt') == []
