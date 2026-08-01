"""Physics World 基础 Mesh XPBD solver 域。"""

from __future__ import annotations

from importlib import import_module


SOLVER_MODULE = {
    "domain": "mesh_xpbd",
    "solver_id": "mesh_xpbd",
    "menu_name": "Mesh XPBD",
    "declaration": ".declaration:MESH_XPBD_SOLVER_DECLARATION",
    "nodes": (".nodes",),
}


_LAZY_EXPORTS = {
    "MESH_XPBD_NATIVE_LAYOUT_VERSION": ".names",
    "MESH_XPBD_SLOT_KIND": ".names",
    "MESH_XPBD_SOLVER_ID": ".names",
    "MESH_XPBD_STATS_CHANNEL": ".names",
    "MESH_XPBD_STEP_WRITER_ID": ".names",
    "MESH_XPBD_LEGACY_SURFACES": ".declaration",
    "MESH_XPBD_SOLVER_DECLARATION": ".declaration",
    "MeshXpbdObjectPropertiesSpec": ".object_spec",
    "MeshXpbdObjectSpec": ".object_spec",
    "make_mesh_xpbd_custom_object": ".object_spec",
    "make_mesh_xpbd_custom_objects": ".object_spec",
    "read_mesh_xpbd_panel_object": ".object_spec",
    "read_mesh_xpbd_panel_objects": ".object_spec",
    "make_mesh_xpbd_tasks": ".authoring",
    "MeshXpbdTaskSpec": ".specs",
    "build_mesh_xpbd_task_specs": ".specs",
    "make_mesh_xpbd_slot_id": ".specs",
    "MeshXpbdTopology": ".topology",
    "MeshXpbdReferenceFrame": ".topology",
    "build_mesh_xpbd_topology": ".topology",
    "build_mesh_xpbd_reference_frame": ".topology",
    "MeshXpbdColliderFrame": ".colliders",
    "build_mesh_xpbd_collider_frame": ".colliders",
    "MeshXpbdNativeContext": ".native",
    "step_mesh_xpbd": ".solver",
    "get_mesh_xpbd_stats_result": ".results",
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
