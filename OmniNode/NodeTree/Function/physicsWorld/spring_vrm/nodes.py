"""VRM SpringBone 新物理世界节点定义。"""

import mathutils

from ....FunctionNodeCore import omni
from ....OmniNodeSocketMapping import _OmniBitMask, _OmniBone
from ... import _Color
from ..types import PhysicsWorldCache
from .debug_draw import update_spring_vrm_debug_draw_store
from .implicit_objects import (
    make_bone_collision_override_properties,
    make_spring_vrm_chain_properties,
    register_bone_collision_override_objects,
    register_spring_vrm_chain_objects,
)
from .solver import step_spring_vrm


@omni(
    enable=True,
    bl_label="VRM骨链属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨链", "刚度", "阻尼", "重力方向", "重力强度"],
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
    stiffness_force: float = 1.0,
    drag_force: float = 0.4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 0.0,
) -> list[object]:
    return make_spring_vrm_chain_properties(
        bone_chain,
        enabled=True,
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
    _INPUT_NAME=["物理世界", "骨链属性"],
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
) -> tuple[object, int, int, int]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0, 0
    count, dirty_count, version = register_spring_vrm_chain_objects(
        world,
        vrm_chain_properties,
        enabled=True,
    )
    return world, int(count), int(dirty_count), int(version)


@omni(
    enable=True,
    bl_label="骨骼碰撞覆写属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "骨骼", "启用",
        "覆写Pin", "Pin",
        "覆写碰撞体", "碰撞体",
        "覆写半径", "半径",
        "覆写长度", "长度",
        "覆写偏移", "偏移",
        "覆写主碰撞组", "主碰撞组",
        "覆写被碰撞组", "被碰撞组",
    ],
    input_init={
        "radius": {"min_value": 0.0, "max_value": 10.0},
        "length": {"min_value": 0.0, "max_value": 10.0},
        "primary_collision_group": {"min_value": 1, "max_value": 16},
        "collided_by_groups": {"mask_length": 16, "default_value": 0},
    },
    _OUTPUT_NAME=["骨骼碰撞覆写"],
    omni_description="""
    构建 bone_collision.override 隐式对象 payload。
    未勾选覆写的字段会继续从 Bone.hotools_collision 或 capability 默认值回退读取。
    """,
)
def physicsBoneCollisionOverrideProperties(
    bone: _OmniBone,
    enabled: bool = True,
    override_pin: bool = False,
    pin: bool = False,
    override_collision_type: bool = False,
    collision_type: str = "SPHERE",
    override_radius: bool = False,
    radius: float = 0.05,
    override_length: bool = False,
    length: float = 0.2,
    override_offset: bool = False,
    offset: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    override_primary_collision_group: bool = False,
    primary_collision_group: int = 1,
    override_collided_by_groups: bool = False,
    collided_by_groups: _OmniBitMask = 0,
) -> dict:
    return make_bone_collision_override_properties(
        bone,
        enabled=bool(enabled),
        pin=bool(pin) if override_pin else None,
        collision_type=str(collision_type or "SPHERE") if override_collision_type else None,
        radius=float(radius) if override_radius else None,
        length=float(length) if override_length else None,
        offset=offset if override_offset else None,
        primary_collision_group=int(primary_collision_group) if override_primary_collision_group else None,
        collided_by_groups=int(collided_by_groups) if override_collided_by_groups else None,
    )


@omni(
    enable=True,
    bl_label="骨骼碰撞覆写注册",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "骨骼碰撞覆写", "启用"],
    _OUTPUT_NAME=["物理世界", "对象数量", "变更数量", "版本"],
    omni_description="""
    把 bone_collision.override payload 注册到 PhysicsWorldCache.implicit_objects。
    SpringBone resolver 会优先读取该隐式对象，再回退到 Bone.hotools_collision。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsBoneCollisionOverrideRegister(
    world: object,
    bone_collision_override_properties: list[object],
    enabled: bool = True,
) -> tuple[object, int, int, int]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0, 0
    count, dirty_count, version = register_bone_collision_override_objects(
        world,
        bone_collision_override_properties,
        enabled=bool(enabled),
    )
    return world, int(count), int(dirty_count), int(version)


@omni(
    enable=True,
    always_run=True,
    bl_label="SpringBone VRM模拟步",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "子步数"],
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
    substeps: int = 1,
) -> tuple[object, int, float]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0.0
    write_count, step_ms = step_spring_vrm(
        world,
        enabled=True,
        substeps=max(1, int(substeps)),
    )
    return world, int(write_count), float(step_ms)


@omni(
    enable=True,
    always_run=True,
    bl_label="SpringBone VRM可视化调试",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "显示解算链条", "显示根骨", "显示碰撞体", "碰撞组颜色"],
    _OUTPUT_NAME=["物理世界"],
    omni_description="""
    SpringBone VRM 自有可视化调试节点。

    本节点从 SpringBone solver slot、frame_state 与 bone_transform result stream
    采样纯线段快照，绘制连续的解算链条、根骨标记、外部碰撞体和骨骼自身碰撞体。
    碰撞体按真实类型绘制为球、胶囊、平面或盒子，并可按碰撞组使用固定颜色。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsSpringVRMDebugDraw(
    world: object,
    show_solved_chain: bool = True,
    show_roots: bool = True,
    show_colliders: bool = True,
    color_by_group: bool = True,
) -> object:
    update_spring_vrm_debug_draw_store(
        str(id(world)),
        world,
        True,
        bool(show_solved_chain),
        bool(show_roots),
        bool(show_colliders),
        bool(color_by_group),
    )
    return world
