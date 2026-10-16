"""Painting dimensions with QPainter. Shared by the canvas and the export so both look identical."""

from __future__ import annotations

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

from .geometry import Layout, LevelLayout, layout, level_layout
from .model import Annotation, Dimension, Document, Level, Style

ALLOCATION_LIMIT_MB = 1024  # Qt's default of 256 MB refuses photos above ~64 MP


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
    layout: Layout | LevelLayout
    angle_boxes: list[QPolygonF | None] = field(default_factory=list)  # per corner; None = no angle text


def build_paths(item: Annotation, style: Style) -> DimensionPaths:
    if isinstance(item, Level):
        return _level_paths(item, style)
    return _dimension_paths(item, style)


def _level_paths(level: Level, style: Style) -> DimensionPaths:
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
    return DimensionPaths(strokes, fills, [box], lay)


def _dimension_paths(dim: Dimension, style: Style) -> DimensionPaths:
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
    for dim in doc.dimensions:
        paint_dimension(painter, build_paths(dim, doc.style), doc.style)
    painter.end()
    return out
