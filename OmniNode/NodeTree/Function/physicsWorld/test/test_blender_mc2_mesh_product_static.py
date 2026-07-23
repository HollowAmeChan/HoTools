"""MeshCloth product static/base-pose contract for Blender 5.2."""

from __future__ import annotations

import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_product_mixed_output_soak as mixed


def _set_frame(world, frame: int) -> None:
    mixed.bone_soak._set_frame(world, frame, 1800)
    world.collider_snapshot = {"frame": frame, "colliders": []}


def test_mesh_product_static_contract() -> None:
    world = mixed.world_types.PhysicsWorldCache()
    mesh = proxy = None
    try:
        mixed.physics_blender.register()
        mesh, proxy = mixed._mesh_object("MC2ProductMeshStatic")
        request = mixed._mesh_request(world, mesh)
        slot_id = mixed._slot_id(request)

        _set_frame(world, 1)
        returned, ready, status = mixed.nodes.physicsMC2Step(world, [request])
        assert returned is world and ready is True, status
        slot = world.solver_slots[slot_id]
        owner = slot.data["owner"]
        program = owner.compiled.program
        assert program.setup_type == "mesh_cloth"
        assert program.partition_count == 1
        assert program.particle_count == len(mesh.data.vertices)
        assert "native_context" not in slot.data
        assert "spec" not in slot.data
        output = owner.read_output()
        assert output.world_positions.shape == (program.particle_count, 3)
        assert np.all(np.isfinite(output.world_positions))
        assert mixed.writeback.writeback_gn_attributes(world) == 1

        # A pure parameter update keeps the product slot/owner and changes only
        # the compiled parameter signature.
        updated = mixed._mesh_request(world, mesh, hot=True)
        assert mixed._slot_id(updated) == slot_id
        first_parameters = owner.compiled.parameters.parameter_signature
        _set_frame(world, 2)
        returned, ready, status = mixed.nodes.physicsMC2Step(world, [updated])
        assert returned is world and ready is True, status
        slot = world.solver_slots[slot_id]
        assert slot.data["owner"] is owner
        assert slot.data["last_sync"].native_domain_reused
        assert owner.compiled.parameters.parameter_signature != first_parameters

        # Changing a surface input starts a new product collection while the
        # public output/writeback contract remains finite and writable.
        pin = mesh.vertex_groups.get("MC2Pin")
        assert pin is not None
        pin.add((4,), 1.0, "REPLACE")
        changed = mixed._mesh_request(world, mesh)
        _set_frame(world, 3)
        returned, ready, status = mixed.nodes.physicsMC2Step(world, [changed])
        assert returned is world and ready is True, status
        changed_slot = world.solver_slots[mixed._slot_id(changed)]
        changed_owner = changed_slot.data["owner"]
        assert changed_owner is owner
        assert changed_owner.compiled.program.particle_count == program.particle_count
        assert np.all(np.isfinite(changed_owner.read_output().world_positions))
        assert mixed.writeback.writeback_gn_attributes(world) == 1
        print("PASS test_mesh_product_static_contract")
    finally:
        world.omni_cache_dispose("mesh_product_static_contract")
        mixed._remove_mesh(mesh)
        mixed._remove_mesh(proxy)


if __name__ == "__main__":
    test_mesh_product_static_contract()
