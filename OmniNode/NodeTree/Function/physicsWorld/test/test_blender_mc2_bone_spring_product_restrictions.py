"""BoneSpring 产品包装层的强制关闭输入隔离门禁。"""

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


def _profile(*, hostile: bool):
    return parameters.make_mc2_particle_profile(
        gravity=19.0 if hostile else 0.0,
        gravity_direction=(0.0, 0.0, -1.0),
        gravity_falloff=0.0,
        damping=0.03,
        stabilization_time_after_reset=0.0,
        particle_speed_limit=6.0,
        radius=0.02,
        tether_compression=0.8,
        distance_stiffness=0.5,
        bending_stiffness=1.0 if hostile else 0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        max_distance_enabled=hostile,
        max_distance=0.75 if hostile else 0.01,
        backstop_enabled=hostile,
        backstop_radius=0.2 if hostile else 0.01,
        backstop_distance=0.15 if hostile else 0.01,
        motion_stiffness=1.0 if hostile else 0.0,
        collision_mode=1,
        self_collision_mode=2 if hostile else 0,
        self_collision_sync_mode=2 if hostile else 0,
        self_collision_thickness=0.05 if hostile else 0.001,
        spring_enabled=False,
        wind_influence=0.0,
    )


def _request(armature, *, hostile: bool):
    profile = _profile(hostile=hostile)
    requests, _report = nodes.physicsMC2BoneSpringTask(
        [{
            "armature": armature,
            "root_bone": "Chain0_0",
            "bones": tuple(f"Chain0_{depth}" for depth in range(6)),
        }],
        profile=profile,
        teleport_mode=0,
    )
    assert len(requests) == 1
    partition_profile = requests[0].plan.active_partitions[0].profile
    assert partition_profile.gravity == profile.gravity
    assert partition_profile.bending_stiffness == profile.bending_stiffness
    assert partition_profile.max_distance_enabled is hostile
    assert partition_profile.max_distance.value == (0.75 if hostile else 0.01)
    assert partition_profile.backstop_enabled is hostile
    assert partition_profile.backstop_radius == (0.2 if hostile else 0.01)
    assert partition_profile.backstop_distance.value == (0.15 if hostile else 0.01)
    assert partition_profile.motion_stiffness == (1.0 if hostile else 0.0)
    assert partition_profile.self_collision_mode == (2 if hostile else 0)
    assert partition_profile.self_collision_sync_mode == (2 if hostile else 0)
    return requests[0]


def _table_row(table) -> dict[str, float | int]:
    return {
        name: table.values[0, index].item()
        for index, name in enumerate(table.fields)
    }


def _assert_compiled_restrictions(owner) -> tuple[np.ndarray, ...]:
    compiled = owner.compiled
    program = compiled.program
    assert program.setup_type == "bone_spring"
    assert "self_collision" not in program.required_capabilities
    assert not program.primitive_tables
    assert "bending" not in {table.kind for table in program.constraint_tables}

    floats = _table_row(compiled.parameters.partition_parameters)
    uints = _table_row(compiled.parameters.partition_uint_parameters)
    particle = compiled.parameters.particle_parameters
    particle_fields = {
        name: index for index, name in enumerate(particle.fields)
    }
    assert floats["gravity"] == 0.0
    assert floats["bending_stiffness"] == 0.0
    assert floats["backstop_radius"] == 0.0
    assert floats["motion_stiffness"] == 0.0
    assert uints["bending_method"] == 0
    assert uints["use_max_distance"] == 0
    assert uints["use_backstop"] == 0
    assert uints["self_collision_mode"] == 0
    assert uints["self_collision_sync_mode"] == 0
    for field in (
        "max_distance",
        "backstop_distance",
        "self_collision_thickness",
    ):
        np.testing.assert_array_equal(
            particle.values[:, particle_fields[field]],
            0.0,
        )
    return (
        np.array(compiled.parameters.partition_parameters.values, copy=True),
        np.array(compiled.parameters.partition_uint_parameters.values, copy=True),
        np.array(compiled.parameters.particle_parameters.values, copy=True),
    )


def _run(*, hostile: bool, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 3700 + run_index
    armature = None
    owner = None
    effective = None
    digest = hashlib.sha256()
    trajectory = []
    try:
        armature = product_soak._armature(
            f"MC2ProductSpringRestrictions_{run_index}",
            chain_count=1,
            chain_length=6,
            x_offset=0.0,
        )
        initial_basis = {
            bone.name: bone.matrix_basis.copy()
            for bone in armature.pose.bones
        }
        request = _request(armature, hostile=hostile)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        for frame in range(1, 601):
            for bone in armature.pose.bones:
                bone.matrix_basis = initial_basis[bone.name].copy()
            root = armature.pose.bones["Chain0_0"]
            root.rotation_mode = "XYZ"
            root.rotation_euler.x = 0.5 * math.sin(frame * 0.09)
            root.rotation_euler.z = 0.7 * math.sin(frame * 0.12)
            bpy.context.view_layer.update()
            product_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = owner is not None and frame in (2, 600)
            if capture:
                owner.begin_constraint_debug(64)
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
                effective = _assert_compiled_restrictions(owner)
            else:
                assert current_owner is owner
            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            positions = np.array(output.world_positions, copy=True)
            trajectory.append(positions)
            digest.update(positions.tobytes())
            if capture:
                owner.end_constraint_debug()
                self_debug = owner.read_constraint_debug_state()[
                    "whole_domain_self_results"
                ]
                assert self_debug["point_primitive_count"] == 0
                assert self_debug["edge_primitive_count"] == 0
                assert self_debug["triangle_primitive_count"] == 0
                assert not np.asarray(self_debug["contact_types"]).size
            assert writeback.writeback_bone_transforms(world) == len(positions)
            bpy.context.view_layer.update()

        assert owner is not None and effective is not None
        kernel = owner.inspect()["domain"]["kernel"]
        assert kernel.get("whole_domain_self_point_count", 0) == 0
        assert kernel.get("whole_domain_self_edge_count", 0) == 0
        assert kernel.get("whole_domain_self_triangle_count", 0) == 0
        assert kernel.get("whole_domain_self_last_candidate_count", 0) == 0
        assert kernel.get("whole_domain_self_last_contact_count", 0) == 0
        assert kernel.get("bending_solve_count", 0) == 0
        return (
            digest.hexdigest(),
            np.asarray(trajectory, dtype=np.float32),
            effective,
            int(kernel.get("whole_domain_self_step_count", 0)),
        )
    finally:
        world.omni_cache_dispose("bone_spring_product_restrictions_cleanup")
        product_soak._remove_armature(armature)


def test_bone_spring_disabled_inputs_are_isolated_deterministically():
    quiet_first = _run(hostile=False, run_index=0)
    quiet_second = _run(hostile=False, run_index=1)
    hostile_first = _run(hostile=True, run_index=2)
    hostile_second = _run(hostile=True, run_index=3)
    for first, second in (
        (quiet_first, quiet_second),
        (hostile_first, hostile_second),
    ):
        assert first[0] == second[0]
        np.testing.assert_array_equal(first[1], second[1])
        for left, right in zip(first[2], second[2]):
            np.testing.assert_array_equal(left, right)
        assert first[3] == second[3]
    assert quiet_first[0] == hostile_first[0]
    np.testing.assert_array_equal(quiet_first[1], hostile_first[1])
    for quiet, hostile in zip(quiet_first[2], hostile_first[2]):
        np.testing.assert_array_equal(quiet, hostile)
    assert quiet_first[3] == hostile_first[3]
    print(
        "MC2_BONE_SPRING_RESTRICTIONS",
        quiet_first[0],
        quiet_first[3],
    )
    print("PASS test_bone_spring_disabled_inputs_are_isolated_deterministically")


if __name__ == "__main__":
    test_bone_spring_disabled_inputs_are_isolated_deterministically()
