"""Long-run BoneCloth/BoneSpring angle-constraint branch acceptance."""

from __future__ import annotations

import hashlib
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

        final_candidate = world.solver_slots[task.task_id].data["result_candidate"]
        digest = hashlib.sha256()
        digest.update(np.asarray(final_candidate.world_positions).tobytes())
        digest.update(np.asarray(final_candidate.world_rotations_xyzw).tobytes())
        print(
            f"[INFO] {setup_type} max zero-force drift: "
            f"{max_rest_error:.9f}m / budget {rest_budget:.9f}m"
        )
        return digest.hexdigest()
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
        candidate = slot.data["result_candidate"]
        digest = hashlib.sha256()
        digest.update(np.asarray(candidate.world_positions).tobytes())
        digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
        return digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_motion_soak")
        if armature.name in bpy.data.objects:
            mixed._remove_object(armature)


def bone_motion_constraints():
    first = _run_bone_motion()
    second = _run_bone_motion()
    assert first == second, (first, second)
    print("[PASS] BoneCloth Motion: connected/disconnected x 2 x 900 frames")


def main():
    mixed.physics_blender.register()
    try:
        bone_angle_constraints()
        bone_motion_constraints()
    finally:
        if mixed.physics_blender.is_registered():
            mixed.physics_blender.unregister()
    print("MC2 Bone angle constraint soak: PASS")


if __name__ == "__main__":
    main()
