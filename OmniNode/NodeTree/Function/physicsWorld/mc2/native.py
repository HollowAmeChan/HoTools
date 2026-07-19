"""Load and qualify the MC2 native extension without owning solver state."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys


MC2_REQUIRED_NATIVE_SYMBOLS = (
    "mc2_interaction_v0_create",
    "mc2_interaction_v0_inspect",
    "mc2_interaction_v0_invalidate",
    "mc2_interaction_v0_step_group",
    "mc2_interaction_v0_read_debug",
    "mc2_interaction_v0_free",
    "mc2_context_v0_create",
    "mc2_context_v0_inspect",
    "mc2_context_v0_classify_static_fingerprint",
    "mc2_context_v0_update_static_fingerprint",
    "mc2_context_v0_clone_config_static",
    "mc2_context_v0_update_proxy_static",
    "mc2_context_v0_finalize_proxy_attributes",
    "mc2_context_v0_update_baseline_static",
    "mc2_context_v0_update_bone_static",
    "mc2_context_v0_update_frame_producer_static",
    "mc2_context_v0_update_distance_static",
    "mc2_context_v0_update_bending_static",
    "mc2_context_v0_update_center_static",
    "mc2_context_v0_update_self_collision_static",
    "mc2_context_v0_update_center_dynamic",
    "mc2_context_v0_update_step_interpolation",
    "mc2_context_v0_update_team_options",
    "mc2_context_v0_set_setup_kind",
    "mc2_context_v0_set_tether_enabled",
    "mc2_context_v0_apply_center_frame_shift",
    "mc2_context_v0_apply_center_negative_scale_teleport",
    "mc2_context_v0_apply_task_teleport",
    "mc2_context_v0_update_parameters",
    "mc2_context_v0_update_dynamic",
    "mc2_context_v0_derive_center_pose_raw",
    "mc2_context_v0_update_mesh_dynamic_raw",
    "mc2_context_v0_update_bone_dynamic_raw",
    "mc2_context_v0_update_colliders",
    "mc2_context_v0_reset",
    "mc2_context_v0_step",
    "mc2_context_v0_read",
    "mc2_context_v0_read_debug_self_indices",
    "mc2_context_v0_read_debug_self_grid",
    "mc2_context_v0_read_debug_self_candidates",
    "mc2_context_v0_read_debug_self_contacts",
    "mc2_context_v0_read_debug_self_intersections",
    "mc2_context_v0_read_bone_output",
    "mc2_context_v0_read_step_basic",
    "mc2_context_v0_read_debug_baseline",
    "mc2_context_v0_read_debug_motion_base",
    "mc2_context_v0_read_debug_angle_restoration",
    "mc2_context_v0_read_debug_angle_limit",
    "mc2_context_v0_read_center_step",
    "mc2_context_v0_free",
    "mc2_context_v0_stats",
    "mc2_mesh_static_fingerprint_v0",
    "mc2_bone_static_fingerprint_v0",
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
        raise RuntimeError("hotools_native is missing MC2 context V0 symbols")
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
