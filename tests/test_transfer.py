"""Copying between folders: groups, conflicts, renaming, no half files."""
import pytest

from captioner import transfer


def files(folder, *names, content=b'x'):
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        path = folder / name
        path.write_bytes(content + name.encode())
        paths.append(path)
    return paths


def test_raw_jpeg_and_sidecar_form_one_group(tmp_path):
    paths = files(tmp_path / 'a', 'DSC_0001.NEF', 'DSC_0001.JPG', 'DSC_0001.xmp', 'DSC_0002.NEF')
    groups = transfer.group_files(paths + [tmp_path / 'a' / 'fehlt.NEF'])
    assert [[p.name for p in g.files] for g in groups] == [
        ['DSC_0001.NEF', 'DSC_0001.JPG', 'DSC_0001.xmp'], ['DSC_0002.NEF']]
    assert groups[0].name == 'DSC_0001.NEF'


def test_copy_keeps_source_and_leaves_no_part_files(tmp_path):
    source = files(tmp_path / 'karte1', 'DSC_0001.NEF', 'DSC_0001.xmp')
    group = transfer.group_files(source)[0]
    (tmp_path / 'karte2').mkdir()
    copied = transfer.copy_group(group, tmp_path / 'karte2')
    assert [p.name for p in copied] == ['DSC_0001.NEF', 'DSC_0001.xmp']
    assert (tmp_path / 'karte2' / 'DSC_0001.NEF').read_bytes() == source[0].read_bytes()
    assert all(p.exists() for p in source)
    assert sorted(p.name for p in (tmp_path / 'karte2').iterdir()) == ['DSC_0001.NEF', 'DSC_0001.xmp']


def test_conflict_needs_a_decision(tmp_path):
    group = transfer.group_files(files(tmp_path / 'a', 'DSC_0001.NEF', 'DSC_0001.JPG'))[0]
    files(tmp_path / 'b', 'DSC_0001.JPG', content=b'alt')
    assert [p.name for p in group.conflicts(tmp_path / 'b')] == ['DSC_0001.JPG']
    with pytest.raises(transfer.TransferError):
        transfer.copy_group(group, tmp_path / 'b')
    assert transfer.copy_group(group, tmp_path / 'b', transfer.SKIP) == []
    assert (tmp_path / 'b' / 'DSC_0001.JPG').read_bytes() == b'altDSC_0001.JPG'
    assert not (tmp_path / 'b' / 'DSC_0001.NEF').exists()


def test_rename_keeps_the_pair_together(tmp_path):
    group = transfer.group_files(files(tmp_path / 'a', 'DSC_0001.NEF', 'DSC_0001.JPG', 'DSC_0001.xmp'))[0]
    files(tmp_path / 'b', 'DSC_0001.NEF', 'DSC_0001-2.xmp')  # -2 is already partly taken
    copied = transfer.copy_group(group, tmp_path / 'b', transfer.RENAME)
    assert [p.name for p in copied] == ['DSC_0001-3.NEF', 'DSC_0001-3.JPG', 'DSC_0001-3.xmp']
    assert (tmp_path / 'b' / 'DSC_0001.NEF').read_bytes() == b'xDSC_0001.NEF'


def test_replace_overwrites(tmp_path):
    group = transfer.group_files(files(tmp_path / 'a', 'DSC_0001.NEF', content=b'neu'))[0]
    files(tmp_path / 'b', 'DSC_0001.NEF', content=b'alt')
    transfer.copy_group(group, tmp_path / 'b', transfer.REPLACE)
    assert (tmp_path / 'b' / 'DSC_0001.NEF').read_bytes() == b'neuDSC_0001.NEF'


def test_same_folder_is_detected(tmp_path):
    group = transfer.group_files(files(tmp_path / 'a', 'DSC_0001.NEF'))[0]
    assert transfer.same_folder(group, tmp_path / 'a')
    assert transfer.same_folder(group, str(tmp_path / 'a' / '.' ))
    assert not transfer.same_folder(group, tmp_path / 'b')


def test_failed_copy_removes_the_part_file(tmp_path, monkeypatch):
    group = transfer.group_files(files(tmp_path / 'a', 'DSC_0001.NEF'))[0]
    (tmp_path / 'b').mkdir()

    def broken_copy(source, target):
        open(target, 'wb').write(b'halb')
        raise OSError('Karte voll')

    monkeypatch.setattr(transfer.shutil, 'copy2', broken_copy)
    with pytest.raises(OSError):
        transfer.copy_group(group, tmp_path / 'b')
    assert list((tmp_path / 'b').iterdir()) == []
