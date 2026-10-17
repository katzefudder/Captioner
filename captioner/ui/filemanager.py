"""Finder/Explorer: Datei zeigen und in den Papierkorb legen."""
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QProcess, QUrl
from PySide6.QtGui import QDesktopServices

from ..i18n import _


def _ok(result):
    """PySide liefert je nach Ueberladung (bool, ...) oder nur bool."""
    return bool(result[0] if isinstance(result, tuple) else result)


def reveal_label():
    if sys.platform == 'darwin':
        return _('Im Finder zeigen')
    if sys.platform == 'win32':
        return _('Im Explorer zeigen')
    return _('Im Dateimanager zeigen')


def reveal(path):
    """Ordner oeffnen und die Datei darin markieren (anderswo nur den Ordner oeffnen)."""
    path = Path(path)
    if sys.platform == 'darwin':
        return _ok(QProcess.startDetached('open', ['-R', str(path)]))
    if sys.platform == 'win32':
        # explorer will "/select," und den Pfad in einem Argument, mit Anfuehrungszeichen
        process = QProcess()
        process.setProgram('explorer.exe')
        process.setNativeArguments(f'/select,"{path}"')
        return _ok(process.startDetached())
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def move_to_trash(path):
    """In den Papierkorb (wiederherstellbar), nie endgueltig loeschen. False bei Fehler."""
    return _ok(QFile.moveToTrash(str(path)))
