"""Bilder nach Schema umbenennen: rename (ohne Qt) und MainWindow.rename_folder (offscreen)."""
import datetime
import os
from pathlib import Path

import pytest

from captioner import rename, scanner
from conftest import make_jpeg, requires_exiftool


def folder_with_images(path):
    (path / 'DSC_0001.NEF').write_bytes(b'raw1')
    (path / 'DSC_0001.JPG').write_bytes(b'jpg1')
    (path / 'DSC_0001.xmp').write_text('<x/>')
    (path / 'DSC_0002.JPG').write_bytes(b'jpg2')
    (path / 'DSC_0003.NEF').write_bytes(b'raw3')
    return scanner.scan(path)


def test_names_follow_the_scheme():
    assert rename.stem('20261023', 'MEM', 'EPC', 1) == '20261023_MEM_EPC_001'
    assert rename.width(999) == 3 and rename.width(1000) == 4
    assert rename.stem('20261023', 'MEM', 'EPC', 7, rename.width(1200)) == '20261023_MEM_EPC_0007'
    assert rename.today() == datetime.date.today().strftime('%Y%m%d')


def test_validation():
    assert rename.valid_date('20261023')
    assert not rename.valid_date('261023') and not rename.valid_date('20261332') and not rename.valid_date('2026-10-2')
    assert rename.valid_code('MEM') and rename.valid_code('EC-BN')
    assert not rename.valid_code('') and not rename.valid_code('M/M') and not rename.valid_code('A B')


def test_group_gets_one_number_and_keeps_extensions(tmp_path):
    items = folder_with_images(tmp_path)
    rename.apply(rename.plan(items, '20261023', 'MEM', 'EPC'))
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        '20261023_MEM_EPC_001.JPG', '20261023_MEM_EPC_001.NEF', '20261023_MEM_EPC_001.xmp',
        '20261023_MEM_EPC_002.JPG', '20261023_MEM_EPC_003.NEF']
    assert (tmp_path / '20261023_MEM_EPC_001.NEF').read_bytes() == b'raw1'


def test_renaming_twice_swaps_names_without_clashing(tmp_path):
    items = folder_with_images(tmp_path)
    rename.apply(rename.plan(items, '20261023', 'MEM', 'EPC'))
    items = scanner.scan(tmp_path)
    items.reverse()      # andere Reihenfolge: 001 <-> 003
    moves = rename.plan(items, '20261023', 'MEM', 'EPC')
    assert rename.conflicts(moves) == []
    rename.apply(moves)
    assert (tmp_path / '20261023_MEM_EPC_001.NEF').read_bytes() == b'raw3'
    assert (tmp_path / '20261023_MEM_EPC_003.NEF').read_bytes() == b'raw1'
    assert not [p for p in tmp_path.iterdir() if p.name.startswith('.')]


def test_foreign_file_with_target_name_blocks(tmp_path):
    items = folder_with_images(tmp_path)
    (tmp_path / '20261023_MEM_EPC_002.JPG').write_bytes(b'other')
    items = [i for i in scanner.scan(tmp_path) if not i.name.startswith('2026')]
    moves = rename.plan(items, '20261023', 'MEM', 'EPC')
    assert [p.name for p in rename.conflicts(moves)] == ['20261023_MEM_EPC_002.JPG']
    with pytest.raises(rename.RenameError):
        rename.apply(moves)
    assert (tmp_path / 'DSC_0002.JPG').exists()


def test_failure_renames_everything_back(tmp_path, monkeypatch):
    items = folder_with_images(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    real, calls = rename.replace_file, []

    def flaky(source, target):
        calls.append(source)
        if len(calls) == 7:        # mitten im zweiten Schritt
            raise PermissionError('gesperrt')
        real(source, target)

    monkeypatch.setattr(rename, 'replace_file', flaky)
    with pytest.raises(rename.RenameError):
        rename.apply(rename.plan(items, '20261023', 'MEM', 'EPC'))
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# --- Hauptfenster ------------------------------------------------------------------

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='module')
def app():
    QtWidgets = pytest.importorskip('PySide6.QtWidgets')
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app):
    from captioner import config
    from captioner.ui.main_window import MainWindow
    w = MainWindow(config.Settings(roster_sources=[]))
    yield w
    w.writer.flush(30)
    w.close()


def scanned(tab):
    from test_tabs import wait_until
    return wait_until(lambda: not tab.scanning()) and wait_until(lambda: all(i.meta_loaded for i in tab.all_items))


@requires_exiftool
def test_menu_renames_folder_and_keeps_rating(window, tmp_path):
    folder = tmp_path / 'spiel'
    folder.mkdir()
    (folder / 'DSC_0001.NEF').write_bytes(b'raw1')
    make_jpeg(folder / 'DSC_0001.JPG')
    make_jpeg(folder / 'DSC_0002.JPG', color='blue')
    tab = window.open_folder(folder)
    assert scanned(tab)
    pair = next(i for i in window.filtered if i.raw)
    window.select_only(pair)
    window.set_rating(4)                                  # Sidecar, noch im Writer
    window.raw_captions.set(pair, '#x1# jubelt')
    file_menu = window.menuBar().actions()[0].menu()
    assert any(a.text() == 'Bilder umbenennen …' for a in file_menu.actions())

    window.rename_folder(('20261023', 'MEM', 'EPC'))
    assert window.settings.rename_home == 'MEM' and window.settings.rename_away == 'EPC'
    assert scanned(tab)
    names = sorted(p.name for p in folder.iterdir())
    assert len(names) == 4 and all(n.startswith('20261023_MEM_EPC_00') for n in names)
    assert {Path(n).suffix for n in names} == {'.NEF', '.JPG', '.xmp'}
    pair = next(i for i in tab.all_items if i.raw)
    assert pair.meta.rating == 4 and pair.sidecar.stem == pair.raw.stem
    assert window.raw_captions.get(pair) == '#x1# jubelt'
