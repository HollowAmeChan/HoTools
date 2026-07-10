"""Rigid/Jolt 语义 fixture 的 native 执行运行时。"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
from typing import Any, Mapping

try:
    from .assertions import evaluate_assertions
    from .canonical import (
        canonical_body_state,
        canonical_contact_event,
        canonical_constraint_state,
        canonical_ray_result,
        physical_trace_hash,
    )
    from .schema import BodySpec, ConstraintSpec, Fixture, FixtureError, TimelineEvent
except ImportError:  # 支持脚本直接执行。
    from assertions import evaluate_assertions
    from canonical import (
        canonical_body_state,
        canonical_contact_event,
        canonical_constraint_state,
        canonical_ray_result,
        physical_trace_hash,
    )
    from schema import BodySpec, ConstraintSpec, Fixture, FixtureError, TimelineEvent


@dataclass
class NativeRunResult:
    fixture: Fixture
    repeat_index: int
    trace: list[dict[str, Any]]
    assertions: list[dict[str, Any]]
    physical_hash: str
    native_module_path: str

    @property
    def passed(self) -> bool:
        return all(result["passed"] for result in self.assertions)


def default_native_dir(repo_root: Path) -> Path:
    py_lib = "py313" if sys.version_info >= (3, 13) else "py311"
    return repo_root / "_Lib" / py_lib / "HotoolsPackage"


def load_native_module(native_dir: str | Path):
    directory = Path(native_dir).resolve()
    if not directory.is_dir():
        raise RuntimeError(f"native module directory does not exist: {directory}")
    directory_text = str(directory)
    if directory_text not in sys.path:
        sys.path.insert(0, directory_text)
    try:
        module = importlib.import_module("hotools_jolt")
    except ImportError as exc:
        raise RuntimeError(f"cannot import hotools_jolt from {directory}") from exc
    module_path = Path(getattr(module, "__file__", "")).resolve()
    if directory not in module_path.parents:
        raise RuntimeError(
            f"hotools_jolt loaded from {module_path}, expected it under {directory}"
        )
    return module


class NativeFixtureRuntime:
    """通过 hotools_jolt.JoltWorld 直接构建并执行一份 fixture。"""

    RUNNER_ID = "native_binding_v1"

    def __init__(self, native_module):
        self.native = native_module
        self.world = None
        self.handles: dict[str, int] = {}
        self.constraint_handles: dict[str, int] = {}
        self._last_step_ms = 0.0

    def _add_body(self, body: BodySpec) -> int:
        shape = body.shape
        return int(self.world.add_body(
            body_type=body.type,
            mass=body.mass,
            friction=body.friction,
            restitution=body.restitution,
            position=body.position,
            rotation_wxyz=body.rotation_wxyz,
            shape_type=shape.type,
            shape_radius=shape.radius,
            shape_half_height=shape.half_height,
            shape_half_extents=shape.half_extents,
            collision_group=body.collision_group,
            collided_by_groups=body.collided_by_groups,
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
            allowed_dofs=body.allowed_dofs,
            collide_kinematic_vs_non_dynamic=body.collide_kinematic_vs_non_dynamic,
            shape_plane_half_extent=shape.plane_half_extent,
            shape_top_radius=shape.top_radius,
            shape_bottom_radius=shape.bottom_radius,
            shape_convex_radius=shape.convex_radius,
        ))

    def _constraint_body_handle(self, body_id: str) -> int:
        if body_id == "WORLD":
            return int(self.native.WORLD_HANDLE)
        return self._require_handle(body_id)

    def _add_constraint(self, constraint: ConstraintSpec) -> int:
        return int(self.world.add_constraint(
            constraint_type=constraint.type,
            body_a_handle=self._constraint_body_handle(constraint.body_a),
            body_b_handle=self._constraint_body_handle(constraint.body_b),
            anchor_pos=constraint.anchor_position,
            anchor_rot_wxyz=constraint.anchor_rotation_wxyz,
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
            disable_collisions=constraint.disable_collisions,
            distance_min=constraint.distance_min,
            distance_max=constraint.distance_max,
            use_separate_anchor_frames=constraint.use_separate_anchor_frames,
            anchor_pos_a=constraint.anchor_position_a,
            anchor_rot_wxyz_a=constraint.anchor_rotation_wxyz_a,
            anchor_pos_b=constraint.anchor_position_b,
            anchor_rot_wxyz_b=constraint.anchor_rotation_wxyz_b,
        ))

    def _require_handle(self, body_id: str) -> int:
        try:
            return self.handles[body_id]
        except KeyError as exc:
            raise FixtureError(f"timeline references unknown body: {body_id}") from exc

    def _apply_event(self, event: TimelineEvent) -> None:
        values = event.values
        if event.op == "set_world_gravity":
            gravity = values.get("gravity")
            if gravity is None:
                raise FixtureError("set_world_gravity requires gravity")
            self.world.set_gravity(gravity)
            return
        if event.op == "remove_constraint":
            try:
                handle = self.constraint_handles.pop(event.constraint)
            except KeyError as exc:
                raise FixtureError(
                    f"timeline references inactive constraint: {event.constraint}"
                ) from exc
            self.world.remove_constraint(handle)
            return
        handle = self._require_handle(event.body)
        if event.op == "set_velocity":
            ok = self.world.set_body_velocity(
                handle,
                values.get("linear_velocity", (0.0, 0.0, 0.0)),
                values.get("angular_velocity", (0.0, 0.0, 0.0)),
            )
        elif event.op == "add_impulse":
            if "impulse" not in values and "angular_impulse" not in values:
                raise FixtureError("add_impulse requires impulse or angular_impulse")
            ok = self.world.add_body_impulse(
                handle,
                values.get("impulse", (0.0, 0.0, 0.0)),
                values.get("angular_impulse", (0.0, 0.0, 0.0)),
            )
        elif event.op == "add_force":
            if "force" not in values and "torque" not in values:
                raise FixtureError("add_force requires force or torque")
            ok = self.world.add_body_force(
                handle,
                values.get("force", (0.0, 0.0, 0.0)),
                values.get("torque", (0.0, 0.0, 0.0)),
            )
        elif event.op == "set_gravity_factor":
            if "gravity_factor" not in values:
                raise FixtureError("set_gravity_factor requires gravity_factor")
            ok = self.world.set_body_gravity_factor(handle, values["gravity_factor"])
        elif event.op == "activate":
            if "active" not in values:
                raise FixtureError("activate requires active")
            ok = self.world.activate_body(handle, values["active"])
        else:  # schema 校验后不应进入此分支。
            raise FixtureError(f"unsupported timeline op: {event.op}")
        if not ok:
            raise RuntimeError(
                f"native operation {event.op} rejected body {event.body} at frame {event.frame}"
            )

    def _sample(self, fixture: Fixture, frame: int) -> dict[str, Any]:
        bodies = [
            canonical_body_state(body.id, self.world.get_body_state(self.handles[body.id]))
            for body in sorted(fixture.bodies, key=lambda item: item.id)
        ]
        constraints = [
            canonical_constraint_state(
                constraint.id,
                self.world.get_constraint_state(self.constraint_handles[constraint.id]),
            )
            for constraint in sorted(fixture.constraints, key=lambda item: item.id)
            if constraint.id in self.constraint_handles
        ]
        handle_to_id = {handle: body_id for body_id, handle in self.handles.items()}
        contacts = []
        if hasattr(self.world, "get_contact_events"):
            contacts = [
                canonical_contact_event(event, handle_to_id)
                for event in self.world.get_contact_events()
            ]
            contacts.sort(key=lambda item: (
                item["body_a"], item["body_b"], item["state"],
                item["sub_shape_a"], item["sub_shape_b"],
            ))
        queries = []
        for query in sorted(fixture.queries, key=lambda item: item.id):
            if query.frame != frame:
                continue
            ignore_handle = self.handles.get(query.ignore_body, 0)
            result = self.world.cast_ray(
                query.origin, query.direction, query.include_sensors, ignore_handle,
            )
            queries.append(canonical_ray_result(query.id, result, handle_to_id))
        overflow = int(getattr(self.world, "contact_event_overflow_count", 0))
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
                "body_count": int(self.world.body_count),
                "constraint_count": int(self.world.constraint_count),
                "contact_event_count": len(contacts),
                "contact_event_overflow": overflow,
                "step_ms": float(self._last_step_ms),
            },
        }

    def run(self, fixture: Fixture, repeat_index: int = 0) -> NativeRunResult:
        if fixture.constraints and not hasattr(self.native.JoltWorld, "get_constraint_state"):
            raise RuntimeError(
                f"{fixture.id}: 当前 hotools_jolt 二进制缺少约束状态 ABI，请先重建对应 Python ABI"
            )
        if fixture.queries and not hasattr(self.native.JoltWorld, "cast_ray"):
            raise RuntimeError(
                f"{fixture.id}: 当前 hotools_jolt 二进制缺少 RayCast ABI，请先重建对应 Python ABI"
            )
        settings = fixture.world
        self.world = self.native.JoltWorld(
            max_bodies=settings.max_bodies,
            max_body_pairs=settings.max_body_pairs,
            max_contact_constraints=settings.max_contact_constraints,
        )
        self.handles = {}
        self.constraint_handles = {}
        trace: list[dict[str, Any]] = []
        sample_frames = set(fixture.sample_frames)
        events: dict[tuple[int, str], list[TimelineEvent]] = {}
        for event in fixture.timeline:
            events.setdefault((event.frame, event.phase), []).append(event)
        try:
            self.world.set_gravity(settings.gravity)
            for body in sorted(fixture.bodies, key=lambda item: item.id):
                handle = self._add_body(body)
                if handle == int(getattr(self.native, "INVALID_HANDLE", 0)):
                    raise RuntimeError(f"native failed to add body {body.id}")
                self.handles[body.id] = handle
            for constraint in sorted(fixture.constraints, key=lambda item: item.id):
                handle = self._add_constraint(constraint)
                if handle == int(getattr(self.native, "INVALID_HANDLE", 0)):
                    raise RuntimeError(f"native failed to add constraint {constraint.id}")
                self.constraint_handles[constraint.id] = handle
            if 0 in sample_frames:
                trace.append(self._sample(fixture, 0))
            for frame in range(1, settings.frames + 1):
                for event in events.get((frame, "pre_step"), ()):
                    self._apply_event(event)
                self._last_step_ms = float(self.world.step(settings.dt, settings.substeps))
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
            if self.world is not None:
                try:
                    self.world.clear()
                finally:
                    self.world = None
                    self.handles = {}
                    self.constraint_handles = {}
