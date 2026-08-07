"""
physicsWorld.nodes — 对外暴露的通用函数节点

按 @omni 装饰器格式定义，由 OmniNodeRegister 统一加载注册。

节点列表（Phase 2 通用节点）：
  physicsObjectsFromScene      — 返回 Scene 根 Collection
  physicsObjectScope           — 从 Collection 列表构造 PhysicsObjectScope
  physicsWorldBegin            — 物理世界帧开始
  physicsBake                  — 配置、触发并切换 Physics World Mesh Bake
  clearPhysicsBake             — 用户控制的 Action/Mesh Bake 清理
  physicsWorldCommit           — 物理世界帧提交
  physicsWorldDebugSnapshot    — 输出 PhysicsWorldCache debug snapshot dict
  physicsWorldResultStream     — 按 channel / solver 读取 world result stream
  physicsWorldDebugText        — 输出 PhysicsWorldCache debug 可读文本
  physicsFieldRuntimeDebugDraw — 显示 World 实际持有的 native 场运行态
"""

import bpy

from ..FunctionNodeCore import omni
from ..OmniNodeSocketMapping import _OmniCache
from ..config import nodeColors

from .types import PhysicsObjectScope, PhysicsWorldCache
from .scope import (
    collection_from_scene,
    make_scope,
)
from .world import physicsWorldBegin as _begin, physicsWorldCommit as _commit
from .debug import snapshot_to_text, result_items_to_text, validate_world, print_world_summary
from .writeback import apply_all_writebacks
from .bake import (
    bake_bone_transforms,
    clear_physics_bake,
    geometry_bake_is_active,
    geometry_bake_should_record_actions,
    geometry_bake_status,
    geometry_bake_target_count,
    rearm_geometry_bake_trigger,
    request_geometry_bake,
    set_session_cache_playback,
)


# ---------------------------------------------------------------------------
# Phase 2 通用 scope 节点
# ---------------------------------------------------------------------------

@omni(
    enable=True,
    always_run=True,
    bl_label="物理对象-从场景",
    base_color=nodeColors.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["场景"],
    _OUTPUT_NAME=["场景集合"],
    mute_passthrough=False,
    omni_description="""
    返回 Scene 根 Collection，供物理对象范围节点使用。
    根 Collection 的 all_objects 会递归覆盖整个场景，并作为批量读写边界。
    """,
)
def physicsObjectsFromScene(
    scene: bpy.types.Scene,
) -> bpy.types.Collection:
    return collection_from_scene(scene)


@omni(
    enable=True,
    always_run=True,
    bl_label="物理对象范围",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "集合",
        "简单碰撞",
        "骨骼碰撞",
        "刚体",
        "刚体约束",
        "场",
    ],
    _OUTPUT_NAME=["对象范围"],
    mute_passthrough=False,
    omni_description="""
    把 Collection 列表和物理类型过滤开关封装成 PhysicsObjectScope。

    集合输入为多重输入。每个 Collection 的 all_objects 都会递归展开，并作为
    帧内批量读取和写回的固定边界。不同输入集合不能包含同一对象；范围内对象
    始终参与物理，不受视图隐藏状态影响。

    各开关对齐 HoTools 统一物理面板的类型名称：
      简单碰撞 — 读取 hotools_object_collision.enabled
      骨骼碰撞 — 读取 Bone.hotools_collision.collision_type
      刚体     — 读取 hotools_rigid_body.enabled
      刚体约束 — 读取 hotools_rigid_constraint.enabled（仅 EMPTY 对象）
      场       — 读取 hotools_field.enabled，并在帧开始注册公共场运行态
    """,
)
def physicsObjectScope(
    collections: list[bpy.types.Collection],
    include_passive_collision: bool = True,
    include_bone_collision: bool = True,
    include_rigid_body: bool = True,
    include_rigid_constraint: bool = True,
    include_field: bool = True,
) -> object:
    return make_scope(
        collections=collections,
        include_passive_collision=bool(include_passive_collision),
        include_bone_collision=bool(include_bone_collision),
        include_rigid_body=bool(include_rigid_body),
        include_rigid_constraint=bool(include_rigid_constraint),
        include_hidden=True,
        include_field=bool(include_field),
    )


# ---------------------------------------------------------------------------
# Phase 2 物理世界节点
# ---------------------------------------------------------------------------

@omni(
    enable=True,
    always_run=True,   # 每帧必须更新帧上下文和碰撞快照
    bl_label="物理世界-帧开始",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "场景",
        "对象范围",
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
    mute_passthrough=False,
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
    reset: bool = False,
    time_scale: float = 1.0,
    substeps: int = 1,
    debug_output: bool = False,
) -> tuple[object, int, int, bool]:
    return _begin(
        cache_state=cache_state,
        scene=scene,
        object_scope=object_scope,
        enabled=True,
        reset=bool(reset),
        time_scale=float(time_scale),
        substeps=int(substeps),
        debug_output=bool(debug_output),
    )


@omni(
    enable=True,
    always_run=True,   # 每帧必须提交 cache intent
    bl_label="物理世界-帧提交",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界"],
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
) -> tuple[_OmniCache, object, int]:
    return _commit(world=world, enabled=True)


@omni(
    enable=True,
    always_run=True,
    bl_label="物理烘焙",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "物理世界",
        "缓存目录",
        "文件前缀",
        "开始帧",
        "结束帧",
        "烘焙Bone",
        "烘焙Mesh",
        "使用Mesh缓存",
        "启用",
    ],
    input_init={
        "frame_start": {"min_value": -1048574, "max_value": 1048574},
        "frame_end": {"min_value": -1048574, "max_value": 1048574},
    },
    _OUTPUT_NAME=[
        "物理世界", "缓存目录", "文件前缀", "Bone数量", "Mesh数量", "状态",
    ],
    omni_description="""
    Physics World 通用烘焙节点的 Bone + Mesh 阶段。

    必须接在「物理写回」之后。节点只消费当前 world 的真实 GN Mesh
    writeback target，不扫描整个场景猜测参与者。

    烘焙Mesh 每次执行时只把当前帧的真实 GN Mesh writeback target 写入独立 PC2 文件。
    它不会接管时间轴，也不会阻塞执行整段 Geometry Nodes Bake；用户播放时间轴即可逐帧记录，
    多目标文件写入彼此独立。

    使用Mesh缓存 与文件留存完全独立：关闭只显示实时后置位移，不删除缓存；
    开启前必须有本节点 manifest 标记为 COMPLETE 的完整 PC2 缓存。

    烘焙Bone 每个连续帧记录当前 bone_transform/batch 中真实出现的 PoseBone，
    首次为每个 Armature 复制/创建专用 Bake Action，绝不遍历整个骨架。

    Object Action Bake 将由后续阶段实现；动画与缓存清理由下游独立
    “清除物理Bake动画”节点负责。
    """,
    mute_passthrough={
        "_OUTPUT0": "world",
        "_OUTPUT1": "cache_directory",
        "_OUTPUT2": "file_prefix",
    },
)
def physicsBake(
    world: object,
    cache_directory: str = "//physics_bake",
    file_prefix: str = "PhysicsBake",
    frame_start: int = 1,
    frame_end: int = 250,
    bake_bones: bool = True,
    bake_mesh: bool = False,
    use_mesh_cache: bool = False,
    enabled: bool = True,
) -> tuple[object, str, str, int, int, str]:
    directory_output = str(cache_directory or "")
    prefix_output = str(file_prefix or "")
    if not isinstance(world, PhysicsWorldCache):
        return (
            world, directory_output, prefix_output, 0, 0,
            f"world 不是 PhysicsWorldCache（{type(world).__name__}）",
        )
    if not bool(enabled):
        return world, directory_output, prefix_output, 0, 0, "物理烘焙已禁用"

    try:
        record_actions = geometry_bake_should_record_actions()
        if bool(bake_bones) and not record_actions:
            bone_count = 0
            bone_status = "后续 Mesh pass 跳过 Action Bake"
        else:
            bone_count, _action_count, bone_status = bake_bone_transforms(
                world,
                cache_directory,
                file_prefix,
                bool(bake_bones),
            )
        if geometry_bake_is_active():
            return (
                world,
                directory_output,
                prefix_output,
                bone_count,
                geometry_bake_target_count(),
                f"{bone_status}；{geometry_bake_status()}",
            )
        if bool(bake_mesh):
            count, status = request_geometry_bake(
                world,
                cache_directory,
                file_prefix,
                int(frame_start),
                int(frame_end),
                bool(use_mesh_cache),
            )
        else:
            rearm_geometry_bake_trigger()
            count, status = set_session_cache_playback(
                world,
                cache_directory,
                file_prefix,
                bool(use_mesh_cache),
            )
        return (
            world, directory_output, prefix_output,
            bone_count, count, f"{bone_status}；{status}",
        )
    except Exception as exc:
        return (
            world, directory_output, prefix_output, 0, 0, f"物理烘焙错误：{exc}",
        )


@omni(
    enable=True,
    always_run=True,
    bl_label="清除物理Bake动画",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "物理世界",
        "缓存目录",
        "文件前缀",
        "清理帧",
        "动画清理模式",
        "Mesh缓存策略",
        "最终缓存策略",
        "清理实时输出",
        "暂停时间轴",
        "启用",
    ],
    input_init={
        "clear_frame": {"min_value": -1048574, "max_value": 1048574},
        "animation_clear_mode": {
            "min_value": 0,
            "max_value": 2,
            "description": "0=仅清理帧，1=清理帧及之后，2=整个Bake Session",
        },
        "mesh_cache_policy": {
            "min_value": 0,
            "max_value": 2,
            "description": "0=保留文件，1=标记清理帧后失效，2=删除整个Session缓存",
        },
        "finalize_cache_policy": {
            "min_value": 0,
            "max_value": 2,
            "description": "0=保留文件，1=标记失效，2=删除Session最终文件",
        },
    },
    _OUTPUT_NAME=["物理世界", "动画清除数量", "Mesh处理数量", "状态"],
    omni_description="""
    只在当前场景帧等于“清理帧”时执行，并且只处理 manifest 明确拥有的
    Bake Action、Mesh cache 与真实 Physics World 写回目标。

    动画、Mesh 工作缓存和最终缓存使用互相独立的策略。默认只清本 session
    动画并保留全部缓存文件；清理实时输出只归零真实物理参与者。

    模式编号：动画 0=仅清理帧、1=清理帧及之后、2=整个Session；
    Mesh 0=保留、1=标记失效、2=删除Session；最终缓存同样为 0/1/2。

    推荐接在“物理烘焙”之后。重置时启用或 unmute，本节点完成后再 mute，
    从清理帧开始播放。首次下一帧会由 Bake 自动回填无残余关键帧的边界基线。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def clearPhysicsBake(
    world: object,
    cache_directory: str = "//physics_bake",
    file_prefix: str = "PhysicsBake",
    clear_frame: int = 1,
    animation_clear_mode: int = 2,
    mesh_cache_policy: int = 0,
    finalize_cache_policy: int = 0,
    clear_live_output: bool = True,
    pause_timeline: bool = True,
    enabled: bool = True,
) -> tuple[object, int, int, str]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0, f"world 不是 PhysicsWorldCache（{type(world).__name__}）"
    if geometry_bake_is_active():
        return world, 0, 0, "Mesh Bake 运行期间抑制 Clear"
    try:
        animation_count, mesh_count, status = clear_physics_bake(
            world,
            cache_directory,
            file_prefix,
            int(clear_frame),
            int(animation_clear_mode),
            int(mesh_cache_policy),
            int(finalize_cache_policy),
            bool(clear_live_output),
            bool(pause_timeline),
            bool(enabled),
        )
        return world, animation_count, mesh_count, status
    except Exception as exc:
        return world, 0, 0, f"Clear Physics Bake 错误：{exc}"


# ---------------------------------------------------------------------------
# Phase 3 调试节点
# ---------------------------------------------------------------------------

@omni(
    enable=True,
    always_run=True,   # debug输出，每帧刷新快照
    bl_label="物理世界-调试快照",
    base_color=nodeColors.colorCat["GetData"],
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
    base_color=nodeColors.colorCat["GetData"],
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
    base_color=nodeColors.colorCat["GetData"],
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
    always_run=True,
    bl_label="场-运行可视化调试",
    base_color=nodeColors.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "Volume边界", "空气速度", "采样密度", "箭头比例"],
    input_init={
        "density": {"min_value": 2, "max_value": 7},
        "glyph_scale": {"min_value": 0.0, "max_value": 10.0},
    },
    _OUTPUT_NAME=["物理世界", "调试状态"],
    omni_description="""
    显示 Physics World Begin 本帧实际提交的场运行态。

    Volume 边界来自与 native runtime 严格同签名的 FieldSnapshot；空气速度只调用
    NativeFieldRuntimeV1 采样，时间固定取 World FrameContext 的帧起点。两个显示项
    默认关闭；全部关闭时不读取运行缓存、不执行采样，也不安装视口绘制处理器。
    含 solver、对象、Collection、排除项或碰撞组过滤的场缺少明确消费上下文时只画边界。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsFieldRuntimeDebugDraw(
    world: object,
    show_bounds: bool = False,
    show_air_velocity: bool = False,
    density: int = 3,
    glyph_scale: float = 0.15,
) -> tuple[object, str]:
    from .field.debug_draw import update_field_runtime_debug_draw_store

    status = update_field_runtime_debug_draw_store(
        world,
        show_bounds=bool(show_bounds),
        show_air_velocity=bool(show_air_velocity),
        density=int(density),
        glyph_scale=float(glyph_scale),
    )
    return world, status


# ---------------------------------------------------------------------------
# Phase 5  写回节点
# ---------------------------------------------------------------------------

@omni(
    enable=True,
    always_run=True,
    bl_label="物理写回",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界"],
    _OUTPUT_NAME=["物理世界", "写回数量"],
    omni_description="""
    物理写回节点——将本帧所有物理 solver 的结果写回 Blender 对象变换。

    写回类型（全部基于偏移量语义，归零即复位）：
      · 刚体：Object.delta_location / delta_rotation_euler（不修改原始 location）
      · 骨骼：PoseBone.matrix_basis（offset from rest pose）
      · GN属性：Simple Cloth 顶点最终 offset（OBJECT_LOCAL）

      GN 写回不为各 solver 创建私有属性。多个中间 offset 必须先在
      world.exchange 中归并，result stream 对每个 Mesh 只接受一个最终 writer。

      初始状态约定：
      Blender 增量变换默认为 (0,0,0)，即"无物理偏移"。
      跳帧/复位时节点统一恢复刚体全部 delta、PoseBone matrix_basis 与 GN offset，
      再写入新的物理结果。
      刚体/骨骼停止模拟后 delta 保留；GN 最终 offset 在写回阶段发现本帧
      无结果时会归零，防止残留上一帧 mesh 形变。删除缓存会统一自动清理。

    跳帧/复位处理：
      world.frame_context.restart_required=True 时先清除三种公共写回状态，
      再写入本帧物理结果——保证跳帧后无残留。

    接法：
      Physics World Begin → Rigid Body Solver → 物理写回 → Physics World Commit
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsWriteback(
    world:   object,
) -> tuple[object, int]:

    from .types import PhysicsWorldCache

    if not isinstance(world, PhysicsWorldCache):
        return world, 0

    fc = world.frame_context
    if fc is None:
        return world, 0

    # Begin clears the result stream on every graph evaluation. Solvers then
    # republish either a stepped result or their same-frame cached result, so
    # current results must always reach Blender, including same-frame updates.
    restart = bool(getattr(fc, "restart_required", False))
    total   = apply_all_writebacks(world, restart=restart)
    return world, total
