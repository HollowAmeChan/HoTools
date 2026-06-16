# OmniNode MC2 模块工作表

更新日期：2026-06-17

本文只记录当前包结构、完成度和 C++ 对齐入口。旧的阶段规划、已废弃模块草案和过时 schema 不再保留；需要看实现细节时，以 `Function/physicsMC2` 当前代码为准。

## 固定边界

| 项 | 当前约定 | 状态 |
| --- | --- | --- |
| MeshCloth 输入 | 输入 mesh 永远就是用户准备好的低模代理。solver 不做减面、重拓扑、代理生成、高低模映射。 | 固定 |
| BoneCloth | 后续实现，但要复用 MeshCloth 的参数、状态、约束和 native ABI 设计。 | 预留 |
| Python 包入口 | `physicsMC2/__init__.py` 直接作为 OmniNode 函数模块入口，导出 `meshClothMC2`。 | 已落地 |
| 蓝本隔离 | 不改 `Physics.py`，SpringBone/XPBD 继续作为可对照蓝本。 | 固定 |
| 碰撞 | 碰撞适配放在 `physicsMC2` 包内部，不抽公共碰撞文件。 | 已落地 |
| 时间语义 | 使用 Blender 工程输出帧率换算真实时间；跳帧、倒放、同帧重复执行会恢复静态并清 cache。 | 已落地 |
| 参数曲线 | 当前 socket 传标量，但内部保留 `ParamSlot`/sample 形式，后续可扩成曲线输入。 | 部分完成 |
| 自碰撞 | 当前不实现，只保留扩展空间。 | 预留 |
| C++ 后端 | Python 是行为参考；C++ 使用同一套数组/state ABI 对齐。 | 准备中 |

## Python 包结构

| 文件 | 当前职责 | 完成度 | C++ 对齐备注 |
| --- | --- | --- | --- |
| `__init__.py` | OmniNode 节点入口、cache 生命周期、reset/jump-frame、碰撞快照收集、shape key 写回。 | 已落地 | C++ 不关心节点，只接收 Python 打包后的数组。 |
| `constants.py` | cache kind/version、属性位、MC2 系统常量、distance/bend 类型常量。 | 已落地 | 后续对应 native 常量头。 |
| `params.py` | 标量参数与按 depth 采样入口。 | 已落地 | 后续曲线表也从这里接入。 |
| `math_utils.py` | numpy/mathutils 转换、向量安全归一化、hash、最近点等基础函数。 | 已落地 | 可按函数语义迁移到 C++ math helper。 |
| `blender_io.py` | Blender 帧时间、substep damping、shape key I/O、local/world 转换。 | 已落地 | Python 独有层，C++ 不访问 Blender。 |
| `collision.py` | HoTools 碰撞组快照、sphere/capsule point collision、collision friction/normal、native collider arrays 打包。 | 已落地 | C++ 复刻 collision projector 和数组视图，不抽公共 Python 模块。 |
| `mesh_build.py` | mesh 连通性、pin/weight/depth/root/tether、structural distance、bend distance approximation 数据构建。 | 已落地 | 第一版 C++ 不重建 mesh，只消费数组。 |
| `state.py` | cache state 构建、schema guard、object transform 同步、ABI 字段维护。 | 已落地 | `MC2_SOLVER_VERSION = 4` 是当前 native 对齐基准。 |
| `constraints.py` | distance、tether、motion、bend distance approximation 等数组约束函数。 | 已落地 | C++ 逐项复刻这些 projector。 |
| `solver.py` | MeshCloth Python 求解调度、substep/iteration、velocity_positions、motion/backstop、friction/post 语义。 | 已落地 | C++ MeshCloth solver 的直接行为参考。 |
| `native_bridge.py` | native 可用性检测、state/params/colliders ABI view 打包。 | 部分完成 | 当前只打包和记录状态，尚未调用 C++ 求解。 |

## 当前 State / ABI 工作表

| 域 | 当前字段 | 状态 | 备注 |
| --- | --- | --- | --- |
| schema | `kind`, `solver_version`, `vertex_count`, object/mesh/config keys | 已落地 | 当前版本为 `MC2_SOLVER_VERSION = 4`。 |
| particle | `next_positions`, `old_positions`, `velocity_positions`, `base_positions`, `rest_world_positions`, `base_normals`, `rest_world_normals`, `velocity`, `real_velocity`, `display_positions`, `friction`, `static_friction`, `collision_normals` | 已落地 | world-space 递推，写回时再转 local。 |
| attribute | `attributes`, `depths`, `inv_masses`, `root_indices`, `parent_indices`, `tether_rest_lengths` | 已落地 | MeshCloth/BoneCloth 未来可共用。 |
| structural distance | `edge_i`, `edge_j`, `edge_rest`, `edge_type`, `distance_start/count/data`, `distance_rest` | 已落地 | 代表 MC2 structural distance。 |
| bend distance approximation | `bend_distance_i/j/rest/type`, `bend_distance_start/count/data`, `bend_distance_neighbor_rest`, `bend_kind` | 已落地 | 当前为距离近似，不是完整 dihedral bending。 |
| collision | `collision_radii`, `collided_by_groups`, native collider arrays | 已落地 | 使用 HoTools 碰撞组，不复制 MC2 显式 collider list 配置方式。 |
| params | `param_slots`, scalar/sample API | 部分完成 | 目前是标量；distance/bend/max distance/backstop/collider friction 已按实际值进入求解，接口保留曲线采样空间。 |
| extension | `self_collision`, `bonecloth`, `native` slots | 预留 | 不影响当前 MeshCloth 求解。 |

## C++ 拆分工作表

| 文件/域 | 目标职责 | 当前状态 | Python 对齐来源 |
| --- | --- | --- | --- |
| `hotools_mc2_types.hpp` | 定义 MeshCloth state、param、collider 的 POD view。 | 待做 | `native_bridge.state_arrays_for_native()` |
| `mc2_bindings.cpp` | Python buffer 校验、dtype/shape/contiguous 检查、组装 view。 | 待做 | `native_bridge.build_abi_view()` |
| `mc2_meshcloth_solver.cpp` | substep/iteration 主调度。 | 待做 | `solver.solve_meshcloth_python()` |
| `mc2_distance.cpp` | structural distance projector。 | 待做 | `constraints.project_neighbor_constraints()` |
| `mc2_tether.cpp` | tether 限制。 | 待做 | `constraints.project_tether()` |
| `mc2_motion.cpp` | max distance / motion constraint。 | 待做 | `constraints.project_motion_constraint()` |
| `mc2_collision.cpp` | sphere/capsule point collision。 | 待做 | `collision.project_collisions()` |
| `mc2_bending.cpp` | 当前先对齐 bend distance approximation，后续补 dihedral。 | 待做 | `constraints.project_neighbor_constraints()` 的 bend 输入 |
| `mc2_post.cpp` | velocity、friction、display/post 更新。 | 待做 | `solver.py` post 段 |
| `mc2_angle.cpp` | angle restoration / angle limit。 | 预留 | Python 端尚未完成 |

## 当前推进表

| 工作项 | 当前结果 | 下一步 |
| --- | --- | --- |
| Python 包拆分 | 已从单文件升级为 `physicsMC2` 包，入口在 `__init__.py`。 | 继续只在包内扩展，不再回到单文件。 |
| Python 求解行为 | MeshCloth 可运行，已支持跳帧保护、世界坐标递推、HoTools 碰撞组、structural distance、tether、motion/backstop、velocity_positions、collision friction、substep post、bend distance approximation。 | 继续补 dihedral bending、angle 和外部 base pose 等高保真差异。 |
| native ABI | 已能从 Python state 打包 state/params/colliders view。 | 写 C++ binding smoke，先只验证 buffer 合同。 |
| C++ 求解 | 尚未开始正式求解实现。 | 先按 Python 当前行为逐项迁移，不直接跳到完整 Unity MC2。 |
| 高保真 MC2 差异 | dihedral bending、angle、曲线输入、自碰撞、完整 inertia/base pose 尚未完成。 | 按风险逐项补，优先不破坏当前接口。 |

## 验收工作表

| 场景 | 目标 | 状态 |
| --- | --- | --- |
| 连续播放 | `current_frame == cached_frame + 1` 时连续推进。 | 需 Blender 场景复测 |
| 跳帧/倒放/同帧重复 | 恢复 rest，清掉旧速度，不隐藏 catch-up。 | 需 Blender 场景复测 |
| object transform/scale | world-space cache 不被局部空间半状态污染。 | 需 Blender 场景复测 |
| sphere/capsule collision | 只按 HoTools 碰撞组过滤并投影。 | 需 Blender 场景复测 |
| native ABI smoke | Python 打包数组能被 C++ 读取并校验。 | 待做 |
| Python/C++ parity | 同输入下 C++ 输出接近 Python reference。 | 待做 |
