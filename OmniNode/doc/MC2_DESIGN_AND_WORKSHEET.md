# OmniNode MC2 真实现状与规划

更新日期：2026-06-20

本文只维护 MC2 当前真实实现状态、后续规划和踩坑记录，删除过程性记录。
MC2 源码对照根目录：`D:\Unity_Fork\MagicaCloth2`  
HoTools 实现根目录：`OmniNode/NodeTree/Function/physicsMC2`，native 后端在 `_native`

## 判断口径

| 术语 | 含义 |
| --- | --- |
| 完美对齐 | 当前 HoTools 支持的输入域内，公式、常量、执行语义与 MC2 源码一致或等价。 |
| 高度对齐 | 数学核心和主要常量已对齐，但缺 MC2 的部分 manager/TeamData/proxy/job 上下文。 |
| 部分对齐 | 当前效果可用，并复制了主行为，但源码中仍有明确未实现分支。 |
| 模式不同 | Blender/OmniNode 架构刻意不同，不用“完成/未完成”直接判断。 |
| 缓做 | 有价值，但不是当前 MeshCloth/C++ parity 的阻塞项。 |
| 不做 | 与当前 Blender/OmniNode 目标冲突，或成本大于收益。 |

当前优先级：先稳定 `meshClothMC2` Python reference，再让 `meshClothMC2Cpp` 严格对齐 Python，最后逐项提高与 MC2 源码的等价度。

## 当前架构边界

1. 当前只做 MeshCloth。输入 mesh 就是用户准备好的低模代理，不做 MC2 的减面、代理生成、高低模 render mapping 生命周期。
2. Solver 内部用 world-space particle state 推进；节点边界负责 object local/world 转换、Blender cache、BasePose 读取、collider 快照和 GN delta 写回。
3. Python 后端是行为参考；C++ 后端复用 Python 节点的 Blender/cache/collider/writeback 层，只把整帧 solver loop 下沉到 native。
4. 不搬 MC2 全局 TeamManager 单例。OmniNode 仍是 per-node evaluation/cache，MC2 语义通过 `MC2RuntimeOwner + MC2TeamState + MC2CenterState` 承载。
5. 不复制 MC2 wall-clock/catch-up 调度。Blender 输出帧率给出真实帧长：`frame_dt = fps_base / fps`；`time_scale` 只作为 per-node 0..1 步长缩放，`step_dt = frame_dt * time_scale / substeps`。
6. BasePose 采用“双对象读写分离 + GN 后置 delta”：只读 BasePose 对象提供骨架/基础修改器后的 animated base pose，当前物理对象写 `mc2_delta`，由 `MC2 后置位移` GN 修改器叠加。

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
| Inertia | world/local/depth inertia、movement smoothing、teleport reset/keep、negative scale teleport 基础、particle speed limit、centrifugal、普通对象路径 anchor/anchorInertia 已实现。 | 部分到高度对齐 |
| 参数曲线 | distance/bend/angle restoration/angle attenuation/angle limit/damping/max distance/backstop distance 支持值 + 曲线；常量曲线和默认 1->1 已走快速路径。 | 当前热路径完成 |
| RuntimeOwner | `_OmniCache.replace(owner)` 用于重建/跳帧，`_OmniCache.mutate(owner)` 用于连续帧；节点 cache 命中只接受 `MC2RuntimeOwner`，旧裸 dict cache 会失配并重建；owner 实现 dispose/debug snapshot。 | 地基已落地 |
| TeamState | 已收进 `frame_delta_time/step_delta_time/update_count/skip_count/substep_count/frame_interpolation/time_scale`、`skip_writing/culling/sync/scale_suspend`、scale/negativeScale、animation/blend/gravity/velocityWeight；`time_scale` 已驱动 Python/C++ 路径 per-node dt，0 时暂停 solver 推进；`skip_writing` 已作为只跳过 GN delta 写回的 per-node 输出策略。 | 关键策略已接入，场景级策略保留状态 |
| CenterState | 已收进 inertia/CenterData 摘要、`MC2TopologyState`、`MC2ParticleState` 和 `MC2BasePoseState`；TopologyState 作为静态拓扑 schema 和 native context 上传来源，正常播放用 header 匹配复用而不每帧重读全量数组，Python solver 入口与约束循环的静态拓扑数组已从它读取，Particle/BasePose 由 solver 读写并在 post_pack 提交，同时镜像 legacy ABI。 | 第一、二批权威化完成 |
| Native context | `MC2NativeContext` 持有 C++ capsule、dirty key、静态数组、param slots、param sample arrays；dirty key 已包含 mesh/config/object 3x3/static count，静态数组上传与 debug ABI 静态打包要求从 `MC2TopologyState` 生成，不再从旧 dict 静态字段兜底；C++ context 已驻留拓扑静态数组和 per-vertex 参数样本数组。 | 第一、二批 native residency 完成 |
| C++ full core | `solve_meshcloth_mc2_context_cached_params()` 优先复用 context 内拓扑静态数组和参数样本；旧数组 ABI 保留 fallback。 | 当前 MeshCloth full-core 完成 |
| 调试计时 | 已拆 `cache.*`、`base_proxy.*`、`base_pose_sync.*`、`solve_setup.*`、`write.*`；日志用 `[sum]` / `[step]` 区分汇总和叶子阶段。 | 可观测地基完成 |
| 测试 | `_native/tests/test_mc2_blender_scene_parity.py` 覆盖 Blender 场景级 Python/C++ parity；当前 12 帧 point/edge collision mode 的 max/RMS/stretch/collision count delta 为 0。 | 已落地 |

## 仍未完成

| 项目 | 当前缺口 | 优先级 |
| --- | --- | --- |
| Team 生命周期策略 | `time_scale` 与 `skip_writing` 已有 Blender 等价行为；`culling/sync/scale_suspend` 当前只保留状态，不做隐式全局/场景调度。若以后加入，必须来自节点显式输入或明确对象级条件。 | P1 |
| Dynamic particle/base/work buffers native-owned | 当前动态粒子、base pose、collider、substep inertia 仍每帧作为 numpy 数组传给 C++。只有 Python parity/writeback 稳定后再评估 native-owned。 | P1 |
| negative scale 细分语义 | 已有 scaleRatio/negativeScaleSign/negativeScaleDirection 与历史状态矫正；Unity proxy local/world、triangle sign、collider sign 等细分语义未完全复制。 | P1 |
| radius 曲线 | MC2 的 `radius` 是参数曲线；HoTools 当前半径来自 mesh/collision 顶点组语义，并暂不进入 solver 参数曲线。 | 暂缓 |
| 多 center / DataChunk | RuntimeOwner 已有 Team/Center 容器，但尚未实现 MC2 式 SoA/DataChunk 多 center 调度。 | P2 |
| self collision / MeshCloth 互碰 | 不是简单把其他 mesh 顶点展开为 sphere collider；还需要 mass、所有权、接触汇总、多体调度语义。 | P3 |
| Wind | 依赖 TeamData/zone/moving wind 语义，当前不阻塞基础 cloth。 | P3 |
| BoneCloth / BoneSpring | 需要新 I/O adapter 和 builder；solver 数组层尽量复用 MeshCloth 地基。 | P3 |
| Job/chunk/split scheduling | 当前 C++ core 是单 state 连续数组循环；并行 job/chunk 要等核心语义稳定后做。 | P3 |

## 下一步规划

1. P0：保持 Python/C++ parity harness 作为每次 native 改动的底线测试。
2. P1：评估 dynamic particle/base/work buffers native-owned。前提是 writeback、BasePose、debug timing 和 Python reference 都稳定。
3. P1：继续校准复杂骨架/修改器链 BasePose 场景，尤其是顶点顺序变化、高模绑定、负缩放和 root/parent 链。
4. P1：若需要 `culling/sync/scale_suspend`，先定义 Blender 显式输入/对象级条件；不要恢复 handler 或全局 scene scan。
5. P2：设计多 center/DataChunk 结构，但不要在 self collision/互碰语义未明确前做全局多体调度。

## 明确不做

| 项目 | 原因 |
| --- | --- |
| MC2 mesh reduction / 代理生成 | 当前工具目标是用户自己准备低模代理；solver 不负责资产生成。 |
| Unity 高低模 render mapping 生命周期 | Blender 中改用低模代理后置写 `mc2_delta`，高模继续绑定到最终低模代理。 |
| MC2 全局 TeamManager 单例 | 会破坏 OmniNode per-node 显式 cache 模型，并增加状态耦合。 |
| 运行帧里改 `Physics.py` 公共碰撞蓝本 | SpringBone/XPBD 继续作为对照蓝本；MC2 碰撞适配只在 `physicsMC2` 内维护。 |
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

### Native 与 ABI

1. `abi_view` 只能按需调试构造。正常播放不能每帧重建大结构，否则会把 debug 数据包变成热路径开销。
2. C++ context 当前已驻留拓扑静态数组和 per-vertex 参数样本数组；但动态 particle/base/collider/substep inertia 仍是每帧输入。不要过早把动态数组 native-owned，先守住 Python parity 和 writeback 稳定性。
3. C++ context 入口只改变静态拓扑与参数样本来源，核心算法仍是同一个 `hotools::solve_meshcloth_mc2(view)`。改 context 不应顺手改物理语义。
4. native fallback 必须保留：旧 `solve_meshcloth_mc2` 数组 ABI 和 `solve_meshcloth_mc2_context` 仍用于定位 Python/C++ 差异；但正常路径传入的是 schema-first arrays，不再从旧 dict cache 生成静态数组。

### 参数与语义

1. `radius` 暂时保持 mesh/顶点组语义，不当作 MC2 参数曲线输入。若以后改变，需要重新评估 collision/motion/backstop 的数据边界。
2. BasePose 双代理路径刻意不使用 anchor；基础动画已由只读 proxy mesh 表达，额外 anchor 会重新引入双重变换。
3. `gravityDot/gravityRatio` 已有基础 Center/inertia 上下文，但仍不是完整 MC2 TeamManager 生命周期。
4. `velocityWeight/blendWeight` 已按基础 TeamStepUpdate 语义接入；`timeScale` 按 MC2 0..1 语义做节点级 dt 缩放，0 时暂停 solver 推进；`skipWriting` 只跳过 GN delta 写回。完整 culling/sync/render interpolation 不复制或待明确。

## 文件地图

| 文件 | 职责 |
| --- | --- |
| `physicsMC2/__init__.py` | OmniNode 入口、cache 校验、BasePose 同步、collider 快照、solver 调用、GN delta 写回。 |
| `physicsMC2/state.py` | `MC2RuntimeOwner`、`MC2TeamState`、`MC2CenterState`、`MC2TopologyState`、`MC2ParticleState`、`MC2BasePoseState`、schema guard、cache/native context 生命周期。 |
| `physicsMC2/solver.py` | Python reference 与 C++ full-core 调度，单帧内 solver 顺序和 post_pack。 |
| `physicsMC2/native_bridge.py` | Python/C++ ABI、静态/动态数组拆分、param slots、native context 调用。 |
| `physicsMC2/runtime_params.py` | 参数曲线采样、param slot、per-vertex 参数样本。 |
| `physicsMC2/baseline.py` | parent/root/depth/local pose、base rotations、step basic pose。 |
| `physicsMC2/collision.py` | HoTools collider 快照、previous pose、collider arrays。 |
| `physicsMC2/inertia.py` | frame prepare/commit、anchor、teleport、negative scale、CenterData 对应状态。 |
| `_native/src/mc2.cpp` | C++ full-core solver 和 kernel。 |
| `_native/src/mc2_context.cpp` | C++ persistent context 生命周期、静态数组和参数样本驻留。 |
