"""
One running app per user (Windows).

For "Open with Captioner" on several selected folders, Explorer starts a separate
process per folder. The first one becomes the app and listens on a local socket (a
named pipe on Windows); every further one passes its folders there and quits. On macOS
the same cases arrive as QFileOpenEvent (main_window.OpenRequests), so it isn't
needed there.
"""
import getpass
import json
import logging
import re

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

TIMEOUT_MS = 1000
ACK_TIMEOUT_MS = 5000   # until the running app has taken over the folders


def server_name():
    try:
        user = getpass.getuser()
    except Exception:
        user = 'user'
    return 'captioner-' + re.sub(r'[^A-Za-z0-9_.-]', '_', user)


def forward(paths, name=None):
    """
    Pass on to a running app. True if there was one (then quit).

    One message per connection: JSON list plus line ending. The server hangs up as soon
    as it has taken it over; only then does this process end. Hanging up right away
    loses unread data in the named pipe on Windows.
    """
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(TIMEOUT_MS):
        return False
    socket.write(json.dumps([str(p) for p in paths]).encode('utf-8') + b'\n')
    socket.flush()
    socket.waitForBytesWritten(TIMEOUT_MS)
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(ACK_TIMEOUT_MS)
    socket.abort()
    return True


class InstanceServer(QObject):
    """Accepts folders of further starts: on_paths(list), also with an empty list (just raise)."""

    def __init__(self, on_paths, name=None, parent=None):
        super().__init__(parent)
        self.on_paths = on_paths
        self.buffers = {}    # socket -> partial line
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept)
        name = name or server_name()
        if not self.server.listen(name):
            # on Unix a crashed run can leave the socket file behind
            QLocalServer.removeServer(name)
            if not self.server.listen(name):
                logger.warning('Kein Instanz-Socket %s: %s', name, self.server.errorString())

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.buffers[socket] = bytearray()
            socket.readyRead.connect(lambda socket=socket: self._read(socket))
            socket.disconnected.connect(lambda socket=socket: self._drop(socket))
            self._read(socket)  # whatever arrived before the connect

    def _read(self, socket):
        buffer = self.buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if b'\n' in buffer:
            line = bytes(buffer).partition(b'\n')[0]
            self._finish(socket)
            self._deliver(line)

    def _finish(self, socket):
        """Taken over: hang up so the passing process ends."""
        if self.buffers.pop(socket, None) is None:
            return
        socket.readyRead.disconnect()
        socket.disconnected.disconnect()
        socket.disconnectFromServer()
        socket.deleteLater()

    def _drop(self, socket):
        """Other side gone: what is still in the buffer counts (even without a line ending)."""
        if socket not in self.buffers:
            return
        self._read(socket)
        rest = self.buffers.pop(socket, None)
        socket.deleteLater()
        if rest:
            self._deliver(bytes(rest))

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
