"""VRM SpringBone 新物理世界节点定义。"""

import mathutils

from ....FunctionNodeCore import omni
from ....OmniNodeSocketMapping import _OmniBone
from ... import _Color
from ..types import PhysicsWorldCache
from .debug_draw import update_spring_vrm_debug_draw_store
from .implicit_objects import make_spring_vrm_chain_properties, register_spring_vrm_chain_objects
from .solver import step_spring_vrm


@omni(
    enable=True,
    bl_label="VRM骨链属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨链", "启用", "刚度", "阻尼", "重力方向", "重力强度"],
    input_init={
        "stiffness_force": {"min_value": 0.0, "max_value": 200.0},
        "drag_force": {"min_value": 0.0, "max_value": 1.0},
        "gravity_power": {"min_value": 0.0, "max_value": 200.0},
    },
    _OUTPUT_NAME=["骨链属性"],
    omni_description="""
    从 Bone socket 列表生成 VRM SpringBone 骨链属性。

    接入单根骨骼时会把它当作 root 递归收集；接入“从根获取骨骼”的列表时会按该列表解释为链/集合。
    本节点只打包属性，不写 world、不创建 solver slot、不推进模拟。
    """,
)
def physicsSpringVRMChainProperties(
    bone_chain: list[_OmniBone],
    enabled: bool = True,
    stiffness_force: float = 1.0,
    drag_force: float = 0.4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 0.0,
) -> list[object]:
    return make_spring_vrm_chain_properties(
        bone_chain,
        enabled=bool(enabled),
        stiffness_force=float(stiffness_force),
        drag_force=float(drag_force),
        gravity_dir=gravity_dir,
        gravity_power=float(gravity_power),
    )


@omni(
    enable=True,
    bl_label="VRM骨链对象注册",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "骨链属性", "启用"],
    _OUTPUT_NAME=["物理世界", "对象数量", "变更数量", "版本"],
    omni_description="""
    把 VRM SpringBone 骨链属性注册为 PhysicsWorldCache.implicit_objects。

    本节点不需要用户提供 key。每条骨链对象带有统一 tag，SpringBone solver 会直接收集全部 VRM 骨链对象。
    相同骨架、根骨和骨链会按内部 stable_id 更新，不会因为节点重复执行而无限累积。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsSpringVRMChainRegister(
    world: object,
    vrm_chain_properties: list[object],
    enabled: bool = True,
) -> tuple[object, int, int, int]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0, 0
    count, dirty_count, version = register_spring_vrm_chain_objects(
        world,
        vrm_chain_properties,
        enabled=bool(enabled),
    )
    return world, int(count), int(dirty_count), int(version)


@omni(
    enable=True,
    always_run=True,
    bl_label="SpringBone VRM模拟步",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "启用", "子步数"],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
    },
    _OUTPUT_NAME=["物理世界", "写回项数量", "耗时ms"],
    omni_description="""
    新物理世界版 VRM SpringBone 模拟步。

    本节点直接走 C++ / native 计算路径，不提供 Python solver fallback。
    节点会从 world.implicit_objects 收集全部 VRM 骨链对象；旧 solver、旧 cache 和旧写回不会参与。

    执行流程：
    1. 从 world 隐式对象构建 SpringVRMSolverSpec。
    2. 注册到 world.solver_slots["spring_vrm:..."]。
    3. 调用 hotools_native.solve_spring_bone_vrm_cpp。
    4. 发布 world.result_streams["bone_transform"] 通用写回指令。
    5. 下游 物理写回 节点统一写 PoseBone.matrix_basis。

    外部碰撞体已接入 world.collider_snapshot（SPHERE/CAPSULE/PLANE/BOX 四类），
    骨骼自身 hit radius / collided_by_groups 经 bone_collision resolver 解析。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsSpringVRMSolver(
    world: object,
    enabled: bool = True,
    substeps: int = 1,
) -> tuple[object, int, float]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0.0
    write_count, step_ms = step_spring_vrm(
        world,
        enabled=bool(enabled),
        substeps=max(1, int(substeps)),
    )
    return world, int(write_count), float(step_ms)


@omni(
    enable=True,
    always_run=True,
    bl_label="SpringBone VRM可视化调试",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "启用", "显示骨骼姿态", "显示解算尾端", "显示根骨"],
    _OUTPUT_NAME=["物理世界"],
    omni_description="""
    SpringBone VRM 自有可视化调试节点。

    本节点从 SpringBone solver slot、frame_state 与 bone_transform result stream
    采样纯线段快照，绘制骨链姿态、解算尾端和根骨标记。绘制语义归 spring_vrm/debug.py
    与 spring_vrm/debug_draw.py 持有，不再走物理世界通用 debug draw。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsSpringVRMDebugDraw(
    world: object,
    enabled: bool = True,
    show_pose: bool = True,
    show_simulated_tail: bool = True,
    show_roots: bool = True,
) -> object:
    update_spring_vrm_debug_draw_store(
        str(id(world)),
        world,
        bool(enabled),
        bool(show_pose),
        bool(show_simulated_tail),
        bool(show_roots),
    )
    return world
