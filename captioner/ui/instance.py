"""
Eine laufende App je Benutzer (Windows).

Der Explorer startet fuer "Mit Captioner oeffnen" bei mehreren markierten Ordnern je
Ordner einen eigenen Prozess. Der erste wird zur App und lauscht auf einem lokalen
Socket (unter Windows eine Named Pipe); jeder weitere reicht seine Ordner dorthin
weiter und beendet sich. Auf macOS kommen dieselben Faelle als QFileOpenEvent an
(main_window.OpenRequests), dort braucht es das nicht.
"""
import getpass
import json
import logging
import re

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

TIMEOUT_MS = 1000


def server_name():
    try:
        user = getpass.getuser()
    except Exception:
        user = 'user'
    return 'captioner-' + re.sub(r'[^A-Za-z0-9_.-]', '_', user)


def forward(paths, name=None):
    """An eine laufende App weiterreichen. True, wenn eine da war (dann beenden)."""
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(TIMEOUT_MS):
        return False
    socket.write(json.dumps([str(p) for p in paths]).encode('utf-8') + b'\n')
    socket.flush()
    socket.waitForBytesWritten(TIMEOUT_MS)
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(TIMEOUT_MS)
    return True


class InstanceServer(QObject):
    """Nimmt Ordner weiterer Starts an: on_paths(liste), auch mit leerer Liste (nur nach vorn holen)."""

    def __init__(self, on_paths, name=None, parent=None):
        super().__init__(parent)
        self.on_paths = on_paths
        self.buffers = {}    # Socket -> angefangene Zeile
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept)
        name = name or server_name()
        if not self.server.listen(name):
            # Unter Unix kann ein abgestuerzter Lauf die Socket-Datei hinterlassen
            QLocalServer.removeServer(name)
            if not self.server.listen(name):
                logger.warning('Kein Instanz-Socket %s: %s', name, self.server.errorString())

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.buffers[socket] = bytearray()
            socket.readyRead.connect(lambda socket=socket: self._read(socket))
            socket.disconnected.connect(lambda socket=socket: self._drop(socket))
            self._read(socket)  # was schon vor dem connect angekommen ist

    def _read(self, socket):
        buffer = self.buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        while b'\n' in buffer:
            line, _, rest = bytes(buffer).partition(b'\n')
            buffer[:] = rest
            self._deliver(line)

    def _drop(self, socket):
        if self.buffers.pop(socket, None) is not None:
            socket.deleteLater()

    def close(self):
        for socket in list(self.buffers):
            socket.readyRead.disconnect()
            socket.disconnected.disconnect()
            self.buffers.pop(socket)
            socket.abort()
            socket.deleteLater()
        self.server.close()

    def _deliver(self, data):
        try:
            paths = json.loads(data.decode('utf-8'))
        except ValueError:
            logger.warning('Unlesbare Nachricht an die laufende App ignoriert')
            return
        self.on_paths([p for p in paths if isinstance(p, str) and p])
