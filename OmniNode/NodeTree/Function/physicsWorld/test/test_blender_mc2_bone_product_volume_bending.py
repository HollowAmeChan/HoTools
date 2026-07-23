"""BoneCloth 产品域的 signed-volume Bending 长程门禁。"""

from __future__ import annotations

import hashlib
import math
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


def _folded_armature(name: str):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    parent = data.edit_bones.new("Parent")
    parent.head = (0.0, 0.0, 0.0)
    parent.tail = (0.0, 0.0, 0.32)
    for chain_index in range(2):
        previous = parent
        x = -0.08 if chain_index == 0 else 0.08
        for depth in range(6):
            z = 0.4
            if chain_index == 1 and depth % 2:
                z += 0.24
            bone = data.edit_bones.new(f"Chain{chain_index}_{depth}")
            bone.head = (x, depth * 0.12, z)
            bone.tail = (x, depth * 0.12 + 0.055, z + 0.015)
            bone.parent = previous
            bone.use_connect = False
            previous = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    bpy.context.view_layer.update()
    return obj


def _profile():
    return parameters.make_mc2_particle_profile(
        gravity=1.5,
        gravity_direction=(0.0, 0.0, -1.0),
        damping=0.04,
        stabilization_time_after_reset=0.0,
        particle_speed_limit=6.0,
        radius=0.02,
        tether_compression=0.35,
        distance_stiffness=0.85,
        bending_stiffness=1.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        max_distance_enabled=False,
        backstop_enabled=False,
        collision_mode=0,
        self_collision_mode=0,
        spring_enabled=False,
        wind_influence=0.0,
    )


def _request(armature):
    requests, _report = nodes.physicsMC2BoneClothTask(
        [{"armature": armature, "bone": "Parent"}],
        profile=_profile(),
        connection_mode=1,
        cloth_mass=0.4,
        teleport_mode=0,
    )
    assert len(requests) == 1
    return requests[0]


def _volume_contract(owner):
    topology = next(
        table
        for table in owner.compiled.program.constraint_tables
        if table.kind == "bending"
    )
    parameters_table = next(
        table
        for table in owner.compiled.parameters.constraint_parameters
        if table.name == "bending"
    )
    volume_mask = np.asarray(topology.flags, dtype=np.uint32) == 100
    assert np.any(volume_mask)
    rest_index = parameters_table.fields.index("rest_value")
    rest = np.asarray(
        parameters_table.values[:, rest_index], dtype=np.float32
    )[volume_mask]
    assert np.all(np.isfinite(rest))
    assert np.all(np.abs(rest) > 1.0e-5)
    quads = np.asarray(topology.indices, dtype=np.int32)[volume_mask]
    assert quads.shape[1] == 4
    return np.array(quads, copy=True), np.array(rest, copy=True)


def _signed_volumes(positions, quads):
    points = np.asarray(positions, dtype=np.float32)[quads]
    cross = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    return (
        np.einsum("ij,ij->i", cross, points[:, 3] - points[:, 0])
        * np.float32(1000.0 / 6.0)
    ).astype(np.float32)


def _run(run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 3800 + run_index
    armature = None
    owner = None
    volume_quads = None
    rest_volumes = None
    digest = hashlib.sha256()
    max_relative_error = 0.0
    min_relative_magnitude = math.inf
    debug_samples = []
    try:
        armature = _folded_armature(f"MC2ProductVolumeBending_{run_index}")
        initial_basis = {
            bone.name: bone.matrix_basis.copy()
            for bone in armature.pose.bones
        }
        request = _request(armature)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        for frame in range(1, 601):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            driven = armature.pose.bones["Chain0_0"]
            driven.rotation_mode = "XYZ"
            driven.rotation_euler.x = 0.18 * math.sin(frame * 0.07)
            driven.rotation_euler.z = 0.12 * math.sin(frame * 0.11)
            driven.location.z = 0.012 * math.sin(frame * 0.09)
            bpy.context.view_layer.update()
            product_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = frame in (2, 300, 600)
            if capture:
                assert owner is not None
                owner.begin_constraint_debug(16)
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
                volume_quads, rest_volumes = _volume_contract(owner)
            else:
                assert current_owner is owner

            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            volumes = _signed_volumes(output.world_positions, volume_quads)
            assert np.all(np.isfinite(volumes))
            assert np.all(volumes * rest_volumes > 0.0), (frame, volumes, rest_volumes)
            relative_magnitude = np.abs(volumes / rest_volumes)
            relative_error = np.abs((volumes - rest_volumes) / rest_volumes)
            min_relative_magnitude = min(
                min_relative_magnitude,
                float(np.min(relative_magnitude)),
            )
            max_relative_error = max(
                max_relative_error,
                float(np.max(relative_error)),
            )
            assert min_relative_magnitude >= 0.2, (
                frame,
                min_relative_magnitude,
            )
            assert max_relative_error <= 0.8, (
                frame,
                max_relative_error,
            )
            digest.update(output.world_positions.tobytes())
            digest.update(volumes.tobytes())

            if capture:
                owner.end_constraint_debug()
                bending = owner.read_constraint_debug_state()["bending_results"]
                valid = np.asarray(bending["valid"], dtype=np.uint8).astype(bool)
                kinds = np.asarray(bending["kinds"], dtype=np.int8)
                volume_valid = valid & (kinds == 1)
                hits = np.asarray(bending["hit"], dtype=np.uint8).astype(bool)
                currents = np.asarray(bending["currents"], dtype=np.float32)
                rests = np.asarray(bending["rests"], dtype=np.float32)
                corrections = np.asarray(
                    bending["corrections"], dtype=np.float32
                ).reshape((-1, 12))
                assert np.any(volume_valid)
                assert np.all(currents[volume_valid] * rests[volume_valid] > 0.0)
                debug_samples.append((
                    int(np.count_nonzero(volume_valid)),
                    int(np.count_nonzero(hits & volume_valid)),
                    float(np.max(np.linalg.norm(
                        corrections[volume_valid], axis=1
                    ))),
                ))
                digest.update(currents[volume_valid].tobytes())
                digest.update(rests[volume_valid].tobytes())
            assert writeback.writeback_bone_transforms(world) == len(
                output.world_positions
            )
            bpy.context.view_layer.update()

        assert owner is not None and len(debug_samples) == 3
        assert max(sample[1] for sample in debug_samples) > 0
        assert max(sample[2] for sample in debug_samples) > 0.0
        return (
            digest.hexdigest(),
            max_relative_error,
            min_relative_magnitude,
            tuple(debug_samples),
            np.array(rest_volumes, copy=True),
        )
    finally:
        world.omni_cache_dispose("bone_product_volume_bending_cleanup")
        product_soak._remove_armature(armature)


def test_bone_product_signed_volume_bending_is_stable_deterministically():
    first = _run(0)
    second = _run(1)
    assert first[0] == second[0]
    assert first[1:4] == second[1:4]
    np.testing.assert_array_equal(first[4], second[4])
    print(
        "MC2_BONE_PRODUCT_VOLUME_BENDING",
        first[0],
        first[1],
        first[2],
        first[3],
        first[4],
    )
    print(
        "PASS test_bone_product_signed_volume_bending_is_stable_deterministically"
    )


if __name__ == "__main__":
    test_bone_product_signed_volume_bending_is_stable_deterministically()
