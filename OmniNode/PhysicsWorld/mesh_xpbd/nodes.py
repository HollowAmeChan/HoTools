"""Mesh XPBD Physics World 用户节点。"""

from __future__ import annotations

import bpy
import mathutils
import typing

from ...FunctionNodeCore import omni
from ...OmniNodeSocketMapping import _OmniBitMask
from ...config import nodeColors
from ..types import PhysicsWorldCache
from .authoring import make_mesh_xpbd_tasks
from .object_spec import (
    make_mesh_xpbd_custom_objects,
    read_mesh_xpbd_panel_objects,
)
from .solver import step_mesh_xpbd


@omni(
    enable=True,
    bl_label="XPBD网格对象",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体"],
    input_init={
        "mesh_objects": {
            "description": "读取每个Mesh物体面板中XPBD实际消费的Pin、半径组和被碰撞组",
        },
    },
    omni_description=(
        "把一个或多个Mesh物体包装成XPBD模拟对象。对象字段来自物体面板；"
        "解算参数在下游XPBD网格任务中统一设置。"
    ),
    _OUTPUT_NAME=["XPBD网格对象", "对象数量"],
    mute_passthrough=False,
)
def physicsMeshXpbdObject(
    mesh_objects: list[bpy.types.Object],
) -> tuple[list[typing.Any], int]:
    objects = read_mesh_xpbd_panel_objects(mesh_objects)
    return list(objects), len(objects)


@omni(
    enable=True,
    bl_label="XPBD网格自定义对象",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "半径顶点组", "Pin启用", "Pin顶点组", "被碰撞组"],
    input_init={
        "mesh_objects": {
            "description": "一个或多个Mesh物体；不读取它们的Mesh碰撞面板",
        },
        "radius_vertex_group": {
            "description": "逐顶点缩放任务粒子半径的顶点组",
        },
        "pin_enabled": {"description": "启用二值Pin顶点"},
        "pin_vertex_group": {
            "description": "Pin顶点组；启用且留空时固定全部顶点",
        },
        "collided_by_groups": {
            "mask_length": 16,
            "default_value": 0,
            "description": "允许哪些公共碰撞体主组碰撞到此对象\n0:不与任何外部对象碰撞",
        },
    },
    omni_description=(
        "用socket完整定义XPBD对象字段；与面板对象节点输出同一种类型，"
        "且不会读取或修改物体面板。默认被碰撞组为0。"
    ),
    _OUTPUT_NAME=["XPBD网格对象", "对象数量"],
    mute_passthrough=False,
)
def physicsMeshXpbdCustomObject(
    mesh_objects: list[bpy.types.Object],
    radius_vertex_group: str = "",
    pin_enabled: bool = False,
    pin_vertex_group: str = "",
    collided_by_groups: _OmniBitMask = 0,
) -> tuple[list[typing.Any], int]:
    objects = make_mesh_xpbd_custom_objects(
        mesh_objects,
        radius_vertex_group=radius_vertex_group,
        pin_enabled=bool(pin_enabled),
        pin_vertex_group=pin_vertex_group,
        collided_by_groups=int(collided_by_groups),
    )
    return list(objects), len(objects)


@omni(
    enable=True,
    bl_label="XPBD网格任务",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "XPBD网格对象", "外部碰撞", "粒子半径",
        "阻尼", "拉伸顺从度", "弯曲顺从度", "迭代",
        "重力方向", "重力强度",
    ],
    input_init={
        "mesh_objects": {
            "description": "只接受XPBD网格对象或XPBD网格自定义对象节点的输出",
        },
        "collision_radius": {"min_value": 0.0},
        "damping": {"min_value": 0.0, "max_value": 1.0},
        "stretch_compliance": {"min_value": 0.0},
        "bend_compliance": {"min_value": 0.0},
        "iterations": {"min_value": 0, "max_value": 64},
        "gravity_power": {"min_value": 0.0},
    },
    _OUTPUT_NAME=["XPBD网格任务", "任务数量"],
    mute_passthrough=False,
    omni_description="""
    把一个或多个XPBD网格对象与一套共享数值参数组装成独立source tasks，再连接到“XPBD模拟步”。

    对象层决定Pin、半径顶点组和被碰撞组；任务层决定粒子半径、外碰开关与解算参数。
    rest pose 来自 source Mesh 的 Basis/reference key；改变顶点身份的 modifier 不属于本 solver。
    外部碰撞只消费 Physics World Begin 的公共 collider snapshot；对象掩码为0时不接受任何外碰。
    拉伸使用 edge distance；弯曲是共享三角边两侧 opposite vertices 的 distance，不是 dihedral bending。
    """,
)
def physicsMeshXpbdTask(
    mesh_objects: list[typing.Any],
    collision_enabled: bool = False,
    collision_radius: float = 0.05,
    damping: float = 0.02,
    stretch_compliance: float = 0.0,
    bend_compliance: float = 0.001,
    iterations: int = 6,
    gravity_direction: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
) -> tuple[list[object], int]:
    tasks = make_mesh_xpbd_tasks(
        mesh_objects,
        collision_enabled=collision_enabled,
        collision_radius=collision_radius,
        damping=damping,
        stretch_compliance=stretch_compliance,
        bend_compliance=bend_compliance,
        iterations=iterations,
        gravity_direction=gravity_direction,
        gravity_power=gravity_power,
    )
    return list(tasks), len(tasks)


@omni(
    enable=True,
    always_run=True,
    bl_label="XPBD模拟步",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "XPBD网格任务", "调试快照"],
    input_init={
        "mesh_tasks": {"description": "一个或多个XPBD网格任务"},
        "debug_capture": {
            "description": "请求本帧positions、constraints与collider数组进入solver slot调试快照",
        },
    },
    _OUTPUT_NAME=["物理世界", "写回对象数量", "耗时ms"],
    mute_passthrough={"_OUTPUT0": "world"},
    omni_description="""
    Physics World 基础 Mesh XPBD 模拟步。子步数、dt、暂停、同帧和重启只读取公共 frame context。

    solver 使用纯 nanobind RAII context，逐 substep 累计 stretch/bend lambda；
    不扫描 Scene、不直接写 Mesh/Basis/GN，也没有 Python 数值 fallback。
    结果发布到公共 GN offset channel，由下游“物理写回”统一应用。
    多个任务先完整验证并以同一事务发布，任何目标写回失败都会由公共写回回滚整批。
    """,
)
def physicsMeshXpbdSolver(
    world: object,
    mesh_tasks: list[object],
    debug_capture: bool = False,
) -> tuple[object, int, float]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0.0
    if (
        isinstance(mesh_tasks, list)
        and len(mesh_tasks) == 1
        and type(mesh_tasks[0]) is float
        and mesh_tasks[0] == 0.0
    ):
        mesh_tasks = []
    writeback_count, elapsed_ms = step_mesh_xpbd(
        world,
        mesh_tasks,
        debug_capture=bool(debug_capture),
    )
    return world, int(writeback_count), float(elapsed_ms)
