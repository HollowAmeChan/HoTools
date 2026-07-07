# VRM SpringBone 物理流程预演

本文用当前已经稳定运行的 VRM SpringBone solver 预演 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 中定义的物理流程契约。目标不是立刻改代码，而是检查新流程拆分是否能解释现有行为、暴露隐性性能问题，并为后续 world-aware 迁移提供样板。

参考源码：

```text
OmniNode/NodeTree/Function/Physics.py
  _BonePhysics
  _SpringBoneVRMCppBackend
  _SpringBoneVRM
  springBoneVRM
  springBoneVRM_CPP

_native/include/hotools_spring_bone_vrm.hpp
_native/src/spring_bone_vrm.cpp
_native/src/spring_bone_vrm_bindings.cpp
```

## 迁移结论：直接重写，不做旧路径兼容

VRM SpringBone 是第一条要落地的非 Jolt solver。迁移策略不是把旧节点搬进 `PhysicsWorldCache`，而是在 `physicsWorld/spring_vrm/` 下直接重写新的 world-aware 代码块。

旧实现只保留三个用途：

1. 审查真实职责和隐藏副作用。
2. 对照数值行为，尤其是 tail Verlet、长度约束、碰撞投影和 parent/connected bone 处理。
3. 临时作为手工比对基准，不能作为新 contract 的兼容目标。

已经建立的新入口：

```text
OmniNode/NodeTree/Function/physicsWorld/spring_vrm/
  specs.py        -> SpringVRMChainSpec / SpringVRMSolverSpec
  results.py      -> spring_vrm_pose / spring_vrm_stats 纯快照 result stream
  solver.py       -> register_spring_vrm_specs，注册到 world.solver_slots
  declaration.py  -> solver declaration + legacy discard audit
```

严格边界：

- 新 solver slot 使用 `spring_vrm:{armature_ptr}:{armature_data_ptr}:{spec_hash}`，不再用 `armature.name_full` 做 cache key。
- solver step 只能发布 `world.result_streams["spring_vrm_pose"]` 和 stats，不能直接写 `PoseBone.matrix_basis`。
- `armature.update_tag()` 归属于统一 writeback apply，不属于 solver。
- 碰撞输入来自 `PhysicsWorldCache.collider_snapshot`，不保留 scene-wide collider fallback。
- 新迁移只保留 C++ / native 计算路径，不再维护 `solve_py` 运行时 backend，也不再暴露 Python / CPP 两套节点。
- Python 层只做 spec 构建、slot 生命周期、buffer 打包、native 调用、result stream 和 writeback plan。
- old node socket/cache/payload 不需要兼容；保留的旧入口必须标记为未迁移模块。

### C++ 单实现迁移原则

旧 SpringBone 有 Python 和 C++ 两条路径，这在历史阶段便于对照，但现在已经成为维护负担：节点数量翻倍、实时更新频率不一致、debug 输出分叉、修 bug 需要双写。新物理世界路径不再保留这种结构。

新 SpringBone 目标结构：

```text
SpringVRMSolverSpec
  -> Python 打包 static/dynamic/collider buffers
  -> C++ native context
  -> C++ step_spring_vrm
  -> Python readback result buffers
  -> world.result_streams["spring_vrm_pose"]
  -> 统一 PoseBone writeback
```

允许存在的 Python 代码：

- 规格构建、骨架/骨骼引用校验、slot id / dirty key。
- numpy buffer 创建和形状校验。
- native context 生命周期管理。
- result stream 发布和 writeback plan 构建。
- 测试用 reference case。

不再允许的 Python 代码：

- 第二套运行时 Verlet / 碰撞 / 约束 solver。
- `springBoneVRM` 与 `springBoneVRM_CPP` 这种按 backend 分裂的公开节点。
- solver 内直接写 PoseBone 或直接扫 scene 的 fallback。

### 可抽到 physicsWorld/utils 的内容

SpringBone 重写时，下列旧 helper 不应继续散落在 `_BonePhysics` / `_SpringBoneVRM` 里：

- `matrix_basis_from_pose_matrix` 一类 PoseBone 写回矩阵换算。
- `collision_group_bit` / `clamp_group_mask` 等碰撞组工具。
- matrix16、vector3、quaternion 的 numpy 打包和 shape 校验。
- obj/data pointer、slot id、spec hash 的生成规则。
- collider snapshot 到 native collider arrays 的通用打包。

这些内容应进入 `physicsWorld/utils/`，但 solver 私有算法状态、native context handle、dirty policy 不进入 utils。

### 丢弃前审查清单

| 旧代码位置 | 处理 | 原因 |
|---|---|---|
| `_run_spring_bone_vrm_node` | 丢弃 | 旧节点把多骨架分发、per-armature cache、solver 执行和 cache intent 合在一起。 |
| `_SpringBoneVRM.prepare` | 重写 | 混合校验、旧 cache match、跳帧判断、scene collider scan 和 initial target。 |
| `_SpringBoneVRM.write_pose` | 丢弃 | 直接写 `PoseBone.matrix_basis`，不符合统一 writeback。 |
| `_SpringBoneVRM.run` 末尾 `armature.update_tag()` | 丢弃 | depsgraph invalidation 必须由 writeback 阶段统一处理。 |
| `_SpringBoneVRM.collision_snapshot*` / `_collision_sources` | 丢弃 | scene-wide 扫描应收敛到 world scope/collider snapshot。 |
| `build_cpp_chain_runtime` / `refresh_cpp_chain_runtime` / `solve_cpp` Python 包装 | 重写 | 可作为数组映射参考，但旧对象引用和 dict state 不能进入新 slot。 |
| `_native/src/spring_bone_vrm.cpp` | 保留为计算核参考 | C++ 层只吃连续数组并输出 tail/matrix/quaternion，没有 Blender 对象写回。 |

## 当前实现摘要

当前 SpringBone 有两条公开节点：

```text
springBoneVRM      Python backend
springBoneVRM_CPP  C++ backend
```

两个节点暴露相同输入输出和 cache 语义：

```text
输入:
  缓存
  VRM骨链属性
  场景
  启用
  重置
  子步数
  调试输出

输出:
  缓存
  骨骼
  骨架列表
  链数量
  碰撞体数量
```

当前节点内部流程：

```text
_run_spring_bone_vrm_node
  -> 展平 VRM 链设置
  -> 按 armature 分组
  -> 对每个 armature 调用 _SpringBoneVRM.run
     -> prepare
        -> validate
        -> cache match / rebuild
        -> collision snapshot
        -> initial targets
     -> solve_py 或 solve_cpp
     -> write_pose
     -> armature.update_tag
     -> return cache intent
  -> 合并多骨架 cache
```

这个结构已经是一个“半拆分”的高封装 solver：`prepare`、`solve`、`write_pose` 已经独立，但对节点图来说仍然是一个黑箱，内部完成碰撞扫描、cache 状态、native 打包、求解、写 PoseBone 和输出 cache intent。

## 当前数据流

### ChainSetting

`springBoneVRMChainSetting` 从骨骼输入构造链设置：

```text
armature
root_bone
bones
enabled
stiffness_force
drag_force
gravity_dir
gravity_power
```

职责判断：

- 它是 Entity / Spec Build 的前身。
- 它不写姿态，不推进时间，不维护跨帧状态。
- 它目前输出 dict，而不是正式 `SpringChainSpec` 类型。

### Runtime Cache

单骨架 cache 结构大致为：

```text
OmniCacheOwnerDict
  frame
  armature_name
  topology_key
  chains
    root_name
      bones
      joints
        bone_name
          current_tail
          prev_tail
          init_axis
          init_axis_local
          init_axis_parent
          length
          init_rotation
          init_scale
          init_matrix_basis
          pinned
  write_records
  write_runtime
  cpp_runtime
```

多骨架节点外层 cache：

```text
OmniCacheOwnerDict
  armatures
    armature_name_full -> per_arm_cache
```

职责判断：

- `chains/joints` 是 solver private state。
- `write_records/write_runtime` 更接近 writeback plan，不应长期混在 solver state 中。
- `cpp_runtime` 是 native-adjacent context，但目前仍由 Python dict + numpy arrays 表达。
- 多骨架 cache 目前用 `armature.name_full` 分区，但这不是稳定 slot id。world-aware 路径应使用 armature pointer + data pointer，name 只作为 debug 显示名。

### C++ Kernel 输入

当前 native binding 一次调用接收 35 个参数：

```text
current_tails
prev_tails
target_matrices
target_quaternions
current_heads
current_pose_matrices
current_pose_quaternions
parent_pose_quaternions
current_pose_tails
lengths
init_axis_local
init_axis_parent
init_rotations
init_scales
parent_indices
pinned
use_connect
root_quaternion
root_tail_world
armature_world
armature_world_inv
gravity_dir
hit_radii
collided_by_groups
collider_types
collider_groups
collider_centers
collider_segment_a
collider_segment_b
collider_radii
dt
substeps
stiffness_force
drag_force
gravity_power
```

职责判断：

- C++ kernel 是纯数组计算，不知道 `bpy`。
- 它不持有 native context。
- 每次调用都要经过 Python buffer 获取、shape/dtype 校验和 `SpringBoneVrmChainView` 组装。
- 性能收益取决于 `native_core` 是否显著大于 Python 侧 `pack/unpack/collision_setup/write`。

## 映射到新物理流程

### Physics World Begin

当前 SpringBone 自己做了：

```text
scene frame
dt
跳帧/倒放检测
collision snapshot
```

新流程中应迁移到 world 或 frame prepare：

```text
frame/dt/restart_required -> Physics World Begin
collider snapshot -> Physics World Begin / Physics Frame Prepare
```

保留在 SpringBone 的内容：

```text
SpringBone 自己的 topology/config 判断
SpringBone 自己的 slot state 校验
```

### Entity / Spec Build

当前来源：

```text
springBoneVRMChainSetting
_BonePhysics.bone_chains_from_bone_values
_SpringBoneVRM.settings_for_armature
```

新流程建议生成：

```text
SpringChainSpec
  armature              ← bpy.types.Object 引用
  root_bone             ← str，骨骼名
  bones                 ← list[str]
  enabled               ← bool
  stiffness_force       ← float
  drag_force            ← float
  gravity_dir           ← Vector
  gravity_power         ← float
  source_id             ← 调试用来源标识，例如 "vrm_chain_setting:Hair_01"
  stable_id             ← 跨帧稳定 id（见下方规则）
```

**stable_id 构造规则：**

```python
stable_id = (
    f"spring_vrm"
    f":{int(armature.as_pointer())}"
    f":{int(armature.data.as_pointer())}"   # 必须包含，防止 Armature 数据块被替换后命中旧 slot
    f":{root_bone}"
)
```

不能只用 `armature.as_pointer()` 或 `armature.name_full`，原因见 CONTRACT.md 的 stable_id 规则章节。

约束：

- 不能允许同一 armature 内重复 root（两个 ChainSetting 用同一根骨骼当 root）。
- 不能允许多个 chain 重复模拟同一根 bone（bone 只能被一个 chain 包含）。
- root 只是 anchor / center，不参与 Verlet 推进，不写回 PoseBone。

### Solver Prepare

当前来源：

```text
_SpringBoneVRM.prepare
_BonePhysics.vrm_spring_bone_topology_key
_BonePhysics.build_vrm_spring_bone_state
_BonePhysics.build_vrm_spring_bone_write_records
_SpringBoneVRM.build_cpp_chain_runtime
_SpringBoneVRM.refresh_cpp_chain_runtime
```

新流程中应进入 solver slot：

```text
world.solver_slots["spring_vrm:{arm_ptr}:{arm_data_ptr}:{spec_hash}"]
  spec_key
  topology_key
  config_key
  frame_state
  topology
  native_context
  writeback_plan
  dirty_flags
```

建议拆分：

```text
frame_state:
  current_tail / prev_tail per bone

topology:
  root order
  chain bone names
  simulated bone names
  parent indices
  use_connect
  pinned flags if restart_only

native_context:
  static arrays
  reusable dynamic arrays
  batch plan
  optional future C++ capsule

writeback_plan:
  pose_bone refs
  pose indices
  bone_rest
  bone_rest_inv
  parent_rest_inv
  basis foreach buffer
```

### Solver Step

当前：

```text
solve_py:
  逐 substep、逐 chain、逐 bone 直接更新 target_pose_matrices 和 next_joints

solve_cpp:
  每 batch 打包数组
  调用 native_core
  解包 current_tails / target_matrices
  更新 next_joints / target_pose_matrices
```

新流程建议：

```text
SpringBone Step
  input:
    SpringChainSpec
    SpringBone slot state
    frame pose input
    collider arrays
  output:
    SpringBonePoseResult
    SpringBoneTailResult
    optional exchange items
```

Step 不直接调用 `write_pose`，只产生结果。

### Cross Solver Publish

SpringBone 可以自然发布：

```text
dynamic_bone_colliders:
  armature
  bone_name
  head_world
  tail_world
  radius
  group
  collided_by_groups

spring_tail_points:
  armature
  bone_name
  tail_world
  velocity

pose_targets:
  armature
  bone_name
  target_pose_matrix
```

用途：

- Cloth 读取动态骨骼 collider。
- Rigid body 读取 attachment points。
- Debug draw 显示弹簧骨轨迹。
- Export cache 记录尾端轨迹。

### Physics Writeback

当前：

```text
_SpringBoneVRM.write_pose
  -> foreach_get matrix_basis
  -> 填 basis_values
  -> foreach_set matrix_basis
  -> 旧实现内的单根 matrix_basis 写入分支
armature.update_tag()    ← 每个 solver 调一次，多 solver 场景下重复调用
```

新流程：

```text
Physics Writeback
  consumes:
    solver_slot["spring_vrm:..."]["output.basis_values"]  ← 预分配 buffer，C++ 原地写
    solver_slot["spring_vrm:..."]["writeback_plan"]       ← pose bone refs、rest matrices
  applies:
    armature.pose.bones.foreach_set("matrix_basis", basis_values)
    armature.update_tag()   ← 每个 armature 只调一次，汇总链路中所有 solver 的写完之后
```

**`armature.update_tag()` 重要约定：**

当前每个 solver 在 `write_pose` 末尾各自调用 `armature.update_tag()`。多个 solver 共同写同一个骨架时，中间的 `update_tag` 会触发不必要的 Blender depsgraph 重算。

新流程：`update_tag()` 必须在 Physics Writeback 节点里统一调用，每个 armature 在本帧所有 solver 写完之后只调一次。Writeback 节点需要收集本帧被写回的所有 armature，统一在最后 `update_tag()`。

长期收益：

- 可以 `Record Only`，跳过 depsgraph/redraw。
- 可以 `Preview Only`，只画 tail 和 target axis。
- 可以统一所有骨骼类 solver 的 `matrix_basis` 批量写回。
- BoneCloth 和 SpringBone 可以共用 writeback plan。
- 消除多 solver 场景下的中间 `update_tag()` 触发。

## 更新频率表

SpringBone 暴露出的最大隐性问题是：Python backend 和 C++ backend 对部分字段的读取频率不同。文档和未来 solver 声明必须明确这些策略。

| 数据 | 当前来源 | 当前 Python 路径 | 当前 CPP 路径 | 建议策略 | 更新 policy |
|---|---|---|---|---|---|
| frame / dt | scene | 每帧 | 每帧 | world begin 每帧 | `every_frame` |
| chain root / bones | ChainSetting | cache match | cache match | 注册为 `world.implicit_objects`，按 tag 收集 | `implicit_object_dirty` |
| stiffness / drag / gravity 数值 | ChainSetting | 每帧读 setting | 每帧读 setting | 进入 VRM 骨链隐式对象 payload，签名变化时更新 spec | `implicit_object_dirty` |
| pose head / tail | PoseBone | 每步按需读 | 每帧 pack | 每帧 dynamic sync | `every_frame` |
| parent target pose | 本帧 target | 每步 dict 查询 | 每 batch pack | 每帧 dynamic sync | `every_frame` |
| current_tail / prev_tail | cache joints | 每步 dict 读写 | pack/unpack 到 arrays | solver slot frame_state（C++ 原地） | `every_frame`（C++ 原地 mutate）|
| initial axis / rotation / scale | cache joint | 重建时建立，求解时读 | cpp_runtime 静态数组 | C++ persistent，topology dirty 才重传 | `restart_only` |
| parent_indices / use_connect | cache joint | 重建时建立 | cpp_runtime 静态数组 | C++ persistent，topology dirty 才重传 | `topology_dirty` |
| pinned | bone hotools_collision.pin | build state 时读 | cpp_runtime 静态数组 | **`restart_only`**（见下方说明）| `restart_only` |
| hit_radius | bone hotools_collision | solve 时每 bone 读取 | build_cpp_chain_runtime 时打入数组 | C++ persistent，dirty tag 触发重传 | `dirty_only`（推荐）或 `restart_only`（旧兼容）|
| collided_by_groups | bone hotools_collision | solve 时每 bone 读取 | build_cpp_chain_runtime 时打入数组 | 同 hit_radius | `dirty_only`（推荐）或 `restart_only`（旧兼容）|
| object/bone colliders | scope objects | 每帧 snapshot cache | 每帧 array snapshot cache | world.collider_snapshot（World Begin 构建）| `every_frame`（由 World Begin 统一）|
| collider arrays (CPP 格式) | colliders | 不用 arrays | 每帧构建/过滤 | solver slot lazy cache，collider source key 脏才重打包 | `lazy_on_access`（dirty 后下帧重建）|
| write records | pose bones | cache 中维护 | cache 中维护 | writeback_plan（topology dirty 才重建）| `topology_dirty` |
| basis foreach buffer | write_runtime | 写回时复用 | 写回时复用 | solver slot 预分配 buffer，永不重建 | `restart_only`（预分配一次）|
| native buffer validation | binding | 无 | 每次调用 | 进 native context，validate 只在 topology rebuild 时 | `topology_dirty` |

**`pin` 字段 restart_only 说明（必须显式声明）：**

当前节点文档和 `_BonePhysics.build_vrm_spring_bone_state()` 中已明确：”非 root 骨骼的 pin 属性只在 cache 重建时读取”。这是有意设计，不是疏漏。

理由：pin 表示”模拟期间该骨骼固定不动”，是 solver 初始化时的结构性决策，不是可以热改的运行时参数。如果允许每帧热读 pin，意味着模拟中途某根骨骼突然从自由变为固定，会导致状态爆炸或不连续跳动。

**声明约定：** solver 声明中必须在 Update Policy 的 `restart_only` 下列出 `pin`，并在节点 UI 描述中标注”修改 Pin 需要 Reset 后生效”。

**`hit_radius` 和 `collided_by_groups` 统一策略：**

Python 路径当前每帧从 bone 属性读取，CPP 路径只在 `build_cpp_chain_runtime` 时打入 static arrays，导致两条路径实时性不一致。新 solver 声明必须明确选择一种：

- `dirty_only`（推荐）：用骨骼属性 hash 做 dirty key，变化时刷新 C++ context 对应数组。
- `restart_only`（旧兼容）：只在 restart/topology 变化时刷新，保持和旧 CPP 路径相同行为。

两种策略的节点 UI 描述必须对用户说明生效时机。

### VRM 骨链的隐式对象模式

新路径中 VRM 骨链不再作为 solver step 的每帧 socket 输入，而是由注册节点写入统一的 `world.implicit_objects`：

```text
Physics World Begin
  -> VRM骨链属性
  -> VRM骨链对象注册
  -> SpringBone VRM模拟步
  -> Physics Writeback
  -> Physics World Commit
```

约定：

- tag 固定使用 `physicsWorld/names.py` 中的全局常量 `SPRING_VRM_CHAIN_OBJECT_TAG`，当前值为 `spring_vrm.chain`。
- 用户不需要提供额外 key；solver 直接按 tag 收集全部 VRM 骨链对象。
- payload 是规范化后的单条骨链对象，不包含 native handle。
- stable_id 由 armature pointer、armature data pointer、root bone 和骨链 hash 组成，只用于 registry 内部去重。
- signature 覆盖 armature pointer、armature data pointer、root bone、bone list、stiffness、drag、gravity 和 enabled。
- signature 不变时 version 不递增，solver 不应重建 slot 或 native static context。
- solver step 只接 world、启用和子步数；后续新 solver 也不应把大批对象 socket 直接堆在 step 节点上。

## 性能预演

当前 debug timing 已经有：

```text
validate
cache
restore
rebuild
colliders
targets
solve
write
write_basis
write_tag
total

CPP inner:
collision_setup
runtime_refresh
pack
native_core
unpack
unpack_tail
unpack_matrix
unpack_state
```

这些阶段已经能支持一次预演判断。

### 判断规则

如果：

```text
native_core 小
pack + unpack + collision_setup + write 大
```

说明 C++ kernel 不是主要瓶颈，性能被 Python 转换、数组筛选、解包和写回吃掉。此时不应该“把 cache 全搬 C++”，而应优先：

- 常驻 `cpp_runtime` 静态数组。
- 减少每 batch 临时切片。
- 把 collider arrays 放进 world runtime cache。
- 增加 native context 或批量 native API。
- 拆出统一 writeback 以支持 record only。

如果：

```text
native_core 大
pack/unpack/write 小
```

说明 kernel 是主瓶颈，应优化算法、碰撞投影、batching 或 C++ 内部结构。

如果：

```text
write_basis / write_tag 大
```

说明 Blender 写回和 depsgraph/redraw 是主瓶颈，应该优先支持：

- preview only。
- record only。
- 降频写回。
- 代理骨架 / 低成本预览。

如果：

```text
colliders 大
```

说明 scene-wide collider 枚举或数组转换太贵，应该迁移到：

- `Physics Object Scope` 限定。
- `Physics World Begin` 公共 snapshot。
- backend-specific collider arrays lazy cache。

### 推荐统一 timing 命名

现有 timing 可映射为：

| 当前 stage | 新阶段名 |
|---|---|
| validate | entity.validate |
| cache | solver.cache_match |
| restore | solver.restore_initial_pose |
| rebuild | solver.prepare_static |
| colliders | frame.collider_snapshot |
| targets | frame.pose_targets |
| cpp_runtime | solver.prepare_native_context |
| runtime_refresh | solver.prepare_dynamic_pose |
| collision_setup | solver.prepare_collider_arrays |
| pack | solver.pack_dynamic_input |
| native_core | solver.step.native_core |
| unpack | solver.unpack_result |
| unpack_tail | solver.unpack_tail |
| unpack_state | solver.update_frame_state |
| unpack_matrix | solver.build_pose_result |
| solve | solver.step |
| write | writeback.apply |
| write_basis | writeback.pose_basis |
| write_tag | writeback.update_tag |

## Solver 声明草案

```text
Solver:
  id: spring_vrm
  domain: bone_dynamics
  legacy_nodes:
    - springBoneVRM
    - springBoneVRM_CPP
  future_world_node:
    - physicsSpringBoneVRMSolver

Consumes:
  authoring:
    - SpringChainSpec from VRM骨链隐式对象
    - Bone.hotools_collision radius / pin / collided_by_groups
  frame_input:
    - armature matrix_world
    - PoseBone matrix / head / tail
    - frame dt
  world:
    - collider_snapshot
    - collider_arrays:spring_vrm_cpp
  exchange:
    - optional external dynamic colliders

Produces:
  result_stream:
    - pose_bone_matrices
    - spring_tail_points
  exchange:
    - optional dynamic_bone_colliders
  debug:
    - chain count
    - collider count
    - timing phases

Persistent State:
  slot_id:
    spring_vrm:{armature_ptr}:{armature_data_ptr}:{spec_hash}
  topology:
    - root order
    - simulated bone names
    - parent indices
    - use_connect
  frame_state:
    - current_tail
    - prev_tail
  native_context:
    - static arrays
    - reusable dynamic buffers
    - batch plan
  writeback_plan:
    - pose indices
    - pose bone refs
    - rest matrices
    - basis foreach buffer

Update Policy:
  every_frame:
    - frame
    - dt
    - armature matrix
    - pose head/tail
    - parent target pose
    - gravity / stiffness / drag
  dirty_only:
    - collider arrays
    - hit radius / collided_by_groups if live-edit supported
  restart_only:
    - initial axis
    - initial rotation
    - initial scale
    - pin if current behavior is preserved
  topology_dirty:
    - root/bones change
    - armature data changes
    - duplicate chain conflict

Writeback:
  targets:
    - PoseBone.matrix_basis
  plan_owner:
    - SpringBone slot, consumed by Physics Writeback
  supports_preview_only:
    true
  supports_record_only:
    true after result stream split

Export:
  supported:
    planned
  result_format:
    - pose_bone_matrices per frame
    - spring_tail_points per frame
```

## Cross Solver 场景预演

### SpringBone 发布动态骨骼碰撞体

流程：

```text
SpringBone Step
  -> produce spring_tail_points
  -> Cross Solver Publish dynamic_bone_colliders
  -> Cloth Solver Consume dynamic_bone_colliders
```

exchange item：

```python
{
    "channel": "dynamic_bone_colliders",
    "producer": "spring_vrm",
    "scope": "frame",
    "source_id": "armature:HairRoot:Hair_03",
    # stable_id 必须同时包含 arm_ptr + arm_data_ptr + bone_name
    # 不能只用 arm_ptr，Blender 删除骨架后可能复用相同指针给新对象
    "stable_id": f"spring_vrm:{int(arm.as_pointer())}:{int(arm.data.as_pointer())}:{bone_name}",
    "payload": {
        "armature": armature_obj,
        "bone_name": bone_name,
        "head_world": head,    # (3,) float32 numpy，不用 mathutils.Vector（性能）
        "tail_world": tail,    # (3,) float32 numpy
        "radius": radius,      # float
        "group": group,        # int
        "collided_by_groups": collided_by_groups,  # int，bitmask
    },
}
```

收益：

- Cloth 不需要知道 SpringBone 私有 cache。
- Debug 可以显示 producer。
- Export cache 可以记录这些临时 collider。

### SpringBone 消费刚体生成的临时 collider

流程：

```text
Rigid Solver Step
  -> publish rigid dynamic colliders
SpringBone Step
  -> consume dynamic rigid colliders
  -> solve tail projection
```

要求：

- Rigid 发布的 collider 必须进入公开 exchange channel。
- SpringBone 声明消费该 channel。
- group/mask 语义仍使用 HoTools collision group，而不是 Jolt layer。

## 迁移建议

**阶段依赖关系说明：** world collider snapshot（阶段 3）必须在 solver slot 化（阶段 4）之前完成，因为 slot 化后的 SpringBone solver 需要从 world 读 collider，而不是自己扫 scene。如果顺序颠倒，slot 化后的 solver 会无法获取碰撞数据。

### 阶段 0：只改文档和 timing 名称

目标：

- 不改节点 UI。
- 不改运行行为。
- 把现有 debug timing 映射到新阶段名（见本文「推荐统一 timing 命名」表格）。
- 确认每帧成本真实分布。

验收：

- 旧 Python / CPP 输出行为不变；新 world-aware 路径只记录 C++ 单实现计划，不新增 Python solver。
- 开启 `debug_output=True` 后，报告能看出 `pack/native_core/unpack/write/colliders` 各项占比和绝对值。

### 阶段 1：world-aware result stream

目标：

- SpringBone solver 接收 `PhysicsWorldCache`，没有 world 的路径视为未迁移旧路径，不作为新 contract 的兼容目标。
- 新路径不引入 `solve_py`；C++ step 不直接依赖 writeback。
- 结果发布到 `world.result_streams["spring_vrm_pose"]`，同时 slot 可保留预分配 buffer（`output.target_matrices`、`output.basis_values`）作为 solver 私有 runtime state。
- 第一条 vertical slice 只要求最小骨链输出能被 debug/result stream 节点观察，不要求一次性搬完整 UI 和旧节点行为。

验收：

- 可以在测试中只跑 step，不写 Blender。
- solver step 执行后，buffer 中有正确结果，`write_pose` 只消费 buffer，不访问 solver 内部 dict。

### 阶段 2：writeback plan 分离

目标：

- 把 `write_records/write_runtime` 从 solver state 概念上分离为 writeback plan。
- `write_records`（pose bone refs、rest matrices）进入 solver slot 的 writeback_plan 区。
- `write_runtime["basis_values"]`（预分配 float32 buffer）归属 writeback_plan，不归属 solver frame_state。

验收：

- SpringBone 和 BoneCloth 可以共享同一套 PoseBone writeback helper。
- `armature.update_tag()` 只在 writeback 阶段调用，不在 solver step 内调用。
- 可以统计 `writeback.prepare` 和 `writeback.apply` 独立耗时。

### 阶段 3：world collider snapshot（必须在阶段 4 之前）

目标：

- SpringBone 从 `world.collider_snapshot` 读取公共碰撞源（World Begin 已构建）。
- 引入 solver slot 内的 lazy collider arrays cache：`collider_source_key` 变化时重新打包成 CPP 格式，否则复用。
- 不保留 scene-wide collider fallback；未放入 object scope 的 collider 不参与新 world-aware 路径。

当前落地状态（2026-07-07）：

- `physicsWorld/spring_vrm/native.py` 已从 `world.collider_snapshot` 打包 SpringBone native ABI 支持的 `SPHERE` / `CAPSULE` / `PLANE` / `BOX` collider arrays。
- 每根模拟骨已经从 `Bone.hotools_collision` 读取 `radius` 与 `collided_by_groups`，作为 C++ `hit_radii` / `collided_by_groups` 输入。
- 同一 armature、同一链内的骨骼碰撞体会从被动 collider arrays 中排除，避免 SpringBone 自己撞自己。
- `SpringBone VRM模拟步` 的 stats result 已报告真实 `collider_count`。
- `PLANE` 用 `collider_segment_a` 传法线，`BOX` 用 `collider_segment_a/b` 传 X/Y 半轴、`collider_radii` 传带符号 Z 半轴长度；这只是 SpringBone native ABI 的打包约定，world snapshot 仍保留语义字段。
- `physicsWorld/spring_vrm/test_blender_spring_vrm.py` 已覆盖：隐式对象注册、native step、PoseBone 写回、连续帧状态保留，以及 sphere / plane / box world collider snapshot 对 SpringBone tail 投影的影响。

验收：

- 同一帧多个 solver（例如 SpringBone + BoneCloth）不重复扫描 scene。
- object scope 缩小后 SpringBone 只消费 scope 内 collider，debug output 显示 collider count 变化。
- collider 不变的帧（静态场景）`solver.prepare_collider_arrays` 耗时接近零。

### 阶段 4：solver slot 化

目标：

- per-armature cache 迁移到 `world.solver_slots["spring_vrm:{arm_ptr}:{arm_data_ptr}:{spec_hash}"]`。
- slot 内部按 topology、frame_state、native_context、writeback_plan 分区。
- `cpp_runtime` 进入 slot 的 native_context 区。

验收：

- `Cache Read → World Begin → SpringBone Step → Physics Writeback → World Commit → Cache Write` 完整路径跑通。
- `Cache Delete` / `clear_all` 可释放 slot 和 native context，内存不泄漏（插件 disable→enable 循环验证）。
- slot_id 包含 `arm_ptr + arm_data_ptr`，删骨架后重建骨架不命中旧 slot。

### 阶段 5：native context 与双调用模型

目标：

- 拆分当前 35 参数单次调用为"静态上传 + 每帧 step"两阶段（见 CONTRACT.md「Native Context 生命周期协议」）。
- static arrays 常驻 C++ context，topology dirty 才重传。
- 每帧只传 animated arrays + collider arrays + 标量参数。

**当前代码 → 新接口映射：**

| 当前代码 / 数据 | 新接口调用 | 触发时机 |
|---|---|---|
| `build_cpp_chain_runtime()` 构建 static arrays | `create_spring_vrm_context(schema, static_arrays)` | topology dirty / generation 变化 |
| `refresh_cpp_chain_runtime()` 更新 static | `update_spring_vrm_static(ctx, static_arrays)` | config dirty（不重建）|
| `solve_cpp()` 每帧 pack animated arrays | `update_spring_vrm_dynamic(ctx, pose_arrays, collider_arrays, scalars)` | 每帧 |
| `hotools_native.solve_spring_bone_vrm_cpp(...)` | `step_spring_vrm(ctx, dt, substeps)` | 每帧（在 dynamic 之后）|
| 解包 `current_tails` / `target_matrices` | `read_spring_vrm_results(ctx, out_basis_values)` | 每帧（在 step 之后）|
| Python owner dispose | `free_spring_vrm_context(ctx)` | slot dispose |

验收：

- `pack/native_core/unpack` 总耗时下降（以阶段 0 的 timing 基准对比）。
- static arrays 在 topology 不变的连续帧中不重传（`solver.prepare_static` 耗时接近零）。
- context dispose 幂等，多次调用不崩溃。
- Python owner 仍通过 slot dispose 控制生命周期。

## 风险点

### Python / CPP 行为实时性不一致

已观察到 hit radius、collided_by_groups、pin 等字段可能存在不同更新频率。迁移前必须决定：

```text
保持旧 CPP 行为:
  文档写明这些字段 restart 后生效。

统一为 live-edit:
  每帧刷新对应 arrays，承担额外成本。

提供 dirty tag:
  用户或属性更新时标记 dirty，下一帧刷新。
```

### 多骨架批量仍是 Python 串行

当前 `_run_spring_bone_vrm_node` 按 armature 分组后逐骨架调用 `_SpringBoneVRM.run()`。源码中已有 TODO 指出批量 C++ 后端需要：

```text
armature_world_per_bone
armature_world_inv_per_bone
armature_id_per_bone
```

这个需求与 world-aware result stream 一致，但不应在第一步处理。

### Writeback 成本可能是最终瓶颈

即使 solver step 和 pack 优化，`PoseBone.matrix_basis` 写回仍会触发 Blender 侧成本。需要通过 `Record Only` 和 `Preview Only` 验证：

- 纯模拟成本。
- 写回成本。
- depsgraph/redraw 成本。

### Collider Scope 改变会改变结果

旧 SpringBone 直接扫描 scene 中可见碰撞体。迁移到 object scope 后，如果用户没有把 collider 放进 scope，结果会不同。必须提供 debug：

```text
scope object count
collider source count
collider count
skipped hidden count
invalid source count
```

## 文档结论

VRM SpringBone 证明新物理流程契约是必要的。它已经包含几乎所有未来问题：

- 跨帧 solver state。
- 历史 Python / C++ 双 backend 带来的行为分叉。
- scene collider snapshot。
- backend-specific collider arrays。
- native 数组打包和解包。
- PoseBone 批量写回。
- 多骨架分发。
- 属性实时性差异。
- 跳帧恢复和 cache 清理。

因此 SpringBone 应作为第一条 world-aware vertical slice。短期目标不是保留 shadow pipeline，也不是维持 Python / C++ 双 backend，而是用最小骨链证明：`world.solver_slots["spring_vrm:{arm_ptr}:{arm_data_ptr}:{spec_hash}"]`、C++ native step、`world.result_streams["spring_vrm_pose"]`、PoseBone writeback plan 和 Cache Delete / clear_all 生命周期可以跑通。完整功能迁移应在这条窄切片通过后再展开。
