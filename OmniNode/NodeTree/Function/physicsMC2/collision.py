"""MC2 自己的 HoTools 碰撞组适配与 point collision。"""

import bpy
import mathutils
import numpy as np

from . import math_utils
from .constants import MC2SystemConstants


def _owner_key(owner) -> str:
    try:
        return str(int(owner.as_pointer()))
    except Exception:
        return str(id(owner))


def collider_key(owner, owner_type: str, bone_name: str = "") -> str:
    return f"{owner_type}:{_owner_key(owner)}:{bone_name or ''}"


def _collider_key(collider: dict) -> str | None:
    key = collider.get("key") if isinstance(collider, dict) else None
    return str(key) if key else None


def _snapshot_vector(value, fallback=None) -> np.ndarray | None:
    vector = math_utils.vector_to_numpy(value)
    if vector is None and fallback is not None:
        vector = math_utils.vector_to_numpy(fallback)
    if vector is None:
        return None
    return np.ascontiguousarray(vector, dtype=np.float32)


def scene_objects(scene) -> list:
    scene = scene or bpy.context.scene
    if scene is None:
        return []
    return list(getattr(scene, "objects", []) or [])


def collider_from_matrix(matrix, props, owner, owner_type: str, bone_name: str = ""):
    collision_type = str(getattr(props, "collision_type", "NONE") or "NONE")
    if collision_type not in {"SPHERE", "CAPSULE"}:
        return None

    radius = max(float(getattr(props, "radius", 0.0)), 0.0) * math_utils.matrix_scale_radius(matrix)
    if radius <= MC2SystemConstants.EPSILON:
        return None

    offset = math_utils.vector3(getattr(props, "offset", None), mathutils.Vector((0.0, 0.0, 0.0)))
    center = matrix @ offset
    group = max(1, min(16, int(getattr(props, "primary_collision_group", 1))))
    collider = {
        "type": collision_type,
        "owner": owner,
        "owner_type": owner_type,
        "bone": bone_name,
        "key": collider_key(owner, owner_type, bone_name),
        "primary_group": group,
        "center": center,
        "radius": radius,
    }

    if collision_type == "CAPSULE":
        half_length = max(float(getattr(props, "length", 0.0)), 0.0) * 0.5
        axis = mathutils.Vector((0.0, 1.0, 0.0))
        collider["segment_a"] = matrix @ (offset - axis * half_length)
        collider["segment_b"] = matrix @ (offset + axis * half_length)

    return collider


def build_collision_snapshot_from_scene(
    scene,
    include_bone_colliders: bool = True,
    include_object_colliders: bool = True,
    include_hidden: bool = False,
) -> dict:
    colliders = []
    for obj in scene_objects(scene):
        if not include_hidden:
            try:
                if not obj.visible_get():
                    continue
            except Exception:
                pass

        if include_object_colliders:
            props = getattr(obj, "hotools_object_collision", None)
            collider = (
                collider_from_matrix(obj.matrix_world, props, obj, "OBJECT")
                if props is not None
                else None
            )
            if collider is not None:
                colliders.append(collider)

        if include_bone_colliders and getattr(obj, "type", None) == "ARMATURE":
            for bone in obj.data.bones:
                props = getattr(bone, "hotools_collision", None)
                if props is None:
                    continue
                pose_bone = obj.pose.bones.get(bone.name) if obj.pose else None
                local_matrix = pose_bone.matrix if pose_bone is not None else bone.matrix_local
                collider = collider_from_matrix(
                    obj.matrix_world @ local_matrix,
                    props,
                    obj,
                    "BONE",
                    bone.name,
                )
                if collider is not None:
                    colliders.append(collider)

    frame = int(getattr(scene or bpy.context.scene, "frame_current", 0) or 0)
    return {
        "frame": frame,
        "colliders": colliders,
    }


def compact_collider_snapshot(colliders: list[dict] | None) -> dict:
    snapshots = {}
    for collider in colliders or []:
        if not isinstance(collider, dict):
            continue
        key = _collider_key(collider)
        center = _snapshot_vector(collider.get("center"))
        if key is None or center is None:
            continue
        collider_type = str(collider.get("type", "SPHERE") or "SPHERE")
        if collider_type == "CAPSULE":
            segment_a = _snapshot_vector(collider.get("segment_a"), center)
            segment_b = _snapshot_vector(collider.get("segment_b"), center)
        else:
            segment_a = center
            segment_b = center
        if segment_a is None or segment_b is None:
            continue
        snapshots[key] = {
            "type": collider_type,
            "center": center,
            "segment_a": segment_a,
            "segment_b": segment_b,
        }
    return {"colliders": snapshots}


def with_previous_collider_pose(colliders: list[dict] | None, previous_snapshot: dict | None) -> list[dict]:
    previous = {}
    if isinstance(previous_snapshot, dict):
        previous = previous_snapshot.get("colliders") or {}
    enriched = []
    for collider in colliders or []:
        if not isinstance(collider, dict):
            continue
        current = dict(collider)
        center = _snapshot_vector(current.get("center"))
        if center is None:
            continue
        if current.get("type") == "CAPSULE":
            segment_a = _snapshot_vector(current.get("segment_a"), center)
            segment_b = _snapshot_vector(current.get("segment_b"), center)
        else:
            segment_a = center
            segment_b = center
        old = previous.get(_collider_key(current))
        if isinstance(old, dict) and str(old.get("type", "")) == str(current.get("type", "")):
            old_center = _snapshot_vector(old.get("center"), center)
            old_segment_a = _snapshot_vector(old.get("segment_a"), segment_a)
            old_segment_b = _snapshot_vector(old.get("segment_b"), segment_b)
        else:
            old_center = center
            old_segment_a = segment_a
            old_segment_b = segment_b
        current["old_center"] = old_center if old_center is not None else center
        current["old_segment_a"] = old_segment_a if old_segment_a is not None else segment_a
        current["old_segment_b"] = old_segment_b if old_segment_b is not None else segment_b
        enriched.append(current)
    return enriched


def project_vertex_collision(
    position: np.ndarray,
    hit_radius: float,
    collided_by_groups: int,
    colliders: list[dict],
    owner_obj: bpy.types.Object,
    fallback: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
    if hit_radius <= MC2SystemConstants.EPSILON or not collided_by_groups:
        return position, np.zeros(3, dtype=np.float32), 0.0

    origin = position.copy()
    add_position = np.zeros(3, dtype=np.float32)
    add_normal = np.zeros(3, dtype=np.float32)
    add_count = 0
    friction_normal = np.zeros(3, dtype=np.float32)
    friction_value = 0.0
    friction_range = max(float(hit_radius), MC2SystemConstants.EPSILON)
    for collider in colliders:
        if not isinstance(collider, dict):
            continue
        if collider.get("owner") is owner_obj:
            continue
        if not collided_by_groups & math_utils.collision_group_bit(collider.get("primary_group", 1)):
            continue

        collider_radius = max(float(collider.get("radius", 0.0)), 0.0)
        radius = float(hit_radius) + collider_radius
        if radius <= MC2SystemConstants.EPSILON:
            continue

        if collider.get("type") == "CAPSULE":
            old_segment_a = math_utils.vector_to_numpy(collider.get("old_segment_a", collider.get("segment_a")))
            old_segment_b = math_utils.vector_to_numpy(collider.get("old_segment_b", collider.get("segment_b")))
            segment_a = math_utils.vector_to_numpy(collider.get("segment_a"))
            segment_b = math_utils.vector_to_numpy(collider.get("segment_b"))
            if old_segment_a is None or old_segment_b is None or segment_a is None or segment_b is None:
                continue
            segment = old_segment_b - old_segment_a
            denom = float(np.dot(segment, segment))
            ratio = 0.0
            if denom > MC2SystemConstants.EPSILON:
                ratio = max(0.0, min(1.0, float(np.dot(origin - old_segment_a, segment) / denom)))
            old_center = old_segment_a + segment * ratio
            center = segment_a + (segment_b - segment_a) * ratio
        else:
            center = math_utils.vector_to_numpy(collider.get("center"))
            old_center = math_utils.vector_to_numpy(collider.get("old_center", collider.get("center")))
        if center is None or old_center is None:
            continue

        delta = origin - old_center
        normal = math_utils.safe_normal_np(delta, fallback)
        surface_point = center + normal * radius
        surface_distance = float(np.dot(origin - surface_point, normal))
        if surface_distance <= friction_range:
            collider_distance = max(surface_distance, 0.0)
            near_friction = 1.0 - max(0.0, min(1.0, collider_distance / friction_range))
            if near_friction > friction_value:
                friction_value = near_friction
            friction_normal += normal
        if surface_distance >= 0.0:
            continue

        add_position += -normal * surface_distance
        add_normal += normal
        add_count += 1

    if add_count <= 0:
        friction_length = float(np.linalg.norm(friction_normal))
        if friction_length <= MC2SystemConstants.EPSILON:
            return origin, np.zeros(3, dtype=np.float32), 0.0
        return (
            origin,
            np.ascontiguousarray(friction_normal / friction_length, dtype=np.float32),
            float(friction_value),
        )

    add_normal /= float(add_count)
    normal_length = float(np.linalg.norm(add_normal))
    if normal_length <= MC2SystemConstants.EPSILON:
        return origin, np.zeros(3, dtype=np.float32), float(friction_value)

    blend = min(normal_length, 1.0)
    projected = origin + (add_position / float(add_count)) * blend
    return projected, np.ascontiguousarray(add_normal / normal_length, dtype=np.float32), max(float(friction_value), 1.0)


def project_collisions(
    positions: np.ndarray,
    base_positions: np.ndarray,
    inv_masses: np.ndarray,
    collision_radii: np.ndarray,
    collided_by_groups: int,
    colliders: list[dict] | None,
    owner_obj: bpy.types.Object,
    collision_normals: np.ndarray,
    friction: np.ndarray | None = None,
) -> None:
    if not colliders or not collided_by_groups:
        return

    for vertex_index in range(len(positions)):
        if float(inv_masses[vertex_index]) <= MC2SystemConstants.EPSILON:
            continue
        hit_radius = float(collision_radii[vertex_index])
        if hit_radius <= MC2SystemConstants.EPSILON:
            continue

        projected, normal, collision_friction = project_vertex_collision(
            positions[vertex_index],
            hit_radius,
            collided_by_groups,
            colliders,
            owner_obj,
            positions[vertex_index] - base_positions[vertex_index],
        )
        positions[vertex_index] = projected
        collision_normals[vertex_index] = normal
        if friction is not None and collision_friction > float(friction[vertex_index]):
            friction[vertex_index] = float(collision_friction)


def collider_arrays_for_native(
    state: dict,
    obj: bpy.types.Object,
    colliders: list[dict] | None,
) -> dict:
    """把当前 HoTools 碰撞组快照打包成未来 native 后端可直接消费的数组。"""
    empty_vec = np.empty((0, 3), dtype=np.float32)
    empty_i = np.empty(0, dtype=np.int32)
    empty_f = np.empty(0, dtype=np.float32)
    collision_radii = np.ascontiguousarray(state.get("collision_radii", empty_f), dtype=np.float32)
    collided_by_groups = math_utils.clamp_group_mask(state.get("collided_by_groups", 0))

    if not colliders or not collided_by_groups:
        return {
            "collision_radii": collision_radii,
            "collided_by_groups": int(collided_by_groups),
            "collider_types": empty_i,
            "collider_groups": empty_i,
            "collider_group_bits": empty_i,
            "collider_centers": empty_vec,
            "collider_segment_a": empty_vec,
            "collider_segment_b": empty_vec,
            "collider_old_centers": empty_vec,
            "collider_old_segment_a": empty_vec,
            "collider_old_segment_b": empty_vec,
            "collider_radii": empty_f,
        }

    collider_types = []
    collider_groups = []
    collider_group_bits = []
    collider_centers = []
    collider_segment_a = []
    collider_segment_b = []
    collider_old_centers = []
    collider_old_segment_a = []
    collider_old_segment_b = []
    collider_radii = []
    for collider in colliders:
        if not isinstance(collider, dict):
            continue
        if collider.get("owner") is obj:
            continue

        try:
            group = max(1, min(16, int(collider.get("primary_group", 1) or 1)))
        except Exception:
            group = 1
        group_bit = math_utils.collision_group_bit(group)
        if not collided_by_groups & group_bit:
            continue

        radius = max(float(collider.get("radius", 0.0)), 0.0)
        if radius <= MC2SystemConstants.EPSILON:
            continue

        collider_type = str(collider.get("type", "SPHERE") or "SPHERE")
        center = math_utils.vector_to_numpy(collider.get("center"))
        if center is None:
            continue

        if collider_type == "CAPSULE":
            seg_a = math_utils.vector_to_numpy(collider.get("segment_a"))
            seg_b = math_utils.vector_to_numpy(collider.get("segment_b"))
            if seg_a is None or seg_b is None:
                continue
            type_code = 1
        else:
            seg_a = center
            seg_b = center
            type_code = 0
        old_center = math_utils.vector_to_numpy(collider.get("old_center"))
        old_seg_a = math_utils.vector_to_numpy(collider.get("old_segment_a"))
        old_seg_b = math_utils.vector_to_numpy(collider.get("old_segment_b"))
        if old_center is None:
            old_center = center
        if old_seg_a is None:
            old_seg_a = seg_a
        if old_seg_b is None:
            old_seg_b = seg_b

        collider_types.append(type_code)
        collider_groups.append(group)
        collider_group_bits.append(group_bit)
        collider_centers.append(center)
        collider_segment_a.append(seg_a)
        collider_segment_b.append(seg_b)
        collider_old_centers.append(old_center)
        collider_old_segment_a.append(old_seg_a)
        collider_old_segment_b.append(old_seg_b)
        collider_radii.append(radius)

    if not collider_types:
        return {
            "collision_radii": collision_radii,
            "collided_by_groups": int(collided_by_groups),
            "collider_types": empty_i,
            "collider_groups": empty_i,
            "collider_group_bits": empty_i,
            "collider_centers": empty_vec,
            "collider_segment_a": empty_vec,
            "collider_segment_b": empty_vec,
            "collider_old_centers": empty_vec,
            "collider_old_segment_a": empty_vec,
            "collider_old_segment_b": empty_vec,
            "collider_radii": empty_f,
        }

    return {
        "collision_radii": collision_radii,
        "collided_by_groups": int(collided_by_groups),
        "collider_types": np.ascontiguousarray(collider_types, dtype=np.int32),
        "collider_groups": np.ascontiguousarray(collider_groups, dtype=np.int32),
        "collider_group_bits": np.ascontiguousarray(collider_group_bits, dtype=np.int32),
        "collider_centers": np.ascontiguousarray(collider_centers, dtype=np.float32),
        "collider_segment_a": np.ascontiguousarray(collider_segment_a, dtype=np.float32),
        "collider_segment_b": np.ascontiguousarray(collider_segment_b, dtype=np.float32),
        "collider_old_centers": np.ascontiguousarray(collider_old_centers, dtype=np.float32),
        "collider_old_segment_a": np.ascontiguousarray(collider_old_segment_a, dtype=np.float32),
        "collider_old_segment_b": np.ascontiguousarray(collider_old_segment_b, dtype=np.float32),
        "collider_radii": np.ascontiguousarray(collider_radii, dtype=np.float32),
    }
