"""Load and qualify the MC2 native extension without owning solver state."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys


MC2_REQUIRED_NATIVE_SYMBOLS = (
    "mc2_mesh_frame_orientations_v1",
    "mc2_bone_frame_orientations_v1",
    "mc2_domain_cpu_v1_step_tether_partitioned",
    "mc2_domain_cpu_v1_step_angle_partitioned",
    "mc2_domain_cpu_v1_step_motion_partitioned",
    "mc2_domain_cpu_v1_step_integration_partitioned",
    "mc2_domain_cpu_v1_step_post_owned_partitioned",
    "mc2_mesh_static_fingerprint_v1",
    "mc2_bone_static_fingerprint_v1",
    "mc2_optimize_triangle_direction_v0",
    "mc2_build_mesh_fallback_tangents_v0",
    "mc2_build_bone_rest_frames_v0",
    "mc2_build_bone_vertex_to_transform_rotations_v0",
    "mc2_build_bone_transform_baseline_derived_v0",
    "mc2_build_mesh_final_proxy_derived_v1",
    "mc2_build_mesh_baseline_derived_v0",
    "mc2_build_baseline_pose_depth_derived_v0",
    "mc2_build_distance_derived_v0",
    "mc2_build_bending_derived_v0",
    "mc2_build_self_collision_derived_v0",
    "mc2_build_center_static_derived_v0",
)
_NATIVE_MODULE = None


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


def require_mc2_native_module(module=None):
    module = native_module() if module is None else module
    if not all(hasattr(module, name) for name in MC2_REQUIRED_NATIVE_SYMBOLS):
        raise RuntimeError("hotools_native is missing required MC2 symbols")
    return module


def is_available() -> bool:
    try:
        require_mc2_native_module()
    except Exception:
        return False
    return True


__all__ = [
    "MC2_REQUIRED_NATIVE_SYMBOLS",
    "is_available",
    "native_module",
    "require_mc2_native_module",
]
