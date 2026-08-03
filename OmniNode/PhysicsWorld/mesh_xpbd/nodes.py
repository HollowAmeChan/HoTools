"""Mesh XPBD Physics World 用户节点。"""

from __future__ import annotations

import bpy
import mathutils
import typing

from ...FunctionNodeCore import omni
from ...OmniNodeSocketMapping import _OmniBitMask
from ...config import nodeColors
from ..types import PhysicsWorldCache
from ..simple_cloth.authoring import (
    prepare_simple_cloth_custom_objects,
    prepare_simple_cloth_panel_objects,
)
from .authoring import make_mesh_xpbd_tasks
from .object_spec import (
    make_mesh_xpbd_custom_objects,
    read_mesh_xpbd_panel_objects,
)
from .family_solver import step_xpbd_tasks


@omni(
    enable=True,
    bl_label="XPBD网格对象",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体"],
    input_init={
        "mesh_objects": {
            "description": "只读取已启用简单布料的Mesh物体面板；关闭的物体会被跳过",
        },
    },
    omni_description=(
        "把一个或多个已启用简单布料的Mesh物体包装成XPBD模拟对象。对象字段来自物体面板；"
        "公共简单布料层会在solver前准备共享GN输出，解算参数在下游XPBD网格任务中统一设置。"
    ),
    _OUTPUT_NAME=["XPBD网格对象", "对象数量"],
    mute_passthrough=False,
)
def physicsMeshXpbdObject(
    mesh_objects: list[bpy.types.Object],
) -> tuple[list[typing.Any], int]:
    resources = prepare_simple_cloth_panel_objects(mesh_objects)
    objects = read_mesh_xpbd_panel_objects(
        [resource.source_object for resource in resources]
    )
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
        "且不会读取或修改物体面板。公共简单布料层只准备共享GN资源；默认被碰撞组为0。"
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
    resources = prepare_simple_cloth_custom_objects(mesh_objects)
    objects = make_mesh_xpbd_custom_objects(
        [resource.source_object for resource in resources],
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
    _INPUT_NAME=["物理世界", "XPBD域任务", "调试快照"],
    input_init={
        "xpbd_tasks": {
            "description": "混合输入一个或多个XPBD网格任务、Bone XPBD任务",
        },
        "debug_capture": {
            "description": "请求本帧positions、constraints与collider数组进入solver slot调试快照",
        },
    },
    _OUTPUT_NAME=["物理世界", "写回任务数量", "耗时ms"],
    mute_passthrough={"_OUTPUT0": "world"},
    omni_description="""
    Physics World 统一 XPBD 模拟步。一个节点显式消费Mesh与Bone两种域任务；
    子步数、dt、暂停、同帧和重启只读取公共frame context。

    两种域共享纯nanobind RAII距离约束context，各自持有独立slot和写回结果；
    不扫描Scene、不直接写Mesh或PoseBone，也没有Python数值fallback。
    任一域失败会清除两种XPBD写回并释放本族slot，下次从公共输入冷建。
    """,
)
def physicsMeshXpbdSolver(
    world: object,
    xpbd_tasks: list[object],
    debug_capture: bool = False,
) -> tuple[object, int, float]:
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
    bl_label="XPBD可视化调试",
    base_color=nodeColors.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=[
        "物理世界", "任务筛选", "最大显示项", "模拟粒子", "模拟表面",
        "Stretch误差", "Bend误差", "Rest偏移", "表面法线", "重力",
        "粒子半径", "外部碰撞体", "碰撞接近/穿透", "约束误差阈值",
        "接触边距", "向量缩放", "法线长度", "平面显示尺寸",
    ],
    input_init={
        "task_filter": {
            "description": "按对象名或slot id筛选；换行或逗号分隔，留空显示全部",
        },
        "max_items": {
            "min_value": 1,
            "max_value": 100000,
            "description": "每种视图最多绘制的粒子、约束、三角形或碰撞体数量",
        },
        "show_particles": {"description": "绿色=Move，红色大点=Pin/Fixed"},
        "show_surface": {"description": "半透明显示当前模拟三角表面"},
        "show_stretch": {"description": "绿色=阈值内，红色=拉伸，蓝色=压缩"},
        "show_bend": {
            "description": "显示当前基础XPBD使用的共享边对顶点distance bending",
        },
        "show_offsets": {"description": "灰点=rest，青色箭头=rest到当前模拟位置"},
        "show_normals": {"description": "按当前模拟三角形计算表面法线"},
        "show_gravity": {"description": "每个任务中心显示任务实际重力方向与相对强度"},
        "show_radii": {"description": "显示逐粒子世界空间碰撞半径"},
        "show_colliders": {
            "description": "显示XPBD实际通过组掩码消费的Sphere/Capsule/Plane/Box",
        },
        "show_contacts": {
            "description": "黄色=接近接触，红色箭头=最终位置仍存在的穿透修正",
        },
        "constraint_tolerance": {"min_value": 0.0, "max_value": 1.0},
        "contact_margin": {"min_value": 0.0},
        "vector_scale": {"min_value": 0.0},
        "normal_scale": {"min_value": 0.0},
        "plane_scale": {"min_value": 0.001},
    },
    _OUTPUT_NAME=["物理世界", "调试状态"],
    mute_passthrough={"_OUTPUT0": "world"},
    omni_description=(
        "从Mesh XPBD solver slot的只读快照绘制真实中间状态，不修改模拟。所有视图默认关闭；"
        "开启任一视图后按需请求下一次solver执行捕获，因此首次启用可能显示等待状态。"
        "关闭全部视图会立即撤销请求、释放快照并移除视口绘制处理器。Stretch/Bend颜色按当前长度"
        "相对rest长度的误差分类；碰撞接触由最终粒子位置与本任务实际消费的公共碰撞体重新审计。"
    ),
)
def physicsMeshXpbdDebugDraw(
    world: object,
    task_filter: str = "",
    max_items: int = 10000,
    show_particles: bool = False,
    show_surface: bool = False,
    show_stretch: bool = False,
    show_bend: bool = False,
    show_offsets: bool = False,
    show_normals: bool = False,
    show_gravity: bool = False,
    show_radii: bool = False,
    show_colliders: bool = False,
    show_contacts: bool = False,
    constraint_tolerance: float = 0.01,
    contact_margin: float = 0.002,
    vector_scale: float = 1.0,
    normal_scale: float = 0.05,
    plane_scale: float = 1.0,
) -> tuple[object, str]:
    from .debug_draw import update_mesh_xpbd_debug_draw_store

    status = update_mesh_xpbd_debug_draw_store(
        str(id(world)),
        world,
        True,
        task_filter=task_filter,
        max_items=max_items,
        show_particles=show_particles,
        show_surface=show_surface,
        show_stretch=show_stretch,
        show_bend=show_bend,
        show_offsets=show_offsets,
        show_normals=show_normals,
        show_gravity=show_gravity,
        show_radii=show_radii,
        show_colliders=show_colliders,
        show_contacts=show_contacts,
        constraint_tolerance=constraint_tolerance,
        contact_margin=contact_margin,
        vector_scale=vector_scale,
        normal_scale=normal_scale,
        plane_scale=plane_scale,
    )
    return world, status
