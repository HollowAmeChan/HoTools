"""MeshCloth 对象、域分区与产品收集合同。"""

from __future__ import annotations

from ...names import MC2_SETUP_MESH_CLOTH
from ...parameters import (
    MC2ParticleProfileSpec,
    MC2TaskParametersSpec,
    make_mc2_particle_profile,
    make_mc2_setup_options,
    make_mc2_task_parameters,
)
from ...partition_specs import (
    MC2PartitionCollectorPlan,
    MC2PartitionEntry,
    MC2_UNSET,
    collect_mc2_partition_entries,
    make_mc2_partition_entry,
)
from ...product_request import MC2_FUSION_REQUIRE, MC2ProductRequestV1
from .object_spec import MC2MeshExplicitPropertiesSpec, MC2MeshObjectSpec


def _flatten_mesh_object_specs(values) -> tuple[MC2MeshObjectSpec, ...]:
    pending = [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        if not isinstance(value, MC2MeshObjectSpec):
            raise TypeError(
                "MC2 MeshCloth域只接受MC2 MeshCloth对象节点包装后的对象"
            )
        result.append(value)
    return tuple(result)


def _flatten_domain_partitions(values) -> tuple[MC2PartitionEntry, ...]:
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
                f"MC2 Mesh域收集只接受Mesh分区，收到{type(value).__name__}"
            )
        if value.setup_type != MC2_SETUP_MESH_CLOTH:
            raise ValueError("MC2 Mesh域收集只接受mesh_cloth分区")
        result.append(value)
    return tuple(result)


def make_mc2_mesh_domain_partitions(
    mesh_objects,
    *,
    profile: MC2ParticleProfileSpec | None = None,
    task_parameters: MC2TaskParametersSpec | None = None,
    anchor_object=None,
    producer: str = "mc2.mesh_cloth_domain",
) -> tuple[MC2PartitionEntry, ...]:
    """把包装对象与域参数组合成无需下游默认值的完整分区。"""

    objects = _flatten_mesh_object_specs(mesh_objects)
    if profile is None:
        profile = make_mc2_particle_profile(spring_enabled=False)
    if task_parameters is None:
        task_parameters = make_mc2_task_parameters()
    if not isinstance(profile, MC2ParticleProfileSpec):
        raise TypeError("MC2 MeshCloth域的粒子配置类型错误")
    if not isinstance(task_parameters, MC2TaskParametersSpec):
        raise TypeError("MC2 MeshCloth域的区域参数类型错误")

    result = []
    for mesh_object in objects:
        properties = mesh_object.explicit_properties
        result.append(make_mc2_partition_entry(
            mesh_object.source_object,
            setup_type=MC2_SETUP_MESH_CLOTH,
            origin="explicit",
            producer=str(producer or "mc2.mesh_cloth_domain"),
            source_properties=properties,
            profile=profile,
            task_parameters=task_parameters,
            setup_options=make_mc2_setup_options(
                MC2_SETUP_MESH_CLOTH,
                self_collision_radius_model="derived_radius",
                collided_by_groups=properties.self_collision_groups,
            ),
            anchor_object=anchor_object,
            enabled=True,
            collision_group=properties.self_group_bit,
            collision_mask=properties.self_collision_groups,
        ))
    return tuple(result)


def _validate_complete_mesh_partition(entry: MC2PartitionEntry) -> None:
    if entry.origin != "explicit":
        raise ValueError("MC2 Mesh域收集不接受隐式分区")
    if not isinstance(entry.source_properties, MC2MeshExplicitPropertiesSpec):
        raise TypeError("MC2 Mesh分区缺少完整对象属性快照")
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
            raise ValueError(f"MC2 Mesh分区字段{name}未在域节点完成解析")
    if entry.enabled is not True:
        raise ValueError("MC2 Mesh分区参与关系由连线决定，不接受enabled=False")
    if entry.patches:
        raise ValueError("MC2 Mesh域收集不接受partition patch")


def _collector_report_text(plan: MC2PartitionCollectorPlan) -> str:
    report = plan.report
    lines = [
        (
            f"MC2 Mesh统一域：收集{report.partition_count}个完整分区；"
            "策略Require Fusion；后端CPU DomainV1。"
        ),
        f"Domain签名：{report.domain_signature}",
    ]
    lines.extend(
        f"[{partition.partition_index}] {partition.stable_id}；来源"
        f"{partition.origins[0]}；对象属性已解析。"
        for partition in plan.partitions
    )
    return "\n".join(lines)


def make_mc2_mesh_product_request(entries) -> MC2ProductRequestV1:
    """只收集完整Mesh分区，不读取World、隐式注册或collector默认值。"""

    partitions = _flatten_domain_partitions(entries)
    if not partitions:
        raise ValueError("MC2 Mesh域收集没有输入分区")
    seen = set()
    for entry in partitions:
        _validate_complete_mesh_partition(entry)
        if entry.stable_id in seen:
            raise ValueError(f"MC2 Mesh域收集发现重复stable id：{entry.stable_id}")
        seen.add(entry.stable_id)

    plan = collect_mc2_partition_entries(
        setup_type=MC2_SETUP_MESH_CLOTH,
        explicit_entries=partitions,
        implicit_entries=(),
    )
    return MC2ProductRequestV1(
        plan=plan,
        fusion_policy=MC2_FUSION_REQUIRE,
        report_text=_collector_report_text(plan),
    )


__all__ = [
    "make_mc2_mesh_domain_partitions",
    "make_mc2_mesh_product_request",
]
