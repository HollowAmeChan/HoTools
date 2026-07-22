import os
import sys
from types import SimpleNamespace

import numpy as np

MC2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, MC2_ROOT)

from collider_frame import build_mc2_collider_frame, build_mc2_domain_collider_frame


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
    assert result.source_pointer == 10
    assert result.collider_count == 4
    assert result.collider_keys == ("sphere", "capsule", "plane", "box")
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


def test_bone_source_uses_explicit_group_mask_and_excludes_armature_owner():
    armature = _Object(30)
    external = _Object(40)
    world = SimpleNamespace(
        collider_snapshot={
            "frame": 4,
            "colliders": [
                {"key": "self", "type": "SPHERE", "owner": armature, "primary_group": 2, "center": (0, 0, 0), "radius": 1},
                {"key": "other", "type": "SPHERE", "owner": external, "primary_group": 2, "center": (1, 0, 0), "radius": 1},
                {"key": "capsule", "type": "CAPSULE", "owner": external, "primary_group": 2, "center": (2, 0, 0), "segment_a": (2, -1, 0), "segment_b": (2, 1, 0), "radius": 1},
            ],
        },
        previous_collider_snapshot=None,
    )
    result = build_mc2_collider_frame(
        world,
        {"armature": armature, "root_bone": "Root"},
        collided_by_groups=2,
        allowed_types=frozenset(("SPHERE",)),
    )
    assert result.collided_by_groups == 2
    assert result.collider_count == 1
    assert result.source_pointer == 30
    assert result.collider_keys == ("other",)
    assert result.collider_group_bits.tolist() == [2]


def test_domain_frame_excludes_all_partition_owners_without_group_prefilter():
    sleeve = _Object(10, groups=1)
    coat = _Object(11, groups=2)
    external = _Object(20)
    world = SimpleNamespace(
        collider_snapshot={
            "frame": 8,
            "colliders": [
                {"key": "sleeve", "type": "SPHERE", "owner": sleeve, "primary_group": 1, "center": (0, 0, 0), "radius": 1},
                {"key": "coat", "type": "SPHERE", "owner": coat, "primary_group": 2, "center": (0, 0, 0), "radius": 1},
                {"key": "group1", "type": "SPHERE", "owner": external, "primary_group": 1, "center": (1, 0, 0), "radius": 1},
                {"key": "group2", "type": "SPHERE", "owner": external, "primary_group": 2, "center": (2, 0, 0), "radius": 1},
                {"key": "group3", "type": "SPHERE", "owner": external, "primary_group": 3, "center": (3, 0, 0), "radius": 1},
            ],
        },
        previous_collider_snapshot=None,
    )
    first = build_mc2_domain_collider_frame(world, (sleeve, coat))
    reordered = build_mc2_domain_collider_frame(world, (coat, sleeve))
    assert first.frame == 8
    assert first.source_pointers == (10, 11)
    assert first.collider_keys == ("group1", "group2", "group3")
    assert first.collider_group_bits.tolist() == [1, 2, 4]
    assert first.frame_signature == reordered.frame_signature
    assert set(first.native_mapping()) == {
        "collider_types", "collider_group_bits", "collider_centers",
        "collider_segment_a", "collider_segment_b", "collider_old_centers",
        "collider_old_segment_a", "collider_old_segment_b", "collider_radii",
    }
    assert all(not value.flags.writeable for value in first.native_mapping().values())


def test_domain_frame_owns_immutable_array_copies():
    center = np.asarray(((1.0, 2.0, 3.0),), dtype=np.float32)
    world = SimpleNamespace(
        collider_snapshot={
            "frame": 9,
            "colliders": [
                {"key": "sphere", "type": "SPHERE", "owner": _Object(20), "primary_group": 1, "center": center[0], "radius": 1},
            ],
        },
        previous_collider_snapshot=None,
    )
    result = build_mc2_domain_collider_frame(world, (_Object(10),))
    center[0, 0] = 99.0
    np.testing.assert_array_equal(result.collider_centers, ((1.0, 2.0, 3.0),))


if __name__ == "__main__":
    test_shared_snapshot_packing_and_previous_pose()
    test_zero_group_mask_returns_typed_empty_arrays()
    test_bone_source_uses_explicit_group_mask_and_excludes_armature_owner()
    test_domain_frame_excludes_all_partition_owners_without_group_prefilter()
    test_domain_frame_owns_immutable_array_copies()
    print("PASS MC2 shared collider frame contract")
