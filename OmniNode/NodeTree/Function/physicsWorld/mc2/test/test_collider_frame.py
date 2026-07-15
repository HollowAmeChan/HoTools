import os
import sys
from types import SimpleNamespace

import numpy as np

MC2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, MC2_ROOT)

from collider_frame import build_mc2_collider_frame


class _Object:
    def __init__(self, pointer, groups=0):
        self._pointer = pointer
        self.hotools_mesh_collision = SimpleNamespace(collided_by_groups=groups)

    def as_pointer(self):
        return self._pointer


def test_shared_snapshot_packing_and_previous_pose():
    source = _Object(10, groups=0b11)
    external = _Object(20)
    world = SimpleNamespace(
        collider_snapshot={
            "frame": 7,
            "colliders": [
                {"key": "sphere", "type": "SPHERE", "owner": external, "primary_group": 1, "center": (1, 2, 3), "radius": 0.5},
                {"key": "capsule", "type": "CAPSULE", "owner": external, "primary_group": 2, "center": (0, 0, 0), "segment_a": (0, -1, 0), "segment_b": (0, 1, 0), "radius": 0.25},
                {"key": "plane", "type": "PLANE", "owner": external, "primary_group": 1, "center": (0, 0, 0), "normal": (0, 0, 2)},
                {"key": "box", "type": "BOX", "owner": external, "primary_group": 1, "center": (0, 0, 0), "box_axis_x": (2, 0, 0), "box_axis_y": (0, 3, 0), "box_axis_z": (0, 0, 4)},
                {"key": "self", "type": "SPHERE", "owner": source, "primary_group": 1, "center": (0, 0, 0), "radius": 1},
                {"key": "masked", "type": "SPHERE", "owner": external, "primary_group": 3, "center": (0, 0, 0), "radius": 1},
            ],
        },
        previous_collider_snapshot={"colliders": {"sphere": {"center": (0, 2, 3), "segment_a": (0, 2, 3), "segment_b": (0, 2, 3)}}},
    )
    result = build_mc2_collider_frame(world, source)
    assert result.frame == 7
    assert result.collider_count == 4
    assert result.collider_types.tolist() == [0, 1, 2, 3]
    assert result.collider_group_bits.tolist() == [1, 2, 1, 1]
    np.testing.assert_allclose(result.collider_old_centers[0], (0, 2, 3))
    np.testing.assert_allclose(result.collider_segment_a[2], (0, 0, 1))
    assert result.collider_radii[3] == 4.0
    assert all(not value.flags.writeable for value in (
        result.collider_types,
        result.collider_centers,
        result.collider_old_centers,
        result.collider_radii,
    ))


def test_zero_group_mask_returns_typed_empty_arrays():
    result = build_mc2_collider_frame(
        SimpleNamespace(collider_snapshot={"frame": 3, "colliders": []}, previous_collider_snapshot=None),
        _Object(10, groups=0),
    )
    assert result.collider_count == 0
    assert result.collider_centers.shape == (0, 3)
    assert result.collider_types.dtype == np.int32
    assert result.collider_radii.dtype == np.float32


if __name__ == "__main__":
    test_shared_snapshot_packing_and_previous_pose()
    test_zero_group_mask_returns_typed_empty_arrays()
    print("PASS MC2 shared collider frame contract")
