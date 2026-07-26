"""MeshCloth 产品域 Triangle Bending 的长程数值闸门。"""

from __future__ import annotations

import hashlib
import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_mesh_product_constraint_soak as mesh_soak


mixed = mesh_soak.mixed
nodes = mesh_soak.nodes
parameters = mesh_soak.parameters
product_slot = mesh_soak.product_slot
world_types = mesh_soak.world_types
physics_blender = mesh_soak.physics_blender


def _request(world, mesh, stiffness: float):
    return mesh_soak._request(
        world,
        mesh,
        gravity_direction=(0.0, 0.0, -1.0),
        gravity_falloff=0.0,
        gravity=8.0,
        distance_stiffness=0.8,
        bending_stiffness=stiffness,
        collision_mode=0,
    )


def _curvature(positions: np.ndarray) -> float:
    rows = np.asarray(positions, dtype=np.float32)[:, 2].reshape((4, 4))
    return float(np.mean(np.abs(rows[:-2] - 2.0 * rows[1:-1] + rows[2:])))


def _run(stiffness: float, run_index: int):
    world = world_types.PhysicsWorldCache()
    mesh = proxy = None
    owner = None
    fixed = None
    base = None
    digest = hashlib.sha256()
    trajectory = []
    debug_samples = []
    generation = 4100 + run_index
    try:
        physics_blender.register()
        mesh, proxy = mixed._mesh_object(
            f"MC2ProductMeshBending_{stiffness:g}_{run_index}"
        )
        request = _request(world, mesh, stiffness)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        for frame in range(1, 901):
            mesh_soak.bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = frame in (2, 450, 900)
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
                assert owner.compiled.program.particle_count == 16
                bending_table = next(
                    table
                    for table in owner.compiled.program.constraint_tables
                    if table.kind == "bending"
                )
                flags = np.asarray(bending_table.flags, dtype=np.int32)
                assert flags.size > 0
                assert np.all(flags == 0)
                assert np.all(
                    np.asarray(bending_table.indices, dtype=np.int32).shape
                    == (flags.size, 4)
                )
                parameter_table = next(
                    table
                    for table in owner.compiled.parameters.constraint_parameters
                    if table.name == "bending"
                )
                stiffness_column = parameter_table.fields.index("stiffness")
                np.testing.assert_allclose(
                    np.asarray(parameter_table.values)[:, stiffness_column],
                    stiffness,
                    rtol=0.0,
                    atol=1.0e-7,
                )
                fixed = (
                    np.asarray(owner.compiled.program.particle_attribute_flags)
                    & 1
                ) != 0
                assert np.any(fixed)
                base = owner.prepare_step_basic_pose()["positions"].copy()
            else:
                assert current_owner is owner
            output = owner.read_output()
            positions = np.asarray(output.world_positions, dtype=np.float32).copy()
            assert np.all(np.isfinite(positions))
            np.testing.assert_allclose(positions[fixed], base[fixed], atol=1.0e-4)
            trajectory.append(positions)
            digest.update(positions.tobytes())
            if capture:
                owner.end_constraint_debug()
                bending = owner.read_constraint_debug_state()["bending_results"]
                valid = np.asarray(bending["valid"], dtype=np.uint8).astype(bool)
                hits = np.asarray(bending["hit"], dtype=np.uint8).astype(bool)
                kinds = np.asarray(bending["kinds"], dtype=np.int8)
                stiffnesses = np.asarray(bending["stiffnesses"], dtype=np.float32)
                corrections = np.asarray(
                    bending["corrections"], dtype=np.float32
                ).reshape((-1, 12))
                assert np.all(np.isin(kinds[valid], (0,)))
                np.testing.assert_allclose(
                    stiffnesses[valid], stiffness, rtol=0.0, atol=1.0e-7
                )
                if stiffness == 0.0:
                    assert not np.any(hits & valid)
                    np.testing.assert_allclose(
                        corrections[valid], 0.0, rtol=0.0, atol=1.0e-7
                    )
                else:
                    assert np.any(valid)
                    assert np.any(hits & valid)
                    assert float(
                        np.max(np.linalg.norm(corrections[valid], axis=1))
                    ) > 0.0
                correction_max = (
                    float(np.max(np.linalg.norm(corrections[valid], axis=1)))
                    if np.any(valid)
                    else 0.0
                )
                debug_samples.append(
                    (
                        int(np.count_nonzero(valid)),
                        int(np.count_nonzero(hits & valid)),
                        correction_max,
                    )
                )
                digest.update(stiffnesses.tobytes())
                digest.update(corrections.tobytes())
        assert owner is not None and len(debug_samples) == 3
        return (
            digest.hexdigest(),
            np.asarray(trajectory, dtype=np.float32),
            _curvature(trajectory[-1]),
            tuple(debug_samples),
        )
    finally:
        world.omni_cache_dispose("mesh_product_bending_cleanup")
        mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_bending_numeric_deterministic() -> None:
    soft = _run(0.0, 0)
    stiff = _run(1.0, 1)
    soft_repeat = _run(0.0, 2)
    stiff_repeat = _run(1.0, 3)
    assert soft[0] == soft_repeat[0]
    assert stiff[0] == stiff_repeat[0]
    np.testing.assert_array_equal(soft[1], soft_repeat[1])
    np.testing.assert_array_equal(stiff[1], stiff_repeat[1])
    assert np.all(np.isfinite(soft[1])) and np.all(np.isfinite(stiff[1]))
    assert max(soft[2], stiff[2]) < 0.02
    trajectory_delta = float(np.max(np.abs(stiff[1] - soft[1])))
    assert trajectory_delta > 1.0e-6
    assert all(sample[1] == 0 for sample in soft[3])
    assert max(sample[1] for sample in stiff[3]) > 0
    print(
        "MC2_MESH_PRODUCT_BENDING",
        soft[0],
        stiff[0],
        soft[2],
        stiff[2],
        trajectory_delta,
    )
    print("MC2_MESH_PRODUCT_BENDING_DEBUG", soft[3], stiff[3])
    print("PASS test_mesh_product_bending_numeric_deterministic")


if __name__ == "__main__":
    test_mesh_product_bending_numeric_deterministic()
