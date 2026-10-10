"""
Orte fuer Stadt/Ort (IPTC City, Sub-location) und GPS, ohne Qt.

* Place: Stadt, Ort/Halle, Koordinaten.
* PlaceBook: einmal gewaehlte Orte (Settings.places). Einzige Quelle fuer
  Koordinaten: Beim Speichern werden sie ueber (Stadt, Ort) nachgeschlagen,
  auch offline.
* GPS wird nur in Bilder geschrieben, die noch keins haben, oder deren GPS
  von einem Ort aus dem PlaceBook stammt (also von Captioner gesetzt wurde).
  Kamera-GPS bleibt immer unangetastet.
* Nominatim (Suche, Rueckwaertssuche) und OSM-Kacheln: hier nur URLs und
  Auswertung; das Netz macht ui/mapview.py. Nutzungsregeln:
  operations.osmfoundation.org/policies/nominatim und .../tiles
  (eigener User-Agent, hoechstens 1 Anfrage/s, keine Suche beim Tippen, Kacheln cachen).
"""
import dataclasses
import math
from dataclasses import dataclass
from urllib.parse import urlencode

USER_AGENT = 'Captioner (+https://github.com/katzefudder/Captioner)'
TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org'
ATTRIBUTION = '© OpenStreetMap-Mitwirkende'
TILE_SIZE = 256
MIN_ZOOM, MAX_ZOOM = 2, 19
MAX_PLACES = 200
# Koordinaten gelten als gleich, wenn sie auf ~1 m uebereinstimmen
COORD_TOLERANCE = 1e-5

# Nominatim-Adressfelder, die als Stadt taugen, in dieser Reihenfolge
CITY_KEYS = ('city', 'town', 'village', 'municipality', 'suburb', 'county')
# Treffer, deren Name ein Ort/eine Halle ist (sonst bleibt "Ort" leer)
VENUE_CLASSES = ('leisure', 'amenity', 'building', 'tourism', 'historic', 'sport')


@dataclass
class Place:
    city: str = ''
    sublocation: str = ''
    latitude: float = None
    longitude: float = None
    label: str = ''  # Anzeige in Suchergebnissen, wird nicht gespeichert

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
    """Zuletzt gewaehlte Orte, neueste zuerst; liest und schreibt eine Liste von Dicts."""

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
        """Stammen die Koordinaten von einem gemerkten Ort (also von Captioner)?"""
        return any(p.has_coordinates and abs(p.latitude - lat) < COORD_TOLERANCE
                   and abs(p.longitude - lon) < COORD_TOLERANCE for p in self.places)


def apply_gps(meta, book):
    """
    Metadaten mit den Koordinaten des Ortes (Stadt, Ort) aus dem PlaceBook.
    Vorhandenes GPS wird nur ersetzt, wenn es selbst von einem gemerkten Ort stammt.
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
    params = {'q': query, 'format': 'jsonv2', 'addressdetails': 1, 'limit': limit, 'accept-language': 'de'}
    return f'{NOMINATIM_URL}/search?{urlencode(params)}'


def reverse_url(lat, lon, zoom=18):
    params = {'lat': f'{lat:.6f}', 'lon': f'{lon:.6f}', 'format': 'jsonv2', 'addressdetails': 1,
              'zoom': zoom, 'accept-language': 'de'}
    return f'{NOMINATIM_URL}/reverse?{urlencode(params)}'


def place_from_result(result):
    """Ein Nominatim-Ergebnis (jsonv2) als Place, oder None."""
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
                 label=result.get('display_name') or name or city)


def places_from_search(results):
    if not isinstance(results, list):
        return []
    return [p for p in (place_from_result(r) for r in results) if p]


# --- Kacheln (Web-Mercator) -----------------------------------------------------

def world_size(zoom):
    return TILE_SIZE * (2 ** zoom)


def to_pixels(lat, lon, zoom):
    """Breite/Laenge -> Weltpixel (x, y) bei dieser Zoomstufe."""
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
