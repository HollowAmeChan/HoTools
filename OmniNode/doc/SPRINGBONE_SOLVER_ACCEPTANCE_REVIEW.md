# SpringBone Solver 蓝本验收报告

日期：2026-07-10

基线：`main@b296691` 加 SpringBone 旧路径删除与 solver 属性原子化

环境：Blender 4.5.0 / CPython 3.11 / Windows / Release native backend

## 验收结论

当前结论：**旧 SpringBone 运行路径删除通过；solver 蓝本原子化仅条件通过，尚不能宣告完全收口。**

发布验证覆盖 Blender 4.5 / CPython 3.11、独立 CPython 3.13 native ABI、1/8/32 armature 扩展曲线和 off/one-shot/continuous debug capture 性能矩阵。

最终收口后的唯一运行链路是：

```text
VRM骨链属性 / 骨骼碰撞覆写属性
  -> PhysicsWorldCache.implicit_objects
  -> spring_vrm solver slot
  -> hotools_native spring_vrm context API
  -> bone_transform batch result
  -> physicsWorld.writeback
```

本轮完成的结构性收口：

| 项目 | 最终状态 |
|---|---|
| Python 旧节点 | `springBoneVRMChainSetting`、`springBoneVRM`、`springBoneVRM_CPP`、`springBoneBase` 已删除 |
| Python 旧 runtime | `_SpringBoneVRM`、`_SpringBoneVRMCppBackend`、旧 cache/scene scan/inline writeback 已删除 |
| Native 旧 ABI | 35 参数 `solve_spring_bone_vrm_cpp` binding、公开 `SpringBoneVrmChainView` 与 C++ wrapper 已删除 |
| Native 唯一入口 | `spring_vrm_create_context/update_dynamic/reset_state/step/read_results/read_debug` |
| 显式属性所有权 | `spring_vrm/capabilities.py` 持有字段 schema，`spring_vrm/properties.py` 生成 Blender RNA |
| 属性注册权 | `physicsWorld.registry` 统一注册/注销 solver 声明的 class 与 `Bone.hotools_collision` binding |
| 数据兼容 | 保留 `Bone.hotools_collision` 存储名，现有 `.blend` 字段路径不变；不保留旧 solver 调用兼容层 |

## 2026-07-10 破坏性变更独立复审

复审对象：`610bdce refactor(spring-vrm): remove legacy solver paths`。该提交跨越旧 Python 节点/runtime、Native ABI、PhysicsTools RNA、Physics World registry、MC2 BoneCloth/MeshCloth 和通用写回/烘焙工作流，因此本节覆盖并修正本报告此前的“最终通过”结论。

复审结论：**条件通过旧路删除，不通过“SpringBone 已成为可复制的 solver 原子蓝本”这一更高门槛。** 没有发现仍可执行的旧 SpringBone Python/C++ 入口，也没有发现 `.blend` 显式属性数据丢失；但存在 4 个 P1 收口阻断项和 3 个 P2 治理/覆盖缺口。修复 P1 并重新跑通跨系统矩阵前，不应继续推进以 SpringBone 当前实现为模板的其它 solver 原子化。

### 阻断项与缺口

| ID | 严重度 | 发现 | 影响与必须动作 |
|---|---|---|---|
| R-01 | P1 | `spring_vrm/nodes.py` 把 capability RNA 的 `soft_max` 直接写成节点 Float socket 的 `max_value`：radius 从旧节点允许的 `10.0` 收紧为 `1.0`，length 从 `10.0` 收紧为 `2.0`；`FunctionNodeCore.py` 会直接 `setattr(sock, "max_value", value)`。 | Blender socket 的 `max_value` 是硬限值，导致隐式覆写无法表达显式 `Bone.hotools_collision` 仍可保存的合法大值，破坏“显式/隐式同一参数定义”。应区分 RNA soft range 与节点 hard range（或保留旧 hard max），并增加 radius > 1、length > 2 的显隐式等价回归。 |
| R-02 | P1 | `physicsWorld.registry` 使用全局 `_REGISTERED_PROPERTY_CLASSES/_BINDINGS` 和一次性 early-return；`register_solver_module()`/`unregister_solver_module()` 只改 descriptor 字典，不会随单个 domain 注册/注销 RNA。实际调用入口仍在 `PhysicsTools.register()/unregister()`。 | 当前实现只支持“启动时全部注册、退出时全部注销”，不支持 solver 自持声明后的原子加载/卸载，也把 Physics World 生命周期继续耦合在旧 PhysicsTools 上。应改为按 domain 记录类/binding、引用计数或依赖图，并让 module register/unregister 真正驱动各自属性生命周期。 |
| R-03 | P1 | `Bone.hotools_collision` 被声明为 `spring_vrm` 私有所有权，但 PhysicsTools 面板/工具、Physics World scope、MC2 BoneCloth、MC2 MeshCloth 等旧系统仍直接消费同一属性，没有声明对 SpringBone domain 的依赖。 | 一旦真正实现按 solver 卸载，关闭 SpringBone 会破坏其它物理系统；这也说明该 capability 不是 SpringBone 私有事实源。应将骨骼碰撞 schema 提升为 Physics World 共享 capability，或显式声明多消费者依赖并采用共享所有权/引用计数。 |
| R-04 | P1 | context-only Native 回归由删除前 17 项缩为 10 项；当前名为 `test_context_api_capsule_collider` 的测试实际传入 `SPHERE=0`。py311/py313 直接 ABI 矩阵不再独立覆盖 PLANE、BOX、真实 CAPSULE、碰撞组/mask，`create_and_free` 也没有显式 free/GC。 | “双 ABI 完整 context-only 矩阵”这一验收表述不成立。应恢复全部 collider 类型与 group/mask 的 context 测试、修正误导性命名，并增加 context 析构/重复释放的直接生命周期回归。 |
| R-05 | P2 | 旧 SpringBone 节点类整体删除后，已有节点树会成为 missing node；`springBoneBase` 的骨骼输出到 `keyframePoseBones` 的旧烘焙路径也一并消失，而保留节点的说明仍写着“SpringBone 的‘骨骼’输出接到本节点”。插件版本仍为 `3.0.0`，没有迁移器或破坏性升级标记。 | 这可以是有意的 breaking change，但不能被描述为透明兼容。需要更新节点说明和发布/迁移说明，明确旧图不可直接运行，并决定统一 writeback bake 节点落地前的烘焙能力状态。 |
| R-06 | P2 | 属性注册失败会使 `PhysicsTools.register()` 整体失败；registry 只在运行期检查 owner/name 冲突，`validate_solver_registry()` 没有预检 RNA 冲突，也只支持 pointer binding。 | 任一 solver 声明错误会扩大为旧 PhysicsTools 全模块不可用。应把 RNA 冲突纳入声明验证，并把跨 solver 失败隔离到 domain。 |
| R-07 | P2 | 全插件 background enable 仍会先被既有 VertexGroupTools GPU shader 初始化阻断；MC2 Blender scene parity runner 当前又因 `solve_meshcloth()` 调用签名陈旧（缺少 25 个参数）失败。两者没有证据表明由 `610bdce` 引入，但使跨旧系统的端到端矩阵仍为红色。 | 不能用 SpringBone 自身 35/35 替代跨系统验收。应修复/更新 MC2 runner 后重新跑通；完整 addon register/unregister 需在可创建 GPU context 的 Blender 会话中补验。 |

### 已确认通过的边界

| 边界 | 复审结果 |
|---|---|
| 旧入口删除 | runtime 引用审计只在“已移除接口”声明、测试断言和历史文档中找到旧符号；生成节点模块中旧 SpringBone 节点不存在，保留的 Mesh XPBD/CPP 与 `keyframePoseBones` 节点仍可生成。 |
| Native 唯一入口 | py311、py313 二进制只暴露 context API；现有 Native suite 两个 ABI 均为 10/10。该结果证明现有用例通过，不抵消 R-04 的覆盖缺口。 |
| SpringBone 主回归 | Blender SpringBone suite 35/35，通过 world slot、writeback、碰撞覆写、debug、cache dispose 等当前用例。 |
| PhysicsTools 注册生命周期 | 使用真实 `PhysicsTools.register()/unregister()` 定向验证：solver PropertyGroup 与 `Bone.hotools_collision` 能被注册和移除，保留物理节点可加载。该结果只证明当前全局启动顺序可用，不证明 R-02 所要求的 per-domain 原子生命周期。 |
| `.blend` 数据兼容 | 用旧等价 PropertyGroup 写入并保存 `.blend`，卸载旧类、注册新 `spring_vrm.properties` 后重开；`pin/collision_type/radius/length/offset/primary_collision_group/collided_by_groups` 七个字段全部保留。数据路径兼容通过，节点图兼容不在此结论内。 |

### 继续推进前的门槛

1. 修复 R-01，证明显式 RNA 与隐式节点对 capability 全值域等价。
2. 完成 R-02/R-03：property class、binding 和共享 capability 具备按 domain 可追踪的所有权与生命周期；加载/卸载一个 solver 不影响无关 solver 和 PhysicsTools。
3. 完成 R-04：py311/py313 context-only collider、mask、错误输入和析构矩阵恢复为绿色。
4. 更新并跑通 MC2 scene parity，补一次真实 UI/GPU 上下文下的全插件 register/unregister。
5. 对 R-05 作明确产品决策：旧节点图正式不兼容并发布迁移说明，或提供一次性迁移；同步清理失效的烘焙说明。

## 本轮代码审查

### 已修复

| 严重度 | 问题 | 修复与验证 |
|---|---|---|
| P0 | legacy 35 参数 ABI 会被后续数组覆盖 `bone_count`；context ABI 未校验 dtype/长度，错误 buffer 可触发 C++ 越界访问 | context ABI 已完整校验 float32/int32/uint8、连续性、精确长度、parent index、schema 和输出 buffer；legacy ABI 在最终收口中整体删除 |
| P1 | Solver 节点 `substeps` 被 `frame_context.substeps` 永久遮蔽，UI 参数不生效 | solver 输入成为 SpringBone 权威子步数，限制为 1-16；测试直接截获真实 native 调用并验证值为 5 |
| P1 | 非均匀 Object scale 使用 XYZ 平均缩放估算骨长 | 改为 `matrix_world.to_3x3() @ rest_vec` 的真实轴向世界长度；`(2,1,3)` 缩放下 Z 轴骨长回归通过 |
| P1 | 没有 Debug Node 时仍每帧分配数组并执行 `spring_vrm_read_debug` | 改成请求状态机：Debug Node 在 slot 留一次性请求，后续推进帧由 solver 消费并清除；节点移除后最多额外采样一帧 |
| P2 | dynamic context 保存并重填从未传入 C++ 的 target matrix/quaternion 数组 | 删除死 buffer 和重复矩阵打包 |
| P2 | 每骨每帧构造完整 `BoneCollisionProfile` 并重复扫描 override registry | solver 热路径一次构建 override index，只解析 C++ 实际消费的 type/radius/mask；公共 resolver 保持完整语义 |
| P1 | 新路径逐骨构造/复制 result dict，统一写回再逐骨解析 16-float matrix 和骨骼目标 | `slot.data.writeback_plan` 落地为跨帧复用的批次计划；result stream 每 slot 只发布一个 batch envelope，逐骨兼容结果按需展开；写回按 armature 通过一次 `foreach_set` 提交 |
| P2 | 连续帧重复解析 PoseBone records、维护未传入 context ABI 的 Python current/prev tail 状态 | topology 由 slot id 保证时复用 records；current/prev tail 只在 reset/debug readback 更新，不再进入正常播放热路径 |
| P0 | SpringBone slot 没有注册 `_dispose`，拓扑 prune/world dispose 只清 Python dict，不释放旧 C++ context handle | slot 安装统一 dispose owner，逐个释放 native context；拓扑热改与 10,000 帧资源身份回归通过 |

### 此前阻塞项（均已解除）

#### 已解除：新架构性能回退

`writeback_plan` 批次化后，128 骨代表轮次的阶段中位数由：

| 阶段 | ms/frame |
|---|---:|
| Physics World Begin（含 `scene.frame_set`） | 0.68 |
| 隐式对象注册 | 0.07 |
| SpringBone solver wall time | 2.50 |
| 统一写回 | 0.53 |
| Commit | 0.01 |

下降到：

| 阶段 | ms/frame |
|---|---:|
| Physics World Begin（含 `scene.frame_set`） | 0.57 |
| 隐式对象注册 | 0.06 |
| SpringBone solver wall time | 1.48 |
| 统一写回 | 0.22 |
| Commit | < 0.01 |

最终纯 envelope 实现下，128 骨总耗时中位数稳定在 `2.347-2.395 ms`，旧路径为 `2.158-2.180 ms`，三轮独立 Blender 进程倍率为 `1.079x-1.099x`，已通过 `<= 1.15x` 门槛。

#### 已解除：隐式对象残留

采用 OmniNode 根树级生命周期取舍，不为注册节点增加 source lease。注册节点没有 `always_run`，输入未变时由懒求值跳过，当前编译图内的 registry 持续复用；一次真正的编译成功后，`OmniNodeTree.compile_cached()` 清空该根树全部 runtime cache，active 注册节点在新图首次运行时重新填充 registry。

因此删除、静音、改接注册节点或改变 stable id 后，只要成功重编译，旧 world、旧 implicit entry、solver slot 和 native context 会一起 dispose；其他根树不受影响。编译缓存命中不会清理，编译失败也保留旧 runtime 状态。框架回归 3/3 覆盖成功编译、缓存命中和编译失败边界，SpringBone 现有 cache dispose 回归覆盖 world 内部 registry/slot/native 清理。

#### 已解除：骨骼碰撞字段只部分落地

真实 C++ 消费现在分为两条语义：

- `pin` -> context static `pinned`
- `collision_type` -> 决定自身 hit sphere 是否启用，并决定外部骨骼 sphere/capsule 类型
- `radius` -> `hit_radii`
- `collided_by_groups` -> 碰撞过滤 mask
- `length` -> 外部胶囊 `segment_a/segment_b`
- `offset` -> 外部骨骼碰撞体 `center/segment_a/segment_b`
- `primary_collision_group` -> 外部碰撞体 `collider_groups`

实现不扩展 C++ ABI：SpringBone 打包 collider arrays 时只对命中 `bone_collision.override` 的骨骼重算 resolved profile，未覆写的显式 RNA 条目直接复用 Begin 快照；override 可以从显式 `NONE` 新增碰撞体，也可以改成 `NONE` 删除条目。cache key 包含 override stable id/version/signature，因此同帧改写也会失效。

Blender 回归直接读取 solver 即将传给 `spring_vrm_update_dynamic` 的 collider arrays，验证 CAPSULE type、radius、length、offset、primary group、同帧版本失效与 `NONE` 禁用。

## 性能对比

以下旧/新对比是删除前的最终留档。当前 benchmark 已收敛为 `spring_vrm_context_benchmark_v2`，只测发布包中的 context 路径，不再动态加载已删除的旧 solver。

场景：单骨架、单链、无 collider、1 substep、debug capture 关闭；每轮 warmup 40 帧，测量 300 帧，共 3 个独立 Blender 进程。

| 模拟骨数 | 旧架构 median ms | 新架构 median ms | 新/旧倍率范围 | 新架构 FPS |
|---:|---:|---:|---:|---:|
| 8 | 0.268-0.276 | 0.347-0.356 | 1.260x-1.292x | 2811-2883 |
| 32 | 0.753-0.754 | 0.851-0.856 | 1.129x-1.136x | 1169-1176 |
| 128 | 2.158-2.180 | 2.347-2.395 | 1.079x-1.099x | 417-426 |

批次化前同机代表数据为 8/32/128 骨 `0.480 / 1.241 / 3.731 ms`；本轮继续下降约 `26% / 31% / 37%`。8 骨仍有 world 固定成本，但验收约定的 128 骨迁移门槛已通过。

32 collider 补充矩阵（300 帧，P50/P95）：

| 模拟骨数 | 旧 P50/P95 ms | 新 P50/P95 ms | P50 新/旧 | 门槛 |
|---:|---:|---:|---:|---:|
| 32 | 1.065 / 1.196 | 1.197 / 1.378 | 1.124x | PASS (`<= 1.25x`) |
| 128 | 2.387 / 2.679 | 2.632 / 2.934 | 1.103x | PASS (`<= 1.25x`) |

多骨架扩展矩阵（每骨架 8 根模拟骨，40 帧 warmup + 300 帧测量，3 个独立进程）：

| Armature 数 | 总骨数 | 总耗时 P50 范围 ms | P95 范围 ms | 相对 1 armature | 单 armature 成本/基线 |
|---:|---:|---:|---:|---:|---:|
| 1 | 8 | 0.353-0.359 | 0.470-0.474 | 1.000x | 1.000x |
| 8 | 64 | 1.710-1.808 | 1.890-2.094 | 4.775x-5.042x | 0.597x-0.630x |
| 32 | 256 | 5.497-5.607 | 5.901-6.078 | 15.348x-15.872x | 0.480x-0.496x |

每轮结束时 slot/context/C++ handle 数严格等于 armature 数，buffer 数严格等于 `3 * armature_count`，没有串槽或额外资源增长。

Debug capture 矩阵（128 根模拟骨，同样 3 个独立进程）：

| 模式 | 总耗时 P50 范围 ms | P95 范围 ms | 相对 off | Capture 自身 P50 ms | Capture 次数 |
|---|---:|---:|---:|---:|---:|
| off | 2.361-2.417 | 2.590-2.599 | 1.000x | 0 | 0 |
| one-shot | 2.375-2.408 | 2.587-2.673 | 0.996x-1.006x | 0.862-0.868 | 1 |
| continuous | 3.387-3.475 | 3.704-3.769 | 1.420x-1.461x | 0.782-0.798 | 300 |

one-shot 捕获所在帧总耗时为 `3.021-3.212 ms`。continuous 模式 Debug Node 自身 P50 为 `0.139-0.143 ms`，主要增量来自 C++ debug readback；三种模式的 slot/context/handle/buffer 数完全一致。

建议门槛：

- 正确性：删除前旧/context native 参数矩阵逐帧误差 `<= 2e-5`；删除后 context-only 回归必须全通过且旧符号必须不存在。
- 性能：128 骨、无碰撞时新路径不高于旧路径 `1.15x`；带 32 collider 时不高于 `1.25x`。
- 稳定性：连续 10,000 帧 native context/slot/buffer 数量不增长。

复现当前 context-only 性能：

```powershell
$env:SPRING_BENCH_SIZES='8,32,128'
$env:SPRING_BENCH_WARMUP='40'
$env:SPRING_BENCH_FRAMES='300'
$env:SPRING_BENCH_COLLIDERS='0' # 设为 32 可复现 collider 矩阵
& 'D:\Blender\Blender 4.5\blender.exe' --background --factory-startup --python `
  'OmniNode\NodeTree\Function\physicsWorld\spring_vrm\test\benchmark_blender_spring_vrm.py'
```

多骨架与 debug capture 矩阵：

```powershell
$env:SPRING_SCALE_ARMATURES='1,8,32'
$env:SPRING_SCALE_BONES='8'
$env:SPRING_DEBUG_BONES='128'
$env:SPRING_MATRIX_WARMUP='40'
$env:SPRING_MATRIX_FRAMES='300'
& 'D:\Blender\Blender 4.5\blender.exe' --background --factory-startup --python `
  'OmniNode\NodeTree\Function\physicsWorld\spring_vrm\test\benchmark_blender_spring_vrm_scale_debug.py'
```

## 功能参数测试矩阵

状态定义：`PASS` 表示已经自动真实运行并满足对应判据。

| ID | 域 | 参数/场景 | 真实运行判据 | 状态 |
|---|---|---|---|---|
| P-01 | Chain | stiffness_force | wrapper 截获 context step 实参；删除前完成旧/context 多帧对拍 | PASS |
| P-02 | Chain | drag_force | wrapper 截获 context step 实参；删除前完成旧/context 多帧对拍 | PASS |
| P-03 | Chain | gravity_dir | C++ 实参方向一致；重力产生对应偏转 | PASS |
| P-04 | Chain | gravity_power | C++ 实参一致；0 与非 0 结果可区分 | PASS |
| P-05 | Solver | substeps 1-16 | 节点值真实进入 `spring_vrm_step` | PASS |
| P-06 | Spec | 参数上下界 | stiffness/gravity >= 0、drag 0-1、substeps 1-16 | PASS |
| P-07 | Runtime | 热改刚度/阻尼/重力 | slot/context 不重建，下一帧实参更新 | PASS |
| P-08 | Time | scene fps/fps_base -> dt | 默认 24 fps 实测 dt=1/24 | PASS |
| P-09 | Time | time_scale=0 / 负值 | 不产生非有限值，暂停并重发结果、不推进 native | PASS |
| P-10 | Time | 倒放 | restart，不推进 Verlet | PASS |
| T-01 | Topology | 单链 | root 排除，模拟 2 骨，发布 2 项 | PASS |
| T-02 | Topology | 同 world 两骨架 | 2 个隔离 slot、4 个写回项 | PASS |
| T-03 | Topology | 同骨架多链 | 无重叠时共享 armature slot、分别推进 | PASS |
| T-04 | Topology | 重复 root | 明确拒绝，不静默覆盖 | PASS |
| T-05 | Topology | 模拟骨重叠 | 明确拒绝，不双写 | PASS |
| T-06 | Topology | 分叉骨链 | parent index/use_connect 与预期一致 | PASS |
| T-07 | Topology | 运行中改拓扑 | 旧 context dispose，新 context 只建一次 | PASS |
| T-08 | Transform | 非均匀 Object scale | 骨长按骨轴世界变换计算 | PASS |
| T-09 | Transform | 负缩放/镜像 | 长度、旋转和 box handedness 稳定 | PASS |
| T-10 | Transform | 零长度骨 | native context 不崩溃、不发布 NaN | PASS |
| C-01 | Bone profile | explicit RNA pin | pinned 骨不发生 basis 偏转 | PASS |
| C-02 | Bone profile | override pin | reset 后进入 C++ static `pinned` | PASS |
| C-03 | Bone profile | collision_type | NONE 禁用 hit/external collider，SPHERE/CAPSULE 启用 | PASS |
| C-04 | Bone profile | radius | override 值进入 C++ `hit_radii` | PASS |
| C-05 | Bone profile | collided_by_groups | override 值进入 C++ mask 并参与过滤 | PASS |
| C-06 | Bone profile | length | 改变真实 bone capsule 长度 | PASS |
| C-07 | Bone profile | offset | 改变真实 bone collider 中心 | PASS |
| C-08 | Bone profile | primary_collision_group | 改变真实 bone collider group | PASS |
| C-09 | Bone profile | override disabled | 回退 solver 显式 RNA profile | PASS |
| C-10 | Registry | 删除/改名注册链并重编译 | 旧 stable id 不再被 solver 消费 | PASS |
| C-11 | Registry | 删除 override 注册节点并重编译 | 新图首次运行回退 solver 显式 RNA | PASS |
| W-01 | World collider | sphere | snapshot -> C++，尾端推出 | PASS |
| W-02 | World collider | capsule | snapshot -> C++，尾端推出 | PASS |
| W-03 | World collider | plane | snapshot -> C++，尾端推出 | PASS |
| W-04 | World collider | box | snapshot -> C++，尾端推出 | PASS |
| W-05 | World collider | group mismatch | 不发生碰撞响应 | PASS |
| W-06 | World collider | self-chain filter | 自身骨 collider 不重复作为外部 collider | PASS |
| W-07 | World collider | 运动 collider | 每帧 snapshot 失效并更新几何 | PASS |
| L-01 | Lifecycle | 首帧/reset | 发布当前 pose，不推进 | PASS |
| L-02 | Lifecycle | 连续帧 | context/buffer/slot 复用 | PASS |
| L-03 | Lifecycle | 跳帧 | reset 且该帧不推进 | PASS |
| L-04 | Lifecycle | same frame | 不推进，重发缓存 result | PASS |
| L-05 | Lifecycle | scope prune | stale slot dispose | PASS |
| L-06 | Lifecycle | cache delete/clear_all | C++ capsule 与 bpy 引用释放 | PASS |
| L-07 | Lifecycle | 10,000 帧 soak | slot/context/handle/static/dynamic/result buffer 身份与数量不增长 | PASS |
| D-01 | Debug | 无 Debug Node | 不调用 debug readback | PASS |
| D-02 | Debug | 下一帧请求状态机 | request -> consume -> clear | PASS |
| D-03 | Debug | 四类 collider 和组颜色 | C++ snapshot 与绘制一致 | PASS |
| R-01 | Result | bone_transform schema | channel/source/slot/frame/generation 完整 | PASS |
| R-02 | Writeback | PoseBone.matrix_basis | solver 不直写，统一节点写回 | PASS |
| R-03 | Writeback | 批量 writeback_plan | 预分配并避免逐骨 dict/matrix 重解析 | PASS |
| A-01 | ABI | 删除前 legacy/context 数值一致 | 4 组参数、碰撞、多帧误差 <= 2e-5，作为删除门槛留档 | PASS |
| A-02 | ABI | context 错误 dtype/shape/count | Python exception，不进入 C++ 越界 | PASS |
| A-03 | ABI | py311 / py313 | 双 Python ABI 重建并运行同一 context-only native 矩阵 | PASS |
| A-04 | ABI | 旧符号删除 | 两个 `.pyd` 均无 `solve_spring_bone_vrm_cpp` 属性 | PASS |
| A-05 | RNA | solver 属性生命周期 | physicsWorld registry 注册/注销后 `Bone.hotools_collision` 对应出现/消失 | PASS |
| F-01 | Perf | 8/32/128 骨无碰撞 | 三轮 300 帧统计 | PASS |
| F-02 | Perf | 32/128 骨 + 32 collider | 新/旧同场景 P50/P95 | PASS |
| F-03 | Perf | 多骨架 | 1/8/32 armature 扩展曲线 | PASS |
| F-04 | Perf | Debug capture | off/continuous/one-shot 成本 | PASS |

## 已执行回归

- Blender SpringBone 10,000 帧 soak 矩阵：36/36 通过。
- OmniNode 编译/runtime cache 生命周期：3/3 通过；覆盖成功编译仅清当前根树、编译缓存命中保留运行态、编译失败保留运行态和旧编译结果。
- SpringBone 删除前 legacy/context 参数矩阵：4 组、每组 6 帧，误差阈值 `2e-5`；该结果作为删除门槛留档，不再要求发布包携带 legacy ABI。
- SpringBone `hotools_native` 的 Release py311 / py313 扩展统一重建成功。
- SpringBone native context-only 矩阵：py311 `10/10`，py313 `10/10`；包含旧符号缺失、错误 buffer 拒绝和零长度 context。
- Blender SpringBone 常规集成：本轮重新执行 `35/35`；其中 capability-owned RNA、显式/隐式 resolver 和 native collider 数组均通过。
- physicsWorld solver RNA 注册/注销 smoke：`1/1`，验证 `Bone.hotools_collision` 生命周期由 registry 接管。
- 多骨架与 Debug capture 性能矩阵：3 个独立 Blender 进程，每个 case 40 帧 warmup + 300 帧测量；资源数量断言全部通过。
