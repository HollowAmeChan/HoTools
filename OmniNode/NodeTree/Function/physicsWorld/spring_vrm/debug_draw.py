"""SpringBone VRM 自有可视化调试绘制。"""

from __future__ import annotations

import bpy
import mathutils

from ..types import PhysicsWorldCache
from ..utils.debug_draw import add_cross_lines, add_line, draw_line_batches, vector3
from .names import SPRING_VRM_SLOT_KIND
from .results import iter_spring_vrm_pose_results


_COLOR_POSE = (0.35, 0.65, 1.00, 0.65)
_COLOR_TAIL = (1.00, 0.70, 0.20, 0.90)
_COLOR_ROOT = (0.80, 0.95, 0.30, 0.85)

_SPRING_VRM_DRAW_STORE: dict[str, dict] = {}
_SPRING_VRM_DRAW_HANDLE = None


def update_spring_vrm_debug_draw_store(
    node_uid: str,
    world,
    enabled: bool,
    show_pose: bool = True,
    show_simulated_tail: bool = True,
    show_roots: bool = True,
) -> None:
    node_key = str(node_uid)
    if not enabled or not isinstance(world, PhysicsWorldCache):
        clear_spring_vrm_debug_draw_store(node_key)
        return

    _ensure_spring_vrm_draw_handler()

    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    generation = int(world.generation)
    pose_lines: list[tuple[float, float, float]] = []
    tail_lines: list[tuple[float, float, float]] = []
    root_lines: list[tuple[float, float, float]] = []

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
            pose_lines if show_pose else None,
            tail_lines if show_simulated_tail else None,
            root_lines if show_roots else None,
        )

    _SPRING_VRM_DRAW_STORE[node_key] = {
        "world_id": str(id(world)),
        "pose_lines": pose_lines,
        "tail_lines": tail_lines,
        "root_lines": root_lines,
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
    draw_line_batches((item.get("pose_lines"), _COLOR_POSE, 1.0) for item in data)
    draw_line_batches((item.get("tail_lines"), _COLOR_TAIL, 2.0) for item in data)
    draw_line_batches((item.get("root_lines"), _COLOR_ROOT, 2.0) for item in data)


def _append_spec_lines(
    spec,
    frame_state,
    result_by_bone: dict[str, dict],
    pose_lines: list | None,
    tail_lines: list | None,
    root_lines: list | None,
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
        for bone_name in bones:
            pose_bone = pose_bones.get(str(bone_name))
            if pose_bone is None:
                continue
            head = arm_world @ pose_bone.head
            rest_tail = arm_world @ pose_bone.tail
            if pose_lines is not None:
                add_line(pose_lines, head, rest_tail)
            if str(bone_name) == str(getattr(chain, "root_bone", "")):
                if root_lines is not None:
                    add_cross_lines(root_lines, head, 0.06)
                continue
            if tail_lines is None:
                continue
            current_tail = _current_tail_for_bone(str(bone_name), tails, result_by_bone, rest_tail)
            add_line(tail_lines, head, current_tail)
            add_cross_lines(tail_lines, current_tail, 0.035)


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
