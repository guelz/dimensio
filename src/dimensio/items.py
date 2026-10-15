"""Graphics items: one per dimension, its point handles, and the drawing preview."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem

from .model import Dimension, Style
from .render import DimensionPaths, build_paths, halo_width, paint_dimension

if TYPE_CHECKING:
    from .canvas import Canvas

HANDLE_RADIUS = 6  # screen pixels


class PathsItem(QGraphicsItem):
    """Draws one dimension exactly like the export does. Used directly for the drawing preview."""

    def __init__(self, dim: Dimension, style: Style) -> None:
        super().__init__()
        self._dim = dim
        self._style = style
        self._paths = build_paths(dim, style)
        self._margin = 0.0

    @property
    def dim(self) -> Dimension:
        return self._dim

    @property
    def paths(self) -> DimensionPaths:
        return self._paths

    def set_dimension(self, dim: Dimension, style: Style | None = None) -> None:
        self.prepareGeometryChange()
        self._dim = dim
        if style is not None:
            self._style = style
        self._paths = build_paths(dim, self._style)
        self.update()

    def boundingRect(self) -> QRectF:
        rect = self._paths.strokes.boundingRect().united(self._paths.fills.boundingRect())
        for box in self._paths.label_boxes:
            rect = rect.united(box.boundingRect())
        m = self._style.line_width / 2 + halo_width(self._style.line_width) + self._margin
        return rect.adjusted(-m, -m, m, m)

    def paint(self, painter, option, widget=None) -> None:
        paint_dimension(painter, self._paths, self._style)


class DimensionItem(PathsItem):
    """An editable dimension: click to select, drag the line to move it, drag handles to move points."""

    def __init__(self, canvas: Canvas, dim: Dimension, style: Style) -> None:
        super().__init__(dim, style)
        self.canvas = canvas
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(1)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_from: QPointF | None = None
        self._drag_start: Dimension | None = None
        self.handles = [HandleItem(self, i) for i in range(len(dim.points))]
        self._place_handles()

    def set_dimension(self, dim: Dimension, style: Style | None = None) -> None:
        super().set_dimension(dim, style)
        self._place_handles()

    def _place_handles(self) -> None:
        for handle, (x, y) in zip(self.handles, self._dim.points):
            handle.setPos(x, y)

    def set_hit_tolerance(self, tolerance: float) -> None:
        """Scene-unit grab distance around the line; the canvas updates it on every zoom."""
        self.prepareGeometryChange()
        self._margin = tolerance

    def shape(self) -> QPainterPath:
        line = QPainterPath()
        for seg in self._paths.layout.segments:
            line.moveTo(*seg.start)
            line.lineTo(*seg.end)
        stroker = QPainterPathStroker()
        w = self._style.line_width
        stroker.setWidth(max(w + 2 * halo_width(w), 2 * self._margin))
        shape = stroker.createStroke(line)
        for box in self._paths.label_boxes:
            outline = QPainterPath()
            outline.addPolygon(box)
            outline.closeSubpath()
            shape = shape.united(outline)
        return shape

    def segment_at(self, pos: QPointF) -> int:
        for i, box in enumerate(self._paths.label_boxes):
            if box.containsPoint(pos, Qt.FillRule.OddEvenFill):
                return i
        segments = self._paths.layout.segments

        def distance(i: int) -> float:
            s = segments[i]
            return math.hypot(pos.x() - (s.start[0] + s.end[0]) / 2, pos.y() - (s.start[1] + s.end[1]) / 2)

        return min(range(len(segments)), key=distance)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            for handle in self.handles:
                handle.setVisible(bool(value))
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)  # selection
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.scenePos()
            self._drag_start = self._dim
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is None or self._drag_start is None:
            return
        delta = event.scenePos() - self._drag_from
        ox, oy = self._drag_start.offset
        self.set_dimension(replace(self._drag_start, offset=(ox + delta.x(), oy + delta.y())))

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._drag_start is not None:
            start, self._drag_from, self._drag_start = self._drag_start, None, None
            self.canvas.commit_edit(self, start, "Move dimension line")

    def mouseDoubleClickEvent(self, event) -> None:
        self.canvas.edit_labels(self, self.segment_at(event.scenePos()))
        event.accept()


class HandleItem(QGraphicsEllipseItem):
    """Round grip on a measured point. Visible while its dimension is selected; constant screen size."""

    def __init__(self, parent: DimensionItem, index: int) -> None:
        r = HANDLE_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, parent)
        self.index = index
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setPen(QPen(QColor("black"), 1.5))
        self.setBrush(QColor("white"))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setVisible(False)
        self._start: Dimension | None = None

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._start = self.parentItem().dim
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._start is None:
            return
        points = list(self._start.points)
        p = event.scenePos()
        points[self.index] = (p.x(), p.y())
        self.parentItem().set_dimension(replace(self._start, points=tuple(points)))

    def mouseReleaseEvent(self, event) -> None:
        if self._start is None:
            return
        start, self._start = self._start, None
        parent = self.parentItem()
        parent.canvas.commit_edit(parent, start, "Move point")
