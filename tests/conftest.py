import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path_factory):
    """Keep QSettings (last used colour) out of the real home directory."""
    from PySide6.QtCore import QSettings

    path = tmp_path_factory.mktemp("settings")
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(path))
