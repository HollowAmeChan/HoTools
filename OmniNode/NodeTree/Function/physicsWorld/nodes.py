"""
physicsWorld.nodes — 对外暴露的通用函数节点

按 @omni 装饰器格式定义，由 OmniNodeRegister 统一加载注册。

节点列表（Phase 2 通用节点）：
  physicsObjectsFromCollection — 从 Collection 收集对象列表
  physicsObjectScope           — 构造 PhysicsObjectScope（objects 为多重输入，无需单独合并节点）
  physicsWorldBegin            — 物理世界帧开始
  physicsWorldCommit           — 物理世界帧提交
  physicsWorldDebugSnapshot    — 输出 PhysicsWorldCache debug snapshot dict
  physicsWorldResultStream     — 按 channel / solver 读取 world result stream
  physicsWorldDebugText        — 输出 PhysicsWorldCache debug 可读文本
"""

import bpy

from ...FunctionNodeCore import omni
from ...OmniNodeSocketMapping import _OmniCache
from .. import _Color

from .types import PhysicsObjectScope, PhysicsWorldCache
from .scope import (
    objects_from_collection,
    objects_from_scene,
    make_scope,
)
from .world import physicsWorldBegin as _begin, physicsWorldCommit as _commit
from .debug import snapshot_to_text, result_items_to_text, validate_world, print_world_summary
from .debug_draw import update_draw_store, clear_draw_store
from .writeback import apply_all_writebacks, clear_all_deltas


# ---------------------------------------------------------------------------
# Phase 2 通用 scope 节点
# ---------------------------------------------------------------------------

@omni(
    enable=True,
    bl_label="物理对象-从集合",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["集合", "递归子集合"],
    _OUTPUT_NAME=["对象列表"],
    omni_description="""
    从 Blender Collection 收集对象列表，供 Physics Object Scope 节点使用。

    始终收集集合内的全部对象（含隐藏），不在此处过滤可见性。
    可见性策略由下游的 Physics Object Scope 节点统一控制（include_hidden）。
    """,
)
def physicsObjectsFromCollection(
    collection: bpy.types.Collection,
    recursive: bool = True,
) -> list[bpy.types.Object]:
    if collection is None:
        return []
    return objects_from_collection(collection, recursive=bool(recursive), include_hidden=True)


@omni(
    enable=True,
    bl_label="物理对象-从场景",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["场景", "包含隐藏"],
    _OUTPUT_NAME=["对象列表"],
    omni_description="""
    从整个场景收集所有对象，供 Physics Object Scope 节点使用。

    无需指定集合，一键获取场景内全部对象，适合快速搭建或测试。
    若需精确控制参与物理的对象范围，改用「物理对象-从集合」并手动组织集合。

    包含隐藏=False（默认）时跳过不可见对象。
    """,
)
def physicsObjectsFromScene(
    scene: bpy.types.Scene,
    include_hidden: bool = False,
) -> list[bpy.types.Object]:
    return objects_from_scene(scene, include_hidden=bool(include_hidden))


@omni(
    enable=True,
    bl_label="物理对象范围",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "对象",
        "简单碰撞",
        "骨骼碰撞",
        "简单布料",
        "刚体",
        "刚体约束",
        "包含隐藏",
    ],
    _OUTPUT_NAME=["对象范围"],
    omni_description="""
    把对象列表和物理类型过滤开关封装成 PhysicsObjectScope，传入物理世界-帧开始。

    对象输入为多重输入（方形 socket），可同时接多个 Object 或多个对象列表，
    无需单独的"合并列表"节点。内部自动去重展平。

    各开关对齐 HoTools 统一物理面板的类型名称：
      简单碰撞 — 读取 hotools_object_collision.enabled
      骨骼碰撞 — 读取 Bone.hotools_collision.collision_type
      简单布料 — 读取 hotools_mesh_collision.enabled
      刚体     — 读取 hotools_rigid_body.enabled
      刚体约束 — 读取 hotools_rigid_constraint.enabled（仅 EMPTY 对象）
    """,
)
def physicsObjectScope(
    objects: list[bpy.types.Object],
    include_passive_collision: bool = True,
    include_bone_collision: bool = True,
    include_mesh_collision: bool = True,
    include_rigid_body: bool = True,
    include_rigid_constraint: bool = True,
    include_hidden: bool = False,
) -> object:
    return make_scope(
        objects=objects,
        include_passive_collision=bool(include_passive_collision),
        include_bone_collision=bool(include_bone_collision),
        include_mesh_collision=bool(include_mesh_collision),
        include_rigid_body=bool(include_rigid_body),
        include_rigid_constraint=bool(include_rigid_constraint),
        include_hidden=bool(include_hidden),
    )


# ---------------------------------------------------------------------------
# Phase 2 物理世界节点
# ---------------------------------------------------------------------------

@omni(
    enable=True,
    always_run=True,   # 每帧必须更新帧上下文和碰撞快照
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
    always_run=True,   # 每帧必须提交 cache intent
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
    mute_passthrough={"_OUTPUT1": "world"},
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
    always_run=True,   # debug输出，每帧刷新快照
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
    mute_passthrough={"_OUTPUT0": "world"},
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
    always_run=True,
    bl_label="物理世界-结果流",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "通道", "Solver", "仅当前帧", "仅当前代"],
    _OUTPUT_NAME=["物理世界", "结果列表", "数量", "结果文本"],
    omni_description="""
    从 PhysicsWorldCache.result_streams 读取 solver 输出。

    通道为空时读取全部 result channel；Solver 为空时不过滤 solver。
    默认只读取当前 frame 和当前 generation，避免误看旧帧数据。

    这是通用观察节点，不访问 solver slot 私有结构或 backend handle。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsWorldResultStream(
    world: object,
    channel: str = "",
    solver: str = "",
    current_frame_only: bool = True,
    current_generation_only: bool = True,
) -> tuple[object, list, int, str]:
    if not isinstance(world, PhysicsWorldCache):
        msg = f"world 不是 PhysicsWorldCache（{type(world).__name__}）"
        return world, [], 0, msg

    fc = world.frame_context
    frame = int(fc.frame) if bool(current_frame_only) else None
    generation = int(world.generation) if bool(current_generation_only) else None
    ch = str(channel).strip() or None
    solver_id = str(solver).strip() or None
    items = [
        dict(item) for item in world.consume_results(
            ch,
            solver=solver_id,
            frame=frame,
            generation=generation,
        )
        if isinstance(item, dict)
    ]
    return world, items, len(items), result_items_to_text(items)


@omni(
    enable=True,
    always_run=True,   # 可能有 print 副作用，每帧刷新
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
    mute_passthrough={"_OUTPUT0": "world"},
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


@omni(
    enable=True,
    always_run=True,   # 写入 draw store，每帧刷新视口绘制
    bl_label="物理世界-可视化调试",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "启用", "显示碰撞体", "显示刚体", "显示约束", "显示Bug"],
    _OUTPUT_NAME=["物理世界"],
    omni_description="""
    在 3D 视口中可视化物理世界内容，比文字快照更直观。

    节点执行时把 PhysicsWorldCache 里的数据采样成纯绘制快照：
      显示碰撞体 — collider_snapshot 里的球/胶囊/平面/盒子（蓝=简单碰撞/黄绿=骨骼）
      显示刚体   — rigid_body slot 的轮廓（绿=动态/灰=静态/蓝=运动学）
      显示约束   — constraint slot 的 Empty 锚点 + 连线到目标（橙黄）
                   FIXED=轴框/HINGE=半圆/SLIDER=双箭头/CONE=锥/POINT=圆
      显示Bug    — 约束缺目标或连到自身时以红色标出

    _DRAW_STORE 不保存 bpy 对象、spec 引用或 live matrix；draw handler 只读快照。
    因此该节点应放在你想观察的写回/求解阶段之后。
    物理世界 透传，可插在链路任意位置。
    """,
)
def physicsWorldDebugDraw(
    world: object,
    enabled: bool = True,
    show_colliders: bool = True,
    show_rigid: bool = True,
    show_constraints: bool = True,
    show_bugs: bool = True,
) -> object:
    update_draw_store(
        str(id(world)),
        world,
        bool(enabled),
        bool(show_colliders),
        bool(show_rigid),
        bool(show_constraints),
        bool(show_bugs),
    )
    return world


# ---------------------------------------------------------------------------
# Phase 5  写回节点
# ---------------------------------------------------------------------------

@omni(
    enable=True,
    always_run=True,
    bl_label="物理写回",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "启用"],
    _OUTPUT_NAME=["物理世界", "写回数量"],
    omni_description="""
    物理写回节点——将本帧所有物理 solver 的结果写回 Blender 对象变换。

    写回类型（全部基于偏移量语义，归零即复位）：
      · 刚体：Object.delta_location / delta_rotation_euler（不修改原始 location）
      · 骨骼：PoseBone.matrix_basis（未来扩展，offset from rest pose）
      · GN属性：mesh attribute offset（未来扩展）

    初始状态约定：
      Blender 增量变换默认为 (0,0,0)，即"无物理偏移"。
      跳帧/复位时节点自动将 delta 归零，再写入新的物理结果。
      停止模拟后 delta 保留（视觉结果持续可见）；如需清空，
      将"启用"关闭运行一帧，或删除缓存触发自动清理。

    跳帧/复位处理：
      world.frame_context.restart_required=True 时先将 delta 归零，
      再写入本帧物理结果——保证跳帧后无残留。

    接法：
      Physics World Begin → Rigid Body Solver → 物理写回 → Physics World Commit
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsWriteback(
    world:   object,
    enabled: bool = True,
) -> tuple[object, int]:

    from .types import PhysicsWorldCache

    # enabled=False：清空上次模拟留下的 delta，对象归位
    if not enabled:
        if isinstance(world, PhysicsWorldCache):
            try:
                clear_all_deltas(world)
            except Exception:
                pass
        return world, 0

    if not isinstance(world, PhysicsWorldCache):
        return world, 0

    fc = world.frame_context
    if fc is None:
        return world, 0

    # same_frame（同帧重复求值）时跳过，避免冗余 bpy 操作
    if bool(getattr(fc, "same_frame", False)):
        return world, 0

    restart = bool(getattr(fc, "restart_required", False))
    total   = apply_all_writebacks(world, restart=restart)
    return world, total
