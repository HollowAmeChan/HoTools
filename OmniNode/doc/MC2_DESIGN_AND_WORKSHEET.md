# OmniNode MC2 真实现状与规划

更新日期：2026-07-10

本文只维护 MC2 当前真实实现状态、后续规划和踩坑记录，删除过程性记录。
MC2 源码对照根目录：`D:\Unity_Fork\MagicaCloth2`（2.18.1，`418f89ff31a45bb4b2336641ad5907a1110eabea`）

新 Physics World 框架：`OmniNode/NodeTree/Function/physicsWorld/mc2`

旧 MeshCloth 公式参考：`OmniNode/NodeTree/Function/physicsMC2MeshCloth`，native 后端在 `_native`

## 判断口径

| 术语 | 含义 |
| --- | --- |
| 完美对齐 | 当前 HoTools 支持的输入域内，公式、常量、执行语义与 MC2 源码一致或等价。 |
| 高度对齐 | 数学核心和主要常量已对齐，但缺 MC2 的部分 manager/TeamData/proxy/job 上下文。 |
| 部分对齐 | 当前效果可用，并复制了主行为，但源码中仍有明确未实现分支。 |
| 模式不同 | Blender/OmniNode 架构刻意不同，不用“完成/未完成”直接判断。 |
| 缓做 | 有价值，但不是当前 MeshCloth/C++ parity 的阻塞项。 |
| 不做 | 与当前 Blender/OmniNode 目标冲突，或成本大于收益。 |

当前优先级：在 `physicsWorld.mc2` 内先冻结统一参数、setup 和签名契约，再接共享状态与 native 运算核心。旧 Python/C++ MeshCloth 保留为公式与 parity 参考，不再作为新 solver 的节点中控、cache 或写回架构蓝本。

## 新 Physics World MC2 边界

1. `MeshCloth`、`BoneCloth`、`BoneSpring` 是一个 MC2 solver 的三种 setup，不是三个 solver。三者共用一套粒子和约束模型。
2. 节点产生不可变的 `MC2ParticleProfileSpec`、`MC2SolverSettingsSpec`、`MC2SetupOptionsSpec`；task 只持有 source 身份、setup、规格和分层签名。
3. solver 入口以 Unity `ClothSerializeData.GetClothParameters()` 为语义边界，先生成 `MC2EffectiveParametersSpec`，之后的计算核心不再读取 Blender RNA、节点 socket 或旧 runtime dict。
4. setup adapter 只负责输入拓扑和输出通道：MeshCloth 使用 mesh source/GN offset，BoneCloth 和 BoneSpring 使用 bone chain/bone transform。BasePose、exchange、GN 与骨骼写回都不属于 MC2 运算核心。
5. B1 仍是安全空模拟步：不创建 slot、不调用旧 MC2 backend、不发布结果。参数契约稳定后再接共享粒子状态和 native context。

### Unity 源码映射

| 新规格 | Unity 权威来源 | 说明 |
| --- | --- | --- |
| `MC2ParticleProfileSpec` | `Runtime/Cloth/ClothSerializeData.cs` 与各 `Constraints/*Constraint.cs::SerializeData` | 每个 task 独立持有的完整计算参数，包括重力、惯性、粒子与约束配置。 |
| `MC2SolverSettingsSpec` | HoTools 显式 step 调度 | 只保留 substeps、iterations、time scale，不持有布料物理属性。 |
| `MC2SetupOptionsSpec` | `RenderSetupData.BoneConnectionMode`、`rotationalInterpolation`、`rootRotation` | 只描述 topology/骨骼写回差异；BoneSpring 强制 Line。 |
| `MC2EffectiveParametersSpec` | `ClothSerializeDataFunction.cs::GetClothParameters()` | 复刻 20% 系数与 BoneSpring 的强制覆盖规则。 |

BoneSpring 的有效参数不是另一份 preset：它由同一 profile 规范化得到。Unity 会把重力设为 0，固定 tether compression 为 0.8、distance stiffness 为 0.5，关闭 MaxDistance/Backstop/self collision，把 collider 固定为 Point 与 0.5 摩擦，并只在 BoneSpring 启用 Spring constraint。正因为共用同一粒子模型，预设也应挂在共享 profile 节点，而不是复制到三个 setup 节点。

## 旧 MeshCloth 实现参考边界

1. 当前只做 MeshCloth。输入 mesh 就是用户准备好的低模代理，不做 MC2 的减面、代理生成、高低模 render mapping 生命周期。
2. Solver 内部用 world-space particle state 推进；节点边界负责 object local/world 转换、Blender cache、BasePose 读取、collider 快照和 GN delta 写回。
3. Python 后端是行为参考；C++ 后端复用 Python 节点的 Blender/cache/collider/writeback 层，只把整帧 solver loop 下沉到 native。
4. 不搬 MC2 全局 TeamManager 单例。OmniNode 仍是 per-node evaluation/cache，MC2 语义通过 `MC2RuntimeOwner + MC2TeamState + MC2CenterState` 承载。
5. 不复制 MC2 wall-clock/catch-up 调度。Blender 输出帧率给出真实帧长：`frame_dt = fps_base / fps`；`time_scale` 只作为 per-node 0..1 步长缩放，`step_dt = frame_dt * time_scale / substeps`。
6. BasePose 采用“双对象读写分离 + GN 后置 delta”：只读 BasePose 对象提供骨架/基础修改器后的 animated base pose，当前物理对象写 `mc2_delta`，由 `MC2 后置位移` GN 修改器叠加。

## 算法差距与可超集点

1. 核心求解核已经非常接近 MC2：当前 `solver.py` 的单帧顺序基本就是 baseline -> inertia/predict -> pin/tether -> distance/angle/bend/collision -> motion -> post -> display。distance / angle / bending / tether / motion / post / display 的主公式、常量和修正方向已经对齐。
2. cache 升级后，很多原本依赖裸 dict 的“前置状态”现在都能精确对齐：`MC2RuntimeOwner`、`MC2TeamState`、`MC2CenterState`、`MC2TopologyState`、`MC2ParticleState`、`MC2BasePoseState`、`MC2NativeContext` 都变成显式对象，静态拓扑、参数样本、碰撞快照、debug ABI 可以按同一份 schema 维护。
3. 现在真正拉开差距的主要是调度层，而不是 PBD 核心：MC2 依赖全局 `TeamManager` / `WindManager` / culling / sync / skipWriting / catch-up / job scheduling；OmniNode 刻意保持 per-node evaluation，不挂全局 handler，也不做 scene-wide scan。这类能力若以后补，只能以显式节点输入或对象级条件实现。
4. self collision 已并入 Python reference、standalone native kernel 和 C++ full-core/context ABI：对象物理属性提供开关、表面厚度和 mass；solver 在 motion 后、post 前执行 point-triangle 与 edge-edge 自接触投影；C++ full-core 每个 substep 按当前 friction 重算 MC2 self inverse mass，并直接调用 `project_self_collisions_mc2()`。尚未对齐的是 MC2 的 intersect 纠正、MeshCloth 互碰、多体所有权/调度，以及 self collision 的 grid broadphase/job 化。
5. cache 升级也让一些 HoTools 侧的超集变得合理了：Box OBB collider 扩展、`distance_weight`、`MC2RuntimeOwner` 独立持有 runtime cache 和 dispose、BasePose 双对象读写分离与 GN 后置 delta，这些都比 MC2 更显式。
6. 结论：后续工作的重点应是 manager/lifecycle/self-collision/多 center，而不是继续盲目微调单帧 PBD kernel；kernel 本身已经接近“对齐完成”，剩下更多是语义补完和调度补完。

## 当前真实完成度

| 领域 | 当前实现 | 状态 |
| --- | --- | --- |
| Solver 顺序 | `solver.py` 与 `_native/src/mc2.cpp::solve_meshcloth_mc2()` 保持同构：baseline、substep inertia、predict/pin、tether、iteration distance/angle/bending/collision/distance/pin、motion、post、centrifugal、display。 | 高度对齐 |
| 系统常量 | `Epsilon=1e-8`、display clamp `1.3`、tether width `0.3`、distance horizontal `0.5`、triangle bending max `120`、volume min `90`、angle limit iteration `3` 已一致。 | 完美对齐 |
| Distance / shear | signed rest、horizontal 负 rest、horizontal stiffness、固定邻点质量、zero rest midpoint、velocity attenuation、`animation_pose_ratio` distance rest lerp 已实现。 | 高度对齐 |
| Tether | compression/stretch limit、stiffness width ramp、velocity attenuation、显式 `use_tether` 早退已实现。 | 高度对齐 |
| Angle restoration / limit | angle limit iteration、limit/restoration ratio、velocity attenuation、gravity falloff、parent/child correction 已实现；`gravityDot/gravityRatio` 来自当前 Center/inertia 上下文。 | 高度对齐 |
| Triangle bending / volume | DirectionDihedralAngle、Volume、固定点低逆质量、MaxAngle/VolumeMin/VolumeScale 已实现。 | 高度对齐 |
| Motion / max distance / backstop | max distance、backstop radius/distance、motion stiffness、normalAxis 的 `baseRot * axis` 语义已接入 Python 和 C++。 | 高度对齐 |
| Post / display | velocity、realVelocity、oldPositions、friction、staticFriction、particle speed limit、display future clamp 和 blendWeight 已实现。 | 高度对齐 |
| Collider | sphere/capsule/plane point collision、sphere/capsule/plane edge collision、group filter、friction/normal、moving collider old/next pose 已对齐；Box OBB point/edge 是 HoTools 额外扩展。 | 当前域完成 |
| Self collision | `PhysicsTools` 网格物理属性已新增自碰撞开关、表面厚度、mass；`MC2TopologyState` 缓存 self-collision 配置与初始逆质量，逆质量常量对齐 MC2 `FixedMass=100 / FrictionMass=10 / ClothMass=50`；Python solver 已接入 FullMesh 风格 point-triangle + edge-edge 自接触投影、4 轮 solver iteration、friction/normal 汇总；`project_self_collisions_mc2()` 既可 standalone 调用，也已并入 `solve_meshcloth_mc2()` full-core/context ABI。 | full-core 首版完成 |
| Inertia | world/local/depth inertia、movement smoothing、teleport reset/keep、negative scale teleport 基础、particle speed limit、centrifugal、普通对象路径 anchor/anchorInertia 已实现。 | 部分到高度对齐 |
| 参数曲线 | distance/bend/angle restoration/angle attenuation/angle limit/damping/max distance/backstop distance 支持值 + 曲线；常量曲线和默认 1->1 已走快速路径。 | 当前热路径完成 |
| RuntimeOwner | `_OmniCache.replace(owner)` 用于重建/跳帧，`_OmniCache.mutate(owner)` 用于连续帧；节点 cache 命中只接受 `MC2RuntimeOwner`，旧裸 dict cache 会失配并重建；owner 实现 dispose/debug snapshot。 | 地基已落地 |
| TeamState | 已收进 `frame_delta_time/step_delta_time/update_count/skip_count/substep_count/frame_interpolation/time_scale`、`skip_writing/culling/sync/scale_suspend`、scale/negativeScale、animation/blend/gravity/velocityWeight；`time_scale` 已驱动 Python/C++ 路径 per-node dt，0 时暂停 solver 推进；`skip_writing` 已作为只跳过 GN delta 写回的 per-node 输出策略。 | 关键策略已接入，场景级策略保留状态 |
| CenterState | 已收进 inertia/CenterData 摘要、`MC2TopologyState`、`MC2ParticleState`、`MC2BasePoseState` 和 `previous_collider_snapshot`；TopologyState 作为静态拓扑 schema 和 native context 上传来源，正常播放用 header 匹配复用而不每帧重读全量数组，Python solver 入口与约束循环的静态拓扑数组已从它读取，Particle/BasePose 由 solver 读写并在 post_pack 提交，同时镜像 legacy ABI。 | 第一、二批权威化完成 |
| Native context | `MC2NativeContext` 持有 C++ capsule、dirty key、静态数组、param slots、param sample arrays；dirty key 已包含 mesh/config/object 3x3/static count，静态数组上传与 debug ABI 静态打包要求从 `MC2TopologyState` 生成，不再从旧 dict 静态字段兜底；debug/native 动态数组打包优先读 Particle/BasePose/Topology/CenterState，param slots 只从 `MC2RuntimeOwner.runtime_cache_slots()` 传入的缓存取；C++ context 已驻留拓扑静态数组和 per-vertex 参数样本数组。 | 第一、二批 native residency 完成 |
| C++ full core | `solve_meshcloth_mc2_context_cached_params()` 优先复用 context 内拓扑静态数组和参数样本；旧数组 ABI 保留 fallback。 | 当前 MeshCloth full-core 完成 |
| 调试计时 | 已拆 `cache.*`、`base_proxy.*`、`base_pose_sync.*`、`solve_setup.*`、`write.*`；日志用 `[sum]` / `[step]` 区分汇总和叶子阶段。 | 可观测地基完成 |
| 测试 | `_native/tests/test_mc2_blender_scene_parity.py` 覆盖 Blender 场景级 Python/C++ parity；当前 12 帧 point/edge collision mode 的 max/RMS/stretch/collision count delta 为 0。 | 已落地 |

## 仍未完成

| 项目 | 当前缺口 | 优先级 |
| --- | --- | --- |
| Team 生命周期策略 | `time_scale` 与 `skip_writing` 已有 Blender 等价行为；`culling/sync/scale_suspend` 当前只保留状态，不做隐式全局/场景调度。若以后加入，必须来自节点显式输入或明确对象级条件。 | P1 |
| Dynamic particle/base/work buffers native-owned | 动态粒子/base/collider/substep inertia 仍每帧作为 numpy 数组传给 C++，但 ABI 打包边界已优先从正式 State 容器取动态粒子、base pose、collision radii 和 Center inertia。只有 Python parity/writeback 稳定后再评估 native-owned。 | P1 |
| negative scale 细分语义 | 已有 scaleRatio/negativeScaleSign/negativeScaleDirection 与历史状态矫正；Unity proxy local/world、triangle sign、collider sign 等细分语义未完全复制。 | P1 |
| radius 曲线 | MC2 的 `radius` 是参数曲线；HoTools 当前半径来自 mesh/collision 顶点组语义，并暂不进入 solver 参数曲线。 | 暂缓 |
| 多 center / DataChunk | RuntimeOwner 已有 Team/Center 容器，但尚未实现 MC2 式 SoA/DataChunk 多 center 调度。 | P2 |
| Self collision broadphase / job 化 | self collision 已并入 `solve_meshcloth_mc2()` full-core/context ABI；`project_self_collisions_mc2()` 已从 `mc2.cpp` 拆到 `_native/src/mc2_self_collision.cpp`；native 已开始补 uniform-grid broadphase，但 contact 生命周期和 job 化仍未对齐 MC2。 | P1 |
| MeshCloth 互碰 | 不等于把其他 mesh 顶点展开为 sphere collider；还需要对象所有权、质量、接触汇总、多体调度语义，最好等 self collision native 稳定后再设计。 | P2 |
| Wind | 依赖 TeamData/zone/moving wind 语义，当前不阻塞基础 cloth。 | P3 |
| BoneCloth / BoneSpring | 需要新 I/O adapter 和 builder；solver 数组层尽量复用 MeshCloth 地基。 | P3 |
| Job/chunk/split scheduling | 当前 C++ core 是单 state 连续数组循环；并行 job/chunk 要等核心语义稳定后做。 | P3 |

## 下一步规划

1. P0：保持 Python/C++ parity harness 作为每次 native 改动的底线测试。
2. P1：继续优化 self collision native 实现。uniform-grid broadphase 已开始补；下一步要把 contact 生命周期分层、去重和分帧 intersect 对齐，再看 job 化，避免大网格上继续放大卡住和抖动。
3. P1：评估 dynamic particle/base/work buffers native-owned。前提是 writeback、BasePose、debug timing 和 Python reference 都稳定。
4. P1：继续校准复杂骨架/修改器链 BasePose 场景，尤其是顶点顺序变化、高模绑定、负缩放和 root/parent 链。
5. P1：若需要 `culling/sync/scale_suspend`，先定义 Blender 显式输入/对象级条件；不要恢复 handler 或全局 scene scan。
6. P2：设计多 center/DataChunk 结构，但不要在 self collision/互碰语义未明确前做全局多体调度。

## 自碰撞参考地图

### 参考来源

- MC2 本体：`Runtime/Cloth/Constraints/SelfCollisionConstraint.cs`、`Runtime/Manager/Simulation/SimulationManager.cs`、`Runtime/Define/SystemDefine.cs`、`Runtime/Utility/Math/MathUtility.cs`
- HoTools 现状：`physicsMC2MeshCloth/collision.py`、`physicsMC2MeshCloth/solver.py`、`physicsMC2MeshCloth/state.py`、`_native/src/mc2_self_collision.cpp`
- 外部参考：`InteractiveComputerGraphics/PositionBasedDynamics`，重点看 broadphase、距离场和 position-based collision handling 的分层思路
- 经典论文线索：Müller et al. `Position Based Dynamics`、Baraff/Witkin `Large Steps in Cloth Simulation`、Bridson/Fedkiw/Anderson `Robust Treatment of Collisions, Contact and Friction for Cloth Animation`、Teschner et al. `Optimized Spatial Hashing for Collision Detection of Deformable Objects`

### MC2 真实状态

1. `SelfCollisionConstraint` 不是单个投影函数，而是 `UpdateGrid -> DetectionContact -> ConvertContactList -> UpdateContact -> SolverContact -> SumContact` 的整套管线；`SelfDetectionIntersectJob` 还单独把 intersect 按 `SelfCollisionIntersectDiv` 分帧处理。
2. self collision 的类型是 `PointTriangle + EdgeEdge + Intersect`，并且 `thickness`、`SelfCollisionSCR`、point-triangle 角度门限、`FixedMass/FrictionMass/ClothMass` 一起控制行为，不是单一参数硬顶。
3. MC2 的重点不是“更大的力”，而是“更薄的候选集 + 更清晰的接触生命周期”。这也是它比首版 brute-force 更不容易把局部区域锁死的核心原因。
4. HoTools 的 native 这次已经开始补 uniform-grid broadphase，说明这条线不是停留在规划，而是已经进入“候选集收缩”阶段；后面要补的是 contact 生命周期和 intersect 分帧。

### HoTools 当前状态

1. Python reference 已经有 grid broadphase；native 侧当前仍是首版点-三角形/边-边扫描，接触构建还是 O(V*T + E^2)。
2. 现在的 self collision 只覆盖单对象内部，不做互碰；这条线先别扩。
3. `thickness` 在 solver 里会先按 world scale 处理，再进入碰撞门限和 friction 计算，所以它更像接触范围阈值，而不是独立稳定器。厚度一大，黏连和重复命中的风险也会上来。

### 降低“卡住”的路线

1. 第一优先级：把 native broadphase 做出来，先把候选对缩小。
2. 第二优先级：做接触去重、接触缓存、帧拆分，减少同一片区域反复生成过密 contact。
3. 第三优先级：把 friction 和 thickness 的耦合做成可调权重或上限，避免厚度变大时把黏连一起放大。
4. 第四优先级：再评估 intersect 是否需要像 MC2 一样分帧，而不是一口气全算。
5. 这条线先只做内部 self collision；互碰留给后续外部设计，不在这次并入主线。

## 明确不做

| 项目 | 原因 |
| --- | --- |
| MC2 mesh reduction / 代理生成 | 当前工具目标是用户自己准备低模代理；solver 不负责资产生成。 |
| Unity 高低模 render mapping 生命周期 | Blender 中改用低模代理后置写 `mc2_delta`，高模继续绑定到最终低模代理。 |
| MC2 全局 TeamManager 单例 | 会破坏 OmniNode per-node 显式 cache 模型，并增加状态耦合。 |
| 运行帧里改 `Physics.py` 公共碰撞蓝本 | SpringBone/XPBD 继续作为对照蓝本；MC2 碰撞适配只在 `physicsMC2MeshCloth` 内维护。 |
| 通用 Armature 反解写回 | Preserve Volume、B-Bone、多修改器链和非线性修改器无法可靠反解。 |
| 回退到 shape key 输出 | shape key 在 Armature 等形变修改器之前生效，会在骨架场景中造成双重变形。 |
| 用同对象 evaluated mesh 临时读 base pose | “屏蔽输出 + 强刷 depsgraph + 读同对象 evaluated mesh”会引入反馈环、刷新不稳定和高 Python 开销。 |

## 踩坑记录

### 性能与 Blender UI

1. 物理解算本身可以在 3ms 以内，帧率仍可能明显下降；debug timing 中的 `outside` 往往来自 Blender UI/depsgraph，而不是 solver。
2. Outliner 是已确认的大性能因素。全屏只显示 3D View 或把大纲换成别的编辑器，帧率能直接上涨几十帧；不同 Outliner 模式帧率也不同。
3. 全局撤销设置、渲染后端 OpenGL/Vulkan 差异，在已测试场景里不是主要因素。
4. 工程里大量空物体、无关物体、Outliner 可见层级，会严重拖慢帧率，即使 MC2 tree/debug 显示 solver 时间没变。不要把这类 UI/场景管理问题误判成 solver 算法瓶颈。
5. debug 日志必须同时看 `total` 和 `outside`。`total` 短但 fps 低，优先查 UI/depsgraph/Outliner/场景对象，而不是继续盲目优化 C++ kernel。

### BasePose 与场景刷新

1. 不允许再挂私有 frame handler 做全局 BasePose 刷新；这违背 OmniNode 设计，也会 scene-wide scan。
2. `_cache_base_pose_on_frame_change` 这类全局扫描方案已经被排除。BasePose 应由节点内部、当前对象、显式 proxy 精确同步。
3. BasePose 读取只能读只读 proxy 对象的 evaluated mesh；写回对象只是 GN delta 容器。BasePose 模式下写入对象的 `matrix_world` 不用于重建 rest/约束，也不驱动整体 inertia。
4. BasePose proxy 与当前物理对象必须保持相同顶点数、loop 数、面数和顶点顺序。运行期只做轻量数量检查；同数量拓扑重排需要用户 reset/清缓存。
5. 自动生成/刷新 BasePose 对象属于明确的工具对象，统一放入 `HoPhysicsCache`；不要额外注册隐藏 handler 或“神秘”场景刷新逻辑。

### Cache 与状态

1. 正常播放为了性能只用轻量 cache key：对象/mesh 标识、顶点/loop/面数量等。同数量拓扑变化不会自动失效，必须 reset/清缓存。
2. 所有复制 state 的路径必须调用 `inherit_runtime_slots()`，否则会断开 `curve_cache/topology_cache/io_cache/native_cache/native_context` 引用。
3. `extension_slots["runtime_cache"]` 是长期运行缓存命名空间；不要再把新长期资源平铺到 `extension_slots` 顶层。
4. `extension_slots["features"]` 只放 native debug/self collision/BoneCloth 等功能预留，不和 runtime cache 混放。
5. `MC2RuntimeOwner` 必须继续实现 `omni_cache_dispose()`，未来所有 C++ 持久 handle 都由这里释放。
6. 节点 cache 入口不再迁移/复用旧裸 dict。若遇到旧 dict cache，当前帧会按失配处理并重建为 `MC2RuntimeOwner`。
7. BasePose proxy 元数据和 previous collider snapshot 已有 State helper；solver 不应再直接读写这些 legacy dict key。

### Native 与 ABI

1. `abi_view` 只能按需调试构造。正常播放不能每帧重建大结构，否则会把 debug 数据包变成热路径开销。
2. C++ context 当前已驻留拓扑静态数组和 per-vertex 参数样本数组；但动态 particle/base/collider/substep inertia 仍是每帧输入。不要过早把动态数组 native-owned，先守住 Python parity 和 writeback 稳定性。
3. C++ context 入口只改变静态拓扑与参数样本来源，核心算法仍是同一个 `hotools::solve_meshcloth_mc2(view)`。改 context 不应顺手改物理语义。
4. native fallback 必须保留：旧 `solve_meshcloth_mc2` 数组 ABI 和 `solve_meshcloth_mc2_context` 仍用于定位 Python/C++ 差异；但正常路径传入的是 schema-first arrays，静态数组不再从旧 dict cache 生成，动态 debug/native ABI 也优先从 State 容器读取，`runtime_cache` 只由 `MC2RuntimeOwner` 提供。

### 参数与语义

1. `radius` 暂时保持 mesh/顶点组语义，不当作 MC2 参数曲线输入。若以后改变，需要重新评估 collision/motion/backstop 的数据边界。
2. BasePose 双代理路径刻意不使用 anchor；基础动画已由只读 proxy mesh 表达，额外 anchor 会重新引入双重变换。
3. `gravityDot/gravityRatio` 已有基础 Center/inertia 上下文，但仍不是完整 MC2 TeamManager 生命周期。
4. `velocityWeight/blendWeight` 已按基础 TeamStepUpdate 语义接入；`timeScale` 按 MC2 0..1 语义做节点级 dt 缩放，0 时暂停 solver 推进；`skipWriting` 只跳过 GN delta 写回。完整 culling/sync/render interpolation 不复制或待明确。

## 文件地图

| 文件 | 职责 |
| --- | --- |
| `physicsMC2MeshCloth/__init__.py` | OmniNode 节点声明层，只保留 `@omni` metadata、socket 默认值和 Python/CPP 两个节点 wrapper；不再承载运行中控。 |
| `physicsMC2MeshCloth/runtime/controller.py` | 节点运行中控：输入校验、cache 命中/重建、BasePose 同步、collider 快照、跳帧冷启动、solver 调用、GN delta 写回。 |
| `physicsMC2MeshCloth/runtime/restart.py` | 首帧、reset、非正向连续帧的冷启动状态重置；负责清粒子动态状态、inertia runtime state 和 previous collider snapshot。 |
| `physicsMC2MeshCloth/runtime/timing.py` | MC2 节点级 debug timing 汇总、分组着色和打印。 |
| `physicsMC2MeshCloth/backends/selector.py` | Python/C++ backend 标签归一化和 solver 函数分派；后续 mixed/native-owned buffer 选择也应从这里扩展。 |
| `physicsMC2MeshCloth/state.py` | `MC2RuntimeOwner`、`MC2TeamState`、`MC2CenterState`、`MC2TopologyState`、`MC2ParticleState`、`MC2BasePoseState`、schema guard、cache/native context 生命周期。 |
| `physicsMC2MeshCloth/solver.py` | Python reference 与 C++ full-core 的解算实现入口，维护单帧内 solver 顺序、native ABI 打包和 post_pack；不要再放节点声明或 cache 中控。 |
| `physicsMC2MeshCloth/native_bridge.py` | Python/C++ ABI、静态/动态数组拆分、param slots、native context 调用。 |
| `physicsMC2MeshCloth/runtime_params.py` | 参数曲线采样、param slot、per-vertex 参数样本。 |
| `physicsMC2MeshCloth/baseline.py` | parent/root/depth/local pose、base rotations、step basic pose。 |
| `physicsMC2MeshCloth/collision.py` | HoTools collider 快照、previous pose、collider arrays、自碰撞 Python reference 与 native fallback。 |
| `physicsMC2MeshCloth/inertia.py` | frame prepare/commit、anchor、teleport、negative scale、CenterData 对应状态。 |
| `_native/src/mc2.cpp` | C++ full-core solver 总调度、自碰撞以外的 kernel、self-collision inverse mass 准备。 |
| `_native/src/mc2_self_collision.cpp` | MC2 self collision point-triangle / edge-edge 接触构建与投影 kernel。 |
| `_native/src/mc2_context.cpp` | C++ persistent context 生命周期、静态数组和参数样本驻留。 |
