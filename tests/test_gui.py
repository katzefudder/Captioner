"""Drag-Regeln aus ADR 0001, Punkt 7, im Offscreen-Modus."""
import os
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
    window.apply_filter(False)

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
    window.apply_filter(False)
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
    window.apply_filter(False)
    window.set_rating(1)
    window.writer.flush(30)
    raw_item.sidecar.unlink()  # Sidecar verschwindet nach dem Schreiben

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
    """Regression: threading.local erzeugte im QThreadPool pro Kachel einen Perl-Prozess."""
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
    assert opened.path == str(shared)  # Original bleibt unveraendert verknuepft

    window.remove_template(window.editor.template)
    assert copy.path not in window.settings.template_files
    assert Path(copy.path).exists()  # fremde Dateien werden nie geloescht


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
    assert list(menus) == ['Ablage', 'Bearbeiten', 'Template', 'Roster', 'Hilfe']
    entries = {a.text(): a for menu in menus.values() for a in menu.actions() if not a.isSeparator()}
    assert entries['Einstellungen …'].menuRole() == QAction.MenuRole.PreferencesRole
    assert entries['Über Captioner'].menuRole() == QAction.MenuRole.AboutRole
    assert entries['Beenden'].menuRole() == QAction.MenuRole.QuitRole
    # keine Doppelbelegung mit der Keymap (Qt loest doppelte Kuerzel gar nicht aus)
    from captioner.ui import keymap
    from PySide6.QtGui import QKeySequence
    keymap_keys = {QKeySequence(k).toString() for b in keymap.BINDINGS for k in b.keys}
    for entry in entries.values():
        assert entry.shortcut().isEmpty() or entry.shortcut().toString() not in keymap_keys, entry.text()


def test_about_dialog_links_to_the_website(app):
    from captioner import WEBSITE, WEBSITE_LINK, version
    from captioner.ui.about import AboutDialog
    dialog = AboutDialog()
    assert WEBSITE == 'https://www.katzefudder.de/captioner'
    # Kampagnen-Parameter da; welcher mtm_source, entscheidet captioner/__init__.py
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
