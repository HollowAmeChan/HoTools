# OmniNode MC2 Cloth Solver Implementation Plan

本文档规划 OmniNode 中 MagicaCloth2 风格解算器的实现路线。目标不是把 Unity 版 MC2 的全局 Manager/Job 系统照搬到 Blender，而是在 OmniNode 现有函数节点、逐帧运行、runtime cache、Python/C++ 双端机制下复刻核心 cloth 行为。

当前用户约束：

- 第一阶段只实现 MeshCloth。
- BoneCloth 后续实现，但 MeshCloth/BoneCloth 的共通数据、约束和求解设施要提前拆出来。
- MeshCloth 的输入就是用户自己准备的低模代理，插件永远不做 MC2 reduction，也不做高低模 mapping。输出永远驱动这个低模代理。
- 碰撞不照搬 MC2 的显式 collider 列表，直接复用 HoTools/OmniNode 已有碰撞组、骨骼碰撞体和物体碰撞体。
- MC2 支持按 depth 曲线采样的参数，第一版先用标量值；参数层必须保留升级为曲线输入/采样表的空间。
- 自碰撞第一版不做，但 cache、参数和 native 接口必须预留扩展槽。
- 仍然遵守“先 Python 行为蓝本，再用同接口实现 C++ 后端”的路线。
- 跳帧和世界坐标系语义要与 SpringBone 蓝本保持一致。

## 源码研究结论

MC2 源码路径：

```text
D:\Unity_Fork\MagicaCloth2
```

重点文件：

```text
Runtime/Cloth/ClothProcess.cs
Runtime/Cloth/ClothProcessGeneration.cs
Runtime/Cloth/ClothParameters.cs
Runtime/Cloth/Constraints/DistanceConstraint.cs
Runtime/Cloth/Constraints/TetherConstraint.cs
Runtime/Cloth/Constraints/MotionConstraint.cs
Runtime/Cloth/Constraints/TriangleBendingConstraint.cs
Runtime/Cloth/Constraints/AngleConstraint.cs
Runtime/Cloth/Constraints/ColliderCollisionConstraint.cs
Runtime/Manager/Simulation/SimulationManager.cs
Runtime/Manager/Simulation/SimulationManagerNormal.cs
Runtime/Manager/Simulation/SimulationManagerSplit.cs
Runtime/Manager/Team/TeamManager.cs
Runtime/VirtualMesh/VirtualMesh.cs
Runtime/VirtualMesh/Function/VirtualMeshProxy.cs
Runtime/VirtualMesh/Function/VirtualMeshMapping.cs
```

MC2 原架构是“全局 Manager + 每个 cloth 一个 ClothProcess + Burst Job 连续数组”。`ClothProcess` 负责构建 proxy/mapping/constraint data，各 Manager 持有全局 chunk 数组。每帧 `ClothManager.ClothUpdate()` 统一调度 `SimulationManager`，再按 Normal/Split 路径运行 Job。

OmniNode 不应复制这套 Manager：

- OmniNode 的默认扩展点是普通函数节点，不是全局 singleton。
- 跨帧状态必须显式走 `_OmniCache`。
- Python 层负责 Blender 对象读取、shape key 写回、cache 生命周期和跳帧保护。
- C++ 层只替换求解热点，不能持有 Blender 指针或跨帧全局状态。

因此 MC2 在 OmniNode 内部应折叠为：

```text
函数节点输入
  -> 校验 Blender mesh / scene / cache
  -> 读取或重建 MC2ProxyData + MC2ConstraintData
  -> 每帧读取碰撞组快照和对象变换
  -> Python solver 原地推进 MC2ParticleState
  -> 写回低模代理 shape key
  -> 输出 next cache
```

## 新文件边界

已新增入口文件：

```text
OmniNode/NodeTree/Function/physicsMC2.py
```

当前文件只放禁用节点桩和共享结构雏形：

- `MC2_CACHE_KIND`
- `MC2_SOLVER_VERSION`
- `_MC2Common`
- `_MC2MeshCloth`
- `meshClothMC2(..., enable=False)`

`OmniNode/NodeTree/OmniNodeRegister.py` 已导入 `physicsMC2`，但由于节点 `enable=False`，当前不会进入用户菜单。等 Python MeshCloth reference 可运行、cache 行为稳定、基本测试通过后再打开。

后续实现时优先保持单文件，直到体量明显影响维护。如果 `physicsMC2.py` 超过约 1200 行，建议拆出非节点 helper：

```text
OmniNode/NodeTree/Function/physicsMC2.py          # 节点接口和 Blender I/O
OmniNode/NodeTree/Function/physicsMC2_core.py     # 纯 Python/NumPy 求解与数据构建
```

这样 `FunctionNodeCore` 只扫描节点文件，核心逻辑可以被 smoke test 直接导入。

## 第一阶段节点接口

目标节点：

```python
meshClothMC2(
    cache_state: _OmniCache,
    proxy_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 4,
    gravity_dir: mathutils.Vector = (0, 0, -1),
    gravity_power: float = 9.8,
    damping: float = 0.04,
    distance_stiffness: float = 1.0,
    bend_stiffness: float = 0.5,
    max_distance: float = 0.0,
    collision_radius: float = 0.0,
    debug_output: bool = False,
) -> tuple[_OmniCache, bpy.types.Object, int, int]
```

实际实现时建议把碰撞半径优先对齐现有 HoTools 网格碰撞属性：

- 输出 shape key 名称：`proxy_obj.hotools_mesh_collision.output_shape_key`，默认 `MC2MeshCloth`。
- per-vertex 碰撞半径：`hotools_mesh_collision.radius * radius_vertex_group_weight`。
- 被碰撞组：`hotools_mesh_collision.collided_by_groups`。
- passive collider 来源：现有骨骼/Object 碰撞体场景快照。

节点上的 `collision_radius` 可以作为后续 override 或无属性时 fallback，但第一版不要同时制造两套互相冲突的碰撞配置。

第一版输出：

- `_OmniCache`: 下一帧状态。
- `proxy_obj`: 低模代理对象本身，方便串接后续节点。
- `vertex_count`: 代理顶点数。
- `constraint_count`: 距离 + 弯曲 + 后续约束数量。

## Cache Schema

MeshCloth cache 必须是普通 dict，且只通过 OmniNode runtime cache 节点跨帧传递。

建议结构：

```python
{
    "kind": "MESH_PHYSICS_MC2",
    "solver_version": 1,
    "frame": int | None,
    "object_name": str,
    "object_ptr": int,
    "mesh_ptr": int,
    "shape_key_name": str,
    "topology_key": tuple,
    "config_key": tuple,
    "vertex_count": int,

    "proxy": {
        "rest_local_positions": float32[n, 3],
        "rest_world_positions": float32[n, 3],
        "triangles": int32[m, 3],
        "edges": int32[e, 2],
        "attributes": uint8[n],
        "depths": float32[n],
        "root_indices": int32[n],
        "parent_indices": int32[n],
        "baseline_start": int32[b],
        "baseline_count": int32[b],
        "baseline_data": int32[k],
        "local_positions": float32[n, 3],
        "local_rotations": float32[n, 4],
    },

    "constraints": {
        "distance_index": uint32[n],
        "distance_data": int32[d],
        "distance_rest": float32[d],
        "distance_type": uint8[d],
        "triangle_pairs": int32[p, 4],
        "triangle_rest": float32[p],
        "triangle_sign": int8[p],
        "angle": None,
        "self_collision": None,
    },

    "particles": {
        "next_positions": float32[n, 3],
        "old_positions": float32[n, 3],
        "base_positions": float32[n, 3],
        "base_rotations": float32[n, 4],
        "velocity_positions": float32[n, 3],
        "display_positions": float32[n, 3],
        "velocity": float32[n, 3],
        "real_velocity": float32[n, 3],
        "friction": float32[n],
        "static_friction": float32[n],
        "collision_normals": float32[n, 3],
    },

    "collision": {
        "local_radii": float32[n],
        "world_radii": float32[n],
        "collided_by_groups": int,
    },

    "extension_slots": {
        "curves": {},
        "bonecloth": None,
        "self_collision": None,
        "native": None,
    },
}
```

`config_key` 要覆盖会影响重建的数据：

- object/mesh pointer
- vertex/edge/triangle count
- edge/triangle topology hash
- pin/fixed vertex group 名称和权重 hash
- collision radius group 名称和权重 hash
- 输出 shape key 名称
- solver schema version

如果 `current_frame != cached_frame + 1`，应恢复 rest 到输出 shape key 并返回 `None` cache，保持现有 XPBD 跳帧保护语义。

### SpringBone 对齐约定

这一点要和现有 SpringBone 蓝本同口径：

- 只接受 `current_frame == cached_frame + 1` 的连续帧推进。
- 跳帧、倒放、同帧重复执行时，不能拿旧速度继续算。
- 失配时先恢复初始/静态姿态，再让 runtime cache 节点清掉旧状态。
- solver 内部状态以 world space 递推，不在 cache 里藏局部空间的半成品速度。
- 只有在节点边界才做 `local -> world -> solve -> local` 的转换。

MeshCloth 里建议把这条语义落实为：

- `rest_local_positions` 只用于重建基准。
- `rest_world_positions`、`next_positions`、`old_positions`、`velocity_positions`、`display_positions` 都按 world space 存。
- object `matrix_world` 只影响边界转换和碰撞半径/约束重采样，不改变缓存里“世界空间递推”的主语义。

## Proxy Data 构建

OmniNode MC2 solver 永远不做 MC2 reduction。输入 mesh 就是 proxy：

```text
proxy_obj.data.vertices -> proxy.local_positions
proxy_obj.data.edges    -> proxy.edges
proxy_obj.data.polygons/loop_triangles -> proxy.triangles
```

拓扑处理：

1. 用 mesh edges 构建无向邻接。
2. 用 loop triangles 构建 triangle list。
3. 用 edge -> adjacent triangles 构建 triangle bending pairs。
4. 用 fixed vertices 作为 root，BFS 得到：
   - `depths`
   - `root_indices`
   - `parent_indices`
   - baseline lists

fixed 顶点来源：

- 优先沿用现有 `hotools_mesh_collision.pin_enabled` 和 `pin_vertex_group`。
- 如果未设置 pin group，允许全部为 move，但文档和 debug 输出应提示“无固定点，cloth 会整体下落”。
- 如果需要 MC2 风格 attribute 绘制工具，后续再单独做，不阻塞第一版。

VertexAttribute 建议先压缩成位标记：

```text
INVALID = 1 << 0
FIXED   = 1 << 1
MOVE    = 1 << 2
MOTION  = 1 << 3
```

第一版只需要 `FIXED/MOVE/MOTION`。`MOTION` 默认等于 move，后续可由 max distance/backstop 权重组控制。

## 参数与曲线扩展

MC2 中大量参数是 `CurveSerializeData`，求解时按 `depth` 调用 `MC2EvaluateCurve()`。第一版先实现标量值，但不要把求解函数写死为单个 float。

建议内部参数表示：

```python
{
    "distance_stiffness": {"mode": "scalar", "value": 1.0, "samples": None},
    "radius": {"mode": "scalar", "value": 0.02, "samples": None},
    "max_distance": {"mode": "scalar", "value": 0.0, "samples": None},
}
```

统一访问函数：

```python
sample_param(param, depths) -> float32[n]
sample_param_at(param, depth) -> float
```

第一版 `mode == "scalar"` 只返回常量。后续加曲线输入时，不改 solver 主流程，只让参数构建层把曲线转成采样表或回调。

预留曲线参数：

- distance stiffness
- particle radius
- max distance
- backstop distance
- angle restoration stiffness
- angle limit
- damping

## MeshCloth 求解流程

第一版采用 MC2 Normal 路径的顺序，不实现 Split/self-collision 调度。

每帧流程：

1. Validate
   - `proxy_obj` 必须是 mesh。
   - 读取或创建输出 shape key。
   - 获取 scene frame/fps。

2. Cache
   - cache 不匹配则重建。
   - `reset=True` 则重建并清空速度。
   - 跳帧/倒放/同帧重复执行则恢复 rest，输出空 cache。

3. Sync Base
   - 第一版 base pose 使用 proxy rest/world positions。
   - 如果后续要接外部动画/数据输入，应在这里更新 `base_positions/base_rotations`，不要绕过 solver。

4. Collision Snapshot
   - 复用现有 HoTools 碰撞组。
   - 收集 scene 中骨骼/Object sphere/capsule collider。
   - 按 `collided_by_groups` 过滤。
   - 排除 owner 自身。

5. Substep Loop
   - `TeamStep` 简化：计算当前 step dt、gravity、damping。
   - `Prediction`: 推进 `next_positions`。
   - `TetherConstraint`
   - `DistanceConstraint`
   - `TriangleBendingConstraint`
   - `ColliderCollisionConstraint`
   - 再跑一次 `DistanceConstraint`，对应 MC2 碰撞后整形。
   - `MotionConstraint`
   - `PostTeam`: 更新 old/velocity/friction。

6. Display
   - 第一版 `display_positions = next_positions`。
   - 后续再补 frame interpolation 和 blend weight。

7. Writeback
   - world positions -> proxy object local -> output shape key。
   - 不写 Basis。
   - 不写高模 mesh。

## 约束实现优先级

### 必须第一批

`DistanceConstraint`

- 这是 MeshCloth 结构保持的核心。
- 不能直接复用现有 XPBD distance projector；MC2 是 per-particle 收集邻接修正，平均后写回。
- 数据要按每个顶点打包为 start/count，保留 vertical/horizontal 类型，horizontal 刚度可先给常量系数。

`TetherConstraint`

- 基于 root particle 限制当前粒子与 root 的伸缩比例。
- root/parent 由 fixed 顶点 BFS 得到。
- 如果没有 fixed/root，跳过。

`MotionConstraint`

- 第一版只做 max distance。
- Backstop 可作为同阶段后半加入。
- 标量 max distance 先全局生效；后续按 depth/曲线采样。

`ColliderCollisionConstraint`

- 使用现有碰撞组 sphere/capsule。
- 第一版只做 point collision。
- Edge collision 与 MC2 collider edge mode 延后。

### 第二批

`TriangleBendingConstraint`

- 需要从 triangle pair 初始化 rest dihedral angle/sign。
- Python 版先实现 DirectionDihedralAngle。
- Volume pair 可先保留字段，不作为第一版 MVP 必须项。

`AngleConstraint`

- 依赖 baseline local position/rotation、parent/root 数据。
- MeshCloth/BoneCloth 共用价值高，但复杂度也高。
- 建议等 distance/tether/motion/collision 稳定后实现。

`Inertia/Teleport/Scale`

- 第一版保持现有 XPBD 风格跳帧保护。
- MC2 的 center inertia、negative scale teleport、blend/display interpolation 后续补。

### 暂不做但预留

`SelfCollisionConstraint`

- 需要 primitive grid、contact list、intersect list 和多阶段迭代。
- 第一版 `self_collision=None`。
- C++ 接口预留 self-collision pointer/array 槽，但 Python 不传实际数据。

`Split Simulation`

- Unity MC2 为大网格或 self collision 拆 Job。
- OmniNode 由用户提供低模代理，solver 不通过 reduction 管理复杂度。
- 如后续需要 split，它也只是求解执行策略或 self-collision 支撑，不是减面/代理生成入口。
- C++ 后端可直接并行化局部循环，不必复制 Unity Job 阶段。

## 碰撞接入

MC2 碰撞实现应保持在 `physicsMC2.py` 自己的文件边界内。现有 `Physics.py` 里的 SpringBone/XPBD solver 是蓝本，保持单文件、少依赖、可对照，不为了 MC2 抽公共碰撞模块。

MC2 可以参考并复制必要逻辑：

- `build_collision_snapshot_from_scene(scene, include_bone_colliders=True, include_object_colliders=True, include_mesh_colliders=False)`
- sphere/capsule 数据结构
- group mask 过滤
- matrix scale radius

但不要依赖 `_BonePhysics` 私有类，也不要让 `Physics.py` 反向依赖 MC2。`physicsMC2.py` 内部应自带：

- `collision_group_bit`
- `clamp_group_mask`
- `matrix_scale_radius`
- `build_collision_snapshot_from_scene`
- `collider_arrays_for_native`

这样 XPBD、SpringBone、MC2 三套物理保持隔离：旧 solver 继续作为可对照蓝本，MC2 自己承担碰撞接入的演进成本。

## BoneCloth 预留

BoneCloth 与 MeshCloth 应共享这些设施：

- 参数系统
- particle state
- proxy topology
- distance/tether/motion/triangle/angle/collision constraints
- debug timing
- native buffer contract

只分离 I/O：

```text
MeshClothInput
  Blender mesh -> proxy local/world positions
  output -> shape key

BoneClothInput
  Armature bone chains -> proxy particles/lines
  output -> PoseBone matrix_basis
```

BoneCloth 需要额外处理：

- bone chain topology
- connected bone head/tail
- parent-space matrix conversion
- batch pose writeback
- root/fixed bone semantics

这些不应进入 MeshCloth solver 核心。MeshCloth solver 只看数组。

## C++ 后端计划

Python reference 稳定后新增 parallel 节点：

```text
网格布料-MC2
网格布料-MC2-CPP
```

两者必须保持相同：

- 输入 socket
- 输出 socket
- cache schema
- 跳帧/重置语义
- shape key 写回
- 碰撞组过滤
- 错误边界

C++ 只接管 solve 热路径。Python 仍负责：

- Blender object/mesh/shape key 校验
- cache 重建和失效
- 读取 vertex group/pin/collision profile
- 场景碰撞体快照
- ndarray 准备
- shape key 写回

建议 native 接口：

```cpp
solve_mc2_meshcloth(
    next_positions,
    old_positions,
    base_positions,
    base_rotations,
    velocity_positions,
    velocity,
    real_velocity,
    friction,
    static_friction,
    collision_normals,
    attributes,
    depths,
    root_indices,
    parent_indices,
    distance_index,
    distance_data,
    distance_rest,
    distance_type,
    triangle_pairs,
    triangle_rest,
    triangle_sign,
    collision_radii,
    collided_by_groups,
    collider_types,
    collider_groups,
    collider_centers,
    collider_segment_a,
    collider_segment_b,
    collider_radii,
    params,
    dt,
    substeps,
    iterations
)
```

所有数组要求：

- `float32` / `int32` / `uint8`，C contiguous。
- C++ 原地更新 particle arrays。
- C++ 不访问 `bpy`。
- C++ 不保存全局状态。
- C++ smoke test 必须用 Python reference 对齐。

目录沿用现有 native 工程：

```text
_native/include/hotools_mc2.hpp
_native/src/mc2_meshcloth.cpp
_native/src/hotools_native.cpp
_native/tests/test_mc2_meshcloth_native.py
```

## Debug Timing

参考现有 XPBD 节点的 stage：

```text
validate
cache
restore
rebuild
transform
collision_snapshot
solve_setup
predict
tether
distance
triangle_bending
angle
collider
motion
post
write
native
total
```

debug 输出每约 1 秒聚合一次，避免逐帧刷屏。

## 验证计划

Python reference smoke:

1. 单条 cloth strip：一端 fixed，重力下垂，距离保持。
2. 方形 grid：fixed 上边，distance + bending 后不爆炸。
3. 无 fixed：整体下落，debug 提示无固定点。
4. 碰撞组过滤：只与目标 group sphere/capsule 相互作用。
5. 跳帧保护：从 frame 1 跳到 frame 10，输出 rest，cache 清空。
6. topology change：增加/删除边或顶点后重建 cache。
7. shape key 写回：Basis 不变，目标 key 更新。
8. scalar parameter sampler：与未来 curve sampler 走同一代码路径。

C++ parity:

1. 距离约束输出与 Python reference `assert_allclose`。
2. tether/motion/collider 单项测试。
3. 随机小网格稳定性测试。
4. 错误输入：非 contiguous、类型错误、索引越界应抛明确异常。

Blender 手工验证：

1. 低模裙摆代理。
2. 低模披风代理。
3. 被动骨骼 collider。
4. 被动物体 collider。
5. 播放、暂停、倒放、跳帧、重置。

## 分期交付

### Phase 0: 基础落点

- 新增 `physicsMC2.py`。
- 新增本文档。
- 注册器导入模块，但节点保持 `enable=False`。

### Phase 1: MeshCloth Python MVP

- Mesh object 校验。
- shape key 创建/写回。
- topology/config hash。
- cache rebuild/reset/jump-frame 语义。
- fixed group、depth/root/parent 构建。
- distance/tether/motion max-distance。
- 现有碰撞组 point collision。
- debug timing。

完成后把 `meshClothMC2(enable=True)`。

### Phase 2: MeshCloth Fidelity

- triangle bending DirectionDihedralAngle。
- backstop。
- angle restoration/limit。
- scalar 参数整理成 curve-ready sampler。
- 更接近 MC2 的 post velocity/friction 处理。

### Phase 3: C++ MeshCloth

- native buffer interface。
- Python/C++ parity tests。
- `meshClothMC2Cpp` parallel node。

### Phase 4: BoneCloth

- BoneCloth input/output adapter。
- 复用 MC2 core solver。
- PoseBone batch writeback。
- BoneCloth Python reference。
- BoneCloth C++ hot path if needed。

### Phase 5: Reserved Features

- self collision。
- edge collider mode。
- curve socket/curve asset input。
- optional high-res mapping node，独立于 MeshCloth solver。
- 不新增 reduction phase；代理创建、减面、重拓扑永远交给用户或独立工具，不属于 MC2 solver。

## 关键取舍

- 永远不做 reduction 是架构边界，不是 MVP 延后项。MC2 的 reduction 是 Unity runtime/editor 构建代理网格的设施；OmniNode 里用户明确提供低模代理，解算器只负责驱动它。
- 不做高低模 mapping 也是 solver 边界。映射会引入新的数据生命周期和写回目标；如未来需要，只能作为独立节点/工具，不进入 MeshCloth solver。
- 不复制 MC2 collider list。HoTools 已经有碰撞组，继续用同一套场景属性更利于用户维护。
- 曲线先不做，但参数访问层必须 curve-ready。否则后续会大改 solver 签名。
- 自碰撞先不做，但 cache/native 参数预留槽。否则后续 C++ ABI 会被迫破坏。
- BoneCloth 不能等 MeshCloth 完全写死后再考虑。现在就按数组 solver + I/O adapter 分层，后续 BoneCloth 才不会重写一套。
