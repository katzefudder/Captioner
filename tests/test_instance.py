"""Weitere Starts reichen ihre Ordner an die laufende App weiter (Windows, ui/instance.py)."""
import os
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


def test_second_start_forwards_folders(app):
    name = f'captioner-test-{os.getpid()}'
    received = []
    server = instance.InstanceServer(received.append, name=name)
    try:
        assert instance.forward(['C:\\Fotos\\Spiel', 'E:\\DCIM\\100NCZ_9'], name=name)
        assert wait_for(lambda: received)
        assert received == [['C:\\Fotos\\Spiel', 'E:\\DCIM\\100NCZ_9']]
        assert instance.forward([], name=name)  # ohne Ordner: nur nach vorn holen
        assert wait_for(lambda: len(received) == 2) and received[1] == []
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
    assert command_line_path('E:"') == 'E:\\'          # aus "E:\" wird E:" (Escape)
    assert command_line_path('E:\\DCIM') == 'E:\\DCIM'
    assert command_line_path('') == ''
