"""Long-run BoneCloth/BoneSpring angle, Motion, and collision acceptance."""

from __future__ import annotations

import hashlib
import math
import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_mixed_output_soak as mixed


parameters = mixed.parameters
names = mixed.names
nodes = mixed.nodes
topology_module = mixed.topology_module
bone_frame_input = mixed.bone_frame_input
world_types = mixed.world_types
writeback = mixed.writeback


def _profile(*, restoration: bool, limit: bool):
    return parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.05,
        stabilization_time_after_reset=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=restoration,
        angle_restoration_stiffness=0.85,
        angle_restoration_velocity_attenuation=0.25,
        angle_restoration_gravity_falloff=0.5,
        angle_limit_enabled=limit,
        angle_limit=35.0,
        angle_limit_stiffness=0.9,
        max_distance_enabled=False,
        backstop_enabled=False,
        self_collision_mode=0,
        teleport_mode=0,
    )


def _task(setup_type, armature, *, restoration: bool, limit: bool):
    profile = _profile(restoration=restoration, limit=limit)
    source = {"armature": armature, "bone": "Root"}
    if setup_type == names.MC2_SETUP_BONE_CLOTH:
        tasks, _task_names = nodes.physicsMC2BoneClothTask(
            [source],
            profile=profile,
            connection_mode=0,
        )
    elif setup_type == names.MC2_SETUP_BONE_SPRING:
        tasks, _task_names = nodes.physicsMC2BoneSpringTask(
            [source],
            profile=profile,
        )
    else:
        raise ValueError(setup_type)
    assert len(tasks) == 1
    return tasks[0]


def _run_setup(setup_type):
    world = world_types.PhysicsWorldCache()
    world.generation = 73
    armature = mixed._armature(
        f"MC2Angle_{setup_type}",
        0.0,
        0.75 if setup_type == names.MC2_SETUP_BONE_CLOTH else 1.25,
    )
    task = _task(setup_type, armature, restoration=True, limit=False)
    stable_task_id = task.task_id
    topology = topology_module.build_mc2_topology_spec(task)
    initial_input = bone_frame_input.build_mc2_bone_frame_input(
        task,
        topology,
        frame=1,
        generation=world.generation,
    )
    context = None
    enabled_count = None
    disabled_count = None
    max_rest_error = 0.0
    trajectory_digest = hashlib.sha256()
    rest_budget = (
        5.0e-5
        if setup_type == names.MC2_SETUP_BONE_CLOTH
        else 1.6e-3
    )
    try:
        for frame in range(1, 901):
            if frame == 301:
                context = world.solver_slots[task.task_id].data["native_context"]
                revision = context.inspect()["parameter_revision"]
                task = _task(setup_type, armature, restoration=False, limit=False)
                assert task.task_id == stable_task_id
            elif frame == 601:
                assert context is world.solver_slots[task.task_id].data["native_context"]
                task = _task(setup_type, armature, restoration=True, limit=True)
                assert task.task_id == stable_task_id

            mixed._set_frame(world, frame, world.generation)
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [task],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            slot = world.solver_slots[task.task_id]
            candidate = slot.data["result_candidate"]
            assert candidate.frame == frame
            assert np.all(np.isfinite(candidate.world_positions))
            assert np.all(np.isfinite(candidate.world_rotations_xyzw))
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
            if setup_type == names.MC2_SETUP_BONE_CLOTH:
                plan = slot.data["writeback_plan"]
                assert plan["rotation_only_connected_count"] > 0
                assert plan["position_rotation_count"] > 0
            rest_error = float(np.max(np.linalg.norm(
                candidate.world_positions - initial_input.world_positions,
                axis=1,
            )))
            max_rest_error = max(max_rest_error, rest_error)
            if rest_error > rest_budget:
                step_basic, _step_rotations = slot.data["native_context"].read_step_basic()
                step_error = float(np.max(np.linalg.norm(
                    step_basic - initial_input.world_positions,
                    axis=1,
                )))
                raise AssertionError((setup_type, frame, rest_error, "step_basic", step_error))
            assert writeback.writeback_bone_transforms(world) == topology.particle_count
            bpy.context.view_layer.update()

            info = slot.data["native_context"].inspect()
            if frame == 300:
                enabled_count = info["angle_solve_count"]
                assert enabled_count > 0
            elif frame == 301:
                assert slot.data["native_context"] is context
                assert info["parameter_revision"] == revision + 1
                disabled_count = info["angle_solve_count"]
            elif 301 < frame <= 600:
                assert info["angle_solve_count"] == disabled_count
            elif frame == 601:
                assert slot.data["native_context"] is context
                assert info["parameter_revision"] == revision + 2
            elif frame == 900:
                assert info["angle_solve_count"] > disabled_count

        print(
            f"[INFO] {setup_type} max zero-force drift: "
            f"{max_rest_error:.9f}m / budget {rest_budget:.9f}m"
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_constraint_soak")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)


def bone_angle_constraints():
    for setup_type in (
        names.MC2_SETUP_BONE_CLOTH,
        names.MC2_SETUP_BONE_SPRING,
    ):
        first = _run_setup(setup_type)
        second = _run_setup(setup_type)
        assert first == second, (setup_type, first, second)
    print("[PASS] Bone angle constraints: 2 setups x 2 deterministic x 900 frames")


def _run_bone_motion():
    world = world_types.PhysicsWorldCache()
    world.generation = 74
    armature = mixed._armature("MC2Motion_bone_cloth", 0.0, 0.8)

    def make_task(backstop):
        profile = parameters.make_mc2_particle_profile(
            gravity=6.0,
            gravity_direction=(0.0, 0.0, -1.0),
            damping=0.05,
            stabilization_time_after_reset=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            max_distance_enabled=True,
            max_distance=0.03,
            backstop_enabled=backstop,
            backstop_radius=0.01,
            backstop_distance=0.005,
            normal_axis=2,
            motion_stiffness=1.0,
            self_collision_mode=0,
        )
        tasks, _task_names = nodes.physicsMC2BoneClothTask(
            [{"armature": armature, "bone": "Root"}],
            profile=profile,
            connection_mode=0,
        )
        assert len(tasks) == 1
        return tasks[0]

    task = make_task(False)
    stable_task_id = task.task_id
    topology = topology_module.build_mc2_topology_spec(task)
    animation_input = bone_frame_input.build_mc2_bone_frame_input(
        task, topology, frame=1, generation=world.generation
    )
    context = None
    trajectory_digest = hashlib.sha256()
    try:
        for frame in range(1, 901):
            if frame == 451:
                context = world.solver_slots[task.task_id].data["native_context"]
                revision = context.inspect()["parameter_revision"]
                task = make_task(True)
                assert task.task_id == stable_task_id
            mixed._set_frame(world, frame, world.generation)
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [task],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            slot = world.solver_slots[task.task_id]
            candidate = slot.data["result_candidate"]
            assert candidate.frame == frame
            assert np.all(np.isfinite(candidate.world_positions))
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
            distance = np.linalg.norm(
                candidate.world_positions - animation_input.world_positions,
                axis=1,
            )
            assert float(np.max(distance)) <= 0.031, (frame, float(np.max(distance)))
            plan = slot.data["writeback_plan"]
            assert plan["rotation_only_connected_count"] > 0
            assert plan["position_rotation_count"] > 0
            assert writeback.writeback_bone_transforms(world) == topology.particle_count
            bpy.context.view_layer.update()
            if frame == 899:
                mixed.debug_module.request_mc2_debug_capture(
                    world,
                    filters={
                        "show_motion": True,
                        "show_motion_base": True,
                        "show_angle_restoration": False,
                        "show_self": False,
                    },
                )
            if frame == 451:
                assert slot.data["native_context"] is context
                assert slot.data["native_context"].inspect()["parameter_revision"] == revision + 1

        slot = world.solver_slots[task.task_id]
        snapshot = slot.data["_debug_draw_snapshot"]
        assert snapshot["frame"] == 900
        assert snapshot["motion"]["use_backstop"] is True
        np.testing.assert_allclose(
            snapshot["motion"]["motion_base_positions"],
            animation_input.world_positions,
            atol=1.0e-6,
        )
        trajectory_digest.update(np.asarray(
            snapshot["motion"]["motion_base_positions"]
        ).tobytes())
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_motion_soak")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)


def bone_motion_constraints():
    first = _run_bone_motion()
    second = _run_bone_motion()
    assert first == second, (first, second)
    print("[PASS] BoneCloth Motion: connected/disconnected x 2 x 900 frames")


def _run_bone_external_collision(setup_type):
    world = world_types.PhysicsWorldCache()
    world.generation = 75
    is_spring = setup_type == names.MC2_SETUP_BONE_SPRING
    armature = mixed._armature(
        f"MC2Collision_{setup_type}",
        0.0,
        1.15 if is_spring else 0.9,
    )

    def make_task(*, radius, collision_limit):
        profile = parameters.make_mc2_particle_profile(
            gravity=0.0,
            damping=0.05,
            stabilization_time_after_reset=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            radius=radius,
            collision_mode=2,
            collision_limit_distance=collision_limit,
            max_distance_enabled=False,
            backstop_enabled=False,
            self_collision_mode=0,
            teleport_mode=0,
        )
        source = {"armature": armature, "bone": "Root"}
        if is_spring:
            tasks, _task_names = nodes.physicsMC2BoneSpringTask(
                [source],
                profile=profile,
                collided_by_groups=1,
            )
        else:
            tasks, _task_names = nodes.physicsMC2BoneClothTask(
                [source],
                profile=profile,
                connection_mode=0,
                collided_by_groups=1,
            )
        assert len(tasks) == 1
        return tasks[0]

    task = make_task(radius=0.012, collision_limit=0.03)
    stable_task_id = task.task_id
    topology = topology_module.build_mc2_topology_spec(task)
    animation_input = bone_frame_input.build_mc2_bone_frame_input(
        task,
        topology,
        frame=1,
        generation=world.generation,
    )
    target_index = min(2, topology.particle_count - 1)
    target = np.asarray(animation_input.world_positions[target_index], dtype=np.float64)
    rest_chain_length = float(np.sum(np.linalg.norm(
        np.diff(animation_input.world_positions, axis=0),
        axis=1,
    )))
    orbit_budget = rest_chain_length * 2.0 + 0.05
    span_budget = rest_chain_length * 1.25 + 0.01
    context = None
    max_response = 0.0
    max_soft_limit_distance = 0.0
    trajectory_digest = hashlib.sha256()
    try:
        for frame in range(1, 901):
            active_limit = 0.03 if frame < 451 else 0.05
            if frame == 451:
                context = world.solver_slots[task.task_id].data["native_context"]
                revision = context.inspect()["parameter_revision"]
                task = make_task(radius=0.016, collision_limit=active_limit)
                assert task.task_id == stable_task_id

            collider_center = target + np.asarray((
                0.033 + 0.002 * math.sin(frame * 0.071),
                0.0,
                0.0,
            ))
            colliders = [
                {
                    "key": f"bone-collision-{setup_type}",
                    "type": "SPHERE",
                    "primary_group": 1,
                    "center": tuple(float(value) for value in collider_center),
                    "radius": 0.025,
                },
                {
                    "key": f"bone-self-owned-{setup_type}",
                    "owner": armature,
                    "type": "SPHERE",
                    "primary_group": 1,
                    "center": tuple(float(value) for value in target),
                    "radius": 0.1,
                },
                {
                    "key": f"bone-masked-{setup_type}",
                    "type": "SPHERE",
                    "primary_group": 2,
                    "center": tuple(float(value) for value in target),
                    "radius": 0.1,
                },
            ]
            if is_spring:
                colliders.append({
                    "key": "bone-spring-disallowed-capsule",
                    "type": "CAPSULE",
                    "primary_group": 1,
                    "center": tuple(float(value) for value in target),
                    "segment_a": tuple(float(value) for value in target - (0.0, 0.1, 0.0)),
                    "segment_b": tuple(float(value) for value in target + (0.0, 0.1, 0.0)),
                    "radius": 0.05,
                })
            world.collider_snapshot = {
                "frame": frame,
                "colliders": tuple(colliders),
            }
            mixed._set_frame(world, frame, world.generation)
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [task],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            slot = world.solver_slots[task.task_id]
            candidate = slot.data["result_candidate"]
            assert candidate.frame == frame
            assert np.all(np.isfinite(candidate.world_positions))
            assert np.all(np.isfinite(candidate.world_rotations_xyzw))
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
            response = np.linalg.norm(
                candidate.world_positions - animation_input.world_positions,
                axis=1,
            )
            frame_response = float(np.max(response))
            max_response = max(max_response, frame_response)
            assert frame_response <= orbit_budget, (
                setup_type,
                frame,
                frame_response,
                orbit_budget,
            )
            positions = candidate.world_positions
            pairwise_span = float(np.max(np.linalg.norm(
                positions[:, None, :] - positions[None, :, :],
                axis=2,
            )))
            assert pairwise_span <= span_budget, (
                setup_type,
                frame,
                pairwise_span,
                span_budget,
            )
            if is_spring:
                max_soft_limit_distance = max(max_soft_limit_distance, frame_response)
                assert frame_response <= active_limit + 1.0e-3, (
                    setup_type,
                    frame,
                    frame_response,
                    active_limit,
                )
            else:
                plan = slot.data["writeback_plan"]
                assert plan["rotation_only_connected_count"] > 0
                assert plan["position_rotation_count"] > 0
            assert writeback.writeback_bone_transforms(world) == topology.particle_count
            bpy.context.view_layer.update()

            info = slot.data["native_context"].inspect()
            assert info["collider_count"] == 1
            if frame == 451:
                assert slot.data["native_context"] is context
                assert info["parameter_revision"] == revision + 1
            if frame == 899:
                mixed.debug_module.request_mc2_debug_capture(
                    world,
                    filters={"show_collision": True, "show_self": False},
                )

        slot = world.solver_slots[task.task_id]
        info = slot.data["native_context"].inspect()
        if is_spring:
            assert info["point_collision_solve_count"] > 0
            assert info["edge_collision_solve_count"] == 0
        else:
            assert info["edge_collision_solve_count"] > 0
        assert max_response > 1.0e-4, (setup_type, max_response)
        snapshot = slot.data["_debug_draw_snapshot"]
        assert snapshot["frame"] == 900
        assert snapshot["collision"]["colliders"]["keys"] == (
            f"bone-collision-{setup_type}",
        )
        trajectory_digest.update("\0".join(
            snapshot["collision"]["colliders"]["keys"]
        ).encode("utf-8"))
        print(
            f"[INFO] {setup_type} external collision max response: "
            f"{max_response:.9f}m"
            + (
                f" / soft limit max {max_soft_limit_distance:.9f}m"
                if is_spring else ""
            )
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_external_collision_soak")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)


def bone_external_collision():
    for setup_type in (
        names.MC2_SETUP_BONE_CLOTH,
        names.MC2_SETUP_BONE_SPRING,
    ):
        first = _run_bone_external_collision(setup_type)
        second = _run_bone_external_collision(setup_type)
        assert first == second, (setup_type, first, second)
    print("[PASS] Bone external collision: 2 setups x 2 x 900 frames")


def _run_bone_cloth_friction(friction):
    world = world_types.PhysicsWorldCache()
    world.generation = 76
    armature = mixed._armature(f"MC2BoneFriction{friction}", 0.0, 0.9)
    initial_basis = {
        bone.name: bone.matrix_basis.copy()
        for bone in armature.pose.bones
    }
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.02,
        stabilization_time_after_reset=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        collision_mode=1,
        collision_friction=friction,
        radius=0.02,
        self_collision_mode=0,
    )
    tasks, _task_names = nodes.physicsMC2BoneClothTask(
        [{"armature": armature, "bone": "Root"}],
        profile=profile,
        connection_mode=0,
        collided_by_groups=1,
    )
    assert len(tasks) == 1
    task = tasks[0]
    topology = topology_module.build_mc2_topology_spec(task)
    bone_names = topology.sources[0].bone_names
    lags = []
    try:
        for bone in armature.pose.bones:
            bone.matrix_basis = initial_basis[bone.name].copy()
        bpy.context.view_layer.update()
        initial = bone_frame_input.build_mc2_bone_frame_input(
            task,
            topology,
            frame=1,
            generation=world.generation,
        ).world_positions
        plane_z = float(initial[1, 2] - 0.015)
        orbit_budget = float(np.sum(np.linalg.norm(
            np.diff(initial, axis=0),
            axis=1,
        ))) * 2.0 + 0.05

        for frame in range(1, 601):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            armature.pose.bones["Root"].location.x = frame * 0.0002
            bpy.context.view_layer.update()
            expected = np.asarray([
                tuple(armature.matrix_world @ armature.pose.bones[name].matrix.translation)
                for name in bone_names
            ], dtype=np.float32)
            world.collider_snapshot = {
                "frame": frame,
                "colliders": ({
                    "key": "bone-friction-plane",
                    "type": "PLANE",
                    "primary_group": 1,
                    "center": (0.0, 0.0, plane_z),
                    "normal": (0.0, 0.0, 1.0),
                },),
            }
            mixed._set_frame(world, frame, world.generation)
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [task],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            slot = world.solver_slots[task.task_id]
            candidate = slot.data["result_candidate"]
            assert np.all(np.isfinite(candidate.world_positions))
            assert np.all(np.isfinite(candidate.world_rotations_xyzw))
            response = float(np.max(np.linalg.norm(
                candidate.world_positions - expected,
                axis=1,
            )))
            assert response <= orbit_budget, (friction, frame, response, orbit_budget)
            plan = slot.data["writeback_plan"]
            assert plan["rotation_only_connected_count"] > 0
            assert plan["position_rotation_count"] > 0
            lag = float(np.mean(
                expected[1:, 0] - candidate.world_positions[1:, 0]
            ))
            if frame > 300:
                lags.append(lag)
            assert writeback.writeback_bone_transforms(world) == topology.particle_count
            bpy.context.view_layer.update()

        info = world.solver_slots[task.task_id].data["native_context"].inspect()
        assert info["point_collision_solve_count"] > 0
        assert info["collider_count"] == 1
        return float(np.mean(lags)), float(lags[-1])
    finally:
        world.omni_cache_dispose("bone_cloth_friction_soak")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)


def bone_friction_response():
    low_mean, low_final = _run_bone_cloth_friction(0.0)
    high_mean, high_final = _run_bone_cloth_friction(0.5)
    assert high_mean > low_mean + 0.02, (low_mean, high_mean)
    assert high_final > low_final + 0.02, (low_final, high_final)
    print(
        "[PASS] BoneCloth friction ordered tangential lag: "
        f"mean {low_mean:.6f}m -> {high_mean:.6f}m"
    )


def main():
    mixed.physics_blender.register()
    try:
        bone_angle_constraints()
        bone_motion_constraints()
        bone_external_collision()
        bone_friction_response()
    finally:
        if mixed.physics_blender.is_registered():
            mixed.physics_blender.unregister()
    print("MC2 Bone constraint soak: PASS")


if __name__ == "__main__":
    main()
