"""VRM SpringBone 新物理世界节点定义。"""

from __future__ import annotations

from ....FunctionNodeCore import omni
from ... import _Color
from ..types import PhysicsWorldCache
from .solver import step_spring_vrm


@omni(
    enable=True,
    always_run=True,
    bl_label="SpringBone VRM模拟步",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "VRM链设置", "启用", "子步数"],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
    },
    _OUTPUT_NAME=["物理世界", "写回项数量", "耗时ms"],
    omni_description="""
    新物理世界版 VRM SpringBone 模拟步。

    本节点直接走 C++ / native 计算路径，不提供 Python solver fallback。
    输入的 VRM链设置 仍可来自旧的链设置节点，但旧 solver、旧 cache 和旧写回不会参与。

    执行流程：
    1. 从 VRM链设置 构建 SpringVRMSolverSpec。
    2. 注册到 world.solver_slots["spring_vrm:..."]。
    3. 调用 hotools_native.solve_spring_bone_vrm_cpp。
    4. 发布 world.result_streams["spring_vrm_pose"]。
    5. 下游 物理写回 节点统一写 PoseBone.matrix_basis。

    当前 vertical slice 先验证骨链、native step、result stream 和 PoseBone 写回闭环；
    外部碰撞体打包会在下一步接入 world.collider_snapshot。
    """,
)
def physicsSpringVRMSolver(
    world: object,
    vrm_chain_settings: list[object],
    enabled: bool = True,
    substeps: int = 1,
) -> tuple[object, int, float]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0.0
    write_count, step_ms = step_spring_vrm(
        world,
        vrm_chain_settings,
        enabled=bool(enabled),
        substeps=max(1, int(substeps)),
    )
    return world, int(write_count), float(step_ms)
