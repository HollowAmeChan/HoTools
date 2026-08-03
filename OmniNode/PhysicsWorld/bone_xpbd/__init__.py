"""Physics World Bone XPBD solver 域。"""

from __future__ import annotations

from importlib import import_module


SOLVER_MODULE = {
    "domain": "bone_xpbd",
    "solver_id": "bone_xpbd",
    "menu_name": "Bone XPBD",
    "declaration": ".declaration:BONE_XPBD_SOLVER_DECLARATION",
    "nodes": (".nodes",),
    "scope_restart_handlers": (
        ".feedback:clear_bone_xpbd_feedback",
    ),
    "world_replace_handlers": (
        ".feedback:carry_bone_xpbd_feedback",
    ),
    "world_dispose_handlers": (
        ".debug_draw:dispose_bone_xpbd_debug_draw_for_world",
    ),
}


_LAZY_EXPORTS = {
    "BONE_XPBD_SOLVER_DECLARATION": ".declaration",
    "BONE_XPBD_SOLVER_ID": ".names",
    "BONE_XPBD_SLOT_KIND": ".names",
    "BONE_XPBD_STATS_CHANNEL": ".names",
    "BONE_XPBD_STEP_WRITER_ID": ".names",
    "BoneXpbdObjectSpec": ".object_spec",
    "make_bone_xpbd_custom_objects": ".object_spec",
    "read_bone_xpbd_panel_objects": ".object_spec",
    "BoneXpbdTaskSpec": ".specs",
    "build_bone_xpbd_task_specs": ".specs",
    "make_bone_xpbd_tasks": ".authoring",
    "BoneXpbdSegment": ".topology",
    "BoneXpbdTopology": ".topology",
    "build_bone_xpbd_topology": ".topology",
    "BoneXpbdNativeContext": ".native",
    "step_bone_xpbd": ".solver",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = ["SOLVER_MODULE", *_LAZY_EXPORTS]
