"""Hauptfenster: Ordner in Tabs, Filter, paginierte Galerie, Beschriftung, Drag nach Lightroom."""
import contextlib
import dataclasses
import html
import json
import logging
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QMimeData, QObject, Qt, QTime, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QTimeEdit,
                               QLabel, QMainWindow, QMessageBox, QProgressDialog, QSplitter,
                               QToolButton, QVBoxLayout, QWidget)

from .. import WEBSITE_LINK, codes, config, geo, i18n, keywords, metadata, scanner, transfer, undo
from ..i18n import _, N_, ngettext
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

TAG_FILTERS = [(N_('Alle Tags'), None), (N_('getaggt'), True), (N_('nicht getaggt'), False)]

RATING_FILTERS = [(N_('Alle Sterne'), None), (N_('★ und mehr'), 1), (N_('★★ und mehr'), 2),
                  (N_('★★★ und mehr'), 3), (N_('★★★★ und mehr'), 4), ('★★★★★', 5), (N_('ohne Sterne'), 0)]


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
        """raw=None entfernt den Eintrag (Rueckgaengig)."""
        if raw is None:
            self.data.pop(str(item.primary), None)
        else:
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


def camera_key(model, serial):
    """Kamera als Text fuer QComboBox-Daten (Tupel vergleicht Qt nicht zuverlaessig)."""
    return f'{model}\x1f{serial}'


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
        self.keyword_history = keywords.KeywordHistory(config.cache_dir() / 'keywords.json')

        self.edited_keys = set()   # ueber alle Tabs; Keys sind Pfade
        self.last_raw_caption = ''
        self.last_headline = ''    # fuer Bilder ohne Titel, wenn das Template keinen vorgibt
        self.roster_worker = None
        self.copy_worker = None
        self._drag_items = []
        self.undo_stack = undo.UndoStack()
        self._recording = None
        self.viewer = None
        self._syncing_selection = False

        self._build_ui()
        self.refresh_templates(settings.last_template)
        self.load_roster()
        self._restore_tabs()
        # Ein Ordner (str/Path) oder eine Liste, z. B. von der Kommandozeile
        folders = [folder] if isinstance(folder, (str, Path)) else list(folder or [])
        if folders:
            self.open_folders(folders)
        self._restoring = False
        self._remember_tabs()

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
        file_menu = bar.addMenu(_('Ablage'))
        action(file_menu, _('Ordner öffnen …'), self.choose_folder, QKeySequence.StandardKey.Open)
        action(file_menu, _('Ordner in neuem Tab öffnen …'), lambda: self.choose_folder(new_tab=True))
        action(file_menu, _('Neu einlesen'), lambda: self.folder and self.rescan(self.tab), QKeySequence('F5'))
        file_menu.addSeparator()
        action(file_menu, _('Tab schließen'), lambda: self.close_tab(self.tabs.currentIndex()))
        file_menu.addSeparator()
        action(file_menu, _('Einstellungen …'), self.edit_settings, QKeySequence.StandardKey.Preferences,
               role.PreferencesRole)
        action(file_menu, _('Beenden'), self.close, QKeySequence.StandardKey.Quit, role.QuitRole)

        edit_menu = bar.addMenu(_('Bearbeiten'))
        # Kuerzel Cmd+Z/Cmd+Shift+Z kommen aus der Keymap (im Textfeld gilt dessen Rueckgaengig)
        self.undo_action = action(edit_menu, _('Rückgängig'), self.undo)
        self.redo_action = action(edit_menu, _('Wiederholen'), self.redo)
        self._update_undo_actions()

        template_menu = bar.addMenu(_('Template'))
        action(template_menu, _('Neues Template …'), lambda: self.edit_template(None))
        action(template_menu, _('Template bearbeiten …'),
               lambda: self.editor.template and self.edit_template(self.editor.template))
        template_menu.addSeparator()
        action(template_menu, _('Template-Datei laden …'), self.open_template_file)
        action(template_menu, _('Template speichern unter …'), self.save_template_as)
        template_menu.addSeparator()
        action(template_menu, _('Template auf Auswahl anwenden'), self.apply_template)

        roster_menu = bar.addMenu(_('Roster'))
        action(roster_menu, _('Roster bearbeiten …'), self.edit_roster)
        action(roster_menu, _('Roster neu laden'), lambda: self.load_roster(force=True))
        action(roster_menu, _('Roster-Datei hinzufügen …'), self.add_roster_file)

        help_menu = bar.addMenu(_('Hilfe'))
        action(help_menu, _('Tastenkürzel'), self.show_shortcuts)
        action(help_menu, _('Captioner-Website'), lambda: QDesktopServices.openUrl(QUrl(WEBSITE_LINK)))
        action(help_menu, _('Über Captioner'), self.show_about, role=role.AboutRole)

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
            self.rating_filter.addItem(_(label), value)
        self.color_filter = QComboBox()
        self.tag_filter = QComboBox()
        for label, value in TAG_FILTERS:
            self.tag_filter.addItem(_(label), value)
        self.uncaptioned_filter = QCheckBox(_('nur unbeschriftet'))
        self.folder_label = QLabel(_('Kein Ordner geöffnet'))
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

        # Zweite Zeile: Suche, Kamera, Uhrzeit
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(_('Suchen: Dateiname, Titel, Beschreibung, Tags'))
        self.search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(lambda: self.apply_filter(True))
        self.search.textChanged.connect(self._search_timer.start)
        self.camera_filter = QComboBox()
        self.camera_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.camera_filter.currentIndexChanged.connect(lambda: self.apply_filter(True))
        self.time_filter = QCheckBox(_('Uhrzeit'))
        self.time_from = QTimeEdit(QTime(0, 0))
        self.time_to = QTimeEdit(QTime(23, 59))
        for edit in (self.time_from, self.time_to):
            edit.setDisplayFormat('HH:mm')
            edit.setEnabled(False)
            edit.timeChanged.connect(lambda: self.time_filter.isChecked() and self.apply_filter(True))
        self.time_filter.toggled.connect(self._time_filter_toggled)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.camera_filter)
        search_row.addWidget(self.time_filter)
        search_row.addWidget(self.time_from)
        search_row.addWidget(QLabel('–'))
        search_row.addWidget(self.time_to)
        self._fill_camera_filter()

        # Reiter oben ueber die ganze Fensterbreite, Galerien darunter links
        self.tabs = FolderTabs(self)
        self.tabs.bar.files_dropped.connect(lambda index: self.copy_dragged_to(self.tabs.widget(index)))
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.bar.tabMoved.connect(self._remember_tabs)
        new_tab_button = QToolButton(text='+')
        new_tab_button.setToolTip(_('Ordner in neuem Tab öffnen'))
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
        left_layout.addLayout(search_row)
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
        self.editor.set_keyword_history(self.keyword_history)
        self.editor.set_spellcheck(self.settings.spellcheck)

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
        self.color_filter.addItem(_('Alle Farben'), None)
        self.color_filter.addItem(_('ohne Farbe'), 0)
        for n in range(1, 9):
            label = self.settings.labels[n - 1] if n <= len(self.settings.labels) else ''
            text = _('Farbklasse {number} ({label})').format(number=n, label=label) if label \
                else _('Farbklasse {number}').format(number=n)
            self.color_filter.addItem(text, n)
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
            'undo': self.undo,
            'redo': self.redo,
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
        folders = folderdialog.choose_folders(self, _('Ordner öffnen – mehrere mit ⌘-Klick'), start)
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
                self, _('Viele Ordner'),
                ngettext('{count} Ordner mit Bildern gefunden. Alle in Tabs öffnen?',
                         '{count} Ordner mit Bildern gefunden. Alle in Tabs öffnen?',
                         len(expanded)).format(count=len(expanded)) + '\n\n'
                + '\n'.join(expanded[:10]) + ('\n…' if len(expanded) > 10 else ''))
            if answer != QMessageBox.StandardButton.Yes:
                return []
        tabs = [self.open_folder(folder, new_tab=new_tab and position == 0)
                for position, folder in enumerate(expanded)]
        if tabs:
            self.tabs.setCurrentWidget(tabs[0])
        return tabs

    def _restore_tabs(self):
        """Tabs vom letzten Mal; Ordner, die fehlen (Karte nicht eingesteckt), fallen weg."""
        self._restoring = True
        folders = [f for f in self.settings.open_tabs if isinstance(f, str) and Path(f).is_dir()]
        for folder in folders:
            self.open_folder(folder)
        active = self.tab_for_folder(self.settings.active_tab) if self.settings.active_tab else None
        if active is not None:
            self.tabs.setCurrentWidget(active)

    def _remember_tabs(self, *_args):
        if getattr(self, '_restoring', True) or getattr(self, '_shut_down', False):
            return
        open_tabs = [tab.folder for tab in self.all_tabs() if tab.folder]
        active = (self.tab.folder or '') if self.tab is not None else ''
        if (open_tabs, active) != (self.settings.open_tabs, self.settings.active_tab):
            self.settings.open_tabs, self.settings.active_tab = open_tabs, active
            self.settings.save()

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
        self._remember_tabs()
        return tab

    def rescan(self, tab, wait_for_writer=True):
        if wait_for_writer and self.writer.pending_count() and not self._wait_for_writer(_('Neu einlesen')):
            return
        tab.stop_scan()
        tab.all_items, tab.by_key, tab.filtered = [], {}, []
        tab.selected_keys.clear()
        tab.page = 0
        tab.model.set_items([])
        self._set_tab_status(tab, _('{folder} – wird eingelesen …').format(folder=tab.folder))
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
        # Stichwoerter der Bilder fuer Vorschlaege merken (ohne die Reihenfolge zu aendern)
        self.keyword_history.add([k for item in chunk for k in item.meta.keywords], recent=False)
        loaded = sum(1 for item in tab.all_items if item.meta_loaded)
        self._set_tab_status(tab, _('{folder} – Metadaten {loaded}/{total} …').format(
            folder=tab.folder, loaded=loaded, total=len(tab.all_items)))
        if tab is self.tab and self._selected_items():
            self._show_selection_in_editor()

    def _on_scan_failed(self, message):
        tab = self._scanning_tab()
        if tab is not None:
            QMessageBox.warning(self, _('Einlesen fehlgeschlagen'), f'{tab.folder}\n\n{message}')

    def _on_scan_finished(self):
        tab = self._scanning_tab()
        if tab is None:
            return
        scanner.sort_items(tab.all_items)
        self.keyword_history.save()
        elapsed = time.time() - tab.scan_started
        count = len(tab.all_items)
        self._set_tab_status(tab, ngettext('{folder} – {count} Bild ({seconds} s)', '{folder} – {count} Bilder ({seconds} s)',
                                           count).format(folder=tab.folder, count=count, seconds=f'{elapsed:.1f}'))
        if tab is self.tab:
            self._fill_camera_filter()
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
        self._fill_camera_filter()
        self.apply_filter(False)
        self._remember_tabs()

    def close_tab(self, index):
        tab = self.tabs.widget(index)
        if tab is None:
            return
        if self.copy_worker and self.copy_worker.isRunning() and self.copy_worker.target_tab is tab:
            QMessageBox.information(self, _('Tab schließen'), _('In diesen Ordner wird gerade kopiert.'))
            return
        tab.stop_scan()
        self.tabs.removeTab(index)
        tab.deleteLater()
        if self.tabs.count() == 0:
            self.new_tab()
        self._remember_tabs()

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
        camera = self.camera_filter.currentData()
        if camera is not None and camera_key(item.camera, item.serial) != camera:
            return False
        if self.time_filter.isChecked():
            taken = scanner.time_of_day(item)
            start, end = self.time_from.time().toString('HH:mm'), self.time_to.time().toString('HH:mm')
            # ueber Mitternacht (22:00-01:00) mit oder statt und
            inside = start <= taken <= end if start <= end else (taken >= start or taken <= end)
            if not taken or not inside:
                return False
        if not scanner.matches_text(item, self.search.text()):
            return False
        return True

    def _time_filter_toggled(self, on):
        for edit in (self.time_from, self.time_to):
            edit.setEnabled(on)
        if on:
            # Vorschlag: Zeitraum der Bilder im Tab
            times = sorted(t for t in (scanner.time_of_day(i) for i in self.all_items) if t)
            if times:
                self.time_from.setTime(QTime.fromString(times[0], 'HH:mm'))
                self.time_to.setTime(QTime.fromString(times[-1], 'HH:mm'))
        self.apply_filter(True)

    def _fill_camera_filter(self):
        """Kameras des aktiven Tabs; die Auswahl bleibt, solange es die Kamera noch gibt."""
        current = self.camera_filter.currentData()
        self.camera_filter.blockSignals(True)
        self.camera_filter.clear()
        self.camera_filter.addItem(_('Alle Kameras'), None)
        tab = self.tab if hasattr(self, 'tabs') else None
        for (model, serial), label in scanner.camera_labels(tab.all_items if tab else []).items():
            self.camera_filter.addItem(label, camera_key(model, serial))
        index = self.camera_filter.findData(current) if current is not None else 0
        self.camera_filter.setCurrentIndex(max(0, index))
        self.camera_filter.setVisible(self.camera_filter.count() > 2)  # bei einer Kamera nichts zu waehlen
        self.camera_filter.blockSignals(False)

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
            text = 'Captioner\n' + _('Ordner öffnen ({keys}) oder einen Ordner hierher ziehen').format(keys=keys)
        elif self.tab.scanning() and not self.all_items:
            text = _('Ordner wird eingelesen …')
        elif not self.all_items:
            text = _('Keine Bilder in diesem Ordner (JPG, NEF und andere RAWs, DNG, TIFF)')
        else:
            text = _('Kein Bild passt zu den Filtern')
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
        text = ngettext('Seite {page} / {pages} · {count} Bild', 'Seite {page} / {pages} · {count} Bilder',
                        total).format(page=self.page + 1, pages=self.page_count(), count=total)
        if self.selected_keys:
            text += ' · ' + _('{count} ausgewählt').format(count=len(self._selected_items()))
        self.page_label.setText(text)
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
        recording = getattr(self, '_recording', None)
        if recording is not None and item.key not in recording:
            recording[item.key] = undo.Change(item, item.meta, meta, raw_before=self.raw_captions.get(item))
        elif recording is not None:
            recording[item.key].after = meta
        item.meta = meta
        item.error = None
        self.edited_keys.add(item.key)
        self.writer.enqueue(item, meta)

    @contextlib.contextmanager
    def _undoable(self, label):
        """Alle Aenderungen darin sind ein Schritt fuer Rueckgaengig (verschachtelt: der aeussere)."""
        outer = getattr(self, '_recording', None) is None
        if outer:
            self._recording = {}
        try:
            yield
        finally:
            if outer:
                changes = list(self._recording.values())
                self._recording = None
                for change in changes:
                    change.raw_after = self.raw_captions.get(change.item)
                self.undo_stack.push(undo.Step(label, changes))
                self._update_undo_actions()

    def undo(self):
        self._apply_step(self.undo_stack.undo(), forward=False)

    def redo(self):
        self._apply_step(self.undo_stack.redo(), forward=True)

    def _apply_step(self, step, forward):
        if step is None:
            return
        for change in step.changes:
            target, raw = (change.after, change.raw_after) if forward else (change.before, change.raw_before)
            self._enqueue(change.item, undo.reverting(change.item.meta, target))
            self.raw_captions.set(change.item, raw)
        for tab in self.all_tabs():
            tab.model.refresh([c.item.key for c in step.changes if c.item.key in tab.by_key])
        self._show_selection_in_editor()
        if self.viewer is not None and self.viewer.isVisible() and self.viewer._item is not None:
            self.viewer.show_item(self.viewer._item, self.viewer._image)
        self._update_status()
        self._update_undo_actions()
        count = len(step.changes)
        text = (ngettext('Wiederholt: {action} ({count} Bild)', 'Wiederholt: {action} ({count} Bilder)', count)
                if forward else
                ngettext('Rückgängig: {action} ({count} Bild)', 'Rückgängig: {action} ({count} Bilder)', count))
        self.statusBar().showMessage(text.format(action=_(step.label), count=count), 5000)

    def _update_undo_actions(self):
        if not hasattr(self, 'undo_action'):
            return
        label, redo_label = self.undo_stack.undo_label, self.undo_stack.redo_label
        self.undo_action.setEnabled(label is not None)
        self.undo_action.setText(_('Rückgängig: {action}').format(action=_(label)) if label else _('Rückgängig'))
        self.redo_action.setEnabled(redo_label is not None)
        self.redo_action.setText(_('Wiederholen: {action}').format(action=_(redo_label)) if redo_label
                                 else _('Wiederholen'))

    def set_rating(self, rating):
        items = self._selected_items()
        with self._undoable(N_('Bewertung')):
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
        with self._undoable(N_('Farbklasse')):
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
        with self._undoable(N_('Tag')):
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
        self.statusBar().showMessage(_('Beschriftung von {name} kopiert').format(name=items[0].name), 5000)

    def paste_snapshot(self):
        with self._undoable(N_('Beschriftung einfügen')):
            self._paste_snapshot()

    def _paste_snapshot(self):
        """
        In alle ausgewaehlten Bilder einfuegen und speichern. Gerechnet wird wie beim
        Speichern, je Bild: Codes aufloesen, Anhang mit dessen Datum, Personen-Tags, GPS.
        """
        snapshot = getattr(self, 'snapshot', None)
        items = self._selected_items()
        if not snapshot or not items:
            return
        resolution = codes.resolve(snapshot['raw_caption'], self.roster, self.settings.code_delimiter)
        headline = codes.resolve(snapshot['headline'], self.roster, self.settings.code_delimiter)
        unknown = resolution.unknown + [c for c in headline.unknown if c not in resolution.unknown]
        if unknown:
            QMessageBox.warning(self, _('Nicht eingefügt'), _('Unbekannte Codes in der kopierten Beschreibung: {codes}')
                                .format(codes=', '.join(unknown)))
            return
        self.save_caption(dict(snapshot, resolution=resolution, caption_modified=True,
                               headline=metadata.single_line(headline.text)), 0)
        self._show_selection_in_editor()
        self.statusBar().showMessage(ngettext('Beschriftung in {count} Bild eingefügt', 'Beschriftung in {count} Bilder eingefügt',
                                              len(items)).format(count=len(items)), 5000)

    def save_and_close(self):
        """Wie "Save Changes and Close Dialog": speichern, zurueck in die Galerie bzw. aufs Bild."""
        if self.editor.submit(0):
            if self._editor_in_viewer():
                self.viewer.zoom.setFocus()
            else:
                self.view.setFocus()

    def save_caption(self, fields, step):
        with self._undoable(N_('Beschriftung')):
            self._save_caption(fields, step)

    def _save_caption(self, fields, step):
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
                QMessageBox.warning(self, _('Nicht gespeichert'), f'{item.name}: ' + '; '.join(problems))
                return
            planned.append((item, meta))
        for item, meta in planned:
            self._enqueue(item, meta)
            if apply_caption:
                self.raw_captions.set(item, fields['raw_caption'])
        if planned:
            self.keyword_history.add(fields['keywords'])
            self.keyword_history.save()
        if apply_caption and fields['raw_caption'].strip():
            self.last_raw_caption = fields['raw_caption']
        if fields['headline']:
            self.last_headline = fields['headline']
        self.model.refresh([item.key for item, _meta in planned])
        self._update_status()
        if self.viewer is not None and self.viewer.isVisible():
            shown = next((item for item, _meta in planned if item.key == self.viewer.key), None)
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
        with self._undoable(N_('Template anwenden')):
            self._apply_template()

    def _apply_template(self):
        template = self.editor.template
        if not template:
            QMessageBox.information(self, _('Kein Template'), _('Bitte zuerst ein Spiel-Template auswählen oder anlegen.'))
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
            self.statusBar().showMessage(_('Fehler: {message}').format(message=message), 15000)
        tab.model.refresh([key])
        self._update_status()

    def _update_status(self):
        pending = self.writer.pending_count()
        errors = sum(1 for tab in self.all_tabs() for item in tab.all_items if getattr(item, 'error', None))
        parts = []
        if pending:
            parts.append(_('schreibe {count} …').format(count=pending))
        if errors:
            parts.append('<span style="color:#d64541">%s</span>'
                         % ngettext('{count} Fehler', '{count} Fehler', errors).format(count=errors))
        self.status_label.setText(' · '.join(parts) or _('alles gespeichert'))
        self.model.refresh()

    def _wait_for_writer(self, purpose):
        dialog = QProgressDialog(_('Metadaten werden geschrieben ({purpose}) …').format(purpose=purpose), None, 0, 0, self)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()
        QApplication.processEvents()
        ok = self.writer.flush(timeout=120)
        dialog.close()
        if not ok:
            QMessageBox.warning(self, _('Schreiben dauert an'), _('Es werden noch Metadaten geschrieben. Bitte kurz warten.'))
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
                    QMessageBox.warning(self, _('Noch nicht bereit'), _('Es werden noch Metadaten geschrieben.'))
                    return None
            finally:
                QApplication.restoreOverrideCursor()

        refused, urls, accepted = [], [], []
        for item in items:
            if getattr(item, 'error', None):
                refused.append(f'{item.name}: {item.error}')
                continue
            if item.raw and item.key in self.edited_keys and not (item.sidecar and item.sidecar.exists()):
                refused.append(_('{name}: XMP-Sidecar fehlt').format(name=item.name))
                continue
            accepted.append(item)
            for path in item.files:
                urls.append(QUrl.fromLocalFile(str(path)))
            if self.settings.drag_include_sidecars and item.raw and item.sidecar and item.sidecar.exists():
                urls.append(QUrl.fromLocalFile(str(item.sidecar)))
        if refused:
            QMessageBox.warning(self, _('Nicht alle Bilder übergeben'),
                                _('Diese Bilder werden nicht gezogen, ihre Metadaten sind nicht sicher gespeichert:')
                                + '\n\n'
                                + '\n'.join(refused[:20]) + ('\n…' if len(refused) > 20 else ''))
        # Fuer einen Drop auf einen anderen Tab: dort wird mit Sidecar kopiert
        self._drag_items = accepted
        if not urls:
            return None
        mime = QMimeData()
        mime.setUrls(urls)
        self.statusBar().showMessage(_('{images} ({files}) gezogen').format(
            images=ngettext('{count} Bild', '{count} Bilder', len(accepted)).format(count=len(accepted)),
            files=ngettext('{count} Datei', '{count} Dateien', len(urls)).format(count=len(urls))), 8000)
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
            QMessageBox.information(self, _('Kopieren'), _('In diesem Tab ist kein Ordner geöffnet.'))
            return
        if self.copy_worker and self.copy_worker.isRunning():
            QMessageBox.information(self, _('Kopieren'), _('Es wird noch kopiert. Bitte warten, bis das fertig ist.'))
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
        self.statusBar().showMessage(ngettext('Kopiere {count} Bild nach {folder} …', 'Kopiere {count} Bilder nach {folder} …',
                                              len(groups)).format(count=len(groups), folder=target.folder))
        worker.start()

    def _on_copy_progress(self, done, total):
        target = self.copy_worker.target_tab if self.copy_worker else None
        name = tab_title(target.folder) if target else ''
        self.statusBar().showMessage(_('Kopiere nach {name}: {done}/{total} …').format(name=name, done=done, total=total))

    def _on_copy_done(self, copied, skipped, errors):
        target = self.copy_worker.target_tab
        parts = [ngettext('{count} Bild nach {folder} kopiert', '{count} Bilder nach {folder} kopiert', copied)
                 .format(count=copied, folder=tab_title(target.folder))]
        if skipped:
            parts.append(_('{count} übersprungen').format(count=skipped))
        self.statusBar().showMessage(', '.join(parts), 10000)
        if errors:
            QMessageBox.warning(self, _('Nicht alles kopiert'), '\n'.join(errors[:20]) + ('\n…' if len(errors) > 20 else ''))
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
            handlers['viewer_undo'] = self.undo
            handlers['viewer_redo'] = self.redo
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
        self.keyword_history.add([k for t in templates for k in t.keywords], recent=False)
        if errors:
            self.statusBar().showMessage(_('Templates nicht geladen: {errors}').format(errors='; '.join(errors)), 15000)

    def edit_template(self, template):
        dialog = TemplateDialog(template, self.places, self)
        accepted = dialog.exec()
        if dialog.places_changed:
            self._save_places()
        if not accepted:
            return
        new = dialog.template()
        if not (new.name or new.headline):
            QMessageBox.warning(self, _('Template unvollständig'), _('Bitte einen Namen eingeben.'))
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
            QMessageBox.warning(self, _('Template nicht gespeichert'), str(e))
            return
        self.refresh_templates(new.path)

    def open_template_file(self, path=None):
        if not path:
            path, _filter = QFileDialog.getOpenFileName(
                self, _('Template-Datei laden'), self.settings.last_folder or str(Path.home()),
                _('Spiel-Templates (*.toml)') + ';;' + _('Alle Dateien (*)'))
        if not path:
            return None
        try:
            template = template_files.load_file(path)
        except TemplateError as e:
            QMessageBox.warning(self, _('Template nicht geladen'), str(e))
            return None
        self._remember_template_file(template)
        self.refresh_templates(template.path)
        self.statusBar().showMessage(_('Template „{name}“ geladen').format(name=template.display_name()), 5000)
        return template

    def save_template_as(self, path=None):
        template = self.editor.template
        if template is None:
            return None
        if not path:
            start = Path(template.path).parent if template.path else Path.home()
            path, _filter = QFileDialog.getSaveFileName(
                self, _('Template speichern unter'), str(start / template_files.default_filename(template)),
                _('Spiel-Templates (*.toml)'))
        if not path:
            return None
        if not path.lower().endswith(template_files.FILE_SUFFIX):
            path += template_files.FILE_SUFFIX
        copy = dataclasses.replace(template)
        try:
            template_files.save_file(copy, path)
        except OSError as e:
            QMessageBox.warning(self, _('Template nicht gespeichert'), str(e))
            return None
        # Ab jetzt wird mit der gespeicherten Datei gearbeitet
        self._remember_template_file(copy)
        self.refresh_templates(copy.path)
        self.statusBar().showMessage(_('Template gespeichert: {path}').format(path=path), 5000)
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
                self, _('Template löschen'),
                _('„{name}“ löschen?').format(name=template.display_name()) + f'\n{template.path}')
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
            path, _filter = QFileDialog.getOpenFileName(self, _('Roster-Datei hinzufügen'), str(Path.home()),
                                                  _(ROSTER_FILE_FILTER))
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
        self.editor.set_roster_status(_('Roster wird geladen …'))
        self.roster_loader.ttl_seconds = self.settings.roster_cache_ttl_minutes * 60
        worker = RosterWorker(self.roster_loader, self.settings.roster_sources, force)
        worker.loaded.connect(self._on_roster_loaded)
        self.roster_worker = worker
        worker.start()

    def _on_roster_loaded(self, roster):
        self.roster = roster
        self.editor.set_roster(roster, self.settings.code_delimiter)
        lines = ['<b>%s</b> %s, %s' % (
            _('Roster:'), ngettext('{count} Code', '{count} Codes', len(roster.entries)).format(count=len(roster.entries)),
            ngettext('{count} Team', '{count} Teams', len(roster.teams)).format(count=len(roster.teams)))]
        for status in roster.status:
            stamp = time.strftime('%d.%m. %H:%M', time.localtime(status.fetched_at)) if status.fetched_at else ''
            color = '' if status.ok and status.origin != 'letzte gute Version' else ' style="color:#d64541"'
            name = html.escape(status.source.rsplit('/', 1)[-1])
            detail = f' – {html.escape(status.message)}' if status.message else ''
            origin = html.escape(_(status.origin)) if status.origin else ''
            lines.append(f'<span{color}>{name}: {origin} {stamp}{detail}</span>')
        if roster.conflicts:
            text = ngettext('{count} widersprüchlicher Code: {codes}', '{count} widersprüchliche Codes: {codes}',
                            len(roster.conflicts)).format(count=len(roster.conflicts),
                                                          codes=', '.join(c[0] for c in roster.conflicts[:10]))
            lines.append(f'<span style="color:#d64541">{html.escape(text)}</span>')
        if not roster.is_usable:
            lines.append('<span style="color:#d64541">%s</span>'
                         % html.escape(_('Kein Roster verfügbar – Codes können nicht aufgelöst werden.')))
        self.editor.set_roster_status('<br>'.join(lines))

    def edit_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if not dialog.exec():
            return
        old_recursive, old_exiftool = self.settings.recursive, self.settings.exiftool_path
        dialog.apply().save()
        self.editor.set_spellcheck(self.settings.spellcheck)
        self._fill_color_filter()
        self.load_roster(force=True)
        if old_exiftool != self.settings.exiftool_path:
            QMessageBox.information(self, 'ExifTool', _('Der neue ExifTool-Pfad gilt nach einem Neustart.'))
        if old_recursive != self.settings.recursive:
            for tab in self.all_tabs():
                if tab.folder:
                    self.rescan(tab)
        self.apply_filter(False)

    # --- Beenden ----------------------------------------------------------------

    def closeEvent(self, event):
        if self.writer.pending_count() and not self._wait_for_writer(_('Beenden')):
            event.ignore()
            return
        if self.copy_worker and self.copy_worker.isRunning():
            answer = QMessageBox.question(self, _('Kopieren läuft'), _('Es wird noch kopiert. Abbrechen und beenden?\n'
                                                            'Bereits kopierte Bilder bleiben, angefangene werden verworfen.'))
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

    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    reap_orphans()
    app = QApplication(argv)
    open_requests = OpenRequests(app)  # vor allem anderen, der Finder schickt sofort
    settings = config.Settings.load()
    # Sprache aus den Einstellungen ('' = wie das System), vor dem ersten Text
    lang = i18n.setup(i18n.resolve(getattr(settings, 'language', ''), QLocale.system().uiLanguages()))
    # Qt-eigene Texte (Schliessen, Abbrechen, Dateidialoge) in derselben Sprache
    translator = QTranslator(app)
    if translator.load(QLocale(lang), 'qtbase', '_', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
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
    try:
        find_exiftool(settings.exiftool_path)
    except ExifToolError as e:
        QMessageBox.critical(None, _('ExifTool fehlt'), str(e))
        return 1
    folders = [arg for arg in argv[1:] if arg]  # make run ohne FOLDER uebergibt ""
    from .resources import app_icon
    app.setWindowIcon(app_icon())
    window = MainWindow(settings, folders)
    open_requests.set_handler(window.open_paths)
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()
