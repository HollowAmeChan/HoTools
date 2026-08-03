"""Mesh XPBD nanobind context 的 Python 生命周期适配。"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

import numpy as np

from .colliders import MeshXpbdColliderFrame
from .specs import MeshXpbdTaskSpec
from .topology import MeshXpbdReferenceFrame, MeshXpbdTopology


MESH_XPBD_REQUIRED_NATIVE_SYMBOLS = (
    "MeshXpbdContextV1",
    "mesh_xpbd_create_context_v1",
)
_NATIVE_MODULE = None


def _ensure_bundled_native_path() -> None:
    override = os.environ.get("HOTOOLS_NATIVE_TEST_DIR")
    package_dir = Path(override) if override else None
    if package_dir is None:
        package_root = Path(__file__).resolve().parents[3]
        py_lib = "py313" if sys.version_info >= (3, 13) else "py311"
        package_dir = package_root / "_Lib" / py_lib / "HotoolsPackage"
    if package_dir.exists() and str(package_dir) not in sys.path:
        sys.path.insert(0, str(package_dir))


def native_module():
    global _NATIVE_MODULE
    if _NATIVE_MODULE is None:
        _ensure_bundled_native_path()
        _NATIVE_MODULE = importlib.import_module("hotools_native")
    return _NATIVE_MODULE


def require_mesh_xpbd_native_module(module=None):
    module = native_module() if module is None else module
    if not all(hasattr(module, name) for name in MESH_XPBD_REQUIRED_NATIVE_SYMBOLS):
        raise RuntimeError("hotools_native 缺少 Mesh XPBD context API")
    return module


def is_available() -> bool:
    try:
        require_mesh_xpbd_native_module()
    except Exception:
        return False
    return True


class MeshXpbdNativeContext:
    """一个 solver slot 持有的唯一 native context owner。"""

    __slots__ = (
        "_context",
        "topology_signature",
        "reference_signature",
        "parameter_signature",
    )

    def __init__(self) -> None:
        self._context = None
        self.topology_signature = ""
        self.reference_signature = ""
        self.parameter_signature = ""

    @property
    def ready(self) -> bool:
        return self._context is not None and not bool(self._context.disposed)

    def rebuild(
        self,
        topology: MeshXpbdTopology,
        reference: MeshXpbdReferenceFrame,
        spec: MeshXpbdTaskSpec,
    ) -> None:
        module = require_mesh_xpbd_native_module()
        next_context = module.mesh_xpbd_create_context_v1(
            np.ascontiguousarray(reference.rest_world_positions, dtype=np.float32),
            np.ascontiguousarray(topology.inverse_masses, dtype=np.float32),
            np.ascontiguousarray(topology.stretch_indices, dtype=np.int32),
            np.ascontiguousarray(topology.bend_indices, dtype=np.int32),
            np.ascontiguousarray(reference.world_collision_radii, dtype=np.float32),
            spec.damping,
            spec.stretch_compliance,
            spec.bend_compliance,
            spec.iterations,
        )
        previous = self._context
        self._context = next_context
        self.topology_signature = topology.topology_signature
        self.reference_signature = reference.signature
        self.parameter_signature = spec.parameter_signature
        if previous is not None:
            previous.dispose()

    def update_reference(
        self,
        topology: MeshXpbdTopology,
        reference: MeshXpbdReferenceFrame,
    ) -> None:
        self._require_context().update_reference(
            np.ascontiguousarray(reference.rest_world_positions, dtype=np.float32),
            np.ascontiguousarray(topology.inverse_masses, dtype=np.float32),
            np.ascontiguousarray(reference.world_collision_radii, dtype=np.float32),
        )
        self.reference_signature = reference.signature

    def update_parameters(self, spec: MeshXpbdTaskSpec) -> None:
        self._require_context().update_parameters(
            spec.damping,
            spec.stretch_compliance,
            spec.bend_compliance,
            spec.iterations,
        )
        self.parameter_signature = spec.parameter_signature

    def update_pin_targets(self, positions) -> None:
        """只移动 Fixed 粒子目标，不改变 constraint rest。"""
        self._require_context().update_pin_targets(
            np.ascontiguousarray(positions, dtype=np.float32)
        )

    def reset(self, reference: MeshXpbdReferenceFrame) -> None:
        self._require_context().reset(
            np.ascontiguousarray(reference.rest_world_positions, dtype=np.float32)
        )

    def step(
        self,
        *,
        delta_time: float,
        substeps: int,
        gravity_direction,
        gravity_power: float,
        colliders: MeshXpbdColliderFrame,
        collided_by_groups: int,
    ) -> np.ndarray:
        gravity = np.ascontiguousarray(gravity_direction, dtype=np.float32).reshape((3,))
        result = self._require_context().step(
            float(delta_time),
            int(substeps),
            gravity,
            float(gravity_power),
            *colliders.native_args(),
            int(collided_by_groups),
        )
        positions = np.asarray(result, dtype=np.float32)
        if positions.ndim != 2 or positions.shape[1] != 3 or not np.isfinite(positions).all():
            raise RuntimeError("Mesh XPBD native 返回了非法 positions")
        return np.ascontiguousarray(positions, dtype=np.float32)

    def read_positions(self) -> np.ndarray:
        return np.ascontiguousarray(
            self._require_context().read_positions(), dtype=np.float32
        )

    def stats(self) -> dict:
        return dict(self._require_context().stats())

    def dispose(self) -> None:
        context = self._context
        self._context = None
        self.topology_signature = ""
        self.reference_signature = ""
        self.parameter_signature = ""
        if context is not None:
            context.dispose()

    def _require_context(self):
        if not self.ready:
            raise RuntimeError("Mesh XPBD native context 尚未建立或已释放")
        return self._context
