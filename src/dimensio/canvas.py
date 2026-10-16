"""The drawing canvas: shows the image and its dimensions and handles mouse and keyboard input."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPixmap, QUndoStack
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QLineEdit, QWidget

from .commands import AddDimension, ChangeDimension, ChangeStyle, RemoveDimension
from .items import EditableItem, HandleItem, PathsItem, make_item
from .model import Annotation, Dimension, Document, Level, Line, Note, Point, Style, annotation_ids, kind_of
from .render import export_image

HIT_TOLERANCE = 6  # screen pixels around a dimension line that still grab it
MIN_POINT_DISTANCE = 3  # screen pixels; a closer click is ignored
ZOOM_STEP = 1.25
EDITOR_WIDTH = 180
EMPTY_HINT = "Open an image (Ctrl+O), drop one here, or paste one (Ctrl+V)"


class LabelEditor(QLineEdit):
    """Inline field for one segment label. Enter/Tab: next segment, Shift+Tab: previous, Esc: cancel."""

    step = Signal(int)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._prefix = ""

    def prefix(self) -> str:
        return self._prefix

    def set_prefix(self, prefix: str) -> None:
        """A symbol in front of the text saying what the field is: ↔ length, ∠ angle."""
        self._prefix = prefix
        self.setTextMargins(self.fontMetrics().horizontalAdvance(prefix) + 6, 0, 0, 0)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(self.rect().adjusted(6, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._prefix)
        painter.end()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.step.emit(1)
                return True
            if key == Qt.Key.Key_Backtab:
                self.step.emit(-1)
                return True
            if key == Qt.Key.Key_Escape:
                self.cancelled.emit()
                return True
        return super().event(event)


@dataclass
class _LabelEdit:
    item: EditableItem
    original: Annotation
    is_new: bool
    field: int  # chains: 2*i = length of segment i, 2*j+1 = angle at corner j+1; levels: 0


def _field_count(dim: Annotation) -> int:
    if isinstance(dim, Line):
        return 0
    return 1 if isinstance(dim, (Level, Note)) else len(dim.labels) + len(dim.angles)


def _field_text(dim: Annotation, field: int) -> str:
    if isinstance(dim, (Level, Note)):
        return dim.label
    return dim.labels[field // 2] if field % 2 == 0 else dim.angles[field // 2]


def _with_field(dim: Annotation, field: int, text: str) -> Annotation:
    if isinstance(dim, (Level, Note)):
        return replace(dim, label=text)
    if field % 2 == 0:
        labels = list(dim.labels)
        labels[field // 2] = text
        return replace(dim, labels=tuple(labels))
    angles = list(dim.angles)
    angles[field // 2] = text
    return replace(dim, angles=tuple(angles))


class Canvas(QGraphicsView):
    style_changed = Signal(object)  # Style, after every style change including undo

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setMouseTracking(True)
        self.setBackgroundBrush(QColor(48, 48, 48))
        self.undo = QUndoStack(self)
        self.doc: Document | None = None
        self.image: QImage | None = None
        self._items: list[EditableItem] = []
        self._auto_fit = True
        self._pan_from: QPointF | None = None
        self._space = False
        self._draft: list[Point] = []
        self._cursor: Point | None = None
        self._preview: PathsItem | None = None
        self._editor: LabelEditor | None = None
        self._edit: _LabelEdit | None = None
        self.tool = "dimension"  # or "level", "line", "note"

    # ----- document -----

    def set_document(self, image: QImage, doc: Document) -> None:
        self.finish_interaction()
        self.scene().clear()
        self._items = []
        self.image, self.doc = image, doc
        self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(QRectF(image.rect()))
        for dim in doc.dimensions:
            item = make_item(self, dim, doc.style)
            self._activate(item)
            self.scene().addItem(item)
            self._items.append(item)
        self._refresh_tags()
        self.undo.clear()
        self.fit()
        self.style_changed.emit(doc.style)

    def set_tool(self, tool: str) -> None:
        """'dimension' / 'line': click, (Ctrl+)click (, type). 'level' / 'note': one click, then type."""
        self.finish_interaction()
        self.tool = tool
        for item in self._items:
            self._activate(item)
        if self.doc is not None and tool in self.doc.style.hidden:  # never draw on an invisible layer
            self.set_style(replace(self.doc.style, hidden=tuple(k for k in self.doc.style.hidden if k != tool)))

    def _activate(self, item: EditableItem) -> None:
        item.set_active(kind_of(item.dim) == self.tool)
        item.setVisible(kind_of(item.dim) not in self.doc.style.hidden)

    def has_image(self) -> bool:
        return self.image is not None

    def dimension_items(self) -> list[EditableItem]:
        return list(self._items)

    def set_style(self, style: Style) -> None:
        if self.doc is not None and style != self.doc.style:
            self.undo.push(ChangeStyle(self, self.doc.style, style))

    def flattened(self) -> QImage:
        self.finish_interaction()
        return export_image(self.image, self.doc)

    # ----- DocumentHost: called by undo commands and the label editor -----

    def insert_dimension(self, index: int, dim: Annotation) -> None:
        self.doc.dimensions.insert(index, dim)
        item = make_item(self, dim, self.doc.style)
        item.set_hit_tolerance(self._scene_tolerance())
        self._activate(item)
        self.scene().addItem(item)
        self._items.insert(index, item)
        self._refresh_tags()

    def remove_dimension(self, index: int) -> None:
        del self.doc.dimensions[index]
        self.scene().removeItem(self._items.pop(index))
        self._refresh_tags()

    def replace_dimension(self, index: int, dim: Annotation) -> None:
        self.doc.dimensions[index] = dim
        self._items[index].set_dimension(dim)

    def apply_style(self, style: Style) -> None:
        self.doc.style = style
        for item in self._items:
            item.set_dimension(item.dim, style)
            self._activate(item)
        self._refresh_tags()
        self.style_changed.emit(style)

    def _refresh_tags(self) -> None:
        """IDs follow the drawing order, so every insert, delete or style change re-tags."""
        names = annotation_ids(self.doc.dimensions) if self.doc.style.ids else [""] * len(self._items)
        for item, name in zip(self._items, names):
            item.set_tag(name)

    def commit_edit(self, item: EditableItem, before: Annotation, text: str) -> None:
        """Record a finished drag of `item` (already showing its new state) as one undo step."""
        if item.dim != before:
            self.undo.push(ChangeDimension(self, self._items.index(item), before, item.dim, text))

    # ----- view -----

    def fit(self) -> None:
        self._auto_fit = True
        if self.image is not None:
            self.resetTransform()
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._view_changed()

    def zoom(self, factor: float) -> None:
        self._auto_fit = False
        self.scale(factor, factor)
        self._view_changed()

    def _scene_tolerance(self) -> float:
        return HIT_TOLERANCE / max(self.transform().m11(), 1e-6)

    def _view_changed(self) -> None:
        tolerance = self._scene_tolerance()
        for item in self._items:
            item.set_hit_tolerance(tolerance)
        self._place_editor()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit()
        else:
            self._place_editor()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._place_editor()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            if steps:
                self.zoom(ZOOM_STEP**steps)
            event.accept()
        else:
            super().wheelEvent(event)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if self.image is None:
            painter.save()
            painter.resetTransform()
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, EMPTY_HINT)
            painter.restore()

    # ----- mouse -----

    def mousePressEvent(self, event) -> None:
        if self._editor is not None:
            self._close_editor(commit=True)  # clicking elsewhere confirms the label
            event.accept()
            return
        button = event.button()
        if button == Qt.MouseButton.MiddleButton or (button == Qt.MouseButton.LeftButton and self._space):
            self._pan_from = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if button != Qt.MouseButton.LeftButton or self.image is None:
            super().mousePressEvent(event)
            return
        if not self._draft and self._grabbable_item_at(event) is not None:
            super().mousePressEvent(event)
            return
        self.scene().clearSelection()
        if self.tool in ("level", "note"):
            point = self._event_point(event)
            s = self.doc.style.text_size
            item = Level(point) if self.tool == "level" else Note(point, "", (1.5 * s, -1.5 * s))
            self.insert_dimension(len(self._items), item)
            self._start_label_edit(self._items[-1], 0, is_new=True)
        else:
            self._add_draft_point(self._event_point(event), event.modifiers())
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._draft:
            self.mousePressEvent(event)  # fast clicking while drawing still places points
        else:
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pan_from is not None:
            delta = event.position() - self._pan_from
            self._pan_from = event.position()
            h, v = self.horizontalScrollBar(), self.verticalScrollBar()
            h.setValue(h.value() - round(delta.x()))
            v.setValue(v.value() - round(delta.y()))
            event.accept()
            return
        if self._draft:
            self._cursor = self._event_point(event)
            self._update_preview()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pan_from is not None and event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._pan_from = None
            if self._space:
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _event_point(self, event) -> Point:
        p = self.mapToScene(event.position().toPoint())
        r = self.sceneRect()
        x = min(max(p.x(), r.left()), r.right())
        y = min(max(p.y(), r.top()), r.bottom())
        if self._draft and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            px, py = self._draft[-1]
            if abs(x - px) >= abs(y - py):
                y = py
            else:
                x = px
        return (x, y)

    def _grabbable_item_at(self, event):
        for item in self.items(event.position().toPoint()):
            owner = item.parentItem() if isinstance(item, HandleItem) else item
            if isinstance(owner, EditableItem) and item.isVisible() and owner.is_active():
                return item
        return None

    def _screen_distance(self, a: Point, b: Point) -> float:
        pa, pb = self.mapFromScene(QPointF(*a)), self.mapFromScene(QPointF(*b))
        return math.hypot(pa.x() - pb.x(), pa.y() - pb.y())

    # ----- drawing -----

    def is_drawing(self) -> bool:
        return bool(self._draft)

    def _add_draft_point(self, point: Point, modifiers) -> None:
        if self._draft and self._screen_distance(self._draft[-1], point) < MIN_POINT_DISTANCE:
            return
        self._draft.append(point)
        self._cursor = None
        if len(self._draft) >= 2 and not (modifiers & Qt.KeyboardModifier.ControlModifier):
            self._finish_draft()
        else:
            self._update_preview()

    def _update_preview(self) -> None:
        points = list(self._draft) + ([self._cursor] if self._cursor is not None else [])
        if len(points) < 2:
            self._remove_preview()
            return
        dim = Line(tuple(points)) if self.tool == "line" else Dimension.new(points)
        if self._preview is None:
            self._preview = PathsItem(dim, self.doc.style)
            self._preview.setZValue(3)
            self.scene().addItem(self._preview)
        else:
            self._preview.set_dimension(dim)

    def _remove_preview(self) -> None:
        if self._preview is not None:
            self.scene().removeItem(self._preview)
            self._preview = None

    def _cancel_draft(self) -> None:
        self._draft = []
        self._cursor = None
        self._remove_preview()

    def _finish_draft(self) -> None:
        points = self._draft
        self._cancel_draft()
        if self.tool == "line":  # nothing to label
            self.undo.push(AddDimension(self, len(self._items), Line(tuple(points))))
            return
        # The new dimension is shown at once but only becomes an undo step when its labels are confirmed.
        self.insert_dimension(len(self._items), Dimension.new(points))
        self._start_label_edit(self._items[-1], 0, is_new=True)

    def finish_interaction(self) -> None:
        """Drop an unfinished drawing and confirm an open label editor."""
        self._cancel_draft()
        self.commit_label_editor()

    def commit_label_editor(self) -> None:
        self._close_editor(commit=True)

    # ----- keyboard -----

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if self._draft:
            if key == Qt.Key.Key_Escape:
                self._cancel_draft()
                return
            if key == Qt.Key.Key_Backspace:
                self._draft.pop()
                if self._draft:
                    self._update_preview()
                else:
                    self._cancel_draft()
                return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()
            return
        if key == Qt.Key.Key_Escape:
            self.scene().clearSelection()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        # A Space release that happens elsewhere (Alt+Tab, toolbar) must not leave pan mode stuck on.
        self._space = False
        self._pan_from = None
        self.viewport().unsetCursor()
        super().focusOutEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = False
            self.viewport().unsetCursor()
            return
        super().keyReleaseEvent(event)

    def _delete_selected(self) -> None:
        self.commit_label_editor()
        indexes = sorted((i for i, item in enumerate(self._items) if item.isSelected()), reverse=True)
        if not indexes:
            return
        self.undo.beginMacro("Delete dimension")
        for i in indexes:
            self.undo.push(RemoveDimension(self, i, self._items[i].dim))
        self.undo.endMacro()

    # ----- label editing -----

    def label_editor(self) -> LabelEditor | None:
        return self._editor

    def edit_labels(self, item: EditableItem, field: int) -> None:
        if _field_count(item.dim):
            self._start_label_edit(item, field, is_new=False)

    def _start_label_edit(self, item: EditableItem, field: int, is_new: bool) -> None:
        self._close_editor(commit=True)
        self._edit = _LabelEdit(item, item.dim, is_new, field)
        editor = LabelEditor(self.viewport())
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.textEdited.connect(self._on_label_edited)
        editor.step.connect(self._on_label_step)
        editor.cancelled.connect(lambda: self._close_editor(commit=False))
        self._editor = editor
        self._show_label_segment()
        editor.show()
        editor.setFocus()

    def _show_label_segment(self) -> None:
        edit = self._edit
        info = edit.item.field_info(edit.field)
        self.ensureVisible(info.area, 60, 60)
        self._editor.setPlaceholderText(info.placeholder)
        self._editor.set_prefix(info.prefix)
        edit.item.set_highlight(edit.field)
        self._editor.setText(_field_text(edit.item.dim, edit.field))
        self._editor.selectAll()
        self._place_editor()

    def _place_editor(self) -> None:
        if self._editor is None:
            return
        info = self._edit.item.field_info(self._edit.field)
        height = self._editor.sizeHint().height()
        anchor = self.mapFromScene(QPointF(*info.anchor))
        top = anchor.y() - (height // 2 if info.centered else height)  # bottom-centred labels sit on their line
        self._editor.setGeometry(anchor.x() - EDITOR_WIDTH // 2, top, EDITOR_WIDTH, height)

    def _on_label_edited(self, text: str) -> None:
        item = self._edit.item
        item.set_dimension(_with_field(item.dim, self._edit.field, text))

    def _on_label_step(self, step: int) -> None:
        nxt = self._edit.field + step
        if nxt >= _field_count(self._edit.item.dim):
            self._close_editor(commit=True)
            return
        self._edit.field = max(0, nxt)
        self._show_label_segment()

    def _close_editor(self, commit: bool) -> None:
        if self._editor is None:
            return
        editor, edit = self._editor, self._edit
        self._editor = self._edit = None
        editor.hide()
        editor.deleteLater()
        edit.item.set_highlight(None)
        self.setFocus()
        index = self._items.index(edit.item)
        final = edit.item.dim
        if edit.is_new:
            self.remove_dimension(index)
            if isinstance(final, Note) and not final.label.strip():
                return  # a note without text says nothing
            if commit:
                self.undo.push(AddDimension(self, index, final))
        elif not commit:
            self.replace_dimension(index, edit.original)
        elif final != edit.original:
            self.undo.push(ChangeDimension(self, index, edit.original, final, "Edit label"))
