# PMX 2.0 永久协议合同与端到端预演

状态：实现前冻结合同；日期：2026-07-29

## 1. 永久合同

HoTools 的 MMD 刚体来源永久只接受 **PMX 2.0**。这是产品不变量，不是首期范围，也不是临时兼容策略。

- 文件签名必须逐字节等于 `PMX `。
- 版本字段必须是 little-endian IEEE-754 `float32` 的精确位模式 `0x40000000`。
- 版本判断不得使用小数格式化、容差、取整或字符串前缀。
- 版本不匹配时，只允许读取完成固定头部并报告 `pmx20.invalid_version`；不得继续解释 payload。
- 不自动降级、不跳过未知尾部、不做部分导入，也不为其它布局预留运行分支。
- 完整文件必须按 PMX 2.0 的段落顺序解析，并在最后一条 Joint 记录后精确到达 EOF。任何尾随字节都拒绝。
- 解析、引用解析、字段转换、骨骼绑定和 spec 校验全部成功后，才允许原子提交到 PhysicsWorld。

PMX 是 `rigid_jolt` 的 source adapter，不是新的 solver。生产代码不得引入 Bullet、平行 `rigid_mmd` 后端或第二套刚体生命周期。

## 2. 协议依据与读取边界

本轮重新逐项阅读本机 PMX Editor 0.2.7.3 附带的 `Lib\PMX仕様\PMX仕様.txt`，只采用其中 PMX 2.0 的结构、字段和行为说明。研究脚本可以用本机 `mmd_tools` 交叉检查字段，但生产解析器必须独立实现，不导入或复制其 GPL 代码。

### 基本编码

| 项目 | PMX 2.0 合同 | 生产校验 |
| --- | --- | --- |
| 文件形式 | 二进制 | 不接受文本或容器猜测 |
| 字节序 | little endian | 所有整数和浮点显式指定 `<` |
| `TextBuf` | `int32 byte_length` + 原始字节 | 长度非负、不得越过剩余文件、严格解码 |
| 文本编码 | 头部值 `0` 为 UTF-16LE，`1` 为 UTF-8 | 其它值拒绝；不回退系统编码 |
| 数量 | 固定 `int32` | 非负，并通过记录数、单条最小尺寸和总字节预算检查 |
| 浮点 | IEEE-754 `float32` | 物理字段必须有限；NaN/Inf 拒绝 |

### 固定头部

固定头部共 17 字节：

```text
offset  size  value
0       4     magic = 50 4d 58 20  ("PMX ")
4       4     version bits = 00 00 00 40
8       1     global data size = 8
9       1     text encoding = 0 or 1
10      1     additional UV count = 0..4
11      1     vertex index size = 1, 2 or 4
12      1     texture index size = 1, 2 or 4
13      1     material index size = 1, 2 or 4
14      1     bone index size = 1, 2 or 4
15      1     morph index size = 1, 2 or 4
16      1     rigid index size = 1, 2 or 4
```

顶点索引按无符号宽度读取；纹理、材质、骨骼、Morph 和刚体索引按有符号宽度读取。非顶点索引中的 `-1` 是上下文相关的协议哨兵：骨骼/刚体可表示无引用，材质 Morph 中可表示全部材质。它不能先转成无符号数，也不能一律记成坏索引。

## 3. 完整结构游标预演

刚体段不是一个可从文件尾猜测的位置。解析器即使只保留物理 DTO，也必须顺序走完前面的所有可变长记录。

| 顺序 | 段落 | 必须解析的变长条件 | 物理适配器保留内容 |
| ---: | --- | --- | --- |
| 1 | 模型信息 | 四个 `TextBuf` | source 诊断所需名称 |
| 2 | 顶点 | additional UV 数量、权重类型 `0..3` 的不同尾部 | 不保留；校验权重枚举与骨骼引用 |
| 3 | 面 | 可变宽顶点索引 | 不保留；数量必须可组成三角形且索引有效 |
| 4 | 纹理 | `TextBuf` 数组 | 不保留；只推进并校验游标 |
| 5 | 材质 | Toon 共享标志决定索引宽度，固定字段后有备注文本 | 不保留；校验索引与面索引覆盖量 |
| 6 | 骨骼 | flag 决定连接、附加变换、轴、局部轴、外部父级和 IK 尾部 | 保留 index、名称、父级、变形层级和 `0x1000` 物理后变形标志 |
| 7 | Morph | 类型 `0..8` 决定 offset 布局 | 不保留；校验类型、数量和引用 |
| 8 | 表示枠 | 元素类型决定骨骼或 Morph 索引 | 不保留；校验类型与引用 |
| 9 | 刚体 | 固定字段，索引宽度来自头部 | 全量原值保留 |
| 10 | Joint | 类型必须为 `0`，索引宽度来自头部 | 全量原值保留 |
| 11 | EOF | 无记录 | 游标必须等于文件长度 |

每一次 `count * record_size`、字符串长度和可变索引读取都要先做溢出与剩余字节检查。解析器应有可配置的文件大小、记录数和文本长度上限，避免损坏输入导致无限分配。

## 4. 物理记录的精确合同

### 4.1 刚体

每条刚体记录按以下顺序读取并原样进入 `Pmx20RigidDto`：

| 字段 | 类型 | 合法域与含义 |
| --- | --- | --- |
| 日文名、英文名 | `TextBuf` x2 | 仅用于显示和诊断，不作为身份 |
| 关联骨骼 | 可变宽 signed index | `-1` 表示未绑定；其它值必须落在骨骼表内 |
| 碰撞组 | `byte` | `0..15` |
| 非碰撞组标志 | `uint16` | 置位表示忽略对应组 |
| 形状 | `byte` | `0` sphere、`1` box、`2` capsule |
| 尺寸 | `float3` | sphere 使用 `x` 半径；box 为三轴半尺寸；capsule 使用 `x` 半径和 `y` 圆柱段高度 |
| 世界位置 | `float3` | PMX 坐标基底中的模型空间位置 |
| 世界旋转 | `float3` | Euler，单位 radian |
| 质量 | `float32` | 原值保留；是否可用于目标 body type 由转换校验决定 |
| 移动衰减、旋转衰减 | `float32` x2 | 原值保留，不能未经校准直接宣称等于 Jolt damping |
| 反发、摩擦 | `float32` x2 | 原值保留并进入通用材质转换 |
| 物理模式 | `byte` | `0` 骨骼追随、`1` 动态、`2` 动态并校正骨骼位置 |

关联骨骼为 `-1` 是合法数据：mode `0` 生成 `STATIC` body；mode `1/2` 仍可生成 `DYNAMIC` body，但没有骨骼 writeback 目标。该状态进入诊断，不叫“孤儿”或“损坏”。

### 4.2 Joint

PMX 2.0 只允许 Joint 类型 `0`。每条记录按以下顺序进入 `Pmx20JointDto`：

| 字段 | 类型 | 合法域与含义 |
| --- | --- | --- |
| 日文名、英文名 | `TextBuf` x2 | 显示和诊断 |
| Joint 类型 | `byte` | 必须等于 `0`，否则整个 source 拒绝 |
| 刚体 A、B | 可变宽 signed index x2 | `-1` 表示 world endpoint；其它值必须落在刚体表内 |
| 世界位置、世界旋转 | `float3` x2 | 旋转单位 radian |
| 移动下限、上限 | `float3` x2 | 原值保留，不在 parser 中交换顺序 |
| 回转下限、上限 | `float3` x2 | 原值保留，单位 radian |
| 移动弹簧常数 | `float3` | 六自由度的前三轴源值 |
| 回转弹簧常数 | `float3` | 六自由度的后三轴源值 |

任一端点为 `-1` 都是合法的 world endpoint。恰有一端为 `-1` 时，转换层为该端创建显式 world frame；两端均为 `-1` 时，记录完整保留为可审计 no-op，不创建没有 body 的 native constraint。两种情况都不能误报成坏索引。

## 5. Canonical DTO 与身份

解析结果先进入宿主无关、不可变的 canonical DTO，不能直接创建 Blender 对象或 Jolt handle。

```text
Pmx20ModelDto
  source_id / content_hash / header
  model_names
  bones[index, names, parent_index, transform_layer, after_physics]
  rigids[index, every raw PMX field]
  joints[index, every raw PMX field]
```

`source_id` 由调用方命名空间和持久 source/instance key 组成；`content_hash` 单独表示当前 generation。body/joint 的稳定身份分别为 `source_id + pmx_index`。显示名可能为空、重复或被用户修改，永远不参与引用解析。

骨骼绑定需要在 PMX source 注册阶段生成持久映射：

```text
pmx_bone_index -> armature stable identity + pose-bone stable identity
```

不得只按显示名或运行时 pointer 匹配。映射缺失可以形成合法未绑定 body；重复、跨骨架或歧义映射必须在提交前拒绝。

## 6. 端到端预演

一次 source prepare 的完整顺序如下：

1. 读取文件元数据并计算稳定 source fingerprint；同一 fingerprint 可命中只读 DTO cache。
2. 在 17 字节固定头部完成精确门卫；失败立即返回，尚未分配任何 body/constraint。
3. 在 scratch arena 中顺序解析全部十个数据段；每条读取都受剩余字节和资源预算保护。
4. 校验字符串、枚举、有限浮点、数量、全部索引和最终 EOF。
5. 构造不可变 DTO，建立 `pmx_bone_index`、`pmx_rigid_index` 引用表。
6. 用单一冻结的坐标 profile 将 pose、尺寸、线性量和角度转换到 Blender/Jolt 约定；转换函数保持纯函数并记录源值和目标值。
7. 在临时集合中生成通用 `RigidBodySpec`、`ConstraintSpec` 和 MMD binding metadata；不触碰 live world。
8. 校验 stable slot ID 唯一性、Joint 端点、shape、motion type、limit/motor profile 和 writeback 所有权。
9. 整个 source 一次性注册为 implicit objects；任一步失败则丢弃临时集合，live world 保持不变。
10. 每帧先收集 mode `0` 的骨骼目标，再由唯一 `rigid_jolt` slot 固定步进，随后产生 body result。
11. binding resolver 把 mode `1/2` 结果转换成统一 writeback command；solver 和 adapter 都不直接写 Blender RNA。
12. reset、jump、reverse、same-frame、bake 和 dispose 继续遵守 PhysicsWorld 总合同。

该预演的关键门槛是第 6、8 步：坐标、限制轴和弹簧 motor 尚未通过 fixture 冻结前，source 可以解析并生成 DTO，但不得标记为 runtime-ready。

## 7. 错误与原子性

| 错误码 | 触发条件 | 是否允许部分提交 |
| --- | --- | --- |
| `pmx20.invalid_magic` | 签名不精确 | 否 |
| `pmx20.invalid_version` | 版本位模式不精确 | 否 |
| `pmx20.invalid_header` | header size、编码、UV 数或索引宽度非法 | 否 |
| `pmx20.truncated` | 任一字段越过 EOF | 否 |
| `pmx20.invalid_count` | 负数量、溢出或超过预算 | 否 |
| `pmx20.invalid_enum` | 权重、Morph、显示、形状、模式或 Joint 类型非法 | 否 |
| `pmx20.index_out_of_range` | 非 `-1` 引用越界 | 否 |
| `pmx20.trailing_bytes` | Joint 段后仍有数据 | 否 |
| `pmx20.binding_ambiguous` | 骨骼映射不唯一 | 否 |
| `pmx20.conversion_unfrozen` | 所需转换 profile 尚未通过校准门卫 | 否 |

所有诊断至少包含 `source_id`、文件偏移、段落、记录 index、字段名和原因；不得把原始模型内容写进日志。

## 8. 本机规模样本

`_research/mmd/pmx_inventory.py` 只用于确认完整解析路径和估算测试规模。2026-07-29 的 schema 3 结果为：

| 项目 | 数量 |
| --- | ---: |
| 完整解析并精确到 EOF 的规模样本 | 322 |
| 刚体 | 57,691 |
| Joint | 81,369 |
| 未绑定骨骼的刚体 | 533 |
| 一个 world endpoint 的 Joint | 126 |
| 两个 world endpoint 的 Joint | 863 |

样本中的 81,369 条 Joint 类型均为 `0`。这些数据只用于确定三种 shape、三种 mode、全部碰撞组、合法 world endpoint 和性能 fixture 的覆盖规模，不充当格式正确性的 oracle。

## 9. 合同出口条件

- 独立 reader 能处理两种文本编码、六类可变索引各自的 `1/2/4` 字节组合和所有 PMX 2.0 可变段落。
- 精确版本、截断、负数量、非法枚举、越界索引和尾随字节 fixture 全部在 DTO 提交前拒绝。
- 每个刚体和 Joint 原始字段都能从 debug snapshot 追溯，合法 `-1` 不被误报。
- parser 与 conversion kernel 可在无 Blender、无 Jolt 环境独立测试。
- source prepare 失败时，PhysicsWorld 中 body、constraint、binding 和 native handle 数量均不变化。
- 只有坐标、shape、limit frame 和逐轴弹簧校准门卫通过后，才进入运行时接入阶段。
