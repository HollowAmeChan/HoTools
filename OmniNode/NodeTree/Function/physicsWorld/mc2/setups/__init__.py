"""MC2 setup adapters: MeshCloth、BoneCloth 与 BoneSpring。"""

from .bone_cloth import MC2_BONE_CLOTH_SETUP_ADAPTER
from .bone_spring import MC2_BONE_SPRING_SETUP_ADAPTER
from .mesh_cloth import MC2_MESH_CLOTH_SETUP_ADAPTER


MC2_SETUP_ADAPTERS = {
    adapter.setup_type: adapter
    for adapter in (
        MC2_MESH_CLOTH_SETUP_ADAPTER,
        MC2_BONE_CLOTH_SETUP_ADAPTER,
        MC2_BONE_SPRING_SETUP_ADAPTER,
    )
}


def get_mc2_setup_adapter(setup_type: object):
    key = str(setup_type or "").strip().lower()
    adapter = MC2_SETUP_ADAPTERS.get(key)
    if adapter is None:
        raise ValueError(f"未知 MC2 setup adapter: {setup_type!r}")
    return adapter


def all_mc2_setup_adapters() -> dict:
    return dict(MC2_SETUP_ADAPTERS)


__all__ = [
    "MC2_BONE_CLOTH_SETUP_ADAPTER",
    "MC2_BONE_SPRING_SETUP_ADAPTER",
    "MC2_MESH_CLOTH_SETUP_ADAPTER",
    "MC2_SETUP_ADAPTERS",
    "all_mc2_setup_adapters",
    "get_mc2_setup_adapter",
]
