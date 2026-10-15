import pytest

from dimensio.model import (
    DEFAULT_COLOR,
    Dimension,
    Document,
    ImageInfo,
    SidecarError,
    Style,
    file_sha256,
    from_json,
    is_hex_color,
    load_sidecar,
    output_path,
    save_sidecar,
    sidecar_path,
)


def test_style_for_image_scales_with_diagonal():
    style = Style.for_image(4032, 3024)  # diagonal 5040
    assert style == Style(line_width=13, text_size=101, color=DEFAULT_COLOR)


def test_style_line_width_has_a_floor():
    assert Style.for_image(100, 100).line_width == 2


def test_dimension_needs_two_points():
    with pytest.raises(ValueError):
        Dimension(((0.0, 0.0),), ())


def test_dimension_needs_one_label_per_segment():
    with pytest.raises(ValueError):
        Dimension(((0.0, 0.0), (1.0, 0.0), (2.0, 0.0)), ("a",))


def test_dimension_new_has_empty_labels_and_no_offset():
    dim = Dimension.new([(0, 0), (10, 0), (20, 5)])
    assert dim.points == ((0.0, 0.0), (10.0, 0.0), (20.0, 5.0))
    assert dim.labels == ("", "")
    assert dim.offset == (0.0, 0.0)


def test_file_names(tmp_path):
    photo = tmp_path / "photo.jpg"
    assert sidecar_path(photo) == tmp_path / "photo.jpg.dims.json"
    assert output_path(photo) == tmp_path / "photo_dims.png"


def test_file_sha256(tmp_path):
    path = tmp_path / "abc"
    path.write_bytes(b"abc")
    assert file_sha256(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_image_info_matches_on_size_and_hash():
    a = ImageInfo("p.jpg", 10, 20, "aa")
    assert a.matches(ImageInfo("renamed.jpg", 10, 20, "aa"))
    assert not a.matches(ImageInfo("p.jpg", 10, 20, "bb"))
    assert not a.matches(ImageInfo("p.jpg", 20, 10, "aa"))


def make_doc():
    return Document(
        style=Style(13, 101, "#FFC400"),
        dimensions=[
            Dimension(((812.0, 1440.5), (2930.0, 1402.0)), ("284 cm",), (-20.0, -310.0)),
            Dimension(((100.0, 2900.0), (900.0, 2890.0), (1700.0, 2880.0)), ("70 cm", ""), (0.0, 200.0)),
        ],
        image=ImageInfo("photo.jpg", 4032, 3024, "ab" * 32),
    )


def test_roundtrip(tmp_path):
    path = tmp_path / "photo.jpg.dims.json"
    save_sidecar(make_doc(), path)
    assert load_sidecar(path) == make_doc()
    assert not list(tmp_path.glob("*.tmp"))


def test_roundtrip_keeps_unicode_unescaped(tmp_path):
    doc = make_doc()
    doc.dimensions[0] = Dimension(((0.0, 0.0), (1.0, 0.0)), ('2½" × 3 m² Ø',))
    path = tmp_path / "x.dims.json"
    save_sidecar(doc, path)
    assert '2½\\" × 3 m² Ø' in path.read_text(encoding="utf-8")
    assert load_sidecar(path).dimensions[0].labels == ('2½" × 3 m² Ø',)


def test_roundtrip_without_image_info(tmp_path):
    doc = Document(style=Style(2, 10))
    path = tmp_path / "x.dims.json"
    save_sidecar(doc, path)
    assert load_sidecar(path) == doc


def test_unknown_version_is_rejected():
    with pytest.raises(SidecarError, match="version"):
        from_json({"version": 99, "style": {}, "dimensions": []})


def test_not_an_object_is_rejected():
    with pytest.raises(SidecarError):
        from_json([1, 2])


def test_invalid_json_is_rejected(tmp_path):
    path = tmp_path / "x.dims.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(SidecarError):
        load_sidecar(path)


def test_label_count_mismatch_is_rejected():
    data = {
        "version": 1,
        "style": {"line_width": 2, "text_size": 10, "color": "#FFC400"},
        "dimensions": [{"points": [[0, 0], [1, 0]], "labels": [], "offset": [0, 0]}],
    }
    with pytest.raises(SidecarError):
        from_json(data)


def test_bad_color_is_rejected():
    data = {"version": 1, "style": {"line_width": 2, "text_size": 10, "color": "red"}, "dimensions": []}
    with pytest.raises(SidecarError):
        from_json(data)


@pytest.mark.parametrize("value, ok", [("#FFC400", True), ("#ffc400", True), ("FFC400", False), ("#FFC40", False), (None, False)])
def test_is_hex_color(value, ok):
    assert is_hex_color(value) is ok


@pytest.mark.parametrize(
    "style, points",
    [
        ({"line_width": 0, "text_size": 10, "color": "#FFC400"}, [[0, 0], [1, 0]]),
        ({"line_width": 2, "text_size": -1, "color": "#FFC400"}, [[0, 0], [1, 0]]),
        ({"line_width": float("inf"), "text_size": 10, "color": "#FFC400"}, [[0, 0], [1, 0]]),
        ({"line_width": 2, "text_size": 10, "color": "#FFC400"}, [[0, float("nan")], [1, 0]]),
    ],
)
def test_non_finite_or_non_positive_values_are_rejected(style, points):
    data = {"version": 1, "style": style, "dimensions": [{"points": points, "labels": ["x"], "offset": [0, 0]}]}
    with pytest.raises(SidecarError):
        from_json(data)


def test_overflowing_image_size_is_rejected():
    data = {
        "version": 1,
        "image": {"file": "p.jpg", "width": float("inf"), "height": 10, "sha256": "aa"},
        "style": {"line_width": 2, "text_size": 10, "color": "#FFC400"},
        "dimensions": [],
    }
    with pytest.raises(SidecarError):
        from_json(data)
