"""公开 BoneCloth/BoneSpring request 的碰撞筛选与响应验收。"""

from __future__ import annotations

import hashlib
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

print(f"MC2_BONE_PRODUCT_COLLISION_SOURCE {__file__}")


def _request(
    armature,
    *,
    spring: bool,
    friction: float,
    collision_mode: int = 2,
    damping: float = 0.05,
    radius: float = 0.012,
    cloth_control_bone: str = "Parent",
):
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=damping,
        stabilization_time_after_reset=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        radius=radius,
        collision_mode=collision_mode,
        collision_friction=friction,
        collision_limit_distance=0.03,
        max_distance_enabled=False,
        backstop_enabled=False,
        self_collision_mode=0,
        spring_enabled=False,
        wind_influence=0.0,
    )
    if spring:
        requests, _report = nodes.physicsMC2BoneSpringTask(
            [{
                "armature": armature,
                "root_bone": "Chain0_0",
                "bones": tuple(f"Chain0_{depth}" for depth in range(6)),
            }],
            profile=profile,
            collided_by_groups=1,
            teleport_mode=0,
        )
    else:
        requests, _report = nodes.physicsMC2BoneClothTask(
            [{"armature": armature, "bone": cloth_control_bone}],
            profile=profile,
            connection_mode=0,
            collided_by_groups=1,
            teleport_mode=0,
        )
    assert len(requests) == 1
    return requests[0]


def _friction_armature(name: str):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    obj.scale = (0.9, 0.9, 0.9)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    control = data.edit_bones.new("Control")
    control.head = (0.0, -0.12, 0.0)
    control.tail = (0.0, 0.0, 0.0)
    parent = control
    for index in range(5):
        bone = data.edit_bones.new("Root" if index == 0 else f"Bone{index}")
        bone.head = (0.0, index * 0.12, 0.02 * index)
        bone.tail = (0.015 * index, (index + 1) * 0.12, 0.02 * (index + 1))
        bone.parent = parent
        bone.use_connect = index > 0 and index != 3
        parent = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _colliders(armature, target, *, accepted: bool, spring: bool):
    target = tuple(float(value) for value in target)
    accepted_center = tuple(
        float(value) for value in (np.asarray(target, dtype=np.float64) + (0.018, 0.0, 0.0))
    )
    values = [
        {
            "key": "product-collision-accepted",
            "type": "SPHERE",
            "primary_group": 1 if accepted else 2,
            "center": accepted_center,
            "radius": 0.025,
        },
        {
            "key": "product-collision-owned",
            "owner": armature,
            "type": "SPHERE",
            "primary_group": 1,
            "center": target,
            "radius": 0.1,
        },
        {
            "key": "product-collision-masked",
            "type": "SPHERE",
            "primary_group": 2,
            "center": target,
            "radius": 0.1,
        },
    ]
    if spring:
        values.append({
            "key": "product-collision-spring-capsule",
            "type": "CAPSULE",
            "primary_group": 1,
            "center": target,
            "segment_a": tuple(float(value) for value in np.asarray(target) - (0.0, 0.1, 0.0)),
            "segment_b": tuple(float(value) for value in np.asarray(target) + (0.0, 0.1, 0.0)),
            "radius": 0.05,
        })
    return values


def _run_case(*, spring: bool, accepted: bool, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 970 + run_index
    armature = None
    digest = hashlib.sha256()
    max_normal = 0.0
    max_response = 0.0
    try:
        armature = product_soak._armature(
            f"MC2ProductCollision_{'Spring' if spring else 'Cloth'}_{run_index}_{int(accepted)}",
            chain_count=1,
            chain_length=6,
            x_offset=0.0,
        )
        request = _request(armature, spring=spring, friction=0.0)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        target = None
        initial = None
        for frame in range(1, 121):
            product_soak._set_frame(world, frame, generation)
            if target is None:
                world.collider_snapshot = {"frame": frame, "colliders": []}
            else:
                world.collider_snapshot = {
                    "frame": frame,
                    "colliders": _colliders(
                        armature,
                        target,
                        accepted=accepted,
                        spring=spring,
                    ),
                }
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
            owner = slot.data["owner"]
            output = owner.read_output()
            assert output.frame == frame and output.generation == generation
            assert np.all(np.isfinite(output.world_positions))
            if initial is None:
                initial = output.world_positions.copy()
                target = output.world_positions[min(2, output.world_positions.shape[0] - 1)].copy()
            response = float(np.max(np.linalg.norm(output.world_positions - initial, axis=1)))
            max_response = max(max_response, response)
            dynamics = owner.read_debug_state()
            normals = np.asarray(dynamics["world_normals"], dtype=np.float32)
            assert normals.shape == output.world_positions.shape
            assert np.all(np.isfinite(normals))
            max_normal = max(max_normal, float(np.max(np.linalg.norm(normals, axis=1))))
            if frame > 1:
                keys = tuple(slot.data["collider_frame"].collider_keys)
                assert "product-collision-owned" not in keys
                assert "product-collision-masked" in keys
                if spring:
                    assert "product-collision-spring-capsule" not in keys
                assert "product-collision-accepted" in keys
                digest.update(output.world_positions.tobytes())
                digest.update(normals.tobytes())
            assert writeback.writeback_bone_transforms(world) == output.world_positions.shape[0]
            bpy.context.view_layer.update()

        kernel = owner.inspect()["domain"]["kernel"]
        assert kernel["compiled_external_ready"] is True
        assert kernel["compiled_external_step_count"] >= 119
        if accepted:
            assert max_normal > 1.0e-5, (spring, accepted, max_normal)
            assert max_response > 1.0e-5, (spring, accepted, max_response)
        else:
            assert max_normal == 0.0, (spring, accepted, max_normal)
        return digest.hexdigest(), max_normal, max_response
    finally:
        world.omni_cache_dispose("bone_product_collision_soak_cleanup")
        product_soak._remove_armature(armature)


def _run_setup(*, spring: bool):
    rejected = _run_case(spring=spring, accepted=False, run_index=0)
    accepted = _run_case(spring=spring, accepted=True, run_index=1)
    repeat = _run_case(spring=spring, accepted=True, run_index=2)
    assert rejected[0] != accepted[0]
    assert accepted[0] == repeat[0]
    assert accepted[1] > rejected[1]
    print(
        "MC2_BONE_PRODUCT_COLLISION_RESULT",
        "bone_spring" if spring else "bone_cloth",
        "rejected_normal=%.9f" % rejected[1],
        "accepted_normal=%.9f" % accepted[1],
        "accepted_response=%.9f" % accepted[2],
    )


def _run_friction_case(friction: float, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 985 + run_index
    armature = None
    initial_basis = None
    lags = []
    max_normal = 0.0
    try:
        armature = _friction_armature(f"MC2ProductFriction_{run_index}")
        initial_basis = {
            bone.name: bone.matrix_basis.copy()
            for bone in armature.pose.bones
        }
        request = _request(
            armature,
            spring=False,
            friction=friction,
            collision_mode=1,
            damping=0.02,
            radius=0.02,
            cloth_control_bone="Control",
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        initial = None
        plane_z = None
        for frame in range(1, 601):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            armature.pose.bones["Root"].location.x = frame * 0.0002
            bpy.context.view_layer.update()
            product_soak._set_frame(world, frame, generation)
            if plane_z is None:
                world.collider_snapshot = {"frame": frame, "colliders": []}
            else:
                world.collider_snapshot = {
                    "frame": frame,
                    "colliders": [{
                        "key": "product-friction-plane",
                        "type": "PLANE",
                        "primary_group": 1,
                        "center": (0.0, 0.0, plane_z),
                        "normal": (0.0, 0.0, 1.0),
                    }],
                }
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
            owner = slot.data["owner"]
            output = owner.read_output()
            expected = slot.data["frame_packet"].animated_base_world_positions
            assert expected.shape == output.world_positions.shape
            assert np.all(np.isfinite(output.world_positions))
            if initial is None:
                initial = output.world_positions.copy()
                plane_z = float(initial[1, 2] - 0.015)
            else:
                lag = float(np.mean(expected[1:, 0] - output.world_positions[1:, 0]))
                if frame > 300:
                    lags.append(lag)
                normals = np.asarray(owner.read_debug_state()["world_normals"])
                max_normal = max(max_normal, float(np.max(np.linalg.norm(normals, axis=1))))
            assert writeback.writeback_bone_transforms(world) == output.world_positions.shape[0]
            bpy.context.view_layer.update()
        kernel = owner.inspect()["domain"]["kernel"]
        assert kernel["compiled_external_step_count"] >= 500, kernel
        assert max_normal > 1.0e-5
        return float(np.mean(lags)), float(lags[-1])
    finally:
        world.omni_cache_dispose("bone_product_friction_soak_cleanup")
        product_soak._remove_armature(armature)


def test_bone_product_friction_ordered_response():
    low_mean, low_final = _run_friction_case(0.0, 0)
    high_mean, high_final = _run_friction_case(0.5, 1)
    assert high_mean > low_mean + 0.02, (low_mean, high_mean)
    assert high_final > low_final + 0.02, (low_final, high_final)
    print(
        "MC2_BONE_PRODUCT_FRICTION_RESULT",
        "low_mean=%.9f" % low_mean,
        "high_mean=%.9f" % high_mean,
        "low_final=%.9f" % low_final,
        "high_final=%.9f" % high_final,
    )


def test_bone_product_collision_filter_response_deterministic():
    _run_setup(spring=False)
    _run_setup(spring=True)
    print("PASS test_bone_product_collision_filter_response_deterministic")


if __name__ == "__main__":
    test_bone_product_collision_filter_response_deterministic()
    test_bone_product_friction_ordered_response()
