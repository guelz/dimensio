"""Painting dimensions with QPainter. Shared by the canvas and the export so both look identical."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTransform,
)

from .geometry import Layout, LevelLayout, NoteLayout, layout, level_layout, note_layout
from .model import Annotation, Dimension, Document, Level, Line, Note, Style, annotation_ids, kind_of

ALLOCATION_LIMIT_MB = 1024  # Qt's default of 256 MB refuses photos above ~64 MP
EMBED_KEY = "dimensio"  # PNG text chunk holding the sidecar JSON in exported images


class ImageLoadError(Exception):
    pass


def load_image(path: Path) -> QImage:
    QImageReader.setAllocationLimit(ALLOCATION_LIMIT_MB)
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)  # apply EXIF orientation
    image = reader.read()
    if image.isNull():
        raise ImageLoadError(f"{path.name}: {reader.errorString()}")
    return image


def save_image(image: QImage, path: Path) -> None:
    if path.suffix.lower() in (".jpg", ".jpeg"):
        ok = image.convertToFormat(QImage.Format.Format_RGB32).save(str(path), "JPG", 92)
    else:
        ok = image.save(str(path), "PNG")
    if not ok:
        raise OSError(f"could not write {path}")


def read_embedded(path: Path) -> dict | None:
    """The Dimensio data an exported image carries, without decoding its pixels."""
    text = QImageReader(str(path)).text(EMBED_KEY)
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def halo_width(line_width: float) -> float:
    return max(1.0, 0.5 * line_width)


def halo_color(color: QColor) -> QColor:
    luminance = 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()
    return QColor("black") if luminance > 0.5 else QColor("white")


def label_font(text_size: float) -> QFont:
    font = QFont(QGuiApplication.font().family())
    font.setPixelSize(max(1, round(text_size)))
    font.setWeight(QFont.Weight.DemiBold)
    return font


@dataclass
class DimensionPaths:
    strokes: QPainterPath  # centre lines (dimension and extension lines), stroked with the line width
    fills: QPainterPath  # arrowheads and label glyphs, filled
    label_boxes: list[QPolygonF]  # one rotated box per segment label, for hit tests and the editor
    layout: Layout | LevelLayout | NoteLayout | None  # None for plain lines
    angle_boxes: list[QPolygonF | None] = field(default_factory=list)  # per corner; None = no angle text


def build_paths(item: Annotation, style: Style, tag: str = "") -> DimensionPaths:
    """`tag` is the item's name (A, L1, …) drawn in a small box next to its first label; "" for none."""
    if isinstance(item, Level):
        return _level_paths(item, style, tag)
    if isinstance(item, Line):
        return _line_paths(item, style, tag)
    if isinstance(item, Note):
        return _note_paths(item, style, tag)
    return _dimension_paths(item, style, tag)


def _line_paths(line: Line, style: Style, tag: str = "") -> DimensionPaths:
    strokes, fills = QPainterPath(), QPainterPath()
    strokes.moveTo(*line.points[0])
    for p in line.points[1:]:
        strokes.lineTo(*p)
    if tag:
        (x0, y0), (x1, y1) = line.points[0], line.points[1]
        transform = QTransform()
        transform.translate((x0 + x1) / 2, (y0 + y1) / 2)
        _add_tag(strokes, fills, tag, style, transform, 0.0, -0.6 * style.text_size, 0)
    return DimensionPaths(strokes, fills, [], None)


def _note_paths(note: Note, style: Style, tag: str = "") -> DimensionPaths:
    lay = note_layout(note, style.line_width, style.text_size)
    font = label_font(style.text_size)
    metrics = QFontMetricsF(font)
    width = max(metrics.horizontalAdvance(lay.label), style.text_size)
    ax, ay = lay.attach
    left = ax if lay.text_right else ax - width
    strokes, fills = QPainterPath(), QPainterPath()
    strokes.moveTo(*lay.spot)
    strokes.lineTo(ax, ay)
    strokes.lineTo(ax + width if lay.text_right else ax - width, ay)  # underline the text sits on
    if lay.arrow is not None:
        fills.addPolygon(QPolygonF([QPointF(*p) for p in lay.arrow]))
        fills.closeSubpath()
    bottom = ay - lay.gap
    if lay.label:
        fills.addText(left, bottom - metrics.descent(), font, lay.label)
    box = QPolygonF(QRectF(left, bottom - metrics.height(), width, metrics.height()))
    if tag:
        _add_tag(strokes, fills, tag, style, QTransform(), left + width if lay.text_right else left,
                 bottom - metrics.height() / 2, +1 if lay.text_right else -1)
    return DimensionPaths(strokes, fills, [box], lay)


def _add_tag(strokes: QPainterPath, fills: QPainterPath, tag: str, style: Style, transform: QTransform, center_x: float, center_y: float, side: int) -> None:
    """Rounded box with the tag, beside a label. `side` -1 puts it left of (center_x), +1 right of it."""
    font = label_font(0.6 * style.text_size)
    metrics = QFontMetricsF(font)
    height = 0.9 * style.text_size
    width = max(height, metrics.horizontalAdvance(tag) + 0.4 * style.text_size)
    cx = center_x + side * (0.3 * style.text_size + width / 2)
    box = QPainterPath()
    box.addRoundedRect(QRectF(cx - width / 2, center_y - height / 2, width, height), height / 2, height / 2)
    strokes.addPath(transform.map(box))
    text = QPainterPath()
    text.addText(cx - metrics.horizontalAdvance(tag) / 2, center_y + (metrics.ascent() - metrics.descent()) / 2, font, tag)
    fills.addPath(transform.map(text))


def _level_paths(level: Level, style: Style, tag: str = "") -> DimensionPaths:
    lay = level_layout(level, style.line_width, style.text_size)
    font = label_font(style.text_size)
    metrics = QFontMetricsF(font)
    tip, left, right = lay.triangle
    strokes = QPainterPath()
    strokes.addPolygon(QPolygonF([QPointF(*tip), QPointF(*left), QPointF(*right)]))
    strokes.closeSubpath()
    width = metrics.horizontalAdvance(lay.label)
    line_end = max(lay.text_anchor[0] + width, right[0]) + 0.3 * style.text_size
    strokes.moveTo(*lay.line_start)
    strokes.lineTo(line_end, lay.line_start[1])
    if lay.leader is not None:
        strokes.moveTo(*lay.leader[0])
        strokes.lineTo(*lay.leader[1])
    fills = QPainterPath()
    top_mid = ((left[0] + right[0]) / 2, left[1])
    fills.addPolygon(QPolygonF([QPointF(*tip), QPointF(*left), QPointF(*top_mid)]))  # left half filled
    fills.closeSubpath()
    x, y = lay.text_anchor
    box = QPolygonF(QRectF(x, y - metrics.height(), max(width, style.text_size), metrics.height()))
    if lay.label:
        fills.addText(x, y - metrics.descent(), font, lay.label)
    if tag:
        _add_tag(strokes, fills, tag, style, QTransform(), x + width, y - metrics.height() / 2, +1)
    return DimensionPaths(strokes, fills, [box], lay)


def _dimension_paths(dim: Dimension, style: Style, tag: str = "") -> DimensionPaths:
    lay = layout(dim, style.line_width, style.text_size)
    strokes = QPainterPath()
    fills = QPainterPath()
    for start, end in lay.extension_lines:
        strokes.moveTo(*start)
        strokes.lineTo(*end)

    font = label_font(style.text_size)
    metrics = QFontMetricsF(font)
    boxes = []
    for seg in lay.segments:
        strokes.moveTo(*seg.line_start)
        strokes.lineTo(*seg.line_end)
        for tip, left, right in seg.arrows:
            fills.addPolygon(QPolygonF([QPointF(*tip), QPointF(*left), QPointF(*right)]))
            fills.closeSubpath()

        transform = QTransform()
        transform.translate(*seg.text_anchor)
        transform.rotate(seg.text_angle)
        width = metrics.horizontalAdvance(seg.label)
        box_width = max(width, style.text_size)
        boxes.append(transform.map(QPolygonF(QRectF(-box_width / 2, -metrics.height(), box_width, metrics.height()))))
        if seg.label:
            text = QPainterPath()
            text.addText(-width / 2, -metrics.descent(), font, seg.label)
            fills.addPath(transform.map(text))
        if tag and seg is lay.segments[0]:
            _add_tag(strokes, fills, tag, style, transform, -box_width / 2, -metrics.height() / 2, -1)

    angle_boxes: list[QPolygonF | None] = []
    for arc in lay.angles:
        if not arc.label:
            angle_boxes.append(None)
            continue
        if arc.radius > 0:
            rect = QRectF(arc.center[0] - arc.radius, arc.center[1] - arc.radius, 2 * arc.radius, 2 * arc.radius)
            strokes.arcMoveTo(rect, -arc.start)  # Qt arcs run counter-clockwise on screen
            strokes.arcTo(rect, -arc.start, -arc.span)
        transform = QTransform()
        transform.translate(*arc.text_center)
        transform.rotate(arc.text_angle)
        width = metrics.horizontalAdvance(arc.label)
        height = metrics.height()
        angle_boxes.append(transform.map(QPolygonF(QRectF(-width / 2, -height / 2, width, height))))
        text = QPainterPath()
        text.addText(-width / 2, (metrics.ascent() - metrics.descent()) / 2, font, arc.label)
        fills.addPath(transform.map(text))
    return DimensionPaths(strokes, fills, boxes, lay, angle_boxes)


def paint_dimension(painter: QPainter, paths: DimensionPaths, style: Style) -> None:
    color = QColor(style.color)
    halo = halo_color(color)
    h = halo_width(style.line_width)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if style.outline:
        # Halo first, underneath everything, so lines and text stay readable on any background.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(halo, style.line_width + 2 * h, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
        painter.drawPath(paths.strokes)
        painter.setPen(QPen(halo, 2 * h, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(paths.fills)
    painter.setPen(QPen(color, style.line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin))
    painter.drawPath(paths.strokes)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(paths.fills)
    painter.restore()


def export_image(image: QImage, doc: Document) -> QImage:
    out = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(out)
    tags = annotation_ids(doc.dimensions) if doc.style.ids else [""] * len(doc.dimensions)
    for dim, tag in zip(doc.dimensions, tags):
        if kind_of(dim) not in doc.style.hidden:
            style = doc.style.for_kind(kind_of(dim))
            paint_dimension(painter, build_paths(dim, style, tag), style)
    painter.end()
    return out
