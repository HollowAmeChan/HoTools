"""Physics World 通用 collider snapshot 到 Mesh XPBD native arrays。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np


_TYPE_CODES = {"SPHERE": 0, "CAPSULE": 1, "PLANE": 2, "BOX": 3}
_EPSILON = 1.0e-8


def _pointer(value) -> int:
    try:
        return int(value.as_pointer())
    except Exception:
        return 0


def _vec3(value, label: str) -> np.ndarray:
    try:
        result = np.asarray(tuple(value), dtype=np.float32)
    except Exception:
        raise ValueError(f"{label} 必须是有限 float3") from None
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(f"{label} 必须是有限 float3")
    return result


def _readonly(values, dtype, shape) -> np.ndarray:
    result = np.array(values, dtype=dtype, order="C", copy=True).reshape(shape)
    result.setflags(write=False)
    return result


def _signed_box_half_z(axis_x: np.ndarray, axis_y: np.ndarray, axis_z: np.ndarray) -> float:
    x_length = float(np.linalg.norm(axis_x))
    y_length = float(np.linalg.norm(axis_y))
    z_length = float(np.linalg.norm(axis_z))
    if min(x_length, y_length, z_length) <= _EPSILON:
        raise ValueError("BOX collider axes 不能退化")
    cross = np.cross(axis_x / x_length, axis_y / y_length)
    cross_length = float(np.linalg.norm(cross))
    if cross_length <= _EPSILON:
        raise ValueError("BOX collider X/Y axes 不能共线")
    if abs(float(np.dot(axis_x / x_length, axis_y / y_length))) > 1.0e-4:
        raise ValueError("BOX collider X/Y axes 必须正交")
    signed = float(np.dot(axis_z, cross / cross_length))
    if abs(signed) <= _EPSILON:
        raise ValueError("BOX collider Z axis 必须垂直于 X/Y")
    return signed


@dataclass(frozen=True)
class MeshXpbdColliderFrame:
    frame: int
    source_object_ptr: int
    collided_by_groups: int
    collider_keys: tuple[str, ...]
    collider_types: np.ndarray
    collider_group_bits: np.ndarray
    collider_centers: np.ndarray
    collider_segment_a: np.ndarray
    collider_segment_b: np.ndarray
    collider_radii: np.ndarray
    signature: str

    @property
    def collider_count(self) -> int:
        return int(self.collider_types.shape[0])

    def native_args(self) -> tuple[np.ndarray, ...]:
        return (
            self.collider_types,
            self.collider_group_bits,
            self.collider_centers,
            self.collider_segment_a,
            self.collider_segment_b,
            self.collider_radii,
        )

    def debug_dict(self) -> dict:
        return {
            "schema": "mesh_xpbd_collider_frame_v1",
            "frame": self.frame,
            "source_object_ptr": self.source_object_ptr,
            "collided_by_groups": self.collided_by_groups,
            "collider_count": self.collider_count,
            "collider_keys": self.collider_keys,
            "signature": self.signature,
        }


def build_mesh_xpbd_collider_frame(
    snapshot,
    source_object,
    collided_by_groups: int,
    *,
    excluded_bone_names=(),
) -> MeshXpbdColliderFrame:
    source_ptr = _pointer(source_object)
    if source_ptr <= 0:
        raise ValueError("Mesh XPBD collider frame 需要稳定 source object identity")
    mask = int(collided_by_groups)
    if mask < 0 or mask > 0xFFFF:
        raise ValueError("collided_by_groups 必须位于 Physics World 16 组范围")
    data = snapshot if isinstance(snapshot, dict) else {}
    frame = int(data.get("frame", -1) if data.get("frame") is not None else -1)
    types = []
    groups = []
    centers = []
    segments_a = []
    segments_b = []
    radii = []
    keys = []
    excluded_bones = {str(name or "") for name in excluded_bone_names if str(name or "")}

    if mask:
        for collider in data.get("colliders") or ():
            if not isinstance(collider, dict):
                continue
            same_owner = _pointer(collider.get("owner")) == source_ptr
            if same_owner:
                is_bone = str(collider.get("owner_type") or "") == "BONE"
                bone_name = str(collider.get("bone") or "")
                if not excluded_bones or not is_bone or bone_name in excluded_bones:
                    continue
            type_name = str(collider.get("type", "") or "").upper()
            type_code = _TYPE_CODES.get(type_name)
            if type_code is None:
                continue
            group = int(collider.get("primary_group", 1) or 1)
            if group < 1 or group > 16:
                raise ValueError("Physics World collider primary_group 必须位于 [1,16]")
            group_bit = 1 << (group - 1)
            if mask & group_bit == 0:
                continue
            center = _vec3(collider.get("center"), f"{type_name} collider center")
            radius = float(collider.get("radius", 0.0) or 0.0)
            if not math.isfinite(radius):
                raise ValueError(f"{type_name} collider radius 必须有限")
            if type_name == "SPHERE":
                if radius < 0.0:
                    raise ValueError("SPHERE collider radius 不能为负")
                segment_a = center
                segment_b = center
            elif type_name == "CAPSULE":
                if radius < 0.0:
                    raise ValueError("CAPSULE collider radius 不能为负")
                segment_a = _vec3(collider.get("segment_a"), "CAPSULE segment_a")
                segment_b = _vec3(collider.get("segment_b"), "CAPSULE segment_b")
            elif type_name == "PLANE":
                segment_a = _vec3(collider.get("normal"), "PLANE normal")
                normal_length = float(np.linalg.norm(segment_a))
                if normal_length <= _EPSILON:
                    raise ValueError("PLANE collider normal 不能退化")
                segment_a = segment_a / normal_length
                segment_b = center
                radius = 0.0
            else:
                segment_a = _vec3(collider.get("box_axis_x"), "BOX axis_x")
                segment_b = _vec3(collider.get("box_axis_y"), "BOX axis_y")
                axis_z = _vec3(collider.get("box_axis_z"), "BOX axis_z")
                radius = _signed_box_half_z(segment_a, segment_b, axis_z)
            types.append(type_code)
            groups.append(group_bit)
            centers.append(center)
            segments_a.append(segment_a)
            segments_b.append(segment_b)
            radii.append(radius)
            keys.append(str(collider.get("key") or collider.get("source_key") or ""))

    count = len(types)
    arrays = (
        _readonly(types, np.int32, (count,)),
        _readonly(groups, np.int32, (count,)),
        _readonly(centers, np.float32, (count, 3)),
        _readonly(segments_a, np.float32, (count, 3)),
        _readonly(segments_b, np.float32, (count, 3)),
        _readonly(radii, np.float32, (count,)),
    )
    digest = hashlib.sha256()
    digest.update(np.asarray((frame, source_ptr, mask), dtype=np.int64).tobytes())
    digest.update("\0".join(keys).encode("utf-8"))
    for values in arrays:
        digest.update(values.tobytes())
    return MeshXpbdColliderFrame(
        frame,
        source_ptr,
        mask,
        tuple(keys),
        *arrays,
        digest.hexdigest(),
    )
