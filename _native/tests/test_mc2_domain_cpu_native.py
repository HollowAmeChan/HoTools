"""Native E3 MC2 CPU domain data-path owner tests."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"),
))

import hotools_native  # noqa: E402


def _create(partition_count=1, particle_attributes=(0, 0, 0)):
    bind_positions = np.asarray(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        dtype=np.float32,
    )
    bind_rotations = np.asarray(
        ((0.0, 0.0, 0.0, 1.0),) * 3,
        dtype=np.float32,
    )
    bind_positions.flags.writeable = False
    bind_rotations.flags.writeable = False
    particle_partitions = np.asarray(
        (0, 0, 0) if partition_count == 1 else (0, 0, 1), dtype=np.uint32
    )
    particle_attributes = np.asarray(particle_attributes, dtype=np.uint32)
    return hotools_native.mc2_domain_cpu_v1_create(
        1,
        3,
        partition_count,
        "domain:test",
        "layout:test",
        bind_positions,
        bind_rotations,
        particle_partitions,
        particle_attributes,
        np.zeros((partition_count, 3), dtype=np.float32),
        np.asarray(((0.0, -1.0, 0.0),) * partition_count, dtype=np.float32),
    )


def _frame(offset=0.0):
    positions = np.asarray(
        ((offset, 0.0, 0.0), (1.0 + offset, 0.0, 0.0), (offset, 1.0, 0.0)),
        dtype=np.float32,
    )
    normals = np.asarray(((0.0, 0.0, 1.0),) * 3, dtype=np.float32)
    positions.flags.writeable = False
    normals.flags.writeable = False
    return positions, normals


def _update_frame(
    handle,
    positions,
    normals,
    *,
    frame,
    generation,
    domain_signature="domain:test",
    partition_positions=((0.0, 0.0, 0.0),),
    partition_flags=None,
    partition_rotations=None,
    partition_linear=None,
    particle_rotations=None,
    frame_delta_time=0.0,
    simulation_delta_time=0.0,
    time_scale=1.0,
    skip_count=0,
    is_running=False,
):
    count = len(partition_positions)
    if partition_flags is None:
        partition_flags = (0,) * count
    if partition_rotations is None:
        partition_rotations = ((0.0, 0.0, 0.0, 1.0),) * count
    if partition_linear is None:
        partition_linear = (np.eye(3, dtype=np.float32),) * count
    if particle_rotations is None:
        particle_rotations = ((0.0, 0.0, 0.0, 1.0),) * len(positions)
    return hotools_native.mc2_domain_cpu_v1_update_frame(
        handle,
        domain_signature,
        "layout:test",
        frame,
        generation,
        positions,
        np.asarray(particle_rotations, dtype=np.float32),
        normals,
        np.asarray(partition_positions, dtype=np.float32),
        np.asarray(partition_rotations, dtype=np.float32),
        np.ones((count, 3), dtype=np.float32),
        np.asarray(partition_linear, dtype=np.float32),
        np.zeros((count, 3), dtype=np.float32),
        np.asarray(((0.0, 0.0, 0.0, 1.0),) * count, dtype=np.float32),
        np.zeros(count, dtype=np.uint32),
        np.asarray(partition_flags, dtype=np.uint32),
        np.ones(count, dtype=np.float32),
        np.ones(count, dtype=np.float32),
        frame_delta_time,
        simulation_delta_time,
        time_scale,
        skip_count,
        is_running,
    )


def test_domain_cpu_native_lifecycle_and_owned_frame_output():
    before = hotools_native.mc2_domain_cpu_v1_stats()["live_domain_count"]
    handle = _create()
    assert hotools_native.mc2_domain_cpu_v1_stats()["live_domain_count"] == before + 1
    try:
        info = hotools_native.mc2_domain_cpu_v1_inspect(handle)
        assert info["particle_count"] == 3
        assert info["frame"] == -1
        np.testing.assert_allclose(
            info["partition_initial_local_gravity_directions"],
            ((0.0, -1.0, 0.0),),
        )
        positions, normals = _frame(2.0)
        expected_positions = positions.copy()
        _update_frame(
            handle,
            positions,
            normals,
            frame=8,
            generation=3,
            frame_delta_time=1.0 / 60.0,
            simulation_delta_time=1.0 / 90.0,
            time_scale=0.5,
            skip_count=2,
            is_running=True,
        )
        info = hotools_native.mc2_domain_cpu_v1_inspect(handle)
        assert info["frame_delta_time"] == np.float32(1.0 / 60.0)
        assert info["simulation_delta_time"] == np.float32(1.0 / 90.0)
        assert info["time_scale"] == np.float32(0.5)
        assert info["skip_count"] == 2
        assert info["is_running"] is True
        positions.flags.writeable = True
        positions[:] = -100.0
        hotools_native.mc2_domain_cpu_v1_step(handle)
        output = hotools_native.mc2_domain_cpu_v1_read(handle)
        assert output["frame"] == 8
        assert output["generation"] == 3
        assert output["step_count"] == 1
        assert output["backend_kind"] == "mc2_domain_cpu_v1_datapath"
        assert np.array_equal(output["world_positions"], expected_positions)
        assert np.array_equal(output["world_normals"], normals)
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)
        hotools_native.mc2_domain_cpu_v1_dispose(handle)
    assert hotools_native.mc2_domain_cpu_v1_stats()["live_domain_count"] == before


def test_domain_cpu_native_rejects_identity_without_mutating_published_frame():
    handle = _create()
    try:
        positions, normals = _frame(1.0)
        _update_frame(handle, positions, normals, frame=4, generation=2)
        bad_positions, bad_normals = _frame(9.0)
        try:
            _update_frame(
                handle, bad_positions, bad_normals,
                frame=5, generation=2, domain_signature="domain:wrong"
            )
        except ValueError as exc:
            assert "signature mismatch" in str(exc)
        else:
            raise AssertionError("mismatched domain signature was accepted")
        output = hotools_native.mc2_domain_cpu_v1_read(handle)
        assert output["frame"] == 4
        assert np.array_equal(output["world_positions"], positions)
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_rejects_particle_rotation_atomically():
    handle = _create()
    try:
        positions, normals = _frame(1.0)
        _update_frame(handle, positions, normals, frame=4, generation=2)
        bad_positions, bad_normals = _frame(9.0)
        try:
            _update_frame(
                handle,
                bad_positions,
                bad_normals,
                frame=5,
                generation=2,
                particle_rotations=((0.0, 0.0, 0.0, 0.0),) * 3,
            )
        except ValueError as exc:
            assert "world_rotations" in str(exc)
        else:
            raise AssertionError("non-unit particle rotations were accepted")
        output = hotools_native.mc2_domain_cpu_v1_read(handle)
        assert output["frame"] == 4
        np.testing.assert_allclose(output["world_positions"], positions)
        np.testing.assert_allclose(
            output["world_rotations_xyzw"],
            ((0.0, 0.0, 0.0, 1.0),) * 3,
        )
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_tracks_partition_history_atomically():
    handle = _create(partition_count=2)
    try:
        positions, normals = _frame(0.0)
        _update_frame(
            handle, positions, normals, frame=1, generation=1,
            partition_positions=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
            partition_flags=(0, 0),
        )
        _update_frame(
            handle, positions, normals, frame=2, generation=1,
            partition_positions=((1.0, 0.0, 0.0), (20.0, 0.0, 0.0)),
            partition_flags=(1, 2),
        )
        info = hotools_native.mc2_domain_cpu_v1_inspect(handle)
        np.testing.assert_array_equal(info["partition_reset_counts"], (1, 0))
        np.testing.assert_array_equal(info["partition_keep_counts"], (0, 1))
        np.testing.assert_allclose(
            info["partition_world_positions"],
            ((1.0, 0.0, 0.0), (20.0, 0.0, 0.0)),
        )
        try:
            _update_frame(
                handle, positions, normals, frame=3, generation=1,
                partition_positions=((99.0, 0.0, 0.0), (99.0, 0.0, 0.0)),
                partition_flags=(3, 0),
            )
        except ValueError as exc:
            assert "partition frame values" in str(exc)
        else:
            raise AssertionError("invalid partition flags were accepted")
        after = hotools_native.mc2_domain_cpu_v1_inspect(handle)
        assert after["frame"] == 2
        np.testing.assert_array_equal(after["partition_reset_counts"], (1, 0))
        np.testing.assert_array_equal(after["partition_keep_counts"], (0, 1))
        np.testing.assert_allclose(
            after["partition_world_positions"], info["partition_world_positions"]
        )
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_preserves_state_and_resets_one_partition():
    handle = _create(partition_count=2, particle_attributes=(1, 0, 0))
    try:
        positions, normals = _frame(0.0)
        _update_frame(
            handle, positions, normals, frame=1, generation=1,
            partition_positions=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        )
        zeros = np.zeros(3, dtype=np.float32)
        hotools_native.mc2_domain_cpu_v1_configure_inertia(
            handle, zeros, np.ones(3, dtype=np.float32)
        )
        hotools_native.mc2_domain_cpu_v1_configure_integration(handle, zeros)
        hotools_native.mc2_domain_cpu_v1_step_integration(
            handle, 0.5, 1.0, 1.0,
            np.asarray((2.0, 0.0, 0.0), dtype=np.float32),
        )
        moved = hotools_native.mc2_domain_cpu_v1_read(handle)["world_positions"].copy()
        next_positions, next_normals = _frame(10.0)
        _update_frame(
            handle, next_positions, next_normals, frame=2, generation=1,
            partition_positions=((1.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
            partition_flags=(0, 1),
        )
        output = hotools_native.mc2_domain_cpu_v1_read(handle)["world_positions"]
        np.testing.assert_allclose(output[0], next_positions[0])
        np.testing.assert_allclose(output[1], moved[1])
        np.testing.assert_allclose(output[2], next_positions[2])
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_applies_keep_pose_to_one_partition():
    handle = _create(partition_count=2, particle_attributes=(1, 0, 0))
    try:
        positions, normals = _frame(0.0)
        _update_frame(
            handle, positions, normals, frame=1, generation=1,
            partition_positions=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        )
        zeros = np.zeros(3, dtype=np.float32)
        hotools_native.mc2_domain_cpu_v1_configure_inertia(
            handle, zeros, np.asarray((0.0, 1.0, 1.0), dtype=np.float32)
        )
        hotools_native.mc2_domain_cpu_v1_configure_integration(handle, zeros)
        hotools_native.mc2_domain_cpu_v1_step_integration(
            handle, 1.0, 1.0, 1.0,
            np.asarray((1.0, 0.0, 0.0), dtype=np.float32),
        )
        before_keep = hotools_native.mc2_domain_cpu_v1_read(handle)[
            "world_positions"
        ].copy()
        half = np.float32(np.sqrt(0.5))
        rotation = (0.0, 0.0, float(half), float(half))
        linear = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        next_positions, next_normals = _frame(5.0)
        _update_frame(
            handle, next_positions, next_normals, frame=2, generation=1,
            partition_positions=((5.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            partition_flags=(2, 0),
            partition_rotations=(rotation, (0.0, 0.0, 0.0, 1.0)),
            partition_linear=(linear, np.eye(3, dtype=np.float32)),
        )
        after_keep = hotools_native.mc2_domain_cpu_v1_read(handle)[
            "world_positions"
        ].copy()
        after_keep_rotations = hotools_native.mc2_domain_cpu_v1_read(handle)[
            "world_rotations_xyzw"
        ]
        np.testing.assert_allclose(after_keep[0], next_positions[0], atol=1e-6)
        np.testing.assert_allclose(after_keep[1], (5.0, 2.0, 0.0), atol=1e-6)
        np.testing.assert_allclose(after_keep[2], before_keep[2], atol=1e-6)
        np.testing.assert_allclose(after_keep_rotations[1], rotation, atol=1e-6)
        np.testing.assert_allclose(
            after_keep_rotations[2], (0.0, 0.0, 0.0, 1.0), atol=1e-6
        )
        hotools_native.mc2_domain_cpu_v1_step_integration(
            handle, 1.0, 1.0, 1.0, np.zeros(3, dtype=np.float32)
        )
        after_velocity = hotools_native.mc2_domain_cpu_v1_read(handle)[
            "world_positions"
        ]
        np.testing.assert_allclose(after_velocity[1], (5.0, 3.0, 0.0), atol=1e-5)
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_requires_frame_before_step():
    handle = _create()
    try:
        try:
            hotools_native.mc2_domain_cpu_v1_step(handle)
        except RuntimeError as exc:
            assert "requires update_frame" in str(exc)
        else:
            raise AssertionError("step without frame was accepted")
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_distance_slice_uses_existing_kernel():
    handle = _create()
    try:
        positions = np.asarray(
            ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (4.0, 0.0, 0.0)),
            dtype=np.float32,
        )
        normals = np.asarray(((0.0, 0.0, 1.0),) * 3, dtype=np.float32)
        positions.flags.writeable = False
        normals.flags.writeable = False
        _update_frame(handle, positions, normals, frame=1, generation=1)
        starts = np.asarray((0, 1, 3), dtype=np.int32)
        counts = np.asarray((1, 2, 1), dtype=np.int32)
        neighbors = np.asarray((1, 0, 2, 1), dtype=np.int32)
        rest = np.ones(4, dtype=np.float32)
        stiffness = np.ones(4, dtype=np.float32)
        for array in (starts, counts, neighbors, rest, stiffness):
            array.flags.writeable = False
        hotools_native.mc2_domain_cpu_v1_configure_distance(
            handle, starts, counts, neighbors, rest, stiffness
        )
        hotools_native.mc2_domain_cpu_v1_step_distance(handle)
        output = hotools_native.mc2_domain_cpu_v1_read(handle)
        assert np.allclose(
            output["world_positions"],
            np.asarray(
                ((0.5, 0.0, 0.0), (2.125, 0.0, 0.0), (3.5625, 0.0, 0.0)),
                dtype=np.float32,
            ),
        )
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_inertia_slice_uses_existing_kernel():
    handle = _create()
    try:
        positions, normals = _frame(0.0)
        _update_frame(handle, positions, normals, frame=2, generation=1)
        depths = np.asarray((0.0, 0.5, 1.0), dtype=np.float32)
        inv_masses = np.ones(3, dtype=np.float32)
        hotools_native.mc2_domain_cpu_v1_configure_inertia(handle, depths, inv_masses)
        vectors = [
            np.asarray((0.0, 0.0, 0.0), dtype=np.float32),
            np.asarray((1.0, 0.0, 0.0), dtype=np.float32),
            np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32),
            np.asarray((0.0, 0.0, 0.0), dtype=np.float32),
            np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32),
        ]
        hotools_native.mc2_domain_cpu_v1_step_inertia(
            handle, *vectors, 1.0
        )
        output = hotools_native.mc2_domain_cpu_v1_read(handle)
        assert np.isclose(output["world_positions"][0, 0], 1.0)
        assert np.isclose(output["world_positions"][1, 0], 1.6464466, atol=1e-5)
        assert np.isclose(output["world_positions"][2, 0], 0.0)
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_integration_slice_uses_shared_kernel():
    handle = _create()
    try:
        positions, normals = _frame(0.0)
        _update_frame(handle, positions, normals, frame=3, generation=1)
        depths = np.zeros(3, dtype=np.float32)
        inv_masses = np.asarray((0.0, 1.0, 1.0), dtype=np.float32)
        damping = np.zeros(3, dtype=np.float32)
        hotools_native.mc2_domain_cpu_v1_configure_inertia(
            handle, depths, inv_masses
        )
        hotools_native.mc2_domain_cpu_v1_configure_integration(handle, damping)
        hotools_native.mc2_domain_cpu_v1_step_integration(
            handle,
            0.5,
            1.0,
            1.0,
            np.asarray((0.0, -2.0, 0.0), dtype=np.float32),
        )
        output = hotools_native.mc2_domain_cpu_v1_read(handle)
        assert np.array_equal(output["world_positions"][0], positions[0])
        np.testing.assert_allclose(
            output["world_positions"][1:],
            positions[1:] + np.asarray((0.0, -0.5, 0.0), dtype=np.float32),
        )
        damping.fill(0.5)
        hotools_native.mc2_domain_cpu_v1_configure_integration(handle, damping)
        hotools_native.mc2_domain_cpu_v1_step_integration(
            handle,
            0.5,
            1.0,
            1.0,
            np.zeros(3, dtype=np.float32),
        )
        output = hotools_native.mc2_domain_cpu_v1_read(handle)
        np.testing.assert_allclose(
            output["world_positions"][1:],
            positions[1:] + np.asarray((0.0, -0.75, 0.0), dtype=np.float32),
        )
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_center_slice_uses_partition_history():
    handle = _create()
    try:
        zeros = np.zeros(1, dtype=np.float32)
        limits = np.full(1, -1.0, dtype=np.float32)
        gravity = np.asarray((5.0,), dtype=np.float32)
        gravity_direction = np.asarray(((0.0, -1.0, 0.0),), dtype=np.float32)
        falloff = np.zeros(1, dtype=np.float32)
        stabilization = np.zeros(1, dtype=np.float32)
        blend = np.ones(1, dtype=np.float32)
        hotools_native.mc2_domain_cpu_v1_configure_center(
            handle,
            np.asarray((0.5,), dtype=np.float32),
            limits,
            limits,
            gravity,
            gravity_direction,
            falloff,
            stabilization,
            blend,
        )
        positions, normals = _frame(0.0)
        _update_frame(handle, positions, normals, frame=1, generation=1)
        next_positions, next_normals = _frame(2.0)
        _update_frame(
            handle,
            next_positions,
            next_normals,
            frame=2,
            generation=1,
            partition_positions=((2.0, 0.0, 0.0),),
        )
        hotools_native.mc2_domain_cpu_v1_step_center(
            handle,
            1.0,
            1.0,
            np.ones(1, dtype=np.float32),
        )
        info = hotools_native.mc2_domain_cpu_v1_inspect(handle)
        np.testing.assert_allclose(info["center_step_vectors"], ((2.0, 0.0, 0.0),))
        np.testing.assert_allclose(info["center_inertia_vectors"], ((1.0, 0.0, 0.0),))
        assert info["center_step_count"] == 1
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_center_pose_uses_fixed_particle_frame():
    handle = _create(partition_count=1, particle_attributes=(1, 0, 0))
    try:
        positions, normals = _frame(4.0)
        _update_frame(
            handle,
            positions,
            normals,
            frame=1,
            generation=1,
            partition_positions=((100.0, 0.0, 0.0),),
        )
        info = hotools_native.mc2_domain_cpu_v1_inspect(handle)
        np.testing.assert_allclose(
            info["center_frame_world_positions"], ((4.0, 0.0, 0.0),)
        )
        np.testing.assert_allclose(
            info["center_frame_world_rotations"], ((0.0, 0.0, 0.0, 1.0),)
        )
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


if __name__ == "__main__":
    tests = sorted(
        (name, value)
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"MC2 native CPU domain: {len(tests)} passed")
