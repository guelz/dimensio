import json
from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage

import dimensio.app as app_module
from dimensio.app import MainWindow, main
from dimensio.commands import AddDimension
from dimensio.model import Dimension, load_sidecar, sidecar_path

DIM = Dimension(((20.0, 50.0), (180.0, 50.0)), ("1.2 m",), (0.0, -20.0))


def make_image(path: Path, color="white", width=200, height=100) -> Path:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path))
    return path


@pytest.fixture
def win(qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.warnings = []
    monkeypatch.setattr(w, "_warn", w.warnings.append)
    # pytest-qt closes the window at teardown; never let that open a real modal dialog.
    monkeypatch.setattr(w, "_ask_save_changes", lambda: "discard")
    return w


def add_dimension(win):
    canvas = win.canvas
    canvas.undo.push(AddDimension(canvas, len(canvas.doc.dimensions), DIM))


def test_save_writes_only_the_png_unless_json_is_ticked(win, tmp_path):
    photo = make_image(tmp_path / "photo.png")
    assert win.open_file(photo)
    add_dimension(win)
    assert win.isWindowModified()
    assert win.save()
    out = tmp_path / "photo_dims.png"
    assert QImage(str(out)).size() == QSize(200, 100)
    assert not sidecar_path(photo).exists()
    assert not win.isWindowModified()
    win.json_box.setChecked(True)
    add_dimension(win)
    win.save()
    assert load_sidecar(sidecar_path(photo)).dimensions == [DIM, DIM]


def test_reopening_restores_dimensions(win, tmp_path):
    photo = make_image(tmp_path / "photo.png")
    win.open_file(photo)
    add_dimension(win)
    win.save()
    win.open_file(photo)
    assert win.canvas.doc.dimensions == [DIM]
    assert win.canvas.undo.count() == 0


def test_changed_image_asks_before_loading_old_dimensions(win, tmp_path, monkeypatch):
    photo = make_image(tmp_path / "photo.png")
    win.open_file(photo)
    add_dimension(win)
    win.save()
    make_image(photo, color="black")  # same size, different content
    monkeypatch.setattr(win, "_ask_load_anyway", lambda: False)
    win.open_file(photo)
    assert win.canvas.doc.dimensions == []
    monkeypatch.setattr(win, "_ask_load_anyway", lambda: True)
    win.open_file(photo)
    assert win.canvas.doc.dimensions == [DIM]


def test_invalid_sidecar_warns_and_is_left_untouched(win, tmp_path):
    photo = make_image(tmp_path / "photo.png")
    side = sidecar_path(photo)
    side.write_text('{"version": 99}', encoding="utf-8")
    assert win.open_file(photo)
    assert win.canvas.doc.dimensions == []
    assert len(win.warnings) == 1
    assert side.read_text(encoding="utf-8") == '{"version": 99}'


def test_unreadable_image_warns(win, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"nope")
    assert not win.open_file(bad)
    assert len(win.warnings) == 1


def test_save_falls_back_to_save_as_when_folder_unwritable(win, tmp_path, monkeypatch):
    photo = make_image(tmp_path / "photo.png")
    win.open_file(photo)
    add_dimension(win)
    real_save = app_module.save_image
    calls = []

    def flaky(image, path):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError(13, "Permission denied", str(path))
        real_save(image, path)

    monkeypatch.setattr(app_module, "save_image", flaky)
    elsewhere = tmp_path / "elsewhere.png"
    monkeypatch.setattr(win, "_ask_save_path", lambda default: elsewhere)
    assert win.save()
    assert len(win.warnings) == 1
    assert QImage(str(elsewhere)).size() == QSize(200, 100)


def test_pasted_image_saves_via_save_as_without_sidecar(win, tmp_path, monkeypatch):
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    QGuiApplication.clipboard().setImage(image)
    win.paste()
    assert win.source is None and win.canvas.has_image()
    monkeypatch.setattr(win, "_ask_save_path", lambda default: tmp_path / "out")
    assert win.save()
    assert QImage(str(tmp_path / "out.png")).size() == QSize(120, 80)
    assert not list(tmp_path.glob("*.dims.json"))


def test_copy_puts_the_flattened_image_on_the_clipboard(win, tmp_path):
    win.open_file(make_image(tmp_path / "photo.png"))
    add_dimension(win)
    win.copy()
    assert QGuiApplication.clipboard().image().size() == QSize(200, 100)


def test_open_other_image_with_unsaved_changes_can_cancel(win, tmp_path, qtbot, monkeypatch):
    first = make_image(tmp_path / "a.png")
    second = make_image(tmp_path / "b.png")
    win.open_file(first)
    add_dimension(win)
    canvas = win.canvas
    canvas.edit_labels(canvas.dimension_items()[0], 0)
    qtbot.keyClicks(canvas.label_editor(), "2 m")  # editor still open
    monkeypatch.setattr(win, "_ask_save_changes", lambda: "cancel")
    assert not win.open_file(second)
    assert win.source == first
    assert canvas.doc.dimensions[0].labels == ("2 m",)  # editor text was committed, not lost


def test_close_with_unsaved_changes_can_cancel(win, tmp_path, monkeypatch):
    win.open_file(make_image(tmp_path / "a.png"))
    add_dimension(win)
    monkeypatch.setattr(win, "_ask_save_changes", lambda: "cancel")
    win.close()
    assert win.isVisible()
    monkeypatch.setattr(win, "_ask_save_changes", lambda: "discard")
    win.close()
    assert not win.isVisible()


def test_style_boxes_push_undoable_changes(win, tmp_path):
    win.open_file(make_image(tmp_path / "a.png"))
    before = win.canvas.doc.style
    win.width_box.setValue(7)
    assert win.canvas.doc.style.layer("dimension").line_width == 7
    win.undo()
    assert win.canvas.doc.style == before
    assert win.width_box.value() == round(before.line_width)


def test_colour_is_remembered_for_the_next_image(win, tmp_path):
    win.open_file(make_image(tmp_path / "a.png"))
    win.set_color("#00ff00")
    assert win.canvas.doc.style.layer("dimension").color == "#00FF00"
    win.canvas.undo.setClean()
    win.open_file(make_image(tmp_path / "b.png"))
    assert win.canvas.doc.style.layer("dimension").color == "#00FF00"


def test_main_installs_the_desktop_entry_without_starting_the_gui(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert main(["--install-desktop"]) == 0
    assert (tmp_path / "applications" / "dimensio.desktop").exists()
    assert main(["--uninstall-desktop"]) == 0
    assert not (tmp_path / "applications" / "dimensio.desktop").exists()


def test_newer_or_broken_sidecar_is_never_overwritten(win, tmp_path):
    photo = make_image(tmp_path / "photo.png")
    side = sidecar_path(photo)
    side.write_text('{"version": 2}', encoding="utf-8")
    win.json_box.setChecked(True)
    win.open_file(photo)
    add_dimension(win)
    assert win.save()
    assert side.read_text(encoding="utf-8") == '{"version": 2}'
    assert (tmp_path / "photo_dims.png").exists()
    assert len(win.warnings) == 2  # once on open, once on save


def test_cancel_keeps_a_half_drawn_draft(win, tmp_path, monkeypatch):
    from tests.test_canvas import CTRL, click

    win.open_file(make_image(tmp_path / "a.png"))
    add_dimension(win)
    click(win.canvas, 30, 80)
    click(win.canvas, 90, 80, CTRL)
    monkeypatch.setattr(win, "_ask_save_changes", lambda: "cancel")
    assert not win.open_file(make_image(tmp_path / "b.png"))
    assert win.canvas.is_drawing()


def test_style_box_hands_focus_back_to_the_canvas(win, tmp_path, qtbot):
    win.open_file(make_image(tmp_path / "a.png"))
    win.activateWindow()
    win.width_box.setFocus()
    qtbot.waitUntil(win.width_box.hasFocus)
    win.width_box.setValue(9)
    assert win.canvas.hasFocus()


def test_opening_the_exported_png_reopens_the_original_for_editing(win, tmp_path):
    photo = make_image(tmp_path / "photo.png")
    win.open_file(photo)
    add_dimension(win)
    win.save()
    win.open_file(tmp_path / "photo_dims.png")
    assert win.source == photo
    assert win.canvas.doc.dimensions == [DIM]


def test_status_bar_explains_zoom_pan_and_undo(win):
    from PySide6.QtWidgets import QLabel

    hints = " ".join(label.text() for label in win.statusBar().findChildren(QLabel))
    for words in ("Ctrl+scroll", "pan", "Ctrl+Z"):
        assert words in hints


def test_outline_checkbox_is_undoable_and_remembered(win, tmp_path):
    win.open_file(make_image(tmp_path / "a.png"))
    win.outline_box.setChecked(False)
    assert win.canvas.doc.style.layer("dimension").outline is False
    win.undo()
    assert win.canvas.doc.style.layer("dimension").outline is True
    assert win.outline_box.isChecked()
    win.redo()
    win.canvas.undo.setClean()
    win.open_file(make_image(tmp_path / "b.png"))
    assert win.canvas.doc.style.layer("dimension").outline is False
    assert not win.outline_box.isChecked()


def test_tool_picker_switches_the_canvas_tool(win, tmp_path):
    win.open_file(make_image(tmp_path / "a.png"))
    win.level_action.trigger()
    assert win.canvas.tool == "level"
    win.dimension_action.trigger()
    assert win.canvas.tool == "dimension"


def test_saved_png_carries_the_data(win, tmp_path):
    import json

    photo = make_image(tmp_path / "photo.png")
    win.open_file(photo)
    add_dimension(win)
    win.save()
    data = json.loads(QImage(str(tmp_path / "photo_dims.png")).text("dimensio"))
    assert data["dimensions"][0]["labels"] == ["1.2 m"] and data["dimensions"][0]["id"] == "A"


def test_exported_png_reopens_from_its_own_data_without_the_sidecar(win, tmp_path):
    photo = make_image(tmp_path / "photo.png")
    win.open_file(photo)
    add_dimension(win)
    win.save()
    assert not sidecar_path(photo).exists()
    win.open_file(tmp_path / "photo_dims.png")
    assert win.source == photo
    assert win.canvas.doc.dimensions == [DIM]


def test_ids_checkbox_is_undoable_and_remembered(win, tmp_path):
    win.open_file(make_image(tmp_path / "a.png"))
    win.ids_box.setChecked(True)
    assert win.canvas.doc.style.ids is True
    win.canvas.undo.setClean()
    win.open_file(make_image(tmp_path / "b.png"))
    assert win.canvas.doc.style.ids is True and win.ids_box.isChecked()


def test_cli_prints_the_data_an_exported_image_carries(win, tmp_path, capsys):
    import json

    photo = make_image(tmp_path / "photo.png")
    win.open_file(photo)
    add_dimension(win)
    win.save()
    assert main(["--data", str(tmp_path / "photo_dims.png")]) == 0
    assert json.loads(capsys.readouterr().out)["dimensions"][0]["labels"] == ["1.2 m"]
    assert main(["--data", str(photo)]) == 0  # the original: falls back to its sidecar
    assert json.loads(capsys.readouterr().out)["dimensions"][0]["id"] == "A"
    assert main(["--data", str(tmp_path / "nothing.png")]) == 1


def test_number_keys_pick_all_four_tools(win, tmp_path):
    win.open_file(make_image(tmp_path / "a.png"))
    for action, tool in ((win.line_action, "line"), (win.note_action, "note"), (win.level_action, "level"), (win.dimension_action, "dimension")):
        action.trigger()
        assert win.canvas.tool == tool
    assert "4" in [s.toString() for s in win.note_action.shortcuts()]


def test_layer_checkmarks_hide_kinds_in_view_and_export(win, tmp_path):
    import json

    photo = make_image(tmp_path / "photo.png")
    win.open_file(photo)
    add_dimension(win)
    win.layer_actions["dimension"].setChecked(False)
    assert win.canvas.doc.style.hidden == ("dimension",)
    win.save()
    assert "dimensions" not in json.loads(QImage(str(tmp_path / "photo_dims.png")).text("dimensio")) or \
        json.loads(QImage(str(tmp_path / "photo_dims.png")).text("dimensio"))["dimensions"] == []
    assert load_sidecar(sidecar_path(photo)).dimensions == [DIM]
    win.undo()
    assert win.layer_actions["dimension"].isChecked()


def test_f_fits_the_picture(win, tmp_path):
    win.open_file(make_image(tmp_path / "a.png"))
    fitted = win.canvas.transform().m11()
    win.canvas.zoom(4.0)
    win.fit_action.trigger()
    assert [s.toString() for s in win.fit_action.shortcuts()] == ["F"]
    assert win.canvas.transform().m11() == pytest.approx(fitted)


def test_toolbar_edits_the_layer_of_the_active_tool(win, tmp_path):
    win.open_file(make_image(tmp_path / "a.png"))
    win.line_action.trigger()
    win.set_color("#0000ff")
    win.width_box.setValue(9)
    style = win.canvas.doc.style
    assert style.layer("line").color == "#0000FF" and style.layer("line").line_width == 9
    assert style.layer("dimension").color != "#0000FF" and style.layer("dimension").line_width != 9
    win.dimension_action.trigger()
    assert win.width_box.value() == round(style.layer("dimension").line_width)


def test_circle_tool_and_layer_exist(win, tmp_path):
    win.open_file(make_image(tmp_path / "a.png"))
    win.circle_action.trigger()
    assert win.canvas.tool == "circle"
    assert "circle" in win.layer_actions
    assert {s.toString() for s in win.circle_action.shortcuts()} == {"5", "C"}


def test_snap_state_is_always_visible_and_s_toggles_it(win, tmp_path):
    win.open_file(make_image(tmp_path / "a.png"))
    assert win.canvas.snap_enabled and "on" in win.snap_status.text()
    win.snap_action.trigger()
    assert not win.canvas.snap_enabled and "off" in win.snap_status.text()
    assert [s.toString() for s in win.snap_action.shortcuts()] == ["S"]
    win.snap_status.click()  # the indicator itself toggles too
    assert win.canvas.snap_enabled


def test_holding_alt_shows_snap_paused(win, tmp_path, qtbot):
    win.open_file(make_image(tmp_path / "a.png"))
    qtbot.keyPress(win.canvas, Qt.Key.Key_Alt)
    assert "Alt" in win.snap_status.text()
    qtbot.keyRelease(win.canvas, Qt.Key.Key_Alt)
    assert win.snap_status.text() == "⌖ Snap on"


def test_save_as_elsewhere_keeps_the_photo_folder_clean_and_stays_editable(win, tmp_path, monkeypatch):
    origin, elsewhere = tmp_path / "origin", tmp_path / "exports"
    origin.mkdir()
    elsewhere.mkdir()
    photo = make_image(origin / "photo.png")
    win.open_file(photo)
    add_dimension(win)
    asked = []
    monkeypatch.setattr(win, "_ask_save_path", lambda default: asked.append(default) or elsewhere / "garden.png")
    assert win.save_as()
    assert sorted(p.name for p in origin.iterdir()) == ["photo.png"]
    win.open_file(photo)  # the original finds its export through this computer's own list
    assert win.canvas.doc.dimensions == [DIM]
    win.open_file(elsewhere / "garden.png")  # and the export finds its original
    assert win.source == photo and win.canvas.doc.dimensions == [DIM]
    add_dimension(win)
    win.save()  # Ctrl+S keeps writing to the chosen file
    assert not (origin / "photo_dims.png").exists()
    assert len(json.loads(QImage(str(elsewhere / "garden.png")).text("dimensio"))["dimensions"]) == 2
    win.save_as()
    assert asked[-1].parent == elsewhere  # Save As remembers the folder


def test_hidden_layers_keep_the_json_and_say_so(win, tmp_path):
    photo = make_image(tmp_path / "photo.png")
    win.open_file(photo)
    add_dimension(win)
    win.layer_actions["dimension"].setChecked(False)
    win.save()
    assert load_sidecar(sidecar_path(photo)).dimensions == [DIM]
    assert "hidden" in win.statusBar().currentMessage()


def test_save_as_is_in_the_toolbar(win):
    from PySide6.QtWidgets import QToolBar

    [bar] = win.findChildren(QToolBar)
    assert win.save_as_action in bar.actions()


def test_print_is_in_the_toolbar_on_ctrl_p(win, tmp_path):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QToolBar

    [bar] = win.findChildren(QToolBar)
    assert win.print_action in bar.actions()
    assert win.print_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Print)
    assert not win.print_action.isEnabled()
    win.open_file(make_image(tmp_path / "a.png"))
    assert win.print_action.isEnabled()
