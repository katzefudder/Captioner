"""Finder/Explorer: show a file and move it to the trash."""
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QProcess, QUrl
from PySide6.QtGui import QDesktopServices

from ..i18n import _


def _ok(result):
    """Depending on the overload PySide returns (bool, ...) or just bool."""
    return bool(result[0] if isinstance(result, tuple) else result)


def reveal_label():
    if sys.platform == 'darwin':
        return _('Im Finder zeigen')
    if sys.platform == 'win32':
        return _('Im Explorer zeigen')
    return _('Im Dateimanager zeigen')


def reveal(path):
    """Open the folder and select the file in it (elsewhere just open the folder)."""
    path = Path(path)
    if sys.platform == 'darwin':
        return _ok(QProcess.startDetached('open', ['-R', str(path)]))
    if sys.platform == 'win32':
        # explorer wants "/select," and the path in one argument, with quotes
        process = QProcess()
        process.setProgram('explorer.exe')
        process.setNativeArguments(f'/select,"{path}"')
        return _ok(process.startDetached())
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def move_to_trash(path):
    """To the trash (restorable), never delete permanently. False on error."""
    return _ok(QFile.moveToTrash(str(path)))
