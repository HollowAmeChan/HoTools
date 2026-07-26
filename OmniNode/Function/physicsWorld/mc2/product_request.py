"""MC2 统一粒子域的 setup 中立产品请求合同。"""

from __future__ import annotations

from dataclasses import dataclass

from .partition_specs import MC2PartitionCollectorPlan


MC2_FUSION_REQUIRE = "REQUIRE_FUSION"


@dataclass(frozen=True)
class MC2ProductRequestV1:
    """一个显式 collector 对应的唯一统一粒子域请求。"""

    plan: MC2PartitionCollectorPlan
    fusion_policy: str
    report_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.plan, MC2PartitionCollectorPlan):
            raise TypeError("plan 必须是 MC2PartitionCollectorPlan")
        if self.fusion_policy != MC2_FUSION_REQUIRE:
            raise ValueError("当前产品 collector 只允许 Require Fusion")
        if not self.plan.active_partitions:
            raise ValueError("产品请求至少需要一个启用的分区")
        if not str(self.report_text or "").strip():
            raise ValueError("产品请求必须包含可读报告")

    @property
    def setup_type(self) -> str:
        return self.plan.setup_type

    @property
    def domain_signature(self) -> str:
        return self.plan.report.domain_signature

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_product_request_v1",
            "setup_type": self.setup_type,
            "fusion_policy": self.fusion_policy,
            "report_text": self.report_text,
            "plan": self.plan.report.debug_dict(),
            "partitions": [
                partition.debug_dict() for partition in self.plan.partitions
            ],
        }


__all__ = ["MC2_FUSION_REQUIRE", "MC2ProductRequestV1"]
