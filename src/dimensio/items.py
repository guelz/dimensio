"""Graphics items: one per dimension or level marker, their point handles, and the drawing preview."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QGraphicsEllipseItem, QGraphicsItem

from .model import Annotation, Circle, Dimension, Level, Line, Note, Point, Style, kind_of
from .render import DimensionPaths, build_paths, halo_width, paint_dimension

if TYPE_CHECKING:
    from .canvas import Canvas

HANDLE_RADIUS = 6  # screen pixels
HIGHLIGHT_WIDTH = 10  # screen pixels; marks the line or arc whose label is being typed


@dataclass(frozen=True)
class FieldInfo:
    """What the label editor needs to know about one text field of an item."""

    prefix: str  # symbol shown in front of the text: ↔ length, ∠ angle, ▽ level
    placeholder: str
    anchor: Point  # scene position of the label
    centered: bool  # True: anchor is the label's centre; False: its bottom-centre
    area: QRectF  # scene area to keep visible while editing


class PathsItem(QGraphicsItem):
    """Draws one annotation exactly like the export does. Used directly for the drawing preview."""

    def __init__(self, dim: Annotation, style: Style) -> None:
        super().__init__()
        self._dim = dim
        self._doc_style = style
        self._style = style.for_kind(kind_of(dim))  # this item's layer
        self.tag = ""  # name drawn next to the first label when IDs are shown
        self._paths = build_paths(dim, self._style)
        self._margin = 0.0

    @property
    def dim(self) -> Annotation:
        return self._dim

    @property
    def paths(self) -> DimensionPaths:
        return self._paths

    def set_dimension(self, dim: Annotation, style: Style | None = None) -> None:
        self.prepareGeometryChange()
        self._dim = dim
        if style is not None:
            self._doc_style = style
        self._style = self._doc_style.for_kind(kind_of(dim))
        self._paths = build_paths(dim, self._style, self.tag)
        self.update()

    def set_tag(self, tag: str) -> None:
        if tag != self.tag:
            self.tag = tag
            self.set_dimension(self._dim)

    def _boxes(self) -> list:
        return self._paths.label_boxes + [b for b in self._paths.angle_boxes if b is not None]

    def boundingRect(self) -> QRectF:
        rect = self._paths.strokes.boundingRect().united(self._paths.fills.boundingRect())
        for box in self._boxes():
            rect = rect.united(box.boundingRect())
        m = self._style.line_width / 2 + halo_width(self._style.line_width) + self._margin
        return rect.adjusted(-m, -m, m, m)

    def paint(self, painter, option, widget=None) -> None:
        paint_dimension(painter, self._paths, self._style)


class EditableItem(PathsItem):
    """Shared behaviour: click to select, drag to move the drawing off its points, drag handles to
    move the points, double-click a label to edit it. Subclasses describe their geometry."""

    def __init__(self, canvas: Canvas, dim: Annotation, style: Style) -> None:
        super().__init__(dim, style)
        self.canvas = canvas
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(1)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_from: QPointF | None = None
        self._drag_start: Annotation | None = None
        self._highlight: int | None = None
        self.handles = [HandleItem(self, i) for i in range(len(self.handle_points()))]
        self._place_handles()

    # ----- geometry each subclass provides -----

    def handle_points(self) -> tuple[Point, ...]:
        raise NotImplementedError

    def with_point(self, index: int, point: Point) -> Annotation:
        raise NotImplementedError

    def _grab_lines(self) -> QPainterPath:
        """Centre lines that grab the item (besides its label boxes)."""
        raise NotImplementedError

    def field_at(self, pos: QPointF) -> int:
        raise NotImplementedError

    def field_info(self, field: int) -> FieldInfo:
        raise NotImplementedError

    def _highlight_path(self, field: int) -> QPainterPath | None:
        return None

    def dragged(self, start: Annotation, dx: float, dy: float) -> Annotation:
        """The item after dragging its body by (dx, dy): by default the drawing moves off its points."""
        ox, oy = start.offset
        return replace(start, offset=(ox + dx, oy + dy))

    # ----- shared behaviour -----

    def set_active(self, active: bool) -> None:
        """Only items of the active tool's kind react to the mouse; the others are click-through."""
        self.setAcceptedMouseButtons(Qt.MouseButton.AllButtons if active else Qt.MouseButton.NoButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, active)
        if active:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setSelected(False)
            self.unsetCursor()

    def is_active(self) -> bool:
        return self.acceptedMouseButtons() != Qt.MouseButton.NoButton

    def set_dimension(self, dim: Annotation, style: Style | None = None) -> None:
        super().set_dimension(dim, style)
        self._place_handles()

    def _place_handles(self) -> None:
        for handle, (x, y) in zip(self.handles, self.handle_points()):
            handle.setPos(x, y)

    def highlighted_field(self) -> int | None:
        return self._highlight

    def set_highlight(self, field: int | None) -> None:
        """Mark the part whose label is being edited. Screen only, never exported."""
        self._highlight = field
        self.update()

    def paint(self, painter, option, widget=None) -> None:
        path = self._highlight_path(self._highlight) if self._highlight is not None else None
        if path is not None:
            accent = QApplication.palette().color(QPalette.ColorRole.Highlight)
            accent.setAlpha(140)
            pen = QPen(accent, HIGHLIGHT_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPath(path)
        super().paint(painter, option, widget)

    def set_hit_tolerance(self, tolerance: float) -> None:
        """Scene-unit grab distance around the lines; the canvas updates it on every zoom."""
        self.prepareGeometryChange()
        self._margin = tolerance

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        w = self._style.line_width
        stroker.setWidth(max(w + 2 * halo_width(w), 2 * self._margin))
        shape = stroker.createStroke(self._grab_lines())
        for box in self._boxes():
            outline = QPainterPath()
            outline.addPolygon(box)
            outline.closeSubpath()
            shape = shape.united(outline)
        return shape

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
        self.set_dimension(self.dragged(self._drag_start, delta.x(), delta.y()))

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._drag_start is not None:
            start, self._drag_from, self._drag_start = self._drag_start, None, None
            self.canvas.commit_edit(self, start, "Move")

    def mouseDoubleClickEvent(self, event) -> None:
        self.canvas.edit_labels(self, self.field_at(event.scenePos()))
        event.accept()


def _box_center(box) -> Point:
    c = box.boundingRect().center()
    return (c.x(), c.y())


class DimensionItem(EditableItem):
    """A dimension or chain. Fields walk along the chain: 2*i = length i, 2*j+1 = angle at corner j+1."""

    def handle_points(self) -> tuple[Point, ...]:
        return self._dim.points

    def with_point(self, index: int, point: Point) -> Dimension:
        points = list(self._dim.points)
        points[index] = point
        return replace(self._dim, points=tuple(points))

    def _grab_lines(self) -> QPainterPath:
        line = QPainterPath()
        for seg in self._paths.layout.segments:
            line.moveTo(*seg.start)
            line.lineTo(*seg.end)
        return line

    def field_at(self, pos: QPointF) -> int:
        for i, box in enumerate(self._paths.label_boxes):
            if box.containsPoint(pos, Qt.FillRule.OddEvenFill):
                return 2 * i
        for j, box in enumerate(self._paths.angle_boxes):
            if box is not None and box.containsPoint(pos, Qt.FillRule.OddEvenFill):
                return 2 * j + 1
        segments = self._paths.layout.segments

        def distance(i: int) -> float:
            s = segments[i]
            return math.hypot(pos.x() - (s.start[0] + s.end[0]) / 2, pos.y() - (s.start[1] + s.end[1]) / 2)

        return 2 * min(range(len(segments)), key=distance)

    def field_info(self, field: int) -> FieldInfo:
        layout = self._paths.layout
        if field % 2 == 0:
            seg = layout.segments[field // 2]
            area = QRectF(QPointF(*seg.start), QPointF(*seg.end)).normalized()
            return FieldInfo("↔", "label", seg.text_anchor, False, area)
        arc = layout.angles[field // 2]
        area = QRectF(QPointF(*arc.center), QPointF(*arc.text_center)).normalized()
        return FieldInfo("∠", "angle (optional)", arc.text_center, True, area)

    def _highlight_path(self, field: int) -> QPainterPath:
        path = QPainterPath()
        layout = self._paths.layout
        if field % 2 == 0:
            seg = layout.segments[field // 2]
            path.moveTo(*seg.start)
            path.lineTo(*seg.end)
        else:
            arc = layout.angles[field // 2]
            rect = QRectF(arc.center[0] - arc.radius, arc.center[1] - arc.radius, 2 * arc.radius, 2 * arc.radius)
            path.arcMoveTo(rect, -arc.start)
            path.arcTo(rect, -arc.start, -arc.span)
        return path


class LevelItem(EditableItem):
    """A level marker: one point (handle), one label (field 0)."""

    def handle_points(self) -> tuple[Point, ...]:
        return (self._dim.point,)

    def with_point(self, index: int, point: Point) -> Level:
        return replace(self._dim, point=point)

    def _grab_lines(self) -> QPainterPath:
        return self._paths.strokes

    def _boxes(self) -> list:
        tip, left, right = self._paths.layout.triangle
        return super()._boxes() + [QPolygonF([QPointF(*tip), QPointF(*left), QPointF(*right)])]  # grab inside too

    def field_at(self, pos: QPointF) -> int:
        return 0

    def field_info(self, field: int) -> FieldInfo:
        box = self._paths.label_boxes[0]
        return FieldInfo("▽", "level, e.g. ±0.00", _box_center(box), True, box.boundingRect())

    def _highlight_path(self, field: int) -> QPainterPath:
        tip, left, right = self._paths.layout.triangle
        path = QPainterPath()
        path.moveTo(*tip)
        path.lineTo(*left)
        path.lineTo(*right)
        path.closeSubpath()
        return path


class LineItem(EditableItem):
    """A plain polyline: dragging moves the whole line, handles move single points, no text."""

    def handle_points(self) -> tuple[Point, ...]:
        return self._dim.points

    def with_point(self, index: int, point: Point) -> Line:
        points = list(self._dim.points)
        points[index] = point
        return Line(tuple(points))

    def dragged(self, start: Line, dx: float, dy: float) -> Line:
        return Line(tuple((x + dx, y + dy) for x, y in start.points))

    def _grab_lines(self) -> QPainterPath:
        return self._paths.strokes

    def field_at(self, pos: QPointF) -> int:
        return 0

    def mouseDoubleClickEvent(self, event) -> None:
        event.accept()  # nothing to edit


class NoteItem(EditableItem):
    """Text with a leader and an arrowhead: dragging moves the text, the handle moves the spot."""

    def handle_points(self) -> tuple[Point, ...]:
        return (self._dim.point,)

    def with_point(self, index: int, point: Point) -> Note:
        return replace(self._dim, point=point)

    def _grab_lines(self) -> QPainterPath:
        return self._paths.strokes

    def field_at(self, pos: QPointF) -> int:
        return 0

    def field_info(self, field: int) -> FieldInfo:
        box = self._paths.label_boxes[0]
        return FieldInfo("✎", "note", _box_center(box), True, box.boundingRect())

    def _highlight_path(self, field: int) -> QPainterPath:
        return self._paths.strokes


class CircleItem(EditableItem):
    """Dragging or the centre handle moves the circle; the edge handle sets radius and line direction."""

    def handle_points(self) -> tuple[Point, ...]:
        return (self._dim.center, self._dim.edge)

    def with_point(self, index: int, point: Point) -> Circle:
        if index == 1:
            return replace(self._dim, edge=point)
        return self.dragged(self._dim, point[0] - self._dim.center[0], point[1] - self._dim.center[1])

    def dragged(self, start: Circle, dx: float, dy: float) -> Circle:
        (cx, cy), (ex, ey) = start.center, start.edge
        return replace(start, center=(cx + dx, cy + dy), edge=(ex + dx, ey + dy))

    def _grab_lines(self) -> QPainterPath:
        return self._paths.strokes

    def field_at(self, pos: QPointF) -> int:
        return 0

    def field_info(self, field: int) -> FieldInfo:
        lay = self._paths.layout
        r = lay.radius
        area = QRectF(lay.center[0] - r, lay.center[1] - r, 2 * r, 2 * r)
        return FieldInfo("Ø", "Ø 40 or R 20 (optional)", lay.text_anchor, False, area)

    def _highlight_path(self, field: int) -> QPainterPath:
        lay = self._paths.layout
        path = QPainterPath()
        path.addEllipse(QPointF(*lay.center), lay.radius, lay.radius)
        return path


_ITEM_TYPES = {Level: LevelItem, Line: LineItem, Note: NoteItem, Circle: CircleItem}


def make_item(canvas: Canvas, dim: Annotation, style: Style) -> EditableItem:
    return _ITEM_TYPES.get(type(dim), DimensionItem)(canvas, dim, style)


class HandleItem(QGraphicsEllipseItem):
    """Round grip on a measured point. Visible while its item is selected; constant screen size."""

    def __init__(self, parent: EditableItem, index: int) -> None:
        r = HANDLE_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, parent)
        self.index = index
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setPen(QPen(QColor("black"), 1.5))
        self.setBrush(QColor("white"))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setVisible(False)
        self._start: Annotation | None = None

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._start = self.parentItem().dim
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._start is None:
            return
        parent = self.parentItem()
        p = event.scenePos()
        point = parent.canvas.snap_point((p.x(), p.y()), event.modifiers(), exclude=parent)
        parent.set_dimension(parent.with_point(self.index, point))

    def mouseReleaseEvent(self, event) -> None:
        if self._start is None:
            return
        start, self._start = self._start, None
        parent = self.parentItem()
        parent.canvas.hide_snap_marker()
        parent.canvas.commit_edit(parent, start, "Move point")


class SnapMarker(QGraphicsItem):
    """Shows where the next point will land: a ring on a point, a cross on a line or circle."""

    SIZE = 7  # screen pixels

    def __init__(self) -> None:
        super().__init__()
        self.kind = "point"
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(10)

    def boundingRect(self) -> QRectF:
        r = self.SIZE + 2
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(self, painter, option, widget=None) -> None:
        pen = QPen(QApplication.palette().color(QPalette.ColorRole.Highlight), 2)
        painter.setPen(pen)
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        r = self.SIZE
        if self.kind == "point":
            painter.drawEllipse(QPointF(0, 0), r, r)
        else:
            painter.drawLine(QPointF(-r, -r), QPointF(r, r))
            painter.drawLine(QPointF(-r, r), QPointF(r, -r))
