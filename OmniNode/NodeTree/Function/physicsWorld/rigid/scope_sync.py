"""Rigid/Jolt scope-to-slot synchronization.

Physics World Begin owns frame/scope lifecycle.  The rigid domain owns how
PhysicsTools rigid properties become RigidBodySpec / ConstraintSpec slots and
which changes require Jolt resync.
"""

from __future__ import annotations

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
    """Return the fields that affect Jolt body creation/sync."""
    body_type = str(getattr(spec, "body_type", "DYNAMIC") or "DYNAMIC")
    static_pose = ()
    if body_type == "STATIC":
        static_pose = (
            _round_tuple(getattr(spec, "world_position", (0.0, 0.0, 0.0))),
            _round_tuple(getattr(spec, "world_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
        )

    return (
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
        str(getattr(spec, "constraint_type", "FIXED") or "FIXED"),
        int(getattr(spec, "target_a_ptr", 0) or 0),
        int(getattr(spec, "target_b_ptr", 0) or 0),
        bool(getattr(spec, "disable_collisions", True)),
        _round_tuple(getattr(spec, "anchor_position", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "anchor_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
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
        _round_float(getattr(spec, "cone_half_angle", 0.0)),
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
    """Collect rigid body/constraint specs from the current object scope."""
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
