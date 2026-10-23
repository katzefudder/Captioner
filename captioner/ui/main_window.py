"""Hauptfenster: Ordner in Tabs, Filter, paginierte Galerie, Beschriftung, Drag nach Lightroom."""
import contextlib
import dataclasses
import html
import json
import logging
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QMimeData, QObject, Qt, QTime, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QTimeEdit,
                               QLabel, QMainWindow, QMenu, QMessageBox, QProgressDialog, QSlider, QSplitter,
                               QPushButton, QToolButton, QVBoxLayout, QWidget)

from .. import (WEBSITE_LINK, manual_path, codes, config, geo, i18n, keywords, metadata, rename, replace, scanner,
               transfer, undo, updates, version)
from ..i18n import _, N_, ngettext
from ..exiftool import ExifToolError, ExifToolPool, find_exiftool, reap_orphans
from ..previews import PreviewCache
from ..roster import Roster, RosterLoader
from .. import templates as template_files
from ..templates import TemplateError, TemplateStore, unique
from . import keymap
from .dialogs import ROSTER_FILE_FILTER, SettingsDialog, ShortcutsDialog, TemplateDialog
from .shortcuteditor import ShortcutEditorDialog
from .about import AboutDialog
from .updatecheck import UpdateChecker
from .editor import CaptionEditor, template_folder_label
from .renamedialog import RenameDialog
from .replacedialog import ReplaceDialog
from .rostereditor import RosterEditorDialog
from . import filemanager, folderdialog, instance
from .viewer import Viewer
from .gallery import CLASS_COLORS, MAX_TILE_W, MIN_TILE_W, ItemRole
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
        self._save()

    def move(self, paths):
        """Nach dem Umbenennen: {alter Pfad: neuer Pfad} der Hauptdateien."""
        for old, new in paths.items():
            if str(old) in self.data:
                self.data[str(new)] = self.data.pop(str(old))
        self._save()

    def _save(self):
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

    def add(self, paths):
        """Ordner aus einem weiteren Start (Windows, ui/instance.py), gesammelt wie FileOpen."""
        self.paths.extend(paths)
        self.timer.start()

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


# Fenstertitel; Markenzeile, in jeder Sprache gleich (nicht uebersetzt)
WINDOW_TITLE = 'Captioner {version} - The Photo Captioning Tool for Professionals'


class MainWindow(QMainWindow):
    folder = _tab_attribute('folder')
    all_items = _tab_attribute('all_items')
    by_key = _tab_attribute('by_key')
    filtered = _tab_attribute('filtered')
    selected_keys = _tab_attribute('selected_keys')
    scan_worker = _tab_attribute('scan_worker')
    model = _tab_attribute('model')
    view = _tab_attribute('view')
    count_label = _tab_attribute('count_label')

    def __init__(self, settings: config.Settings, folder=None):
        super().__init__()
        self.settings = settings
        keymap.apply(settings.shortcuts)   # eigene Kuerzel, bevor Menues und Panel sie anzeigen
        self.setWindowTitle(WINDOW_TITLE.format(version=version()))
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
        self._setup_update_check()

    # --- Aufbau ---------------------------------------------------------------

    def _build_menus(self):
        """
        Menueleiste; auf macOS oben am Bildschirm, "Ueber", "Einstellungen" und "Beenden"
        wandern dort ins App-Menue "Captioner". Menuepunkte zu Befehlen mit Keymap-Kuerzel
        (Tab schliessen, Template, F1) bekommen kein eigenes Kuerzel: zwei gleiche Kuerzel loest
        Qt nicht aus, und Cmd+W gehoert in der Grossansicht dieser.
        """
        bar = self.menuBar()
        self._menu_actions = {}   # Befehl der Keymap (Kontext menu) -> Menuepunkt mit dessen Kuerzeln

        def action(menu, text, handler, command=None, role=None):
            item = QAction(text, self)
            if command is not None:
                self._menu_actions[command] = item
            if role is not None:
                item.setMenuRole(role)
            item.triggered.connect(lambda checked=False: handler())
            menu.addAction(item)
            return item

        role = QAction.MenuRole
        # macOS: "Ablage" wie im Finder, Windows: "Datei"
        file_menu = bar.addMenu(_('Ablage') if sys.platform == 'darwin' else _('Datei'))
        action(file_menu, _('Ordner öffnen …'), self.choose_folder, 'open_folder')
        action(file_menu, _('Ordner in neuem Tab öffnen …'), lambda: self.choose_folder(new_tab=True), 'open_folder_tab')
        action(file_menu, _('Neu einlesen'), lambda: self.folder and self.rescan(self.tab), 'rescan')
        file_menu.addSeparator()
        action(file_menu, _('Bilder umbenennen …'), self.rename_folder)
        file_menu.addSeparator()
        action(file_menu, _('Tab schließen'), lambda: self.close_tab(self.tabs.currentIndex()))
        file_menu.addSeparator()
        action(file_menu, _('Einstellungen …'), self.edit_settings, 'preferences', role.PreferencesRole)
        action(file_menu, _('Tastenkürzel anpassen …'), self.customize_shortcuts, 'customize_shortcuts')
        action(file_menu, _('Beenden'), self.close, 'quit', role.QuitRole)
        self._apply_menu_shortcuts()

        edit_menu = bar.addMenu(_('Bearbeiten'))
        # Kuerzel Cmd+Z/Cmd+Shift+Z kommen aus der Keymap (im Textfeld gilt dessen Rueckgaengig)
        self.undo_action = action(edit_menu, _('Rückgängig'), self.undo)
        self.redo_action = action(edit_menu, _('Wiederholen'), self.redo)
        edit_menu.addSeparator()
        action(edit_menu, _('Suchen und Ersetzen …'), self.find_replace)   # Kuerzel aus der Keymap
        self._update_undo_actions()

        template_menu = bar.addMenu(_('Template'))
        action(template_menu, _('Neues Template …'), lambda: self.edit_template(None))
        action(template_menu, _('Neues Template aus dem gewählten …'),
               lambda: self.editor.template and self.copy_template(self.editor.template))
        action(template_menu, _('Template aus Foto erzeugen …'), self.template_from_photo)
        action(template_menu, _('Template bearbeiten …'),
               lambda: self.editor.template and self.edit_template(self.editor.template))
        template_menu.addSeparator()
        action(template_menu, _('Template-Datei laden …'), self.open_template_file)
        action(template_menu, _('Template speichern unter …'), self.save_template_as)
        template_menu.addSeparator()
        action(template_menu, _('Template auf Auswahl anwenden'), self.apply_template)
        template_menu.addSeparator()
        action(template_menu, template_folder_label(), self.open_template_folder)

        roster_menu = bar.addMenu(_('Roster'))
        action(roster_menu, _('Roster bearbeiten …'), self.edit_roster)
        action(roster_menu, _('Roster neu laden'), lambda: self.load_roster(force=True))
        action(roster_menu, _('Roster-Datei hinzufügen …'), self.add_roster_file)

        help_menu = bar.addMenu(_('Hilfe'))
        action(help_menu, _('Anleitung (PDF)'), self.open_manual)
        action(help_menu, _('Tastenkürzel'), self.show_shortcuts)
        action(help_menu, _('Captioner-Website'), lambda: QDesktopServices.openUrl(QUrl(WEBSITE_LINK)))
        action(help_menu, _('Nach Updates suchen …'), lambda: self.check_updates(manual=True))
        action(help_menu, _('Über Captioner'), self.show_about, role=role.AboutRole)

    # --- Updates -----------------------------------------------------------------

    def _setup_update_check(self):
        self.update_checker = UpdateChecker(self)
        self.update_checker.found.connect(self._update_found)
        self.update_checker.up_to_date.connect(self._update_none)
        self.update_checker.failed.connect(self._update_failed)
        self._manual_update_check = False
        self.update_button = QPushButton()
        self.update_button.setFlat(True)
        self.update_button.setStyleSheet('color: #2f7de1; font-weight: bold;')
        self.update_button.hide()
        self.update_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(self.update_button.toolTip())))
        self.statusBar().addPermanentWidget(self.update_button)
        # Nur die gebuendelte App fragt von selbst, hoechstens einmal am Tag
        if (self.settings.check_updates and getattr(sys, 'frozen', False)
                and updates.due(self.settings.last_update_check)):
            QTimer.singleShot(3000, self.check_updates)

    def check_updates(self, manual=False):
        self._manual_update_check = manual
        self.update_checker.check()

    def _checked(self):
        self.settings.last_update_check = time.time()
        self.settings.save()

    def _update_found(self, latest, url):
        self._checked()
        self.update_button.setText(_('Update {version} verfügbar').format(version=latest))
        self.update_button.setToolTip(url)
        self.update_button.show()
        if self._manual_update_check:
            answer = QMessageBox.question(self, _('Update verfügbar'),
                                          _('Captioner {latest} ist verfügbar (installiert: {current}). '
                                            'Release-Seite öffnen?').format(latest=latest, current=version()))
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(url))

    def _update_none(self, current):
        self._checked()
        if self._manual_update_check:
            QMessageBox.information(self, _('Keine Updates'),
                                    _('Captioner {version} ist aktuell.').format(version=current))

    def _update_failed(self, detail):
        if self._manual_update_check:
            QMessageBox.information(self, _('Updates'), _('Konnte nicht prüfen, ob es eine neue Version gibt '
                                                         '(keine Verbindung zu GitHub oder Repository nicht '
                                                         'öffentlich).'))

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
        self.rating_filter.currentIndexChanged.connect(lambda: self.apply_filter())
        self.color_filter.currentIndexChanged.connect(lambda: self.apply_filter())
        self.tag_filter.currentIndexChanged.connect(lambda: self.apply_filter())
        self.uncaptioned_filter.toggled.connect(lambda: self.apply_filter())

        # Zweite Zeile: Suche, Kamera, Uhrzeit
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(_('Suchen: Dateiname, Titel, Beschreibung, Tags'))
        self.search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(lambda: self.apply_filter())
        self.search.textChanged.connect(self._search_timer.start)
        self.camera_filter = QComboBox()
        self.camera_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.camera_filter.currentIndexChanged.connect(lambda: self.apply_filter())
        self.time_filter = QCheckBox(_('Uhrzeit'))
        self.time_from = QTimeEdit(QTime(0, 0))
        self.time_to = QTimeEdit(QTime(23, 59))
        for edit in (self.time_from, self.time_to):
            edit.setDisplayFormat('HH:mm')
            edit.setEnabled(False)
            edit.timeChanged.connect(lambda: self.time_filter.isChecked() and self.apply_filter())
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
        self.tabs.bar.close_requested.connect(self.close_tabs)
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
        self.editor.save_requested.connect(self.save_caption)
        self.editor.apply_template_requested.connect(self.apply_template)
        self.editor.template_changed.connect(self._on_template_changed)
        self.editor.edit_template_requested.connect(self.edit_template)
        self.editor.copy_template_requested.connect(self.copy_template)
        self.editor.template_from_photo_requested.connect(self.template_from_photo)
        self.editor.open_template_folder_requested.connect(self.open_template_folder)
        self.editor.open_template_requested.connect(self.open_template_file)
        self.editor.save_template_as_requested.connect(self.save_template_as)
        self.editor.remove_template_requested.connect(self.remove_template)
        self.editor.reload_roster_requested.connect(lambda: self.load_roster(force=True))
        self.editor.add_roster_file_requested.connect(self.add_roster_file)
        self.editor.edit_roster_requested.connect(self.edit_roster)
        self.editor.navigate_requested.connect(self.step_selection)
        self.editor.snapshot_take_requested.connect(self.take_snapshot)
        self.editor.snapshot_paste_requested.connect(self.paste_snapshot)
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

        # Groesse der Vorschaubilder, fuer alle Tabs; gemerkt wird beim Loslassen
        self.thumbnail_slider = QSlider(Qt.Orientation.Horizontal)
        self.thumbnail_slider.setRange(MIN_TILE_W, MAX_TILE_W)
        self.thumbnail_slider.setValue(max(MIN_TILE_W, min(MAX_TILE_W, self.settings.thumbnail_size)))
        self.thumbnail_slider.setFixedWidth(160)
        self.thumbnail_slider.setToolTip(_('Größe der Vorschaubilder'))
        self.thumbnail_slider.valueChanged.connect(self.set_thumbnail_size)
        self.thumbnail_slider.sliderReleased.connect(self._remember_thumbnail_size)
        self.statusBar().addPermanentWidget(QLabel(_('Vorschau')))
        self.statusBar().addPermanentWidget(self.thumbnail_slider)
        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label)
        self.setAcceptDrops(True)
        self._install_shortcuts()
        self._update_count()

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
            'next_image': lambda: self.step_selection(1),
            'prev_image': lambda: self.step_selection(-1),
            'roster_settings': self.edit_settings,
            'trash': self.trash_selected,
            'reveal': self.reveal_current,
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
            'find_replace': self.find_replace,
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
        """QShortcuts nach der wirksamen Keymap; gemerkt, damit _rebind_shortcuts sie neu anlegen kann."""
        self._bindings = getattr(self, '_bindings', [])
        self._bindings.append((handlers, widget, context))
        self._create_shortcuts(handlers, widget, context)

    def _create_shortcuts(self, handlers, widget, context):
        self._shortcuts = getattr(self, '_shortcuts', [])
        for command, handler in handlers.items():
            for sequence in keymap.keys(command):
                shortcut = QShortcut(QKeySequence(sequence), widget)
                shortcut.setContext(self._editor_shortcut_context() if widget is self.editor else context)
                shortcut.activated.connect(handler)
                self._shortcuts.append(shortcut)

    def _editor_shortcut_context(self):
        """
        Panel-Kuerzel (Cmd+N speichern und weiter, ...): im Hauptfenster nur mit Fokus im Panel,
        dort belegt die Galerie dieselben Tasten. In der Grossansicht im ganzen Fenster, auch
        wenn das Bild den Fokus hat; deren eigene Kuerzel ueberschneiden sich nicht (Test).
        """
        if self._editor_in_viewer():
            return Qt.ShortcutContext.WindowShortcut
        return Qt.ShortcutContext.WidgetWithChildrenShortcut

    def _update_editor_shortcuts(self):
        context = self._editor_shortcut_context()
        for shortcut in self._shortcuts:
            if shortcut.parent() is self.editor:
                shortcut.setContext(context)

    def _apply_menu_shortcuts(self):
        for command, item in self._menu_actions.items():
            item.setShortcuts([QKeySequence(key) for key in keymap.keys(command)])

    def _rebind_shortcuts(self):
        """Nach dem Anpassen: alle Kuerzel neu, ohne Neustart (auch die der Grossansicht)."""
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._shortcuts = []
        for handlers, widget, context in self._bindings:
            self._create_shortcuts(handlers, widget, context)
        self._apply_menu_shortcuts()
        self.editor.update_shortcut_texts()

    def show_shortcuts(self):
        ShortcutsDialog(self).exec()

    def open_manual(self):
        """Die mitgelieferte Anleitung im PDF-Programm des Systems (Vorschau, Edge, ...)."""
        path = manual_path()
        if not path.exists() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.information(self, _('Anleitung'), _('Die Anleitung wurde nicht gefunden: {path}').format(path=path))

    def customize_shortcuts(self):
        dialog = ShortcutEditorDialog(self)
        if not dialog.exec():
            return
        self.settings.shortcuts = dialog.overrides()
        self.settings.save()
        keymap.apply(self.settings.shortcuts)
        self._rebind_shortcuts()

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
        # Doppelklick auf eine Kachel: Grossansicht wie mit der Leertaste (erster Klick macht sie aktuell)
        tab.view.doubleClicked.connect(lambda index: self.open_viewer())
        # Doppelklick in die leere Galerie ohne Ordner: wie Cmd+O
        tab.view.context_menu_requested.connect(self.show_gallery_menu)
        tab.view.background_double_clicked.connect(lambda t=tab: t.folder or self.choose_folder())
        tab.view.visible_changed.connect(lambda t=tab: self._request_thumbnails(t))
        tab.view.set_tile_width(self.settings.thumbnail_size)
        index = self.tabs.addTab(tab, tab_title(folder))
        self.tabs.setCurrentIndex(index)
        self._update_empty_text()
        self._update_count()
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
            self._update_count()
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
            self.apply_filter()

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
            self.apply_filter()

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
        self.apply_filter()
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

    def close_tabs(self, indices):
        """Mehrere Tabs schliessen (Kontextmenue am Reiter); ueber die Widgets, Indizes verschieben sich."""
        for tab in [self.tabs.widget(index) for index in indices]:
            self.close_tab(self.tabs.indexOf(tab))

    # --- Filter, Auswahl -------------------------------------------------------

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
        self.apply_filter()

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

    def apply_filter(self):
        self.filtered = [item for item in self.all_items if self._passes(item)]
        self.show_gallery()

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

    def show_gallery(self, focus_key=None):
        """Alle gefilterten Bilder zeigen und die Auswahl (selected_keys) in die Galerie uebernehmen."""
        self._update_empty_text()
        current = self.view.currentIndex().data(ItemRole) if self.view.currentIndex().isValid() else None
        self._syncing_selection = True
        if self.model.set_items(self.filtered) and not focus_key and current is not None:
            focus_key = current.key  # nach dem Neuaufbau beim Bild unter dem Cursor bleiben
        # zusammenhaengende Zeilen als ein Bereich: Alles auswaehlen bei tausenden Bildern
        selection, start = QItemSelection(), None
        for row, item in enumerate([*self.model.items, None]):
            chosen = item is not None and item.key in self.selected_keys
            if chosen and start is None:
                start = row
            elif not chosen and start is not None:
                selection.select(self.model.index(start), self.model.index(row - 1))
                start = None
        self.view.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if focus_key and focus_key in self.model.rows:
            index = self.model.index(self.model.rows[focus_key])
            self.view.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.view.scrollTo(index)
        self._syncing_selection = False
        self._request_thumbnails(self.tab)
        self._update_count()
        self._show_selection_in_editor()

    def _request_thumbnails(self, tab):
        """Kacheln fuer den sichtbaren Bereich, dazu je einen Bildschirm davor und danach."""
        if tab is not self.tab:
            return
        rows = tab.view.visible_rows()
        if rows is None:
            return
        first, last = rows
        margin = last - first + 1
        visible = tab.model.items[first:last + 1]
        around = tab.model.items[last + 1:last + 1 + margin] + tab.model.items[max(0, first - margin):first]
        self.loader.request(visible + around)  # sichtbare zuerst

    def set_thumbnail_size(self, width):
        """Kachelbreite in allen Tabs (Regler); gespeichert erst beim Loslassen."""
        self.settings.thumbnail_size = width
        for tab in self.all_tabs():
            tab.view.set_tile_width(width)
        if not self.thumbnail_slider.isSliderDown():
            self._remember_thumbnail_size()  # Tastatur/Klick neben den Griff

    def _remember_thumbnail_size(self):
        self.settings.save()

    def _update_count(self):
        total = len(self.filtered)
        text = ngettext('{count} Bild', '{count} Bilder', total).format(count=total)
        if self.selected_keys:
            text += ' · ' + _('{count} ausgewählt').format(count=len(self._selected_items()))
        self.count_label.setText(text)

    def _on_selection_changed(self, selected, deselected):
        if self._syncing_selection:
            return
        for index in selected.indexes():
            self.selected_keys.add(index.data(ItemRole).key)
        for index in deselected.indexes():
            self.selected_keys.discard(index.data(ItemRole).key)
        self._update_count()
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
        self.editor.show_items(items, raw_lookup=self.raw_captions.get,
                               carry_over_headline=self.last_headline)

    def select_all_filtered(self):
        self.selected_keys = {item.key for item in self.filtered}
        self.show_gallery()

    def deselect_all(self):
        self.selected_keys = set()
        self.show_gallery()

    def select_tagged(self):
        self.selected_keys = {item.key for item in self.filtered if item.meta.tagged}
        self.show_gallery()

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
        self.show_gallery(focus_key=item.key)
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
            self.apply_filter()

    def take_snapshot(self):
        """
        Beschriftung kopieren: was im Panel steht (das Bild unter dem Cursor), auch
        ungespeicherte Aenderungen. Die Beschreibung als Rohtext mit Codes.
        """
        items = self._focused_first(self._selected_items())
        if not items:
            return
        self.snapshot = self.editor.current_fields()
        self.editor.set_has_snapshot(True)
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

    def find_replace(self):
        """Suchen und Ersetzen in der Auswahl, ohne Auswahl in allen angezeigten Bildern."""
        # Gerechnet wird mit dem Stand der Bilder: erst fertig schreiben
        if self.writer.pending_count() and not self._wait_for_writer(_('Suchen und Ersetzen')):
            return
        selected = self._selected_items()
        items = selected or list(self.filtered)
        if not items:
            return
        scope = (ngettext('{count} ausgewähltes Bild', '{count} ausgewählte Bilder', len(items)) if selected
                 else ngettext('{count} angezeigtes Bild', 'alle {count} angezeigten Bilder', len(items)))
        template = self.editor.template

        def planner(find, replacement, fields, options):
            return replace.plan(items, find, replacement, fields, self.roster, self.settings.code_delimiter,
                                options, raw_lookup=self.raw_captions.get, template=template, places=self.places)

        dialog = ReplaceDialog(scope.format(count=len(items)), planner, self)
        if not dialog.exec():
            return
        changes = dialog.chosen()
        with self._undoable(N_('Ersetzen')):
            for change in changes:
                self._enqueue(change.item, change.meta)
                if change.raw is not None:
                    self.raw_captions.set(change.item, change.raw)
        for tab in self.all_tabs():
            tab.model.refresh([c.item.key for c in changes if c.item.key in tab.by_key])
        self._update_status()
        self._show_selection_in_editor()
        if self.viewer is not None and self.viewer.isVisible() and self.viewer._item is not None:
            self.viewer.show_item(self.viewer._item, self.viewer._image)
        self.statusBar().showMessage(ngettext('In {count} Bild ersetzt', 'In {count} Bildern ersetzt',
                                              len(changes)).format(count=len(changes)), 5000)

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
                        city=fields['city'], sublocation=fields['sublocation'], **template.field_values(item.meta))
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
            # in der Grossansicht mit Fokus auf dem Bild bleibt er dort (Cmd+N ohne Panel-Fokus)
            on_image = self.viewer is not None and self.viewer.isVisible() and self.viewer.zoom.hasFocus()
            self.select_only(self.filtered[target])
            if not on_image:
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
        # "Inhalte überschreiben": nur noch, was im Template steht; Beschreibung leer
        overwrite = self.editor.overwrite_box.isChecked()
        if overwrite:
            # sonst schluege das Panel den zuletzt gespeicherten Titel wieder vor
            self.last_headline = template.headline
        for item in items:
            if overwrite:
                headline, caption = template.headline, ''
                self.raw_captions.set(item, None)
            else:
                # Ohne Heim/Gast gibt das Template keinen Titel vor: der des Bildes bleibt
                headline = template.headline or item.meta.headline
                caption = template.compose_caption(item.meta.caption, item.taken_at, headline=headline,
                                                   **template.field_values(item.meta)) \
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

    # --- Kontextmenue der Galerie ----------------------------------------------------

    def show_gallery_menu(self, position):
        menu = self.gallery_menu(self)
        menu.exec(position)
        menu.deleteLater()

    def gallery_menu(self, parent):
        """Rechtsklick auf Kacheln: wirkt auf die Auswahl, wie die Kuerzel daneben."""
        items = self._selected_items()
        menu = QMenu(parent)
        if not items:
            return menu

        def entry(target, text, handler, command=None, checked=None, icon=None):
            keys = keymap.keys(command) if command else ()
            if keys:
                text += '\t' + QKeySequence(keys[0]).toString(QKeySequence.SequenceFormat.NativeText)
            item = target.addAction(text)
            item.triggered.connect(lambda checked=False: handler())
            if checked is not None:
                item.setCheckable(True)
                item.setChecked(checked)
            if icon is not None:
                item.setIcon(icon)
            return item

        def same(values):
            values = set(values)
            return values.pop() if len(values) == 1 else None

        rating = same(item.meta.rating for item in items)
        stars = menu.addMenu(_('Bewertung'))
        entry(stars, _('Keine Sterne'), lambda: self.set_rating(0), 'rating_0', rating == 0)
        for n in range(1, 6):
            entry(stars, '★' * n, lambda n=n: self.set_rating(n), f'rating_{n}', rating == n)

        color = same(self.color_class_of(item) for item in items)
        colors = menu.addMenu(_('Farbklasse'))
        entry(colors, _('Keine Farbe'), lambda: self.set_color_class(0), 'color_0', color == 0)
        for n in range(1, 9):
            label = self.settings.labels[n - 1] if n <= len(self.settings.labels) else ''
            text = _('Farbklasse {number} ({label})').format(number=n, label=label) if label \
                else _('Farbklasse {number}').format(number=n)
            swatch = QPixmap(12, 12)
            swatch.fill(QColor(CLASS_COLORS[n]))
            entry(colors, text, lambda n=n: self.set_color_class(n), f'color_{n}', color == n, QIcon(swatch))

        entry(menu, _('Getaggt'), lambda: self.set_tag(None), 'tag_toggle', all(item.meta.tagged for item in items))
        menu.addSeparator()
        entry(menu, _('Großansicht'), self.open_viewer, 'preview')
        entry(menu, _('Beschriftung kopieren'), self.take_snapshot, 'snapshot_take')
        entry(menu, _('Beschriftung einfügen'), self.paste_snapshot, 'snapshot_paste').setEnabled(
            bool(getattr(self, 'snapshot', None)))
        targets = [tab for tab in self.all_tabs() if tab is not self.tab and tab.folder]
        if targets:
            copy_menu = menu.addMenu(_('In Tab kopieren'))
            for tab in targets:
                entry(copy_menu, self.tabs.tabText(self.tabs.indexOf(tab)), lambda t=tab: self.copy_selected_to(t))
        menu.addSeparator()
        entry(menu, filemanager.reveal_label(), self.reveal_current, 'reveal')
        entry(menu, ngettext('Pfad kopieren', 'Pfade kopieren', len(items)), self.copy_paths)
        menu.addSeparator()
        entry(menu, _('In den Papierkorb legen …'), self.trash_selected, 'trash')   # Anzahl nennt die Rueckfrage
        return menu

    def _current_item(self):
        items = self._focused_first(self._selected_items())
        return items[0] if items else None

    def reveal_current(self):
        item = self._current_item()
        if item is not None and not filemanager.reveal(item.primary):
            QMessageBox.information(self, filemanager.reveal_label(), str(item.primary))

    def copy_paths(self):
        paths = [str(path) for item in self._focused_first(self._selected_items()) for path in item.files]
        if paths:
            QApplication.clipboard().setText('\n'.join(paths))
            self.statusBar().showMessage(ngettext('{count} Pfad kopiert', '{count} Pfade kopiert',
                                                  len(paths)).format(count=len(paths)), 5000)

    def copy_selected_to(self, target):
        """Wie Ziehen auf den Reiter: erst alles schreiben, dann mit Sidecar kopieren."""
        if self.build_drag_mime() is not None:
            self.copy_dragged_to(target)

    def trash_selected(self):
        """
        Ausgewaehlte Bilder mit allen Dateien (RAW, JPG, Sidecar) in den Papierkorb, nach
        Rueckfrage. Wiederherstellen geht im Finder/Explorer, nicht mit Rueckgaengig.
        """
        items = self._selected_items()
        tab = self.tab
        if not items:
            return
        if self.copy_worker and self.copy_worker.isRunning():
            QMessageBox.information(self, _('Papierkorb'), _('Es wird noch kopiert. Bitte warten, bis das fertig ist.'))
            return
        question = (_('„{name}“ in den Papierkorb legen?').format(name=items[0].name) if len(items) == 1 else
                    ngettext('{count} Bild in den Papierkorb legen?', '{count} Bilder in den Papierkorb legen?',
                             len(items)).format(count=len(items)))
        answer = QMessageBox.question(
            self, _('Papierkorb'),
            question + '\n\n' + _('Dazu gehören alle Dateien des Bildes (RAW, JPG, XMP-Sidecar). '
                                   'Aus dem Papierkorb lassen sie sich wiederherstellen.'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        # Nichts mehr in Dateien schreiben, die gleich im Papierkorb liegen
        if self.writer.pending_count() and not self._wait_for_writer(_('Papierkorb')):
            return
        trashed, failed = [], []
        for item in items:
            paths = item.files + ([item.sidecar] if item.sidecar and item.sidecar.exists() else [])
            missing = [path for path in paths if not filemanager.move_to_trash(path)]
            (failed if missing else trashed).append(item)
            failed_names = [path.name for path in missing]
            if failed_names:
                logger.warning('Nicht in den Papierkorb: %s', ', '.join(failed_names))
        self.undo_stack.forget(trashed)
        self._update_undo_actions()
        if self.viewer is not None and self.viewer.isVisible() and self.viewer.key in {i.key for i in trashed}:
            self.viewer.close()
        if failed:
            QMessageBox.warning(self, _('Papierkorb'), _('Nicht alle Dateien ließen sich in den Papierkorb legen:')
                                + '\n\n' + '\n'.join(item.name for item in failed[:20]))
            self.rescan(tab, wait_for_writer=False)
            return
        gone = {item.key for item in trashed}
        tab.all_items = [item for item in tab.all_items if item.key not in gone]
        tab.by_key = {item.key: item for item in tab.all_items}
        tab.selected_keys.difference_update(gone)
        self._fill_camera_filter()
        self.apply_filter()
        self._update_count()
        self.statusBar().showMessage(ngettext('{count} Bild in den Papierkorb gelegt',
                                              '{count} Bilder in den Papierkorb gelegt',
                                              len(trashed)).format(count=len(trashed)), 5000)

    def rename_folder(self, answer=None):
        """
        Alle Bilder des Ordners nach Schema JJJJMMTT_HEIM_GAST_NNN umbenennen, nummeriert nach
        Aufnahmezeit (Reihenfolge des Scans). answer=(Datum, Heim, Gast) ersetzt den Dialog (Tests).
        """
        tab = self.tab
        title = _('Bilder umbenennen')
        if not tab.folder or not tab.all_items:
            return
        if tab.scanning():
            QMessageBox.information(self, title, _('Der Ordner wird noch eingelesen. Bitte warten, bis das fertig ist.'))
            return
        if self.copy_worker and self.copy_worker.isRunning():
            QMessageBox.information(self, title, _('Es wird noch kopiert. Bitte warten, bis das fertig ist.'))
            return
        items = list(tab.all_items)
        if answer is None:
            dialog = RenameDialog(len(items), self.settings.rename_home, self.settings.rename_away, self)
            if not dialog.exec():
                return
            answer = dialog.values()
        date, home, away = answer
        self.settings.rename_home, self.settings.rename_away = home, away
        self.settings.save()
        # Erst fertig schreiben: der Writer kennt nur die alten Pfade
        if self.writer.pending_count() and not self._wait_for_writer(title):
            return
        moves = rename.plan(items, date, home, away)
        taken = rename.conflicts(moves)
        if taken:
            QMessageBox.warning(self, title, _('Diese Namen gibt es im Ordner schon, nichts wurde umbenannt:')
                                + '\n\n' + '\n'.join(path.name for path in taken[:20]))
            return
        moved = {move.source: move.target for move in moves}
        try:
            rename.apply(moves)
        except rename.RenameError as error:
            QMessageBox.warning(self, title, _('Umbenennen fehlgeschlagen, nichts wurde umbenannt:')
                                + f'\n\n{error}')
            return
        self.raw_captions.move({item.primary: moved[item.primary] for item in items if item.primary in moved})
        # Rueckgaengig kennt die Bilder unter altem Namen; die Items ersetzt das Neueinlesen
        self.undo_stack.forget(items)
        self._update_undo_actions()
        if self.viewer is not None and self.viewer.isVisible():
            self.viewer.close()
        for other in self.all_tabs():
            if other.folder and transfer._same_dir(other.folder, tab.folder):
                self.rescan(other, wait_for_writer=False)
        self.statusBar().showMessage(ngettext('{count} Bild umbenannt', '{count} Bilder umbenannt',
                                              len(items)).format(count=len(items)), 5000)

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
        return getattr(self, 'viewer', None) is not None and self.viewer.caption_slot.widget() is self.editor

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
        self._update_editor_shortcuts()

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
        # Eingepasst reicht die Aufloesung des Bildschirms; die volle kommt fuer 100 % nach
        screen = self.viewer.screen() or QApplication.primaryScreen()
        size = screen.size() * screen.devicePixelRatio()
        self.loader.display_edge = max(size.width(), size.height())
        self.loader.request_full(item, self._viewer_neighbours(item))
        self.loader.request_details(item)

    def _viewer_neighbours(self, item):
        """Vorladen beim Blaettern: die naechsten zwei, das vorige."""
        if item not in self.filtered:
            return []
        position = self.filtered.index(item)
        return [self.filtered[p] for p in (position + 1, position + 2, position - 1) if 0 <= p < len(self.filtered)]

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
            return False
        new = dialog.template()
        if not (new.name or new.headline):
            QMessageBox.warning(self, _('Template unvollständig'), _('Bitte einen Namen eingeben.'))
            return False
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
            return False
        self.refresh_templates(new.path)
        return True

    def copy_template(self, template):
        """
        Neues Template mit allen Werten des gewaehlten: als Kopie speichern, dorthin wechseln
        und zum Bearbeiten oeffnen. Abbrechen nimmt die Kopie wieder weg, das alte bleibt gewaehlt.
        """
        copy = dataclasses.replace(template, path='',
                                   name=_('{name} (Kopie)').format(name=template.display_name()))
        try:
            self.template_store.save(copy)
        except OSError as e:
            QMessageBox.warning(self, _('Template nicht gespeichert'), str(e))
            return
        self.refresh_templates(copy.path)
        if not self.edit_template(copy):
            self.template_store.delete(copy)
            self.refresh_templates(template.path)

    def template_from_photo(self):
        """
        Neues Template aus der Beschriftung des Bildes unter dem Cursor (Titel, Ort, Rechte,
        Zusatz-Tags, Anhang), zum Pruefen gleich im Dialog. Gespeichert wird erst mit OK.
        """
        items = self._focused_first(self._selected_items())
        title = _('Template aus Foto')
        if not items:
            QMessageBox.information(self, title, _('Bitte zuerst ein beschriftetes Foto auswählen.'))
            return
        item = items[0]
        if not item.meta_loaded:
            QMessageBox.information(self, title, _('Die Metadaten von {name} werden noch eingelesen.').format(name=item.name))
            return
        meta = item.meta
        if not (meta.headline.strip() or meta.caption.strip()):
            QMessageBox.information(self, title, _('{name} hat weder Titel noch Beschreibung.').format(name=item.name))
            return
        persons = codes.persons_in(meta.caption, self.roster) + codes.person_names_in(meta.caption)
        template = template_files.from_metadata(
            meta, item.taken_at, name=meta.headline or _('Aus {name}').format(name=item.name), persons=persons)
        if self.edit_template(template):
            self.statusBar().showMessage(_('Template „{name}“ aus {photo} erzeugt').format(
                name=template.display_name(), photo=item.name), 5000)

    def open_template_folder(self):
        """Konfigurationsordner der Templates im Finder/Explorer (dort liegen alle ausser geladenen Dateien)."""
        folder = self.template_store.directory
        folder.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.information(self, _('Template-Ordner'), str(folder))

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
        dialog = RosterEditorDialog(self.settings.roster_sources, self.roster_loader.cached_text, self,
                                    font_size=self.settings.roster_font_size)
        dialog.saved.connect(lambda path: self.load_roster(force=True))
        dialog.exec()
        if dialog.font_size.value() != self.settings.roster_font_size:
            self.settings.roster_font_size = dialog.font_size.value()
            self.settings.save()

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
        summary = '<b>%s</b> %s, %s' % (
            _('Roster:'), ngettext('{count} Code', '{count} Codes', len(roster.entries)).format(count=len(roster.entries)),
            ngettext('{count} Team', '{count} Teams', len(roster.teams)).format(count=len(roster.teams)))
        # Quellen mit Stand im Tooltip; was nicht stimmt, bleibt sichtbar
        details, problems = [], []
        for status in roster.status:
            stamp = time.strftime('%d.%m. %H:%M', time.localtime(status.fetched_at)) if status.fetched_at else ''
            name = html.escape(status.source.rsplit('/', 1)[-1])
            detail = f' – {html.escape(status.message)}' if status.message else ''
            origin = html.escape(_(status.origin)) if status.origin else ''
            line = f'{name}: {origin} {stamp}{detail}'
            details.append(line)
            if not status.ok or status.origin == 'letzte gute Version':
                problems.append(f'<span style="color:#d64541">{line}</span>')
        if roster.conflicts:
            text = ngettext('{count} widersprüchlicher Code: {codes}', '{count} widersprüchliche Codes: {codes}',
                            len(roster.conflicts)).format(count=len(roster.conflicts),
                                                          codes=', '.join(c[0] for c in roster.conflicts[:10]))
            problems.append(f'<span style="color:#d64541">{html.escape(text)}</span>')
        if not roster.is_usable:
            problems.append('<span style="color:#d64541">%s</span>'
                            % html.escape(_('Kein Roster verfügbar – Codes können nicht aufgelöst werden.')))
        self.editor.set_roster_status(summary, details, problems)

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
        self.apply_filter()

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


def command_line_path(arg):
    """
    Explorer: "Mit Captioner oeffnen" auf einer Karte uebergibt "E:\\", und Windows liest
    den Backslash vor dem Anfuehrungszeichen als Escape: an kommt E:". Hier repariert.
    """
    if sys.platform == 'win32':
        arg = arg.rstrip('"')
        if len(arg) == 2 and arg[1] == ':':
            arg += '\\'
    return arg


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
    folders = [arg for arg in map(command_line_path, argv[1:]) if arg]  # make run ohne FOLDER uebergibt ""
    # Windows: laeuft schon eine App, bekommt sie die Ordner (Explorer startet je Ordner neu)
    if sys.platform == 'win32' and instance.forward(folders):
        return 0
    from .resources import app_icon
    app.setWindowIcon(app_icon())
    window = MainWindow(settings, folders)
    open_requests.set_handler(window.open_paths)
    if sys.platform == 'win32':
        app._instance_server = instance.InstanceServer(
            lambda paths: open_requests.add(paths) if paths else window.open_paths([]), parent=app)
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()
