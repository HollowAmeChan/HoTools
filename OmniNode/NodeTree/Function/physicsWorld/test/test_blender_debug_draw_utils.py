"""Blender-background checks for shared physics debug geometry helpers."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import mathutils


MODULE_PATH = Path(__file__).parents[1] / "utils" / "debug_draw.py"
SPEC = importlib.util.spec_from_file_location("hotools_debug_draw_utils_test", MODULE_PATH)
debug_draw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(debug_draw)


def _finite(points):
    return all(math.isfinite(value) for point in points for value in point)


points = []
debug_draw.add_point(points, (1.0, 2.0, 3.0))
assert points == [(1.0, 2.0, 3.0)]
debug_draw.draw_point_batches(())

arrow = []
debug_draw.add_arrow_lines(arrow, (0.0, 0.0, 0.0), (0.0, 0.0, 2.0))
assert len(arrow) == 10 and arrow[0] == (0.0, 0.0, 0.0)
assert arrow[1] == (0.0, 0.0, 2.0) and _finite(arrow)

arc = []
debug_draw.add_arc_lines(
    arc,
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    2.0,
    0.0,
    math.pi / 2.0,
    segments=4,
)
assert len(arc) == 8 and _finite(arc)
for point in arc:
    assert abs(mathutils.Vector(point).length - 2.0) <= 1.0e-6

spring = []
debug_draw.add_spring_lines(
    spring,
    (0.0, 0.0, 0.0),
    (0.0, 2.0, 0.0),
    radius=0.1,
    turns=3,
    segments_per_turn=4,
)
assert spring[0] == (0.0, 0.0, 0.0)
assert spring[-1] == (0.0, 2.0, 0.0) and _finite(spring)

basis = []
debug_draw.add_basis_lines(
    basis,
    (1.0, 2.0, 3.0),
    mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)),
    0.5,
)
assert len(basis) == 6 and basis[0] == (1.0, 2.0, 3.0)
assert basis[1] == (1.5, 2.0, 3.0) and _finite(basis)

print("Physics debug draw utils: PASS")
