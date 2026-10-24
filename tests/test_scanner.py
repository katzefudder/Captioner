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
    # an existing sidecar keeps being used in its spelling
    assert pair.sidecar_target.name == 'DSC_0001.XMP'

    # new sidecar: <base>.xmp, not <base>.NEF.xmp
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


def test_camera_labels_distinguish_two_identical_bodies():
    from captioner.scanner import Item
    def item(model, serial):
        i = Item(key=f'{model}{serial}')
        i.camera, i.serial = model, serial
        return i
    labels = scanner.camera_labels([item('NIKON Z 9', '3001234'), item('NIKON Z 9', '3005678'),
                                    item('NIKON Z 8', '2000001'), item('', '')])
    assert labels == {('NIKON Z 8', '2000001'): 'NIKON Z 8', ('NIKON Z 9', '3001234'): 'NIKON Z 9 · …1234',
                      ('NIKON Z 9', '3005678'): 'NIKON Z 9 · …5678'}


def test_text_search_and_time_of_day(tmp_path):
    from captioner.scanner import Item, Metadata
    item = Item(key='a', embedded=[tmp_path / 'DSC_0001.JPG'], taken_at='2026:10:11 19:42:07.120')
    item.meta = Metadata(headline='DEL 2 - EC Bad Nauheim gegen Kassel', caption='Torjubel Erk',
                         keywords=['Eishockey'])
    assert scanner.matches_text(item, '')
    assert scanner.matches_text(item, 'jubel erk')          # all words, case-insensitive
    assert scanner.matches_text(item, 'dsc_0001 kassel')
    assert not scanner.matches_text(item, 'jubel regensburg')
    assert scanner.time_of_day(item) == '19:42'
    item.taken_at = ''
    assert scanner.time_of_day(item) == ''
