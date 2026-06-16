# OmniNode MC2 模块拆分规划

本文档规划 `Function/physicsMC2` 后续如何从当前入口文件拆成多个 Python 私有模块，并同步规划 C++ native 文件边界。目标是让 Python 端继续作为行为蓝本，让 C++ 端按同一份数组协议实现加速，而不是让两套实现各自演化。

## 结论

推荐先按“数据/参数/I/O/约束/碰撞/native 打包/节点入口”拆 Python 包，再按同样的 solver 阶段拆 C++。不要先按 MC2 Unity 源码目录原样复制，因为 OmniNode 没有 MC2 的全局 Manager、TeamData、Burst Job chunk 系统。

拆分优先级：

1. 先拆纯工具与数据结构：`constants.py`、`params.py`、`math_utils.py`。已完成。
2. 再拆 Blender I/O：`blender_io.py`、`mesh_build.py`。已完成。
3. 再拆求解阶段：`constraints.py`、`collision.py`、`solver.py`。已完成。
4. 节点入口保持在 `__init__.py`；`native_bridge.py` 已用于 ABI view 打包，C++ 调用后续启用。
5. 每一步拆完都必须保证 `physicsMC2.__init__.py` 仍导出同一个 `meshClothMC2` 节点函数。当前已满足。

## 不变边界

- MeshCloth 输入永远是用户准备好的低模代理；不做 reduction、减面、重拓扑、代理生成、高低模 mapping。
- 旧 `Physics.py` 中 SpringBone/XPBD 保持蓝本隔离，不为了 MC2 抽公共碰撞文件。
- MC2 碰撞适配留在 `physicsMC2` 包内，直接读取 HoTools 碰撞组。
- 自碰撞、曲线参数、BoneCloth 可以预留接口，但第一阶段不强行实现。
- C++ 端只接收 numpy/pybuffer 数组，不接收 Blender 对象或 Python dict。

## Python 推荐结构

```text
OmniNode/NodeTree/Function/physicsMC2/
  __init__.py          # OmniNode 节点入口，定义 meshClothMC2 与节点生命周期
  constants.py         # cache kind/version、attr flag、MC2 系统常量、曲线参数名
  params.py            # scalar/curve 参数槽、depth 采样、默认参数集合
  math_utils.py        # numpy/mathutils 转换、safe normal、segment closest point、hash
  blender_io.py        # scene dt、shape key I/O、object matrix key、local/world 转换
  collision.py         # HoTools object/bone collider 快照、point collision、native collider arrays
  mesh_build.py        # mesh connectivity、attributes、depth/root、constraint array 构建
  state.py             # cache state build/sync/state_matches/schema guard
  constraints.py       # distance/tether/motion/bend distance approximation
  solver.py            # MeshCloth solve 顺序调度、frame/substep/iteration 生命周期
  native_bridge.py     # native import、array ABI 打包、Python fallback 分派
```

### `__init__.py`

职责：

- 定义 `meshClothMC2` 与 `_run_mesh_cloth_mc2_node()`。
- 管理 cache、跳帧、reset、碰撞快照收集和 shape key 写回。
- 不放约束算法、state 构建或 C++ ABI 打包。
- 保持 `FunctionNodeCore.loadRegisterFuncNodes(physicsMC2)` 可扫描到节点函数。

注意：`physicsMC2` 本身就是 OmniNode 的函数模块，额外拆 `node.py` 没有收益。入口留在 `__init__.py`，其余实现拆到包内私有模块。

### `constants.py`

放置：

- `MC2_CACHE_KIND`
- `MC2_SOLVER_VERSION`
- `MC2_ATTR_INVALID/FIXED/MOVE/MOTION`
- `MC2_CURVE_READY_PARAMETERS`
- MC2 系统常量：friction mass、tether compression/stretch、stiffness width、motion velocity attenuation、collider friction ratio 等。

对应 C++：

```text
_native/include/hotools_mc2_types.hpp
_native/src/mc2/mc2_constants.hpp
```

### `params.py`

放置：

- `scalar_param()`
- `sample_param()`
- 后续曲线 table 构建与校验。
- 默认参数槽填充函数，例如 `default_param_slots()`。

拆分理由：

- MC2 大量参数支持 depth curve。即使当前只用标量，也应让所有约束只依赖“采样后的数组或 ParamSlot”，不要直接读取节点 socket。

对应 C++：

```text
_native/include/hotools_mc2_types.hpp    # Mc2ParamView / curve table view
_native/src/mc2/mc2_params.cpp           # curve sampling helper
```

### `math_utils.py`

放置：

- `matrix_to_numpy()`
- `transform_positions()`
- `vector_to_numpy()`
- `closest_point_on_segment_np()`
- `safe_normal_np()`
- `array_hash()`
- clamp helpers。

原则：

- 这里可以依赖 `numpy` 和 `mathutils`，但不要依赖 `bpy` 场景对象。
- C++ 对应的数学函数应保持同名或近似同名，方便逐行对照。

对应 C++：

```text
_native/src/mc2/mc2_math.hpp
```

### `blender_io.py`

放置：

- `scene_delta_time()`
- `substep_damping()`
- mesh object 校验。
- shape key 创建、读取、写回。
- rest pose 读取。
- object matrix key。
- local/world 转换。

原则：

- 这是 Python 独有层，C++ 不应出现任何 Blender 指针或 shape key 逻辑。
- 跳帧、reset、写回 shape key 的生命周期仍由 `__init__.py` 入口和 `solver.py` 组合管理。

对应 C++：

无直接对应。C++ 只接收 Python 已准备好的数组。

### `collision.py`

放置：

- HoTools object/bone sphere/capsule 碰撞快照读取。
- collision group mask/bit。
- `project_vertex_collision()`。
- `project_collisions()`。
- `collider_arrays_for_native()`。

原则：

- 不抽到公共碰撞模块。
- 不改 `Physics.py`。
- C++ 端只复刻 `project_collisions()` 和数组 ABI，不复刻 Blender collision props 读取。

对应 C++：

```text
_native/src/mc2/mc2_collision.cpp
```

### `mesh_build.py`

放置：

- `mesh_collision_props()`
- `vertex_group_weights()`
- `mesh_pin_config()`
- `build_attributes()`
- `build_collision_profile()`
- `mesh_connectivity_arrays()`
- `mesh_signature_key()`
- `config_key()`
- `build_edge_constraints()`
- `build_bend_constraints()` 当前仍是 bend distance approximation。
- `build_neighbor_table()`
- `build_depth_and_roots()`
- `build_tether_rest_lengths()`

原则：

- 只读取用户输入 mesh，不生成、修改或减面 mesh。
- 可生成 solver 内部约束数组，但必须明确这些不是代理生成或重拓扑。

对应 C++：

第一阶段无直接对应。因为 MeshCloth 构建仍由 Python 做。C++ 若以后需要加速构建，可单独进入：

```text
_native/src/mc2/mc2_mesh_build.cpp
```

但不作为第一版 native 后端目标。

### `state.py`

放置：

- `build_state()`
- `sync_state_to_object_transform()`
- `state_matches()`
- cache schema version guard。
- cache 字段默认值和扩展槽。

原则：

- 这里决定 Python/C++ ABI 的真实形状。
- 每次新增 C++ 必需数组都要同步 `state_matches()` 和文档。

对应 C++：

```text
_native/include/hotools_mc2.hpp          # Mc2MeshClothView
```

### `constraints.py`

放置：

- `project_neighbor_constraints()`。
- `project_tether()`。
- `project_motion_constraint()`。
- 当前 `bend distance approximation` 函数。
- 后续 `project_dihedral_bending()`。
- 后续 angle restoration / angle limit。

原则：

- 这里不读取 Blender 对象。
- 输入必须是 numpy 数组和采样后的参数。
- 不做求解顺序调度，只实现单个约束阶段。

对应 C++：

```text
_native/src/mc2/mc2_distance.cpp
_native/src/mc2/mc2_tether.cpp
_native/src/mc2/mc2_motion.cpp
_native/src/mc2/mc2_bending.cpp
_native/src/mc2/mc2_angle.cpp
```

### `solver.py`

放置：

- `solve_meshcloth_python()`。
- 子步/迭代调度。
- predict/pin/tether/distance/bend/collision/motion/post 顺序。
- `velocity/real_velocity/velocity_positions` 的当前 Python 语义。

原则：

- 不创建 shape key，不读取 Blender props。
- 可接收 `colliders` 快照，但不负责从 scene 中收集。
- 这里是未来 C++ parity 的直接参考。

对应 C++：

```text
_native/src/mc2/mc2_meshcloth_solver.cpp
_native/src/mc2/mc2_post.cpp
```

### `native_bridge.py`

放置：

- `import hotools_native` fallback。
- 判断 native 可用性。
- 把 Python state/param/collider arrays 打成 native function 参数。
- 调用 C++ 后端并把结果写回 state。
- native 与 Python fallback 的一致性检查。

原则：

- 不把 C++ ABI 散落在 `__init__.py` 或 `solver.py`。
- ABI 变化只改这里、`state.py` 和 C++ binding。

对应 C++：

```text
_native/src/hotools_native.cpp
```

### 节点入口

节点入口保留在 `__init__.py`：

- `_run_mesh_cloth_mc2_node()`。
- `@omni(...) def meshClothMC2(...)`。
- Blender scene/cache/shape key 生命周期编排。

原则：

- 只做节点入口与高层流程。
- 不内联约束算法。

对应 C++：

无直接对应。C++ 不知道节点存在。

## MC2 物理算法阶段映射

当前 Python 求解顺序：

```text
validate/cache
restore/rebuild/sync transform
collect colliders
solve:
  setup dt/substeps/damping/gravity
  for each substep:
    predict
    pin fixed
    tether
    collision
    for each iteration:
      distance
      bend distance approximation
      pin fixed
      collision
    motion
  post velocity/display
write shape key
```

目标 MC2 Normal 近似顺序：

```text
step particle update
step base pose
tether
distance
angle restoration / angle limit
triangle bending
collider
distance after collision
motion
post velocity/friction
display
```

模块对应：

```text
predict/pin/post      -> solver.py / mc2_meshcloth_solver.cpp / mc2_post.cpp
tether                -> constraints.py / mc2_tether.cpp
distance              -> constraints.py / mc2_distance.cpp
bend approximation    -> constraints.py / mc2_bending.cpp
dihedral bending      -> constraints.py / mc2_bending.cpp
angle constraints     -> constraints.py / mc2_angle.cpp
collider point        -> collision.py / mc2_collision.cpp
motion/backstop       -> constraints.py / mc2_motion.cpp
velocity/friction     -> solver.py + collision.py / mc2_post.cpp + mc2_collision.cpp
```

## C++ 推荐结构

第一版仍可编译进现有 `hotools_native`，但源码必须拆到 `src/mc2/`，避免 `hotools_native.cpp` 继续膨胀。

推荐目录：

```text
_native/include/hotools_mc2.hpp
_native/include/hotools_mc2_types.hpp
_native/src/mc2/mc2_math.hpp
_native/src/mc2/mc2_constants.hpp
_native/src/mc2/mc2_params.cpp
_native/src/mc2/mc2_meshcloth_solver.cpp
_native/src/mc2/mc2_distance.cpp
_native/src/mc2/mc2_tether.cpp
_native/src/mc2/mc2_motion.cpp
_native/src/mc2/mc2_bending.cpp
_native/src/mc2/mc2_angle.cpp
_native/src/mc2/mc2_collision.cpp
_native/src/mc2/mc2_post.cpp
_native/src/mc2/mc2_bindings.cpp
_native/src/hotools_native.cpp
_native/tests/test_mc2_meshcloth_native.py
```

### `hotools_mc2_types.hpp`

定义纯 C++ POD view：

```text
Mc2MeshClothView
Mc2ParamsView
Mc2CollisionView
Mc2ConstraintView
```

要求：

- 所有数组长度显式传入。
- 不持有 Python object。
- 不分配跨帧状态。
- 不存 Blender 指针。

### `hotools_mc2.hpp`

公开 native 入口：

```text
void solve_meshcloth_mc2(Mc2MeshClothView& view);
```

未来可以增加：

```text
void solve_bonecloth_mc2(Mc2BoneClothView& view);
```

### `mc2_bindings.cpp`

职责：

- 从 Python buffer 解析 `numpy` 数组。
- 校验 dtype、shape、contiguous、索引范围。
- 构造 `Mc2MeshClothView`。
- 注册 `solve_meshcloth_mc2` 到 `hotools_native`。

建议把 XPBD 当前 `hotools_native.cpp` 中的 buffer helper 抽成：

```text
_native/src/python_buffer_utils.hpp
```

这属于 native 内部工具，不影响 Python solver 边界。

### `hotools_native.cpp`

长期职责应缩小为：

- Python module init。
- method table 汇总。
- 调用 `register_xpbd_methods()` / `register_mc2_methods()` 或 include method arrays。

不要继续把 MC2 binding 全塞进 `hotools_native.cpp`。

## Python/C++ ABI 分层

Python 负责：

- Blender scene/object/shape key。
- Mesh 顶点、边、triangle 读取。
- 固定点、depth、root、tether rest length 构建。
- collision group 快照。
- cache 生命周期、跳帧、reset。
- shape key 写回。

C++ 负责：

- 单帧输入数组上原地求解。
- predict/pin/constraints/collision/motion/post。
- 不创建和缓存 Blender 数据。

第一版 C++ 函数参数建议按结构而不是长参数列表规划。Python C API 可以仍然接收长 tuple，但 binding 内部必须立即组装成 `Mc2MeshClothView`。

核心数组：

```text
positions                  float32[n, 3] in/out
old_positions              float32[n, 3] in/out
base_positions             float32[n, 3]
rest_world_positions       float32[n, 3]
attributes                 uint8[n]
depths                     float32[n]
inv_masses                 float32[n]
root_indices               int32[n]
tether_rest_lengths        float32[n]
distance_start/count/data  int32[n], int32[n], int32[d]
distance_rest              float32[d]
bend_start/count/data      int32[n], int32[n], int32[b]
bend_neighbor_rest         float32[b]
collision_radii            float32[n]
collider arrays            int32/float32[c]
param arrays/scalars       scalar or sampled float32[n]
```

## 拆分迁移顺序

### Step 1: 纯搬运，不改行为

- 从 `__init__.py` 拆出 `constants.py`、`params.py`、`math_utils.py`。
- `__init__.py` 仍 re-export `meshClothMC2`。
- 跑 `py_compile`。

状态：已完成。`__init__.py` 当前保留 OmniNode 节点入口，常量、参数和数学工具已进入独立模块。

### Step 2: 拆 Blender I/O 和碰撞快照

- 拆 `blender_io.py`。
- 拆 `collision.py` 中的 scene snapshot 和 native collider arrays。
- 确认不引入对 `Physics.py` 的依赖。

状态：已完成 `blender_io.py`、`collision.py` 和 `mesh_build.py`。碰撞仍只在 `physicsMC2` 包内部，没有抽公共碰撞文件。

### Step 3: 拆 mesh/state 构建

- 拆 `mesh_build.py`。
- 拆 `state.py`。
- 这一步最影响 cache schema，必须配合 `state_matches()` 测试。

状态：已完成。`mesh_build.py` 负责只读 mesh 连接、pin/碰撞半径配置、edge/bend/tether 预计算；`state.py` 负责 cache state、transform 同步和 schema guard。

风险中等，重点测 reset、跳帧、object scale change。

### Step 4: 拆约束与 solver

- 拆 `constraints.py`。
- 拆 `solver.py`。
- 这一步不能改求解顺序。

状态：已完成。`constraints.py` 承载纯数组约束；`solver.py` 承载当前 Python 求解顺序和 Blender 帧率时间语义。求解顺序未改变。

风险中高，重点测连续播放手感。

### Step 5: native bridge 预留

- 增加 `native_bridge.py`。
- 暂时只打包 arrays，不调用 C++。
- 后续 C++ parity 完成后再启用。

状态：已完成 ABI view 打包。当前只记录 native 可用性、state arrays、param slots 和 collider arrays，不调用 C++。

风险低到中。

### Step 6: C++ 文件骨架

- 增加 `hotools_mc2.hpp/types.hpp`。
- 增加 `src/mc2/*.cpp` 空实现或 parity 小实现。
- 修改 CMakeLists 把 MC2 源文件加入 `hotools_native`。
- 先跑 native smoke test，不接正式节点。

风险中等。

## 每步验收标准

每一步拆分后至少检查：

```text
python -m py_compile OmniNode/NodeTree/Function/physicsMC2/*.py
git diff --check
Blender 内节点菜单仍出现 meshClothMC2
旧测试场景可连续播放
reset/jump frame 行为不变
sphere/capsule collision 行为不变
```

拆到 C++ 时额外检查：

```text
dotnet/cmake build native
test_mc2_meshcloth_native.py
Python solver vs C++ solver 同输入数组差异
```

## 建议下一步

Python 包内主要拆分已完成，下一步建议按顺序推进：

- 在 Blender 测试场景里验证 `meshClothMC2` 注册、连续播放、reset、jump frame、object scale、sphere/capsule collision。
- `native_bridge.py` 已能打包当前 state/collider/param ABI view。下一步是按该视图写 C++ binding smoke，不启用正式节点后端。
- 开始 C++ 文件骨架：`hotools_mc2_types.hpp`、`mc2_distance.cpp`、`mc2_tether.cpp`、`mc2_motion.cpp`、`mc2_collision.cpp`、`mc2_meshcloth_solver.cpp`。
- C++ 第一版只对齐当前 Python reference，不直接补完整 Unity MC2。
