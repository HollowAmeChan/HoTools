# OmniNode MC2 Python 复刻状态
更新日期：2026-06-17

本文只记录当前 Python 后端相对 MagicaCloth2 的实现差异、迁移完成度和 C++ 准入条件。过程流水账不放在这里；实现细节以 `OmniNode/NodeTree/Function/physicsMC2` 当前代码为准。

## 当前结论

| 项目 | 判断 |
| --- | --- |
| 推荐路线 | 继续先稳定 Python reference，再做 C++ parity。Python 不是临时草稿，而是 C++ 行为蓝本。 |
| C++ 第一版目标 | 对齐当前 Python reference，不直接跳到完整 Unity MC2。 |
| C++ 节点交付 | C++ 后端完成整帧 solver parity 后，新增独立 `meshClothMC2Cpp` OmniNode；不提前注册半成品节点。 |
| Mesh 输入边界 | 永远使用用户输入的低模代理；不做 reduction、减面、重拓扑、代理生成、高低模 mapping。 |
| 碰撞边界 | 继续使用 HoTools 碰撞组；MC2 碰撞适配只放在 `physicsMC2` 包内，不抽公共碰撞模块，不改 `Physics.py` 蓝本。这是架构刻意不同。 |
| 时间语义 | 对齐 SpringBone/XPBD 蓝本：按 Blender `render.fps / render.fps_base` 得到真实帧长；只有连续下一帧继承 cache 速度。这是刻意不同，不按 MC2 manager wall-clock/catch-up 复制。 |
| iterations | 保留。当前目的是让 Python/C++ 后端共享同一套调度参数和循环结构；job/chunk 细化后续再处理。 |
| 当前可进 C++ 吗 | 可以开始 C++ binding/ABI 和逐项 solver parity；不要先在 C++ 发明新行为。 |

## 模块完成度

| 模块 | 当前文件 | 状态 | C++ 对应 | 说明 |
| --- | --- | --- | --- | --- |
| 节点入口 | `__init__.py` | 已落地 | 无 | `meshClothMC2`、cache 生命周期、reset/jump-frame、shape key 写回。 |
| 常量/schema | `constants.py` | 已落地 | `mc2_constants.hpp` | 当前 `MC2_SOLVER_VERSION = 11`；`EPSILON = 1e-8` 对齐 MC2；包含 Angle/Inertia 参数与曲线预留名。 |
| 参数槽 | `params.py` | 部分完成 | `mc2_params.cpp` | 当前 socket 传标量；内部保留 scalar/sample 结构，后续可接 depth curve。 |
| Baseline | `baseline.py` | 部分偏高 | `mc2_baseline.cpp` | MeshCloth 的 parent/depth/root、baseline span、local pose、step basic pose 已落地；step basic pose 已有 native smoke；BoneCloth builder 未做。 |
| State/cache ABI | `state.py` | 已落地 | `Mc2MeshClothView` | 维护 cache 字段、shape guard、transform 同步、参数槽完整性。 |
| 约束函数 | `constraints.py` | 部分偏高 | `mc2_distance.cpp` / `mc2_angle.cpp` / `mc2_bending.cpp` / `mc2_tether.cpp` / `mc2_motion.cpp` / `mc2_post.cpp` | distance/tether/motion/backstop/post、Angle restoration/limit、DirectionDihedralAngle + Volume bending 已接入；阈值统一走 MC2 `EPSILON`。 |
| Inertia | `inertia.py` | 部分偏高 | `mc2_inertia.cpp` | 已实现 world/local/depth inertia、movement smoothing、world/local speed limit、particle speed limit、teleport reset/keep、centrifugal 近似和 ABI state；substep/depth inertia 与 centrifugal 纯数组热路径已有 native kernel。 |
| 碰撞 | `collision.py` | 部分偏高 | `mc2_collision.cpp` | HoTools sphere/capsule point collision、group filter、collision normal/friction、native collider arrays 已有；edge/self collision 未做。 |
| 求解调度 | `solver.py` | 部分偏高 | `mc2_meshcloth_solver.cpp` | Python reference 的 substep 顺序已固定：baseline、inertia/predict、tether、iteration distance/angle/bending/collision/distance、motion、post、display；C++ `solve_meshcloth_mc2` 已复刻首版数组 core。 |
| Native 桥 | `native_bridge.py` | 部分完成 | `mc2_bindings.cpp` / `mc2.cpp` | 已打包 state/params/colliders/inertia ABI view；已调用 C++ baseline step pose、neighbor distance、tether、angle、motion/backstop、collision、triangle bending、post step、substep inertia、centrifugal、display，并新增 `solve_meshcloth_core()` 包装首版整帧数组入口；现有节点暂不切换。 |

## MC2 行为对照

| 功能域 | Unity MC2 做法 | 当前 Python 做法 | 主要差异 | 完成度 | C++ 前建议 |
| --- | --- | --- | --- | --- | --- |
| MeshCloth 输入 | 可生成/管理 proxy 和 mapping。 | 直接读取用户低模 mesh 顶点、边、loop triangles。 | 刻意不做减面、代理生成、高低模 mapping。 | 刻意不同 | C++ 只吃 Python 准备好的数组。 |
| Team/Manager | 全局 TeamData、chunk、Burst job、skip/time scale。 | OmniNode 单节点 cache + Python substep loop。 | 不复制全局 manager；跳帧直接 reset。 | 刻意不同 | C++ 只替换热路径。 |
| 时间系统 | TeamManager 维护 update time、frame interpolation、velocityWeight。 | `frame_dt = fps_base / fps`，`step_dt = frame_dt / substeps`。 | 刻意不同：Blender 输出帧率已决定真实时间；不做 catch-up/timeScale；reset 稳定化未完整复制。 | 已落地 | C++ 使用 Python 传入 dt。 |
| Baseline | Mesh/Bone 共用粒子求解层，builder 不同。 | MeshCloth builder 已有；BoneCloth builder 未做。 | 外部 base pose 动画入口还不完整。 | 部分偏高 | BoneCloth 只新增 builder，复用 solver 层。 |
| Distance | vertical/horizontal、负 rest length、velocityPos attenuation；MeshCloth proxy triangle 会补 shear 横向连接。 | 支持 signed rest、固定邻点质量、velocity_positions 写入；已按共享边生成 MC2 风格 shear 横向连接。 | 不复制 MC2 proxy/mapping 生命周期；完整 parent cost 仍未做。 | 部分偏高 | C++ 对齐当前 signed rest + shear projector。 |
| Tether | compression/stretch，参考 step basic pose。 | compression/stretch 已实现，root rest 来自 Mesh baseline。 | 仍是 MeshCloth 简化 root 语义。 | 部分偏高 | C++ 先做 parity。 |
| Motion/backstop | max distance + backstop，依赖 base pose rotation/normal axis。 | 使用输入 mesh base normal 简化。 | 外部 base rotation 未接。 | 部分偏高 | 先复刻当前行为。 |
| Triangle bending | DirectionDihedralAngle + Volume。 | 已生成 `dihedral_*` 与 `volume_*`，无三角对时 fallback。 | rest/world 语义与 MC2 proxy local 不完全一致。 | 部分偏高 | C++ 第一版复刻 `project_triangle_bending()`。 |
| Angle | 基于 baseline 和 step basic pose 做 restoration/limit。 | 已接入 restoration、limit、limit stiffness、velocity attenuation、0.2 恢复力缩放。 | gravity falloff 暂用常量；曲线 UI 未做。 | 部分偏高 | 用小网格继续校准。 |
| Collision | 显式 collider list，point/edge/self 等。 | 使用 HoTools 碰撞组，sphere/capsule point collision。 | 架构刻意不同；edge/self/plane 未做。 | 部分偏高 | C++ 复刻 HoTools arrays。 |
| Collision friction | PostTeam dynamic/static friction。 | 已近似实现 friction/static_friction/collision_normals 对 velocity 的影响。 | velocityWeight 稳定化未完整复制。 | 部分偏高 | C++ 对齐当前 post。 |
| Inertia / Teleport | center inertia、anchor、smoothing、速度限制、teleport、negative scale。 | 已实现对象中心 world/local/depth inertia、movement smoothing、限速、teleport、centrifugal。 | anchor、sync team、negative scale teleport、完整 velocityWeight 未做；frame/object runtime state 仍由 Python 准备。 | 部分偏高 | substep/depth inertia 与 centrifugal 已有 native smoke；其余 inertia runtime 流程随整帧 solver 继续对齐。 |
| Self collision | MC2 有独立自碰撞体系。 | 只预留 `extension_slots.self_collision`。 | 未实现。 | 预留 | 不阻塞第一版 C++ parity。 |
| Display interpolation | MC2 有显示插值/混合，并对 future prediction 做 root distance clamp。 | `display_positions` 已做 `position + real_velocity * frame_dt` 与 root rest distance * 1.3 clamp。 | Unity render-time interpolation/blendWeight 未复制。 | 部分偏高 | 当前 display 输出已有 native smoke；blendWeight 后续再评估。 |
| 曲线参数 | 多数参数可按 depth curve 采样。 | 内部有 `ParamSlot`/sample；节点当前传实际值。 | UI/socket 曲线输入未做。 | 预留 | C++ ABI 设计保留 scalar/sample。 |

## C++ 准入条件

| 检查项 | 当前状态 | 是否阻塞 C++ parity |
| --- | --- | --- |
| Python 节点能注册 `meshClothMC2` | 已满足 | 否 |
| C++ 节点能注册 `meshClothMC2Cpp` | 待整帧 C++ solver parity 完成后新增 | 是，不能早于 native solver 完成 |
| Python 包边界稳定 | 已满足 | 否 |
| Cache schema 明确 | 已满足，当前 `MC2_SOLVER_VERSION = 11` | 否 |
| Native ABI view | 已有 state/params/colliders/inertia 打包，并接入 MC2 baseline/distance/tether/angle/motion/collision/bending/post/substep inertia/centrifugal/display native kernel；`solve_meshcloth_mc2` 整帧数组 core 已有 smoke | 不阻塞骨架；下一步是 Blender 场景级 parity 和独立 C++ 节点 |
| reset/jump frame 规则 | 已明确 | 否 |
| object transform/scale 同步 | 已有 state sync | 仍需 Blender 场景验证 |
| Inertia 主流程 | substep/depth inertia 与 centrifugal 已 native；frame shift、teleport、smoothing runtime state 仍 Python | 不阻塞；C++ 必须按当前 Python 复刻 |
| self collision / BoneCloth | 未完成 | 不阻塞 MeshCloth 第一版 C++ |

## 建议验证场景

| 场景 | 目标 |
| --- | --- |
| 单条 strip，根部 fixed | 验证 tether、distance、jump reset、world/local inertia。 |
| grid 上边 fixed | 验证 distance、angle、bending、motion/backstop。 |
| 快速移动/旋转 object | 验证 world inertia、movement smoothing、speed limit、centrifugal。 |
| teleport reset/keep | 验证 cache 重置和保留相对状态。 |
| sphere/capsule collision | 验证 point collision、normal 聚合、friction。 |
| object scale 改变 | 验证 rest world、约束长度、collision radius 同步。 |
| native ABI smoke | 验证 C++ 能读取 schema=11 的 state/params/colliders/inertia；当前已覆盖 baseline step pose、neighbor distance、tether、angle、motion/backstop、collision、triangle bending、post step、substep inertia、centrifugal、display projector，以及 `solve_meshcloth_mc2` 整帧数组 core 与逐 kernel 调度一致性。 |
