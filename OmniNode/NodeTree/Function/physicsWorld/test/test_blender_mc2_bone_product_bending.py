"""Bone 产品域的 Bending 数值响应与 BoneSpring 限制门禁。"""

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

import test_blender_mc2_bone_product_constraint_soak as product_soak


nodes = product_soak.nodes
parameters = product_soak.parameters
product_slot = product_soak.product_slot
world_types = product_soak.world_types
writeback = product_soak.writeback


def _profile(*, bending_stiffness: float):
    return parameters.make_mc2_particle_profile(
        gravity=4.0,
        gravity_direction=(0.0, 0.0, -1.0),
        damping=0.03,
        stabilization_time_after_reset=0.0,
        particle_speed_limit=6.0,
        radius=0.02,
        tether_compression=0.35,
        distance_stiffness=0.85,
        bending_stiffness=bending_stiffness,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        max_distance_enabled=False,
        backstop_enabled=False,
        collision_mode=0,
        self_collision_mode=0,
        spring_enabled=False,
        wind_influence=0.0,
    )


def _cloth_request(armature, *, bending_stiffness: float):
    requests, _report = nodes.physicsMC2BoneClothTask(
        [{"armature": armature, "bone": "Parent"}],
        profile=_profile(bending_stiffness=bending_stiffness),
        connection_mode=1,
        cloth_mass=0.4,
        teleport_mode=0,
    )
    assert len(requests) == 1
    return requests[0]


def _spring_request(armature):
    requests, _report = nodes.physicsMC2BoneSpringTask(
        [{
            "armature": armature,
            "root_bone": "Chain0_0",
            "bones": tuple(f"Chain0_{depth}" for depth in range(6)),
        }],
        profile=_profile(bending_stiffness=1.0),
        teleport_mode=0,
    )
    assert len(requests) == 1
    return requests[0]


def _run_cloth(*, stiffness: float, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 3400 + run_index
    armature = None
    owner = None
    fixed = None
    digest = hashlib.sha256()
    trajectory = []
    samples = []
    try:
        armature = product_soak._armature(
            f"MC2ProductBending_{run_index}",
            chain_count=2,
            chain_length=6,
            x_offset=0.0,
            chain_spacing=0.055,
            bone_spacing=0.04,
        )
        initial_basis = {
            bone.name: bone.matrix_basis.copy()
            for bone in armature.pose.bones
        }
        request = _cloth_request(
            armature,
            bending_stiffness=stiffness,
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        for frame in range(1, 601):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            driven = armature.pose.bones["Chain0_0"]
            driven.rotation_mode = "XYZ"
            driven.rotation_euler.x = 0.65 * math.sin(frame * 0.13)
            driven.rotation_euler.z = 0.45 * math.sin(frame * 0.09)
            driven.location.z = 0.05 * math.sin(frame * 0.11)
            bpy.context.view_layer.update()
            product_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = frame in (2, 300, 600)
            if capture:
                assert owner is not None
                owner.begin_constraint_debug(16)
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [request],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            current_owner = world.solver_slots[slot_id].data["owner"]
            if owner is None:
                owner = current_owner
                assert "bending" in {
                    table.kind for table in owner.compiled.program.constraint_tables
                }
                fixed = (
                    owner.compiled.program.particle_attribute_flags & 1
                ) != 0
                assert np.any(fixed)
            else:
                assert current_owner is owner
            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            trajectory.append(np.array(output.world_positions, copy=True))
            digest.update(output.world_positions.tobytes())
            if capture:
                owner.end_constraint_debug()
                bending = owner.read_constraint_debug_state()["bending_results"]
                valid = np.asarray(
                    bending["valid"], dtype=np.uint8
                ).astype(bool)
                hits = np.asarray(bending["hit"], dtype=np.uint8).astype(bool)
                currents = np.asarray(bending["currents"], dtype=np.float32)
                rests = np.asarray(bending["rests"], dtype=np.float32)
                stiffnesses = np.asarray(
                    bending["stiffnesses"], dtype=np.float32
                )
                corrections = np.asarray(
                    bending["corrections"], dtype=np.float32
                )
                kinds = np.asarray(bending["kinds"], dtype=np.int8)
                assert np.all(np.isfinite(currents[valid]))
                assert np.all(np.isfinite(rests[valid]))
                if stiffness == 0.0:
                    np.testing.assert_allclose(
                        stiffnesses[valid], 0.0, rtol=0.0, atol=1.0e-7
                    )
                    assert not np.any(hits & valid)
                    np.testing.assert_allclose(
                        corrections[valid], 0.0, rtol=0.0, atol=1.0e-7
                    )
                else:
                    assert np.any(valid)
                    np.testing.assert_allclose(
                        stiffnesses[valid], stiffness, rtol=0.0, atol=1.0e-7
                    )
                sample = (
                    int(np.count_nonzero(valid)),
                    int(np.count_nonzero(hits & valid)),
                    float(np.max(np.linalg.norm(
                        corrections[valid].reshape((-1, 12)), axis=1
                    ))) if np.any(valid) else 0.0,
                    tuple(sorted(set(int(value) for value in kinds[valid]))),
                )
                samples.append(sample)
                digest.update(currents.tobytes())
                digest.update(rests.tobytes())
                digest.update(stiffnesses.tobytes())
            assert writeback.writeback_bone_transforms(world) == output.world_positions.shape[0]
            bpy.context.view_layer.update()
        assert owner is not None and len(samples) == 3
        return digest.hexdigest(), np.asarray(trajectory, dtype=np.float32), tuple(samples)
    finally:
        world.omni_cache_dispose("bone_product_bending_cleanup")
        product_soak._remove_armature(armature)


def _run_spring_absence(run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 3500 + run_index
    armature = None
    owner = None
    digest = hashlib.sha256()
    try:
        armature = product_soak._armature(
            f"MC2ProductSpringNoBending_{run_index}",
            chain_count=1,
            chain_length=6,
            x_offset=0.0,
        )
        request = _spring_request(armature)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        for frame in range(1, 601):
            root = armature.pose.bones["Chain0_0"]
            root.rotation_mode = "XYZ"
            root.rotation_euler.z = 0.7 * math.sin(frame * 0.12)
            bpy.context.view_layer.update()
            product_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = frame in (2, 600)
            if capture:
                assert owner is not None
                owner.begin_constraint_debug(16)
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [request],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            current_owner = world.solver_slots[slot_id].data["owner"]
            if owner is None:
                owner = current_owner
                assert "bending" not in {
                    table.kind for table in owner.compiled.program.constraint_tables
                }
            else:
                assert current_owner is owner
            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            digest.update(output.world_positions.tobytes())
            if capture:
                owner.end_constraint_debug()
                bending = owner.read_constraint_debug_state()["bending_results"]
                assert not np.any(np.asarray(bending["valid"], dtype=np.uint8))
            assert writeback.writeback_bone_transforms(world) == output.world_positions.shape[0]
            bpy.context.view_layer.update()
        assert owner is not None
        assert owner.inspect()["domain"]["kernel"].get(
            "bending_solve_count", 0
        ) == 0
        return digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_product_spring_bending_absence_cleanup")
        product_soak._remove_armature(armature)


def _run_cloth_fixed_static(run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 3600 + run_index
    armature = None
    owner = None
    fixed = None
    fixed_reference = None
    max_fixed_drift = 0.0
    digest = hashlib.sha256()
    try:
        armature = product_soak._armature(
            f"MC2ProductBendingFixed_{run_index}",
            chain_count=2,
            chain_length=6,
            x_offset=0.0,
            chain_spacing=0.055,
            bone_spacing=0.04,
        )
        initial_basis = {
            bone.name: bone.matrix_basis.copy()
            for bone in armature.pose.bones
        }
        request = _cloth_request(armature, bending_stiffness=1.0)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        for frame in range(1, 601):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
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
            current_owner = world.solver_slots[slot_id].data["owner"]
            if owner is None:
                owner = current_owner
                fixed = (
                    owner.compiled.program.particle_attribute_flags & 1
                ) != 0
                assert np.any(fixed)
            else:
                assert current_owner is owner
            output = owner.read_output()
            if fixed_reference is None:
                fixed_reference = np.array(
                    output.world_positions[fixed], copy=True
                )
            fixed_drift = float(np.max(np.abs(
                output.world_positions[fixed] - fixed_reference
            )))
            max_fixed_drift = max(max_fixed_drift, fixed_drift)
            assert max_fixed_drift <= 1.0e-4, (
                frame,
                max_fixed_drift,
            )
            digest.update(output.world_positions.tobytes())
            assert writeback.writeback_bone_transforms(world) == output.world_positions.shape[0]
            bpy.context.view_layer.update()
        assert owner is not None
        return digest.hexdigest(), max_fixed_drift
    finally:
        world.omni_cache_dispose("bone_product_bending_fixed_cleanup")
        product_soak._remove_armature(armature)


def test_bone_product_bending_numeric_deterministic():
    soft_first = _run_cloth(stiffness=0.0, run_index=0)
    soft_second = _run_cloth(stiffness=0.0, run_index=1)
    stiff_first = _run_cloth(stiffness=1.0, run_index=2)
    stiff_second = _run_cloth(stiffness=1.0, run_index=3)
    assert soft_first[0] == soft_second[0]
    assert soft_first[2] == soft_second[2]
    np.testing.assert_array_equal(soft_first[1], soft_second[1])
    assert stiff_first[0] == stiff_second[0]
    assert stiff_first[2] == stiff_second[2]
    np.testing.assert_array_equal(stiff_first[1], stiff_second[1])
    response_delta = float(np.max(np.abs(soft_first[1] - stiff_first[1])))
    assert response_delta > 1.0e-5, response_delta
    assert max(sample[0] for sample in stiff_first[2]) > 0
    assert max(sample[1] for sample in stiff_first[2]) > 0
    assert max(sample[2] for sample in stiff_first[2]) > 0.0

    spring_first = _run_spring_absence(10)
    spring_second = _run_spring_absence(11)
    assert spring_first == spring_second
    fixed_first = _run_cloth_fixed_static(20)
    fixed_second = _run_cloth_fixed_static(21)
    assert fixed_first == fixed_second
    print(
        "MC2_BONE_PRODUCT_BENDING",
        soft_first[0],
        stiff_first[0],
        response_delta,
        stiff_first[2],
        spring_first,
        fixed_first,
    )
    print("PASS test_bone_product_bending_numeric_deterministic")


if __name__ == "__main__":
    test_bone_product_bending_numeric_deterministic()
