"""刚体/Jolt 的对象作用域到解算器槽同步。

物理世界 Begin 只负责帧和对象作用域生命周期。刚体领域负责决定
Physics World 刚体属性如何变成 RigidBodySpec / ConstraintSpec 槽，
以及哪些变化需要触发 Jolt 重新同步。
"""

from __future__ import annotations

import bpy

from ..types import PhysicsObjectScope, PhysicsWorldCache
from .declaration import RIGID_SOLVER_DECLARATION
from .implicit_objects import active_generated_constraint_slot_ids
from .names import (
    RIGID_BACKEND_RESOURCE_KEY,
    RIGID_BODY_SLOT_KIND,
    RIGID_CONSTRAINT_SLOT_KIND,
)
from .specs import build_constraint_spec, build_rigid_body_spec


def _flatten(values) -> list:
    result = []
    stack = list(values) if isinstance(values, (list, tuple)) else (
        [values] if values is not None else []
    )
    while stack:
        item = stack.pop(0)
        if isinstance(item, (list, tuple)):
            stack[0:0] = list(item)
        else:
            result.append(item)
    return result


def clear_scope_dynamic_rigid_deltas(world: PhysicsWorldCache, scope: PhysicsObjectScope) -> None:
    """
    在重启阶段收集规格前清理动态刚体对象 delta。

    Jolt 冷启动会读取 obj.matrix_world 作为初始刚体姿态；Blender 的
    matrix_world 会包含 delta_location / delta_rotation_euler，所以重建
    刚体规格前必须先清掉旧写回残留的 delta。
    """
    if not isinstance(scope, PhysicsObjectScope):
        return
    if not getattr(scope, "include_rigid_body", False):
        return

    updated = set()
    for obj in _flatten(getattr(scope, "objects", ())):
        rb = getattr(obj, "hotools_rigid_body", None)
        if rb is None or not bool(getattr(rb, "enabled", False)):
            continue
        if str(getattr(rb, "body_type", "DYNAMIC") or "DYNAMIC") != "DYNAMIC":
            continue
        try:
            obj.delta_location = (0.0, 0.0, 0.0)
            obj.delta_rotation_euler = (0.0, 0.0, 0.0)
            updated.add(obj)
        except Exception:
            pass

    for obj in updated:
        try:
            obj.update_tag()
        except Exception:
            pass
    if updated:
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass


def _round_float(value, digits: int = 8) -> float:
    try:
        return round(float(value), digits)
    except Exception:
        return 0.0


def _round_tuple(values, digits: int = 8) -> tuple[float, ...]:
    try:
        return tuple(_round_float(v, digits) for v in values)
    except Exception:
        return ()


def _rigid_body_sync_signature(spec) -> tuple:
    """返回会影响 Jolt 刚体创建和同步的字段。"""
    body_type = str(getattr(spec, "body_type", "DYNAMIC") or "DYNAMIC")
    static_pose = ()
    if body_type == "STATIC":
        static_pose = (
            _round_tuple(getattr(spec, "world_position", (0.0, 0.0, 0.0))),
            _round_tuple(getattr(spec, "world_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
        )

    return (
        tuple(getattr(spec, "simulation_order_key", ())),
        body_type,
        _round_float(getattr(spec, "mass", 1.0)),
        _round_float(getattr(spec, "friction", 0.5)),
        _round_float(getattr(spec, "restitution", 0.0)),
        int(getattr(spec, "rigid_collision_group", 1) or 1),
        int(getattr(spec, "rigid_collides_with_groups", 0xFFFF) or 0),
        str(getattr(spec, "shape_type", "SPHERE") or "SPHERE"),
        _round_float(getattr(spec, "shape_radius", 0.5)),
        _round_float(getattr(spec, "shape_half_height", 0.5)),
        _round_tuple(getattr(spec, "shape_half_extents", (0.5, 0.5, 0.5))),
        _round_float(getattr(spec, "shape_plane_half_extent", 10.0)),
        _round_float(getattr(spec, "shape_top_radius", 0.5)),
        _round_float(getattr(spec, "shape_bottom_radius", 0.3)),
        _round_float(getattr(spec, "shape_convex_radius", 0.05)),
        _round_tuple(getattr(spec, "shape_offset", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "shape_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "linear_velocity", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "angular_velocity", (0.0, 0.0, 0.0))),
        _round_float(getattr(spec, "linear_damping", 0.05)),
        _round_float(getattr(spec, "angular_damping", 0.05)),
        _round_float(getattr(spec, "gravity_factor", 1.0)),
        bool(getattr(spec, "allow_sleeping", True)),
        str(getattr(spec, "motion_quality", "DISCRETE") or "DISCRETE"),
        _round_float(getattr(spec, "max_linear_velocity", 500.0)),
        _round_float(getattr(spec, "max_angular_velocity", 47.1239)),
        bool(getattr(spec, "is_sensor", False)),
        bool(getattr(spec, "collide_kinematic_vs_non_dynamic", False)),
        int(getattr(spec, "allowed_dofs", 0x3F) or 0),
        static_pose,
    )


def _kinematic_pose_signature(spec) -> tuple:
    if str(getattr(spec, "body_type", "DYNAMIC") or "DYNAMIC") != "KINEMATIC":
        return ()
    return (
        _round_tuple(getattr(spec, "world_position", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "world_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
    )


def _constraint_sync_signature(spec) -> tuple:
    return (
        tuple(getattr(spec, "simulation_order_key", ())),
        str(getattr(spec, "constraint_type", "FIXED") or "FIXED"),
        int(getattr(spec, "target_a_ptr", 0) or 0),
        int(getattr(spec, "target_b_ptr", 0) or 0),
        bool(getattr(spec, "disable_collisions", True)),
        bool(getattr(spec, "breakable", False)),
        _round_float(getattr(spec, "breaking_threshold", 1000.0)),
        str(getattr(spec, "anchor_mode", "SHARED_WORLD") or "SHARED_WORLD"),
        _round_tuple(getattr(spec, "anchor_position", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "anchor_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "anchor_position_a", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "anchor_rotation_wxyz_a", (1.0, 0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "anchor_position_b", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "anchor_rotation_wxyz_b", (1.0, 0.0, 0.0, 0.0))),
        int(getattr(spec, "constraint_priority", 0) or 0),
        int(getattr(spec, "solver_velocity_steps", 0) or 0),
        int(getattr(spec, "solver_position_steps", 0) or 0),
        _round_float(getattr(spec, "draw_constraint_size", 1.0)),
        bool(getattr(spec, "limit_enabled", False)),
        _round_float(getattr(spec, "angular_limit_min", -3.141592653589793)),
        _round_float(getattr(spec, "angular_limit_max", 3.141592653589793)),
        _round_float(getattr(spec, "linear_limit_min", -1.0)),
        _round_float(getattr(spec, "linear_limit_max", 1.0)),
        _round_float(getattr(spec, "limit_spring_frequency", 0.0)),
        _round_float(getattr(spec, "limit_spring_damping", 0.0)),
        _round_float(getattr(spec, "max_friction_torque", 0.0)),
        _round_float(getattr(spec, "max_friction_force", 0.0)),
        str(getattr(spec, "motor_state", "OFF") or "OFF"),
        _round_float(getattr(spec, "motor_frequency", 2.0)),
        _round_float(getattr(spec, "motor_damping", 1.0)),
        _round_float(getattr(spec, "motor_force_limit", 0.0)),
        _round_float(getattr(spec, "motor_torque_limit", 0.0)),
        _round_float(getattr(spec, "motor_target_angular_velocity", 0.0)),
        _round_float(getattr(spec, "motor_target_angle", 0.0)),
        _round_float(getattr(spec, "motor_target_velocity", 0.0)),
        _round_float(getattr(spec, "motor_target_position", 0.0)),
        str(getattr(spec, "swing_motor_state", "OFF") or "OFF"),
        str(getattr(spec, "twist_motor_state", "OFF") or "OFF"),
        tuple(_round_float(value) for value in getattr(
            spec, "swing_twist_target_angular_velocity", (0.0, 0.0, 0.0),
        )),
        tuple(_round_float(value) for value in getattr(
            spec, "swing_twist_target_orientation_wxyz", (1.0, 0.0, 0.0, 0.0),
        )),
        tuple(str(value) for value in getattr(spec, "six_dof_axis_modes", ("FIXED",) * 6)),
        tuple(_round_float(value) for value in getattr(
            spec, "six_dof_limit_min", (-1.0, -1.0, -1.0, -0.7853981634, -0.7853981634, -0.7853981634),
        )),
        tuple(_round_float(value) for value in getattr(
            spec, "six_dof_limit_max", (1.0, 1.0, 1.0, 0.7853981634, 0.7853981634, 0.7853981634),
        )),
        str(getattr(spec, "six_dof_swing_type", "PYRAMID") or "PYRAMID"),
        tuple(_round_float(value) for value in getattr(
            spec, "six_dof_max_friction", (0.0,) * 6,
        )),
        tuple(_round_float(value) for value in getattr(
            spec, "six_dof_limit_spring_frequency", (0.0,) * 3,
        )),
        tuple(_round_float(value) for value in getattr(
            spec, "six_dof_limit_spring_damping", (0.0,) * 3,
        )),
        tuple(str(value) for value in getattr(spec, "six_dof_motor_states", ("OFF",) * 6)),
        tuple(_round_float(value) for value in getattr(
            spec, "six_dof_target_velocity", (0.0, 0.0, 0.0),
        )),
        tuple(_round_float(value) for value in getattr(
            spec, "six_dof_target_angular_velocity", (0.0, 0.0, 0.0),
        )),
        tuple(_round_float(value) for value in getattr(
            spec, "six_dof_target_position", (0.0, 0.0, 0.0),
        )),
        tuple(_round_float(value) for value in getattr(
            spec, "six_dof_target_orientation_wxyz", (1.0, 0.0, 0.0, 0.0),
        )),
        _round_float(getattr(spec, "cone_half_angle", 0.0)),
        _round_float(getattr(spec, "distance_min", 0.0)),
        _round_float(getattr(spec, "distance_max", 1.0)),
        tuple(_round_float(value) for value in getattr(
            spec, "pulley_fixed_point_a", (-1.0, 2.0, 0.0),
        )),
        tuple(_round_float(value) for value in getattr(
            spec, "pulley_fixed_point_b", (1.0, 2.0, 0.0),
        )),
        _round_float(getattr(spec, "pulley_ratio", 1.0)),
        _round_float(getattr(spec, "pulley_min_length", 0.0)),
        _round_float(getattr(spec, "pulley_max_length", -1.0)),
        str(getattr(spec, "reference_constraint_a", "") or ""),
        str(getattr(spec, "reference_constraint_b", "") or ""),
        _round_float(getattr(spec, "gear_ratio", 1.0)),
        _round_float(getattr(spec, "rack_and_pinion_ratio", 1.0)),
    )


def _flush_rigid_backend_handles(world: PhysicsWorldCache) -> None:
    adapter = world.backend_resources.get(RIGID_BACKEND_RESOURCE_KEY)
    flush = getattr(adapter, "_flush_handles", None)
    if callable(flush):
        try:
            flush()
        except Exception:
            pass


def _mark_all_rigid_slots_for_resync(world: PhysicsWorldCache) -> None:
    _flush_rigid_backend_handles(world)
    for slot in world.solver_slots.values():
        if slot.kind in {RIGID_BODY_SLOT_KIND, RIGID_CONSTRAINT_SLOT_KIND}:
            slot.data.pop("_jolt_generation", None)


def _prune_stale_rigid_slots(
    world: PhysicsWorldCache,
    active_body_ids: set[str],
    active_constraint_ids: set[str],
) -> int:
    stale_ids = []
    for slot_id, slot in list(world.solver_slots.items()):
        if slot.kind == RIGID_BODY_SLOT_KIND and slot_id not in active_body_ids:
            stale_ids.append(slot_id)
        elif slot.kind == RIGID_CONSTRAINT_SLOT_KIND and slot_id not in active_constraint_ids:
            stale_ids.append(slot_id)

    if not stale_ids:
        return 0

    for slot_id in stale_ids:
        slot = world.solver_slots.pop(slot_id, None)
        if slot is not None:
            try:
                slot.dispose("rigid_scope_prune")
            except Exception:
                pass

    _mark_all_rigid_slots_for_resync(world)
    return len(stale_ids)


def collect_rigid_specs_from_scope(world: PhysicsWorldCache, scope: PhysicsObjectScope) -> None:
    """从当前对象作用域收集刚体和约束规格。"""
    if not isinstance(world, PhysicsWorldCache) or not isinstance(scope, PhysicsObjectScope):
        return
    if not (scope.include_rigid_body or scope.include_rigid_constraint):
        return

    solver_id = "_rigid_scope_sync"
    world.acquire_write(solver_id)
    try:
        active_body_ids: set[str] = set()
        active_constraint_ids: set[str] = set(active_generated_constraint_slot_ids(world))
        spec_sync_dirty = False

        for obj in _flatten(scope.objects):
            if scope.include_rigid_body:
                spec = build_rigid_body_spec(obj)
                if spec is not None:
                    active_body_ids.add(spec.slot_id)
                    slot = world.ensure_solver_slot(spec.slot_id, RIGID_BODY_SLOT_KIND)
                    if slot.world_generation != world.generation:
                        slot.data.clear()
                        slot.world_generation = world.generation

                    signature = _rigid_body_sync_signature(spec)
                    previous_signature = slot.data.get("_sync_signature")
                    if previous_signature is not None and previous_signature != signature:
                        spec_sync_dirty = True
                    slot.data["_sync_signature"] = signature

                    pose_signature = _kinematic_pose_signature(spec)
                    previous_pose_signature = slot.data.get("_kinematic_pose_signature")
                    if pose_signature:
                        if (
                            previous_pose_signature is not None
                            and previous_pose_signature != pose_signature
                        ):
                            slot.data["_jolt_kinematic_pose_dirty"] = True
                        slot.data["_kinematic_pose_signature"] = pose_signature
                    else:
                        slot.data.pop("_kinematic_pose_signature", None)
                        slot.data.pop("_jolt_kinematic_pose_dirty", None)

                    slot.data["spec"] = spec
                    slot.data["declaration"] = RIGID_SOLVER_DECLARATION
                    slot.data["_debug_snapshot"] = lambda s=spec: s.debug_dict()

            if scope.include_rigid_constraint:
                try:
                    if obj.type != "EMPTY":
                        continue
                    cspec = build_constraint_spec(obj)
                    if cspec is None:
                        continue

                    active_constraint_ids.add(cspec.slot_id)
                    cslot = world.ensure_solver_slot(cspec.slot_id, RIGID_CONSTRAINT_SLOT_KIND)
                    if cslot.world_generation != world.generation:
                        cslot.data.clear()
                        cslot.world_generation = world.generation

                    signature = _constraint_sync_signature(cspec)
                    previous_signature = cslot.data.get("_sync_signature")
                    if previous_signature is not None and previous_signature != signature:
                        spec_sync_dirty = True
                    cslot.data["_sync_signature"] = signature
                    cslot.data["spec"] = cspec
                    cslot.data["declaration"] = RIGID_SOLVER_DECLARATION
                    cslot.data["_debug_snapshot"] = lambda s=cspec: s.debug_dict()
                except Exception:
                    pass

        pruned = _prune_stale_rigid_slots(world, active_body_ids, active_constraint_ids)
        if spec_sync_dirty:
            _mark_all_rigid_slots_for_resync(world)
        if pruned or spec_sync_dirty:
            world.replace_required = True
    finally:
        world.release_write(solver_id)
