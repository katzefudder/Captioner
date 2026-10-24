"""
Places for city/location (IPTC City, Sub-location) and GPS, without Qt.

* Place: city, location/arena, coordinates.
* PlaceBook: places chosen once (Settings.places). The only source of coordinates:
  when saving they are looked up via (city, location), offline too.
* GPS is only written into images that don't have any yet, or whose GPS comes from a
  place in the PlaceBook (i.e. was set by Captioner). Camera GPS always stays untouched.
* Nominatim (search, reverse search) and OSM tiles: only URLs and parsing here; the
  networking is in ui/mapview.py. Usage policies:
  operations.osmfoundation.org/policies/nominatim and .../tiles
  (own User-Agent, at most 1 request/s, no search while typing, cache tiles).
"""
import dataclasses
import math
from dataclasses import dataclass, field
from urllib.parse import urlencode

from . import i18n
from .i18n import N_

USER_AGENT = 'Captioner (+https://github.com/katzefudder/Captioner)'
TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org'
ATTRIBUTION = N_('© OpenStreetMap-Mitwirkende')  # translate with _() when displayed
TILE_SIZE = 256
MIN_ZOOM, MAX_ZOOM = 2, 19
MAX_PLACES = 200
# coordinates count as equal if they match to ~1 m
COORD_TOLERANCE = 1e-5

# Nominatim address fields that work as a city, in this order
CITY_KEYS = ('city', 'town', 'village', 'municipality', 'suburb', 'county')
# results whose name is a place/arena (otherwise "location" stays empty)
VENUE_CLASSES = ('leisure', 'amenity', 'building', 'tourism', 'historic', 'sport')


@dataclass
class Place:
    city: str = ''
    sublocation: str = ''
    latitude: float = None
    longitude: float = None
    label: str = ''  # shown in search results, not saved
    # from the address search, for state/country in the template; not in the PlaceBook
    state: str = field(default='', compare=False)
    country: str = field(default='', compare=False)

    @property
    def has_coordinates(self):
        return self.latitude is not None and self.longitude is not None

    def key(self):
        return (self.city.strip().casefold(), self.sublocation.strip().casefold())

    def display(self):
        return ' – '.join(part for part in (self.city, self.sublocation) if part)

    def to_dict(self):
        data = {'city': self.city, 'sublocation': self.sublocation}
        if self.has_coordinates:
            data.update(latitude=self.latitude, longitude=self.longitude)
        return data

    @classmethod
    def from_dict(cls, data):
        lat, lon = data.get('latitude'), data.get('longitude')
        valid = valid_coordinates(lat, lon)
        return cls(city=str(data.get('city') or ''), sublocation=str(data.get('sublocation') or ''),
                   latitude=float(lat) if valid else None, longitude=float(lon) if valid else None)


def valid_coordinates(lat, lon):
    return (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and not isinstance(lat, bool) and not isinstance(lon, bool)
            and -90 <= lat <= 90 and -180 <= lon <= 180)


class PlaceBook:
    """Places chosen last, newest first; reads and writes a list of dicts."""

    def __init__(self, entries=()):
        self.places = [Place.from_dict(e) for e in entries if isinstance(e, dict)]

    def to_list(self):
        return [p.to_dict() for p in self.places]

    def lookup(self, city, sublocation):
        key = Place(city or '', sublocation or '').key()
        if not any(key):
            return None
        return next((p for p in self.places if p.key() == key), None)

    def remember(self, place):
        if not (place.city.strip() or place.sublocation.strip()):
            return
        stored = Place(place.city.strip(), place.sublocation.strip(), place.latitude, place.longitude)
        existing = self.lookup(stored.city, stored.sublocation)
        if existing and not stored.has_coordinates:
            stored.latitude, stored.longitude = existing.latitude, existing.longitude
        self.places = [p for p in self.places if p.key() != stored.key()]
        self.places.insert(0, stored)
        del self.places[MAX_PLACES:]

    def is_ours(self, lat, lon):
        """Do the coordinates come from a remembered place (i.e. from Captioner)?"""
        return any(p.has_coordinates and abs(p.latitude - lat) < COORD_TOLERANCE
                   and abs(p.longitude - lon) < COORD_TOLERANCE for p in self.places)


def apply_gps(meta, book):
    """
    Metadata with the coordinates of the place (city, location) from the PlaceBook.
    Existing GPS is only replaced if it comes from a remembered place itself.
    """
    place = book.lookup(meta.city, meta.sublocation)
    if place is None or not place.has_coordinates:
        return meta
    if meta.latitude is not None and meta.longitude is not None:
        same = (abs(meta.latitude - place.latitude) < COORD_TOLERANCE
                and abs(meta.longitude - place.longitude) < COORD_TOLERANCE)
        if same or not book.is_ours(meta.latitude, meta.longitude):
            return meta
    return dataclasses.replace(meta, latitude=place.latitude, longitude=place.longitude, gps_changed=True)


# --- Nominatim ------------------------------------------------------------------

def search_url(query, limit=8):
    params = {'q': query, 'format': 'jsonv2', 'addressdetails': 1, 'limit': limit, 'accept-language': i18n.language()}
    return f'{NOMINATIM_URL}/search?{urlencode(params)}'


def reverse_url(lat, lon, zoom=18):
    params = {'lat': f'{lat:.6f}', 'lon': f'{lon:.6f}', 'format': 'jsonv2', 'addressdetails': 1,
              'zoom': zoom, 'accept-language': i18n.language()}
    return f'{NOMINATIM_URL}/reverse?{urlencode(params)}'


def place_from_result(result):
    """A Nominatim result (jsonv2) as a Place, or None."""
    if not isinstance(result, dict) or 'lat' not in result or 'lon' not in result:
        return None
    try:
        lat, lon = float(result['lat']), float(result['lon'])
    except (TypeError, ValueError):
        return None
    address = result.get('address') or {}
    city = next((address[k] for k in CITY_KEYS if address.get(k)), '')
    name = (result.get('name') or '').strip()
    category = result.get('category') or result.get('class') or ''
    sublocation = name if name and category in VENUE_CLASSES and name != city else ''
    return Place(city=city, sublocation=sublocation, latitude=lat, longitude=lon,
                 label=result.get('display_name') or name or city,
                 state=address.get('state', ''), country=address.get('country', ''))


def places_from_search(results):
    if not isinstance(results, list):
        return []
    return [p for p in (place_from_result(r) for r in results) if p]


# --- Tiles (Web Mercator) -------------------------------------------------------

def world_size(zoom):
    return TILE_SIZE * (2 ** zoom)


def to_pixels(lat, lon, zoom):
    """Latitude/longitude -> world pixels (x, y) at this zoom level."""
    lat = max(-85.05112878, min(85.05112878, lat))
    size = world_size(zoom)
    x = (lon + 180.0) / 360.0 * size
    sin = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + sin) / (1 - sin)) / (4 * math.pi)) * size
    return x, y


def to_coordinates(x, y, zoom):
    size = world_size(zoom)
    lon = x / size * 360.0 - 180.0
    n = math.pi - 2 * math.pi * y / size
    lat = math.degrees(math.atan(math.sinh(n)))
    return lat, lon


def tile_url(z, x, y):
    return TILE_URL.format(z=z, x=x, y=y)
