"""Main window and command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSpinBox,
    QToolButton,
)

from . import __version__, desktop
from .canvas import Canvas
from .model import (
    DEFAULT_COLOR,
    KINDS,
    Document,
    ImageInfo,
    SidecarError,
    Style,
    find_original,
    from_json,
    is_hex_color,
    original_from_data,
    load_sidecar,
    output_path,
    save_sidecar,
    sidecar_path,
    to_json_text,
)
from .render import EMBED_KEY, ImageLoadError, load_image, read_embedded, save_image

IMAGE_FILTER = "Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp *.heic *.heif *.avif);;All files (*)"
SAVE_FILTER = "PNG image (*.png);;JPEG image (*.jpg *.jpeg)"
HINT = (
    "1-5: dimension, level, line, note, circle (each edits only its own kind) · Click, click, type · Ctrl+click: chain · Shift: straight · Esc: cancel · "
    "Double-click label: edit · "
    "Ctrl+scroll: zoom · Middle or Space+drag: pan · F: fit · Ctrl+Z / Ctrl+Shift+Z: undo / redo"
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("dimensio", "dimensio")
        self.source: Path | None = None
        self._keep_sidecar = False  # True when the existing sidecar could not be read: never overwrite it
        self.canvas = Canvas(self)
        self.canvas.setAcceptDrops(False)  # drops are handled by the window
        self.canvas.viewport().setAcceptDrops(False)
        self.setCentralWidget(self.canvas)
        self.setAcceptDrops(True)
        self._build_actions()
        self._build_toolbar()
        self.canvas.style_changed.connect(self._show_style)
        self.canvas.undo.cleanChanged.connect(lambda clean: self.setWindowModified(not clean))
        self.statusBar().addWidget(QLabel(HINT))  # stays visible; temporary messages cover it briefly
        self._set_image_loaded(False)
        self._update_title()
        self.resize(1200, 800)

    # ----- UI -----

    def _action(self, text, shortcut, slot, icon=None) -> QAction:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        if icon:
            action.setIcon(QIcon.fromTheme(icon))
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        self.open_action = self._action("&Open…", QKeySequence.StandardKey.Open, self.choose_file, "document-open")
        self.save_action = self._action("&Save", QKeySequence.StandardKey.Save, self.save, "document-save")
        self.save_as_action = self._action("Save &As…", "Ctrl+Shift+S", self.save_as, "document-save-as")
        self.copy_action = self._action("&Copy image", QKeySequence.StandardKey.Copy, self.copy, "edit-copy")
        self._action("&Paste image", QKeySequence.StandardKey.Paste, self.paste)
        self.undo_action = self._action("&Undo", QKeySequence.StandardKey.Undo, self.undo, "edit-undo")
        self.redo_action = self._action("&Redo", "Ctrl+Shift+Z", self.redo, "edit-redo")
        self.fit_action = self._action("&Fit", "F", self.canvas.fit, "zoom-fit-best")
        self.fit_action.setToolTip("Fit the whole picture into the window — F")
        self._action("&Quit", QKeySequence.StandardKey.Quit, self.close)
        self.tools = QActionGroup(self)
        self.dimension_action = self._action("&Dimension", "1", lambda: self._pick_tool("dimension"))
        self.level_action = self._action("&Level", "2", lambda: self._pick_tool("level"))
        self.line_action = self._action("L&ine", "3", lambda: self._pick_tool("line"))
        self.note_action = self._action("&Note", "4", lambda: self._pick_tool("note"))
        self.circle_action = self._action("&Circle", "5", lambda: self._pick_tool("circle"))
        for action, letter, tip in (
            (self.dimension_action, "D", "Click two points (Ctrl+click for a chain), then type"),
            (self.level_action, "L", "Click a spot, type its height (±0.00, +1.25 m …)"),
            (self.line_action, None, "Click two points (Ctrl+click for more), a plain line"),
            (self.note_action, "T", "Click what you mean, type a note; drag the text where it fits"),
            (self.circle_action, "C", "Click the centre, then the edge; type Ø 40 or R 20, or nothing for a plain circle"),
        ):
            if letter:
                action.setShortcuts([action.shortcut(), QKeySequence(letter)])
            action.setCheckable(True)
            action.setToolTip(f"{tip} — {' / '.join(s.toString() for s in action.shortcuts())}")
            self.tools.addAction(action)
        self.dimension_action.setChecked(True)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        self.canvas.undo.canUndoChanged.connect(self.undo_action.setEnabled)
        self.canvas.undo.canRedoChanged.connect(self.redo_action.setEnabled)

    def _spin(self, low: int, high: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setSuffix(" px")
        box.setKeyboardTracking(False)
        box.valueChanged.connect(self._on_size_input)
        return box

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("Main")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for action in (self.open_action, self.save_action, self.copy_action, self.fit_action):
            bar.addAction(action)
        bar.addSeparator()
        for action in (self.dimension_action, self.level_action, self.line_action, self.note_action, self.circle_action):
            bar.addAction(action)
        bar.addSeparator()
        bar.addWidget(QLabel(" Line width "))
        self.width_box = self._spin(1, 500)
        bar.addWidget(self.width_box)
        bar.addWidget(QLabel("  Text size "))
        self.size_box = self._spin(4, 2000)
        bar.addWidget(self.size_box)
        bar.addWidget(QLabel("  Color "))
        self.color_button = QToolButton()
        self.color_button.setToolTip("Color of all dimensions")
        self.color_button.clicked.connect(self.choose_color)
        bar.addWidget(self.color_button)
        bar.addWidget(QLabel("  "))
        self.outline_box = QCheckBox("Outline")
        self.outline_box.setToolTip("Contrasting outline around lines and text; switch off for very thin lines")
        self.outline_box.toggled.connect(self._on_outline_input)
        bar.addWidget(self.outline_box)
        self.ids_box = QCheckBox("IDs")
        self.ids_box.setToolTip("Name every dimension (A, B, …) and level (L1, …) in the picture, to refer to them in text")
        self.ids_box.toggled.connect(self._on_ids_input)
        bar.addWidget(self.ids_box)
        layers = QToolButton()
        layers.setText("Layers")
        layers.setToolTip("Show or hide each kind; hidden layers are left out of the saved picture too")
        layers.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(layers)
        self.layer_actions = {}
        for kind, title in (("dimension", "Dimensions"), ("level", "Levels"), ("line", "Lines"), ("note", "Notes"), ("circle", "Circles")):
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(self._on_layers_input)
            self.layer_actions[kind] = action
        self.color_button.setToolTip("Color of the active tool's layer")
        self.outline_box.setToolTip("Outline for the active tool's layer; switch off for very thin lines")
        layers.setMenu(menu)
        self.layers_button = layers
        bar.addWidget(layers)

    def _set_image_loaded(self, loaded: bool) -> None:
        for widget in (self.save_action, self.save_as_action, self.copy_action, self.width_box, self.size_box, self.color_button, self.outline_box, self.ids_box, self.layers_button):
            widget.setEnabled(loaded)

    def _update_title(self) -> None:
        if self.source is not None:
            name = self.source.name
        elif self.canvas.doc is not None:
            name = "Pasted image"
        else:
            name = None
        self.setWindowTitle(f"{name}[*] — Dimensio" if name else "Dimensio")

    def _pick_tool(self, tool: str) -> None:
        self.canvas.set_tool(tool)
        if self.canvas.doc is not None:
            self._show_style(self.canvas.doc.style)  # the toolbar shows the new tool's layer

    def _show_style(self, style: Style) -> None:
        """Toolbar = text size, IDs, layers for the picture; width, colour, outline for the active tool's layer."""
        own = style.layer(self.canvas.tool)
        for box, value in ((self.width_box, own.line_width), (self.size_box, style.text_size)):
            box.blockSignals(True)
            box.setValue(round(value))
            box.blockSignals(False)
        checks = [(self.outline_box, own.outline), (self.ids_box, style.ids)]
        checks += [(action, kind not in style.hidden) for kind, action in self.layer_actions.items()]
        for box, value in checks:
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)
        swatch = QPixmap(16, 16)
        swatch.fill(QColor(own.color))
        self.color_button.setIcon(QIcon(swatch))

    # ----- style -----

    def _on_size_input(self) -> None:
        if self.canvas.doc is not None:
            style = self.canvas.doc.style.with_layer(self.canvas.tool, line_width=self.width_box.value())
            self.canvas.set_style(replace(style, text_size=self.size_box.value()))
        self.canvas.setFocus()  # keep Ctrl+Z, Delete, Esc and Space working on the drawing

    def _on_outline_input(self, checked: bool) -> None:
        if self.canvas.doc is not None:
            self.canvas.set_style(self.canvas.doc.style.with_layer(self.canvas.tool, outline=checked))
            self.settings.setValue(f"outline/{self.canvas.tool}", checked)
        self.canvas.setFocus()

    def _on_layers_input(self) -> None:
        if self.canvas.doc is not None:
            hidden = tuple(kind for kind, action in self.layer_actions.items() if not action.isChecked())
            self.canvas.set_style(replace(self.canvas.doc.style, hidden=hidden))
        self.canvas.setFocus()

    def _on_ids_input(self, checked: bool) -> None:
        if self.canvas.doc is not None:
            self.canvas.set_style(replace(self.canvas.doc.style, ids=checked))
            self.settings.setValue("ids", checked)
        self.canvas.setFocus()

    def choose_color(self) -> None:
        if self.canvas.doc is None:
            return
        tool = self.canvas.tool
        color = QColorDialog.getColor(QColor(self.canvas.doc.style.layer(tool).color), self, f"Color of the {tool} layer")
        if color.isValid():
            self.set_color(color.name())
        self.canvas.setFocus()

    def set_color(self, name: str) -> None:
        name = name.upper()
        self.canvas.set_style(self.canvas.doc.style.with_layer(self.canvas.tool, color=name))
        self.settings.setValue(f"color/{self.canvas.tool}", name)

    def _new_style(self, width: int, height: int) -> Style:
        """Defaults for a new image, with the colour and outline each layer had last."""
        color = self.settings.value("color", DEFAULT_COLOR)  # pre-layer setting, still the base
        base = Style.for_image(width, height, color if is_hex_color(color) else DEFAULT_COLOR)
        style = replace(base, outline=self.settings.value("outline", True, type=bool), ids=self.settings.value("ids", False, type=bool))
        for kind in KINDS:
            layer_color = self.settings.value(f"color/{kind}")
            layer_outline = self.settings.value(f"outline/{kind}")
            changes = {}
            if is_hex_color(layer_color):
                changes["color"] = layer_color
            if layer_outline is not None:
                changes["outline"] = self.settings.value(f"outline/{kind}", True, type=bool)
            if changes:
                style = style.with_layer(kind, **changes)
        return style

    # ----- files -----

    def choose_file(self) -> None:
        start = str(self.source.parent) if self.source else str(Path.home())
        name, _ = QFileDialog.getOpenFileName(self, "Open image", start, IMAGE_FILTER)
        if name:
            self.open_file(Path(name))

    def open_file(self, path: Path) -> bool:
        if not self._confirm_discard():
            return False
        path = path.absolute()
        original = find_original(path)
        embedded = None
        if original is None:  # an exported image whose sidecar is gone still carries the data
            embedded = read_embedded(path)
            original = original_from_data(path, embedded)
        if original is not None:
            path = original
        try:
            image = load_image(path)
        except ImageLoadError as e:
            self._warn(f"Could not open the image.\n\n{e}")
            return False
        info = ImageInfo.from_file(path, image.width(), image.height())
        doc = Document(self._new_style(image.width(), image.height()), image=info)
        side = sidecar_path(path)
        keep_sidecar = False
        saved = None
        if side.exists():
            try:
                saved = load_sidecar(side)
            except SidecarError as e:
                keep_sidecar = True
                self._warn(f"Ignoring {side.name} because it could not be read. It will be left untouched.\n\n{e}")
        elif embedded is not None:
            try:
                saved = from_json(embedded)
            except SidecarError:
                saved = None
        if saved is not None and (saved.image is None or saved.image.matches(info) or self._ask_load_anyway()):
            doc = Document(saved.style, saved.dimensions, info)
        self.source = path
        self._keep_sidecar = keep_sidecar
        self.canvas.set_document(image, doc)
        self._loaded()
        if original is not None:
            self.statusBar().showMessage(f"Opened the original {path.name}, so the dimensions stay editable", 8000)
        return True

    def paste(self) -> None:
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData()
        files = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()] if mime.hasUrls() else []
        if files:
            self.open_file(Path(files[0]))
            return
        image = clipboard.image()
        if image.isNull():
            self.statusBar().showMessage("The clipboard holds no image", 5000)
            return
        if not self._confirm_discard():
            return
        self.source = None
        self.canvas.set_document(image, Document(self._new_style(image.width(), image.height())))
        self._loaded()

    def save(self) -> bool:
        if self.canvas.doc is None:
            return False
        if self.source is None:
            return self.save_as()
        try:
            self._write(output_path(self.source))
        except OSError as e:
            self._warn(f"Could not save next to the original.\n\n{e}\n\nChoose another location.")
            return self.save_as()
        return True

    def save_as(self) -> bool:
        if self.canvas.doc is None:
            return False
        default = output_path(self.source) if self.source else Path.home() / "dimensions.png"
        target = self._ask_save_path(default)
        if target is None:
            return False
        if target.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            target = target.with_name(target.name + ".png")
        try:
            self._write(target)
        except OSError as e:
            self._warn(f"Could not save the image.\n\n{e}")
            return False
        return True

    def _write(self, target: Path) -> None:
        image = self.canvas.flattened()
        image.setText(EMBED_KEY, to_json_text(self.canvas.doc, visible_only=True))  # the export explains itself
        save_image(image, target)
        if self.source is not None and self._keep_sidecar:
            self._warn(f"Saved {target.name}. {sidecar_path(self.source).name} was left untouched, so these dimensions are not kept for re-editing.")
        elif self.source is not None:
            side = sidecar_path(self.source)
            try:
                save_sidecar(self.canvas.doc, side)
            except OSError as e:
                self._warn(f"Saved {target.name}, but could not write {side.name} to keep the dimensions editable.\n\n{e}")
        self.canvas.undo.setClean()
        self.statusBar().showMessage(f"Saved {target}", 5000)

    def copy(self) -> None:
        if self.canvas.doc is None:
            return
        QGuiApplication.clipboard().setImage(self.canvas.flattened())
        self.statusBar().showMessage("Image copied to the clipboard", 3000)

    def undo(self) -> None:
        self.canvas.finish_interaction()
        self.canvas.undo.undo()

    def redo(self) -> None:
        self.canvas.finish_interaction()
        self.canvas.undo.redo()

    def _loaded(self) -> None:
        self._set_image_loaded(True)
        self._update_title()
        self.setWindowModified(False)
        self.canvas.setFocus()

    def _confirm_discard(self) -> bool:
        # Confirm the label being typed, but keep a half-drawn draft until the user decides.
        self.canvas.commit_label_editor()
        if self.canvas.doc is None or self.canvas.undo.isClean():
            return True
        answer = self._ask_save_changes()
        if answer == "save":
            return self.save()
        return answer == "discard"

    # ----- dialogs (replaced in tests) -----

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "Dimensio", text)

    def _ask_load_anyway(self) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, "Dimensio", "The image changed since these dimensions were saved.", parent=self)
        load = box.addButton("Load anyway", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Ignore", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() == load

    def _ask_save_changes(self) -> str:
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.question(
            self, "Dimensio", "Save your changes first?", buttons.Save | buttons.Discard | buttons.Cancel, buttons.Save
        )
        return {buttons.Save: "save", buttons.Discard: "discard"}.get(answer, "cancel")

    def _ask_save_path(self, default: Path) -> Path | None:
        name, _ = QFileDialog.getSaveFileName(self, "Save image", str(default), SAVE_FILTER)
        return Path(name) if name else None

    # ----- window events -----

    def dragEnterEvent(self, event) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        files = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if files:
            event.acceptProposedAction()
            path = Path(files[0])
            QTimer.singleShot(0, lambda: self.open_file(path))  # let the drop finish before any dialog

    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()


def _print_data(path: Path) -> int:
    """JSON for scripts and AI assistants: data embedded in an export, else the sidecar next to the image."""
    data = read_embedded(path) if path.is_file() else None
    if data is None and sidecar_path(path).is_file():
        try:
            data = json.loads(to_json_text(load_sidecar(sidecar_path(path))))
        except SidecarError as e:
            print(f"dimensio: {e}", file=sys.stderr)
            return 1
    if data is None:
        print(f"dimensio: no dimension data found for {path}", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dimensio", description="Add dimension lines with your own measurements to photos.")
    parser.add_argument("image", nargs="?", type=Path, help="image to open")
    parser.add_argument("--install-desktop", action="store_true", help="add Dimensio to the application menu and 'Open With'")
    parser.add_argument("--uninstall-desktop", action="store_true", help="remove the application menu entry and icon")
    parser.add_argument("--data", type=Path, metavar="IMAGE", help="print the dimension data of an image as JSON and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.data is not None:
        return _print_data(args.data)
    if args.install_desktop:
        for path in desktop.install():
            print(f"wrote {path}")
        return 0
    if args.uninstall_desktop:
        for path in desktop.uninstall():
            print(f"removed {path}")
        return 0
    if desktop.ensure_installed():
        print("dimensio: added to the application menu and 'Open With' (undo with --uninstall-desktop)", file=sys.stderr)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Dimensio")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(desktop.APP_ID)
    app.setWindowIcon(QIcon(str(desktop.icon_source())))
    window = MainWindow()
    window.show()
    if args.image is not None:
        window.open_file(args.image)
    return app.exec()
