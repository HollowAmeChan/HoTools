"""旧 PhysicsTools PropertyGroup 导入适配；真实 owner 均位于 physicsWorld。"""

from importlib import import_module


_EXPORT_MODULES = {
    "PG_Hotools_ObjectCollision": "collision.properties",
    "PG_Hotools_MeshCollision": "mesh_cloth.properties",
    "PG_Hotools_RigidBody": "rigid.properties",
    "PG_Hotools_RigidConstraint": "rigid.properties",
}


def __getattr__(name: str):
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    package_root = __package__.split(".", 1)[0] if "." in __package__ else "HoTools"
    module = import_module(
        f"{package_root}.OmniNode.NodeTree.Function.physicsWorld.{module_name}"
    )
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = sorted(_EXPORT_MODULES)
