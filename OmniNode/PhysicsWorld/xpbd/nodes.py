"""XPBD 家族共享的模拟步与通用调试节点。"""

from __future__ import annotations

from ...FunctionNodeCore import omni
from ...config import nodeColors
from ..types import PhysicsWorldCache
from .family_solver import step_xpbd_tasks


@omni(
    enable=True,
    always_run=True,
    bl_label="XPBD模拟步",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "XPBD域任务", "调试快照"],
    input_init={
        "xpbd_tasks": {
            "description": "混合输入一个或多个Simple Mesh XPBD任务、Bone XPBD任务",
        },
        "debug_capture": {
            "description": "请求本帧positions、constraints与collider数组进入域slot调试快照",
        },
    },
    _OUTPUT_NAME=["物理世界", "写回任务数量", "耗时ms"],
    mute_passthrough={"_OUTPUT0": "world"},
    omni_description="""
    Physics World 统一 XPBD 模拟步。一个节点显式消费Simple Mesh与Bone两种域任务；
    子步数、dt、暂停、同帧和重启只读取公共frame context。

    两种域共享nanobind距离约束后端与公共碰撞快照，各自持有独立slot和写回结果；
    不扫描Scene，也没有Python数值fallback。任一域失败会清除整个XPBD家族的写回与slot。
    """,
)
def physicsMeshXpbdSolver(
    world: object,
    xpbd_tasks: list[object],
    debug_capture: bool = False,
) -> tuple[object, int, float]:
    """函数名保持不变，确保已有节点的 bl_idname 不因模块移动而改变。"""
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0.0
    if (
        isinstance(xpbd_tasks, list)
        and len(xpbd_tasks) == 1
        and type(xpbd_tasks[0]) is float
        and xpbd_tasks[0] == 0.0
    ):
        xpbd_tasks = []
    writeback_count, elapsed_ms = step_xpbd_tasks(
        world,
        xpbd_tasks,
        debug_capture=bool(debug_capture),
    )
    return world, int(writeback_count), float(elapsed_ms)


@omni(
    enable=True,
    always_run=True,
    bl_label="XPBD通用可视化调试",
    base_color=nodeColors.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "最大显示项", "模拟粒子", "拉伸约束", "弯曲约束"],
    input_init={
        "max_items": {"min_value": 1, "max_value": 100000},
        "show_particles": {"description": "同时显示网格与骨骼域的Move和Fixed粒子"},
        "show_stretch": {"description": "显示各域实际使用的distance stretch约束"},
        "show_bend": {"description": "显示各域实际使用的distance bend约束"},
    },
    _OUTPUT_NAME=["物理世界", "调试状态"],
    mute_passthrough={"_OUTPUT0": "world"},
    omni_description=(
        "用一组通用开关读取Simple Mesh XPBD与Bone XPBD的真实运行slot。"
        "只注册静态视口绘制状态；运行数据仍由模拟步按需捕获。"
    ),
)
def physicsXpbdDebugDraw(
    world: object,
    max_items: int = 10000,
    show_particles: bool = False,
    show_stretch: bool = False,
    show_bend: bool = False,
) -> tuple[object, str]:
    from .debug_draw import update_xpbd_debug_draw_stores

    status = update_xpbd_debug_draw_stores(
        str(id(world)),
        world,
        show_particles=show_particles,
        show_stretch=show_stretch,
        show_bend=show_bend,
        max_items=max_items,
    )
    return world, status
