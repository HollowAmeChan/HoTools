"""Owner for the new Physics World MC2 native context V0."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

import numpy as np

from .frame_state import MC2FrameInputSpec
from .runtime_parameters import (
    MC2RuntimeParametersV0,
    pack_mc2_runtime_parameters,
)
from .static_data import pack_mc2_baseline_static, pack_mc2_proxy_static


MC2_NATIVE_CONTEXT_SCHEMA_VERSION = 0
_NATIVE_MODULE = None
_REQUIRED_SYMBOLS = (
    "mc2_context_v0_create",
    "mc2_context_v0_inspect",
    "mc2_context_v0_update_proxy_static",
    "mc2_context_v0_update_baseline_static",
    "mc2_context_v0_update_parameters",
    "mc2_context_v0_update_dynamic",
    "mc2_context_v0_reset",
    "mc2_context_v0_step",
    "mc2_context_v0_read",
    "mc2_context_v0_free",
    "mc2_context_v0_stats",
)


def _ensure_bundled_native_path() -> None:
    override = os.environ.get("HOTOOLS_NATIVE_TEST_DIR")
    package_dir = Path(override) if override else None
    if package_dir is None:
        package_root = Path(__file__).resolve().parents[5]
        py_lib = "py313" if sys.version_info >= (3, 13) else "py311"
        package_dir = package_root / "_Lib" / py_lib / "HotoolsPackage"
    if package_dir.exists():
        path = str(package_dir)
        if path not in sys.path:
            sys.path.insert(0, path)


def native_module():
    global _NATIVE_MODULE
    if _NATIVE_MODULE is None:
        _ensure_bundled_native_path()
        _NATIVE_MODULE = importlib.import_module("hotools_native")
    return _NATIVE_MODULE


def is_available() -> bool:
    try:
        module = native_module()
    except Exception:
        return False
    return all(hasattr(module, name) for name in _REQUIRED_SYMBOLS)


class MC2NativeContextV0:
    """The slot-owned resource; the capsule never leaves this object."""

    def __init__(self, vertex_count: int, *, module=None) -> None:
        vertex_count = int(vertex_count)
        if vertex_count <= 0:
            raise ValueError("MC2 native context vertex_count must be positive")
        self._module = native_module() if module is None else module
        if not all(hasattr(self._module, name) for name in _REQUIRED_SYMBOLS):
            raise RuntimeError("hotools_native is missing MC2 context V0 symbols")
        self._handle = self._module.mc2_context_v0_create(
            MC2_NATIVE_CONTEXT_SCHEMA_VERSION,
            vertex_count,
        )
        if self._handle is None:
            raise RuntimeError("mc2_context_v0_create returned None")
        self.vertex_count = vertex_count
        self.parameter_signature = ""
        self.proxy_signature = ""
        self.baseline_signature = ""
        self.last_frame: tuple[int, int] | None = None
        self._out_positions = np.empty((vertex_count, 3), dtype=np.float32)
        self._out_rotations = np.empty((vertex_count, 4), dtype=np.float32)

    @property
    def disposed(self) -> bool:
        return self._handle is None

    def __enter__(self):
        self._ensure_live()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.dispose()

    def update_parameters(self, spec: MC2RuntimeParametersV0) -> None:
        if not isinstance(spec, MC2RuntimeParametersV0):
            raise TypeError("spec must be MC2RuntimeParametersV0")
        self._ensure_live()
        packed = pack_mc2_runtime_parameters(spec)
        self._module.mc2_context_v0_update_parameters(
            self._handle,
            packed["float_values"],
            packed["int_values"],
            packed["curve_values"],
        )
        self.parameter_signature = spec.parameter_signature

    def update_mesh_static(self, static) -> None:
        from .setups.mesh_cloth.static_build import MC2MeshClothStaticBuildResult

        if not isinstance(static, MC2MeshClothStaticBuildResult):
            raise TypeError("static must be MC2MeshClothStaticBuildResult")
        if static.final_proxy.vertex_count != self.vertex_count:
            raise ValueError("MC2 native static vertex count mismatch")
        self._ensure_live()
        proxy = pack_mc2_proxy_static(static.final_proxy)
        baseline = pack_mc2_baseline_static(static.baseline.baseline)
        self._module.mc2_context_v0_update_proxy_static(
            self._handle,
            proxy["local_positions"],
            proxy["local_normals"],
            proxy["local_tangents"],
            proxy["uvs"],
            proxy["vertex_attributes"],
            proxy["edges"],
            proxy["triangles"],
        )
        self._module.mc2_context_v0_update_baseline_static(
            self._handle,
            baseline["parent_indices"],
            baseline["child_ranges"],
            baseline["child_data"],
            baseline["baseline_flags"],
            baseline["baseline_ranges"],
            baseline["baseline_data"],
            baseline["root_indices"],
            baseline["depths"],
            baseline["vertex_local_positions"],
            baseline["vertex_local_rotations"],
        )
        self.proxy_signature = static.final_proxy.proxy_signature
        self.baseline_signature = static.baseline.baseline.baseline_signature

    def update_dynamic(self, frame_input: MC2FrameInputSpec) -> None:
        if not isinstance(frame_input, MC2FrameInputSpec):
            raise TypeError("frame_input must be MC2FrameInputSpec")
        if frame_input.particle_count != self.vertex_count:
            raise ValueError("MC2 native frame particle count mismatch")
        self._ensure_live()
        self._module.mc2_context_v0_update_dynamic(
            self._handle,
            frame_input.frame,
            frame_input.generation,
            frame_input.world_positions,
            frame_input.world_rotations_xyzw,
        )
        self.last_frame = (frame_input.frame, frame_input.generation)

    def reset(self) -> None:
        self._ensure_live()
        self._module.mc2_context_v0_reset(self._handle)

    def step_no_collision(self, dt: float) -> None:
        self._ensure_live()
        self._module.mc2_context_v0_step(self._handle, float(dt))

    def read(self) -> tuple[np.ndarray, np.ndarray]:
        self._ensure_live()
        self._module.mc2_context_v0_read(
            self._handle,
            self._out_positions,
            self._out_rotations,
        )
        return self._out_positions, self._out_rotations

    def inspect(self) -> dict:
        if self._handle is None:
            return {
                "schema": "mc2_context_v0",
                "schema_version": MC2_NATIVE_CONTEXT_SCHEMA_VERSION,
                "vertex_count": self.vertex_count,
                "released": True,
            }
        return dict(self._module.mc2_context_v0_inspect(self._handle))

    def dispose(self) -> None:
        if self._handle is not None:
            try:
                self._module.mc2_context_v0_free(self._handle)
            finally:
                self._handle = None
        self.parameter_signature = ""
        self.proxy_signature = ""
        self.baseline_signature = ""
        self.last_frame = None
        self._out_positions = np.empty((0, 3), dtype=np.float32)
        self._out_rotations = np.empty((0, 4), dtype=np.float32)

    def _ensure_live(self) -> None:
        if self._handle is None:
            raise RuntimeError("MC2 native context owner has been disposed")


__all__ = [
    "MC2_NATIVE_CONTEXT_SCHEMA_VERSION",
    "MC2NativeContextV0",
    "is_available",
    "native_module",
]
