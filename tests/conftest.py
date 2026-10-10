import shutil

import pytest
from PIL import Image

from captioner.roster import parse, Roster

ROSTER_TEXT = (
    "- Bietigheim Steelers -\n\n"
    "bi99\t-99- John Doe (Bietigheim Steelers)\n"
    "bi100\tTim Kehler (Coach Bietigheim Steelers)\n\n"
    "- EC Bad Nauheim -\n\n"
    "bn23\t-23- Marius Erk (EC Bad Nauheim)\n"
    "bn31\t-31- Dean Döge (EC Bad Nauheim)\n"
)


@pytest.fixture
def roster():
    r = Roster()
    for entry in parse(ROSTER_TEXT, 'test'):
        r.entries[entry.code] = entry
    return r


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv('CAPTIONER_HOME', str(tmp_path / 'home'))


requires_exiftool = pytest.mark.skipif(shutil.which('exiftool') is None, reason='ExifTool nicht installiert')


def make_jpeg(path, size=(600, 400), color='red'):
    Image.new('RGB', size, color).save(path, 'JPEG')
    return path
