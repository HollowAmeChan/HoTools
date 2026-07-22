"""HoTools 根插件使用的唯一 Physics World Blender 生命周期入口。"""

from .registry import (
    register_physics_world_blender_properties,
    unregister_physics_world_blender_properties,
)


_ACTIVE = False


def register() -> None:
    global _ACTIVE
    if _ACTIVE:
        return
    from .ui import register as register_ui
    from .source_revisions import register as register_source_revisions

    register_physics_world_blender_properties()
    try:
        register_source_revisions()
        register_ui()
    except Exception:
        from .source_revisions import unregister as unregister_source_revisions

        unregister_source_revisions()
        unregister_physics_world_blender_properties()
        raise
    _ACTIVE = True


def unregister() -> None:
    global _ACTIVE
    if not _ACTIVE:
        return
    from .ui import unregister as unregister_ui
    from .bake import shutdown_geometry_bake_runtime
    from .source_revisions import unregister as unregister_source_revisions

    shutdown_geometry_bake_runtime()
    unregister_ui()
    unregister_source_revisions()
    unregister_physics_world_blender_properties()
    _ACTIVE = False


def is_registered() -> bool:
    return bool(_ACTIVE)


__all__ = ["is_registered", "register", "unregister"]
