"""MeshCloth 产品域跨 partition 自碰撞的数值与过滤合同。"""

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


def _profile():
    return parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.1,
        stabilization_time_after_reset=0.0,
        particle_speed_limit=3.5,
        radius=0.04,
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
        self_collision_mode=2,
        self_collision_sync_mode=2,
        self_collision_thickness=0.05,
        spring_enabled=False,
        wind_influence=0.0,
    )


def _partition(mesh, *, group: int, mask: int, mass: float):
    entries, count = nodes.physicsMC2MeshObject([mesh])
    assert count == 1 and len(entries) == 1
    entries, count = nodes.physicsMC2MeshOverride(
        entries,
        profile=_profile(),
        cloth_mass=mass,
        collision_group=group,
        collision_mask=mask,
    )
    assert count == 1 and len(entries) == 1
    return entries[0]


def _request(world, meshes, *, accepted: bool):
    masks = (2, 1) if accepted else (1, 2)
    entries = [
        _partition(meshes[0], group=1, mask=masks[0], mass=0.25),
        _partition(meshes[1], group=2, mask=masks[1], mass=0.75),
    ]
    requests, report = nodes.physicsMC2MeshCollector(
        world,
        entries,
        include_implicit=False,
    )
    assert len(requests) == 1 and report
    return requests[0]


def _cross_contact_count(owner) -> tuple[int, int, int]:
    debug = owner.read_constraint_debug_state()["whole_domain_self_results"]
    primitive_owners = np.asarray(debug["owner_indices"], dtype=np.int32)
    contact_indices = np.asarray(
        debug["contact_indices"], dtype=np.int32
    ).reshape((-1, 2))
    enabled = np.asarray(
        debug["contact_enabled"], dtype=np.uint8
    ).astype(bool)
    assert len(contact_indices) == len(enabled)
    if len(contact_indices) == 0:
        return 0, 0, 0
    cross = (
        primitive_owners[contact_indices[:, 0]]
        != primitive_owners[contact_indices[:, 1]]
    )
    return (
        int(np.count_nonzero(cross)),
        int(np.count_nonzero(cross & enabled)),
        int(np.count_nonzero(enabled)),
    )


def _run_scope_case(*, accepted: bool, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 4700 + run_index
    meshes = [None, None]
    digest = hashlib.sha256()
    samples = []
    owner = None
    try:
        physics_blender.register()
        meshes[0], _proxy_a = mixed._mesh_object(
            f"MC2ProductMeshSelfA{run_index}"
        )
        meshes[1], proxy_b = mixed._mesh_object(
            f"MC2ProductMeshSelfB{run_index}"
        )
        meshes[1].location.x += 0.01
        meshes[1].location.z += 0.005
        proxy_b.location.x += 0.01
        proxy_b.location.z += 0.005
        bpy.context.view_layer.update()

        request = _request(world, meshes, accepted=accepted)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        for frame in range(1, 601):
            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = frame in (2, 600)
            if capture:
                assert owner is not None
                owner.begin_constraint_debug(64)
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
                assert owner.compiled.program.partition_count == 2
                assert set(owner.compiled.program.particle_partition_index) == {0, 1}
                uint_table = owner.compiled.parameters.partition_uint_parameters
                uint_rows = [
                    dict(zip(uint_table.fields, row)) for row in uint_table.values
                ]
                assert [int(row["self_collision_mode"]) for row in uint_rows] == [2, 2]
                assert [int(row["self_collision_sync_mode"]) for row in uint_rows] == [2, 2]
                assert [int(row["collision_group"]) for row in uint_rows] == [1, 2]
                expected_masks = [2, 1] if accepted else [1, 2]
                assert [int(row["collision_mask"]) for row in uint_rows] == expected_masks

                particle = owner.compiled.parameters.particle_parameters
                fields = {name: index for index, name in enumerate(particle.fields)}
                radius = particle.values[:, fields["radius"]]
                thickness = particle.values[:, fields["self_collision_thickness"]]
                multipliers = particle.values[:, fields["radius_multiplier"]]
                masses = particle.values[:, fields["cloth_mass"]]
                np.testing.assert_allclose(
                    thickness,
                    radius * 0.25,
                    rtol=0.0,
                    atol=1.0e-7,
                )
                np.testing.assert_allclose(
                    multipliers, 1.0, rtol=0.0, atol=1.0e-7
                )
                partition_indices = owner.compiled.program.particle_partition_index
                np.testing.assert_allclose(
                    masses[partition_indices == 0], 0.25, rtol=0.0, atol=1.0e-7
                )
                np.testing.assert_allclose(
                    masses[partition_indices == 1], 0.75, rtol=0.0, atol=1.0e-7
                )
            else:
                assert current_owner is owner

            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            digest.update(output.world_positions.tobytes())
            kernel = owner.inspect()["domain"]["kernel"]
            assert kernel["whole_domain_self_ready"] is True
            primitive_count = sum(
                int(kernel[f"whole_domain_self_{kind}_count"])
                for kind in ("point", "edge", "triangle")
            )
            candidate_count = int(
                kernel.get("whole_domain_self_last_candidate_count", 0)
            )
            contact_count = int(
                kernel.get("whole_domain_self_last_contact_count", 0)
            )
            cache_count = int(kernel.get("self_contact_cache_count", 0))
            assert primitive_count > 0
            assert 0 <= contact_count <= candidate_count <= primitive_count ** 2
            assert 0 <= cache_count <= primitive_count ** 2
            if frame > 1:
                assert kernel["whole_domain_self_step_count"] > 0
            if capture:
                owner.end_constraint_debug()
                cross_candidates, cross_enabled, enabled = _cross_contact_count(owner)
                if frame == 2:
                    if accepted:
                        assert cross_candidates > 0
                        assert cross_enabled > 0
                    else:
                        assert cross_enabled == 0
                samples.append((
                    frame,
                    primitive_count,
                    candidate_count,
                    contact_count,
                    cache_count,
                    cross_candidates,
                    cross_enabled,
                    enabled,
                ))
                digest.update(np.asarray(samples[-1], dtype=np.int64).tobytes())

        assert owner is not None and len(samples) == 2
        return digest.hexdigest(), tuple(samples)
    finally:
        world.omni_cache_dispose("mesh_product_self_scope_cleanup")
        for mesh in meshes:
            mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_self_collision_cross_partition_scope_and_cache() -> None:
    rejected = _run_scope_case(accepted=False, run_index=0)
    rejected_repeat = _run_scope_case(accepted=False, run_index=1)
    accepted = _run_scope_case(accepted=True, run_index=2)
    accepted_repeat = _run_scope_case(accepted=True, run_index=3)
    assert rejected == rejected_repeat, (rejected, rejected_repeat)
    assert accepted == accepted_repeat, (accepted, accepted_repeat)
    assert rejected[0] != accepted[0]
    print("MC2_MESH_PRODUCT_SELF_SCOPE", rejected, accepted)
    print("PASS test_mesh_product_self_collision_cross_partition_scope_and_cache")


if __name__ == "__main__":
    test_mesh_product_self_collision_cross_partition_scope_and_cache()
