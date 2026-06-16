# OmniNode MC2 Python 复刻进度

本文档记录 `Function/physicsMC2/__init__.py` 对 MagicaCloth2 的 Python 复刻进度、当前差异、后续目标，以及进入 C++ 后端前应满足的准入条件。

Python/C++ 模块拆分的详细方案见 `MC2_MODULE_SPLIT_PLAN.md`。本文档只记录复刻状态和差异。

结论先写在前面：建议先把 Python 端作为行为蓝本尽量复刻到稳定状态，再做 C++ 后端。C++ 第一版应以 Python parity 为目标，而不是直接在 C++ 里补完整 MC2；否则 Python/CPP 两端会同时漂移，接口和 cache 协议会很难稳定。

## 当前边界

必须继续遵守：

- Python 端已经升级为 `Function/physicsMC2/__init__.py` 小模块包；当前实现仍集中在入口文件中，后续可逐步拆包内私有模块。
- 旧 `Physics.py` 中 SpringBone/XPBD solver 继续作为蓝本隔离，不为了 MC2 抽公共碰撞文件。
- MeshCloth 输入永远是用户提供的低模代理；不做 reduction、减面、重拓扑、代理生成、高低模 mapping。
- 先 MeshCloth，后 BoneCloth；共通数据结构和求解设施先在 `physicsMC2` 包内按类/函数分层。
- 自碰撞暂不实现，但保留 cache/native 扩展空间。
- 曲线参数当前可先用标量值，但参数访问层必须保留曲线采样表入口。
- 时间语义对齐 SpringBone/XPBD：按 Blender 工程输出帧率 `render.fps / render.fps_base` 得到真实 `frame_dt`，每次节点执行只推进一个 Blender 输出帧。

## 已完成内容

文件：

```text
OmniNode/NodeTree/Function/physicsMC2/__init__.py
```

当前已可运行：

- `meshClothMC2(enable=True)` 节点已进入物理分类菜单。
- 直接读取输入 mesh 顶点、边、loop triangles 作为低模代理连接关系。
- 输出写回 `MC2MeshCloth` 或 `hotools_mesh_collision.output_shape_key` 指定的 shape key，不修改 Basis。
- cache 保存 world-space particle state，并在节点边界做 local/world 转换。
- 跳帧、倒放、同帧重复时不继承旧速度，恢复 rest pose 并返回空 cache。
- `reset=True` 优先于跳帧判断，可在任意帧重建状态。
- per-frame damping 换算为 per-substep damping：

```python
substep_damping = 1.0 - ((1.0 - damping) ** (1.0 / substeps))
```

- 基础属性构建：fixed/move/motion、depth、root、parent、root length。
- 距离约束：基于输入 edge 的 per-vertex neighbor 平均修正。
- 弯曲近似：基于相邻 triangle 对角点的 neighbor 距离修正。
- Tether：基于 fixed root 的 compression/stretch 两侧限制，压缩默认 0.4，拉伸默认 0.03，对齐 MC2 系统常量。
- Motion：当前做 max distance，并已加入 stiffness lerp 参数槽；backstop 仍未实现。
- 碰撞：直接读取 HoTools 现有 object/bone sphere/capsule 碰撞体和碰撞组，做 point collision，并已加入多 collider 合成推离与 collision normal 聚合。
- Debug timing：validate/cache/restore/rebuild/transform/colliders/solve/write 等阶段聚合输出。
- cache/native 扩展槽：curve、bonecloth、self_collision、native；native 槽已能打包当前 collider arrays。

## 与 Unity MC2 的主要差异

### 1. 积分模型

当前 Python：

```python
inertia = (positions - old_positions) * (1.0 - substep_damping)
positions += inertia + gravity * step_dt * step_dt
```

Unity MC2 Normal 路径：

```text
velocity *= velocityWeight
velocity *= 1 - damping
velocity += force * simulationDeltaTime
nextPos += velocity * simulationDeltaTime
```

差异：

- Python 是 Verlet 风格位移积分，更接近现有 XPBD mesh。
- MC2 是显式 velocity buffer，并在 PostTeam 中根据约束后的 `nextPos - velocityOldPos` 重建速度。
- Python 当前保存 `velocity/real_velocity`，但它们更多是诊断/预留，不是主积分状态。

目标：

- C++ 前先决定是否继续以 Python Verlet 为第一版基准。
- 如果要转向 MC2 velocity 模型，应先在 Python 改完并验证，再固化 C++ ABI。

### 2. DistanceConstraint

当前 Python：

- 使用输入 mesh edges 构建邻接。
- 每个顶点对邻居约束取平均修正。
- `distance_stiffness` 是单个标量。

Unity MC2：

- 区分 vertical / horizontal，horizontal 通过负 rest distance 标记。
- 自动补 shear 连接。
- 按 depth curve 采样 stiffness。
- 约束修正还会反向影响 `velocityPosArray`，用于后续速度计算。

目标：

- 先补 `distance_type`/vertical-horizontal 数据结构，即使第一阶段仍用同一 stiffness。
- 再补 depth sampler。
- shear 连接是否需要引入要谨慎：它不是减面/重拓扑，但会改变用户输入连接关系的约束密度。若加入，必须明确它只是 solver 内部约束，不修改 mesh。

### 3. TetherConstraint

当前 Python：

- 已处理 compression 与 stretch。
- `root_rest_lengths` 保存 root 路径长度，主要用于 depth；`tether_rest_lengths` 保存粒子到 root 的基础姿态直线距离，用于 tether 求解。
- 不更新 velocity position。

Unity MC2：

- 同时处理 compression 和 stretch。
- compression 软、stretch 硬，使用不同 stiffness/attenuation。
- 使用 step basic pose 作为恢复距离参考。
- 会把修正写入 `velocityPosArray`。

目标：

- 后续只需要把 tether 参数槽暴露到节点输入或曲线采样表。
- 若切换到 MC2 velocity 模型，要同步处理 `velocity_positions`。

### 4. MotionConstraint

当前 Python：

- 做 `max_distance`，并用 `motion_stiffness` 在旧位置和约束位置之间 lerp。
- 以 `base_positions` 为中心。
- 没有 backstop、normal axis、velocity 影响。

Unity MC2：

- max distance 和 backstop 都相对 base pose。
- backstop 依赖 base rotation 和 normal axis。
- 最终用 stiffness 在旧位置和约束位置之间 lerp。
- 会写入 `velocityPosArray`。

目标：

- 继续补 normal axis 和 backstop radius/distance。
- backstop 需要 base rotation，MeshCloth 当前没有完整 per-particle rotation，需要先确定简化策略。

### 5. TriangleBendingConstraint

当前 Python：

- 从相邻 triangles 得到对角点 pair。
- 使用对角点距离作为 bend rest length。
- 没有二面角、方向 sign、volume pair。

Unity MC2：

- 生成 `trianglePairArray`。
- 存 `restAngleOrVolumeArray`。
- 存 `signOrVolumeArray`。
- DirectionDihedralAngle 是固定模式。
- 大角度 pair 可转 volume。
- Solver 先写 buffer，再 SumConstraint 聚合到粒子。

目标：

- 这是 MeshCloth fidelity 的最大缺口。
- 建议 Python 端先补 DirectionDihedralAngle 数据构建和求解，再考虑 volume。
- C++ 第一版如果先做 parity，可以继续实现当前 Python bend；但在文档和命名里必须叫 `bend_distance_approx`，避免误称 MC2 triangle bending。

### 6. ColliderCollisionConstraint

当前 Python：

- 使用 HoTools 碰撞组，支持 object/bone sphere/capsule。
- 对每个顶点聚合所有命中的 collider 推离向量，并按平均法线长度抑制夹挤抖动。
- 保存 `collision_normals`，但暂未驱动 friction。
- 不支持 plane、edge collision、摩擦。

Unity MC2：

- 原生使用显式 collider list。
- 支持 point/edge collision。
- 支持 sphere/capsule/plane。
- 多 collider 接触会聚合推离，减少夹挤抖动。
- 会计算 dynamic/static friction，并在 PostTeam 影响速度。

目标：

- 继续使用 HoTools 碰撞组，不照搬显式 collider list。
- friction 可以作为第二阶段，必须和 velocity 模型一起考虑。
- edge collision 可继续延后。

### 7. Inertia / Teleport / Display

当前 Python：

- 跳帧/倒放/同帧重复直接 reset cache。
- object transform 改变时会重采样 rest world、约束长度和半径。
- 没有 MC2 center inertia、anchor、negative scale teleport、display interpolation、blend weight。

Unity MC2：

- TeamData 维护 frame/update time、skip count、time scale、frame interpolation。
- InertiaConstraint 管理中心惯性、anchor、速度限制、teleport。
- Display position 可能使用未来预测和 blend。

目标：

- OmniNode 不需要复制 MC2 TeamManager 全局时间系统。
- 但需要在 Python 端明确“每节点执行一帧”的简化语义，并保留 display/interpolation 扩展槽。
- 若用户需要外部动画输入驱动 base pose，必须先在 Python 增加 base pose 更新入口。

## 建议路线

推荐路线：先 Python fidelity，再 C++。

理由：

- Python 负责 Blender I/O、cache 生命周期、shape key 写回和跳帧规则。接口不稳定时先写 C++，会频繁改 C++ ABI。
- C++ 只能可靠加速已经稳定的数组协议；不适合同时承担物理语义探索。
- Python 入口文件虽然不适合长期承载全部实现，但可以先用类和函数边界把数据构建、参数采样、约束求解、碰撞、native 打包清楚分层，再逐步拆到包内私有模块。
- 等 Python 行为接近目标后，C++ 端可以拆很多文件；那时拆分不会反向污染节点接口。

可接受的折中：

1. 先把 Python 当前实现的 cache 校验、参数槽、命名修一轮。
2. 做一个 C++ parity 原型验证 native 桥接成本，但只覆盖当前 Python 行为。
3. 暂不把这个 C++ 节点作为正式推荐后端。
4. Python 继续补 MC2 fidelity；每次语义稳定后再同步 C++。

不建议：

- 直接在 C++ 中实现更完整的 MC2，再回头迁 Python。
- 这样会形成两套不同物理行为，节点接口、cache schema、测试基准都很难收敛。

## Python 端下一阶段目标

进入正式 C++ 后端前，建议 Python 至少完成：

### P0: 接口与 cache 稳定

- `state_matches()` 校验所有 C++ 必需数组：
  - `edges`
  - `triangles`
  - `edge_i/edge_j/edge_rest`
  - `bend_i/bend_j/bend_rest`
  - `distance_data/distance_rest`
  - `bend_data/bend_neighbor_rest`
  - `velocity`
  - `real_velocity`
  - `friction`
  - `static_friction`
  - `collision_normals`
- 明确 cache schema version 变更规则。
- 增加 `collider_arrays_for_native()`，但仍放在 `physicsMC2` 包内部，不抽公共文件。
- 将当前 bend 明确命名为 bend distance approximation，给未来 dihedral bending 留字段。

当前状态：前三项已完成，bend 命名还未清理。

### P1: 参数采样与 MC2 参数形状

- 所有 stiffness/radius/max_distance/damping 继续走 `sample_param()`。
- 增加未来曲线输入所需的 samples cache 字段。
- 增加：
  - tether compression
  - tether stretch
  - motion stiffness
  - backstop radius/distance
  - collider friction 参数槽

当前状态：tether compression、tether stretch、motion stiffness、backstop radius、backstop distance、collider friction 参数槽已预留；backstop/collider friction 还未参与求解。

### P2: 求解顺序贴近 MC2

当前大体顺序已有：

```text
predict
pin
tether
collision
distance/bend iteration
motion
post
```

目标顺序更接近 MC2 Normal：

```text
step particle update
step base pose
tether
distance
angle
triangle bending
collider
distance after collision
motion
post velocity/friction
display
```

第一阶段可继续不做 angle/self collision，但 distance-after-collision 和 post velocity/friction 的位置要先固定。

### P3: TriangleBending fidelity

- 构建 `triangle_pairs` 为 `(v0, v1, edge0, edge1)`。
- 计算 rest dihedral angle。
- 记录 direction sign。
- 实现 DirectionDihedralAngle 修正。
- 暂不做 volume 时也要保留字段。

### P4: Velocity/PostTeam

- 决定是否从 Verlet 切到 MC2 velocity buffer。
- 如果切换：
  - `old_positions` 对齐 MC2 `oldPosArray`。
  - `velocity_positions` 对齐 MC2 `velocityPosArray`。
  - `velocity` 对齐 MC2 `velocityArray`。
  - `real_velocity` 对齐 MC2 `realVelocityArray`。
  - constraints 要按 MC2 规则影响 `velocity_positions`。

这是最影响手感和 C++ ABI 的改动，必须在 C++ 正式化前决定。

### P5: Collision fidelity

- 多 collider 推离平均。
- collision normal 聚合。
- dynamic/static friction。
- edge collider mode 延后。
- self collision 继续只预留。

当前状态：多 collider 推离平均与 collision normal 聚合已完成；friction/edge/self collision 未完成。

## Python 小模块迁移状态

当前注册链为 `OmniNodeRegister.py` 中：

```python
from .Function import ..., physicsMC2
node_cls_physics_mc2 = FunctionNodeCore.loadRegisterFuncNodes(physicsMC2)
```

这意味着 `physicsMC2` 可以从单个 `physicsMC2.py` 迁移为目录包 `Function/physicsMC2/__init__.py`，只要包对象继续导出 `@omni(enable=True)` 的 `meshClothMC2` 函数，`loadRegisterFuncNodes()` 就能按模块对象扫描节点。

当前状态：已经完成机械迁移，`Function/physicsMC2/__init__.py` 继续导出原 `meshClothMC2` 节点函数。

后续拆分规则：

- 不改变节点 `bl_idname`、函数名、socket 顺序、cache schema。
- 外部入口只通过 `physicsMC2/__init__.py` 暴露。
- 碰撞、约束、native 打包可以拆成包内私有模块，但不要抽到 `Physics.py` 或公共碰撞层。

推荐包内边界：

```text
Function/physicsMC2/__init__.py        # 节点入口与公开函数
Function/physicsMC2/common.py          # MC2 常量、参数采样、shape key I/O
Function/physicsMC2/meshcloth.py       # MeshCloth 数据构建和 solve 调度
Function/physicsMC2/collision.py       # MC2 自己的 HoTools 碰撞组适配
Function/physicsMC2/native_bridge.py   # native 数组打包和 fallback
```

本次只做入口文件级机械迁移，尚未拆 `common.py`、`meshcloth.py`、`collision.py`、`native_bridge.py`。

## C++ 端拆分建议

Python 端已经是同名包目录，后续可按需要拆包内私有文件；C++ 端仍建议多拆文件。

推荐 C++ 目录：

```text
_native/include/hotools_mc2.hpp
_native/src/mc2/mc2_math.hpp
_native/src/mc2/mc2_types.hpp
_native/src/mc2/mc2_meshcloth.cpp
_native/src/mc2/mc2_distance.cpp
_native/src/mc2/mc2_tether.cpp
_native/src/mc2/mc2_motion.cpp
_native/src/mc2/mc2_bending.cpp
_native/src/mc2/mc2_collision.cpp
_native/src/mc2/mc2_post.cpp
_native/src/hotools_native.cpp
_native/tests/test_mc2_meshcloth_native.py
```

也可以拆成独立扩展模块：

```text
hotools_native_xpbd
hotools_native_mc2
```

优点：

- MC2 代码体量会明显大于 XPBD，独立模块更容易维护。
- ABI 变化不会影响已经稳定的 XPBD 后端。
- 编译和测试可以分开跑。

缺点：

- Python 侧需要多一个 import fallback。
- 发布包多一个 `.pyd`。

折中方案：

- 第一阶段仍编译到 `hotools_native`，但 C++ 源码按 `src/mc2/` 拆分。
- 如果 MC2 ABI 变化频繁或编译单元过大，再拆成 `hotools_native_mc2`。

## C++ 准入条件

在正式做 `meshClothMC2Cpp` 前，建议满足：

- Python 节点在测试场景中稳定连续播放。
- Python 跳帧、reset、倒放、同帧重复行为明确。
- cache schema 和 native 参数数组固定。
- Python reference smoke 至少覆盖：
  - 单条 cloth strip
  - grid 上边 fixed
  - 无 fixed 整体下落
  - sphere collision
  - capsule collision
  - collision group filter
  - reset/jump frame
  - object transform scale change
- C++ smoke test 只对齐 Python reference，不直接对齐 Unity MC2。

## 后续记录方式

建议后续每次修改 Python fidelity 时，在本文档更新：

```text
日期
改动项
对齐的 MC2 源码文件/函数
新增或变更的 cache 字段
是否影响 C++ ABI
验证场景
```

示例：

```text
2026-06-17
- 补 Tether compression/stretch。
- 对齐 Runtime/Cloth/Constraints/TetherConstraint.cs SolverConstraint。
- 新增 cache param_slots.tether_compression / tether_stretch。
- 影响 C++ ABI：是。
- 验证：strip root fixed，下落后不超过 stretch，不出现根部压缩穿插。
```

## 变更记录

```text
2026-06-17
- 升级 cache schema 到 MC2_SOLVER_VERSION=2。
- 补 Tether compression/stretch，默认 compression=0.4、stretch=0.03、stiffness width=0.3。
- 新增 tether_rest_lengths：root_rest_lengths 保持路径长度/depth 语义，tether_rest_lengths 对齐 MC2 stepBasicPosition 与 root 的直线恢复距离。
- 补 Motion stiffness lerp，当前内部默认 1.0，保留曲线参数槽。
- 补 ColliderCollision 多 collider 平均推离和 collision normal 聚合。
- 补 state_matches() 对 native/C++ 必需数组的完整形状和索引范围校验。
- 新增 collider_arrays_for_native()，仍在 physicsMC2 包内部，不抽公共碰撞文件。
- 新增 param_slots：tether_compression、tether_stretch、motion_stiffness、backstop_radius、collider_friction。
- 影响 C++ ABI：是。C++ 第一版应以 version=2 cache/native arrays 为基准。
- 待验证：strip root fixed、弯曲链 tether 限位、sphere/capsule 多碰撞体夹挤、reset/jump frame、object scale change。

2026-06-17
- 将 `OmniNode/NodeTree/Function/physicsMC2.py` 机械迁移为 `OmniNode/NodeTree/Function/physicsMC2/__init__.py`。
- 修正相对 import 层级：`FunctionNodeCore`/`OmniNodeSocketMapping` 使用 `...`，`_Color` 从父 `Function` 包导入。
- 节点函数、socket、cache schema、物理行为不变。
- 影响 C++ ABI：否。
- 待验证：Blender 内重新加载插件后物理分类仍能注册 `meshClothMC2`。

2026-06-17
- 新增 `MC2_MODULE_SPLIT_PLAN.md`。
- 规划 Python 包内拆分边界：constants/params/math_utils/blender_io/collision/mesh_build/state/constraints/solver/native_bridge/node。
- 规划 C++ MC2 native 文件边界：hotools_mc2_types、mc2_math、mc2_distance、mc2_tether、mc2_motion、mc2_bending、mc2_collision、mc2_post、mc2_bindings。
- 本次只改文档，不改变物理行为。

2026-06-17
- 执行第一批 Python 包内拆分。
- 新增 `constants.py`、`params.py`、`math_utils.py`、`blender_io.py`、`collision.py`。
- `__init__.py` 继续导出原 `meshClothMC2`，并保留 `_MC2Common` / `_MC2MeshCloth` 作为兼容门面。
- 碰撞实现已移入 `collision.py`，但仍只属于 `physicsMC2` 包内部，没有抽公共碰撞文件。
- 物理行为、节点 socket、cache schema 不变。
```
