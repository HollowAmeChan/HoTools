"""Rigid/Jolt 语义 fixture 的 native 执行运行时。"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
from typing import Any, Mapping

try:
    from .assertions import evaluate_assertions
    from .canonical import canonical_body_state, canonical_value, physical_trace_hash
    from .schema import BodySpec, Fixture, FixtureError, TimelineEvent
except ImportError:  # 支持脚本直接执行。
    from assertions import evaluate_assertions
    from canonical import canonical_body_state, canonical_value, physical_trace_hash
    from schema import BodySpec, Fixture, FixtureError, TimelineEvent


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
        contacts = []
        if hasattr(self.world, "get_contact_events"):
            contacts = canonical_value(
                list(self.world.get_contact_events()), f"frame[{frame}].contacts",
            )
        overflow = int(getattr(self.world, "contact_event_overflow_count", 0))
        return {
            "fixture_id": fixture.id,
            "runner": self.RUNNER_ID,
            "frame": frame,
            "dt": fixture.world.dt,
            "substeps": fixture.world.substeps,
            "bodies": bodies,
            "constraints": [],
            "contacts": contacts,
            "queries": [],
            "stats": {
                "body_count": int(self.world.body_count),
                "constraint_count": int(self.world.constraint_count),
                "contact_event_count": len(contacts),
                "contact_event_overflow": overflow,
                "step_ms": float(self._last_step_ms),
            },
        }

    def run(self, fixture: Fixture, repeat_index: int = 0) -> NativeRunResult:
        if fixture.constraints:
            raise FixtureError(
                f"{fixture.id}: constraints are reserved by schema v1 but not yet supported "
                "by native_binding_v1"
            )
        settings = fixture.world
        self.world = self.native.JoltWorld(
            max_bodies=settings.max_bodies,
            max_body_pairs=settings.max_body_pairs,
            max_contact_constraints=settings.max_contact_constraints,
        )
        self.handles = {}
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
