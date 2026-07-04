"""
physicsWorld.nodes — 对外暴露的通用函数节点

按 @omni 装饰器格式定义，由 OmniNodeRegister 统一加载注册。

节点列表（Phase 2 通用节点）：
  physicsObjectsFromCollection — 从 Collection 收集对象列表
  physicsObjectScope           — 构造 PhysicsObjectScope（objects 为多重输入，无需单独合并节点）
  physicsWorldBegin            — 物理世界帧开始
  physicsWorldCommit           — 物理世界帧提交
  physicsWorldDebugSnapshot    — 输出 PhysicsWorldCache debug snapshot dict
  physicsWorldDebugText        — 输出 PhysicsWorldCache debug 可读文本
"""

import bpy

from ...FunctionNodeCore import omni
from ...OmniNodeSocketMapping import _OmniCache
from .. import _Color

from .types import PhysicsObjectScope, PhysicsWorldCache
from .scope import (
    objects_from_collection,
    make_scope,
)
from .world import physicsWorldBegin as _begin, physicsWorldCommit as _commit
from .debug import snapshot_to_text, validate_world, print_world_summary


# ---------------------------------------------------------------------------
# Phase 2 通用 scope 节点
# ---------------------------------------------------------------------------

@omni(
    enable=True,
    bl_label="物理对象-从集合",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["集合", "递归子集合", "包含隐藏"],
    _OUTPUT_NAME=["对象列表"],
    omni_description="""
    从 Blender Collection 收集对象列表，供 Physics Object Scope 节点使用。

    recursive=True 时递归子集合。
    include_hidden=False 时跳过不可见对象。
    """,
)
def physicsObjectsFromCollection(
    collection: bpy.types.Collection,
    recursive: bool = True,
    include_hidden: bool = False,
) -> list:
    if collection is None:
        return []
    return objects_from_collection(collection, recursive=bool(recursive), include_hidden=bool(include_hidden))


@omni(
    enable=True,
    bl_label="物理对象范围",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "对象",
        "包含物体碰撞",
        "包含骨骼碰撞",
        "包含网格碰撞",
        "包含隐藏",
    ],
    _OUTPUT_NAME=["对象范围"],
    omni_description="""
    把对象列表和包含策略封装成 PhysicsObjectScope，传入 Physics World Begin。

    对象输入为多重输入（方形 socket），可同时接多个 Object 或多个对象列表，
    无需单独的"合并列表"节点。内部自动去重展平。
    对象范围决定本物理世界能感知哪些对象；PhysicsTools 属性决定这些对象具有什么物理语义。
    include_hidden 由此节点统一设置，Physics World Begin 不再接收同名参数。
    """,
)
def physicsObjectScope(
    objects: list[bpy.types.Object],
    include_object_colliders: bool = True,
    include_bone_colliders: bool = True,
    include_mesh_collision: bool = True,
    include_hidden: bool = False,
) -> object:
    return make_scope(
        objects=objects,
        include_object_colliders=bool(include_object_colliders),
        include_bone_colliders=bool(include_bone_colliders),
        include_mesh_collision=bool(include_mesh_collision),
        include_hidden=bool(include_hidden),
    )


# ---------------------------------------------------------------------------
# Phase 2 物理世界节点
# ---------------------------------------------------------------------------

@omni(
    enable=True,
    bl_label="物理世界-帧开始",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "场景",
        "对象范围",
        "启用",
        "重置",
        "时间缩放",
        "子步数",
        "调试输出",
    ],
    input_init={
        "time_scale": {"min_value": 0.0, "max_value": 10.0},
        "substeps": {"min_value": 1, "max_value": 16},
    },
    _OUTPUT_NAME=["物理世界", "当前帧", "碰撞体数量", "需要重启"],
    omni_description="""
    物理世界帧开始节点。

    读取上一帧的 PhysicsWorldCache，更新帧上下文、对象范围和碰撞快照，
    返回裸 world owner 供后续 solver 节点使用。

    返回值：
      物理世界   — PhysicsWorldCache 裸对象（不是 cache intent）
      当前帧     — 当前帧帧号
      碰撞体数量 — 本帧参与碰撞的条目数量（供调试）
      需要重启   — True 表示本帧 solver 应冷启动
    """,
)
def physicsWorldBegin(
    cache_state: _OmniCache,
    scene: bpy.types.Scene,
    object_scope: object,
    enabled: bool = True,
    reset: bool = False,
    time_scale: float = 1.0,
    substeps: int = 1,
    debug_output: bool = False,
) -> tuple[object, int, int, bool]:
    return _begin(
        cache_state=cache_state,
        scene=scene,
        object_scope=object_scope,
        enabled=bool(enabled),
        reset=bool(reset),
        time_scale=float(time_scale),
        substeps=int(substeps),
        debug_output=bool(debug_output),
    )


@omni(
    enable=True,
    bl_label="物理世界-帧提交",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "启用"],
    _OUTPUT_NAME=["缓存值", "物理世界", "Solver数量"],
    omni_description="""
    物理世界帧提交节点。

    把 PhysicsWorldCache 包装成 cache intent（replace 或 mutate），
    最终由 Cache Write 节点提交到 OmniRuntimeState。

    返回值：
      缓存值    — _OmniCache.replace(world) 或 _OmniCache.mutate(world)
      物理世界  — 裸 world，供后续 debug/输出节点使用
      Solver数量 — 当前活跃的 solver slot 数量
    """,
)
def physicsWorldCommit(
    world: object,
    enabled: bool = True,
) -> tuple[_OmniCache, object, int]:
    return _commit(world=world, enabled=bool(enabled))


# ---------------------------------------------------------------------------
# Phase 3 调试节点
# ---------------------------------------------------------------------------

@omni(
    enable=True,
    bl_label="物理世界-调试快照",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界"],
    _OUTPUT_NAME=["物理世界", "快照"],
    omni_description="""
    输出 PhysicsWorldCache 的完整调试快照（dict）。

    输出的快照包含帧上下文、对象范围、碰撞体统计、所有 solver slot 状态，
    可接入 Debug Print 或 Debug Text 节点查看。

    物理世界 透传，方便在节点链中插入调试而不打断 world 流向。
    """,
)
def physicsWorldDebugSnapshot(
    world: object,
) -> tuple[object, object]:
    if not isinstance(world, PhysicsWorldCache):
        return world, {"error": f"world 不是 PhysicsWorldCache（{type(world).__name__}）"}
    snapshot = world.omni_cache_debug_snapshot()
    return world, snapshot


@omni(
    enable=True,
    bl_label="物理世界-调试文本",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "打印到控制台"],
    _OUTPUT_NAME=["物理世界", "调试文本", "问题列表"],
    omni_description="""
    把 PhysicsWorldCache 状态转成可读文本，可选择同时打印到控制台。

    输出：
      物理世界  — 透传，方便链式调试
      调试文本  — 多行可读文本（可接 Debug Print 节点）
      问题列表  — 校验发现的问题描述列表（空列表表示无问题）
    """,
)
def physicsWorldDebugText(
    world: object,
    print_to_console: bool = False,
) -> tuple[object, str, list]:
    if not isinstance(world, PhysicsWorldCache):
        msg = f"world 不是 PhysicsWorldCache（{type(world).__name__}）"
        return world, msg, [msg]

    snapshot = world.omni_cache_debug_snapshot()
    text = snapshot_to_text(snapshot)
    problems = validate_world(world)

    if bool(print_to_console):
        print_world_summary(world)

    return world, text, problems
