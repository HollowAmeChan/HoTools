"""Bone XPBD 端点空间桶焊接的纯宿主契约。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import numpy as np


BONE_XPBD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(BONE_XPBD_ROOT)
OMNINODE = os.path.dirname(PHYSICS_WORLD)
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)


topology = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.bone_xpbd.topology"
)


def _roots(disjoint, count: int) -> tuple[int, ...]:
    return tuple(disjoint.find(index) for index in range(count))


def test_zero_tolerance_uses_exact_coordinate_groups():
    positions = np.asarray((
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (1.0 + 1.0e-12, 0.0, 0.0),
        (3.0, 0.0, 0.0),
    ), dtype=np.float64)
    roots = _roots(topology._weld_endpoint_groups(positions, 0.0), len(positions))
    assert roots[1] == roots[2]
    assert roots[4] != roots[1]


def test_positive_tolerance_scans_neighbor_cells_deterministically():
    positions = np.asarray((
        (-10.0, 0.0, 0.0),
        (0.0009, 0.0, 0.0),
        (0.0011, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (0.0022, 0.0, 0.0),
        (20.0, 0.0, 0.0),
    ), dtype=np.float64)
    first = _roots(topology._weld_endpoint_groups(positions, 0.001), len(positions))
    second = _roots(topology._weld_endpoint_groups(positions, 0.001), len(positions))
    assert first == second
    assert first[1] == first[2]
    assert first[4] != first[2]


def test_same_bone_endpoints_are_not_directly_welded():
    positions = np.asarray((
        (0.0, 0.0, 0.0),
        (0.0005, 0.0, 0.0),
    ), dtype=np.float64)
    roots = _roots(topology._weld_endpoint_groups(positions, 0.001), 2)
    assert roots[0] != roots[1]


def test_same_bone_endpoints_cannot_collapse_through_third_endpoint():
    positions = np.asarray((
        (0.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
    ), dtype=np.float64)
    roots = _roots(topology._weld_endpoint_groups(positions, 1.1), 4)
    assert roots[0] != roots[1]
    assert roots[2] in {roots[0], roots[1]}


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"Bone XPBD spatial weld: {len(tests)} passed")
