"""EXIF/IPTC fuer das Info-Panel der Grossansicht."""
import os

import pytest

from captioner import details, scanner
from captioner.exiftool import ExifTool, find_exiftool
from captioner.scanner import Metadata
from conftest import make_jpeg, requires_exiftool

# So liefert ExifTool die Werte einer Z9 (aus einem echten NEF abgelesen)
Z9 = {
    'SubSecDateTimeOriginal': '2026:03:01 17:17:55.40+02:00', 'Make': 'NIKON CORPORATION',
    'Model': 'NIKON Z 9', 'SerialNumber': '6003553', 'ShutterCount': 244295,
    'LensID': 'NIKKOR Z 70-200mm f/2.8 VR S', 'FocalLength': '100.0 mm',
    'FocalLengthIn35mmFormat': '100 mm', 'Aperture': 3.2, 'ShutterSpeed': '1/1600', 'ISO': 3200,
    'ExposureCompensation': 0, 'ExposureProgram': 'Manual', 'FocusMode': 'AF-C',
    'AFAreaMode': '3D-tracking', 'ImageSize': '8280x5520', 'Megapixels': 45.7,
    'Creator': 'Florian Dehn', 'Rights': 'Florian Dehn', 'State': 'Hessen',
    '_files': [('DSC_5912.NEF', 33_144_832), ('DSC_5912.XMP', 4839)],
}


def as_dict(sections):
    return {title: dict(rows) for title, rows in sections}


def test_sections_format_camera_values():
    result = as_dict(details.sections(Z9, Metadata()))
    camera = result['Aufnahme']
    assert camera['Aufgenommen'] == '01.03.2026 17:17:55,40'
    assert camera['Kamera'] == 'NIKON Z 9'            # Hersteller nicht doppelt
    assert camera['Blende'] == 'f/3.2'
    assert camera['Belichtungszeit'] == '1/1600 s'
    assert camera['Brennweite'] == '100.0 mm'          # KB-Wert nur, wenn er abweicht
    assert camera['Fokus'] == 'AF-C · 3D-tracking'
    assert camera['Auflösung'] == '8280 × 5520 (45,7 MP)'
    assert camera['Auslösungen'] == '244295'
    assert 'Belichtungskorrektur' not in camera        # 0 wird nicht angezeigt


def test_caption_fields_come_from_the_app_not_the_file():
    meta = Metadata(headline='DEL 2 - A gegen B', caption='Jubel', keywords=['A', 'B'],
                    rating=3, color_class=1, label='Red', tagged=True)
    result = as_dict(details.sections(Z9, meta))
    assert result['IPTC / XMP']['Titel'] == 'DEL 2 - A gegen B'
    assert result['IPTC / XMP']['Fotograf'] == 'Florian Dehn'
    assert result['Bewertung'] == {'Sterne': '★★★☆☆', 'Farbklasse': '1 (Red)', 'Tag': 'ja'}


def test_summary_line_under_the_image():
    raw = {'Make': 'NIKON CORPORATION', 'Model': 'NIKON Z 9', 'LensID': 'NIKKOR Z 70-200mm f/2.8 VR S',
           'FocalLength': '200.0 mm', 'ShutterSpeed': '1/500', 'Aperture': 2.8, 'ISO': 64,
           '_files': [('DSC_0001.NEF', 1), ('DSC_0001.JPG', 1), ('DSC_0001.xmp', 1)]}
    assert details.summary(raw) == ('NIKON Z 9 · NIKKOR Z 70-200mm f/2.8 VR S · 200 mm · 1/500 s · f/2.8 · ISO 64 · '
                                    'DSC_0001.NEF, DSC_0001.JPG')
    assert details.summary({'_files': [('a.jpg', 1)]}) == 'a.jpg' and details.summary({}) == ''


def test_files_and_empty_sections():
    sections = details.sections({'_files': Z9['_files']}, Metadata())
    titles = [title for title, _ in sections]
    assert 'Aufnahme' not in titles                    # leere Abschnitte fallen weg
    files = dict(sections)['Dateien']
    assert files[0] == ('Datei', 'DSC_5912.NEF · 33,1 MB')


def test_crop_sensor_shows_full_frame_equivalent():
    camera = as_dict(details.sections({'FocalLength': '50.0 mm', 'FocalLengthIn35mmFormat': '75 mm'},
                                      Metadata()))['Aufnahme']
    assert camera['Brennweite'] == '50.0 mm (KB 75 mm)'


@requires_exiftool
def test_read_prefers_sidecar_for_iptc_and_raw_for_camera(tmp_path):
    tool = ExifTool(find_exiftool()).start()
    try:
        jpg = make_jpeg(tmp_path / 'DSC_0001.JPG')
        tool.execute('-overwrite_original', '-Make=NIKON CORPORATION', '-Model=NIKON Z 9', '-ISO=6400',
                     '-IPTC:By-line=Aus dem JPG', str(jpg))
        (tmp_path / 'DSC_0001.NEF').write_bytes(b'kein echtes RAW')
        tool.execute('-XMP-dc:Creator=Aus dem Sidecar', '-o', str(tmp_path / 'DSC_0001.xmp'))
        item = scanner.scan(tmp_path)[0]
        raw = details.read(tool, item)
    finally:
        tool.close()
    # Kamera aus der RAW-Datei; die ist hier leer, also keine Kamera-Werte aus dem JPG
    assert 'Model' not in raw
    assert raw['Creator'] == 'Aus dem Sidecar'
    assert raw['By-line'] == 'Aus dem JPG'
    assert [name for name, _ in raw['_files']] == ['DSC_0001.NEF', 'DSC_0001.JPG', 'DSC_0001.xmp']


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@requires_exiftool
def test_info_panel_in_viewer(tmp_path):
    QtWidgets = pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtTest import QTest
    from captioner import config
    from captioner.ui.main_window import MainWindow
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    folder = tmp_path / 'fotos'
    folder.mkdir()
    jpg = make_jpeg(folder / 'a.jpg', size=(1200, 800))
    tool = ExifTool(find_exiftool()).start()
    tool.execute('-overwrite_original', '-Make=NIKON CORPORATION', '-Model=NIKON Z 9',
                 '-ExposureTime=1/1600', '-FNumber=3.2', '-ISO=3200', str(jpg))
    tool.close()
    w = MainWindow(config.Settings(roster_sources=[]), str(folder))
    try:
        w.scan_worker.wait(30000)
        app.processEvents()
        w.show()
        w.select_only(w.filtered[0])
        w.view.setCurrentIndex(w.model.index(0))
        w.open_viewer()
        for _ in range(200):
            app.processEvents()
            if 'NIKON Z 9' in w.viewer.info_panel.toPlainText():
                break
            QTest.qWait(20)
        text = w.viewer.info_panel.toPlainText()
        assert 'NIKON Z 9' in text and 'f/3.2' in text and '1/1600 s' in text and '3200' in text
        # ganz unten unter dem Bild: Kamera und Belichtung in einer Zeile, mit Dateiname
        assert 'NIKON Z 9 · 1/1600 s · f/3.2 · ISO 3200 · a.jpg' in w.viewer.info.text()

        w.set_rating(4)
        w.viewer.show_item(w.filtered[0])
        assert '★★★★☆' in w.viewer.info_panel.toPlainText()   # live, ohne neu zu lesen

        w.viewer.info_button.click()
        assert not w.viewer.info_panel.isVisible() and w.settings.viewer_info_panel is False
    finally:
        w.close()
