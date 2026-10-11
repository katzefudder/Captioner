"""Hauptfenster: Ordner in Tabs, Filter, paginierte Galerie, Beschriftung, Drag nach Lightroom."""
import dataclasses
import html
import json
import logging
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QMimeData, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QMainWindow, QMessageBox, QProgressDialog, QSplitter,
                               QToolButton, QVBoxLayout, QWidget)

from .. import WEBSITE, codes, config, geo, metadata, scanner, transfer
from ..exiftool import ExifToolError, ExifToolPool, find_exiftool, reap_orphans
from ..previews import PreviewCache
from ..roster import Roster, RosterLoader
from .. import templates as template_files
from ..templates import TemplateError, TemplateStore, unique
from . import keymap
from .dialogs import ROSTER_FILE_FILTER, SettingsDialog, ShortcutsDialog, TemplateDialog
from .about import AboutDialog
from .editor import CaptionEditor
from .rostereditor import RosterEditorDialog
from . import folderdialog
from .viewer import Viewer
from .gallery import CLASS_COLORS, ItemRole
from .tabs import CopyWorker, FolderTab, FolderTabs, ask_conflicts, tab_title
from .workers import MetadataWriter, RosterWorker, ScanWorker, ThumbnailLoader

logger = logging.getLogger(__name__)

TAG_FILTERS = [('Alle Tags', None), ('getaggt', True), ('nicht getaggt', False)]

RATING_FILTERS = [('Alle Sterne', None), ('★ und mehr', 1), ('★★ und mehr', 2), ('★★★ und mehr', 3),
                  ('★★★★ und mehr', 4), ('★★★★★', 5), ('ohne Sterne', 0)]


class RawCaptionStore:
    """Rohtext mit Codes pro Datei, damit man ihn spaeter weiterbearbeiten kann (ADR 0001, Punkt 5)."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.data = {}

    def get(self, item):
        return self.data.get(str(item.primary))

    def set(self, item, raw):
        self.data[str(item.primary)] = raw
        try:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
        except OSError as e:
            logger.warning('Rohtexte nicht gespeichert: %s', e)


class OpenRequests(QObject):
    """
    macOS: Ordner aus dem Finder (aufs Dock-Symbol gezogen, "Oeffnen mit") kommen als
    QFileOpenEvent an der Application an, je Ordner eins, beim Start auch vor dem
    Fenster. Sie werden kurz gesammelt und dann gemeinsam uebergeben.
    """
    DELAY_MS = 250

    def __init__(self, app):
        super().__init__(app)
        self.paths = []
        self.handler = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(self.DELAY_MS)
        self.timer.timeout.connect(self.deliver)
        app.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FileOpen:
            if event.file():
                self.paths.append(event.file())
                self.timer.start()
            return True
        return False

    def set_handler(self, handler):
        self.handler = handler
        if self.paths:
            self.timer.start()

    def deliver(self):
        if self.handler is None or not self.paths:
            return
        paths, self.paths = self.paths, []
        self.handler(paths)


def _tab_attribute(name):
    """Zustand des aktiven Tabs, damit Bewertung, Editor, Viewer usw. unveraendert bleiben."""
    return property(lambda self: getattr(self.tab, name), lambda self, value: setattr(self.tab, name, value))


class MainWindow(QMainWindow):
    folder = _tab_attribute('folder')
    all_items = _tab_attribute('all_items')
    by_key = _tab_attribute('by_key')
    filtered = _tab_attribute('filtered')
    page = _tab_attribute('page')
    selected_keys = _tab_attribute('selected_keys')
    scan_worker = _tab_attribute('scan_worker')
    model = _tab_attribute('model')
    view = _tab_attribute('view')
    prev_button = _tab_attribute('prev_button')
    next_page_button = _tab_attribute('next_page_button')
    page_label = _tab_attribute('page_label')

    def __init__(self, settings: config.Settings, folder=None):
        super().__init__()
        self.settings = settings
        self.setWindowTitle('Captioner')
        self.resize(1500, 950)

        self.pool = ExifToolPool(find_exiftool(settings.exiftool_path))
        self.loader = ThumbnailLoader(self.pool, PreviewCache(config.cache_dir()))
        self.writer = MetadataWriter(self.pool)
        self.writer.written.connect(self._on_written)
        self.writer.idle_changed.connect(lambda idle: self._update_status())
        self.writer.start()
        self.roster_loader = RosterLoader(config.cache_dir(), settings.roster_cache_ttl_minutes)
        self.roster = Roster()
        self.template_store = TemplateStore(config.templates_dir())
        self.raw_captions = RawCaptionStore(config.cache_dir() / 'raw_captions.json')
        self.places = geo.PlaceBook(settings.places)

        self.edited_keys = set()   # ueber alle Tabs; Keys sind Pfade
        self.last_raw_caption = ''
        self.last_headline = ''    # fuer Bilder ohne Titel, wenn das Template keinen vorgibt
        self.roster_worker = None
        self.copy_worker = None
        self._drag_items = []
        self.viewer = None
        self._syncing_selection = False

        self._build_ui()
        self.refresh_templates(settings.last_template)
        self.load_roster()
        # Ein Ordner (str/Path) oder eine Liste, z. B. von der Kommandozeile
        folders = [folder] if isinstance(folder, (str, Path)) else list(folder or [])
        if folders:
            self.open_folders(folders)

    # --- Aufbau ---------------------------------------------------------------

    def _build_menus(self):
        """
        Menueleiste; auf macOS oben am Bildschirm, "Ueber", "Einstellungen" und "Beenden"
        wandern dort ins App-Menue "Captioner". Menuepunkte zu Befehlen mit Keymap-Kuerzel
        (Tab schliessen, Template, F1) bekommen kein eigenes Kuerzel: zwei gleiche Kuerzel loest
        Qt nicht aus, und Cmd+W gehoert in der Grossansicht dieser.
        """
        bar = self.menuBar()

        def action(menu, text, handler, shortcut=None, role=None):
            item = QAction(text, self)
            if shortcut is not None:
                item.setShortcut(shortcut)
            if role is not None:
                item.setMenuRole(role)
            item.triggered.connect(lambda checked=False: handler())
            menu.addAction(item)
            return item

        role = QAction.MenuRole
        file_menu = bar.addMenu('Ablage')
        action(file_menu, 'Ordner öffnen …', self.choose_folder, QKeySequence.StandardKey.Open)
        action(file_menu, 'Ordner in neuem Tab öffnen …', lambda: self.choose_folder(new_tab=True))
        action(file_menu, 'Neu einlesen', lambda: self.folder and self.rescan(self.tab), QKeySequence('F5'))
        file_menu.addSeparator()
        action(file_menu, 'Tab schließen', lambda: self.close_tab(self.tabs.currentIndex()))
        file_menu.addSeparator()
        action(file_menu, 'Einstellungen …', self.edit_settings, QKeySequence.StandardKey.Preferences,
               role.PreferencesRole)
        action(file_menu, 'Beenden', self.close, QKeySequence.StandardKey.Quit, role.QuitRole)

        template_menu = bar.addMenu('Template')
        action(template_menu, 'Template öffnen …', self.open_template_file)
        action(template_menu, 'Template speichern unter …', self.save_template_as)
        action(template_menu, 'Template auf Auswahl anwenden', self.apply_template)

        roster_menu = bar.addMenu('Roster')
        action(roster_menu, 'Roster bearbeiten …', self.edit_roster)
        action(roster_menu, 'Roster neu laden', lambda: self.load_roster(force=True))
        action(roster_menu, 'Roster-Datei hinzufügen …', self.add_roster_file)

        help_menu = bar.addMenu('Hilfe')
        action(help_menu, 'Tastenkürzel', self.show_shortcuts)
        action(help_menu, 'Captioner-Website', lambda: QDesktopServices.openUrl(QUrl(WEBSITE)))
        action(help_menu, 'Über Captioner', self.show_about, role=role.AboutRole)

    def show_about(self):
        AboutDialog(self).exec()

    def _build_ui(self):
        self._build_menus()

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 6)

        filters = QHBoxLayout()
        self.rating_filter = QComboBox()
        for label, value in RATING_FILTERS:
            self.rating_filter.addItem(label, value)
        self.color_filter = QComboBox()
        self.tag_filter = QComboBox()
        for label, value in TAG_FILTERS:
            self.tag_filter.addItem(label, value)
        self.uncaptioned_filter = QCheckBox('nur unbeschriftet')
        self.folder_label = QLabel('Kein Ordner geöffnet')
        filters.addWidget(self.folder_label, 1)
        filters.addWidget(self.tag_filter)
        filters.addWidget(self.rating_filter)
        filters.addWidget(self.color_filter)
        filters.addWidget(self.uncaptioned_filter)
        self._fill_color_filter()
        self.rating_filter.currentIndexChanged.connect(lambda: self.apply_filter(True))
        self.color_filter.currentIndexChanged.connect(lambda: self.apply_filter(True))
        self.tag_filter.currentIndexChanged.connect(lambda: self.apply_filter(True))
        self.uncaptioned_filter.toggled.connect(lambda: self.apply_filter(True))

        # Reiter oben ueber die ganze Fensterbreite, Galerien darunter links
        self.tabs = FolderTabs(self)
        self.tabs.bar.files_dropped.connect(lambda index: self.copy_dragged_to(self.tabs.widget(index)))
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        new_tab_button = QToolButton(text='+')
        new_tab_button.setToolTip('Ordner in neuem Tab öffnen')
        new_tab_button.clicked.connect(lambda: self.choose_folder(new_tab=True))
        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        tab_row.addWidget(self.tabs.bar, 1)
        tab_row.addWidget(new_tab_button)
        outer.addLayout(tab_row)
        self.new_tab()

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(filters)
        left_layout.addWidget(self.tabs.stack, 1)

        self.editor = CaptionEditor()
        self.editor.setMinimumWidth(380)
        self.editor.save_requested.connect(self.save_caption)
        self.editor.apply_template_requested.connect(self.apply_template)
        self.editor.template_changed.connect(self._on_template_changed)
        self.editor.edit_template_requested.connect(self.edit_template)
        self.editor.open_template_requested.connect(self.open_template_file)
        self.editor.save_template_as_requested.connect(self.save_template_as)
        self.editor.remove_template_requested.connect(self.remove_template)
        self.editor.reload_roster_requested.connect(lambda: self.load_roster(force=True))
        self.editor.add_roster_file_requested.connect(self.add_roster_file)
        self.editor.edit_roster_requested.connect(self.edit_roster)
        self.editor.navigate_requested.connect(self.step_selection)
        self.editor.place_chosen.connect(self.remember_place)
        self.editor.set_place_book(self.places)

        self.main_splitter = QSplitter()
        self.main_splitter.addWidget(left)
        self.main_splitter.addWidget(self.editor)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setSizes([1080, 420])
        outer.addWidget(self.main_splitter, 1)
        self.setCentralWidget(central)

        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label)
        self.setAcceptDrops(True)
        self._install_shortcuts()
        self._update_pager()

    def _fill_color_filter(self):
        self.color_filter.blockSignals(True)
        self.color_filter.clear()
        self.color_filter.addItem('Alle Farben', None)
        self.color_filter.addItem('ohne Farbe', 0)
        for n in range(1, 9):
            label = self.settings.labels[n - 1] if n <= len(self.settings.labels) else ''
            self.color_filter.addItem(f'Farbklasse {n}' + (f' ({label})' if label else ''), n)
            self.color_filter.setItemData(self.color_filter.count() - 1, QColor(CLASS_COLORS[n]),
                                          Qt.ItemDataRole.DecorationRole)
        self.color_filter.blockSignals(False)

    # --- Tastenkuerzel (keymap.py) ----------------------------------------------

    def _install_shortcuts(self):
        g = {
            'tag_toggle': lambda: self.set_tag(None),
            'tag_on': lambda: self.set_tag(True),
            'tag_off': lambda: self.set_tag(False),
            'preview': self.open_viewer,
            'info': self.editor.focus_caption,
            'last_previewed': self.select_last_previewed,
            'select_all': self.select_all_filtered,
            'deselect_all': self.deselect_all,
            'select_tagged': self.select_tagged,
            'home': lambda: self.jump_to(0),
            'end': lambda: self.jump_to(-1),
            'page_prev': lambda: self.go_to_page(self.page - 1),
            'page_next': lambda: self.go_to_page(self.page + 1),
            'next_image': lambda: self.step_selection(1),
            'prev_image': lambda: self.step_selection(-1),
            'roster_settings': self.edit_settings,
        }
        for n in range(0, 9):
            g[f'color_{n}'] = lambda n=n: self.set_color_class(n)
        for n in range(0, 6):
            g[f'rating_{n}'] = lambda n=n: self.set_rating(n)
        w = {
            'view_tagged': lambda: self.toggle_tag_view(True),
            'view_untagged': lambda: self.toggle_tag_view(False),
            'template_load': self.open_template_file,
            'template_save': self.save_template_as,
            'template_apply': self.apply_template,
            'roster_reload': lambda: self.load_roster(force=True),
            'shortcuts': self.show_shortcuts,
            'snapshot_take': self.take_snapshot,
            'snapshot_paste': self.paste_snapshot,
            'close_tab': lambda: self.close_tab(self.tabs.currentIndex()),
            'tab_next': lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % self.tabs.count()),
            'tab_prev': lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % self.tabs.count()),
        }
        e = {
            'save_next': lambda: self.editor.submit(1),
            'save_prev': lambda: self.editor.submit(-1),
            'save_close': self.save_and_close,
            'next_nosave': lambda: self.step_selection(1),
            'prev_nosave': lambda: self.step_selection(-1),
            'editor_apply_template': self.apply_template,
        }
        widget_ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        # Galerie-Kuerzel gelten in jedem Tab (Fokus in einer der Galerien oder auf den Reitern)
        self._bind(g, self.tabs.stack, widget_ctx)
        self._bind(w, self, Qt.ShortcutContext.WindowShortcut)
        self._bind(e, self.editor, widget_ctx)

    def _bind(self, handlers, widget, context):
        self._shortcuts = getattr(self, '_shortcuts', [])
        for command, handler in handlers.items():
            for sequence in keymap.keys(command):
                shortcut = QShortcut(QKeySequence(sequence), widget)
                shortcut.setContext(context)
                shortcut.activated.connect(handler)
                self._shortcuts.append(shortcut)

    def show_shortcuts(self):
        ShortcutsDialog(self).exec()

    # --- Tabs und Ordner ---------------------------------------------------------

    @property
    def tab(self) -> FolderTab:
        return self.tabs.currentWidget()

    def all_tabs(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def new_tab(self, folder=None):
        tab = FolderTab(self.loader, self.writer)
        tab.view.mime_factory = self.build_drag_mime
        tab.view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        tab.view.files_dropped.connect(lambda t=tab: self.copy_dragged_to(t))
        tab.prev_button.clicked.connect(lambda: self.go_to_page(self.page - 1))
        tab.next_page_button.clicked.connect(lambda: self.go_to_page(self.page + 1))
        index = self.tabs.addTab(tab, tab_title(folder))
        self.tabs.setCurrentIndex(index)
        self._update_empty_text()
        self._update_pager()
        return tab

    def tab_for_folder(self, folder):
        for tab in self.all_tabs():
            if tab.folder and transfer._same_dir(tab.folder, folder):
                return tab
        return None

    def choose_folder(self, new_tab=False):
        """Finder-Dialog mit Mehrfachauswahl (Cmd-/Shift-Klick); jeder Ordner ein Tab."""
        start = self.folder or self.settings.last_folder or str(Path.home())
        folders = folderdialog.choose_folders(self, 'Ordner öffnen – mehrere mit ⌘-Klick', start)
        if folders:
            self.open_folders(folders, new_tab=new_tab)

    def open_paths(self, paths):
        """Vom Finder: Ordner werden Tabs, bei Bilddateien wird ihr Ordner geoeffnet."""
        folders = []
        for path in map(Path, paths):
            folder = path if path.is_dir() else path.parent if path.suffix.lower() in scanner.IMAGE_EXTENSIONS else None
            if folder is not None and str(folder) not in folders:
                folders.append(str(folder))
        if folders:
            self.open_folders(folders)
        self.showNormal() if self.isMinimized() else None
        self.raise_()
        self.activateWindow()

    # Mehr Tabs auf einmal nur nach Rueckfrage (z. B. versehentlich ~/Pictures gewaehlt)
    MANY_FOLDERS = 8

    def open_folders(self, folders, new_tab=False):
        """
        Jeder Ordner ein Tab. Ein Ordner ohne eigene Bilder (Karte, DCIM) oeffnet seine
        Unterordner mit Bildern, ausser "Unterordner mit einlesen" ist an.
        """
        expanded = []
        for folder in folders:
            found = [] if self.settings.recursive else scanner.image_folders(folder)
            expanded += [str(f) for f in found] or [str(folder)]
        if len(expanded) > self.MANY_FOLDERS:
            answer = QMessageBox.question(
                self, 'Viele Ordner', f'{len(expanded)} Ordner mit Bildern gefunden. Alle in Tabs öffnen?\n\n'
                + '\n'.join(expanded[:10]) + ('\n…' if len(expanded) > 10 else ''))
            if answer != QMessageBox.StandardButton.Yes:
                return []
        tabs = [self.open_folder(folder, new_tab=new_tab and position == 0)
                for position, folder in enumerate(expanded)]
        if tabs:
            self.tabs.setCurrentWidget(tabs[0])
        return tabs

    def open_folder(self, folder, new_tab=False):
        """In einem neuen Tab; ein leerer aktueller Tab wird benutzt. Schon offen: dorthin wechseln."""
        folder = str(folder)
        existing = self.tab_for_folder(folder)
        if existing is not None:
            self.tabs.setCurrentWidget(existing)
            return existing
        tab = self.tab if (self.tab.folder is None and not new_tab) else self.new_tab()
        tab.folder = folder
        index = self.tabs.indexOf(tab)
        self.tabs.setTabText(index, tab_title(folder))
        self.tabs.setTabToolTip(index, folder)
        self.settings.last_folder = folder
        self.settings.save()
        self.rescan(tab, wait_for_writer=False)
        return tab

    def rescan(self, tab, wait_for_writer=True):
        if wait_for_writer and self.writer.pending_count() and not self._wait_for_writer('Neu einlesen'):
            return
        tab.stop_scan()
        tab.all_items, tab.by_key, tab.filtered = [], {}, []
        tab.selected_keys.clear()
        tab.page = 0
        tab.model.set_items([])
        self._set_tab_status(tab, f'{tab.folder} – wird eingelesen …')
        tab.scan_started = time.time()
        worker = ScanWorker(self.pool, tab.folder, self.settings.recursive)
        worker.tab = tab
        tab.scan_worker = worker
        worker.scanned.connect(self._on_scanned)
        worker.chunk_loaded.connect(self._on_chunk_loaded)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(self._on_scan_finished)
        worker.start()
        if tab is self.tab:
            self._update_empty_text()
            self._update_pager()
            self._show_selection_in_editor()

    def _scanning_tab(self):
        """Tab des Scans, der das Signal gesendet hat; None, wenn er veraltet ist."""
        worker = self.sender()
        tab = getattr(worker, 'tab', None)
        if tab is None or tab.scan_worker is not worker or self.tabs.indexOf(tab) < 0:
            return None
        return tab

    def _on_scanned(self, items):
        tab = self._scanning_tab()
        if tab is None:
            return
        tab.all_items = items
        tab.by_key = {item.key: item for item in items}
        if tab is self.tab:
            self.apply_filter(True)

    def _on_chunk_loaded(self, chunk):
        tab = self._scanning_tab()
        if tab is None:
            return
        tab.model.refresh([item.key for item in chunk])
        loaded = sum(1 for item in tab.all_items if item.meta_loaded)
        self._set_tab_status(tab, f'{tab.folder} – Metadaten {loaded}/{len(tab.all_items)} …')
        if tab is self.tab and self._selected_items():
            self._show_selection_in_editor()

    def _on_scan_failed(self, message):
        tab = self._scanning_tab()
        if tab is not None:
            QMessageBox.warning(self, 'Einlesen fehlgeschlagen', f'{tab.folder}\n\n{message}')

    def _on_scan_finished(self):
        tab = self._scanning_tab()
        if tab is None:
            return
        scanner.sort_items(tab.all_items)
        elapsed = time.time() - tab.scan_started
        self._set_tab_status(tab, f'{tab.folder} – {len(tab.all_items)} Bilder ({elapsed:.1f} s)')
        if tab is self.tab:
            self.apply_filter(False)

    def _set_tab_status(self, tab, text):
        tab.status_text = text
        if tab is self.tab:
            self.folder_label.setText(text)

    def _on_tab_changed(self, index):
        if not hasattr(self, 'editor') or index < 0:
            return
        # Filter gelten fuer alle Tabs; beim Wechsel fuer den neuen anwenden
        self.folder_label.setText(self.tab.status_text)
        self.apply_filter(False)

    def close_tab(self, index):
        tab = self.tabs.widget(index)
        if tab is None:
            return
        if self.copy_worker and self.copy_worker.isRunning() and self.copy_worker.target_tab is tab:
            QMessageBox.information(self, 'Tab schließen', 'In diesen Ordner wird gerade kopiert.')
            return
        tab.stop_scan()
        self.tabs.removeTab(index)
        tab.deleteLater()
        if self.tabs.count() == 0:
            self.new_tab()

    # --- Filter, Seiten, Auswahl -------------------------------------------------

    def _passes(self, item):
        rating = self.rating_filter.currentData()
        if rating == 0 and item.meta.rating != 0:
            return False
        if rating and item.meta.rating < rating:
            return False
        color = self.color_filter.currentData()
        if color is not None and self.color_class_of(item) != color:
            return False
        tagged = self.tag_filter.currentData()
        if tagged is not None and item.meta.tagged != tagged:
            return False
        if self.uncaptioned_filter.isChecked() and item.meta.is_captioned:
            return False
        return True

    def apply_filter(self, reset_page):
        self.filtered = [item for item in self.all_items if self._passes(item)]
        if reset_page:
            self.page = 0
        self.page = max(0, min(self.page, self.page_count() - 1))
        self.show_page()

    def page_count(self):
        size = self.settings.page_size
        return max(1, (len(self.filtered) + size - 1) // size)

    def page_items(self, page=None):
        page = self.page if page is None else page
        size = self.settings.page_size
        return self.filtered[page * size:(page + 1) * size]

    def go_to_page(self, page, focus_key=None):
        if not 0 <= page < self.page_count():
            return
        self.page = page
        self.show_page(focus_key)

    def _update_empty_text(self):
        """Hinweis unter dem Logo, solange die Galerie leer ist."""
        if not self.folder:
            keys = QKeySequence(QKeySequence.StandardKey.Open).toString(QKeySequence.SequenceFormat.NativeText)
            text = f'Captioner\nOrdner öffnen ({keys}) oder einen Ordner hierher ziehen'
        elif self.tab.scanning() and not self.all_items:
            text = 'Ordner wird eingelesen …'
        elif not self.all_items:
            text = 'Keine Bilder in diesem Ordner (JPG, NEF und andere RAWs, DNG, TIFF)'
        else:
            text = 'Kein Bild passt zu den Filtern'
        self.view.empty_text = text
        self.view.viewport().update()

    def show_page(self, focus_key=None):
        self._update_empty_text()
        items = self.page_items()
        self._syncing_selection = True
        self.model.set_items(items)
        selection = QItemSelection()
        for row, item in enumerate(items):
            if item.key in self.selected_keys:
                index = self.model.index(row)
                selection.select(index, index)
        self.view.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if focus_key and focus_key in self.model.rows:
            index = self.model.index(self.model.rows[focus_key])
            self.view.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.view.scrollTo(index)
        self._syncing_selection = False
        self.loader.request(items + self.page_items(self.page + 1))
        self._update_pager()
        self._show_selection_in_editor()

    def _update_pager(self):
        total = len(self.filtered)
        self.page_label.setText(f'Seite {self.page + 1} / {self.page_count()} · {total} Bilder'
                                + (f' · {len(self._selected_items())} ausgewählt' if self.selected_keys else ''))
        self.prev_button.setEnabled(self.page > 0)
        self.next_page_button.setEnabled(self.page < self.page_count() - 1)

    def _on_selection_changed(self, selected, deselected):
        if self._syncing_selection:
            return
        model_selection = self.view.selectionModel()
        for row, item in enumerate(self.model.items):
            if model_selection.isSelected(self.model.index(row)):
                self.selected_keys.add(item.key)
            else:
                self.selected_keys.discard(item.key)
        self._update_pager()
        self._show_selection_in_editor()

    def _selected_items(self):
        return [item for item in self.filtered if item.key in self.selected_keys]

    def _focused_first(self, items):
        """Das Item unter dem Cursor zuerst, damit der Editor es zeigt."""
        index = self.view.currentIndex()
        current = index.data(ItemRole) if index.isValid() else None
        if current in items:
            return [current] + [i for i in items if i is not current]
        return items

    def _show_selection_in_editor(self):
        items = self._focused_first(self._selected_items())
        carry = self.last_raw_caption if len(items) == 1 and not items[0].meta.is_captioned else None
        self.editor.show_items(items, carry_over_raw=carry, raw_lookup=self.raw_captions.get,
                               carry_over_headline=self.last_headline)

    def select_all_filtered(self):
        """Alle, nicht nur die sichtbare Seite."""
        self.selected_keys = {item.key for item in self.filtered}
        self.show_page()

    def deselect_all(self):
        self.selected_keys = set()
        self.show_page()

    def select_tagged(self):
        self.selected_keys = {item.key for item in self.filtered if item.meta.tagged}
        self.show_page()

    def toggle_tag_view(self, tagged):
        """F3/F4: nur getaggte bzw. nicht getaggte; nochmal druecken zeigt wieder alle."""
        current = self.tag_filter.currentData()
        target = None if current is tagged else tagged
        self.tag_filter.setCurrentIndex(self.tag_filter.findData(target))

    def jump_to(self, position):
        """Home/End: zum ersten bzw. letzten Bild scrollen, Auswahl bleibt."""
        if not self.filtered:
            return
        item = self.filtered[position]
        page = self.filtered.index(item) // self.settings.page_size
        if page != self.page:
            self.page = page
            self.show_page()
        index = self.model.index(self.model.rows[item.key])
        self.view.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.view.scrollTo(index)

    def select_last_previewed(self):
        item = self.by_key.get(getattr(self, 'last_previewed_key', None))
        if item in self.filtered:
            self.select_only(item)

    def step_selection(self, step):
        """Zum naechsten/vorherigen Bild nach der Auswahl, ohne zu speichern."""
        items = [item for item in self._selected_items() if item in self.filtered]
        if not items:
            return
        positions = [self.filtered.index(item) for item in items]
        target = (max(positions) + 1) if step > 0 else (min(positions) - 1)
        if 0 <= target < len(self.filtered):
            focus_in_editor = self.editor.isAncestorOf(QApplication.focusWidget())
            self.select_only(self.filtered[target])
            if focus_in_editor:
                self.editor.focus_caption()

    def select_only(self, item):
        self.selected_keys = {item.key}
        position = self.filtered.index(item)
        page = position // self.settings.page_size
        if page != self.page:
            self.page = page
        self.show_page(focus_key=item.key)
        # Beim Beschriften in der Grossansicht (Cmd+N/B) zeigt sie das neue Bild
        if self.viewer is not None and self.viewer.isVisible() and self.viewer.key != item.key:
            self._show_in_viewer(item)

    # --- Bewertung und Beschriftung ---------------------------------------------

    def _enqueue(self, item, meta):
        item.meta = meta
        item.error = None
        self.edited_keys.add(item.key)
        self.writer.enqueue(item, meta)

    def set_rating(self, rating):
        items = self._selected_items()
        for item in items:
            self._enqueue(item, dataclasses.replace(item.meta, rating=rating))
        self.model.refresh([i.key for i in items])
        self._update_status()

    def color_class_of(self, item):
        """Farbklasse; fehlt sie (z. B. nur Lightroom-Label), aus dem Label abgeleitet."""
        if item.meta.color_class:
            return item.meta.color_class
        if item.meta.label in self.settings.labels:
            return self.settings.labels.index(item.meta.label) + 1
        return 0

    def set_color_class(self, n):
        """Farbklasse 1-8, 0 entfernt. Dazu das Lightroom-Label."""
        label = self.settings.labels[n - 1] if 0 < n <= len(self.settings.labels) else ''
        items = self._selected_items()
        for item in items:
            self._enqueue(item, dataclasses.replace(item.meta, color_class=n, label=label))
        self.model.refresh([i.key for i in items])
        self._update_status()

    def set_tag(self, value):
        """True/False setzt, None schaltet um (alle an, ausser alle sind schon an)."""
        items = self._selected_items()
        if not items:
            return
        if value is None:
            value = not all(item.meta.tagged for item in items)
        for item in items:
            self._enqueue(item, dataclasses.replace(item.meta, tagged=value))
        self.model.refresh([i.key for i in items])
        self._update_status()
        if self.tag_filter.currentData() is not None:
            self.apply_filter(False)

    def take_snapshot(self):
        """
        Beschriftung kopieren: was im Panel steht (das Bild unter dem Cursor), auch
        ungespeicherte Aenderungen. Die Beschreibung als Rohtext mit Codes.
        """
        items = self._focused_first(self._selected_items())
        if not items:
            return
        self.snapshot = self.editor.current_fields()
        self.statusBar().showMessage(f'Beschriftung von {items[0].name} kopiert', 5000)

    def paste_snapshot(self):
        """
        In alle ausgewaehlten Bilder einfuegen und speichern. Gerechnet wird wie beim
        Speichern, je Bild: Codes aufloesen, Anhang mit dessen Datum, Personen-Tags, GPS.
        """
        snapshot = getattr(self, 'snapshot', None)
        items = self._selected_items()
        if not snapshot or not items:
            return
        resolution = codes.resolve(snapshot['raw_caption'], self.roster, self.settings.code_delimiter)
        if resolution.unknown:
            QMessageBox.warning(self, 'Nicht eingefügt', 'Unbekannte Codes in der kopierten Beschreibung: '
                                + ', '.join(resolution.unknown))
            return
        self.save_caption(dict(snapshot, resolution=resolution, caption_modified=True), 0)
        self._show_selection_in_editor()
        self.statusBar().showMessage(f'Beschriftung in {len(items)} Bild(er) eingefügt', 5000)

    def save_and_close(self):
        """Wie "Save Changes and Close Dialog": speichern, zurueck in die Galerie bzw. aufs Bild."""
        if self.editor.submit(0):
            if self._editor_in_viewer():
                self.viewer.zoom.setFocus()
            else:
                self.view.setFocus()

    def save_caption(self, fields, step):
        items = self._focused_first(self._selected_items())
        if not items:
            return
        resolution = fields['resolution']
        apply_caption = len(items) == 1 or fields['caption_modified']
        template = self.editor.template
        planned = []
        for item in items:
            if apply_caption:
                caption = metadata.single_line(resolution.text)
                if template and caption:
                    caption = template.compose_caption(
                        caption, item.taken_at, headline=fields['headline'],
                        city=fields['city'], sublocation=fields['sublocation'])
                persons = resolution.persons
            else:
                caption = item.meta.caption
                persons = codes.persons_in(caption, self.roster)
            meta = geo.apply_gps(dataclasses.replace(
                item.meta, headline=fields['headline'], caption=caption,
                keywords=unique(fields['keywords'] + persons),
                city=fields['city'], sublocation=fields['sublocation'],
                **(template.fixed_values() if template else {})), self.places)
            problems = metadata.validate(meta)
            if problems:
                QMessageBox.warning(self, 'Nicht gespeichert', f'{item.name}: ' + '; '.join(problems))
                return
            planned.append((item, meta))
        for item, meta in planned:
            self._enqueue(item, meta)
            if apply_caption:
                self.raw_captions.set(item, fields['raw_caption'])
        if apply_caption and fields['raw_caption'].strip():
            self.last_raw_caption = fields['raw_caption']
        if fields['headline']:
            self.last_headline = fields['headline']
        self.model.refresh([item.key for item, _ in planned])
        self._update_status()
        if self.viewer is not None and self.viewer.isVisible():
            shown = next((item for item, _ in planned if item.key == self.viewer.key), None)
            if shown is not None:
                self.viewer.show_item(shown, self.viewer._image)
        if step:
            self._advance(items, step)

    def _advance(self, items, step=1):
        positions = [self.filtered.index(item) for item in items if item in self.filtered]
        if not positions:
            return
        target = max(positions) + 1 if step > 0 else min(positions) - 1
        if 0 <= target < len(self.filtered):
            self.select_only(self.filtered[target])
            self.editor.focus_caption()

    def apply_template(self):
        template = self.editor.template
        if not template:
            QMessageBox.information(self, 'Kein Template', 'Bitte zuerst ein Spiel-Template auswählen oder anlegen.')
            return
        items = self._selected_items()
        for item in items:
            # Ohne Heim/Gast gibt das Template keinen Titel vor: der des Bildes bleibt
            headline = template.headline or item.meta.headline
            caption = template.compose_caption(item.meta.caption, item.taken_at, headline=headline) \
                if item.meta.caption else ''
            persons = codes.persons_in(caption, self.roster)
            self._enqueue(item, geo.apply_gps(dataclasses.replace(
                item.meta, headline=headline, caption=caption, city=template.city,
                sublocation=template.sublocation, keywords=unique(template.keywords + persons),
                **template.fixed_values()), self.places))
        self.model.refresh([i.key for i in items])
        self._show_selection_in_editor()
        self._update_status()

    def _on_written(self, key, ok, message):
        tab = next((t for t in self.all_tabs() if key in t.by_key), None)
        if tab is None:
            return
        item = tab.by_key[key]
        item.error = None if ok else message
        self.loader.invalidate_details(key)  # Dateigroesse und Werte neu lesen
        if not ok:
            self.statusBar().showMessage(f'Fehler: {message}', 15000)
        tab.model.refresh([key])
        self._update_status()

    def _update_status(self):
        pending = self.writer.pending_count()
        errors = sum(1 for tab in self.all_tabs() for item in tab.all_items if getattr(item, 'error', None))
        parts = []
        if pending:
            parts.append(f'schreibe {pending} …')
        if errors:
            parts.append(f'<span style="color:#d64541">{errors} Fehler</span>')
        self.status_label.setText(' · '.join(parts) or 'alles gespeichert')
        self.model.refresh()

    def _wait_for_writer(self, purpose):
        dialog = QProgressDialog(f'Metadaten werden geschrieben ({purpose}) …', None, 0, 0, self)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()
        QApplication.processEvents()
        ok = self.writer.flush(timeout=120)
        dialog.close()
        if not ok:
            QMessageBox.warning(self, 'Schreiben dauert an', 'Es werden noch Metadaten geschrieben. Bitte kurz warten.')
        return ok

    # --- Drag nach Lightroom ---------------------------------------------------

    def build_drag_mime(self):
        """
        Erst alles schreiben, dann ziehen. Lightroom darf nie eine halb
        geschriebene Datei sehen, und eine beschriftete RAW-Datei ohne Sidecar
        geht nicht durch (ADR 0001, Punkt 7).
        """
        items = self._selected_items()
        if not items:
            return None
        if self.writer.pending_count():
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                if not self.writer.flush(timeout=120):
                    QMessageBox.warning(self, 'Noch nicht bereit', 'Es werden noch Metadaten geschrieben.')
                    return None
            finally:
                QApplication.restoreOverrideCursor()

        refused, urls, accepted = [], [], []
        for item in items:
            if getattr(item, 'error', None):
                refused.append(f'{item.name}: {item.error}')
                continue
            if item.raw and item.key in self.edited_keys and not (item.sidecar and item.sidecar.exists()):
                refused.append(f'{item.name}: XMP-Sidecar fehlt')
                continue
            accepted.append(item)
            for path in item.files:
                urls.append(QUrl.fromLocalFile(str(path)))
            if self.settings.drag_include_sidecars and item.raw and item.sidecar and item.sidecar.exists():
                urls.append(QUrl.fromLocalFile(str(item.sidecar)))
        if refused:
            QMessageBox.warning(self, 'Nicht alle Bilder übergeben',
                                'Diese Bilder werden nicht gezogen, ihre Metadaten sind nicht sicher gespeichert:\n\n'
                                + '\n'.join(refused[:20]) + ('\n…' if len(refused) > 20 else ''))
        # Fuer einen Drop auf einen anderen Tab: dort wird mit Sidecar kopiert
        self._drag_items = accepted
        if not urls:
            return None
        mime = QMimeData()
        mime.setUrls(urls)
        self.statusBar().showMessage(f'{len(items) - len(refused)} Bilder ({len(urls)} Dateien) gezogen', 8000)
        return mime

    def dragEnterEvent(self, event):
        """Von aussen: Ordner (je ein Tab), Template-Dateien (.toml) oder Roster-Dateien (.txt)."""
        if event.source() is not None:
            return
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths and all(p.is_dir() for p in paths):
            event.acceptProposedAction()
        elif paths and all(p.suffix.lower() in ('.toml', '.txt', '.tsv') for p in paths):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths and all(p.is_dir() for p in paths):
            self.open_folders(paths)
            return
        for path in paths:
            if path.suffix.lower() == '.toml':
                self.open_template_file(str(path))
            else:
                self.add_roster_file(str(path))

    # --- Kopieren zwischen Tabs ----------------------------------------------------

    def copy_dragged_to(self, target):
        """Die gezogenen Bilder (RAW, JPG, Sidecar) in den Ordner des Ziel-Tabs kopieren."""
        items, self._drag_items = self._drag_items, []
        if target is None or not items:
            return
        if not target.folder:
            QMessageBox.information(self, 'Kopieren', 'In diesem Tab ist kein Ordner geöffnet.')
            return
        if self.copy_worker and self.copy_worker.isRunning():
            QMessageBox.information(self, 'Kopieren', 'Es wird noch kopiert. Bitte warten, bis das fertig ist.')
            return
        files = []
        for item in items:
            files += item.files
            if item.sidecar and item.sidecar.exists():
                files.append(item.sidecar)
        groups = [g for g in transfer.group_files(files) if not transfer.same_folder(g, target.folder)]
        if not groups:
            return
        decisions = ask_conflicts(groups, target.folder, self)
        if decisions is None:
            return
        worker = CopyWorker(groups, target.folder, decisions)
        worker.target_tab = target
        worker.progress.connect(self._on_copy_progress)
        worker.done.connect(self._on_copy_done)
        self.copy_worker = worker
        self.statusBar().showMessage(f'Kopiere {len(groups)} Bilder nach {target.folder} …')
        worker.start()

    def _on_copy_progress(self, done, total):
        target = self.copy_worker.target_tab if self.copy_worker else None
        name = tab_title(target.folder) if target else ''
        self.statusBar().showMessage(f'Kopiere nach {name}: {done}/{total} …')

    def _on_copy_done(self, copied, skipped, errors):
        target = self.copy_worker.target_tab
        parts = [f'{copied} Bilder nach {tab_title(target.folder)} kopiert']
        if skipped:
            parts.append(f'{skipped} übersprungen')
        self.statusBar().showMessage(', '.join(parts), 10000)
        if errors:
            QMessageBox.warning(self, 'Nicht alles kopiert', '\n'.join(errors[:20]) + ('\n…' if len(errors) > 20 else ''))
        if copied and self.tabs.indexOf(target) >= 0:
            self.rescan(target)

    # --- Grossansicht -------------------------------------------------------------

    def open_viewer(self):
        """Grossansicht des Bildes unter dem Cursor; Kuerzel wirken dann auf genau dieses Bild."""
        index = self.view.currentIndex()
        item = index.data(ItemRole) if index.isValid() else None
        if item is None:
            return
        if self.viewer is None:
            self.viewer = Viewer(self)
            self.viewer.navigate.connect(self._viewer_navigate)
            self.loader.full_ready.connect(self.viewer.set_image)
            self.loader.details_ready.connect(self.viewer.set_details)
            self.viewer.labels = self.settings.labels
            self.viewer.set_info_visible(self.settings.viewer_info_panel)
            self.viewer.info_toggled.connect(self._on_info_toggled)
            zoom = self.viewer.zoom
            handlers = {'viewer_close': self.viewer.close,
                        'viewer_tag_toggle': lambda: self._in_viewer(lambda: self.set_tag(None)),
                        'viewer_zoom_toggle': lambda: zoom.toggle(zoom.cursor_anchor()),
                        'viewer_zoom_in': lambda: zoom.step(1, zoom.cursor_anchor()),
                        'viewer_zoom_out': lambda: zoom.step(-1, zoom.cursor_anchor())}
            for n in range(0, 9):
                handlers[f'viewer_color_{n}'] = lambda n=n: self._in_viewer(lambda: self.set_color_class(n))
            for n in range(0, 6):
                handlers[f'viewer_rating_{n}'] = lambda n=n: self._in_viewer(lambda: self.set_rating(n))
            handlers['viewer_caption'] = self._caption_in_viewer
            handlers['viewer_snapshot_take'] = lambda: self._in_viewer(self.take_snapshot)
            handlers['viewer_snapshot_paste'] = lambda: self._in_viewer(self.paste_snapshot)
            self._bind(handlers, self.viewer, Qt.ShortcutContext.WindowShortcut)
            self.viewer.caption_toggled.connect(self._on_viewer_caption_toggled)
            self.viewer.finished.connect(lambda _: self._move_editor(into_viewer=False))
        self.select_only(item)
        self._show_in_viewer(item)
        self.viewer.show()
        self.viewer.raise_()
        self.viewer.activateWindow()
        self.viewer.set_caption_visible(self.settings.viewer_caption_panel)
        self.viewer.zoom.setFocus()

    # Das Beschriftungs-Panel gibt es nur einmal: es wandert in die Grossansicht und zurueck,
    # samt Inhalt, Kuerzeln (haengen am Panel) und Template-Auswahl.

    def _editor_in_viewer(self):
        return self.viewer is not None and self.viewer.caption_slot.widget() is self.editor

    def _move_editor(self, into_viewer):
        if into_viewer == self._editor_in_viewer():
            return
        if into_viewer:
            self._editor_sizes = self.main_splitter.sizes()
            self.viewer.caption_slot.setWidget(self.editor)
        else:
            had_focus = self.editor.isAncestorOf(QApplication.focusWidget())
            self.viewer.caption_slot.takeWidget()   # sonst loescht die Scrollflaeche das Panel mit
            self.main_splitter.insertWidget(1, self.editor)
            self.main_splitter.setSizes(getattr(self, '_editor_sizes', [1080, 420]))
            if had_focus:
                self.view.setFocus()
        self.editor.show()

    def _on_viewer_caption_toggled(self, visible):
        self._move_editor(into_viewer=visible)
        if self.settings.viewer_caption_panel != visible:
            self.settings.viewer_caption_panel = visible
            self.settings.save()

    def _caption_in_viewer(self):
        """I: Panel einblenden und in die Beschreibung des angezeigten Bildes."""
        item = self.by_key.get(self.viewer.key)
        if item is None:
            return
        if self.selected_keys != {item.key}:
            self.select_only(item)
        self.viewer.set_caption_visible(True)
        self.editor.focus_caption()

    def _show_in_viewer(self, item):
        self.last_previewed_key = item.key
        self.viewer.show_item(item, self.loader.image(item.key), provisional=True)
        self.loader.request_details(item)
        self.loader.request_full(item)

    def _on_info_toggled(self, visible):
        if self.settings.viewer_info_panel != visible:
            self.settings.viewer_info_panel = visible
            self.settings.save()

    def _in_viewer(self, action):
        """Aktion auf das angezeigte Bild anwenden und die Anzeige aktualisieren."""
        item = self.by_key.get(self.viewer.key)
        if item is None:
            return
        if self.selected_keys != {item.key}:
            self.select_only(item)
        action()
        self.viewer.show_item(item, self.viewer._image)

    def _viewer_navigate(self, step):
        current = self.by_key.get(self.viewer.key)
        if current not in self.filtered:
            return
        position = self.filtered.index(current) + step
        if 0 <= position < len(self.filtered):
            item = self.filtered[position]
            self.select_only(item)
            self._show_in_viewer(item)

    # --- Templates, Roster, Einstellungen ----------------------------------------

    def _on_template_changed(self, template):
        self.settings.last_template = template.path if template else ''
        self.settings.save()

    def remember_place(self, place):
        self.places.remember(place)
        self._save_places()

    def _save_places(self):
        self.settings.places = self.places.to_list()
        self.settings.save()
        self.editor.set_place_book(self.places)

    def refresh_templates(self, active_path=''):
        templates, errors = self.template_store.list(self.settings.template_files)
        # Koordinaten aus Template-Dateien (z. B. von einem anderen Rechner) mitlernen
        learned = False
        for template in templates:
            known = self.places.lookup(template.city, template.sublocation)
            if template.latitude is not None and not (known and known.has_coordinates):
                self.places.remember(geo.Place(template.city, template.sublocation,
                                               template.latitude, template.longitude))
                learned = True
        if learned:
            self._save_places()
        self.editor.set_templates(templates, active_path)
        if errors:
            self.statusBar().showMessage('Templates nicht geladen: ' + '; '.join(errors), 15000)

    def edit_template(self, template):
        dialog = TemplateDialog(template, self.places, self)
        accepted = dialog.exec()
        if dialog.places_changed:
            self._save_places()
        if not accepted:
            return
        new = dialog.template()
        if not (new.name or new.headline):
            QMessageBox.warning(self, 'Template unvollständig', 'Bitte einen Namen eingeben.')
            return
        if template and template.path:
            if self.template_store.is_internal(template) and \
                    template_files.default_filename(new) != Path(template.path).name:
                # Umbenannt: neue Datei im Konfigurationsverzeichnis, alte weg
                self.template_store.delete(template)
            else:
                # Bearbeitet: zurueck in dieselbe Datei, auch wenn sie woanders liegt
                new.path = template.path
        try:
            self.template_store.save(new)
        except OSError as e:
            QMessageBox.warning(self, 'Template nicht gespeichert', str(e))
            return
        self.refresh_templates(new.path)

    def open_template_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, 'Template öffnen', self.settings.last_folder or str(Path.home()),
                'Spiel-Templates (*.toml);;Alle Dateien (*)')
        if not path:
            return None
        try:
            template = template_files.load_file(path)
        except TemplateError as e:
            QMessageBox.warning(self, 'Template nicht geladen', str(e))
            return None
        self._remember_template_file(template)
        self.refresh_templates(template.path)
        self.statusBar().showMessage(f'Template „{template.display_name()}“ geladen', 5000)
        return template

    def save_template_as(self, path=None):
        template = self.editor.template
        if template is None:
            return None
        if not path:
            start = Path(template.path).parent if template.path else Path.home()
            path, _ = QFileDialog.getSaveFileName(
                self, 'Template speichern unter', str(start / template_files.default_filename(template)),
                'Spiel-Templates (*.toml)')
        if not path:
            return None
        if not path.lower().endswith(template_files.FILE_SUFFIX):
            path += template_files.FILE_SUFFIX
        copy = dataclasses.replace(template)
        try:
            template_files.save_file(copy, path)
        except OSError as e:
            QMessageBox.warning(self, 'Template nicht gespeichert', str(e))
            return None
        # Ab jetzt wird mit der gespeicherten Datei gearbeitet
        self._remember_template_file(copy)
        self.refresh_templates(copy.path)
        self.statusBar().showMessage(f'Template gespeichert: {path}', 5000)
        return copy

    def _remember_template_file(self, template):
        if self.template_store.is_internal(template):
            return
        if template.path not in self.settings.template_files:
            self.settings.template_files.append(template.path)
            self.settings.save()

    def remove_template(self, template):
        if self.template_store.is_internal(template):
            answer = QMessageBox.question(
                self, 'Template löschen', f'„{template.display_name()}“ löschen?\n{template.path}')
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.template_store.delete(template)
        else:
            # Fremde Dateien werden nur aus der Liste genommen, nie geloescht
            self.settings.template_files = [p for p in self.settings.template_files if p != template.path]
            self.settings.save()
        self.refresh_templates()

    def add_roster_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Roster-Datei hinzufügen', str(Path.home()),
                                                  ROSTER_FILE_FILTER)
        if not path:
            return
        if path not in self.settings.roster_sources:
            self.settings.roster_sources.append(path)
            self.settings.save()
        self.load_roster(force=True)

    def edit_roster(self):
        dialog = RosterEditorDialog(self.settings.roster_sources, self.roster_loader.cached_text, self)
        dialog.saved.connect(lambda path: self.load_roster(force=True))
        dialog.exec()

    def load_roster(self, force=False):
        self.editor.set_roster_status('Roster wird geladen …')
        self.roster_loader.ttl_seconds = self.settings.roster_cache_ttl_minutes * 60
        worker = RosterWorker(self.roster_loader, self.settings.roster_sources, force)
        worker.loaded.connect(self._on_roster_loaded)
        self.roster_worker = worker
        worker.start()

    def _on_roster_loaded(self, roster):
        self.roster = roster
        self.editor.set_roster(roster, self.settings.code_delimiter)
        lines = [f'<b>Roster:</b> {len(roster.entries)} Codes, {len(roster.teams)} Teams']
        for status in roster.status:
            stamp = time.strftime('%d.%m. %H:%M', time.localtime(status.fetched_at)) if status.fetched_at else ''
            color = '' if status.ok and status.origin != 'letzte gute Version' else ' style="color:#d64541"'
            name = html.escape(status.source.rsplit('/', 1)[-1])
            detail = f' – {html.escape(status.message)}' if status.message else ''
            lines.append(f'<span{color}>{name}: {status.origin} {stamp}{detail}</span>')
        if roster.conflicts:
            lines.append(f'<span style="color:#d64541">{len(roster.conflicts)} widersprüchliche Codes: '
                         + html.escape(', '.join(c[0] for c in roster.conflicts[:10])) + '</span>')
        if not roster.is_usable:
            lines.append('<span style="color:#d64541">Kein Roster verfügbar – Codes können nicht aufgelöst werden.</span>')
        self.editor.set_roster_status('<br>'.join(lines))

    def edit_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if not dialog.exec():
            return
        old_recursive, old_exiftool = self.settings.recursive, self.settings.exiftool_path
        dialog.apply().save()
        self._fill_color_filter()
        self.load_roster(force=True)
        if old_exiftool != self.settings.exiftool_path:
            QMessageBox.information(self, 'ExifTool', 'Der neue ExifTool-Pfad gilt nach einem Neustart.')
        if old_recursive != self.settings.recursive:
            for tab in self.all_tabs():
                if tab.folder:
                    self.rescan(tab)
        self.apply_filter(False)

    # --- Beenden ----------------------------------------------------------------

    def closeEvent(self, event):
        if self.writer.pending_count() and not self._wait_for_writer('Beenden'):
            event.ignore()
            return
        if self.copy_worker and self.copy_worker.isRunning():
            answer = QMessageBox.question(self, 'Kopieren läuft', 'Es wird noch kopiert. Abbrechen und beenden?\n'
                                          'Bereits kopierte Bilder bleiben, angefangene werden verworfen.')
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        """Idempotent; auch bei SIGTERM und app.quit() ohne closeEvent."""
        if getattr(self, '_shut_down', False):
            return
        self._shut_down = True
        for tab in self.all_tabs():
            tab.stop_scan()
        if self.copy_worker and self.copy_worker.isRunning():
            self.copy_worker.cancel()
            self.copy_worker.wait(60000)
        self.writer.stop()
        self.loader.shutdown()
        self.pool.close()
        self.settings.save()


def run(argv):
    import signal
    from PySide6.QtCore import QTimer

    reap_orphans()
    app = QApplication(argv)
    open_requests = OpenRequests(app)  # vor allem anderen, der Finder schickt sofort
    # Qt-eigene Texte (Schliessen, Abbrechen, Dateidialoge) in der Systemsprache
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    translator = QTranslator(app)
    if translator.load(QLocale.system(), 'qtbase', '_', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    # SIGTERM/Strg+C: sauber beenden, damit Schreibauftraege fertig werden und
    # ExifTool-Prozesse nicht liegen bleiben. Der Timer gibt Python regelmaessig
    # die Kontrolle, sonst kaeme der Signal-Handler in Qts Event-Loop nie dran.
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    heartbeat = QTimer()
    heartbeat.start(500)
    heartbeat.timeout.connect(lambda: None)
    app.setApplicationName('Captioner')
    app.setOrganizationName('chuc')
    settings = config.Settings.load()
    try:
        find_exiftool(settings.exiftool_path)
    except ExifToolError as e:
        QMessageBox.critical(None, 'ExifTool fehlt', str(e))
        return 1
    folders = [arg for arg in argv[1:] if arg]  # make run ohne FOLDER uebergibt ""
    from .resources import app_icon
    app.setWindowIcon(app_icon())
    window = MainWindow(settings, folders)
    open_requests.set_handler(window.open_paths)
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()
