"""公开 Bone 产品 request 的 Center/Anchor/Teleport 数值门禁。"""

from __future__ import annotations

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

print(f"MC2_BONE_PRODUCT_CENTER_SOURCE {__file__}")


def _request(
    armature,
    *,
    spring: bool,
    anchor=None,
    anchor_inertia: float = 0.0,
    world_inertia: float = 1.0,
    local_inertia: float = 1.0,
    depth_inertia: float = 0.0,
    teleport_mode: int = 0,
):
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.1,
        stabilization_time_after_reset=0.0,
        particle_speed_limit=100.0,
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
    task_values = {
        "anchor_object": anchor,
        "anchor_inertia": anchor_inertia,
        "world_inertia": world_inertia,
        "movement_inertia_smoothing": 0.0,
        "movement_speed_limit": -1.0,
        "rotation_speed_limit": -1.0,
        "local_inertia": local_inertia,
        "local_movement_speed_limit": -1.0,
        "local_rotation_speed_limit": -1.0,
        "depth_inertia": depth_inertia,
        "teleport_mode": teleport_mode,
        "teleport_distance": 0.5,
        "teleport_rotation": 90.0,
    }
    if spring:
        requests, _report = nodes.physicsMC2BoneSpringTask(
            [{
                "armature": armature,
                "root_bone": "Chain0_0",
                "bones": tuple(f"Chain0_{depth}" for depth in range(6)),
            }],
            profile=profile,
            **task_values,
        )
    else:
        requests, _report = nodes.physicsMC2BoneClothTask(
            [{"armature": armature, "bone": "Parent"}],
            profile=profile,
            connection_mode=0,
            **task_values,
        )
    assert len(requests) == 1
    return requests[0]


def _remove_object(obj) -> None:
    if obj is not None and obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def _run_case(
    *,
    spring: bool,
    run_index: int,
    world_delta: float = 0.0,
    local_delta: float = 0.0,
    anchor_enabled: bool = False,
    anchor_inertia: float = 0.0,
    world_inertia: float = 1.0,
    local_inertia: float = 1.0,
    depth_inertia: float = 0.0,
    teleport_mode: int = 0,
    frame_count: int = 5,
):
    world = world_types.PhysicsWorldCache()
    generation = 1020 + run_index
    armature = anchor = None
    snapshots = []
    outputs = []
    try:
        armature = product_soak._armature(
            f"MC2ProductCenter_{run_index}_{int(spring)}",
            chain_count=1,
            chain_length=6,
            x_offset=0.0,
        )
        initial_basis = {
            bone.name: bone.matrix_basis.copy()
            for bone in armature.pose.bones
        }
        if anchor_enabled:
            anchor = bpy.data.objects.new(f"MC2ProductCenterAnchor_{run_index}", None)
            bpy.context.scene.collection.objects.link(anchor)
        request = _request(
            armature,
            spring=spring,
            anchor=anchor,
            anchor_inertia=anchor_inertia,
            world_inertia=world_inertia,
            local_inertia=local_inertia,
            depth_inertia=depth_inertia,
            teleport_mode=teleport_mode,
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        owner = scheduler = None
        for frame in range(1, frame_count + 1):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            armature.location.x = world_delta * float(frame - 1)
            armature.pose.bones["Parent"].location.x = local_delta * float(frame - 1)
            if anchor is not None:
                anchor.location.x = world_delta * float(frame - 1)
            bpy.context.view_layer.update()
            product_soak._set_frame(world, frame, generation)
            world.frame_context.raw_dt = 1.0 / 30.0
            world.frame_context.dt = 1.0 / 30.0
            world.collider_snapshot = {"frame": frame, "colliders": []}
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [request],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            slot = world.solver_slots[slot_id]
            assert "native_context" not in slot.data
            assert "spec" not in slot.data
            current_owner = slot.data["owner"]
            current_scheduler = slot.data["scheduler_state"]
            if owner is None:
                owner = current_owner
                scheduler = current_scheduler
            else:
                assert current_owner is owner
                assert current_scheduler is scheduler
                assert slot.data["last_sync"].native_domain_reused is True
            output = owner.read_output()
            kernel = owner.inspect()["domain"]["kernel"]
            assert np.all(np.isfinite(output.world_positions))
            snapshots.append({
                "center_shift_count": int(kernel["center_shift_count"]),
                "center_step_count": int(kernel["center_step_count"]),
                "shift": np.array(kernel["center_shift_vectors"], copy=True),
                "step": np.array(kernel["center_step_vectors"], copy=True),
                "inertia": np.array(kernel["center_inertia_vectors"], copy=True),
                "teleport": np.array(kernel["center_shift_teleport_flags"], copy=True),
                "reset": np.array(kernel["partition_reset_counts"], copy=True),
                "keep": np.array(kernel["partition_keep_counts"], copy=True),
            })
            outputs.append(np.array(output.world_positions, copy=True))
            assert writeback.writeback_bone_transforms(world) == output.world_positions.shape[0]
            bpy.context.view_layer.update()
        return snapshots, outputs
    finally:
        world.omni_cache_dispose("bone_product_center_teleport_cleanup")
        product_soak._remove_armature(armature)
        _remove_object(anchor)


def _assert_world_and_anchor_endpoints(*, spring: bool, base_index: int):
    follow, _ = _run_case(
        spring=spring,
        run_index=base_index,
        world_delta=0.03,
        world_inertia=0.0,
    )
    hold, _ = _run_case(
        spring=spring,
        run_index=base_index + 1,
        world_delta=0.03,
        world_inertia=1.0,
    )
    for frame_index in range(1, len(follow)):
        np.testing.assert_allclose(follow[frame_index]["shift"][0], (0.03, 0.0, 0.0), atol=2.0e-6)
        np.testing.assert_allclose(hold[frame_index]["shift"][0], 0.0, atol=2.0e-6)
        assert follow[frame_index]["center_shift_count"] == frame_index
        assert follow[frame_index]["center_step_count"] == frame_index * 3

    anchor_follow, _ = _run_case(
        spring=spring,
        run_index=base_index + 2,
        world_delta=0.03,
        anchor_enabled=True,
        anchor_inertia=0.0,
        world_inertia=1.0,
    )
    anchor_hold, _ = _run_case(
        spring=spring,
        run_index=base_index + 3,
        world_delta=0.03,
        anchor_enabled=True,
        anchor_inertia=1.0,
        world_inertia=1.0,
    )
    for frame_index in range(1, len(anchor_follow)):
        np.testing.assert_allclose(anchor_follow[frame_index]["shift"][0], (0.03, 0.0, 0.0), atol=2.0e-6)
        np.testing.assert_allclose(anchor_hold[frame_index]["shift"][0], 0.0, atol=2.0e-6)


def _assert_local_and_depth_endpoints(*, spring: bool, base_index: int):
    local_zero, _ = _run_case(
        spring=spring,
        run_index=base_index,
        local_delta=0.03,
        local_inertia=0.0,
    )
    local_one, _ = _run_case(
        spring=spring,
        run_index=base_index + 1,
        local_delta=0.03,
        local_inertia=1.0,
    )
    for frame_index in range(1, len(local_zero)):
        np.testing.assert_allclose(
            local_zero[frame_index]["inertia"],
            local_zero[frame_index]["step"],
            atol=2.0e-6,
        )
        np.testing.assert_allclose(local_one[frame_index]["inertia"], 0.0, atol=2.0e-6)

    _depth_zero, output_zero = _run_case(
        spring=spring,
        run_index=base_index + 2,
        local_delta=0.03,
        local_inertia=1.0,
        depth_inertia=0.0,
    )
    _depth_one, output_one = _run_case(
        spring=spring,
        run_index=base_index + 3,
        local_delta=0.03,
        local_inertia=1.0,
        depth_inertia=1.0,
    )
    delta = float(np.max(np.abs(output_zero[-1] - output_one[-1])))
    assert delta > 1.0e-5, (spring, delta)


def _assert_teleport_modes(*, spring: bool, base_index: int):
    reset, _ = _run_case(
        spring=spring,
        run_index=base_index,
        world_delta=1.0,
        world_inertia=0.0,
        teleport_mode=1,
        frame_count=2,
    )
    keep, _ = _run_case(
        spring=spring,
        run_index=base_index + 1,
        world_delta=1.0,
        world_inertia=0.0,
        teleport_mode=2,
        frame_count=2,
    )
    assert int(reset[1]["teleport"][0]) == 5
    assert int(keep[1]["teleport"][0]) == 3
    assert reset[1]["center_shift_count"] == 1
    assert keep[1]["center_shift_count"] == 1
    assert reset[1]["center_step_count"] == 3
    assert keep[1]["center_step_count"] == 3
    np.testing.assert_array_equal(reset[1]["reset"], reset[0]["reset"])
    np.testing.assert_array_equal(keep[1]["keep"], keep[0]["keep"])


def test_bone_product_center_teleport_endpoints():
    for setup_index, spring in enumerate((False, True)):
        base = 100 * setup_index
        _assert_world_and_anchor_endpoints(spring=spring, base_index=base)
        _assert_local_and_depth_endpoints(spring=spring, base_index=base + 20)
        _assert_teleport_modes(spring=spring, base_index=base + 40)
        print(
            "MC2_BONE_PRODUCT_CENTER_RESULT",
            "bone_spring" if spring else "bone_cloth",
            "world/anchor/local/depth/reset/keep",
        )
    print("PASS test_bone_product_center_teleport_endpoints")


if __name__ == "__main__":
    test_bone_product_center_teleport_endpoints()
