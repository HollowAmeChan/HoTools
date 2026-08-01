"""BoneCloth/BoneSpring 的显式统一域产品 authoring。"""

from __future__ import annotations

from dataclasses import replace

from ...names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ...parameters import (
    MC2ParticleProfileSpec,
    MC2SetupOptionsSpec,
    MC2TaskParametersSpec,
    make_mc2_particle_profile,
    make_mc2_setup_options,
    make_mc2_task_parameters,
)
from ...partition_specs import (
    MC2PartitionEntry,
    MC2_UNSET,
    collect_mc2_partition_entries,
    make_mc2_partition_entry,
)
from ...product_request import MC2_FUSION_REQUIRE, MC2ProductRequestV1
from .object_spec import (
    MC2BoneClothExplicitPropertiesSpec,
    MC2BoneClothObjectSpec,
)
from .source_spec import (
    MC2BonePartitionSourceV1,
    make_mc2_bone_chain_source,
)


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


def _flatten_bone_object_specs(values):
    pending = [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        if not isinstance(value, MC2BoneClothObjectSpec):
            raise TypeError(
                "MC2 BoneCloth domain only accepts wrapped BoneCloth objects"
            )
        result.append(value)
    return tuple(result)


def make_mc2_bone_cloth_domain_partitions(
    bone_objects,
    *,
    profile: MC2ParticleProfileSpec | None = None,
    task_parameters: MC2TaskParametersSpec | None = None,
    setup_options: MC2SetupOptionsSpec | None = None,
    anchor_object=None,
    producer: str = "mc2.bone_cloth_domain",
) -> tuple[MC2PartitionEntry, ...]:
    """Combine wrapped objects and domain values into complete partitions."""

    objects = _flatten_bone_object_specs(bone_objects)
    if profile is None:
        profile = make_mc2_particle_profile(spring_enabled=False)
    if task_parameters is None:
        task_parameters = make_mc2_task_parameters()
    if setup_options is None:
        setup_options = make_mc2_setup_options(
            MC2_SETUP_BONE_CLOTH,
            connection_model="hotools_product",
            self_collision_radius_model="derived_radius",
        )
    if not isinstance(profile, MC2ParticleProfileSpec):
        raise TypeError("MC2 BoneCloth domain particle profile type is invalid")
    if not isinstance(task_parameters, MC2TaskParametersSpec):
        raise TypeError("MC2 BoneCloth domain task parameter type is invalid")
    if (
        not isinstance(setup_options, MC2SetupOptionsSpec)
        or setup_options.setup_type != MC2_SETUP_BONE_CLOTH
    ):
        raise TypeError("MC2 BoneCloth domain setup options are invalid")

    result = []
    for bone_object in objects:
        properties = bone_object.explicit_properties
        partition_options = replace(
            setup_options,
            collided_by_groups=properties.collided_by_groups,
        )
        result.append(make_mc2_partition_entry(
            bone_object.partition_source,
            setup_type=MC2_SETUP_BONE_CLOTH,
            origin="explicit",
            producer=str(producer or "mc2.bone_cloth_domain"),
            source_properties=properties,
            profile=profile,
            task_parameters=task_parameters,
            setup_options=partition_options,
            anchor_object=anchor_object,
            enabled=True,
            collision_group=properties.self_group_bit,
            collision_mask=properties.self_collision_groups,
        ))
    return tuple(result)


def _flatten_bone_cloth_partitions(values) -> tuple[MC2PartitionEntry, ...]:
    pending = [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        if not isinstance(value, MC2PartitionEntry):
            raise TypeError(
                f"MC2 Bone domain collector only accepts Bone partitions, got "
                f"{type(value).__name__}"
            )
        if value.setup_type != MC2_SETUP_BONE_CLOTH:
            raise ValueError(
                "MC2 Bone domain collector only accepts bone_cloth partitions"
            )
        result.append(value)
    return tuple(result)


def _validate_complete_bone_cloth_partition(entry: MC2PartitionEntry) -> None:
    if entry.origin != "explicit":
        raise ValueError("MC2 Bone domain collector rejects implicit partitions")
    if not isinstance(entry.source, MC2BonePartitionSourceV1):
        raise TypeError("MC2 BoneCloth partition source is invalid")
    if not isinstance(
        entry.source_properties, MC2BoneClothExplicitPropertiesSpec
    ):
        raise TypeError("MC2 BoneCloth partition lacks complete object properties")
    for name in (
        "profile",
        "task_parameters",
        "setup_options",
        "anchor_object",
        "enabled",
        "collision_group",
        "collision_mask",
    ):
        if getattr(entry, name) is MC2_UNSET:
            raise ValueError(
                f"MC2 BoneCloth partition field {name} was not resolved by the domain"
            )
    if entry.enabled is not True:
        raise ValueError(
            "MC2 BoneCloth participation is expressed by links, not enabled=False"
        )
    if entry.patches:
        raise ValueError("MC2 Bone domain collector rejects partition patches")


def _armature_key(entry: MC2PartitionEntry) -> tuple[int, int]:
    armature = entry.source.armature
    pointer = getattr(armature, "as_pointer", None)
    data_pointer = getattr(getattr(armature, "data", None), "as_pointer", None)
    owner = int(pointer()) if callable(pointer) else 0
    data = int(data_pointer()) if callable(data_pointer) else 0
    if owner <= 0 or data <= 0:
        raise ValueError("MC2 BoneCloth Armature identity is invalid")
    return owner, data


def make_mc2_bone_cloth_product_requests(
    entries,
) -> tuple[MC2ProductRequestV1, ...]:
    """Collect complete partitions into visible per-Armature requests."""

    partitions = _flatten_bone_cloth_partitions(entries)
    if not partitions:
        raise ValueError("MC2 Bone domain collector has no input partitions")
    grouped: dict[tuple[int, int], list[MC2PartitionEntry]] = {}
    seen = set()
    for entry in partitions:
        _validate_complete_bone_cloth_partition(entry)
        if entry.stable_id in seen:
            raise ValueError(
                f"MC2 Bone domain collector found duplicate stable id: "
                f"{entry.stable_id}"
            )
        seen.add(entry.stable_id)
        grouped.setdefault(_armature_key(entry), []).append(entry)

    requests = []
    for armature_partitions in grouped.values():
        plan = collect_mc2_partition_entries(
            setup_type=MC2_SETUP_BONE_CLOTH,
            explicit_entries=tuple(armature_partitions),
            implicit_entries=(),
        )
        armature = armature_partitions[0].source.armature
        report = (
            f"{_report_text(plan)}\n"
            f"Grouping: Armature {getattr(armature, 'name_full', getattr(armature, 'name', ''))}"
        )
        requests.append(MC2ProductRequestV1(
            plan=plan,
            fusion_policy=MC2_FUSION_REQUIRE,
            report_text=report,
        ))
    return tuple(requests)


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

    chains = tuple(make_mc2_bone_chain_source(value) for value in _flatten(root_bones))
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
    "make_mc2_bone_cloth_domain_partitions",
    "make_mc2_bone_cloth_product_requests",
    "make_mc2_bone_spring_product_request",
]
