"""Long-run BoneCloth/BoneSpring angle, Motion, and collision acceptance."""

from __future__ import annotations

import hashlib
import math
import os
import sys

import bpy
import mathutils
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


def _profile(
    *, restoration: bool, limit: bool,
    attenuation: float = 0.25, falloff: float = 0.5,
    gravity: float = 0.0,
):
    return parameters.make_mc2_particle_profile(
        gravity=gravity,
        damping=0.05,
        stabilization_time_after_reset=0.0,
        distance_stiffness=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=restoration,
        angle_restoration_stiffness=0.85,
        angle_restoration_velocity_attenuation=attenuation,
        angle_restoration_gravity_falloff=falloff,
        angle_limit_enabled=limit,
        angle_limit=35.0,
        angle_limit_stiffness=0.9,
        max_distance_enabled=False,
        backstop_enabled=False,
        self_collision_mode=0,
        spring_enabled=False,
    )


def _task(
    setup_type, armature, *, restoration: bool, limit: bool,
    attenuation: float = 0.25, falloff: float = 0.5,
    gravity: float = 0.0,
):
    profile = _profile(
        restoration=restoration,
        limit=limit,
        attenuation=attenuation,
        falloff=falloff,
        gravity=gravity,
    )
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
        1.0e-7
        if setup_type == names.MC2_SETUP_BONE_CLOTH
        else 1.0e-6
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
            if frame in (1, 900):
                native_snapshot = slot.data["native_context"].refresh_debug_draw_snapshot(
                    include_step_basic=True,
                    include_angle_restoration=True,
                )
                step_basic = native_snapshot["step_basic_positions"]
                targets = native_snapshot["angle_restoration_target_positions"]
                vectors = native_snapshot["angle_restoration_target_vectors"]
                valid = native_snapshot["angle_restoration_target_valid"].astype(bool)
                valid_indices = np.flatnonzero(valid)
                assert len(valid_indices) > 0
                parent_points = (
                    targets[valid_indices] - vectors[valid_indices]
                )
                parent_distances = np.linalg.norm(
                    parent_points[:, None, :] - candidate.world_positions[None, :, :],
                    axis=2,
                )
                parent_indices = np.argmin(parent_distances, axis=1)
                matched_distances = parent_distances[
                    np.arange(len(valid_indices)), parent_indices
                ]
                assert float(np.max(matched_distances)) <= 1.0e-7
                assert np.all(parent_indices != valid_indices)
                expected_vectors = (
                    step_basic[valid_indices] - step_basic[parent_indices]
                )
                expected_targets = (
                    candidate.world_positions[parent_indices] + expected_vectors
                )
                np.testing.assert_allclose(
                    vectors[valid_indices], expected_vectors, rtol=0.0, atol=1.0e-7
                )
                np.testing.assert_allclose(
                    targets[valid_indices], expected_targets, rtol=0.0, atol=1.0e-7
                )
                trajectory_digest.update(vectors[valid_indices].tobytes())
                trajectory_digest.update(targets[valid_indices].tobytes())
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


def _run_bone_angle_attenuation(setup_type, attenuation):
    world = world_types.PhysicsWorldCache()
    world.generation = 78
    armature = mixed._armature(
        f"MC2AngleAttenuation_{setup_type}_{attenuation:.1f}",
        0.0,
        0.9,
    )
    task = _task(
        setup_type,
        armature,
        restoration=True,
        limit=False,
        attenuation=attenuation,
        falloff=0.0,
        gravity=4.0,
    )
    topology = topology_module.build_mc2_topology_spec(task)
    initial_input = bone_frame_input.build_mc2_bone_frame_input(
        task,
        topology,
        frame=1,
        generation=world.generation,
    )
    responses = []
    movements = []
    animation_input_response = 0.0
    previous = None
    initial_basis = {
        bone.name: bone.matrix_basis.copy()
        for bone in armature.pose.bones
    }
    try:
        for frame in range(1, 602):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            root = armature.pose.bones["Root"]
            root.rotation_mode = "XYZ"
            root.rotation_euler.z = 0.65 * math.sin(frame * 0.11)
            root.location.x = 0.03 * math.sin(frame * 0.07)
            bpy.context.view_layer.update()
            if frame == 2:
                animated_input = bone_frame_input.build_mc2_bone_frame_input(
                    task,
                    topology,
                    frame=frame,
                    generation=world.generation,
                )
                animation_input_response = float(np.max(np.linalg.norm(
                    animated_input.world_positions - initial_input.world_positions,
                    axis=1,
                )))
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
            if setup_type == names.MC2_SETUP_BONE_CLOTH:
                plan = slot.data["writeback_plan"]
                assert plan["rotation_only_connected_count"] > 0
                assert plan["position_rotation_count"] > 0
            if frame >= 2:
                positions = candidate.world_positions.copy()
                responses.append(float(np.mean(np.linalg.norm(
                    positions - initial_input.world_positions,
                    axis=1,
                ))))
                movements.append(
                    0.0 if previous is None
                    else float(np.mean(np.linalg.norm(positions - previous, axis=1)))
                )
                previous = positions
            assert writeback.writeback_bone_transforms(world) == topology.particle_count
            bpy.context.view_layer.update()
        return {
            "responses": np.asarray(responses),
            "movements": np.asarray(movements),
            "animation_input_response": animation_input_response,
        }
    finally:
        world.omni_cache_dispose("bone_angle_attenuation")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)


def bone_angle_restoration_attenuation():
    for setup_type in (
        names.MC2_SETUP_BONE_CLOTH,
        names.MC2_SETUP_BONE_SPRING,
    ):
        low = _run_bone_angle_attenuation(setup_type, 0.0)
        high = _run_bone_angle_attenuation(setup_type, 1.0)
        np.testing.assert_allclose(
            low["responses"][0], high["responses"][0], rtol=0.0, atol=1.0e-7
        )
        assert low["animation_input_response"] >= 0.05
        assert low["responses"][1] >= high["responses"][1] + 0.001
        low_movement = float(np.sum(low["movements"][1:30]))
        high_movement = float(np.sum(high["movements"][1:30]))
        assert low_movement >= high_movement * 1.5
        print(
            f"[INFO] {setup_type} Angle Restoration attenuation: "
            f"frame3 low/high={low['responses'][1]:.9f}/"
            f"{high['responses'][1]:.9f}; movement30 low/high="
            f"{low_movement:.9f}/{high_movement:.9f}; "
            f"animation input={low['animation_input_response']:.9f}"
        )


def _run_bone_gravity_axes_falloff():
    world = world_types.PhysicsWorldCache()
    world.generation = 94
    directions = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    armatures = tuple(
        mixed._armature(f"MC2BoneGravityAxis{index}", index * 0.8, 0.9)
        for index in range(3)
    ) + (
        mixed._armature("MC2BoneGravityFalloff0", 2.8, 0.9),
        mixed._armature("MC2BoneGravityFalloff1", 3.6, 0.9),
    )
    anchors = tuple(
        bpy.data.objects.new(f"MC2BoneGravityAnchor{index}", None)
        for index in range(2)
    )
    for anchor in anchors:
        bpy.context.scene.collection.objects.link(anchor)

    def make_profile(direction, falloff):
        return parameters.make_mc2_particle_profile(
            gravity=0.6,
            gravity_direction=direction,
            gravity_falloff=falloff,
            damping=0.5,
            stabilization_time_after_reset=0.0,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            collision_mode=0,
            self_collision_mode=0,
        )

    profiles = tuple(make_profile(direction, 0.0) for direction in directions) + (
        make_profile((0.0, 0.0, -1.0), 0.0),
        make_profile((0.0, 0.0, -1.0), 1.0),
    )
    tasks = []
    for index, (armature, profile) in enumerate(zip(armatures, profiles)):
        product_tasks, _names = nodes.physicsMC2BoneClothTask(
            [{"armature": armature, "bone": "Root"}],
            profile=profile,
            anchor_object=(anchors[index - 3] if index >= 3 else None),
            world_inertia=0.0,
            anchor_inertia=0.0,
            connection_mode=0,
        )
        assert len(product_tasks) == 1
        tasks.append(product_tasks[0])
    tasks = tuple(tasks)
    topologies = tuple(
        topology_module.build_mc2_topology_spec(task) for task in tasks
    )
    initial_basis = tuple({
        bone.name: bone.matrix_basis.copy()
        for bone in armature.pose.bones
    } for armature in armatures)
    initial_positions = [None] * len(tasks)
    axis_velocity_directions = {}
    gravity_ratios = {task.task_id: [] for task in tasks[3:]}
    trajectory_digest = hashlib.sha256()
    try:
        for frame in range(1, 601):
            for armature, basis in zip(armatures, initial_basis):
                for bone in armature.pose.bones:
                    bone.matrix_basis = basis[bone.name].copy()
            angle = 0.0 if frame == 1 else math.radians(90.0)
            for armature, anchor in zip(armatures[3:], anchors):
                armature.rotation_mode = "XYZ"
                anchor.rotation_mode = "XYZ"
                armature.rotation_euler.x = angle
                anchor.rotation_euler.x = angle
            bpy.context.view_layer.update()
            mixed._set_frame(world, frame, world.generation)
            returned, ready, status = nodes.physicsMC2Step(
                world,
                list(tasks),
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            for index, (task, topology) in enumerate(zip(tasks, topologies)):
                slot = world.solver_slots[task.task_id]
                candidate = slot.data["result_candidate"]
                assert candidate.frame == frame
                assert np.all(np.isfinite(candidate.world_positions))
                assert np.all(np.isfinite(candidate.world_rotations_xyzw))
                plan = slot.data["writeback_plan"]
                assert plan["rotation_only_connected_count"] > 0
                assert plan["position_rotation_count"] > 0
                if frame == 1:
                    initial_positions[index] = np.array(
                        candidate.world_positions, dtype=np.float32, copy=True
                    )
                if frame == 2 and index < 3:
                    dynamics = slot.data[
                        "native_context"
                    ].refresh_debug_draw_snapshot(
                        include_dynamics=True,
                    )["dynamics"]
                    attributes = np.asarray(
                        slot.data["bone_static"].final_proxy.vertex_attributes,
                        dtype=np.uint8,
                    )
                    move = (attributes & np.uint8(0x02)) != 0
                    mean_velocity = np.mean(dynamics["velocities"][move], axis=0)
                    speed = float(np.linalg.norm(mean_velocity))
                    assert speed > 1.0e-6
                    axis_velocity_directions[task.task_id] = mean_velocity / speed
                if index >= 3 and frame > 1:
                    center_step = slot.data["center_step_result"]
                    if center_step is not None:
                        gravity_ratios[task.task_id].append(
                            float(center_step.gravity_ratio)
                        )
                trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
                trajectory_digest.update(np.asarray(index, dtype=np.int32).tobytes())
                trajectory_digest.update(candidate.world_positions.tobytes())
            assert writeback.writeback_bone_transforms(world) == sum(
                topology.particle_count for topology in topologies
            )
            bpy.context.view_layer.update()

        for task, direction, initial in zip(tasks[:3], directions, initial_positions[:3]):
            slot = world.solver_slots[task.task_id]
            candidate = slot.data["result_candidate"]
            attributes = np.asarray(
                slot.data["bone_static"].final_proxy.vertex_attributes,
                dtype=np.uint8,
            )
            move = (attributes & np.uint8(0x02)) != 0
            displacement = np.mean(
                candidate.world_positions[move] - initial[move],
                axis=0,
            )
            expected = np.asarray(direction, dtype=np.float32)
            projection = float(np.dot(displacement, expected))
            assert projection > 0.01, (direction, projection)
            np.testing.assert_allclose(
                axis_velocity_directions[task.task_id],
                expected,
                rtol=0.0,
                atol=1.0e-6,
            )

        zero_task, one_task = tasks[3:]
        zero_ratios = np.asarray(gravity_ratios[zero_task.task_id])
        one_ratios = np.asarray(gravity_ratios[one_task.task_id])
        np.testing.assert_allclose(zero_ratios, 1.0, rtol=0.0, atol=1.0e-6)
        assert float(np.max(one_ratios)) <= 0.500001
        assert float(np.min(one_ratios)) >= 0.499999
        zero_slot = world.solver_slots[zero_task.task_id]
        one_slot = world.solver_slots[one_task.task_id]
        zero_move = np.asarray(
            zero_slot.data["bone_static"].final_proxy.vertex_attributes,
            dtype=np.uint8,
        ) & np.uint8(0x02)
        one_move = np.asarray(
            one_slot.data["bone_static"].final_proxy.vertex_attributes,
            dtype=np.uint8,
        ) & np.uint8(0x02)
        zero_displacement = float(np.mean(np.linalg.norm(
            zero_slot.data["result_candidate"].world_positions[zero_move != 0]
            - initial_positions[3][zero_move != 0],
            axis=1,
        )))
        one_displacement = float(np.mean(np.linalg.norm(
            one_slot.data["result_candidate"].world_positions[one_move != 0]
            - initial_positions[4][one_move != 0],
            axis=1,
        )))
        assert zero_displacement > one_displacement + 0.005, (
            zero_displacement,
            one_displacement,
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_gravity_axes_falloff")
        for armature in armatures:
            if armature.name in bpy.data.objects:
                mixed._remove_object(armature)
        for anchor in anchors:
            if anchor.name in bpy.data.objects:
                mixed._remove_object(anchor)


def bone_gravity_axes_falloff():
    first = _run_bone_gravity_axes_falloff()
    second = _run_bone_gravity_axes_falloff()
    assert second == first, (first, second)
    print("[PASS] BoneCloth gravity XYZ/falloff: 2 deterministic x 600 frames")


def _run_bone_angle_restoration_falloff(setup_type, falloff):
    world = world_types.PhysicsWorldCache()
    world.generation = 95
    armature = mixed._armature(
        f"MC2AngleFalloff_{setup_type}_{falloff:.1f}",
        0.0,
        0.9,
    )
    anchor = bpy.data.objects.new(
        f"MC2AngleFalloffAnchor_{setup_type}_{falloff:.1f}",
        None,
    )
    bpy.context.scene.collection.objects.link(anchor)
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        gravity_direction=(0.0, 0.0, -1.0),
        damping=0.05,
        stabilization_time_after_reset=0.0,
        distance_stiffness=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=True,
        angle_restoration_stiffness=0.85,
        angle_restoration_velocity_attenuation=0.0,
        angle_restoration_gravity_falloff=falloff,
        angle_limit_enabled=False,
        collision_mode=0,
        self_collision_mode=0,
    )
    source = [{"armature": armature, "bone": "Root"}]
    if setup_type == names.MC2_SETUP_BONE_CLOTH:
        task = nodes.physicsMC2BoneClothTask(
            source,
            profile=profile,
            anchor_object=anchor,
            world_inertia=0.0,
            anchor_inertia=0.0,
            connection_mode=0,
        )[0][0]
    else:
        task = nodes.physicsMC2BoneSpringTask(
            source,
            profile=profile,
            anchor_object=anchor,
            world_inertia=0.0,
            anchor_inertia=0.0,
        )[0][0]
    topology = topology_module.build_mc2_topology_spec(task)
    initial_basis = {
        bone.name: bone.matrix_basis.copy()
        for bone in armature.pose.bones
    }
    errors = []
    trajectory_digest = hashlib.sha256()
    initial_context = None
    try:
        for frame in range(1, 601):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            angle = 0.0 if frame == 1 else math.radians(90.0)
            armature.rotation_mode = "XYZ"
            anchor.rotation_mode = "XYZ"
            armature.rotation_euler.x = angle
            anchor.rotation_euler.x = angle
            root = armature.pose.bones["Root"]
            root.rotation_mode = "XYZ"
            root.rotation_euler.z = 0.65 * math.sin(frame * 0.11)
            root.location.x = 0.03 * math.sin(frame * 0.07)
            bpy.context.view_layer.update()
            current = bone_frame_input.build_mc2_bone_frame_input(
                task,
                topology,
                frame=frame,
                generation=world.generation,
            )
            mixed._set_frame(world, frame, world.generation)
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [task],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            slot = world.solver_slots[task.task_id]
            context = slot.data["native_context"]
            if initial_context is None:
                initial_context = context
            else:
                assert context is initial_context
            candidate = slot.data["result_candidate"]
            assert candidate.frame == frame
            assert np.all(np.isfinite(candidate.world_positions))
            assert np.all(np.isfinite(candidate.world_rotations_xyzw))
            errors.append(float(np.mean(np.linalg.norm(
                candidate.world_positions - current.world_positions,
                axis=1,
            ))))
            plan = slot.data["writeback_plan"]
            assert plan["rotation_only_connected_count"] > 0
            assert plan["position_rotation_count"] > 0
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(candidate.world_positions.tobytes())
            trajectory_digest.update(candidate.world_rotations_xyzw.tobytes())
            assert writeback.writeback_bone_transforms(world) == topology.particle_count
            bpy.context.view_layer.update()
            if frame == 599:
                assert mixed.debug_module.request_mc2_debug_capture(
                    world,
                    filters={
                        "show_center": True,
                        "show_angle_restoration": True,
                    },
                ) == 1

        slot = world.solver_slots[task.task_id]
        info = slot.data["native_context"].inspect()
        assert info["angle_solve_count"] == 599
        assert info["debug_capture_count"] == 1
        assert info["debug_readback_count"] == 3
        runtime = slot.data["effective_parameters"].debug_dict()
        np.testing.assert_allclose(
            runtime["float_values"]["angle_restoration_gravity_falloff"],
            falloff,
            rtol=0.0,
            atol=1.0e-7,
        )
        snapshot = slot.data["_debug_draw_snapshot"]
        assert snapshot["frame"] == 600
        assert snapshot["center"]["frame_pose"]["anchor_identity"] == (
            f"object:{int(anchor.as_pointer())}"
        )
        valid = np.asarray(
            snapshot["motion"]["angle_restoration_target_valid"],
            dtype=np.uint8,
        )
        assert int(np.count_nonzero(valid)) > 0
        error_array = np.asarray(errors, dtype=np.float32)
        trajectory_digest.update(error_array.tobytes())
        return error_array, trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_angle_restoration_falloff")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)
        if anchor.name in bpy.data.objects:
            mixed._remove_object(anchor)


def bone_angle_restoration_falloff():
    for setup_type in (
        names.MC2_SETUP_BONE_CLOTH,
        names.MC2_SETUP_BONE_SPRING,
    ):
        zero, zero_digest = _run_bone_angle_restoration_falloff(setup_type, 0.0)
        one, one_digest = _run_bone_angle_restoration_falloff(setup_type, 1.0)
        zero_repeat, zero_repeat_digest = _run_bone_angle_restoration_falloff(
            setup_type, 0.0
        )
        one_repeat, one_repeat_digest = _run_bone_angle_restoration_falloff(
            setup_type, 1.0
        )
        assert zero_repeat_digest == zero_digest
        assert one_repeat_digest == one_digest
        np.testing.assert_array_equal(zero_repeat, zero)
        np.testing.assert_array_equal(one_repeat, one)
        assert one[1] > zero[1] + 0.0005, (setup_type, zero[1], one[1])
        zero_early = float(np.mean(zero[1:50]))
        one_early = float(np.mean(one[1:50]))
        assert one_early > zero_early * 1.25, (
            setup_type,
            zero_early,
            one_early,
        )
        assert float(np.mean(one[-100:])) > float(np.mean(zero[-100:])) * 1.25
        print(
            f"[INFO] {setup_type} Angle Restoration gravity falloff: "
            f"early {zero_early:.9f}->{one_early:.9f}"
        )
    print("[PASS] Bone Angle Restoration gravity falloff: 2 setups x 2 x 600")


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
            motion_stiffness=1.0,
            self_collision_mode=0,
        )
        tasks, _task_names = nodes.physicsMC2BoneClothTask(
            [{"armature": armature, "bone": "Root"}],
            profile=profile,
            normal_axis=2,
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


def _run_bone_distance_tether():
    world = world_types.PhysicsWorldCache()
    world.generation = 77
    armature = mixed._armature("MC2BoneDistanceTether", 0.0, 1.1)

    def make_task(*, gravity, gravity_direction, compression, stiffness):
        profile = parameters.make_mc2_particle_profile(
            gravity=gravity,
            gravity_direction=gravity_direction,
            damping=0.5,
            stabilization_time_after_reset=0.0,
            tether_compression=compression,
            distance_stiffness=stiffness,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            collision_mode=0,
            self_collision_mode=0,
        )
        tasks, _task_names = nodes.physicsMC2BoneClothTask(
            [{"armature": armature, "bone": "Root"}],
            profile=profile,
            connection_mode=0,
        )
        assert len(tasks) == 1
        return tasks[0]

    task = make_task(
        gravity=0.8,
        gravity_direction=(0.0, 1.0, 0.0),
        compression=0.4,
        stiffness=0.1,
    )
    stable_task_id = task.task_id
    topology = topology_module.build_mc2_topology_spec(task)
    animation_input = bone_frame_input.build_mc2_bone_frame_input(
        task,
        topology,
        frame=1,
        generation=world.generation,
    )
    edge_indices = np.asarray([
        (index, index + 1)
        for index in range(topology.particle_count - 1)
    ], dtype=np.int32)
    edge_rests = np.linalg.norm(
        animation_input.world_positions[edge_indices[:, 1]]
        - animation_input.world_positions[edge_indices[:, 0]],
        axis=1,
    )
    trajectory_digest = hashlib.sha256()
    roots = step_basic = attributes = None
    phase_ratios = {"stretch": [], "compression": []}
    try:
        for frame in range(1, 901):
            if frame == 226:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = make_task(
                    gravity=0.8,
                    gravity_direction=(0.0, 1.0, 0.0),
                    compression=0.4,
                    stiffness=0.05,
                )
                assert task.task_id == stable_task_id
            elif frame == 451:
                rebuild_context = world.solver_slots[task.task_id].data["native_context"]
                task = make_task(
                    gravity=0.5,
                    gravity_direction=(0.0, -1.0, 0.0),
                    compression=0.65,
                    stiffness=0.35,
                )
                assert task.task_id == stable_task_id
            elif frame == 676:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = make_task(
                    gravity=0.5,
                    gravity_direction=(0.0, -1.0, 0.0),
                    compression=0.65,
                    stiffness=0.25,
                )
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
            assert np.all(np.isfinite(candidate.world_positions))
            assert np.all(np.isfinite(candidate.world_rotations_xyzw))
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())

            if roots is None:
                native_debug = slot.data["native_context"].refresh_debug_draw_snapshot(
                    include_step_basic=True,
                    include_motion_base=False,
                    include_dynamics=False,
                    include_distance_tether=True,
                    include_bending=False,
                )
                roots = np.asarray(
                    native_debug["distance_tether"]["baseline_roots"],
                    dtype=np.int32,
                )
                step_basic = np.asarray(
                    native_debug["step_basic_positions"],
                    dtype=np.float32,
                )
                attributes = np.asarray(
                    slot.data["bone_static"].final_proxy.vertex_attributes,
                    dtype=np.uint8,
                )
                assert np.any(attributes & 0x01)

            fixed = (attributes & 0x01) != 0
            np.testing.assert_allclose(
                candidate.world_positions[fixed],
                animation_input.world_positions[fixed],
                atol=1.0e-6,
            )
            lengths = np.linalg.norm(
                candidate.world_positions[edge_indices[:, 1]]
                - candidate.world_positions[edge_indices[:, 0]],
                axis=1,
            )
            assert float(np.max(lengths / edge_rests)) <= 1.55, (
                frame,
                float(np.max(lengths / edge_rests)),
            )
            for particle, root in enumerate(roots):
                if root < 0 or root == particle:
                    continue
                rest = float(np.linalg.norm(step_basic[particle] - step_basic[root]))
                if rest <= 1.0e-8:
                    continue
                current = float(np.linalg.norm(
                    candidate.world_positions[particle]
                    - candidate.world_positions[root]
                ))
                ratio = current / rest
                phase = "stretch" if frame < 451 else "compression"
                phase_ratios[phase].append(ratio)
                minimum = 0.55 if frame < 451 else 0.32
                assert ratio >= minimum, (frame, particle, ratio, minimum)
                assert ratio <= 1.25, (frame, particle, ratio)

            plan = slot.data["writeback_plan"]
            assert plan["rotation_only_connected_count"] > 0
            assert plan["position_rotation_count"] > 0
            assert writeback.writeback_bone_transforms(world) == topology.particle_count
            bpy.context.view_layer.update()
            if frame in (226, 676):
                assert slot.data["native_context"] is old_context
                assert slot.data["native_context"].inspect()["parameter_revision"] == old_revision + 1
            elif frame == 451:
                assert slot.data["native_context"] is not rebuild_context
                assert rebuild_context.inspect()["released"] is True

        info = world.solver_slots[task.task_id].data["native_context"].inspect()
        assert info["distance_solve_count"] > 0
        assert info["tether_solve_count"] > 0
        stretch_min = min(phase_ratios["stretch"])
        stretch_max = max(phase_ratios["stretch"])
        compression_min = min(phase_ratios["compression"])
        compression_max = max(phase_ratios["compression"])
        assert stretch_max > 1.03, stretch_max
        assert compression_min < 0.35, compression_min
        print(
            "[INFO] BoneCloth tether root ratio: "
            f"stretch {stretch_min:.6f}..{stretch_max:.6f}, "
            f"compression {compression_min:.6f}..{compression_max:.6f}"
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_distance_tether_soak")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)


def bone_distance_tether():
    first = _run_bone_distance_tether()
    second = _run_bone_distance_tether()
    assert first == second, (first, second)
    print("[PASS] BoneCloth Distance/Tether: connected/disconnected x 2 x 900")


def _bone_angle_values(native_context, candidate):
    snapshot = native_context.refresh_debug_draw_snapshot(
        include_step_basic=False,
        include_angle_limit=True,
        include_dynamics=False,
        include_distance_tether=False,
        include_bending=False,
    )
    targets = snapshot["angle_limit_target_positions"]
    vectors = snapshot["angle_limit_target_vectors"]
    valid = snapshot["angle_limit_target_valid"]
    angles = []
    for child, is_valid in enumerate(valid):
        if not is_valid:
            continue
        base_vector = vectors[child]
        parent_position = targets[child] - base_vector
        current_vector = candidate.world_positions[child] - parent_position
        base_length = float(np.linalg.norm(base_vector))
        current_length = float(np.linalg.norm(current_vector))
        if min(base_length, current_length) <= 1.0e-8:
            continue
        cosine = float(np.dot(base_vector, current_vector) / (base_length * current_length))
        angles.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    assert angles
    return angles


def _run_bone_angle_limit(setup_type):
    world = world_types.PhysicsWorldCache()
    world.generation = 78 if setup_type == names.MC2_SETUP_BONE_CLOTH else 79
    armature = mixed._armature(f"MC2AngleLimit_{setup_type}", 0.0, 1.0)
    initial_basis = {
        bone.name: bone.matrix_basis.copy()
        for bone in armature.pose.bones
    }

    def make_task(enabled, limit):
        profile = parameters.make_mc2_particle_profile(
            gravity=4.0,
            gravity_direction=(0.0, 0.0, -1.0),
            damping=0.1,
            stabilization_time_after_reset=0.0,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=enabled,
            angle_limit=limit,
            angle_limit_stiffness=1.0,
            collision_mode=0,
            self_collision_mode=0,
        )
        source = {"armature": armature, "bone": "Root"}
        if setup_type == names.MC2_SETUP_BONE_CLOTH:
            tasks, _task_names = nodes.physicsMC2BoneClothTask(
                [source], profile=profile, connection_mode=0
            )
        else:
            tasks, _task_names = nodes.physicsMC2BoneSpringTask(
                [source], profile=profile
            )
        assert len(tasks) == 1
        return tasks[0]

    task = make_task(False, 30.0)
    stable_task_id = task.task_id
    topology = topology_module.build_mc2_topology_spec(task)
    phase_angles = {"off_a": [], "limit_30": [], "off_b": [], "limit_15": []}
    trajectory_digest = hashlib.sha256()
    disabled_count = None
    try:
        for frame in range(1, 901):
            if frame == 201:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = make_task(True, 30.0)
                assert task.task_id == stable_task_id
            elif frame == 401:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = make_task(False, 30.0)
                assert task.task_id == stable_task_id
            elif frame == 601:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = make_task(True, 15.0)
                assert task.task_id == stable_task_id

            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            root = armature.pose.bones["Root"]
            root.rotation_mode = "XYZ"
            root.rotation_euler.z = 0.75 * math.sin(frame * 0.13)
            root.location.x = 0.035 * math.sin(frame * 0.09)
            bpy.context.view_layer.update()
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
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
            if frame <= 200:
                phase = "off_a"
            elif frame <= 400:
                phase = "limit_30"
            elif frame <= 600:
                phase = "off_b"
            else:
                phase = "limit_15"
            if phase in ("limit_30", "limit_15"):
                phase_angles[phase].append(max(_bone_angle_values(
                    slot.data["native_context"], candidate
                )))

            info = slot.data["native_context"].inspect()
            if frame == 200:
                assert info["angle_solve_count"] == 0
            elif frame in (201, 401, 601):
                assert slot.data["native_context"] is old_context
                assert info["parameter_revision"] == old_revision + 1
                if frame == 401:
                    disabled_count = info["angle_solve_count"]
            elif 401 < frame <= 600:
                assert info["angle_solve_count"] == disabled_count
            if setup_type == names.MC2_SETUP_BONE_CLOTH:
                plan = slot.data["writeback_plan"]
                assert plan["rotation_only_connected_count"] > 0
                assert plan["position_rotation_count"] > 0
            assert writeback.writeback_bone_transforms(world) == topology.particle_count
            bpy.context.view_layer.update()

        steady_15 = phase_angles["limit_15"][100:]
        steady_30 = phase_angles["limit_30"][100:]
        print(
            f"[INFO] {setup_type} Angle Limit observed: "
            f"30deg max={max(steady_30):.6f} p95={np.percentile(steady_30, 95):.6f}; "
            f"15deg max={max(steady_15):.6f} p95={np.percentile(steady_15, 95):.6f}"
        )
        assert max(steady_30) <= 36.0, (setup_type, "30deg", max(steady_30))
        assert max(steady_15) <= 29.0, (setup_type, "15deg", max(steady_15))
        assert max(steady_15) <= max(steady_30) - 5.0, (
            setup_type, max(steady_30), max(steady_15)
        )
        assert slot.data["native_context"].inspect()["angle_solve_count"] > disabled_count
        for phase in ("limit_30", "limit_15"):
            trajectory_digest.update(np.asarray(phase_angles[phase], dtype=np.float32).tobytes())
        print(
            f"[INFO] {setup_type} Angle Limit max: "
            f"30deg {max(steady_30):.6f}, "
            f"15deg {max(steady_15):.6f}"
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_angle_limit_soak")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)


def bone_angle_limit():
    for setup_type in (names.MC2_SETUP_BONE_CLOTH, names.MC2_SETUP_BONE_SPRING):
        first = _run_bone_angle_limit(setup_type)
        second = _run_bone_angle_limit(setup_type)
        assert first == second, (setup_type, first, second)
    print("[PASS] Bone Angle Limit: 2 setups x 2 deterministic x 900 frames")


def _bending_armature(name, x_offset):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    obj.location.x = x_offset
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    control = data.edit_bones.new("Control")
    control.head = (0.0, 0.0, 0.0)
    control.tail = (0.0, 0.0, 1.0)
    offsets = (
        (1.0, 0.35, 0.20),
        (0.85, -0.25, 0.45),
        (0.70, 0.55, -0.15),
        (0.55, -0.40, 0.30),
    )
    for chain_index in range(2):
        head = control.tail + mathutils.Vector(
            (0.0, chain_index * 0.55, chain_index * 0.1)
        )
        previous = control
        for depth, offset in enumerate(offsets):
            bone = data.edit_bones.new(f"Chain{chain_index}_{depth}")
            bone.head = head
            bone.tail = head + mathutils.Vector(offset)
            bone.parent = previous
            bone.use_connect = depth > 0 and not (chain_index == 1 and depth == 2)
            bone.roll = 0.2 + depth * 0.35 + chain_index * 0.15
            head = bone.tail.copy()
            previous = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _bending_task(armature, stiffness):
    profile = parameters.make_mc2_particle_profile(
        gravity=6.0,
        gravity_direction=(0.0, 0.0, -1.0),
        damping=0.08,
        stabilization_time_after_reset=0.0,
        distance_stiffness=0.65,
        bending_stiffness=stiffness,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        max_distance_enabled=False,
        backstop_enabled=False,
        collision_mode=0,
        self_collision_mode=0,
    )
    tasks, _names = nodes.physicsMC2BoneClothTask(
        [{"armature": armature, "bone": "Control"}],
        profile=profile,
        connection_mode=1,
    )
    assert len(tasks) == 1
    return tasks[0]


def _bending_errors(positions, static):
    angle_errors = []
    volume_errors = []
    volume_signs = []
    for quad, rest, marker in zip(
        static["quads"], static["rests"], static["markers"]
    ):
        p = positions[quad]
        if marker == 100:
            actual = float(np.dot(
                np.cross(p[1] - p[0], p[2] - p[0]),
                p[3] - p[0],
            ) / 6.0 * 1000.0)
            volume_errors.append(abs(actual - rest) / max(abs(rest), 1.0e-6))
            volume_signs.append(actual * rest > 0.0)
            continue
        edge = p[3] - p[2]
        n1 = np.cross(p[2] - p[0], p[3] - p[0])
        n2 = np.cross(p[3] - p[1], p[2] - p[1])
        n1_length = float(np.linalg.norm(n1))
        n2_length = float(np.linalg.norm(n2))
        if min(n1_length, n2_length) <= 1.0e-10:
            angle_errors.append(math.pi)
            continue
        n1 /= n1_length
        n2 /= n2_length
        actual = math.acos(float(np.clip(np.dot(n1, n2), -1.0, 1.0)))
        direction = float(np.dot(np.cross(n1, n2), edge))
        actual *= -1.0 if direction < 0.0 else 1.0
        expected = float(rest) * (-1.0 if marker < 0 else 1.0)
        angle_errors.append(abs(actual - expected))
    return angle_errors, volume_errors, volume_signs


def _run_bone_bending_suite():
    world = world_types.PhysicsWorldCache()
    world.generation = 82
    armatures = (
        _bending_armature("MC2BendingSoft", -1.5),
        _bending_armature("MC2BendingStiff", 1.5),
    )
    tasks = (
        _bending_task(armatures[0], 0.0),
        _bending_task(armatures[1], 1.0),
    )
    topologies = tuple(topology_module.build_mc2_topology_spec(task) for task in tasks)
    assert all(topology.bone_connection.triangles for topology in topologies)
    static_bending = [None, None]
    angle_history = ([], [])
    volume_history = ([], [])
    trajectory_digest = hashlib.sha256()
    try:
        for frame in range(1, 901):
            for armature in armatures:
                control = armature.pose.bones["Control"]
                control.rotation_mode = "XYZ"
                control.rotation_euler.x = 0.22 * math.sin(frame * 0.031)
                control.rotation_euler.z = 0.35 * math.sin(frame * 0.047)
                control.location.y = 0.08 * math.sin(frame * 0.037)
            bpy.context.view_layer.update()
            mixed._set_frame(world, frame, world.generation)
            returned, ready, status = nodes.physicsMC2Step(
                world,
                list(tasks),
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            candidate_positions = []
            for index, (task, topology) in enumerate(zip(tasks, topologies)):
                slot = world.solver_slots[task.task_id]
                candidate = slot.data["result_candidate"]
                candidate_positions.append(candidate.world_positions)
                assert candidate.frame == frame
                assert np.all(np.isfinite(candidate.world_positions))
                assert np.all(np.isfinite(candidate.world_rotations_xyzw))
                if frame == 1:
                    snapshot = slot.data["native_context"].refresh_debug_draw_snapshot(
                        include_bending=True,
                    )
                    static_bending[index] = {
                        key: np.array(value, copy=True)
                        for key, value in snapshot["bending"].items()
                    }
                    assert np.any(static_bending[index]["markers"] == 100)
                    assert np.any(static_bending[index]["markers"] != 100)
                angle_errors, volume_errors, volume_signs = _bending_errors(
                    candidate.world_positions,
                    static_bending[index],
                )
                assert angle_errors and volume_errors
                if index == 1 and frame > 30:
                    assert all(volume_signs), (frame, volume_errors)
                angle_history[index].append(float(np.mean(angle_errors)))
                volume_history[index].append(float(np.mean(volume_errors)))
                plan = slot.data["writeback_plan"]
                assert plan["rotation_only_connected_count"] > 0
                assert plan["position_rotation_count"] > 0
                trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
                trajectory_digest.update(np.asarray(index, dtype=np.int32).tobytes())
                trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
                trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
            roots = np.asarray(topologies[0].bone_connection.root_order, dtype=np.int32)
            np.testing.assert_allclose(
                candidate_positions[0][roots] - np.asarray(armatures[0].location),
                candidate_positions[1][roots] - np.asarray(armatures[1].location),
                rtol=0.0,
                atol=2.0e-5,
            )
            assert writeback.writeback_bone_transforms(world) == sum(
                topology.particle_count for topology in topologies
            )
            bpy.context.view_layer.update()

        soft_info = world.solver_slots[tasks[0].task_id].data["native_context"].inspect()
        stiff_info = world.solver_slots[tasks[1].task_id].data["native_context"].inspect()
        assert soft_info["bending_solve_count"] == 0
        assert stiff_info["bending_solve_count"] > 0
        soft_angle = float(np.mean(angle_history[0][-300:]))
        stiff_angle = float(np.mean(angle_history[1][-300:]))
        soft_volume = float(np.mean(volume_history[0][-300:]))
        stiff_volume = float(np.mean(volume_history[1][-300:]))
        assert stiff_angle < soft_angle * 0.9, (soft_angle, stiff_angle)
        assert stiff_volume < soft_volume * 0.9, (soft_volume, stiff_volume)
        print(
            "[INFO] BoneCloth Bending mean error: "
            f"angle {soft_angle:.6f}->{stiff_angle:.6f}, "
            f"volume {soft_volume:.6f}->{stiff_volume:.6f}"
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_bending_soak")
        for armature in armatures:
            if armature.name in bpy.data.objects:
                mixed._remove_object(armature)


def bone_triangle_bending():
    first = _run_bone_bending_suite()
    second = _run_bone_bending_suite()
    assert first == second, (first, second)
    print("[PASS] BoneCloth Triangle Bending: 2 tasks x 2 deterministic x 900")


def _bone_self_task(armature, enabled, cloth_mass, teleport_mode=0):
    profile = nodes.physicsMC2BoneClothProfile(
        gravity=7.0,
        gravity_direction=(0.0, 0.0, -1.0),
        damping=0.05,
        stabilization_time_after_reset=0.0,
        radius=0.04,
        distance_stiffness=0.45,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        collision_mode=0,
        self_collision_enabled=enabled,
    )
    tasks, _names = nodes.physicsMC2BoneClothTask(
        [{"armature": armature, "bone": "Control"}],
        profile=profile,
        cloth_mass=cloth_mass,
        teleport_mode=teleport_mode,
        teleport_distance=0.5,
        teleport_rotation=180.0,
        connection_mode=1,
    )
    assert len(tasks) == 1
    return tasks[0]


def _run_bone_self_collision():
    world = world_types.PhysicsWorldCache()
    world.generation = 83
    armature = _bending_armature("MC2BoneSelf", 0.0)
    task = _bone_self_task(armature, True, 0.25)
    topology = topology_module.build_mc2_topology_spec(task)
    stable_task_id = task.task_id
    trajectory_digest = hashlib.sha256()
    disabled_counts = None
    pre_teleport_self_counts = None
    teleport_cleared = False
    try:
        for frame in range(1, 901):
            if frame == 301:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = _bone_self_task(armature, True, 0.75)
                assert task.task_id == stable_task_id
            elif frame == 451:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = _bone_self_task(armature, False, 0.75)
                assert task.task_id == stable_task_id
            elif frame == 601:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = _bone_self_task(armature, True, 0.75)
                assert task.task_id == stable_task_id
            elif frame == 801:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                before = old_context.inspect()
                pre_teleport_self_counts = (
                    before["self_contact_candidate_count"],
                    before["self_contact_cache_count"],
                    before["self_intersect_record_count"],
                )
                assert all(value > 0 for value in pre_teleport_self_counts), (
                    pre_teleport_self_counts,
                    before,
                )
                old_revision = before["parameter_revision"]
                task = _bone_self_task(armature, True, 0.75, teleport_mode=1)
                assert task.task_id == stable_task_id

            control = armature.pose.bones["Control"]
            control.rotation_mode = "XYZ"
            animation_frame = min(frame, 800)
            control.rotation_euler.x = 0.7 * math.sin(animation_frame * 0.043)
            control.rotation_euler.z = 1.1 * math.sin(animation_frame * 0.057)
            control.location.y = 0.2 * math.sin(animation_frame * 0.039)
            if frame == 801:
                armature.pose.bones["Chain1_2"].location = (2.0, 0.0, 0.0)
            bpy.context.view_layer.update()
            mixed._set_frame(world, frame, world.generation)
            if frame == 801:
                world.frame_context.time_scale = 0.0
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
            info = slot.data["native_context"].inspect()
            if frame in (301, 451, 601, 801):
                assert slot.data["native_context"] is old_context
                assert info["parameter_revision"] == old_revision + 1
            if frame == 801:
                teleport = slot.data["particle_teleport_result"]
                assert teleport["mode"] == 1
                assert 0 < teleport["trigger_count"] < topology.particle_count
                assert slot.data["frame_schedule"].update_count == 0
                assert info["self_contact_candidate_count"] == 0
                assert info["self_contact_cache_count"] == 0
                assert info["self_intersect_record_count"] == 0
                assert info["self_primitive_dynamic_ready"] is False
                assert info["self_grid_dynamic_ready"] is False
                assert info["self_candidate_ready"] is False
                teleport_cleared = True
            if frame == 450:
                disabled_counts = (
                    info["self_primitive_update_count"],
                    info["self_grid_update_count"],
                    info["self_candidate_update_count"],
                    info["self_contact_build_count"],
                )
            elif 451 <= frame <= 600:
                assert disabled_counts == (
                    info["self_primitive_update_count"],
                    info["self_grid_update_count"],
                    info["self_candidate_update_count"],
                    info["self_contact_build_count"],
                )
            plan = slot.data["writeback_plan"]
            assert plan["rotation_only_connected_count"] > 0
            assert plan["position_rotation_count"] > 0
            assert writeback.writeback_bone_transforms(world) == topology.particle_count
            bpy.context.view_layer.update()
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
            if frame == 899:
                mixed.debug_module.request_mc2_debug_capture(
                    world,
                    filters={
                        "show_self_primitives": True,
                        "show_self_candidates": True,
                        "show_self_contacts": True,
                    },
                )

        slot = world.solver_slots[task.task_id]
        info = slot.data["native_context"].inspect()
        assert info["self_primitive_update_count"] > disabled_counts[0]
        assert info["self_contact_candidate_count"] > 0
        assert info["self_contact_cache_count"] <= info["self_contact_candidate_count"]
        assert info["self_intersect_record_count"] > 0
        assert pre_teleport_self_counts is not None
        assert teleport_cleared is True
        runtime = slot.data["effective_parameters"].debug_dict()
        assert runtime["float_values"]["cloth_mass"] == np.float32(0.75)
        assert runtime["int_values"]["self_collision_mode"] == 2
        assert runtime["int_values"]["self_collision_sync_mode"] == 0
        np.testing.assert_allclose(
            runtime["curve_values"]["radius"], 0.04, rtol=0.0, atol=1.0e-7
        )
        np.testing.assert_allclose(
            runtime["curve_values"]["self_collision_thickness"],
            0.01,
            rtol=0.0,
            atol=1.0e-7,
        )
        snapshot = slot.data["_debug_draw_snapshot"]
        assert snapshot["frame"] == 900
        assert len(snapshot["self_collision"]["particle_indices"]) > 0
        assert len(snapshot["self_collision"]["candidates"]) > 0
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_self_collision_soak")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)


def bone_self_collision():
    first = _run_bone_self_collision()
    second = _run_bone_self_collision()
    assert first == second, (first, second)
    print("[PASS] BoneCloth task self: 2 deterministic x 900 frames")


def _quaternion_angle_degrees(left, right):
    left_norm = left / np.linalg.norm(left, axis=-1, keepdims=True)
    right_norm = right / np.linalg.norm(right, axis=-1, keepdims=True)
    dots = np.clip(np.abs(np.sum(left_norm * right_norm, axis=-1)), 0.0, 1.0)
    return np.degrees(2.0 * np.arccos(dots))


def _quaternion_component_distance(left, right):
    direct = np.max(np.abs(left - right), axis=-1)
    negated = np.max(np.abs(left + right), axis=-1)
    return np.minimum(direct, negated)


def _run_bone_rotation_output_case(setup_type, interpolation, root_rotation):
    world = world_types.PhysicsWorldCache()
    world.generation = 96
    armature = mixed._armature(
        f"MC2RotationOutput_{setup_type}_{interpolation}_{root_rotation}",
        0.0,
        0.9,
    )
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.05,
        stabilization_time_after_reset=0.0,
        distance_stiffness=0.4,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        radius=0.012,
        collision_mode=2,
        collision_limit_distance=0.05,
        self_collision_mode=0,
    )
    source = [{"armature": armature, "bone": "Root"}]
    if setup_type == names.MC2_SETUP_BONE_CLOTH:
        task = nodes.physicsMC2BoneClothTask(
            source,
            profile=profile,
            connection_mode=0,
            rotational_interpolation=interpolation,
            root_rotation=root_rotation,
            collided_by_groups=1,
        )[0][0]
    else:
        task = nodes.physicsMC2BoneSpringTask(
            source,
            profile=profile,
            rotational_interpolation=interpolation,
            root_rotation=root_rotation,
            collided_by_groups=1,
        )[0][0]
    topology = topology_module.build_mc2_topology_spec(task)
    initial_input = bone_frame_input.build_mc2_bone_frame_input(
        task,
        topology,
        frame=1,
        generation=world.generation,
    )
    initial_basis = {
        bone.name: bone.matrix_basis.copy()
        for bone in armature.pose.bones
    }
    target = np.asarray(initial_input.world_positions[2], dtype=np.float64)
    positions = []
    rotations = []
    initial_context = None
    try:
        for frame in range(1, 601):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            bpy.context.view_layer.update()
            world.collider_snapshot = {
                "frame": frame,
                "colliders": ({
                    "key": "bone-rotation-output",
                    "type": "SPHERE",
                    "primary_group": 1,
                    "center": tuple(
                        float(value) for value in target + (0.033, 0.0, 0.0)
                    ),
                    "radius": 0.025,
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
            context = slot.data["native_context"]
            if initial_context is None:
                initial_context = context
            else:
                assert context is initial_context
            candidate = slot.data["result_candidate"]
            assert candidate.frame == frame
            assert np.all(np.isfinite(candidate.world_positions))
            assert np.all(np.isfinite(candidate.world_rotations_xyzw))
            positions.append(np.array(candidate.world_positions, copy=True))
            rotations.append(np.array(candidate.world_rotations_xyzw, copy=True))
            plan = slot.data["writeback_plan"]
            assert plan["rotation_only_connected_count"] > 0
            assert plan["position_rotation_count"] > 0
            assert writeback.writeback_bone_transforms(world) == topology.particle_count
            bpy.context.view_layer.update()
            if frame == 599:
                assert mixed.debug_module.request_mc2_debug_capture(
                    world,
                    filters={"show_output": True},
                ) == 1

        slot = world.solver_slots[task.task_id]
        info = slot.data["native_context"].inspect()
        if setup_type == names.MC2_SETUP_BONE_SPRING:
            assert info["point_collision_solve_count"] > 0
        else:
            assert info["edge_collision_solve_count"] > 0
        assert info["debug_capture_count"] == 0
        runtime = slot.data["effective_parameters"].debug_dict()["float_values"]
        np.testing.assert_allclose(
            runtime["rotational_interpolation"], interpolation, rtol=0.0, atol=1.0e-7
        )
        np.testing.assert_allclose(
            runtime["root_rotation"], root_rotation, rtol=0.0, atol=1.0e-7
        )
        snapshot = slot.data["_debug_draw_snapshot"]
        assert snapshot["frame"] == 600
        assert snapshot["filters"]["show_output"] is True
        assert len(snapshot["output"]["world_offsets"]) == topology.particle_count
        attributes = np.asarray(
            slot.data["bone_static"].final_proxy.vertex_attributes,
            dtype=np.uint8,
        )
        return (
            np.asarray(positions, dtype=np.float32),
            np.asarray(rotations, dtype=np.float32),
            attributes,
        )
    finally:
        world.omni_cache_dispose("bone_rotation_output_soak")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)


def _run_bone_rotation_output_setup(setup_type):
    base = _run_bone_rotation_output_case(setup_type, 0.0, 0.0)
    interpolation = _run_bone_rotation_output_case(setup_type, 1.0, 0.0)
    root = _run_bone_rotation_output_case(setup_type, 0.0, 1.0)
    np.testing.assert_array_equal(base[0], interpolation[0])
    np.testing.assert_array_equal(base[0], root[0])
    np.testing.assert_array_equal(base[2], interpolation[2])
    np.testing.assert_array_equal(base[2], root[2])

    attributes = base[2]
    indices = np.arange(len(attributes))
    fixed = (attributes & 0x01) != 0
    move_parent = np.logical_and(
        (attributes & 0x02) != 0,
        indices < len(attributes) - 1,
    )
    leaf = np.logical_not(np.logical_or(fixed, move_parent))
    assert int(np.count_nonzero(fixed)) == 1
    assert int(np.count_nonzero(move_parent)) >= 2
    assert int(np.count_nonzero(leaf)) == 1

    interpolation_angles = _quaternion_angle_degrees(base[1], interpolation[1])
    root_angles = _quaternion_angle_degrees(base[1], root[1])
    interpolation_distance = _quaternion_component_distance(
        base[1], interpolation[1]
    )
    root_distance = _quaternion_component_distance(base[1], root[1])
    assert float(np.max(interpolation_angles[:, move_parent])) > 0.05
    assert float(np.max(interpolation_distance[:, fixed])) < 1.0e-6
    assert float(np.max(root_angles[:, fixed])) > 0.01
    assert float(np.max(root_distance[:, np.logical_not(fixed)])) < 1.0e-6, (
        setup_type,
        float(np.max(root_angles[:, fixed])),
        float(np.max(root_distance[:, np.logical_not(fixed)])),
    )

    digest = hashlib.sha256()
    for values in (base[0], base[1], interpolation[1], root[1], attributes):
        digest.update(np.asarray(values).tobytes())
    return digest.hexdigest()


def bone_rotation_output_controls():
    for setup_type in (names.MC2_SETUP_BONE_CLOTH, names.MC2_SETUP_BONE_SPRING):
        first = _run_bone_rotation_output_setup(setup_type)
        second = _run_bone_rotation_output_setup(setup_type)
        assert second == first, (setup_type, first, second)
    print(
        "[PASS] Bone output rotation controls: "
        "2 setups x 3 endpoints x 2 deterministic x 600 frames"
    )


def main():
    mixed.physics_blender.register()
    try:
        bone_angle_constraints()
        bone_angle_restoration_attenuation()
        bone_gravity_axes_falloff()
        bone_angle_restoration_falloff()
        bone_motion_constraints()
        bone_external_collision()
        bone_friction_response()
        bone_distance_tether()
        bone_angle_limit()
        bone_triangle_bending()
        bone_self_collision()
        bone_rotation_output_controls()
    finally:
        if mixed.physics_blender.is_registered():
            mixed.physics_blender.unregister()
    print("MC2 Bone constraint soak: PASS")


if __name__ == "__main__":
    main()
