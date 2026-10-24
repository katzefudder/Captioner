"""Further starts pass their folders to the running app (Windows, ui/instance.py)."""
import os
import subprocess
import sys
import time

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')
QApplication = QtWidgets.QApplication

from captioner.ui import instance  # noqa: E402


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def wait_for(condition, seconds=3):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    return condition()


FORWARD = """
import sys
from PySide6.QtCore import QCoreApplication
from captioner.ui import instance
app = QCoreApplication([])
sys.exit(0 if instance.forward(sys.argv[2:], name=sys.argv[1]) else 3)
"""


def start_second(name, *paths):
    """A second start as a separate process, as from Explorer."""
    return subprocess.Popen([sys.executable, '-c', FORWARD, name, *paths])


def test_second_start_forwards_folders(app):
    name = f'captioner-test-{os.getpid()}'
    received = []
    server = instance.InstanceServer(received.append, name=name)
    try:
        second = start_second(name, 'C:\\Fotos\\Spiel', 'E:\\DCIM\\100NCZ_9')
        assert wait_for(lambda: second.poll() is not None, 15)
        assert second.returncode == 0 and received == [['C:\\Fotos\\Spiel', 'E:\\DCIM\\100NCZ_9']]
        third = start_second(name)  # without folders: just raise the window
        assert wait_for(lambda: third.poll() is not None, 15)
        assert third.returncode == 0 and received[1:] == [[]]
    finally:
        server.close()
        QApplication.processEvents()
        server.deleteLater()
        QApplication.processEvents()


def test_first_start_finds_nobody(app):
    assert not instance.forward(['/tmp'], name=f'captioner-niemand-{os.getpid()}')


def test_drive_from_explorer_context_menu(monkeypatch):
    from captioner.ui.main_window import command_line_path
    monkeypatch.setattr('sys.platform', 'win32')
    assert command_line_path('E:"') == 'E:\\'          # "E:\" becomes E:" (escape)
    assert command_line_path('E:\\DCIM') == 'E:\\DCIM'
    assert command_line_path('') == ''
