# HoAux Unity 空间与 IR 可行性

状态：设计验证
研究样本：`辅助骨研究.blend / WholeLeftArm_Constraint_Driver`
目标：确认 Unity 自定义求值器能否复现 HoAux 的约束空间与驱动信号

## 1. 结论

Unity 的 `Transform.localToWorldMatrix`、父级 `worldToLocalMatrix` 和运行时缓存的绑定态矩阵，足以计算本系统需要的空间。风险不在于 Unity 取不到变换，而在于不能把 Blender 空间枚举直接翻译成 `localRotation`、`localEulerAngles` 或 Unity 原生 Constraint。

首版采用以下边界：

1. Unity 使用一个中央 HoAux 求值器，在 Animator 写入主骨后统一计算全部 DIR/TRK/DEF。
2. 求值器缓存导入后的 bind local 与 bind skeleton matrix；所有空间计算使用矩阵或四元数。
3. Source IR 一比一记录 Blender 中由系统生成的骨、约束、Driver、变量、参数、顺序和引用。DIR、Twist 等用途只作为归属信息，不建立额外的旋转类型层级。
4. `head_tail=1` 统一在导出副本中物化为目标骨的尾端子骨；Unity 只解析 Transform，不推测骨长。
5. 驱动角不读取 Unity `localEulerAngles`。先计算相对绑定态旋转，再按 IR 指定的分解方式和角度范围取轴值。
6. 首版拒绝非均匀层级缩放、剪切以及未验证的 Blender 继承缩放模式；这些不是 Transform 取值能力问题，而是 TRS 写回无法无损表达仿射剪切。

因此，这套系统可以进入实现，但必须先通过本文件第 9 节的空间黄金测试。未通过测试的空间组合仍可被 Source IR 完整保存，但 Unity capability validator 必须标记为 unsupported，不能静默降级。

## 2. 样例实际使用范围

`WholeLeftArm_Constraint_Driver` 有 55 个约束和 20 条 Driver：

| 类型 | 数量 | 实际空间 |
| --- | ---: | --- |
| Copy Location | 20 | `WORLD -> WORLD`，全部使用 target tail |
| Copy Rotation | 24 | `LOCAL_OWNER_ORIENT -> LOCAL` |
| Copy Rotation | 2 | `LOCAL_WITH_PARENT -> LOCAL` |
| Copy Rotation | 1 | `LOCAL -> LOCAL` |
| Copy Rotation | 2 | `WORLD -> WORLD` |
| Stretch To | 6 | `WORLD -> WORLD` |

20 条 Driver 全部是 Transform Channel 变量并读取 `LOCAL_SPACE`：4 条取 `ROT_X`，16 条取 `ROT_Z`。变量表达式只有 `ABS_0_TO_90` 与 `ABS_45_TO_90` 两类响应曲线。

旋转关系按 Blender 中的实际记录逐条保存：

```text
CopyRotation
  ownerKey
  sourceKey
  sourceSpace
  ownerSpace
  influence
  axes
  mixMode
```

DIR 读取关节下段骨的自由度旋转，`influence=0.5`，形成半角状态。Twist 直接读取 Hand 或 LowerArm 的旋转，以 `0.10 / 0.45 / 0.80` 写入各段 DEF。其余体积、滑移骨从 DIR 复制或映射旋转。它们使用同一个矩阵空间实现，但在 IR 中保留各自真实 source 和 influence，不强行合并成共同的“关节旋转信号”。

## 3. 空间的中立矩阵定义

全部矩阵先在同一个 skeleton/root 坐标系内计算。令：

```text
B_i = 骨 i 的绑定态 skeleton matrix
P_i = 骨 i 在当前求值阶段的 skeleton matrix
B_p = 父骨绑定态 skeleton matrix；无父骨时为单位矩阵
P_p = 父骨当前 skeleton matrix；无父骨时为单位矩阵

B_i_local = inverse(B_p) * B_i
P_i_local = inverse(P_p) * P_i
```

Blender 4.5 合成双骨测试确认：

```text
LOCAL_DELTA(i) = inverse(B_i_local) * P_i_local
LOCAL_WITH_PARENT_DELTA(i) = inverse(B_i) * P_i
```

前者排除父骨当前运动和静置姿态，对应本样例 Driver `LOCAL_SPACE` 所需的相对绑定态局部量；后者保留父骨引入的当前运动，对应骨约束 `LOCAL_WITH_PARENT`。

不能用下面的简化替代：

```text
Transform.localRotation
Transform.localEulerAngles
inverse(parent.rotation) * child.rotation
```

这些写法没有显式移除 bind local，并且 Euler 顺序、角度回绕和 FBX 预旋转都不受我们的契约控制。

## 4. Owner Orientation 换轴

`LOCAL_OWNER_ORIENT` 的目标是：目标骨和 owner 的静置方向不同时，让目标局部旋转在 owner 静置坐标轴中产生相同的全局运动。

只考虑旋转，令 `R(B_i)` 表示从 bind skeleton matrix 提取并正交化的旋转：

```text
C_owner_target = inverse(R(B_owner)) * R(B_target)
Q_owner = C_owner_target * Q_target * inverse(C_owner_target)
```

其中 `Q_target` 是目标的 `LOCAL_DELTA` 旋转。这个共轭换轴可以由 Unity `Quaternion` 实现，但修正量必须来自导入后的 bind pose，不能只靠 Blender 骨名或假设两根骨轴一致。

写回 owner 的 LOCAL 结果时：

```text
P_owner_local = B_owner_local * D_owner
P_owner = P_parent * P_owner_local
```

IR 的 `CopyRotation.sourceSpace=LOCAL_OWNER_ORIENT` 使用上述精确定义。Blender writer 写成对应约束设置；Unity runtime 用 bind orientation correction 实现。`sourceSpace` 与 `ownerSpace` 使用各自独立的枚举，parser 必须拒绝把只属于 target/source 的 `LOCAL_OWNER_ORIENT` 填到 owner space。

这不是对 Copy Rotation 的高层抽象，而是 Blender 记录的一比一数据模型；Unity 的空间函数负责解释相同枚举。

## 5. DIR 半角与 Twist

DIR 只是一次普通 Copy Rotation。求值器按该条记录的 source space 读取关节下段骨旋转：

```text
D_source = read_rotation(sourceKey, sourceSpace)
D_dir = blend(identity, orient_for_owner(D_source), influence=0.5)
```

其中 blend 必须采用 Blender Copy Rotation influence 的等效规则并由黄金测试冻结。未冻结前不能用 Unity `Quaternion.Euler(euler * 0.5)`，因为多轴姿态下两者不等价。

Twist 同样只是 Copy Rotation，但 source 仍是 Hand/LowerArm，influence 分别为 `0.10 / 0.45 / 0.80`。DIR 和 Twist 共用 `read_rotation()`、owner orientation correction 与 blend 算法，不共享一份人为构造的中间信号。

## 6. Driver 局部角信号

Blender 对 Transform Channel 变量 `LOCAL_SPACE` 的说明是：包含约束结果，但不包含 parenting/rest pose。Unity 一比一执行这条 Driver 记录时：

1. 先完成该信号源依赖的 DIR/TRK 约束；
2. 从当前虚拟 pose buffer 计算 `LOCAL_DELTA(source)`；
3. HoAux 生成的 Transform Variable 固定使用 `QUATERNION`，读取 X/Z 四元数分量并用 `2 * asin(component)` 还原对应有符号角；外部或旧数据仍按 Source IR 原始 `rotation_mode` 解释；
4. 规范到 `[-pi, pi]`；
5. 应用命名曲线 `ABS_0_TO_90` 或 `ABS_45_TO_90`；
6. 将结果绑定到后续 Position/Rotation 操作的 influence。

Source IR 必须保留 FCurve、Driver 和 Variable 的实际字段：

```text
Driver
  drivenResourceKey
  dataPath
  arrayIndex
  driverType
  expression
  useSelf
  variableKeys[]

DriverVariable
  name
  variableType
  targetResourceKey
  boneTargetKey
  transformType
  transformSpace
  rotationMode

analysis (optional)
  resolvedRotationMode
  recognizedExpression
```

研究样例 Driver 使用 `AUTO`，但 HoAux 正式生成器固定写入 `QUATERNION`。因此 `ABS_0_TO_90` 的生成表达式先以 `asin` 把四元数分量还原为角度，再做归一化。Source IR 始终保存实际原始值；Unity 一比一执行时按该值选择分解路径。`recognizedExpression` 可以标记已识别曲线供快速执行，但原始 `expression` 始终保留。

如果以后需要 quaternion swing/twist angle，应作为新的 Driver Variable 类型或后端优化记录；不能覆盖当前 Transform Channel 原始记录。

## 7. 尾端点策略

Blender `head_tail=1` 指目标骨尾端；FBX/Unity 的一根骨通常只有头部 Transform。

首版固定使用导出专用尾端子骨：

```text
target bone
  EXPORT_TAIL_<resourceKey>
```

规则：

- 子骨位于目标骨 tail，零旋转、单位缩放；
- `use_deform=False`，不写 HoAux 业务元数据；
- 只存在于导出副本，并登记到 Export Binding Table；
- Copy Location IR 直接绑定此 Transform；
- 相同 target tail 只生成一个共享锚点；
- 锚点在 MCH/骨轴清理完成后按最终导出骨架生成。

这样 Unity runtime 不需要骨长、Blender Y 轴或 FBX 单位换算知识。

## 8. Unity 中央求值器

### 8.1 业内组织方式比较

常见方案不是纯二选一，而是把“描述放置”和“求值调度”分开：

| 方案 | 典型形式 | 优点 | 对 HoAux 的问题 |
| --- | --- | --- | --- |
| 每骨/每约束组件 | Unity 内置 Constraint 直接挂在受约束 GameObject；Animation Rigging 的 Constraint 组件放在 Rig 子层级 | Inspector 直观，单项容易手调、复制和做 Prefab override | 组件数量大；跨骨 Driver 和多个约束仍需要全局顺序；模块启停、批处理和导入更新分散 |
| 整骨架图/中控 | Unreal Control Rig 图；自定义 Playable/Animation Job | 顺序、依赖、缓存和批量求值集中；容易优化 | 默认 Inspector 不够直观，需要专门编辑器和调试视图 |
| 分布描述、集中调度 | Unity Animation Rigging：Constraint 分散描述，Rig 收集为有序 IAnimationJob，RigBuilder 在 Animator 根构建 PlayableGraph | 同时兼顾编辑体验与统一求值 | 适合在 Unity 内手工搭 Rig；HoAux 的作者态在 Blender，重复生成大量 Unity 组件收益较低 |

Unity Animation Rigging 官方工作流明确把 `RigBuilder` 放在 Animator 根，`Rig` 收集子层级 Constraint 并生成有序 IAnimationJob，在 Animator 正常求值后执行。Unity 内置 Constraint 则是挂在单个 GameObject 上的组件。Unreal Control Rig 采用集中 Rig Graph/Component。三者共同点是严肃的角色 Rig 最终都有中央图或调度器，而不是依赖每根骨的 MonoBehaviour 自治顺序。

### 8.2 HoAux 决定

HoAux 采用：

```text
每个 Animator / skeleton root 一个 HoAuxRig
每条 Blender Constraint/Driver 对应一条运行记录
骨骼和尾端锚点只保留 Transform，不挂 HoAux 运行时组件
```

“一比一”指 Source IR 与运行记录一比一，不指 MonoBehaviour 数量一比一。

建议 Unity 资源结构：

```text
Character Root
  Animator
  HoAuxRig
    HoAuxRigAsset / imported Source IR
    BindingTable: resourceKey -> serialized Transform reference
    ModuleStates
    RuntimeDiagnostics
  Skeleton
    bones and export tail anchors (Transform only)
```

`HoAuxRigAsset` 保存不可变导入记录；角色实例上的 `HoAuxRig` 保存该骨架的直接 Transform 引用。Unity 序列化对象引用能承受 GameObject 改名，运行时不需要反复按路径查找。

不创建 `HoAuxBone` 运行时组件。选中骨骼时的约束、Driver、来源和消费者由 HoAux 自定义 Inspector/Overlay 反查中控数据；这能保留每骨调试体验而不污染骨层级。

### 8.3 求值与迁移

一个 `HoAuxRig` 持有整条流水线并在 Animator 之后执行：

```text
Animator output
  -> capture main-bone pose
  -> CopyRotation operations that produce DIR
  -> CopyRotation operations that produce TRK/DEF/Twist
  -> Driver/Variable records that read TRK local angles and write constraint properties
  -> CopyLocation operations on DEF
  -> Stretch/Aim operations
  -> commit virtual pose buffer to Transforms
```

运行时按 Source IR 中的 constraint stack order 和 Driver 引用图逐条求值。实现上仍先在 pose buffer 中计算 skeleton matrices，最后按父子顺序提交，避免同一帧的读取结果依赖组件排列或 Unity Transform 刷新时机。

Unity 初始化时必须缓存：

```text
skeletonRoot
resourceKey -> Transform
parentIndex
bindLocalMatrix
bindSkeletonMatrix
bindLocalRotation
bindSkeletonRotation
evaluationOrder
```

每帧可从 `localToWorldMatrix` 读 Animator 输入，再转为 skeleton space。骨架根对象的平移、旋转和统一缩放会被 root 变换消掉。

实施分两步：

1. 首版使用单个 `HoAuxRig.LateUpdate()` 和显式 Script Execution Order，优先完成空间黄金测试和调试工具。
2. 数据和求值器稳定后，将同一连续 operation/binding 数组迁入 `AnimationScriptPlayable + IAnimationJob`，在 Animator PlayableGraph 内获得确定时机和更好的批处理能力。

不采用“首版每骨组件、以后再合并”的路线，因为那会让序列化结构、模块启停和求值顺序都需要二次迁移。当前 Unity 6.3 工程已包含内置 animation module，但未安装 Animation Rigging package；HoAux 借鉴其集中调度模式，不增加该包依赖。

参考：

- Unity Animation Rigging 1.3 Rigging Workflow：RigBuilder、Rig、Constraint 与 IAnimationJob 的组织和顺序；
- Unity Constraint components：单 GameObject 组件模式；
- Unity `IAnimationJob`：Playable 内动画求值接口；
- Unreal Engine Control Rig：集中 Rig Graph/Component 模式。

## 9. 预演与准入门槛

### Gate A：IR 编解码

- writer -> JSON -> parser 往返完全一致；
- 未知 schema version 和缺失 resourceKey 必须拒绝；
- Blender 当前已断裂的引用保留原始值并标记 `UNRESOLVED`，parser 不负责修复；
- schema 合法但 Unity 尚未实现的约束/Driver 能力必须保留 payload，并报告 unsupported capability；
- JSON 字段顺序不影响解析，浮点值保持规定精度。

### Gate B：Blender/Python 空间预演

建立合成双骨与三骨骨架，覆盖：

- owner/target 静置轴不同；
- 父骨独立旋转；
- `LOCAL`、`LOCAL_WITH_PARENT` 和 owner orientation correction；
- `-90/-45/0/45/90` 度；
- X/Z 驱动轴、多轴组合和角度跨越 180 度；
- 左右镜像。

Python reference solver 与 Blender 最终 pose matrix 比较。

### Gate C：FBX/Unity 导入预演

导出最小骨架和对应 IR，在 Unity 中记录每个测试帧的 local/skeleton matrix，与 Blender 基准逐骨比较：

```text
position <= 1e-4 m
rotation <= 0.1 degree
scale <= 1e-4
```

此阶段必须覆盖 FBX 轴转换、Armature 根变换、尾端子骨和 Animator 后求值时机。

### Gate D：完整手臂

最后才运行 `WholeLeftArm_Constraint_Driver` 全臂测试。按模块逐个启用，先 DIR，再 Volume/Slide，最后 Twist/Stretch；任一模块失败都能定位到具体 resourceKey、原始记录和 capability。

若 Gate C 中 `LOCAL_WITH_PARENT` 或 quaternion signal 无法稳定达标，先把对应 capability 标记为 unsupported，再修正 Unity 空间实现或增加显式导出代理骨。Source IR 原始记录不改写，也不允许增加骨名特判。

## 10. IR 所有权与目录

HoAux 的 IR model、写入、解析、验证和空间编译全部放在新文件夹内：

```text
BoneTools/hoAux/ir/
  __init__.py
  model.py
  schema.py
  writer.py
  parser.py
  validator.py
  graph.py
  capabilities.py
  blender_reader.py
  resolver.py
  export_binding.py
  coordinate.py
  reference_solver.py
  tests/
    test_codec.py
    test_coordinate_spaces.py
    test_sample_arm.py
```

职责：

| 文件 | 职责 |
| --- | --- |
| `model.py` | 纯 Python IR dataclass/enum，不导入 `bpy` |
| `schema.py` | schema version、字段常量和兼容规则 |
| `writer.py` | model 写为 dict/JSON |
| `parser.py` | dict/JSON 严格解析为 model |
| `validator.py` | JSON/schema 结构检查；允许业务引用为 `UNRESOLVED` |
| `graph.py` | owns/uses/usedBy 边、作用域过滤和依赖闭包 |
| `capabilities.py` | 从原始记录计算所需能力，并与 Unity capability set 对照 |
| `blender_reader.py` | 从 HoAux 清单/ModuleSpec 捕获一比一 Source IR |
| `resolver.py` | 解析 Name Table、data path、栈顺序和 Driver 属性引用，不做强制语义降级 |
| `export_binding.py` | 处理 Name Table、MCH 重定向、尾端子骨与 Unity 路径 |
| `coordinate.py` | bind/current matrix 和坐标系换算 |
| `reference_solver.py` | 与 Unity 共用算法定义的 Python 预演器 |

`Exporter/BoneConstraintExporter.py` 只负责普通 aux 与 MCH 的中立 Rig 约束 IR。HoAux 仍只能通过 `hoAux.ir` 的公开 facade 导出；普通 IR 导出器不能持有 HoAux schema、writer、parser 或 capability 定义，两套系统也不能互相推造身份字段。

Source IR 是导出时的完整事实快照；Blender 作者态不持久保存骨集合成员、owned/uses 或 capability 字符串列表。导出时 resolver 从稳定 Key、Name Table 和实际 Blender 数据采集这些关系，不监测、不修复也不回写 Blender；validator 只检查 JSON/schema 结构，Unity importer 再根据 capability set 决定哪些记录可以执行。

## 11. 与当前普通 aux 导出的关系

当前普通 aux 导出由 `auxBone.isAuxBone` 识别 owner，并保留该 owner 上指向同骨架的原始约束、空间、轴和类型专用参数。它不再把 Fan/Twist 转成 Unity 组件，也不再执行 world/world 或 Twist Y 轴降级；这些决策属于导入预览和落地策略。

另外，现有 FBX 流程会生成 MCH、清理主骨静置方向，并重定向 constraint subtarget 与 driver bone target。HoAux IR 不能在这之后重新猜测原始 Blender 语义。

HoAux 导出顺序固定为：

```text
1. 从 HoAux manifest/ModuleSpec 读取一比一 Source IR 资源图
2. 在导出副本执行 MCH 与骨轴预处理
3. 根据 Name Table 建立独立的 Export Binding Overlay
4. 物化共享尾端子骨
5. 记录最终导入契约需要的资源路径
6. 写出版本化 Source IR + Export Binding Overlay
7. 导出 FBX
```

Blender 原始资源图和最终导出 Transform 绑定必须分层保存，避免 MCH 重定向破坏 Driver/约束的原始含义。Unity 可以直接逐条执行 Source IR；可选优化结果放在独立派生区，不能替代源记录。
