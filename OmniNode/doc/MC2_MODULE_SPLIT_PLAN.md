# OmniNode MC2 模块工作表
更新日期：2026-06-17

本文只记录当前包结构、完成度和 C++ 对齐入口。旧阶段规划和过期 schema 不再保留；实现细节以 `OmniNode/NodeTree/Function/physicsMC2` 当前代码为准。

## 固定边界

| 项 | 当前约定 | 状态 |
| --- | --- | --- |
| MeshCloth 输入 | 输入 mesh 永远就是用户准备好的低模代理；solver 不做减面、重拓扑、代理生成、高低模映射。 | 固定 |
| BoneCloth | 后续实现，但复用 MeshCloth 的参数、状态、baseline、约束和 native ABI 设计。 | 预留 |
| Python 包入口 | `physicsMC2/__init__.py` 直接作为 OmniNode 函数模块入口，导出 `meshClothMC2`；C++ 后端完成后再新增独立 `meshClothMC2Cpp` OmniNode。 | 已落地 |
| 蓝本隔离 | 不改 `Physics.py`，SpringBone/XPBD 继续作为可对照蓝本。 | 固定 |
| 碰撞 | 碰撞适配放在 `physicsMC2` 包内部，不抽公共碰撞文件。 | 已落地 |
| 时间语义 | 刻意使用 Blender 输出帧率换算真实帧长；不复制 MC2 manager 的 wall-clock/catch-up/timeScale 体系。 | 已落地 |
| Iterations | 保留 `iterations` 作为 Python/C++ 共享调度参数；当前 C++ parity 目标要复刻 Python 循环语义。 | 已落地 |
| 参数曲线 | 当前 socket 传标量，内部保留 `ParamSlot`/sample 形式，后续可扩成曲线输入。 | 部分完成 |
| 自碰撞 | 当前不实现，只保留扩展空间。 | 预留 |
| C++ 后端 | Python 是行为参考；C++ 已接入逐 kernel 热路径，并新增首版 `solve_meshcloth_mc2` 整帧数组 core，沿同一套 state ABI 对齐。 | 进行中 |
| C++ OmniNode | 整帧 C++ solver parity 通过后再暴露独立 `meshClothMC2Cpp`；当前不注册半成品 C++ 节点，也不悄悄改变 `meshClothMC2` 的参考语义。 | 待做 |

## Python 包结构

| 文件 | 当前职责 | 完成度 | C++ 对齐备注 |
| --- | --- | --- | --- |
| `__init__.py` | OmniNode 节点入口、cache 生命周期、reset/jump-frame、碰撞快照收集、shape key 写回。 | 已落地 | 当前导出 Python reference `meshClothMC2`；整帧 native solver 完成后新增 `meshClothMC2Cpp`。 |
| `constants.py` | cache kind/version、属性位、MC2 系统常量、distance/bend 类型、曲线预留参数名。 | 已落地 | 当前 `MC2_SOLVER_VERSION = 11`；`EPSILON = 1e-8` 对齐 MC2。 |
| `params.py` | 标量参数与按 depth 采样入口。 | 已落地 | 曲线表也从这里接入。 |
| `math_utils.py` | numpy/mathutils 转换、向量安全归一化、hash、最近点等基础函数。 | 已落地 | 可迁移为 C++ math helper。 |
| `blender_io.py` | Blender 帧时间、substep damping、shape key I/O、local/world 转换。 | 已落地 | Python 独有层，C++ 不访问 Blender。 |
| `collision.py` | HoTools 碰撞组快照、sphere/capsule point collision、collision friction/normal、native collider arrays。 | 已落地 | C++ 复刻 collision projector 和数组视图，不抽公共 Python 模块。 |
| `mesh_build.py` | mesh 连通性、pin/weight、structural distance、MC2 shear 横向连接、dihedral/volume bending、bend fallback 数据构建。 | 已落地 | 第一版 C++ 不重建 mesh，只消费数组。 |
| `baseline.py` | MeshCloth 固定点出发的父子 baseline、depth/root、local pose、step basic pose。 | 已落地 | step basic pose 已 native-first；BoneCloth 后续替换 builder，求解层消费同一套 baseline 数组。 |
| `inertia.py` | MC2 风格 center inertia、movement smoothing、速度限制、teleport、depth inertia、centrifugal。 | 部分偏高 | substep/depth inertia 和 centrifugal 纯数组热路径已有 native kernel；frame/object runtime state 仍留 Python。 |
| `state.py` | cache state 构建、schema guard、object transform 同步、ABI 字段维护。 | 已落地 | state 是 C++ ABI 真源。 |
| `constraints.py` | signed distance、angle、triangle bending、tether、motion/backstop、post 等数组约束函数。 | 已落地 | C++ 逐项复刻这些 projector。 |
| `solver.py` | MeshCloth Python 求解调度、substep/iteration、inertia、velocity_positions、display future prediction、post 语义。 | 已落地 | 仍是行为参考；首版 C++ 整帧数组 core 已复刻其子步顺序，但现有节点暂不切换。 |
| `native_bridge.py` | native 可用性检测、state/params/colliders/inertia ABI view 打包，逐项调用 native kernel 并回退 Python。 | 部分完成 | 已调用 baseline step pose、neighbor distance、tether、angle、motion/backstop、collision、triangle bending、post step、substep inertia、centrifugal、display；新增 `solve_meshcloth_core()` 包装 `solve_meshcloth_mc2`，但未默认接管 `meshClothMC2`。 |

## State / ABI 工作表

| 域 | 当前字段 | 状态 | 备注 |
| --- | --- | --- | --- |
| schema | `kind`, `solver_version`, `vertex_count`, object/mesh/config keys | 已落地 | 当前版本 `11`。 |
| particle | `next_positions`, `old_positions`, `velocity_positions`, `base_positions`, `rest_world_positions`, `display_positions`, `velocity`, `real_velocity`, `friction`, `static_friction`, `collision_normals` | 已落地 | world-space 递推；`display_positions` 做 MC2 风格未来预测与 root clamp，写回时转 local。 |
| pose/baseline | `base_normals`, `base_rotations`, `step_basic_positions`, `step_basic_rotations`, `vertex_local_positions`, `vertex_local_rotations` | 已落地 | Angle/Inertia/BoneCloth 共用设施。 |
| attributes | `attributes`, `depths`, `inv_masses`, `root_indices`, `parent_indices`, `root_rest_lengths`, `baseline_start/count/data/flags`, `tether_rest_lengths` | 已落地 | MeshCloth/BoneCloth 未来共用。 |
| structural distance | `edge_i`, `edge_j`, `edge_rest`, `edge_type`, `distance_start/count/data`, `distance_rest` | 已落地 | `distance_rest < 0` 表示 horizontal；已包含 MeshCloth 共享边 shear 横向连接。 |
| triangle bending | `dihedral_pairs`, `dihedral_rest_angles`, `dihedral_signs`, `volume_pairs`, `volume_rest`, `bend_kind`, `bend_distance_*` | 已落地 | 主路径为 DirectionDihedralAngle + Volume；fallback 保留。 |
| inertia | `inertia_state` 及 native `inertia_*` fields | 已落地 | 包含 component/world center、shift pivot、smoothing velocity、step/inertia vector/rotation、teleport state。 |
| collision | `collision_radii`, `collided_by_groups`, native collider arrays | 已落地 | 使用 HoTools 碰撞组，不复制 MC2 显式 collider list。 |
| params | `param_slots`, scalar/sample API | 部分完成 | 当前为标量；solver 已按 sample API 消费主要参数。 |
| extension | `self_collision`, `bonecloth`, `native` slots | 预留 | 不影响当前 MeshCloth 求解。 |

## C++ 拆分工作表

| 文件/域 | 目标职责 | 当前状态 | Python 对齐来源 |
| --- | --- | --- | --- |
| `hotools_mc2_types.hpp` | 定义 MeshCloth state、param、collider、inertia 的 POD view。 | 待做 | `native_bridge.state_arrays_for_native()` |
| `mc2_bindings.cpp` | Python buffer 校验、dtype/shape/contiguous 检查、组装 view。 | 部分完成 | 当前集中在 `hotools_native.cpp`，后续再拆文件。 |
| `mc2_meshcloth_solver.cpp` | substep/iteration 主调度。 | 部分完成 | 当前集中在 `mc2.cpp::solve_meshcloth_mc2()`，后续再拆文件。 |
| `mc2_inertia.cpp` | world/local/depth inertia、smoothing、teleport、centrifugal。 | 部分 kernel | `inertia.py` |
| `mc2_distance.cpp` | structural distance projector。 | 已有首版 kernel | `constraints.project_neighbor_constraints()` |
| `mc2_baseline.cpp` | step basic pose 更新、baseline view 工具。 | 已有首版 kernel | `baseline.update_step_basic_pose()` |
| `mc2_tether.cpp` | tether 限制。 | 已有首版 kernel | `constraints.project_tether()` |
| `mc2_motion.cpp` | max distance / backstop。 | 已有首版 kernel | `constraints.project_motion_constraint()` |
| `mc2_collision.cpp` | sphere/capsule point collision。 | 已有首版 kernel | `collision.project_collisions()` |
| `mc2_bending.cpp` | DirectionDihedralAngle + Volume bending，保留 fallback。 | 已有首版 kernel | `constraints.project_triangle_bending()` |
| `mc2_angle.cpp` | angle restoration / angle limit。 | 已有首版 kernel | `constraints.project_angle_constraints()` |
| `mc2_post.cpp` | velocity、friction、real_velocity、old position 更新。 | 已有首版 kernel | `constraints.apply_post_step()` |
| `mc2_display.cpp` | display future prediction / root distance clamp。 | 已有首版 kernel | `solver._calc_display_positions()` |

## 当前推进表

| 工作项 | 当前结果 | 下一步 |
| --- | --- | --- |
| Python 包拆分 | 已从单文件升级为 `physicsMC2` 包，入口在 `__init__.py`。 | 继续只在包内扩展。 |
| Python MeshCloth 行为 | 已支持跳帧保护、世界坐标递推、HoTools 碰撞组、baseline/depth/root、signed distance、Angle、dihedral/volume bending、tether、motion/backstop、inertia、post。 | 用小场景继续校准 MC2 手感差异。 |
| native ABI | 已能从 Python state 打包 state/params/baseline/colliders/inertia view，并接入 baseline/distance/tether/angle/motion/collision/bending/post/substep inertia/centrifugal/display native kernel；首版整帧数组 core ABI 已通过 smoke。 | 继续做 Blender 场景级 parity 和 frame runtime 边界验证。 |
| C++ 求解 | 已有 `solve_meshcloth_mc2` 首版数组 core，覆盖 baseline、predict/pin、tether、distance、angle、bending、collision、motion、post、centrifugal、display 调度。 | 按 Python 当前行为继续扩 Blender 场景回归。 |
| C++ OmniNode | 暂不暴露；等待整帧 native solver 的 Blender 场景级 parity 和 cache/writeback 接入完成。 | 新增独立 `meshClothMC2Cpp`，保留 `meshClothMC2` 作为 Python reference。 |
| 高保真差异 | 曲线 UI、自碰撞、BoneCloth、anchor/sync/negative scale、完整 velocityWeight、Unity render interpolation/blendWeight 尚未完成。 | 按风险逐项补，优先不破坏当前接口。 |
