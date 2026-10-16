# Dimensio

Add dimension lines with **your own measurements** to photos — the way a technical drawing does
it, but on a picture of a sofa, a wall or a window opening. Click two points, type `284 cm`,
drag the line clear of the object. Done.

**Dimensio doesn't measure anything.** No scale, no calibration, no photogrammetry. You already
know your numbers from the tape measure, the plan or the datasheet. Dimensio is for *handing them
on*: the quickest way to put them on a picture so clearly that whoever gets it (a carpenter, a
friend, an AI drawing your house model) knows without asking which number belongs to which edge.

![Dimensio examples](docs/examples.png)

- Click, click, type: a dimension line with arrowheads and your label
- Drag the line anywhere; extension lines follow the drag direction, so dimensions sit naturally
  in perspective photos
- **Ctrl+click** for chains (`70 | 70 | 70 cm` along a wall)
- Optional angles: every corner of a chain can get an angle label (`35°`) with an arc — drawn
  only if you type something
- Text always lies along the line and is never upside down
- Four settings for the whole image: line width, text size, color, outline on/off (off for very
  thin lines)
- Saves a flat `photo_dims.png` to send to people, plus `photo.jpg.dims.json` so you can keep
  editing later — opening either `photo.jpg` or `photo_dims.png` brings the editable lines back
- Copy the result straight to the clipboard

## Install

```bash
pipx install git+https://github.com/guelz/dimensio
# or
uv tool install git+https://github.com/guelz/dimensio
```

The first start adds Dimensio to your application menu and to **Open With** for images
(`dimensio --uninstall-desktop` removes it again).

**Native look (KDE/Breeze, HEIC/AVIF):** the PySide6 wheel from PyPI brings its own Qt, which
ignores your desktop theme and system image plugins. To use the system Qt instead (Arch example):

```bash
sudo pacman -S pyside6 kimageformats
pipx install --system-site-packages git+https://github.com/guelz/dimensio
```

## Use

| Do | How |
|---|---|
| Open | `dimensio photo.jpg`, Open With, drag and drop, Ctrl+O, or paste (Ctrl+V) |
| Dimension | click A, click B, type the label, Enter |
| Chain | Ctrl+click every point but the last; Enter/Tab walks the labels, Shift+Tab goes back |
| Angle | in a chain, Tab walks length → angle at the corner → length …; leave an angle empty to skip it |
| Straight | hold Shift for horizontal or vertical |
| Move | drag the line; drag a point's handle (select the dimension first) |
| Edit text | double-click the label |
| Delete | select, Delete |
| Undo / redo | Ctrl+Z / Ctrl+Shift+Z |
| Zoom / pan | Ctrl+wheel, middle-drag or Space+drag, Ctrl+0 fits |
| Save | Ctrl+S → `photo_dims.png` + `photo.jpg.dims.json`; Ctrl+Shift+S to choose |
| Copy result | Ctrl+C |

## Develop

```bash
uv venv && uv pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen .venv/bin/pytest
```

## License

MIT
