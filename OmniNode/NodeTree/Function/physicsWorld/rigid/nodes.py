"""
physicsWorld.rigid.nodes — 刚体 domain 节点定义（Phase 5）

刚体和约束 spec 由 physicsWorldBegin 自动从 scope 收集。
physicsRigidSolver 节点执行 Jolt 模拟步 + 写回 Blender 对象变换。
"""

from ....FunctionNodeCore import omni
from ... import _Color
from .solver import step_rigid_bodies


@omni(
    enable=True,
    bl_label="刚体模拟步",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "启用"],
    _OUTPUT_NAME=["物理世界", "刚体数量", "耗时ms"],
    omni_description="""
    执行 Jolt 刚体模拟步，并把结果写回 Blender 对象变换。

    刚体/约束 spec 已由"物理世界-帧开始"自动收集，无需手动注册节点。

    执行流程：
    1. 获取或创建 JoltAdapter（首帧编译 hotools_jolt 模块未找到时节点静默跳过）。
    2. 首帧或 generation 变化时把 spec 同步到 Jolt（add_body / add_constraint）。
    3. KINEMATIC 刚体每帧跟随 Blender 动画位置。
    4. 执行 Jolt step（dt 和 substeps 来自物理世界帧上下文）。
    5. DYNAMIC 刚体位置/旋转写回 Blender Object.location / rotation_euler。

    hotools_jolt 未编译时透传 world，输出 (world, 0, 0.0)，不报错。
    """,
)
def physicsRigidSolver(
    world: object,
    enabled: bool = True,
) -> tuple[object, int, float]:
    body_count, step_ms = step_rigid_bodies(world, bool(enabled))
    return world, body_count, float(step_ms)
