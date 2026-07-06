# OmniNode 物理模拟流程契约

本文定义 OmniNode 物理系统的长期流程边界。它不是某个 backend 的接入计划，也不是现有节点的用户手册，而是未来刚体、布料、弹簧骨、软体、流体和跨 solver 交互共同遵守的架构契约。

现有 `UNIFIED_PHYSICS_WORLD_NODE_SYSTEM_DESIGN.md` 已经定义了“统一 `PhysicsWorldCache` owner + 多 solver 协作”的方向。本文进一步拆开每个阶段的职责，回答下面这些问题：

- 每个物理节点到底拥有什么数据。
- 每帧运行、dirty 更新、懒更新和重建的边界在哪里。
- solver 如何声明自己消费和产生的数据。
- 程序化实体、临时物理对象和跨 solver 交互如何进入系统。
- 写回、导出缓存和预览如何共用同一套结果流。
- Python cache 与 native context 如何分工，避免隐藏全局状态。

## 设计结论

OmniNode 物理系统应该从“一个高封装 solver 节点内部完成所有步骤”推进到“显式物理流程阶段”。第一版不要求用户手动连接所有阶段，但实现和文档必须按这些阶段拆清楚。

推荐完整流程：

```text
Cache Read
  -> Physics Object Scope
  -> Physics World Begin
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
- 更新 `PhysicsFrameContext`：frame、previous_frame、continuous、same_frame、restart_required、dt、time_scale、substeps、generation。
- 计算 object scope key，检测 scope 变化。
- 构建公共 source / collider snapshot。
- 清理上一帧异常残留的 write lock。
- 根据 validity、reset、跳帧、倒放、scope 变化设置 `replace_required`。
- 准备 frame exchange registry。

不负责：

- 不知道 MeshCloth、BoneCloth、SpringBone、RigidBody 的业务参数。
- 不执行 solver prepare 或 solver step。
- 不写 Blender。
- 不提交 runtime cache。

### Physics Entity / Spec Build

职责：

- 从 Blender 属性、节点参数、规则节点、程序化生成节点产生物理实体描述。
- 输出稳定、可 debug、可导出的 spec。
- 为隐式物理实体提供正式入口。

典型输入：

- `PhysicsTools` 挂在 Object / Bone / Mesh 上的属性。
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
- 产生 result stream 或更新 solver slot 内的 frame result。

默认约束：

- 不直接写 PoseBone、Object transform、mesh attribute。
- 不直接调用 Cache Write。
- 不创建不可清理的 native 全局状态。

允许例外：

- 已存在的 legacy/integrated solver 可以继续内部写回，但必须标记为 legacy path。
- 迁移期间可保留旧节点行为，同时新增 world-aware shadow path。

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
rigid_contact_events
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

Rigid solver 必须把这些命令翻译到 adapter 的 slot_id API，不允许命令节点直接保存或读取 Jolt native handle。

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

当前刚体落地点：

- `physicsRigidSolver` 在每个 rigid body slot 写入 `result.rigid_transform`。
- `result.rigid_transform` 是本帧纯快照 dict/tuple 数据，包含 `frame`、`generation`、`slot_id`、`body_type`、`position`、`rotation_wxyz`、`linear_velocity`、`angular_velocity`、`active`、`sleeping`。
- `physicsWriteback` 和 `physicsWorldDebugDraw` 消费该 result，不读取 `JoltAdapter._jw`、`_body_handles` 或其他 backend-private handle。
- 这是 `world.exchange` 的过渡形态；等跨 solver result channel 稳定后，可把相同 payload 移到 exchange。

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

当链路中有多个 solver，且下游 solver 需要感知上游 solver 的物理结果时，有以下三种语义：

**模式 A：solver 内写回 bpy，下游读 bpy（当前做法）**

```text
SpringBone step → 立即写 PoseBone
  ↓ (bpy)
Cloth step 读到 SpringBone 已写回的骨骼状态
  ↓
链路末尾 Writeback（Cloth 自己再写）
```

- 优点：下游 solver 不需要改，直接读 bpy。
- 缺点：同一骨架在一帧内发生"写 bpy → 读 bpy"循环，可能触发 Blender depsgraph 中间重算；无法做 Record Only；无法统一 writeback 统计。

**模式 B：所有 solver 结果存 world.exchange，链路末尾统一写 bpy（推荐长期目标）**

```text
SpringBone step → 写 world.exchange["spring_bone_matrices"]
  ↓ (world.exchange，无 bpy 写)
Cloth step 读 world.exchange["spring_bone_matrices"]（不读 bpy）
  ↓
Physics Writeback 统一写 PoseBone + mesh delta
```

- 优点：零 bpy 中间写；支持 Record Only；writeback 成本可统一统计。
- 缺点：所有下游 solver 必须声明消费 exchange channel；首次迁移改动范围较大。

**模式 C：上游 solver 内写回 bpy，下游 solver 读 bpy（同 A），但 writeback 节点可选（当前旧路径兼容）**

### 系统约定

**第一版统一选模式 A 作为兼容路径，模式 B 作为新 solver 的目标。**

规则：
1. **新写的 solver 必须用模式 B**：step 不写 bpy，结果存 solver slot 或 world.exchange，由 Physics Writeback 节点消费。
2. **旧 solver 迁移前可保留模式 A**，但必须在 solver 声明的 Writeback 字段里标注 `legacy_inline_writeback: true`。
3. **如果下游 solver 需要消费上游物理结果**，上游 solver 必须发布 exchange item；下游 solver 声明消费该 channel，不依赖 bpy 中间状态。
4. **`armature.update_tag()` 只能在 Physics Writeback 节点调用**，每个 armature 只调一次（汇总所有 solver 写完后），不能在 solver step 内调用。

### Physics World Commit

职责：

- 按 `world.replace_required` 生成 `_OmniCache.replace(world)` 或 `_OmniCache.mutate(world)`。
- 透传 world 用于 debug。
- 统计 solver slot、exchange、writeback、backend resource 状态。

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
- 使用 name 时要说明是兼容旧缓存还是稳定 id。
- native context schema 变化必须进入 backend key。
- 修改 socket 参数名会影响节点兼容性，不能随意作为 key 的唯一来源。

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

阶段 6：释放（dispose 时）
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

## Writeback Result Stream

solver step 应产生统一 result stream，而不是直接写 Blender。

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

## 兼容迁移策略

现有 solver 不应一次性打散。推荐 shadow pipeline：

1. 保留旧节点 UI 和行为。
2. 在内部按新阶段重命名 timing。
3. 把 prepare、step、writeback 拆成可独立调用 helper。
4. 让 solver step 产生 result stream，同时旧路径立即消费它写回。
5. 新增 world-aware 节点或可选 world 输入。
6. 验证性能和行为后，再把写回移到统一节点。

优先预演对象：

```text
VRM SpringBone:
  已有 Python / C++ 双路径，cache、碰撞、PoseBone 写回、multi-armature 都齐全。

MC2 MeshCloth:
  已有 native context 和 mesh delta 写回，适合验证 native resident state。

Rigid Jolt:
  适合验证 backend world resource、dispose 和 object transform writeback。
```

## Debug 与性能统计

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

后续每个 solver 迁移或新增时，至少补充：

1. Solver 声明表。
2. 数据归属表。
3. 更新频率表。
4. result stream 格式。
5. exchange channel 使用情况。
6. dirty key 定义。
7. native context 生命周期。
8. writeback/export 支持状态。
9. legacy 兼容说明。

## 当前建议

不要先把所有 solver 重写到 C++。先以 VRM SpringBone 做预演，把一条稳定 solver 的内部阶段映射到本文契约，确认职责拆分是否真的减少重复转换、提高可读性，并暴露出更新频率和 dirty 策略差异。

在文档和 timing 稳定后，再决定：

- 哪些静态数组进入 native context。
- 哪些公共数据进入 world。
- 哪些结果进入统一 writeback。
- 哪些跨 solver hack 升级为 exchange channel。
