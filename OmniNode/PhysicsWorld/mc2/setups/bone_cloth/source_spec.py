"""Immutable BoneCloth/BoneSpring authoring source descriptors."""

from __future__ import annotations

from dataclasses import dataclass

from ...names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ...source_identity import mc2_source_token


@dataclass(frozen=True)
class MC2BoneChainSourceV1:
    """One ordered and resolved Bone chain within an Armature."""

    armature: object
    root_bone: str
    bone_names: tuple[str, ...]

    def __post_init__(self) -> None:
        root = str(self.root_bone or "").strip()
        names = tuple(str(name or "").strip() for name in self.bone_names)
        if getattr(self.armature, "type", None) != "ARMATURE":
            raise TypeError("Bone product chain requires an Armature Object")
        if not root or not names or any(not name for name in names):
            raise ValueError("Bone product chain root and names cannot be empty")
        if names[0] != root:
            raise ValueError("Bone product chain must start with root_bone")
        if len(set(names)) != len(names):
            raise ValueError("Bone product chain cannot repeat a Bone")
        object.__setattr__(self, "root_bone", root)
        object.__setattr__(self, "bone_names", names)

    def task_source_dict(self) -> dict:
        return {
            "armature": self.armature,
            "root_bone": self.root_bone,
            "bones": self.bone_names,
        }

    def token(self) -> dict:
        return {
            "root_bone": self.root_bone,
            "bones": self.bone_names,
        }


@dataclass(frozen=True)
class MC2BonePartitionSourceV1:
    """One setup partition containing one or more same-Armature chains."""

    setup_type: str
    armature: object
    chains: tuple[MC2BoneChainSourceV1, ...]

    def __post_init__(self) -> None:
        chains = tuple(self.chains)
        object.__setattr__(self, "chains", chains)
        if self.setup_type not in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING):
            raise ValueError("Bone partition setup_type is invalid")
        if getattr(self.armature, "type", None) != "ARMATURE":
            raise TypeError("Bone partition requires an Armature Object")
        if not chains or any(
            not isinstance(chain, MC2BoneChainSourceV1) for chain in chains
        ):
            raise TypeError("Bone partition requires MC2BoneChainSourceV1 values")
        if any(chain.armature is not self.armature for chain in chains):
            raise ValueError("Bone partition chains must share one Armature")
        roots = tuple(chain.root_bone for chain in chains)
        if len(set(roots)) != len(roots):
            raise ValueError("Bone partition cannot repeat a root chain")

    @property
    def task_sources(self) -> tuple[dict, ...]:
        return tuple(chain.task_source_dict() for chain in self.chains)

    def mc2_source_token(self) -> dict:
        return {
            "kind": "bone_partition_v1",
            "setup_type": self.setup_type,
            "armature": mc2_source_token(self.armature),
            "chains": tuple(chain.token() for chain in self.chains),
        }


def _chain_names(root_bone) -> tuple[str, ...]:
    names = []
    current = root_bone
    guard = 0
    while current is not None and guard < 4096:
        name = str(getattr(current, "name", "") or "").strip()
        if name:
            names.append(name)
        children = tuple(getattr(current, "children", ()) or ())
        current = children[0] if children else None
        guard += 1
    if current is not None:
        raise ValueError("Bone product chain exceeds the 4096 Bone limit")
    return tuple(names)


def make_mc2_bone_chain_source(source) -> MC2BoneChainSourceV1:
    if not isinstance(source, dict) or source.get("armature") is None:
        raise TypeError("Bone product source must be a Bone socket or chain dict")
    armature = source["armature"]
    names = tuple(str(name) for name in (source.get("bones") or ()) if str(name))
    root_name = str(source.get("root_bone") or source.get("bone") or "").strip()
    if names:
        root_name = root_name or names[0]
    else:
        pose_bones = getattr(getattr(armature, "pose", None), "bones", None)
        root = pose_bones.get(root_name) if pose_bones is not None else None
        if root is None:
            raise ValueError(f"Bone product root Bone not found: {root_name!r}")
        names = _chain_names(root)
    return MC2BoneChainSourceV1(armature, root_name, names)


def expand_mc2_bone_cloth_control(
    value,
) -> tuple[MC2BoneChainSourceV1, ...]:
    if isinstance(value, dict) and value.get("armature") is not None:
        if value.get("bones"):
            return (make_mc2_bone_chain_source(value),)
        armature = value["armature"]
        parent_name = str(value.get("bone") or value.get("root_bone") or "").strip()
    elif isinstance(value, tuple) and len(value) == 2:
        armature, parent_name = value
        parent_name = str(parent_name or "").strip()
    else:
        raise TypeError("BoneCloth source must be a control Bone socket or chain")
    pose_bones = getattr(getattr(armature, "pose", None), "bones", None)
    parent = pose_bones.get(parent_name) if pose_bones is not None else None
    if parent is None:
        raise ValueError(f"BoneCloth control Bone not found: {parent_name!r}")
    children = tuple(getattr(parent, "children", ()) or ())
    if not children:
        raise ValueError(f"BoneCloth control Bone has no child chains: {parent_name!r}")
    return tuple(
        MC2BoneChainSourceV1(armature, names[0], names)
        for names in (_chain_names(child) for child in children)
        if names
    )


def mc2_bone_cloth_property_owner(value) -> tuple[object, str]:
    if isinstance(value, dict) and value.get("armature") is not None:
        armature = value["armature"]
        names = tuple(str(name) for name in (value.get("bones") or ()) if str(name))
        bone_name = str(
            value.get("bone") or value.get("root_bone") or (names[0] if names else "")
        ).strip()
    elif isinstance(value, tuple) and len(value) == 2:
        armature, bone_name = value
        bone_name = str(bone_name or "").strip()
    else:
        raise TypeError("BoneCloth object source must be a Bone socket or chain")
    if getattr(armature, "type", None) != "ARMATURE" or not bone_name:
        raise TypeError("BoneCloth object source requires an Armature and Bone name")
    return armature, bone_name


def make_mc2_bone_cloth_partition_source(value) -> MC2BonePartitionSourceV1:
    chains = expand_mc2_bone_cloth_control(value)
    if not chains:
        raise ValueError("BoneCloth object source did not produce any chains")
    return MC2BonePartitionSourceV1(
        MC2_SETUP_BONE_CLOTH,
        chains[0].armature,
        chains,
    )


__all__ = [
    "MC2BoneChainSourceV1",
    "MC2BonePartitionSourceV1",
    "expand_mc2_bone_cloth_control",
    "make_mc2_bone_chain_source",
    "make_mc2_bone_cloth_partition_source",
    "mc2_bone_cloth_property_owner",
]
