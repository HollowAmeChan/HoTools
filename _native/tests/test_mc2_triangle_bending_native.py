import sys
import os
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

import hotools_native  # noqa: E402


EPSILON = 0.00000001
TRIANGLE_BENDING_FIXED_INVERSE_MASS = 0.01
TRIANGLE_VOLUME_SCALE = 1000.0


def safe_normal(delta, fallback):
    length = float(np.linalg.norm(delta))
    if length > EPSILON:
        return delta / length
    fallback_length = float(np.linalg.norm(fallback))
    if fallback_length > EPSILON:
        return fallback / fallback_length
    return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)


def dihedral_angle_correction(pos_buffer, inv_mass_buffer, rest_angle, sign, stiffness):
    p0 = pos_buffer[0]
    p1 = pos_buffer[1]
    p2 = pos_buffer[2]
    p3 = pos_buffer[3]
    edge = p3 - p2
    edge_length = float(np.linalg.norm(edge))
    if edge_length < EPSILON:
        return None
    inv_edge_length = 1.0 / edge_length

    n1 = np.cross(p2 - p0, p3 - p0)
    n2 = np.cross(p3 - p1, p2 - p1)
    n1_len_sq = float(np.dot(n1, n1))
    n2_len_sq = float(np.dot(n2, n2))
    if n1_len_sq <= EPSILON or n2_len_sq <= EPSILON:
        return None

    n1_grad = n1 / n1_len_sq
    n2_grad = n2 / n2_len_sq
    d0 = edge_length * n1_grad
    d1 = edge_length * n2_grad
    d2 = (
        float(np.dot(p0 - p3, edge)) * inv_edge_length * n1_grad
        + float(np.dot(p1 - p3, edge)) * inv_edge_length * n2_grad
    )
    d3 = (
        float(np.dot(p2 - p0, edge)) * inv_edge_length * n1_grad
        + float(np.dot(p2 - p1, edge)) * inv_edge_length * n2_grad
    )

    n1_norm = safe_normal(n1_grad, np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    n2_norm = safe_normal(n2_grad, np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    dot = max(-1.0, min(1.0, float(np.dot(n1_norm, n2_norm))))
    phi = float(np.arccos(dot))

    gradients = (d0, d1, d2, d3)
    lamb = 0.0
    for i in range(4):
        lamb += float(inv_mass_buffer[i]) * float(np.dot(gradients[i], gradients[i]))
    if lamb <= EPSILON:
        return None

    dir_value = float(np.dot(np.cross(n1_norm, n2_norm), edge))
    dir_sign = -1.0 if dir_value < 0.0 else 1.0
    if abs(sign) > EPSILON:
        phi *= dir_sign
    else:
        lamb *= dir_sign

    lamb = (float(rest_angle) - phi) / lamb * float(stiffness)
    corrections = np.zeros((4, 3), dtype=np.float32)
    for i in range(4):
        corrections[i] = -float(inv_mass_buffer[i]) * lamb * gradients[i]
    return corrections


def volume_correction(pos_buffer, inv_mass_buffer, rest_volume, stiffness):
    p0 = pos_buffer[0]
    p1 = pos_buffer[1]
    p2 = pos_buffer[2]
    p3 = pos_buffer[3]
    volume = (1.0 / 6.0) * float(np.dot(np.cross(p1 - p0, p2 - p0), p3 - p0)) * TRIANGLE_VOLUME_SCALE
    gradients = (
        np.cross(p1 - p2, p3 - p2),
        np.cross(p2 - p0, p3 - p0),
        np.cross(p0 - p1, p3 - p1),
        np.cross(p1 - p0, p2 - p0),
    )

    lamb = 0.0
    for i in range(4):
        lamb += float(inv_mass_buffer[i]) * float(np.dot(gradients[i], gradients[i]))
    lamb *= TRIANGLE_VOLUME_SCALE
    if abs(lamb) <= EPSILON:
        return None

    lamb = float(stiffness) * (float(rest_volume) - volume) / lamb
    corrections = np.zeros((4, 3), dtype=np.float32)
    for i in range(4):
        corrections[i] = float(inv_mass_buffer[i]) * lamb * gradients[i]
    return corrections


def inv_mass_buffer(inv_masses, vertices):
    return np.asarray(
        [
            TRIANGLE_BENDING_FIXED_INVERSE_MASS if float(inv_masses[int(v)]) <= EPSILON else float(inv_masses[int(v)])
            for v in vertices
        ],
        dtype=np.float32,
    )


def add_corrections(add_positions, add_counts, inv_masses, vertices, corrections):
    if corrections is None:
        return
    for local_index, vertex_index in enumerate(vertices):
        if float(inv_masses[int(vertex_index)]) <= EPSILON:
            continue
        add_positions[int(vertex_index)] += corrections[local_index]
        add_counts[int(vertex_index)] += 1


def project_triangle_bending_reference(
    positions,
    inv_masses,
    dihedral_pairs,
    rest_angles,
    signs,
    volume_pairs,
    rest_volumes,
    stiffness_values,
):
    if len(dihedral_pairs) == 0 and len(volume_pairs) == 0:
        return
    if not bool(np.any(stiffness_values > EPSILON)):
        return

    add_positions = np.zeros_like(positions, dtype=np.float32)
    add_counts = np.zeros(len(positions), dtype=np.int32)

    for pair_index, pair in enumerate(dihedral_pairs):
        vertices = np.asarray(pair, dtype=np.int32)
        local_stiffness = float(np.mean(stiffness_values[vertices]))
        if local_stiffness <= EPSILON:
            continue
        inv_buffer = inv_mass_buffer(inv_masses, vertices)
        if float(np.sum(inv_buffer)) <= EPSILON:
            continue
        sign = -1.0 if int(signs[pair_index]) < 0 else 1.0
        corrections = dihedral_angle_correction(
            np.ascontiguousarray(positions[vertices], dtype=np.float32),
            inv_buffer,
            float(rest_angles[pair_index]) * sign,
            sign,
            local_stiffness,
        )
        add_corrections(add_positions, add_counts, inv_masses, vertices, corrections)

    for pair_index, pair in enumerate(volume_pairs):
        vertices = np.asarray(pair, dtype=np.int32)
        local_stiffness = float(np.mean(stiffness_values[vertices]))
        if local_stiffness <= EPSILON:
            continue
        inv_buffer = inv_mass_buffer(inv_masses, vertices)
        if float(np.sum(inv_buffer)) <= EPSILON:
            continue
        corrections = volume_correction(
            np.ascontiguousarray(positions[vertices], dtype=np.float32),
            inv_buffer,
            float(rest_volumes[pair_index]),
            local_stiffness,
        )
        add_corrections(add_positions, add_counts, inv_masses, vertices, corrections)

    active = add_counts > 0
    positions[active] += add_positions[active] / add_counts[active, None].astype(np.float32)


def assert_native_matches_reference():
    positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.1, 1.0, 0.1],
            [0.25, 0.25, 0.9],
            [1.1, 0.9, -0.15],
        ],
        dtype=np.float32,
    )
    inv_masses = np.array([0.0, 1.0, 0.8, 1.0, 1.2], dtype=np.float32)
    dihedral_pairs = np.array([[0, 1, 2, 3], [1, 4, 2, 3]], dtype=np.int32)
    rest_angles = np.array([0.35, -0.25], dtype=np.float32)
    signs = np.array([1, -1], dtype=np.int32)
    volume_pairs = np.array([[0, 1, 2, 3], [1, 4, 2, 3]], dtype=np.int32)
    rest_volumes = np.array([120.0, -40.0], dtype=np.float32)
    stiffness = np.array([1.0, 0.9, 0.7, 0.8, 0.6], dtype=np.float32)

    expected = positions.copy()
    actual = positions.copy()

    project_triangle_bending_reference(
        expected,
        inv_masses,
        dihedral_pairs,
        rest_angles,
        signs,
        volume_pairs,
        rest_volumes,
        stiffness,
    )
    hotools_native.project_triangle_bending_mc2(
        actual,
        inv_masses,
        dihedral_pairs,
        rest_angles,
        signs,
        volume_pairs,
        rest_volumes,
        stiffness,
    )

    np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-5)


def main():
    assert_native_matches_reference()
    print("mc2 triangle bending native smoke test passed")


if __name__ == "__main__":
    main()
