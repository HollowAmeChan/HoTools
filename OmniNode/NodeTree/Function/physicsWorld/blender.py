"""HoTools 根插件使用的唯一 Physics World Blender 生命周期入口。"""

from .registry import (
    register_physics_world_blender_properties,
    unregister_physics_world_blender_properties,
)


_ACTIVE = False


def register() -> None:
    global _ACTIVE
    from .gn_offset import refresh_managed_gn_node_groups

    if _ACTIVE:
        refresh_managed_gn_node_groups()
        return
    from .ui import register as register_ui

    refresh_managed_gn_node_groups()
    register_physics_world_blender_properties()
    try:
        register_ui()
    except Exception:
        unregister_physics_world_blender_properties()
        raise
    _ACTIVE = True


def unregister() -> None:
    global _ACTIVE
    if not _ACTIVE:
        return
    from .ui import unregister as unregister_ui
    from .bake import shutdown_geometry_bake_runtime

    shutdown_geometry_bake_runtime()
    unregister_ui()
    unregister_physics_world_blender_properties()
    _ACTIVE = False


def is_registered() -> bool:
    return bool(_ACTIVE)


__all__ = ["is_registered", "register", "unregister"]
