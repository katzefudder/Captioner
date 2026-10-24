"""Template from photo: a template from an image's caption (e.g. from Lightroom)."""
import os
import subprocess
import time

import pytest

from conftest import make_jpeg, requires_exiftool

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')

pytestmark = requires_exiftool

HEADLINE = 'Impressionen aus der DEL 2 - EC Bad Nauheim gegen ESV Kaufbeuren'


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait_until(condition, timeout=30.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)
    return condition()


@pytest.fixture
def window(app, tmp_path):
    from captioner import config
    from captioner.exiftool import find_exiftool
    from captioner.ui.main_window import MainWindow
    folder = tmp_path / 'fotos'
    folder.mkdir()
    photo = folder / 'L1001167.JPG'
    make_jpeg(photo)
    # as Lightroom captioned the sample file
    subprocess.run([find_exiftool(''), '-overwrite_original', '-charset', 'iptc=UTF8', '-codedcharacterset=utf8',
                    f'-XMP-photoshop:Headline={HEADLINE}', f'-IPTC:Headline={HEADLINE}',
                    f'-XMP-dc:Description=Hellvis (Maskottchen EC BadNauheim), {HEADLINE}, Bad Nauheim, , 20.02.24',
                    '-XMP-dc:Subject=DEL2', '-XMP-dc:Subject=EC Bad Nauheim', '-XMP-dc:Subject=ESV Kaufbeuren',
                    '-XMP-dc:Subject=Eishockey', '-XMP-dc:Subject=Colonel-Knight-Stadion',
                    '-XMP-photoshop:City=Bad Nauheim', '-XMP-photoshop:Country=Deutschland',
                    '-XMP-dc:Creator=Florian Dehn', '-XMP-photoshop:CaptionWriter=Florian Dehn',
                    '-XMP-photoshop:Source=https://chuc.de', '-XMP-xmpRights:WebStatement=https://chuc.de',
                    '-XMP-photoshop:Category=Eishockey', '-XMP-photoshop:Credit=Florian Dehn',
                    '-XMP-iptcCore:CountryCode=DEU', '-XMP-iptcCore:CreatorWorkEmail=info@chuc.de', '-DateTimeOriginal=2024:02:20 19:20:19', str(photo)],
                   check=True, capture_output=True)
    w = MainWindow(config.Settings(roster_sources=[]), str(folder))
    assert wait_until(lambda: not w.tab.scanning() and w.filtered and w.filtered[0].meta_loaded)
    yield w
    w.writer.flush(30)
    w.close()


def test_template_from_photo_opens_the_dialog_and_saves_on_ok(window, monkeypatch):
    from captioner.ui import main_window
    shown = []

    class Dialog:
        places_changed = False

        def __init__(self, template, places, parent):
            shown.append(template)

        def exec(self):
            return True

        def template(self):
            return shown[0]

    monkeypatch.setattr(main_window, 'TemplateDialog', Dialog)
    window.select_only(window.filtered[0])
    window.template_from_photo()
    template = shown[0]
    assert template.name == template.headline == HEADLINE
    assert (template.city, template.country, template.creator, template.caption_writer, template.source,
            template.web_statement, template.category) == (
        'Bad Nauheim', 'Deutschland', 'Florian Dehn', 'Florian Dehn', 'https://chuc.de', 'https://chuc.de', 'Eishockey')
    assert (template.credit, template.country_code, template.contact_email) == ('Florian Dehn', 'DEU', 'info@chuc.de')
    assert template.caption_suffix == ', {headline}, {city}, {sublocation}, {date}'
    assert template.extra_tags == ['DEL2', 'Eishockey', 'Colonel-Knight-Stadion']
    # saved and selected
    assert template.path and window.editor.template.path == template.path


def test_template_from_photo_needs_a_captioned_selection(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda parent, title, text: messages.append(text))
    window.deselect_all()
    window.template_from_photo()
    assert messages == ['Bitte zuerst ein beschriftetes Foto auswählen.']
