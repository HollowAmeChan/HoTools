"""XPBD 家族共享调试的轻量调度层。"""

from __future__ import annotations

from .bone_xpbd.debug_draw import update_bone_xpbd_debug_draw_store
from .simple_mesh_xpbd.debug_draw import update_mesh_xpbd_debug_draw_store


def update_xpbd_debug_draw_stores(
    node_uid: str,
    world,
    *,
    show_particles: bool,
    show_stretch: bool,
    show_bend: bool,
    max_items: int,
) -> str:
    """用同一组通用开关驱动两个域各自的真实运行快照。"""
    enabled = bool(show_particles or show_stretch or show_bend)
    mesh_status = update_mesh_xpbd_debug_draw_store(
        f"{node_uid}:mesh",
        world,
        enabled,
        max_items=max_items,
        show_particles=show_particles,
        show_stretch=show_stretch,
        show_bend=show_bend,
    )
    bone_status = update_bone_xpbd_debug_draw_store(
        f"{node_uid}:bone",
        world,
        show_particles=show_particles,
        show_segments=show_stretch,
        show_bend=show_bend,
        max_items=max_items,
    )
    return f"{mesh_status}\n{bone_status}"


__all__ = ["update_xpbd_debug_draw_stores"]
