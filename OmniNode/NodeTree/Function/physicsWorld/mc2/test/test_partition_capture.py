"""E1 tests for the one-read MeshCloth capture boundary."""

from __future__ import annotations

import importlib
import os
import sys
import types

import numpy as np


MC2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MC2_ROOT)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = os.path.dirname(NODETREE)
HOTOOLS = os.path.dirname(OMNINODE)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", MC2_ROOT),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups", os.path.join(MC2_ROOT, "setups")),
    (
        "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth",
        os.path.join(MC2_ROOT, "setups", "mesh_cloth"),
    ),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

topology = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
capture = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.source_capture"
)


class _Source:
    def __init__(self, pointer: int = 101):
        self._pointer = pointer
        self.matrix_world = (
            (2.0, 0.0, 0.0, 4.0),
            (0.0, -3.0, 0.0, 5.0),
            (0.0, 0.0, 1.0, 6.0),
            (0.0, 0.0, 0.0, 1.0),
        )

    def as_pointer(self):
        return self._pointer


def _raw(*, pin_enabled=True, pin_name="pins", pin_weights=(1.0, 0.0, 0.0)):
    return topology.MC2MeshRawSnapshot(
        source_pointer=101,
        mesh_pointer=202,
        positions=np.asarray(((0, 0, 0), (1, 0, 0), (0, 1, 0)), dtype=np.float32),
        normals=np.asarray(((0, 0, 1),) * 3, dtype=np.float32),
        edges=np.asarray(((0, 1), (1, 2), (2, 0)), dtype=np.int32),
        triangles=np.asarray(((0, 1, 2),), dtype=np.int32),
        triangle_loops=np.asarray(((0, 1, 2),), dtype=np.int32),
        polygon_loop_totals=np.asarray((3,), dtype=np.int32),
        loop_vertices=np.asarray((0, 1, 2), dtype=np.int32),
        loop_uvs=np.asarray(((0, 0), (1, 0), (0, 1)), dtype=np.float32),
        pin_weights=np.asarray(pin_weights, dtype=np.float32),
        radius_multipliers=np.asarray((1.0, 0.5, 0.25), dtype=np.float32),
        pin_enabled=pin_enabled,
        pin_name=pin_name,
        radius_group_name="radius",
        has_uv=True,
    )


def _capture(raw=None, source=None):
    return capture.capture_mc2_mesh_partition_static_snapshot(
        source or _Source(),
        raw or _raw(),
        partition_id="partition:single",
        source_identity="source:single",
        source_revision="revision:single",
        output_target_id="output:single",
    )


def test_capture_freezes_arrays_and_row_major_source_matrix() -> None:
    result = _capture()
    assert result.vertex_count == 3
    assert result.source_bind_matrix.tolist() == [
        [2.0, 0.0, 0.0, 4.0],
        [0.0, -3.0, 0.0, 5.0],
        [0.0, 0.0, 1.0, 6.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    assert result.source_element_ids.tolist() == [0, 1, 2]
    assert not result.local_positions.flags.writeable
    assert not result.source_bind_matrix.flags.writeable


def test_pin_enabled_without_group_means_every_particle_is_fixed() -> None:
    result = _capture(_raw(pin_name="", pin_weights=()))
    assert result.pin_present is True
    assert result.pin_weights.tolist() == [1.0, 1.0, 1.0]


def test_pin_disabled_keeps_optional_weights_explicitly_empty() -> None:
    result = _capture(_raw(pin_enabled=False, pin_name="", pin_weights=()))
    assert result.pin_present is False
    assert result.pin_weights.shape == (0,)


def test_capture_rejects_snapshot_from_another_object() -> None:
    try:
        _capture(source=_Source(pointer=999))
    except ValueError as exc:
        assert "does not belong" in str(exc)
    else:
        raise AssertionError("cross-object raw snapshot was accepted")


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 partition capture: {len(TESTS)} passed")
