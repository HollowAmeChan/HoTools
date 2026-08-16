# Jolt Physics 产品化路线图

本文是 HoTools / OmniNode `rigid_jolt` 的资源导航、能力边界和下一阶段路线。它只保留当前成立的事实、已冻结决定、待补能力和验收出口；日期追加、单次测试输出、提交说明和已经结束的施工过程只留在 Git 与专项测试报告中。

## 资源导航与版本

### 文档路由

- 本文：Jolt 产品方向、当前能力、近期边界和实施顺序。
- [Physics World 公共管线契约](PHYSICS_SIMULATION_PIPELINE_CONTRACT.md)：跨 solver 的阶段、生命周期、result/exchange、native owner 和写回规则。
- [Physics World 当前状态](PHYSICS_WORLD_IMPLEMENTATION_STATUS.md)：所有 domain 当前处于什么阶段。
- [Physics Field / Volume 蓝本](PHYSICS_FIELD_VOLUME_BLUEPRINT.md)：共享 Field 资源、runtime 和 consumer 边界，可作为 Jolt 后续消费 Field 的架构参考。
- [OmniNode 架构](../ARCHITECTURE.md)：函数节点、业务域注册、runtime cache、批结果和 socket 规则。
- [刚体文档入口](../PhysicsWorld/rigid/docs/README.md)：约束、设置、测试、性能、调试和专项接入文档。
- [刚体破碎资产蓝本](../PhysicsWorld/rigid/docs/RIGID_FRACTURE_BLUEPRINT.md)：GN 显式刷新、受管 Piece、运行时展开、激活语义和球撞墙验收。
- [Native 后端 README](../../_native/README.md)：构建入口、产物、目录和 native/Python 分工。
- [Jolt Blender 兼容约束](../../_native/docs/JOLT_BLENDER_COMPAT.md)：Windows/Blender 进程内必须保留的构建与线程原语约束。

### 本地实现入口

| 领域 | 路径 |
|---|---|
| Jolt 版本 | `5.2.0`，由 `_native/CMakeLists.txt` 的 `HOTOOLS_JOLT_VERSION` 固定 |
| Jolt 本地源码 | `_native/extern/JoltPhysics` 或 `_native/build/*/_deps/joltphysics-src`；后者是生成目录，不是永久 patch 源 |
| Native binding | `_native/src/jolt_rigid.cpp` |
| Python adapter | `OmniNode/PhysicsWorld/rigid/backends/jolt.py` |
| Solver / result | `OmniNode/PhysicsWorld/rigid/solver.py`、`results.py` |
| Canonical spec | `OmniNode/PhysicsWorld/rigid/specs.py` |
| 持久属性 | `OmniNode/PhysicsWorld/rigid/schema.py`、`properties.py` |
| Blender 属性/面板迁移索引 | 旧资料中的 `PhysicsTools/physicsProperty.py`、`PhysicsTools/physicsPanel.py` 已不在当前树中；现行注册与字段来源是上一行的 `schema.py`、`properties.py` |
| 节点 / 隐式对象 | `OmniNode/PhysicsWorld/rigid/nodes.py`、`implicit_objects.py` |
| Solver 声明 | `OmniNode/PhysicsWorld/rigid/declaration.py` |
| Native 测试 | `_native/tests/test_jolt_rigid_native.py` |
| 三层语义测试 | `OmniNode/PhysicsWorld/rigid/test/` |
| 刚体破碎专项 | `OmniNode/PhysicsWorld/rigid/docs/RIGID_FRACTURE_BLUEPRINT.md` |
| 约束参考 | `OmniNode/PhysicsWorld/rigid/docs/CONSTRAINT_REFERENCE.md` |
| 世界设置参考 | `OmniNode/PhysicsWorld/rigid/docs/JOLT_SETTINGS_REFERENCE.md` |
| 测试策略 | `OmniNode/PhysicsWorld/rigid/docs/JOLT_TEST_STRATEGY.md` |
| 性能边界 | `JOLT_PERFORMANCE_OPTIMIZATION.md`、`JOLT_WRITEBACK_PERFORMANCE_BOUNDARY.md`、`JOLT_BLENDER_10K_PERFORMANCE_BOUNDARY.md` |

### 外部资料

- [Jolt Physics GitHub / README](https://github.com/jrouwe/JoltPhysics)
- [Jolt 官方 API 文档](https://jrouwe.github.io/JoltPhysics/)
- [Jolt release 文档](https://jrouwe.github.io/JoltPhysicsDocs/)
- [Jolt Constraints 总览](https://jrouwe.github.io/JoltPhysics/index.html#constraints)
- [Jolt Samples](https://github.com/jrouwe/JoltPhysics/tree/master/Samples)
- [Godot Jolt 集成](https://github.com/godot-jolt/godot-jolt)，只作成熟 DCC/runtime 映射参考，不作为 HoTools schema 来源。

Jolt 的公开 API 不能直接成为 OmniNode 公共协议。HoTools 持久属性、spec、result stream 和节点命名保持产品语义，由 adapter 映射到当前固定版本的 Jolt。

## 当前结论

`rigid_jolt` 已经具备可靠的刚体纵向切片，不再是“最小可运行 backend”。当前已有基础刚体、十一种通用约束、运行时命令、接触/传感器事件、closest-hit RayCast、调试绘制、双 ABI 语义 fixture、golden、soak 和批量结果/写回路径。

近期主线继续以 Blender Object 作为唯一模拟实体和写回目标：

```text
Source Object.hotools_rigid_fracture + GN / modifier
  -> 显式刷新、Realize、按连通块拆成受管 Mesh Piece Objects
  -> Product Collection + asset/piece identity + 普通刚体属性
  -> 排除 Source，展开受管 Piece
  -> Physics Object Scope / ordinary RigidBodySpec
  -> Jolt
  -> 现有列式结果 + Collection 批量 Object 写回
```

这条链先解决可用性、资产准备、稳定身份和大批 Object 的注册/写回，不直接让 Jolt 管理 GN runtime instances，也不把模拟结果直接写进动态实例 mesh。

凸包 shape、精确 Full Mesh shape 和 GN 动态实例直连都是后续能力。它们现在需要被设计兼容，但不能抢在 Object 工作流前实现或把近期 schema 搞成两套实体模型。

很长一段时间内明确不做：`Path`、Vehicle、Soft Body、Ragdoll。它们不得出现在近期 planned node、里程碑或“顺手接入”列表中。Character 也不是当前刚体产品化的前置能力。

## 当前基线

### 已成立能力

| 领域 | 当前能力 |
|---|---|
| Body | `STATIC`、`DYNAMIC`、`KINEMATIC`；质量、摩擦、弹性、初速度、阻尼、重力倍率、睡眠、CCD、传感器、速度上限、轴锁、刚体碰撞组 |
| Shape | Sphere、Capsule、Box、Plane、Cylinder、Tapered Capsule、Tapered Cylinder；局部偏移和局部旋转 |
| Constraint | Fixed、Point、Distance、Hinge、Slider、Cone、SwingTwist、SixDOF、Pulley、Gear、RackAndPinion |
| Runtime | 设置速度、施力/力矩、冲量/角冲量、重力倍率、材质响应、运动质量、激活状态 |
| Result | transform、constraint state/lambda、contact、sensor、query、stats；公开结果不含 Jolt handle |
| Query / Debug | closest-hit RayCast；body/constraint/contact/sensor 调试快照与视口绘制 |
| World | 重力、容量、Jolt 子步、求解迭代、线程、事件记录、确定性、warm start、body-pair cache、manifold reduction、large-island splitter、world sleeping |
| Lifecycle | stable slot、same-frame、restart、dispose、结构脏重建、约束依赖顺序和断裂策略 |
| Verification | py311/py313 native/adapter/Blender fixture、cross-ABI、golden、soak 和性能门禁 |

### 主要缺口

| 缺口 | 直接后果 |
|---|---|
| GN 生成资产没有受管的“应用并拆分为 Objects”入口 | 用户需要手工应用 modifier、Realize、拆分、命名、放入 Collection 和配置刚体，流程容易漂移 |
| 没有刚体破碎 Source/Piece 属性与 linked Collection resolver | 本体和碎块不能形成可验证的 owner 关系，也无法保证只排除本体并接纳受管碎块 |
| 新建 Jolt body 当前始终 Active | 破碎块注册后立即受重力，不能表达接触前保持静止的 armed 状态 |
| Object authoring 缺少批属性和稳定生成身份 | 重新生成后约束、缓存和调试难以追踪同一块几何 |
| 稳定帧仍有 Object body 同步与 Blender 写回成本 | Jolt step 很快，但大规模场景仍受 Python/Blender 对象层限制 |
| 属性与生成约束节点是弱类型大参数面 | 连接错误晚发现，约束节点过宽，难以复用和批量生成 |
| 没有 mesh/convex shape 资源协议 | 复杂 Object 仍需基础 shape 代理；GN 生成的凸几何当前只是 authoring mesh，不自动成为 Jolt convex shape |
| 世界设置只覆盖第一批开关 | 接触容差、CCD、睡眠阈值和 cache 容差仍使用 Jolt 默认值 |
| 查询只接 closest-hit RayCast | ShapeCast、overlap、多命中和 query filter 尚未形成产品链 |

## 设计边界

- 近期 canonical body identity 只对应 Blender Object。生成资产、显式节点和面板属性最终都必须解析成 Object + Data 双身份。
- GN 在近期是 authoring/preprocess 工具。应用、Realize 和拆分发生在显式创作操作中，不发生在每帧 solver step、frame handler 或 writeback 中。
- Jolt 不创建、删除或拆分 Blender 数据块；资产生成器完成后，Physics Object Scope 只看到普通 Objects。
- Python 负责 Blender authoring 解析、依赖图读取、稳定身份、事务和 dirty 判定；native 只接收连续纯值快照并持有 Jolt 资源。
- Native worker 不访问 Blender RNA、Python 对象或依赖图。
- Solver 只发布 result stream；Object 写入和 `update_tag()` 继续由公共 writeback 执行。
- 公共 schema 使用 HoTools 语义，不暴露 `BodyID`、`Constraint*`、`Shape*` 或 Jolt 内部枚举。
- 拓扑、shape、body type 和约束拓扑是结构数据；运动学 transform、命令和允许热更新的参数是帧输入。
- 同一 Object identity 在一个 world 中只能有一个 authoring owner。面板、显式节点或生成清单重复声明必须在进入 Jolt 前报错。
- 大数组可以使用 `PhysicsResultBatch` 保持列式/惰性；不得为了兼容节点先展开为逐 body 字典。
- 所有新增物理能力按 `spec -> adapter -> native -> result/debug -> fixture/golden/performance` 作为不可拆分的纵向切片交付。

## 近期主线：GN 资产对象化

第一条产品纵向切片已经收敛为“刚体破碎资产”，详细字段、事务、Scope resolver、激活语义和测试出口只维护在 [刚体破碎资产蓝本](../PhysicsWorld/rigid/docs/RIGID_FRACTURE_BLUEPRINT.md)。本节只保留所有 GN Object 资产都要遵守的公共边界。

### 产品语义

需要新增的是显式创作工具，不是一个每帧执行的模拟节点。它把 GN 或 modifier 的 evaluated 结果固化为受管的普通 Objects，随后完全复用现有 Jolt Object 链路。

第一版工作流：

1. 接收一个源 Object 和一个目标 Collection。
2. 在创作操作边界取得 evaluated geometry，应用目标 modifier/GN 结果并 Realize instances。
3. 按明确模式拆分：`REALIZED_INSTANCE` 或 `CONNECTED_COMPONENT`。不能用含糊的“自动”规则混合两者。
4. 为每块生成独立 Mesh 数据和 Object，保留正确 world transform；禁止让所有结果共享仍会被后续编辑污染的临时 mesh。
5. 写入受管 source identity、piece identity、生成 revision 和源对象引用信息。
6. 可选批量写入 `Object.hotools_rigid_body` 的属性模板；物理 shape 第一版只能选当前已支持的基础类型。
7. 原子提交到目标 Collection。失败时不留下部分 Objects；重新生成按 manifest 替换上一版受管结果。

GN 生成了凸外观，不等于当前 Jolt 已经使用 convex shape。凸包 shape 接入前，生成的 Objects 仍使用 Sphere/Box/Capsule/Cylinder 等已支持代理；这个限制必须在 UI 和 diagnostics 中显式显示，不能静默把 mesh 当成 Box 或 ConvexHull。

### 稳定身份与重建

建议 identity：

```text
generated_object_id = source_id + piece_id
```

- 如果 GN 输出持久整数 ID，优先使用该 ID 作为 `piece_id`。
- 如果没有稳定 ID，只能把本次结果视为整批 replacement；不能承诺约束或缓存跨重新生成保持绑定。
- Connected component 的遍历下标不是稳定 ID。若要做确定性 fallback，必须由局部几何 fingerprint 和规范排序产生，并用重复几何 fixture 验证冲突处理。
- 生成器维护 manifest：source、revision、目标 Collection、生成 Objects、piece IDs 和 schema version。
- 更新先在暂存 Collection/数据块完成全部验证，再一次替换旧 manifest；删除旧受管资源必须支持 Undo，且不能删除用户接管或移出 manifest 的 Objects。

### 节点与 Operator

建议将破坏性数据块操作放在显式 Operator，节点只构造和提交 setup request：

| 入口 | 职责 |
|---|---|
| `刚体资产-GN应用拆分设置` | 构造 source、modifier、split mode、ID attribute、target Collection、replace policy 和属性模板 |
| `刚体资产-GN应用并拆分` Operator | 显式执行 evaluated copy、Realize、拆分、暂存、原子替换和 Undo |
| `刚体对象-批属性` | 对已存在的 Object Collection 构造/应用统一 `RigidBodyPropertiesV1`；不执行模拟 |
| `刚体对象集` | 把 Collection 中已验证的 Objects 解析成强类型 Object set，供后续 request/compiler 使用 |

帧执行图不得自动重新应用 GN 或重建 Objects。源 GN 变化只把 setup 标成 `OUTDATED` 并给出显式重建入口；用户确认后才修改场景资产。

## Object 批同步与批写回

近期性能目标仍是当前 Object 模型，不引入实例实体：

- Object Scope 保留稳定 Collection/Object 顺序和 Object/Data 双指针身份。
- 冷启动或结构变化批量注册 body manifest；稳定帧只同步运动学位姿、热参数和命令。
- Native 保留稳定 body row；只有 manifest revision 变化才重建 `slot_id/object_ptr -> native row` 映射。
- Transform 继续以列式 `PhysicsResultBatch` 发布；dense Collection writeback 直接消费列，不逐项物化公开 dict。
- Object 写回继续使用公共 `Object.delta_*` 语义、统一 reset/restart/dispose 和三种写回模式。
- 不为性能建立 Jolt 私有写回旁路，也不让 native 调 Blender RNA。

这条路线应先测 `body_sync_ms`、result publish、Collection writeback 和 depsgraph，而不是继续优先调 Jolt solver 开关。1k/10k Object 的目标是减少 Python 往返和重复索引，不是假装 Object 数量本身没有成本。

## 未来 Shape：Full Mesh 与 Convex Hull

Shape 扩展晚于 GN 对象化和 Object 批路径。两个概念必须分开：

| 公共语义 | Jolt shape | 合法 body | 计划 |
|---|---|---|---|
| `FULL_MESH_STATIC` | `MeshShape` | Static | 精确三角面，适合场景障碍；Jolt 5.2.0 `MeshShape::MustBeStatic()` 明确要求 static |
| `CONVEX_HULL` | `ConvexHullShape` | Static / Dynamic / Kinematic | 动态凸 Object；作者先用 Blender/GN 生成凸 mesh，HoTools 不做自动凸分解 |

因此不存在“Dynamic Full Mesh 先顶上”的合法捷径。动态的 GN 凸块最终需要 `CONVEX_HULL` shape，但这是后续独立纵向切片，不纳入近期 Object 基础设施里程碑。

未来 shape 资源仍遵守：

- evaluated mesh 只在结构 dirty 时快照/cook，不逐帧重建。
- 大顶点/索引数组放在 world-owned shape resource store，`RigidBodySpec` 只持资源键。
- 多个 Objects 可以共享同一 cooked shape；局部缩放/offset/rotation 必须进入 shape key。
- Shape 错误原子拒绝引用该资源的 body set，不留下半注册 body 或失效约束。
- Convex Hull 输入需要 finite、非共面和退化诊断；Full Mesh 需要固定三角化、winding 和 active-edge 策略。

## 远期：直接 GN 实例模拟

直接控制 GN 动态实例确实可能把 N 个 Object 写回收敛为少量 mesh attribute 写入，但近期不冻结它的实体 schema、节点或属性名。

只有下面条件全部成立后才进入设计：

- Object 模式的资产准备、stable identity、batch sync/writeback 和约束引用已经稳定。
- 性能报告证明 Object/depsgraph 是剩余主瓶颈，并给出 GN carrier 的可测收益目标。
- 能定义持久 instance ID、shape sharing、约束端点、命令目标、删除/重排和 bake 语义。
- Source/Rest carrier 与 Runtime output carrier 明确隔离，不形成 depsgraph feedback。
- 公共 Physics Writeback 定义统一 result schema 和受管 GN 资源；Jolt solver 不直接操作 attribute、modifier 或 node group。

在此之前，GN 只负责生成并拆分 Objects，所有参与模拟的实体保持为 Objects。

## 显式物理属性

### Canonical 类型

新节点不应继续输出 `list[object]` 和超宽弱类型参数。近期只围绕 Object 模型冻结：

| 类型 | 职责 |
|---|---|
| `RigidBodyPropertiesV1` | body type、质量策略、材质响应、阻尼、重力、睡眠、CCD、轴锁、过滤和传感器 |
| `RigidShapeSpecV1` | 当前 Primitive shape；未来可增加 shape resource ref，不改变 body property socket |
| `RigidObjectSetV1` | 一组已验证的 Blender Objects、稳定顺序、source owner 和属性/shape 绑定 |
| `RigidConstraintSpecV1` | 类型、A/B Object stable ref、A/B frame、公共设置和类型 payload |
| `RigidSimulationRequestV1` | 已去重并完整验证的 Object/constraint manifest、world policy 和 writeback policy |
| `RigidTransformBatchV1` | 与稳定 Object manifest 对齐的列式只读结果；内部和批读取使用，不替代 Object identity |

面板属性保留，但只是 `Object.hotools_rigid_body -> RigidBodyPropertiesV1/RigidShapeSpecV1` 的 authoring adapter。显式节点产生相同 canonical 类型。Solver 不分别维护“面板字段”和“节点字段”两套解析。

### 属性分组

| 分组 | 字段 |
|---|---|
| Motion | body type、initial linear/angular velocity、max velocity、allowed DOFs |
| Mass | auto mass / override mass；完整 inertia override 延后到 mesh/convex fixture |
| Material | friction、restitution；shape material 延后 |
| Forces | linear/angular damping、gravity factor、gyroscopic force |
| Collision | group、collides-with mask、sensor、kinematic-vs-non-dynamic、motion quality |
| Sleep/Solver | allow sleeping、body velocity/position step override |

每个字段标注 `STRUCTURAL`、`HOT_PARAM` 或 `INITIAL_ONLY`。节点 UI、signature 和 adapter 使用同一张字段元数据表，避免同一字段在面板里声称热更新、native 实际却需要重建。

## 新 Node 与 Socket

### Socket

第一批只增加能阻止错误连接的业务类型，不为每个 enum 创建 socket：

| Socket | 运行值 | 连接规则 |
|---|---|---|
| `Rigid Body Properties` | `RigidBodyPropertiesV1` | 接 Object set / body authoring adapter |
| `Rigid Shape` | `RigidShapeSpecV1` | 接 Object set；未来 shape 扩展保持同 socket |
| `Rigid Object Set` | `RigidObjectSetV1` | 可 multi 输入到 request/compiler |
| `Rigid Constraint` | `RigidConstraintSpecV1` | 可 multi 输入到 constraint collect/request |
| `Jolt World Settings` | `JoltWorldSettingsV2` | 一个 request 最终只能解析出一个生效设置 |
| `Rigid Transform Batch` | `RigidTransformBatchV1` | 只接 read/debug/export，不接 authoring body 输入 |

`Object`、`Collection`、`Mesh` 继续使用现有 Blender socket，只存在于 adapter 边缘。内部业务 socket 不保存 live PropertyGroup、Jolt handle 或未声明 dict。低层 debug dict 不是生产连接协议。

### Body / Request 节点

| 节点 | 输入 | 输出 |
|---|---|---|
| `刚体属性` | Motion、Mass、Material、Collision、Sleep 常用字段 | `Rigid Body Properties` |
| `刚体属性-高级` | 低频 body solver 字段 | 属性 fragment |
| `刚体形状-基础` | 类型、尺寸、局部 frame | `Rigid Shape` |
| `刚体对象集` | Collection、Body Properties、Rigid Shape、source ID | `Rigid Object Set` |
| `刚体请求组装` | multi Object Set、multi Rigid Constraint、World Settings | `RigidSimulationRequestV1` |

`刚体属性-高级` 采用显式覆盖并检测冲突，不能依赖连接顺序。GN 应用/拆分设置属于创作 setup 类型，不与 `Rigid Object Set` 混成一个 socket。

### Constraint 节点

现有“刚体生成约束属性”参数过宽。新设计按约束族拆分，共享 A/B Object ref、frame、disable collision、priority、step override 和 break policy：

| 节点 | 覆盖类型 |
|---|---|
| `刚体约束-固定/点` | Fixed、Point |
| `刚体约束-距离/滑轮` | Distance、Pulley |
| `刚体约束-单轴` | Hinge、Slider、Cone |
| `刚体约束-SwingTwist` | SwingTwist |
| `刚体约束-SixDOF` | SixDOF |
| `刚体约束-耦合` | Gear、RackAndPinion，引用 request 内稳定 constraint ID |

类型专属节点只显示有效字段。旧大节点在新链路完成前兼容，随后进入明确 migration；不能永久维护两套 canonical schema。

### Solver 与结果节点

- `刚体模拟步` 后续接收一个或多个已验证 request；旧 scope 自动收集先由兼容 adapter 转成相同 request。
- `刚体结果-读取状态` 保留单 Object 工作流。
- 可增加 `刚体结果-批读取` 返回与 Object manifest 对齐的 `Rigid Transform Batch`，不逐项物化。
- 运行时命令增加 stable body reference 版本；Object 命令节点是便捷 adapter。
- 近期不增加 instance source/result/GN runtime output socket。

## 约束补齐方向

现有十一种类型已经覆盖近期通用约束集合。“补齐”指参数、控制和 UX 完整，不指增加 Path。

| 优先项 | 当前缺口 | 目标 |
|---|---|---|
| Spring mode | 主要使用 frequency + damping | 支持 frequency/damping 与 stiffness/damping，单位和 hard-limit 语义统一 |
| Motor limits | 多数路径使用对称 force/torque limit | 允许显式 min/max，保留对称便捷输入；SixDOF 逐轴一致 |
| Runtime control | breakable 可内部 disable，用户缺统一命令 | enable/disable、motor target、limit 和 break reset 使用 stable constraint ref 命令 |
| Frame | 输入 frame 已独立 A/B，运行时只部分观测 | 读回 backend 实际 world frame 与误差用于 debug，不改变 authoring frame |
| Fixed | 未提供 auto-detect point 产品语义 | 先定义 HoTools 语义和可重复 fixture，再决定是否暴露 |
| Coupling refs | Object/slot 引用不利于显式图 | 改为 request 内 stable constraint ID，拓扑排序和循环诊断前置 |
| Break policy | 当前以 impulse 阈值 disable | 明确 `DISABLE` / `REMOVE` / event-only；力阈值若加入必须独立字段并显式使用 dt |
| Diagnostics | 错误主要在同步期出现 | 每种约束提供结构验证、参数规范化和 native 创建错误的稳定诊断码 |

每种约束的交付出口包括：显式属性、Object authoring 映射、生成节点、native binding、state/lambda、专用 debug、S1/S2/S3 fixture、golden 和文档。

## 世界设置

### 当前设置

| 层级 | 设置 | 更新方式 |
|---|---|---|
| Basic | gravity、substeps、velocity steps、position steps | gravity/迭代可热更新；substeps 属于 Jolt 调度参数 |
| Capacity | max bodies、max body pairs、max contact constraints | 构造期，变化重建 world |
| Runtime | worker threads、record contact events | 变化重建 world |
| Solver policy | deterministic、constraint warm start、body-pair cache、manifold reduction、large-island splitter、world sleeping | 当前签名变化重建；后续按 native 安全性细分热更新 |

### 下一批候选

基于本地 Jolt 5.2.0 `PhysicsSettings.h`，按产品单位分组：

| 分组 | 候选字段 |
|---|---|
| Contact | Baumgarte、speculative contact distance、penetration slop、max penetration correction、min restitution velocity |
| CCD | linear cast threshold、max penetration fraction |
| Sleep | time before sleep、point velocity threshold |
| Cache | body-pair max translation/rotation delta、contact-point preserve distance、contact-normal merge angle |
| Parallel scheduling | max in-flight body pairs、step listener batch size/并行阈值 |
| Debug-only | check active edges 等 Jolt 调试开关，只进入专家/测试配置 |

节点不公开 squared distance 或 cosine 存储形式；adapter 把米、秒、角度转换为 native 表示。TempAllocator 大小保持 native/build policy，不进入普通项目设置。

`JoltWorldSettingsV2` 建议支持 `DEFAULT / CUSTOM` profile，并为高级分组提供“使用 Jolt 默认值”。新增字段加载旧工程时必须得到当前轨迹，不能因 schema 增长改变结果。

容量长期增加 `AUTO / MANUAL`：AUTO 根据已验证的 Object/constraint manifest 加固定 headroom 构建；只有容量不足或结构显著变化时重建。MANUAL 保留给确定性测试和问题复现。

## 实施顺序

### M0：破碎合同与初始激活地基

- 冻结 Source/Piece owner、显式刷新、Scope resolver 和球撞墙 acceptance。
- 在普通刚体 spec/adapter/native 增加默认兼容的 `start_deactivated`，验证重力静止、碰撞唤醒和 restart；本轮只使用 Blender 5.2 / py313，py311 验证暂缓。
- 保留并更新全部资源导航；删除近期 Path/Ragdoll planned 声明，不复制施工流水账。

出口：现有 golden 默认轨迹不变；非激活 Dynamic body 的语义有独立 native/adapter/Blender oracle。

### M1：刚体破碎资产刷新

- 增加 `Object.hotools_rigid_fracture`、Piece metadata、物理大面板和显式 Operators。
- 落地默认 GN、evaluated mesh snapshot、连通块拆分、稳定 ID、暂存提交、manifest、replace/Undo 和诊断。
- 保留匹配 Piece 的用户刚体属性；刷新成功后失效旧模拟 cache。

出口：同一 Source 可反复刷新为受管普通 Objects；失败不留半批，不误删 Product Collection 中的用户对象。

### M2：运行时展开与球撞墙

- fracture resolver 排除 Source，只展开 owner/revision 匹配的受管 Piece。
- Product Collection 进入稳定 transform/writeback 批边界；所有 Piece 继续构造普通 `RigidBodySpec`。
- 交付并后台验证 `rigid/test/assets/jolt_fracture_wall.blend`：碰撞前中央 Piece 静止，命中后局部激活，外圈锚定 Piece 不动。

出口：从 GN 作者态、显式刷新、Scope、Jolt 到 Object 写回形成第一条可打开、可重放的破碎链。

### M3：稳定 Object 表、批同步和批写回

- 冷启动/结构变化批量提交稳定 Object manifest，稳定帧只同步运动学、热参数和命令。
- 表 revision 不变时复用 row/result/object 映射，继续优化公共 dense Collection 写回。
- 以 1k/10k Objects 冻结 body sync、pipeline、writeback、depsgraph 和内存门槛。

出口：破碎 Piece 增长不改变 restart/same-frame/delete/rewind 语义，不以 Jolt 私有旁路换性能。

### M4：局部传播、显式属性、约束与世界设置

- 增加业务 socket、模块化 body/shape/request 节点和 Object authoring adapter。
- 增加接触位置半径/邻接激活、每步上限和可断 Fixed constraint；冲量阈值必须先补真实观测与 oracle。
- 拆分约束族节点，补 spring/motor/runtime control/live frame/diagnostics。
- 分批开放 Contact/CCD/Sleep/Cache 世界设置，并细分热更新与重建字段。

出口：Object-only 显式图可建立 body、破碎资产、十一种约束和世界设置；结构强度不再与 sleeping 混用。

### M5：Full Mesh Static 与 Convex Hull

- 先接 `FULL_MESH_STATIC` 的三角 snapshot、shape cache、静态接触/查询/debug。
- 再接作者提供 mesh 的 `CONVEX_HULL`，不做自动生成或凸分解；Blender/GN 负责预先生成凸几何。
- 覆盖 shape sharing、结构 dirty、modifier/GN source、mass/inertia、CCD 和失败回滚。

出口：Static 精确 mesh 与 Dynamic convex Object 各自使用合法 Jolt shape；稳定帧不复制或 recook mesh。

### M6：查询扩展

按 ShapeCast、overlap、多命中 RayCast、query filter 的顺序扩展。查询结果继续使用 stable Object/slot identity，不暴露 native handle。

### M7：GN 动态实例研究

只在 Object 路线的性能证据和身份合同满足前述门槛后立项。该阶段另建蓝本，不在本轮提前冻结实现 schema。

## 验收总门槛

- 语义：现有 golden 默认轨迹不变；新增能力有独立 fixture，不用 Jolt readback 自证。
- 实体：M0-M5 所有模拟参与者都是 Blender Objects；不在 solver 内创建隐藏实例实体。
- 事务：资产生成、body/constraint manifest 任一验证失败时零部分提交，旧 owner 可继续使用或明确冷重建。
- 生命周期：restart、same-frame、jump、rewind、delete、undo/load、Cache Delete 和 unregister 无陈旧 handle/对象 manifest。
- 性能：分别记录 native step、body sync、result publish、Object writeback 和 depsgraph；不能只报告 Jolt 内核时间。
- 可观测性：公开 result/debug/diagnostics 只含 stable identity 和普通值；调试关闭时没有额外 mesh 展开或 native readback。
- 双 ABI：py311/py313 使用同一 schema、fixture hash 和容差合同。

## 文档维护

- 资源导航是本文的永久内容；路径、版本或文档职责变化时同步更新，不得以“清理历史”为由删除。
- 本文不追加日期流水账或单次测试输出。
- 当前实现状态只在 `PHYSICS_WORLD_IMPLEMENTATION_STATUS.md` 保留一行摘要。
- 精确约束字段维护在 `PhysicsWorld/rigid/docs/CONSTRAINT_REFERENCE.md`。
- 精确世界设置维护在 `PhysicsWorld/rigid/docs/JOLT_SETTINGS_REFERENCE.md`。
- 测试数量、golden、命令和门禁维护在 `PhysicsWorld/rigid/docs/JOLT_TEST_STRATEGY.md`。
- 性能基线和优化顺序维护在 `JOLT_PERFORMANCE_OPTIMIZATION.md` 与 `JOLT_WRITEBACK_PERFORMANCE_BOUNDARY.md`。
- 构建兼容约束维护在 `_native/docs/JOLT_BLENDER_COMPAT.md`；自动化已经覆盖的手工 patch 流程不得复制到其它文档。
