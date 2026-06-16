# OmniNode MC2 Solver 实现工作表

更新日期：2026-06-17

本文只保留当前 Python 复刻状态、与 Unity MagicaCloth2 的差异、C++ 对齐目标和验证工作表。旧的阶段路线、旧单文件结构、旧 cache schema 和已经失效的接口草案不再保留。

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
| Cloth 数据构建 | 通过 ClothProcess/VirtualMesh 构建 proxy、mapping、constraint data。 | 直接读取用户输入 mesh，构建 solver 内部数组。 | OmniNode 不复制 MC2 proxy/mapping 生命周期。 | 已落地 | 保持“不做减面/映射”边界。 |
| Team/Manager 调度 | 全局 manager + Burst job chunk。 | OmniNode 节点单实例 cache + Python substep loop。 | 不复制全局 manager；C++ 只替换热路径。 | 已落地 | C++ 以 state view 为单位求解。 |
| 时间步 | MC2 manager 统一传入 simulation dt。 | `frame_dt = fps_base / fps`，`step_dt = frame_dt / substeps`。 | 必须避免 wall-clock 或播放速度影响。 | 已落地 | C++ 使用 Python 传入的 `frame_dt`。 |
| 跳帧保护 | MC2 有自身 team/teleport 处理。 | 对齐 SpringBone：只接受连续帧推进。 | 不做隐藏多帧 catch-up。 | 已落地 | Blender 场景持续复测。 |
| 空间语义 | MC2 在 Unity transform/team 数据上运行。 | cache 内为 world space，边界做 local/world 转换。 | object scale/transform 改动需继续重点测。 | 已落地 | C++ 不接触 Blender transform。 |
| Particle predict | MC2 有显式 team/particle 更新。 | Verlet 式位置预测，含 gravity/damping。 | 与 MC2 velocity buffer 不是完全同构。 | 部分等价 | C++ 先复刻 Python，再决定是否调整到更 MC2。 |
| Structural distance | MC2 DistanceConstraint。 | `edge_*` + neighbor table，支持 per-depth stiffness sample。 | 类型分层较简化。 | 已落地 | C++ 先对齐当前 projector。 |
| Tether | MC2 TetherConstraint。 | 基于 fixed/root BFS 的 tether rest length。 | root/parent 生成方式为 OmniNode 简化版。 | 已落地 | 补小网格 parity test。 |
| Motion/max distance | MC2 MotionConstraint 含 max distance/backstop。 | 已有 max distance/motion 投影。 | backstop 尚未实现。 | 部分完成 | 补 backstop 字段和 projector。 |
| Bending | MC2 TriangleBendingConstraint/dihedral。 | 当前是 bend distance approximation，`bend_kind = distance_approx`。 | 与 MC2 高保真弯曲差异较大。 | 部分完成 | 后续实现 dihedral bending，保留现有近似模式。 |
| Angle | MC2 AngleConstraint。 | 尚未实现。 | MeshCloth/BoneCloth 共用价值高，但复杂。 | 待做 | 等 distance/tether/collision C++ 对齐后补。 |
| Collision | MC2 显式 collider list。 | 读取 HoTools 碰撞组快照，支持 sphere/capsule point collision。 | 不支持 MC2 edge collision/self collision。 | 部分完成 | C++ 复刻现有 point collision。 |
| Friction/post | MC2 有更完整 post velocity/friction。 | Python 已维护 velocity/friction 字段，但语义仍简化。 | 高速碰撞和贴附手感可能不同。 | 部分完成 | 对照 MC2 post 逻辑补差异。 |
| Display/interpolation | MC2 有显示插值/混合。 | `display_positions = next_positions`。 | 无插值。 | 简化完成 | 如 Blender 播放需要再补。 |
| 曲线参数 | MC2 多参数按 depth curve 采样。 | 当前 socket 是标量，内部已 sample 化。 | 用户还不能输入曲线。 | 预留 | 后续新增曲线输入而不改 solver 主流程。 |
| Self collision | MC2 有 primitive/grid/contact 管线。 | 不实现。 | 复杂度高，C++ ABI 需预留。 | 预留 | MeshCloth parity 稳定后再评估。 |
| BoneCloth | MC2 与 MeshCloth 共用大量设施。 | 尚未实现 I/O adapter。 | 不能把 MeshCloth 写死成 mesh-only solver core。 | 预留 | 复用 state/constraints/native ABI。 |

## 当前 Python 求解顺序

| 顺序 | 阶段 | 当前行为 |
| --- | --- | --- |
| 1 | validate/cache | 校验 mesh、scene、shape key、cache schema、config key。 |
| 2 | reset/jump-frame | reset 或非连续帧时恢复 rest，清理旧状态。 |
| 3 | rebuild/sync | 必要时重建 state；object transform 改动时同步 world-space state。 |
| 4 | collision snapshot | 从 HoTools 碰撞组收集 sphere/capsule 快照。 |
| 5 | solve setup | 计算 `frame_dt`、`step_dt`、substep damping、gravity、参数采样。 |
| 6 | predict | 推进 `next_positions`，固定点回 pin。 |
| 7 | pre constraints | tether、collision。 |
| 8 | iteration loop | structural distance、bend distance approximation、pin、collision。 |
| 9 | motion | 执行 max distance/motion constraint。 |
| 10 | post | 更新 velocity、real_velocity、friction、display state。 |
| 11 | writeback | world positions 转回 object local，写入目标 shape key。 |

## 当前 State / ABI 工作表

| 域 | 当前字段 | C++ 要求 |
| --- | --- | --- |
| 粒子位置 | `next_positions`, `old_positions`, `base_positions`, `rest_world_positions`, `display_positions` | `float32[n, 3]` contiguous，原地更新。 |
| 速度/后处理 | `velocity`, `real_velocity`, `velocity_positions`, `friction`, `static_friction`, `collision_normals` | C++ 与 Python post 语义逐项对齐。 |
| 属性/深度 | `attributes`, `depths`, `inv_masses`, `root_indices`, `parent_indices` | dtype/shape 必须严格校验。 |
| tether | `tether_rest_lengths` | 无 fixed/root 时允许跳过。 |
| structural distance | `edge_i`, `edge_j`, `edge_rest`, `edge_type`, `distance_start/count/data`, `distance_rest` | 当前 Python reference 的主结构约束。 |
| bend distance | `bend_distance_i/j/rest/type`, `bend_distance_start/count/data`, `bend_distance_neighbor_rest`, `bend_kind` | 当前只要求复刻 `distance_approx`。 |
| collision | `collision_radii`, `collided_by_groups`, collider arrays | C++ 只消费快照，不读取 Blender。 |
| params | scalar/sample slot | C++ 先支持 scalar 和已采样数组视图。 |
| extension | self collision/BoneCloth/native slots | 允许为空，不影响当前 MeshCloth。 |

## C++ 准入工作表

| 工作项 | 准入条件 | 状态 |
| --- | --- | --- |
| Buffer binding smoke | C++ 能读取 Python 打包的 state/params/colliders，并报出明确 dtype/shape 错误。 | 待做 |
| Distance parity | 单独 distance projector 与 Python `assert_allclose`。 | 待做 |
| Tether parity | root/tether 场景与 Python 对齐。 | 待做 |
| Motion parity | max distance 投影与 Python 对齐。 | 待做 |
| Collision parity | sphere/capsule point collision 与 Python 对齐。 | 待做 |
| Solver parity | 完整 substep/iteration 输出与 Python 小网格接近。 | 待做 |
| Blender integration | 同一节点接口下可切换 Python/C++，cache 与跳帧语义不变。 | 待做 |

## 验证工作表

| 场景 | 要验证的行为 | 状态 |
| --- | --- | --- |
| 单条 cloth strip | 一端 fixed，重力下垂，distance 保持。 | 需复测 |
| 方形 grid | 上边 fixed，distance + bend 后不炸裂。 | 需复测 |
| 无 fixed | 整体下落，tether 不产生错误约束。 | 需复测 |
| 碰撞组过滤 | 只与目标 group 的 sphere/capsule 相互作用。 | 需复测 |
| 跳帧 | 从 frame 1 跳到 frame 10 时恢复 rest 并清 cache。 | 需复测 |
| object transform/scale | cache world-space 语义稳定，写回 local 正确。 | 需复测 |
| shape key 写回 | Basis 不变，只更新目标 key。 | 需复测 |
| native ABI | Python 打包出的数组能被 C++ smoke 读取。 | 待做 |

## 当前优先级

| 优先级 | 工作 | 目的 |
| --- | --- | --- |
| P0 | 保持 Python MeshCloth 行为稳定并继续补 MC2 差异。 | Python 是 C++ 的 reference，不能在 C++ 前失控分叉。 |
| P0 | 做 native binding smoke。 | 先锁死 ABI，减少后续双端返工。 |
| P1 | C++ 逐项迁移 distance、tether、motion、collision、post。 | 让 C++ 先等价当前 Python，而不是直接追完整 MC2。 |
| P1 | 补 backstop 与更完整 post/friction。 | 提升 MC2 行为等价度。 |
| P2 | 实现 dihedral bending、angle constraint。 | 提升高保真弯曲与 BoneCloth 共用能力。 |
| P2 | 规划曲线输入 UI/socket。 | 在不改 solver 主流程的前提下接入 depth curve。 |
| P3 | 自碰撞。 | 复杂度高，等 MeshCloth/BoneCloth 主路径稳定后再做。 |
