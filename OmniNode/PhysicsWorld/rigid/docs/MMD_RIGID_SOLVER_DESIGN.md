# PMX 2.0 刚体接入现有 Jolt 世界设计

状态：实现前架构冻结草案；日期：2026-07-29

关联：[PMX 2.0 永久协议合同](MMD_PMX20_PROTOCOL_CONTRACT.md)、[接纳矩阵](MMD_JOLT_ACCEPTANCE_MATRIX.md)、[PhysicsWorld 管线合同](../../../doc/PHYSICS_SIMULATION_PIPELINE_CONTRACT.md)

## 1. 架构决定

1. 生产输入永久只有 PMX 2.0，reader 使用精确头部与完整 EOF 门卫。
2. PMX 是 source，不是 solver；所有 body/constraint 最终进入唯一 `rigid_jolt` backend。
3. 不引入 Bullet，不复制一套 MMD 刚体 schema，不让 source adapter 持有 native handle。
4. parser、DTO 和 conversion kernel 宿主无关；它们在没有 Blender、没有 Jolt 时必须可测试。
5. PMX index 是文件内权威引用；运行时身份由 source identity + index 生成，名称和 pointer 不参与语义身份。
6. 合法 `-1` 保持未绑定/world 语义；不伪造对象，也不静默跳过记录。
7. 坐标、shape、衰减、limit frame 和弹簧在校准门卫通过前不得进入 active runtime。
8. source prepare 使用临时数据和原子替换；失败不能留下半套 body、constraint、binding 或 native handle。
9. solver 只产出结果，骨骼修改继续通过统一 writeback/commit 管线完成。

## 2. 分层结构

```text
PMX 2.0 bytes
    |
    v
strict pmx20 reader  --------------------  diagnostics(offset/record/field)
    |
    v
immutable canonical DTO
    |
    +--> stable bone binding table <------ evaluated armature identity
    |
    v
pure conversion kernel
    |
    v
generated RigidBodySpec / ConstraintSpec + binding metadata
    |
    v
world.implicit_objects  --atomic register--> existing rigid solver slots
    |
    v
single rigid_jolt adapter / native world
    |
    v
rigid result streams --> PMX binding resolver --> unified writeback --> Commit
```

建议把新代码收敛在 `OmniNode/PhysicsWorld/rigid/sources/pmx20/`：

```text
reader.py       # bytes -> Pmx20ModelDto；无 bpy、无 Jolt
dto.py          # frozen DTO、错误类型、source fingerprint
validate.py     # 枚举、计数、索引、有限值和 EOF 校验
coordinates.py  # PMX -> PhysicsWorld basis/units 的纯函数
convert.py      # DTO -> generated specs + conversion snapshot
source.py       # implicit source 注册、fingerprint、原子替换
binding.py      # bone target 收集与 result -> writeback command
```

这只是模块责任建议；实现时可按现有包结构合并小文件，但依赖方向不能倒置：`reader/dto/coordinates` 不得导入 `bpy`、world cache 或 native wrapper。

## 3. 数据所有权

| 数据 | 唯一所有者 | 生命周期 | 禁止行为 |
| --- | --- | --- | --- |
| PMX 原始 bytes | source/cache 层 | fingerprint 有效期 | backend 重读文件 |
| canonical DTO | PMX source cache | source fingerprint 有效期 | Blender 对象持有可变副本 |
| conversion snapshot | source prepare | 与 DTO/spec 版本一致 | UI 重新计算另一套公式 |
| generated specs | PhysicsWorld implicit source | world registration 生命周期 | adapter 私藏第二份可变 spec |
| stable bone binding | source registration | armature/source identity 有效期 | 按名称临时猜绑定 |
| Jolt handles | `rigid_jolt` adapter | solver slot 生命周期 | source/binding/UI 读取或释放 handle |
| body/constraint results | `world.exchange` result streams | step/frame 约定 | solver 直接写 PoseBone |
| writeback commands | unified writeback | 当前事务 | binding resolver 直接写 RNA |

canonical DTO 保留全部刚体和 Joint 原字段。转换后的通用 spec 不是证据源；调试或重新转换必须回到 DTO + profile，而不是反向猜测 PMX 值。

## 4. 稳定身份与引用

### 4.1 Source identity

`source_id` 由 producer namespace、持久 source key 和 instance key 组成。`content_hash` 是独立的 generation/fingerprint，只触发 cache、signature 和原子替换，不参与 slot identity。文件路径可用于显示或作为没有持久 ID 时的显式 fallback，但不能默认独占身份，因为路径可移动、同一模型可有多个实例且大小写规则依赖平台。

建议的语义 key：

```text
body simulation_order_key      = ("pmx20", source_id, "body", rigid_index)
constraint simulation_order_key = ("pmx20", source_id, "joint", joint_index)
```

运行时 `slot_id` 可以使用同样的信息编码成不透明字符串。它负责当前 world 内去重和精确引用；`simulation_order_key` 单独负责确定性排序。两者都不能退化为 Blender pointer，也不能因同一 source 的 content hash 更新而整体改名。

### 4.2 通用 spec 扩展

`RigidBodySpec` 需要支持：

- 调用方显式传入 `slot_id` 和 `simulation_order_key`；
- `obj=None`、`obj_ptr=0`、`data_ptr=0`；
- source metadata 只保存诊断所需的轻量标识，不嵌入 DTO 大对象。

`ConstraintSpec` 需要增加：

```text
target_a_slot_id: str | None
target_b_slot_id: str | None
```

Jolt adapter 先按完整 slot ID 查找 body；只有现有 Blender Object 路径没有 slot ID 时，才回退 pointer 前缀。`None` 对 PMX source 表示 world endpoint，不等于“查找失败”；任何非空 slot ID 查找失败都在调用 native 前报错，绝不能回退到 WORLD_HANDLE。

### 4.3 Implicit object

新增通用 `rigid.generated_body`，并与现有 `rigid.generated_constraint` 对称提供：

- normalize/copy；
- stable ID、signature、simulation order key；
- register；
- enabled entry 枚举；
- solver slot sync；
- stale slot prune；
- reset/dispose；
- debug snapshot。

PMX source 只生产这两种通用 implicit object，不直接调用 `JoltWorld.add_body/add_constraint`。

## 5. Reader 与 DTO 边界

reader 严格执行 [永久协议合同](MMD_PMX20_PROTOCOL_CONTRACT.md)：完整走过模型信息、顶点、面、纹理、材质、骨骼、Morph、表示枠、刚体和 Joint，并精确落在 EOF。

生产 DTO 至少包含：

```text
Pmx20HeaderDto
  encoding, additional_uv_count, six index widths, raw version bits

Pmx20BoneDto
  index, names, parent_index, transform_layer, raw_flags, after_physics

Pmx20RigidDto
  index, names, bone_index, group, non_collision_mask
  shape, size, position, rotation
  mass, move_attenuation, rotation_attenuation, bounce, friction, mode

Pmx20JointDto
  index, names, type, rigid_a_index, rigid_b_index
  position, rotation
  translation_lower, translation_upper
  rotation_lower, rotation_upper
  linear_spring, angular_spring
```

所有 tuple 使用固定长度，所有 index 先保持整数/`None`，所有 float 在 reader 边界校验 finite。DTO 构造后冻结，禁止 adapter 就地改写 limit 顺序或尺寸。

`mmd_tools` 只作为研究 oracle。它的高层 loader 允许部分截断数据返回，不能用于生产完整性门卫。

## 6. 坐标与 frame 设计

只允许一个 `Pmx20CoordinateProfile` 定义：

- PMX basis 到 PhysicsWorld basis 的正交变换 `C`；
- 模型单位到 world 单位的 `unit_scale`；
- Euler 构造顺序；
- capsule 局部轴；
- model root transform 的组合顺序。

点、方向和姿态的转换由同一 profile 提供：

```text
p_target = root * (unit_scale * C * p_pmx)
R_target = root_rotation * C * R_pmx * inverse(C)
```

实际实现使用矩阵/四元数 API，不手写分散的轴交换。shape size 只应用 basis permutation 与绝对单位缩放，不应用位置平移。

### 6.1 Joint local frames

PMX Joint 保存的是模型空间 world pose。完成 basis/root 转换后得到 `J0`，并以 body 初始 world transforms `A0/B0` 求局部 frame：

```text
frame_a = inverse(A0) * J0
frame_b = inverse(B0) * J0
```

如果恰有一端是 world endpoint，该端 frame 保持为 `J0` 的 world 表达，由通用 constraint adapter 走显式 world 分支。不得复制另一端 body，也不得用原点替代。两端都是 world endpoint 时，converted source 保留该 Joint 和 `inert_world_world` 诊断，但不生成 `ConstraintSpec` 或 native handle。

limits 和 springs 的轴都属于 Joint frame。转换 kernel 必须一起转换 frame 和轴向值，不能只 swizzle body pose。

## 7. 刚体语义

### 7.1 Shape

- sphere：`size.x` 转 Jolt radius。
- box：三轴 PMX 半尺寸经 basis permutation 后转 `shape_half_extents`，不再次除二。
- capsule：`size.x` 是 radius，`size.y` 是圆柱段全高；Jolt `half_height = size.y / 2`，再处理局部轴转换。

raw size 永远保留。非正尺寸、非有限值或转换后超出 world 合法域时拒绝 source；不替换成默认 sphere。

### 7.2 Motion mode 与骨骼

| mode | bound bone | Jolt body | frame input | writeback |
| ---: | --- | --- | --- | --- |
| `0` | 有 | `KINEMATIC` | 每帧读取已评估骨骼 pose | 无 |
| `0` | 无 | `STATIC` | 初始 transform | 无 |
| `1` | 有 | `DYNAMIC` | 仅初始化/reset | 完整 pose |
| `1` | 无 | `DYNAMIC` | 仅初始化/reset | 无，记录 unbound |
| `2` | 有 | `DYNAMIC` | 仅初始化/reset | 旋转 + 位置校正策略 |
| `2` | 无 | `DYNAMIC` | 仅初始化/reset | 无，记录 unbound |

mode `2` 不是新的 native body type。位置校正发生在 binding resolver，并使用初始 body-to-bone offset；不能在 Jolt adapter 内修改骨骼。

在 source activation/reset 时，以初始骨骼和刚体 world transforms 计算一对互逆 bind transforms：

```text
bone_to_body_bind = inverse(bone_world_0) * body_world_0
body_to_bone_bind = inverse(body_world_0) * bone_world_0

mode 0 body_target = bone_world * bone_to_body_bind
mode 1 bone_target = body_world * body_to_bone_bind
```

mode `2` 复用 `body_to_bone_bind` 的旋转关系，但位置分量按独立校正 fixture 冻结；没有通过前不能直接套用 mode `1` 的完整矩阵。

### 7.3 Collision 与材质

```text
jolt_group = pmx_group + 1
allow_mask = (~pmx_non_collision_mask) & 0xffff
```

继续使用现有双向 group filter。Joint 不隐式禁用已连接 body 的碰撞，`disable_collisions=False`；PMX group/mask 是唯一 source 碰撞关系。

mass、bounce、friction 保留原值并走现有通用合法域。move/rotation attenuation 在校准公式冻结前保持 DTO-only，不允许临时直接复制到 Jolt damping。

## 8. Spring6DOF 设计

Joint 类型 `0` 在至少有一个 body endpoint 时生成 `ConstraintSpec.constraint_type=SIX_DOF`；双 world endpoint 按前述规则保留为 no-op。hard frame/limits 与 motor springs 分两道门卫：

1. frame/limit fixture 冻结轴顺序、world endpoint、固定轴和有限轴。
2. motor fixture 冻结六个独立 spring constant 的目标空间、stiffness/damping 和时间尺度。

非零 spring 的候选实现是每轴 position motor；平移目标为 Joint frame 零位，旋转目标为 identity。候选不是已冻结事实，必须覆盖 A/B 非恒等旋转，因为 Jolt 平移和旋转 motor 的 constraint space 约定不同。

通用 `ConstraintSpec`/native 只需增加六轴独立 spring mode、stiffness 和 damping。PMX 不提供 damping 或 force cap，因此它们来自带版本的 import profile，并写入 conversion snapshot。

limit span 的处理也必须由 fixture 冻结：相等值可形成 `FIXED`，正常顺序形成 `LIMITED`；反向 span 在行为确认前阻止 runtime-ready，不能擅自交换或假设自由轴。

## 9. 骨骼绑定与变形顺序

PMX 的 bone index 是绑定源。source 注册时必须取得同一次模型导入生成的显式 index map；名称只用于诊断。绑定记录包含：

```text
source_id
pmx_bone_index
armature_stable_id
pose_bone_stable_id
body_to_bone_bind_transform
bone_to_body_bind_transform
transform_layer
after_physics
writeback_policy
```

每帧顺序：

```text
animation/morph/IK evaluated pose
  -> collect mode 0 kinematic targets
  -> fixed Jolt steps
  -> collect mode 1/2 body results
  -> sort binding commands by transform layer, PMX bone index
  -> apply post-physics bone semantics
  -> unified Commit
```

`after_physics` 和 transform layer 是写回调度依据，不是 UI 标签。与现有 VMD/IK 评估阶段的冲突必须在统一 pipeline 中解决；PMX binding resolver 不能自行触发 depsgraph 更新。

## 10. Source 事务与生命周期

source 状态机：

```text
ABSENT -> PARSED -> CONVERTED -> VALIDATED -> REGISTERED -> ACTIVE
```

- `PARSED/CONVERTED/VALIDATED` 全部发生在 scratch 数据中。
- 只有 source 集合完整校验后才替换 `world.implicit_objects` 的同一 source generation。
- replacement 先准备新 generation，再裁剪旧 generation；stable IDs 未变化的 slot 可走普通 signature update。
- backend sync 中途失败时，反向释放本次新增 handle，并保留上一份 active generation 或把新 generation 标为 error；不能混用两代 constraint endpoints。
- source fingerprint、armature identity、coordinate profile 或 binding map 变化都触发 topology/signature 更新。
- reset 重建初始 body/bone offsets；dispose 由现有 slot owner 释放 native handle。

## 11. Result、查询与 bake

generated body 的 `obj_ptr` 可以为零，因此以下路径都必须以 `slot_id` 为主键：

- `rigid_transform`、contact/sensor、constraint state；
- ray/shape query 的 hit identity 与 ignore identity；
- debug draw 和 stats；
- force/impulse/activation command target；
- bake 采样和 MMD binding resolver。

普通 Object 路径仍可附带 Blender object 引用；PMX generated body 返回 source/body index metadata。外部模块永远不读取 Jolt handle。

bake 先消费统一 rigid results，再通过同一个 binding resolver 生成 PoseBone keyframes。实时和 bake 不允许各自实现一套 mode `2` 公式。

## 12. 诊断与安全

conversion snapshot 至少记录：

```text
source_id, profile_id, dto_hash
record_kind, record_index, field
raw_value, converted_value, status, reason
```

日志不写完整模型文本、绝对路径或纹理内容。reader 对文件大小、记录数、字符串长度、累计 allocation 和递归/引用深度设置预算；错误包含字节偏移但不回显原始 payload。

测试使用合成 PMX 2.0 fixture 和 canonical JSON golden。本机模型只做只读规模 smoke，不进入仓库。生产实现不复制 `mmd_tools` 代码。

## 13. 明确不做

- 不增加第二刚体后端或 MMD 专属 native world。
- 不把 PMX raw 字段复制成与通用 spec 同名的第二套属性。
- 不按骨骼/刚体显示名解析引用。
- 不从文件尾搜索刚体或 Joint 段。
- 不容忍尾随 padding、部分 Joint 或未知枚举。
- 不在 spring 校准失败时降成 hard limit 后继续宣称完整接入。
- 不在运行链闭环前增加大面积 MMD UI；首要交付是 reader、转换、运行和诊断。
