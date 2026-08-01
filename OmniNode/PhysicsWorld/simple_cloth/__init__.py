"""Physics World 简单布料公共对象与资源语义。"""

from __future__ import annotations

from importlib import import_module


COMPONENT_MODULE = {
    "component_id": "simple_cloth",
    "kind": "core",
    "depends_on": ("collision",),
    "capabilities": ".capabilities:SIMPLE_CLOTH_CAPABILITIES",
    "blender_properties": ".properties:SIMPLE_CLOTH_BLENDER_PROPERTIES",
}


_EXPORTS = {
    "PG_Hotools_MeshCollision": ".properties",
    "SIMPLE_CLOTH_BLENDER_PROPERTIES": ".properties",
    "SIMPLE_CLOTH_CAPABILITIES": ".capabilities",
    "SIMPLE_CLOTH_CAPABILITY": ".capabilities",
    "SIMPLE_CLOTH_CAPABILITY_ID": ".capabilities",
    "SIMPLE_CLOTH_RNA_FIELDS": ".schema",
    "SimpleClothRuntimeResources": ".authoring",
    "clear_gn_local_offsets": ".output",
    "ensure_simple_cloth_resources": ".authoring",
    "ensure_gn_offset_output": ".output",
    "iter_gn_offset_writebacks": ".results",
    "make_gn_offset_writeback": ".results",
    "prepare_simple_cloth_panel_objects": ".authoring",
    "publish_gn_offset_writeback": ".results",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = ["COMPONENT_MODULE", *sorted(_EXPORTS)]
