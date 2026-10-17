"""Document model and sidecar (.dims.json) persistence. Pure Python, no Qt."""

from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field, replace
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
class LayerStyle:
    """What each layer (kind) can set for itself."""

    line_width: float
    color: str = DEFAULT_COLOR
    outline: bool = True


LAYER_FIELDS = ("line_width", "color", "outline")


@dataclass(frozen=True)
class Style:
    line_width: float
    text_size: float
    color: str = DEFAULT_COLOR
    outline: bool = True  # contrasting halo under lines and text
    ids: bool = False  # draw the A, B, … / L1, … names next to the labels
    hidden: tuple[str, ...] = ()  # kinds (see KINDS) left out of the view and the export
    # Per-kind line width / colour / outline; a kind without an entry uses the fields above.
    layers: tuple[tuple[str, LayerStyle], ...] = ()

    def layer(self, kind: str) -> LayerStyle:
        return dict(self.layers).get(kind, LayerStyle(self.line_width, self.color, self.outline))

    def for_kind(self, kind: str) -> Style:
        """This style as seen by one layer: its own width, colour and outline."""
        own = self.layer(kind)
        return replace(self, line_width=own.line_width, color=own.color, outline=own.outline)

    def with_layer(self, kind: str, **changes) -> Style:
        layers = dict(self.layers)
        layers[kind] = replace(self.layer(kind), **changes)
        return replace(self, layers=tuple(sorted(layers.items(), key=lambda kv: KINDS.index(kv[0]))))

    @classmethod
    def for_image(cls, width: int, height: int, color: str = DEFAULT_COLOR) -> Style:
        diagonal = math.hypot(width, height)
        # Middle ground (geometric mean) between thin-on-white-scans and readable-on-busy-photos:
        # a 12 MP photo gets 6 px / 60 px, a 640 px plan 1 px / 9 px.
        return cls(line_width=max(1, round(0.0011 * diagonal)), text_size=max(6, round(0.012 * diagonal)), color=color)


@dataclass(frozen=True)
class Dimension:
    """Measured points P0..Pn, one label per segment, one shared offset for the whole chain,
    and one optional angle label per corner (P1..Pn-1); an empty angle label draws nothing."""

    points: tuple[Point, ...]
    labels: tuple[str, ...]
    offset: Point = (0.0, 0.0)
    angles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("a dimension needs at least 2 points")
        if len(self.labels) != len(self.points) - 1:
            raise ValueError("a dimension needs exactly one label per segment")
        corners = len(self.points) - 2
        if not self.angles and corners:
            object.__setattr__(self, "angles", ("",) * corners)
        if len(self.angles) != corners:
            raise ValueError("a dimension needs exactly one angle label per corner")

    @classmethod
    def new(cls, points) -> Dimension:
        pts = tuple((float(x), float(y)) for x, y in points)
        return cls(pts, ("",) * (len(pts) - 1))


@dataclass(frozen=True)
class Level:
    """A height marker (Höhenkote): a half-filled triangle pointing at `point` with a free-text level."""

    point: Point
    label: str = ""
    offset: Point = (0.0, 0.0)


@dataclass(frozen=True)
class Line:
    """A plain polyline: no arrows, no labels."""

    points: tuple[Point, ...]

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("a line needs at least 2 points")


@dataclass(frozen=True)
class Note:
    """One line of text with a leader and an arrowhead pointing at `point`; `offset` places the text."""

    point: Point
    label: str = ""
    offset: Point = (0.0, 0.0)


@dataclass(frozen=True)
class Circle:
    """A circle around `center` through `edge`. A label adds a measurement line towards `edge`:
    a radius line if the label starts with R, otherwise a diameter line."""

    center: Point
    edge: Point
    label: str = ""

    @property
    def radius(self) -> float:
        return math.dist(self.center, self.edge)


Annotation = Dimension | Level | Line | Note | Circle

KINDS = ("dimension", "level", "line", "note", "circle")  # one layer per kind, edited by the tool of that name


def kind_of(item: Annotation) -> str:
    return {Dimension: "dimension", Level: "level", Line: "line", Note: "note", Circle: "circle"}[type(item)]


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
    dimensions: list[Annotation] = field(default_factory=list)  # everything drawn, in drawing order
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


ABOUT = {
    "generator": "Dimensio, https://github.com/guelz/dimensio",
    "coordinates": "image pixels of the (EXIF-oriented) image: origin top-left, x to the right, y down",
    "dimensions": (
        "points are the measured points in order; labels[i] is the text for the segment points[i] -> points[i+1]; "
        "angles[j], if present, is the text for the corner at points[j+1]; offset only moves the drawn line away "
        "from the points"
    ),
    "levels": "point is the marked spot; label is its height text; offset only moves the drawn symbol",
    "lines": "plain polylines through points, without meaning beyond what the picture shows",
    "notes": "free text pointing at point (the arrowhead); the text sits at point + offset",
    "circles": (
        "center and edge define the circle; label, if any, is its measurement text: starting with R it is drawn "
        "on a radius line from center to edge, otherwise on a diameter line through center towards edge"
    ),
    "ids": (
        "A, B, C, ... name the dimensions, L1, ... the levels, N1, ... the lines, T1, ... the notes and C1, ... the circles, "
        "as tagged on the image when ids are shown"
    ),
    "labels": "free text typed by a person; Dimensio does not measure anything",
}


def annotation_ids(items) -> list[str]:
    """Names in drawing order: dimensions A, B, …, Z, AA, AB, …; levels L1, …; lines N1, …; notes T1, …"""
    names, letters = [], 0
    counts = {"L": 0, "N": 0, "T": 0, "C": 0}
    prefixes = {Level: "L", Line: "N", Note: "T", Circle: "C"}
    for item in items:
        prefix = prefixes.get(type(item))
        if prefix is not None:
            counts[prefix] += 1
            names.append(f"{prefix}{counts[prefix]}")
            continue
        n, name = letters, ""
        while True:
            name = chr(ord("A") + n % 26) + name
            n = n // 26 - 1
            if n < 0:
                break
        names.append(name)
        letters += 1
    return names


def to_json(doc: Document, visible_only: bool = False) -> dict:
    """The sidecar data. `visible_only` leaves out hidden layers (for data embedded in an export);
    ids are always counted over everything, so they match the editable file."""
    data: dict = {"version": SIDECAR_VERSION, "about": ABOUT}
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
        "ids": doc.style.ids,
        "hidden": list(doc.style.hidden),
    }
    if doc.style.layers:
        data["style"]["layers"] = {
            kind: {"line_width": s.line_width, "color": s.color, "outline": s.outline} for kind, s in doc.style.layers
        }
    data["dimensions"] = []
    levels, lines, notes, circles = [], [], [], []
    for d, name in zip(doc.dimensions, annotation_ids(doc.dimensions)):
        if visible_only and kind_of(d) in doc.style.hidden:
            continue
        if isinstance(d, Level):
            levels.append({"id": name, "point": list(d.point), "label": d.label, "offset": list(d.offset)})
            continue
        if isinstance(d, Line):
            lines.append({"id": name, "points": [list(p) for p in d.points]})
            continue
        if isinstance(d, Note):
            notes.append({"id": name, "point": list(d.point), "label": d.label, "offset": list(d.offset)})
            continue
        if isinstance(d, Circle):
            circles.append({"id": name, "center": list(d.center), "edge": list(d.edge), "label": d.label})
            continue
        entry = {"id": name, "points": [list(p) for p in d.points], "labels": list(d.labels), "offset": list(d.offset)}
        if any(d.angles):  # only stored when something was typed
            entry["angles"] = list(d.angles)
        data["dimensions"].append(entry)
    for key, entries in (("levels", levels), ("lines", lines), ("notes", notes), ("circles", circles)):
        if entries:
            data[key] = entries
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
        ids = style_data.get("ids", False)
        if not isinstance(outline, bool) or not isinstance(ids, bool):
            raise ValueError(f"bad outline/ids {outline!r}/{ids!r}")
        hidden = style_data.get("hidden", [])
        if not isinstance(hidden, list) or not set(hidden) <= set(KINDS):
            raise ValueError(f"bad hidden layers {hidden!r}")
        hidden = tuple(k for k in KINDS if k in hidden)
        layers = []
        for kind, v in style_data.get("layers", {}).items():
            if kind not in KINDS or not is_hex_color(v["color"]) or not isinstance(v["outline"], bool):
                raise ValueError(f"bad layer {kind!r}")
            layers.append((kind, LayerStyle(_positive(v["line_width"]), v["color"], v["outline"])))
        layers.sort(key=lambda kv: KINDS.index(kv[0]))
        style = Style(
            _positive(style_data["line_width"]), _positive(style_data["text_size"]), color, outline, ids, hidden, tuple(layers)
        )
        dimensions = [
            Dimension(
                tuple(_point(p) for p in d["points"]),
                tuple(str(label) for label in d["labels"]),
                _point(d["offset"]),
                tuple(str(a) for a in d.get("angles", ())),
            )
            for d in data["dimensions"]
        ]
        dimensions += [
            Level(_point(v["point"]), str(v["label"]), _point(v["offset"])) for v in data.get("levels", [])
        ]
        dimensions += [Line(tuple(_point(p) for p in v["points"])) for v in data.get("lines", [])]
        dimensions += [
            Note(_point(v["point"]), str(v["label"]), _point(v["offset"])) for v in data.get("notes", [])
        ]
        dimensions += [
            Circle(_point(v["center"]), _point(v["edge"]), str(v["label"])) for v in data.get("circles", [])
        ]
        image = None
        if "image" in data:
            i = data["image"]
            image = ImageInfo(str(i["file"]), int(_positive(i["width"])), int(_positive(i["height"])), str(i["sha256"]))
    except (KeyError, TypeError, ValueError, OverflowError) as e:
        raise SidecarError(f"invalid sidecar: {e}") from e
    return Document(style=style, dimensions=dimensions, image=image)


def to_json_text(doc: Document, visible_only: bool = False) -> str:
    return json.dumps(to_json(doc, visible_only), indent=2, ensure_ascii=False) + "\n"


def original_from_data(path: Path, data: dict | None) -> Path | None:
    """The original photo named in data embedded in an exported image, if it sits next to it."""
    image = data.get("image") if isinstance(data, dict) else None
    name = image.get("file") if isinstance(image, dict) else None
    if not isinstance(name, str) or not name or name != Path(name).name or name in (".", ".."):
        return None
    candidate = path.with_name(name)
    return candidate if candidate.is_file() and candidate != path else None


def save_sidecar(doc: Document, path: Path) -> None:
    """Write atomically: a crash never leaves a half-written sidecar behind."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(to_json_text(doc), encoding="utf-8")
    os.replace(tmp, path)


def load_sidecar(path: Path) -> Document:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SidecarError(f"cannot read {path.name}: {e}") from e
    return from_json(data)
