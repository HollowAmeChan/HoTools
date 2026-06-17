import os
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

import hotools_native  # noqa: E402


EPSILON = 0.00000001
MAX_DISTANCE_RATIO_FUTURE_PREDICTION = 1.3


def calculate_display_reference(positions, real_velocity, root_indices, frame_dt):
    display_positions = np.ascontiguousarray(positions, dtype=np.float32).copy()
    if frame_dt <= EPSILON:
        return display_positions

    future_positions = display_positions + np.ascontiguousarray(real_velocity, dtype=np.float32) * float(frame_dt)
    roots = np.ascontiguousarray(root_indices, dtype=np.int32)
    for vertex_index in range(len(future_positions)):
        root_index = int(roots[vertex_index]) if vertex_index < len(roots) else -1
        if root_index < 0 or root_index >= len(future_positions):
            continue
        root_position = display_positions[root_index]
        original_dist = float(np.linalg.norm(display_positions[vertex_index] - root_position))
        clamp_dist = original_dist * MAX_DISTANCE_RATIO_FUTURE_PREDICTION
        if clamp_dist <= EPSILON:
            continue
        delta = future_positions[vertex_index] - root_position
        length = float(np.linalg.norm(delta))
        if length > clamp_dist and length > EPSILON:
            future_positions[vertex_index] = root_position + delta * (clamp_dist / length)
    return np.ascontiguousarray(future_positions, dtype=np.float32)


def assert_native_matches_reference():
    positions = np.asarray(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 2.0, 0.0),
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
        ),
        dtype=np.float32,
    )
    real_velocity = np.asarray(
        (
            (4.0, 0.0, 0.0),
            (20.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (2.0, 3.0, 4.0),
            (-1.0, 0.5, 0.0),
        ),
        dtype=np.float32,
    )
    root_indices = np.asarray((-1, 0, 0, 3, 20), dtype=np.int32)

    expected = calculate_display_reference(positions, real_velocity, root_indices, 0.1)
    actual = positions.copy()
    hotools_native.calculate_display_positions_mc2(
        positions,
        real_velocity,
        root_indices,
        actual,
        0.1,
        MAX_DISTANCE_RATIO_FUTURE_PREDICTION,
    )
    np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-6)

    zero_dt_actual = np.zeros_like(positions)
    hotools_native.calculate_display_positions_mc2(
        positions,
        real_velocity,
        root_indices,
        zero_dt_actual,
        0.0,
        MAX_DISTANCE_RATIO_FUTURE_PREDICTION,
    )
    np.testing.assert_allclose(zero_dt_actual, positions, rtol=0.0, atol=0.0)


def main():
    assert_native_matches_reference()
    print("mc2 display native smoke test passed")


if __name__ == "__main__":
    main()
