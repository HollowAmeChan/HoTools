"""
physicsWorld.rigid.nodes — 刚体 domain 节点定义

Phase 4：刚体和约束 spec 已由 physicsWorldBegin 自动从 scope 收集，
无需用户额外接节点。本文件预留 Phase 5 的 Jolt 模拟步节点占位。

Phase 5 节点（Jolt backend 接入后启用）：
  physicsRigidSolver — Jolt 模拟步：step + writeback
"""

from ....FunctionNodeCore import omni
from ... import _Color


@omni(
    enable=True,
    bl_label="刚体模拟步",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "启用"],
    _OUTPUT_NAME=["物理世界"],
    omni_description="""
    刚体 Jolt 模拟步（Phase 5 占位节点）。

    刚体 spec 和约束 spec 已由"物理世界-帧开始"自动从对象范围收集，
    无需手动注册。此节点在 Phase 5 接入 Jolt backend 后将负责
    执行实际模拟步并写回对象变换。

    Phase 4 阶段此节点透传 world，无实际运算。
    """,
)
def physicsRigidSolver(
    world: object,
    enabled: bool = True,
) -> object:
    # Phase 5: 接入 Jolt step + writeback
    # Phase 4: 透传，spec 已由 physicsWorldBegin 自动收集
    return world
