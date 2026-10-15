"""Pure geometry for dimension drawings. Image pixel coordinates, y axis pointing down."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import Dimension, Point

ARROW_HALF_ANGLE = math.radians(15)
ANGLE_RADIUS_LEG = 0.4  # arc radius as a share of the shorter leg ...
ANGLE_RADIUS_TEXT = 2.5  # ... but at most this many text sizes

Triangle = tuple[Point, Point, Point]


def overshoot(w: float, s: float) -> float:
    return max(3 * w, 0.25 * s)


def arrow_length(w: float, s: float) -> float:
    return max(4 * w, 0.6 * s)


def text_gap(w: float, s: float) -> float:
    return w / 2 + 0.2 * s


def _readable(angle: float) -> float:
    """Turn a text angle by 180 when needed so text is never upside down. Result in [-90, 90)."""
    angle = (angle + 180) % 360 - 180
    if angle >= 90:
        angle -= 180
    elif angle < -90:
        angle += 180
    return angle


def reading_angle(p: Point, q: Point) -> float:
    """Angle of p->q in degrees (clockwise positive), turned by 180 so text is never upside down.

    The result lies in [-90, 90), so a vertical line reads bottom to top.
    """
    return _readable(math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])))


@dataclass(frozen=True)
class SegmentLayout:
    start: Point  # dimension line ends, offset applied
    end: Point
    line_start: Point  # visible line, shortened to the arrow bases when there is room
    line_end: Point
    arrows: tuple[Triangle, Triangle]  # (tip, left, right) at start and at end
    label: str
    text_anchor: Point  # bottom-centre of the label
    text_angle: float  # degrees, as for QPainter.rotate


@dataclass(frozen=True)
class AngleLayout:
    center: Point  # the corner, offset applied (the arc follows the dragged line)
    radius: float
    start: float  # degrees towards the previous point (clockwise positive, like atan2 with y down)
    span: float  # signed sweep to the next point, |span| <= 180 (the smaller angle)
    label: str
    text_center: Point  # centre of the label, just outside the middle of the arc
    text_angle: float


@dataclass(frozen=True)
class Layout:
    segments: tuple[SegmentLayout, ...]
    extension_lines: tuple[tuple[Point, Point], ...]
    angles: tuple[AngleLayout, ...] = ()


def _unit(p: Point, q: Point) -> Point:
    dx, dy = q[0] - p[0], q[1] - p[1]
    length = math.hypot(dx, dy)
    return (1.0, 0.0) if length < 1e-9 else (dx / length, dy / length)


def _arrow(tip: Point, ux: float, uy: float, length: float) -> Triangle:
    """Arrowhead with its tip at `tip`, opening along (ux, uy)."""
    half = length * math.tan(ARROW_HALF_ANGLE)
    bx, by = tip[0] + ux * length, tip[1] + uy * length
    nx, ny = -uy, ux
    return (tip, (bx + nx * half, by + ny * half), (bx - nx * half, by - ny * half))


def layout(dim: Dimension, line_width: float, text_size: float) -> Layout:
    w, s = line_width, text_size
    dx, dy = dim.offset
    d_len = math.hypot(dx, dy)

    extension_lines: tuple[tuple[Point, Point], ...] = ()
    if d_len > 0 and d_len >= w:
        ux, uy = dx / d_len, dy / d_len
        o = overshoot(w, s)
        extension_lines = tuple(((px, py), (px + dx + ux * o, py + dy + uy * o)) for px, py in dim.points)

    arrow_len = arrow_length(w, s)
    gap = text_gap(w, s)
    segments = []
    for p, q, label in zip(dim.points, dim.points[1:], dim.labels):
        a = (p[0] + dx, p[1] + dy)
        b = (q[0] + dx, q[1] + dy)
        ux, uy = _unit(a, b)
        if math.dist(a, b) > 2 * arrow_len:
            line_start = (a[0] + ux * arrow_len, a[1] + uy * arrow_len)
            line_end = (b[0] - ux * arrow_len, b[1] - uy * arrow_len)
        else:
            line_start, line_end = a, b
        angle = reading_angle(a, b)
        rad = math.radians(angle)
        up = (math.sin(rad), -math.cos(rad))  # "up" in the label's reading frame
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        segments.append(
            SegmentLayout(
                start=a,
                end=b,
                line_start=line_start,
                line_end=line_end,
                arrows=(_arrow(a, ux, uy, arrow_len), _arrow(b, -ux, -uy, arrow_len)),
                label=label,
                text_anchor=(mid[0] + up[0] * gap, mid[1] + up[1] * gap),
                text_angle=angle,
            )
        )

    angles = []
    for i, label in enumerate(dim.angles, start=1):
        c = (dim.points[i][0] + dx, dim.points[i][1] + dy)
        prev = (dim.points[i - 1][0] + dx, dim.points[i - 1][1] + dy)
        nxt = (dim.points[i + 1][0] + dx, dim.points[i + 1][1] + dy)
        u1, u2 = _unit(c, prev), _unit(c, nxt)
        start = math.degrees(math.atan2(u1[1], u1[0]))
        span = (math.degrees(math.atan2(u2[1], u2[0])) - start + 180) % 360 - 180
        radius = min(ANGLE_RADIUS_LEG * min(math.dist(c, prev), math.dist(c, nxt)), ANGLE_RADIUS_TEXT * s)
        mid = math.radians(start + span / 2)
        reach = radius + gap + 0.6 * s
        angles.append(
            AngleLayout(
                center=c,
                radius=radius,
                start=start,
                span=span,
                label=label,
                text_center=(c[0] + reach * math.cos(mid), c[1] + reach * math.sin(mid)),
                text_angle=_readable(math.degrees(mid) + 90),
            )
        )
    return Layout(tuple(segments), extension_lines, tuple(angles))
