"""公开 Bone 产品 request 的 Angle/Motion 数值边界验收。"""

from __future__ import annotations

import math
import os
import sys

import bpy
import mathutils
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_bone_product_constraint_soak as product_soak


nodes = product_soak.nodes
parameters = product_soak.parameters
product_slot = product_soak.product_slot
world_types = product_soak.world_types
writeback = product_soak.writeback

print(f"MC2_BONE_PRODUCT_ANGLE_MOTION_SOURCE {__file__}")


def _request(
    armature,
    *,
    spring: bool,
    restoration: bool,
    limit_enabled: bool,
    angle_limit: float,
    motion: bool = False,
    backstop: bool = False,
):
    profile = parameters.make_mc2_particle_profile(
        gravity=6.0 if motion else 4.0,
        gravity_direction=(0.0, 0.0, -1.0),
        damping=0.05 if motion else 0.1,
        stabilization_time_after_reset=0.0,
        distance_stiffness=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=restoration,
        angle_restoration_stiffness=0.85,
        angle_restoration_velocity_attenuation=0.25,
        angle_restoration_gravity_falloff=0.0,
        angle_limit_enabled=limit_enabled,
        angle_limit=angle_limit,
        angle_limit_stiffness=1.0,
        max_distance_enabled=motion,
        max_distance=0.03,
        backstop_enabled=motion and backstop,
        backstop_radius=0.01,
        backstop_distance=0.005,
        motion_stiffness=1.0,
        collision_mode=0,
        self_collision_mode=0,
        spring_enabled=False,
        wind_influence=0.0,
    )
    task_values = {"teleport_mode": 0}
    if spring:
        requests, _report = nodes.physicsMC2BoneSpringTask(
            [{
                "armature": armature,
                "root_bone": "Chain0_0",
                "bones": tuple(f"Chain0_{depth}" for depth in range(6)),
            }],
            profile=profile,
            **task_values,
        )
    else:
        requests, _report = nodes.physicsMC2BoneClothTask(
            [{"armature": armature, "bone": "Parent"}],
            profile=profile,
            connection_mode=0,
            normal_axis=2,
            **task_values,
        )
    assert len(requests) == 1
    return requests[0]


def _quaternion(xyzw) -> mathutils.Quaternion:
    return mathutils.Quaternion((xyzw[3], xyzw[0], xyzw[1], xyzw[2]))


def _angles(
    program,
    output_positions,
    base_positions,
    base_rotations,
) -> np.ndarray:
    parents = np.asarray(program.baseline_parent_indices, dtype=np.int32)
    rotations = [_quaternion(value) for value in base_rotations]
    values = []
    starts = np.asarray(program.baseline_line_start, dtype=np.int32)
    counts = np.asarray(program.baseline_line_count, dtype=np.int32)
    data = np.asarray(program.baseline_line_data, dtype=np.int32)
    for start, count in zip(starts, counts):
        for child in data[start + 1:start + count]:
            parent = int(parents[child])
            if parent < 0 or parent == child:
                continue
            base = mathutils.Vector(base_positions[child] - base_positions[parent])
            current = mathutils.Vector(output_positions[child] - output_positions[parent])
            if min(base.length, current.length) <= 1.0e-8:
                continue
            local_direction = (
                _quaternion(base_rotations[parent]).inverted()
                @ base.normalized()
            )
            target = rotations[parent] @ local_direction
            cosine = float(target.dot(current) / current.length)
            values.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
            local_rotation = (
                _quaternion(base_rotations[parent]).inverted()
                @ _quaternion(base_rotations[child])
            )
            rotations[child] = (
                target.rotation_difference(current)
                @ rotations[parent]
                @ local_rotation
            )
    assert values
    return np.asarray(values, dtype=np.float32)


def _restoration_angles(program, output_positions, base_positions) -> np.ndarray:
    parents = np.asarray(program.baseline_parent_indices, dtype=np.int32)
    values = []
    for child, parent in enumerate(parents):
        if parent < 0 or parent == child:
            continue
        base = base_positions[child] - base_positions[parent]
        current = output_positions[child] - output_positions[parent]
        base_length = float(np.linalg.norm(base))
        current_length = float(np.linalg.norm(current))
        if min(base_length, current_length) <= 1.0e-8:
            continue
        cosine = float(np.dot(base, current) / (base_length * current_length))
        values.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    assert values
    return np.asarray(values, dtype=np.float32)


def _run_angle_case(
    *,
    spring: bool,
    run_index: int,
    restoration: bool,
    limit_enabled: bool,
    angle_limit: float,
    drive_root: bool,
):
    world = world_types.PhysicsWorldCache()
    generation = 1200 + run_index
    armature = None
    errors = []
    max_angles = []
    try:
        armature = product_soak._armature(
            f"MC2ProductAngle_{run_index}_{int(spring)}",
            chain_count=1,
            chain_length=6,
            x_offset=0.0,
        )
        initial_basis = {
            bone.name: bone.matrix_basis.copy()
            for bone in armature.pose.bones
        }
        request = _request(
            armature,
            spring=spring,
            restoration=restoration,
            limit_enabled=limit_enabled,
            angle_limit=angle_limit,
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        owner = None
        for frame in range(1, 301):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            if drive_root:
                root = armature.pose.bones["Chain0_0"]
                root.rotation_mode = "XYZ"
                root.rotation_euler.z = 0.75 * math.sin(frame * 0.13)
                root.location.x = 0.035 * math.sin(frame * 0.09)
            bpy.context.view_layer.update()
            product_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [request],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            slot = world.solver_slots[slot_id]
            current_owner = slot.data["owner"]
            if owner is None:
                owner = current_owner
            else:
                assert current_owner is owner
            output = owner.read_output()
            step_basic = owner.prepare_step_basic_pose()
            assert np.all(np.isfinite(output.world_positions))
            errors.append(float(np.mean(_restoration_angles(
                owner.compiled.program,
                output.world_positions,
                step_basic["positions"],
            ))))
            max_angles.append(float(np.max(_angles(
                owner.compiled.program,
                output.world_positions,
                step_basic["positions"],
                step_basic["rotations"],
            ))))
            assert writeback.writeback_bone_transforms(world) == output.world_positions.shape[0]
            bpy.context.view_layer.update()
        kernel = owner.inspect()["domain"]["kernel"]
        if restoration or limit_enabled:
            assert kernel["angle_solve_count"] > 0
        else:
            assert kernel["angle_solve_count"] == 0
        return np.asarray(errors, dtype=np.float32), np.asarray(max_angles, dtype=np.float32)
    finally:
        world.omni_cache_dispose("bone_product_angle_numeric_cleanup")
        product_soak._remove_armature(armature)


def _rotate_axes(rotations) -> np.ndarray:
    result = np.empty((len(rotations), 3), dtype=np.float32)
    for index, xyzw in enumerate(rotations):
        quaternion = _quaternion(xyzw)
        result[index] = quaternion @ mathutils.Vector((0.0, 0.0, 1.0))
    return result


def _run_motion_case(*, backstop: bool, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 1300 + run_index
    armature = None
    trajectory = []
    max_distance = 0.0
    min_backstop_surface = float("inf")
    try:
        armature = product_soak._armature(
            f"MC2ProductMotion_{run_index}",
            chain_count=1,
            chain_length=6,
            x_offset=0.0,
        )
        request = _request(
            armature,
            spring=False,
            restoration=False,
            limit_enabled=False,
            angle_limit=30.0,
            motion=True,
            backstop=backstop,
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        movable = owner = None
        for frame in range(1, 451):
            product_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [request],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            slot = world.solver_slots[slot_id]
            current_owner = slot.data["owner"]
            if owner is None:
                owner = current_owner
                movable = np.asarray(owner.compiled.program.particle_attribute_flags & 1 == 0)
            else:
                assert current_owner is owner
            output = owner.read_output()
            step_basic = owner.prepare_step_basic_pose()
            motion_base = step_basic["positions"]
            motion_rotations = step_basic["rotations"]
            distances = np.linalg.norm(output.world_positions - motion_base, axis=1)
            max_distance = max(max_distance, float(np.max(distances[movable])))
            assert float(np.max(distances[movable])) <= 0.031
            if backstop:
                normals = _rotate_axes(motion_rotations)
                centers = motion_base - normals * np.float32(0.015)
                surface_distances = np.linalg.norm(output.world_positions - centers, axis=1)
                min_backstop_surface = min(
                    min_backstop_surface,
                    float(np.min(surface_distances[movable])),
                )
                assert float(np.min(surface_distances[movable])) >= 0.0095
            trajectory.append(np.array(output.world_positions, copy=True))
            assert writeback.writeback_bone_transforms(world) == output.world_positions.shape[0]
            bpy.context.view_layer.update()
        kernel = owner.inspect()["domain"]["kernel"]
        assert kernel["motion_solve_count"] > 0
        return np.asarray(trajectory), max_distance, min_backstop_surface
    finally:
        world.omni_cache_dispose("bone_product_motion_numeric_cleanup")
        product_soak._remove_armature(armature)


def test_bone_product_angle_motion_numeric_boundaries():
    for setup_index, spring in enumerate((False, True)):
        base = setup_index * 10
        restoration_drive = spring
        free_error, _free_angles = _run_angle_case(
            spring=spring,
            run_index=base,
            restoration=False,
            limit_enabled=False,
            angle_limit=30.0,
            drive_root=restoration_drive,
        )
        restored_error, _restored_angles = _run_angle_case(
            spring=spring,
            run_index=base + 1,
            restoration=True,
            limit_enabled=False,
            angle_limit=30.0,
            drive_root=restoration_drive,
        )
        _limit_30_error, limit_30_angles = _run_angle_case(
            spring=spring,
            run_index=base + 2,
            restoration=False,
            limit_enabled=True,
            angle_limit=30.0,
            drive_root=True,
        )
        _limit_15_error, limit_15_angles = _run_angle_case(
            spring=spring,
            run_index=base + 3,
            restoration=False,
            limit_enabled=True,
            angle_limit=15.0,
            drive_root=True,
        )
        free_steady = float(np.mean(free_error[-100:]))
        restored_steady = float(np.mean(restored_error[-100:]))
        restoration_delta = float(np.mean(np.abs(
            restored_error[-100:] - free_error[-100:]
        )))
        max_30 = float(np.max(limit_30_angles[-100:]))
        max_15 = float(np.max(limit_15_angles[-100:]))
        if spring:
            assert restoration_delta > 1.0, restoration_delta
        else:
            assert restored_steady < free_steady * 0.8, (
                spring, free_steady, restored_steady
            )
        assert max_30 <= 36.0, (spring, max_30)
        assert max_15 <= 29.0, (spring, max_15)
        assert max_15 <= max_30 - 5.0, (spring, max_30, max_15)
        print(
            "MC2_BONE_PRODUCT_ANGLE_RESULT",
            "bone_spring" if spring else "bone_cloth",
            "restoration=%.9f->%.9f" % (free_steady, restored_steady),
            "restoration_delta=%.9f" % restoration_delta,
            "limit30=%.6f" % max_30,
            "limit15=%.6f" % max_15,
        )

    no_backstop, no_backstop_max, _unused = _run_motion_case(
        backstop=False,
        run_index=50,
    )
    with_backstop, backstop_max, backstop_surface = _run_motion_case(
        backstop=True,
        run_index=51,
    )
    trajectory_delta = float(np.max(np.abs(no_backstop - with_backstop)))
    assert trajectory_delta > 1.0e-5
    print(
        "MC2_BONE_PRODUCT_MOTION_RESULT",
        "max_distance=%.9f/%.9f" % (no_backstop_max, backstop_max),
        "backstop_surface=%.9f" % backstop_surface,
        "trajectory_delta=%.9f" % trajectory_delta,
    )
    print("PASS test_bone_product_angle_motion_numeric_boundaries")


if __name__ == "__main__":
    test_bone_product_angle_motion_numeric_boundaries()
