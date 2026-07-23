"""MeshCloth 产品域的重力、Distance 与 Tether 数值合同。"""

from __future__ import annotations

import hashlib
import importlib
import math
import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

mixed = importlib.import_module("test_blender_mc2_product_mixed_output_soak")
bone_soak = mixed.bone_soak
nodes = mixed.nodes
parameters = mixed.parameters
product_slot = mixed.product_slot
world_types = mixed.world_types
physics_blender = mixed.physics_blender


def _request(
    world,
    mesh,
    *,
    gravity_direction,
    gravity_falloff,
    gravity=4.0,
    damping=0.0,
    distance_stiffness=0.0,
    bending_stiffness=0.0,
    tether_compression=0.35,
    angle_restoration_enabled=False,
    collision_mode=0,
):
    entries, count = nodes.physicsMC2MeshObject([mesh])
    assert count == 1 and len(entries) == 1
    entries, count = nodes.physicsMC2MeshOverride(
        entries,
        profile=parameters.make_mc2_particle_profile(
            gravity=gravity,
            gravity_direction=gravity_direction,
            gravity_falloff=gravity_falloff,
            damping=damping,
            particle_speed_limit=3.5,
            radius=0.018,
            tether_compression=tether_compression,
            distance_stiffness=distance_stiffness,
            bending_stiffness=bending_stiffness,
            angle_restoration_enabled=angle_restoration_enabled,
            angle_limit_enabled=False,
            max_distance_enabled=False,
            backstop_enabled=False,
            motion_stiffness=0.0,
            collision_mode=collision_mode,
            collision_friction=0.0,
            self_collision_mode=0,
            spring_enabled=False,
            wind_influence=0.0,
        ),
    )
    assert count == 1
    requests, report = nodes.physicsMC2MeshCollector(
        world, entries, include_implicit=False
    )
    assert len(requests) == 1 and report
    return requests[0]


def _run_once(run_index: int, *, gravity_direction, gravity_falloff):
    world = world_types.PhysicsWorldCache()
    mesh = proxy = None
    digest = hashlib.sha256()
    trajectory = []
    generation = 1800 + run_index
    try:
        physics_blender.register()
        mesh, proxy = mixed._mesh_object(f"MC2ProductMeshGravity{run_index}")
        request = _request(
            world,
            mesh,
            gravity_direction=gravity_direction,
            gravity_falloff=gravity_falloff,
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        owner = None
        for frame in range(1, 601):
            phase = frame * 0.017
            mesh.rotation_euler.z = 0.08 * math.sin(phase)
            bpy.context.view_layer.update()
            bone_soak._set_frame(world, frame, generation)
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
                table = owner.compiled.parameters.partition_parameters
                values = dict(zip(table.fields, table.values[0]))
                direction = np.asarray(gravity_direction, dtype=np.float32)
                direction /= np.linalg.norm(direction)
                np.testing.assert_allclose(
                    [
                        values["gravity_direction_x"],
                        values["gravity_direction_y"],
                        values["gravity_direction_z"],
                    ],
                    direction,
                    rtol=0.0,
                    atol=1.0e-6,
                )
                np.testing.assert_allclose(
                    values["gravity"], 4.0, rtol=0.0, atol=1.0e-6
                )
                np.testing.assert_allclose(
                    values["gravity_falloff"],
                    gravity_falloff,
                    rtol=0.0,
                    atol=1.0e-6,
                )
            else:
                assert current_owner is owner
            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            trajectory.append(np.array(output.world_positions, copy=True))
            digest.update(output.world_positions.tobytes())
        assert owner is not None
        kernel = owner.inspect()["domain"]["kernel"]
        assert kernel["compiled_external_ready"] is True
        assert owner.inspect()["domain"]["step_count"] >= 599
        return digest.hexdigest(), np.asarray(trajectory, dtype=np.float32)
    finally:
        world.omni_cache_dispose("mesh_product_gravity_cleanup")
        mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_gravity_axes_falloff() -> None:
    direction = (1.0, -0.25, -0.5)
    first_digest, first = _run_once(
        0, gravity_direction=direction, gravity_falloff=0.35
    )
    second_digest, second = _run_once(
        1, gravity_direction=direction, gravity_falloff=0.35
    )
    assert first_digest == second_digest, (first_digest, second_digest)
    np.testing.assert_array_equal(first, second)
    x_digest, x_axis = _run_once(
        2, gravity_direction=(1.0, 0.0, 0.0), gravity_falloff=0.0
    )
    z_digest, z_axis = _run_once(
        3, gravity_direction=(0.0, 0.0, -1.0), gravity_falloff=0.0
    )
    assert x_digest != z_digest
    assert not np.array_equal(x_axis, z_axis)
    print("MC2_MESH_PRODUCT_GRAVITY_DIGESTS", first_digest, x_digest, z_digest)
    print("PASS test_mesh_product_gravity_axes_falloff")


def _run_distance_tether_profile(run_index: int):
    world = world_types.PhysicsWorldCache()
    mesh = proxy = None
    generation = 2250 + run_index
    digest = hashlib.sha256()
    max_edge_ratio = 0.0
    debug_samples = []
    try:
        physics_blender.register()
        mesh, proxy = mixed._mesh_object(f"MC2ProductMeshDistance{run_index}")
        request = _request(
            world,
            mesh,
            gravity_direction=(0.0, 0.0, -1.0),
            gravity_falloff=0.0,
            gravity=7.0,
            distance_stiffness=1.0,
            tether_compression=0.35,
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        edges = np.asarray(
            [tuple(edge.vertices) for edge in mesh.data.edges], dtype=np.int32
        )
        owner = None
        base = None
        rest_lengths = None
        initial_parameter_signature = None
        for frame in range(1, 901):
            if frame == 451:
                request = _request(
                    world,
                    mesh,
                    gravity_direction=(0.0, 0.0, -1.0),
                    gravity_falloff=0.0,
                    gravity=7.0,
                    distance_stiffness=0.35,
                    tether_compression=0.35,
                )
                assert product_slot.make_mc2_product_slot_id(
                    request.setup_type, request.domain_signature
                ) == slot_id
            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = frame in (2, 900)
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
            slot = world.solver_slots[slot_id]
            current_owner = slot.data["owner"]
            if owner is None:
                owner = current_owner
                initial_parameter_signature = (
                    owner.compiled.parameters.parameter_signature
                )
                base = owner.prepare_step_basic_pose()["positions"].copy()
                rest_lengths = np.linalg.norm(
                    base[edges[:, 1]] - base[edges[:, 0]], axis=1
                )
                required_fields = {
                    "tether_compression_limit", "tether_stretch_limit",
                    "distance_velocity_attenuation", "distance_stiffness",
                }
                available_fields = set(
                    owner.compiled.parameters.partition_parameters.fields
                ) | set(owner.compiled.parameters.particle_parameters.fields)
                missing_fields = required_fields - available_fields
                assert not missing_fields, missing_fields
            else:
                assert current_owner is owner
            if frame == 451:
                assert (
                    owner.compiled.parameters.parameter_signature
                    != initial_parameter_signature
                )
            output = owner.read_output()
            fixed = (owner.compiled.program.particle_attribute_flags & 1) != 0
            np.testing.assert_allclose(
                output.world_positions[fixed], base[fixed], atol=1.0e-6
            )
            lengths = np.linalg.norm(
                output.world_positions[edges[:, 1]]
                - output.world_positions[edges[:, 0]], axis=1
            )
            edge_ratio = float(np.max(lengths / rest_lengths))
            max_edge_ratio = max(max_edge_ratio, edge_ratio)
            assert edge_ratio <= 1.55
            assert np.all(np.isfinite(output.world_positions))
            digest.update(output.world_positions.tobytes())
            if capture:
                owner.end_constraint_debug()
                debug = owner.read_constraint_debug_state()
                distance = debug["distance_results"]
                tether = debug["tether_results"]
                distance_valid = np.asarray(distance["valid"][0], dtype=bool)
                tether_valid = np.asarray(tether["valid"], dtype=bool)
                assert np.any(distance_valid) and np.any(tether_valid)
                np.testing.assert_array_less(
                    np.asarray(distance["rests"])[0][distance_valid] * 0.0,
                    np.asarray(distance["rests"])[0][distance_valid] + 1.0e-7,
                )
                tether_lengths = np.asarray(tether["lengths"])[tether_valid]
                tether_rests = np.asarray(tether["rests"])[tether_valid]
                tether_ratios = tether_lengths / np.maximum(tether_rests, 1.0e-8)
                assert np.all(tether_ratios >= 0.15)
                assert np.all(tether_ratios <= 1.35)
                debug_samples.append((int(np.count_nonzero(distance_valid)), int(np.count_nonzero(tether_valid))))
        assert owner is not None
        return digest.hexdigest(), max_edge_ratio, tuple(debug_samples)
    finally:
        world.omni_cache_dispose("mesh_product_distance_tether_cleanup")
        mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_distance_tether_data_path_deterministic() -> None:
    first = _run_distance_tether_profile(0)
    second = _run_distance_tether_profile(1)
    assert first == second, (first, second)
    assert first[1] <= 1.55
    print("MC2_MESH_PRODUCT_DISTANCE_TETHER_DIGEST", first[0])
    print("MC2_MESH_PRODUCT_DISTANCE_TETHER_DEBUG", first[2])
    print("PASS test_mesh_product_distance_tether_data_path_deterministic")


def _run_distance_tether_numeric(
    *,
    stiffness: float,
    direction,
    compression: float,
    gravity: float,
    damping: float,
    run_index: int,
):
    world = world_types.PhysicsWorldCache()
    mesh = proxy = None
    generation = 2400 + run_index
    digest = hashlib.sha256()
    trajectory = []
    samples = []
    capture_frames = {2, 30, 100, 300, 600}
    try:
        physics_blender.register()
        mesh, proxy = mixed._mesh_object(f"MC2ProductMeshDistanceNumeric{run_index}")
        request = _request(
            world,
            mesh,
            gravity_direction=direction,
            gravity_falloff=0.0,
            gravity=gravity,
            damping=damping,
            distance_stiffness=stiffness,
            tether_compression=compression,
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        owner = None
        base = None
        for frame in range(1, 601):
            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = frame in capture_frames
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
            slot = world.solver_slots[slot_id]
            current_owner = slot.data["owner"]
            if owner is None:
                owner = current_owner
                base = owner.prepare_step_basic_pose()["positions"].copy()
                partition = owner.compiled.parameters.partition_parameters
                values = dict(zip(partition.fields, partition.values[0]))
                np.testing.assert_allclose(
                    values["tether_compression_limit"],
                    compression,
                    rtol=0.0,
                    atol=1.0e-7,
                )
                np.testing.assert_allclose(
                    values["tether_stretch_limit"],
                    0.03,
                    rtol=0.0,
                    atol=1.0e-7,
                )
                np.testing.assert_allclose(
                    values["distance_velocity_attenuation"],
                    0.3,
                    rtol=0.0,
                    atol=1.0e-7,
                )
                particle = owner.compiled.parameters.particle_parameters
                distance_column = particle.fields.index("distance_stiffness")
                np.testing.assert_allclose(
                    particle.values[:, distance_column],
                    stiffness,
                    rtol=0.0,
                    atol=1.0e-7,
                )
            else:
                assert current_owner is owner

            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            fixed = (owner.compiled.program.particle_attribute_flags & 1) != 0
            np.testing.assert_allclose(
                output.world_positions[fixed], base[fixed], atol=1.0e-6
            )
            trajectory.append(np.array(output.world_positions, copy=True))
            digest.update(output.world_positions.tobytes())

            if capture:
                owner.end_constraint_debug()
                debug = owner.read_constraint_debug_state()
                distance = debug["distance_results"]
                distance_valid = np.asarray(distance["valid"], dtype=bool)
                distance_rests = np.asarray(distance["rests"], dtype=np.float32)
                distance_hits = np.asarray(distance["hit"], dtype=bool)
                distance_corrections = np.asarray(
                    distance["corrections"], dtype=np.float32
                )
                if stiffness > 0.0:
                    assert np.any(distance_valid)
                    assert np.all(distance_rests[distance_valid] > 0.0)
                else:
                    assert not np.any(distance_hits & distance_valid)

                tether = debug["tether_results"]
                tether_valid = np.asarray(tether["valid"], dtype=bool)
                tether_rests = np.asarray(tether["rests"], dtype=np.float32)
                tether_minimums = np.asarray(
                    tether["minimums"], dtype=np.float32
                )
                tether_maximums = np.asarray(
                    tether["maximums"], dtype=np.float32
                )
                tether_branches = np.asarray(tether["branches"], dtype=np.int8)
                tether_hits = np.asarray(tether["hit"], dtype=bool)
                tether_corrections = np.asarray(
                    tether["corrections"], dtype=np.float32
                )
                assert np.any(tether_valid)
                assert np.all(tether_rests[tether_valid] > 0.0)
                np.testing.assert_allclose(
                    tether_minimums[tether_valid],
                    tether_rests[tether_valid] * (1.0 - compression),
                    rtol=0.0,
                    atol=1.0e-6,
                )
                np.testing.assert_allclose(
                    tether_maximums[tether_valid],
                    tether_rests[tether_valid] * 1.03,
                    rtol=0.0,
                    atol=1.0e-6,
                )
                sample = (
                    int(np.count_nonzero(distance_hits & distance_valid)),
                    (
                        float(np.max(np.linalg.norm(
                            distance_corrections[distance_valid], axis=1
                        )))
                        if np.any(distance_valid)
                        else 0.0
                    ),
                    int(np.count_nonzero(
                        tether_hits & tether_valid & (tether_branches > 0)
                    )),
                    int(np.count_nonzero(
                        tether_hits & tether_valid & (tether_branches < 0)
                    )),
                    float(np.max(np.linalg.norm(
                        tether_corrections[tether_valid], axis=1
                    ))),
                )
                assert np.all(np.isfinite(sample))
                samples.append(sample)
                for values in (
                    distance_rests,
                    tether_rests,
                    tether_minimums,
                    tether_maximums,
                    tether_branches,
                ):
                    digest.update(values.tobytes())

        assert owner is not None and len(samples) == len(capture_frames)
        return (
            digest.hexdigest(),
            np.asarray(trajectory, dtype=np.float32),
            tuple(samples),
        )
    finally:
        world.omni_cache_dispose("mesh_product_distance_numeric_cleanup")
        mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_distance_tether_numeric_deterministic() -> None:
    common = {
        "direction": (0.0, 0.0, -1.0),
        "compression": 0.4,
        "gravity": 7.0,
        "damping": 0.0,
    }
    soft = _run_distance_tether_numeric(
        stiffness=0.0, run_index=0, **common
    )
    soft_repeat = _run_distance_tether_numeric(
        stiffness=0.0, run_index=1, **common
    )
    stiff = _run_distance_tether_numeric(
        stiffness=1.0, run_index=2, **common
    )
    stiff_repeat = _run_distance_tether_numeric(
        stiffness=1.0, run_index=3, **common
    )
    assert soft[0] == soft_repeat[0] and soft[2] == soft_repeat[2]
    np.testing.assert_array_equal(soft[1], soft_repeat[1])
    assert stiff[0] == stiff_repeat[0] and stiff[2] == stiff_repeat[2]
    np.testing.assert_array_equal(stiff[1], stiff_repeat[1])
    response_delta = float(np.max(np.abs(soft[1] - stiff[1])))
    assert response_delta > 1.0e-5, response_delta
    assert max(sample[0] for sample in stiff[2]) > 0
    assert max(sample[1] for sample in stiff[2]) > 0.0
    assert max(sample[2] for sample in stiff[2]) > 0
    assert max(sample[4] for sample in stiff[2]) > 0.0

    compression = {
        "stiffness": 0.0,
        "direction": (0.0, -1.0, 0.0),
        "compression": 0.65,
        "gravity": 0.5,
        "damping": 0.5,
    }
    compressed = _run_distance_tether_numeric(run_index=4, **compression)
    compressed_repeat = _run_distance_tether_numeric(run_index=5, **compression)
    assert compressed[0] == compressed_repeat[0]
    assert compressed[2] == compressed_repeat[2]
    np.testing.assert_array_equal(compressed[1], compressed_repeat[1])
    assert max(sample[3] for sample in compressed[2]) > 0
    assert max(sample[4] for sample in compressed[2]) > 0.0
    print(
        "MC2_MESH_PRODUCT_DISTANCE_TETHER_NUMERIC",
        soft[0],
        stiff[0],
        compressed[0],
        response_delta,
        stiff[2],
        compressed[2],
    )
    print("PASS test_mesh_product_distance_tether_numeric_deterministic")


if __name__ == "__main__":
    test_mesh_product_gravity_axes_falloff()
    test_mesh_product_distance_tether_data_path_deterministic()
    test_mesh_product_distance_tether_numeric_deterministic()
