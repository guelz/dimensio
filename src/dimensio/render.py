"""Painting dimensions with QPainter. Shared by the canvas and the export so both look identical."""

from __future__ import annotations

from dataclasses import dataclass
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

from .geometry import Layout, layout
from .model import Dimension, Document, Style

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
    layout: Layout


def build_paths(dim: Dimension, style: Style) -> DimensionPaths:
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
    return DimensionPaths(strokes, fills, boxes, lay)


def paint_dimension(painter: QPainter, paths: DimensionPaths, style: Style) -> None:
    color = QColor(style.color)
    halo = halo_color(color)
    h = halo_width(style.line_width)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
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
