"""Rigid/Jolt fixture runtime through production specs and JoltAdapter."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys
import types
from typing import Any

try:
    from .assertions import evaluate_assertions
    from .canonical import (
        canonical_body_state,
        canonical_contact_event,
        canonical_constraint_state,
        canonical_ray_result,
        physical_trace_hash,
    )
    from .fixture_runtime import NativeRunResult, _constraint_creation_order
    from .schema import Fixture, FixtureError, TimelineEvent
except ImportError:  # Support direct script execution.
    from assertions import evaluate_assertions
    from canonical import (
        canonical_body_state,
        canonical_contact_event,
        canonical_constraint_state,
        canonical_ray_result,
        physical_trace_hash,
    )
    from fixture_runtime import NativeRunResult, _constraint_creation_order
    from schema import Fixture, FixtureError, TimelineEvent


_PACKAGE_ROOT = "_hotools_jolt_adapter_fixture"


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    sys.modules[name] = module


def _load_module(name: str, path: Path):
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def load_production_adapter(rigid_root: str | Path):
    root = Path(rigid_root).resolve()
    _ensure_package(_PACKAGE_ROOT, root.parent)
    _ensure_package(f"{_PACKAGE_ROOT}.rigid", root)
    _ensure_package(f"{_PACKAGE_ROOT}.rigid.backends", root / "backends")
    _load_module(f"{_PACKAGE_ROOT}.rigid.names", root / "names.py")
    specs = _load_module(f"{_PACKAGE_ROOT}.rigid.specs", root / "specs.py")
    adapter = _load_module(
        f"{_PACKAGE_ROOT}.rigid.backends.jolt", root / "backends" / "jolt.py"
    )
    return specs, adapter


class AdapterFixtureRuntime:
    """Run a fixture through production RigidBodySpec/ConstraintSpec/JoltAdapter."""

    RUNNER_ID = "adapter_binding_v1"

    def __init__(self, native_module, rigid_root: str | Path):
        self.native = native_module
        self.specs, self.adapter_module = load_production_adapter(rigid_root)
        self.adapter = None
        self.body_slots: dict[str, str] = {}
        self.body_pointers: dict[str, int] = {}
        self.constraint_slots: dict[str, str] = {}
        self._last_step_ms = 0.0

    def _body_spec(self, body, pointer: int):
        shape = body.shape
        return self.specs.RigidBodySpec(
            obj=None,
            obj_ptr=pointer,
            data_ptr=0,
            simulation_order_key=("fixture_body", body.id),
            world_position=body.position,
            world_rotation_wxyz=body.rotation_wxyz,
            body_type=body.type,
            mass=body.mass,
            friction=body.friction,
            restitution=body.restitution,
            rigid_collision_group=body.collision_group,
            rigid_collides_with_groups=body.collided_by_groups,
            shape_type=shape.type,
            shape_radius=shape.radius,
            shape_half_height=shape.half_height,
            shape_half_extents=shape.half_extents,
            shape_plane_half_extent=shape.plane_half_extent,
            shape_top_radius=shape.top_radius,
            shape_bottom_radius=shape.bottom_radius,
            shape_convex_radius=shape.convex_radius,
            shape_offset=shape.offset,
            shape_rotation_wxyz=shape.rotation_wxyz,
            linear_velocity=body.linear_velocity,
            angular_velocity=body.angular_velocity,
            linear_damping=body.linear_damping,
            angular_damping=body.angular_damping,
            gravity_factor=body.gravity_factor,
            allow_sleeping=body.allow_sleeping,
            motion_quality=body.motion_quality,
            max_linear_velocity=body.max_linear_velocity,
            max_angular_velocity=body.max_angular_velocity,
            is_sensor=body.is_sensor,
            collide_kinematic_vs_non_dynamic=body.collide_kinematic_vs_non_dynamic,
            allowed_dofs=body.allowed_dofs,
        )

    def _constraint_spec(self, constraint):
        slot_id = f"fixture.constraint:{constraint.id}"
        target_a_ptr = self.body_pointers.get(constraint.body_a, 0)
        target_b_ptr = self.body_pointers.get(constraint.body_b, 0)
        return self.specs.ConstraintSpec(
            empty_obj=None,
            empty_ptr=0,
            slot_id=slot_id,
            simulation_order_key=("fixture_constraint", constraint.id),
            constraint_type=constraint.type,
            target_a_ptr=target_a_ptr,
            target_b_ptr=target_b_ptr,
            disable_collisions=constraint.disable_collisions,
            breakable=constraint.breakable,
            breaking_threshold=constraint.breaking_threshold,
            anchor_mode=(
                "LOCAL_FRAMES" if constraint.use_separate_anchor_frames
                else "SHARED_WORLD"
            ),
            anchor_position=constraint.anchor_position,
            anchor_rotation_wxyz=constraint.anchor_rotation_wxyz,
            anchor_position_a=constraint.anchor_position_a,
            anchor_rotation_wxyz_a=constraint.anchor_rotation_wxyz_a,
            anchor_position_b=constraint.anchor_position_b,
            anchor_rotation_wxyz_b=constraint.anchor_rotation_wxyz_b,
            constraint_priority=constraint.priority,
            solver_velocity_steps=constraint.solver_velocity_steps,
            solver_position_steps=constraint.solver_position_steps,
            draw_constraint_size=constraint.draw_size,
            limit_enabled=constraint.limit_enabled,
            angular_limit_min=constraint.angular_limit_min,
            angular_limit_max=constraint.angular_limit_max,
            linear_limit_min=constraint.linear_limit_min,
            linear_limit_max=constraint.linear_limit_max,
            limit_spring_frequency=constraint.limit_spring_frequency,
            limit_spring_damping=constraint.limit_spring_damping,
            max_friction_torque=constraint.max_friction_torque,
            max_friction_force=constraint.max_friction_force,
            motor_state=constraint.motor_state,
            motor_frequency=constraint.motor_frequency,
            motor_damping=constraint.motor_damping,
            motor_force_limit=constraint.motor_force_limit,
            motor_torque_limit=constraint.motor_torque_limit,
            motor_target_angular_velocity=constraint.motor_target_angular_velocity,
            motor_target_angle=constraint.motor_target_angle,
            motor_target_velocity=constraint.motor_target_velocity,
            motor_target_position=constraint.motor_target_position,
            swing_motor_state=constraint.swing_motor_state,
            twist_motor_state=constraint.twist_motor_state,
            swing_twist_target_angular_velocity=constraint.swing_twist_target_angular_velocity,
            swing_twist_target_orientation_wxyz=constraint.swing_twist_target_orientation_wxyz,
            six_dof_axis_modes=constraint.six_dof_axis_modes,
            six_dof_limit_min=constraint.six_dof_limit_min,
            six_dof_limit_max=constraint.six_dof_limit_max,
            six_dof_swing_type=constraint.six_dof_swing_type,
            six_dof_max_friction=constraint.six_dof_max_friction,
            six_dof_limit_spring_frequency=constraint.six_dof_limit_spring_frequency,
            six_dof_limit_spring_damping=constraint.six_dof_limit_spring_damping,
            six_dof_motor_states=constraint.six_dof_motor_states,
            six_dof_target_velocity=constraint.six_dof_target_velocity,
            six_dof_target_angular_velocity=constraint.six_dof_target_angular_velocity,
            six_dof_target_position=constraint.six_dof_target_position,
            six_dof_target_orientation_wxyz=constraint.six_dof_target_orientation_wxyz,
            cone_half_angle=constraint.cone_half_angle,
            swing_type=constraint.swing_type,
            swing_normal_half_angle=constraint.swing_normal_half_angle,
            swing_plane_half_angle=constraint.swing_plane_half_angle,
            twist_min_angle=constraint.twist_min_angle,
            twist_max_angle=constraint.twist_max_angle,
            distance_min=constraint.distance_min,
            distance_max=constraint.distance_max,
            pulley_fixed_point_a=constraint.pulley_fixed_point_a,
            pulley_fixed_point_b=constraint.pulley_fixed_point_b,
            pulley_ratio=constraint.pulley_ratio,
            pulley_min_length=constraint.pulley_min_length,
            pulley_max_length=constraint.pulley_max_length,
            reference_constraint_a=self.constraint_slots.get(
                constraint.reference_constraint_a, ""
            ),
            reference_constraint_b=self.constraint_slots.get(
                constraint.reference_constraint_b, ""
            ),
            gear_ratio=constraint.gear_ratio,
            rack_and_pinion_ratio=constraint.rack_and_pinion_ratio,
        )

    def _require_body_slot(self, body_id: str) -> str:
        try:
            return self.body_slots[body_id]
        except KeyError as exc:
            raise FixtureError(f"timeline references unknown body: {body_id}") from exc

    def _apply_event(self, event: TimelineEvent) -> None:
        values = event.values
        if event.op == "set_world_gravity":
            gravity = values.get("gravity")
            if gravity is None:
                raise FixtureError("set_world_gravity requires gravity")
            self.adapter.set_gravity(gravity)
            return
        if event.op == "remove_constraint":
            try:
                slot_id = self.constraint_slots.pop(event.constraint)
            except KeyError as exc:
                raise FixtureError(
                    f"timeline references inactive constraint: {event.constraint}"
                ) from exc
            self.adapter.remove_constraint(slot_id)
            return

        slot_id = self._require_body_slot(event.body)
        if event.op == "set_velocity":
            ok = self.adapter.set_body_velocity(
                slot_id,
                values.get("linear_velocity", (0.0, 0.0, 0.0)),
                values.get("angular_velocity", (0.0, 0.0, 0.0)),
            )
        elif event.op == "add_impulse":
            if "impulse" not in values and "angular_impulse" not in values:
                raise FixtureError("add_impulse requires impulse or angular_impulse")
            ok = self.adapter.add_body_impulse(
                slot_id,
                values.get("impulse", (0.0, 0.0, 0.0)),
                values.get("angular_impulse", (0.0, 0.0, 0.0)),
            )
        elif event.op == "add_force":
            if "force" not in values and "torque" not in values:
                raise FixtureError("add_force requires force or torque")
            ok = self.adapter.add_body_force(
                slot_id,
                values.get("force", (0.0, 0.0, 0.0)),
                values.get("torque", (0.0, 0.0, 0.0)),
            )
        elif event.op == "set_gravity_factor":
            ok = self.adapter.set_body_gravity_factor(
                slot_id, values["gravity_factor"]
            )
        elif event.op == "activate":
            ok = self.adapter.set_body_active(slot_id, values["active"])
        else:
            raise FixtureError(f"unsupported timeline op: {event.op}")
        if not ok:
            raise RuntimeError(
                f"adapter operation {event.op} rejected body {event.body} "
                f"at frame {event.frame}"
            )

    @staticmethod
    def _body_state_tuple(state: dict) -> tuple:
        return (
            state["position"],
            state["rotation_wxyz"],
            state["linear_velocity"],
            state["angular_velocity"],
            state["active"],
            state["sleeping"],
        )

    @staticmethod
    def _constraint_state_tuple(state: dict) -> tuple:
        return (
            state["constraint_type"],
            state["enabled"],
            state["current_value_kind"],
            state["current_value"],
            state["lambda_position"],
            state["lambda_rotation"],
            state["lambda_limit"],
            state["lambda_motor"],
            state["current_translation"],
            state["current_rotation"],
        )

    def _sample(self, fixture: Fixture, frame: int) -> dict[str, Any]:
        body_ids = sorted(self.body_slots)
        pseudo_handles = {body_id: index + 1 for index, body_id in enumerate(body_ids)}
        handle_to_id = {handle: body_id for body_id, handle in pseudo_handles.items()}
        slot_to_handle = {
            self.body_slots[body_id]: pseudo_handles[body_id] for body_id in body_ids
        }
        bodies = [
            canonical_body_state(
                body_id,
                self._body_state_tuple(
                    self.adapter.get_body_state(self.body_slots[body_id])
                ),
            )
            for body_id in body_ids
        ]
        constraints = []
        for constraint_id in sorted(self.constraint_slots):
            constraint = fixture.constraints_by_id[constraint_id]
            state = self.adapter.get_constraint_state(
                self.constraint_slots[constraint_id]
            )
            if state is not None:
                constraints.append(canonical_constraint_state(
                    constraint_id,
                    self._constraint_state_tuple(state),
                    breakable=constraint.breakable,
                    breaking_threshold=constraint.breaking_threshold,
                ))

        contacts = []
        for event in self.adapter.get_contact_events():
            raw = (
                event["state"],
                slot_to_handle[event["body_a_slot_id"]],
                slot_to_handle[event["body_b_slot_id"]],
                event["body_a_sensor"],
                event["body_b_sensor"],
                event["is_sensor"],
                event["normal"],
                event["penetration_depth"],
                event["points_on_a"],
                event["points_on_b"],
                event["sub_shape_a"],
                event["sub_shape_b"],
            )
            contacts.append(canonical_contact_event(raw, handle_to_id))
        contacts.sort(key=lambda item: (
            item["body_a"], item["body_b"], item["state"],
            item["sub_shape_a"], item["sub_shape_b"],
        ))

        queries = []
        for query in sorted(fixture.queries, key=lambda item: item.id):
            if query.frame != frame:
                continue
            max_distance = math.sqrt(sum(value * value for value in query.direction))
            result = self.adapter.ray_cast(
                query.origin,
                query.direction,
                max_distance=max_distance,
                include_sensors=query.include_sensors,
                ignore_slot_id=self.body_slots.get(query.ignore_body),
            )
            hit_slot = str(result.get("slot_id", "") or "")
            raw = (
                bool(result.get("hit", False)),
                slot_to_handle.get(hit_slot, 0),
                result.get("position", (0.0, 0.0, 0.0)),
                result.get("normal", (0.0, 0.0, 0.0)),
                float(result.get("fraction", 0.0)),
                int(result.get("sub_shape_id", 0)),
                bool(result.get("is_sensor", False)),
            )
            queries.append(canonical_ray_result(query.id, raw, handle_to_id))

        return {
            "fixture_id": fixture.id,
            "runner": self.RUNNER_ID,
            "frame": frame,
            "dt": fixture.world.dt,
            "substeps": fixture.world.substeps,
            "bodies": bodies,
            "constraints": constraints,
            "contacts": contacts,
            "queries": queries,
            "stats": {
                "body_count": int(self.adapter.body_count),
                "constraint_count": int(self.adapter.constraint_count),
                "contact_event_count": len(contacts),
                "contact_event_overflow": int(
                    self.adapter.last_contact_event_overflow
                ),
                "step_ms": float(self._last_step_ms),
            },
        }

    def run(self, fixture: Fixture, repeat_index: int = 0) -> NativeRunResult:
        settings = fixture.world
        self.adapter = self.adapter_module.JoltAdapter(
            max_bodies=settings.max_bodies,
            max_body_pairs=settings.max_body_pairs,
            max_contact_constraints=settings.max_contact_constraints,
        )
        self.body_slots = {}
        self.body_pointers = {}
        self.constraint_slots = {}
        trace: list[dict[str, Any]] = []
        sample_frames = set(fixture.sample_frames)
        events: dict[tuple[int, str], list[TimelineEvent]] = {}
        for event in fixture.timeline:
            events.setdefault((event.frame, event.phase), []).append(event)
        try:
            self.adapter.set_gravity(settings.gravity)
            for pointer, body in enumerate(
                sorted(fixture.bodies, key=lambda item: item.id), start=1
            ):
                spec = self._body_spec(body, pointer)
                self.body_pointers[body.id] = pointer
                self.body_slots[body.id] = spec.slot_id
                self.adapter.sync_body(spec.slot_id, spec)
            for constraint in _constraint_creation_order(fixture.constraints):
                spec = self._constraint_spec(constraint)
                self.adapter.sync_constraint(spec.slot_id, spec)
                self.constraint_slots[constraint.id] = spec.slot_id
            if 0 in sample_frames:
                trace.append(self._sample(fixture, 0))
            for frame in range(1, settings.frames + 1):
                for event in events.get((frame, "pre_step"), ()):
                    self._apply_event(event)
                self._last_step_ms = float(
                    self.adapter.step(settings.dt, settings.substeps)
                )
                for event in events.get((frame, "post_step"), ()):
                    self._apply_event(event)
                if frame in sample_frames:
                    trace.append(self._sample(fixture, frame))
            assertion_results = evaluate_assertions(fixture, trace)
            return NativeRunResult(
                fixture=fixture,
                repeat_index=repeat_index,
                trace=trace,
                assertions=assertion_results,
                physical_hash=physical_trace_hash(trace),
                native_module_path=str(Path(self.native.__file__).resolve()),
            )
        finally:
            if self.adapter is not None:
                try:
                    self.adapter.dispose("adapter_fixture_runtime")
                finally:
                    self.adapter = None
                    self.body_slots = {}
                    self.body_pointers = {}
                    self.constraint_slots = {}
