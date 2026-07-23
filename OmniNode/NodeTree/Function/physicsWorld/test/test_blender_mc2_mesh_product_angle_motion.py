"""MeshCloth 产品域 Angle Restoration / Limit 数值合同。"""

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
    attenuation,
    falloff,
    enabled=True,
    gravity=4.0,
    damping=0.05,
    stiffness=0.65,
    limit_enabled=False,
    angle_limit=30.0,
    angle_limit_stiffness=1.0,
    distance_stiffness=0.0,
):
    entries, count = nodes.physicsMC2MeshObject([mesh])
    assert count == 1 and len(entries) == 1
    entries, count = nodes.physicsMC2MeshOverride(
        entries,
        profile=parameters.make_mc2_particle_profile(
            gravity=gravity,
            gravity_direction=(0.0, 0.0, -1.0),
            gravity_falloff=0.0,
            damping=damping,
            particle_speed_limit=3.5,
            radius=0.018,
            tether_compression=0.35,
            distance_stiffness=distance_stiffness,
            bending_stiffness=0.0,
            angle_restoration_enabled=enabled,
            angle_restoration_stiffness=stiffness,
            angle_restoration_velocity_attenuation=attenuation,
            angle_restoration_gravity_falloff=falloff,
            angle_limit_enabled=limit_enabled,
            angle_limit=angle_limit,
            angle_limit_stiffness=angle_limit_stiffness,
            max_distance_enabled=False,
            backstop_enabled=False,
            motion_stiffness=0.0,
            collision_mode=0,
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


def _run_rest_debug(run_index: int):
    world = world_types.PhysicsWorldCache()
    mesh = proxy = None
    generation = 1950 + run_index
    digest = hashlib.sha256()
    max_error = 0.0
    try:
        physics_blender.register()
        mesh, proxy = mixed._mesh_object(f"MC2ProductMeshAngleRest{run_index}")
        request = _request(
            world,
            mesh,
            attenuation=1.0,
            falloff=0.0,
            gravity=0.0,
            damping=0.0,
            stiffness=0.2,
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        owner = None
        base = None
        initial_parameter_signature = None
        for frame in range(1, 901):
            if frame == 451:
                request = _request(
                    world,
                    mesh,
                    attenuation=1.0,
                    falloff=0.0,
                    gravity=0.0,
                    damping=0.0,
                    stiffness=0.85,
                )
                assert product_slot.make_mc2_product_slot_id(
                    request.setup_type, request.domain_signature
                ) == slot_id
            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture_constraints = frame in (2, 900)
            if capture_constraints:
                assert owner is not None
                owner.begin_constraint_debug(1)
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
                initial_parameter_signature = (
                    owner.compiled.parameters.parameter_signature
                )
            else:
                assert current_owner is owner
            if frame == 451:
                assert (
                    owner.compiled.parameters.parameter_signature
                    != initial_parameter_signature
                )
            output = owner.read_output()
            error = float(np.max(np.linalg.norm(output.world_positions - base, axis=1)))
            max_error = max(max_error, error)
            assert error <= 1.0e-7, (frame, error)
            if capture_constraints:
                owner.end_constraint_debug()
                raw = owner.read_constraint_debug_state()
                angle = raw["angle_results"]
                valid = np.asarray(angle["valid"][1], dtype=np.uint8).astype(bool)
                assert np.any(valid)
                children = np.asarray(angle["children"][1], dtype=np.int32)[valid]
                parents = np.asarray(angle["parents"][1], dtype=np.int32)[valid]
                step_basic = owner.prepare_step_basic_pose()["positions"]
                targets = np.asarray(angle["targets"][1], dtype=np.float32)[valid]
                vectors = np.asarray(angle["target_vectors"][1], dtype=np.float32)[valid]
                np.testing.assert_allclose(
                    vectors,
                    step_basic[children] - step_basic[parents],
                    rtol=0.0,
                    atol=1.0e-7,
                )
                np.testing.assert_allclose(
                    targets,
                    output.world_positions[parents] + vectors,
                    rtol=0.0,
                    atol=1.0e-7,
                )
                digest.update(vectors.tobytes())
                digest.update(targets.tobytes())
        assert owner is not None
        assert owner.inspect()["domain"]["kernel"]["angle_solve_count"] > 0
        return digest.hexdigest(), max_error
    finally:
        world.omni_cache_dispose("mesh_product_angle_rest_cleanup")
        mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def _run_response(run_index: int, *, attenuation: float, falloff: float):
    world = world_types.PhysicsWorldCache()
    mesh = proxy = None
    generation = 1900 + run_index
    response = []
    movement = []
    digest = hashlib.sha256()
    previous = None
    try:
        physics_blender.register()
        mesh, proxy = mixed._mesh_object(f"MC2ProductMeshAngle{run_index}")
        request = _request(
            world,
            mesh,
            attenuation=attenuation,
            falloff=falloff,
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        owner = None
        for frame in range(1, 601):
            phase = frame * 0.021
            mesh.rotation_euler.z = 0.65 * math.sin(phase)
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
                np.testing.assert_allclose(
                    values["angle_restoration_velocity_attenuation"],
                    attenuation,
                    rtol=0.0,
                    atol=1.0e-6,
                )
                np.testing.assert_allclose(
                    values["angle_restoration_gravity_falloff"],
                    falloff,
                    rtol=0.0,
                    atol=1.0e-6,
                )
            else:
                assert current_owner is owner
            output = owner.read_output()
            base = owner.prepare_step_basic_pose()["positions"]
            delta = np.linalg.norm(output.world_positions - base, axis=1)
            movable = (owner.compiled.program.particle_attribute_flags & 1) == 0
            value = float(np.mean(delta[movable]))
            response.append(value)
            movement.append(
                0.0
                if previous is None
                else float(np.mean(np.linalg.norm(
                    output.world_positions - previous, axis=1
                )[movable]))
            )
            previous = np.array(output.world_positions, copy=True)
            digest.update(output.world_positions.tobytes())
        assert owner is not None
        assert owner.inspect()["domain"]["kernel"]["angle_solve_count"] > 0
        return {
            "response": np.asarray(response, dtype=np.float32),
            "movement": np.asarray(movement, dtype=np.float32),
            "digest": digest.hexdigest(),
        }
    finally:
        world.omni_cache_dispose("mesh_product_angle_cleanup")
        mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_angle_restoration_response() -> None:
    low = _run_response(0, attenuation=0.0, falloff=0.0)
    high = _run_response(1, attenuation=1.0, falloff=0.0)
    np.testing.assert_allclose(low["response"][0], high["response"][0], atol=1.0e-6)
    assert high["response"][2] >= low["response"][2] + 1.0e-5
    assert float(np.sum(high["movement"][1:30])) >= (
        float(np.sum(low["movement"][1:30])) * 1.05
    )
    print("MC2_MESH_PRODUCT_ANGLE_RESPONSE_DIGESTS", low["digest"], high["digest"])
    print("PASS test_mesh_product_angle_restoration_response")


def test_mesh_product_angle_restoration_falloff() -> None:
    low = _run_response(2, attenuation=1.0, falloff=0.0)
    high = _run_response(3, attenuation=1.0, falloff=1.0)
    assert low["digest"] != high["digest"]
    assert float(np.mean(high["response"][-100:])) != float(
        np.mean(low["response"][-100:])
    )
    print("MC2_MESH_PRODUCT_ANGLE_FALLOFF_DIGESTS", low["digest"], high["digest"])
    print("PASS test_mesh_product_angle_restoration_falloff")


def test_mesh_product_angle_restoration_rest_debug() -> None:
    first = _run_rest_debug(0)
    second = _run_rest_debug(1)
    assert first == second, (first, second)
    assert first[1] <= 1.0e-7
    print("MC2_MESH_PRODUCT_ANGLE_REST_DIGEST", first[0])
    print("MC2_MESH_PRODUCT_ANGLE_REST_MAX_ERROR", first[1])
    print("PASS test_mesh_product_angle_restoration_rest_debug")


def _limit_angles(output, angle_debug) -> np.ndarray:
    valid = np.asarray(angle_debug["valid"][0], dtype=np.uint8).astype(bool)
    children = np.asarray(angle_debug["children"][0], dtype=np.int32)[valid]
    parents = np.asarray(angle_debug["parents"][0], dtype=np.int32)[valid]
    targets = np.asarray(angle_debug["target_vectors"][0], dtype=np.float32)[valid]
    values = []
    for child, parent, target in zip(children, parents, targets):
        if child < 0 or parent < 0 or child == parent:
            continue
        current = output.world_positions[child] - output.world_positions[parent]
        target_length = float(np.linalg.norm(target))
        current_length = float(np.linalg.norm(current))
        if min(target_length, current_length) <= 1.0e-8:
            continue
        cosine = float(np.dot(target, current) / (target_length * current_length))
        values.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    assert values
    return np.asarray(values, dtype=np.float32)


def _run_angle_limit_transition(run_index: int):
    world = world_types.PhysicsWorldCache()
    mesh = proxy = None
    generation = 4200 + run_index
    digest = hashlib.sha256()
    owner = None
    disabled_solve_count = None
    transition_signatures = []
    try:
        physics_blender.register()
        mesh, proxy = mixed._mesh_object(f"MC2ProductMeshAngleLimit{run_index}")

        def make_request(enabled: bool, limit: float):
            return _request(
                world,
                mesh,
                attenuation=0.0,
                falloff=0.0,
                enabled=False,
                gravity=8.0,
                damping=0.05,
                limit_enabled=enabled,
                angle_limit=limit,
                angle_limit_stiffness=1.0,
                distance_stiffness=0.8,
            )

        request = make_request(False, 30.0)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        output = None
        for frame in range(1, 1201):
            transition = None
            if frame == 301:
                transition = (True, 30.0)
            elif frame == 601:
                transition = (False, 30.0)
            elif frame == 901:
                transition = (True, 20.0)
            if transition is not None:
                old_owner = owner
                old_signature = owner.compiled.parameters.parameter_signature
                request = make_request(*transition)
                assert product_slot.make_mc2_product_slot_id(
                    request.setup_type, request.domain_signature
                ) == slot_id

            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = frame == 1200
            if capture:
                assert owner is not None
                owner.begin_constraint_debug(1)
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
            if transition is not None:
                assert owner is old_owner
                new_signature = owner.compiled.parameters.parameter_signature
                assert new_signature != old_signature
                transition_signatures.append(new_signature)

            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            assert np.all(np.isfinite(output.world_rotations_xyzw))
            digest.update(output.world_positions.tobytes())
            digest.update(output.world_rotations_xyzw.tobytes())
            kernel = owner.inspect()["domain"]["kernel"]
            if frame == 300:
                assert kernel["angle_solve_count"] == 0
            elif frame == 601:
                disabled_solve_count = kernel["angle_solve_count"]
            elif 601 < frame <= 900:
                assert kernel["angle_solve_count"] == disabled_solve_count

        assert owner is not None and output is not None
        owner.end_constraint_debug()
        angle_debug = owner.read_constraint_debug_state()["angle_results"]
        angles = _limit_angles(output, angle_debug)
        assert float(np.max(angles)) <= 26.0, float(np.max(angles))
        assert owner.inspect()["domain"]["kernel"]["angle_solve_count"] > 0
        assert len(set(transition_signatures)) == 3

        float_table = owner.compiled.parameters.partition_parameters
        float_values = dict(zip(float_table.fields, float_table.values[0]))
        uint_table = owner.compiled.parameters.partition_uint_parameters
        uint_values = dict(zip(uint_table.fields, uint_table.values[0]))
        particle_table = owner.compiled.parameters.particle_parameters
        limit_column = particle_table.fields.index("angle_limit")
        np.testing.assert_allclose(
            float_values["angle_limit_stiffness"], 1.0, rtol=0.0, atol=1.0e-7
        )
        assert int(uint_values["use_angle_limit"]) == 1
        np.testing.assert_allclose(
            particle_table.values[:, limit_column], 20.0, rtol=0.0, atol=1.0e-6
        )
        digest.update(angles.tobytes())
        return (
            digest.hexdigest(),
            float(np.max(angles)),
            len(transition_signatures),
            int(disabled_solve_count),
        )
    finally:
        world.omni_cache_dispose("mesh_product_angle_limit_cleanup")
        mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_angle_limit_transition_deterministic() -> None:
    first = _run_angle_limit_transition(0)
    second = _run_angle_limit_transition(1)
    assert first == second, (first, second)
    print("MC2_MESH_PRODUCT_ANGLE_LIMIT", first)
    print("PASS test_mesh_product_angle_limit_transition_deterministic")


if __name__ == "__main__":
    test_mesh_product_angle_restoration_response()
    test_mesh_product_angle_restoration_falloff()
    test_mesh_product_angle_restoration_rest_debug()
    test_mesh_product_angle_limit_transition_deterministic()
