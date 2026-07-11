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

MC2 reduction/render mapping 永久不属于本 solver：用户输入 mesh 就是最终 proxy，用户自行制作低模代理。第一版暂不承诺 anchor、team synchronization、negative scale、wind zone、collider、self/inter collision、culling、bake/export 或完整 Unity manager/job 结构。未支持项必须返回明确 capability/error，不得使用 identity/zero 值静默伪装为 source parity。

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

Host-only immutable data：profile 原始值、curve key/handle、selection/pin 输入、setup options、bone hierarchy、final-proxy 静态 Mesh snapshot 和外部引用 identity。它们用于重建和诊断，不直接成为 native runtime representation。逐帧 evaluated pose 属于 N3 frame input，不得混进 H1/N0 topology signature。

当前 `MC2TaskSpec` 的 identity/signature 逻辑、`MC2ParticleProfileSpec` 和 `MC2SourceTopologySpec` 的 snapshot 思路可作为该层候选地基，但这些 class 不能原样冻结：现有 `MC2TaskSpec.sources` 仍保存 live Blender owner。slot 的长期数值契约只能保存纯 identity/snapshot；live `PropertyGroup`、Mesh、Object、PoseBone 必须由 frame resolver 临时持有。

### N0 Proxy static

第一版 native static upload 使用最终 proxy index space。proxy geometry 与 baseline 是两个独立 spec/signature；所有逐顶点数组共享 `vertex_count`，坐标空间和角色必须在字段名中显式。

Proxy geometry：

| 字段 | 类型/shape | 来源 |
|---|---|---|
| `local_positions` | `float32[N,3]` | final proxy reference/rest local position，不是 Armature 求值后的当前帧位置。 |
| `local_normals` / `local_tangents` | `float32[N,3]` | final proxy reference/rest local orientation basis。 |
| `uvs` | `float32[N,2]` | triangle tangent producer input。 |
| `vertex_attributes` | `uint8[N]` | mapped `VertexAttribute` bits；baseline local pose build 还会 finalise `ZeroDistance(0x20)`。 |
| `edges` | `int32[E,2]` | canonical final proxy edges。 |
| `triangles` | `int32[T,3]` | final proxy triangle role/winding。 |

Baseline derived data：

| 字段 | 类型/shape | 来源 |
|---|---|---|
| `parent_indices` | `int32[N]` | baseline parent；无 parent 为 `-1`。 |
| `child_ranges` / `child_data` | `int32[N,2]` / `int32[C]` | baseline child adjacency。 |
| `baseline_flags` | `uint8[B]` | 是否包含非 triangle line vertex 等 source flag。 |
| `baseline_ranges` / `baseline_data` | `int32[B,2]` / `int32[L]` | baseline traversal。 |
| `root_indices` | `int32[N]` | Move vertex 的 fixed root；无 root 为 `-1`。 |
| `depths` | `float32[N]` | 累计几何长度按全 proxy 最大值归一化。 |
| `vertex_local_positions` | `float32[N,3]` | `inverse(parent orientation) * (child - parent)`；非 baseline vertex 为 zero。 |
| `vertex_local_rotations` | `float32[N,4]` | parent-local baseline rotation，quaternion `xyzw`；baseline root 为 identity，非 baseline vertex 保留 zero quaternion。 |

后续 pose/output static：

| 字段 | 类型/shape | 来源 |
|---|---|---|
| `vertex_bind_pose_positions` | `float32[N,3]` | mapping/pose reconstruction。 |
| `vertex_bind_pose_rotations` | `float32[N,4]` | center/output reconstruction。 |

Mesh 长期输入契约是“用户输入已经是 final proxy、无 reduction、identity mapping”。solver 不得执行 SelectionMesh、merge、reduction、optimization、重采样或任何改变 vertex count/order/topology 的预处理；pin/attribute 按输入 vertex index 直接映射，result 按同一 vertex identity 回写。Bone static 还需要以下 setup-specific arrays；未验证前不得用普通 source-chain index 替代：

Blender Mesh 的“final proxy”契约不是把当前 `mesh.vertices/edges/loop_triangles` 直接别名成 baseline 输入。adapter 仍必须保持 vertex identity 不变，但要先按固定 MC2 source 的 proxy finalization 规则生成 source-equivalent final proxy：triangle 来自 reference Mesh `loop_triangles`，edge 集合是显式 Mesh edges 与所有 triangle edges 的 canonical union；含 triangle 的 Mesh 必须存在逐顶点唯一 UV，若同一 Blender vertex 的多个 loop UV 不一致则报错并要求用户拆分代理顶点；line-only Mesh 可使用 zero UV。finalization 完成后才能产生 `MC2ProxyStaticSpec` 并进入 `build_mc2_mesh_baseline()`。现有 `topology.py::_mesh_payload()` 只是 B3 scaffold/count shell，不得接入 native N0。

Mesh N0 topology signature 在注册时冻结。源对象后续可以通过 Armature、Shape Key 等修改顶点位置，但基础变形栈必须保持相同 vertex count/order/connectivity；任何会改变 topology/identity 的 modifier 都必须由 adapter 拒绝，不能把每帧 evaluated topology 偷换成新的 N0。

| 字段 | 类型/shape | 用途 |
|---|---|---|
| `vertex_to_transform_rotations` | `float32[N,4]` | proxy rotation -> bone transform rotation。 |
| `normal_adjustment_rotations` | `float32[N,4]` | triangle normal/tangent output adjustment。 |
| `vertex_to_triangle_ranges/data` | `int32[N,2]` / semantic records | triangle normal/tangent accumulation + flip flags。 |
| `source_vertex_identity` | host mapping table | native index -> stable bone/mesh target；不由 kernel 解释。 |

`mc2/static_data.py` 实现 Proxy geometry 与 Baseline derived data 的 immutable tuple contract、signature、validation 和显式 NumPy dtype packer；`mc2/mesh_baseline.py` 已按固定 source entry 实现纯 Mesh baseline builder，返回可能因 ZeroDistance 更新 signature 的 final proxy 与 baseline。`mc2/setups/mesh_cloth/final_proxy.py` 已按 `ConvertProxyMesh()` Tier A oracle 实现 Mesh finalization；`mc2/setups/mesh_cloth/static_build.py` 已把 Blender Mesh final proxy -> baseline -> Distance 组合成 slot static bundle，并由 `step_mc2()` 缓存到 `slot.data["mesh_static"]`。Mesh static input key 在 topology token 之外显式包含 active UV、Pin 开关/组名和最终 Fixed/Move mask；Pin mask 或 UV 变化以 `static_input_changed` 整包重建。它不读 N3 pose、不创建 native context、不 step、不发布 result。

### N1 Constraint static

Distance v0 使用 source 语义的 per-vertex adjacency，不使用无向 pair table。冻结的 host/native static group 名为 `MC2DistanceStaticV0`：

| 字段 | 类型/shape | 规则 |
|---|---|---|
| `distance_ranges` | `int32[N,2]` | 每个 source vertex 的 `(start,count)`；按 source vertex index 排列，所有 range 连续覆盖 data arrays。 |
| `distance_targets` | `int32[D]` | target proxy index。 |
| `distance_rest_signed` | `float32[D]` | vertical 为正、horizontal 为负；`abs(rest)<1e-8` 按 source 写 `+0.0` 并进入 zero special case。 |

每个 range 内先 vertical，后 horizontal；shear 记录与普通 horizontal 共用同一段和负号编码。原始 MC2 `uint[N] indexArray + ushort[D] dataArray` 只在 Tier A fixture 中保留，host 展开为 `int32` 后上传。create 必须拒绝非连续/重叠 range、负数或越界 target、非 finite rest、shape 不一致，以及 source 12-bit count、20-bit start 或 16-bit target 会截断的输入。

v0 kernel 不接收 `distance_kinds`。原因是 source 对 horizontal zero-distance 同样写 `+0.0`，运行时明确按 zero special case 而非 horizontal 分支处理；增加可消费 kind 会改变行为。builder 可以生成 host-only provenance/debug record，区分 `vertical`、`horizontal_edge` 和 `horizontal_shear`，但它不进入 ABI、constraint signature 或 source parity expected。

Distance builder 的 source 边界冻结如下：普通 final-proxy adjacency 过滤 all-non-Move 和任一 Invalid，按 baseline parent relation 分类；普通 adjacency 本身不由 `connectSet` 去重。shear 遍历每条 edge 的全部 triangle pair 组合，使用 `abs(normalDot)>=0.9396926`、对角线长度比误差 `<=0.3` 和全局 undirected `connectSet` 去重。shear 源码只过滤 opposite 两端都不 Move，没有重复 Invalid 过滤；v0 必须先由 Tier A fixture 复现该边界，不能在 builder 中静默修正。

同一类型内的 MC2 raw target 顺序来自 native hash map 枚举，horizontal bucket 内也不能假设普通 edge 位于 shear 前。2 个 Tier A runtime case 已证明该顺序属于数值语义：相同的 nonzero+zero records 按 `nonzero -> zero` 排列时 source vertex 最终 `next.x=1.0`，按 `zero -> nonzero` 排列时为 `1.47846889`，因为 zero 分支覆盖此前累计 correction。HoTools 不得按 target/kind 对 N1 records 重排；builder 产出的 range 内顺序必须原样进入 signature、ABI 和 native consumer。

MC2 的 hash container 不提供跨版本/平台顺序保证，因此 HoTools builder 要基于已经冻结的 finalizer `vertex_to_vertex_ranges/data` 和确定性 shear traversal 产生自己的稳定有序 records，并在当前固定 Unity/MC2 基线上逐 case 对拍 raw order。Tier A fixture 同时保存 source raw packed dump 与按每个 source vertex 的 `(rest-sign-class,target,rest)` canonicalize comparison view；zero 单独成类，不声称能从 raw dump恢复阈值化前的 vertical/horizontal provenance。canonical view 只关闭 static membership，raw order 与 runtime output 关闭顺序语义；任何差异都必须升级为 blocker，不能用 canonicalization 掩盖。

`distance_key` 由 `schema_version + distance_ranges + distance_targets + distance_rest_signed` 完整签名。N0 positions/attributes/edges/triangles 或 baseline parent 变化时重建 Distance；`distance_key` 变化触发整个 context rebuild + reset。`CreateData()` 当前不读取 parameters；stiffness curve、depth、friction、scale、`animationPoseRatio` 和 dynamic base pose 都是 runtime 输入，不属于 N1。`horizontalStiffness=0.5` 与 `velocityAttenuation=0.3` 是固定 kernel/N2 常量，参数热更新同样不得重建 Distance static。

TriangleBending v0 保留 source ordered quad role，冻结为 `MC2BendingStaticV0`：

| 字段 | 类型/shape |
|---|---|
| `bending_quads` | `int32[K,4]`，顺序为 source `(opposite0,opposite1,edge.x,edge.y)` role。 |
| `bending_rest_angle_or_volume` | `float32[K]`。 |
| `bending_sign_or_volume` | `int8[K]`。 |

三数组严格同长、finite、index 在 vertex/source ushort 域，marker 只允许 -1/+1/100。完整 record order 进入 signature 和 ABI。MC2 raw `ulong` 只在 Tier A fixture 保留，host create 显式拒绝任何 Pack64 会静默截断的 index。

同一 triangle pair 可以按 bending-then-volume 生成两条相同 role quad record。只有 volume 使用 sorted four-vertex key全局去重，且保留 traversal 中首个未排序 role quad；不得把 quad 排序后写入 ABI，也不得对 bending 做 unordered 去重。source edge/multi-hash 顺序没有跨版本保证，HoTools 必须定义确定性 edge/triangle-pair traversal，并同时用 raw fixture 与 canonical membership检查固定基线。

`writeBufferCount/writeDataArray/writeIndexArray` 不进入 v0：固定 source 的 Register、Normal 和 Split runtime 都不消费它们。runtime scratch count/vector同样不进入 static spec。

volume rest 的 producer 依赖 proxy `initLocalToWorld` 后的 initial world positions；因此 Bending builder input/dirty key 必须包含明确的 initial local-to-world transform或等价初始 scale/sign producer。它不是 N3 每帧 animated pose。静态 rest 写入后，runtime 另消费 `scaleRatio` 和 `negativeScaleSign`。

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
| `animated_base_world_positions` | `float32[N,3]` | Mesh 必需；当前帧无物理反馈的 BasePose evaluated position。 |
| `animated_base_world_normals` | `float32[N,3]` | Mesh 必需；与 positions 来自同一 evaluated snapshot。 |
| `proxy_animation_world_rotations` | `float32[N,4]` | 必需；Mesh 可由本帧 positions/normals + N0 baseline local pose 转换，Bone 由 transform pose 输入。 |
| `component_world_position/rotation/scale` | scalar arrays | 必需；Center frame input。 |
| `frame_time/dt/continuous/restart_required` | scalar metadata | 必需。 |
| `anchor pose` | dynamic reference | deferred；启用前需要 identity + pose + reset flag。 |
| `colliders/wind zones/sync center` | frame snapshot | deferred。 |

dynamic input 不参与 topology signature。shape 或 identity domain 改变不是普通 dynamic update，必须返回 rebuild/rebind 结果。

### H2 Blender Mesh frame adapter（唯一支持路径）

MeshCloth slot 为源对象持有一个生命周期受控的 BasePose read object：复制源对象及 Mesh data，保留 topology-preserving 基础变形，永久移除共享 Physics World GN offset，并禁止自身启用 solver。每帧只从这个对象的 `evaluated_get(...).to_mesh()` 取得 positions/normals；禁止从已接受 physics writeback 的源对象 evaluated mesh 读取 N3，否则上一帧结果会反馈到下一帧动画输入。旧物理资产、旧私有 output 和旧 solver parity 不属于该契约的支持或验收范围。

这是 Blender host 的固定性能架构。已实测排除 BlendShape/Shape Key 逐帧写回、单对象切换或移动 GN modifier、同一对象读取修改器栈前后两个 evaluated 阶段；前两者触发不可接受的回调/重算卡顿，后者无法稳定低成本取得两个阶段。实现不得保留这些替代分支或自动 fallback。

frame snapshot cache key 至少包含 source identity、BasePose identity、frame 和 world generation，缓存值不可被 consumer 原地修改。same-frame 可复用；跳帧、倒放、BasePose identity 更换或 topology signature 不符触发 restart/rebuild/error。该 cache 只缓存动态 pose，不拥有 N0 topology。

当前 Blender adapter 基础层已实现 BasePose 的共享物理 output 清除、创建时 Mesh topology identity 哈希、不可写 evaluated world position/normal snapshot，以及包含 source object/data、BasePose、frame、generation、Mesh topology token 的 same-frame cache；真实 Armature + 常驻源对象 GN 回归已证明无反馈。这里的 Mesh topology token 只覆盖 vertex identity/connectivity，不能替代包含 reference pose、UV 和 attribute 的 `final_proxy.proxy_signature`。MC2 slot 接线必须让同一次 N0 提取同时持有并校验两个 token；这部分以及 N3 rotation 派生仍未完成。

Mesh result adapter 使用同一帧的 `display_world` 和 `animated_base_world_positions`：

```text
world_delta = display_world - animated_base_world_positions
object_local_offset = inverse_linear(source.matrix_world) * world_delta
```

最终只发布 `float32[N,3]` object-local offset 到 Physics World result stream；源对象上的共享 GN modifier 常驻，不逐帧 toggle/reorder。writer 按相同 vertex identity 只更新 POINT attribute，并保证 Set Position 位于 Armature/Shape Key 等基础变形之后；它不接收 world position，不读取 solver state，也不参与 BasePose snapshot。

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
| `proxy_key` | final proxy topology、UV、attributes/Pin mask、baseline、bind/output mapping | rebuild context + reset；Blender slot 当前以 `static_input_changed` 重建 host bundle。 |
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
| final-proxy MeshCloth static build | supported host slice | ConvertProxyMesh Tier A、Mesh baseline Tier A、Blender n-gon/pin/UV seam 和 slot `mesh_static` cache 回归通过；仍不含 native context/solver step。 |
| Bone Line | planned first bone slice | hierarchy/baseline/output fixture。 |
| Bone Automatic/Sequential | blocked by oracle | Tier A connection fixtures。 |
| Distance | supported host static slice | `MC2DistanceStaticV0` immutable spec/signature/packer + 保序纯 host builder；7 个 `CreateData()` static fixture、2 个 `SolverConstraint()` ordered runtime fixture和 Blender slot bundle 回归。仍无 native consumer/solver capability。 |
| Bending | static oracle landed, runtime oracle/builder pending | `MC2BendingStaticV0` 三数组契约 + 13 个 `CreateData()` Tier A fixture；仍需 Solver/Sum scratch oracle与保序 host builder，不迁移 write arrays。 |
| Center without anchor/sync/negative scale | planned restricted | reset + moving component fixture。 |
| anchor/sync/negative scale/wind | deferred | W4 Tier A runtime fixtures。 |
| collider/self/inter collision | deferred | dedicated worksheet + registration/step fixtures。 |
| MC2 render mapping/reduction | intentionally out of scope | 用户负责 final proxy；不得添加对应 builder/capability。 |
| result stream + external writeback | required | same-frame/restart/failure tests。 |

`capabilities.py` 只能公开 `supported` 或已进入具体交付阶段的 `planned` 项。内部 worksheet 术语、近似数组或 self-consistency test 不构成 capability。

## Current B4 Disposition

未提交 B4 已于 2026-07-11 按本表整体清理，工作区恢复到 B1-B3 已提交基线。本表保留为删除审计，防止后续重新引入同类近似结构。

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

清理后已从 N0 独立重新开始；`static_data.py` 与 contract-shape fixture 不复用 B4 selection/constraint 算法。

## Open Decisions

| ID | 决策 | 草案建议 |
|---|---|---|
| C-01 | Mesh 是否固定 final-proxy/identity mapping？ | **已决**：永久固定。用户负责低模代理，mapping/reduction 不进入实现范围。 |
| C-02 | ABI 是否展开 Unity packed arrays？ | 是；显式 `int32` ranges，原始 packed dump只作 oracle。 |
| C-03 | 第一条 constraint slice？ | **已决**：Mesh/Bone Line 共用 `MC2DistanceStaticV0`；Bending 后接。 |
| C-04 | center v0 支持范围？ | component transform + fixed center；anchor/sync/negative scale/wind deferred。 |
| C-05 | Bone connection mode 3 是否公开？ | 内部 enum/fixture 保留，节点 surface 等产品决定。 |
| C-06 | 当前 B4 如何清理？ | **已执行**：整体移除算法/spec 改动，只通过新测试重建可保留的 lifecycle intent。 |
| C-07 | Tier A host？ | **已决并落地**：`tools/mc2_unity_oracle`；Unity 6000.3 batch host，外部引用固定 MC2 checkout，商业源码 ignore；明确排除废弃 HoClothUnity。 |
| C-08 | 骨架驱动 Mesh 的动态 pose/writeback 边界？ | **已决且唯一支持**：双对象常驻；N0 静态 topology + N3 无反馈 BasePose evaluated snapshot + 同帧 object-local final offset；源对象共享 GN 常驻且只更新 POINT attribute。 |

## S2 Exit Checklist

- [x] C-01 final-proxy/identity mapping 已冻结。
- [x] C-08 animated BasePose/GN writeback 边界已冻结。
- [x] C-02 packed arrays 在 ABI 展开为显式 ranges；raw packed dump 只作 oracle。
- [x] C-03 第一条 constraint slice 冻结为 Distance，Bending 后接。
- [ ] C-04 至 C-05 完成人工决策。
- [x] C-07 独立 Tier A host 已落地并关闭 Mesh baseline slice。
- [x] Mesh N0 final proxy/baseline 字段有 producer/consumer、Tier A oracle 和 slot static cache。
- [x] N1 Distance 字段、producer/consumer、7 个 build oracle、2 个 runtime order oracle、保序 host builder/packer 与 slot static bundle 已关闭。
- [ ] N1 Bending static 字段和 13 个 build oracle 已冻结；仍需 runtime scratch oracle与 host builder。Inertia 尚未冻结。
- [ ] Runtime parameter 16-sample schema 有 fixture。
- [ ] Coordinate/quaternion/unit convention 有 binding test。
- [ ] create/update/dynamic/reset/step/read/free 错误语义冻结。
- [ ] dirty/reset/rebuild matrix 与 Physics World frame context 对齐。
- [ ] result item/writeback plan schema 通过公共架构审查。
- [ ] deferred capability 不出现在已实现声明中。
- [x] B4 工作区按决策清理，现有测试不再验证错误近似模型。

在 checklist 完成前，不创建 C++ MC2 context，也不扩展 solver 节点 surface。
