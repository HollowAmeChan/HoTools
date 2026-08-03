"""Bone XPBD Physics World 用户节点。"""

from __future__ import annotations

import bpy
import mathutils
import typing

from ...FunctionNodeCore import omni
from ...OmniNodeSocketMapping import _OmniBitMask, _OmniBone
from ...config import nodeColors
from .authoring import make_bone_xpbd_tasks
from .object_spec import (
    make_bone_xpbd_custom_objects,
    read_bone_xpbd_panel_objects,
)


@omni(
    enable=True,
    bl_label="Bone XPBD对象",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["实际骨骼"],
    input_init={
        "bones": {
            "description": (
                "显式参与模拟的实际骨骼列表；可直接连接“从根获取骨骼”\n"
                "不会把输入解释成MC2中控骨，也不会只取第一根子骨骼"
            ),
        },
    },
    _OUTPUT_NAME=["Bone XPBD对象", "对象数量"],
    mute_passthrough=False,
    omni_description=(
        "把用户显式给出的实际骨骼按集合包装为Bone XPBD对象。"
        "每根骨映射head/tail两个端点；Pin读取物理世界公共Bone属性及隐式覆盖。"
        "根骨不会被自动固定，父子级也不会生成单向深度。"
    ),
)
def physicsBoneXpbdObject(
    bones: list[_OmniBone],
) -> tuple[list[typing.Any], int]:
    objects = read_bone_xpbd_panel_objects(bones)
    return list(objects), len(objects)


@omni(
    enable=True,
    bl_label="Bone XPBD自定义对象",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["实际骨骼", "Pin启用"],
    input_init={
        "bones": {
            "description": "显式实际骨骼列表；不读取或修改公共Bone面板",
        },
        "pin_enabled": {
            "description": "统一覆写本对象内全部骨段的Pin；每根骨仍固定head与tail",
        },
    },
    _OUTPUT_NAME=["Bone XPBD对象", "对象数量"],
    mute_passthrough=False,
    omni_description=(
        "用socket完整定义Bone XPBD对象的Pin来源。"
        "输出与面板对象节点为同一强类型，但不会读取公共Bone Pin或隐式覆写。"
    ),
)
def physicsBoneXpbdCustomObject(
    bones: list[_OmniBone],
    pin_enabled: bool = False,
) -> tuple[list[typing.Any], int]:
    objects = make_bone_xpbd_custom_objects(
        bones,
        pin_enabled=bool(pin_enabled),
    )
    return list(objects), len(objects)


@omni(
    enable=True,
    bl_label="Bone XPBD任务",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "Bone XPBD对象", "Tail吸附", "外部碰撞", "粒子半径", "被碰撞组",
        "阻尼", "拉伸顺从度", "弯曲顺从度", "迭代", "重力方向", "重力强度",
    ],
    input_init={
        "bone_objects": {
            "description": "只接受Bone XPBD对象或Bone XPBD自定义对象节点输出",
        },
        "tail_follow": {
            "description": (
                "开启时用模拟head->tail方向吸附骨骼旋转；"
                "关闭时只让骨头跟随模拟head并保留输入旋转"
            ),
        },
        "collision_enabled": {"description": "让端点粒子消费公共外部碰撞体"},
        "particle_radius": {"min_value": 0.0},
        "collided_by_groups": {
            "mask_length": 16,
            "default_value": 0,
            "description": "任务统一外碰掩码；0表示不接受外部碰撞",
        },
        "damping": {"min_value": 0.0, "max_value": 1.0},
        "stretch_compliance": {"min_value": 0.0},
        "bend_compliance": {"min_value": 0.0},
        "iterations": {"min_value": 0, "max_value": 64},
        "gravity_power": {"min_value": 0.0},
    },
    _OUTPUT_NAME=["Bone XPBD任务", "任务数量"],
    mute_passthrough=False,
    omni_description=(
        "把一个或多个显式骨骼集合组装成独立Bone XPBD任务。"
        "共点端点按静态rest几何共享粒子，stretch与二阶distance bend均为无向约束；"
        "没有深度、根节点特权或父到子的单向传播。多个任务可交给同一个模拟步。"
    ),
)
def physicsBoneXpbdTask(
    bone_objects: list[typing.Any],
    tail_follow: bool = True,
    collision_enabled: bool = False,
    particle_radius: float = 0.05,
    collided_by_groups: _OmniBitMask = 0,
    damping: float = 0.02,
    stretch_compliance: float = 0.0,
    bend_compliance: float = 0.0,
    iterations: int = 16,
    gravity_direction: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
) -> tuple[list[object], int]:
    tasks = make_bone_xpbd_tasks(
        bone_objects,
        tail_follow=bool(tail_follow),
        collision_enabled=bool(collision_enabled),
        particle_radius=particle_radius,
        collided_by_groups=int(collided_by_groups),
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
    bl_label="Bone XPBD可视化调试",
    base_color=nodeColors.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "最大显示项", "模拟粒子", "骨段", "弯曲约束"],
    input_init={
        "max_items": {"min_value": 1, "max_value": 100000},
        "show_particles": {"description": "绿色=Move，红色=Fixed/Pin"},
        "show_segments": {"description": "显示每根骨的真实head/tail粒子线段"},
        "show_bend": {"description": "显示共享关节两侧端点的二阶distance bend"},
    },
    _OUTPUT_NAME=["物理世界", "调试状态"],
    mute_passthrough={"_OUTPUT0": "world"},
    omni_description=(
        "只读取Bone XPBD slot的真实运行快照并绘制，不修改模拟。"
        "首次开启视图后会请求下一次模拟步捕获端点与约束数组。"
    ),
)
def physicsBoneXpbdDebugDraw(
    world: object,
    max_items: int = 10000,
    show_particles: bool = False,
    show_segments: bool = False,
    show_bend: bool = False,
) -> tuple[object, str]:
    from .debug_draw import update_bone_xpbd_debug_draw_store

    status = update_bone_xpbd_debug_draw_store(
        str(id(world)),
        world,
        show_particles=show_particles,
        show_segments=show_segments,
        show_bend=show_bend,
        max_items=max_items,
    )
    return world, status
