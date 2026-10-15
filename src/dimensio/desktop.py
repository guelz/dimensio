"""Freedesktop integration: launcher entry, 'Open With' for images, and the icon."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

APP_ID = "dimensio"
MIME_TYPES = ("image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp", "image/heif", "image/avif")

_NEEDS_QUOTES = set(' \t\n"\'\\><~|&;$*?#()`')


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def desktop_file() -> Path:
    return data_home() / "applications" / f"{APP_ID}.desktop"


def icon_file() -> Path:
    return data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"


def icon_source():
    return resources.files("dimensio") / "data" / "dimensio.svg"


def _quote(arg: str) -> str:
    if not _NEEDS_QUOTES.intersection(arg):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'


def exec_command() -> str:
    """Command line that starts this installation of Dimensio."""
    script = Path(sys.argv[0])
    if script.name == APP_ID:  # the console script that pipx / uv tool put on PATH
        return _quote(str(script.absolute()))
    return f"{_quote(sys.executable)} -m {APP_ID}"


def desktop_entry(exec_cmd: str) -> str:
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Dimensio",
            "GenericName=Dimension Lines",
            "Comment=Add dimension lines with your own measurements to photos",
            f"Exec={exec_cmd} %f",
            f"Icon={APP_ID}",
            "Terminal=false",
            "Categories=Graphics;2DGraphics;",
            f"MimeType={';'.join(MIME_TYPES)};",
            "Keywords=measure;dimension;annotate;photo;",
            "",
        ]
    )


def install() -> list[Path]:
    entry, icon = desktop_file(), icon_file()
    entry.parent.mkdir(parents=True, exist_ok=True)
    icon.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(desktop_entry(exec_command()), encoding="utf-8")
    icon.write_bytes(icon_source().read_bytes())
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(entry.parent)], check=False, capture_output=True)
    return [entry, icon]


def uninstall() -> list[Path]:
    removed = []
    for path in (desktop_file(), icon_file()):
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def ensure_installed() -> bool:
    """Install on first launch. Returns True only if it installed just now."""
    if desktop_file().exists():
        return False
    try:
        install()
    except OSError:
        return False
    return True
