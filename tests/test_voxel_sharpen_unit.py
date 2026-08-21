"""Unit tests for the NumPy-only selected vertex voxel sharpen core."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "VertexGroupTools" / "voxel_sharpen.py"
SPEC = importlib.util.spec_from_file_location("hotools_voxel_sharpen", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
voxel_sharpen = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = voxel_sharpen
SPEC.loader.exec_module(voxel_sharpen)


class VoxelSharpenUnitTests(unittest.TestCase):
    def test_selected_only_ignores_unselected_nan_rows_and_edges(self):
        positions = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                ["unselected", "row", "sentinel"],
            ]
        )
        weights = np.array([0.2, 0.6, 0.2, "unselected"], dtype=object)
        result = voxel_sharpen.sharpen_weights(
            positions,
            weights,
            selected=[0, 1, 2],
            edges=[[0, 1], [1, 2], [2, 3]],
            resolution=16,
        )

        np.testing.assert_array_equal(result.selected_indices, [0, 1, 2])
        self.assertTrue(np.all(np.isfinite(result.weights)))
        self.assertEqual(result.diagnostics["edge_count"], 2)
        self.assertEqual(result.diagnostics["selected_count"], 3)
        self.assertEqual(set(result.weight_map), {0, 1, 2})

    def test_single_group_unsharp_increases_center_contrast(self):
        positions = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        weights = np.array([0.2, 0.6, 0.2])
        result = voxel_sharpen.sharpen_weights(
            positions,
            weights,
            selected=np.array([True, True, True]),
            edges=[[0, 1], [1, 2]],
            resolution=16,
            strength=1.0,
        )

        self.assertEqual(result.weights.shape, (3,))
        self.assertGreater(result.weights[1], weights[1])
        self.assertLess(result.weights[0], weights[0])
        self.assertLess(result.weights[2], weights[2])
        self.assertGreater(result.diagnostics["coverage_nonzero"], 0)

    def test_single_group_ramp_gets_monotonic_contrast(self):
        positions = np.column_stack(
            (np.arange(8, dtype=float), np.zeros(8), np.zeros(8))
        )
        weights = np.linspace(0.0, 1.0, 8)
        edges = np.column_stack((np.arange(7), np.arange(1, 8)))
        result = voxel_sharpen.sharpen_weights(
            positions,
            weights,
            selected=np.arange(8),
            edges=edges,
            resolution=32,
            strength=1.0,
        )

        self.assertTrue(np.all(np.diff(result.weights) >= 0.0))
        self.assertLess(result.weights[1], weights[1])
        self.assertGreater(result.weights[-2], weights[-2])

    def test_multiple_groups_preserve_each_input_row_sum(self):
        positions = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        weights = np.array([[0.2, 0.8], [0.6, 0.4], [0.2, 0.8]])
        result = voxel_sharpen.sharpen_weights(
            positions,
            weights,
            selected=[0, 1, 2],
            edges=[[0, 1], [1, 2]],
            resolution=16,
            strength=1.0,
            normalization_target="input_sum",
        )

        self.assertEqual(result.weights.shape, (3, 2))
        np.testing.assert_allclose(result.weights.sum(axis=1), weights.sum(axis=1), atol=1e-12)
        self.assertTrue(np.all(result.weights >= 0.0))
        self.assertTrue(np.all(result.weights <= 1.0))

    def test_disconnected_close_components_do_not_mix(self):
        # The two lines are close in world space but have no selected topology
        # edge between them.  Changing line B must not affect line A.
        positions = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 0.05, 0.0],
                [1.0, 0.05, 0.0],
            ]
        )
        edges = [[0, 1], [2, 3]]
        first = voxel_sharpen.sharpen_weights(
            positions,
            [0.2, 0.6, 0.9, 0.1],
            selected=[0, 1, 2, 3],
            edges=edges,
            resolution=16,
            blur_radius=4,
            topology_hops=2,
        )
        second = voxel_sharpen.sharpen_weights(
            positions,
            [0.2, 0.6, 0.1, 0.9],
            selected=[0, 1, 2, 3],
            edges=edges,
            resolution=16,
            blur_radius=4,
            topology_hops=2,
        )

        self.assertEqual(first.diagnostics["component_count"], 2)
        np.testing.assert_allclose(first.weights[:2], second.weights[:2], atol=1e-12)
        self.assertFalse(np.allclose(first.weights[2:], second.weights[2:]))

    def test_resolution_is_bounded_by_max_voxels(self):
        positions = np.stack(
            [np.linspace(0.0, 10.0, 20), np.zeros(20), np.zeros(20)], axis=1
        )
        edges = np.stack([np.arange(19), np.arange(1, 20)], axis=1)
        result = voxel_sharpen.sharpen_weights(
            positions,
            np.linspace(0.0, 1.0, 20),
            selected=np.arange(20),
            edges=edges,
            resolution=64,
            max_voxels=1000,
        )

        self.assertLessEqual(result.diagnostics["voxel_count"], 1000)
        self.assertGreaterEqual(result.diagnostics["grid_shape"][0], 2)

    def test_manual_resolution_changes_sparse_grid_spacing(self):
        positions = np.column_stack(
            (np.linspace(0.0, 10.0, 12), np.zeros(12), np.zeros(12))
        )
        weights = np.linspace(0.0, 1.0, 12)
        edges = np.column_stack((np.arange(11), np.arange(1, 12)))
        coarse = voxel_sharpen.sharpen_weights(
            positions, weights, np.arange(12), edges, resolution=16
        )
        fine = voxel_sharpen.sharpen_weights(
            positions, weights, np.arange(12), edges, resolution=128
        )
        self.assertGreater(
            fine.diagnostics["base_resolution"][0],
            coarse.diagnostics["base_resolution"][0],
        )

    def test_zero_strength_is_exact_noop(self):
        positions = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        weights = np.array([[0.15, 0.85], [0.8, 0.2]])
        result = voxel_sharpen.sharpen_weights(
            positions,
            weights,
            selected=[0, 1],
            edges=[[0, 1]],
            strength=0.0,
        )
        np.testing.assert_array_equal(result.weights, weights)
        self.assertEqual(result.diagnostics["voxel_count"], 0)

    def test_invalid_empty_selection_is_rejected(self):
        with self.assertRaises(voxel_sharpen.VoxelSharpenError):
            voxel_sharpen.sharpen_weights(
                np.zeros((2, 3)),
                np.zeros(2),
                selected=np.array([False, False]),
            )


if __name__ == "__main__":
    unittest.main()
