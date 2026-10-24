"""
App settings, as TOML in the operating system's configuration directory.

There is no image database of its own (ADR 0001, item 4). This only holds what the
app itself needs: roster sources, label names, templates.
"""
import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w
from platformdirs import user_cache_dir, user_config_dir

APP_NAME = 'captioner'

# Lightroom compares xmp:Label as text against the active label set.
# An English Lightroom (and the existing sidecars) use "Red", a German one
# expects "Rot". Keys 6-9 as in Lightroom: red, yellow, green, blue.
DEFAULT_LABELS = ['Red', 'Yellow', 'Green', 'Blue', 'Purple']


def _home_override():
    """CAPTIONER_HOME redirects configuration and cache, e.g. for tests."""
    home = os.environ.get('CAPTIONER_HOME')
    return Path(home) if home else None


def config_dir() -> Path:
    home = _home_override()
    path = home / 'config' if home else Path(user_config_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    home = _home_override()
    path = home / 'cache' if home else Path(user_cache_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def templates_dir() -> Path:
    path = config_dir() / 'templates'
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    roster_sources: list = field(default_factory=lambda: [
        'https://github.com/katzefudder/del2_roster/blob/main/roster_del2.txt',
    ])
    roster_cache_ttl_minutes: int = 60
    code_delimiter: str = '#'
    recursive: bool = False
    labels: list = field(default_factory=lambda: list(DEFAULT_LABELS))
    # Also put the .xmp URLs into the drag (ADR 0001, item 7). Can be turned off
    # in case a Lightroom version doesn't accept them in the drop.
    drag_include_sidecars: bool = True
    viewer_info_panel: bool = True   # EXIF/IPTC on the right in the preview
    viewer_caption_panel: bool = False  # caption panel in the preview
    language: str = ''           # '' = system language, otherwise 'de'/'en'; see i18n.LANGUAGES
    spellcheck: str = 'auto'     # caption: 'auto' (macOS chooses), 'de', 'en', 'off'
    check_updates: bool = True   # ask GitHub for a new release once a day
    last_update_check: float = 0.0
    exiftool_path: str = ''
    last_folder: str = ''
    # Tabs open on quit (folder paths, in order) and the active one; reopened on start,
    # missing ones (card not inserted) are skipped
    open_tabs: list = field(default_factory=list)
    active_tab: str = ''
    last_template: str = ''      # path of the template chosen last
    # template files on the computer that live outside the configuration directory
    template_files: list = field(default_factory=list)
    # chosen places (city, location, coordinates), newest first; see geo.PlaceBook
    places: list = field(default_factory=list)
    thumbnail_size: int = 220    # tile width in the gallery (slider), see gallery.tile_size
    roster_font_size: int = 0    # font size in the roster editor (points), 0 = system default
    # custom shortcuts, only deviations from the defaults: {command: [keys, ...]}, see keymap.apply
    shortcuts: dict = field(default_factory=dict)
    # name entered last in the "Rename images" dialog (without number), see rename.default_prefix
    rename_prefix: str = ''

    @classmethod
    def path(cls) -> Path:
        return config_dir() / 'settings.toml'

    @classmethod
    def load(cls, path: Path = None) -> 'Settings':
        path = path or cls.path()
        if not path.exists():
            return cls()
        with open(path, 'rb') as handle:
            data = tomllib.load(handle)
        known = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: Path = None):
        path = path or self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as handle:
            tomli_w.dump(asdict(self), handle)
