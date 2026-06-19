# OmniNode MC2 设计目标与工作表
更新日期：2026-06-19

本文合并原来的 `MC2_MODULE_SPLIT_PLAN.md`、`MC2_PYTHON_REPLICATION_STATUS.md`、`MC2_SOLVER_IMPLEMENTATION_PLAN.md`。后续 MC2 相关状态只维护这一份文档。

MC2 源码对照根目录：`D:\Unity_Fork\MagicaCloth2`  
HoTools 实现根目录：`OmniNode/NodeTree/Function/physicsMC2`，native 后端在 `_native`

## 判定口径

| 术语 | 含义 |
| --- | --- |
| 完美对齐 | 只表示“当前 HoTools 支持的输入域和默认/已暴露参数域内，公式、常量、执行含义与 MC2 对应源码一致或等价”。如果 MC2 额外依赖 TeamData、Unity transform、render interpolation、job chunk、BoneCloth、自碰撞等未覆盖上下文，不标为完美对齐。 |
| 高度对齐 | 数学核心和主要常量已对齐，但仍缺少 MC2 的部分上下文、scale/curve/frame 语义或少量边界分支。 |
| 部分对齐 | 当前效果可用，并且复刻了主要行为，但 MC2 源码中仍有明确未实现分支。 |
| 模式不同 | 架构或调度模式刻意不同，不能用“完美/不完美”直接判断，只描述两边模式和边界。 |
| 未做 | 尚未实现，但后续可能需要。 |
| 缓做 | 有价值，但不是当前 MeshCloth/C++ 对比节点的阻塞项。 |
| 不做 | 与当前 Blender/OmniNode 目标冲突，或成本大于收益，明确不实现。 |
| 额外做 | MC2 没有同形态需求，但为了 Blender/OmniNode/C++ parity 需要额外实现。 |

当前优先顺序是：先保证 `meshClothMC2` Python reference 稳定，再让 `meshClothMC2Cpp` 对齐 Python，最后逐项提高与 MC2 源码的等价度。

## 设计与目标大纲

| 主题 | 当前目标/边界 | 状态 |
| --- | --- | --- |
| 第一目标 | 先做 MeshCloth，且输入 mesh 就是用户准备好的低模代理。 | 已落地 |
| 后续目标 | BoneCloth 后续接入，但复用同一套参数、state、baseline、约束、native ABI。 | 缓做 |
| Python 后端 | `meshClothMC2` 是行为参考，不是临时草稿。 | 已落地 |
| C++ 后端 | `meshClothMC2Cpp` 独立节点用于对比；复用 Python 节点的 Blender/cache/collider/writeback 层，只把整帧 solver loop 下沉到 `hotools_native.solve_meshcloth_mc2`。 | 已落地 |
| 运行空间 | solver state 内部以 world-space particle state 递推；节点边界负责 object local/world 转换和输出写回。MC2 与旧 XPBD 物理输出都已改为 solver 内各自维护的 GN 后置 delta，不再通过碰撞属性配置 shape key。 | 已落地 |
| 时间系统 | 刻意使用 Blender 输出帧率计算真实帧长：`frame_dt = fps_base / fps`，`step_dt = frame_dt / substeps`。不复制 MC2 manager 的 wall-clock/catch-up/timeScale。 | 模式不同 |
| Iterations | 保留为 Python/C++ 共享调度参数。当前不复制 MC2 job/chunk 体系，但 C++ 必须对齐 Python 循环语义。 | 已落地 |
| 碰撞系统 | 继续使用 HoTools/OmniNode 碰撞组；MC2 适配逻辑只放在 `physicsMC2` 包内，不抽公共碰撞文件，不改 `Physics.py` 蓝本。 | 模式不同 |
| 参数曲线/组分开关 | 已接入 “基础值 + 浮点曲线” 形式，覆盖 distance、bend、angle restoration、angle restoration velocity attenuation、angle limit、damping、max distance、backstop distance 等当前热路径；已补 `useTether/useDistance/useBend/useAngleRestoration/useAngleLimit/useMaxDistance/useBackstop/useColliderCollision`、tether compression、motion stiffness。gravityFalloff 退回标量，radius 目前刻意保留 mesh/顶点组语义，不作为 solver 曲线输入。 | 部分完成 |
| 全局 TeamData | 不直接搬 MC2 全局 TeamManager。建议后续把当前 per-node cache 收敛成 TeamState-like schema，而不是做全局单例。 | 缓做 |

## 运行调度对照

| 阶段 | MC2 模式/源码 | HoTools 模式/源码 | 对齐判断 |
| --- | --- | --- | --- |
| Manager 入口 | `Runtime/Manager/Cloth/ClothManager.cs`：PreSimulation、Time.FrameUpdate、AlwaysTeamUpdate、WorkBufferUpdate、ClothSimulationSchedule、PostSimulation。 | `physicsMC2/__init__.py`：OmniNode 函数调用、cache 校验、跳帧保护、collider 快照、GN delta 输出写回。 | 模式不同。MC2 是全局 manager；HoTools 是 per-node evaluation。 |
| Normal solver 顺序 | `Runtime/Manager/Simulation/SimulationManagerNormal.cs`：proxy pre、center/inertia/wind、每 step 里 tether/distance/angle/bending/collision/distance/motion/post，最后 display/proxy post。 | `physicsMC2/solver.py` 与 `_native/src/mc2.cpp::solve_meshcloth_mc2()`：baseline、substep inertia、predict/pin、tether、iteration distance/angle/bending/collision/distance/pin、motion、post、centrifugal、display。 | 高度对齐。核心约束顺序已接近 MC2 normal path；没有 MC2 proxy post、wind、split/self collision/job chunk。 |
| Split/job 调度 | `Runtime/Manager/Simulation/SimulationManagerSplit.cs`：chunk 化调度、自碰撞和并行 job 分段。 | 当前 C++ core 是单 state view 的连续数组循环。 | 模式不同，缓做。Python/C++ parity 优先，job 化不是当前阻塞项。 |
| 时间/插值 | `Runtime/Manager/Simulation/TimeManager.cs` 与 `TeamManager.cs`：simulationFrequency、updateCount、frameInterpolation、timeScale、velocityWeight。 | `blender_io.scene_delta_time()` 根据 Blender 输出设置给真实帧长；跳帧/倒放/同帧重复直接 reset 或复用 cache。 | 刻意不同。不按 MC2 wall-clock/catch-up 复制。 |
| C++ 后端边界 | MC2 C# + Burst job 原生执行。 | Python 负责 Blender 对象、frame dt、collider 快照、frame/substep inertia runtime state 准备；C++ 负责数组热路径。 | 已落地。场景级 Python/C++ parity harness 已补，下一步不应继续扩散入口，而是补 MC2 未覆盖分支。 |

## 约束与物理算法对齐表

| 功能域 | MC2 源码 | HoTools Python | HoTools C++ | 对齐判断 | 差异/下一步 |
| --- | --- | --- | --- | --- | --- |
| 系统常量 | `Runtime/Define/SystemDefine.cs` | `constants.py` | `_native/src/mc2.cpp` | 完美对齐：当前关键常量 `Epsilon=1e-8`、display clamp `1.3`、tether width `0.3`、distance horizontal `0.5`、triangle bending max `120`、volume min `90`、angle limit iteration `3` 已一致。 | 后续新增常量必须同时更新 Python 和 C++。 |
| MeshCloth 数据构建 | `Runtime/Cloth/ClothProcess.cs`、`Runtime/VirtualMesh/*`、`Editor/PreBuild/PreBuildDataCreation.cs` | `mesh_build.py`、`state.py` | C++ 只消费 Python 打包数组 | 模式不同。 | 不做 MC2 proxy 生成、减面、重拓扑、高低模 mapping。输入低模就是 solver mesh。 |
| Baseline/step basic pose | `Runtime/Manager/VirtualMesh/VirtualMeshManager.cs`、`SimulationManagerNormal.cs` | `baseline.py` | `update_step_basic_pose_mc2()` | 部分到高度对齐。MeshCloth parent/root/depth/local pose 和 step basic pose 已有 native-first 路径。`hotools_mesh_collision.mc2_base_pose_proxy` 可引用只读 Mesh 对象，逐帧读取其 evaluated mesh 作为 animated base pose。 | 当前采用“双对象读写分离 + 后置 delta”路线：BasePose 对象只读，当前物理对象保留骨架/基础修改器，MC2 结果通过 `mc2_delta` 和 `MC2 后置位移` GN 修改器叠加。BoneCloth builder 另行缓做。 |
| Structural distance | `Runtime/Cloth/Constraints/DistanceConstraint.cs` | `constraints.project_neighbor_constraints()`、`mesh_build.py` | `project_neighbor_constraints_mc2()` | 高度对齐。支持 signed rest、horizontal 负 rest、horizontal stiffness、固定邻点质量、zero rest midpoint、velocity_positions attenuation。 | 不完美点：当前 `animation_pose_ratio` 固定为 0；MC2 可在初始 rest 和动画后 base pose 距离间 lerp；runtime scale/negative scale 语义未完整复制。 |
| Shear 横向连接 | `DistanceConstraint.CreateData()` 中共享边 triangle pair 的 p3-p4 shear | `mesh_build.append_mc2_shear_links()` | distance projector 消费同一 neighbor table | 高度对齐。按 MC2 的同面 20 度、对角线比例 0.3、horizontal type 生成。 | 不复制 MC2 proxy 生命周期；只在当前输入 mesh 上直接生成。 |
| Tether | `Runtime/Cloth/Constraints/TetherConstraint.cs` | `constraints.project_tether()` | `project_tether_mc2()` | 高度对齐。compression/stretch limit、stiffness width ramp、velocity attenuation、节点级 `use_tether` 与 compression 输入已对齐。 | 不完美点：MC2 每 step 用 `stepBasicPositionBuffer` 算当前基准距离；当前 HoTools 使用构建出的 root rest length，动态 base pose 场景仍需补。Python fallback 和 C++ full-core 关闭 tether 时都显式早退，不再用特殊阈值模拟关闭。 |
| Angle restoration/limit | `Runtime/Cloth/Constraints/AngleConstraint.cs` | `constraints.project_angle_constraints()` | `project_angle_constraints_mc2()` | 高度对齐。AngleLimitIteration=3、limit rot ratio、restoration rot ratio、velocity attenuation 值+曲线、gravity falloff 标量、0.2 restoration scale、parent/child correction 逻辑已复刻。 | 不完美点：MC2 TeamData gravityDot 上下文未接；需要链状/网格场景继续校准。 |
| Triangle bending/volume | `Runtime/Cloth/Constraints/TriangleBendingConstraint.cs` | `mesh_build.build_dihedral_constraints()`、`constraints.project_triangle_bending()` | `project_triangle_bending_mc2()` | 高度对齐。DirectionDihedralAngle、Volume、固定点低逆质量、MaxAngle/VolumeMin/VolumeScale 已对齐。 | 不完美点：runtime scaleRatio、negativeScaleSign、MC2 proxy local/world 生命周期未完整复制。 |
| Motion/max distance/backstop | `Runtime/Cloth/Constraints/MotionConstraint.cs` | `constraints.project_motion_constraint()` | `project_motion_constraints_mc2()` | 高度对齐。max distance、backstop radius/distance、motion stiffness、`use_max_distance/use_backstop`、velocity attenuation 已有；normalAxis 已按 MC2 的 `baseRot * axis` 语义接入 Python 与 C++。 | BasePose 场景通过只读对象提供 animated base pose；后续重点是复杂骨架/修改器链校准。 |
| Collider point/edge collision | `Runtime/Cloth/Constraints/ColliderCollisionConstraint.cs`、`Runtime/Manager/Simulation/ColliderManager.cs` | `collision.py`、`solver.py` | `project_collisions_mc2()`、`project_edge_collisions_mc2()`、`solve_meshcloth_mc2()` | 对 MC2 已有的 sphere/capsule/plane point/edge collision 严格对齐，并额外扩展 HoTools Box OBB point/edge collision。节点 `use_collider_collision` 可直接跳过场景 collider 快照，`collider_collision_mode`：0=关闭外部碰撞，1=Point collision，2=Edge collision。group filter、collision normal/friction、post friction、moving collider old/next pose 推出平面已实现。Plane 按 MC2 `PointPlaneColliderDetction()` 的无限半空间语义处理：`cpos + normal * particleRadius` 为推出平面。当前 `hotools_mesh_collision` 只作为本 cloth 顶点 `collision_radii` 的来源，不会把其他 mesh 顶点展开成外部 sphere collider。 | 不完美点：BoneSpring soft collider 未实现；Box collider 是 HoTools 额外 OBB 扩展，MC2 源码只保留 Box enum/size 数据，当前 MC2 point/edge solver 源码均无 Box collision 分支；HoTools collider 来源仍是 Blender scene snapshot，而不是 MC2 全局 ColliderManager。 |
| Post velocity/friction | `SimulationManagerNormal.cs` post step | `constraints.apply_post_step()` | `apply_post_step_mc2()`/`solve_meshcloth_mc2()` 内 post | 高度对齐。velocity、real_velocity、old_positions、friction、static_friction、particle speed limit 已有。 | 不完美点：MC2 velocityWeight/stabilization、culling/skip/timeScale 相关分支未完整复制。 |
| Inertia/teleport/centrifugal | `Runtime/Cloth/Constraints/InertiaConstraint.cs`、`Runtime/Manager/Team/TeamManager.cs`、`SimulationManagerNormal.cs` | `inertia.py` | `apply_substep_inertia_mc2()`、`apply_centrifugal_velocity_mc2()` | 部分对齐。world/local/depth inertia、movement smoothing、world/local speed limit、teleport reset/keep、particle speed limit、centrifugal 已有。 | 未完整实现 anchor inertia、sync team、negative scale teleport、velocityWeight、culling/skip/timeScale。frame/object runtime state 暂留 Python。 |
| Display prediction | `SimulationManagerNormal.cs::SimulationCalcDisplayPosition()`、`Define.System.MaxDistanceRatioFutuerPrediction` | `solver._calc_display_positions()` | `calculate_display_positions_mc2()` | 高度对齐。`position + real_velocity * frame_dt` 和 root distance * 1.3 clamp 已实现。 | 不完美点：Unity render-time interpolation、blendWeight、proxy/render mapping 未复制。 |
| Self collision | `Runtime/Cloth/Constraints/SelfCollisionConstraint.cs` | 仅保留 extension slot | 未实现 | 未做/缓做。 | 工作量大，先不阻塞 MeshCloth C++ parity。不同 MeshCloth 之间的互碰也归入这一类需求；它不是简单把 mesh 顶点球塞进 collider list，还需要质量、所有权、接触汇总和多 body 调度语义。 |
| Wind | `Runtime/Cloth/Wind/*`、`TeamManager.UpdateWind()` | 未实现 | 未实现 | 未做/缓做。 | 不是当前基础 cloth 约束和 C++ 对比节点阻塞项。 |
| BoneSpring/BoneCloth | `SpringConstraint.cs`、BoneCloth builder 相关源码 | solver ABI 预留 | 未实现 | 缓做。 | MeshCloth 稳定后再接 I/O adapter 和 builder，solver 数组层尽量复用。 |

严格结论：当前没有把完整 MC2 产品级行为“完美搬完”。在当前 MeshCloth 输入域内，distance/shear/tether/angle/bending/post/display 属于高对齐；collider、inertia、motion/backstop 因 MC2 manager/TeamData/base pose/collider pose 上下文缺失，不能标成全域完美。

## 参数面对照缺口

本节按 `Runtime/Cloth/ClothSerializeData.cs`、`ClothSerializeDataFunction.cs` 与各 Constraint `SerializeData/Params` 实际代码对照。结论是：引入 PropertyCurve 后，当前 MeshCloth 主约束已经能表达 MC2 的“曲线加值”核心模式，但还不能说参数面完全对齐。

| MC2 参数域 | MC2 语义 | HoTools 当前状态 | 结论/下一步 |
| --- | --- | --- | --- |
| `damping` | `CurveSerializeData`，转成 `dampingCurveData * 0.2`，在 post 阶段按 depth 采样阻尼。 | `damping + damping_curve` 已进入 Python/C++ solver；Python 侧按 depth 采样并乘 0.2，再转成 substep damping 数组传给 native full-core。 | 已接入；后续主要做默认曲线快速路径/缓存采样结果。 |
| `radius` | `CurveSerializeData`，碰撞与 motion/backstop 按 depth 采样粒子半径。 | 当前半径语义刻意放在 mesh/collision 数据上：`collision_radius` 与 `hotools_mesh_collision.radius` 顶点组继续生成/维护 `collision_radii`；暂不接入 solver 曲线输入。 | 设计决定：半径暂保持 mesh/顶点组语义，后续若要改成 MC2 曲线语义必须单独评估重建/缓存边界。 |
| `distanceConstraint.stiffness` | `CurveSerializeData`，基础值乘曲线，按 depth 控制 distance stiffness。 | `distance_stiffness + distance_stiffness_curve` 已进入 Python/C++ solver。 | 已接入；后续补默认/预设与性能快路径。 |
| `triangleBendingConstraint.stiffness` | MC2 是标量 stiffness。 | 当前 `bend_stiffness + bend_stiffness_curve` 支持按 depth 曲线，属于 HoTools 额外增强。 | 功能超集；若要严格 MC2 preset 映射，默认应按标量 1->1。 |
| `angleRestorationConstraint` | `useAngleRestoration`、stiffness 曲线、velocityAttenuation、gravityFalloff。 | `use_angle_restoration`、stiffness 曲线、velocityAttenuation 值+曲线已接；gravityFalloff 暂按标量处理。关闭时 Python fallback 跳过 angle 投影，C++ full-core 走零数组空操作。 | 基本接入；TeamData gravityDot 语义仍属于更大的 TeamState/base pose 工作，当前不把它暴露成曲线。 |
| `angleLimitConstraint` | `useAngleLimit`、limitAngle 曲线、stiffness。 | `use_angle_limit`、limitAngle 曲线和 stiffness 已接；关闭时 Python fallback 跳过，C++ full-core 走零数组空操作。 | 基本接入；后续主要是默认预设和校准。 |
| `motionConstraint` | `useMaxDistance`、maxDistance 曲线、`useBackstop`、backstopRadius 标量、backstopDistance 曲线、stiffness 标量、normalAxis。 | `use_max_distance/use_backstop`、maxDistance/backstopDistance 曲线、backstopRadius 标量、motion stiffness、normalAxis 输入已接；两者都关闭时跳过/零数组。 | 基本接入；normalAxis 已对齐，external base pose rotation 仍需单独输入源。 |
| `tetherConstraint.distanceCompression` | MeshCloth 可配置标量 compression；stretch 为系统常量。 | `use_tether` 与 `tether_compression` 已暴露；stretch 仍保持系统常量。Python fallback 与 C++ full-core 关闭时都直接跳过 tether。 | 基本接入；关闭语义已收紧到显式开关。 |
| `inertiaConstraint.anchor/anchorInertia` | Anchor 运动从惯性中剔除，可配置 anchorInfluence。 | 未实现 anchor 输入和 anchorInertia。 | P1/P2 取决于是否需要载具/父物体剔除惯性场景。 |
| `inertiaConstraint` 速度限制类 | MC2 用 CheckSlider，可关闭时传 -1。 | 当前用数值约定，负数等价无上限；没有显式开关。 | 语义基本可用，但 UI/参数面不完全同构。 |
| `gravityFalloff` | TeamData 根据初始姿态 gravityDot 衰减重力。 | 未接 TeamData gravityDot，仅有普通 gravity direction/power。 | 需要 TeamState-like 上下文后再补。 |
| `stablizationTimeAfterReset` / `blendWeight` | reset 后 velocityWeight 平滑恢复，并参与显示 blend。 | 未实现。 | 仍是明确缺口。 |
| `animationPoseRatio` / `normalAxis` | distance rest lerp、motion/backstop 法线轴和 baseRot 相关。 | `animation_pose_ratio` 固定 0；normalAxis 已接入 motion/backstop，使用 `baseRot * axis`。 | external base pose rotation 输入源仍需继续。 |
| `colliderCollisionConstraint.limitDistance` | 主要给 BoneSpring 限制 collider 推出距离。 | MeshCloth 当前不需要；未接。 | MeshCloth 可暂缓，BoneSpring 时再接。 |
| SelfCollision / Wind / Spring / BoneCloth 参数 | 独立大系统或非 MeshCloth 主路径。 | 未实现或仅预留 extension slot。 | 不属于当前 MeshCloth 参数面对齐完成范围。 |

## 当前完成工作表

| 类别 | 项目 | 文件 | 状态 |
| --- | --- | --- | --- |
| 节点入口 | Python reference `meshClothMC2` | `physicsMC2/__init__.py` | 已完成 |
| 节点入口 | C++ 对比节点 `meshClothMC2Cpp` | `physicsMC2/__init__.py` | 已完成 |
| Cache/schema | world-space runtime state、schema guard、轻量缓存判定、jump/reset 保护、collider previous snapshot | `state.py`、`__init__.py`、`collision.py` | 已完成；当前 schema version 14。运行期为了避免每帧扫描拓扑，缓存命中只比较对象/mesh 标识和顶点/loop/面数量；同数量拓扑变化不会自动失效，必须通过 reset/清缓存重建。 |
| Blender I/O | GN delta 写回、local/world 转换、scene dt、BasePose evaluated mesh 帧缓存 | `blender_io.py` | 已完成 |
| Mesh 构建 | pin/weight、distance neighbor table、MC2 shear、dihedral/volume、bend fallback | `mesh_build.py` | 已完成当前 MeshCloth 域 |
| Baseline | parent/root/depth/local pose、step basic pose | `baseline.py`、`_native/src/mc2.cpp` | 已完成当前 MeshCloth 域 |
| 约束 | distance、tether、angle、triangle bending、motion/backstop、post | `constraints.py`、`_native/src/mc2.cpp` | 已完成当前 Python/C++ parity 域 |
| 参数曲线/组分开关 | distance/bend/angle restoration/angle restoration attenuation/angle limit/damping/max distance/backstop distance 的值 + 曲线输入；gravityFalloff 标量；tether/distance/bend/angle/motion/collision 显式开关；tether compression 与 motion stiffness 输入；radius 保持 mesh/顶点组语义 | `PropertyCurve/*`、`physicsMC2/params.py`、`physicsMC2/solver.py`、`physicsMC2/__init__.py`、`_native/src/mc2.cpp` | 已接入当前热路径；后续主要补默认曲线快速路径、base pose/negative scale 等 MC2 上下文语义 |
| 碰撞 | 碰撞模式 0/1/2、sphere/capsule/plane point collision、sphere/capsule/plane edge collision、Box OBB 额外 point/edge collision、group filter、friction/normal、moving collider old/next pose、native collider arrays | `collision.py`、`solver.py`、`native_bridge.py`、`_native/src/mc2.cpp`、`_native/src/hotools_native.cpp` | 已完成当前 point/edge collision 域；sphere/capsule/plane 严格按 MC2 对齐；Plane 已按 MC2 无限半空间平面对齐；Box 是 HoTools 额外扩展 |
| Inertia | world/local/depth inertia、movement smoothing、teleport、centrifugal | `inertia.py`、`_native/src/mc2.cpp` | 部分完成 |
| Native bridge | buffer 校验、state/params/collider/inertia 打包、old/next collider ABI、full-core 调用 | `native_bridge.py`、`_native/src/hotools_native.cpp` | 已完成首版 |
| Native full core | `solve_meshcloth_mc2` 整帧数组 core | `_native/src/mc2.cpp` | 已完成首版 |
| 测试 | native kernel smoke、solver core smoke、Blender 场景级 Python/C++ parity harness | `_native/tests/*` | 已完成；`test_mc2_blender_scene_parity.py` 覆盖 12 帧 max/RMS delta、stretch error、collision count |

## 未做工作表

| 项目 | 原因 | 建议优先级 |
| --- | --- | --- |
| MeshCloth 互碰 / mesh 顶点球外部碰撞 | 当前 `hotools_mesh_collision` 只决定本 cloth 顶点碰撞半径；尚未把其他 mesh 的逐顶点球展开为外部 sphere collider。该需求与 self collision 同类，需要新增 mass/所有权/接触汇总等语义。 | P3 |
| external animated base pose position/rotation | 已接入物体碰撞属性 `BasePose只读对象`：MC2 每帧只读该对象的 evaluated mesh 世界坐标/法线，更新 `base_positions/base_rotations/step_basic_*`，再把 `display_positions - base_positions` 写入当前物理对象的 `mc2_delta`，由后置 GN 修改器叠加。 | P0 基础可用；仍需继续测试复杂骨架、修改器链、顶点顺序变化和高模形变工作流。 |
| negative scale teleport/scaleRatio/negativeScaleSign | Distance/bending/inertia 在 runtime scale/negative scale 场景仍不完整。 | P1 |
| radius 曲线 | MC2 `radius` 是运行期值 + 曲线；当前 HoTools 半径刻意来自 `collision_radius` 或 `hotools_mesh_collision` 顶点组，并且暂不进入 solver 参数曲线。 | 暂不做 |
| velocityWeight/stabilization | MC2 reset 后速度权重稳定化未完整复制。 | P2 |

## 不做工作表

| 项目 | 不做原因 |
| --- | --- |
| Mesh reduction/减面/重拓扑/代理生成 | 当前工具目标是用户自己准备低模代理；solver 不负责资产生成。 |
| 高低模 render mapping | Blender 这边不复制 MC2 Unity render mesh mapping 生命周期；BasePose/骨架叠加场景改为在低模代理上后置写入 `mc2_delta`，高模继续绑定到最终低模代理。 |
| 复制 MC2 wall-clock/catch-up/timeScale | Blender 输出帧率已经给出真实帧间隔；用 wall-clock 反而会让离线输出不可控。 |
| 直接搬 MC2 全局 TeamManager 单例 | OmniNode 是 per-node evaluation/cache；全局 manager 会增加状态耦合，不利于节点对比和 C++ parity。 |
| 修改 `Physics.py` 蓝本或抽公共碰撞模块 | SpringBone/XPBD 继续作为对照蓝本；MC2 碰撞适配只在 `physicsMC2` 内部维护。 |

## 缓做工作表

| 项目 | 缓做原因 | 触发条件 |
| --- | --- | --- |
| Self collision / MeshCloth 互碰 | MC2 自碰撞是独立大系统，包含 primitive/grid/contact/intersect 多阶段；MeshCloth 互碰本质上也需要类似的多体接触模型，并且还要补 mass、所有权、接触汇总和调度规则。当前不把其他 mesh 的 `hotools_mesh_collision` 顶点球展开成外部 collider，避免先做出只有几何、没有物理语义的半成品。 | 基础 MeshCloth 场景 parity 稳定后，并且明确 mass/多体接触语义后。 |
| Wind | 依赖 TeamData/zone/moving wind 语义；当前约束和碰撞优先。 | Cloth 基础手感稳定后。 |
| BoneCloth/BoneSpring | 需要新 I/O adapter 和 builder；solver 数组层已尽量预留。 | MeshCloth C++ 后端稳定后。 |
| Job/chunk/split scheduling | Python 侧没有同构 job 系统；先保证单数组 core 语义正确。 | 性能瓶颈明确或进入并行 C++ 阶段。 |
| TeamData-like cache 重构 | 方向正确，但不应阻塞当前 C++ 对比节点。 | 场景级 parity 和 moving collider ABI 已完成；进入 P1 结构整理时触发。 |
| Unity render interpolation/blendWeight | 当前 display prediction 已可用；完整 render 插值与 Blender shape key 工作流不完全同构。 | 用户明确需要 Unity 式显示混合时。 |

## 额外做工作表

| 项目 | 为什么额外做 |
| --- | --- |
| `meshClothMC2Cpp` 独立节点 | MC2 没有这个节点形态；这是为了在 Blender 里直接对比 Python/C++ 后端效果。 |
| Python reference 保留 | C++ 开发需要稳定行为蓝本，避免直接在 C++ 发明新行为。 |
| HoTools 碰撞组适配 | Blender/OmniNode 已有碰撞组工作流；比复制 MC2 Unity collider list 更符合当前架构。 |
| jump-frame/reset 保护 | Blender 时间轴可以跳帧、倒放、同帧重复求值；必须额外保护 cache。 |
| GN 后置 delta 输出 | MC2 Unity 侧不是这个输出形态；这是 Blender 修改器栈下为了在骨架/基础变形后叠加物理的必要适配。BasePose 场景不再把最终结果写入 shape key；通用写回机制在 `PhysicsTools/deltaOutput.py`，各后端使用自己的 attribute/modifier/node group 名称。 |
| `ParamSlot`/sample 内部结构 | 当前 UI 先传标量，但先把 solver 写成可接曲线，避免后续重写核心。 |
| MC2 轻量缓存判定 | 连续帧性能优先，正常运行不每帧计算完整拓扑 hash/config hash；只用对象/mesh 标识和顶点/loop/面数量复用 cache。拓扑同数量变化、pin/collision 配置同帧变化需要用户 reset/清缓存重建。 |
| MC2 组分开关 | distance/bend/angle/motion/collision 关闭时减少曲线采样、投影调用或 collider 快照扫描；tether 在 Python fallback 和 C++ full-core 中都由显式 `use_tether` 早退。 |
| native full-core + 逐 kernel fallback 并存 | 便于定位 Python/C++ 差异；full-core 用于真实节点，逐 kernel 用于 smoke/parity。 |

## 后续推进建议

| 优先级 | 工作 | 目标 |
| --- | --- | --- |
| P0 已完成 | Blender 场景级 `meshClothMC2` vs `meshClothMC2Cpp` parity harness。 | `_native/tests/test_mc2_blender_scene_parity.py` 已落地，当前 12 帧 point/edge collision mode 的 max/RMS/stretch/collision count delta 为 0。 |
| P0 已完成 | moving collider old/next pose ABI。 | `collision.py` 保存 previous collider snapshot；`native_bridge.py` 和 `_native/src/hotools_native.cpp` 传递 old/current arrays；`_native/src/mc2.cpp` 用 old pose 求法线、current pose 推平面。 |
| P0 已完成 | Edge collision 模式。 | `meshClothMC2`/`meshClothMC2Cpp` 新增碰撞模式输入；`collision.py`、`solver.py`、`native_bridge.py`、`_native/src/mc2.cpp`、`_native/src/hotools_native.cpp` 已实现 sphere/capsule/plane edge collision，并额外扩展 Box OBB edge collision；Blender 5.1 场景 parity 已验证。 |
| P0 基础接入 | external animated base pose。 | 当前采用 `hotools_mesh_collision.mc2_base_pose_proxy` 双对象方案：只读 BasePose 对象提供骨架/修改器后的基础姿态，当前物理对象保留骨架/基础修改器，并通过 `mc2_delta` + `MC2 后置位移` GN 修改器叠加物理偏移。 |
| P1 | 曲线采样快速路径。 | 目前 `param_curves` / `stiffness_curves` / `motion_curves` 仍会做完整 `resolve + sample`；默认 1->1、无变化曲线应直接走标量或缓存采样结果，避免每帧重复采样。 |
| P1 | `abi_view` 按需构造。 | `post_pack` 现在每帧重建 native ABI 视图，属于偏调试的数据打包；正常运行应尽量只保留 solve 必需数组。 |
| P1 | 细化 `solve_setup`。 | 把高频准备拆成更小、更稳定的块，优先压缩曲线参数整理、惯性子步数组和 native 输入打包的 Python 开销。 |
| P1 | persistent native context。 | 后续把拓扑固定、参数固定、曲线固定时的重复准备下沉到 C++ 持久上下文，Python 只提交动态输入和写回结果。 |
| P1 | 把 cache/state 命名和结构逐步收敛成 per-node TeamState-like schema。 | 方便继续对照 MC2 TeamData，同时避免全局 manager 耦合。 |
| P1 | 补 negative scale。 | normalAxis 已完成；external animated base pose 已提升为 P0。negative scale 仍用于提高 runtime scale/teleport/scaleRatio 等 MC2 行为等价度。 |
| P1 | 继续收敛 MC2 参数面与上下文语义。 | damping 与 angle attenuation/falloff 已按值+曲线接入，normalAxis 已接入；radius 暂保持 mesh/顶点组语义。后续重点转向 external base pose rotation、negative scale、anchor/velocityWeight 等上下文缺口。 |
| P3 | self collision、wind、BoneCloth、job/chunk。 | 等主路径稳定后作为独立阶段推进。 |

### P0：BasePose 与 GN 后置输出约定

BasePose 的目标是在“骨架/基础修改器已经变形后的低模代理姿态”上叠加 MC2 物理。正式架构是“双对象读写分离 + GN 后置 delta”：

1. `hotools_mesh_collision.mc2_base_pose_proxy` 是只读 BasePose 对象；它提供 evaluated mesh 的 `base_positions/base_normals`，并参与 `base_rotations/step_basic_*` 更新。
2. 当前物理对象是写入对象；它可以保留骨架和基础修改器，但不再写 shape key，也不读取碰撞属性里的 `output_shape_key`。
3. 求解输出写入当前物体的 `mc2_delta` 点域 `FLOAT_VECTOR` 属性，由 `MC2 后置位移` Geometry Nodes 修改器在修改器栈末尾消费。
4. 写入值为 `display_positions - base_positions`，并在写入前从 world delta 转换为当前对象局部 offset。
5. BasePose 对象与当前物理对象必须保持相同顶点数、loop 数、面数和顶点顺序；运行时只做轻量数量检查，拓扑变化需要用户刷新 BasePose 并 reset/清缓存。
6. 自动生成/刷新的 BasePose 对象统一放入 `HoPhysicsCache` 集合，并移除历史输出 shape key、`mc2_delta` 属性和 `MC2 后置位移` 修改器。
7. `output_shape_key` 碰撞属性已移除；MC2 运行路径不创建、不写入目标 shape key。

结论性约束：

1. shape key 不能作为 MC2 的最终输出模型，因为它在 Armature 等形变修改器之前生效，会导致骨架场景的双重变形。
2. 不做通用 Armature 反解写回；Blender 修改器链包含 Preserve Volume、B-Bone、多修改器和非线性修改器时无法可靠反解。
3. 不在运行帧里通过“临时屏蔽输出 + 强刷 depsgraph + 读取同对象 evaluated mesh”获取 base pose；这会引入反馈环、刷新不稳定和过高的 Python 侧开销。
4. BasePose 模式下，写入对象的 `matrix_world` 不用于重建 rest/约束，也不驱动整体 inertia；基础位移由 BasePose evaluated mesh 表达。
5. 后续优化方向是复杂骨架/修改器链校准、BasePose 读取缓存和必要时下沉到 C++，不是回退到 shape key 输出。
