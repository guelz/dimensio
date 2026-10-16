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
- Level markers (`▽ ±0.00`, `+1.25 m`) for heights and terrain
- Plain lines, and one-line notes with an arrow pointing at what you mean ("drain pipe")
- Text always lies along the line and is never upside down
- Settings for the whole image: line width, text size, color, outline on/off (off for very thin
  lines), ID tags on/off
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
| Tool | **1**/**D** dimension, **2**/**L** level marker, **3** line, **4**/**T** note (toolbar) |
| Dimension | click A, click B, type the label, Enter |
| Chain | Ctrl+click every point but the last; Enter/Tab walks the labels, Shift+Tab goes back |
| Angle | in a chain, Tab walks length → angle at the corner → length …; leave an angle empty to skip it |
| Level | with the level tool, click the spot and type its height; drag the marker away if it's in the way |
| Line | click, Ctrl+click for more points, click to finish; drag to move it |
| Note | click what you mean, type one line, Enter; drag the text where it fits |
| Straight | hold Shift for horizontal or vertical |
| Move | drag the line; drag a point's handle (select the dimension first) |
| Edit text | double-click the label |
| Delete | select, Delete |
| Undo / redo | Ctrl+Z / Ctrl+Shift+Z |
| Zoom / pan | Ctrl+wheel, middle-drag or Space+drag, Ctrl+0 fits |
| Save | Ctrl+S → `photo_dims.png` + `photo.jpg.dims.json`; Ctrl+Shift+S to choose |
| Copy result | Ctrl+C |

## For scripts and AI assistants

Every exported PNG carries its dimension data as JSON inside the file, and the same data sits in
the `.dims.json` next to the original. It names every item (`A`, `B`, … for dimensions, `L1`, …
for levels, `N1`, … for lines, `T1`, … for notes — switch on **IDs** to tag them in the picture
too) and explains its own fields: pixel coordinates of every point, the text of every segment,
angle, level and note.

```bash
dimensio --data photo_dims.png    # print it
```

So when you hand a picture to an AI model, it doesn't have to guess which number belongs to which
edge; it can read both the picture and the exact geometry.

## Develop

```bash
uv venv && uv pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen .venv/bin/pytest
```

## License

MIT
