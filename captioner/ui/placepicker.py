"""
Ort waehlen: Suche (Adresse, PLZ, Halle -> Punkt), Klick auf die Karte
(Punkt -> Stadt/Halle), oder einfach Stadt und Ort eintippen.

Offline ersetzt ein Hinweis die Karte; Stadt und Ort bleiben Textfelder, und
gemerkte Orte werden weiter vorgeschlagen.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCompleter, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import geo
from .mapview import Geocoder, MapView

OFFLINE_TEXT = ('Diese Karte kann nur bei Verbindung mit dem Internet angezeigt werden.\n'
                'Stadt und Ort lassen sich unten trotzdem eintragen; bereits gewählte Orte werden vorgeschlagen.')


def place_completer(book, parent):
    """Vorschlaege 'Stadt – Ort' aus dem PlaceBook; funktioniert offline."""
    completer = QCompleter([p.display() for p in book.places], parent)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    return completer


def place_for_completion(book, text):
    return next((p for p in book.places if p.display() == text), None)


class PlacePickerDialog(QDialog):
    def __init__(self, place: geo.Place, book: geo.PlaceBook, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Ort wählen')
        self.resize(760, 680)
        self.book = book
        self.latitude = place.latitude if place else None
        self.longitude = place.longitude if place else None
        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText('Adresse, PLZ oder Halle suchen, z. B. „61231 Bad Nauheim“')
        self.query.returnPressed.connect(self.search)
        self.search_button = QPushButton('Suchen')
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        self.results = QListWidget()
        self.results.setMaximumHeight(110)
        self.results.hide()
        self.results.itemActivated.connect(self._result_chosen)
        self.results.itemClicked.connect(self._result_chosen)
        layout.addWidget(self.results)

        self.stack = QStackedWidget()
        self.map = MapView()
        self.map.clicked.connect(self._map_clicked)
        self.map.online_changed.connect(self._online_changed)
        self.stack.addWidget(self.map)
        offline = QWidget()
        offline_layout = QVBoxLayout(offline)
        offline_layout.addStretch(1)
        self.offline_label = QLabel(OFFLINE_TEXT)
        self.offline_label.setWordWrap(True)
        self.offline_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        offline_layout.addWidget(self.offline_label)
        retry = QPushButton('Erneut versuchen')
        retry.clicked.connect(self._retry)
        offline_layout.addWidget(retry, 0, Qt.AlignmentFlag.AlignHCenter)
        offline_layout.addStretch(1)
        self.stack.addWidget(offline)
        layout.addWidget(self.stack, 1)

        self.status = QLabel('Auf die Karte klicken, um den Ort zu setzen. Ziehen verschiebt, Mausrad zoomt.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color: gray;')
        layout.addWidget(self.status)

        form = QFormLayout()
        self.city = QLineEdit(place.city if place else '')
        self.sublocation = QLineEdit(place.sublocation if place else '')
        self.city.setCompleter(place_completer(book, self))
        self.city.completer().activated.connect(self._known_place_chosen)
        self.coordinates = QLabel()
        form.addRow('Stadt', self.city)
        form.addRow('Ort / Halle', self.sublocation)
        form.addRow('GPS', self.coordinates)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.geocoder = Geocoder(self)
        self.geocoder.found.connect(self._found)
        self.geocoder.resolved.connect(self._resolved)
        self.geocoder.failed.connect(self._failed)

        if self.latitude is not None:
            self.map.set_view(self.latitude, self.longitude, 15)
            self.map.set_marker(self.latitude, self.longitude)
        self._update_coordinates()
        self.query.setFocus()

    # --- Ergebnis -------------------------------------------------------------

    def place(self):
        place = geo.Place(self.city.text().strip(), self.sublocation.text().strip(), self.latitude, self.longitude)
        found = getattr(self, '_found_place', None)
        if found is not None:
            place.state, place.country = found.state, found.country
        return place

    def _set_point(self, lat, lon, zoom=None):
        self.latitude, self.longitude = lat, lon
        if zoom is not None:
            self.map.set_view(lat, lon, zoom)
        self.map.set_marker(lat, lon)
        self._update_coordinates()

    def _update_coordinates(self):
        if self.latitude is None:
            self.coordinates.setText('<i>keine – nur Stadt und Ort werden geschrieben</i>')
        else:
            self.coordinates.setText(f'{self.latitude:.5f}, {self.longitude:.5f} '
                                     '<small>(nur in Bilder ohne GPS der Kamera)</small>')

    def _fill(self, place):
        self._found_place = place
        if place.city:
            self.city.setText(place.city)
        # Ohne Hallen-/Ortsnamen bleibt ein eingetippter Ort stehen
        if place.sublocation:
            self.sublocation.setText(place.sublocation)

    # --- Suche und Karte ------------------------------------------------------

    def search(self):
        if self.query.text().strip():
            self.status.setText('Suche …')
            self.geocoder.search(self.query.text())

    def _found(self, places):
        self.results.clear()
        if not places:
            self.results.hide()
            self.status.setText('Nichts gefunden. Anders formulieren oder direkt auf die Karte klicken.')
            return
        for place in places:
            entry = QListWidgetItem(place.label)
            entry.setData(Qt.ItemDataRole.UserRole, place)
            self.results.addItem(entry)
        self.results.setVisible(len(places) > 1)
        self.results.setCurrentRow(0)
        self._use_result(places[0])
        self.status.setText(f'{len(places)} Treffer' + (' – den passenden in der Liste wählen.' if len(places) > 1 else ''))

    def _result_chosen(self, entry):
        self._use_result(entry.data(Qt.ItemDataRole.UserRole))

    def _use_result(self, place):
        self._set_point(place.latitude, place.longitude, 16 if place.sublocation else 14)
        self._fill(place)

    def _map_clicked(self, lat, lon):
        self._set_point(lat, lon)
        self.status.setText('Ort wird ermittelt …')
        self.geocoder.reverse(lat, lon)

    def _resolved(self, place):
        if place is None:
            self.status.setText('Zu diesem Punkt ist keine Adresse bekannt; Stadt und Ort bitte eintragen.')
            return
        self._fill(place)
        self.status.setText(place.label)

    def _failed(self, message):
        self.status.setText(message)

    def _known_place_chosen(self, text):
        place = place_for_completion(self.book, text)
        if place is None:
            return
        # QLineEdit hat gerade den Vorschlag "Stadt – Ort" eingesetzt; aufteilen
        self.city.setText(place.city)
        self.sublocation.setText(place.sublocation)
        if place.has_coordinates:
            self._set_point(place.latitude, place.longitude, 15)

    def _online_changed(self, online):
        self.stack.setCurrentIndex(0 if online else 1)
        self.search_button.setEnabled(online)
        self.query.setEnabled(online)

    def _retry(self):
        self.map.retry()
        self.stack.setCurrentIndex(0)
        self.search_button.setEnabled(True)
        self.query.setEnabled(True)
