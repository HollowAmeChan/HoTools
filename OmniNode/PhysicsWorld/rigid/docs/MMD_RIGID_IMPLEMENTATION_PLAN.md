# PMX 2.0 刚体接入实施计划

状态：协议预演后重新排期；日期：2026-07-29

依据：[永久协议合同](MMD_PMX20_PROTOCOL_CONTRACT.md)、[接纳矩阵](MMD_JOLT_ACCEPTANCE_MATRIX.md)、[架构设计](MMD_RIGID_SOLVER_DESIGN.md)

## 1. 重新评估结果

旧方案把通用 generated body、PMX adapter、Jolt Spring6DOF 和骨骼写回并行推进，风险太高：一旦坐标或二进制游标错误，问题会在 Blender、Python spec 和 native Jolt 三层之间来回漂移。

新顺序先完成 **独立 PMX 2.0 reader + 纯转换 kernel**，用 canonical fixture 冻结语义；随后补通用 generated body/slot 基础设施；最后接 Jolt 和骨骼。这样每一阶段都有单一 oracle，也不会为了 MMD 临时绕过 PhysicsWorld 合同。

关键路径：

```text
P0 contract/fixtures
  -> P1 strict reader
  -> P2 pure conversion
  -> P3 generic generated-body infrastructure
  -> P4 bodies + hard Spring6DOF runtime
  -> P5 per-axis spring calibration/runtime
  -> P6 bone binding/writeback
  -> P7 lifecycle, bake, diagnostics, performance, minimal UI
```

任何阶段未达到出口条件，都不提前开始依赖它的运行态工作。

## 2. 预计改动面

新增建议：

```text
OmniNode/PhysicsWorld/rigid/sources/pmx20/
  __init__.py
  dto.py
  reader.py
  validate.py
  coordinates.py
  convert.py
  source.py
  binding.py

OmniNode/PhysicsWorld/rigid/test/fixtures/pmx20/
  binaries/       # 手工/生成的最小 PMX 2.0 二进制
  canonical/      # DTO 和 conversion JSON golden
  runtime/        # 进入现有 fixture runner 的通用 spec
```

通用代码预计修改：

```text
rigid/specs.py
rigid/names.py
rigid/declaration.py
rigid/implicit_objects.py
rigid/scope_sync.py
rigid/solver.py
rigid/backends/jolt.py
rigid/results.py
rigid/queries.py
rigid/debug.py
rigid/test/schema.py
rigid/test/fixture_runtime.py
native Jolt SixDOF settings/ABI/wrapper files
unified PhysicsWorld writeback integration
```

正式落位前以 `rg` 确认实际所有调用点；不得只改构造器而遗漏 result、query、command、debug、prune 或 dispose 路径。

## 3. P0：合同和 fixture 骨架

目标：把协议预演转成可执行测试输入，不碰运行时代码。

交付：

1. 冻结精确 `PMX ` magic、版本位模式、17 字节头部和 EOF 规则。
2. 建立最小 PMX 2.0 binary builder，仅供测试生成确定字节；builder 与 reader 不共享解析实现。
3. 定义 frozen DTO schema 和 JSON canonicalizer。
4. 为 source error 定义稳定错误码、offset/section/record/field 位置结构。
5. 定义 reader 资源预算：最大文件、字符串、段落 count 和累计 allocation。

fixture 最小集合：

```text
HDR-001  UTF-16LE + 全部 1-byte indexes
HDR-002  UTF-8 + 混合 1/2/4-byte indexes
WALK-001 每个可变段至少一条记录
BODY-001 sphere/box/capsule + mode 0/1/2
JOINT-001 type 0 + 六轴 limits/springs
WORLD-001 rigid bone -1 + Joint A/B -1
BAD-001  magic/version/header 单字节破坏
BAD-002  每个段落边界截断
BAD-003  负 count、越界 index、非法 enum、NaN/Inf
BAD-004  Joint 后尾随字节
```

出口条件：fixture builder 的十六进制布局由协议表人工复核；reader 尚不存在时，fixture 自身也能通过独立 offset 清单审计。

## 4. P1：独立严格 reader

目标：`bytes -> Pmx20ModelDto`，完全不依赖 Blender、Jolt 或 `mmd_tools`。

实现任务：

1. 实现 bounds-checked `BinaryReader`：little-endian scalar、可变宽 signed/unsigned index、`TextBuf`。
2. 固定头部使用原始四字节比较版本，不使用 float tolerance 或格式化结果。
3. 顺序实现模型信息、顶点、面、纹理、材质、骨骼、Morph、表示枠、刚体、Joint。
4. 只保留物理需要的数据，但所有 skipped 段也完整验证可变分支和引用。
5. count 在任何分配前做非负、乘法溢出、剩余字节和预算检查。
6. 物理 float 校验 finite；枚举和索引在完整 table count 已知后做交叉验证。
7. 最终 `reader.offset == len(bytes)`，否则 `pmx20.trailing_bytes`。
8. 错误不可返回 partial DTO。

测试：

- P0 全部 binary fixtures；
- 两种文本编码；
- 六类 index 的 1/2/4 字节边界值与 `-1`；
- 骨骼 flags、四种权重布局、九种 Morph 布局和表示枠两种元素；
- 每个 variable tail 的逐字节 truncation；
- count/fuzz budget，保证失败时间和内存有上界；
- 同一 bytes 重复解析得到相同 DTO hash。

出口条件：无 `bpy` 环境运行全部测试；有效 fixture 精确到 EOF，所有坏 fixture 在预期 offset/field 拒绝；coverage 覆盖每种变长分支。

## 5. P2：纯转换 kernel

目标：`Pmx20ModelDto + coordinate profile + bone map -> ConvertedPmx20Source`，仍不创建 live world 或 native handle。

实现任务：

1. 定义 `Pmx20CoordinateProfile`：basis、unit scale、Euler 顺序、capsule 轴和 profile ID。
2. 实现 point/vector/rotation/transform/shape 的单一转换模块与 round-trip 辅助断言。
3. 生成 body stable ID、constraint stable ID 和独立 simulation order key。
4. 实现 group/mask、三种 shape、mode 0/1/2 和合法 unbound policy。
5. 由初始 body worlds 与 Joint world pose 推导 local frames；单个 world endpoint 生成 world frame，双 world endpoint 保留为 no-op。
6. 保留 limit 和 spring 原值；只把已经冻结的 hard-limit 语义写入 converted record。
7. 建立显式 `pmx_bone_index -> stable bone identity` 输入合同；名称不参与匹配。
8. 生成逐字段 conversion snapshot。

纯函数测试：

- 三个基轴、正负位置、非恒等 root transform；
- sphere radius、box half-extents、capsule radius/half-height 与局部轴；
- 16 组和关键 mask 真值表；
- mode/bound/unbound 的六种组合；
- body-body、world-body、body-world Joint frames，以及 world-world no-op；
- A/B 非恒等旋转和非零 Joint Euler；
- stable ID 不受显示名、对象 pointer、content hash generation 或 scope 枚举顺序影响；不同 instance key 必须隔离；
- 转换重复执行得到字节相同 canonical JSON。

出口条件：除 attenuation、反向 limit span 和 nonzero spring 外，所有 PMX 2.0 物理字段均有 `PRESERVED` 或已测试的 `DERIVED` 结果；校准字段明确阻止 runtime-ready。

## 6. P3：通用 generated body 与稳定端点

目标：让没有 Blender Object 的刚体成为 PhysicsWorld 一等公民，同时保持现有 Object 路径行为不变。

实现任务：

1. `RigidBodySpec` 接受显式 `slot_id`/`simulation_order_key` 和 `obj=None`；旧构造调用保持兼容。
2. `ConstraintSpec` 增加 `target_a_slot_id/target_b_slot_id`；禁止既有 pointer 与显式 ID 指向不同 body。
3. Jolt adapter 优先按精确 slot ID 解析，单个 `None` 支持 world endpoint，旧 Object 路径保留 pointer 前缀 fallback；双 `None` 不进入 adapter，非空 ID 查找失败必须报错。
4. 新增 `rigid.generated_body` implicit object 的 normalize/register/sync/prune/dispose 全链路。
5. generated body 与 generated constraint 使用同一个 source generation 和拓扑签名。
6. result、contact、query、command、debug、stats、bake target 全部审计 `obj_ptr=0`。
7. backend sync 失败时释放本次新增 handles，不污染上一 generation。

测试：

- 无 Object 的 sphere body 创建、step、query、command、remove；
- 两个 generated body 通过显式 slot ID 约束；
- generated 与 Object body 混合约束；
- world endpoint；
- pointer fallback 原有 fixture 全回归；
- source signature 更新、stale prune、reset、dispose、失败回滚；
- 插入顺序打乱后 simulation trace 不变。

出口条件：普通 Jolt 全套 adapter/native/Blender fixture 不回归；generated body 在所有 result/query/lifecycle 路径中不需要伪造 Object。

## 7. P4：刚体与 hard Spring6DOF 运行闭环

目标：把 P2 已冻结的 converted source 原子注册到现有 Jolt world，先完成源衰减和弹簧均为零的完整闭环。

实现任务：

1. `source.py` 按 fingerprint cache DTO/converted records，并批量注册 generated bodies/constraints。
2. 三种 shape、质量、材质、group/mask、mode motion type 进入现有 `RigidBodySpec`。
3. Joint local frames 与 hard limits 进入现有 `SIX_DOF`。
4. `disable_collisions=False`，只用 PMX group/mask 决定碰撞。
5. 源 attenuation 精确为零时映射为 Jolt zero damping；非零 source 在 P5 前保持 parsed/converted，但禁止 active。
6. 非零 spring source 同样在 P5 前禁止 active；不得用 hard limit 或 profile default 代替。
7. conversion snapshot 能从 debug/result 定位到 source/body/joint index。

运行测试：

- 三种 shape 落地、AABB/debug geometry 与纯转换 golden 一致；
- mode `0` 先用合成 kinematic target，mode `1/2` 先验证 body result；
- 16x16 group/mask 关键真值；
- fixed/limited axes 与 world endpoints；
- PMX generated body 和普通 Object body 同 world 碰撞、约束、query；
- source prepare 失败不改变 body/constraint/handle counts。

出口条件：零 attenuation、零 spring fixture 完成 `PMX bytes -> DTO -> specs -> Jolt -> result`；没有第二 solver 或 MMD native 分支。

## 8. P5：逐轴弹簧与衰减校准

目标：用实测冻结 PMX spring/attenuation 到 Jolt 的 profile，并补最小通用 SixDOF 能力。

### 8.1 先做实验，不先改 ABI

建立可观测 native fixture，逐轴记录：

- initial error、position/orientation target；
- motor state、spring mode、stiffness、damping、cap；
- 每 substep 位移/角度、速度、constraint impulse；
- A/B frame、质量和惯量。

覆盖 identity/nonidentity frames、A/B 交换、world endpoint、六轴不同常数、质量比、固定步长和 substep 变化。同期用单 body 衰减 fixture 冻结 move/rotation attenuation 转换。

### 8.2 通用实现

实验通过后：

1. 复用已有 `six_dof_motor_states[6]`，增加六轴独立 spring mode/stiffness/damping。
2. Python wrapper、ABI struct/hash、C++ native 和 debug snapshot 同步扩展。
3. 现有共享 motor 字段继续作为普通约束 fallback；新数组有值时优先。
4. PMX profile 使用 `StiffnessAndDamping`，damping/cap 明确来自 profile。
5. nonzero source spring 开启对应 position motor，零值保持 OFF。
6. 冻结反向 limit span 的含义；证据不足则继续阻止相关 source active。

出口条件：六轴不同 spring 不被折叠；非恒等 frame 恢复方向正确；旧 `SIX_DOF-*` golden 的非相关行为不变；profile ID 与参数进入 snapshot/replay。

## 9. P6：骨骼输入与 writeback

目标：完成 mode `0/1/2` 与统一 PhysicsWorld 写回闭环。

实现任务：

1. PMX/armature 导入或 source 注册流程提供持久 bone index map；重复名称不影响身份。
2. 保存互逆的 bone-to-body/body-to-bone bind transforms、transform layer 和 `after_physics` 标志。
3. step 前批量读取 mode `0` 的 evaluated pose，生成 kinematic targets；避免每 body 重复 RNA lookup。
4. step 后 mode `1` 生成完整 bone pose command。
5. mode `2` 复用同一 body result，只在 resolver 应用旋转 + 位置校正公式。
6. writeback command 按 transform layer、PMX bone index 和 source ID 稳定排序。
7. 明确与动画、Morph、IK、depsgraph 和 Commit 的时序；resolver 不直接更新 scene。
8. reset/jump/reverse 重建 bind offsets 和 kinematic history。

测试：

- bound/unbound mode `0/1/2`；
- 父子骨骼、不同 transform layer 和 `after_physics`；
- 非零 body-to-bone offset；
- 多 body 指向同 bone 的冲突策略；
- source/armature 替换导致 binding 失效；
- same-frame、`dt=0`、jump/back、reset、replay；
- solver 阶段无 Blender 写操作。

出口条件：实时运行和 bake 共用一个 binding resolver；所有写入通过统一 commit；无名称猜测和 pointer 持久身份。

## 10. P7：产品化收尾

目标：补齐可诊断性、bake、性能、稳定性和最小 UI。

交付：

- source 状态、profile ID、body/joint index、raw/converted 值和 error location 的 debug snapshot；
- 原子 reload、disable、remove、reset、dispose；
- 实时/bake 一致性测试；
- 100/500/1000/5000 body+joint 的 parse、convert、register、step、bone I/O 和内存 P50/P95；
- 真实本机资源只读 smoke，失败按 source 汇总，不写回模型；
- 最小折叠 UI：source、绑定状态、mode/writeback、profile 和诊断；不重复 mass/shape/material/group 等通用属性；
- 文档、错误码、测试 manifest 和性能阈值更新。

优化顺序：先测量 parser、conversion、spec registration、Jolt step、bone target collection、writeback；只优化实测热点。PMX 与普通刚体共享一个 world，禁止为性能另建 broadphase/job system。

出口条件：完整 E2E、生命周期和性能门卫通过后才显示“PMX 2.0 物理 ready”；UI 不得成为隐藏失败的替代品。

## 11. 测试矩阵

| ID 族 | 层级 | 核心断言 |
| --- | --- | --- |
| `PMX20-HDR-*` | reader | magic、精确版本、编码、UV/index widths、EOF |
| `PMX20-WALK-*` | reader | 全段落变长分支、truncation、count/index budget |
| `PMX20-BODY-*` | conversion | shape、物理标量、mode、unbound bone |
| `PMX20-FILTER-*` | conversion/native | group + mask 双向真值表 |
| `PMX20-FRAME-*` | conversion/native | root/body/joint frames、world endpoints、limits |
| `PMX20-SPRING-*` | native | 六轴 stiffness/damping、target space、substep |
| `PMX20-BIND-*` | Blender integration | mode `0/1/2`、排序、IK/物理后阶段、writeback |
| `PMX20-MIX-*` | PhysicsWorld | generated/Object 混合碰撞、约束、query、debug |
| `PMX20-LIFE-*` | PhysicsWorld | fingerprint、reload、rollback、reset、dispose、bake |
| `PMX20-PERF-*` | benchmark | parse/convert/step/bone I/O/内存阈值 |

二进制 fixture 与 canonical golden 可提交；真实模型、纹理和本机绝对路径不得进入测试依赖。

## 12. 风险与停止条件

| 风险 | 处理 | 停止条件 |
| --- | --- | --- |
| reader 游标错位 | 完整段落 fixture + 每边界 truncation | 任一 partial DTO 返回 |
| GPL 实现污染 | 独立 reader，代码审查记录来源 | 发现复制实现即停止合并 |
| box/capsule 尺寸或轴错误 | AABB/debug geometry 合成 fixture | extent 重复除二或轴随姿态漂移 |
| attenuation 公式不稳定 | 固定步长/多 substep 衰减实验 | profile 不能重放 |
| Spring motor 空间错误 | 非恒等 A/B frame 与交换端点 | 恢复方向错误或轴串扰 |
| 共享 motor 参数丢轴差异 | 通用六轴数组 + native snapshot | 六个源值在 ABI 后不再独立 |
| pointer 身份泄漏 | `obj_ptr=0` 全链路 fixture | query/result/dispose 仍要求 Object |
| bone 绑定歧义 | index map + stable armature identity | 只能靠名字解析 |
| source 更新半提交 | generation transaction + handle rollback | 新旧 endpoints 混用 |
| mode `2` 与 IK 冲突 | pipeline 时序与统一 writeback | resolver 直接写 RNA/触发 depsgraph |

## 13. 完成定义

- 仅精确 PMX 2.0 能形成 DTO，整个文件通过后才可提交。
- 全部刚体和 Joint 原字段可审计；合法 `-1` 语义完整保留。
- 三种 shape、三种 mode、group/mask、world endpoint、hard limits 和逐轴 springs 均有分层 fixture。
- PMX source 和普通刚体共享现有 Jolt world、result、query、debug、bake、reset 和 dispose。
- mode `0/1/2` 通过稳定 bone index map 和统一 writeback 工作。
- 无 Bullet、无 `rigid_mmd` solver、无 MMD 专属 native handle 或重复通用字段。
- 所有校准 profile 可版本化、可重放、可从诊断定位；不存在静默降级。
