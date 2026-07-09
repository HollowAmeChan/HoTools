"""SpringBone VRM 自有可视化调试绘制。"""

from __future__ import annotations

import bpy
import mathutils

from ..types import PhysicsWorldCache
from ..utils.debug_draw import (
    add_box_lines,
    add_capsule_lines,
    add_cross_lines,
    add_line,
    add_plane_lines,
    add_sphere_lines,
    draw_line_batches,
    float_value,
    vector3,
)
from ..utils.geometry import matrix_scale_radius
from .bone_collision import resolve_bone_collision_fields
from .names import SPRING_VRM_SLOT_KIND
from .results import iter_spring_vrm_pose_results


_COLOR_SOLVED_CHAIN = (1.00, 0.70, 0.20, 0.90)
_COLOR_ROOT = (0.80, 0.95, 0.30, 0.85)
_COLOR_COLLIDER_DEFAULT = (0.62, 0.66, 0.72, 0.58)  # 统一灰：对齐外部未固定碰撞预览

# 与 PhysicsTools.physicsUtils._COLLISION_GROUP_COLORS 保持一致。
_GROUP_COLORS = (
    (0.10, 0.63, 1.00, 0.86),  # 组1：亮蓝
    (1.00, 0.45, 0.25, 0.86),  # 组2：橙红
    (0.35, 0.90, 0.35, 0.86),  # 组3：绿色
    (1.00, 0.82, 0.18, 0.86),  # 组4：金黄
    (0.78, 0.48, 1.00, 0.86),  # 组5：紫色
    (0.12, 0.92, 0.82, 0.86),  # 组6：青色
    (1.00, 0.35, 0.62, 0.86),  # 组7：粉红
    (0.62, 0.88, 0.18, 0.86),  # 组8：黄绿
    (0.30, 0.48, 1.00, 0.86),  # 组9：深蓝
    (1.00, 0.60, 0.12, 0.86),  # 组10：橙色
    (0.20, 0.78, 0.55, 0.86),  # 组11：青绿
    (0.92, 0.38, 1.00, 0.86),  # 组12：洋红
    (0.88, 0.75, 0.55, 0.86),  # 组13：沙金
    (0.52, 0.72, 0.95, 0.86),  # 组14：浅蓝
    (0.95, 0.52, 0.52, 0.86),  # 组15：浅红
    (0.78, 0.78, 0.78, 0.86),  # 组16：中灰
)

_SPRING_VRM_DRAW_STORE: dict[str, dict] = {}
_SPRING_VRM_DRAW_HANDLE = None


def update_spring_vrm_debug_draw_store(
    node_uid: str,
    world,
    enabled: bool,
    show_solved_chain: bool = True,
    show_roots: bool = True,
    show_colliders: bool = True,
    color_by_group: bool = True,
) -> None:
    node_key = str(node_uid)
    if not enabled or not isinstance(world, PhysicsWorldCache):
        clear_spring_vrm_debug_draw_store(node_key)
        return

    _ensure_spring_vrm_draw_handler()

    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    generation = int(world.generation)
    chain_lines: list[tuple[float, float, float]] = []
    root_lines: list[tuple[float, float, float]] = []
    collider_batches: list[tuple[list[tuple[float, float, float]], tuple[float, float, float, float], float]] = []
    spring_bone_keys: set[tuple[int, str]] = set()

    for slot_id, slot in list(world.solver_slots.items()):
        if slot.kind != SPRING_VRM_SLOT_KIND:
            continue
        spec = slot.data.get("spec")
        if spec is None:
            continue
        result_by_bone = {
            str(item.get("bone_name") or ""): item
            for item in iter_spring_vrm_pose_results(
                world,
                frame=frame,
                generation=generation,
                slot_id=slot_id,
            )
            if isinstance(item, dict)
        }
        _append_spec_lines(
            spec,
            slot.data.get("frame_state"),
            result_by_bone,
            chain_lines if show_solved_chain else None,
            root_lines if show_roots else None,
            collider_batches if show_colliders else None,
            color_by_group=bool(color_by_group),
            spring_bone_keys=spring_bone_keys,
        )

    if show_colliders:
        _append_world_collider_batches(
            collider_batches,
            world,
            color_by_group=bool(color_by_group),
            skip_bone_keys=spring_bone_keys,
        )

    _SPRING_VRM_DRAW_STORE[node_key] = {
        "world_id": str(id(world)),
        "chain_lines": chain_lines,
        "root_lines": root_lines,
        "collider_batches": collider_batches,
    }


def clear_spring_vrm_debug_draw_store(
    node_uid: str | None = None,
    world_id: str | None = None,
) -> None:
    if node_uid is not None:
        _SPRING_VRM_DRAW_STORE.pop(str(node_uid), None)
    elif world_id is not None:
        wid = str(world_id)
        for key, value in list(_SPRING_VRM_DRAW_STORE.items()):
            if str(value.get("world_id")) == wid:
                _SPRING_VRM_DRAW_STORE.pop(key, None)
    else:
        _SPRING_VRM_DRAW_STORE.clear()

    if not _SPRING_VRM_DRAW_STORE:
        _remove_spring_vrm_draw_handler()


def _ensure_spring_vrm_draw_handler() -> None:
    global _SPRING_VRM_DRAW_HANDLE
    if _SPRING_VRM_DRAW_HANDLE is None:
        _SPRING_VRM_DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _draw_spring_vrm_debug,
            (),
            "WINDOW",
            "POST_VIEW",
        )


def _remove_spring_vrm_draw_handler() -> None:
    global _SPRING_VRM_DRAW_HANDLE
    if _SPRING_VRM_DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_SPRING_VRM_DRAW_HANDLE, "WINDOW")
        except Exception:
            pass
        _SPRING_VRM_DRAW_HANDLE = None


def _draw_spring_vrm_debug() -> None:
    data = list(_SPRING_VRM_DRAW_STORE.values())
    for item in data:
        draw_line_batches(item.get("collider_batches") or ())
    draw_line_batches((item.get("chain_lines"), _COLOR_SOLVED_CHAIN, 2.0) for item in data)
    draw_line_batches((item.get("root_lines"), _COLOR_ROOT, 2.0) for item in data)


def _append_spec_lines(
    spec,
    frame_state,
    result_by_bone: dict[str, dict],
    chain_lines: list | None,
    root_lines: list | None,
    collider_batches: list | None,
    color_by_group: bool = True,
    spring_bone_keys: set[tuple[int, str]] | None = None,
) -> None:
    armature = getattr(spec, "armature", None)
    pose_bones = getattr(getattr(armature, "pose", None), "bones", None)
    if armature is None or pose_bones is None:
        return
    arm_world = getattr(armature, "matrix_world", mathutils.Matrix.Identity(4))
    chain_states = frame_state.get("chains") if isinstance(frame_state, dict) else {}
    if not isinstance(chain_states, dict):
        chain_states = {}

    for chain in getattr(spec, "chains", ()):
        bones = tuple(getattr(chain, "bones", ()) or ())
        chain_state = chain_states.get(getattr(chain, "root_bone", "")) or {}
        tails = chain_state.get("tails") if isinstance(chain_state, dict) else {}
        if not isinstance(tails, dict):
            tails = {}
        previous_tail = None
        for bone_name in bones:
            bone_name = str(bone_name)
            pose_bone = pose_bones.get(bone_name)
            if pose_bone is None:
                continue
            if spring_bone_keys is not None:
                spring_bone_keys.add((id(armature), bone_name))
            head = arm_world @ pose_bone.head
            rest_tail = arm_world @ pose_bone.tail
            if collider_batches is not None:
                _append_bone_collider_batch(
                    collider_batches,
                    armature,
                    bone_name,
                    pose_bone,
                    color_by_group=bool(color_by_group),
                )
            current_tail = rest_tail
            if bone_name != str(getattr(chain, "root_bone", "")):
                current_tail = _current_tail_for_bone(bone_name, tails, result_by_bone, rest_tail)
            if chain_lines is not None:
                add_line(chain_lines, previous_tail if previous_tail is not None else head, current_tail)
            previous_tail = current_tail
            if bone_name == str(getattr(chain, "root_bone", "")):
                if root_lines is not None:
                    add_cross_lines(root_lines, head, 0.06)
                continue


def _current_tail_for_bone(
    bone_name: str,
    tails: dict,
    result_by_bone: dict[str, dict],
    fallback,
) -> mathutils.Vector:
    tail_state = tails.get(bone_name)
    if isinstance(tail_state, dict) and tail_state.get("current_tail") is not None:
        return vector3(tail_state.get("current_tail"), fallback)
    result = result_by_bone.get(bone_name)
    if isinstance(result, dict) and result.get("current_tail") is not None:
        return vector3(result.get("current_tail"), fallback)
    return vector3(fallback, fallback)


def _append_world_collider_batches(
    batches: list,
    world: PhysicsWorldCache,
    color_by_group: bool,
    skip_bone_keys: set[tuple[int, str]] | None = None,
) -> None:
    snapshot = getattr(world, "collider_snapshot", None)
    colliders = snapshot.get("colliders") if isinstance(snapshot, dict) else None
    if not colliders:
        return
    for collider in colliders:
        if not isinstance(collider, dict):
            continue
        bone_key = _collider_bone_key(collider)
        if bone_key is not None and skip_bone_keys is not None and bone_key in skip_bone_keys:
            continue
        lines: list[tuple[float, float, float]] = []
        if not _append_collider_shape_lines(lines, collider):
            continue
        batches.append((
            lines,
            _collider_color(collider.get("primary_group", 1), color_by_group),
            1.4,
        ))


def _collider_bone_key(collider: dict) -> tuple[int, str] | None:
    if str(collider.get("owner_type") or "") != "BONE":
        return None
    owner = collider.get("owner")
    bone_name = str(collider.get("bone") or "")
    if owner is None or not bone_name:
        return None
    return (id(owner), bone_name)


def _append_bone_collider_batch(
    batches: list,
    armature,
    bone_name: str,
    pose_bone,
    color_by_group: bool,
) -> None:
    profile = resolve_bone_collision_fields(armature, bone_name)
    collider_type = str(profile.collision_type or "NONE")
    if collider_type not in {"SPHERE", "CAPSULE"}:
        return

    try:
        matrix = armature.matrix_world @ pose_bone.matrix
    except Exception:
        return
    radius = max(float_value(profile.radius, 0.0), 0.0) * matrix_scale_radius(matrix)
    if radius <= 1e-8:
        return

    offset = vector3(getattr(profile, "offset", (0.0, 0.0, 0.0)))
    center = matrix @ offset
    lines: list[tuple[float, float, float]] = []
    if collider_type == "CAPSULE":
        half_length = max(float_value(profile.length, 0.0), 0.0) * 0.5
        axis = mathutils.Vector((0.0, 1.0, 0.0))
        add_capsule_lines(
            lines,
            matrix @ (offset - axis * half_length),
            matrix @ (offset + axis * half_length),
            radius,
        )
    else:
        add_sphere_lines(
            lines,
            center,
            mathutils.Vector((1.0, 0.0, 0.0)),
            mathutils.Vector((0.0, 1.0, 0.0)),
            mathutils.Vector((0.0, 0.0, 1.0)),
            radius,
        )
    if lines:
        batches.append((
            lines,
            _collider_color(profile.primary_collision_group, color_by_group),
            1.8,
        ))


def _append_collider_shape_lines(lines: list, collider: dict) -> bool:
    collider_type = str(collider.get("type", "SPHERE") or "SPHERE")
    center = _vector_or_none(collider.get("center"))

    if collider_type == "SPHERE":
        if center is None:
            return False
        radius = max(float_value(collider.get("radius", 0.0), 0.0), 0.0)
        if radius <= 1e-8:
            return False
        add_sphere_lines(
            lines,
            center,
            mathutils.Vector((1.0, 0.0, 0.0)),
            mathutils.Vector((0.0, 1.0, 0.0)),
            mathutils.Vector((0.0, 0.0, 1.0)),
            radius,
        )
        return True

    if collider_type == "CAPSULE":
        segment_a = _vector_or_none(collider.get("segment_a"))
        segment_b = _vector_or_none(collider.get("segment_b"))
        radius = max(float_value(collider.get("radius", 0.0), 0.0), 0.0)
        if segment_a is None or segment_b is None or radius <= 1e-8:
            return False
        add_capsule_lines(lines, segment_a, segment_b, radius)
        return True

    if collider_type == "PLANE":
        if center is None:
            return False
        axis_x = _vector_or_none(collider.get("plane_axis_x"))
        axis_y = _vector_or_none(collider.get("plane_axis_y"))
        normal = _vector_or_none(collider.get("normal"))
        if axis_x is None or axis_y is None or normal is None or normal.length <= 1e-8:
            return False
        add_plane_lines(lines, center, axis_x, axis_y, normal)
        return True

    if collider_type == "BOX":
        if center is None:
            return False
        axis_x = _vector_or_none(collider.get("box_axis_x"))
        axis_y = _vector_or_none(collider.get("box_axis_y"))
        axis_z = _vector_or_none(collider.get("box_axis_z"))
        if axis_x is None or axis_y is None or axis_z is None:
            return False
        add_box_lines(lines, center, axis_x, axis_y, axis_z)
        return True

    return False


def _collider_color(group_value, color_by_group: bool) -> tuple[float, float, float, float]:
    if not color_by_group:
        return _COLOR_COLLIDER_DEFAULT
    try:
        group = int(group_value)
    except Exception:
        group = 1
    group = max(1, min(16, group))
    return _GROUP_COLORS[group - 1]


def _vector_or_none(value) -> mathutils.Vector | None:
    try:
        return mathutils.Vector(value).to_3d()
    except Exception:
        return None
