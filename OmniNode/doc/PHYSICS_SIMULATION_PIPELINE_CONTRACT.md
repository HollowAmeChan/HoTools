# OmniNode 物理世界架构设计

本文是 OmniNode 物理世界的**权威架构设计文档**。它定义未来刚体、布料、弹簧骨、软体、流体和跨 solver 交互共同遵守的长期结构边界：阶段职责、数据通道、生命周期、声明协议和写回时序。它不是某个 backend 的接入计划，也不是现有节点的用户手册。

## 写作边界

- **应该写**：所有solver共同遵守的阶段职责、数据所有权、生命周期、声明协议、dirty/update语义、exchange/result/writeback和native context公共约束。
- **不应该写**：某个solver当前完成度、专属算法顺序/公式、fixture数量、产品输入限制、下一交付或迁移流水。
- **内容路由**：domain当前阶段写`PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`；MC2稳定产品/实现合同写`MC2_BLUEPRINT.md`；通用Bake、关键帧与外部几何缓存写`PHYSICS_BAKE_NODE_BLUEPRINT.md`；OmniNode编译/IR/cache机制写`../ARCHITECTURE.md`；历史只留Git。
- **准入原则**：一条规则只有被两个以上domain共享，或明确属于Physics World公共边界，才进入本文；solver私有规则留在该domain。

## 文档路由

- **本文（架构设计）**：物理世界的结构约定，是"应该怎么组织"的权威。回答——每个物理节点拥有什么数据、每帧/dirty/懒更新/重建的边界、solver 如何声明消费与产出、程序化实体与跨 solver 交互如何进入系统、写回与导出如何共用结果流、Python cache 与 native context 如何分工。
- **`PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`（当前实现状态）**：只记录各 domain 当前边界、未完成项和验收门槛，不保存逐次实施流水。
- **`MC2_BLUEPRINT.md`（MC2 实现蓝本）**：MC2当前产品决策、支持域、数据流、Python/C++职责、数值边界、debug、性能与扩展合同的稳定入口。
- **`PHYSICS_BAKE_NODE_BLUEPRINT.md`（通用 Bake 蓝图）**：Physics World结果到Bone/Object关键帧、Mesh外部缓存、跳帧清理、播放代理和Finalize的产品与实施合同。
- **`ARCHITECTURE.md`（OmniNode 框架）**：编译/执行/缓存/懒求值等框架机制，不含物理语义。

本文只写"结构应该怎样"；具体 solver 当前做到哪里见实现状态文档，历史过程由 Git 保存。

## 设计结论

OmniNode 物理系统应该从“一个高封装 solver 节点内部完成所有步骤”推进到“显式物理流程阶段”。第一版不要求用户手动连接所有阶段，但实现和文档必须按这些阶段拆清楚。

推荐完整流程：

```text
Cache Read
  -> Physics Object Scope
  -> Physics World Begin
  -> [Implicit Physics Objects]      ← 可选：注册节点把持久隐式对象写入 world.implicit_objects
  -> [Physics Entity / Spec Build]   ← 可选独立节点，或内联在 Solver 内
  -> Solver Step                     ← 含 Solver Prepare（内部，不是独立节点）
     (-> Cross Solver Publish)       ← 可选：solver 写 world.exchange
  -> Solver Step...                  ← 后续 solver 可消费上游 exchange
  -> Physics Writeback
  -> Physics World Commit
  -> Cache Write
```

节点图暴露给用户的最简链路应只有：`World Begin → Solver → Writeback → Commit`。其余阶段（Spec Build、Frame Prepare、Solver Prepare）是实现层拆分，不应强制用户在图上连线。

核心原则：

1. `PhysicsWorldCache` 管公共生命周期、frame context、scope、registry、exchange 和 solver slot，不成为巨型上帝对象。
2. solver 私有状态留在 solver slot 中，包含 topology、参数缓存、native context 和运行状态。
3. solver step 默认不写 Blender 数据，不写 runtime cache，不创建隐藏全局状态。
4. 写回是独立阶段。PoseBone、Object transform、mesh delta attribute、导出缓存和 bake 都消费同一类 result stream。
5. 程序化实体和 hack 行为可以存在，但必须产出可检查的 spec 或 exchange item，不能直接写入不可见 solver 内部状态。
6. 所有跨 solver 数据必须有类型、命名空间、生命周期和生产者信息。
7. 每个 solver 必须声明 consumes、produces、persistent state、update policy、writeback 和 export 能力。
8. Python 管 Blender 边界、cache 生命周期和 debug；C++ 管适合常驻的纯数据 context 和数值热路径。
9. 隐式写入会参与模拟的 solver 对象必须走 `world.implicit_objects`，不能写 `exchange`、不能直接写 solver slot、不能放进模块全局状态。
10. 消费 `PhysicsWorldCache.frame_context` 的公开 solver step 必须逐次进入自身时间判定；节点应声明 `always_run=True`，不能因 world/task对象身份跨帧复用而被值缓存跳过。

## 已固定的架构支柱

下列方向是**已确定的架构决策**，不再重新讨论；本文其余章节是它们的展开：

1. **框架 + 模块化 solver**：物理世界是一层薄框架，每个 solver 是 `physicsWorld/<domain>/` 下自带 names/capabilities/declaration/nodes/specs/solver 的可装卸模块。
2. **显式声明身份卡**：每个 solver 有一份声明（solver_id / slot_kind / consumes / produces / persistent_state / dirty_keys / writeback / update_policy），作为跨模块识别与迁移审查的单一事实源。
3. **通用世界状态输入**：frame / dt / reset / 跳帧 / 倒放 / object scope / collider snapshot 由 `Physics World Begin` 统一产出，solver 只消费不重算。
4. **通用写回**：solver 只发布写回指令到 result stream，真实 Blender 写入（Object delta / PoseBone / GN 属性）和 `update_tag` 由统一 writeback 执行，`solver_inline_writeback=False` 是硬约束。
5. **支持隐式表达**：authoring 对象通过 `world.implicit_objects`（跨帧、按 tag/stable_id/signature 收集）进入 solver，用户无需手连大批 socket。
6. **纯 C++ 后端**：迁移后的 solver 采用 C++ 单实现，不再维护平行 Python solver、不再按 backend 暴露双节点；旧实现只在删除前作审查/数值参考。
7. **移除全部旧 solver 的迁移计划**：新路径落地并验证后，旧 solver 一次性移除，不做长期兼容。
8. **跨 solver 交互规划**：多 solver 在同一 world owner 上通过 result stream / exchange 协作。
9. **物理属性由物理世界动态注册**：共享 component 或 solver capability 是字段、默认值、范围、RNA metadata 和 resolver 的单一事实源；`physicsWorld.registry` 按依赖注册/注销 Blender property，外部模块不得定义第二份 PropertyGroup 或 binding。
10. **通用力场归 Physics World 所有**：风只是未来通用力场的一种类型，不归 MC2 或任何单一 solver 私有；力场的收集、稳定身份、作用域和逐帧求值由公共物理世界组织，solver 只消费声明过的公共快照。

各 solver 对这些支柱的当前覆盖情况见实现状态文档。

## 阶段职责

### Cache Read

职责：

- 从 OmniNode runtime cache 读取上一轮成功提交的 world owner。
- 不解析物理语义。
- 不做重建判断。

边界：

- Cache Read 仍然是 GraphNode，因为它影响运行上下文、命名空间、commit/rollback 和 batch/group 隔离。
- 物理系统不应绕过 Cache Read 使用模块全局变量或 native 全局单例保存跨帧状态。

### Physics Object Scope

职责：

- 显式定义当前物理世界能感知哪些 Blender object。
- 决定是否包含简单碰撞、骨骼碰撞、简单布料、刚体、约束、隐藏对象等类别。
- 只表达扫描范围和依赖范围，不表达具体 solver 参数。

边界：

- object scope 不是 participant schema。
- object scope 不承诺限制 Blender depsgraph 求值范围，只限制 OmniNode 自己的枚举、打包和物理输入范围。

### Physics World Begin

职责：

- 校验或创建 `PhysicsWorldCache`。
- 更新 `PhysicsFrameContext`：frame、previous_frame、continuous、same_frame、restart_required、raw_dt、dt、time_scale、substeps、generation。`raw_dt` 是未缩放场景帧时长，`dt = raw_dt * time_scale`；需要在暂停帧移动坐标历史的 solver 不得从零 `dt` 反推帧时长。
- 计算 object scope key，检测 scope 变化。
- 构建公共 source / collider snapshot。
- 清理上一帧异常残留的 write lock。
- 根据 validity、reset、跳帧、倒放、scope 变化设置 `replace_required`。
- 准备 frame exchange registry：`world.clear_exchange()` 会在 Begin 清理上一轮帧级 scratch。

不负责：

- 不知道 MeshCloth、BoneCloth、SpringBone、RigidBody 的业务参数。
- 不执行 solver prepare 或 solver step。
- 不写 Blender。
- 不提交 runtime cache。
- 不直接导入或点名具体 solver 域。需要从 scope 派生 solver spec 时，只能通过 `physicsWorld/registry.py` 调用已装载 solver module 声明的 hook；solver declaration 汇总也由 registry descriptor 提供，公共层只保留兼容导出。

### 统一时间合同

Physics World 是节点图内唯一的基础时间生产者。Blender 输出设置决定未缩放的真实帧时长：

```text
scene_fps = Scene.render.fps / Scene.render.fps_base
frame_context.raw_dt = 1 / scene_fps
frame_context.dt = frame_context.raw_dt * frame_context.time_scale
```

`raw_dt` 和 `dt` 的单位都是秒。`fps_base` 必须参与计算，因此 29.97/59.94 等非整数输出帧率不能退化为整数 fps。场景帧率无效或不可读取时由 Physics World 明确报错或采用公共层定义的降级；solver 不得各自选择 fallback。

所有 solver 共同遵守：

- `frame_context.raw_dt` 是 Blender 当前输出设置对应的未缩放帧时长，只有 Physics World Begin 可以从 Scene 生产它。
- `frame_context.dt` 是应用世界级 `time_scale` 后的统一基础步长。Rigid、SpringBone、MC2 和未来 solver 都必须从同一个 world owner 消费该值，不得自行读取 `Scene.render`、重新计算 fps，或用固定 `1/24`、`1/30`、`1/60` 替代有效 world 时间。
- solver 可以保留局部 `time_scale` 作为产品调参，但它只能是统一基础时间之上的乘数：`solver_dt = frame_context.dt * solver_time_scale`。默认值必须为 1；局部倍率不得反向改写 `frame_context`，也不得成为第二个场景时间源。
- 固定频率 scheduler、substeps、iterations 和 catch-up 上限只决定怎样离散、累计或限制 `solver_dt`，不改变时间来源。它们不得隐式假设 Blender 是 60 fps。
- `frame_context.time_scale == 0` 或 `frame_context.dt == 0` 表示统一暂停。solver 可以同步参数、拓扑、动画输入、命令和只读结果，但不得推进数值时间；不能以 fallback dt 偷跑一步。
- `same_frame=True` 时不得再次累计时间或再次执行 backend step。重复求值只能复用/重发同帧结果，或消费明确允许的同帧命令。
- 跳帧、倒放、reset 或 scope restart 走 `restart_required` 冷启动合同，不把帧号差乘进 `dt` 追赶历史。需要 catch-up 的 realtime scheduler 只能消费自己已经从连续 world 帧累计的时间。
- 需要在暂停帧观察动画坐标变化的 solver，可以用 `raw_dt` 维护输入历史或 debug 判定，但必须显式标明该数据不代表数值解算推进；不能从零 `dt` 反推一个私有帧时长。

允许的从属关系：

```text
Blender render fps/fps_base
  -> Physics World raw_dt
  -> world time_scale
  -> Physics World dt
  -> optional solver-local time_scale
  -> scheduler/substeps/native step
```

禁止的平行关系：

```text
Solver -> Scene.render fps
Solver -> hard-coded fallback dt
Solver-local time_scale -> rewrite world dt
```

时间合同的最低验收矩阵必须覆盖 24、30、60、`fps_base != 1`、世界倍率 0/非1、局部倍率 0/非1、same-frame 和 restart；测试应比较各 solver 实际提交给 backend/scheduler 的累计秒数，而不只检查 UI socket 值。

### Physics Entity / Spec Build

职责：

- 从 Blender 属性、节点参数、规则节点、程序化生成节点产生物理实体描述。
- 输出稳定、可 debug、可导出的 spec。
- 为隐式物理实体提供正式入口。

典型输入：

- Physics World component/solver 挂在 Object / Bone / Mesh 上的持久属性。
- 节点参数。
- 对象列表、骨链、集合、命名规则。
- 程序化生成规则。

典型输出：

```text
RigidBodySpec
RigidConstraintSpec
SpringChainSpec
MeshClothSpec
BoneClothSpec
GeneratedConstraintSpec
TemporaryColliderSpec
ImplicitPhysicsObjectSpec
```

必须包含：

- `source_id`：实体来源，例如 object pointer、bone name、generator node id。
- `stable_id`：可跨帧匹配的 id。
- `kind`：公开物理语义，不暴露 backend handle。
- `lifetime`：persistent、frame、until_dirty、until_restart。
- `producer`：生成者，用于 debug 和冲突定位。

程序化实体示例：

```text
批量生成刚体约束:
  Constraint Generator -> list[RigidConstraintSpec]

给竖向刚体自动加横向连接:
  Rule-based Constraint Generator -> GeneratedConstraintSpec

上一个 solver 创建临时碰撞代理:
  Solver Publish -> TemporaryColliderSpec / exchange item
```

边界：

- 允许 hack，但 hack 结果必须实体化为 spec 或 exchange item。
- 不允许直接把生成物塞进另一个 solver 的私有 dict。
- spec 不保存 Jolt BodyID、ConstraintID、MC2 handle 等 backend 内部概念。

### Physics Frame Prepare

**定位说明：** Frame Prepare 是一个内部实现概念，不是必须独立存在的用户节点。它的职责通常内联在 Physics World Begin（公共部分）或 Solver Prepare（solver 私有部分）里。只有当多个 solver 共用同一份昂贵输入转换结果（例如相同 backend 的 collider arrays）时，才值得把这层逻辑显式化为可缓存的独立步骤。

职责：

- 汇总本帧 frame input。
- 把公共 collider snapshot、object transforms、armature pose、mesh state 等整理成 solver 可消费的输入视图。
- 维护公共 runtime arrays cache，例如不同 backend 共用的 collider arrays（lazy 生成，key = `collider_arrays:{backend_id}`）。

边界：

- Frame Prepare 可以缓存本帧临时数组，但默认帧末丢弃。
- 如果某个数组跨帧复用且重建昂贵，应放进 world runtime cache 或 solver slot，并声明 dirty policy。
- **不应把 Frame Prepare 单独做成节点强加给用户**；用户只应感知 Scope、World Begin、Solver、Writeback、Commit 这几个语义清晰的节点。Frame Prepare 是实现细节，应内聚在 World Begin 或 solver 内部。

### 通用力场（未来兼容区）

通用力场是 Physics World 的未来公共输入域，不是某个 solver 的内置特效。`wind` 只是其中一种 `kind`；后续还可以扩展其他方向场、径向场或程序化场，而不要求各 solver 各自维护一套 Blender 扫描、对象身份和生命周期。

已冻结边界：

- 持久 authoring 数据应先进入 Physics World 管理的隐式对象或正式 spec；逐帧求值结果再由公共 Frame Prepare 整理成普通数值快照。
- 公共层负责 stable identity、kind、scope、producer、lifetime、变换与参数快照；具体 channel、schema 和采样布局等到通用力场 vertical slice 落地时再冻结，本文当前不提前承诺 ABI。
- solver 必须在 declaration/capability 中显式声明可消费的力场类型，并只把公共快照转换为自己的 backend 输入；不得扫描场景寻找私有 wind 对象，不得把 live Blender 对象或 backend handle 塞进 native context。
- 力场 authoring/topology/scope 变化与逐帧数值变化必须分开定义 dirty/update 频率，不能把每帧变化误判为 solver topology rebuild。
- 在通用力场域落地前，solver 中已有的 `wind_*` 等字段只属于未来兼容参数面，不代表存在力场输入、采样、native 消费或已验收数值能力。

### Solver Prepare

职责：

- 为 solver 获取或创建 solver slot。
- 检查 topology/config/spec/native context 是否匹配。
- 根据 dirty policy 同步静态和动态输入。
- 决定冷启动、热更新、懒更新或完全跳过。

典型内容：

```text
slot = world.ensure_solver_slot(slot_id, kind)
slot.data["spec_key"]
slot.data["topology_key"]
slot.data["config_key"]
slot.data["native_context"]
slot.data["writeback_plan"]
slot.data["frame_state"]
```

不负责：

- 不写 Blender。
- 不提交 runtime cache。
- 不扫描整个 scene，除非该扫描已经通过 object scope 明确限制。

### Solver Step

职责：

- 推进模拟状态。
- 消费 frame input、spec、solver state、exchange input。
- 产生 world result stream。

默认约束：

- 不直接写 PoseBone、Object transform、mesh attribute。
- 不直接调用 Cache Write。
- 不创建不可清理的 native 全局状态。
- 一个solver step可以一次接收多个规范化task；公开step粒度不要求与对象、component或native context一一对应。具体component到task/spec的映射由domain声明并在专项验收中冻结。
- 聚合多task时，必须先完成全部只读prepare和校验，再取得world写权限；持久状态仍由稳定task slot/context分别拥有，最后通过一次result transaction发布。任一prepare失败不得留下部分slot更新或部分结果。
- 同一solver内需要跨task约束时，solver必须先同步全部参与slot，再按substep锁步推进；跨task临时聚合资源放入`world.backend_resources`并遵循dispose协议。不得在Python中逐对象完成Post后再两两补碰撞，也不得把公开step退化为component/object逐个调用。

当前开发约束：

- 统一物理世界内的新 solver 不保留 legacy inline writeback。
- 不为旧资产或旧节点 socket / payload 格式保留兼容层；破坏性调整必须在本文档记录。

### Cross Solver Publish / Consume

职责：

- 允许 solver 之间交换临时物理数据。
- 为跨 solver hack 提供可见、可清理、可 debug 的正式通道。

推荐结构：

```python
exchange_item = {
    "channel": "dynamic_bone_colliders",
    "producer": "spring_vrm",
    "scope": "frame",
    # source_id：当前帧的来源标识，可用于 debug/log
    "source_id": "armature:HairRoot:Hair_03",
    # stable_id：跨帧稳定匹配 id，必须同时包含 obj_ptr + data_ptr + name
    # 不能只用 obj.as_pointer()，Blender 删除对象后会释放地址可被新对象复用
    "stable_id": "spring_vrm:{arm_ptr}:{arm_data_ptr}:{bone_name}",
    "payload": {...},
}
```

**stable_id 构造规则（必须遵守）：**

所有需要跨帧匹配的 ID（exchange item 的 `stable_id`、solver slot 的 `slot_id`、spec 的 `stable_id`）都必须遵循：

```python
# 正确：同时包含对象指针和数据指针
stable_id = f"spring_vrm:{int(arm.as_pointer())}:{int(arm.data.as_pointer())}:{bone_name}"

# 错误：只用对象指针
stable_id = f"spring_vrm:{int(arm.as_pointer())}:{bone_name}"

# 错误：只用名字（不同场景可能重名，link 导入等情况更复杂）
stable_id = f"spring_vrm:{arm.name_full}:{bone_name}"
```

`arm.data.as_pointer()` 的作用：感知骨架数据被替换（例如用户换了 Armature 数据块），此时对象指针不变但数据变了，如果没有 data_ptr，会命中旧 slot 而不触发重建。

常见 channel：

```text
dynamic_bone_colliders
temporary_constraints
attachment_points
rigid_body_commands
force_fields
surface_samples
cloth_proxy_colliders
debug_markers
```

生命周期：

- `frame`：本帧结束清理。
- `until_next_begin`：下一次 `Physics World Begin` 清理。
- `persistent_slot`：进入 solver slot，由 producer 负责 dirty 和 dispose。
- `exportable`：可被导出缓存消费。

规则：

- exchange item 必须带 producer 和 channel。
- consumer 必须声明自己消费哪些 channel。
- 不允许 consumer 依赖 producer 的私有 slot 结构。
- 如需跨帧存在，必须升级为 spec 或 slot state。
- 当前最小 API：`world.publish_exchange(...)`、`world.consume_exchange(channel)`、`world.clear_exchange()`、`world.exchange_counts()`。
- `consume_exchange` 是非破坏性读取；需要避免重复消费时，consumer 在 item 上写入自己的私有 `_consumed_by_*` 标记。

### 隐式物理对象 / Implicit Objects

`world.implicit_objects` 是统一物理世界里的“隐式物理对象”registry。它用于表达那些由注册节点、规则节点或批量生成节点写入世界、会参与后续物理模拟、但不应该被当作每帧事件的数据。

它和其它三条通道的边界如下：

| 通道 | 用途 | 生命周期 | 允许谁写 | 允许谁读 |
|---|---|---|---|---|
| `implicit_objects` | 持久懒更新的隐式物理对象，例如批量生成约束、solver 参数对象、运行时覆写 | 当前根树兼容 runtime namespace 内跨帧；Begin 不清空，成功重编译时按 manifest 对账 | 属性/注册/生成节点 | 声明消费该 tag 的 solver |
| `exchange` | 当前图执行内的命令、事件、临时共享数据，例如 force/impulse、临时碰撞代理 | frame / until_next_begin | solver 或命令节点 | 下游声明消费 channel 的 solver |
| `result_streams` | solver 输出的本帧纯结果快照，例如 transform、pose matrix、contact event | 当前图执行 | solver | writeback、debug、export、下游 solver |
| `solver_slots` | solver 私有状态和 native context | 跨帧，归属单个 solver | 所属 solver | 只能所属 solver 读写，debug 只读摘要 |

`implicit_objects` 的最小 entry 结构：

```python
{
    "tag": "rigid.generated_constraint",
    "stable_id": "rigid.generated_constraint:{source_or_target_identity}",
    "schema": 1,
    "payload": {...},               # 纯对象/spec 片段；可含 Blender 引用，但不得含 native handle
    "signature": "stable_hash",
    "version": 3,
    "dirty": False,
    "enabled": True,
    "producer": "physicsRigidGeneratedConstraintRegister",
    "source_id": "node-or-rule-id",
    "updated_frame": 12,
    "last_seen_frame": 14,
    "generation": 5,
    "metadata": {...},
}
```

规则：

- `tag` 是对象类型标记，必须使用名称常量而不是各写一份裸字符串。例如 `RIGID_GENERATED_CONSTRAINT_OBJECT_TAG = "rigid.generated_constraint"`。
- 名称常量的组织方式已分层：跨 solver 通用的 channel / collider ABI 常量仍集中在 `physicsWorld/names.py`；各 solver 自有的 tag / slot_kind / solver_id 等权威定义已拆回各自子模块的 `names.py`（`spring_vrm/names.py`、`rigid/names.py`）。中央 `physicsWorld/names.py` 只保留惰性重导出兼容，避免跨 solver 识别名称错位。
- `stable_id` 是 registry 内部去重/替换用的稳定对象 ID，不作为用户 socket 暴露。相同 tag + stable_id 表示更新同一个隐式对象。
- `signature` 必须覆盖影响 solver spec / topology / config / param 的输入。只有 `signature` 或 `enabled` 变化时递增 `version`。
- `dirty=True` 只表示该 entry 相对上一轮写入发生了设置变化，不表示本帧必须 step。
- `enabled=False` 是禁用该隐式对象，不是 no-op。在当前已编译图持续运行期间，未被再次写入的旧 entry 仍然保留；需要不重编译就立即关闭时，应显式写 disabled entry，或执行 Cache Delete / clear runtime cache。删除、静音、改接或改名注册节点会改变 Cache Write owner 的上游结构合同，成功重编译时对应 namespace 会被定向释放，旧 entry 不会进入新图，因此不再额外实现 source lease / mark-and-sweep。
- `Physics World Begin` 不清空 `implicit_objects`。world owner 被 replace 时应浅拷贝对象；solver slot 和 native state 仍按 generation 冷启动。
- 注册节点必须接收并返回同一个 `PhysicsWorldCache`，只调用 `world.append_implicit_object()`，不得直接创建 solver slot、不得写 `world.exchange`、不得写 Blender。
- 注册节点默认不标记 `always_run=True`。即使因节点图依赖被执行，语义上也只是按 stable_id/signature 更新 registry；输入未变时不产生新的 solver 重建。
- 成功重编译是统一物理世界的兼容性边界：框架按 namespace manifest 比较 Cache producer 与 owner 上游结构。合同相同则保留 world，由 solver 的 config/param/static fingerprint 决定热更新或 slot 重建；合同变化、动态 cache key 或缺少 manifest 时释放对应 namespace，active 注册节点在新图第一次运行时重新填充 registry。编译缓存命中和编译失败都不清理。
- solver 在 Prepare 阶段读取自己声明的 tag，按 `version/signature` 做懒重建或参数热更新。
- 直接任务 socket 与隐式对象 registry 是两种不同产品合同。需要在一个模拟步内显式组合、随图输入立即增删的组件可直接输入 task list；需要跨帧持久存在、由注册/规则节点懒更新的程序化实体才进入 `implicit_objects`。同一类输入不得同时保留两条生产路径。
- 如果多个 writer 写同一个 tag + stable_id，线性 world 链路中后写者覆盖前写者。多个对象天然 append 到同一个 tag 下，solver 直接 collect all。
- `implicit_objects` 不用于表达一次性命令。force、impulse、activate、sensor event、contact event 等仍走 `exchange` 或 `result_streams`。

选择隐式对象合同的 domain 按以下模式组织：

```text
<Domain>属性节点
  输入：authoring data / rules / targets
  输出：可注册的属性对象

<Domain>对象注册节点
  输入：world, 属性对象, enabled
  输出：world, item_count, dirty_count, version
  行为：append/update world.implicit_objects[tag]

<Domain> Solver Step
  输入：world, enabled, solver runtime params
  行为：读取声明的 implicit object tag，注册/更新 solver slot，调用 native，发布 result stream
```

示例（刚体生成约束隐式对象链路）：

```text
Physics World Begin
  -> 刚体生成约束属性                # <Domain>属性节点
  -> 刚体生成约束注册                # <Domain>对象注册节点，append world.implicit_objects[tag]
  -> 刚体模拟步                      # 读取 tag=RIGID_GENERATED_CONSTRAINT_OBJECT_TAG 的全部隐式对象
  -> Physics Writeback
  -> Physics World Commit
```

> 各 solver 隐式对象链路的当前覆盖情况见实现状态文档。

`rigid_body_commands` 建议 payload：

```python
{
    "channel": "rigid_body_commands",
    "producer": "node_id",
    "scope": "frame",
    "target_slot_id": "rigid:{obj_ptr}:{data_ptr}",
    "command": "set_velocity | add_force | add_impulse | set_gravity_factor | set_material_response | set_motion_quality | set_active",
    "linear_velocity": (0.0, 0.0, 0.0),
    "angular_velocity": (0.0, 0.0, 0.0),
    "force": (0.0, 0.0, 0.0),
    "torque": (0.0, 0.0, 0.0),
    "impulse": (0.0, 0.0, 0.0),
    "angular_impulse": (0.0, 0.0, 0.0),
}
```

命令通道的架构约束：

- 命令由 solver 翻译到 backend 的 slot_id API，命令节点不得直接保存或读取 backend native handle。
- 一次性命令（impulse / force）必须防重复消费：consumer 在 item 上写私有 `_consumed_by_*` 标记，同一 generation/frame 内不重复应用。
- **单帧命令走 `exchange`，持久配置走 `implicit_objects`**。二者的区分是架构性的：impulse / force / activate 这类单帧事件属于 `rigid_body_commands` exchange；而刚体世界级设置（重力、容量上限等）持续生效直到被同 stable_id 的 disabled entry 或新签名覆盖，属于持久隐式对象，不走命令通道。容量类字段变化触发 backend 重建，重力类字段变化只触发参数刷新——对应下文 config_key 与 param_key 的区分。

### Physics Writeback / Export / Preview

职责：

- 消费 solver result stream。
- 根据模式写 Blender、导出缓存、bake 或仅预览。

写回目标：

```text
Object transform
PoseBone matrix_basis
mesh delta attribute
shape key
modifier parameter
debug draw store
export cache stream
```

关键边界：

- solver result 与 Blender writeback plan 分离。
- writeback plan 可以由 solver prepare 生成，但执行写回应由统一 writeback 阶段完成。
- 导出缓存应消费同一 result stream，不能重新从 solver 私有状态里猜。

solver declaration 的 `export` 必须区分 channel 生命周期与所有权：

| 字段 | 语义 | registry 规则 |
|---|---|---|
| `result_channels` | 当前实际发布、solver/domain 独占 | channel 名全局唯一 |
| `shared_result_channels` | 当前实际发布、Physics World 共享写回 | 允许多个 solver，共享 schema |
| `planned_result_channels` | 尚未发布、未来独占 | 只展示，不进入 active 冲突校验 |
| `planned_shared_result_channels` | 尚未发布、未来共享写回 | 只展示，不进入 active 冲突校验 |

`bone_transform` 与 `gn_attribute` 属于共享写回 channel，不应登记为 solver 独占
channel。domain 自有 stats、event、query channel 仍应登记为独占。框架 no-op 不得把
未来 channel 填入 active 字段，否则 declaration 会虚报运行能力。

共享 channel 只表示多个生产者使用同一 payload schema，不自动规定目标合成策略：

- `bone_transform` 按 result 发布时间顺序执行；同一 PoseBone 的后发布结果覆盖先发布
  结果。图作者负责避免让多个 solver 重复解算同一骨骼。
- `gn_attribute` 表示每个 Mesh 的单一最终 offset；其中间分量仍先经 `world.exchange`
  归并，最终 writer 冲突策略见下节。

#### 共享 GN 顶点 offset 契约

Geometry Nodes 写回只表示“目标 Mesh 在本帧的最终顶点 offset”，不是任意属性
总线，也不是 solver 私有输出槽。公开结构固定为：

```python
{
    "channel": "gn_attribute",
    "writeback_type": "mesh_vertex_offset",
    "offset_space": "OBJECT_LOCAL",
    "solver": "mc2",
    "slot_id": "稳定 task/slot id",
    "writer_id": "<solver>:<slot_id>",
    "object_ptr": 0,
    "object_data_ptr": 0,
    "target_key": "<object_ptr>:<object_data_ptr>",
    "vertex_count": 0,
    "local_offsets": "只读 float32[N,3] snapshot",
}
```

- 写回层只维护一个共享 `hotools_physics_offset` 点域 `FLOAT_VECTOR` 属性和一个
  topology-preserving 栈底 Geometry Nodes 后置修改器；完整 PC2 播放时只允许受管
  Mesh Cache modifier 位于其后覆盖显示。result 不允许指定 attribute name、modifier、
  blend mode 或 solver 私有槽名。
- offset 已经是对象局部空间最终值。writeback 不读取 base pose、不做 solver 混合，
  也不从 display/base position 二次推导结果。
- 同一 writer 在同帧重复发布采用 replace 语义，最后一个快照生效；同一目标出现
  多个 writer 是未完成归并的契约错误，目标清零并产生可观察 diagnostics。
- 多 solver 或多阶段的中间 offset、权重、优先级和分槽属于帧级 scratch data，必须
  先在 `world.exchange` 的 setup/domain 通道中归并；归并者最后只发布一个最终 result。
  `gn_attribute` result stream 本身不承担叠加器职责。
- 目标 Mesh 数据必须单用户，result 顶点数必须与目标拓扑完全一致；不自动截断、
  填充或复制 Mesh 数据。`hotools_physics_offset`、共享修改器和 node group 是 HoTools
  保留名：同名内容会被接管，类型/schema 不匹配时直接替换。无本帧结果、restart
  和 cache dispose 都会把曾写入目标归零，避免 stale offset。
- 通用 Bake 只从当前 frame/generation 的真实 `gn_attribute` target 集合取样；第一版
  工作缓存为每对象独立 PC2。`use_mesh_cache` 只控制末端 Mesh Cache modifier 显隐，
  与 payload 留存完全分离；清理、截断和删除由独立 Clear 节点按 manifest ownership 执行。
- 共享 GN 组是受管持久资源。原有 ensure 路径必须按当前 builder 自动生成的结构
  contract 判断代码版本差异，不能只信任整数 schema；显式完整检查由受管 refresh helper
  执行。插件 register 阶段不得扫描旧场景资源。刷新必须保持 modifier 指向稳定组、修复播放层顺序并显式 tag 使用对象。

result channel 的结构约定（以 transform + stats 双通道为例）：

- solver 向 `world.result_streams["<domain>_transform"]` 写每个模拟体的本帧结果，是纯快照 dict/tuple 数据（如 `frame`、`generation`、`slot_id`、`body_type`、`position`、`rotation_wxyz`、`linear_velocity`、`angular_velocity`、`active`、`sleeping`），不含 backend handle。
- solver 同时向 `world.result_streams["<domain>_solver_stats"]` 写本次调用统计（body/constraint 数、step_ms、dt、substeps、same_frame、各类 error count），供 debug/观察节点读取。
- contact/sensor 等事件输出写入声明过的 result channel，例如 rigid/Jolt 的 `rigid_contact_event` / `rigid_sensor_event`。事件只含稳定 slot id 与普通数值快照，不含 backend body handle；same-frame 重发上一真实 step 快照，不重新触发 native step。
- writeback、solver 自有 debug draw、read-state 节点只消费 result stream 或本 solver 的 slot debug 快照，不读 backend-private handle（如 Jolt adapter 内部字段）。
- 需要backend中间态的solver debug采用隐式请求：debug节点自动发现world内所属slot，只登记scope/过滤器。substep中间态在下一次真实推进后冻结；若某层观察的是scheduler前的新帧判定（例如Teleport阈值/触发），domain必须显式声明其producer阶段，并允许在zero-substep新帧冻结。same-frame和没有到达声明生产阶段的调用不得伪造新快照。
- 未登记请求时禁止执行中间态native readback和逐项viewport几何展开。持续显示由`always_run`调试节点逐帧重新登记一次性请求表达，不把调试成本永久塞进solver主循环。
- renderer只消费冻结的只读数组/普通值与真实result stream，禁止读取当前RNA或从最终输出反推约束、碰撞、teleport等backend过程；world dispose必须清除对应draw store。
- solver slot 不保存每帧 transform result；slot 只持有 spec、runtime sync 状态和 native 绑定状态。每帧结果只活在 result stream 里。
- 通用观察节点按 channel / solver 读取当前 frame + generation 的 result stream，用于调试 contact、constraint lambda、query 等输出。空间查询必须在 domain adapter 内把 backend handle 转成 stable slot id 后再发布，例如 rigid/Jolt 的 `rigid_query_result`。

模式：

```text
Apply
  写 Blender。

Preview Only
  只写 debug draw 或临时 viewport 数据。

Record Only
  不写 Blender，只记录导出缓存。

Apply + Record
  写 Blender，同时记录。

Disabled
  不写，solver state 是否推进由 solver policy 决定。
```

## 写回时序语义（必须在系统级统一选择）

这是全系统最重要的设计决策之一，直接影响所有跨 solver 场景的行为。

### 问题

当链路中有多个 solver，且下游 solver 需要感知上游 solver 的物理结果时，必须避免隐式 bpy 中间态。

**禁止模式：solver 内写回 bpy，下游读 bpy**

```text
SpringBone step → 立即写 PoseBone
  ↓ (bpy)
Cloth step 读到 SpringBone 已写回的骨骼状态
  ↓
链路末尾 Writeback（Cloth 自己再写）
```

- 缺点：同一骨架在一帧内发生"写 bpy → 读 bpy"循环，可能触发 Blender depsgraph 中间重算；无法做 Record Only；无法统一 writeback 统计。

**目标模式：solver 结果进入 `world.result_streams` / `world.exchange`，链路末尾统一写 bpy**

```text
SpringBone step → 写 world.result_streams["bone_transform"] 通用写回指令
  ↓ (world result stream / exchange，无 bpy 写)
Cloth step 读声明的 result / exchange channel（不读 bpy）
  ↓
Physics Writeback 统一写 PoseBone + mesh delta
```

- 优点：零 bpy 中间写；支持 Record Only；writeback 成本可统一统计。
- 代价：所有下游 solver 必须声明消费 result / exchange channel；首次迁移可以破坏旧接口。

### 系统约定

**统一物理世界只选目标模式。当前项目没有旧资产兼容要求，接口可以破坏性收敛到强契约。**

规则：
1. **solver step 不写 bpy**：结果写入 `world.result_streams`；跨 solver 命令、事件和临时共享数据写入 `world.exchange`。
2. **slot 不作为结果总线**：solver slot 只保存 spec、topology、native handle、dirty/runtime 状态。
3. **如果下游 solver 需要消费上游物理结果**，上游 solver 必须发布 result / exchange item；下游 solver 声明消费该 channel，不依赖 bpy 中间状态。
4. **`armature.update_tag()` 只能在 Physics Writeback 节点调用**，每个 armature 只调一次（汇总所有 solver 写完后），不能在 solver step 内调用。

### Physics World Commit

职责：

- 按 `world.replace_required` 生成 `_OmniCache.replace(world)` 或 `_OmniCache.mutate(world)`。
- 透传 world 用于 debug。
- 统计 solver slot、exchange、writeback、backend resource 状态。
- 透出 solver 自己注册的 debug 摘要和 debug draw mode；世界级可视化 debug 不定义或绘制 solver 私有调试语义。公共绘制工具只放在 `physicsWorld/utils/debug_draw.py`，具体采样和 draw store 归各 solver。

不负责：

- 不执行 solver。
- 不写 Blender。
- 不清理 solver 内部业务状态，除非 world 被 dispose。

### Cache Write

职责：

- 将 Commit 产生的 cache intent 交给 OmniRuntimeState。
- 成功 root run 后提交 pending。
- 失败时丢弃 pending。

边界：

- Cache Write 不理解物理语义。
- 资源释放依赖 owner 的 `omni_cache_dispose()`。

## 数据分类

### Authoring Data

用户可编辑数据：

- Blender custom properties。
- 节点参数。
- 骨链、对象列表、集合引用。
- 规则节点配置。

特点：

- 持久化在 `.blend` 或节点树中。
- 不能假设每帧稳定。
- 需要参与 dirty key 或 spec key。

### Blender Authoring 与 RNA 所有权

“Physics World 持有属性”不表示把 Blender `PropertyGroup` 实例塞进 `PhysicsWorldCache`。长期边界固定为四层：

```text
Blender ID 数据块
  保存稳定 RNA 路径和用户原始值
          |
          v
Physics World component / solver domain
  持有 capability schema、PropertyGroup class、binding 声明和注册生命周期
          |
          v
resolver / spec builder
  生成普通 profile/spec、签名和数组快照
          |
          v
PhysicsWorldCache / solver slot
  只持有归一化运行时数据，不跨帧保存 live PropertyGroup
```

当前稳定持久路径与语义 owner：

| 持久路径 | 语义 owner | 主要消费者 |
|---|---|---|
| `Bone.hotools_collision` | `physicsWorld.collision` 的 `bone_collision` capability | SpringBone、MC2 BoneCloth/BoneSpring、scope、UI/preview |
| `Object.hotools_object_collision` | `physicsWorld.collision` 的 `object_collision` capability | collider snapshot、SpringBone、MC2、UI/preview |
| `Object.hotools_mesh_collision` | `physicsWorld.mc2.setups.mesh_cloth` 的 `mesh_collision` capability | 简单布料面板、MC2 MeshCloth、BasePose、mesh delta；字段含enabled、BasePose、半径组、Pin与碰撞组 |
| `Object.hotools_rigid_body` | `physicsWorld.rigid` 的 `rigid_body` capability | Rigid/Jolt、scope、UI |
| `Object.hotools_rigid_constraint` | `physicsWorld.rigid` 的 `rigid_constraint` capability | Rigid/Jolt、scope、UI |
| `Scene.ho_*` 物理叠加层字段 | `physicsWorld.ui` | 面板、header、GPU preview |

所有权规则：

- 被多个 solver 消费、或在 World Begin/scope 阶段解析的语义进入共享 component，例如 Object/Bone collider 和碰撞组。
- 只影响单个 solver/setup 的拓扑、参数或后端同步策略的字段留在所属 domain。
- UI 展开、过滤和叠加层状态属于 `physicsWorld.ui`，不进入 solver capability 或 world generation。
- Operator 自身参数只服务单次命令，不进入持久 property registry。
- 显式 RNA 和隐式 override 必须进入同一个 resolver，生成同一种 profile/spec；solver 不得分别实现两套字段解释。
- 面板、preview、scope 和 solver 只能消费 capability，不得复制默认值、枚举、范围或字段表。

稳定存储契约：

- 目录和 Python module 可以改变，稳定 RNA owner/name 不随内部重构改名。
- 同一 `(bpy owner, property name)` 永远只有一个 binding；迁移时禁止同时注册旧 class 和新 class。
- PropertyGroup class 名、字段顺序、property factory、默认值、范围、enum identifier 和 pointer poll 由契约测试冻结。
- `.blend` 往返必须覆盖全部持久字段、bitmask、向量和 Object pointer。
- 如需重命名持久路径，必须设计独立的版本化 data migration，不能夹带在目录重构中。

注册生命周期：

```text
HoTools.register()
  -> physicsWorld.blender.register()
       -> collision component properties
       -> mc2 MeshCloth adapter properties
       -> rigid solver properties
       -> physics UI classes/state/preview
  -> OmniNode.register()                 # 仅节点功能开关启用时
```

- `physicsWorld.blender` 是物理 RNA/UI 的唯一根注册入口；物理属性不随 OmniNode 功能开关消失。
- `physicsWorld.blender_registry` 按 domain 保存 class/binding/dependency journal，注册失败只回滚当前 domain。
- 注册前检查 `(owner, name)` 冲突、重复 class、依赖缺失和同 domain 声明漂移。
- 按依赖顺序注册、逆序注销；有 dependents 的 component 不能提前释放。
- solver/component 在 Blender lifecycle 活跃时动态加入或移除，只影响自己的 domain。
- UI 与 solver 不决定全局注册顺序，也不直接注册共享 capability。

运行时禁止长期保存 `PropertyGroup`：resolver 必须把它转换为纯值 profile/spec、签名或数组。否则 RNA 注销、热修改或 class module 迁移会让 world cache 持有过期对象。

### Frame Input

当前帧从 Blender 读取的数据：

- Object matrix。
- PoseBone pose。
- Mesh evaluated state。
- 可见性。
- 当前 frame、fps、dt。

特点：

- 每帧可能变化。
- 通常不能跨帧保存为可信输入。
- 可以转成 arrays 供本帧 solver 消费。

### World Persistent State

`PhysicsWorldCache` 持有：

- frame context。
- object scope key。
- public snapshots。
- solver slot registry。
- backend resource registry。
- implicit object registry。
- exchange registry。
- debug snapshot。

特点：

- 通过 runtime cache 显式跨帧。
- 实现 `omni_cache_dispose()`。
- 不深拷贝，走资源 owner 零拷贝路径。

### Solver Private State

solver slot 持有：

- solver topology。
- config key。
- native context。
- particle/body/bone state。
- dirty flags。
- solver-local arrays。

特点：

- 只能由所属 solver 解释。
- 可被 debug snapshot 摘要展示。
- 不应被其他 solver 直接读取。

### Frame Scratch / Exchange Data

本帧临时数据：

- collider arrays。
- solver outputs。
- temporary constraints。
- force fields。
- debug markers。

特点：

- 默认帧末清理。
- 跨 solver 共享时必须走 exchange channel。
- 跨帧保存时必须升级到 world state 或 solver slot。
- 持久的 solver 对象和生成 spec 不属于 frame scratch，应进入 `world.implicit_objects`。

## Solver 声明协议

每个 solver 都需要一份声明。建议格式：

```text
Solver:
  id:
  domain:
  node:
  backend:

Consumes:
  authoring:
  frame_input:
  world:
  implicit_objects:
  exchange:

Produces:
  result_stream:
  exchange:
  debug:

Persistent State:
  slot_id:
  topology:
  config:
  native_context:
  frame_state:

Update Policy:
  implicit_object_policy:
  every_frame:
  dirty_only:
  lazy_on_access:
  restart_only:
  never_while_running:

Writeback:
  targets:
  plan_owner:
  supports_preview_only:
  supports_record_only:

Export:
  supported:
  result_format:
  limitations:

Failure:
  invalid_input:
  skipped_frame:
  failed_run:
  dispose:
```

`implicit_objects` 声明必须列出：

```text
implicit_objects:
  tag:
  tag_constant:
  schema:
  payload_contract:
  signature_fields:
  stable_id_fields:
  conflict_policy: replace_same_stable_id | collect_all | error
  disabled_policy:
```

### Update Policy 语义

`every_frame`：

- 每帧必须读取或刷新。
- 例如 object transform、pose matrix、dt。

`dirty_only`：

- 只有 key 或 tag 变化时刷新。
- 例如 topology、constraint table、static arrays。

`lazy_on_access`：

- 第一次被某个 solver 消费时生成。
- 例如 backend-specific collider arrays。

`restart_only`：

- 只在 reset、scope 变化、topology 变化或 world generation 变化时重建。
- 例如 native context、initial pose cache。

`never_while_running`：

- 运行中修改不立即生效，必须 reset 或重建。
- 需要在节点描述中明确。

## Dirty Tag 与 Key

所有 dirty 判断必须可解释。推荐分层：

```text
scope_key
  object 范围和 include flags。

spec_key
  authoring data 和生成实体列表。

topology_key
  骨链、mesh topology、body/constraint identity。
  变化触发：slot 重建 + native context 全量重传。

config_key
  影响 solver 静态结构但不影响拓扑的配置。
  例如：连接模式、碰撞组过滤、backend 版本。
  变化触发：slot 重建，native context 静态结构重传。

param_key（与 config_key 区分）
  影响每帧参数数组但不影响结构的运行参数。
  例如：stiffness/drag/gravity 数值、substeps、time_scale。
  变化触发：仅刷新对应 native context 参数数组，不重建 slot。
  如果 solver 支持 hot param update，params 可以每帧直接传入，不走 key 检测。

dynamic_key（可选）
  影响每帧动态同步的参数摘要。
  仅当需要确认动态数据来源是否变化时使用。

backend_key
  backend 版本、schema、native layout。
  变化触发：native context 重建。
```

**config_key 和 param_key 的关键区别：**

- config 变化 → slot 结构无效，需要重建（例如改了骨链连接模式，整个 solver 要冷启动）。
- param 变化 → slot 结构有效，只需刷新参数数组（例如调低 stiffness，不需要冷启动，直接下一帧生效）。
- 不区分这两个 key 会导致用户调参时触发不必要的冷启动，体验变差。

规则：

- key 应包含 Blender object pointer 和 data pointer，避免对象删除后指针复用。
- 使用 name 时要说明它是否只是显示名；稳定 id 不能只依赖 name。
- native context schema 变化必须进入 backend key。
- 修改 socket 参数名会改变节点 contract，不能作为 dirty key 的唯一来源。

## Native Context 分工

推荐模式：

```text
Python owner:
  生命周期
  runtime cache intent
  debug snapshot
  Blender RNA 读取
  writeback plan
  dispose 调度

C++ native context:
  static arrays（topology、constraint table、init pose）
  reusable dynamic buffers（per-frame 动态数据的预分配 buffer）
  solver state（particle positions、velocities、angular state）
  broadphase / backend world（Jolt PhysicsSystem 等）
  heavy conversion cache（collider arrays per backend）
  numeric kernels
```

收益点不在于把 Cache Read/Write 搬到 C++，而在于减少每帧重复：

- 拓扑数组重建（topology 不变时每帧白重建）。
- 约束表重建。
- Python list/dict 到 numpy 的打包。
- backend-specific collider arrays 转换。
- buffer 校验和多参数调用（当前 35 参数单次调用模型无法避免 per-call overhead）。
- 大量中间 matrix/vector 解包。

静态输入较大且每帧都必须判脏时，dirty producer应和native consumer共址：Python只提取Blender可连续读取的raw arrays，native context生成并持有分类指纹或revision。分类至少要能区分topology、geometry、surface/authoring与影响静态构建的config；无变化不得重建或分配静态派生数组。Python不得同时保留一套平行JSON签名、contract tuple或派生大数组作为第二真值来源。没有native context的空任务可以比较同样的短摘要，但不得因此重新引入大payload遍历。

### Native Context 生命周期协议

每个需要 C++ persistent context 的 solver 应遵循以下调用协议，不得合并成单一大函数：

```text
阶段 1：创建（topology dirty 或 generation 变化时）
  ctx = create_{solver}_context(schema_version, static_arrays)
    - 分配 C++ 内部结构
    - 上传 topology、constraint table、init pose 等静态数组
    - 返回 opaque handle（Python capsule）

阶段 2：静态参数更新（config dirty 时，不触发重建）
  update_{solver}_static(ctx, static_param_arrays)
    - 只更新参数数组（stiffness、radius 等）
    - 不重建 topology

阶段 3：每帧动态同步（每帧）
  update_{solver}_dynamic(ctx, animated_arrays, collider_arrays, scalar_params)
    - 上传当前帧的动画数据（骨骼矩阵、碰撞体变换等）
    - 不触发任何重建

阶段 4：step（每帧，在 dynamic sync 之后）
  step_{solver}(ctx, dt, substeps)
    - 推进模拟
    - 原地更新内部 solver state

阶段 5：结果读取（每帧，在 writeback 时）
  read_{solver}_results(ctx, output_arrays)
    - 将 C++ 内部结果写入 Python 预分配 buffer
    - 不返回新 Python 对象

阶段 6：调试读取（可选，每帧，在 debug draw / debug snapshot 需要时）
  read_{solver}_debug(ctx, debug_output_arrays)
    - 只读拷贝后端 context 中已经被 update/step 消费或产出的真实状态
    - 可包含用于绘制的语义化数组，例如 resolved collider、constraint anchor、current tail、hit radius、mask、pinned state
    - 不推进模拟、不重新解析 Blender 属性、不重新计算一套预览状态
    - 不暴露 native handle 或 C++ 内部对象，只返回纯数组/纯 dict 快照

阶段 7：释放（dispose 时）
  free_{solver}_context(ctx)
    - 按顺序释放：先 bodies/constraints/sub-resources，再 world/context 本体
    - 必须幂等
    - 不得引发 Python 异常（否则中断上层 dispose 链）
```

**关键约束：**

- 阶段 3（dynamic sync）和阶段 4（step）必须分开，不能合并成"传入参数同时 step"的单次调用，否则无法区分"动画数据更新"和"模拟推进"的性能开销。
- `read_results` 写入调用方预分配的 Python buffer（`np.ndarray`），不创建新 numpy 数组。
- C++ context 不得是隐藏全局单例。
- C++ context 必须由 Python owner 持有并可释放（存入 solver slot 的 native_context 字段，slot dispose 时触发 free）。
- dispose 必须幂等（多次调用不崩溃）。
- debug snapshot 只输出数量统计和状态摘要，不直接暴露 C++ 内部对象。
- solver 自有 debug draw 必须使用 result stream 或 `read_{solver}_debug()` 读回的后端真实快照。不得在 Python 绘制层根据 Blender 当前对象、属性面板或 result matrix 重新推导一套可能与后端不一致的状态。
- solver可视化debug默认采用SpringBone VRM式隐式请求：debug入口声明world/scope、语义层和过滤条件，自动发现匹配solver slot，不要求用户为每个constraint或中间数组接线。请求在该语义层声明的后续生产阶段捕获；substep层等待真实推进，scheduler前帧判定层可在zero-substep新帧捕获。一次性请求消费后清除，只有continuous模式持续readback。
- 无debug请求时不得执行native中间态readback、per-item对象展开或viewport几何构建。复杂solver通过分层snapshot、按需buffer和renderer registry扩展，不通过常驻全量快照换取实现简单。
- 每个会改变空间边界、连接membership或重要分支判定的用户参数，必须在solver专项验收中登记可观测方式：直接绘制、数值overlay/diagnostic或明确说明其为何不是空间量。debug coverage属于产品验收，不以“MC2/第三方原版没有可视化”作为豁免。
- 同一产品词下存在多个真实基准时必须拆分模式。MC2的Motion BasePosition来自animated base pose，Angle Restoration target来自StepBasic父子目标，Final Output Offset来自result/writeback；三者不得共用一个模糊Motion快照。外部碰撞debug必须消费每个task实际上传、经过owner/group/type过滤后的collider frame，不能直接绘制world全量collider snapshot。
- 当某个 domain 的调试语义因类型而显著不同（例如 Fixed/Hinge/Slider/Cone）时，应在 solver 子模块内拆分按类型 renderer registry。renderer 只把“后端实际消费的 spec 快照 + 后端发布的动态 state”转换成纯绘制 primitives；viewport handler 只聚合、着色和提交 GPU batch。未知类型必须显式降级并进入 debug audit，不能套用一个看似成功的通用图形。
- solver 用户文档应与实现一起放在 solver 子模块的 `docs/` 中，并区分 backend 原生能力、当前 binding 能力和节点已暴露能力；新增约束类型的验收必须同时覆盖 spec/binding、result state、专用 renderer、用户文档和测试。

## Writeback Result Stream

solver step 应产生统一 result stream，而不是直接写 Blender。

当solver下一帧会从同一个Blender owner重新采集frame input时，必须定义输出反馈屏障：能够区分“上帧物理写回仍残留”和“本帧动画/driver已经覆盖”。该屏障及其持久状态由solver frame adapter拥有；统一writeback只应用结果plan，不替solver决定动画输入、不记录solver私有反馈状态，也不默认清零PoseBone。若蓝本在动画求值前恢复初始Transform、动画求值后再读取，Blender适配器必须在内存中表达等价输入时序，不得在solver执行期倒写场景来伪造早更新。

**性能说明：** result stream 不应每帧在 Python 层构造 per-item dict 列表。对于骨骼数量较多的 solver（50+ bones），每帧为每根骨骼创建 Python dict 的开销不可忽视。推荐做法：

- result stream 在 solver slot 里以预分配 numpy buffer 表达（`output.target_matrices`, `output.basis_values`）。
- Python 只传递 buffer 引用给 writeback，不每帧创建新对象。
- 下面的 dict 格式适合 debug/export 场景，不作为每帧高频路径的正式格式。

示例（debug/export 用途）：

```python
{
    "kind": "pose_bone_matrices",
    "producer": "spring_vrm",
    "target": armature_obj,
    "items": [
        {
            "bone_name": "Hair_01",
            "target_pose_matrix": matrix,
            "tail_world": vector,
        },
    ],
    "writeback_plan_id": "...",
}
```

高频路径（每帧写回）推荐：

```python
# solver slot 内预分配
slot["output.target_matrices"]  # (N, 16) float32，C++ 原地写
slot["output.basis_values"]     # (N*16,) float32，Python 写回 foreach_set 用

# writeback 节点消费
armature.pose.bones.foreach_set("matrix_basis", slot["output.basis_values"])
armature.update_tag()  # 每个 armature 只调一次，汇总所有 solver 写完后
```

其他 result 类型：

```text
object_transforms    → Object.matrix_world 批量写回
mesh_delta_attribute → GN attribute 或 shape key
shape_key_values
debug_draw_primitives
export_samples
```

隐式对象与写回边界：

- `world.implicit_objects` 本身不进入写回阶段。Physics Writeback 只能消费 `world.result_streams` 中的公开结果，不能把隐式对象 payload 当作 Blender owner 直接写。
- 即使未来出现“虚拟刚体 / 批量生成约束 / 临时 attachment”这类长得像 Blender 对象的隐式对象，也默认只参与 solver prepare 和 debug，不允许伪装成真实 `Object` / `PoseBone` / `Mesh` 写回目标。
- 如果某类隐式对象确实需要写回 transform，必须先在 result item 中显式声明 `writeback_target_type`、`target_id`、`source_implicit_object_id` 和 owner resolver；没有明确 owner resolver 时只能发布 debug/export 结果，不能静默写 Blender。

好处：

- Writeback、Export、Bake、Preview 共享结果。
- solver 可以被测试为纯计算阶段。
- 可以做 `Record Only`，不触发 Blender depsgraph。
- 可以统一统计 writeback 成本。

### Same Frame 策略

`PhysicsFrameContext.same_frame = True` 表示同一帧被重复求值（例如 Blender 交互拖动、场景重建）。各 solver 应在 solver 声明里明确 same_frame 策略：

```text
skip（推荐默认）：
  same_frame 时跳过时间积分 / step，复用上一次结果。
  world.begin 仍然必须重新采集 scope、collider 和 spec。
  如果 spec/kinematic pose 已变脏，solver 可以执行“无时间推进”的 backend sync，
  但不能重复推进模拟时间。
  适合大多数确定性物理 solver。

re_run：
  same_frame 时重新 step。
  仅当 solver 有非确定性外部输入（用户实时调参）时考虑。

re_run_and_reset：
  same_frame 时先 reset 再 step。
  谨慎使用，会破坏连续帧的状态连贯性。
```

默认：`skip`。必须在 solver 声明的 Update Policy 里显式列出 `same_frame_policy` 字段。

## 不兼容收敛策略

当前没有旧资产格式兼容要求，但这不等于可以跳过旧产品行为审计。迁移目标仍是最终收敛为单路径；删除必须晚于替代资格审计，而不是把双路径长期维护成 shadow pipeline：

1. 先确定 world-aware contract：scope、spec、result stream、exchange、writeback 边界。
2. 对旧实现建立产品语义清单：除 direct bpy write、旧 cache owner、scene-wide scan、frame/restart 判断和native handle生命周期外，还要登记输入解释、排序/identity、业务特化、错误域和写回行为。
3. 新 solver 建在 `physicsWorld/<domain>/` 下，直接重写新的 spec / slot / result / writeback 模块。
4. 直接调整节点 socket、payload 和内部数据结构到新 contract。
5. 把 prepare、step、result publish、writeback apply 拆成可独立调用 helper。
6. solver step 只产生 result stream / exchange item，不直接写 bpy。
7. 外部下游节点只读公开result/exchange；solver自有debug renderer只能通过声明过的slot debug snapshot读取私有状态，不直接触碰native handle或任意slot字段。
8. 用后台集成测试锁住同帧、连续帧、跳帧、reset、dispose 行为。
9. 在同一代表性资产和等价配置上比较旧/新生产链的语义、逐阶段耗时、内存和分配；只有source对拍或新链路绝对耗时不能证明产品替代资格。
10. 证明新生产入口、测试和构建对待删除package、context和公开ABI零依赖；需要复用的数值kernel必须先转移到新owner。
11. 语义、生产可达性、性能、架构和独立性门槛全部关闭后，才允许用独立提交删除旧路径并重跑完整门禁。
12. 删除旧路径后，重新生成生产文件/translation-unit职责表和import/include/ABI依赖图；删除准入不能替代删除后的事实审计。
13. 对迁移期间形成的巨型context、转发壳、临时命名和职责碎片做纯结构收口；结构提交不得夹带产品或数值变化。
14. 维护态必须有单一稳定蓝本和可重复热点基线。迁移计划、验收流水和源码worksheet在收口后不继续作为平行权威文档。

旧 solver 的 Python 包装层默认不直接迁移，但删除前必须作为产品语义、生产行为、性能和依赖审查材料；它不是source parity oracle。SpringBone 的旧 wrapper、旧节点和数组 ABI 已删除；其可复用数值 kernel 已收为 context 实现的私有 step，不再公开第二接口。

MC2删除后的永久构建边界不再包含legacy开关：旧数组solve、旧context、旧BoneCloth IO、旧package和公开ABI均不存在；新Physics World V0、static producer、self collision与共享`mc2_kernels`必须通过`311 native`/`313 native`独立构建和生产符号门禁。共享kernel的保留不构成旧solver兼容；任何恢复旧package/context/公开ABI或让测试反向依赖删除项的改动都构成违规。

MC2已通过P-08替代资格总门禁，允许按独立提交进入旧路径删除。准入只授权删除已审计的legacy node/package/context/IO，不改变公开world step一次处理全部active tasks、profile+task component、自动self scope、单半径authoring和全隐式debug合同；删除后正确性、职责重组、依赖洁净度、稳定蓝本和热点基线全部关闭前不得关闭solver acceptance blocker。

属性迁移也遵循同样的单路径原则：保留 Blender 持久属性名不等于保留旧所有权。solver capability 持有 schema，domain `properties.py` 生成 RNA 声明，`physicsWorld.registry` 统一注册/注销；外部面板模块不得再定义同名 PropertyGroup。

MeshCloth BasePose是automatic frame prepare前的惰性场景资源，不是逐帧solver输入：帧首只允许对active live Mesh做属性组与空pointer检查，且仅在`mc2_base_pose_proxy`为空时创建独立Object/Mesh缓存。已有pointer必须零创建工作量返回，不得为了“保险”逐帧执行完整ensure、拓扑hash、复制或刷新；后续只读frame adapter消费已分配代理。

## 新迁移 solver 的 C++ 单实现策略

新迁移进统一物理世界的 solver 默认只保留一条计算实现：C++ / native 侧。Python 层只负责：

1. 从 Blender / 节点输入构建 spec。
2. 管理 `PhysicsWorldCache`、solver slot、dirty key、生命周期和 dispose。
3. 把 spec / world snapshot 打包成 native buffer。
4. 调用 native context / step / readback。
5. 发布 result stream / exchange，并由统一 writeback 执行 bpy 写回。

不再新增 Python solver 与 C++ solver 双实现，也不再暴露 `xxx` / `xxx_CPP` 两套节点。节点数量应按“语义能力”组织，而不是按 backend 数量组织。需要调试或降级时，只允许以下方式：

- native 后端不可用时节点报错或输出明确的 stats/error result，不自动切回 Python 计算。
- 单元测试可以有 Python 参考函数，但只能放在 test / reference 区，不作为运行时 backend。
- 数值算法的可读性应通过 C++ 侧拆函数、注释、测试和小型 reference case 解决，不靠维护第二套 Python solver。

这一策略的目标是减少节点数量、减少行为分叉、避免 Python / C++ 实时性不一致，并让调度、跳帧、缓存生命周期都只在世界层表达一次。

C++边界必须由生产链计时和分配数据决定，而不是按语言偏好扩大。逐帧的大数组遍历、list/dict到buffer转换、重复矩阵/碰撞体转换和数值kernel是优先候选；Blender RNA读取、生命周期、spec/identity、result transaction和writeback owner仍归Python。一次性静态构建只有在代表性大资产上被证明为瓶颈时才迁入C++。

## physicsWorld/utils 抽取计划

迁移过程中明显通用的数学和实用函数，应从旧 solver 包装层抽到 `OmniNode/NodeTree/Function/physicsWorld/utils/`。这个目录只放与统一物理世界相关、且不属于某个单一 solver 的 helper。

初始建议分层：

```text
physicsWorld/utils/
  math.py           -> 矩阵、四元数、向量、归一化、矩阵 16 展平等纯 Python helper
  ids.py            -> obj/data pointer、slot id、hash key、scope key 片段
  buffers.py        -> numpy buffer 创建、shape 校验、matrix/vector 打包
  writeback_pose.py -> PoseBone matrix_basis 计算与批量写回准备
  collision.py      -> 碰撞组 mask、半径缩放、collider snapshot 到 native arrays 的打包
```

抽取规则：

- 纯数学、buffer shape、id/hash、通用 writeback plan 可以进 utils。
- solver 独有参数、算法状态、native handle、业务 dirty policy 不能进 utils。
- utils 不读取 solver slot 私有结构；需要数据时由调用者显式传入。
- utils 不直接调用 native step；native context 生命周期仍归属各 solver backend。
- 如果某个 helper 同时被 SpringBone、BoneCloth、Rigid/Jolt 或 MC2 使用，优先抽到 utils。

## 其它 solver 迁移入口

不要把“Jolt 全能力完成”作为其它 solver 迁移的前置条件。统一物理世界要验证的是通用 contract，而不是 Jolt 的全部 feature。满足以下条件后，可以开始其它 solver 的 world-aware vertical slice：

1. `PhysicsWorldCache` 的生命周期已经通过真实 runtime cache 路径验证：Cache Write 提交、Cache Delete、`OmniRuntimeState.clear_all()` 都能触发 owner dispose。
2. 目标 solver 可以声明 consumes / produces / persistent state / dirty key / same_frame_policy / writeback 支持。
3. solver step 不直接写 bpy；输出先进入 `world.result_streams` 或 `world.exchange`。
4. 写回路径已经有明确 owner：Object、PoseBone、mesh delta、shape key 或 export cache，不能在 solver 内隐式写；隐式对象不能伪装成 owner 绕过统一写回。
5. debug 节点能观察该 solver 的 slot / result / stats，而不读取 backend-private handle。
6. native/C++ 计算入口明确，Python 运行时不维护第二套 solver 算法。
7. 如需隐式对象或生成 spec，必须先定义 `implicit_objects` tag / schema / stable_id / signature / conflict policy。
8. 最小后台测试覆盖连续帧、same-frame、跳帧/首帧回退、reset、dispose。

> 各 solver 对上述条件的实际覆盖情况见实现状态文档。

迁移不是一次性把旧 solver 全搬完。每个 solver 的第一步必须是极窄 vertical slice：

```text
world.begin
  -> collect/build minimal spec
  -> solver slot 持有最小 runtime state
  -> solver step 发布一个 result stream
  -> debug/result stream 节点可观察
  -> writeback 节点消费最小 result
  -> world.commit/cache.write
```

每个 solver 的第一条迁移都应是这样一条 vertical slice：先打通 slot 生命周期、result stream、writeback、runtime cache dispose 的最小闭环，再逐步补齐 collider、多目标、参数热更新等能力。当前完成度见实现状态文档。

具体 solver 的迁移优先级、当前完成度和未完成项只在实现状态或各 solver 验收表维护，本文不保存对象级推进记录。

## Debug 与性能统计

Viewport物理debug的基础图元由`physicsWorld/utils/debug_draw.py`统一拥有，solver不得各自复制GPU状态或几何生成器。表达规则固定为：

- 只有位置语义的粒子、锚点、目标点和接触点使用抗锯齿圆点；圆点大小是屏幕像素，不随world scale变化。
- 位移、速度、力、法线和修正量使用带箭头向量；普通线只表达拓扑边、无向约束、候选pair或形状轮廓。
- 只有数据真实包含旋转时才绘制basis/axis，禁止用三轴十字代替普通位置点并暗示不存在的旋转。
- 角限制/旋转差使用角弧，弹簧或柔性距离语义可使用spring line；半径、包围体和碰撞形状继续使用world-space圆、球、胶囊、平面和box。
- 公共renderer负责GPU blend/depth/line width/point size的保存与恢复；domain renderer只组装冻结snapshot生成的line/point batches，不读取live RNA补画。

统一 timing 应使用阶段名，而不是 solver 私有术语。推荐基础阶段：

```text
world.begin
scope.collect
entity.build
frame.prepare
solver.cache_match
solver.prepare_static
solver.prepare_dynamic
solver.native_sync
solver.step
exchange.publish
exchange.consume
writeback.prepare
writeback.apply
world.commit
cache.write
```

solver 内部可附加细分：

```text
spring.pack
spring.native_core
spring.unpack
mc2.collision
mc2.solve_context
rigid.jolt_step
```

判断优化方向：

- `solver.step` 小，`pack/unpack/native_sync` 大：优先 native context 和常驻 arrays。
- `writeback.apply` 大：优先统一写回、批量写回、record only 模式。
- `scope.collect/frame.prepare` 大：优先 object scope 限定和公共 snapshot。
- `cache.read/cache.write` 大：检查 owner 是否走零拷贝，避免深拷贝。

## 文档落地要求

已完成迁移的 solver 应提供面向当前实现的稳定蓝本，不再让迁移预演或验收流水承担维护入口。SpringBone 的参考实现见 `SPRINGBONE_VRM_BLUEPRINT.md`。

后续每个 solver 迁移或新增时，至少补充：

1. Solver 声明表。
2. 数据归属表。
3. 更新频率表。
4. result stream 格式。
5. exchange channel 使用情况。
6. implicit_objects tag / schema / stable_id / signature / conflict policy。
7. dirty key 定义。
8. native context 生命周期。
9. writeback/export 支持状态。
10. 不兼容变更说明。

## Solver 声明 registry

solver 声明不仅是文档表格，还必须落成运行时可查询的 registry。代码入口 `physicsWorld/declarations.py`，debug 入口 `solver_declarations_debug_snapshot()`。

**每个新 solver 必须先声明再接节点。** 最小字段：`solver_id`、`slot_kind`、`stage`、`consumes`、`produces`、`persistent_state`、`dirty_keys`、`same_frame_policy`、`update_policy`、`writeback`。

registry 校验规则：

- `consumes` / `produces` 只列公开通道：world snapshot、implicit object tag、exchange、result stream、solver slot 摘要。
- result 不能只藏在 solver slot 或 native handle 里，否则无法被统一 writeback / export / debug 消费。
- `writeback.solver_inline_writeback=False` 是硬约束（对应写回时序语义的目标模式）。
- `same_frame_policy` 必须说明同帧重复求值是 step、sync 还是只重发结果。

后续 solver 迁移先补 `names.py` 常量和 declaration，再接节点；已注册的内置声明清单见实现状态文档和运行时 registry snapshot。
