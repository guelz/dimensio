"""Document model and sidecar (.dims.json) persistence. Pure Python, no Qt."""

from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

SIDECAR_VERSION = 1
SIDECAR_SUFFIX = ".dims.json"
DEFAULT_COLOR = "#FFC400"

Point = tuple[float, float]

_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


class SidecarError(Exception):
    """The sidecar file is unreadable, not valid JSON, or not a version this app understands."""


def is_hex_color(value: object) -> bool:
    return isinstance(value, str) and _HEX_COLOR.fullmatch(value) is not None


@dataclass(frozen=True)
class Style:
    line_width: float
    text_size: float
    color: str = DEFAULT_COLOR
    outline: bool = True  # contrasting halo under lines and text

    @classmethod
    def for_image(cls, width: int, height: int, color: str = DEFAULT_COLOR) -> Style:
        diagonal = math.hypot(width, height)
        return cls(line_width=max(2, round(0.0025 * diagonal)), text_size=round(0.02 * diagonal), color=color)


@dataclass(frozen=True)
class Dimension:
    """Measured points P0..Pn, one label per segment, and one shared offset for the whole chain."""

    points: tuple[Point, ...]
    labels: tuple[str, ...]
    offset: Point = (0.0, 0.0)

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("a dimension needs at least 2 points")
        if len(self.labels) != len(self.points) - 1:
            raise ValueError("a dimension needs exactly one label per segment")

    @classmethod
    def new(cls, points) -> Dimension:
        pts = tuple((float(x), float(y)) for x, y in points)
        return cls(pts, ("",) * (len(pts) - 1))


@dataclass(frozen=True)
class ImageInfo:
    file: str
    width: int
    height: int
    sha256: str

    @classmethod
    def from_file(cls, path: Path, width: int, height: int) -> ImageInfo:
        return cls(path.name, width, height, file_sha256(path))

    def matches(self, other: ImageInfo) -> bool:
        return (self.width, self.height, self.sha256) == (other.width, other.height, other.sha256)


@dataclass
class Document:
    style: Style
    dimensions: list[Dimension] = field(default_factory=list)
    image: ImageInfo | None = None  # None for pasted images


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_path(image_path: Path) -> Path:
    return image_path.with_name(image_path.name + SIDECAR_SUFFIX)


def output_path(image_path: Path) -> Path:
    return image_path.with_name(image_path.stem + "_dims.png")


def find_original(path: Path) -> Path | None:
    """For an exported `<stem>_dims.png`, the original photo that has a sidecar next to it, if any."""
    if not path.stem.endswith("_dims"):
        return None
    base = path.stem[: -len("_dims")]
    for side in sorted(path.parent.glob(glob.escape(base) + ".*" + SIDECAR_SUFFIX)):
        original = side.with_name(side.name[: -len(SIDECAR_SUFFIX)])
        if original.is_file() and output_path(original) == path:
            return original
    return None


def to_json(doc: Document) -> dict:
    data: dict = {"version": SIDECAR_VERSION}
    if doc.image is not None:
        data["image"] = {
            "file": doc.image.file,
            "width": doc.image.width,
            "height": doc.image.height,
            "sha256": doc.image.sha256,
        }
    data["style"] = {
        "line_width": doc.style.line_width,
        "text_size": doc.style.text_size,
        "color": doc.style.color,
        "outline": doc.style.outline,
    }
    data["dimensions"] = [
        {"points": [list(p) for p in d.points], "labels": list(d.labels), "offset": list(d.offset)}
        for d in doc.dimensions
    ]
    return data


def _finite(value) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"not a finite number: {value!r}")
    return number


def _positive(value) -> float:
    number = _finite(value)
    if number <= 0:
        raise ValueError(f"must be positive: {value!r}")
    return number


def _point(value) -> Point:
    x, y = value
    return (_finite(x), _finite(y))


def from_json(data: object) -> Document:
    if not isinstance(data, dict):
        raise SidecarError("invalid sidecar: top level is not an object")
    if data.get("version") != SIDECAR_VERSION:
        raise SidecarError(f"unsupported sidecar version: {data.get('version')!r}")
    try:
        style_data = data["style"]
        color = style_data["color"]
        if not is_hex_color(color):
            raise ValueError(f"bad color {color!r}")
        outline = style_data.get("outline", True)
        if not isinstance(outline, bool):
            raise ValueError(f"bad outline {outline!r}")
        style = Style(_positive(style_data["line_width"]), _positive(style_data["text_size"]), color, outline)
        dimensions = [
            Dimension(
                tuple(_point(p) for p in d["points"]),
                tuple(str(label) for label in d["labels"]),
                _point(d["offset"]),
            )
            for d in data["dimensions"]
        ]
        image = None
        if "image" in data:
            i = data["image"]
            image = ImageInfo(str(i["file"]), int(_positive(i["width"])), int(_positive(i["height"])), str(i["sha256"]))
    except (KeyError, TypeError, ValueError, OverflowError) as e:
        raise SidecarError(f"invalid sidecar: {e}") from e
    return Document(style=style, dimensions=dimensions, image=image)


def save_sidecar(doc: Document, path: Path) -> None:
    """Write atomically: a crash never leaves a half-written sidecar behind."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(to_json(doc), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_sidecar(path: Path) -> Document:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SidecarError(f"cannot read {path.name}: {e}") from e
    return from_json(data)
