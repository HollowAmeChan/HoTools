# MC2 Host/Native Contract Draft

更新日期：2026-07-11

状态：**S2 审查草案，不是已实现 ABI**。本文把 `MC2_SOURCE_DATAFLOW_WORKSHEETS.md` 的 W1-W7 收敛为 HoTools host/native 边界；字段只有通过 source oracle 和人工审查后才能进入 capability、slot schema 或 C++ ABI。

源码基线：`D:\Unity_Fork\MagicaCloth2`，MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

## 目标与非目标

本契约只冻结第一条 native vertical slice 所需的数据域和生命周期：

```text
Blender authoring/frame input
  -> immutable host snapshots + signatures
  -> source-aligned proxy/baseline/constraint build
  -> slot-owned native context
  -> dynamic sync -> reset/step -> readback
  -> Physics World result stream
  -> external writeback
```

第一版不承诺：MC2 reduction/render mapping、anchor、team synchronization、negative scale、wind zone、collider、self/inter collision、culling、bake/export 或完整 Unity manager/job 结构。未支持项必须返回明确 capability/error，不得使用 identity/zero 值静默伪装为 source parity。

## 固定边界

1. MC2 只有一个 solver identity，MeshCloth、BoneCloth、BoneSpring 是三个 setup adapter。
2. 每个 active task 使用一个 Physics World slot，并由该 slot 唯一持有一个 opaque native context。所有 task 复用同一 C++ implementation/schema，不建立三套 solver。
3. Python 负责 Blender 读取、identity/signature、静态构建输入、buffer packing、slot 生命周期、result publish 和 writeback plan；不保留第二套 runtime solver。
4. native 负责静态 constraint 数据、Center/particle persistent state、scratch、step 数学和原地 result buffer。
5. dynamic sync、reset、step、readback 是独立调用；same-frame 不重新 step。
6. solver 不写 `bpy`。公开结果只进入 `world.result_streams`；slot 不是结果总线。
7. native 不保存 Python/Blender object，不返回 backend handle，不使用隐藏全局 context。

“一个 native context”在本文中指每个 task slot 一个 context owner，而不是整个进程一个全局单例。以后若做多 team batch，仍必须保持 task identity、dispose 和 result ownership 可分离。

## 数据层次

### H0 Authoring identity

Host-only，不进入数值 kernel：

| 字段 | 语义 |
|---|---|
| `task_id` | `mc2:{setup_type}:{source_identity_hash}`；参数变化不改变。 |
| `setup_type` | `mesh_cloth`、`bone_cloth`、`bone_spring`。 |
| `source_identity[]` | Object 使用 owner/data pointer token；Bone 使用 armature owner/data + bone path。 |
| `ordered_source_identity[]` | 保留 Bone root authoring order，参与 topology key。 |
| `target_identity[]` | Mesh object/vertex 或 armature/bone 的稳定写回目标。 |

Blender pointer 只在当前 session 内作为 identity token。fixture 和 native debug 使用稳定 case id/path，不能保存 manager direct index。

### H1 Authoring snapshots

Host-only immutable data：profile 原始值、curve key/handle、selection/pin 输入、setup options、bone hierarchy、evaluated mesh snapshot 和外部引用 identity。它们用于重建和诊断，不直接成为 native runtime representation。

当前 `MC2TaskSpec` 的 identity/signature 逻辑、`MC2ParticleProfileSpec` 和 `MC2SourceTopologySpec` 的 snapshot 思路可作为该层候选地基，但这些 class 不能原样冻结：现有 `MC2TaskSpec.sources` 仍保存 live Blender owner。slot 的长期数值契约只能保存纯 identity/snapshot；live `PropertyGroup`、Mesh、Object、PoseBone 必须由 frame resolver 临时持有。

### N0 Proxy static

第一版 native static upload 使用最终 proxy index space。所有数组共享 `vertex_count`，坐标空间和角色必须在字段名中显式：

| 字段 | 类型/shape | 来源 |
|---|---|---|
| `rest_local_positions` | `float32[N,3]` | final proxy local pose。 |
| `rest_local_rotations` | `float32[N,4]` | baseline/proxy local pose，quaternion `xyzw`。 |
| `vertex_attributes` | `uint8[N]` | mapped final `VertexAttribute` bits。 |
| `edges` | `int32[E,2]` | canonical final proxy edges。 |
| `triangles` | `int32[T,3]` | final proxy triangle role/winding。 |
| `parent_indices` | `int32[N]` | baseline parent；无 parent 为 `-1`。 |
| `child_ranges` / `child_data` | `int32[N,2]` / `int32[C]` | baseline child adjacency。 |
| `baseline_ranges` / `baseline_data` | `int32[B,2]` / `int32[L]` | baseline traversal。 |
| `root_indices` | `int32[N]` | Move vertex 的 fixed root；无 root 为 `-1`。 |
| `depths` | `float32[N]` | 累计几何长度按全 proxy 最大值归一化。 |
| `vertex_bind_pose_positions` | `float32[N,3]` | mapping/pose reconstruction。 |
| `vertex_bind_pose_rotations` | `float32[N,4]` | center/output reconstruction。 |

Mesh v0 只接受“用户输入已经是 final proxy、无 reduction、identity render mapping”的受限输入域。Bone static 还需要以下 setup-specific arrays；未验证前不得用普通 source-chain index 替代：

| 字段 | 类型/shape | 用途 |
|---|---|---|
| `vertex_to_transform_rotations` | `float32[N,4]` | proxy rotation -> bone transform rotation。 |
| `normal_adjustment_rotations` | `float32[N,4]` | triangle normal/tangent output adjustment。 |
| `vertex_to_triangle_ranges/data` | `int32[N,2]` / semantic records | triangle normal/tangent accumulation + flip flags。 |
| `source_vertex_identity` | host mapping table | native index -> stable bone/mesh target；不由 kernel 解释。 |

### N1 Constraint static

Distance 使用 source 语义的 per-vertex adjacency，不使用无向 pair table：

| 字段 | 类型/shape | 规则 |
|---|---|---|
| `distance_ranges` | `int32[N,2]` | 每个 source vertex 的 target range。 |
| `distance_targets` | `int32[D]` | target proxy index。 |
| `distance_rest_signed` | `float32[D]` | vertical 为正、horizontal 为负；zero distance 的类型另有显式 flag/record。 |

若 native kernel 需要显式 kind，可增加 `distance_kinds:uint8[D]`，但 fixture 仍须证明与 source signed encoding 等价。shear 记录进入同一 per-vertex layout。

TriangleBending 保留 ordered quad role：

| 字段 | 类型/shape |
|---|---|
| `bending_quads` | `int32[K,4]`，顺序为 source `(v0,v1,v2,v3)` role。 |
| `bending_rest_angle_or_volume` | `float32[K]`。 |
| `bending_sign_or_volume` | `int8[K]`。 |
| `bending_write_ranges/data` | `int32[N,2]` / source-equivalent write records。 |

同一 triangle pair 可以生成 dihedral 和 volume 两条 record；不得按 unordered quad 去重。

Inertia static：

| 字段 | 类型/shape |
|---|---|
| `center_transform_identity` | host identity；dynamic sync 时解析，不上传 Blender pointer。 |
| `center_fixed_indices` | `int32[F]`。 |
| `center_local_position` | `float32[3]`。 |
| `initial_local_gravity_direction` | `float32[3]`。 |

### N2 Runtime value parameters

参数结构与 scheduler metadata 分离：

- 所有 `CurveSerializeData` 在 host 侧或可信 native conversion 中转为确定性的 `float32[16]` samples。
- scalar/bool/enum 按 `ClothParameters` 展开，包含 BoneSpring override 后的最终值。
- bending method、collision dynamic/static ratio、selfMode/syncMode 等派生字段显式存在。
- `animation_pose_ratio`、anchor identity、collider identity、wind zones 不属于纯 `ClothParameters` value block。
- `substeps/iterations/time_scale` 属于 HoTools scheduler block，使用独立 signature。

建议分为：

```text
MC2RuntimeParametersV0     # source GetClothParameters() 等价值
MC2TeamDynamicOptionsV0    # animation pose ratio 等 team 输入
MC2SchedulerSettingsV0     # dt/substeps/iterations/time scale
```

`MC2RuntimeParametersV0` 的字段顺序、enum width、padding 和 schema version 必须在 C++ binding 测试中冻结；Python dict 只用于 debug，不作为 ABI。

### N3 Dynamic frame input

每帧 `update_mc2_dynamic()` 原地写预分配 input buffers：

| 字段 | 类型/shape | v0 要求 |
|---|---|---|
| `proxy_world_positions` | `float32[N,3]` | 必需；当前动画/evaluated pose。 |
| `proxy_world_rotations` | `float32[N,4]` | 必需。 |
| `component_world_position/rotation/scale` | scalar arrays | 必需；Center frame input。 |
| `frame_time/dt/continuous/restart_required` | scalar metadata | 必需。 |
| `anchor pose` | dynamic reference | deferred；启用前需要 identity + pose + reset flag。 |
| `colliders/wind zones/sync center` | frame snapshot | deferred。 |

dynamic input 不参与 topology signature。shape 或 identity domain 改变不是普通 dynamic update，必须返回 rebuild/rebind 结果。

### N4 Persistent state and scratch

Native persistent：Center 跨帧历史、particle old position/rotation、animation pose history、display history、velocity/real velocity、friction/static friction/collision history、reset/stabilization runtime state。

Native step working arrays：next position、velocity reference position、base position/rotation。它们由每 step 明确覆盖，但为避免分配可驻留 context。

Native scratch：step basic pose、constraint temp/write/count/vector buffers、triangle normal/tangent buffers。scratch 可以常驻容量，语义上不得进入跨帧 state signature、result 或 fixture persistent block。

static topology/attributes/depth/source mapping 不得复制进“particle state”对外模型。native 内部可以为 cache locality 复制，但 dirty owner 仍属于 N0/N1。

## ABI Representation Rules

1. 输入输出 buffer 连续、C-order、固定 dtype；禁止 object dtype 和 Python nested list 跨 ABI。
2. host/native quaternion 统一为 `xyzw`；Blender `wxyz` 只在 adapter 边界转换。fixture 必须声明 convention。
3. 长度/位置单位使用 Blender scene unit 归一后的 meter；角速度字段按 source 分别保留 degree/s 或 rad/s，不做模糊“angle”命名。
4. N0-N4 的坐标空间写进字段名/descriptor；禁止只叫 `positions`。
5. source 的 packed 12/20、`ushort` 和 `ulong` 在 fixture exporter 中保留原始 dump，同时在 ABI 使用显式 `int32` ranges/records。二者通过转换 oracle 对拍。
6. array count 和 range 使用 `int32`，创建时检查溢出、负 index、range overlap 和 target 越界。
7. NaN/Inf、非单位 quaternion、degenerate role、重复 identity 在 create/update 边界返回结构化错误。
8. 所有 ABI struct/array group 带 `schema_version` 和 `backend_key`；shape validation 先于任何 context mutation。

## Native Lifecycle V0

```text
create_mc2_context(schema, setup_type, N0, N1, inertia_static)
update_mc2_parameters(ctx, runtime_parameters)
update_mc2_dynamic(ctx, dynamic_frame_buffers, team_options)
reset_mc2_context(ctx, reset_reason)
step_mc2_context(ctx, scheduler_settings)
read_mc2_results(ctx, output_buffers)
read_mc2_debug(ctx, debug_buffers)       # optional/read-only
free_mc2_context(ctx)                    # idempotent/noexcept
```

调用规则：

- `create` 成功前不替换 slot 里的旧 context；失败保持旧 slot 可 dispose。
- `update_parameters` 不重建 topology，不清空 particle history。
- `update_dynamic` 不推进时间；同一 frame 可重复调用，最后一次完整成功的 snapshot 生效。
- `reset` 使用最近一次成功 dynamic sync 的 proxy world pose，逐 array 执行 W5 reset 语义。
- `step` 只在 continuous frame 或显式允许的 restart policy 下执行；same-frame 复用上一真实 step result。
- `read_results` 写调用方预分配 buffer，不创建新 ndarray。
- `free` 可重复，任何错误路径均不得泄漏 context/subresource。

## Dirty、Reset 与 Rebuild

| Key | 内容 | 变化动作 |
|---|---|---|
| `identity_key` | task/setup/source/target identity | prune old slot + create new slot。 |
| `proxy_key` | final proxy topology、attributes、baseline、bind/output mapping | rebuild context + reset。 |
| `constraint_key` | Distance/Bending/Inertia static exact arrays | rebuild context + reset；首版不做 partial static patch。 |
| `parameter_key` | 16-sample runtime value parameters | hot update，保留 history。 |
| `team_option_key` | animation pose ratio 等非结构 team 值 | dynamic/static update；不默认 reset。 |
| `scheduler_key` | dt policy/substeps/iterations/time scale | hot update；时间不连续由 frame context 单独触发 reset。 |
| `backend_key` | ABI schema、native build/version/layout | rebuild context + reset。 |
| `world_generation` | Physics World owner generation | rebuild slot/context。 |

reset reasons 使用稳定 enum/string：`created`、`world_generation_changed`、`proxy_changed`、`constraint_changed`、`time_discontinuous`、`user_reset`、`backend_recreated`。仅参数变化不得记录为 reset。

selection 改变通常会重建 attributes、baseline 和 constraint arrays，因此归入 proxy/constraint rebuild；不要建立一个脱离这些派生数据的 `selection_signature_restart` 并假设下游自动有效。

## Result and Writeback

Native result buffers：

| Setup | Native output | Host publication |
|---|---|---|
| MeshCloth v0 | proxy display world positions，可选 rotations | 转 object-local final offset，发布 `GN_ATTRIBUTE_CHANNEL`。 |
| BoneCloth | proxy display world pose | 按 `vertex_to_transform_rotation` 和 parent world pose转 stable bone local transform，发布 `BONE_TRANSFORM_CHANNEL`。 |
| BoneSpring | 与 BoneCloth 同 shape | 同一 bone transform channel；setup 标识仍为 bone_spring。 |

result item 至少含 `frame`、`generation`、`slot_id`、`setup_type`、`target_identity`、`result_revision`、纯数值 buffer 引用和 error/status。不得含 native handle、manager direct index、Blender owner 或 live property。

writeback plan 由 host prepare；apply 阶段解析 target identity 并写 Blender。solver step、native readback、debug draw 和 export 都不能直接写 Blender。

## Capability V0 Proposal

| 能力 | v0 状态 | 验收条件 |
|---|---|---|
| one solver / three setup identities | supported contract | registry/declaration test。 |
| final-proxy MeshCloth static build | planned | W1-W3 Tier A/B full-array fixture。 |
| Bone Line | planned first bone slice | hierarchy/baseline/output fixture。 |
| Bone Automatic/Sequential | blocked by oracle | Tier A connection fixtures。 |
| Distance | planned | per-vertex signed layout fixture。 |
| Bending | planned after Distance | quad/rest/sign/write mapping fixture。 |
| Center without anchor/sync/negative scale | planned restricted | reset + moving component fixture。 |
| anchor/sync/negative scale/wind | deferred | W4 Tier A runtime fixtures。 |
| collider/self/inter collision | deferred | dedicated worksheet + registration/step fixtures。 |
| MC2 render mapping/reduction | unsupported v0 | product decision and mapping fixtures。 |
| result stream + external writeback | required | same-frame/restart/failure tests。 |

`capabilities.py` 只能公开 `supported` 或已进入具体交付阶段的 `planned` 项。内部 worksheet 术语、近似数组或 self-consistency test 不构成 capability。

## Current B4 Disposition

当前未提交 B4 保留在工作区作为审查材料。本表决定下一次代码处理方向，不在本文提交中修改它们。

| 工作区改动 | 处理结论 | 原因 |
|---|---|---|
| `selection.py::MC2SelectionSpec` 与 `_selection_tree()` | 整体重写 | 混合 authoring selection、proxy attributes、baseline parent/depth；普通 BFS 不等价。 |
| `constraints.py::MC2ConstraintTopologySpec` | 整体重写 | undirected pair/kind 和简化 bending quad 不是 source runtime layout。 |
| Automatic/Sequential Bone connection helper | 整体重写 | 缺 reverse-and-continue、many-to-many、triangle filters 和 residual line 语义。 |
| `initial_state.py` 接收 selection parent/depth/attributes | 移除该耦合 | static proxy/baseline 与 reset pose 是不同数据域。 |
| `MC2ParticleBuffer.apply_constraint_topology()` | 移除 | triangle/zero-distance bits 应由 proxy conversion producer 生成，不应在动态 buffer 上补写。 |
| slot 增加 selection/constraint signatures | 方向保留、名称重构 | 应升级为 proxy/constraint exact keys，不能绑定当前错误 spec。 |
| adapter 增加 selection/constraint builders | 接口方向保留、实现重接 | setup adapter 应生成分层 host snapshots，但参数列表需按 H/N 层拆开。 |
| solver 的“先只读 prepare，再 acquire_write” | 保留 | 满足失败不半更新的 Physics World 事务边界。 |
| selection/topology change dispose/rebuild 测试 | 保留测试意图、重写断言 | lifecycle 有效；当前 count/近似数组断言不能作为 parity。 |
| capability/declaration 升级为 selection/constraint framework | 不提交 | 在 source-aligned specs 和 oracle 之前公开为 capability 过早。 |

建议处理顺序：先保存本表和必要 diff 参考，再把 B4 未提交改动从工作区移除，随后在独立提交中按 N0/N1 从纯静态 spec + Tier B fixture 重新开始。移除动作需要单独确认，本文不自动回滚用户工作区。

## Open Decisions

| ID | 决策 | 草案建议 |
|---|---|---|
| C-01 | Mesh v0 是否固定 final-proxy/identity mapping？ | 是；把限制写进 node/capability，mapping/reduction deferred。 |
| C-02 | ABI 是否展开 Unity packed arrays？ | 是；显式 `int32` ranges，原始 packed dump只作 oracle。 |
| C-03 | 第一条 constraint slice？ | Mesh/Bone Line 共用 Distance；Bending 后接。 |
| C-04 | center v0 支持范围？ | component transform + fixed center；anchor/sync/negative scale/wind deferred。 |
| C-05 | Bone connection mode 3 是否公开？ | 内部 enum/fixture 保留，节点 surface 等产品决定。 |
| C-06 | 当前 B4 如何清理？ | 整体移除算法/spec 改动，只通过新测试重建可保留的 lifecycle intent。 |
| C-07 | Tier A host？ | 独立最小 Unity 验证工程；明确排除废弃 HoClothUnity。 |

## S2 Exit Checklist

- [ ] C-01 至 C-07 完成人工决策。
- [ ] N0/N1 每个字段有 W1-W7 producer/consumer 和最小 oracle。
- [ ] Runtime parameter 16-sample schema 有 fixture。
- [ ] Coordinate/quaternion/unit convention 有 binding test。
- [ ] create/update/dynamic/reset/step/read/free 错误语义冻结。
- [ ] dirty/reset/rebuild matrix 与 Physics World frame context 对齐。
- [ ] result item/writeback plan schema 通过公共架构审查。
- [ ] deferred capability 不出现在已实现声明中。
- [ ] B4 工作区按决策清理后，测试不再验证错误近似模型。

在 checklist 完成前，不创建 C++ MC2 context，也不扩展 solver 节点 surface。
