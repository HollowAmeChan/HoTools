"""BoneCloth/BoneSpring 的显式统一域产品 authoring。"""

from __future__ import annotations

from dataclasses import dataclass

from ...names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ...parameters import (
    MC2ParticleProfileSpec,
    MC2SetupOptionsSpec,
    MC2TaskParametersSpec,
    make_mc2_particle_profile,
    make_mc2_setup_options,
    make_mc2_task_parameters,
)
from ...partition_specs import collect_mc2_partition_entries, make_mc2_partition_entry
from ...product_request import MC2_FUSION_REQUIRE, MC2ProductRequestV1
from ...source_identity import mc2_source_token


@dataclass(frozen=True)
class MC2BoneChainSourceV1:
    """一个 Armature 内有序且已解析的骨链引用。"""

    armature: object
    root_bone: str
    bone_names: tuple[str, ...]

    def __post_init__(self) -> None:
        root = str(self.root_bone or "").strip()
        names = tuple(str(name or "").strip() for name in self.bone_names)
        if getattr(self.armature, "type", None) != "ARMATURE":
            raise TypeError("Bone product chain 需要有效 Armature Object")
        if not root or not names or any(not name for name in names):
            raise ValueError("Bone product chain 的根骨和骨名不能为空")
        if names[0] != root:
            raise ValueError("Bone product chain 的第一根骨必须等于 root_bone")
        if len(set(names)) != len(names):
            raise ValueError("Bone product chain 不能重复包含同一根骨")
        object.__setattr__(self, "root_bone", root)
        object.__setattr__(self, "bone_names", names)

    def task_source_dict(self) -> dict:
        """仅供 setup capture 适配器读取，不创建 task。"""

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
    """一个 Bone partition 的同 Armature 多链 source。"""

    setup_type: str
    armature: object
    chains: tuple[MC2BoneChainSourceV1, ...]

    def __post_init__(self) -> None:
        if self.setup_type not in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING):
            raise ValueError("Bone partition setup_type 无效")
        if getattr(self.armature, "type", None) != "ARMATURE":
            raise TypeError("Bone partition 需要有效 Armature Object")
        if not self.chains or any(
            not isinstance(chain, MC2BoneChainSourceV1) for chain in self.chains
        ):
            raise TypeError("Bone partition 至少需要一个 MC2BoneChainSourceV1")
        if any(chain.armature is not self.armature for chain in self.chains):
            raise ValueError("Bone partition 的全部骨链必须属于同一 Armature")
        roots = tuple(chain.root_bone for chain in self.chains)
        if len(set(roots)) != len(roots):
            raise ValueError("Bone partition 不能重复包含同一根链")
        if self.setup_type == MC2_SETUP_BONE_SPRING and any(
            not chain.bone_names for chain in self.chains
        ):
            raise ValueError("BoneSpring partition 包含空链")

    @property
    def task_sources(self) -> tuple[dict, ...]:
        return tuple(chain.task_source_dict() for chain in self.chains)

    def mc2_source_token(self) -> dict:
        armature_token = mc2_source_token(self.armature)
        return {
            "kind": "bone_partition_v1",
            "setup_type": self.setup_type,
            "armature": armature_token,
            "chains": tuple(chain.token() for chain in self.chains),
        }


def _flatten(values) -> tuple[object, ...]:
    pending = [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, list):
            pending[0:0] = value
            continue
        result.append(value)
    return tuple(result)


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
        raise ValueError("Bone product chain 超过 4096 根骨，疑似存在非法循环")
    return tuple(names)


def _chain_from_explicit_source(source) -> MC2BoneChainSourceV1:
    if not isinstance(source, dict) or source.get("armature") is None:
        raise TypeError("Bone product source 必须是 Bone socket 或显式 chain dict")
    armature = source["armature"]
    names = tuple(str(name) for name in (source.get("bones") or ()) if str(name))
    root_name = str(source.get("root_bone") or source.get("bone") or "").strip()
    if names:
        root_name = root_name or names[0]
    else:
        pose_bones = getattr(getattr(armature, "pose", None), "bones", None)
        root = pose_bones.get(root_name) if pose_bones is not None else None
        if root is None:
            raise ValueError(f"Bone product root bone not found: {root_name!r}")
        names = _chain_names(root)
    return MC2BoneChainSourceV1(armature, root_name, names)


def _expand_bone_cloth_control(value) -> tuple[MC2BoneChainSourceV1, ...]:
    if isinstance(value, dict) and value.get("armature") is not None:
        if value.get("bones"):
            return (_chain_from_explicit_source(value),)
        armature = value["armature"]
        parent_name = str(value.get("bone") or value.get("root_bone") or "").strip()
    elif isinstance(value, tuple) and len(value) == 2:
        armature, parent_name = value
        parent_name = str(parent_name or "").strip()
    else:
        raise TypeError("BoneCloth product source 必须是控制 Bone socket 或显式 chain")
    pose_bones = getattr(getattr(armature, "pose", None), "bones", None)
    parent = pose_bones.get(parent_name) if pose_bones is not None else None
    if parent is None:
        raise ValueError(f"BoneCloth control bone not found: {parent_name!r}")
    children = tuple(getattr(parent, "children", ()) or ())
    if not children:
        raise ValueError(f"BoneCloth control bone has no child chains: {parent_name!r}")
    return tuple(
        MC2BoneChainSourceV1(armature, names[0], names)
        for names in (_chain_names(child) for child in children)
        if names
    )


def _one_armature(groups) -> object:
    armatures = tuple(
        chain.armature
        for group in groups
        for chain in group
    )
    if not armatures:
        raise ValueError("Bone product collector 没有启用的骨链")
    armature = armatures[0]
    if any(candidate is not armature for candidate in armatures[1:]):
        raise ValueError(
            "Require Fusion Bone collector 只接受一个 Armature；"
            "请为不同 Armature 使用多个显式 collector"
        )
    return armature


def _report_text(plan) -> str:
    report = plan.report
    return (
        f"MC2 {plan.setup_type}统一域：融合 {report.active_partition_count} 个分区；"
        f"骨架 1；策略 Require Fusion；后端 CPU DomainV1。\n"
        f"Domain签名：{report.domain_signature}"
    )


def _request_from_groups(
    setup_type: str,
    groups,
    *,
    profile: MC2ParticleProfileSpec | None,
    task_parameters: MC2TaskParametersSpec | None,
    setup_options: MC2SetupOptionsSpec | None,
    anchor_object,
    enabled: bool,
) -> MC2ProductRequestV1:
    normalized_groups = []
    for group in groups:
        frozen = tuple(group)
        if frozen:
            normalized_groups.append(frozen)
    groups = tuple(normalized_groups)
    armature = _one_armature(groups)
    if profile is None:
        profile = make_mc2_particle_profile(spring_enabled=False)
    if task_parameters is None:
        task_parameters = make_mc2_task_parameters()
    if setup_options is None:
        setup_options = make_mc2_setup_options(setup_type)
    entries = tuple(
        make_mc2_partition_entry(
            MC2BonePartitionSourceV1(setup_type, armature, group),
            setup_type=setup_type,
            origin="explicit",
            producer=f"mc2.{setup_type}_product_node",
            profile=profile,
            task_parameters=task_parameters,
            setup_options=setup_options,
            anchor_object=anchor_object,
            enabled=bool(enabled),
        )
        for group in groups
    )
    plan = collect_mc2_partition_entries(
        setup_type=setup_type,
        explicit_entries=entries,
    )
    if not plan.active_partitions:
        raise ValueError(f"MC2 {setup_type} collector 没有启用的分区")
    return MC2ProductRequestV1(
        plan=plan,
        fusion_policy=MC2_FUSION_REQUIRE,
        report_text=_report_text(plan),
    )


def make_mc2_bone_cloth_product_request(
    control_bones,
    *,
    profile: MC2ParticleProfileSpec | None = None,
    task_parameters: MC2TaskParametersSpec | None = None,
    setup_options: MC2SetupOptionsSpec | None = None,
    anchor_object=None,
    enabled: bool = True,
) -> MC2ProductRequestV1:
    """每个控制骨形成一个 partition；显式链按首次出现位置合并。"""

    groups: list[list[MC2BoneChainSourceV1]] = []
    explicit_group_index = None
    for value in _flatten(control_bones):
        chains = _expand_bone_cloth_control(value)
        explicit = isinstance(value, dict) and bool(value.get("bones"))
        if explicit:
            if explicit_group_index is None:
                explicit_group_index = len(groups)
                groups.append([])
            groups[explicit_group_index].extend(chains)
        else:
            groups.append(list(chains))
    return _request_from_groups(
        MC2_SETUP_BONE_CLOTH,
        groups,
        profile=profile,
        task_parameters=task_parameters,
        setup_options=setup_options,
        anchor_object=anchor_object,
        enabled=enabled,
    )


def make_mc2_bone_spring_product_request(
    root_bones,
    *,
    profile: MC2ParticleProfileSpec | None = None,
    task_parameters: MC2TaskParametersSpec | None = None,
    setup_options: MC2SetupOptionsSpec | None = None,
    anchor_object=None,
    enabled: bool = True,
) -> MC2ProductRequestV1:
    """同 Armature 的全部 root chain 形成一个 Line partition。"""

    chains = tuple(_chain_from_explicit_source(value) for value in _flatten(root_bones))
    if setup_options is None:
        setup_options = make_mc2_setup_options(
            MC2_SETUP_BONE_SPRING,
            connection_mode=0,
        )
    if setup_options.setup_type != MC2_SETUP_BONE_SPRING:
        raise ValueError("BoneSpring setup options 不匹配")
    if setup_options.connection_mode != 0:
        raise ValueError("BoneSpring 产品统一域只支持 Line connection mode")
    return _request_from_groups(
        MC2_SETUP_BONE_SPRING,
        (chains,),
        profile=profile,
        task_parameters=task_parameters,
        setup_options=setup_options,
        anchor_object=anchor_object,
        enabled=enabled,
    )


__all__ = [
    "MC2BoneChainSourceV1",
    "MC2BonePartitionSourceV1",
    "make_mc2_bone_cloth_product_request",
    "make_mc2_bone_spring_product_request",
]
