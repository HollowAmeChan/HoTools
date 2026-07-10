"""meshClothBasePose 兼容适配；实现已迁入 physicsWorld.mesh_cloth。"""

from importlib import import_module


def _canonical_module():
    package_root = __package__.split(".", 1)[0] if "." in __package__ else "HoTools"
    return import_module(
        f"{package_root}.OmniNode.NodeTree.Function.physicsWorld.mesh_cloth.base_pose"
    )


def __getattr__(name: str):
    value = getattr(_canonical_module(), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(dir(_canonical_module())))
