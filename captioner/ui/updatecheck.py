"""Neue Version suchen (GitHub-Releases) und in der Statusleiste anbieten."""
import json
import time

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import updates, version


class UpdateChecker(QObject):
    found = Signal(str, str)       # Version, Release-Seite
    up_to_date = Signal(str)       # eigene Version
    failed = Signal(str)

    url = updates.LATEST_URL       # in Tests ersetzbar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.checked_at = None

    def check(self):
        request = QNetworkRequest(QUrl(self.url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, f'Captioner/{version()}')
        request.setRawHeader(b'Accept', b'application/vnd.github+json')
        request.setTransferTimeout(10000)
        reply = self.network.get(request)
        reply.finished.connect(lambda r=reply: self._finished(r))

    def _finished(self, reply):
        error = reply.error()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        data = bytes(reply.readAll())
        reply.deleteLater()
        self.checked_at = time.time()
        if error != QNetworkReply.NetworkError.NoError:
            self.failed.emit(str(status or reply.errorString()))
            return
        try:
            release = updates.parse_release(json.loads(data.decode('utf-8')))
        except ValueError:
            release = None
        if release is None:
            self.failed.emit('')
        elif updates.is_newer(release[0], version()):
            self.found.emit(*release)
        else:
            self.up_to_date.emit(version())
