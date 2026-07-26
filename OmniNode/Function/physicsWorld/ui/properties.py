"""Physics World UI 的稳定 Scene RNA 声明。"""

from .collision_preview import COLLISION_OVERLAY_PREVIEW_MODE_ITEMS
from .utils import _overlay_show_update


PHYSICS_UI_BLENDER_PROPERTIES = {
    "bindings": (
        {"owner": "Scene", "name": "ho_collision_overlay_show", "property": "bool", "kwargs": {"name": "HoTools碰撞预览", "description": "在3D视图中显示HoTools碰撞预览叠加层", "default": False, "update": _overlay_show_update}},
        {"owner": "Scene", "name": "ho_collision_overlay_show_bone", "property": "bool", "kwargs": {"name": "骨骼碰撞体", "default": True, "update": _overlay_show_update}},
        {"owner": "Scene", "name": "ho_collision_overlay_only_visible_bones", "property": "bool", "kwargs": {"name": "仅显示可见骨", "description": "仅绘制在当前视图层中有效可见的骨骼碰撞体", "default": False, "update": _overlay_show_update}},
        {"owner": "Scene", "name": "ho_collision_overlay_preview_mode", "property": "enum", "kwargs": {"name": "预览模式", "description": "切换碰撞预览的查看方式", "items": COLLISION_OVERLAY_PREVIEW_MODE_ITEMS, "default": "STANDARD", "update": _overlay_show_update}},
        {"owner": "Scene", "name": "ho_collision_overlay_include_passive_collision", "property": "bool", "kwargs": {"name": "额外显示简单碰撞", "description": "在碰撞组交互检查模式下，同时显示被该组命中的简单碰撞体", "default": False, "update": _overlay_show_update}},
        {"owner": "Scene", "name": "ho_collision_overlay_color_mode", "property": "enum", "kwargs": {"name": "颜色模式", "description": "切换碰撞叠加层的颜色含义", "items": [("GROUP", "主碰撞组", "按主碰撞组显示颜色"), ("PIN", "Pin状态", "按是否固定显示颜色")], "default": "GROUP", "update": _overlay_show_update}},
        {"owner": "Scene", "name": "ho_collision_overlay_show_object", "property": "bool", "kwargs": {"name": "物体碰撞体", "default": True, "update": _overlay_show_update}},
        {"owner": "Scene", "name": "ho_bone_collision_show_info_section", "property": "bool", "kwargs": {"name": "信息", "default": True}},
        {"owner": "Scene", "name": "ho_bone_collision_show_roots_section", "property": "bool", "kwargs": {"name": "活动骨碰撞", "default": True}},
    ),
}


__all__ = ["PHYSICS_UI_BLENDER_PROPERTIES"]
