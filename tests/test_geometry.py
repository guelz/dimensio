import math

import pytest

from dimensio.geometry import arrow_length, layout, overshoot, reading_angle, text_gap
from dimensio.model import Dimension

W, S = 4.0, 20.0


def cross(u, v):
    return u[0] * v[1] - u[1] * v[0]


def vec(a, b):
    return (b[0] - a[0], b[1] - a[1])


@pytest.mark.parametrize(
    "p, q, expected",
    [
        ((0, 0), (10, 0), 0.0),      # left to right
        ((10, 0), (0, 0), 0.0),      # right to left is flipped, not upside down
        ((0, 0), (0, 10), -90.0),    # vertical down: reads bottom to top
        ((0, 10), (0, 0), -90.0),    # vertical up: reads bottom to top
        ((0, 0), (10, 10), 45.0),    # slopes down to the right
        ((10, 10), (0, 0), 45.0),
        ((0, 0), (10, -10), -45.0),  # slopes up to the right
        ((10, -10), (0, 0), -45.0),
    ],
)
def test_reading_angle(p, q, expected):
    assert reading_angle(p, q) == pytest.approx(expected)


def test_constants():
    assert overshoot(W, S) == 12.0
    assert arrow_length(W, S) == 16.0
    assert text_gap(W, S) == 6.0


def chain():
    # deliberately not collinear (perspective photo)
    return Dimension(((0.0, 0.0), (100.0, 10.0), (220.0, 40.0)), ("a", "b"), (30.0, -100.0))


def test_each_segment_is_parallel_to_its_points_and_shifted_by_offset():
    dim = chain()
    lay = layout(dim, W, S)
    for seg, p, q in zip(lay.segments, dim.points, dim.points[1:]):
        assert seg.start == pytest.approx((p[0] + 30, p[1] - 100))
        assert seg.end == pytest.approx((q[0] + 30, q[1] - 100))
        assert cross(vec(seg.start, seg.end), vec(p, q)) == pytest.approx(0.0, abs=1e-9)


def test_extension_lines_follow_the_drag_direction():
    dim = chain()
    lay = layout(dim, W, S)
    d = dim.offset
    assert len(lay.extension_lines) == 3
    for (start, end), p in zip(lay.extension_lines, dim.points):
        assert start == p
        assert cross(vec(start, end), d) == pytest.approx(0.0, abs=1e-9)
        assert math.dist(start, end) == pytest.approx(math.hypot(*d) + overshoot(W, S))


def test_extension_lines_are_not_forced_perpendicular():
    lay = layout(Dimension(((0.0, 0.0), (100.0, 0.0)), ("x",), (30.0, -100.0)), W, S)
    (start, end) = lay.extension_lines[0]
    direction = vec(start, end)
    assert direction[0] != pytest.approx(0.0)  # oblique, like the drag


def test_no_extension_lines_for_tiny_offset():
    lay = layout(Dimension(((0.0, 0.0), (100.0, 0.0)), ("x",), (1.0, 1.0)), W, S)
    assert lay.extension_lines == ()


def test_text_sits_above_the_line_in_reading_orientation():
    left_to_right = layout(Dimension(((0.0, 50.0), (100.0, 50.0)), ("x",)), W, S).segments[0]
    right_to_left = layout(Dimension(((100.0, 50.0), (0.0, 50.0)), ("x",)), W, S).segments[0]
    vertical = layout(Dimension(((50.0, 0.0), (50.0, 100.0)), ("x",)), W, S).segments[0]
    assert left_to_right.text_anchor == pytest.approx((50.0, 50.0 - text_gap(W, S)))
    assert right_to_left.text_anchor == pytest.approx((50.0, 50.0 - text_gap(W, S)))
    assert vertical.text_anchor == pytest.approx((50.0 - text_gap(W, S), 50.0))
    assert vertical.text_angle == pytest.approx(-90.0)


def test_arrows_point_outward_and_line_stops_at_arrow_bases():
    seg = layout(Dimension(((0.0, 0.0), (100.0, 0.0)), ("x",)), W, S).segments[0]
    (tip_a, la, ra), (tip_b, lb, rb) = seg.arrows
    assert tip_a == (0.0, 0.0) and tip_b == (100.0, 0.0)
    assert la[0] == pytest.approx(16.0) and ra[0] == pytest.approx(16.0)
    assert lb[0] == pytest.approx(84.0) and rb[0] == pytest.approx(84.0)
    assert abs(la[1] - ra[1]) == pytest.approx(2 * 16.0 * math.tan(math.radians(15)))
    assert seg.line_start == pytest.approx((16.0, 0.0))
    assert seg.line_end == pytest.approx((84.0, 0.0))


def test_short_segment_keeps_the_full_line():
    seg = layout(Dimension(((0.0, 0.0), (20.0, 0.0)), ("x",)), W, S).segments[0]
    assert seg.line_start == (0.0, 0.0) and seg.line_end == (20.0, 0.0)


def test_zero_length_segment_does_not_crash():
    lay = layout(Dimension(((5.0, 5.0), (5.0, 5.0)), ("x",), (0.0, 50.0)), W, S)
    seg = lay.segments[0]
    assert seg.text_angle == 0.0
    assert all(math.isfinite(c) for pt in seg.arrows[0] for c in pt)


def test_one_label_per_segment():
    lay = layout(chain(), W, S)
    assert [seg.label for seg in lay.segments] == ["a", "b"]
