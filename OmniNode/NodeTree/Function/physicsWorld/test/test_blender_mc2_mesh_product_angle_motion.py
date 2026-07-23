"""MeshCloth product-only Angle Restoration response contracts."""

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


def _request(world, mesh, *, attenuation, falloff, enabled=True):
    entries, count = nodes.physicsMC2MeshObject([mesh])
    assert count == 1 and len(entries) == 1
    entries, count = nodes.physicsMC2MeshOverride(
        entries,
        profile=parameters.make_mc2_particle_profile(
            gravity=4.0,
            gravity_direction=(0.0, 0.0, -1.0),
            gravity_falloff=0.0,
            damping=0.05,
            particle_speed_limit=3.5,
            radius=0.018,
            tether_compression=0.35,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=enabled,
            angle_restoration_stiffness=0.65,
            angle_restoration_velocity_attenuation=attenuation,
            angle_restoration_gravity_falloff=falloff,
            angle_limit_enabled=False,
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


if __name__ == "__main__":
    test_mesh_product_angle_restoration_response()
    test_mesh_product_angle_restoration_falloff()
