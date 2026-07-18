"""VRM SpringBone 新物理世界节点定义。"""

import mathutils

from ....FunctionNodeCore import omni
from ....OmniNodeSocketMapping import _OmniBitMask, _OmniBone
from ... import _Color
from ..types import PhysicsWorldCache
from ..collision.capabilities import BONE_COLLISION_CAPABILITY
from .debug_draw import update_spring_vrm_debug_draw_store
from .implicit_objects import (
    make_bone_collision_override_properties,
    make_spring_vrm_chain_properties,
    register_bone_collision_override_objects,
)
from .solver import step_spring_vrm
from .specs import normalize_spring_vrm_chain_properties


_SPRING_VRM_CHAIN_PRESETS = [
    {
        "name": "极软拖尾",
        "values": {
            "stiffness_force": 1.0,
            "drag_force": 0.15,
            "gravity_dir": (0.0, 0.0, -1.0),
            "gravity_power": 0.0,
        },
    },
    {
        "name": "柔软头发",
        "values": {
            "stiffness_force": 8.0,
            "drag_force": 0.28,
            "gravity_dir": (0.0, 0.0, -1.0),
            "gravity_power": 0.08,
        },
    },
    {
        "name": "布条裙摆",
        "values": {
            "stiffness_force": 18.0,
            "drag_force": 0.38,
            "gravity_dir": (0.0, 0.0, -1.0),
            "gravity_power": 0.35,
        },
    },
    {
        "name": "硬质挂件",
        "values": {
            "stiffness_force": 55.0,
            "drag_force": 0.55,
            "gravity_dir": (0.0, 0.0, -1.0),
            "gravity_power": 0.15,
        },
    },
    {
        "name": "强回弹测试",
        "values": {
            "stiffness_force": 100.0,
            "drag_force": 0.18,
            "gravity_dir": (0.0, 0.0, -1.0),
            "gravity_power": 0.0,
        },
    },
]


_SPRING_VRM_SOLVER_PRESETS = [
    {"name": "标准", "values": {"substeps": 1}},
    {"name": "高稳定", "values": {"substeps": 4}},
]


def _bone_collision_field(name: str) -> dict:
    for field in BONE_COLLISION_CAPABILITY.get("fields", ()):
        if str(field.get("name") or "") == str(name):
            return field
    return {}


def _bone_collision_default(name: str, fallback):
    return _bone_collision_field(name).get("default", fallback)


def _bone_collision_rna(name: str) -> dict:
    return dict(_bone_collision_field(name).get("rna") or {})


def _bone_collision_type_values() -> tuple[str, ...]:
    for field in BONE_COLLISION_CAPABILITY.get("fields", ()):
        if str(field.get("name") or "") == "collision_type":
            values = tuple(str(item) for item in field.get("values", ()) if str(item))
            if values:
                return values
    return ("NONE", "SPHERE", "CAPSULE")


def _bone_collision_type_socket_description() -> str:
    items = "\n".join(
        f"{index}={name}"
        for index, name in enumerate(_bone_collision_type_values())
    )
    return f"collision_type:\n{items}"


def _bone_collision_type_from_socket(value) -> str:
    # Int socket -> BONE_COLLISION_CAPABILITY.fields['collision_type'].values index.
    values = _bone_collision_type_values()
    try:
        index = int(value)
    except Exception:
        index = 0
    index = max(0, min(len(values) - 1, index))
    return values[index]


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
    omni_presets=_SPRING_VRM_CHAIN_PRESETS,
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
    bl_label="VRM骨链任务",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨链属性"],
    input_init={
        "vrm_chain_properties": {"description": "一条或多条VRM骨链属性"},
    },
    _OUTPUT_NAME=["VRM骨链任务"],
    omni_description="""
    把VRM骨链属性整理成任务列表，直接连接到SpringBone VRM模拟步。
    本节点不读写物理世界，不创建solver slot，也不推进模拟。
    """,
)
def physicsSpringVRMChainTask(
    vrm_chain_properties: list[object],
) -> list[object]:
    return list(normalize_spring_vrm_chain_properties(vrm_chain_properties))


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
        "collision_type": {
            "min_value": 0,
            "max_value": len(_bone_collision_type_values()) - 1,
            "description": _bone_collision_type_socket_description(),
            "default_value": _bone_collision_type_values().index(
                str(_bone_collision_default("collision_type", "NONE"))
            ),
        },
        "radius": {
            "min_value": _bone_collision_rna("radius").get("min", 0.0),
        },
        "length": {
            "min_value": _bone_collision_rna("length").get("min", 0.0),
        },
        "primary_collision_group": {
            "min_value": _bone_collision_rna("primary_collision_group").get("min", 1),
            "max_value": _bone_collision_rna("primary_collision_group").get("max", 16),
        },
        "collided_by_groups": {
            "mask_length": 16,
            "default_value": _bone_collision_default("collided_by_groups", 0),
        },
    },
    _OUTPUT_NAME=["骨骼碰撞覆写"],
    omni_description="""
    构建 bone_collision.override 隐式对象 payload。
    未勾选覆写的字段会继续从 solver 拥有的 Bone.hotools_collision 显式参数或 capability 默认值读取。
    """,
)
def physicsBoneCollisionOverrideProperties(
    bone: list[_OmniBone],
    enabled: bool = True,
    override_pin: bool = False,
    pin: bool = bool(_bone_collision_default("pin", False)),
    override_collision_type: bool = False,
    collision_type: int = _bone_collision_type_values().index(
        str(_bone_collision_default("collision_type", "NONE"))
    ),
    override_radius: bool = False,
    radius: float = float(_bone_collision_default("radius", 0.05)),
    override_length: bool = False,
    length: float = float(_bone_collision_default("length", 0.2)),
    override_offset: bool = False,
    offset: mathutils.Vector = mathutils.Vector(_bone_collision_default("offset", (0.0, 0.0, 0.0))),
    override_primary_collision_group: bool = False,
    primary_collision_group: int = int(_bone_collision_default("primary_collision_group", 1)),
    override_collided_by_groups: bool = False,
    collided_by_groups: _OmniBitMask = int(_bone_collision_default("collided_by_groups", 0)),
) -> list[object]:
    bones = list(bone) if isinstance(bone, (list, tuple)) else [bone]
    return [
        make_bone_collision_override_properties(
            item,
            enabled=bool(enabled),
            pin=bool(pin) if override_pin else None,
            collision_type=_bone_collision_type_from_socket(collision_type) if override_collision_type else None,
            radius=float(radius) if override_radius else None,
            length=float(length) if override_length else None,
            offset=offset if override_offset else None,
            primary_collision_group=int(primary_collision_group) if override_primary_collision_group else None,
            collided_by_groups=int(collided_by_groups) if override_collided_by_groups else None,
        )
        for item in bones
        if item is not None
    ]


@omni(
    enable=True,
    bl_label="骨骼碰撞覆写注册",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "骨骼碰撞覆写", "启用"],
    _OUTPUT_NAME=["物理世界", "对象数量", "变更数量", "版本"],
    omni_description="""
    把 bone_collision.override payload 注册到 PhysicsWorldCache.implicit_objects。
    SpringBone resolver 会优先读取该隐式对象，再读取 solver 拥有的 Bone.hotools_collision 显式参数。
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
    _INPUT_NAME=["物理世界", "VRM骨链任务", "子步数"],
    input_init={
        "vrm_chain_tasks": {"description": "全部VRM骨链任务\n单步统一处理"},
        "substeps": {"min_value": 1, "max_value": 16},
    },
    omni_presets=_SPRING_VRM_SOLVER_PRESETS,
    _OUTPUT_NAME=["物理世界", "写回项数量", "耗时ms"],
    omni_description="""
    新物理世界版 VRM SpringBone 模拟步。

    本节点直接走 C++ / native 计算路径，不提供 Python solver fallback。
    节点直接消费全部VRM骨链任务；旧solver、旧cache和旧写回不会参与。

    执行流程：
    1. 从VRM骨链任务构建SpringVRMSolverSpec。
    2. 注册到 world.solver_slots["spring_vrm:..."]。
    3. 调用 hotools_native SpringBone context API（create/update/step/read）。
    4. 发布 world.result_streams["bone_transform"] 通用写回指令。
    5. 下游 物理写回 节点统一写 PoseBone.matrix_basis。

    外部碰撞体已接入 world.collider_snapshot（SPHERE/CAPSULE/PLANE/BOX 四类）。
    bone_collision resolver 同时驱动骨骼自身 hit radius / collided_by_groups，
    以及骨骼作为外部 sphere/capsule 的 type/radius/length/offset/primary group。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsSpringVRMSolver(
    world: object,
    vrm_chain_tasks: list[object],
    substeps: int = 1,
) -> tuple[object, int, float]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0.0
    if (
        isinstance(vrm_chain_tasks, list)
        and len(vrm_chain_tasks) == 1
        and type(vrm_chain_tasks[0]) is float
        and vrm_chain_tasks[0] == 0.0
    ):
        vrm_chain_tasks = []
    write_count, step_ms = step_spring_vrm(
        world,
        vrm_chain_tasks,
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
