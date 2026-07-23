"""真实 Bone 多产品域失败时的整批事务与重试验收。"""

from __future__ import annotations

import importlib
import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_bone_product_constraint_soak as product_soak


nodes = product_soak.nodes
product_slot = product_soak.product_slot
world_types = product_soak.world_types
writeback = product_soak.writeback
bone_frame_input = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_frame_input"
)

print(f"MC2_BONE_PRODUCT_FAILURE_SOURCE {__file__}")


def test_bone_product_second_domain_failure_is_atomic_and_retryable():
    world = world_types.PhysicsWorldCache()
    generation = 1100
    cloth = spring = None
    owner_type = original_step = None
    try:
        cloth = product_soak._armature(
            "MC2ProductFailureCloth",
            chain_count=1,
            chain_length=6,
            x_offset=-0.25,
        )
        spring = product_soak._armature(
            "MC2ProductFailureSpring",
            chain_count=1,
            chain_length=6,
            x_offset=0.25,
        )
        requests = product_soak._requests(cloth, spring)
        slot_ids = product_soak._slot_ids(requests)
        product_soak._set_frame(world, 1, generation)
        world.collider_snapshot = {"frame": 1, "colliders": []}
        returned, ready, status = nodes.physicsMC2Step(
            world,
            list(requests),
            simulation_frequency=90,
            max_simulation_count_per_frame=3,
        )
        assert returned is world and ready is True, status
        slots = tuple(world.solver_slots[slot_id] for slot_id in slot_ids)
        owners = tuple(slot.data["owner"] for slot in slots)
        expected_bones = sum(
            owner.compiled.program.particle_count for owner in owners
        )
        assert writeback.writeback_bone_transforms(world) == expected_bones
        bpy.context.view_layer.update()
        feedback_key = bone_frame_input.MC2_BONE_FRAME_STATE_KEY
        feedback_before = world.backend_resources[feedback_key]
        pose_before = {
            (armature.name, bone.name): bone.matrix_basis.copy()
            for armature in (cloth, spring)
            for bone in armature.pose.bones
        }

        fail_owner = owners[1]
        owner_type = type(fail_owner)
        original_step = owner_type.step

        def _step_then_fail(self, settings):
            if self is fail_owner:
                raise RuntimeError("injected Bone product second-domain failure")
            return original_step(self, settings)

        owner_type.step = _step_then_fail
        product_soak._set_frame(world, 2, generation)
        world.collider_snapshot = {"frame": 2, "colliders": []}
        try:
            nodes.physicsMC2Step(
                world,
                list(requests),
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
        except RuntimeError as exc:
            assert "second-domain failure" in str(exc)
        else:
            raise AssertionError("第二个 Bone 产品域故障没有传播")
        finally:
            owner_type.step = original_step
            owner_type = original_step = None

        assert all(slot_id not in world.solver_slots for slot_id in slot_ids)
        assert tuple(world.result_streams.get("bone_transform", ())) == ()
        assert world.backend_resources[feedback_key] is feedback_before
        assert world.replace_required is True
        assert all(owner.inspect()["live"] is False for owner in owners)
        for armature in (cloth, spring):
            for bone in armature.pose.bones:
                np.testing.assert_allclose(
                    bone.matrix_basis,
                    pose_before[(armature.name, bone.name)],
                    rtol=0.0,
                    atol=0.0,
                )

        world.replace_required = False
        product_soak._set_frame(world, 2, generation)
        world.collider_snapshot = {"frame": 2, "colliders": []}
        returned, ready, status = nodes.physicsMC2Step(
            world,
            list(requests),
            simulation_frequency=90,
            max_simulation_count_per_frame=3,
        )
        assert returned is world and ready is True, status
        retry_slots = tuple(world.solver_slots[slot_id] for slot_id in slot_ids)
        retry_owners = tuple(slot.data["owner"] for slot in retry_slots)
        assert all(current is not previous for current, previous in zip(retry_owners, owners))
        assert all(owner.read_output().frame == 2 for owner in retry_owners)
        assert all(np.all(np.isfinite(owner.read_output().world_positions)) for owner in retry_owners)
        results = tuple(world.result_streams.get("bone_transform", ()))
        assert results
        assert sum(int(result["bone_count"]) for result in results) == expected_bones
        assert writeback.writeback_bone_transforms(world) == expected_bones
        print("PASS test_bone_product_second_domain_failure_is_atomic_and_retryable")
    finally:
        if owner_type is not None and original_step is not None:
            owner_type.step = original_step
        world.omni_cache_dispose("bone_product_failure_transaction_cleanup")
        product_soak._remove_armature(cloth)
        product_soak._remove_armature(spring)


if __name__ == "__main__":
    test_bone_product_second_domain_failure_is_atomic_and_retryable()
