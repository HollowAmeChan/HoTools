"""Immutable MC2 collider arrays derived from the shared World snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

import numpy as np


_TYPE_CODES = {"SPHERE": 0, "CAPSULE": 1, "PLANE": 2, "BOX": 3}
_EPSILON = 1.0e-8


def _array(values, dtype, shape) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype).reshape(shape)
    result.flags.writeable = False
    return result


def _vec3(value) -> np.ndarray | None:
    if value is None:
        return None
    try:
        result = np.asarray(tuple(value), dtype=np.float32).reshape(3)
    except (TypeError, ValueError):
        return None
    if not np.all(np.isfinite(result)):
        return None
    return result


def _pointer(value) -> int:
    try:
        return int(value.as_pointer())
    except Exception:
        return id(value) if value is not None else 0


def _box_signed_half_z(axis_x, axis_y, axis_z) -> float | None:
    if axis_x is None or axis_y is None or axis_z is None:
        return None
    x_length = float(np.linalg.norm(axis_x))
    y_length = float(np.linalg.norm(axis_y))
    z_length = float(np.linalg.norm(axis_z))
    if min(x_length, y_length, z_length) <= _EPSILON:
        return None
    cross = np.cross(axis_x / x_length, axis_y / y_length)
    cross_length = float(np.linalg.norm(cross))
    if cross_length <= _EPSILON:
        return None
    signed = float(np.dot(axis_z, cross / cross_length))
    return signed if abs(signed) > _EPSILON else z_length


@dataclass(frozen=True)
class MC2ColliderFrameSpec:
    frame: int
    collided_by_groups: int
    collider_types: np.ndarray
    collider_group_bits: np.ndarray
    collider_centers: np.ndarray
    collider_segment_a: np.ndarray
    collider_segment_b: np.ndarray
    collider_old_centers: np.ndarray
    collider_old_segment_a: np.ndarray
    collider_old_segment_b: np.ndarray
    collider_radii: np.ndarray
    frame_signature: str

    @property
    def collider_count(self) -> int:
        return int(self.collider_types.shape[0])

    def debug_dict(self) -> dict:
        return {
            "frame": self.frame,
            "collided_by_groups": self.collided_by_groups,
            "collider_count": self.collider_count,
            "frame_signature": self.frame_signature,
        }


def build_mc2_collider_frame(world, source_obj) -> MC2ColliderFrameSpec:
    snapshot = getattr(world, "collider_snapshot", None)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    previous = getattr(world, "previous_collider_snapshot", None)
    previous = previous.get("colliders", {}) if isinstance(previous, dict) else {}
    previous = previous if isinstance(previous, dict) else {}
    properties = getattr(source_obj, "hotools_mesh_collision", None)
    collided_by_groups = max(
        0,
        min(0xFFFF, int(getattr(properties, "collided_by_groups", 0) or 0)),
    )
    source_pointer = _pointer(source_obj)

    types = []
    group_bits = []
    centers = []
    segment_a_values = []
    segment_b_values = []
    old_centers = []
    old_segment_a_values = []
    old_segment_b_values = []
    radii = []
    for collider in snapshot.get("colliders") or ():
        if not isinstance(collider, dict) or _pointer(collider.get("owner")) == source_pointer:
            continue
        collider_type = str(collider.get("type", "SPHERE") or "SPHERE").upper()
        type_code = _TYPE_CODES.get(collider_type)
        center = _vec3(collider.get("center"))
        if type_code is None or center is None:
            continue
        group = max(1, min(16, int(collider.get("primary_group", 1) or 1)))
        group_bit = 1 << (group - 1)
        if collided_by_groups & group_bit == 0:
            continue

        radius = max(0.0, float(collider.get("radius", 0.0) or 0.0))
        if collider_type == "CAPSULE":
            segment_a = _vec3(collider.get("segment_a"))
            segment_b = _vec3(collider.get("segment_b"))
            if radius <= _EPSILON or segment_a is None or segment_b is None:
                continue
        elif collider_type == "PLANE":
            segment_a = _vec3(collider.get("normal"))
            if segment_a is None or float(np.linalg.norm(segment_a)) <= _EPSILON:
                continue
            segment_a = segment_a / np.linalg.norm(segment_a)
            segment_b = center
            radius = 0.0
        elif collider_type == "BOX":
            segment_a = _vec3(collider.get("box_axis_x"))
            segment_b = _vec3(collider.get("box_axis_y"))
            radius_value = _box_signed_half_z(
                segment_a,
                segment_b,
                _vec3(collider.get("box_axis_z")),
            )
            if radius_value is None:
                continue
            radius = radius_value
        else:
            if radius <= _EPSILON:
                continue
            segment_a = center
            segment_b = center

        key = str(collider.get("key") or collider.get("source_key") or "")
        old = previous.get(key, {}) if key else {}
        old_center = _vec3(old.get("center")) if isinstance(old, dict) else None
        old_a = _vec3(old.get("segment_a")) if isinstance(old, dict) else None
        old_b = _vec3(old.get("segment_b")) if isinstance(old, dict) else None
        types.append(type_code)
        group_bits.append(group_bit)
        centers.append(center)
        segment_a_values.append(segment_a)
        segment_b_values.append(segment_b)
        old_centers.append(center if old_center is None else old_center)
        old_segment_a_values.append(segment_a if old_a is None else old_a)
        old_segment_b_values.append(segment_b if old_b is None else old_b)
        radii.append(radius)

    count = len(types)
    arrays = (
        _array(types, np.int32, (count,)),
        _array(group_bits, np.int32, (count,)),
        _array(centers, np.float32, (count, 3)),
        _array(segment_a_values, np.float32, (count, 3)),
        _array(segment_b_values, np.float32, (count, 3)),
        _array(old_centers, np.float32, (count, 3)),
        _array(old_segment_a_values, np.float32, (count, 3)),
        _array(old_segment_b_values, np.float32, (count, 3)),
        _array(radii, np.float32, (count,)),
    )
    digest = hashlib.sha256()
    digest.update(np.asarray((int(snapshot.get("frame", -1) or -1), collided_by_groups), dtype=np.int64).tobytes())
    for value in arrays:
        digest.update(value.tobytes())
    return MC2ColliderFrameSpec(
        int(snapshot.get("frame", -1) or -1),
        collided_by_groups,
        *arrays,
        digest.hexdigest(),
    )


__all__ = ["MC2ColliderFrameSpec", "build_mc2_collider_frame"]
