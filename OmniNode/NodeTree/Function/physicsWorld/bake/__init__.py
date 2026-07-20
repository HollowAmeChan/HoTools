"""Physics World bake backends and session coordination."""

from .mesh import (
    cancel_pending_geometry_bake,
    current_mesh_targets,
    geometry_bake_is_active,
    geometry_bake_should_record_actions,
    geometry_bake_status,
    geometry_bake_target_count,
    rearm_geometry_bake_trigger,
    request_geometry_bake,
    reset_geometry_bake_runtime_for_tests as _reset_geometry_bake_runtime_for_tests,
    run_pending_geometry_bake,
    set_session_cache_playback,
    shutdown_geometry_bake_runtime as _shutdown_geometry_bake_runtime,
)
from .bones import bake_bone_transforms, current_bone_targets
from .clear import clear_physics_bake, shutdown_clear_runtime


def shutdown_geometry_bake_runtime() -> None:
    _shutdown_geometry_bake_runtime()
    shutdown_clear_runtime()


def reset_geometry_bake_runtime_for_tests() -> None:
    _reset_geometry_bake_runtime_for_tests()
    shutdown_clear_runtime()


__all__ = [
    "bake_bone_transforms",
    "cancel_pending_geometry_bake",
    "clear_physics_bake",
    "current_bone_targets",
    "current_mesh_targets",
    "geometry_bake_is_active",
    "geometry_bake_should_record_actions",
    "geometry_bake_status",
    "geometry_bake_target_count",
    "rearm_geometry_bake_trigger",
    "request_geometry_bake",
    "reset_geometry_bake_runtime_for_tests",
    "run_pending_geometry_bake",
    "set_session_cache_playback",
    "shutdown_geometry_bake_runtime",
]
