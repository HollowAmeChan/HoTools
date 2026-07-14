# MC2 当前状态与执行计划

更新日期：2026-07-14

文档状态：**新 `physicsWorld.mc2` 的唯一实施计划与状态入口**。

源码基线：`D:\Unity_Fork\MagicaCloth2`，MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

本文回答新路径已经完成什么、Host/Native 边界是什么、当前阻塞在哪里以及下一交付如何推进。字段级源码语义、顺序敏感行为与 oracle 规则见 `MC2_SOURCE_DATAFLOW_WORKSHEETS.md`。

## 不可变方向

1. MC2 只有一个 solver identity：`mc2`。MeshCloth、BoneCloth、BoneSpring 是三个 setup adapter，共用 context、粒子状态、step 与结果生命周期。
2. 新运行时只保留一个 C++ 数值实现。Python 负责 Blender snapshot、签名、静态构建、slot/context 生命周期、buffer packing、result publish、writeback plan 和 debug，不保留第二套 Python solver。
3. 用户输入 Mesh 永远视为 final proxy。solver 不做 selection crop、merge、reduction、optimization 或 render mapping，也不改变 vertex count/order/identity。
4. Mesh 动画输入固定采用“只读 BasePose 对象 + 源对象常驻 GN offset”。直接读取已接受物理写回的源对象 evaluated mesh 会形成反馈，永久禁止。
5. 每个声称 source-aligned 的字段都必须有固定源码 producer/consumer、明确输入域和 Tier A oracle。旧 solver parity、自洽测试、shape/count 测试只能证明 regression，不能证明 MC2 parity。
6. 旧 `physicsMC2MeshCloth` 与 `_native/src/mc2*` full-core/context 是待删除实现。它们可用于寻找公式、生命周期风险和性能经验，但不是新 ABI、兼容目标、运行依赖或验收 oracle。

## 文档职责

| 文档 | 唯一职责 |
|---|---|
| 本文 | 当前完成度、Host/Native 契约、工程禁区、下一交付和已决产品边界。 |
| `MC2_SOURCE_DATAFLOW_WORKSHEETS.md` | 固定 MC2 源码中的 producer/consumer、顺序敏感行为、数值陷阱和 oracle 规则。 |
| `PHYSICS_WORLD_IMPLEMENTATION_STATUS.md` | 整个 Physics World 的跨 solver 摘要；MC2 细节以本文为准。 |

发生冲突时按以下顺序判断：固定 MC2 源码行为、`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 的公共架构、本文的已决边界、当前代码与测试。旧实现和历史文档排在最后。

## 当前事实快照

状态标签只使用：`landed`（生产路径已接线）、`verified contract`（契约/oracle 已冻结但未接生产）、`scaffold`（生命周期地基）、`not implemented`。

| 层 | 当前状态 | 事实边界 |
|---|---|---|
| solver/task scaffold | landed foundation | `specs.py`、`topology.py`、`solver.py` 已有统一 task、slot reuse/rebuild/prune 和先 prepare 后写锁的事务边界；slot 已接入 native context 的 staged create/replace、热更新、reset/step/read 与 dispose。连续帧已执行 Pin 跟随与单次 ordered Distance projection。 |
| particle owner | landed foundation | `MC2ParticleBuffer.allocate()` 只分配并保持未初始化；`reset_from_frame()` 按源码同时覆盖 position/rotation history并清零 velocity/friction/collision。slot 唯一持有 native context V0；native reset已清零 velocity，连续 step按 Tier A producer执行 Center depth inertia→position/velocity-reference shift→velocity rotation→velocityWeight→damping→gravity→predict，并在 Distance velocity-reference调整后提交 persistent velocity。animated base pose同时进入 step-basic scratch；friction/collision仍只有 host contract。 |
| Mesh N0 final proxy | landed | `final_proxy.py` 已实现 triangle/edge union、方向统一、vertex adjacency、vertex-to-triangle flip、normal/tangent、UV seam gate 和同 index Pin attribute，并由 Tier A fixture 覆盖；7 组冻结数组已由 staged native context 校验并持有。 |
| Mesh N0 baseline | landed | `mesh_baseline.py` 已实现 parent/child、baseline ranges/data、root/depth、local pose 和 ZeroDistance attribute finalization；equal-cost 使用 HoTools 确定性 index 规则并登记为 intentional deviation；10 组冻结数组已接入 native context。 |
| Mesh static slot bundle | landed | `static_build.py` 在 rebuild 时组合 finalizer、baseline、Distance、Bending 与 Center；完整 Mesh connectivity token、UV/Pin mask及 Center initial gravity direction进入 schema 3 static input signature，同 vertex count下的连接变化也会重建。任一 N0/N1 上传失败会释放 staged context并保留旧 slot。 |
| Distance N1 | landed foundation | `distance_static.py` 已提供保序 host builder、immutable spec/signature 与显式 packer；7 个 build fixture、2 个顺序敏感 runtime fixture通过。`ranges/targets/rest_signed` 已由 native context 校验并持有，连续帧执行 ordered projection并同步 velocity-reference。 |
| TriangleBending N1 | landed foundation | `bending_static.py` 已提供 role-preserving host builder、immutable spec/signature 与 `int32/float32/int8` 只读 packer；ordered role quad/rest/marker 已上传 native。directional dihedral、volume、negative scale、fixed-point accumulate、Move-only average与scratch clear已由3个 Tier A runtime case逐数组验证。 |
| Inertia/Center | landed restricted production slice | `center_state.py` 已冻结 center fixed list/local center、initial local gravity、component/anchor frame pose、persistent reset与 substep derived分层；Center static、`center_step_inertia_001` 与 `particle_step_inertia_001` 均由 Tier A oracle覆盖。`center_frame_shift_world_inertia_001` 已冻结无 fixed list、单位正缩放、无 anchor/smoothing/limit/teleport 域内的 component world-inertia shift；Host persistent 会将 shift 后的 old-frame/now-world history送入 Center step，native预步同步变换粒子 position/rotation/velocity-reference/velocity，solver仅在该精确域且 stabilization 完成后启用。Mesh BasePose frame snapshot 已携带 evaluated component pose；solver 会按固定点平均/绑定旋转或 component pose 构建 Center world pose，在 reset/连续帧上传、读取并提交 native Center history。anchor、smoothing/limit、fixed-list frame shift、完整 negative-scale teleport matrix与 baseline重建型 step-basic仍未完成。 |
| Mesh BasePose adapter | landed foundation | `base_pose.py`/`frame_input.py` 已验证双对象、无反馈、topology token、不可写 same-frame snapshot，并从 N0 triangles/UV/flip records派生 `float32[N,4] xyzw` world rotations。`physicsMC2Step` 在 active World中会从已配置 `mc2_base_pose_proxy` 自动读取/缓存 N3 snapshot，并使用 World dt；显式 `frame_inputs` 仍用于测试和受控调用。rotation/reset数组已有 Tier A oracle；当前首版仍要求每个 vertex属于 triangle。 |
| Runtime parameters N2 | landed foundation | `runtime_parameters.py` 已冻结 V0 value ABI：47 个 `float32`、11 个 `int32`、9x16 个 curve samples；task/slot parameter signature已改用该运行时块，scheduler保持独立签名。Mesh 非线性曲线与 BoneSpring完整覆写由 2 个固定 commit Tier A dump逐数组验证；particle prediction已消费 gravity/direction与 damping curve，Distance消费 stiffness/velocity attenuation，其余值仍只保存未消费。 |
| Dynamic/reset N3/N4 | landed foundation | `frame_state.py` 已冻结 frame identity与 first pose/same-frame/continuous/reverse/gap/generation/user reset transition；N3携带受检 `velocity_weight/gravity_ratio/scale_ratio/negative_scale_sign/frame_interpolation`。native context V0 已接 old/current animated pose、Fixed position/rotation interpolation、prediction、Pin、Distance、Bending、post与read。Bone connection-aware rotation、Move step-basic pose与inertia仍未实现。 |
| 新 native context/step | landed foundation | 新 V0 已完成 `create -> inspect -> update N0/N1/parameters/dynamic/center dynamic -> reset -> step(no collision) -> read -> free`，由 slot 独占并支持 staged replacement、输入先验证、幂等释放、双 ABI 与 soak 测试。step 已执行 Center derived state与Move inertia、frame interpolation、animated step-basic scratch、gravity/damping prediction、Pin、Distance、Bending fixed-point scratch与 persistent velocity commit；仍无 wind/collision、Bone output与 stats。旧 `_native` full-core 不计入此项。 |
| result/writeback | landed Mesh transaction | Mesh native readback先复制为带 frame/generation/world generation/revision/native revision 的只读内部 candidate，始终保持 `ready=False`；公共层验证 active world frame/generation与单 final-proxy target后，构造 `ready=True` 的共享 `gn_attribute` object-local offset envelope。same-frame只重发已有 candidate且不重复 read/step/revision，context rebuild从 revision 1重新开始；批次先完整验证、发布失败恢复旧 result streams。统一 GN writeback已覆盖成功、vertex-count mismatch清零/诊断及下一有效 result恢复。`BONE_TRANSFORM_CHANNEL`与`mc2_stats` 仍为计划通道。 |

## Host/Native 契约

新路径的数据流固定为：

```text
Blender authoring/frame input
  -> immutable host snapshots + signatures
  -> source-aligned N0/N1 static build
  -> slot-owned native context
  -> parameter/dynamic sync -> reset/step -> readback
  -> Physics World result stream
  -> external writeback
```

每个 active task 对应一个 Physics World slot 和一个 opaque native context。context 只能由 slot dispose 链释放；native 不保存 Blender/Python object、不返回 handle 给公开结果、不创建隐藏全局 owner。

### 数据分层

| 层 | 内容 | 生命周期 |
|---|---|---|
| H0 identity | task/setup/source/target identity、ordered Bone root identity | host/session；不进入数值 kernel |
| H1 authoring snapshot | profile、curve authoring、Pin/selection、setup options、bone hierarchy、外部引用 identity | host immutable；用于重建/诊断 |
| N0 proxy static | final proxy positions/orientation/UV/attributes/edges/triangles、baseline parent/child/root/depth/local pose、output mapping | slot static |
| N1 constraint static | Distance/Bending/Inertia 等 source-aligned exact arrays | slot static |
| N2 runtime parameters | 16-sample curves、scalar/bool/enum、BoneSpring override、team options、scheduler block | hot update |
| N3 frame input | animated world pose、component pose、dt/frame continuity、collider/anchor snapshots | frame |
| N4 state/scratch | Center/particle history、step working arrays、constraint scratch | context persistent / substep |

静态 mapping、persistent state 与 scratch 不得因为内存上放在同一 context 就混成一个公开 spec。逐帧 evaluated pose 不得进入 N0 signature；反过来 N0 reference pose、UV 或 Pin mask变化也不能伪装成普通 dynamic update。

### 首版 ABI 规则

1. buffer 为连续 C-order 固定 dtype；禁止 object dtype、Python nested list 和隐式 dtype conversion 跨 ABI。
2. quaternion 统一 `xyzw`；Blender `wxyz` 只在 adapter 边界转换。
3. 坐标空间写进字段名；禁止 ABI 中出现无上下文的 `positions`、`rotations`、`scale`。
4. Unity packed 12/20、`ushort`、`ulong` 只保留在 raw fixture；ABI 使用 checked `int32` ranges/records。
5. create/update 在 mutation 前校验 schema version、backend key、shape、range、index、finite、unit quaternion 与 identity uniqueness。
6. static arrays 默认 immutable；dynamic update 原地写预分配 buffer；readback 写调用方提供的 output buffer。
7. debug dict 不是 ABI。debug 只能展示 context 实际消费的数据，不能从 authoring input 重算一份“看起来正确”的状态。

### Dirty、Reset 与 Rebuild

| 变化 | 动作 |
|---|---|
| task/setup/source/target identity | prune 旧 slot，创建新 slot/context |
| final proxy、UV、Pin/attribute、baseline、output mapping | rebuild context + reset |
| Distance/Bending/Inertia exact static arrays | rebuild context + reset；首版不做 partial patch |
| runtime value parameters | hot update，保留 particle/Center history |
| scheduler 值 | hot update；时间连续性由 frame context 独立判断 |
| world generation、backend/schema/layout | rebuild context + reset |
| same-frame | 不重复 step；复用上一真实 step result |
| user reset、倒放、跳帧策略触发 | 使用最近一次完整 N3 pose执行显式 reset |

`create` 失败时旧 context 仍保持可 dispose；`free` 必须 idempotent/noexcept。参数变化不能被记录为 reset。allocation 只建立容量，不代表 particle 已按当前帧 pose 初始化。

### Result 契约

MeshCloth native 输出 world-space display pose，host 转为同一 vertex identity 的 object-local final offset并发布 `GN_ATTRIBUTE_CHANNEL`。BoneCloth/BoneSpring 输出 world proxy pose，host 转为 stable bone identity 的 local transform并发布 `BONE_TRANSFORM_CHANNEL`。

result item 至少包含 frame、generation、slot id、setup type、target identity、revision、纯数值 buffer和状态；不得包含 native handle、manager direct index、Blender owner或 live property。solver/readback/debug 不直接写 Blender，writeback 只消费 result stream。

## 工程经验与禁区

这些结论来自旧实现实践，但对新路径仍有效；旧 class、cache schema 和 ABI 本身不迁移。

### Blender 与性能

- solver timing 很短但 fps 低时，优先检查 depsgraph、Outliner、场景对象数量和 UI；不要只继续优化 C++ kernel。
- 禁止私有 frame handler 或 scene-wide scan 刷新 BasePose。snapshot 只由当前 task、当前对象按需读取。
- 禁止逐帧写 Shape Key、移动/toggle GN modifier 或在同一对象上读取物理前后两个 evaluated 阶段；这些路径已证明会产生反馈、不稳定刷新或不可接受的重算。
- BasePose 与源对象必须保持相同 vertex identity/connectivity。逐帧只做轻量 token/count 校验，完整 topology hash只在静态创建/刷新时计算。

### Cache 与生命周期

- 长期 native resource 只能挂在 slot/context owner；不得平铺到模块全局、节点 dict 或第二套 cache。
- state 复制/替换必须显式转移或释放 runtime slots；不能让 topology cache、frame snapshot和 native context各自拥有不同 generation。
- 参数热更新保留 history；静态输入变化先完整只读构建，成功后再替换 slot，避免 world 半更新。
- debug/ABI view 按需构造，不能每帧重建大 dict/array tree。

### 数值与碰撞

- 不把旧 full-core 的“效果接近”当作 source parity。尤其 Distance record order、Bending role、Center/reset 和 self-collision contact lifecycle都不是可凭结果外观猜测的细节。
- self collision 不是单个 point-triangle/edge-edge 投影函数；broadphase、contact 去重/缓存、intersect 分帧、质量和摩擦共同决定稳定性。厚度增大也会增加重复命中和黏连风险。
- 互碰不是把另一个 mesh 的顶点展开成 sphere collider。它需要对象所有权、质量、接触汇总和多体调度，必须独立设计。
- 不复制 Unity TeamManager/job/chunk 结构；只迁移经过 oracle确认的数学状态转移和执行顺序。

## 当前切入点

下一交付是 **剩余 Center frame shift 与 Mesh vertical-slice 收口**：

1. Blender component/BasePose frame snapshot 到 Center dynamic、world-inertia frame shift、Move particle inertia 与 animated step-basic scratch 的纵切已在无 fixed list、单位正缩放、无 anchor/smoothing/limit/teleport 且 stabilization 完成的精确域闭环；下一步逐项冻结并扩展 anchor、smoothing/limit、fixed-list、negative-scale teleport 和 baseline重建型 step-basic边界。
2. private candidate 已同时持有同 vertex identity 的 world pose和 object-local offset并保持 `ready=False`；公共 Mesh result transaction、发布失败回滚、统一 GN writeback交接、节点自动 N3 snapshot与写回失败恢复验收均已完成。
3. candidate 与公共 envelope 已分别验证 frame/frame generation/world generation/revision；same-frame不得重复 read/step/revision，只重发同一 revision。
4. static 上传或 rebuild 失败必须保留旧 slot/context；除 initial gravity direction等明确 N1 producer外，参数热更新继续保留粒子 history。

退出条件：双 ABI 的静态数组校验、reset/continuous/same-frame 数值状态、失败回滚与 Tier A 最小 Mesh fixture通过。

## 后续交付顺序

### 1. N3 Frame Input 与 Reset（已完成生命周期地基）

- 从 BasePose 同一 snapshot 生成 world positions、normals 和 per-vertex rotations。
- 明确 `create/register` 只分配 owner，首次有效 current-frame world pose 才执行 reset。
- same-frame 只更新/复用 snapshot，不重复 step；跳帧、倒放、用户 reset 和 generation 变化有稳定 reason。
- static mapping、persistent particle history、step working arrays 与 scratch 分组，禁止继续混放在 initial-state spec。

退出条件：allocation-before-reset、首次 reset、连续帧、same-frame、time discontinuity、参数热更新保留 history 的数组级测试通过。

### 2. Native Context 最小闭环（已完成生命周期地基）

首条 API 只允许：`create -> inspect -> update_parameters -> update_dynamic -> reset -> step(no collision) -> read -> free`。

- 每个 slot 唯一持有一个 opaque context；create 失败不能破坏旧 slot。
- native 不保存 `bpy`/Python object，不暴露 backend handle，不使用隐藏全局 context。
- static key 改变 rebuild + reset；parameter/scheduler 热更新保留 history。
- ABI 先做 schema/version/dtype/shape/finite/index 校验，再修改 context。
- Python 不实现平行 solver 作为 fallback；调试只读取 context 实际消费的数据。

退出条件：双 ABI、连续帧、same-frame、reset、异常回滚、idempotent free 和 leak/soak 测试通过。

### 3. MeshCloth Vertical Slice

第一版范围：单 final-proxy Mesh、Pin、无 collider。输出为同 vertex identity 的 object-local offset，经公共 GN writeback 应用。

验收必须覆盖首帧、连续帧、same-frame、参数热更新、UV/Pin/static rebuild、Armature 驱动 BasePose、topology mismatch、reset、dispose 和写回失败。数值只以固定 MC2 Tier A fixture验收，不要求与旧 solver 对拍。

扩展顺序：Distance -> Bending -> Tether/Angle/Motion -> Center/Inertia -> collider -> self collision。每项仍遵循 worksheet -> contract -> oracle -> host/native -> integration。

### 4. Bone Setup

顺序：Bone Line -> BoneSpring override -> BoneCloth Automatic/Sequential。Bone connection 必须先有“Bone Connection 与代理拓扑”对应 Tier A fixture；不能复用旧逐链 zip 近似。输出只发布稳定 bone identity 的 local transform，由公共 writeback 写 PoseBone。

### 5. 旧路径删除

新路径达到对应能力后，直接删除旧节点、Python reference、native full-core/context、兼容 cache 与 shadow pipeline。允许迁移的只有经过新契约和 oracle 重新证明的数值规则；不保留旧资产 adapter 或运行时 fallback。

## 已决产品边界

| ID | 决策 |
|---|---|
| D-01 | 用户 Mesh 是 final proxy；Pin/attribute 按 input vertex index 映射。 |
| D-02 | 不实现 MC2 reduction/render mapping；result 与输入 vertex identity 一一对应。 |
| D-03 | Blender Mesh 动态输入唯一支持双对象 BasePose + 常驻 GN offset。 |
| D-04 | loop-domain UV seam 不自动拆点；同 vertex 多 loop UV 不一致时明确报错。 |
| D-05 | Unity packed 12/20、ushort/ulong 只保留在 raw oracle；ABI 展开为显式 checked int32 arrays。 |
| D-06 | Tier A host 为 `tools/mc2_unity_oracle`；废弃 HoClothUnity 与旧 solver均为 Tier C。 |
| D-07 | Normal/Split 只迁移共同数学语义，不复制 Unity manager/job 调度结构。 |
| D-08 | Bone connection mode 3 的内部语义必须保留；是否公开节点 surface 仍是产品决定。 |

## 提交与声明规则

1. 一次提交只关闭一个 contract/oracle/implementation slice。
2. 提交说明指出 source producer、intentional deviation 和验证层级。
3. spec、packer、dirty policy、capability、debug 和测试作为同一交付单元更新。
4. `supported` 只用于真实生产链路；仅有 fixture/spec 使用 `verified contract`，只有对象壳使用 `scaffold`。
5. 遇到不明确行为先扩展 oracle，不从旧 solver 或直觉补齐。
