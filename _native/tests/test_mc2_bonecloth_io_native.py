import os
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

import hotools_native  # noqa: E402


def main():
    world_rotations = np.asarray(
        (
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
        ),
        dtype=np.float32,
    )
    display_positions = np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), dtype=np.float32)
    base_positions = display_positions.copy()
    base_rotations = world_rotations.copy()
    vertex_local_positions = np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), dtype=np.float32)
    vertex_local_rotations = world_rotations.copy()
    parent_indices = np.asarray((-1, 0), dtype=np.int32)
    baseline_start = np.asarray((0,), dtype=np.int32)
    baseline_count = np.asarray((2,), dtype=np.int32)
    baseline_data = np.asarray((0, 1), dtype=np.int32)
    attributes = np.asarray((0, 4), dtype=np.uint8)

    hotools_native.solve_mc2_bonecloth_io(
        world_rotations,
        display_positions,
        base_positions,
        base_rotations,
        vertex_local_positions,
        vertex_local_rotations,
        parent_indices,
        baseline_start,
        baseline_count,
        baseline_data,
        attributes,
        1.0,
        1.0,
        0.0,
        0.5,
    )

    if not np.all(np.isfinite(world_rotations)):
        raise AssertionError(f"world_rotations contains non-finite values: {world_rotations!r}")
    norms = np.linalg.norm(world_rotations, axis=1)
    np.testing.assert_allclose(norms, np.ones_like(norms), rtol=1e-5, atol=1e-5)
    print("mc2 bonecloth io native smoke test passed")


if __name__ == "__main__":
    main()
