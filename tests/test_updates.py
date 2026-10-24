"""Update notice: version comparison, GitHub response, display (without a real network)."""
import json
import os

import pytest

from captioner import updates
from conftest import requires_exiftool

RELEASE = {'tag_name': 'v0.1.20', 'html_url': 'https://github.com/katzefudder/Captioner/releases/tag/v0.1.20',
           'draft': False, 'prerelease': False}


def test_versions():
    assert updates.parse_version('v0.1.20') == (0, 1, 20)
    assert updates.parse_version('dev') is None
    assert updates.is_newer('0.1.20', '0.1.9')           # numerically, not as text
    assert not updates.is_newer('0.1.9', '0.1.20')
    assert not updates.is_newer('0.1.20', '0.1.20')
    assert not updates.is_newer('0.2.0', 'dev')


def test_parse_release():
    assert updates.parse_release(RELEASE) == ('0.1.20', RELEASE['html_url'])
    assert updates.parse_release(dict(RELEASE, draft=True)) is None
    assert updates.parse_release({'message': 'Not Found'}) is None


def test_due():
    assert updates.due(0)
    assert not updates.due(1000, now=1000 + 3600)
    assert updates.due(1000, now=1000 + updates.INTERVAL_SECONDS)


@requires_exiftool
@pytest.mark.parametrize('tag, expected', [('v99.0.1', 'found'), ('v0.0.1', 'up_to_date')])
def test_manual_check_shows_result(tmp_path, monkeypatch, tag, expected):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    QtWidgets = pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtCore import QUrl
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from captioner import config
    from captioner.ui.main_window import MainWindow
    from captioner.ui.updatecheck import UpdateChecker
    answer = tmp_path / 'latest.json'
    answer.write_text(json.dumps(dict(RELEASE, tag_name=tag)), encoding='utf-8')
    monkeypatch.setattr(UpdateChecker, 'url', QUrl.fromLocalFile(str(answer)).toString())
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, 'question', lambda *a: shown.append(a[1]) or QtWidgets.QMessageBox.StandardButton.No)
    monkeypatch.setattr(QtWidgets.QMessageBox, 'information', lambda *a: shown.append(a[1]))
    window = MainWindow(config.Settings(roster_sources=[]))
    try:
        window.check_updates(manual=True)
        import time
        deadline = time.time() + 5
        while not shown and time.time() < deadline:
            QtWidgets.QApplication.processEvents()
        if expected == 'found':
            assert shown == ['Update verfügbar'] and window.update_button.isVisibleTo(window)
            assert '99.0.1' in window.update_button.text()
        else:
            assert shown == ['Keine Updates'] and not window.update_button.isVisibleTo(window)
        assert window.settings.last_update_check > 0
    finally:
        window.close()


def test_release_version_goes_into_pyproject_project_section_only():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('set_version', Path(__file__).parent.parent / 'scripts' / 'set_version.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = '[project]\nname = "captioner"\nversion = "0.2"\n\n[tool.other]\nversion = "9"\n'
    assert module.set_version(text, '0.2.41') == text.replace('version = "0.2"', 'version = "0.2.41"')
    real = (Path(__file__).parent.parent / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'version = "0.2.41"' in module.set_version(real, '0.2.41')
    with pytest.raises(ValueError):
        module.set_version('[tool.poetry]\nversion = "1"\n', '0.2.41')
