"""MeshCloth 产品域外碰 scope 与摩擦响应数值闸门。"""

from __future__ import annotations

import hashlib
import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_product_mixed_output_soak as mixed


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
    collision_mode: int,
    friction: float,
    radius: float = 0.02,
):
    entries, count = nodes.physicsMC2MeshObject([mesh])
    assert count == 1 and len(entries) == 1
    entries, count = nodes.physicsMC2MeshOverride(
        entries,
        profile=parameters.make_mc2_particle_profile(
            gravity=0.0,
            damping=0.02,
            stabilization_time_after_reset=0.0,
            particle_speed_limit=3.5,
            radius=radius,
            tether_compression=0.35,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            max_distance_enabled=False,
            backstop_enabled=False,
            motion_stiffness=0.0,
            collision_mode=collision_mode,
            collision_friction=friction,
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


def _slot_id(request):
    return product_slot.make_mc2_product_slot_id(
        request.setup_type, request.domain_signature
    )


def _scope_colliders(mesh_a, mesh_b, targets, *, accepted: bool):
    group = 1 if accepted else 2
    target_a, target_b = (np.asarray(value, dtype=np.float64) for value in targets)
    return (
        {
            "key": "mesh-scope-plane-for-a",
            "owner": mesh_b,
            "type": "PLANE",
            "primary_group": group,
            "center": (0.0, 0.0, float(target_a[2] + 0.01)),
            "normal": (0.0, 0.0, 1.0),
        },
        {
            "key": "mesh-scope-plane-for-b",
            "owner": mesh_a,
            "type": "PLANE",
            "primary_group": group,
            "center": (0.0, 0.0, float(target_b[2] + 0.01)),
            "normal": (0.0, 0.0, 1.0),
        },
    )


def _run_scope_case(*, accepted: bool, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 4300 + run_index
    meshes = [None, None]
    digest = hashlib.sha256()
    owners = None
    initial = None
    targets = None
    max_responses = [0.0, 0.0]
    max_normals = [0.0, 0.0]
    max_spans = [0.0, 0.0]
    try:
        physics_blender.register()
        meshes[0], _proxy_a = mixed._mesh_object(f"MC2ProductMeshScopeA{run_index}")
        meshes[1], _proxy_b = mixed._mesh_object(f"MC2ProductMeshScopeB{run_index}")
        meshes[1].location.x += 0.45
        _proxy_b.location.x += 0.45
        bpy.context.view_layer.update()
        requests = tuple(
            _request(world, mesh, collision_mode=1, friction=0.0)
            for mesh in meshes
        )
        slot_ids = tuple(_slot_id(request) for request in requests)
        assert len(set(slot_ids)) == 2

        for frame in range(1, 601):
            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {
                "frame": frame,
                "colliders": () if targets is None else _scope_colliders(
                    meshes[0], meshes[1], targets, accepted=accepted
                ),
            }
            returned, ready, status = nodes.physicsMC2Step(
                world,
                list(requests),
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            current_owners = tuple(
                world.solver_slots[slot_id].data["owner"] for slot_id in slot_ids
            )
            if owners is None:
                owners = current_owners
                if accepted:
                    for owner in owners:
                        uint_table = owner.compiled.parameters.partition_uint_parameters
                        particle_table = owner.compiled.parameters.particle_parameters
                        radius_column = particle_table.fields.index("radius")
                        uint_values = dict(zip(
                            uint_table.fields,
                            uint_table.values[0],
                        ))
                        assert int(uint_values["collision_mode"]) == 1
                        assert int(uint_values["collided_by_groups"]) == 1
                        np.testing.assert_allclose(
                            particle_table.values[:, radius_column],
                            0.02,
                            rtol=0.0,
                            atol=1.0e-7,
                        )
            else:
                assert current_owners == owners
            outputs = tuple(owner.read_output() for owner in owners)
            assert all(np.all(np.isfinite(out.world_positions)) for out in outputs)
            if initial is None:
                initial = tuple(out.world_positions.copy() for out in outputs)
                targets = tuple(value[5].copy() for value in initial)
                continue

            expected_keys = (
                ("mesh-scope-plane-for-a",),
                ("mesh-scope-plane-for-b",),
            )
            for index, (slot_id, owner, output) in enumerate(
                zip(slot_ids, owners, outputs)
            ):
                slot = world.solver_slots[slot_id]
                assert tuple(slot.data["collider_frame"].collider_keys) == expected_keys[index]
                response = float(np.max(np.linalg.norm(
                    output.world_positions - initial[index], axis=1
                )))
                span = float(np.max(np.linalg.norm(
                    output.world_positions[:, None, :]
                    - output.world_positions[None, :, :],
                    axis=2,
                )))
                normals = np.asarray(
                    owner.read_debug_state()["world_normals"], dtype=np.float32
                )
                normal = float(np.max(np.linalg.norm(normals, axis=1)))
                max_responses[index] = max(max_responses[index], response)
                max_normals[index] = max(max_normals[index], normal)
                max_spans[index] = max(max_spans[index], span)
                assert response <= 0.8, (index, frame, response)
                assert span <= 0.8, (index, frame, span)
                assert normal <= 1.000001, (index, frame, normal)
                digest.update(output.world_positions.tobytes())
                digest.update(normals.tobytes())
        assert owners is not None
        for owner in owners:
            kernel = owner.inspect()["domain"]["kernel"]
            assert kernel["compiled_external_ready"] is True
            assert kernel["compiled_external_step_count"] >= 500
        if accepted:
            assert all(value > 1.0e-5 for value in max_responses), max_responses
        else:
            assert max(max_responses) <= 1.0e-7, max_responses
        digest.update(str(expected_keys).encode("ascii"))
        return (
            digest.hexdigest(),
            tuple(max_responses),
            tuple(max_normals),
            tuple(max_spans),
        )
    finally:
        world.omni_cache_dispose("mesh_product_collision_scope_cleanup")
        for mesh in meshes:
            mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_collider_scope_response_deterministic() -> None:
    rejected = _run_scope_case(accepted=False, run_index=0)
    rejected_repeat = _run_scope_case(accepted=False, run_index=1)
    accepted = _run_scope_case(accepted=True, run_index=2)
    accepted_repeat = _run_scope_case(accepted=True, run_index=3)
    assert rejected == rejected_repeat, (rejected, rejected_repeat)
    assert accepted == accepted_repeat, (accepted, accepted_repeat)
    assert rejected[0] != accepted[0]
    assert min(accepted[1]) > max(rejected[1])
    print("MC2_MESH_PRODUCT_COLLIDER_SCOPE", rejected, accepted)
    print("PASS test_mesh_product_collider_scope_response_deterministic")


def _run_friction_case(friction: float, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 4400 + run_index
    mesh = None
    digest = hashlib.sha256()
    lags = []
    owner = None
    plane_z = None
    max_normal = 0.0
    try:
        physics_blender.register()
        mesh, _proxy = mixed._mesh_object(f"MC2ProductMeshFriction{run_index}")
        initial_x = float(mesh.location.x)
        request = _request(
            world,
            mesh,
            collision_mode=1,
            friction=friction,
            radius=0.02,
        )
        slot_id = _slot_id(request)
        for frame in range(1, 601):
            mesh.location.x = initial_x + frame * 0.002
            bpy.context.view_layer.update()
            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {
                "frame": frame,
                "colliders": () if plane_z is None else ({
                    "key": "mesh-product-friction-plane",
                    "type": "PLANE",
                    "primary_group": 1,
                    "center": (0.0, 0.0, plane_z),
                    "normal": (0.0, 0.0, 1.0),
                },),
            }
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
                float_table = owner.compiled.parameters.partition_parameters
                float_values = dict(zip(float_table.fields, float_table.values[0]))
                uint_table = owner.compiled.parameters.partition_uint_parameters
                uint_values = dict(zip(uint_table.fields, uint_table.values[0]))
                particle_table = owner.compiled.parameters.particle_parameters
                radius_column = particle_table.fields.index("radius")
                np.testing.assert_allclose(
                    float_values["collision_dynamic_friction"],
                    friction,
                    rtol=0.0,
                    atol=1.0e-7,
                )
                np.testing.assert_allclose(
                    float_values["collision_static_friction"],
                    friction,
                    rtol=0.0,
                    atol=1.0e-7,
                )
                assert int(uint_values["collision_mode"]) == 1
                np.testing.assert_allclose(
                    particle_table.values[:, radius_column],
                    0.02,
                    rtol=0.0,
                    atol=1.0e-7,
                )
            else:
                assert current_owner is owner

            output = owner.read_output()
            expected = slot.data["frame_packet"].animated_base_world_positions
            assert expected.shape == output.world_positions.shape
            assert np.all(np.isfinite(output.world_positions))
            if plane_z is None:
                plane_z = float(output.world_positions[4, 2] - 0.015)
                continue
            lag = float(np.mean(expected[4:, 0] - output.world_positions[4:, 0]))
            assert abs(lag) < 0.2, (friction, frame, lag)
            if frame > 300:
                lags.append(lag)
            normals = np.asarray(
                owner.read_debug_state()["world_normals"], dtype=np.float32
            )
            max_normal = max(
                max_normal, float(np.max(np.linalg.norm(normals, axis=1)))
            )
            digest.update(output.world_positions.tobytes())
            digest.update(normals.tobytes())

        assert owner is not None and lags
        kernel = owner.inspect()["domain"]["kernel"]
        assert kernel["compiled_external_step_count"] >= 500
        assert max_normal > 1.0e-5
        return (
            digest.hexdigest(),
            float(np.mean(lags)),
            float(lags[-1]),
            max_normal,
        )
    finally:
        world.omni_cache_dispose("mesh_product_friction_cleanup")
        mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_friction_ordered_deterministic() -> None:
    low = _run_friction_case(0.0, 0)
    low_repeat = _run_friction_case(0.0, 1)
    high = _run_friction_case(0.5, 2)
    high_repeat = _run_friction_case(0.5, 3)
    assert low == low_repeat, (low, low_repeat)
    assert high == high_repeat, (high, high_repeat)
    assert high[1] > low[1] + 0.0002, (low, high)
    assert high[2] > low[2] + 0.0002, (low, high)
    print("MC2_MESH_PRODUCT_FRICTION", low, high)
    print("PASS test_mesh_product_friction_ordered_deterministic")


if __name__ == "__main__":
    test_mesh_product_collider_scope_response_deterministic()
    test_mesh_product_friction_ordered_deterministic()
