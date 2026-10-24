"""Drag rules from ADR 0001, item 7, in offscreen mode."""
import os
import sys
from pathlib import Path

import pytest

from conftest import make_jpeg, requires_exiftool

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')

pytestmark = requires_exiftool


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app, tmp_path):
    from captioner import config
    from captioner.ui.main_window import MainWindow
    (tmp_path / 'fotos').mkdir()
    settings = config.Settings(roster_sources=[])
    w = MainWindow(settings)
    yield w
    w.close()


def open_and_wait(window, folder):
    window.open_folder(folder)
    window.scan_worker.wait(30000)
    QtWidgets.QApplication.processEvents()


def test_drag_contains_raw_jpeg_and_sidecar(window, tmp_path):
    folder = tmp_path / 'fotos'
    (folder / 'DSC_0001.NEF').write_bytes(b'raw')
    make_jpeg(folder / 'DSC_0001.JPG')
    open_and_wait(window, folder)
    item = window.all_items[0]
    window.selected_keys = {item.key}
    window.apply_filter()

    window.set_rating(3)
    mime = window.build_drag_mime()

    names = sorted(u.toLocalFile().rsplit('/', 1)[-1] for u in mime.urls())
    assert names == ['DSC_0001.JPG', 'DSC_0001.NEF', 'DSC_0001.xmp']


def test_drag_without_sidecars_when_disabled(window, tmp_path):
    folder = tmp_path / 'fotos'
    (folder / 'DSC_0001.NEF').write_bytes(b'raw')
    open_and_wait(window, folder)
    window.settings.drag_include_sidecars = False
    item = window.all_items[0]
    window.selected_keys = {item.key}
    window.apply_filter()
    window.set_rating(2)
    names = [u.toLocalFile().rsplit('/', 1)[-1] for u in window.build_drag_mime().urls()]
    assert names == ['DSC_0001.NEF']


def test_edited_raw_without_sidecar_is_refused(window, tmp_path, monkeypatch):
    folder = tmp_path / 'fotos'
    (folder / 'DSC_0001.NEF').write_bytes(b'raw')
    make_jpeg(folder / 'b.jpg')
    open_and_wait(window, folder)
    raw_item = next(i for i in window.all_items if i.raw)
    window.selected_keys = {i.key for i in window.all_items}
    window.apply_filter()
    window.set_rating(1)
    window.writer.flush(30)
    raw_item.sidecar.unlink()  # sidecar disappears after writing

    warnings = []
    monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', lambda *a: warnings.append(a[2]))
    names = [u.toLocalFile().rsplit('/', 1)[-1] for u in window.build_drag_mime().urls()]

    assert names == ['b.jpg']
    assert 'DSC_0001' in warnings[0]


def test_failed_write_is_refused(window, tmp_path, monkeypatch):
    folder = tmp_path / 'fotos'
    make_jpeg(folder / 'a.jpg')
    open_and_wait(window, folder)
    item = window.all_items[0]
    window.selected_keys = {item.key}
    item.error = 'kaputt'
    monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', lambda *a: None)
    assert window.build_drag_mime() is None


def test_thumbnail_threads_share_one_exiftool_per_thread(app, tmp_path):
    """Regression: threading.local created one Perl process per tile in the QThreadPool."""
    from captioner import scanner
    from captioner.exiftool import ExifToolPool, find_exiftool
    from captioner.previews import PreviewCache
    from captioner.ui.workers import ThumbnailLoader

    for n in range(24):
        make_jpeg(tmp_path / f'{n:03}.jpg')
    items = scanner.scan(tmp_path)
    pool = ExifToolPool(find_exiftool())
    loader = ThumbnailLoader(pool, PreviewCache(tmp_path / 'cache'))
    for item in items:
        loader.request_full(item)
    loader.threads.waitForDone(60000)
    try:
        assert pool.size() <= loader.threads.maxThreadCount()
    finally:
        loader.shutdown()
        pool.close()


def test_open_and_save_template_files(window, tmp_path):
    from captioner import templates
    from captioner.templates import MatchTemplate
    shared = templates.save_file(MatchTemplate(name='Auswärts Kassel', headline='DEL 2 - EC Kassel Huskies gegen '
                                               'EC Bad Nauheim', city='Kassel'), tmp_path / 'kassel.toml')

    opened = window.open_template_file(str(shared))
    assert window.editor.template.path == str(shared)
    assert str(shared) in window.settings.template_files

    copy = window.save_template_as(str(tmp_path / 'export' / 'kopie'))
    assert copy.path.endswith('kopie.toml')
    assert templates.load_file(copy.path).teams[0] == 'EC Kassel Huskies'
    assert window.editor.template.path == copy.path
    assert opened.path == str(shared)  # original stays linked unchanged

    window.remove_template(window.editor.template)
    assert copy.path not in window.settings.template_files
    assert Path(copy.path).exists()  # foreign files are never deleted


def test_broken_template_file_shows_warning(window, tmp_path, monkeypatch):
    path = tmp_path / 'kaputt.toml'
    path.write_text('format = "etwas anderes"\n', encoding='utf-8')
    warnings = []
    monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', lambda *a: warnings.append(a[2]))
    assert window.open_template_file(str(path)) is None
    assert 'kein Captioner-Template' in warnings[0]


def test_add_roster_file(window, tmp_path):
    path = tmp_path / 'roster.txt'
    path.write_text('- A -\nx1\t-1- Foo Bar (A)\n', encoding='utf-8')
    window.add_roster_file(str(path))
    window.roster_worker.wait(10000)
    QtWidgets.QApplication.processEvents()
    assert window.settings.roster_sources == [str(path)]
    assert window.roster.lookup('x1')


def test_menus_replace_the_toolbar(window):
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QToolBar
    assert window.findChildren(QToolBar) == []
    menus = {a.text(): a.menu() for a in window.menuBar().actions()}
    assert list(menus) == ['Ablage' if sys.platform == 'darwin' else 'Datei', 'Bearbeiten', 'Template', 'Roster', 'Hilfe']
    entries = {a.text(): a for menu in menus.values() for a in menu.actions() if not a.isSeparator()}
    assert entries['Einstellungen …'].menuRole() == QAction.MenuRole.PreferencesRole
    assert entries['Über Captioner'].menuRole() == QAction.MenuRole.AboutRole
    assert entries['Beenden'].menuRole() == QAction.MenuRole.QuitRole
    # no clash with the keymap (Qt doesn't trigger duplicate shortcuts at all)
    from captioner.ui import keymap
    from PySide6.QtGui import QKeySequence
    keymap_keys = {QKeySequence(k).toString() for b in keymap.BINDINGS if b.context != 'menu' for k in b.keys}
    for entry in entries.values():
        assert entry.shortcut().isEmpty() or entry.shortcut().toString() not in keymap_keys, entry.text()
    # menu shortcuts come from the keymap (context menu) so they can be customized
    assert [k.toString() for k in entries['Ordner öffnen …'].shortcuts()] == ['Ctrl+O']
    assert [k.toString() for k in entries['Neu einlesen'].shortcuts()] == ['F5']


def test_window_title_shows_the_version(window):
    from captioner import version
    assert window.windowTitle().startswith(f'Captioner {version()} - ')


def test_help_menu_opens_the_bundled_manual(window, monkeypatch):
    from captioner import manual_path
    from captioner.ui import main_window
    # checked in, bundled by both specs; one per UI language, English for anything else
    for language in ('de', 'en'):
        assert manual_path(language).is_file() and manual_path(language).suffix == '.pdf'
    assert manual_path('en') != manual_path('de') and manual_path('fr') == manual_path('en')
    assert manual_path() == manual_path('de')    # tests run in German
    opened = []
    # Qt returns '/' on Windows, Python '\\': compare as Path
    monkeypatch.setattr(main_window.QDesktopServices, 'openUrl', lambda url: opened.append(Path(url.toLocalFile())) or True)
    help_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == 'Hilfe')
    next(a for a in help_menu.actions() if a.text() == 'Anleitung (PDF)').trigger()
    assert opened == [manual_path()]


def test_about_dialog_links_to_the_website(app):
    from captioner import WEBSITE, WEBSITE_LINK, version
    from captioner.ui.about import AboutDialog
    dialog = AboutDialog()
    assert WEBSITE == 'https://www.katzefudder.de/captioner'
    # campaign parameters present; captioner/__init__.py decides which mtm_source
    from urllib.parse import parse_qs, urlsplit
    query = parse_qs(urlsplit(WEBSITE_LINK).query)
    assert WEBSITE_LINK.startswith(WEBSITE + '?') and query['mtm_campaign'] == ['captioner'] and query['mtm_source']
    import html
    assert f'href="{html.escape(WEBSITE_LINK)}"' in dialog.link.text() and dialog.link.openExternalLinks()
    assert '>www.katzefudder.de/captioner</a>' in dialog.link.text()
    assert version() not in ('', None)


def _template_dialog(monkeypatch, accept, name=None):
    from captioner.ui import main_window
    shown = []

    def fake_exec(dialog):
        shown.append(dialog.name.text())
        if name is not None:
            dialog.name.setText(name)
        return accept
    monkeypatch.setattr(main_window.TemplateDialog, 'exec', fake_exec)
    return shown


def test_copy_template_switches_and_opens_copy(window, monkeypatch):
    from captioner.templates import MatchTemplate
    original = MatchTemplate(name='DEL 2 Heim', city='Bad Nauheim', sublocation='Colonel-Knight-Stadion',
                             extra_tags=['Eishockey'], copyright='© 2026 Test')
    window.template_store.save(original)
    window.refresh_templates(original.path)
    shown = _template_dialog(monkeypatch, True, name='DEL 2 Auswärts')

    window.copy_template(window.editor.template)

    assert shown == ['DEL 2 Heim (Kopie)']
    current = window.editor.template
    assert current.name == 'DEL 2 Auswärts' and current.path != original.path
    assert (current.city, current.sublocation, current.extra_tags, current.copyright) == \
        ('Bad Nauheim', 'Colonel-Knight-Stadion', ['Eishockey'], '© 2026 Test')
    names = sorted(t.name for t in window.template_store.list()[0])
    assert names == ['DEL 2 Auswärts', 'DEL 2 Heim']


def test_copy_template_cancel_removes_copy(window, monkeypatch):
    from captioner.templates import MatchTemplate
    original = MatchTemplate(name='DEL 2 Heim', city='Bad Nauheim')
    window.template_store.save(original)
    window.refresh_templates(original.path)
    _template_dialog(monkeypatch, False)

    window.copy_template(window.editor.template)

    assert window.editor.template.path == original.path
    assert [t.name for t in window.template_store.list()[0]] == ['DEL 2 Heim']


def test_new_template_never_overwrites_same_name(tmp_path):
    from captioner.templates import MatchTemplate, TemplateStore
    store = TemplateStore(tmp_path / 'templates')
    first, second = MatchTemplate(name='Heim', city='A'), MatchTemplate(name='Heim', city='B')
    store.save(first)
    store.save(second)
    assert first.path != second.path
    assert sorted(t.city for t in store.list()[0]) == ['A', 'B']


def test_open_template_folder(window, monkeypatch):
    from captioner.ui import main_window
    opened = []
    # compare as Path: Qt returns C:/... on Windows, Python C:\\...
    monkeypatch.setattr(main_window.QDesktopServices, 'openUrl',
                        lambda url: opened.append(Path(url.toLocalFile())) or True)
    actions = [a for a in window.editor.template_menu.actions() if a.text().startswith('Template-Ordner')]
    actions += [a for m in window.menuBar().actions() if m.menu()
                for a in m.menu().actions() if a.text().startswith('Template-Ordner')]
    assert len(actions) == 2

    for action in actions:   # via the menu, not the method: that way a wrong connection shows up
        action.trigger()

    assert opened == [Path(window.template_store.directory)] * 2


def test_template_menu_entries_emit(window):
    """Entries in the "⋯" menu must emit their signal (a signal is not a slot for addAction)."""
    editor = window.editor
    emitted = []
    for signal in (editor.open_template_requested, editor.save_template_as_requested,
                   editor.open_template_folder_requested):
        signal.disconnect()
        signal.connect(lambda name=signal: emitted.append(name))
    names = ('Template-Datei laden …', 'Speichern unter …', 'Template-Ordner')
    for action in editor.template_menu.actions():
        if action.text().startswith(names):
            action.setEnabled(True)   # "Save as" is disabled without a template
            action.trigger()
    assert len(emitted) == 3


def test_template_dialog_shows_where_suffix_values_come_from(app):
    from captioner.templates import MatchTemplate
    from captioner.ui.dialogs import PLACEHOLDER_COLORS, SUFFIX_PLACEHOLDERS, TemplateDialog
    dialog = TemplateDialog(MatchTemplate(name='Heim', headline='DEL 2 - A gegen B', city='Bad Nauheim',
                                          sublocation='', caption_suffix=', {headline}, {city}'))
    preview = dialog.suffix_preview.text()
    assert f'color:{PLACEHOLDER_COLORS["headline"]}">DEL 2 - A gegen B<' in preview
    assert f'color:{PLACEHOLDER_COLORS["city"]}">Bad Nauheim<' in preview
    labels = {key: label.text() for key, (label, _text) in dialog._source_labels.items()}
    assert '●' in labels['headline'] and '●' in labels['city'] and '●' not in labels['sublocation']

    dialog.suffix.setCursorPosition(len(', {head'))
    assert dialog.placeholder_at_cursor() == 'headline'
    dialog.suffix.setCursorPosition(1)
    assert dialog.placeholder_at_cursor() is None

    from PySide6.QtWidgets import QPushButton
    chips = {b.text(): b for b in dialog.placeholder_legend.findChildren(QPushButton)}
    assert len(chips) == len(SUFFIX_PLACEHOLDERS)
    dialog.suffix.setCursorPosition(len(dialog.suffix.text()))
    chips['{sublocation}'].click()                   # click on the chip in the legend
    assert dialog.suffix.text() == ', {headline}, {city}{sublocation}'
    assert '●' in dialog._source_labels['sublocation'][0].text()
    # empty location in the template: the value comes from the panel when saving
    assert 'Ort aus dem Panel' in dialog.suffix_preview.text()
    dialog._insert_placeholder('creator')
    assert 'Fotograf (vom Bild)' in dialog.suffix_preview.text()   # empty: the image's value
    dialog.creator.setText('Florian Dehn')
    assert f'color:{PLACEHOLDER_COLORS["creator"]}">Florian Dehn<' in dialog.suffix_preview.text()
    assert '●' in dialog._source_labels['creator'][0].text()


def test_suffix_mark_wraps_only_filled_values():
    from captioner.templates import MatchTemplate
    template = MatchTemplate(headline='T', city='', caption_suffix=', {headline}, {city}, {date}')
    marked = template.suffix_for('2026:03:01 18:00:00', mark=lambda key, value: f'[{key}:{value}]')
    assert marked == ', [headline:T], [date:01.03.26]'


def test_template_dialog_fixed_date(app):
    from captioner.templates import MatchTemplate
    from captioner.ui.dialogs import PLACEHOLDER_COLORS, TemplateDialog
    dialog = TemplateDialog(MatchTemplate(name='Sonntag', caption_suffix=', {city}, {date}'))
    assert 'Datum (vom Bild)' in dialog.suffix_preview.text()
    assert '●' in dialog._source_labels['date'][0].text()
    dialog.date.setText('18.10.26')
    assert f'color:{PLACEHOLDER_COLORS["date"]}">18.10.26<' in dialog.suffix_preview.text()
    assert dialog.template().date == '18.10.26'


def test_panel_warns_when_fixed_date_differs(app):
    from captioner.scanner import Item
    from captioner.templates import MatchTemplate
    from captioner.ui.editor import CaptionEditor
    editor = CaptionEditor()
    template = MatchTemplate(name='Sonntag', date='18.10.26')
    editor.set_templates([template])
    editor.template_box.setCurrentIndex(1)
    item = Item(key='a', embedded=[Path('/tmp/a.jpg')], taken_at='2026:10:13 19:30:00')
    editor._update_date_hint(item)
    assert not editor.date_hint.isHidden() and '18.10.26' in editor.date_hint.text()
    item.taken_at = '2026:10:18 19:30:00'
    editor._update_date_hint(item)
    assert editor.date_hint.isHidden()


def test_gallery_visible_rows_match_the_layout(app):
    """No pages: tiles are only requested for the visible area."""
    from types import SimpleNamespace
    from PySide6.QtCore import QObject, QSize, Signal
    from captioner.ui.gallery import GalleryModel, GalleryView, TILE_H, TILE_W

    class Loader(QObject):
        ready = Signal(str)

    view = GalleryView()
    view.setModel(GalleryModel(Loader()))
    view.setGridSize(QSize(TILE_W, TILE_H))  # tile size without TileDelegate
    view.model().set_items([SimpleNamespace(key=str(n), name=str(n)) for n in range(1000)])
    view.resize(3 * TILE_W + 40, 2 * TILE_H + 20)
    view.show()
    app.processEvents()

    def check():
        first, last = view.visible_rows()
        area = view.viewport().rect()
        shown = [r for r in range(1000) if view.visualRect(view.model().index(r)).intersects(area)]
        assert first <= shown[0] and shown[-1] <= last  # nothing visible is missing
        assert last - first < 30                         # and not all 1000
        return first, last

    assert check()[0] == 0
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    app.processEvents()
    assert check()[1] == 999
    view.close()


def test_thumbnail_slider_resizes_tiles_in_all_tabs(window):
    from captioner.ui.gallery import tile_size
    second = window.new_tab()
    window.thumbnail_slider.setValue(400)
    assert window.settings.thumbnail_size == 400
    for tab in window.all_tabs():
        delegate = tab.view.itemDelegate()
        assert (delegate.tile_w, delegate.tile_h, delegate.image_h) == tile_size(400)
    assert tile_size(220) == (220, 210, 150)      # default as before
    third = window.new_tab()                       # new tabs get the configured size
    assert third.view.itemDelegate().tile_w == 400 and second is not third


def test_thumbnail_memory_keeps_wanted_tiles(app):
    from types import SimpleNamespace
    from PySide6.QtGui import QImage
    from captioner.ui.workers import ThumbnailLoader
    loader = ThumbnailLoader(None, None)
    image = QImage(100, 100, QImage.Format.Format_RGB32)
    loader.MEMORY_BYTES = 3 * image.sizeInBytes()
    loader.wanted = {'a', 'b', 'c', 'd'}           # all visible: drop nothing, even above the budget
    for key in 'abcd':
        loader._on_ready(key, QImage(image))
    assert set(loader.images) == {'a', 'b', 'c', 'd'}
    loader.wanted = {'d', 'e'}                     # scrolled on: the oldest no longer visible ones go
    loader._on_ready('e', QImage(image))
    assert set(loader.images) == {'c', 'd', 'e'}
    assert loader.memory == 3 * image.sizeInBytes()
    loader.invalidate('c')
    assert loader.memory == 2 * image.sizeInBytes()
    loader.shutdown()


def test_template_dialog_instructions_are_multiline(app):
    from captioner.templates import MatchTemplate
    from captioner.ui.dialogs import MultiLineField, TemplateDialog
    text = 'Honorarpflichtig\nKontakt: foto@example.org\nIBAN DE00 1234'
    dialog = TemplateDialog(MatchTemplate(name='Hinweise', instructions=text, caption_suffix=', {instructions}'))
    assert isinstance(dialog.instructions, MultiLineField) and dialog.instructions.text() == text
    assert dialog.template().instructions == text            # lines stay in the template file
    dialog.instructions.setPlainText('x' * 300)                  # too long: saving blocked
    assert not dialog.buttons.button(dialog.buttons.StandardButton.Save).isEnabled()
    dialog.instructions.setPlainText('a\n' * 70)                 # 140 bytes, in the image with " · " 342
    assert not dialog.buttons.button(dialog.buttons.StandardButton.Save).isEnabled()
    dialog.instructions.setPlainText(text)
    assert dialog.buttons.button(dialog.buttons.StandardButton.Save).isEnabled()


def test_codes_are_highlighted_green_or_red(app, roster):
    from captioner.ui.editor import CaptionEditor
    editor = CaptionEditor()
    editor.set_roster(roster, '#')
    highlighter = editor.caption.spelling
    text = '😀 Jubel #bn23# und #xx1# nach #bn3'           # emoji: two UTF-16 units
    assert highlighter.code_spans(text) == [(9, 6, True), (20, 5, False)]  # #bn3 not complete yet
    editor.caption.setPlainText(text)
    formats = editor.caption.document().firstBlock().layout().formats()
    backgrounds = {(f.start, f.length): f.format.background().color().name() for f in formats}
    assert backgrounds[(9, 6)] == '#3fa34d' and backgrounds[(20, 5)] == '#d64541'

    editor.caption.setPlainText('Jubel #bn23#')
    preview = editor.preview.text()
    assert f'<span style="background-color:{editor._replacement_color()}">-23- Marius Erk (EC Bad Nauheim)</span>' in preview
    assert '' not in preview and '' not in preview
    assert editor.resolve().text == 'Jubel -23- Marius Erk (EC Bad Nauheim)'   # saved without marking
