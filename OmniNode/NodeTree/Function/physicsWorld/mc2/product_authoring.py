"""MC2 Mesh 统一域的显式对象、覆盖、隐式 registry 与 collector 合同。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .names import MC2_SETUP_MESH_CLOTH
from .parameters import (
    MC2ParticleProfileSpec,
    MC2SetupOptionsSpec,
    MC2TaskParametersSpec,
    make_mc2_particle_profile,
    make_mc2_setup_options,
    make_mc2_task_parameters,
)
from .partition_specs import (
    MC2PartitionCollectorPlan,
    MC2PartitionEntry,
    MC2_UNSET,
    collect_mc2_partition_entries,
    make_mc2_partition_entry,
)


MC2_MESH_PARTITION_IMPLICIT_TAG = "mc2.mesh_partition.v1"
MC2_MESH_FUSION_REQUIRE = "REQUIRE_FUSION"


def _flatten_entries(values) -> tuple[MC2PartitionEntry, ...]:
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
                f"MC2 Mesh collector 输入必须是 partition entry，收到 {type(value).__name__}"
            )
        if value.setup_type != MC2_SETUP_MESH_CLOTH:
            raise ValueError("MC2 Mesh collector 只接受 mesh_cloth entry")
        result.append(value)
    return tuple(result)


def make_mc2_mesh_partition_entries(
    mesh_objects,
    *,
    producer: str = "mc2.mesh_object_node",
) -> tuple[MC2PartitionEntry, ...]:
    """把显式 Mesh 对象列表转换成稳定 partition entries。"""

    pending = list(mesh_objects) if isinstance(mesh_objects, (list, tuple)) else [mesh_objects]
    sources = []
    while pending:
        source = pending.pop(0)
        if source is None:
            continue
        if isinstance(source, (list, tuple)):
            pending[0:0] = list(source)
            continue
        if getattr(source, "type", None) != "MESH":
            raise TypeError("MC2 Mesh对象节点只接受 Mesh Object")
        sources.append(source)
    return tuple(
        make_mc2_partition_entry(
            source,
            setup_type=MC2_SETUP_MESH_CLOTH,
            origin="explicit",
            producer=producer,
        )
        for source in sources
    )


def override_mc2_mesh_partition_entries(
    entries,
    *,
    profile=MC2_UNSET,
    task_parameters=MC2_UNSET,
    setup_options=MC2_UNSET,
    anchor_object=MC2_UNSET,
    enabled=MC2_UNSET,
    collision_group=MC2_UNSET,
    collision_mask=MC2_UNSET,
    producer: str = "mc2.mesh_override_node",
) -> tuple[MC2PartitionEntry, ...]:
    """对选定 entries 写入一层显式完整覆盖，不修改源对象属性。"""

    normalized = _flatten_entries(entries)
    result = []
    for entry in normalized:
        if entry.origin != "explicit":
            raise ValueError("MC2 Mesh覆盖节点只修改显式 entry")
        result.append(replace(
            entry,
            producer=str(producer or "mc2.mesh_override_node"),
            profile=profile,
            task_parameters=task_parameters,
            setup_options=setup_options,
            anchor_object=anchor_object,
            enabled=enabled,
            collision_group=collision_group,
            collision_mask=collision_mask,
        ))
    return tuple(result)


def register_mc2_mesh_partition_entries(
    world,
    entries,
    *,
    producer: str = "mc2.mesh_partition_registry",
) -> tuple[int, int]:
    """把 entries 作为隐式 producer 快照写入 Physics World registry。"""

    append = getattr(world, "append_implicit_object", None)
    iterate = getattr(world, "iter_implicit_objects", None)
    if not callable(append) or not callable(iterate):
        raise TypeError("world 不支持 Physics World implicit registry")
    explicit = _flatten_entries(entries)
    implicit = tuple(
        replace(
            entry,
            origin="implicit",
            producer=str(producer or "mc2.mesh_partition_registry"),
        )
        for entry in explicit
    )
    seen = set()
    dirty_count = 0
    for entry in implicit:
        seen.add(entry.stable_id)
        enabled = entry.enabled is not False
        item = append(
            tag=MC2_MESH_PARTITION_IMPLICIT_TAG,
            producer=producer,
            stable_id=entry.stable_id,
            signature=entry.signature,
            enabled=enabled,
            schema=1,
            payload={"entry": entry},
        )
        dirty_count += int(bool(item and item.get("dirty")))
    for item in iterate(
        tag=MC2_MESH_PARTITION_IMPLICIT_TAG,
        producer=producer,
        enabled=None,
    ):
        stable_id = str(item.get("stable_id") or "")
        if stable_id in seen or not bool(item.get("enabled", True)):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        stale_entry = payload.get("entry")
        stale_signature = (
            stale_entry.signature
            if isinstance(stale_entry, MC2PartitionEntry)
            else str(item.get("signature") or "")
        )
        updated = append(
            tag=MC2_MESH_PARTITION_IMPLICIT_TAG,
            producer=producer,
            stable_id=stable_id,
            signature=stale_signature,
            enabled=False,
            schema=1,
            payload={"entry": stale_entry},
        )
        dirty_count += int(bool(updated and updated.get("dirty")))
    return len(implicit), dirty_count


def collect_implicit_mc2_mesh_partition_entries(world) -> tuple[MC2PartitionEntry, ...]:
    """读取全部启用的 MC2 Mesh 隐式 partition producers。"""

    iterate = getattr(world, "iter_implicit_objects", None)
    if not callable(iterate):
        raise TypeError("world 不支持 Physics World implicit registry")
    result = []
    for item in iterate(tag=MC2_MESH_PARTITION_IMPLICIT_TAG, enabled=True):
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        entry = payload.get("entry")
        if not isinstance(entry, MC2PartitionEntry):
            raise ValueError("MC2 Mesh implicit registry entry 已损坏")
        if entry.origin != "implicit" or entry.stable_id != item.get("stable_id"):
            raise ValueError("MC2 Mesh implicit registry identity 不一致")
        result.append(entry)
    result.sort(key=lambda entry: entry.stable_id)
    return tuple(result)


def _collector_report_text(plan: MC2PartitionCollectorPlan) -> str:
    report = plan.report
    lines = [
        (
            f"MC2 Mesh统一域：融合 {report.active_partition_count} 个分区；"
            f"显式 {report.explicit_input_count}，隐式 {report.implicit_input_count}，"
            f"显隐合并 {report.merged_partition_count}；策略 Require Fusion；后端 CPU DomainV1。"
        ),
        f"Domain签名：{report.domain_signature}",
    ]
    for partition in plan.partitions:
        sources = dict(partition.field_sources)
        override_count = sum(
            1
            for owner in sources.values()
            if "override" in str(owner).lower()
        )
        origin_text = " + ".join(partition.origins)
        state = "启用" if partition.enabled else "停用"
        lines.append(
            f"[{partition.partition_index}] {partition.stable_id}：{state}；"
            f"来源 {origin_text}；覆盖字段 {override_count}；输出 owner 唯一。"
        )
    return "\n".join(lines)


@dataclass(frozen=True)
class MC2MeshProductRequestV1:
    """collector 节点输出的一个明确 fused Mesh domain 请求。"""

    plan: MC2PartitionCollectorPlan
    fusion_policy: str
    report_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.plan, MC2PartitionCollectorPlan):
            raise TypeError("plan must be MC2PartitionCollectorPlan")
        if self.plan.setup_type != MC2_SETUP_MESH_CLOTH:
            raise ValueError("Mesh product request setup type mismatch")
        if self.fusion_policy != MC2_MESH_FUSION_REQUIRE:
            raise ValueError("当前产品 collector 只允许 Require Fusion")
        if not self.plan.active_partitions:
            raise ValueError("Mesh product request requires active partitions")
        if not str(self.report_text or "").strip():
            raise ValueError("Mesh product request requires a readable report")

    @property
    def domain_signature(self) -> str:
        return self.plan.report.domain_signature

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_mesh_product_request_v1",
            "fusion_policy": self.fusion_policy,
            "report_text": self.report_text,
            "plan": self.plan.report.debug_dict(),
            "partitions": [
                partition.debug_dict() for partition in self.plan.partitions
            ],
        }


def make_mc2_mesh_product_request(
    world,
    explicit_entries=(),
    *,
    include_implicit: bool = True,
    default_profile: MC2ParticleProfileSpec | None = None,
    default_task_parameters: MC2TaskParametersSpec | None = None,
    default_setup_options: MC2SetupOptionsSpec | None = None,
    default_anchor_object=None,
    default_enabled: bool = True,
    default_collision_group: int | None = None,
    default_collision_mask: int = 0xFFFFFFFF,
) -> MC2MeshProductRequestV1:
    """解析显式/隐式输入并生成唯一 Require-Fusion domain request。"""

    if default_profile is None:
        default_profile = make_mc2_particle_profile(spring_enabled=False)
    if default_task_parameters is None:
        default_task_parameters = make_mc2_task_parameters()
    if default_setup_options is None:
        default_setup_options = make_mc2_setup_options(MC2_SETUP_MESH_CLOTH)
    implicit = (
        collect_implicit_mc2_mesh_partition_entries(world)
        if include_implicit
        else ()
    )
    plan = collect_mc2_partition_entries(
        setup_type=MC2_SETUP_MESH_CLOTH,
        explicit_entries=_flatten_entries(explicit_entries),
        implicit_entries=implicit,
        default_profile=default_profile,
        default_task_parameters=default_task_parameters,
        default_setup_options=default_setup_options,
        default_anchor_object=default_anchor_object,
        default_enabled=bool(default_enabled),
        default_collision_group=default_collision_group,
        default_collision_mask=default_collision_mask,
    )
    if not plan.active_partitions:
        raise ValueError("MC2 Mesh collector 没有启用的分区")
    return MC2MeshProductRequestV1(
        plan=plan,
        fusion_policy=MC2_MESH_FUSION_REQUIRE,
        report_text=_collector_report_text(plan),
    )


__all__ = [
    "MC2_MESH_FUSION_REQUIRE",
    "MC2_MESH_PARTITION_IMPLICIT_TAG",
    "MC2MeshProductRequestV1",
    "collect_implicit_mc2_mesh_partition_entries",
    "make_mc2_mesh_partition_entries",
    "make_mc2_mesh_product_request",
    "override_mc2_mesh_partition_entries",
    "register_mc2_mesh_partition_entries",
]
