"""Strict XPBD nanobind context tests shared by Python 3.11 and 3.13."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
PACKAGE_DIR = Path(os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    ROOT / "_Lib" / PY_LIB / "HotoolsPackage",
))
sys.path.insert(0, str(PACKAGE_DIR))

import hotools_native


F32 = np.float32
I32 = np.int32


def _empty_colliders():
    return (
        np.empty((0,), dtype=I32),
        np.empty((0,), dtype=I32),
        np.empty((0, 3), dtype=F32),
        np.empty((0, 3), dtype=F32),
        np.empty((0, 3), dtype=F32),
        np.empty((0,), dtype=F32),
    )


def _context(*, compliance=0.0, iterations=2):
    return hotools_native.mesh_xpbd_create_context_v1(
        np.asarray(((0, 0, 0), (1, 0, 0)), dtype=F32),
        np.asarray((0, 1), dtype=F32),
        np.asarray(((0, 1),), dtype=I32),
        np.empty((0, 2), dtype=I32),
        np.zeros((2,), dtype=F32),
        0.0,
        compliance,
        0.0,
        iterations,
    )


def _step(context, *, mask=0, colliders=None):
    collider_values = _empty_colliders() if colliders is None else colliders
    return context.step(
        1.0,
        1,
        np.zeros((3,), dtype=F32),
        0.0,
        *collider_values,
        mask,
    )


def test_accumulated_lambda_distinguishes_strict_xpbd_from_pbd_projection():
    context = _context(compliance=1.0, iterations=2)
    context.reset(np.asarray(((0, 0, 0), (2, 0, 0)), dtype=F32))
    positions = _step(context)
    np.testing.assert_allclose(positions[1], (1.5, 0.0, 0.0), atol=1.0e-6)
    assert positions[1, 0] != np.float32(1.25)


def test_zero_compliance_is_a_hard_distance_constraint():
    context = _context(compliance=0.0, iterations=2)
    context.reset(np.asarray(((0, 0, 0), (2, 0, 0)), dtype=F32))
    positions = _step(context)
    np.testing.assert_allclose(positions[1], (1.0, 0.0, 0.0), atol=1.0e-6)


def test_bend_uses_its_own_strict_xpbd_lambda_array():
    context = hotools_native.mesh_xpbd_create_context_v1(
        np.asarray(((0, 0, 0), (1, 0, 0)), dtype=F32),
        np.asarray((0, 1), dtype=F32),
        np.empty((0, 2), dtype=I32),
        np.asarray(((0, 1),), dtype=I32),
        np.zeros((2,), dtype=F32),
        0.0,
        0.0,
        1.0,
        2,
    )
    context.reset(np.asarray(((0, 0, 0), (2, 0, 0)), dtype=F32))
    positions = _step(context)
    np.testing.assert_allclose(positions[1], (1.5, 0.0, 0.0), atol=1.0e-6)
    assert context.stats()["bend_constraint_count"] == 1


def test_reference_update_rebuilds_lengths_and_gravity_direction_is_normalized():
    context = _context(compliance=0.0, iterations=1)
    context.update_reference(
        np.asarray(((0, 0, 0), (2, 0, 0)), dtype=F32),
        np.asarray((0, 1), dtype=F32),
        np.zeros((2,), dtype=F32),
    )
    context.reset(np.asarray(((0, 0, 0), (3, 0, 0)), dtype=F32))
    positions = _step(context)
    np.testing.assert_allclose(positions[1], (2, 0, 0), atol=1.0e-6)
    assert context.stats()["reference_update_count"] == 1

    particle = _particle_context((0, 0, 0))
    positions = particle.step(
        0.5,
        1,
        np.asarray((0, 0, -2), dtype=F32),
        4.0,
        *_empty_colliders(),
        0,
    )
    np.testing.assert_allclose(positions[0], (0, 0, -1), atol=1.0e-6)


def test_moving_pin_target_preserves_constraint_rest_length_and_counts_updates():
    context = _context(compliance=0.0, iterations=2)

    context.update_pin_targets(
        np.asarray(((1, 0, 0), (1, 0, 0)), dtype=F32)
    )
    assert context.stats()["pin_target_update_count"] == 1
    assert context.stats()["reference_update_count"] == 0
    positions = _step(context)
    np.testing.assert_allclose(
        positions,
        ((1, 0, 0), (2, 0, 0)),
        atol=1.0e-6,
    )

    context.update_pin_targets(
        np.asarray(((2, 0, 0), (2, 0, 0)), dtype=F32)
    )
    assert context.stats()["pin_target_update_count"] == 2
    positions = _step(context)
    np.testing.assert_allclose(
        positions,
        ((2, 0, 0), (3, 0, 0)),
        atol=1.0e-6,
    )


def _particle_context(position):
    return hotools_native.mesh_xpbd_create_context_v1(
        np.asarray((position,), dtype=F32),
        np.ones((1,), dtype=F32),
        np.empty((0, 2), dtype=I32),
        np.empty((0, 2), dtype=I32),
        np.asarray((0.1,), dtype=F32),
        0.0,
        0.0,
        0.0,
        1,
    )


def _one_collider(collider_type, center, segment_a, segment_b, radius):
    return (
        np.asarray((collider_type,), dtype=I32),
        np.asarray((1,), dtype=I32),
        np.asarray((center,), dtype=F32),
        np.asarray((segment_a,), dtype=F32),
        np.asarray((segment_b,), dtype=F32),
        np.asarray((radius,), dtype=F32),
    )


def test_all_public_world_collider_shapes_have_deterministic_projection():
    fixtures = (
        ((0.5, 0, 0), _one_collider(0, (0, 0, 0), (0, 0, 0), (0, 0, 0), 1.0), (1.1, 0, 0)),
        ((0, 0.1, 0), _one_collider(1, (0, 0, 0), (-1, 0, 0), (1, 0, 0), 0.5), (0, 0.6, 0)),
        ((0, 0, -0.2), _one_collider(2, (0, 0, 0), (0, 0, 1), (0, 0, 0), 0.0), (0, 0, 0.1)),
        ((0, 0, 0), _one_collider(3, (0, 0, 0), (1, 0, 0), (0, 1, 0), 1.0), (1.1, 0, 0)),
    )
    for initial, collider, expected in fixtures:
        context = _particle_context(initial)
        positions = _step(context, mask=1, colliders=collider)
        np.testing.assert_allclose(positions[0], expected, atol=1.0e-6)
        assert context.stats()["last_contact_count"] == 1


def test_zero_collision_mask_is_explicit_no_collision():
    context = _particle_context((0.5, 0, 0))
    collider = _one_collider(0, (0, 0, 0), (0, 0, 0), (0, 0, 0), 1.0)
    positions = _step(context, mask=0, colliders=collider)
    np.testing.assert_allclose(positions[0], (0.5, 0, 0), atol=1.0e-6)
    assert context.stats()["last_contact_count"] == 0


def test_context_lifecycle_and_strict_array_contract():
    context = _context()
    assert context.stats() == {
        "schema_version": 1,
        "step_count": 0,
        "reset_count": 0,
        "parameter_update_count": 0,
        "reference_update_count": 0,
        "pin_target_update_count": 0,
        "last_contact_count": 0,
        "particle_count": 2,
        "stretch_constraint_count": 1,
        "bend_constraint_count": 0,
    }
    context.update_parameters(0.1, 0.0, 0.01, 4)
    assert context.stats()["parameter_update_count"] == 1
    context.dispose()
    context.dispose()
    assert context.disposed is True
    try:
        context.read_positions()
    except RuntimeError as exc:
        assert "disposed" in str(exc)
    else:
        raise AssertionError("disposed Mesh XPBD context remained readable")

    try:
        hotools_native.mesh_xpbd_create_context_v1(
            np.zeros((1, 3), dtype=np.float64),
            np.ones((1,), dtype=F32),
            np.empty((0, 2), dtype=I32),
            np.empty((0, 2), dtype=I32),
            np.zeros((1,), dtype=F32),
            0.0, 0.0, 0.0, 1,
        )
    except TypeError:
        pass
    else:
        raise AssertionError("float64 rest_positions bypassed typed ndarray ABI")


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"Mesh XPBD native: {len(TESTS)} passed on Python {sys.version_info.major}.{sys.version_info.minor}")
