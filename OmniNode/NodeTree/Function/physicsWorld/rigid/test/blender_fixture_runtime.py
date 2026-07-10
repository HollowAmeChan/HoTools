"""Blender pipeline runtime for the shared Rigid/Jolt semantic fixtures."""

from __future__ import annotations

import math
from pathlib import Path
import runpy
from typing import Any

import bpy
import mathutils

try:
    from .assertions import evaluate_assertions
    from .canonical import (
        canonical_body_state,
        canonical_contact_event,
        canonical_constraint_state,
        canonical_ray_result,
        physical_trace_hash,
    )
    from .compare_traces import compare_traces
    from .fixture_runtime import NativeFixtureRuntime, NativeRunResult
    from .schema import Fixture
except ImportError:  # Support direct script execution inside Blender.
    from assertions import evaluate_assertions
    from canonical import (
        canonical_body_state,
        canonical_contact_event,
        canonical_constraint_state,
        canonical_ray_result,
        physical_trace_hash,
    )
    from compare_traces import compare_traces
    from fixture_runtime import NativeFixtureRuntime, NativeRunResult
    from schema import Fixture


_BOOTSTRAP = None


def _bootstrap(bootstrap_path: str | Path):
    global _BOOTSTRAP
    if _BOOTSTRAP is None:
        _BOOTSTRAP = runpy.run_path(
            str(Path(bootstrap_path).resolve()),
            run_name="_hotools_rigid_blender_fixture_bootstrap",
        )
    return _BOOTSTRAP


class BlenderFixtureRuntime:
    """Build Blender RNA objects, then run world/scope/result/writeback pipeline."""

    RUNNER_ID = "blender_pipeline_v1"
    SUPPORTED_FIXTURES = frozenset(
        path.stem for path in (Path(__file__).parent / "fixtures").rglob("*.json")
    )

    def __init__(self, native_module, bootstrap_path: str | Path):
        self.native = native_module
        self.api = _bootstrap(bootstrap_path)
        self.objects: dict[str, bpy.types.Object] = {}
        self.constraints: dict[str, bpy.types.Object] = {}
        self._owned_objects: list[bpy.types.Object] = []
        self._last_step_ms = 0.0
        self._gravity = (0.0, 0.0, -9.81)

    @staticmethod
    def _set_if_present(target, name: str, value) -> None:
        if hasattr(target, name):
            setattr(target, name, value)

    def _create_body(self, body) -> bpy.types.Object:
        mesh = bpy.data.meshes.new(f"S3_{body.id}_mesh")
        obj = bpy.data.objects.new(f"S3_{body.id}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = body.position
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = mathutils.Quaternion(body.rotation_wxyz)
        props = obj.hotools_rigid_body
        props.enabled = True
        direct = {
            "body_type": body.type,
            "mass": body.mass,
            "friction": body.friction,
            "restitution": body.restitution,
            "rigid_collision_group": body.collision_group,
            "rigid_collides_with_groups": body.collided_by_groups,
            "shape_type": body.shape.type,
            "shape_radius": body.shape.radius,
            "shape_half_height": body.shape.half_height,
            "shape_half_extents": body.shape.half_extents,
            "shape_plane_half_extent": body.shape.plane_half_extent,
            "shape_top_radius": body.shape.top_radius,
            "shape_bottom_radius": body.shape.bottom_radius,
            "shape_convex_radius": body.shape.convex_radius,
            "shape_offset": body.shape.offset,
            "linear_velocity": body.linear_velocity,
            "angular_velocity": body.angular_velocity,
            "linear_damping": body.linear_damping,
            "angular_damping": body.angular_damping,
            "gravity_factor": body.gravity_factor,
            "allow_sleeping": body.allow_sleeping,
            "motion_quality": body.motion_quality,
            "max_linear_velocity": body.max_linear_velocity,
            "max_angular_velocity": body.max_angular_velocity,
            "is_sensor": body.is_sensor,
            "collide_kinematic_vs_non_dynamic": body.collide_kinematic_vs_non_dynamic,
        }
        for name, value in direct.items():
            self._set_if_present(props, name, value)
        props.shape_rotation = mathutils.Quaternion(
            body.shape.rotation_wxyz
        ).to_euler("XYZ")
        for index, suffix in enumerate(("x", "y", "z")):
            self._set_if_present(
                props, f"lock_linear_{suffix}", not bool(body.allowed_dofs & (1 << index))
            )
            self._set_if_present(
                props, f"lock_angular_{suffix}",
                not bool(body.allowed_dofs & (1 << (index + 3)))
            )
        self.objects[body.id] = obj
        self._owned_objects.append(obj)
        return obj

    @staticmethod
    def _world_frame_to_local(target, position, rotation_wxyz):
        world_position = mathutils.Vector(position)
        world_rotation = mathutils.Quaternion(rotation_wxyz)
        if target is None:
            return tuple(world_position), tuple(world_rotation.to_euler("XYZ"))
        local_position = target.matrix_world.inverted() @ world_position
        _location, target_rotation, _scale = target.matrix_world.decompose()
        local_rotation = target_rotation.inverted() @ world_rotation
        return tuple(local_position), tuple(local_rotation.to_euler("XYZ"))

    def _create_constraint(self, constraint) -> bpy.types.Object:
        obj = bpy.data.objects.new(f"S3_{constraint.id}", None)
        bpy.context.scene.collection.objects.link(obj)
        obj.empty_display_type = "ARROWS"
        obj.location = constraint.anchor_position
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = mathutils.Quaternion(
            constraint.anchor_rotation_wxyz
        )
        props = obj.hotools_rigid_constraint
        props.enabled = True
        props.constraint_type = constraint.type
        props.target_a = self.objects.get(constraint.body_a)
        props.target_b = self.objects.get(constraint.body_b)
        direct = {
            "disable_collisions": constraint.disable_collisions,
            "constraint_priority": constraint.priority,
            "solver_velocity_steps": constraint.solver_velocity_steps,
            "solver_position_steps": constraint.solver_position_steps,
            "draw_constraint_size": constraint.draw_size,
            "limit_enabled": constraint.limit_enabled,
            "angular_limit_min": constraint.angular_limit_min,
            "angular_limit_max": constraint.angular_limit_max,
            "linear_limit_min": constraint.linear_limit_min,
            "linear_limit_max": constraint.linear_limit_max,
            "limit_spring_frequency": constraint.limit_spring_frequency,
            "limit_spring_damping": constraint.limit_spring_damping,
            "max_friction_torque": constraint.max_friction_torque,
            "max_friction_force": constraint.max_friction_force,
            "motor_state": constraint.motor_state,
            "motor_frequency": constraint.motor_frequency,
            "motor_damping": constraint.motor_damping,
            "motor_force_limit": constraint.motor_force_limit,
            "motor_torque_limit": constraint.motor_torque_limit,
            "motor_target_angular_velocity": constraint.motor_target_angular_velocity,
            "motor_target_angle": constraint.motor_target_angle,
            "motor_target_velocity": constraint.motor_target_velocity,
            "motor_target_position": constraint.motor_target_position,
            "distance_min": constraint.distance_min,
            "distance_max": constraint.distance_max,
            "swing_motor_state": constraint.swing_motor_state,
            "twist_motor_state": constraint.twist_motor_state,
            "swing_twist_target_angular_velocity": (
                constraint.swing_twist_target_angular_velocity
            ),
            "six_dof_swing_type": constraint.six_dof_swing_type,
            "six_dof_target_velocity": constraint.six_dof_target_velocity,
            "six_dof_target_angular_velocity": (
                constraint.six_dof_target_angular_velocity
            ),
            "six_dof_target_position": constraint.six_dof_target_position,
            "cone_half_angle": constraint.cone_half_angle,
            "swing_type": constraint.swing_type,
            "swing_normal_half_angle": constraint.swing_normal_half_angle,
            "swing_plane_half_angle": constraint.swing_plane_half_angle,
            "twist_min_angle": constraint.twist_min_angle,
            "twist_max_angle": constraint.twist_max_angle,
            "pulley_fixed_point_a": constraint.pulley_fixed_point_a,
            "pulley_fixed_point_b": constraint.pulley_fixed_point_b,
            "pulley_ratio": constraint.pulley_ratio,
            "pulley_min_length": constraint.pulley_min_length,
            "pulley_max_length": constraint.pulley_max_length,
            "gear_ratio": constraint.gear_ratio,
            "rack_and_pinion_ratio": constraint.rack_and_pinion_ratio,
        }
        for name, value in direct.items():
            self._set_if_present(props, name, value)
        props.swing_twist_target_rotation = mathutils.Quaternion(
            constraint.swing_twist_target_orientation_wxyz
        ).to_euler("XYZ")
        props.six_dof_target_rotation = mathutils.Quaternion(
            constraint.six_dof_target_orientation_wxyz
        ).to_euler("XYZ")
        axis_names = (
            "translation_x", "translation_y", "translation_z",
            "rotation_x", "rotation_y", "rotation_z",
        )
        for index, axis_name in enumerate(axis_names):
            axis_values = {
                "mode": constraint.six_dof_axis_modes[index],
                "min": constraint.six_dof_limit_min[index],
                "max": constraint.six_dof_limit_max[index],
                "friction": constraint.six_dof_max_friction[index],
                "motor_state": constraint.six_dof_motor_states[index],
            }
            if index < 3:
                axis_values.update({
                    "limit_spring_frequency": (
                        constraint.six_dof_limit_spring_frequency[index]
                    ),
                    "limit_spring_damping": (
                        constraint.six_dof_limit_spring_damping[index]
                    ),
                })
            for suffix, value in axis_values.items():
                self._set_if_present(
                    props, f"six_dof_{axis_name}_{suffix}", value
                )
        if constraint.use_separate_anchor_frames:
            props.anchor_mode = "LOCAL_FRAMES"
            point_a, rotation_a = self._world_frame_to_local(
                props.target_a,
                constraint.anchor_position_a,
                constraint.anchor_rotation_wxyz_a,
            )
            point_b, rotation_b = self._world_frame_to_local(
                props.target_b,
                constraint.anchor_position_b,
                constraint.anchor_rotation_wxyz_b,
            )
            props.local_point_a = point_a
            props.local_rotation_a = rotation_a
            props.local_point_b = point_b
            props.local_rotation_b = rotation_b
        else:
            props.anchor_mode = "SHARED_WORLD"
        self.constraints[constraint.id] = obj
        self._owned_objects.append(obj)
        return obj

    def _build_scene(self, fixture: Fixture) -> None:
        self.objects = {}
        self.constraints = {}
        self._owned_objects = []
        for body in sorted(fixture.bodies, key=lambda item: item.id):
            self._create_body(body)
        bpy.context.view_layer.update()
        for constraint in fixture.constraints:
            self._create_constraint(constraint)
        for constraint in fixture.constraints:
            props = self.constraints[constraint.id].hotools_rigid_constraint
            if constraint.reference_constraint_a:
                props.reference_constraint_a = self.constraints[
                    constraint.reference_constraint_a
                ]
            if constraint.reference_constraint_b:
                props.reference_constraint_b = self.constraints[
                    constraint.reference_constraint_b
                ]
        bpy.context.view_layer.update()

    def _animate_kinematic_bodies(self, fixture: Fixture, frame: int) -> None:
        # The cache treats 0 -> 1 as the first advancing solve and rebuilds the
        # backend at frame 1. Keep the source pose at frame 0 for that solve so
        # the fixture's initial kinematic velocity advances exactly one dt.
        source_frame = 0 if frame == 1 else frame
        elapsed = float(source_frame) * fixture.world.dt
        for body in fixture.bodies:
            if body.type != "KINEMATIC":
                continue
            obj = self.objects[body.id]
            obj.location = tuple(
                body.position[index] + body.linear_velocity[index] * elapsed
                for index in range(3)
            )
            angular_velocity = mathutils.Vector(body.angular_velocity)
            angle = angular_velocity.length * elapsed
            delta = (
                mathutils.Quaternion(angular_velocity.normalized(), angle)
                if angle > 0.0
                else mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
            )
            obj.rotation_quaternion = delta @ mathutils.Quaternion(
                body.rotation_wxyz
            )
        bpy.context.view_layer.update()

    def _register_world_settings(self, world, fixture: Fixture) -> None:
        props = self.api["make_rigid_jolt_world_setting_properties"](
            gravity=self._gravity,
            max_bodies=fixture.world.max_bodies,
            max_body_pairs=fixture.world.max_body_pairs,
            max_contact_constraints=fixture.world.max_contact_constraints,
            enabled=True,
            source_id=f"s3:{fixture.id}",
            priority=100,
        )
        self.api["register_rigid_jolt_world_setting_objects"](
            world, props, enabled=True
        )

    def _publish_event(self, world, event) -> None:
        if event.op == "remove_constraint":
            self.constraints[event.constraint].hotools_rigid_constraint.enabled = False
            return
        if event.op == "set_world_gravity":
            self._gravity = tuple(event.values["gravity"])
            return
        obj = self.objects[event.body]
        spec = self.api["build_rigid_body_spec"](obj)
        item = {
            "channel": "rigid_body_commands",
            "producer": "blender_fixture_runtime",
            "scope": "frame",
            "target_slot_id": spec.slot_id,
            "target_simulation_order_key": spec.simulation_order_key,
            "command_order_key": (f"{len(world.exchange.get('rigid_body_commands', ())):012d}",),
            "command": "set_active" if event.op == "activate" else event.op,
        }
        item.update(event.values)
        world.publish_exchange(item)

    @staticmethod
    def _constraint_state_tuple(state: dict) -> tuple:
        return (
            state["constraint_type"], state["enabled"], state["current_value_kind"],
            state["current_value"], state["lambda_position"], state["lambda_rotation"],
            state["lambda_limit"], state["lambda_motor"],
            state["current_translation"], state["current_rotation"],
        )

    def _sample(self, fixture: Fixture, world, frame: int) -> dict[str, Any]:
        body_specs = {
            body_id: self.api["build_rigid_body_spec"](obj)
            for body_id, obj in self.objects.items()
        }
        slot_to_id = {
            spec.slot_id: body_id for body_id, spec in body_specs.items()
        }
        bodies = []
        for body_id in sorted(self.objects):
            spec = body_specs[body_id]
            result = self.api["get_rigid_transform_result"](
                world, slot_id=spec.slot_id, frame=frame, generation=world.generation
            )
            if result is None:
                raise RuntimeError(f"missing Blender rigid result for {body_id} at {frame}")
            bodies.append(canonical_body_state(body_id, (
                result["position"], result["rotation_wxyz"],
                result["linear_velocity"], result["angular_velocity"],
                result["active"], result["sleeping"],
            )))
        constraints = []
        for constraint_id in sorted(self.constraints):
            spec = self.api["build_constraint_spec"](self.constraints[constraint_id])
            if spec is None:
                continue
            result = self.api["get_rigid_constraint_state_result"](
                world, slot_id=spec.slot_id, frame=frame, generation=world.generation
            )
            if result is not None:
                constraints.append(canonical_constraint_state(
                    constraint_id, self._constraint_state_tuple(result)
                ))
        contacts = []
        for event in self.api["iter_rigid_contact_event_results"](
            world, frame=frame, generation=world.generation
        ):
            body_a = slot_to_id.get(str(event.get("body_a_slot_id", "")))
            body_b = slot_to_id.get(str(event.get("body_b_slot_id", "")))
            if body_a is None or body_b is None:
                raise RuntimeError(
                    f"contact references unknown Blender slots: "
                    f"{event.get('body_a_slot_id')}, {event.get('body_b_slot_id')}"
                )
            pseudo_handles = {
                body_id: index + 1
                for index, body_id in enumerate(sorted(self.objects))
            }
            raw = (
                event["state"], pseudo_handles[body_a], pseudo_handles[body_b],
                event["body_a_sensor"], event["body_b_sensor"], event["is_sensor"],
                event["normal"], event["penetration_depth"],
                event["points_on_a"], event["points_on_b"],
                event["sub_shape_a"], event["sub_shape_b"],
            )
            contacts.append(canonical_contact_event(
                raw, {value: key for key, value in pseudo_handles.items()}
            ))
        contacts.sort(key=lambda item: (
            item["body_a"], item["body_b"], item["state"],
            item["sub_shape_a"], item["sub_shape_b"],
        ))

        queries = []
        for query in sorted(fixture.queries, key=lambda item: item.id):
            if query.frame != frame:
                continue
            max_distance = math.sqrt(sum(value * value for value in query.direction))
            result, _hit_object = self.api["perform_rigid_ray_cast"](
                world,
                origin=query.origin,
                direction=query.direction,
                max_distance=max_distance,
                include_sensors=query.include_sensors,
                ignore_object=self.objects.get(query.ignore_body),
            )
            hit_slot = str(result.get("slot_id", "") or "")
            body_id = slot_to_id.get(hit_slot, "")
            pseudo_handles = {
                body_id: index + 1
                for index, body_id in enumerate(sorted(self.objects))
            }
            raw = (
                bool(result.get("hit", False)),
                pseudo_handles.get(body_id, 0),
                result.get("position", (0.0, 0.0, 0.0)),
                result.get("normal", (0.0, 0.0, 0.0)),
                float(result.get("fraction", 0.0)),
                int(result.get("sub_shape_id", 0)),
                bool(result.get("is_sensor", False)),
            )
            queries.append(canonical_ray_result(
                query.id, raw, {value: key for key, value in pseudo_handles.items()}
            ))

        adapter = world.backend_resources.get("rigid_solver")
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
                "body_count": int(getattr(adapter, "body_count", 0) or 0),
                "constraint_count": int(getattr(adapter, "constraint_count", 0) or 0),
                "contact_event_count": len(contacts),
                "contact_event_overflow": int(
                    getattr(adapter, "last_contact_event_overflow", 0) or 0
                ),
                "step_ms": float(self._last_step_ms),
            },
        }

    def _cleanup(self, world=None) -> str:
        dispose_error = ""
        if world is not None:
            resource_keys = tuple(world.backend_resources)
            touched = world.backend_resources.get("_writeback_touched_objects")
            touched_count = len(touched) if touched is not None else -1
            world.omni_cache_dispose("blender_fixture_runtime")
            for obj in self.objects.values():
                if str(getattr(obj.hotools_rigid_body, "body_type", "")) != "DYNAMIC":
                    continue
                if obj.delta_location.length > 1.0e-8:
                    dispose_error = (
                        f"dispose left rigid delta on {obj.name}; "
                        f"resources={resource_keys}; touched={touched_count}"
                    )
                    break
        for obj in reversed(self._owned_objects):
            try:
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data is not None and data.users == 0:
                    bpy.data.meshes.remove(data)
            except Exception:
                pass
        self._owned_objects = []
        self.objects = {}
        self.constraints = {}
        return dispose_error

    def _lifecycle_probe(self, fixture: Fixture, scope, cache_state, world):
        scene = bpy.context.scene
        previous_world = world
        if fixture.world.frames == 0:
            scene.frame_set(1)
            previous_world, _, _, _ = self.api["physicsWorldBegin"](
                cache_state=cache_state,
                scene=scene,
                object_scope=scope,
                enabled=True,
                substeps=fixture.world.substeps,
            )
            self._register_world_settings(previous_world, fixture)
            previous_world.frame_context.same_frame = True
            self.api["step_rigid_bodies"](previous_world, enabled=True)
            cache_state, _, _ = self.api["physicsWorldCommit"](
                previous_world, enabled=True
            )
        scene.frame_set(fixture.world.frames + 2)
        if fixture.world.frames == 0:
            scene.frame_set(3)
        jump_world, _, _, jump_restart = self.api["physicsWorldBegin"](
            cache_state=cache_state,
            scene=scene,
            object_scope=scope,
            enabled=True,
            substeps=fixture.world.substeps,
        )
        if not jump_restart or jump_world is previous_world:
            raise RuntimeError("frame jump did not restart the Blender physics world")
        self._register_world_settings(jump_world, fixture)
        jump_world.frame_context.same_frame = True
        self.api["step_rigid_bodies"](jump_world, enabled=True)
        self._verify_restart_initial_state(fixture, jump_world)
        self.api["apply_all_writebacks"](jump_world, restart=True)
        self._verify_writeback(jump_world, scene.frame_current)
        jump_cache, _, _ = self.api["physicsWorldCommit"](jump_world, enabled=True)

        reset_generation = jump_world.generation
        reset_world, _, _, reset_restart = self.api["physicsWorldBegin"](
            cache_state=jump_cache,
            scene=scene,
            object_scope=scope,
            enabled=True,
            reset=True,
            substeps=fixture.world.substeps,
        )
        if not reset_restart or reset_world.generation <= reset_generation:
            raise RuntimeError("explicit reset did not restart the Blender physics world")
        self._register_world_settings(reset_world, fixture)
        reset_world.frame_context.same_frame = True
        self.api["step_rigid_bodies"](reset_world, enabled=True)
        self._verify_restart_initial_state(fixture, reset_world)
        self.api["apply_all_writebacks"](reset_world, restart=True)
        self._verify_writeback(reset_world, scene.frame_current)
        reset_cache, _, _ = self.api["physicsWorldCommit"](
            reset_world, enabled=True
        )
        return reset_cache, reset_world

    def _verify_restart_initial_state(self, fixture: Fixture, world) -> None:
        bodies_by_id = fixture.bodies_by_id
        frame = int(world.frame_context.frame)
        for body_id, obj in self.objects.items():
            if fixture.bodies_by_id[body_id].type == "KINEMATIC":
                continue
            spec = self.api["build_rigid_body_spec"](obj)
            result = self.api["get_rigid_transform_result"](
                world, slot_id=spec.slot_id, frame=frame, generation=world.generation
            )
            if result is None:
                raise RuntimeError(f"restart missing result for {body_id}")
            expected = bodies_by_id[body_id]
            position_error = (
                mathutils.Vector(result["position"]) - mathutils.Vector(expected.position)
            ).length
            actual_rotation = mathutils.Quaternion(result["rotation_wxyz"])
            expected_rotation = mathutils.Quaternion(expected.rotation_wxyz)
            rotation_dot = min(max(abs(actual_rotation.dot(expected_rotation)), 0.0), 1.0)
            rotation_error = 2.0 * math.acos(rotation_dot)
            if position_error > 2.0e-5 or rotation_error > 2.0e-3:
                raise RuntimeError(
                    f"restart did not restore {body_id}: position={position_error}, "
                    f"rotation={rotation_error}"
                )

    def _verify_writeback(self, world, frame: int) -> None:
        bpy.context.view_layer.update()
        for body_id, obj in self.objects.items():
            if str(obj.hotools_rigid_body.body_type) != "DYNAMIC":
                continue
            spec = self.api["build_rigid_body_spec"](obj)
            result = self.api["get_rigid_transform_result"](
                world, slot_id=spec.slot_id, frame=frame, generation=world.generation
            )
            if result is None:
                raise RuntimeError(f"writeback verification missing result for {body_id}")
            position_error = (
                obj.matrix_world.translation - mathutils.Vector(result["position"])
            ).length
            _location, actual_rotation, _scale = obj.matrix_world.decompose()
            expected_rotation = mathutils.Quaternion(result["rotation_wxyz"])
            rotation_dot = min(max(abs(actual_rotation.dot(expected_rotation)), 0.0), 1.0)
            rotation_error = 2.0 * math.acos(rotation_dot)
            if position_error > 2.0e-5 or rotation_error > 2.0e-3:
                raise RuntimeError(
                    f"writeback mismatch for {body_id}: position={position_error}, "
                    f"rotation={rotation_error}"
                )

    def run(self, fixture: Fixture, repeat_index: int = 0) -> NativeRunResult:
        if fixture.id not in self.SUPPORTED_FIXTURES:
            raise RuntimeError(f"{fixture.id}: fixture is outside the S3 manifest")
        self._build_scene(fixture)
        self._gravity = tuple(fixture.world.gravity)
        scene = bpy.context.scene
        scene.render.fps = round(1.0 / fixture.world.dt)
        scene.render.fps_base = 1.0
        scope = self.api["make_scope"](
            list(self.objects.values()) + list(self.constraints.values()),
            include_rigid_body=True,
            include_rigid_constraint=bool(self.constraints),
            include_passive_collision=False,
            include_bone_collision=False,
            include_mesh_collision=False,
        )
        events: dict[tuple[int, str], list] = {}
        for event in fixture.timeline:
            events.setdefault((event.frame, event.phase), []).append(event)
        trace = []
        cache_state = None
        world = None
        try:
            for frame in range(0, fixture.world.frames + 1):
                scene.frame_set(frame)
                self._animate_kinematic_bodies(fixture, frame)
                for event in events.get((frame, "pre_step"), ()):
                    if event.op == "remove_constraint":
                        self._publish_event(None, event)
                world, _, _, restart = self.api["physicsWorldBegin"](
                    cache_state=cache_state,
                    scene=scene,
                    object_scope=scope,
                    enabled=True,
                    substeps=fixture.world.substeps,
                )
                registry_errors = world.runtime_cache("solver_registry_errors") or []
                if registry_errors:
                    raise RuntimeError(f"scope collection failed: {registry_errors}")
                if frame == 0:
                    world.frame_context.same_frame = True
                for event in events.get((frame, "pre_step"), ()):
                    if event.op != "remove_constraint":
                        self._publish_event(world, event)
                self._register_world_settings(world, fixture)
                _body_count, self._last_step_ms = self.api["step_rigid_bodies"](
                    world, enabled=True
                )
                if frame == 0:
                    before = self._sample(fixture, world, frame)
                    body_count, repeated_step_ms = self.api["step_rigid_bodies"](
                        world, enabled=True
                    )
                    after = self._sample(fixture, world, frame)
                    same_frame_comparison = compare_traces([before], [after])
                    if (
                        body_count != len(fixture.bodies)
                        or repeated_step_ms != 0.0
                        or not same_frame_comparison.passed
                    ):
                        raise RuntimeError(
                            f"same-frame replay advanced or changed state: "
                            f"{same_frame_comparison.differences}"
                        )
                for event in events.get((frame, "post_step"), ()):
                    self._publish_event(world, event)
                    world.frame_context.same_frame = True
                    self.api["step_rigid_bodies"](world, enabled=True)
                if frame in set(fixture.sample_frames):
                    trace.append(self._sample(fixture, world, frame))
                self.api["apply_all_writebacks"](world, restart=restart)
                self._verify_writeback(world, frame)
                touched = world.backend_resources.get("_writeback_touched_objects")
                if frame > 0 and self.objects and (touched is None or len(touched) == 0):
                    errors = [
                        slot.data.get("_writeback_error")
                        for slot in world.solver_slots.values()
                        if slot.data.get("_writeback_error")
                    ]
                    raise RuntimeError(
                        f"writeback did not retain touched objects at frame {frame}: {errors}"
                    )
                cache_state, _, _ = self.api["physicsWorldCommit"](
                    world, enabled=True
                )
            assertion_results = evaluate_assertions(fixture, trace)
            native_result = NativeFixtureRuntime(self.native).run(fixture, repeat_index)
            comparison = compare_traces(native_result.trace, trace)
            assertion_results.append({
                "kind": "runner_parity",
                "passed": comparison.passed,
                "message": (
                    f"S1/S3 max_abs={comparison.max_abs_error:.9g}; "
                    f"differences={comparison.differences}"
                ),
            })
            cache_state, world = self._lifecycle_probe(
                fixture, scope, cache_state, world
            )
            result = NativeRunResult(
                fixture=fixture,
                repeat_index=repeat_index,
                trace=trace,
                assertions=assertion_results,
                physical_hash=physical_trace_hash(trace),
                native_module_path=str(Path(self.native.__file__).resolve()),
            )
            cleanup_error = self._cleanup(world)
            world = None
            if cleanup_error:
                raise RuntimeError(cleanup_error)
            return result
        finally:
            if self._owned_objects:
                self._cleanup(world)
