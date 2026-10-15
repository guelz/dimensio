"""Main window and command-line entry point."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QToolButton,
)

from . import __version__, desktop
from .canvas import Canvas
from .model import (
    DEFAULT_COLOR,
    Document,
    ImageInfo,
    SidecarError,
    Style,
    is_hex_color,
    load_sidecar,
    output_path,
    save_sidecar,
    sidecar_path,
)
from .render import ImageLoadError, load_image, save_image

IMAGE_FILTER = "Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp *.heic *.heif *.avif);;All files (*)"
SAVE_FILTER = "PNG image (*.png);;JPEG image (*.jpg *.jpeg)"
HINT = (
    "Click two points to add a dimension · Ctrl+click adds chain points · Shift snaps · "
    "Esc cancels · Double-click a label to edit it"
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("dimensio", "dimensio")
        self.source: Path | None = None
        self.canvas = Canvas(self)
        self.canvas.setAcceptDrops(False)  # drops are handled by the window
        self.canvas.viewport().setAcceptDrops(False)
        self.setCentralWidget(self.canvas)
        self.setAcceptDrops(True)
        self._build_actions()
        self._build_toolbar()
        self.canvas.style_changed.connect(self._show_style)
        self.canvas.undo.cleanChanged.connect(lambda clean: self.setWindowModified(not clean))
        self.statusBar().showMessage(HINT)
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
        self._action("&Fit to window", "Ctrl+0", self.canvas.fit, "zoom-fit-best")
        self._action("&Quit", QKeySequence.StandardKey.Quit, self.close)
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
        for action in (self.open_action, self.save_action, self.copy_action):
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

    def _set_image_loaded(self, loaded: bool) -> None:
        for widget in (self.save_action, self.save_as_action, self.copy_action, self.width_box, self.size_box, self.color_button):
            widget.setEnabled(loaded)

    def _update_title(self) -> None:
        if self.source is not None:
            name = self.source.name
        elif self.canvas.doc is not None:
            name = "Pasted image"
        else:
            name = None
        self.setWindowTitle(f"{name}[*] — Dimensio" if name else "Dimensio")

    def _show_style(self, style: Style) -> None:
        for box, value in ((self.width_box, style.line_width), (self.size_box, style.text_size)):
            box.blockSignals(True)
            box.setValue(round(value))
            box.blockSignals(False)
        swatch = QPixmap(16, 16)
        swatch.fill(QColor(style.color))
        self.color_button.setIcon(QIcon(swatch))

    # ----- style -----

    def _on_size_input(self) -> None:
        if self.canvas.doc is not None:
            style = replace(self.canvas.doc.style, line_width=self.width_box.value(), text_size=self.size_box.value())
            self.canvas.set_style(style)

    def choose_color(self) -> None:
        if self.canvas.doc is None:
            return
        color = QColorDialog.getColor(QColor(self.canvas.doc.style.color), self, "Dimension color")
        if color.isValid():
            self.set_color(color.name())

    def set_color(self, name: str) -> None:
        name = name.upper()
        self.canvas.set_style(replace(self.canvas.doc.style, color=name))
        self.settings.setValue("color", name)

    def _last_color(self) -> str:
        value = self.settings.value("color", DEFAULT_COLOR)
        return value if is_hex_color(value) else DEFAULT_COLOR

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
        try:
            image = load_image(path)
        except ImageLoadError as e:
            self._warn(f"Could not open the image.\n\n{e}")
            return False
        info = ImageInfo.from_file(path, image.width(), image.height())
        doc = Document(Style.for_image(image.width(), image.height(), self._last_color()), image=info)
        side = sidecar_path(path)
        if side.exists():
            try:
                saved = load_sidecar(side)
            except SidecarError as e:
                self._warn(f"Ignoring {side.name} because it could not be read.\n\n{e}")
            else:
                if saved.image is None or saved.image.matches(info) or self._ask_load_anyway():
                    doc = Document(saved.style, saved.dimensions, info)
        self.source = path
        self.canvas.set_document(image, doc)
        self._loaded()
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
        self.canvas.set_document(image, Document(Style.for_image(image.width(), image.height(), self._last_color())))
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
        save_image(self.canvas.flattened(), target)
        if self.source is not None:
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
        self.canvas.finish_interaction()
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dimensio", description="Add dimension lines with your own measurements to photos.")
    parser.add_argument("image", nargs="?", type=Path, help="image to open")
    parser.add_argument("--install-desktop", action="store_true", help="add Dimensio to the application menu and 'Open With'")
    parser.add_argument("--uninstall-desktop", action="store_true", help="remove the application menu entry and icon")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

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
