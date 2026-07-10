"""统一 MC2 solver 的 MeshCloth setup Blender adapter。"""

from importlib import import_module


_EXPORTS = {
    "MESH_COLLISION_CAPABILITY": ".capabilities",
    "MESH_COLLISION_CAPABILITY_ID": ".capabilities",
    "MESH_CLOTH_CAPABILITIES": ".capabilities",
    "MESH_COLLISION_RNA_FIELDS": ".schema",
    "MESH_CLOTH_BLENDER_PROPERTIES": ".properties",
    "PG_Hotools_MeshCollision": ".properties",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = sorted(_EXPORTS)
