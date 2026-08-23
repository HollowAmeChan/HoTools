"""Load and qualify the MC2 native extension without owning solver state."""

from __future__ import annotations

from ....Utils.optional_dependencies import import_native_module


MC2_REQUIRED_NATIVE_SYMBOLS = (
    "mc2_mesh_frame_orientations_v1",
    "mc2_bone_frame_orientations_v1",
    "mc2_bone_line_output_v1",
    "mc2_domain_cpu_v1_step_tether_partitioned",
    "mc2_domain_cpu_v1_step_angle_partitioned",
    "mc2_domain_cpu_v1_step_motion_partitioned",
    "mc2_domain_cpu_v1_step_integration_partitioned",
    "mc2_domain_cpu_v1_step_post_owned_partitioned",
    "mc2_mesh_static_fingerprint_v1",
    "mc2_bone_static_fingerprint_v1",
    "mc2_optimize_triangle_direction",
    "mc2_build_mesh_fallback_tangents",
    "mc2_build_bone_rest_frames",
    "mc2_build_bone_vertex_to_transform_rotations",
    "mc2_build_bone_transform_baseline_derived",
    "mc2_build_mesh_final_proxy_derived",
    "mc2_build_mesh_baseline_derived",
    "mc2_build_baseline_pose_depth_derived",
    "mc2_build_distance_derived",
    "mc2_build_bending_derived",
    "mc2_build_self_collision_derived",
    "mc2_build_center_static_derived",
)
_NATIVE_MODULE = None


def native_module():
    global _NATIVE_MODULE
    if _NATIVE_MODULE is None:
        _NATIVE_MODULE = import_native_module("hotools_native")
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
