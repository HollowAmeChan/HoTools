# OmniNode 物理世界实现推进日志

本文是 OmniNode 物理世界的**实现推进日志**：记录分阶段落地进度、各 solver 迁移状态、测试覆盖和实施期变更。它是"现在做到哪了"的记录，不是架构权威。

文档分工：

- **`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`（架构设计）**：物理世界的结构约定与已固定的架构支柱，是"应该怎么组织"的权威。任何结构性判断以它为准。
- **本文（实现推进日志）**：Phase 进度、solver 迁移状态、测试覆盖、实施期变更记录。
- **`ARCHITECTURE.md`（OmniNode 框架）**：编译/执行/缓存/懒求值等框架机制。

九条已固定架构支柱（框架+模块化 solver、显式身份卡、通用世界状态输入、通用写回、隐式表达、纯 C++ 后端、旧 solver 移除、跨 solver 交互、物理属性动态注册）见架构设计文档。当前落地态：spring_vrm 领先（已原子化 + resolver），rigid 次之（vertical slice 已跑通、尚未原子化），MeshCloth/BoneCloth 仍待迁移。

## 设计方向

统一物理世界把物理节点系统从“每个解算器各自维护 cache”重构为“统一物理世界 owner + 多解算器协作”。

核心判断：

```text
runtime cache 系统不需要继续膨胀。
需要重构的是物理解算层的组织方式。

Cache Read / Cache Write 仍然作为跨帧生命周期边界。
物理节点内部改为传递同一个 PhysicsWorldCache owner。
不同 solver 在同一个 world owner 上读写自己的 slot。
公共 frame / reset / collider / object scope 由 Physics World Begin 统一处理。
```

## 背景

当前 OmniNode 已经具备资源型 runtime cache 能力：

- cache value 可以实现 `omni_cache_dispose(reason)`。
- `cache_replace(value)` 表示替换 owner。
- `cache_mutate(owner)` 表示同一个 committed owner 已被原地更新。
- 带 dispose 协议的 owner 可以走零拷贝路径。

这解决了“一个节点自身的大状态每帧深拷贝”的问题，但没有解决更高层的物理编排问题。

现在的物理解算器仍然大多按“独立小世界”组织：

- MeshCloth MC2 自己读写 `MC2RuntimeOwner`。
- BoneCloth MC2 自己读写 `MC2RuntimeOwner`。
- SpringBone VRM 自己维护 spring cache。
- Mesh XPBD 自己维护 XPBD state。
- 每个节点内部各自判断 reset、跳帧、倒放、连续帧。
- 多个 solver 各自从 scene 枚举 collider。
- 不同 solver 的 cache 互相隔离，跨 solver 交互很难表达。

这导致几个问题：

1. 多个物理节点同时存在时，会出现多份 cache 读写、快照、提交和调试开销。
2. 同一帧内多个 solver 会重复枚举 scene、armature、bone collider 和 object collider。
3. 刚体、布料、骨骼弹簧之间很难共享同一个动态世界。
4. batch 或复杂角色场景里，跨 cache 的交互几乎不可维护。
5. 每个 solver 都写一套 frame/restart/collider 逻辑，行为容易漂移。

## 设计目标

### 必须做到

1. 一个物理链路只读写一个 runtime cache key。
2. 物理链路内部传递同一个 `PhysicsWorldCache` owner。
3. `Physics World Begin` 统一处理当前帧上下文、reset、跳帧、倒放和公共 object scope。
4. solver 节点只处理自己的拓扑、参数、求解和写回。
5. collider 和可动对象范围由显式对象列表控制，避免每帧扫描整个 scene。
6. 物理语义由 solver/domain 自己的 capability 声明持有；显式属性、隐式对象、调试绘制和面板字段都应引用同一份 capability。
7. 未来刚体、cloth、spring、mesh XPBD、soft body、fluid 都能共享同一个 physics world owner。
8. Jolt 这类第三方物理库只作为 solver backend，不成为 OmniNode 公开物理语义。
9. Cache Delete、clear runtime cache、插件注销仍然能释放所有物理资源。
10. 每个 solver 应作为 `physicsWorld` 下可装载/卸载的子模块存在，自己持有 names、capabilities、declaration、nodes、debug draw modes 和属性注册声明。
11. 物理世界核心负责装载 solver 子模块、注册/注销物理属性、汇总 debug 能力、维护公共 world 生命周期，而不成为所有 solver 语义的集中事实源。

### 不做

1. 不把 `PhysicsWorldCache` 做成隐藏全局单例。
2. 不让普通 solver 节点直接写 `OmniRuntimeState`。
3. 不在节点输入里重新描述 radius、group、pin、box size 等已有碰撞属性。
4. 不恢复 scene-wide handler 或全局扫描式 TeamManager。
5. 不要求第一版实现真正的多 solver 双向耦合，只先建立共同容器和公共上下文。
6. 不承诺 Blender depsgraph 只求值 object scope 内对象。object scope 只能限制 OmniNode 自己的枚举、打包和物理输入范围。
7. 不把 Jolt BodyID、ConstraintID、shape enum、constraint enum 等 backend 概念暴露成节点图的稳定公共协议。
8. 不把 `physicsWorld/names.py` 或 `physicsWorld/declarations.py` 发展成永久性的全局大 registry；它们当前可以作为过渡汇总层，但最终权威声明应回到各 solver 子模块内部。
9. 不让 `PhysicsTools` 成为新的全局物理语义所有者；它可以在过渡期提供面板和工具，但属性注册与字段能力最终应由 `physicsWorld` 装载 solver 时统一处理。

## 总体节点形态

推荐链路：

```text
Cache Read
  -> Physics Object Scope
  -> Physics World Begin
  -> Implicit Object Registers
  -> MeshCloth Solver
  -> BoneCloth Solver
  -> SpringBone Solver
  -> Rigid Body Solver
  -> Physics World Commit
  -> Cache Write
```

> 注：`MeshCloth Solver` / `BoneCloth Solver` 为规划中示意，尚未实现；当前仅 `SpringBone Solver`（spring_vrm）与 `Rigid Body Solver`（rigid）两个 domain 已落地。上图展示的是目标形态，含未实现 solver，仅作链路示意。

其中：

- `Cache Read` 读取上一轮 committed 的 `PhysicsWorldCache`。
- `Physics Object Scope` 输出本物理世界关心的对象范围。
- `Physics World Begin` 确保 world owner 对当前帧有效。
- `Implicit Object Registers` 可选地把持久隐式对象写进 `world.implicit_objects`。
- solver 节点接收并返回同一个 world owner。
- `Physics World Commit` 把裸 world owner 包装成 `_OmniCache.replace(...)` 或 `_OmniCache.mutate(...)`。
- `Cache Write` 仍然是最终 runtime cache 提交边界。

关键点：链路中间传递的是裸 `PhysicsWorldCache`，不是 `_OmniCache.mutate(world)` intent。intent 只应在最终 commit 节点产生，避免 wrapper 泄漏给后续普通函数节点。

## 为什么输入对象列表就够

`PhysicsTools` 当前已经把物理配置持久化在 Blender 数据上：

- `Bone.hotools_collision`
  - bone pin
  - sphere / capsule
  - radius / length / offset
  - primary collision group
  - collided-by group mask

- `Object.hotools_object_collision`
  - object-level passive collider
  - sphere / capsule / plane / box
  - radius / length / offset / box_size
  - primary collision group

- `Object.hotools_mesh_collision`
  - mesh vertex collision balls
  - radius vertex group
  - pin vertex group
  - self collision
  - mass
  - primary group / collided-by groups
  - MC2 base pose proxy

因此节点图不需要再创建一套 `PhysicsParticipantSpec` 去重复描述这些字段。更合理的分工是：

```text
对象列表：
  决定本物理世界扫描哪些 Object / Armature / Mesh。

PhysicsTools 属性：
  决定这些 Object / Bone / Mesh 具有什么物理语义。

solver 节点输入：
  决定哪个 solver 作用到哪个目标对象、骨链或 mesh。
```

也就是说，object scope 是“扫描范围”和“依赖范围”，不是“物理语义 schema”。

## Object Scope

第一版定义的轻量 runtime value（**已实现**）：

```python
class PhysicsObjectScope:
    objects: tuple[bpy.types.Object, ...]
    include_passive_collision: bool  # 简单碰撞（hotools_object_collision）
    include_bone_collision: bool     # 骨骼碰撞（hotools_collision on Bone）
    include_mesh_collision: bool     # 简单布料（hotools_mesh_collision）
    include_rigid_body: bool         # 刚体（hotools_rigid_body）
    include_rigid_constraint: bool   # 刚体约束（hotools_rigid_constraint，仅 EMPTY）
    include_hidden: bool
```

它是普通 class，不实现 `omni_cache_dispose()`，因为它只是本帧运行值，不是跨帧资源 owner。

**字段命名对齐原则**：字段名与 HoTools 统一物理面板的类型开关名称一一对应，
降低用户配置 scope 时的认知成本。

### Scope 节点

已实现的节点（Phase 2）：

```text
Physics Objects From Collection（物理对象-从集合）
  输入：Collection, recursive
  输出：list[Object]
  注：不在此处过滤可见性，统一由下游 Physics Object Scope 决定。

Physics Object Scope（物理对象范围）
  输入：list[Object]（多重输入，自动展平去重）,
        include_passive_collision, include_bone_collision,
        include_mesh_collision, include_rigid_body,
        include_rigid_constraint, include_hidden
  输出：PhysicsObjectScope
```

已移除的节点：
- `Physics Merge Objects` — `list[Object]` 类型自动生成多重输入 socket，无需单独合并节点。
```

这些都是普通函数节点，不需要 GraphNode，因为它们只是在当前帧构造运行值，不改变 runtime cache 语义。

### Scope 解析规则

`Physics World Begin` 解析 scope 时：

1. 对每个 object 去重，使用 `obj.as_pointer()` 或 fallback `id(obj)`。
2. `include_hidden=False` 时跳过不可见对象（`include_hidden` 语义以 `PhysicsObjectScope` 为准，`Physics World Begin` 不再接收同名参数，见下文）。
3. 若 object 有 `hotools_object_collision` 且 `enabled=True`，生成简单碰撞 source（旧逻辑为 `collision_type != "NONE"`，现已统一改为 `enabled` 开关）。
4. 若 object 是 Armature 且 `include_bone_collision=True`，扫描该 armature 的 bones 上的 `hotools_collision`。
5. 若 object 是 Mesh 且 `include_mesh_collision=True`，读取 `hotools_mesh_collision`（简单布料），作为 mesh collision / self collision / base pose proxy 的可用配置来源。
6. 若 object 引用失效，当前帧跳过并在 debug snapshot 中记录 invalid count。

### Scope Key 计算规则（重要）

scope key 用于检测 object 范围是否变化，进而触发 `restart_required`。

**不能只用 `obj.as_pointer()` 作为 key**：Blender 删除对象后会释放地址，新建对象可能复用同一整数指针，导致 scope 已经变化但 key 未改变，restart 不会触发。

推荐的 scope key 构造：

```python
def build_scope_key(objects: tuple, include_flags: tuple) -> frozenset:
    entries = []
    for obj in objects:
        try:
            obj_ptr = int(obj.as_pointer())
            # data_ptr 感知 mesh / armature 数据被替换的情况
            data_ptr = int(obj.data.as_pointer()) if obj.data is not None else 0
            entries.append((obj_ptr, data_ptr))
        except Exception:
            # 引用已失效，记录一个标记值而不是跳过（跳过会导致数量稳定但内容变了）
            entries.append((-1, id(obj)))
    return frozenset(entries) | {("flags", include_flags)}
```

`include_flags` 包含 `(include_passive_collision, include_bone_collision, include_mesh_collision, include_rigid_body, include_rigid_constraint, include_hidden)` 的 bool tuple，flag 变化也应触发 restart。

scope key 存入 `world.object_scope_key`，每帧 Begin 时重新计算并与上帧比较。

## PhysicsWorldCache

`PhysicsWorldCache` 是新的共享 owner。它应实现：

```python
def omni_cache_dispose(self, reason: str) -> None:
    ...

def omni_cache_debug_snapshot(self) -> dict:
    ...
```

建议职责：

```text
PhysicsWorldCache
  frame_context
  object_scope_key
  object_sources
  collider_snapshot
  previous_collider_snapshot
  solver_slots
  implicit_objects
  exchange
  backend_resources
  debug counters
```

### FrameContext

统一表示当前帧状态：

```python
class PhysicsFrameContext:
    scene_key: str
    frame: int
    previous_frame: int | None
    continuous: bool
    same_frame: bool
    reset_requested: bool
    restart_required: bool
    dt: float
    time_scale: float
    substeps: int
    generation: int
```

语义：

- `continuous=True`：`current_frame == previous_frame + 1`。
- `same_frame=True`：`current_frame == previous_frame`。是否允许同帧重复执行由 world policy 决定。
- `restart_required=True`：reset、倒放、跳帧、scope 改变或 world invalid。
- `generation`：world 每次重建或全局 restart 时递增，solver slot 可用它判断是否需要冷启动。
- `exchange`：当前图执行内的帧级 scratch registry。`Physics World Begin` 会清空上一轮 exchange；需要跨帧保存的数据必须升级为 spec、solver slot 或 world state。
- `implicit_objects`：跨帧持久的隐式物理对象 registry。它不属于帧级 exchange，Begin 不清空；注册节点按 tag/stable_id 追加或更新对象，solver 通过 tag 收集自己要消费的对象。

### 隐式物理对象

统一物理世界允许“注册节点 / 生成节点”把会参与模拟的对象隐式写入 world，但这个入口必须是正式、可检查的 registry：`world.implicit_objects`。

这类数据包括：

```text
SpringBone VRM 链设置
MC2 mesh / bone cloth 设置组
规则生成的 Jolt 刚体约束
批量生成的 joint / attachment / force field 规格
solver 参数对象
```

它不包括：

```text
force / impulse / activate 等一次性命令       -> world.exchange
solver 每帧输出 transform / pose / contact     -> world.result_streams
native body / constraint handle                -> solver slot / backend resource
```

隐式对象节点的统一形态：

```text
<Domain>属性
  输入：对象、骨链或规则参数
  输出：属性对象

<Domain>对象注册
  输入：world, 属性对象, enabled
  输出：world, item_count, dirty_count, version
  行为：world.append_implicit_object(tag, stable_id, payload, signature, enabled)
```

约束：

1. 属性节点和注册节点都是普通函数节点，不是 GraphNode。
2. 注册节点必须接收并返回同一个 `PhysicsWorldCache`，保证 world 链路仍然线性。
3. 注册节点不直接创建 solver slot，不写 backend handle，不写 Blender，不写 `exchange`。
4. `tag` 必须来自 solver 子模块自己的 names 声明，例如 `physicsWorld/spring_vrm/names.py` 中的 `SPRING_VRM_CHAIN_OBJECT_TAG`；物理世界核心只在装载 solver 时汇总这些名称，避免注册节点和 solver 字符串错位。
5. `stable_id` 是 registry 内部去重/替换用，不暴露成用户设置。相同 tag + stable_id 后写覆盖前写。
6. 同一 tag 下可以自然 append 多个对象；solver 直接按 tag 收集全部对象。
7. `signature` 必须由拓扑、配置和参数输入组成。签名不变时 `version` 不递增，solver 不应重建。
8. `enabled=False` 表达禁用该隐式对象；删除节点不会自动清除旧对象。
9. `implicit_objects` 在 world replace 时浅拷贝，在 Cache Delete / clear runtime cache / world dispose 时清除。
10. 隐式对象默认不参与写回。即使某个 payload 表达了虚拟刚体、批量约束或临时 attachment，Physics Writeback 也只能消费 result stream；没有显式 owner resolver 时不得把隐式对象当作 Blender `Object` 或 `PoseBone` 写回。

当前 `physicsWorld/names.py` 可以作为过渡汇总层，但长期不应成为永久集中事实源。后续新增 solver 时，solver id、slot kind、result channel、exchange channel、backend resource key、implicit object tag 和 debug draw mode 都应先定义在 solver 子模块内部，再由物理世界核心在装载阶段注册到公共索引。公共索引只负责查找和冲突检查，不拥有语义。

未来 solver 迁移时不再把大量对象/设置 socket 全塞进 solver step 节点。推荐拆成：

```text
World Begin
  -> <Domain>属性
  -> <Domain>对象注册
  -> <Domain>模拟步
  -> Physics Writeback
  -> World Commit
```

solver step 的职责是读取自己声明的 `implicit_objects` tag，构建/更新 spec 和 solver slot，再调用 native 后端。这样 SpringBone、Jolt 约束生成、MC2 规则设置会走同一套隐式对象模式。

### Solver 子模块装载协议

长期结构应把每个 solver 当成 `physicsWorld` 下的可拆卸小模块，而不是把所有声明集中塞进物理世界根目录。物理世界核心只定义装载协议和公共服务；solver 子模块自己持有完整生态。

推荐 solver 子模块结构：

```text
physicsWorld/<solver_domain>/
  __init__.py
  names.py              # solver id、slot kind、result/exchange channel、implicit object tag、debug draw mode id
  capabilities.py       # 显式属性、隐式对象、面板字段、resolver 共用的能力表
  declaration.py        # consumes / produces / persistent_state / update_policy / writeback
  nodes.py              # 属性节点、注册节点、模拟步节点
  specs.py              # 规范化 spec / payload / signature
  solver.py             # slot 生命周期和求解调度
  debug.py              # debug snapshot 摘要、debug draw mode 声明
  backends/             # native / 第三方 backend adapter
```

物理世界核心提供：

- solver module discovery / register / unregister。
- 名称冲突检查：solver id、channel、implicit object tag、debug draw mode id 不能重复。
- capability registry：汇总 solver 暴露的能力表，供面板、节点生成、隐式对象注册和测试审查使用。
- property registration：根据 solver capability 注册或注销 Blender PropertyGroup / PointerProperty / 面板入口。
- common draw service：`physicsWorld/utils/debug_draw.py` 只提供线段、GPU batch、向量/矩阵转换和基础 shape 线框等无语义函数；solver 自己持有 debug snapshot 摘要、debug draw mode 和精细绘制语义。
- world debug draw：不再承载 collider / rigid / SpringBone 等具体绘制。刚体/Jolt、SpringBone 等精细绘制已经下沉到各自 solver 的 debug 模块；未来若恢复世界级可视化，只用于 exchange item、result stream 和跨 solver 关系。
- world 生命周期：frame context、scope、collider snapshot、solver slot、exchange、result stream、commit/dispose。

solver 子模块必须提供：

- `SOLVER_DECLARATION`。
- `NAMES` 或等价的 names 常量集合。
- `CAPABILITIES`，包括显式属性和隐式对象引用的同源字段表。
- 可选 `PROPERTY_REGISTRATION`，声明需要挂到 `Object`、`Bone`、`Scene` 等 Blender owner 上的属性。
- 可选 `DEBUG_DRAW_MODES`，声明自己支持的调试绘制模式和对应 result/debug snapshot 来源。
- `register_nodes()` / `unregister_nodes()` 或等价节点注册入口。
- `dispose_world_resources(world)` 或 slot/backend dispose 钩子，保证 Cache Delete、clear runtime cache 和插件注销可以释放资源。

这样做的边界是：物理世界核心知道“有哪些 solver 插件、它们声明了哪些公开通道、如何装载/卸载”，但不直接拥有 SpringBone、Rigid、MC2、BoneCloth 的具体字段语义。具体字段语义由 solver capability 拥有。

### 物理属性注册职责

物理属性注册也应逐步收归 `physicsWorld` 装载流程，而不是长期由外部 `PhysicsTools` 模块独立维护事实源。

过渡期：

- `PhysicsTools/physicsProperty.py` 继续保存现有 `Bone.hotools_collision`、`Object.hotools_object_collision`、`Object.hotools_mesh_collision` 等 PropertyGroup，避免破坏旧面板和旧节点。
- solver capability 先 copy 一份同构字段表，用测试证明 resolver 输出与旧属性直读完全一致。
- 外部物理面板改为引用 capability 或由 capability 审查字段，减少字段定义分叉。

目标期：

- solver capability 是字段、默认值、显示名、范围、更新频率和 resolver 的单一事实源。
- `physicsWorld` 在装载 solver 时注册它声明的显式属性，并在卸载 solver 时注销。
- 显式属性和隐式对象只是同一 capability 的两种 authoring interface。
- `PhysicsTools` 退化为 UI/操作器/预览工具集合，不再拥有 solver contract。

### Object Source

`Physics World Begin` 不应每次都构造完整 collider dict 后再让不同 backend 反复转换。建议先构造轻量 source，再按需求生成 snapshot 或 arrays。

```python
class PhysicsColliderSource:
    owner: bpy.types.Object
    owner_type: "OBJECT" | "BONE" | "MESH"
    bone_name: str
    props: object
    key: str
    visible: bool
```

第一版可以继续用 dict，不必先做类。重点是 source 只来自 object scope。

### Collider Snapshot

公共 collider snapshot 由 world owner 持有：

```python
world.collider_snapshot
world.collider_arrays("mc2")
world.collider_arrays("spring_bone_cpp")
```

第一版可以先只缓存通用 dict list：

```python
{
    "frame": frame,
    "colliders": [ ... ],
    "source_count": N,
    "object_count": M,
}
```

以后再按 backend 增加 arrays cache：

```python
world.runtime_cache("collider_arrays:mc2")
world.runtime_cache("collider_arrays:spring_vrm_cpp")
world.runtime_cache("collider_arrays:rigid_jolt")
```

### Previous Collider Snapshot

MC2 已经需要 moving collider 的 previous pose。这个状态应该从 solver 私有 state 上移到 world：

```text
world.previous_collider_snapshot
world.current_collider_snapshot
```

提交策略：

- `Physics World Begin` 生成 current snapshot。
- solver 在本帧使用 `previous + current`。
- `Physics World Commit` 成功前，world 内部已经被原地更新。
- 如果本轮后续节点报错，下一帧 `Physics World Begin` 必须通过 frame/generation 判断是否可信，不可信就重建或冷启动。

这和当前 resource cache 原地 mutation 语义一致。

### Solver Slots

solver 不再拥有整个 runtime cache owner，而是在 world 内拿自己的 slot：

```python
slot = world.ensure_solver_slot(
    solver_id="meshcloth:{obj_ptr}:{mesh_ptr}:{output_key}",
    kind="mc2_mesh_cloth",
    topology_key=...,
    config_key=...,
)
```

**solver_id 构造规则（重要）：**

solver_id 必须同时包含 `obj.as_pointer()` 和 `obj.data.as_pointer()`（对于 Mesh/Armature），不能只用 `obj.as_pointer()`。

原因：Blender 删除对象后会释放内存指针，随后新建对象可能获得完全相同的整数地址。若 slot_id 只含对象指针，新对象会命中旧 solver slot，继承错误的拓扑缓存或 native context，导致物理爆炸或静默错误。

各 solver 的 id 构造示意：

```text
MeshCloth:   "mc2_mesh:{obj_ptr}:{mesh_ptr}:{output_key}"
BoneCloth:   "mc2_bone:{armature_ptr}:{armature_data_ptr}:{chain_hash}"
SpringBone:  "spring_vrm:{armature_ptr}:{armature_data_ptr}:{topology_hash}"
RigidBody:   "rigid:{obj_ptr}:{obj_data_ptr}"
```

scope/world restart（generation 递增）时，world 会标记所有 slot 失效；solver 检测到 generation 不匹配时应冷启动 slot，不依赖 slot_id 做旧状态恢复。

slot 内容由 solver 自己维护：

```text
MeshCloth slot:
  MC2RuntimeOwner or MC2CenterState
  topology cache
  native context
  base pose state
  particle state

BoneCloth slot:
  MC2RuntimeOwner or bone-specific state
  write records
  chain topology

SpringBone slot:
  chain state
  write records
  native arrays cache

RigidBody slot:
  body handles
  constraint handles
  body specs
```

world 只管 slot 生命周期：

- scope/world restart 时可标记所有 slot `world_restart_generation`。
- solver topology/config 变化时，由 solver 自己重建自己的 slot。
- world dispose 时调用所有 slot 的 dispose。

slot 可以实现：

```python
def dispose(self, reason: str) -> None:
    ...

def debug_snapshot(self) -> dict:
    ...
```

也可以第一版用 dict + owner 对象混合实现。

## Physics World Begin

建议节点签名：

```python
def physicsWorldBegin(
    cache_state: _OmniCache,
    scene: bpy.types.Scene,
    object_scope: PhysicsObjectScope,
    reset: bool = False,
    time_scale: float = 1.0,
    substeps: int = 1,
    debug_output: bool = False,
) -> tuple[PhysicsWorldCache, int, int, bool]:
    ...
```

注意：`include_hidden` 已从此处移除。可见性策略统一由 `PhysicsObjectScope` 决定（在 `Physics Object Scope` 节点构造时传入），`Physics World Begin` 直接读取 `object_scope.include_hidden`，不再接收同名参数。这样避免两处设置不一致导致隐藏对象是否参与碰撞产生歧义。

输出：

```text
world
frame
collider_count
restart_required
```

职责：

1. 校验 scene 和 object scope。
2. 如果 `cache_state` 不是 `PhysicsWorldCache`，创建新 owner。
3. 计算 scene key、frame、dt、substeps、time scale。
4. 判断连续帧、同帧、倒放、跳帧、reset。
5. 计算 object scope key。
6. 如果 scope key 改变，标记 `restart_required`。
7. 从 object scope 构建 collider sources。
8. 从 sources 构建 collider snapshot。
9. 更新 world frame context。
10. 返回裸 world owner。

注意：Begin 不应该知道 MeshCloth、BoneCloth、SpringBone 的业务参数。它只处理世界级上下文。

## Physics World Commit

建议节点签名：

```python
def physicsWorldCommit(
    world: PhysicsWorldCache,
) -> tuple[_OmniCache, PhysicsWorldCache, int]:
    ...
```

输出：

```text
cache_value
world
solver_count
```

职责：

1. 校验 world。
2. 若 world 是本轮新建或重建，返回 `_OmniCache.replace(world)`。
3. 若 world 是连续帧复用，返回 `_OmniCache.mutate(world)`。
4. 透传裸 world 供后续 debug 或输出链路使用。

它不应自己写 runtime cache。最终仍由 Cache Write 节点提交。

## Solver 节点迁移后的职责

### 通用规则

solver 节点输入从：

```text
cache_state: _OmniCache
scene
reset
...
```

迁移为：

```text
world: PhysicsWorldCache
target object / armature / chains
solver params
...
```

solver 不再做：

- Cache Read / Cache Write wrapper。
- 全局 frame continuity 判断。
- scene-wide collider scan。
- runtime cache owner 替换。

solver 仍然做：

- target 校验。
- solver_id 构造。
- topology key / config key 计算。
- slot 命中或重建。
- base pose 同步。
- solver kernel 调用。
- 产出 result / writeback 数据，或调用统一写回阶段需要的 runtime 输出。
- solver-specific debug timing。

### MeshCloth MC2

当前 `MC2RuntimeOwner` 可以先不删除，而是挂进 world slot：

```text
world.solver_slots["mc2_mesh:{obj_ptr}:{output_key}"].owner = MC2RuntimeOwner
```

迁移点：

- `current_frame` 读取 `world.frame_context.frame`。
- `restart_required` 读取 `world.frame_context.restart_required`，再 OR 自己的 topology/config mismatch。
- `colliders` 读取 `world.colliders_for(owner=obj, mask=...)` 或 `world.collider_snapshot["colliders"]`。
- `previous_collider_snapshot` 逐步从 `MC2CenterState` 上移到 world。
- `cache_value = _OmniCache...` 删除，改为返回裸 world。

### BoneCloth MC2

BoneCloth 目前已经复用 `MC2RuntimeOwner`，迁移方式和 MeshCloth 类似：

- slot id 由 armature pointer + chain topology + connection mode 组成。
- write records 留在 slot 的 runtime cache。
- frame/restart 来自 world。
- collider snapshot 来自 world。
- 写回仍由 BoneCloth 自己负责。

### SpringBone VRM

SpringBone VRM 现在有自己的 collision source cache 和 C++ arrays cache。迁移后：

- `collision_snapshot(scene)` 改为 `world.collider_snapshot`。
- `collision_snapshot_cpp(scene)` 改为由 SpringBone native 包装层从 `world.collider_snapshot` 打包；当前已接入 `SPHERE` / `CAPSULE` / `PLANE` / `BOX`，并沿用 MC2/Jolt 的公共 collider type code。
- chain state 放到 spring solver slot。
- `frame` 和跳帧恢复策略读取 world frame context。
- root hard pin 仍由 chain 输入决定，不放进 world。
- 当前最小链路已覆盖 `VRM骨链属性 -> VRM骨链对象注册 -> SpringBone VRM模拟步 -> 物理写回`，并有 Blender 后台测试验证 native step、PoseBone 写回、连续帧状态、same-frame 结果复发、spec 变化后的 stale slot prune、Cache Delete / `clear_all` 的 PoseBone 复位，以及 collider snapshot 投影。

#### 案例：链 root 与骨骼碰撞的单一真值源

SpringBone 是「同一语义只能有一个真值来源」原则（见 `ARCHITECTURE.md` §7.3）在物理侧的具体应用，值得作为后续 solver 的参考。

**链 root**：曾经有两个来源——解算侧靠“从根获取骨链”节点输入的骨决定 root，数据侧又有 `Bone.hotools_collision.spring_root` 布尔标记配套一整套 operator 和面板。但解算器**从不读** `spring_root`，它只被预览侧用来离线猜 root 画 Pin 高亮，于是两套判定天然脱钩：节点里填了骨 A 当 root，只要 A 没勾 `spring_root`，预览就显示不出。已删除 `spring_root` 属性、三个 operator 和面板块，root 的唯一真值来源就是骨骼输入本身。新路径的 root 判定虽已比“输入骨即 root”复杂（`spring_vrm/implicit_objects.py` 的 `_chains_from_direct_bone_values` 按父子关系在“单根递归”和“多 root 分组”间选择），但真值来源不变：始终来自骨骼输入，不存在并行持久标记。

**骨骼碰撞字段（含 pin）**：新路径不再由 solver 直读 `Bone.hotools_collision`。`spring_vrm/bone_collision.py` 的 `resolve_bone_collision_fields` / `resolve_bone_pin` 是统一 resolver，解析优先级 `bone_collision.override` 隐式对象（计划中）> 旧 `Bone.hotools_collision` > `BONE_COLLISION_CAPABILITY` 默认值。native 消费端只认 resolver，不再各写一份 `getattr`。这样等 override 隐式对象节点落地、属性注册最终迁到物理世界侧（支柱 9）时，唯一真值来源始终收敛在 capability + resolver 上。

### Mesh XPBD 参考迁移

Mesh XPBD 是旧蓝本，只作为阶段拆分和 native resident state 的参考，不作为兼容路径保留。若迁移：

- state 放到 `world.solver_slots["mesh_xpbd:{obj_ptr}:{data_ptr}"]`。
- collision snapshot 来自 world。
- frame/restart 来自 world。
- owner 直接收敛到 world slot，不再用 `OmniCacheOwnerDict` 包旧 dict 作为双路径。

### Rigid Body solver / Jolt backend

统一 physics world owner 对刚体也很重要，因为刚体仿真天然需要长期资源。但公开层不要设计成 Jolt world，也不要设计成单独的 rigid world。Jolt 只是刚体 solver 的 native backend，OmniNode 自己的物理世界表达才是稳定协议：

```text
world.backend_resources["rigid_solver"]   # private backend context, backend="jolt"
world.solver_slots["rigid_body:{object_ptr}"]
world.solver_slots["constraint:{constraint_object_ptr}"]
```

公开节点和数据命名应保持 OmniNode / Blender 语义：

```text
Rigid Body Setting
Rigid Constraint Setting
Rigid Constraint Point
Rigid Body Solver
```

不推荐在公开节点里使用：

```text
Jolt Body
Jolt Constraint
Jolt Shape
Jolt World
```

`Rigid Body Solver` 可以有一个 backend 选项，第一版默认或唯一值是 `JOLT`。这个选项只影响内部适配器，不改变节点图的物理语义。

刚体节点可以先做高封装：

```text
Rigid Body Solver(world, rigid_objects, constraint_objects, settings)
```

以后需要拆分时再拆成：

```text
Rigid Body Register Objects
Rigid Constraint Register Objects
Rigid Body Step
Rigid Body Writeback
```

第一版不需要新增 GraphNode。它们都是普通函数节点，传入并返回 `PhysicsWorldCache`。

### Jolt 只作为 backend 适配层

Jolt 接入的边界建议是：

```text
OmniNode object scope
  -> HoTools rigid body specs
  -> HoTools constraint specs
  -> Jolt adapter build/update
  -> Jolt step
  -> world.result_streams["rigid_transform"]
  -> world.result_streams["rigid_solver_stats"]
  -> Physics Writeback
  -> Object.delta_* / PoseBone / mesh delta writeback
```

也就是说，Jolt 的 `BodyID`、`ConstraintID`、shape handle、constraint handle 只能存在于 rigid solver slot 或 `world.backend_resources["rigid_solver"]` 内部。debug snapshot 可以显示 backend 名称和数量统计，但不应要求用户或其他 solver 依赖 Jolt handle。

这样未来即使替换、混用或补充其他 backend，公开图也仍然是：

```text
对象范围 + OmniNode 物理属性 + solver 设置 + 约束点对象
```

而不是：

```text
Jolt 专用对象图
```

### 约束点载体

刚体约束不建议一开始设计成大量细输入 socket。更稳的方向是引入新的 Blender 物体对象作为约束点载体，第一版可以使用 Empty：

```text
Empty object transform:
  表示约束 anchor frame、位置、旋转和可视化操控点。

Empty read-only custom properties:
  表示 OmniNode 约束语义，例如 constraint type、target A、target B、axis、limit、motor、break threshold、disable_collisions。
```

这些 custom properties 应该通过 HoTools 面板或操作器维护，对节点和 solver 来说视为只读配置。节点图只需要把这些 Empty 对象纳入 object scope 或显式接到 `Rigid Constraint Setting` / `Rigid Body Solver`。

关键边界：

- 约束点是 OmniNode 物理语义，不是 Jolt 语义。
- Empty 的 transform 是约束 anchor 的 Blender-native 表达。
- custom property enum 使用 HoTools 自己的名字，Jolt adapter 负责映射到 Jolt constraint。
- `disable_collisions` 表示约束连接体之间是否禁用直接碰撞，应由刚体 solver 私有 pair filter 表达，不复用简单碰撞组。
- Jolt constraint handle 只保存在 runtime slot 中，不写回 Empty。
- 约束点对象应该能被其他 solver 看见，至少作为调试、采样或未来跨 solver 交互的公共锚点。

## Object Scope 与 solver target 的关系

用户可能会问：某个对象既要放进 object scope，又要接到 solver，是否重复？

这是有意分工：

```text
object scope:
  告诉 world “这些对象是本物理世界需要感知的对象”。

solver target:
  告诉某个 solver “你要模拟或写回这个对象”。
```

典型情况：

```text
地面 collider:
  放进 object scope。
  不接 solver。

布料 proxy:
  放进 object scope，让其他 solver 能感知它的 mesh collision。
  同时接 MeshCloth solver，自己被模拟。

角色 armature:
  放进 object scope，让 bone collider 被采样。
  同时接 SpringBone / BoneCloth solver。

刚体道具:
  放进 object scope。
  同时接 RigidBody solver。
```

这样比隐式扫 scene 更清楚，也比手写 participant schema 更轻。

## Cache 边界

推荐用户图：

```text
Cache Read(key="physics_world")
  -> Physics World Begin
  -> Solver...
  -> Physics World Commit
  -> Cache Write(key="physics_world")
```

规则：

1. 每条物理世界链路只有一个 cache key。
2. 中间 solver 不接 Cache Write。
3. solver 不直接调用 `OmniRuntimeState.write_cache()`。
4. `PhysicsWorldCache` 实现 `omni_cache_dispose()`。
5. `Physics World Commit` 是唯一把 world 包成 cache intent 的普通函数节点。
6. Cache Delete / clear runtime cache 仍然释放整个 world 和所有 solver slot。

## 执行顺序和副作用

统一 world owner 依赖节点连线提供顺序：

```text
world -> solver A -> solver B -> solver C -> commit
```

不要把同一个 world 分叉给两个并行 solver 后再 merge。OmniNode 当前没有事务式并行 mutation 语义，分叉原地修改同一个 owner 会让执行顺序变得隐性。

如果需要多 solver 交互，应通过线性链路表达：

```text
RigidBody step
  -> Cloth step
  -> SpringBone step
  -> Writeback
```

以后如果确实需要并行，可以再设计显式 `Physics World Merge` 或调度型 GraphNode。第一版不要做。

### 运行时分叉防护

上述约束仅靠文档无法保证用户不误接。`PhysicsWorldCache` 应在实现层维护一个写入锁：

```python
class PhysicsWorldCache:
    def __init__(self):
        ...
        self._current_writer: str | None = None  # 当前持锁的 solver_id

    def acquire_write(self, solver_id: str) -> None:
        """solver 开始写入前调用。若 world 已被另一个 solver 持有则立即抛错。"""
        if self._current_writer is not None and self._current_writer != solver_id:
            raise RuntimeError(
                f"PhysicsWorldCache 分叉写入冲突：{self._current_writer!r} 尚未释放，"
                f"{solver_id!r} 不能同时写入同一个 world。请检查节点连线是否把 world 分叉给了多个 solver。"
            )
        self._current_writer = solver_id

    def release_write(self, solver_id: str) -> None:
        """solver 写入结束后调用。"""
        if self._current_writer == solver_id:
            self._current_writer = None
```

solver 节点包裹：

```python
world.acquire_write(solver_id)
try:
    # ... solver kernel ...
finally:
    world.release_write(solver_id)
```

这样误接时会在节点执行阶段立即抛出 `RuntimeError`，错误信息直接指向分叉来源，不会产生静默的状态污染。

`Physics World Begin` 在每帧开始时也应清空 `_current_writer = None`，防止上一帧异常退出留下锁。

## 调试和可观察性

`PhysicsWorldCache.omni_cache_debug_snapshot()` 至少输出：

```python
{
    "kind": "PhysicsWorldCache",
    "frame": frame,
    "previous_frame": previous_frame,
    "continuous": continuous,
    "restart_required": restart_required,
    "generation": generation,
    "objects": object_count,
    "collider_sources": source_count,
    "colliders": collider_count,
    "exchange_channels": {"rigid_body_commands": 2},
    "exchange_item_count": 2,
    "solver_slots": {
        slot_id: slot.debug_snapshot(),
    },
}
```

`Physics World Begin` 节点也可以输出：

```text
frame
object_count
collider_count
restart_required
```

这样用户不用 dump 整个 cache 也能确认本帧实际参与物理的数据规模。

## replace / mutate 切换规则

`replace_required` 是 `Physics World Commit` 决定写入模式的唯一依据。以下表格说明各种情况下该标志的正确状态：

| 情况 | `replace_required` | Commit 写入模式 |
|---|---|---|
| 第一帧（`cache_state` 不是 `PhysicsWorldCache`） | `True`（Begin 新建 world 时设置） | `replace` |
| scope 改变触发 world 重建 | `True` | `replace` |
| `reset=True` 触发 world 重建 | `True` | `replace` |
| 连续帧正常推进，world 对象复用 | `False`（Begin 复用 world 后清除） | `mutate` |
| 上一帧提交失败（pending 未提交，committed owner 可能脏） | `True`（Begin 检测到帧不连续，标记 invalid，重建 world） | `replace` |

**关键约定（必须遵守）：**

1. `replace_required` 只由 `Physics World Begin` 写入，`Physics World Commit` 只读。
2. `Physics World Begin` 在函数返回前必须保证 `replace_required` 已被正确设置，不能把 world 内部残留的上一帧标志带到 Commit。
3. `Physics World Commit` 遇到 `mutate` 路径时，world 对象必须已经在 committed cache 中（`OmniRuntimeState` 的 mutate 校验会检查这一点）。若 Begin 因为脏帧重建了 world，应走 `replace`，不应走 `mutate`。
4. world 在 Begin 内被原地更新（`_current_writer` 释放后），`replace_required=False` 时 Commit 走 `mutate` 是安全的，因为这和 `OmniRuntimeState` 的原地 mutation 语义一致。

## 失败与回滚

统一 world 仍然沿用资源型 cache 的现实边界：

- world owner 是原地 mutation。
- runtime cache 不 clone native world。
- 若某个 solver 已经修改 world，后续节点报错，本轮 pending 不提交，但 committed owner 可能已经被原地改过。
- 下一帧 `Physics World Begin` 必须通过 frame/generation/validity 检测处理不可信状态。

因此 `Physics World Begin` 是可信度检查的第一道门：

```text
if previous_frame is not current_frame - 1:
    world.valid = False

if world.valid is False:
    # 不复用现有 world，重建一个新 owner
    world = PhysicsWorldCache()
    world.replace_required = True

if object scope key changed:
    restart_required = True
    generation += 1
```

脏帧（failed run）的处理流程：

1. 本轮 `OmniRuntimeState.finish_run` 因 `run.failed=True` 跳过提交，pending 被丢弃。
2. committed cache 仍然持有上一次成功提交的 world owner（可能已被原地改过一半）。
3. 下一帧 Begin 读取该 owner，帧号不连续（`frame != prev_frame + 1`），标记 `world.valid = False`。
4. Begin 重建新 world，`replace_required = True`，旧 owner 被 Commit 的 `replace` 写入替换，`omni_cache_dispose` 释放旧资源。

solver slot 也必须保留自己的 topology/config 校验：

```text
if world restart generation changed:
    cold restart slot

if solver topology changed:
    rebuild slot

if solver params require rebuild:
    rebuild or refresh static arrays
```

## 与现有文档约定的关系

本设计不改变以下原则：

1. 默认业务节点仍然是函数生成节点。
2. Cache Read / Cache Write / Cache Delete 仍然是 GraphNode。
3. 跨帧状态仍然必须显式通过 runtime cache 暴露。
4. C++ backend 不应保存隐藏全局状态。
5. 资源生命周期仍通过 owner 的 `omni_cache_dispose()` 管理。

变化的是物理节点库的推荐接法：

```text
旧：
  每个 solver 有自己的 Cache Read -> Solver -> Cache Write。

新：
  一个 Physics World 有自己的 Cache Read -> Begin -> 多 solver -> Commit -> Cache Write。
```

## 实施路线

核心顺序：不要从迁移旧 solver 开始。先搭低层物理世界和通用节点，让 debug 节点能稳定观察 `PhysicsWorldCache` 本身；这部分测试稳定以后，再开始迁移 MC2、SpringBone、XPBD 等已有 solver。

### Phase 0：命名和目录边界

新增顶层物理世界目录：

```text
OmniNode/NodeTree/Function/physicsWorld/
```

不要新增 `rigidWorld/`、`physicsRigidWorld/` 这类目录。刚体只是物理世界里的一个 domain，应该放在 `physicsWorld` 下面：

```text
physicsWorld/
  __init__.py
  types.py
  scope.py
  sources.py
  world.py
  debug.py
  registry.py
  nodes.py
  spring_vrm/
    __init__.py
    names.py
    capabilities.py
    declaration.py
    implicit_objects.py
    nodes.py
    specs.py
    solver.py
    debug.py
    backends/
  rigid/
    __init__.py
    names.py
    capabilities.py
    declaration.py
    specs.py
    constraints.py
    nodes.py
    solver.py
    debug.py
    backends/
      jolt.py
```

目录语义：

- `types.py`：`PhysicsWorldCache`、`PhysicsFrameContext`、`PhysicsObjectScope` 等基础类型。
- `scope.py`：对象列表合并、过滤、去重、scope key 计算。
- `sources.py`：从 object scope 解析 Object / Bone / Mesh 的物理 source。
- `world.py`：begin / commit / lifecycle / slot 管理。
- `debug.py`：debug snapshot、flatten text、校验结果。
- `registry.py`：solver 子模块装载/卸载、名称冲突检查、capability/property/debug draw mode 汇总。
- `nodes.py`：对外暴露的通用函数节点。
- `<solver>/names.py`：该 solver 自己的 id、slot kind、channel、implicit object tag、debug draw mode id。
- `<solver>/capabilities.py`：该 solver 的显式/隐式属性能力表。
- `<solver>/declaration.py`：该 solver 的 consumes / produces / persistent_state / update_policy / writeback。
- `<solver>/debug.py`：该 solver 的 debug snapshot 摘要与 debug draw mode 声明。
- `<solver>/backends/`：native 或第三方 backend adapter。

### Phase 0：命名和目录边界 ⚠️ 部分完成

上面的目录清单是**目标结构**，当前尚未完全落地。实际进度是“spring_vrm 领先、rigid 待原子化”：

- `physicsWorld/` 根目录**缺 `registry.py` 和 `sources.py`**：solver 子模块装载/卸载、名称冲突检查仍未有独立装载器；source 解析目前仍并入 `world.py` / `physicsWorldBegin`，未单独成文件。
- `spring_vrm/` 已接近目标原子化结构：`names.py`、`capabilities.py`、`declaration.py`、`implicit_objects.py`、`specs.py`、`solver.py`、`debug.py`、`debug_draw.py` 均已建；当前 `debug.py` 持有 debug snapshot 摘要、native context 统计和 debug draw mode 声明，`debug_draw.py` 持有骨链/尾端可视化采样与 draw store。
- `rigid/` 仍是过渡结构：**既缺 `capabilities.py` 也缺正式 `debug.py`**，rigid 的 solver 声明仍整块内联在中央 `declarations.py`，rigid 名称常量仍留在中央 `names.py`，尚未拆回子模块；但 Jolt 刚体可视化已经从世界层拆到 `rigid/debug_draw.py`。
- 中央 `physicsWorld/names.py` 目前只对 spring_vrm 做了权威下沉：spring_vrm 名称常量已迁到 `spring_vrm/names.py`，中央文件仅用 `__getattr__` 惰性重导出兼容；rigid 名称尚未下沉。

因此 Phase 0 不能记作“目录结构已完成”，只能记作“骨架已建、spring_vrm 接近目标、rigid 与公共装载层（registry/sources）待补齐”。

### Phase 1：低层物理世界基础 ✅ 已完成

### Phase 2：通用函数工具和通用节点 ✅ 已完成

**实际落地节点（已注册）：**

```text
物理对象-从集合（physicsObjectsFromCollection）
物理对象范围（physicsObjectScope）        ← list[Object] 多重输入，无需单独合并节点
物理世界-帧开始（physicsWorldBegin）
物理世界-帧提交（physicsWorldCommit）
```

`Physics Filter Objects`、`Physics Merge Objects` 未实现（多重输入已覆盖合并需求）。

### Phase 3：debug 节点先行 ✅ 已完成，链路已验证

**实际落地节点：**

```text
物理世界-调试快照（physicsWorldDebugSnapshot）
物理世界-调试文本（physicsWorldDebugText）
Jolt刚体可视化调试（physicsRigidJoltDebugDraw）
SpringBone VRM可视化调试（physicsSpringVRMDebugDraw）
```

验证结论：frame/continuous/restart/replace/mutate 行为稳定，跳帧检测正常。

可视化 debug 的 store 必须由各 solver 自己持有，并且必须是纯快照：节点执行时把刚体 shape / constraint anchor / SpringBone bone-tail 等采样成 tuple/list/dict，不保存 `bpy` 对象、spec 引用或 live `matrix_world`。draw handler 只负责把快照转成 GPU lines，不允许在绘制阶段重新读取 Blender 对象。这样 debug 视图表达的是节点链路中该节点所在位置的状态，而不是视口重绘时的外部状态。公共绘制函数只放在 `physicsWorld/utils/debug_draw.py`。

### Phase 4：刚体 domain ✅ 已完成

**实际落地内容：**

刚体实现位于 `physicsWorld/rigid/`（specs.py / solver.py / nodes.py），
属性挂在 `PhysicsTools/physicsProperty.py`（`PG_Hotools_RigidBody` / `PG_Hotools_RigidConstraint`），
面板在统一物理属性面板中（`PhysicsTools/physicsPanel.py`）。

**架构调整（与原设计不同）：**

原设计要求用户接 `Rigid Body Setting` 节点来注册 spec，实际实现将 spec 收集内置到 `physicsWorldBegin`：

```text
旧（原设计）：
  physicsWorldBegin
  → 刚体注册（physicsRigidSolver）← 用户需要手动接这个节点
  → physicsWorldCommit

新（实际落地）：
  physicsWorldBegin  ← 自动从 scope 收集 rigid body spec 和 constraint spec
  → physicsRigidSolver  ← 同步脏 spec/kinematic pose，并在新帧推进 Jolt
  → physicsWriteback    ← 统一写 Object.delta_*
  → physicsWorldCommit
```

原因：刚体/约束 spec 收集和碰撞 snapshot 构建性质相同——都是"从 scope 对象读取 PhysicsTools 属性"，属于 world begin 的职责，不应要求用户额外接节点。

`physicsRigidSolver`（"刚体模拟步"）负责 Jolt backend 同步和 step，不直接写 Blender 对象；写回由 `physicsWriteback` 统一处理。

**已注册节点：**

节点菜单注册到独立 `PHYSICS_WORLD` / `物理世界` 分类，不再混入 legacy `Physics` 分类。

```text
刚体模拟步（physicsRigidSolver）  ← Jolt sync + step，不直接写回
刚体结果-读取状态（physicsRigidReadState）             ← 读取 rigid_transform result stream
刚体命令-设置速度（physicsRigidSetVelocity）          ← 发布 set_velocity
刚体命令-施加力（physicsRigidAddForce）               ← 发布 add_force
刚体命令-施加冲量（physicsRigidAddImpulse）           ← 发布 add_impulse
刚体命令-重力倍率（physicsRigidSetGravityFactor）     ← 发布 set_gravity_factor
刚体世界-Jolt设置属性/注册（physicsRigidJoltWorldSettings*） ← 通过 rigid_jolt.world_setting 配置 Jolt 刚体世界 gravity 和 JoltWorld 容量
刚体命令-材质响应（physicsRigidSetMaterialResponse）  ← 发布 set_material_response
刚体命令-运动质量（physicsRigidSetMotionQuality）     ← 发布 set_motion_quality
刚体命令-激活状态（physicsRigidSetActive）            ← 发布 set_active
物理写回（physicsWriteback）      ← Object.delta_* 增量写回
```

`刚体注册` 节点已移除（功能并入 physicsWorldBegin）。

**声明表与真实节点对齐（历史修正）：** 中央 `physicsWorld/declarations.py` 的 rigid 声明 nodes 列表曾残留 `刚体注册` / `刚体约束注册` 这两个已不存在的幽灵节点名（它们是上述"刚体注册功能并入 physicsWorldBegin"之前的旧命名）。该列表现已修正为真实注册节点名——`刚体模拟步` / `刚体结果-读取状态` / `刚体世界-Jolt设置属性` / `刚体世界-Jolt设置注册` / `刚体生成约束属性` / `刚体生成约束注册` 等，使声明表与实际落地节点、以及本 Phase 4 描述保持一致，不再引用幽灵节点。

### Phase 5：Jolt backend 接入

在 rigid specs 和 debug 输出稳定后，再接 Jolt adapter：

- Jolt native context 只挂在 `world.backend_resources["rigid_solver"]`。
- Jolt body / constraint handles 只保存在 rigid solver slot 内。
- 公开节点仍然是 `Rigid Body Solver`，不是 `Jolt World`。
- debug snapshot 只输出 backend 名称、body count、constraint count、step timing 和错误摘要。

第一版 Jolt 接入建议先用最小场景验证：少量动态刚体、静态 collider、一个 Empty 约束点、无跨 solver 交互。

**Phase 5 完成标准（必须通过，不可跳过）：**

Jolt world 内部持有大量 native 堆资源（bodies、constraints、broadphase 等），必须在 Phase 5 完成时专门验证 dispose 路径的完整性，不能留到后续阶段：

1. **热重载压测：** 多次执行 Blender 插件 disable → enable 循环（至少 5 次），验证：
   - 内存占用不持续增长（`omni_cache_dispose` 能正确释放 Jolt world）。
   - Blender 进程不崩溃（无悬空 Jolt native 引用）。
2. **Cache Delete 压测：** 在物理链路运行中途执行 `Cache Delete`，验证 world 和所有 rigid solver slot 都被释放，不残留 native body handle。
3. **`clear_all` 路径：** 验证 `OmniRuntimeState.clear_all()` 能触发 `PhysicsWorldCache.omni_cache_dispose`，进而释放 `backend_resources["rigid_solver"]`。

Jolt adapter 的 `dispose` 实现必须确保：先销毁所有 bodies 和 constraints，再销毁 Jolt world，顺序不能颠倒。dispose 内不能引发 Python 异常（否则会中断上层 dispose 链）。

### Phase 5 退出审计

当前 Phase 5 的目标不是把 Jolt 全能力补完，而是证明统一物理世界 contract 足够支撑其它 solver 迁移。Jolt 只需要作为第一条完整 vertical slice：scope -> spec -> native backend -> result stream -> writeback/debug -> runtime cache lifecycle。

**已完成，可作为迁移参照的部分：**

- `PhysicsWorldCache` 已持有 frame context、scope key、collider snapshot、solver slots、implicit_objects、exchange、result streams、backend resources。
- `physicsWorldBegin` 每帧重采集 scope / collider / rigid spec，并处理 restart、scope change、slot prune、spec sync signature、kinematic pose dirty。
- `physicsRigidSolver` 不直接写 Blender；它发布 `rigid_transform` 和 `rigid_solver_stats` result stream。
- `physicsWriteback` 已验证 Object transform 的统一写回路径：只写 `Object.delta_*`，不改原始 transform。
- Jolt / SpringBone 自有 debug draw 节点和 `physicsWorldResultStream` 消费纯快照，不读取 live bpy 对象、Jolt handle 或其它 solver 私有 transform。
- Jolt adapter 主路径只消费 `RigidBodySpec` / `ConstraintSpec` 快照，不再回读 Object / Empty。
- Blender 后台集成测试已覆盖：Jolt adapter 直接运行、world 生命周期、刚体命令 exchange、Jolt 刚体世界 gravity/capacity setting、结果读取节点、60 帧落地、dispose + rebuild、约束 disable collisions。
- 真实 runtime cache 生命周期 smoke 已覆盖：Physics World Commit 输出的 replace/mutate intent 进入 `OmniRuntimeState.write_cache()`；`Cache Delete` / `OmniRuntimeState.clear_all()` 会释放 `PhysicsWorldCache`、rigid slots、`backend_resources["rigid_solver"]`，并清空 writeback delta。
- 帧语义 smoke 已覆盖：连续 60 帧、same-frame 重复求值、`2 -> 1` 跳回首帧、显式 reset、scope 删除刚体、静态体 transform dirty、运动学体 transform dirty、shape 参数 dirty、约束目标 dirty。测试会验证 generation/restart、Jolt resync、result stream 和 writeback delta。

**Phase 5 P0 已关闭：**

1. **非 Object 写回 contract 已落地到 PoseBone。** SpringBone VRM 通过通用 `bone_transform` 写回指令和 `physicsWorld.writeback -> PoseBone.matrix_basis` 写回，不在 solver step 中直接写 bpy。`Cache Delete` / `OmniRuntimeState.clear_all()` 会释放 world、slot 和 writeback cleanup，并把已写过的 PoseBone matrix_basis 复位。
2. **第一条非 Jolt solver vertical slice 已落地。** `physicsWorld/spring_vrm/` 已进入 `world.solver_slots`，读取 `world.frame_context` 与 `world.collider_snapshot`，调用 C++ native step，发布通用 `bone_transform` 写回指令和 `spring_vrm_stats`，并由统一 writeback 消费。后台测试覆盖 native step、same-frame、spec prune、runtime cache lifecycle、sphere / capsule / plane / box collider 投影和 group mask 过滤。
3. **当前 Jolt 能力不是 Phase 5 退出阻塞项。** Jolt 已作为刚体 backend 验证 world owner、native resource、result stream、Object delta writeback 和 runtime cache lifecycle；contact/query/lambda 等能力应进入后续 Jolt capability 阶段。

**不是 Phase 5 退出阻塞项，可放到 Jolt 后续能力阶段：**

- contact listener / sensor event / query API。
- constraint lambda、breakable policy、hinge/slider current value。
- advanced shape、compound、mesh static collider、convex hull。
- Jolt material、inertia override、COM offset、shape cook cache。
- cloth 直接读取 rigid body contact 或 rigid broadphase。

**是否可以开始其它 solver 重写：**

Phase 5 的 world-aware vertical slice 已可作为迁移样板。后续推荐顺序：

1. **继续收窄 SpringBone VRM 的 native context 双调用模型。** Python slot 侧已先落 `native_context` façade，常驻 chain topology signature 和 numpy buffers，并验证连续帧复用、stale slot dispose、stats/debug 摘要。下一步是把 façade 后面的 35 参数单次调用替换为 C++ handle：static arrays / dynamic arrays / result readback 分层，减少每帧 pack/unpack。
2. **再做 MC2 MeshCloth / BoneCloth 的最小 world-aware slice。** 它们更能验证 native resident state、mesh delta 写回和大数组 result/writeback，但改动面更大。
3. **最后做跨 solver 交互。** 例如 cloth 读取 rigid collider、spring bone 发布/消费动态 collider，应走显式 exchange/result channel，不让 solver 互读私有 slot。

新迁移 solver 只保留 C++ / native 计算路径。Python 层负责 spec、slot 生命周期、buffer 打包、result stream、writeback plan 和调试可视化，不再维护 Python / C++ 两套运行时 solver，也不再按 backend 拆两套公开节点。

### Phase 6：稳定门槛

开始迁移旧 solver 前，至少需要通过这些门槛：

- debug 节点能稳定输出 world snapshot。
- same frame、连续帧、跳帧、倒放、reset 行为明确。
- Cache Read / Begin / Commit / Cache Write 的 replace / mutate 行为稳定。
- Cache Delete / clear runtime cache 能释放 world、slot 和 backend resources。
- object scope 改变会触发 generation / restart。
- 刚体 domain 的 specs 不泄漏 Jolt handle。

### Phase 7：重写已有 solver

稳定后再重写已有 solver。这里的“迁移”不是兼容旧节点黑箱，而是为每个 domain 建立新的 world-aware code block：

- SpringBone VRM 第一条落地，使用 `physicsWorld/spring_vrm/` 新 spec/result/slot/writeback 链路。
- MC2 MeshCloth / BoneCloth 第二条，复用 native resident state 经验，但重写 world slot、result stream 和 mesh/PoseBone writeback。
- frame/restart 逻辑统一读取 `world.frame_context`，solver 内不再自有跳帧策略。
- per-node owner 不进入新路径；所有 runtime state 归属 `world.solver_slots`。
- solver 数值计算统一落在 native/C++ 侧；Python 运行时不再保留第二套算法实现。
- 通用数学、buffer、id/hash、PoseBone writeback 和 collider array 打包 helper 抽到 `physicsWorld/utils/`，避免继续寄生在旧 solver 包装层。

旧节点不作为统一物理世界的兼容目标。迁移时可以直接收敛到 world-aware 路径；需要保留的旧入口必须被标记为未迁移模块，不能影响新 contract。旧实现删除前必须有审查清单，至少覆盖 direct bpy write、旧 cache owner、scene-wide scan、native lifecycle、writeback side effects。

### Phase 8：跨 solver 交互

在统一 world 基础上逐步支持：

- cloth 读取 rigid body collider。
- rigid body 读取 animated bone collider。
- spring bone 读取 rigid body collider。
- mesh cloth 之间的互碰。
- self collision 与外部 collision 的公共 broadphase。

这一步必须谨慎，不要在第一版把 world 做成大而全的调度器。

## 推荐第一版 API 草图

```python
class PhysicsWorldCache:
    kind = "hotools.physics_world"
    schema = 1

    def __init__(self):
        self.frame_context = {}
        self.object_scope_key = None
        self.collider_snapshot = {"frame": None, "colliders": []}
        self.previous_collider_snapshot = None
        self.solver_slots = {}
        self.implicit_objects = []
        self.exchange = {}
        self.result_streams = {}
        self.runtime_caches = {}
        self.backend_resources = {}
        self.generation = 0
        self.replace_required = True
        self.valid = True

    def ensure_solver_slot(self, slot_id, kind):
        ...

    def runtime_cache(self, name):
        ...

    def append_implicit_object(self, item=None, tag=None, producer="unknown", stable_id="", signature="", enabled=True, schema=1, **payload):
        ...

    def iter_implicit_objects(self, tag=None, producer=None, enabled=True):
        ...

    def implicit_object_counts(self):
        ...

    def publish_exchange(self, item=None, channel=None, producer="unknown", scope="frame", **payload):
        ...

    def consume_exchange(self, channel=None, producer=None, scope=None):
        ...

    def publish_result(self, item=None, channel=None, solver="unknown", **payload):
        ...

    def consume_results(self, channel=None, solver=None, frame=None, generation=None):
        ...

    def clear_results(self, channel=None, solver=None):
        ...

    def omni_cache_dispose(self, reason):
        ...

    def omni_cache_debug_snapshot(self):
        ...
```

```python
def physicsWorldBegin(cache_state, scene, object_scope, reset=False, time_scale=1.0, substeps=1):
    world = cache_state if isinstance(cache_state, PhysicsWorldCache) else PhysicsWorldCache()
    world.begin_frame(scene, object_scope, reset=reset, time_scale=time_scale, substeps=substeps)
    return world, world.frame, world.collider_count, world.restart_required
```

```python
def physicsWorldCommit(world):
    if world is None:
        return _OmniCache.replace(None), world, 0
    cache_value = _OmniCache.replace(world) if world.replace_required else _OmniCache.mutate(world)
    return cache_value, world, len(world.solver_slots)
```

## 关键风险

### world owner 变成巨型上帝对象

避免方式：

- world 只管公共上下文、object scope、collider snapshot、slot 生命周期。
- solver 业务状态仍在 solver slot 内。
- solver 参数、拓扑、writeback 不上移到 world。

### object scope 不完整导致碰撞缺失

这是显式输入的代价。需要通过节点输出和 debug snapshot 让用户看到：

- object count
- collider source count
- collider count
- skipped hidden count
- invalid object count

### 同一个 world 被分叉 mutation

第一版文档和节点描述必须明确：world 链路应线性串联，不支持并行分叉后合并。

### 旧节点收敛

统一物理世界不再为旧节点接法保留兼容层。旧节点可以暂时作为未迁移模块存在，但新刚体世界节点、result stream、exchange 和 writeback contract 不应为了旧接法增加双路径。

### Blender depsgraph 开销不会完全消失

object scope 限制的是 OmniNode 自己的扫描和打包范围。只要 solver 写回 PoseBone 或 mesh delta，Blender 仍可能重算依赖图和视图。

## 最终建议

第一版不要做复杂 participant schema。短期仍可读取现有 `PhysicsTools` 属性作为 legacy storage，但物理语义的权威来源应逐步迁到各 solver 子模块的 capability 声明。

推荐核心口径：

```text
用 object scope 限定物理世界能感知的对象。
用 solver capability 解释这些对象的碰撞、pin、自碰撞、组和 solver 参数语义。
用 PhysicsWorldCache 统一 frame/collider/exchange/resource/slot 生命周期。
用 solver slot 保持各解算器自己的拓扑、参数、状态和写回逻辑。
用 solver 子模块持有 names、capabilities、declaration、nodes、debug draw modes 和 backend adapter。
用 physicsWorld registry 装载/卸载 solver 子模块，并汇总属性注册、debug 绘制模式和公开通道。
用 Physics World Commit 把同一个 world owner 提交回 runtime cache。
```

这样可以在不破坏 OmniNode runtime cache 架构的前提下，把物理系统从”多个独立 cache 小世界”推进到”一个显式物理世界，多 solver 协作”的模型。

---

## 附录：实施期间的变更记录

### PhysicsTools 文件重组

本模块原本所有文件都以 `collision` 开头，随着刚体/约束属性和统一面板的加入，文件名已与实际职责不符，按以下规则重组：

| 旧文件名 | 新文件名 | 说明 |
|---|---|---|
| `collisionProperty.py` | `physicsProperty.py` | 包含刚体/约束 PropertyGroup，名字已不止碰撞 |
| `collisionPanel.py` | 内容并入 `physicsPanel.py` | 旧面板类全部删除，draw 工具函数内联 |
| `collisionOperators.py` | `physicsOperators.py` | 未来刚体操作器也会加入 |
| `collisionUtils.py` | `physicsUtils.py` | 碰撞组工具会被刚体复用 |
| `collisionBasePose.py` | `meshClothBasePose.py` | 内容专属 MC2 简单布料，名字更准确 |
| `collisionPreview.py` | 保持不变 | 碰撞预览叠加层，名字准确 |

新增文件：

- `physicsPanel.py` — 统一物理属性面板（参考 Blender 内置物理布局：开关网格 + 子面板）

### 统一物理面板结构

```text
OBJECT 上下文（Object Properties）
  PT_Hotools_PhysicsPanel (“HoTools 物理”)
    PT_Hotools_Physics_ObjectCollision  “简单碰撞”  — enabled 时展开
    PT_Hotools_Physics_MeshCollision    “简单布料”  — enabled 时展开（仅 MESH）
    PT_Hotools_Physics_RigidBody        “刚体”     — enabled 时展开
    PT_Hotools_Physics_RigidConstraint  “刚体约束” — enabled 时展开（仅 EMPTY）

BONE 上下文（Bone Properties，Pose 模式）
  PT_Hotools_Bone_PhysicsPanel (“HoTools 物理”)  ← 原 ArmaturePanel 操作也合并至此
    PT_Hotools_Bone_CollisionSubPanel   “骨骼碰撞” — collision_type≠NONE 时展开
```

### 物理类型 UI 命名约定

| Python 属性名 | 旧 UI 名称 | 新 UI 名称 | 说明 |
|---|---|---|---|
| `hotools_object_collision` | 被动碰撞 | **简单碰撞** | “被动”暗示不能移动，实际可被动画驱动；改名更准确描述”一整块固体碰撞形状” |
| `hotools_mesh_collision` | 网格碰撞 | **简单布料** | 实质是 XPBD 布料模拟，不仅仅是碰撞 |
| `hotools_rigid_body` | 刚体 | 刚体 | 保持不变 |
| `hotools_rigid_constraint` | 刚体约束 | 刚体约束 | 保持不变 |
| `hotools_collision`（Bone） | 骨骼碰撞 | 骨骼碰撞 | 保持不变 |

当前实现暂沿用这些 Python 属性名作为内部 API。它们不是兼容承诺；后续如果统一物理世界需要更清晰的属性分层，可以做破坏性重命名。

### physicsObjectScope 参数名变更

`PhysicsObjectScope` 字段名随 UI 命名约定统一更新，同时新增刚体/约束开关：

| 旧字段名 | 新字段名 | 对应 UI |
|---|---|---|
| `include_object_colliders` | `include_passive_collision` | 简单碰撞 |
| `include_bone_colliders` | `include_bone_collision` | 骨骼碰撞 |
| `include_mesh_collision` | `include_mesh_collision`（不变） | 简单布料 |
| —（新增） | `include_rigid_body` | 刚体 |
| —（新增） | `include_rigid_constraint` | 刚体约束 |
| `include_hidden` | `include_hidden`（不变） | 包含隐藏 |
## 2026-07-07 追加：Solver 声明 registry

统一物理世界的 solver 声明已落到 `physicsWorld/declarations.py`，并进入 `PhysicsWorldCache.omni_cache_debug_snapshot()["solver_declarations"]`。

当前内置声明：`spring_vrm` 与 `rigid_jolt`。这是 Phase 5 为了快速验证 debug snapshot 和声明审查而采用的集中式过渡实现，不是最终边界。

硬约束：`writeback.solver_inline_writeback` 必须为 `False`；隐式对象不能伪装成 Blender owner 写回。

Phase 5 的声明样板缺口、runtime cache 生命周期 smoke、帧语义验收矩阵，以及 PoseBone 类非 Object 写回测试已关闭。剩余重点是 SpringBone native context 双调用模型、MC2 / BoneCloth 的 Mesh/PoseBone 写回样板，以及后续 Jolt contact/query/lambda 能力边界。

## 2026-07-09 追加：Solver 子模块原子化方向

后续架构应把集中式 `physicsWorld/names.py` / `physicsWorld/declarations.py` 拆回 solver 子模块：

- `physicsWorld/spring_vrm/names.py` 持有 SpringBone 的 id、slot kind、result channel、implicit object tag 和 debug draw mode id。
- `physicsWorld/spring_vrm/capabilities.py` 持有 SpringBone 消费或声明的能力表，例如 `bone_collision`。
- `physicsWorld/spring_vrm/declaration.py` 持有 SpringBone 的完整 solver 声明。
- `physicsWorld/spring_vrm/debug.py` 持有 SpringBone 自己的 debug snapshot 摘要和 debug draw mode 声明。
- `physicsWorld/registry.py` 或等价装载器只负责发现、注册、冲突检查和卸载这些子模块。

物理世界核心应像装载插件一样装载 solver：读取 names、capabilities、declaration、nodes、debug draw modes、property registration，并在插件 disable、Cache Delete 或 clear runtime cache 时按声明释放资源。这样 SpringBone、Rigid、MC2、BoneCloth 都可以成为边界清晰的小模块，后续新增 solver 不需要继续修改一个越来越大的全局声明表。

物理属性注册也应进入这个装载流程。外部 `PhysicsTools` 面板和操作器可以继续存在，但字段事实源应来自 solver capability；面板只负责呈现和编辑，不再定义 solver contract。
