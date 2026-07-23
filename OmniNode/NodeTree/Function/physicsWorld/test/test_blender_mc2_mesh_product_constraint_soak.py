"""MeshCloth product-only gravity axes and falloff contract."""

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


def _request(world, mesh, *, gravity_direction, gravity_falloff):
    entries, count = nodes.physicsMC2MeshObject([mesh])
    assert count == 1 and len(entries) == 1
    entries, count = nodes.physicsMC2MeshOverride(
        entries,
        profile=parameters.make_mc2_particle_profile(
            gravity=4.0,
            gravity_direction=gravity_direction,
            gravity_falloff=gravity_falloff,
            damping=0.0,
            particle_speed_limit=3.5,
            radius=0.018,
            tether_compression=0.35,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
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


if __name__ == "__main__":
    test_mesh_product_gravity_axes_falloff()
