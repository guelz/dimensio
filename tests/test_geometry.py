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


def test_zero_line_width_with_zero_offset_does_not_divide_by_zero():
    lay = layout(Dimension(((0.0, 0.0), (100.0, 0.0)), ("x",)), 0.0, S)
    assert lay.extension_lines == ()


def corner(offset=(0.0, 0.0), angle="90°"):
    # right angle at (100, 0): legs towards (0, 0) and (100, 100)
    return Dimension(((0.0, 0.0), (100.0, 0.0), (100.0, 100.0)), ("a", "b"), offset, angles=(angle,))


def test_two_point_dimension_has_no_angles():
    assert layout(Dimension(((0.0, 0.0), (100.0, 0.0)), ("x",)), W, S).angles == ()


def test_angle_arc_sits_on_the_corner_and_spans_the_smaller_angle():
    [arc] = layout(corner(), W, S).angles
    assert arc.center == pytest.approx((100.0, 0.0))
    assert abs(arc.span) == pytest.approx(90.0)
    assert arc.radius == pytest.approx(min(0.4 * 100.0, 2.5 * S))
    bisector = math.radians(arc.start + arc.span / 2)
    assert (math.cos(bisector), math.sin(bisector)) == pytest.approx((-math.sqrt(0.5), math.sqrt(0.5)))  # inside the corner
    assert arc.label == "90°"


def test_angle_arc_follows_the_dragged_line():
    [arc] = layout(corner(offset=(20.0, -30.0)), W, S).angles
    assert arc.center == pytest.approx((120.0, -30.0))


def test_angle_text_is_outside_the_arc_on_the_bisector():
    [arc] = layout(corner(), W, S).angles
    bisector = math.radians(arc.start + arc.span / 2)
    distance = arc.radius + text_gap(W, S) + 0.6 * S
    expected = (100.0 + distance * math.cos(bisector), 0.0 + distance * math.sin(bisector))
    assert arc.text_center == pytest.approx(expected)
    assert -90.0 <= arc.text_angle < 90.0


def test_straight_chain_gives_a_half_circle_and_no_crash_on_zero_legs():
    [arc] = layout(Dimension(((0.0, 0.0), (100.0, 0.0), (200.0, 0.0)), ("a", "b"), angles=("180°",)), W, S).angles
    assert abs(arc.span) == pytest.approx(180.0)
    [arc] = layout(Dimension(((0.0, 0.0), (0.0, 0.0), (10.0, 0.0)), ("a", "b"), angles=("x",)), W, S).angles
    assert math.isfinite(arc.start) and math.isfinite(arc.span) and arc.radius == 0.0


def test_level_marker_points_at_the_spot_and_writes_right_of_it():
    from dimensio.geometry import level_layout
    from dimensio.model import Level

    lay = level_layout(Level((100.0, 200.0), "+1.20"), W, S)
    tip, left, right = lay.triangle
    assert tip == (100.0, 200.0) and lay.leader is None
    assert left[1] == right[1] < 200.0  # triangle sits above the spot, pointing down
    assert (right[0] - left[0]) / 2 == pytest.approx((200.0 - left[1]) / math.sqrt(3))  # 60° triangle
    assert lay.line_start[1] == 200.0 and lay.line_start[0] < left[0]
    assert lay.text_anchor[0] > right[0] and lay.text_anchor[1] < 200.0


def test_dragged_level_marker_gets_a_leader_to_the_spot():
    from dimensio.geometry import level_layout
    from dimensio.model import Level

    lay = level_layout(Level((100.0, 200.0), "x", (40.0, -80.0)), W, S)
    assert lay.triangle[0] == (140.0, 120.0)
    assert lay.leader == ((100.0, 200.0), (140.0, 120.0))
