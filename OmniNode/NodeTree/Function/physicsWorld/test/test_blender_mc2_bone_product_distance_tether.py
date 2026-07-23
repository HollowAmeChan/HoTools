"""BoneCloth/BoneSpring 产品域的 Distance/Tether 数值门禁。"""

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


def _request(armature, *, spring: bool, distance_stiffness: float):
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0 if spring else 5.0,
        gravity_direction=(0.0, 0.0, -1.0),
        damping=0.02,
        stabilization_time_after_reset=0.0,
        particle_speed_limit=6.0,
        radius=0.02,
        tether_compression=0.35,
        distance_stiffness=distance_stiffness,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        max_distance_enabled=False,
        backstop_enabled=False,
        collision_mode=0,
        self_collision_mode=0,
        spring_enabled=False,
        wind_influence=0.0,
    )
    if spring:
        requests, _report = nodes.physicsMC2BoneSpringTask(
            [{
                "armature": armature,
                "root_bone": "Chain0_0",
                "bones": tuple(f"Chain0_{depth}" for depth in range(6)),
            }],
            profile=profile,
            teleport_mode=0,
        )
    else:
        requests, _report = nodes.physicsMC2BoneClothTask(
            [{"armature": armature, "bone": "Parent"}],
            profile=profile,
            connection_mode=0,
            cloth_mass=0.4,
            teleport_mode=0,
        )
    assert len(requests) == 1
    return requests[0]


def _run_profile(*, spring: bool, stiffness: float, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 3100 + run_index
    armature = None
    digest = hashlib.sha256()
    trajectory = []
    samples = []
    try:
        armature = product_soak._armature(
            f"MC2ProductDistanceTether_{run_index}_{int(spring)}",
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
            distance_stiffness=stiffness,
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        owner = None
        for frame in range(1, 601):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            driver = armature.pose.bones["Chain0_0" if spring else "Parent"]
            driver.rotation_mode = "XYZ"
            drive_scale = 0.35 if spring else 0.08
            drive_frequency = 0.22 if spring else 0.075
            driver.rotation_euler.z = (
                (1.1 if spring else 0.8) * math.sin(frame * drive_frequency)
            )
            driver.location.x = drive_scale * math.sin(frame * drive_frequency)
            bpy.context.view_layer.update()
            product_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = frame in (2, 300, 600)
            if capture:
                assert owner is not None
                owner.begin_constraint_debug(12)
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
            else:
                assert current_owner is owner
            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            trajectory.append(np.array(output.world_positions, copy=True))
            digest.update(output.world_positions.tobytes())
            if capture:
                owner.end_constraint_debug()
                debug = owner.read_constraint_debug_state()
                distance = debug["distance_results"]
                distance_valid = np.asarray(
                    distance["valid"], dtype=np.uint8
                ).astype(bool)
                distance_origins = np.asarray(
                    distance["origins"], dtype=np.float32
                )
                distance_targets = np.asarray(
                    distance["target_origins"], dtype=np.float32
                )
                distance_lengths = np.asarray(
                    distance["lengths"], dtype=np.float32
                )
                distance_rests = np.asarray(
                    distance["rests"], dtype=np.float32
                )
                distance_stiffnesses = np.asarray(
                    distance["stiffnesses"], dtype=np.float32
                )
                distance_hits = np.asarray(
                    distance["hit"], dtype=np.uint8
                ).astype(bool)
                distance_corrections = np.asarray(
                    distance["corrections"], dtype=np.float32
                )
                expected_lengths = np.linalg.norm(
                    distance_origins - distance_targets,
                    axis=2,
                )
                if np.any(distance_valid):
                    np.testing.assert_allclose(
                        distance_lengths[distance_valid],
                        expected_lengths[distance_valid],
                        rtol=0.0,
                        atol=1.0e-6,
                    )
                    assert np.all(distance_rests[distance_valid] > 0.0)
                expected_stiffness = 0.5 if spring else stiffness
                if expected_stiffness > 0.0:
                    assert np.any(distance_valid)
                    np.testing.assert_allclose(
                        distance_stiffnesses[distance_valid],
                        expected_stiffness,
                        rtol=0.0,
                        atol=1.0e-7,
                    )
                else:
                    np.testing.assert_allclose(
                        distance_stiffnesses[distance_valid],
                        0.0,
                        rtol=0.0,
                        atol=1.0e-7,
                    )
                    assert not np.any(distance_hits & distance_valid)
                    np.testing.assert_allclose(
                        distance_corrections[distance_valid],
                        0.0,
                        rtol=0.0,
                        atol=1.0e-7,
                    )

                tether = debug["tether_results"]
                tether_valid = np.asarray(
                    tether["valid"], dtype=np.uint8
                ).astype(bool)
                assert np.any(tether_valid)
                tether_origins = np.asarray(tether["origins"], dtype=np.float32)
                root_origins = np.asarray(
                    tether["root_origins"], dtype=np.float32
                )
                tether_lengths = np.asarray(tether["lengths"], dtype=np.float32)
                tether_rests = np.asarray(tether["rests"], dtype=np.float32)
                tether_minimums = np.asarray(tether["minimums"], dtype=np.float32)
                tether_maximums = np.asarray(tether["maximums"], dtype=np.float32)
                tether_hits = np.asarray(
                    tether["hit"], dtype=np.uint8
                ).astype(bool)
                tether_corrections = np.asarray(
                    tether["corrections"], dtype=np.float32
                )
                np.testing.assert_allclose(
                    tether_lengths[tether_valid],
                    np.linalg.norm(
                        tether_origins - root_origins,
                        axis=1,
                    )[tether_valid],
                    rtol=0.0,
                    atol=1.0e-6,
                )
                assert np.all(tether_rests[tether_valid] > 0.0)
                assert np.all(
                    tether_minimums[tether_valid] <= tether_rests[tether_valid]
                )
                assert np.all(
                    tether_rests[tether_valid] <= tether_maximums[tether_valid]
                )
                sample = (
                    int(np.count_nonzero(distance_valid)),
                    int(np.count_nonzero(distance_hits & distance_valid)),
                    (
                        float(np.max(np.linalg.norm(
                            distance_corrections[distance_valid], axis=1
                        )))
                        if np.any(distance_valid)
                        else 0.0
                    ),
                    int(np.count_nonzero(tether_valid)),
                    int(np.count_nonzero(tether_hits)),
                    float(np.max(np.linalg.norm(
                        tether_corrections[tether_valid], axis=1
                    ))),
                    (
                        float(np.max(distance_stiffnesses[distance_valid]))
                        if np.any(distance_valid)
                        else 0.0
                    ),
                )
                assert np.all(np.isfinite(sample))
                samples.append(sample)
                for values in (
                    distance_lengths,
                    distance_rests,
                    distance_stiffnesses,
                    tether_lengths,
                    tether_rests,
                    tether_minimums,
                    tether_maximums,
                ):
                    digest.update(values.tobytes())
            assert writeback.writeback_bone_transforms(world) == output.world_positions.shape[0]
            bpy.context.view_layer.update()
        assert owner is not None and len(samples) == 3
        return digest.hexdigest(), np.asarray(trajectory, dtype=np.float32), tuple(samples)
    finally:
        world.omni_cache_dispose("bone_product_distance_tether_cleanup")
        product_soak._remove_armature(armature)


def test_bone_product_distance_tether_numeric_deterministic():
    results = []
    for spring, base_index in ((False, 0), (True, 4)):
        soft_first = _run_profile(
            spring=spring,
            stiffness=0.0,
            run_index=base_index,
        )
        soft_second = _run_profile(
            spring=spring,
            stiffness=0.0,
            run_index=base_index + 1,
        )
        stiff_first = _run_profile(
            spring=spring,
            stiffness=1.0,
            run_index=base_index + 2,
        )
        stiff_second = _run_profile(
            spring=spring,
            stiffness=1.0,
            run_index=base_index + 3,
        )
        assert soft_first[0] == soft_second[0]
        assert soft_first[2] == soft_second[2]
        np.testing.assert_array_equal(soft_first[1], soft_second[1])
        assert stiff_first[0] == stiff_second[0]
        assert stiff_first[2] == stiff_second[2]
        np.testing.assert_array_equal(stiff_first[1], stiff_second[1])
        response_delta = float(np.max(np.abs(soft_first[1] - stiff_first[1])))
        if spring:
            assert soft_first[0] == stiff_first[0]
            assert soft_first[2] == stiff_first[2]
            np.testing.assert_array_equal(soft_first[1], stiff_first[1])
            assert response_delta == 0.0
        else:
            assert response_delta > 1.0e-5, response_delta
        assert max(sample[0] for sample in stiff_first[2]) > 0
        assert max(sample[3] for sample in stiff_first[2]) > 0
        if spring:
            np.testing.assert_allclose(
                [sample[6] for sample in soft_first[2]],
                0.5,
                rtol=0.0,
                atol=1.0e-7,
            )
        else:
            assert max(sample[1] for sample in stiff_first[2]) > 0
            assert max(sample[2] for sample in stiff_first[2]) > 0.0
            assert max(sample[4] for sample in stiff_first[2]) > 0
            assert max(sample[5] for sample in stiff_first[2]) > 0.0
            assert max(sample[6] for sample in soft_first[2]) < max(
                sample[6] for sample in stiff_first[2]
            )
        results.append((
            "bone_spring" if spring else "bone_cloth",
            soft_first[0],
            stiff_first[0],
            response_delta,
            stiff_first[2],
        ))
    print("MC2_BONE_PRODUCT_DISTANCE_TETHER", results)
    print("PASS test_bone_product_distance_tether_numeric_deterministic")


if __name__ == "__main__":
    test_bone_product_distance_tether_numeric_deterministic()
