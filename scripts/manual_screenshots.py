"""
Screenshots for the manuals, taken offscreen from the real app: German into
docs/manual/img, English into docs/manual/img/en.

Sample photos, roster and template are created here; settings and caches live in a
separate CAPTIONER_HOME, the real ones stay untouched. Needs ExifTool.

    poetry run python scripts/manual_screenshots.py [de|en]
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix='captioner-manual-'))
os.environ['CAPTIONER_HOME'] = str(HOME / 'home')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from PIL.TiffImagePlugin import IFDRational  # noqa: E402
from PySide6.QtCore import QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LANGUAGE = sys.argv[1] if len(sys.argv) > 1 else 'de'
OUT = ROOT / 'docs' / 'manual' / 'img' / ('' if LANGUAGE == 'de' else LANGUAGE)
sys.path.insert(0, str(ROOT))

ROSTER = """- Bietigheim Steelers -

bi99\t-99- John Doe (Bietigheim Steelers)
bi17\t-17- Erik Beispiel (Bietigheim Steelers)
bi1\t-1- Lars Probe (Bietigheim Steelers)

- EC Bad Nauheim -

bn23\t-23- Max Muster (EC Bad Nauheim)
bn9\t-9- Tom Platzhalter (EC Bad Nauheim)
bn30\t-30- Jan Vorlage (EC Bad Nauheim)

- Teams -

bn\tEC Bad Nauheim
bi\tBietigheim Steelers
"""

TEMPLATE = """format = "captioner-template"
version = 2
name = "{name}"
headline = ""
city = "Bad Nauheim"
sublocation = "Colonel-Knight-Stadion"
state = "{state}"
country = "{country}"
extra_tags = ["{sport}", "DEL2"]
caption_suffix = ", {{headline}}, {{city}}, {{sublocation}}, {{date}}"
date = ""
creator = "Erika Beispiel"
copyright = "© 2026 Erika Beispiel"
"""

# Sample texts per language. The headline keeps "gegen": person recognition reads exactly that.
TEXTS = {
    'de': dict(name='DEL 2 Heimspiele', state='Hessen', country='Deutschland', sport='Eishockey',
               captions=['Bully #bn9# gegen #bi17#', 'Zweikampf #bn30# gegen #bi1#',
                         'Zweikampf an der Bande, #bi17# und #bn23#'],
               shown='Zweikampf zwischen #bn23# und #bi99# vor dem Tor',
               find='Zweikampf', replacement='Duell', own_roster='~/Dokumente/Roster/eigene.txt'),
    'en': dict(name='DEL 2 home games', state='Hesse', country='Germany', sport='Ice hockey',
               captions=['Face-off #bn9# against #bi17#', 'Battle #bn30# against #bi1#',
                         'Battle along the boards, #bi17# and #bn23#'],
               shown='Battle between #bn23# and #bi99# in front of the goal',
               find='Battle', replacement='Duel', own_roster='~/Documents/Roster/own.txt'),
}[LANGUAGE]

# Ice surface with players as colored blobs: enough for the gallery to look like photos
JERSEYS = [(200, 30, 40), (240, 240, 245), (20, 60, 150), (250, 200, 0)]


def make_photo(path, seed):
    width, height = 1200, 800
    image = Image.new('RGB', (width, height), (215, 228, 238))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width, 180], fill=(60, 70, 90))                       # boards, crowd
    for x in range(0, width, 22):
        draw.ellipse([x, 60 + (x * seed) % 50, x + 16, 76 + (x * seed) % 50], fill=(110 + seed * 7 % 80, 90, 80))
    draw.rectangle([0, 180, width, 200], fill=(250, 250, 250))
    draw.line([0, 520, width, 520], fill=(200, 40, 40), width=8)                # red line
    draw.ellipse([width // 2 - 140, 450, width // 2 + 140, 590], outline=(40, 80, 180), width=5)
    for n in range(2 + seed % 3):
        x = 180 + (seed * 173 + n * 290) % (width - 360)
        y = 330 + (seed * 37 + n * 61) % 180
        color = JERSEYS[(seed + n) % len(JERSEYS)]
        draw.ellipse([x - 10, y + 210, x + 90, y + 235], fill=(160, 175, 190))  # shadow
        draw.rounded_rectangle([x, y, x + 80, y + 150], 30, fill=color)
        draw.ellipse([x + 18, y - 45, x + 62, y + 5], fill=(30, 30, 30))       # helmet
        draw.rectangle([x + 10, y + 150, x + 70, y + 215], fill=(25, 25, 30))
        draw.line([x + 75, y + 90, x + 150, y + 220], fill=(80, 50, 20), width=7)  # stick
    image = image.filter(ImageFilter.GaussianBlur(1.2))
    exif = Image.Exif()
    exif[0x010f], exif[0x0110] = 'NIKON CORPORATION', 'NIKON Z 9'
    details = exif.get_ifd(0x8769)
    details[0x9003] = f'2026:10:18 18:{30 + seed // 6:02d}:{(seed * 7) % 60:02d}'   # DateTimeOriginal
    details[0x829a] = IFDRational(1, 1000)                                         # exposure time
    details[0x829d] = IFDRational(28, 10)                                          # aperture
    details[0x8827] = 3200                                                         # ISO
    details[0x920a] = IFDRational(200, 1)                                          # focal length
    details[0xa431] = '6012345'                                                    # serial number
    image.save(path, 'JPEG', quality=88, exif=exif)


def wait(condition, timeout=30):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    QApplication.processEvents()


def settle(seconds=0.4):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.02)


def save(widget, name):
    OUT.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    pixmap.setDevicePixelRatio(1)
    pixmap.save(str(OUT / f'{name}.png'))
    print('  ', name, pixmap.width(), 'x', pixmap.height())


def main():
    folder = HOME / 'Karte 1' / '100NCZ_9'
    second = HOME / 'Karte 2' / '100NCZ_9'
    for target, start, count in ((folder, 1, 12), (second, 20, 4)):
        target.mkdir(parents=True)
        for n in range(start, start + count):
            make_photo(target / f'DSC_{n:04d}.JPG', n)
    roster = HOME / 'roster.txt'
    roster.write_text(ROSTER, encoding='utf-8')

    app = QApplication([])
    from captioner import config, i18n
    i18n.setup(LANGUAGE)
    template = config.templates_dir() / 'del2-heimspiele.toml'
    template.write_text(TEMPLATE.format(**TEXTS), encoding='utf-8')
    settings = config.Settings(roster_sources=[str(roster)], last_template=str(template), check_updates=False,
                               language=LANGUAGE)

    from captioner.ui.main_window import MainWindow
    window = MainWindow(settings, str(folder))
    window.menuBar().hide()          # on the Mac the menu is at the top of the screen
    window.resize(1500, 920)
    window.show()
    wait(lambda: not window.tab.scanning() and len(window.filtered) == 12
         and all(item.meta_loaded for item in window.all_items))
    window.open_folder(str(second), new_tab=True)
    wait(lambda: not window.tab.scanning() and window.filtered)
    window.tabs.setCurrentIndex(0)
    wait(lambda: window.roster.entries)

    # ratings, colors, tags as after reviewing
    marks = {0: (3, 3, True), 1: (0, 0, False), 2: (4, 2, True), 3: (5, 3, True), 5: (2, 1, False),
             6: (0, 0, True), 8: (3, 4, False), 9: (1, 0, False), 11: (4, 3, True)}
    for index, (rating, color, tagged) in marks.items():
        window.select_only(window.filtered[index])
        window.set_rating(rating)
        window.set_color_class(color)
        window.set_tag(tagged)
    window.writer.flush(60)

    # a few images already captioned (for find and replace)
    editor = window.editor
    editor.headline.setText('DEL 2 - EC Bad Nauheim gegen Bietigheim Steelers')
    for index, caption in zip((0, 2, 11), TEXTS['captions']):
        window.select_only(window.filtered[index])
        editor.caption.setPlainText(caption)
        settle(0.3)
        editor.submit(0)
    window.writer.flush(60)

    # paths as from the memory card instead of the temp folder
    window.tabs.setTabText(0, 'NIKON Z 9 › 100NCZ_9')
    window.tabs.setTabText(1, 'NIKON Z 6 › 100NCZ_6')
    window.select_only(window.filtered[3])
    editor.headline.setText('DEL 2 - EC Bad Nauheim gegen Bietigheim Steelers')
    editor.caption.setPlainText(TEXTS['shown'])
    editor.headline.setCursorPosition(0)
    settle(1.5)                       # tiles, preview, highlighting
    window.folder_label.setText('/Volumes/NIKON Z 9/DCIM/100NCZ_9 – '
                                + i18n.ngettext('{count} Bild', '{count} Bilder', 12).format(count=12))
    save(window, 'hauptfenster')

    # context menu of a tile
    menu = window.gallery_menu(window)
    menu.popup(QPoint(0, 0))
    settle()
    save(menu, 'kontextmenue')
    menu.close()

    # preview with info panel
    window.editor.caption.setPlainText('')
    window.view.setFocus()
    window.open_viewer()
    window.viewer.resize(1400, 860)
    wait(lambda: window.viewer._image is not None, 15)
    settle(1.5)
    save(window.viewer, 'grossansicht')
    window.viewer.close()

    # dialogs
    from captioner.ui.dialogs import SettingsDialog, TemplateDialog
    from captioner.ui.shortcuteditor import KeyCaptureDialog, ShortcutEditorDialog
    template_dialog = TemplateDialog(editor.template, window.places, window)
    template_dialog.resize(800, template_dialog.scroll.widget().sizeHint().height() + 70)  # complete, without scrolling
    template_dialog.show()
    settle()
    save(template_dialog, 'template')
    template_dialog.close()

    shortcut_editor = ShortcutEditorDialog(window)
    shortcut_editor.select('tag_toggle')
    shortcut_editor.show()
    capture = KeyCaptureDialog('tag_toggle', shortcut_editor.keys, shortcut_editor)
    capture.show()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.keyPress(capture.field, Qt.Key.Key_G)
    settle()
    save(capture, 'kuerzel-aufnehmen')
    capture.close()
    shortcut_editor.close()

    import dataclasses
    shown = dataclasses.replace(settings, check_updates=True, roster_sources=[
        'https://github.com/katzefudder/del2_roster/blob/main/roster_del2.txt', TEXTS['own_roster']])
    settings_dialog = SettingsDialog(shown, window)
    settings_dialog.resize(760, settings_dialog.sizeHint().height())
    settings_dialog.show()
    settle()
    save(settings_dialog, 'einstellungen')
    settings_dialog.close()

    # find and replace, opened non-modally and closed again right away
    window.select_all_filtered()
    from captioner.ui import replacedialog
    original_exec = replacedialog.ReplaceDialog.exec

    def grab_and_cancel(dialog):
        dialog.show()
        dialog.find.setText(TEXTS['find'])
        dialog.replacement.setText(TEXTS['replacement'])
        settle(0.8)
        save(dialog, 'suchen-ersetzen')
        return 0
    replacedialog.ReplaceDialog.exec = grab_and_cancel
    try:
        window.find_replace()
    finally:
        replacedialog.ReplaceDialog.exec = original_exec

    window.writer.flush(30)
    window.close()
    QTimer.singleShot(0, app.quit)


if __name__ == '__main__':
    main()
