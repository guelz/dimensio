import sys

import pytest

from dimensio import desktop


@pytest.fixture(autouse=True)
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path


def test_install_writes_entry_and_icon(data_home, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["/home/u/.local/bin/dimensio"])
    written = desktop.install()
    entry_path = data_home / "applications" / "dimensio.desktop"
    icon_path = data_home / "icons" / "hicolor" / "scalable" / "apps" / "dimensio.svg"
    assert written == [entry_path, icon_path]
    entry = entry_path.read_text(encoding="utf-8")
    assert "Exec=/home/u/.local/bin/dimensio %f" in entry
    assert "MimeType=image/jpeg;image/png;" in entry
    assert "Icon=dimensio" in entry
    assert icon_path.read_bytes().startswith(b"<svg")


def test_exec_falls_back_to_the_module(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["/somewhere/dimensio/__main__.py"])
    monkeypatch.setattr(sys, "executable", "/venv/bin/python")
    assert desktop.exec_command() == "/venv/bin/python -m dimensio"


def test_exec_quotes_paths_with_spaces(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["/home/u/my apps/dimensio"])
    assert desktop.exec_command() == '"/home/u/my apps/dimensio"'


def test_ensure_installed_only_installs_once():
    assert desktop.ensure_installed() is True
    assert desktop.ensure_installed() is False


def test_uninstall_removes_both_files(data_home):
    desktop.install()
    assert len(desktop.uninstall()) == 2
    assert not (data_home / "applications" / "dimensio.desktop").exists()
    assert desktop.uninstall() == []
