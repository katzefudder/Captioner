"""Places, place book, GPS rule, Nominatim parsing, tile math (without network)."""
from urllib.parse import parse_qs, urlparse

import pytest

from captioner import geo
from captioner.scanner import Metadata

# shortened real responses from nominatim.openstreetmap.org (jsonv2, addressdetails=1)
STADIUM = {
    'lat': '50.3725500', 'lon': '8.7384500', 'category': 'leisure', 'type': 'stadium',
    'name': 'Colonel-Knight-Stadion',
    'display_name': 'Colonel-Knight-Stadion, Nördlicher Park, Bad Nauheim, Wetteraukreis, Hessen, 61231, Deutschland',
    'address': {'leisure': 'Colonel-Knight-Stadion', 'town': 'Bad Nauheim', 'county': 'Wetteraukreis',
                'postcode': '61231', 'country': 'Deutschland'},
}
POSTCODE = {
    'lat': '50.3667', 'lon': '8.7500', 'category': 'place', 'type': 'postcode', 'name': '61231',
    'display_name': '61231, Bad Nauheim, Wetteraukreis, Hessen, Deutschland',
    'address': {'postcode': '61231', 'town': 'Bad Nauheim', 'county': 'Wetteraukreis'},
}
STREET = {
    'lat': '49.0', 'lon': '9.1', 'category': 'highway', 'type': 'residential', 'name': 'Hauptstraße',
    'display_name': 'Hauptstraße, Bietigheim-Bissingen', 'address': {'road': 'Hauptstraße', 'city': 'Bietigheim-Bissingen'},
}

BN = geo.Place('Bad Nauheim', 'Colonel-Knight-Stadion', 50.3725500, 8.7384500)


def test_stadium_gives_city_and_venue():
    place = geo.place_from_result(STADIUM)
    assert (place.city, place.sublocation) == ('Bad Nauheim', 'Colonel-Knight-Stadion')
    assert place.latitude == pytest.approx(50.3725500) and place.longitude == pytest.approx(8.7384500)
    assert place.label.startswith('Colonel-Knight-Stadion, ')


def test_postcode_and_street_give_only_the_city():
    assert (geo.place_from_result(POSTCODE).city, geo.place_from_result(POSTCODE).sublocation) == ('Bad Nauheim', '')
    assert (geo.place_from_result(STREET).city, geo.place_from_result(STREET).sublocation) == ('Bietigheim-Bissingen', '')


def test_broken_results_are_skipped():
    assert geo.place_from_result({'error': 'Unable to geocode'}) is None
    assert geo.place_from_result({'lat': 'x', 'lon': '1'}) is None
    assert geo.places_from_search([STADIUM, {'nope': 1}, POSTCODE]) == [
        geo.place_from_result(STADIUM), geo.place_from_result(POSTCODE)]
    assert geo.places_from_search({'error': 'x'}) == []


def test_urls_follow_the_usage_policy():
    search = urlparse(geo.search_url('61231 Bad Nauheim'))
    assert search.netloc == 'nominatim.openstreetmap.org' and search.path == '/search'
    assert parse_qs(search.query)['q'] == ['61231 Bad Nauheim']
    reverse = parse_qs(urlparse(geo.reverse_url(50.36335, 8.74107)).query)
    assert reverse['lat'] == ['50.363350'] and reverse['format'] == ['jsonv2']
    assert 'Captioner' in geo.USER_AGENT
    assert geo.tile_url(6, 33, 21) == 'https://tile.openstreetmap.org/6/33/21.png'


@pytest.mark.parametrize('lat, lon', [(50.3633, 8.7411), (-33.86, 151.21), (0, 0), (64.1, -21.9)])
def test_pixels_roundtrip(lat, lon):
    for zoom in (2, 10, 19):
        back = geo.to_coordinates(*geo.to_pixels(lat, lon, zoom), zoom)
        assert back == pytest.approx((lat, lon), abs=1e-7)


def test_known_tile():
    # Bad Nauheim at zoom 10: tile 536/345 (x = (8.7411 + 180) / 360 * 1024 = 536.9,
    # y = (1 - asinh(tan(50.3633°)) / pi) / 2 * 1024 = 345.6)
    x, y = geo.to_pixels(50.3633, 8.7411, 10)
    assert (int(x // geo.TILE_SIZE), int(y // geo.TILE_SIZE)) == (536, 345)


def test_place_book_remembers_newest_first_without_duplicates():
    book = geo.PlaceBook()
    book.remember(BN)
    book.remember(geo.Place('Regensburg', 'Donau-Arena', 49.01, 12.12))
    book.remember(geo.Place('bad nauheim', 'COLONEL-KNIGHT-STADION'))  # without coordinates
    assert [p.city for p in book.places] == ['bad nauheim', 'Regensburg']
    assert book.places[0].latitude == BN.latitude  # coordinates are kept
    assert book.lookup('Bad Nauheim ', 'colonel-knight-stadion').longitude == BN.longitude
    assert book.lookup('', '') is None
    book.remember(geo.Place('', ''))
    assert len(book.places) == 2


def test_place_book_roundtrip_drops_invalid_coordinates():
    book = geo.PlaceBook([BN.to_dict(), {'city': 'X', 'latitude': 123.0, 'longitude': 5.0}, 'kaputt'])
    assert book.places[1].city == 'X' and not book.places[1].has_coordinates
    assert geo.PlaceBook(book.to_list()).to_list() == book.to_list()
    assert 'latitude' not in book.to_list()[1]


def test_place_book_is_limited():
    book = geo.PlaceBook()
    for n in range(geo.MAX_PLACES + 5):
        book.remember(geo.Place(f'Stadt {n}'))
    assert len(book.places) == geo.MAX_PLACES and book.places[0].city == f'Stadt {geo.MAX_PLACES + 4}'


def test_gps_is_set_only_without_camera_gps():
    book = geo.PlaceBook([BN.to_dict()])
    meta = Metadata(city=BN.city, sublocation=BN.sublocation)
    result = geo.apply_gps(meta, book)
    assert (result.latitude, result.longitude, result.gps_changed) == (BN.latitude, BN.longitude, True)

    camera = Metadata(city=BN.city, sublocation=BN.sublocation, latitude=50.1, longitude=8.6)
    assert geo.apply_gps(camera, book) is camera  # camera GPS stays

    unknown = Metadata(city='Irgendwo')
    assert geo.apply_gps(unknown, book) is unknown


def test_gps_from_an_earlier_place_is_replaced():
    other = geo.Place('Regensburg', 'Donau-Arena', 49.01, 12.12)
    book = geo.PlaceBook([BN.to_dict(), other.to_dict()])
    meta = Metadata(city=other.city, sublocation=other.sublocation, latitude=BN.latitude, longitude=BN.longitude)
    result = geo.apply_gps(meta, book)
    assert (result.latitude, result.longitude, result.gps_changed) == (49.01, 12.12, True)
    # same place: nothing to write
    same = Metadata(city=BN.city, sublocation=BN.sublocation, latitude=BN.latitude, longitude=BN.longitude)
    assert geo.apply_gps(same, book) is same
