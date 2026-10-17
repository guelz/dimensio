import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from dimensio.canvas import Canvas
from dimensio.model import Dimension, Document, Style

LEFT = Qt.MouseButton.LeftButton
NO_BUTTON = Qt.MouseButton.NoButton
NO_MOD = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
STYLE = Style(4, 20, "#FF0000")


def blank(width=400, height=300):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    return image


@pytest.fixture
def canvas(qtbot):
    c = Canvas()
    c.resize(800, 600)
    qtbot.addWidget(c)
    c.show()
    qtbot.waitExposed(c)
    c.set_document(blank(), Document(style=STYLE))
    return c


def with_dimension(canvas, dim):
    canvas.set_document(blank(), Document(style=STYLE, dimensions=[dim]))


def view_pos(canvas, x, y) -> QPoint:
    return canvas.mapFromScene(QPointF(x, y))


def send(canvas, etype, pos, button, buttons, mods=NO_MOD):
    viewport = canvas.viewport()
    event = QMouseEvent(etype, QPointF(pos), QPointF(viewport.mapToGlobal(pos)), button, buttons, mods)
    QApplication.sendEvent(viewport, event)


def click(canvas, x, y, mods=NO_MOD):
    p = view_pos(canvas, x, y)
    send(canvas, QEvent.Type.MouseButtonPress, p, LEFT, LEFT, mods)
    send(canvas, QEvent.Type.MouseButtonRelease, p, LEFT, NO_BUTTON, mods)


def double_click(canvas, x, y):
    p = view_pos(canvas, x, y)
    send(canvas, QEvent.Type.MouseButtonPress, p, LEFT, LEFT)
    send(canvas, QEvent.Type.MouseButtonRelease, p, LEFT, NO_BUTTON)
    send(canvas, QEvent.Type.MouseButtonDblClick, p, LEFT, LEFT)
    send(canvas, QEvent.Type.MouseButtonRelease, p, LEFT, NO_BUTTON)


def drag(canvas, start, end):
    a, b = view_pos(canvas, *start), view_pos(canvas, *end)
    send(canvas, QEvent.Type.MouseButtonPress, a, LEFT, LEFT)
    send(canvas, QEvent.Type.MouseMove, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2), NO_BUTTON, LEFT)
    send(canvas, QEvent.Type.MouseMove, b, NO_BUTTON, LEFT)
    send(canvas, QEvent.Type.MouseButtonRelease, b, LEFT, NO_BUTTON)


def approx_points(points):
    return [pytest.approx(p, abs=1.0) for p in points]


def test_click_click_type_creates_dimension(canvas, qtbot):
    click(canvas, 50, 150)
    click(canvas, 350, 150)
    editor = canvas.label_editor()
    assert editor is not None
    qtbot.keyClicks(editor, "284 cm")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert canvas.label_editor() is None
    [dim] = canvas.doc.dimensions
    assert list(dim.points) == approx_points([(50, 150), (350, 150)])
    assert dim.labels == ("284 cm",)
    assert dim.offset == (0.0, 0.0)
    assert canvas.undo.count() == 1
    canvas.undo.undo()
    assert canvas.doc.dimensions == []
    assert canvas.dimension_items() == []


def test_escape_while_labelling_discards_the_new_dimension(canvas, qtbot):
    click(canvas, 50, 150)
    click(canvas, 350, 150)
    qtbot.keyClick(canvas.label_editor(), Qt.Key.Key_Escape)
    assert canvas.doc.dimensions == []
    assert canvas.dimension_items() == []
    assert canvas.undo.count() == 0


def test_escape_cancels_the_draft(canvas, qtbot):
    click(canvas, 50, 150)
    assert canvas.is_drawing()
    qtbot.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.is_drawing()
    click(canvas, 100, 100)
    assert canvas.is_drawing() and canvas.label_editor() is None


def test_ctrl_click_builds_a_chain_and_tab_walks_its_labels(canvas, qtbot):
    click(canvas, 50, 250)
    click(canvas, 150, 250, CTRL)
    click(canvas, 250, 240, CTRL)
    assert canvas.label_editor() is None
    click(canvas, 350, 250)
    editor = canvas.label_editor()
    tab = lambda: qtbot.keyClick(editor, Qt.Key.Key_Tab)  # fields: length, angle, length, angle, length
    qtbot.keyClicks(editor, "70")
    tab()
    tab()
    qtbot.keyClicks(editor, "x")
    qtbot.keyClick(editor, Qt.Key.Key_Backtab)
    qtbot.keyClick(editor, Qt.Key.Key_Backtab)
    assert editor.text() == "70"
    tab()
    tab()
    assert editor.text() == "x"
    qtbot.keyClicks(editor, "71")  # replaces the selected "x"
    tab()
    tab()
    qtbot.keyClicks(editor, "72")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    [dim] = canvas.doc.dimensions
    assert list(dim.points) == approx_points([(50, 250), (150, 250), (250, 240), (350, 250)])
    assert dim.labels == ("70", "71", "72")
    assert dim.angles == ("", "")


def test_backspace_removes_the_last_draft_point(canvas, qtbot):
    click(canvas, 50, 150)
    click(canvas, 150, 150, CTRL)
    qtbot.keyClick(canvas, Qt.Key.Key_Backspace)
    click(canvas, 350, 150)
    qtbot.keyClick(canvas.label_editor(), Qt.Key.Key_Return)
    [dim] = canvas.doc.dimensions
    assert list(dim.points) == approx_points([(50, 150), (350, 150)])


def test_shift_snaps_to_horizontal(canvas, qtbot):
    click(canvas, 50, 150)
    click(canvas, 350, 170, SHIFT)
    qtbot.keyClick(canvas.label_editor(), Qt.Key.Key_Return)
    [dim] = canvas.doc.dimensions
    assert dim.points[1][1] == dim.points[0][1]


def test_click_too_close_to_the_previous_point_is_ignored(canvas):
    click(canvas, 50, 150)
    click(canvas, 50.3, 150.2)
    assert canvas.is_drawing()
    assert canvas.label_editor() is None


def test_clicks_without_an_image_do_nothing(qtbot):
    c = Canvas()
    c.resize(400, 300)
    qtbot.addWidget(c)
    c.show()
    click(c, 10, 10)
    assert not c.is_drawing()


def test_dragging_the_line_changes_only_the_offset(canvas):
    dim = Dimension(((50.0, 150.0), (350.0, 150.0)), ("a",))
    with_dimension(canvas, dim)
    drag(canvas, (200, 150), (230, 90))
    [moved] = canvas.doc.dimensions
    assert moved.points == dim.points
    assert moved.offset == pytest.approx((30, -60), abs=1.0)
    canvas.undo.undo()
    assert canvas.doc.dimensions == [dim]


def test_dragging_a_handle_moves_one_point(canvas):
    dim = Dimension(((50.0, 150.0), (350.0, 150.0)), ("a",), (0.0, -60.0))
    with_dimension(canvas, dim)
    click(canvas, 200, 90)  # select via the dimension line
    assert canvas.dimension_items()[0].isSelected()
    drag(canvas, (50, 150), (60, 170))
    [moved] = canvas.doc.dimensions
    assert moved.points[0] == pytest.approx((60, 170), abs=1.0)
    assert moved.points[1] == dim.points[1]
    assert moved.offset == dim.offset


def test_double_click_edits_an_existing_label(canvas, qtbot):
    with_dimension(canvas, Dimension(((50.0, 150.0), (350.0, 150.0)), ("old",), (0.0, -60.0)))
    centre = canvas.dimension_items()[0].paths.label_boxes[0].boundingRect().center()
    double_click(canvas, centre.x(), centre.y())
    editor = canvas.label_editor()
    assert editor is not None and editor.text() == "old"
    qtbot.keyClicks(editor, "new")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert canvas.doc.dimensions[0].labels == ("new",)
    canvas.undo.undo()
    assert canvas.doc.dimensions[0].labels == ("old",)


def test_escape_while_editing_an_existing_label_restores_it(canvas, qtbot):
    with_dimension(canvas, Dimension(((50.0, 150.0), (350.0, 150.0)), ("old",), (0.0, -60.0)))
    canvas.edit_labels(canvas.dimension_items()[0], 0)
    qtbot.keyClicks(canvas.label_editor(), "zzz")
    qtbot.keyClick(canvas.label_editor(), Qt.Key.Key_Escape)
    assert canvas.dimension_items()[0].dim.labels == ("old",)
    assert canvas.undo.count() == 0


def test_delete_removes_the_selected_dimension(canvas, qtbot):
    dim = Dimension(((50.0, 150.0), (350.0, 150.0)), ("a",), (0.0, -60.0))
    with_dimension(canvas, dim)
    click(canvas, 200, 90)
    qtbot.keyClick(canvas, Qt.Key.Key_Delete)
    assert canvas.doc.dimensions == []
    canvas.undo.undo()
    assert canvas.doc.dimensions == [dim]


def test_style_change_is_undoable_and_reaches_the_items(canvas):
    with_dimension(canvas, Dimension(((50.0, 150.0), (350.0, 150.0)), ("a",)))
    seen = []
    canvas.style_changed.connect(seen.append)
    canvas.set_style(Style(8, 30, "#00FF00"))
    assert canvas.doc.style == Style(8, 30, "#00FF00")
    assert seen[-1] == Style(8, 30, "#00FF00")
    canvas.undo.undo()
    assert canvas.doc.style == STYLE


def test_finish_interaction_confirms_an_open_editor(canvas, qtbot):
    click(canvas, 50, 150)
    click(canvas, 350, 150)
    qtbot.keyClicks(canvas.label_editor(), "1 m")
    canvas.finish_interaction()
    assert canvas.doc.dimensions[0].labels == ("1 m",)
    assert canvas.undo.count() == 1


def test_flattened_has_the_image_size(canvas):
    with_dimension(canvas, Dimension(((50.0, 150.0), (350.0, 150.0)), ("a",)))
    assert canvas.flattened().size() == QSize(400, 300)


def test_losing_focus_releases_space_pan(canvas, qtbot):
    from PySide6.QtGui import QFocusEvent

    qtbot.keyPress(canvas, Qt.Key.Key_Space)
    QApplication.sendEvent(canvas, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.ActiveWindowFocusReason))
    click(canvas, 50, 150)
    assert canvas.is_drawing()


def test_delete_while_editing_a_label_does_not_break_the_editor(canvas, qtbot):
    dim = Dimension(((50.0, 150.0), (350.0, 150.0)), ("a",), (0.0, -60.0))
    with_dimension(canvas, dim)
    click(canvas, 200, 90)
    canvas.edit_labels(canvas.dimension_items()[0], 0)
    qtbot.keyClick(canvas, Qt.Key.Key_Delete)
    canvas.finish_interaction()
    assert canvas.label_editor() is None
    assert canvas.doc.dimensions == []


def test_tab_walks_lengths_and_angles_along_the_chain(canvas, qtbot):
    click(canvas, 50, 250)
    click(canvas, 150, 250, CTRL)
    click(canvas, 150, 150)
    editor = canvas.label_editor()
    qtbot.keyClicks(editor, "1 m")
    qtbot.keyClick(editor, Qt.Key.Key_Tab)  # → angle at the corner
    assert editor.placeholderText() == "angle (optional)"
    qtbot.keyClicks(editor, "90°")
    qtbot.keyClick(editor, Qt.Key.Key_Tab)  # → second length
    qtbot.keyClicks(editor, "1 m")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    [dim] = canvas.doc.dimensions
    assert dim.labels == ("1 m", "1 m")
    assert dim.angles == ("90°",)


def test_skipping_the_angle_leaves_it_empty(canvas, qtbot):
    click(canvas, 50, 250)
    click(canvas, 150, 250, CTRL)
    click(canvas, 150, 150)
    editor = canvas.label_editor()
    for _ in range(3):
        qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert canvas.label_editor() is None
    assert canvas.doc.dimensions[0].angles == ("",)


def test_double_click_edits_an_angle_label(canvas, qtbot):
    with_dimension(canvas, Dimension(((50.0, 250.0), (150.0, 250.0), (150.0, 150.0)), ("a", "b"), angles=("90°",)))
    centre = canvas.dimension_items()[0].paths.angle_boxes[0].boundingRect().center()
    double_click(canvas, centre.x(), centre.y())
    editor = canvas.label_editor()
    assert editor.text() == "90°"
    qtbot.keyClicks(editor, "89°")
    qtbot.keyClick(editor, Qt.Key.Key_Return)  # → next field (length b)
    qtbot.keyClick(editor, Qt.Key.Key_Return)  # last field: finish
    assert canvas.doc.dimensions[0].angles == ("89°",)


def test_editor_shows_which_kind_of_field_and_highlights_it(canvas, qtbot):
    click(canvas, 50, 250)
    click(canvas, 150, 250, CTRL)
    click(canvas, 150, 150)
    editor = canvas.label_editor()
    item = canvas.dimension_items()[0]
    assert editor.prefix() == "↔" and item.highlighted_field() == 0
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.prefix() == "∠" and item.highlighted_field() == 1
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert canvas.dimension_items()[0].highlighted_field() is None


def test_highlight_never_reaches_the_export(canvas, qtbot):
    with_dimension(canvas, Dimension(((50.0, 150.0), (350.0, 150.0)), ("a",), (0.0, -60.0)))
    before = canvas.flattened()
    canvas.edit_labels(canvas.dimension_items()[0], 0)
    assert canvas.dimension_items()[0].highlighted_field() == 0
    from dimensio.render import export_image

    assert export_image(canvas.image, canvas.doc) == before


def test_level_tool_places_a_marker_with_one_click(canvas, qtbot):
    from dimensio.model import Level

    canvas.set_tool("level")
    click(canvas, 200, 200)
    editor = canvas.label_editor()
    assert editor.prefix() == "▽"
    qtbot.keyClicks(editor, "+1.20")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    [level] = canvas.doc.dimensions
    assert isinstance(level, Level) and level.label == "+1.20"
    assert level.point == pytest.approx((200, 200), abs=1.0)
    drag(canvas, (200, 190), (240, 150))  # grab the triangle, move it away
    [moved] = canvas.doc.dimensions
    assert moved.point == level.point and moved.offset == pytest.approx((40, -40), abs=1.0)
    canvas.undo.undo()
    canvas.undo.undo()
    assert canvas.doc.dimensions == []


def test_escape_discards_a_new_level_marker(canvas, qtbot):
    canvas.set_tool("level")
    click(canvas, 200, 200)
    qtbot.keyClick(canvas.label_editor(), Qt.Key.Key_Escape)
    assert canvas.doc.dimensions == []


def test_id_tags_follow_the_drawing_order(canvas, qtbot):
    from dataclasses import replace as dc_replace

    a = Dimension(((50.0, 100.0), (350.0, 100.0)), ("a",))
    b = Dimension(((50.0, 200.0), (350.0, 200.0)), ("b",))
    canvas.set_document(blank(), Document(style=STYLE, dimensions=[a, b]))
    canvas.set_style(dc_replace(STYLE, ids=True))
    assert [item.tag for item in canvas.dimension_items()] == ["A", "B"]
    click(canvas, 200, 100)
    qtbot.keyClick(canvas, Qt.Key.Key_Delete)
    assert [item.tag for item in canvas.dimension_items()] == ["A"]
    canvas.undo.undo()
    canvas.undo.undo()
    assert [item.tag for item in canvas.dimension_items()] == ["", ""]


def test_line_tool_draws_without_asking_for_labels(canvas):
    from dimensio.model import Line

    canvas.set_tool("line")
    click(canvas, 50, 250)
    click(canvas, 150, 200, CTRL)
    click(canvas, 250, 250)
    assert canvas.label_editor() is None
    [line] = canvas.doc.dimensions
    assert isinstance(line, Line) and len(line.points) == 3
    assert canvas.undo.count() == 1
    drag(canvas, (100, 225), (100, 175))  # dragging moves the whole line
    [moved] = canvas.doc.dimensions
    assert [p[1] for p in moved.points] == pytest.approx([p[1] - 50 for p in line.points], abs=1.0)


def test_note_tool_points_at_a_spot_and_takes_one_line(canvas, qtbot):
    from dimensio.model import Note

    canvas.set_tool("note")
    click(canvas, 100, 250)
    editor = canvas.label_editor()
    assert editor.prefix() == "✎"
    qtbot.keyClicks(editor, "drain pipe")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    [note] = canvas.doc.dimensions
    assert isinstance(note, Note) and note.label == "drain pipe"
    assert note.point == pytest.approx((100, 250), abs=1.0)


def test_empty_note_is_discarded(canvas, qtbot):
    canvas.set_tool("note")
    click(canvas, 100, 250)
    qtbot.keyClick(canvas.label_editor(), Qt.Key.Key_Return)
    assert canvas.doc.dimensions == [] and canvas.undo.count() == 0


def test_other_kinds_are_click_through_for_the_active_tool(canvas, qtbot):
    from dimensio.model import Level, Line

    line = Line(((50.0, 150.0), (350.0, 150.0)))
    canvas.set_document(blank(), Document(style=STYLE, dimensions=[line]))
    click(canvas, 100, 150)  # dimension tool: starts a dimension on top of the line
    click(canvas, 300, 150)
    qtbot.keyClick(canvas.label_editor(), Qt.Key.Key_Return)
    assert canvas.doc.dimensions[0] == line and isinstance(canvas.doc.dimensions[1], Dimension)
    canvas.set_tool("level")
    click(canvas, 200, 150)  # level tool: neither the line nor the dimension grabs the click
    qtbot.keyClick(canvas.label_editor(), Qt.Key.Key_Escape)
    assert canvas.doc.dimensions[0] == line and len(canvas.doc.dimensions) == 2
    canvas.set_tool("line")
    drag(canvas, (60, 150), (60, 120))  # line tool: the line is yours again
    assert canvas.doc.dimensions[0] != line


def test_switching_tools_drops_the_selection_of_other_kinds(canvas):
    with_dimension(canvas, Dimension(((50.0, 150.0), (350.0, 150.0)), ("a",), (0.0, -60.0)))
    click(canvas, 200, 90)
    assert canvas.dimension_items()[0].isSelected()
    canvas.set_tool("line")
    assert not canvas.dimension_items()[0].isSelected()


def test_hidden_layer_disappears_and_its_tool_brings_it_back(canvas):
    from dataclasses import replace as dc_replace

    from dimensio.model import Line

    canvas.set_document(blank(), Document(style=STYLE, dimensions=[Line(((50.0, 150.0), (350.0, 150.0)))]))
    canvas.set_style(dc_replace(STYLE, hidden=("line",)))
    assert not canvas.dimension_items()[0].isVisible()
    canvas.set_tool("line")
    assert canvas.doc.style.hidden == () and canvas.dimension_items()[0].isVisible()


def test_circle_tool_centre_then_edge_then_optional_text(canvas, qtbot):
    from dimensio.model import Circle

    canvas.set_tool("circle")
    click(canvas, 200, 150)
    click(canvas, 260, 150)
    editor = canvas.label_editor()
    assert editor.prefix() == "Ø"
    qtbot.keyClick(editor, Qt.Key.Key_Return)  # no text: still a circle
    [circle] = canvas.doc.dimensions
    assert isinstance(circle, Circle) and circle.label == ""
    assert circle.radius == pytest.approx(60, abs=1.0)
    drag(canvas, (200, 90), (220, 90))  # grab the circle's top and move it
    [moved] = canvas.doc.dimensions
    assert moved.center == pytest.approx((220, 150), abs=1.0) and moved.radius == pytest.approx(circle.radius)
