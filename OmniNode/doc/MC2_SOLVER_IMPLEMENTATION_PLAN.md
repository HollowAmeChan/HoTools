# OmniNode MC2 Solver 实现工作表
更新日期：2026-06-17

本文只保留当前 Python 复刻状态、与 Unity MagicaCloth2 的差异、C++ 对齐目标和验证工作表。旧阶段路线、旧单文件结构、旧 cache schema 和失效接口草稿不再保留。

## 总体状态

| 域 | 当前状态 | 备注 |
| --- | --- | --- |
| 目标范围 | 先 MeshCloth，BoneCloth 后续接入同源设施。 | MeshCloth/BoneCloth 共用 solver 数组层，I/O adapter 分开。 |
| 输入 mesh | 用户提供的低模代理就是求解目标。 | 永远不做 reduction、减面、重拓扑、代理生成、高低模 mapping。 |
| Python 后端 | 已可运行，作为行为蓝本。 | C++ 后端必须先对齐 Python，再继续提高 MC2 等价度。 |
| C++ 后端 | 尚未开始正式求解，只完成 Python 侧 ABI view 打包。 | 下一步先做 binding smoke。 |
| 碰撞 | 使用 HoTools/OmniNode 现有碰撞组；逻辑留在 `physicsMC2` 包内。 | 不抽公共碰撞函数文件，不改 SpringBone/XPBD 蓝本。 |
| 时间 | 使用 Blender 工程输出帧率，damping 按每场景帧解释并换算到 substep。 | 与 SpringBone 蓝本语义保持一致。 |
| cache | runtime cache 以 world-space particle state 递推。 | 跳帧、倒放、同帧重复或 reset 会恢复静态并清旧速度。 |

## MC2 功能对照工作表

| 功能域 | Unity MC2 | 当前 Python | 差异/风险 | 完成度 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| Cloth 数据构建 | ClothProcess/VirtualMesh 构建 proxy、mapping、constraint data。 | 直接读取用户输入 mesh，构建 solver 内部数组。 | 不复制 proxy/mapping 生命周期。 | 刻意不同 | 保持“不减面/不 mapping”边界。 |
| Team/Manager | 全局 manager + Burst job chunk。 | OmniNode 单实例 cache + Python substep loop。 | 不复制全局 manager；C++ 只替换热路径。 | 已落地 | C++ 以 state view 为单位求解。 |
| 时间步 | manager 统一传入 simulation dt。 | `frame_dt = fps_base / fps`，`step_dt = frame_dt / substeps`。 | 避免 wall-clock 或播放速度影响。 | 已落地 | C++ 使用 Python 传入 dt。 |
| 跳帧保护 | MC2 有 team/teleport 处理。 | 对齐 SpringBone：只接受连续帧推进。 | 不做隐藏多帧 catch-up。 | 已落地 | Blender 场景持续复测。 |
| 空间语义 | Unity transform/team 数据。 | cache 内为 world space，边界做 local/world 转换。 | object scale/transform 改动需持续测。 | 已落地 | C++ 不接触 Blender transform。 |
| Particle predict | 显式 velocity buffer。 | 显式 velocity + world position predict；post 重建 velocity/real_velocity。 | velocityWeight reset 稳定化未完整复制。 | 部分偏高 | C++ 先复制 Python。 |
| Baseline | Mesh/Bone builder 不同，求解层共用。 | `baseline.py` 已实现 MeshCloth parent/depth/root、local pose、step basic pose。 | 外部 base pose 和 BoneCloth builder 未做。 | 部分偏高 | 后续补 BoneCloth builder。 |
| Structural distance | DistanceConstraint，vertical/horizontal、负 rest、velocityPos。 | `edge_*` + neighbor table，支持 signed rest、固定邻点质量、velocity_positions 写入。 | 未加入 MC2 shear 横向连接。 | 部分偏高 | C++ 先复刻当前 signed rest projector。 |
| Tether | compression/stretch，参考 step basic pose。 | 基于 fixed/root BFS 的 tether rest length。 | root/parent 生成是 OmniNode 简化版。 | 部分偏高 | 小网格 parity test。 |
| Motion/backstop | max distance/backstop，依赖 base pose rotation/normal axis。 | 已有 max distance、backstop、motion stiffness，使用 base normal。 | external base rotation 未接。 | 部分偏高 | 后续补外部 base pose rotation。 |
| Bending | TriangleBendingConstraint/dihedral/volume。 | 已生成 `dihedral_pairs/rest_angles/signs` 与 `volume_pairs/volume_rest`。 | world-space rest/base 与 MC2 proxy local 不完全一致。 | 部分偏高 | C++ 对齐 `project_triangle_bending()`。 |
| Angle | AngleConstraint 基于 baseline/step basic pose 做 restoration/limit。 | 已接入 `project_angle_constraints()`，支持恢复力、限制角、限制刚度、velocity attenuation、0.2 缩放。 | gravity falloff 暂用默认常量，曲线 UI 未做。 | 部分偏高 | 小网格/链状网格校准。 |
| Collision | 显式 collider list，支持更多 primitive/contact。 | HoTools 碰撞组，sphere/capsule point collision、friction/normal。 | 不支持 MC2 edge collision/self collision/plane。 | 部分偏高 | C++ 复刻当前 point collision。 |
| Friction/post | PostTeam velocity/friction。 | 已更新 velocity、real_velocity、friction、static_friction、old_positions，并支持 particle speed limit。 | velocityWeight 稳定化未完整复制。 | 部分偏高 | C++ 对齐当前 post。 |
| Inertia | center inertia、anchor、smoothing、限速、teleport、negative scale、centrifugal。 | 已实现 world/local/depth inertia、movement smoothing、world/local speed limit、teleport reset/keep、particle speed limit、centrifugal。 | anchor、sync team、negative scale teleport、完整 velocityWeight 未做。 | 部分偏高 | C++ 拆 `mc2_inertia.cpp` 并复刻当前 Python。 |
| Display/interpolation | 显示插值/混合。 | `display_positions = next_positions`。 | 无插值。 | 简化完成 | Blender 播放需要时再补。 |
| 曲线参数 | 多参数按 depth curve 采样。 | socket 当前传标量，内部已 sample 化。 | 用户还不能输入曲线。 | 预留 | 后续新增曲线输入，不改 solver 主流程。 |
| Self collision | primitive/grid/contact 管线。 | 不实现，只预留扩展槽。 | 复杂度高。 | 预留 | MeshCloth/BoneCloth 主路径稳定后再做。 |
| BoneCloth | 与 MeshCloth 共用大量设施。 | 未实现 I/O adapter，但 baseline/solver ABI 已预留共用层。 | 不能把 solver core 写死成 mesh-only。 | 预留 | 复用 baseline/state/constraints/native ABI。 |

## 当前 Python 求解顺序

| 顺序 | 阶段 | 当前行为 |
| --- | --- | --- |
| 1 | validate/cache | 校验 mesh、scene、shape key、cache schema、config key。 |
| 2 | reset/jump-frame | reset 或非连续帧时恢复 rest，清理旧状态。 |
| 3 | rebuild/sync | 必要时重建 state；object transform 改动时同步 world-space state。 |
| 4 | collision snapshot | 从 HoTools 碰撞组收集 sphere/capsule 快照。 |
| 5 | solve setup | 计算 `frame_dt`、`step_dt`、substep damping、gravity、参数采样。 |
| 6 | frame inertia | 计算对象整帧 world inertia shift、movement smoothing、teleport。 |
| 7 | baseline | 每个 substep 更新 `step_basic_positions/rotations`。 |
| 8 | substep inertia + predict | 计算 local/depth inertia，调整 old position 与 velocity，再预测位置。 |
| 9 | pre constraints | tether、必要时 collision。 |
| 10 | iteration loop | signed structural distance、angle restoration/limit、triangle bending、collision、collision 后 distance、pin。 |
| 11 | motion | 执行 max distance/backstop/motion constraint，并写入 velocity_positions。 |
| 12 | post | 更新 velocity、real_velocity、friction、static_friction、old_positions、particle speed limit、centrifugal。 |
| 13 | writeback | world positions 转回 object local，写入目标 shape key。 |

## 当前 State / ABI 工作表

| 域 | 当前字段 | C++ 要求 |
| --- | --- | --- |
| 粒子位置 | `next_positions`, `old_positions`, `velocity_positions`, `base_positions`, `rest_world_positions`, `display_positions`, `step_basic_positions` | `float32[n, 3]` contiguous，原地更新。 |
| 姿态/法线 | `base_normals`, `rest_world_normals`, `base_rotations`, `step_basic_rotations`, `vertex_local_positions`, `vertex_local_rotations` | C++ motion/backstop/angle 直接消费，不反查 Blender。 |
| 速度/后处理 | `velocity`, `real_velocity`, `velocity_positions`, `friction`, `static_friction`, `collision_normals` | C++ 与 Python post 语义逐项对齐。 |
| inertia | `inertia_state`, native `inertia_*` fields | 包含 shift pivot、smoothing velocity、center pose、substep inertia、teleport state。 |
| baseline/属性/深度 | `attributes`, `depths`, `inv_masses`, `root_indices`, `parent_indices`, `baseline_start/count/data/flags` | dtype/shape/span 必须严格校验。 |
| tether | `tether_rest_lengths` | 无 fixed/root 时允许跳过。 |
| structural distance | `edge_i`, `edge_j`, `edge_rest`, `edge_type`, `distance_start/count/data`, `distance_rest` | `distance_rest < 0` 表示 horizontal。 |
| triangle bending | `dihedral_pairs`, `dihedral_rest_angles`, `dihedral_signs`, `volume_pairs`, `volume_rest`, `bend_kind`, `bend_distance_*` | 主路径复制 dihedral + volume；fallback 保留。 |
| collision | `collision_radii`, `collided_by_groups`, collider arrays | C++ 只消费快照，不读取 Blender。 |
| params | scalar/sample slot | C++ 先支持 scalar 和已采样数组视图。 |
| extension | self collision/BoneCloth/native slots | 可为空，不影响当前 MeshCloth。 |

## C++ 准入工作表

| 工作项 | 准入条件 | 状态 |
| --- | --- | --- |
| Buffer binding smoke | C++ 能读取 Python 打包的 state/params/colliders/inertia，并报出明确 dtype/shape 错误。 | 待做 |
| Distance parity | 单独 distance projector 与 Python `assert_allclose`。 | 待做 |
| Inertia parity | frame shift、local/depth inertia、teleport、centrifugal 与 Python 对齐。 | 待做 |
| Tether parity | root/tether 场景与 Python 对齐。 | 待做 |
| Motion parity | max distance/backstop 投影与 Python 对齐。 | 待做 |
| Collision parity | sphere/capsule point collision、friction、normal 与 Python 对齐。 | 待做 |
| Post parity | velocity_positions、dynamic/static friction、real_velocity 与 Python 对齐。 | 待做 |
| Solver parity | 完整 substep/iteration/post 输出与 Python 小网格接近。 | 待做 |
| Blender integration | 同一节点接口下可切换 Python/C++，cache 与跳帧语义不变。 | 待做 |

## 当前优先级

| 优先级 | 工作 | 目的 |
| --- | --- | --- |
| P0 | 保持 Python MeshCloth 行为稳定。 | Python 是 C++ reference，不能在 C++ 前失控分叉。 |
| P0 | 做 native binding smoke。 | 先锁 ABI，减少后续双端返工。 |
| P1 | C++ 迁移 inertia、distance、tether、motion、collision、post。 | 让 C++ 先等价当前 Python。 |
| P1 | C++ 迁移 angle 和 bending。 | 当前 Python 已进入 reference，需要同一 projector。 |
| P2 | 实现 shear 横向连接。 | 提升 MC2 等价结构连接，但不改变输入 mesh 语义。 |
| P2 | 规划曲线输入 UI/socket。 | 在不改 solver 主流程的前提下接入 depth curve。 |
| P3 | 自碰撞。 | 复杂度高，等 MeshCloth/BoneCloth 主路径稳定后再做。 |
