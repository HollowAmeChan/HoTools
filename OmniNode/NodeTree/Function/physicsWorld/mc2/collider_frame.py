"""Immutable MC2 collider arrays derived from the shared World snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

import numpy as np


_TYPE_CODES = {"SPHERE": 0, "CAPSULE": 1, "PLANE": 2, "BOX": 3}
_EPSILON = 1.0e-8


def _array(values, dtype, shape) -> np.ndarray:
    result = np.array(values, dtype=dtype, order="C", copy=True).reshape(shape)
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
    source_pointer: int
    collider_keys: tuple[str, ...]
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
            "source_pointer": self.source_pointer,
            "collider_keys": self.collider_keys,
            "collider_count": self.collider_count,
            "frame_signature": self.frame_signature,
        }


@dataclass(frozen=True)
class MC2DomainColliderFrameSpec:
    """One unfiltered external collider table for a compiled particle domain."""

    frame: int
    source_pointers: tuple[int, ...]
    collider_keys: tuple[str, ...]
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

    def __post_init__(self) -> None:
        if type(self.frame) is not int:
            raise TypeError("domain collider frame must be an integer")
        pointers = tuple(int(value) for value in self.source_pointers)
        if (
            not pointers
            or pointers != tuple(sorted(set(pointers)))
            or any(value <= 0 for value in pointers)
        ):
            raise ValueError("domain collider source pointers must be sorted unique positives")
        keys = tuple(str(value) for value in self.collider_keys)
        count = len(keys)
        arrays = (
            _array(self.collider_types, np.int32, (count,)),
            _array(self.collider_group_bits, np.int32, (count,)),
            _array(self.collider_centers, np.float32, (count, 3)),
            _array(self.collider_segment_a, np.float32, (count, 3)),
            _array(self.collider_segment_b, np.float32, (count, 3)),
            _array(self.collider_old_centers, np.float32, (count, 3)),
            _array(self.collider_old_segment_a, np.float32, (count, 3)),
            _array(self.collider_old_segment_b, np.float32, (count, 3)),
            _array(self.collider_radii, np.float32, (count,)),
        )
        if not all(np.all(np.isfinite(value)) for value in arrays):
            raise ValueError("domain collider arrays must be finite")
        types, groups, *_vectors, radii = arrays
        if np.any((types < 0) | (types > 3)):
            raise ValueError("domain collider types must be in 0..3")
        if np.any((groups <= 0) | ((groups & (groups - 1)) != 0)):
            raise ValueError("domain collider groups must contain one positive bit")
        if np.any(radii < 0.0):
            raise ValueError("domain collider radii cannot be negative")
        signature = str(self.frame_signature or "")
        if len(signature) != 64:
            raise ValueError("domain collider frame signature must contain 64 characters")
        object.__setattr__(self, "source_pointers", pointers)
        object.__setattr__(self, "collider_keys", keys)
        object.__setattr__(self, "frame_signature", signature)
        for name, value in zip((
            "collider_types", "collider_group_bits", "collider_centers",
            "collider_segment_a", "collider_segment_b", "collider_old_centers",
            "collider_old_segment_a", "collider_old_segment_b", "collider_radii",
        ), arrays):
            object.__setattr__(self, name, value)

    @property
    def collider_count(self) -> int:
        return int(self.collider_types.shape[0])

    def native_mapping(self) -> dict[str, np.ndarray]:
        return {
            "collider_types": self.collider_types,
            "collider_group_bits": self.collider_group_bits,
            "collider_centers": self.collider_centers,
            "collider_segment_a": self.collider_segment_a,
            "collider_segment_b": self.collider_segment_b,
            "collider_old_centers": self.collider_old_centers,
            "collider_old_segment_a": self.collider_old_segment_a,
            "collider_old_segment_b": self.collider_old_segment_b,
            "collider_radii": self.collider_radii,
        }

    def debug_dict(self) -> dict:
        return {
            "frame": self.frame,
            "source_pointers": self.source_pointers,
            "collider_keys": self.collider_keys,
            "collider_count": self.collider_count,
            "frame_signature": self.frame_signature,
        }


def _source_owner(source):
    if isinstance(source, dict):
        return source.get("armature") or source.get("proxy_obj") or source.get("object")
    if isinstance(source, tuple) and source:
        return source[0]
    return source


def _pack_colliders(
    snapshot: dict,
    previous: dict,
    *,
    excluded_pointers: frozenset[int],
    collided_by_groups: int | None,
    allowed_types: frozenset[str] | None,
):
    types = []
    group_bits = []
    centers = []
    segment_a_values = []
    segment_b_values = []
    old_centers = []
    old_segment_a_values = []
    old_segment_b_values = []
    radii = []
    keys = []
    for collider in snapshot.get("colliders") or ():
        if not isinstance(collider, dict):
            continue
        if _pointer(collider.get("owner")) in excluded_pointers:
            continue
        collider_type = str(collider.get("type", "SPHERE") or "SPHERE").upper()
        if allowed_types is not None and collider_type not in allowed_types:
            continue
        type_code = _TYPE_CODES.get(collider_type)
        center = _vec3(collider.get("center"))
        if type_code is None or center is None:
            continue
        group = max(1, min(16, int(collider.get("primary_group", 1) or 1)))
        group_bit = 1 << (group - 1)
        if collided_by_groups is not None and collided_by_groups & group_bit == 0:
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
        keys.append(key)

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
    return tuple(keys), arrays


def build_mc2_collider_frame(
    world,
    source_obj,
    *,
    collided_by_groups: int | None = None,
    allowed_types: frozenset[str] | None = None,
) -> MC2ColliderFrameSpec:
    snapshot = getattr(world, "collider_snapshot", None)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    previous = getattr(world, "previous_collider_snapshot", None)
    previous = previous.get("colliders", {}) if isinstance(previous, dict) else {}
    previous = previous if isinstance(previous, dict) else {}
    if collided_by_groups is None:
        properties = getattr(source_obj, "hotools_mesh_collision", None)
        collided_by_groups = getattr(properties, "collided_by_groups", 0)
    collided_by_groups = max(0, min(0xFFFF, int(collided_by_groups or 0)))
    source_pointer = _pointer(_source_owner(source_obj))

    keys, arrays = _pack_colliders(
        snapshot,
        previous,
        excluded_pointers=frozenset((source_pointer,)),
        collided_by_groups=collided_by_groups,
        allowed_types=allowed_types,
    )
    digest = hashlib.sha256()
    digest.update(np.asarray(
        (int(snapshot.get("frame", -1) or -1), collided_by_groups, source_pointer),
        dtype=np.int64,
    ).tobytes())
    digest.update("\0".join(keys).encode("utf-8"))
    for value in arrays:
        digest.update(value.tobytes())
    return MC2ColliderFrameSpec(
        int(snapshot.get("frame", -1) or -1),
        collided_by_groups,
        source_pointer,
        tuple(keys),
        *arrays,
        digest.hexdigest(),
    )


def build_mc2_domain_collider_frame(
    world,
    partition_sources,
    *,
    allowed_types: frozenset[str] | None = None,
) -> MC2DomainColliderFrameSpec:
    """Pack one World snapshot for all partitions without per-source mask filtering."""

    snapshot = getattr(world, "collider_snapshot", None)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    previous = getattr(world, "previous_collider_snapshot", None)
    previous = previous.get("colliders", {}) if isinstance(previous, dict) else {}
    previous = previous if isinstance(previous, dict) else {}
    sources = tuple(partition_sources)
    source_pointers = tuple(sorted({
        pointer
        for source in sources
        if (pointer := _pointer(_source_owner(source))) > 0
    }))
    keys, arrays = _pack_colliders(
        snapshot,
        previous,
        excluded_pointers=frozenset(source_pointers),
        collided_by_groups=None,
        allowed_types=allowed_types,
    )
    frame = int(snapshot.get("frame", -1) or -1)
    digest = hashlib.sha256()
    digest.update(np.asarray((frame, *source_pointers), dtype=np.int64).tobytes())
    digest.update("\0".join(keys).encode("utf-8"))
    for value in arrays:
        digest.update(value.tobytes())
    return MC2DomainColliderFrameSpec(
        frame,
        source_pointers,
        keys,
        *arrays,
        digest.hexdigest(),
    )


__all__ = [
    "MC2ColliderFrameSpec",
    "MC2DomainColliderFrameSpec",
    "build_mc2_collider_frame",
    "build_mc2_domain_collider_frame",
]
