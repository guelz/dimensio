import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QImageIOHandler, QImageWriter

from dimensio.model import Dimension, Document, Style
from dimensio.render import (
    ImageLoadError,
    build_paths,
    export_image,
    halo_color,
    load_image,
    save_image,
)

STYLE = Style(4, 20, "#FF0000")


def blank(width=400, height=300):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    return image


def is_red(c):
    return c.red() > 200 and c.green() < 80 and c.blue() < 80


def is_white(c):
    return min(c.red(), c.green(), c.blue()) > 230


def test_export_draws_line_extension_lines_halo_and_label(qapp):
    dim = Dimension(((50.0, 150.0), (350.0, 150.0)), ("ABC",), (0.0, -60.0))
    gray = blank()
    gray.fill(QColor(128, 128, 128))
    out = export_image(gray, Document(style=STYLE, dimensions=[dim]))
    assert out.size() == QSize(400, 300)
    assert is_red(out.pixelColor(200, 90))  # dimension line, offset to y = 90
    assert is_red(out.pixelColor(60, 90))  # inside the left arrowhead
    assert is_red(out.pixelColor(50, 120))  # extension line at A
    assert is_white(out.pixelColor(53, 120))  # halo beside the extension line (red is dark → white halo)
    assert out.pixelColor(10, 10) == QColor(128, 128, 128)  # untouched
    label_pixels = sum(is_red(out.pixelColor(x, y)) for x in range(170, 231) for y in range(55, 85))
    assert label_pixels > 20


def test_export_keeps_the_source_untouched(qapp):
    source = blank()
    export_image(source, Document(style=STYLE, dimensions=[Dimension(((0.0, 0.0), (100.0, 100.0)), ("x",))]))
    assert is_white(source.pixelColor(50, 50))


def test_empty_label_still_has_a_label_box(qapp):
    paths = build_paths(Dimension(((0.0, 0.0), (100.0, 0.0)), ("",)), STYLE)
    [box] = paths.label_boxes
    assert box.boundingRect().width() >= STYLE.text_size - 0.01


def test_chain_has_one_label_box_per_segment(qapp):
    paths = build_paths(Dimension(((0.0, 0.0), (100.0, 0.0), (200.0, 0.0)), ("a", "b")), STYLE)
    assert len(paths.label_boxes) == 2


def test_unicode_label_renders(qapp):
    paths = build_paths(Dimension(((0.0, 0.0), (300.0, 0.0)), ('2½" × 3 m² Ø',)), STYLE)
    assert paths.fills.boundingRect().height() > STYLE.text_size / 2


def test_zero_length_segment_renders(qapp):
    dim = Dimension(((5.0, 5.0), (5.0, 5.0)), ("x",), (0.0, 50.0))
    out = export_image(blank(), Document(style=STYLE, dimensions=[dim]))
    assert out.size() == QSize(400, 300)


def test_halo_contrasts_with_the_colour():
    assert halo_color(QColor("#FFC400")) == QColor("black")
    assert halo_color(QColor("#1A237E")) == QColor("white")


def test_save_png_and_jpg(qapp, tmp_path):
    for name in ("out.png", "out.jpg"):
        save_image(blank(), tmp_path / name)
        assert QImage(str(tmp_path / name)).size() == QSize(400, 300)


def test_save_into_missing_folder_raises_oserror(qapp, tmp_path):
    with pytest.raises(OSError):
        save_image(blank(), tmp_path / "missing" / "out.png")


def test_load_applies_exif_orientation(qapp, tmp_path):
    path = tmp_path / "rotated.jpg"
    source = QImage(64, 32, QImage.Format.Format_RGB32)
    source.fill(Qt.GlobalColor.red)
    writer = QImageWriter(str(path))
    writer.setTransformation(QImageIOHandler.Transformation.TransformationRotate90)
    assert writer.write(source)
    assert load_image(path).size() == QSize(32, 64)


def test_load_accepts_images_above_qts_default_256_mb_limit(qapp, tmp_path):
    path = tmp_path / "big.png"
    big = QImage(9000, 8000, QImage.Format.Format_RGB32)  # 288 MB decoded
    big.fill(QColor("white"))
    assert big.save(str(path))
    del big
    assert load_image(path).width() == 9000


def test_load_rejects_garbage(qapp, tmp_path):
    path = tmp_path / "x.png"
    path.write_bytes(b"not an image")
    with pytest.raises(ImageLoadError):
        load_image(path)


def test_outline_off_draws_no_halo(qapp):
    dim = Dimension(((50.0, 150.0), (350.0, 150.0)), ("ABC",), (0.0, -60.0))
    gray = blank()
    gray.fill(QColor(128, 128, 128))
    out = export_image(gray, Document(style=Style(4, 20, "#FF0000", outline=False), dimensions=[dim]))
    assert is_red(out.pixelColor(50, 120))
    assert out.pixelColor(53, 120) == QColor(128, 128, 128)


def test_angle_arc_is_drawn_only_when_it_has_text(qapp):
    from dimensio.geometry import layout
    import math

    def arc_pixel(angle_label):
        dim = Dimension(((100.0, 250.0), (200.0, 250.0), (200.0, 150.0)), ("", ""), angles=(angle_label,))
        [arc] = layout(dim, STYLE.line_width, STYLE.text_size).angles
        mid = math.radians(arc.start + arc.span / 2)
        out = export_image(blank(), Document(style=STYLE, dimensions=[dim]))
        return out.pixelColor(round(arc.center[0] + arc.radius * math.cos(mid)), round(arc.center[1] + arc.radius * math.sin(mid)))

    assert is_red(arc_pixel("90°"))
    assert is_white(arc_pixel(""))


def test_angle_label_gets_a_box_only_when_it_has_text(qapp):
    dim = Dimension(((0.0, 100.0), (100.0, 100.0), (100.0, 0.0)), ("a", "b"), angles=("",))
    assert build_paths(dim, STYLE).angle_boxes == [None]
    from dataclasses import replace

    assert build_paths(replace(dim, angles=("90°",)), STYLE).angle_boxes[0] is not None


def test_level_marker_is_half_filled(qapp):
    from dimensio.geometry import level_layout
    from dimensio.model import Level

    style = Style(2, 100, "#FF0000")  # big enough that the probes sit well inside the triangle
    level = Level((200.0, 250.0), "+1.20")
    tip, left, right = level_layout(level, style.line_width, style.text_size).triangle
    out = export_image(blank(), Document(style=style, dimensions=[level]))
    y = round(left[1] + (tip[1] - left[1]) * 0.4)  # a bit below the triangle's top edge
    assert is_red(out.pixelColor(round(tip[0] - 8), y))  # left half filled
    assert is_white(out.pixelColor(round(tip[0] + 8), y))  # right half open
