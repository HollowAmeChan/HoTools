"""Pure tests for signed, shear-free component transform decomposition."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

import numpy as np


MC2_ROOT = Path(__file__).resolve().parents[1]
PHYSICS_WORLD = MC2_ROOT.parent
FUNCTION = PHYSICS_WORLD.parent
NODETREE = FUNCTION.parent
OMNINODE = NODETREE.parent
HOTOOLS = OMNINODE.parent

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [str(package_path)]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

math3d = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.utils.math3d"
)


def _rotation_z(degrees: float) -> np.ndarray:
    radians = np.deg2rad(degrees)
    cosine = np.cos(radians)
    sine = np.sin(radians)
    return np.asarray(
        ((cosine, -sine, 0.0), (sine, cosine, 0.0), (0.0, 0.0, 1.0)),
        dtype=np.float64,
    )


def _reconstruct(rotation_xyzw, signed_scale) -> np.ndarray:
    rotation = math3d.quaternion_matrix_unit_f32(
        np.asarray(rotation_xyzw, dtype=np.float32)
    ).astype(np.float64)
    return rotation @ np.diag(np.asarray(signed_scale, dtype=np.float64))


def test_single_axis_reflection_reconstructs_without_reflected_rotation() -> None:
    linear = _rotation_z(35.0) @ np.diag((-2.0, 1.5, 0.75))
    rotation, scale = math3d.decompose_signed_orthogonal_linear_f64(
        linear,
        (-1.0, 1.0, 1.0),
        name="single reflection",
    )
    np.testing.assert_allclose(scale, (-2.0, 1.5, 0.75), atol=1.0e-12)
    np.testing.assert_allclose(_reconstruct(rotation, scale), linear, atol=2.0e-7)
    assert np.linalg.det(_reconstruct(rotation, (1.0, 1.0, 1.0))) > 0.0


def test_two_negative_axes_preserve_proper_rotation() -> None:
    linear = _rotation_z(-20.0) @ np.diag((-3.0, -2.0, 0.5))
    rotation, scale = math3d.decompose_signed_orthogonal_linear_f64(
        linear,
        (-1.0, -1.0, 1.0),
        name="double reflection",
    )
    np.testing.assert_allclose(scale, (-3.0, -2.0, 0.5), atol=1.0e-12)
    np.testing.assert_allclose(_reconstruct(rotation, scale), linear, atol=2.0e-7)


def test_shear_and_wrong_axis_signs_are_rejected() -> None:
    cases = (
        (
            np.asarray(((1.0, 0.5, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))),
            (1.0, 1.0, 1.0),
        ),
        (np.diag((-1.0, 1.0, 1.0)), (1.0, 1.0, 1.0)),
    )
    for linear, signs in cases:
        try:
            math3d.decompose_signed_orthogonal_linear_f64(
                linear,
                signs,
                name="invalid component",
            )
        except ValueError as exc:
            assert "shear-free" in str(exc)
        else:
            raise AssertionError("invalid signed component transform was accepted")


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
