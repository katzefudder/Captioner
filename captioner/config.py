"""
Einstellungen der App, als TOML im Konfigurationsverzeichnis des Betriebssystems.

Es gibt keine eigene Bilddatenbank (ADR 0001, Punkt 4). Hier liegt nur, was die
App selbst braucht: Roster-Quellen, Seitengroesse, Label-Namen, Templates.
"""
import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w
from platformdirs import user_cache_dir, user_config_dir

APP_NAME = 'captioner'

# xmp:Label wird von Lightroom als Text gegen das aktive Label-Set verglichen.
# Ein englisches Lightroom (und die vorhandenen Sidecars) nutzen "Red", ein deutsches
# erwartet "Rot". Tasten 6-9 wie in Lightroom: Rot, Gelb, Gruen, Blau.
DEFAULT_LABELS = ['Red', 'Yellow', 'Green', 'Blue', 'Purple']


def _home_override():
    """CAPTIONER_HOME lenkt Konfiguration und Cache um, z. B. fuer Tests."""
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
    page_size: int = 100
    recursive: bool = False
    labels: list = field(default_factory=lambda: list(DEFAULT_LABELS))
    # .xmp-URLs zusaetzlich in den Drag legen (ADR 0001, Punkt 7). Abschaltbar,
    # falls eine Lightroom-Version sie im Drop nicht akzeptiert.
    drag_include_sidecars: bool = True
    viewer_info_panel: bool = True   # EXIF/IPTC rechts in der Grossansicht
    viewer_caption_panel: bool = False  # Beschriftungs-Panel in der Grossansicht
    exiftool_path: str = ''
    last_folder: str = ''
    last_template: str = ''      # Pfad des zuletzt gewaehlten Templates
    # Template-Dateien vom Rechner, die ausserhalb des Konfigurationsverzeichnisses liegen
    template_files: list = field(default_factory=list)
    # Gewaehlte Orte (Stadt, Ort, Koordinaten), neueste zuerst; siehe geo.PlaceBook
    places: list = field(default_factory=list)

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
