"""MeshCloth product-only Motion/Backstop contract."""

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


def _request(world, mesh, *, backstop: bool):
    entries, count = nodes.physicsMC2MeshObject([mesh])
    assert count == 1 and len(entries) == 1
    entries, count = nodes.physicsMC2MeshOverride(
        entries,
        profile=parameters.make_mc2_particle_profile(
            gravity=4.0,
            gravity_direction=(0.0, 0.0, -1.0),
            damping=0.06,
            particle_speed_limit=3.5,
            radius=0.018,
            tether_compression=0.35,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            max_distance_enabled=True,
            max_distance=0.03,
            backstop_enabled=backstop,
            backstop_radius=0.01,
            backstop_distance=0.005,
            motion_stiffness=1.0,
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


def _world_vertices(mesh):
    return np.asarray(
        [tuple(mesh.matrix_world @ vertex.co) for vertex in mesh.data.vertices],
        dtype=np.float32,
    )


def _run_once(run_index: int):
    world = world_types.PhysicsWorldCache()
    mesh = proxy = None
    generation = 2000 + run_index
    digest = hashlib.sha256()
    last_base = None
    max_distance = 0.0
    try:
        physics_blender.register()
        mesh, proxy = mixed._mesh_object(f"MC2ProductMeshMotion{run_index}")
        request = _request(world, mesh, backstop=False)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        owner = None
        bpy.context.view_layer.update()
        expected_previous = _world_vertices(mesh)
        for frame in range(1, 901):
            mesh.location.x = -0.7 + 0.06 * math.sin(frame * 0.031)
            proxy.location = mesh.location
            proxy.rotation_mode = mesh.rotation_mode
            proxy.rotation_euler = mesh.rotation_euler
            bpy.context.view_layer.update()
            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            if frame == 451:
                request = _request(world, mesh, backstop=True)
                assert product_slot.make_mc2_product_slot_id(
                    request.setup_type, request.domain_signature
                ) == slot_id
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
            base = owner.prepare_step_basic_pose()["positions"]
            expected_current = _world_vertices(mesh)
            # Product capture may publish the previous frame's frozen base
            # before the current frame is committed.  Both are valid as long
            # as the pose is an observed Blender snapshot, never an arbitrary
            # interpolated value.
            assert (
                np.allclose(base, expected_previous, rtol=0.0, atol=1.0e-6)
                or np.allclose(base, expected_current, rtol=0.0, atol=1.0e-6)
            )
            expected_previous = expected_current
            last_base = np.array(base, copy=True)
            distances = np.linalg.norm(output.world_positions - base, axis=1)
            movable = (owner.compiled.program.particle_attribute_flags & 1) == 0
            max_distance = max(max_distance, float(np.max(distances[movable])))
            assert float(np.max(distances[movable])) <= 0.031
            assert np.all(np.isfinite(output.world_positions))
            digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            digest.update(output.world_positions.tobytes())
            digest.update(output.world_rotations_xyzw.tobytes())
        assert owner is not None and last_base is not None
        kernel = owner.inspect()["domain"]["kernel"]
        assert kernel["motion_solve_count"] > 0
        table = owner.compiled.parameters.partition_parameters
        motion_fields = set(table.fields)
        motion_fields.update(owner.compiled.parameters.domain_scalars.fields)
        motion_fields.update(owner.compiled.parameters.partition_uint_parameters.fields)
        assert {"motion_stiffness", "movement_speed_limit", "normal_axis"} <= motion_fields
        particle = owner.compiled.parameters.particle_parameters
        assert {"max_distance", "backstop_distance"} <= set(
            particle.fields
        )
        assert "backstop_radius" in motion_fields
        return digest.hexdigest(), max_distance
    finally:
        world.omni_cache_dispose("mesh_product_motion_cleanup")
        mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_motion_base_deterministic() -> None:
    first = _run_once(0)
    second = _run_once(1)
    assert first == second, (first, second)
    assert first[1] <= 0.031
    print("MC2_MESH_PRODUCT_MOTION_DIGEST", first[0])
    print("MC2_MESH_PRODUCT_MOTION_MAX_DISTANCE", first[1])
    print("PASS test_mesh_product_motion_base_deterministic")


if __name__ == "__main__":
    test_mesh_product_motion_base_deterministic()
