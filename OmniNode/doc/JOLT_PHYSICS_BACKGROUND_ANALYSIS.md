# Jolt Physics 背景分析

本文面向 HoTools / OmniNode 后续刚体属性、刚体约束属性、debug 可视化和 Jolt binding 扩展设计。它回答四个问题：

- Jolt 能做什么。
- Jolt 需要吃什么数据。
- Jolt 能输出什么数据。
- Jolt 是怎样求解的，以及当前 HoTools 接入离完整能力还差什么。

结论先行：当前 `hotools_jolt` 已经证明 Jolt 可以在 Blender 进程里稳定运行，但现在只是“最小可运行刚体 backend”。Jolt 原生能力远大于当前 HoTools 属性和 binding 覆盖面。接下来不应该把 Jolt 内部类型直接暴露给节点图，而应该把 Jolt 稳定能力抽象成 HoTools 的持久化属性、spec 和 result stream，再由 Jolt adapter 映射。

## 资料来源与版本

本地源码版本：

- JoltPhysics：`v5.2.0`，本地源码位于 `_native/build/vs2022-py311/_deps/joltphysics-src`。
- 本地 binding：`_native/src/jolt_rigid.cpp`。
- Python adapter：`OmniNode/NodeTree/Function/physicsWorld/rigid/backends/jolt.py`。
- HoTools 刚体属性：`PhysicsTools/physicsProperty.py`、`PhysicsTools/physicsPanel.py`。
- 统一物理流程契约：`OmniNode/doc/PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`。
- Blender 兼容记录：`_native/JOLT_BLENDER_COMPAT.md`。

外部资料：

- Jolt GitHub / README：https://github.com/jrouwe/JoltPhysics
- Jolt 官方 API 文档：https://jrouwe.github.io/JoltPhysics/
- Jolt release docs：https://jrouwe.github.io/JoltPhysicsDocs/
- Godot Jolt 社区集成：https://github.com/godot-jolt/godot-jolt

## Jolt 的定位

Jolt 是游戏/VR 取向的 C++ 刚体物理和碰撞检测库。它的重点不是 DCC 编辑器语义，而是高性能 runtime physics：

- 多线程友好，支持模拟外并发读写和 collision query。
- 刚体为核心，同时提供软体、角色、车辆、ragdoll 等上层系统。
- 支持 deterministic simulation，但 determinism 依赖一致的输入、body/constraint 添加顺序、平台和配置。
- 所有对象通过 `PhysicsSystem` 管理；body 通过 `BodyInterface` 创建、添加、移动、施力、删除。
- 碰撞 shape 是 body 的核心数据，Jolt 会基于 shape 计算 bounds、质量、惯性、碰撞支持函数和 contact manifold。

对 HoTools 的意义：

- Jolt 适合作为统一物理世界里的 `rigid_body` backend。
- Jolt 的 soft body、vehicle、character 可以作为远期参考，但不应该抢在刚体属性、约束属性、debug/output 流之前接入。
- Jolt 的公开 API 不能直接成为 OmniNode 公共 schema；公共 schema 应该保持 HoTools 语义。

## 能力总览

### 刚体

Jolt body 的基本运动类型：

| 类型 | Jolt 语义 | HoTools 设计意义 |
|---|---|---|
| Static | 不参与动力学，通常是固定场景碰撞体 | 地面、墙、固定代理 |
| Dynamic | 由重力、力、碰撞、约束驱动 | 普通刚体、ragdoll body |
| Kinematic | 由用户设置速度/目标 transform 驱动，会推动 dynamic | 动画驱动体、骨骼/物体代理 |

刚体可配置的核心参数来自 `BodyCreationSettings.h`：

- 初始 `position`、`rotation`。
- 初始 `linear_velocity`、`angular_velocity`。
- `motion_type`：static / dynamic / kinematic。
- `motion_quality`：离散或线性 cast，用于高速物体 CCD。
- `allowed_dofs`：允许/锁定平移和旋转轴，可用于 2D 化或轴锁定。
- `friction`、`restitution`。
- `linear_damping`、`angular_damping`。
- `max_linear_velocity`、`max_angular_velocity`。
- `gravity_factor`。
- `allow_sleeping`。
- `is_sensor`。
- `collide_kinematic_vs_non_dynamic`。
- `use_manifold_reduction`。
- `apply_gyroscopic_force`。
- `enhanced_internal_edge_removal`。
- `num_velocity_steps_override`、`num_position_steps_override`。
- 质量和惯性策略：自动由 shape 计算、只覆写质量、或质量与惯性全手动提供。

运行中通过 `BodyInterface.h` 还能：

- 设置/读取 transform。
- 设置/读取线速度、角速度、点速度。
- 添加 force、torque、impulse、angular impulse。
- 切换 motion type、motion quality。
- 切换 shape、object layer、friction、restitution、gravity factor。
- 激活、休眠、重置 sleep timer。
- 获取 body user data、material、active 状态和 world transform。

当前 HoTools 已从最小字段扩展到：`body_type`、`mass`、`friction`、`restitution`、`rigid_collision_group` / `rigid_collides_with_groups`、基础 shape（sphere / capsule / box / plane / cylinder / tapered capsule / tapered cylinder）的尺寸、shape offset/local rotation、初始速度、阻尼、gravity factor、sleep、CCD、sensor、max velocity 和 allowed DOFs。runtime body control 已覆盖 velocity、force/torque、impulse/angular impulse、gravity factor、material response、motion quality 和 activation；仍未接入惯性全量覆写、shape material、advanced shape 和结构性 body update API。

### Shape

Jolt 原生 shape 覆盖面：

| 类别 | Shape | 设计备注 |
|---|---|---|
| 简单凸体 | sphere、box、capsule、cylinder、tapered capsule、tapered cylinder | HoTools 第一阶段应补齐 cylinder / convex radius / shape offset |
| 凸包 | convex hull | 适合 mesh 生成的动态代理，需 cook 顶点 |
| 平面/三角/mesh | plane、triangle、mesh | mesh 主要用于 static；dynamic mesh 需要手动质量/惯性，且不建议常用 |
| 地形 | height field | 适合 static terrain，不是普通 mesh collider 替代 |
| 组合 | static compound、mutable compound | 适合复杂刚体代理、ragdoll body、骨骼 collider 组合 |
| 装饰器 | scaled、rotated-translated、offset-center-of-mass | 对 HoTools 很关键：shape offset/rotation/COM offset 不应该靠改 Object transform 表达 |
| 空 shape | empty | 可作为 dummy body 或约束挂点 |

Jolt shape 重要约束：

- shape 会围绕 center of mass 工作，复杂 shape 创建后可能自动重心化。
- box、sphere 等凸体有 convex radius 概念，影响接触稳定和几何精度。
- 非均匀缩放、旋转后缩放、compound shearing 需要小心；Jolt 有 `ScaleShape` 规则，但不能随意把 Blender scale 直接塞进去。
- 动态 mesh 代价高，且 mesh 不提供可靠 inside/outside，容易卡住；只应作为高级选项。

当前 HoTools binding 只创建：

- `SphereShape(shape_radius)`
- `CapsuleShape(shape_half_height, shape_radius)`
- `CylinderShape(shape_half_height, shape_radius, shape_convex_radius)`
- `TaperedCapsuleShape(shape_half_height, shape_top_radius, shape_bottom_radius)`
- `TaperedCylinderShape(shape_half_height, shape_top_radius, shape_bottom_radius, shape_convex_radius)`
- `BoxShape(shape_half_extents)`
- `PlaneShape(local +Z normal, shape_plane_half_extent)`；HoTools 语义为局部 XY 平面、局部 Z 法线，PLANE 在 spec/native 层按 STATIC 处理。

当前 binding 已通过 `RotatedTranslatedShape` 接入 shape offset / local rotation。当前仍没有：

- box convex radius。
- convex hull / mesh / compound。
- scaled shape / COM offset。
- shape material。
- shape user data / sub shape ID 映射。

### 约束

Jolt 支持的主要 two-body constraint：

| 约束 | 原生能力 | 当前 HoTools binding |
|---|---|---|
| Fixed | 锁定相对位置和旋转；支持 world/local frame、auto detect point | 已接类型，但只传统一 anchor frame |
| Point | 锁定一个点，允许任意旋转 | 已接类型，但只传统一 anchor point |
| Distance | 点到点距离范围，支持 min/max 和 spring | 未接 |
| Hinge | 单轴旋转，支持角度 limit、limit spring、friction torque、motor | 已接类型，并已接基础 limit/friction/motor |
| Slider | 单轴平移，支持线性 limit、limit spring、friction force、motor | 已接类型，并已接基础 limit/friction/motor |
| Cone | 点约束 + swing cone angle | 已接类型，并已接 half cone angle |
| SwingTwist | 肩关节/球窝角限制，支持 normal/twist/plane half cone angle、twist min/max、friction、motor | 未接 |
| SixDOF | 每个平移/旋转轴自由、固定或限制；每轴摩擦、translation spring、每轴 motor | 未接；最适合作为“全面约束属性”的兜底 |
| Gear | 两个 hinge 角速度/角度关系 | 未接 |
| RackAndPinion | slider 与 hinge 的线性/旋转关系 | 未接 |
| Pulley | 两个点通过绳长比例约束 | 未接 |
| Path | 沿平滑路径约束，支持 path fraction 和 motor | 未接 |
| Vehicle | 车辆专用约束系统 | 未接，不建议近期混入通用刚体面板 |

所有 constraint 都继承 `ConstraintSettings` 的通用参数：

- `enabled`
- `constraint_priority`
- `num_velocity_steps_override`
- `num_position_steps_override`
- `draw_constraint_size`
- `user_data`

Breakable constraint 不是一个独立 Jolt setting。HoTools 已按 Jolt 建议在 adapter/solver 边界读取 constraint lambda / impulse，超过 `breaking_threshold` 时调用 `SetEnabled(false)`；这个字段是 HoTools policy，不是假装存在于 Jolt 的原生属性。

连接体之间是否互相碰撞不是 Jolt constraint 本身的字段。HoTools 的 `disable_collisions` 已映射到刚体 solver 私有的 pair filter：约束连接的两个 body 可以禁用直接碰撞，同时不影响它们与其他刚体的碰撞。

### Motor 和 Spring

Jolt 的 motor 通用结构是 `MotorSettings`：

- `motor_state`：off / velocity / position。
- spring：frequency+damping 或 stiffness+damping。
- force limit：线性 motor 用。
- torque limit：角 motor 用。
- target velocity / target position / target angle / target orientation 由具体 constraint 提供。

Jolt 的 spring 通用结构是 `SpringSettings`：

- `mode`：frequency+damping 或 stiffness+damping。
- frequency 或 stiffness。
- damping。
- frequency/stiffness <= 0 表示 hard limit。

HoTools 不应该给每个 constraint 单独发明不同命名。建议统一命名：

- `limit_spring_enabled`
- `spring_mode`
- `spring_frequency`
- `spring_stiffness`
- `spring_damping`
- `motor_state`
- `motor_target_velocity`
- `motor_target_position`
- `motor_force_limit`
- `motor_torque_limit`

具体 constraint 只决定这些字段的 axis 和单位。

### 碰撞过滤

Jolt 有两层过滤：

- `ObjectLayer` / `BroadPhaseLayer`：粗粒度，影响 broadphase。
- `CollisionGroup` / `GroupFilter`：细粒度，允许同组内 subgroup pair 控制。

当前 `jolt_rigid.cpp` 的 broadphase / object layer 仍只有两层：

- `NON_MOVING`
- `MOVING`

当前过滤规则：

- static-static 不碰。
- moving 与所有层碰。

HoTools 刚体自己的 1..16 `rigid_collision_group` 和 `rigid_collides_with_groups` mask 已通过自定义 `CollisionGroup` / `GroupFilter` 接入 native。当前策略是对称过滤：两个刚体都必须允许对方的刚体组，才会碰撞。它不复用简单碰撞、骨骼碰撞或 mesh collision 的 `primary_collision_group / collided_by_groups` 状态。约束级 `disable_collisions` 也在同一个 rigid group filter 内实现为 pair override，不污染 coarse object layer。

建议：

- `ObjectLayer` 先保持 coarse：static、dynamic/kinematic、sensor，必要时再扩展。
- 刚体 1..16 过滤组和可碰 mask 用自定义 pair filter 或 group filter 表达，命名空间独立于简单碰撞组。
- 约束连接体禁用碰撞由 `ConstraintSpec.disable_collisions` 驱动，在 native rigid pair table 中表达，避免污染全局 layer。

### 查询与事件

Jolt 可以做：

- Ray cast。
- Shape cast。
- Shape vs shape overlap。
- Broadphase-only AABB 类查询。
- Narrowphase 精确查询。
- Contact listener：validate、added、persisted、removed。
- Sensor trigger。
- Soft body contact listener。
- Body activation listener。
- Step listener。

Contact manifold 可提供：

- contact normal。
- penetration depth。
- sub shape IDs。
- contact points on body 1 / body 2。

注意：`OnContactAdded` 发生在 contact solver 前，真实 collision impulse 当时未知。若要做撞击音效/强度，需要估算或在 solver 后读其他累计数据。Constraint 的 lambda 可以在 update 后读取，适合做断裂阈值和 debug 强度。

当前 HoTools binding 已能在 Jolt update 后读取约束 current value 和 lambda；contact listener、sensor event 与 query API 仍未接入。

### 软体、角色、车辆、Ragdoll

Jolt 还提供：

- Soft body：edge、bend、tetra volume、tether、pressure、skinning 范围限制、与刚体碰撞。
- Character：rigid body character、virtual character。
- Vehicle：wheeled、tracked、motorcycle。
- Ragdoll：用 body + constraints + motor 驱动。

这些能力说明 Jolt 的上限很高，但对 HoTools 当前优先级来说：

- 近期重点应是通用刚体和约束，不要立刻接 Jolt soft body 替代 MC2。
- Ragdoll 可作为“骨骼刚体链 + 约束 + motor”的中期目标。
- Character / Vehicle 应该作为独立 domain，不能塞进普通刚体属性面板。

## Jolt 需要吃什么数据

### World 级输入

`PhysicsSystem::Init` 需要：

- `max_bodies`
- `num_body_mutexes`
- `max_body_pairs`
- `max_contact_constraints`
- broadphase layer interface
- object vs broadphase layer filter
- object layer pair filter

运行中还需要：

- gravity。
- physics settings：solver iterations、sleep settings、Baumgarte、speculative contact distance、penetration slop、CCD 参数、deterministic 开关等。
- temp allocator。
- job system。
- collision step/substep 数。

当前 HoTools：

- OmniNode adapter 默认 `max_bodies=1024`。
- OmniNode adapter 默认 `max_body_pairs=max_bodies * 4`。
- OmniNode adapter 默认 `max_contact_constraints=max_bodies * 2`。
- `JobSystemSingleThreaded`。
- gravity 默认 `(0, 0, -9.81)`；Python adapter 已接 `set_gravity()`，节点侧通过 `rigid_jolt.world_setting` 隐式对象热更新 Jolt 刚体世界 gravity 和构造期容量。
- `step(dt, substeps)` 从 `world.frame_context` 获取。

### Body 级输入

Body 创建最低需要：

- shape。
- position。
- rotation。
- motion type。
- object layer。

实用刚体还需要：

- mass / inertia。
- velocities。
- material response：friction / restitution。
- damping。
- gravity factor。
- CCD / motion quality。
- sleeping。
- DOF lock。
- sensor flag。
- rigid collision group / rigid collides-with mask。
- user data，用于从 native event 映射回 HoTools slot。

HoTools 当前 `RigidBodySpec` 已覆盖基础刚体输入：

- object pointer / data pointer。
- world transform 快照。
- body type、mass、friction、restitution。
- rigid collision group / rigid collides-with mask。
- sphere / capsule / box / plane / cylinder / tapered capsule / tapered cylinder 的基础 shape 参数。
- shape offset / local rotation。
- initial velocity、damping、gravity factor、sleep、CCD、sensor、axis locks。

下一步的输入补齐重点不再是基础 shape，而是高级 shape、惯性覆写、contact/query 输出和更完整的 material / body update API。节点侧 `rigid_body_commands` 已可通过 `world.exchange` 进入 rigid solver，并映射到底层 velocity / force / impulse / gravity factor / material response / motion quality / activate 控制 API。

### Constraint 级输入

Constraint 创建最低需要：

- constraint type。
- body A / body B。
- anchor frame 或 body-local frames。

实用 constraint 还需要：

- frame space：world / local-to-body-COM。
- point1/axis1/normal1 与 point2/axis2/normal2。
- limits。
- springs。
- friction。
- motors。
- priority。
- solver iteration override。
- enabled。
- break threshold policy。
- connected bodies collision policy。

HoTools 当前 constraint spec 覆盖：

- Empty 对象。
- constraint type。
- target A / target B。
- anchor transform 来自 Empty。
- `rigid.generated_constraint` 隐式对象生成的持久约束；它不创建 Empty，但会在 solver prepare 阶段转成同一类 `ConstraintSpec` slot。

当前 adapter 直接用 `ConstraintSpec.anchor_position` / `anchor_rotation_wxyz` 同时填 body1/body2 的 frame。它能跑基础 demo，但不能表达两个 body 的不同 local anchor，也不能表达 limit/motor。

### Per-frame 输入

每帧可变输入包括：

- `dt`、substeps、time scale。
- Kinematic body 的目标 position/rotation。
- Force / torque / impulse 命令。底层 API、`world.exchange` 命令流和第一批刚体命令节点已接入。
- Motor target。
- Constraint enable/break 状态。
- 动态切换 body motion type、shape、filter、sensor 等。

当前 HoTools 已支持节点侧向 `rigid_body_commands` 发布 velocity、force、impulse、gravity factor、material response、motion quality、active 命令，并由 rigid solver 翻译到 adapter。motor target、constraint enable/break 和 shape/filter/sensor 等结构性运行更新仍未形成正式节点流。

### Jolt 的隐式物理对象边界

Jolt 后续会需要大量“看起来像节点写入 solver 信息”的能力，例如批量生成约束、规则生成 ragdoll 关节、按命名规则给刚体设置 material preset、给一批约束设置 motor profile。它们本质是会参与刚体模拟的隐式对象，不能直接写 Jolt adapter、不能写 solver slot，也不应该塞进帧级 `exchange`。

统一约定：

- 持久或懒更新的刚体/约束对象进入 `world.implicit_objects`。
- 一次性命令进入 `world.exchange["rigid_body_commands"]`。
- 求解结果、contact、sensor、constraint lambda 进入 `world.result_streams`。
- Jolt native handle 只允许存在于 rigid solver slot 或 `backend_resources["rigid_solver"]` 内。

示例 tag：

```text
rigid.generated_constraint        # 规则/批量节点生成的持久约束对象
rigid.constraint_override         # motor、limit、break policy 等可懒更新对象
rigid.material_preset             # 刚体材质响应 preset 对象
rigid_jolt.world_setting          # Jolt 刚体世界 gravity、max bodies/pairs/contact constraints 等 world 级对象
```

示例链路：

```text
Physics World Begin
  -> 刚体约束-批量生成写入世界
  -> 刚体材质Preset-写入世界
  -> 刚体模拟步
  -> Physics Writeback
  -> Physics World Commit
```

`physicsRigidSolver` 在 prepare 阶段读取声明的 `implicit_objects` tag，合并到 `RigidBodySpec` / `RigidConstraintSpec` 或 adapter sync plan，再按 signature/version 决定增量更新或重建。这样批量约束和 preset 是持久懒更新对象，不会被误解成每帧事件。

写回顾虑：Jolt 后续可能会有批量生成的虚拟刚体、虚拟约束或 attachment，它们在 solver 内会有 transform / anchor 结果，但不一定对应真实 Blender `Object`。这类隐式对象默认只能进入 solver 和 debug/export；如果要写回 Blender，必须在 result stream 中显式声明真实 owner resolver，不能因为 payload 长得像内置物体就让 Physics Writeback 静默写回。

## Jolt 能输出什么

### 当前已输出

当前 `hotools_jolt` / adapter 输出：

- `step_ms`。
- `body_count`。
- `constraint_count`。
- body state：position、rotation、linear velocity、angular velocity、active、sleeping。
- constraint state：enabled、current value kind/value、position/rotation/limit/motor lambda 与聚合峰值。

当前写回机制：

- `physicsRigidSolver()` 只 step，不直接写 Blender。
- solver 每帧把 body state 纯快照发布到 `world.result_streams["rigid_transform"]`。
- solver 每帧把 constraint state 纯快照发布到 `world.result_streams["rigid_constraint_state"]`；lambda 是上一物理步求解冲量，不是力或扭矩，断裂阈值必须按该单位定义。
- solver 每次调用把统计快照发布到 `world.result_streams["rigid_solver_stats"]`，包括 body/constraint 数量、step 时间、dt/substeps、same-frame/restart 状态、transform 输出数量、命令消费数量和错误计数。
- 下游 `Physics Writeback` 统一写 `Object.delta_location / delta_rotation_euler`。
- `Jolt刚体可视化调试` 优先消费 `rigid_transform` result，因此可以显示求解后刚体位置，而不依赖 Blender 增量写回是否已经执行。
- `physicsRigidReadState` 直接从 `rigid_transform` result 向节点图输出位置、旋转、速度、active 和 sleeping 状态。
- `physicsRigidConstraintReadState` 从 `rigid_constraint_state` 输出 Hinge 当前角度、Slider 当前位置、Distance 当前锚点距离，以及各类 lambda。
- `physicsWorldResultStream` 可直接观察 `rigid_transform` / `rigid_constraint_state` / `rigid_solver_stats` 等 channel；后续 contact 和 query 也应按同一模式输出。
- `JoltAdapter.writeback_transforms()` 只保留为 deprecated no-op，不能重新引入直接写 `Object.location` 的路径。

### 迁移其它 solver 前的 Jolt 状态判断

Jolt 现在已经足够作为“统一物理世界 vertical slice”的样板：它证明了 scope/spec/backend/result/writeback/debug/cache owner 这条链路能跑通。继续补 contact listener、query、breakable policy 和 advanced shape 会提升刚体能力，但不是 SpringBone/MC2/BoneCloth 迁移的前置条件。

其它 solver 迁移前还缺的是工程验收，而不是 Jolt feature：

- 真实 Cache Delete / `OmniRuntimeState.clear_all()` background smoke 已补：测试通过真实 runtime cache replace/mutate、delete 和 clear_all 路径验证 Jolt world dispose 与 writeback delta 归零。
- 帧语义矩阵已补连续帧、same-frame、跳回首帧、reset、scope prune、静态/运动学 transform dirty、shape dirty 和 constraint target dirty 的专门 smoke。
- 需要 PoseBone 和 mesh delta 的统一 writeback contract，因为 SpringBone/MC2 不写 Object.delta。
- 需要第一条非 Jolt solver 的窄切片，把 result stream 和 solver slot 用起来。

因此下一步应转向“SpringBone VRM world-aware rewrite vertical slice”，而不是继续把 Jolt Phase 5 扩成全功能刚体系统。SpringBone 旧 `_SpringBoneVRM` 只作为审查和数值参考；新路径应从 `physicsWorld/spring_vrm/` 的 spec / slot / result stream / writeback contract 直接重写。新迁移 solver 默认只保留 C++ / native 计算路径，Python 不再维护第二套运行时算法。

### 核心输出状态

建议下一批补：

- body type / shape type / bounds。
- constraint current value：hinge angle、slider position、distance 已接；6DOF limits 状态待约束类型接入。
- constraint lambda / impulse 已接，用于 debug 和 breakable constraint。
- contact list：body pair、normal、penetration、points、state added/persisted/removed。
- sensor event。
- query result：ray/shape cast hit body、point、normal、fraction、subshape。

这些输出不应直接写到 Blender 自定义属性里。推荐写入 `world.result_streams` 或 `world.exchange`，再由：

- Jolt 自有 debug draw 节点消费。
- Physics Writeback 消费。
- bake/export 消费。
- event/hack 规则节点消费。

## Jolt 怎么算

`PhysicsSystem::Update(dt, collision_steps, allocator, job_system)` 的大致流程：

1. 执行 step listener。
2. 找 active body / active constraints。
3. broadphase 找候选 body pair。
4. narrowphase 生成 contact manifold。
5. contact listener validate / added / persisted / removed。
6. 根据 contact 和 constraint 构建 simulation islands。
7. 速度约束求解。
8. integrate velocity。
9. CCD body 做 linear cast / TOI 处理。
10. 位置约束求解。
11. 更新 broadphase bounds。
12. 根据 sleep 规则休眠 island。

`collision_steps` 是 Jolt update 内的碰撞步数，HoTools 当前用 `world.frame_context.substeps` 传入。它不是简单“多次外部 step 循环”的同义词，但效果上都是把一帧 dt 切成更稳定的物理推进。

求解稳定性受以下因素影响：

- dt 和 substeps。
- velocity / position solver iterations。
- shape 类型和 convex radius。
- mass ratio。
- constraint priority。
- contact cache / manifold reduction。
- sleeping。
- CCD motion quality。
- dynamic mesh / heightfield 使用方式。

## 当前 HoTools 接入状态

### Native binding

`_native/src/jolt_rigid.cpp` 暴露：

```text
JoltWorld(max_bodies, max_body_pairs, max_contact_constraints)
add_body(body_type, mass, friction, restitution, position, rotation_wxyz,
         shape_type, shape_radius, shape_half_height, shape_half_extents,
         shape_plane_half_extent,
         collision_group, collided_by_groups,
         shape_offset, shape_rotation_wxyz,
         linear_velocity, angular_velocity, damping, gravity, sleep, CCD,
         sensor, allowed_dofs, ...)
remove_body(handle)
set_kinematic_transform(handle, position, rotation_wxyz, dt)
set_body_velocity(handle, linear_velocity, angular_velocity)
add_body_force(handle, force, torque)
add_body_impulse(handle, impulse, angular_impulse)
set_body_gravity_factor(handle, gravity_factor)
set_body_material_response(handle, friction, restitution)
set_body_motion_quality(handle, motion_quality)
activate_body(handle, active)
get_body_transform(handle)
get_body_state(handle)
add_constraint(constraint_type, body_a_handle, body_b_handle, anchor_pos, anchor_rot_wxyz,
               solver overrides, limit/spring, friction, motor, cone angle,
               disable_collisions)
remove_constraint(handle)
step(dt, substeps)
body_count
constraint_count
set_gravity(gravity)
clear()
```

Native 侧当前特点：

- `JobSystemSingleThreaded`，适合 Blender 进程集成初期。
- Z-up，gravity 默认 `(0, 0, -9.81)`。
- broadphase/object layer 只有 moving/non-moving。
- static-static 不碰。
- 支持固定到 world：`WORLD_HANDLE = 0xFFFFFFFF`。
- 约束当前创建 fixed/hinge/slider/cone/point，并已接 Hinge/Slider 基础 limit/friction/motor、Cone half angle、通用 solver overrides。
- 没有 contact listener。
- 没有 debug draw API。
- 已有 body state getter 和 body 控制 API：set velocity、add force/torque、add impulse/angular impulse、gravity factor、friction/restitution、motion quality、activate/deactivate。
- HoTools collision group / mask 已接入 Jolt `CollisionGroup` / 自定义 `GroupFilter`。
- 运行时控制 API 已覆盖 velocity / force / impulse / material response / gravity factor / motion quality / activation；shape、mass、motion type 等结构性参数变化仍靠 remove + add。

### Python adapter

`JoltAdapter` 负责：

- 懒加载 `hotools_jolt`。
- 管理 slot id 到 native handle。
- restart/generation 变化时 clear。
- 从 `RigidBodySpec` / `ConstraintSpec` 快照同步 body / constraint。
- 从 `rigid_jolt.world_setting` 隐式对象同步 Jolt 刚体世界 gravity；容量字段映射到 `JoltWorld(max_bodies, max_body_pairs, max_contact_constraints)`，签名变化会重建 JoltAdapter。
- update kinematic。
- step。
- 输出 body transform 给统一 Physics Writeback。

需要修正或设计决策的点：

- `world.begin` 每次都重采集 spec；slot 使用 sync signature 判断参数/形状/约束是否需要重新同步 Jolt。
- `same_frame` 不重复推进 Jolt step，但允许脏 spec 或 kinematic pose 执行无时间推进的 backend sync。
- adapter 只消费 `RigidBodySpec` / `ConstraintSpec` 内的 `world_position`、`world_rotation_wxyz`、anchor 和 shape 快照；不再回读 Object / Empty。
- `rigid_collision_group` / `rigid_collides_with_groups` 已进 spec，并由 adapter 映射到 Jolt/native 的 `CollisionGroup` 参数。
- sync 策略目前每次 sync 旧 body 都 remove + add；后续需要区分 topology/config rebuild 与 runtime value update。

### HoTools 属性面板

当前 `PG_Hotools_RigidBody`：

- enabled。
- body_type。
- mass。
- friction。
- restitution。
- rigid_collision_group / rigid_collides_with_groups。
- shape_type：sphere / capsule / box / plane / cylinder / tapered capsule / tapered cylinder。
- shape_radius。
- shape_half_height。
- shape_half_extents。
- shape_plane_half_extent：Jolt PlaneShape broadphase/debug half extent。
- shape_top_radius / shape_bottom_radius：tapered shape 两端半径。
- shape_convex_radius：cylinder / tapered cylinder 的 Jolt convex radius。
- shape_offset / shape_rotation。
- initial linear/angular velocity、damping、gravity factor、sleep、CCD、sensor、axis locks。

当前 `PG_Hotools_RigidConstraint`：

- enabled。
- constraint_type：fixed / hinge / slider / cone / point。
- target_a。
- target_b。
- solver overrides、limit/spring、friction、motor、cone half angle。
- target_b。

这只是 Jolt 能力的基础子集。

### Blender 兼容约束

`_native/JOLT_BLENDER_COMPAT.md` 记录了关键限制：

- Blender 进程里的 `tbbmalloc_proxy.dll` 会干扰 MSVCP140 STL mutex/TLS。
- 本地 Jolt patch 用 Win32 `CRITICAL_SECTION` / `SRWLOCK` 替代部分 mutex。
- `std::call_once` 已改为 atomic init。
- `JPH_DEBUG_RENDERER` 和 `JPH_PROFILE_ENABLED` 被禁用。
- AVX / AVX2 被禁用，避免 Python 调用栈对齐问题。

因此 HoTools 的 debug 可视化不要依赖 Jolt 原生 `DebugRenderer`。应该由 native 输出 body/shape/constraint/contact 的简化 debug primitives，再用 HoTools 现有 overlay 绘制。

## 属性迁移建议

### 第一批：刚体基础属性

这些应尽快搬进 `PG_Hotools_RigidBody`、`RigidBodySpec`、native `add_body()`：

| 属性 | Jolt 字段/API | 推荐 HoTools 字段 | 优先级 | 备注 |
|---|---|---|---|---|
| 初始线速度 | `mLinearVelocity` | `linear_velocity` | P0 | 动态刚体初始状态和 bake 必需 |
| 初始角速度 | `mAngularVelocity` | `angular_velocity` | P0 | 单位 rad/s |
| 线阻尼 | `mLinearDamping` | `linear_damping` | P0 | 默认 0.05 |
| 角阻尼 | `mAngularDamping` | `angular_damping` | P0 | 默认 0.05 |
| 重力倍率 | `mGravityFactor` | `gravity_factor` | P0 | 0 可做漂浮/无重力 |
| 允许睡眠 | `mAllowSleeping` | `allow_sleeping` | P0 | debug 时可关闭 |
| CCD | `mMotionQuality` | `motion_quality` | P0 | DISCRETE / LINEAR_CAST |
| 最大线速度 | `mMaxLinearVelocity` | `max_linear_velocity` | P1 | 防爆炸 |
| 最大角速度 | `mMaxAngularVelocity` | `max_angular_velocity` | P1 | 防爆炸 |
| Sensor | `mIsSensor` | `is_sensor` | P1 | trigger/debug event |
| Kinematic 碰静态 | `mCollideKinematicVsNonDynamic` | `collide_kinematic_vs_static` | P1 | sensor/大触发器谨慎使用 |
| Manifold reduction | `mUseManifoldReduction` | `use_manifold_reduction` | P2 | 高级 debug |
| Gyroscopic force | `mApplyGyroscopicForce` | `apply_gyroscopic_force` | P2 | 旋转真实感 |
| Internal edge removal | `mEnhancedInternalEdgeRemoval` | `enhanced_internal_edge_removal` | P2 | mesh/地形上滑动 |
| Solver steps override | `mNumVelocityStepsOverride` / `mNumPositionStepsOverride` | `solver_velocity_steps_override` / `solver_position_steps_override` | P2 | 局部增强稳定性 |
| DOF lock | `mAllowedDOFs` | `lock_linear_*` / `lock_angular_*` 或 `allowed_dofs` | P2 | 2D/轴锁 |
| 质量策略 | `mOverrideMassProperties` | `mass_mode` | P2 | dynamic mesh/精确惯性需要 |
| 惯性倍率 | `mInertiaMultiplier` | `inertia_multiplier` | P2 | 快速调手感 |

### 第一批：Shape 基础属性

| 属性 | Jolt 能力 | 推荐优先级 | 备注 |
|---|---|---|---|
| shape offset | `RotatedTranslatedShape` | P0 | 现在只能中心对齐，无法表达偏心 collider |
| shape rotation | `RotatedTranslatedShape` | P0 | capsule/box 方向必须可调 |
| convex radius | cylinder/tapered cylinder 已接；box/convex hull 未接 | 部分已接 | 稳定性和精度调节 |
| cylinder | `CylinderShape` | 已接 | 常见刚体形状，但 Jolt 文档提示 cylinder 稳定性较差 |
| tapered capsule/cylinder | `TaperedCapsuleShape` / `TaperedCylinderShape` | 已接 | 两端半径可不同的基础凸体，局部 Y 为高度方向 |
| plane | `PlaneShape` | 已接 | 静态地面/无限平面；当前 PLANE 按 STATIC 处理，使用 `shape_plane_half_extent` 控制 broadphase/debug 范围 |
| compound shape | `StaticCompoundShape` | P1 | 多 collider 刚体、ragdoll proxy |
| convex hull | `ConvexHullShape` | P2 | 从 mesh 生成动态代理 |
| mesh shape | `MeshShape` | P2 | 静态场景碰撞；dynamic 需强警告 |
| height field | `HeightFieldShape` | P3 | terrain 专用 |
| center of mass offset | `OffsetCenterOfMassShape` | P2 | 车辆/稳定站立体 |

### 第一批：约束属性

先补当前已有 constraint 类型的真实参数：

| 类型 | 应补属性 | 优先级 |
|---|---|---|
| 通用 | enabled、priority、solver step override、breakable、break threshold、disable connected collision | P0 |
| 通用 anchor | use_world_space、auto_detect_point、point1/point2、axis/normal per body | P0 |
| Hinge | limit enabled、limit min/max、friction torque、motor state、target angle、target angular velocity、motor torque limits、spring | P0 |
| Slider | limit enabled、limit min/max、friction force、motor state、target position、target velocity、motor force limits、spring | P0 |
| Cone | half cone angle | P0 |
| Distance | min distance、max distance、spring | 已接 |
| Point | point1/point2 separate anchors | P1 |
| Fixed | auto detect / separate frames | P1 |
| SixDOF | per-axis free/fixed/limited、limits、friction、motors | P1 |
| SwingTwist | twist/swing limits、friction、motor | P2 |

建议新增 constraint 类型：

- `DISTANCE`：非常便宜且对链条/绳/弹性连接有用。
- `SIX_DOF`：作为高级用户和程序化生成的通用约束。
- `SWING_TWIST`：给 ragdoll/肩关节。

### World/debug 属性

World 级建议：

- gravity。
- time scale。
- substeps。
- velocity solver iterations。
- position solver iterations。
- sleep time / sleep threshold。
- deterministic simulation。
- broadphase optimize trigger。
- max bodies / body pairs / contact constraints。

Debug 建议：

- draw body shape wire。
- draw body COM。
- draw velocity vector。
- draw sleeping/active color。
- draw sensor volume。
- draw constraint frame。
- draw constraint limits。
- draw contacts：normal、penetration、contact points。
- draw error/lambda heatmap。
- print body/constraint/contact counts and step timing。

由于 `JPH_DEBUG_RENDERER` 被禁用，debug primitives 应由我们自己导出：

```text
RigidDebugFrame
  bodies: [slot_id, type, active, transform, shape_desc, com, velocity]
  constraints: [slot_id, type, frame_a, frame_b, limits, lambda]
  contacts: [body_a, body_b, normal, depth, points, state]
  stats: [body_count, active_count, constraint_count, contact_count, step_ms]
```

HoTools overlay 的 draw store 也应保持同样规则：它由 Jolt 自有 debug draw 节点执行时生成纯快照，不保存 live `bpy` 对象、spec 引用或 `matrix_world`。视口 draw handler 只能消费快照坐标、类型和调试参数。这样 debug 结果才能准确表达节点链路中该节点所在阶段，而不是表达后续 Blender 依赖图或手动编辑后的状态。

## 推荐实现路线

### 阶段 1：把当前属性正规化进 spec

目标：

- `RigidBodySpec` 包含 shape 字段，不再由 adapter 回读 Blender 属性。
- `ConstraintSpec` 包含 anchor frame、target、基础通用字段。
- transform 改为读取 `matrix_world`，并明确输出/写回的 local/world 策略。
- `rigid_collision_group` / `rigid_collides_with_groups` 已接入最小过滤；`ConstraintSpec.disable_collisions` 已接入约束连接体 pair override。

这一步不要求增加很多 Jolt 能力，但能把架构方向摆正。

### 阶段 2：补 body 参数和 native ABI

目标：

- 扩展 `add_body()` 参数或改为结构化参数。
- 接入 velocity、damping、gravity factor、sleep、CCD、sensor、max velocity。
- 已增加 getter：transform + velocity + active state。
- 已增加 runtime body control：velocity、force/torque、impulse/angular impulse、gravity factor、friction/restitution、motion quality、activate/deactivate。

注意：nanobind 函数参数继续线性增长会失控。建议 native 侧引入 `BodyDesc` 风格结构或 Python dict 解析层。

### 阶段 3：补约束参数

目标：

- 先补 hinge/slider/cone 的真实参数。
- 已新增 distance，并贯通显式属性、生成约束、spec、adapter 与 native binding。
- 新增 generic sixdof。
- 已导出 constraint lambda / current angle / current position。
- 已实现 breakable policy。

### 阶段 4：debug 与事件

目标：

- 实现 native contact listener，但只缓存轻量 event，不在 callback 里碰 Blender。
- 每帧输出 debug snapshot。
- HoTools overlay 消费 debug primitives。
- 增加 sensor event channel。

### 阶段 5：高级 shape 和生成器

目标：

- compound shape。
- convex hull。
- mesh static collider。
- shape cook/cache key。
- 从现有 `hotools_object_collision` / bone collider 生成 compound rigid proxy。

## 关键设计风险

### 不要让 adapter 重新回读 Blender

当前基础 shape 和 transform 已进入 spec，adapter 主路径消费 spec 快照；这是正确方向。后续新增 Jolt 输入时必须继续走 HoTools property -> spec -> adapter 映射，不能把新字段临时塞回 `JoltAdapter` 里直接读 `bpy` 对象，否则 debug、export、bake 和 headless 测试都会重新变得不可检查。

### 不要把 Jolt enum 直接暴露成公共协议

HoTools 公共属性可以接近 Jolt，但命名应保持领域语义。例如 `motion_quality=DISCRETE/CCD` 比 `EMotionQuality::LinearCast` 更适合 UI；adapter 内再映射。

### 约束 frame 必须认真设计

只用一个 Empty transform 同时作为 body A/B frame，对简单 world anchor 可跑，但表达不了局部铰链、非对称约束、COM offset 后的正确 frame。应支持：

- world anchor 自动转换到 body local。
- 显式 local anchor A/B。
- auto detect point。
- axis/normal 可视化。

### 刚体 collision group 必须独立持有

Object/Bone/Mesh 的简单碰撞组服务于 cloth / spring / collider snapshot，是外部碰撞输入语义；刚体 collision group 服务于 Jolt 刚体之间的 pair filter，是刚体 solver 私有输入。两者可以共享 1..16 的交互习惯和按钮 UI，但不能共享同一份属性状态。跨 solver 交互（例如 cloth 读取 rigid body collider）应通过显式 bridge/result channel 映射，而不是让 rigid 直接复用 `hotools_object_collision` 的组字段。

### DebugRenderer 不可作为依赖

本地 Blender 兼容 patch 已经禁用 Jolt debug renderer。HoTools debug 应该使用 native snapshot + Python overlay。

## 给下一步设计的最小字段清单

如果现在要“赶快把 Jolt 支持的基础属性变量全部搬过来”，建议先按这个最小集落地：

`PG_Hotools_RigidBody`：

```text
enabled
body_type
mass
friction
restitution
rigid_collision_group
rigid_collides_with_groups
shape_type
shape_radius
shape_half_height
shape_half_extents
shape_plane_half_extent
shape_offset
shape_rotation
linear_velocity
angular_velocity
linear_damping
angular_damping
gravity_factor
allow_sleeping
motion_quality
max_linear_velocity
max_angular_velocity
is_sensor
lock_linear_x/y/z
lock_angular_x/y/z
```

`PG_Hotools_RigidConstraint`：

```text
enabled
constraint_type
target_a
target_b
disable_connected_collision
breakable
breaking_threshold
priority
solver_velocity_steps_override
solver_position_steps_override
anchor_mode
local_point_a
local_point_b
axis
normal
limit_enabled
limit_min
limit_max
limit_spring_enabled
spring_mode
spring_frequency
spring_stiffness
spring_damping
friction_force
friction_torque
motor_state
motor_target_position
motor_target_velocity
motor_force_limit
motor_torque_limit
cone_half_angle
distance_min
distance_max
sixdof_linear_mode_x/y/z
sixdof_angular_mode_x/y/z
sixdof_linear_limit_min/max
sixdof_angular_limit_min/max
```

Native output first batch：

```text
get_body_state(handle) -> transform, velocities, active/sleeping
get_constraint_state(handle) -> current value, lambda, enabled
get_debug_snapshot() -> bodies, constraints, contacts, stats
```

这批字段足以覆盖 Jolt 的基础刚体和常用约束能力，并为 debug 可视化、断裂、传感器、事件流和后续 sixdof/ragdoll 铺路。
## 2026-07-07 追加：Rigid/Jolt 声明状态

`RIGID_SOLVER_DECLARATION` 已落在 `physicsWorld/declarations.py`，并由 `physicsWorld/rigid/declaration.py` 重导出。

关键边界：`rigid_jolt` 消费刚体/约束 slot 与 `rigid_body_commands`，输出 `rigid_transform` / `rigid_constraint_state` / `rigid_solver_stats`，写回统一走 `physicsWorld.writeback -> Object.delta_transform`。

`physicsWorld/rigid/names.py` 中的 `rigid.generated_constraint` 已由刚体 solver 消费：`刚体生成约束属性 -> 刚体生成约束注册` 会写入 `world.implicit_objects`，solver prepare 会转成普通 `ConstraintSpec` slot，并在同帧禁用时移除 slot/native constraint。

`rigid_jolt.world_setting` 已接入第一批 Jolt 刚体世界级能力：`刚体世界-Jolt设置属性 -> 刚体世界-Jolt设置注册` 写入 gravity、max bodies、max body pairs 和 max contact constraints。rigid solver 在同步 body/constraint 前调用 `JoltAdapter.set_gravity()`；容量签名变化会重建 JoltAdapter 并重新同步刚体/约束。这让零重力、横向重力、恢复默认重力和 JoltWorld 容量上限都可以作为跨帧 Jolt 刚体世界配置表达，而不是临时 frame command。

刚体/Jolt 从 object scope 自动收集 `RigidBodySpec` / `ConstraintSpec` 的逻辑已从 `physicsWorld/world.py` 下沉到 `physicsWorld/rigid/scope_sync.py`，并由 `rigid.SOLVER_MODULE` 暴露为 registry scope hook。Physics World Begin 只调用 `physicsWorld/registry.py`，不再直接点名 Jolt/rigid；Jolt 冷启动前清理动态刚体 Object delta 也作为 rigid 的 `scope_restart_handlers` 执行。rigid 的 solver declaration 也由 `SOLVER_MODULE.declaration` 汇入 registry，再由 `physicsWorld/declarations.py` 做兼容汇总。

公共 `physicsWorld/names.py`、`physicsWorld/declarations.py` 和根级 `physicsWorld/__init__.py` 对 rigid/Jolt 自有名称、能力表和声明已改为兼容惰性导出；只有实际访问 `RIGID_*` / `JOLT_*` 符号时才进入 rigid 子模块，公共包导入阶段不再主动拉起 Jolt 私有实现。

`rigid.material_preset`、`rigid.ragdoll_proxy` 仍是 planned implicit object tag，当前只占位，不被 solver 消费。

后续重点：完善刚体属性/约束 spec、runtime cache 生命周期 smoke，以及 contact/query/advanced shape 能力。

## 2026-07-10 追加：Rigid/Jolt 原子化收口

Rigid/Jolt 的 solver 子模块入口已从公共注册层收口到 `rigid.SOLVER_MODULE`：descriptor 现在声明 `nodes`、`capabilities`、`debug_draw_modes`、`declaration`、`scope_restart_handlers` 和 `scope_collectors`。`OmniNodeRegister.py` 不再直接导入 `physicsWorld.rigid.nodes`，而是通过 `physicsWorld/registry.py` 的 solver node loader 装载内置 solver 节点模块。

`registry.py` 现在同时提供 capability/debug draw mode 汇总和基础冲突检查，覆盖 solver id、slot kind、result channel、implicit object tag 与 debug draw mode id。为兼容后台测试和未来部分装载器先注册空包的场景，registry 在发现 solver 包已存在但缺少 `SOLVER_MODULE` 时，会补载该包的 `__init__.py`，保证 rigid scope collector 仍能被 Begin 阶段发现。

验收状态：`test_blender_rigid.py` 后台集成测试 20/20 通过，覆盖 Jolt adapter、world 生命周期、命令 exchange、world setting 隐式对象、完整 60 帧刚体链路、runtime cache dispose、same-frame/frame-jump/reset、scope prune、transform/shape/constraint dirty resync、Distance 约束和 generated constraint 隐式对象链路。

## 2026-07-10 追加：Distance 约束切片

`DISTANCE` 已作为第六种刚体约束类型接入。持久化属性和生成约束节点都提供 `distance_min` / `distance_max`，范围会在进入 `ConstraintSpec` 前归一化为非负升序值；`limit_spring_frequency` / `limit_spring_damping` 直接映射到 Jolt `DistanceConstraintSettings.mLimitsSpringSettings`。

链路覆盖 `PG_Hotools_RigidConstraint -> ConstraintSpec -> scope sync signature -> JoltAdapter -> hotools_jolt`，生成约束也把距离范围纳入 payload、signature 和 materialized slot。native 对未知 constraint type 现在显式报错，不再静默退化成 Point。

验收状态：`hotools_jolt` Release 单目标构建通过；native 测试 26/26 通过；Blender 刚体后台集成测试 20/20 通过。下一步约束侧优先级是分离的 body A/B anchor frame、constraint state/lambda 输出和 breakable policy，再考虑 SixDOF。

## 2026-07-10 追加：Constraint state / lambda 结果流

native `get_constraint_state(handle)` 已覆盖当前六种约束。Hinge 输出当前角度，Slider 输出当前位置，Distance 输出两个实际锚点的当前距离；Fixed、Hinge、Slider、Cone、Point、Distance 分别读取其可用的 position / rotation / limit / motor lambda。adapter 将向量 lambda 保留为三元组，并给出 `lambda_max_abs` 作为调试与断裂策略的统一比较值。

solver 每次新帧 step 或 same-frame 结果重发都会发布 `world.result_streams["rigid_constraint_state"]`。结果只包含 slot/owner 标识和普通数值，不包含 Jolt constraint handle。显式 Empty 可通过 `physicsRigidConstraintReadState` 读取；生成约束可按 slot id 或通用 result stream 节点读取。

lambda 是 Jolt 上一物理步为满足约束施加的冲量。后续 `breaking_threshold` 不能把它命名或解释为力阈值；若 UI 需要力近似值，必须显式除以 dt 并使用独立字段。

验收状态：`hotools_jolt` Release 单目标构建通过；native 测试 27/27、legacy binding 12/12、Blender 刚体后台集成测试 21/21 通过。

### Breakable policy

`breakable` / `breaking_threshold` 已进入显式约束属性、`ConstraintSpec`、生成约束 payload/signature 和 scope sync signature。`breaking_threshold` 明确定义为“单个 Jolt update 后的约束冲量阈值”；solver 只在真实 step 后比较 `lambda_max_abs > breaking_threshold`，same-frame 重发不重复执行断裂判定。

超过阈值时 adapter 调用 native `set_constraint_enabled(false)`，slot 记录 `_jolt_broken` 与实际 `breaking_impulse`，随后 `rigid_constraint_state` 发布 `broken=True`、`enabled=False`。spec 签名或 generation 变化会重新创建约束并清除断裂状态。

断裂时如果约束配置了 `disable_collisions`，native 会同步撤销这条约束持有的 pair-filter 引用，使两个已分离刚体恢复碰撞；重新启用约束会重新应用过滤。配置状态和当前 pair-filter 应用状态分开保存，保证多约束引用计数、重复 disable/re-enable 与 remove 生命周期一致。

当前约束侧下一优先级是分离的 body A/B anchor frame，再考虑 SixDOF。contact listener 与 query API 可独立并行推进。
