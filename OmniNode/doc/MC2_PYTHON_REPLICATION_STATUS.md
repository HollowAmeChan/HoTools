# OmniNode MC2 Python 复刻状态

最后更新：2026-06-17

本文只记录当前 Python 后端相对 MagicaCloth2 的实现差异、迁移完成度和进入 C++ 后端前的准入条件。过程流水账不放在这里；代码结构规划见 `MC2_MODULE_SPLIT_PLAN.md`。

## 当前结论

| 项目 | 判断 |
| --- | --- |
| 推荐路线 | 先把 Python 作为行为蓝本稳定下来，再做 C++ parity。 |
| C++ 第一版目标 | 对齐当前 Python reference，不直接追完整 Unity MC2。 |
| Mesh 输入边界 | 永远使用用户输入的低模代理；不做 reduction、减面、重拓扑、代理生成、高低模 mapping。 |
| 碰撞边界 | 继续使用 HoTools 碰撞组；MC2 碰撞适配只放在 `physicsMC2` 包内，不抽公共碰撞模块，不改 `Physics.py`。 |
| 时间语义 | 对齐 SpringBone/XPBD 蓝本：按 Blender `render.fps / render.fps_base` 得到真实帧长；只有连续下一帧继承 cache 速度。 |
| 当前可进入 C++ 吗 | 可以开始 C++ parity 骨架和数组 ABI，但不建议先在 C++ 里补完整 MC2 行为。 |

## 模块完成度

| 模块 | 当前文件 | 状态 | C++ 对应 | 说明 |
| --- | --- | --- | --- | --- |
| 节点入口 | `__init__.py` | 已完成 | 无 | 保留 `@omni meshClothMC2`、cache 生命周期、跳帧/reset、shape key 写回。 |
| 常量/schema | `constants.py` | 已完成 | `mc2_constants.hpp` / `hotools_mc2_types.hpp` | 包含 cache kind、solver version、attr flag、MC2 系统常量。 |
| 参数槽 | `params.py` | 部分完成 | `mc2_params.cpp` | 当前只支持标量采样；已保留未来曲线输入入口。 |
| 数学工具 | `math_utils.py` | 已完成 | `mc2_math.hpp` | numpy/mathutils 转换、hash、向量工具。 |
| Blender I/O | `blender_io.py` | 已完成 | 无 | Python 独有层，C++ 不接触 Blender 对象。 |
| Mesh 构建 | `mesh_build.py` | 已完成 | 可选 `mc2_mesh_build.cpp` | 只读取用户 mesh 并生成内部约束数组；不生成或修改代理。 |
| State/cache ABI | `state.py` | 已完成 | `Mc2MeshClothView` | 集中维护 cache 字段、shape guard、transform 同步。 |
| 约束函数 | `constraints.py` | 部分完成 | `mc2_distance.cpp` / `mc2_tether.cpp` / `mc2_motion.cpp` | distance/tether/motion 已有；angle/dihedral bending 未补。 |
| 碰撞 | `collision.py` | 部分完成 | `mc2_collision.cpp` | HoTools sphere/capsule 快照、point collision、native collider arrays 已有；friction/edge/self collision 未做。 |
| 求解调度 | `solver.py` | 部分完成 | `mc2_meshcloth_solver.cpp` / `mc2_post.cpp` | 当前 Python 顺序稳定，但还不是完整 MC2 Normal 流程。 |
| Native 桥 | 待建 `native_bridge.py` | 未开始 | `mc2_bindings.cpp` | 下一步应先打包数组和 fallback，不急着启用 C++。 |

## MC2 行为对照

完成度含义：

- 完成：当前 Python 行为已经可作为 C++ parity 基准。
- 部分：已有可运行近似或基础结构，但与 MC2 仍有明确差异。
- 未开始：仅预留字段或文档，尚未进入求解。
- 刻意不同：由 OmniNode 边界决定，不计划照搬 MC2。

| 功能域 | Unity MC2 做法 | 当前 Python 做法 | 主要差异 | 完成度 | C++ 前建议 |
| --- | --- | --- | --- | --- | --- |
| MeshCloth 输入 | MC2 可生成/管理代理数据，并有自己的 TeamData 管线。 | 直接读取用户提供的低模 mesh 顶点、边和 loop triangles。 | 我们永远不做减面、代理生成或高低模 mapping。 | 刻意不同 | 保持现状，C++ 只吃 Python 准备好的数组。 |
| BoneCloth / MeshCloth 共通层 | 同源约束与粒子数据，TeamData 管理不同 cloth 类型。 | MeshCloth 已拆出共通常量、参数、约束、碰撞、state；BoneCloth 未实现。 | BoneCloth 缺入口与骨骼粒子构建。 | 部分 | C++ 文件可提前按共通层拆，但先只绑定 MeshCloth。 |
| 时间系统 | TeamManager 维护 update time、skip count、time scale、frame interpolation。 | 每节点执行推进一个 Blender 输出帧；跳帧/倒放/同帧重复重置 cache。 | 不复制 MC2 全局 TeamManager；更贴合 OmniNode/SpringBone 帧语义。 | 刻意不同 | C++ 不实现全局时间系统，只接收 Python 传入 dt/substep。 |
| 积分模型 | 显式 velocity buffer：velocity 阻尼、force 积分、PostTeam 重建速度。 | Verlet 风格：`positions - old_positions` 形成惯性，阻尼按子步换算。 | 手感和 velocity 语义不同；`velocity/real_velocity` 目前更多是诊断/预留。 | 部分 | C++ 第一版先对齐 Python；若要切 MC2 velocity，必须先改 Python ABI。 |
| Base pose 更新 | MC2 每步更新 step basic pose，并参与 tether/motion/backstop。 | 当前 `base_positions` 来自 rest world；object transform 改变时同步 rest/约束长度。 | 外部动画驱动 base pose 的入口还不完整。 | 部分 | 如需要动画驱动，先在 Python 增加 base pose 更新输入。 |
| Fixed/Move/Motion 属性 | MC2 使用粒子属性和 depth/team 数据。 | 已有 fixed/move/motion、depth、root、parent、root length。 | depth 生成简化，依赖 fixed root 图遍历。 | 部分 | 可作为 C++ parity 基准；后续再补 MC2 depth/attribute 细节。 |
| DistanceConstraint | vertical/horizontal 分类，horizontal 用负 rest distance，可能补 shear，按 depth curve 采样。 | 基于输入 edge 构建 neighbor table，每顶点平均修正，单标量 stiffness。 | 没有 vertical/horizontal、shear、depth curve，也不更新 velocity position。 | 部分 | 先补 distance type 字段和 depth sampler；是否补 shear 需单独决定。 |
| TetherConstraint | compression/stretch 双侧限制，使用不同 stiffness/attenuation，参考 step basic pose，会影响 velocityPos。 | 已有 compression/stretch；`tether_rest_lengths` 用粒子到 root 的基础姿态直线距离。 | 未写 velocity position；参数还未暴露为节点曲线输入。 | 部分偏高 | 可先做 C++ parity；velocity 模型切换时再同步 velocityPos。 |
| MotionConstraint | max distance + backstop，依赖 base pose rotation/normal axis，stiffness lerp，影响 velocityPos。 | 已有 max distance 和 motion stiffness lerp；以 base position 为中心。 | 未实现 backstop、normal axis、base rotation、velocityPos 写入。 | 部分 | 先补 backstop 数据结构，再决定 mesh normal 简化策略。 |
| TriangleBendingConstraint | DirectionDihedralAngle，存 rest angle/volume、sign、triangle pair，SumConstraint 聚合。 | 当前是相邻三角对角点距离约束，属于 bend distance approximation。 | 没有二面角、方向 sign、volume pair，也不是 MC2 真实 triangle bending。 | 部分偏低 | C++ 若先做 parity，命名必须保持 `bend_distance_approx`；高保真前先补 Python dihedral。 |
| Angle constraints | MC2 有 angle restoration / angle limit 相关参数和约束阶段。 | 参数槽预留，求解未实现。 | 求解阶段缺失。 | 未开始 | 先保留 ABI 字段，等 bending/velocity 稳定后再补。 |
| ColliderCollision | 显式 collider list，point/edge collision，sphere/capsule/plane，多碰撞聚合，计算摩擦。 | 使用 HoTools 碰撞组，支持 object/bone sphere/capsule，point collision，多 collider 平均推离和 normal 聚合。 | 不照搬显式指定 collider；未支持 plane、edge collision、friction。 | 部分 | C++ 只复刻 HoTools collider arrays 和当前 point collision。 |
| Collision friction | dynamic/static friction 在 PostTeam 影响速度。 | 已有 friction/static_friction/collision_normals 字段，暂未参与求解。 | 摩擦求解缺失。 | 未开始 | 需要和 velocity/PostTeam 一起设计。 |
| Self collision | MC2 有自碰撞体系。 | 只预留 `extension_slots.self_collision`。 | 未实现。 | 未开始 | 不阻塞第一版 C++，但 ABI 保留扩展位。 |
| Inertia / Teleport | MC2 处理中心惯性、anchor、速度限制、teleport、negative scale。 | 跳帧/倒放/同帧重复直接 reset cache；object scale 改变时重算约束长度和半径。 | 不复制完整 InertiaConstraint。 | 部分 / 刻意简化 | 先保持 SpringBone 风格行为；C++ 不主动引入 Team inertia。 |
| Display interpolation | MC2 可用未来预测、blend、display position 插值。 | `display_positions` 当前等于求解后 positions。 | 无插值/混合权重。 | 未开始 | 不阻塞 C++ parity。 |
| 参数曲线 | 大量参数支持 depth curve。 | `params.sample_param()` 已有入口；节点当前主要传标量。 | 曲线输入 UI/缓存表未做。 | 部分 | C++ ABI 设计为 scalar/array view，Python 后续再接曲线。 |
| Cache/schema guard | MC2 有 TeamData/Chunk 数据版本和运行时状态。 | `state_matches()` 已校验 C++ 必需数组形状、索引范围、schema version。 | 运行时管理体系不同。 | 完成 | C++ 第一版以 `state.py` 为 ABI 真源。 |
| Native collider arrays | MC2 原生内部直接持有 collider 数据。 | `collision.collider_arrays_for_native()` 已能打包当前 HoTools collider 快照。 | 尚未接入 native bridge。 | 部分 | 下一步做 `native_bridge.py`，只打包和 fallback。 |

## C++ 迁移优先级

| 优先级 | 内容 | Python 基准 | C++ 文件建议 | 完成后标准 |
| --- | --- | --- | --- | --- |
| P0 | 固定 ABI 和 smoke 输入 | `state.py`、`collision.collider_arrays_for_native()` | `hotools_mc2_types.hpp`、`mc2_bindings.cpp` | C++ 能接收数组并原样返回/做空跑。 |
| P1 | Distance/Tether/Motion parity | `constraints.py` | `mc2_distance.cpp`、`mc2_tether.cpp`、`mc2_motion.cpp` | 同输入数组下 Python/C++ 输出误差可控。 |
| P2 | Collision parity | `collision.py` | `mc2_collision.cpp` | sphere/capsule/group filter 与 Python 一致。 |
| P3 | Solver 调度 parity | `solver.py` | `mc2_meshcloth_solver.cpp`、`mc2_post.cpp` | 连续帧、reset、jump frame 外围仍由 Python 管，单帧 solve 与 Python 对齐。 |
| P4 | Python fidelity 继续补 MC2 | `constraints.py`、`solver.py` | 对应 C++ 同步补 | 每次 Python 语义稳定后再同步 C++。 |

## C++ 准入条件

| 检查项 | 当前状态 | 是否阻塞 C++ parity |
| --- | --- | --- |
| Python 节点能注册 `meshClothMC2` | 已满足 | 否 |
| Python 包内模块边界稳定 | 已满足 | 否 |
| Cache schema version 明确 | 已满足，当前 `MC2_SOLVER_VERSION=2` | 否 |
| Native collider arrays | 已有打包函数，未接 bridge | 不阻塞骨架，阻塞正式 collision native |
| reset/jump frame 规则 | 已明确 | 否 |
| object scale change 同步 | 已有 state sync | 否，仍需 Blender 场景验证 |
| bend 命名清理为 approximation | 未完成 | 不阻塞 parity，阻塞高保真命名 |
| velocity 模型是否切 MC2 | 未决定 | 不阻塞 parity，阻塞高保真 MC2 |
| backstop/dihedral/friction/self collision | 未完成或部分完成 | 不阻塞第一版 C++ parity |

## 建议验证场景

| 场景 | 目标 |
| --- | --- |
| 单条 strip，根部 fixed | 验证 tether compression/stretch、跳帧 reset。 |
| grid 上边 fixed | 验证 distance/bend 约束稳定性。 |
| 无 fixed 整体下落 | 验证 gravity、damping、无 root 情况。 |
| sphere collision | 验证 point collision 和 normal 聚合。 |
| capsule collision | 验证 segment closest point 和 group filter。 |
| 多碰撞体夹挤 | 验证多 collider 平均推离。 |
| object scale 改变 | 验证 rest world、约束长度、collision radius 同步。 |
| reset/倒放/同帧重复 | 验证 cache 不继承非法速度。 |
