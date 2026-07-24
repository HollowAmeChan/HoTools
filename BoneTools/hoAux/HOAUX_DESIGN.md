# HoTools HoAux 系统设计草案

状态：规划中，尚未进入实现
研究样本：`C:\Users\hhh12\Desktop\辅助骨研究.blend`
主要参考对象：`WholeLeftArm_Constraint_Driver`
目标运行环境：Blender；Unity + HoTools 等效约束组件

## 1. 系统定位

HoAux 不是普通辅助骨的“更多选项”，而是一套边界不同的绑定系统。

普通辅助骨追求：

- 使用尽可能基础、普适的约束；
- 在更多 DCC、导出链和运行环境中工作；
- 生成时处理权重，删除时可逆地归还权重；
- 因为必须可逆，生成结构和约束复杂度受到严格限制。

HoAux 追求：

- 只支持 Blender 和带 HoTools 等效组件的 Unity；
- 允许组合约束、驱动器、共享方向骨和分段响应曲线；
- 只负责骨骼、约束、驱动和运行时描述，不读取、转移或恢复权重；
- 允许用户生成后手工调整 `TRK`，再自行绑定或执行自动权重；
- 不满意时删除整段或整条流水线，再重新生成和重新绑定；
- 用若干独立模块组成一条顺序明确的肢体流水线。

两套系统必须并存，但不能共用删除语义或数据标记。

## 2. 硬性不变量

以下规则应由生成器和验证器强制执行，而不是依赖用户整理：

1. HoAux 使用独立元数据，不能设置普通辅助骨的 `isAuxBone`。
2. 所有新生成的 `DEF` 骨，`use_deform=True`。
3. 所有 `TRK` 和 `DIR` 骨，`use_deform=False`。
4. 系统不创建、不删除、不重命名、不合并任何顶点组，也不修改任何顶点权重。
5. 删除 HoAux 时不执行权重归还。
6. 每根生成骨都必须带 HoAux 元数据和稳定 `nameKey`，不能只靠显示名称识别。
7. 生成时为每根骨、每个约束、每条驱动绑定和共享 `DIR` 写入 Name Table 记录；记录允许在后续用户编辑后过期。
8. 共享 `DIR` 只生成一次；存在消费者时不能被单个模块删除。
9. 生成必须可预检、可预览，并且以一次事务提交；中途失败不能留下半套结构。
10. Source IR 必须无损记录系统生成的骨、约束、Driver、变量、参数、顺序和引用；Unity 暂不支持的能力只能标记为 unsupported，不能在导出时静默丢弃或降级。
11. Unity 首先尝试按 Source IR 一比一执行。语义归并、优化或降级是可选后端步骤，不是 Source IR 的前置条件。
12. 每次采集 Source IR 时，每个 HoAux 资源都生成“属于谁、拥有谁、使用谁、提供什么能力、要求什么能力”，从任意 Pipeline、Module 或骨都能闭包查询出本次快照的完整实现。
13. 主骨的 `use_deform` 和骨骼集合成员关系完全属于用户；HoAux 系统不检查、不修改、不恢复。
14. 每根新生成骨必须进入系统骨骼集合，并允许同时属于模块、角色、部位、侧别等多个集合；系统不得为此移除它已有的非系统集合成员关系。

研究文件中的 `use_deform` 尚未整理，存在 `DEF` 关闭、`TRK/DIR` 开启的情况。样本只作为结构和行为参考；正式生成器只整理自己新建的 DEF/TRK/DIR，不处理角色映射中的主骨。

## 3. 与普通辅助骨的数据隔离

普通系统当前使用：

- `bone.hotools_boneprops.auxBone.isAuxBone`
- `auxType`
- `sourceBones`
- 按 `(auxType, sourceBones)` 聚合列表
- 删除时根据父骨寻找权重回收目标

HoAux 系统不能复用这一标记，否则普通删除器会把 HoAux 骨当成可逆辅助骨并尝试恢复权重。

建议在 `PG_Hotools_BoneProps` 下增加独立指针：

```text
hoAux
```

建议的骨级元数据：

| 字段 | 含义 |
| --- | --- |
| `isHoAuxBone` | 是否由 HoAux 系统生成 |
| `schemaVersion` | 元数据结构版本 |
| `rigId` | 当前 HoAux Rig 的稳定 ID |
| `pipelineId` | 所属流水线实例 ID，例如一条左臂流水线 |
| `moduleId` | 所属模块实例 ID |
| `moduleType` | 模块类型，如 `FOREARM_TWIST` |
| `roleTag` | `DEF`、`TRK` 或 `DIR` |
| `part` | 部位字段 |
| `function` | 功能字段 |
| `marker` | 模块内部标记 |
| `side` | `L` 或 `R` |
| `generationId` | 本次生成事务 ID |
| `sharedKey` | 仅 `DIR` 使用的共享基础设施键 |
| `nameKey` | 在 Name Table 中稳定且唯一的语义键 |

HoAux 骨不保存 `sourceBones`。主骨只作为流水线角色映射和生成锚点，不代表权重来源。

骨级元数据用于：

- 用户改名后凭 `nameKey` 找到当前骨名，不要求回写 Name Table；
- 列表聚合；
- 分区启停；
- 删除和冲突检测；
- 检查 Name Table、系统集合成员关系与新生成骨的 `use_deform` 是否符合契约。
- 以骨上的稳定 `nameKey` 为入口，让 resolver 从 Name Table 和实际 Blender 数据重建它拥有及使用的资源。

骨上只保存不能可靠反推的身份和归属，不保存集合成员、owned/uses 或 capability 这类可从 Blender 数据重建的事实。完整资源关系由 resolver 在需要时生成；这样不会产生一组无法稳定指向、还需要持续同步的字符串列表。

## 4. Armature 级清单

骨级信息不足以描述模块顺序、共享依赖和 Unity 导出。Armature 数据上还需要一个 HoAux 清单。

建议结构：

```text
hoAuxRig
  schemaVersion
  rigId
  nameTable[]
    resourceKey
    resourceKind
    currentName
    ownerBoneKey
    pipelineId
    moduleId
  pipelines[]
    pipelineId
    presetType
    side
    enabled
    roleBindings[]
    modules[]
      moduleId
      moduleType
      order
      enabled
      state
      dependencyIds[]
      generationId
  resources[]
    resourceKey
    resourceKind
    provenance
      rigId
      pipelineId
      moduleId
      generationId
      ownerResourceKey
    owns[]
    uses[]
    usedBy[]
    providesCapabilities[]
    requiresCapabilities[]
    blenderBinding
    payload
```

`roleBindings` 只保存生成所需的主骨角色，例如：

```text
SHOULDER -> Shoulder_L
UPPER_ARM -> UpperArm_L
LOWER_ARM -> LowerArm_L
HAND -> Hand_L
```

它不是权重映射，也不参与删除时的权重处理。

清单持久保存模块实例、Name Table 和无法附着到 Blender 资源本身的生成记录。`resources[]` 是按需生成的 Source IR 视图：展示或导出时从实际骨、约束、Driver 和集合重新采集。骨级元数据仍是判断一根骨是否属于 HoAux 系统的最终依据。

### 4.1 溯源资源图

`resources[]` 是 Source IR 的主体，不是模块效果的高层摘要。首版资源类型至少包括：

```text
PIPELINE
MODULE
BONE
CONSTRAINT
DRIVER
DRIVER_VARIABLE
BONE_COLLECTION
EXPORT_ENDPOINT
```

每条资源记录都有相同的图字段：

- `provenance`：它属于哪条 Rig、Pipeline、Module、生成事务和 owner；
- `owns`：它直接持有哪些资源，例如 Bone 持有 Constraint，Driver 持有 Variable；
- `uses`：它读取、指向或依赖哪些资源；
- `usedBy`：`uses` 的反向索引，在本次快照解析时计算；
- `providesCapabilities`：它能提供的行为或数据；
- `requiresCapabilities`：Unity/Blender 后端执行它必须具备的能力；
- `blenderBinding`：当前 Blender 名称、data path、array index、约束栈序号等定位信息；
- `payload`：该类型的完整原始参数。

实际 Blender 数据、持久身份/归属和 Name Table 是作者态事实来源。Source IR 的 `payload`、正向边、`usedBy` 和 capability 都在解析时生成；writer 可以全部导出以便 Unity 快速过滤，但不能把这份快照反过来当成 Blender 作者态的指针数据库。

边关系必须带类型，不能只有一组无含义的 Key：

```text
OWNS
PARENT_OF
TARGETS
READS_TRANSFORM
DRIVES_PROPERTY
DEPENDS_ON
SHARES
EXPORTS_AS
MEMBER_OF
```

例如一条受 Driver 控制 influence 的 Copy Location 应可以追成：

```text
MODULE
  OWNS -> DEF bone
DEF bone
  OWNS -> Copy Location constraint
Copy Location constraint
  TARGETS -> TRK bone
  OWNS <- Driver
Driver
  DRIVES_PROPERTY -> constraint.influence
  OWNS -> Transform Channel variable
Transform Channel variable
  READS_TRANSFORM -> TRK bone
```

按 `moduleId` 过滤时，先取该模块直接归属的资源，再沿 `OWNS / USES / DEPENDS_ON / SHARES` 做有向闭包，就能得到一个实现涉及的全部内容。共享 DIR 会进入依赖闭包，但删除时还要检查其 `usedBy`，不能因为本模块命中就删除。

### 4.2 一比一记录示例

一条 Copy Rotation 不需要先被解释成“半角”“扭转”或“体积保持”，直接记录它在 Blender 中是什么：

```text
resourceKey: ARM.L.WRIST_VOLUME.TRK.X1.COPY_ROTATION
resourceKind: CONSTRAINT
provenance:
  pipelineId: ARM.L
  moduleId: WRIST_VOLUME.L
  ownerResourceKey: ARM.L.WRIST_VOLUME.TRK.X1
uses:
  - relation: TARGETS
    resourceKey: ARM.L.ROTATION_HALF.DIR.HAND
requiresCapabilities:
  - CONSTRAINT:COPY_ROTATION
  - SPACE:LOCAL
  - SPACE:LOCAL_OWNER_ORIENT
payload:
  blenderType: COPY_ROTATION
  stackIndex: 0
  targetSpace: LOCAL_OWNER_ORIENT
  ownerSpace: LOCAL
  influence: 1.0
  useX: true
  useY: true
  useZ: true
  mixMode: REPLACE
```

从 owner 骨的 `nameKey` 查询时，resolver 先找到当前骨，再枚举它当前实际拥有的约束和相关 Driver，并从实际 target/Variable 重建目标 DIR 引用。闭包查询消费本次资源图，不要求骨 PropertyGroup 持有字符串引用列表。

### 4.3 能力指向

能力标签描述“执行这条原始记录需要什么”，不描述推测出来的肌肉或关节效果。示例：

```text
CONSTRAINT:COPY_ROTATION
CONSTRAINT:COPY_LOCATION
CONSTRAINT:STRETCH_TO
SPACE:LOCAL
SPACE:LOCAL_WITH_PARENT
SPACE:LOCAL_OWNER_ORIENT
TARGET_POINT:TAIL
DRIVER:TRANSFORM_CHANNEL
DRIVER:SCRIPTED_EXPRESSION
DRIVER_TARGET:LOCAL_SPACE
STRETCH:SWING_Y
STRETCH:NO_VOLUME
ORGANIZATION:BONE_COLLECTION
ORGANIZATION:NESTED_COLLECTION
ORGANIZATION:MULTI_COLLECTION_MEMBERSHIP
```

Unity importer 提供自己的 capability set。解析时逐条比较 `requiresCapabilities`：全部满足即可一比一建立运行记录；缺失时报告具体 resourceKey、模块和缺少的能力。即使后端不支持，Source IR 中的 payload 和引用仍保留，方便后续迭代补能力。

`requiresCapabilities` 默认由 `resourceKind + payload + uses` 推导，不要求每个模块作者手写。模块只在存在无法从字段判断的运行时要求时追加声明。骨的聚合 capability 只存在于解析结果和 Source IR，不写入骨 PropertyGroup。

## 5. Name Table 与默认显示名称

骨名是可变的显示信息，不是系统主键。模块管理、删除、分区关闭、DIR 复用和 Unity 导出都必须先解析稳定 Key，再通过 Name Table 得到当前 Blender 名称。

建议的 Name Table 条目：

| 字段 | 含义 |
| --- | --- |
| `resourceKey` | Rig 内的记录 Key；Bone/Collection 使用稳定 Key，Constraint/Driver 的生成记录不承诺跨任意用户编辑仍绑定同一实例 |
| `resourceKind` | `PIPELINE`、`MODULE`、`BONE`、`BONE_COLLECTION`、`CONSTRAINT`、`DRIVER`、`DRIVER_VARIABLE` 或 `EXPORT_ENDPOINT` |
| `currentName` | 当前 Blender 骨名或约束名 |
| `ownerBoneKey` | 约束/驱动所属骨；骨条目为空 |
| `pipelineId` | 所属流水线 |
| `moduleId` | 所属模块；共享 DIR 可为空或指向 infrastructure |
| `roleTag` | 骨资源的 `DEF/TRK/DIR` 语义 |

稳定 Key 可以使用层级式语义，不受显示名称格式限制，例如：

```text
ARM.L.WRIST_VOLUME.DEF.X1
ARM.L.UPPER_ARM_SLIDE.TRK.OUT.1
ARM.L.ROTATION_HALF.DIR.LOWER_ARM
```

### 5.1 默认显示名称

为了让用户直接看懂，生成器仍提供推荐格式：

```text
<TAG>_<PART>_<FUNCTION>_<MARKER>_<SIDE>
```

这只是默认 Formatter，不是解析契约。字段可以由模块提供不同模板，用户也可以在生成后改名。系统不得通过拆分下划线来判断骨骼身份或功能。

研究样本中的名称都可以原样进入表，包括 `TRK_UpperArm_Slide1_OUT_L`；是否显示为 `Slide1` 或 `Slide_OUT1` 只是命名模板选择，不影响模块语义。

### 5.2 角色语义

`DEF/TRK/DIR` 保留为结构化 `roleTag`，并决定行为：

| roleTag | 含义 | `use_deform` | 用户是否可调整 |
| --- | --- | --- | --- |
| `DEF` | 最终参与蒙皮形变的骨 | 开 | 通常不直接调整 |
| `TRK` | 轨道、方向或幅度调节骨 | 关 | 可以调整位置/方向来塑形 |
| `DIR` | 跨模块共享的方向与信号基础设施 | 关 | 不建议直接调整 |

即使用户把 `DEF_...` 改成完全不同的名字，deform 规则仍按元数据中的 `roleTag=DEF` 执行。主骨不登记为 HoAux，其 `use_deform` 保持用户当前设置，HoAux 系统不把它作为生成或导出合法性条件。

### 5.3 系统骨骼集合

普通 aux 的 `BoneUtils.assign_bones_to_collection()` 会先从全部旧集合移除再加入单一目标集合。HoAux 系统需要多集合过滤，不能复用该破坏性行为，应提供独立接口：

```text
ensure_system_collection(collectionKey, preferredName, parentCollectionKey)
add_bone_membership(boneKey, collectionKey)
remove_bone_membership(boneKey, collectionKey)
sync_bone_memberships(boneKey)
prune_empty_system_collections()
```

这些接口只增减 HoAux 系统拥有的集合成员关系，不触碰用户集合、普通 aux 集合或其他插件集合。

建议的折叠嵌套结构：

```text
HoAux
  Pipelines
    Left Arm
      01 Wrist Volume
      02 Forearm Bulge
      03 Forearm Twist
      04 Elbow Volume
      05 Upper Arm Longitudinal Bulge
      06 Upper Arm Twist
      07 Upper Arm Muscle Slide
      08 Shoulder Volume
  Infrastructure
    Shared DIR
  Filters
    Role
      DEF
      TRK
      DIR
    Part
      Shoulder
      Upper Arm
      Elbow
      Forearm
      Wrist
    Side
      L
      R
```

集合层级负责折叠浏览，骨的多集合成员关系为正交过滤提供索引。例如 `DEF_Elbow_Volume_Z1_L` 同时属于：

```text
Pipelines / Left Arm / 04 Elbow Volume
Filters / Role / DEF
Filters / Part / Elbow
Filters / Side / L
```

Blender 的原生骨集合可见性是并集：一根骨只要属于任意可见集合就仍会显示，因此多集合本身不能直接表达 `Role=DEF AND Part=Elbow`。规则如下：

- `Pipelines` 与 `Infrastructure` 是主要结构集合，承担常规折叠和原生可见性；
- `Filters` 下的索引集合默认关闭可见性，主要供 HoAux 面板查询、选择和列表过滤；
- 多条件过滤由 HoAux 面板扫描骨的实际 `bone.collections` 并求交集，不能依赖同时打开多个 Blender 集合；
- 若提供“视图聚焦”，只临时修改 HoAux 生成骨的 hide 状态，并保存/恢复之前状态，不影响主骨和非 HoAux 骨。

共享 DIR 不加入任何单一模块集合，只进入 `Infrastructure / Shared DIR`、`Filters / Role / DIR`、对应 Part 和 Side。模块通过资源图的 `SHARES/usedBy` 找到 DIR。

每个系统集合都是 `BONE_COLLECTION` ResourceRecord，保存稳定 `collectionKey`、父集合 Key、当前显示名和成员骨 Key。显示名冲突时由 Name Allocator 分配其他名称；不能接管同名但不属于本系统的集合。

上面的英文集合名只是默认显示模板，不是固定解析格式；系统身份和父子关系仍由 collectionKey 与资源图决定。

删除或重建时，先通过 Collection Registry 解析本系统集合，再扫描骨的实际集合成员并只解除命中的系统集合。清理集合必须自底向上，并且只有集合没有成员、没有子集合且仍由本系统拥有时才允许删除。

### 5.4 按需定位

Name Table 是生成记录和名称定位提示，不是要求与 Blender 实时一致的镜像数据库：

1. Bone 优先通过自身 `nameKey` 扫描，直接读取当前名称；
2. BoneCollection 优先通过自身 `hoaux_key` 扫描，直接读取当前名称和实际成员；
3. Constraint、Driver 和 Variable 在采集 Source IR 时枚举 owner 当前实际数据，不依赖旧缓存重建对象；
4. Name Table 中保存的名称只作为首次定位和诊断信息，名称不一致时不自动回写；
5. 当前字符串引用无法解析时，Source IR 保留原始字符串并标记 `UNRESOLVED`；
6. 新生成资源发生显示名称冲突时，Name Allocator 选择可用名称并记录本次实际结果。

Constraint 不支持 IDProperty，因此不承诺它在用户任意改名、重排后的跨采集稳定 identity。Source IR 可以用 `ownerBoneKey + 当前 stackIndex + type` 为本次快照分配 resourceKey。Driver/FCurve 同样按当前 data path、array index 和栈引用建立本次快照；旧 Name Table 条目不强行绑定到已经变化的对象。

左右镜像使用模块语义、Side 字段和 Name Table 生成另一侧资源，不对完整显示名称做无约束字符串替换。

### 5.5 统一管理接口

所有模块只能通过统一 Name Registry 访问资源，不能自行拼骨名后调用 `bones.get()`：

```text
allocate(resourceKey, preferredName)
bind(resourceKey, actualResource)
resolve_bone(resourceKey)
resolve_collection(resourceKey)
snapshot_scope(pipelineId/moduleId)
release_scope(pipelineId/moduleId)
```

这样模块只维护自己的 Key 表和默认显示名表。用户改名后的当前事实由 `snapshot_scope()` 直接读取，不通过后台同步表来维持。

### 5.6 改名边界

HoAux 不注册为了保持一致性的 rename 监听、msgbus 同步、depsgraph 扫描或自动修复器，也不在打开面板时强制审计整个 Rig。

持久数据只保留确实无法省略的名称：骨的生成名称、Name Table 显示名、约束生成名称、Driver 原始 data path、集合显示名。它们允许过期。

需要展示、导出或删除时，只读取当前实际状态：

- 骨和系统集合可以分别通过 `nameKey/hoaux_key` 找回改名后的对象；
- Constraint、Driver 和 Variable 按当前 owner 的实际内容重新采集，不尝试证明它们仍是生成时的同一个实例；
- Blender 已经同步更新的名称引用直接使用当前值；
- Blender 没有同步、当前已经断裂的字符串引用原样保留为 `UNRESOLVED`，HoAux 不替用户改写；
- 删除只处理身份明确的 HoAux 骨、系统集合，以及当前能明确定位的 FCurve；不确定项保留并列入结果。

因此改名不会触发维护成本；代价是 Constraint/Driver 的 resourceKey 只保证在一次 Source IR 快照内稳定，而不是承诺跨任意用户编辑保持不变。

## 6. 研究样本结论

`WholeLeftArm_Constraint_Driver` 包含：

- 47 根骨；
- 4 根主骨：Shoulder、UpperArm、LowerArm、Hand；
- 22 根 `DEF`；
- 18 根 `TRK`；
- 3 根共享 `DIR`；
- 55 个约束；
- 20 条驱动器。

约束构成：

| 类型 | 数量 |
| --- | ---: |
| Copy Rotation | 29 |
| Copy Location | 20 |
| Stretch To | 6 |

驱动曲线只有两种语义：

```text
abs(angle * 2 / pi)
clamp(abs(angle * 2 / pi) - 0.5) * 2
```

对应：

1. `ABS_0_TO_90`：绝对旋转从 0° 到 90° 映射为 0 到 1；
2. `ABS_45_TO_90`：0° 到 45° 保持 0，45° 到 90° 映射为 0 到 1。

Source IR 保存原始表达式，同时可以标记它匹配 `ABS_0_TO_90` 或 `ABS_45_TO_90`。Unity 首版可优先执行这两个已识别实现；以后增加安全表达式解释器时仍使用同一份 Driver 原始记录。

### 6.1 共享 DIR

样本包含三根半旋转方向骨：

| DIR | 输入主骨 | 当前消费者 |
| --- | --- | --- |
| `DIR_UpperArm_Rotation_HALF_L` | UpperArm | Shoulder Volume |
| `DIR_LowerArm_Rotation_HALF_L` | LowerArm | UpperArm Slide、Elbow Volume、Raise 系列 |
| `DIR_Hand_Rotation_HALF_L` | Hand | Wrist Volume |

这些骨说明 `DIR` 是跨模块基础设施，不能归某个单一功能模块私有所有。

### 6.2 Twist

UpperArm 和 LowerArm 都各有三段 Twist：

- Copy Rotation 使用 `LOCAL -> LOCAL_OWNER_ORIENT`；
- 三段 influence 约为 `0.10 / 0.45 / 0.80`；
- 每段同时用 Stretch To 指向末端主骨；
- Stretch To 使用 `NO_VOLUME` 和 `SWING_Y`，主要用于维持链长和抑制翻转。

### 6.3 Volume

Shoulder 和 Wrist 各使用四方向的 `TRK + DEF` 组合：

- `TRK` 跟随半旋转 `DIR`；
- `DEF` 复制对应方向，并 Copy Location 到可调 `TRK`；
- Copy Location influence 由相应局部旋转轴的 `ABS_0_TO_90` 曲线驱动。

Elbow Volume 就是“手肘关节保持”模块，不再拆出第二套“肘关节体积保持”。它使用两个 Z 方向的 `TRK + DEF`：

```text
TRK_Elbow_Volume_Z0_L
TRK_Elbow_Volume_Z1_L
DEF_Elbow_Volume_Z0_L
DEF_Elbow_Volume_Z1_L
```

其中两个 `DEF` 分别跟随对应 `TRK` 的旋转和位置，Copy Location influence 由对应 TRK 的局部 Z 旋转驱动。这一组共同负责手肘弯曲时的关节体积保持。

### 6.4 Raise 与 Slide

- Raise 使用 UP/DOWN 两个方向，通过 `ABS_45_TO_90` 在大角度弯曲时启用；
- UpperArm Slide 使用 IN/OUT 轨道和两段响应：第一段从 0° 开始，第二段从 45° 开始；
- `TRK` 的位置是用户塑形入口，驱动只控制响应幅度。

## 7. HoAux 模块模型

每个功能必须实现统一的声明式 Module Spec，而不是直接在 Operator 中散写骨骼和约束。Module Spec 的首要产物是完整资源记录，不是高层效果摘要。

建议概念结构：

```text
ModuleSpec
  type
  version
  requiredRoles[]
  dependencies[]
  sharedDirections[]
  boneSpecs[]
  constraintSpecs[]
  driverSpecs[]
  driverVariableSpecs[]
  previewSpecs[]
```

其中：

- `BoneSpec` 描述 `nameKey`、默认名称模板、父级、几何生成规则、角色和显示样式；
- `ConstraintSpec` 按约束类型保存 owner、target、栈顺序、空间、轴、混合模式和全部使用参数；
- `DriverSpec` 保存被驱动属性、array index、类型、表达式和变量顺序；
- `DriverVariableSpec` 保存变量类型、target、bone target、transform type/space、rotation mode 等原始字段；
- `PreviewSpec` 描述预览线、点、颜色和可调 TRK 位置。

生成器创建 Blender 数据的同时写入同构 ResourceRecord。Unity 可以直接消费这些记录一比一求值；如果以后需要把固定组合优化成更低成本组件，再在不修改 Source IR 的前提下增加可选解析层。

## 8. DIR 共享基础设施

DIR 是本系统最需要严格处理的部分。

每个 DIR 必须有稳定 `sharedKey`，例如：

```text
ROTATION_HALF:UPPER_ARM:L
ROTATION_HALF:LOWER_ARM:L
ROTATION_HALF:HAND:L
```

复用规则：

1. 先按 `sharedKey` 查找已有 DIR；
2. 校验目标主骨、父级、空间、轴、影响值和版本签名；
3. 签名完全一致才允许复用；
4. 相同显示名但无 HoAux 元数据时不接管，Name Allocator 可以分配其他名称；
5. 同 `sharedKey` 但签名不同，停止生成并报告迁移需求；
6. 删除模块后重新计算消费者，不使用脆弱的手写引用计数；
7. 只有没有任何模块依赖时才删除 DIR；
8. 单模块关闭时共享 DIR 保持运行；整条流水线关闭后才可连同无消费者 DIR 一起停用。

DIR 必须进入 `Infrastructure / Shared DIR` 及对应过滤集合，并且强制 `use_deform=False`。

## 9. 流水线工作流

推荐用户流程：

1. 选择目标 Armature；
2. 选择侧别和流水线预设；
3. 映射主骨角色；
4. 运行预检；
5. 预览当前模块或整条流水线；
6. 按顺序逐段生成，或一次生成全部已启用模块；
7. 用户调整 `TRK` 位置和方向；
8. 用户自行绑定、自动权重或手调权重；
9. 可按模块或流水线关闭效果；
10. 不满意时删除模块或全部 HoAux，重新生成后重新绑定。

系统不维护“已经绑定”的状态，因为权重完全属于用户工作流。

## 10. 预览模式

预览必须与正式生成分离。

### 10.1 预览原则

- 使用 Viewport Draw Handler 绘制计划骨骼、方向和作用范围；
- 不创建临时骨、不创建约束、不创建驱动；
- 参数变化时只重算 Preview Model；
- `DEF`、`TRK`、`DIR` 使用不同颜色和线型；
- 清楚标出共享 DIR 和将被复用的现有基础设施；
- `resourceKey` 冲突、轴退化和依赖缺失直接在预览状态中显示为错误；显示名称冲突则展示 Name Allocator 计划采用的实际名称；
- 切换对象、退出面板、加载文件或取消时必须可靠关闭预览。

### 10.2 生成事务

点击生成后：

1. 再次执行与预览相同的预检；
2. 固化全部 `resourceKey`、实际显示名称和依赖；
3. 创建或复用 DIR；
4. 创建 TRK、DEF；
5. 创建或复用嵌套骨骼集合，并为新骨追加多集合成员关系；
6. 创建约束；
7. 创建驱动；
8. 写入骨级元数据和 Armature 清单；
9. 验证目标、驱动路径、新骨 `use_deform` 与集合索引；
10. 任一步失败，按事务日志删除本次新建内容并撤销本次系统集合成员变化。

“不可逆”只表示不恢复用户权重，不表示生成过程可以留下半套数据。

## 11. UI 规划

在骨骼工具分页中增加与“辅助骨”同级的“HoAux”页。

建议布局：

### 11.1 顶部上下文

- 当前 Armature；
- 流水线预设；
- L/R 侧别；
- 主骨角色映射；
- 预检状态。

### 11.2 流水线工具栏

- 预览全部；
- 生成下一段；
- 生成全部；
- 整体启用/关闭；
- 删除整条流水线。

### 11.3 模块列表

每个模块一行，显示：

- 顺序；
- 模块名称；
- `未生成 / 已生成 / 已关闭 / 缺失 / 冲突` 状态；
- 启用开关；
- 预览；
- 生成或重建；
- 删除。

展开模块后显示生成骨列表、DIR 依赖和关键参数。共享 DIR 放在独立折叠区，不混入普通模块删除按钮。

### 11.4 总览分组

HoAux 总览按以下层级组织：

```text
Pipeline
  Module
    DEF
    TRK
    DIR dependency
```

不要按普通辅助骨的 `(auxType, sourceBones)` 聚合。

## 12. 分区关闭

关闭模块时：

1. mute 该模块拥有的约束；
2. mute 该模块拥有的 Driver FCurve；
3. 不改变骨骼位置、父级、权重和 `use_deform`；
4. 不关闭仍被其他启用模块使用的共享 DIR；
5. UI 和清单记录模块 `enabled=False`。

关闭整条流水线时，对全部模块执行相同操作，并关闭只服务于该流水线且已经没有启用消费者的 DIR。

重新启用时只恢复系统拥有的数据，不修改用户额外添加的约束。

约束本身不支持可靠的 IDProperty 标记，因此由 Name Table 的 `resourceKey -> ownerBoneKey + currentName + type` 记录所有权。约束名可以使用可读默认模板，但不能只按 `Copy Location` 这类显示名称删除。

## 13. 删除语义

支持：

- 删除单个模块；
- 删除整条流水线；
- 删除当前 Armature 上全部 HoAux。

删除顺序：

1. 找出依赖模块和共享 DIR；
2. 拒绝删除仍被其他模块依赖的基础设施；
3. 删除模块拥有的 Driver FCurve；
4. 删除模块拥有的约束；
5. 逆父子顺序删除 HoAux；
6. 删除无消费者的 DIR；
7. 只解除系统集合成员关系，并自底向上清理无成员、无子级的系统 Bone Collection；
8. 清理清单。

明确不做：

- 不扫描 Mesh；
- 不修改顶点权重；
- 不归还权重；
- 不删除顶点组；
- 不替用户重新绑定。

如果 HoAux 骨下挂有非 HoAux 骨，应阻止删除并列出阻断项，避免意外破坏用户骨架。这里的安全检查与权重可逆无关，仍然需要保留。

删除骨后，同名顶点组可能仍留在 Mesh 上；之后重新生成同名 `DEF` 时，Blender 会再次让这些顶点组影响新骨。这属于 Blender 的正常行为，系统不接管，用户需要重新绑定或自行清理。

## 14. 首版整臂流水线

用户定义的顺序作为产品流水线主序：

| 顺序 | 模块类型 | 显示名 | 研究样本映射 | 主要依赖 |
| ---: | --- | --- | --- | --- |
| 1 | `WRIST_VOLUME` | 手腕体积保持 | `Wrist_Volume` | `DIR_Hand_Rotation_HALF` |
| 2 | `FOREARM_BULGE` | 小臂膨胀 | `LowerArm_Raise` | `DIR_LowerArm_Rotation_HALF` |
| 3 | `FOREARM_TWIST` | 小臂扭转 | `LowerArm_Twist` | LowerArm、Hand |
| 4 | `ELBOW_VOLUME` | 手肘关节保持 | `Elbow_Volume` | `DIR_LowerArm_Rotation_HALF` |
| 5 | `UPPER_ARM_LONGITUDINAL_BULGE` | 大臂纵向膨胀 | `UpperArm_Raise` | `DIR_LowerArm_Rotation_HALF` |
| 6 | `UPPER_ARM_TWIST` | 大臂扭转 | `UpperArm_Twist` | UpperArm、LowerArm |
| 7 | `UPPER_ARM_MUSCLE_SLIDE` | 大臂肌肉滑移 | `UpperArm_Slide` | `DIR_LowerArm_Rotation_HALF` |
| 8 | `SHOULDER_VOLUME` | 肩体积保持 | `Shoulder_Volume` | `DIR_UpperArm_Rotation_HALF` |

`Wrist Volume` 和 `UpperArm Twist` 都属于默认整臂流水线，不作为可选候选。“手肘关节保持”与 `Elbow Volume` 是同一个模块。上表顺序目前按“手腕到肩部、同部位基础形变先于肌肉滑移”暂定。

## 15. Blender 与 Unity 的共同 Source IR

HoAux 系统需要独立于现有普通辅助骨 `ConstraintAnalyzer` 的导出路径。

坐标系可行性、Unity 矩阵定义、尾端子骨策略和预演门槛见 [UNITY_IR_FEASIBILITY.md](./UNITY_IR_FEASIBILITY.md)。结论是 Unity Transform 能提供所需矩阵，但必须由中央求值器缓存 bind pose 并计算相对绑定态空间，不能直接映射到 Unity 原生 Constraint 或 `localEulerAngles`。

首版 Source IR 至少逐项保存：

```text
Bone
BoneCollection
CopyRotation
CopyLocation
StretchTo
Driver
DriverVariable
ExportEndpoint
```

Unity 导出数据需要携带：

- schema 和模块版本；
- Pipeline/Module ID；
- owner/target 的骨路径；
- owner/target 的稳定 resourceKey 和导出 Transform 路径；
- 原始 constraint/driver 类型、栈顺序、全部使用参数和空间枚举；
- Driver data path、array index、表达式、变量和 transform channel 配置；
- bind pose、方向换轴和旋转分解所需数据；
- 静态 influence；
- 原始表达式以及可选的已识别曲线标签；
- Stretch To 参数；
- 骨骼集合层级、多集合成员关系和 DIR 共享关系；
- 模块求值顺序。

Unity 组件必须以相同顺序求值，并对以下姿态建立黄金测试：

```text
-90° / -45° / 0° / 45° / 90°
```

还要增加多轴组合旋转、左右镜像、非单位 Armature Transform 和父骨旋转场景。误差应比较最终骨骼局部/世界矩阵，而不仅比较单个参数。

研究样本的旋转不建立额外类型层级。DIR、Twist、TRK/DEF 都按实际 Copy Rotation 逐条记录 source、owner、space、influence、axes、mix mode 和栈顺序。Unity 共用同一空间换算器并按记录一比一求值。

## 16. 操作时最低检查

生成前只检查本次操作能否执行：

- 目标对象是可编辑 Armature；
- 主骨角色齐全且属于同一 Armature；
- 侧别与主骨角色映射一致；
- 骨长和所需方向轴不退化；
- Name Allocator 能为本次新资源分配显示名称；
- 被复用的 DIR 身份明确；
- 模块依赖满足；
- 当前模式和 View Layer 支持编辑。

生成事务结束时只确认本次新建结果：

- 本次新骨已写身份/归属元数据；
- 本次新建 `DEF=True`、`TRK/DIR=False`；
- 本次新骨已追加到计划集合，且没有移除原有集合成员；
- 本次 API 调用创建的约束和 Driver 成功返回；
- 任一步失败时只回滚本次事务。

事务结束后不持续监测这些状态，也不因为用户修改、删除、重排或改名而自动恢复。Source IR 采集遇到断裂关系时输出 `UNRESOLVED`；这属于当前 Rig 的事实，不触发 Blender 数据修复。

## 17. 建议模块目录

```text
BoneTools/hoAux/
  __init__.py
  panel.py
  properties.py
  name_registry.py
  collection_registry.py
  manifest.py
  preview.py
  transaction.py
  shared_direction.py
  module_spec.py
  modules/
    wrist_volume.py
    forearm_bulge.py
    forearm_twist.py
    elbow_volume.py
    upper_arm_bulge.py
    upper_arm_twist.py
    upper_arm_slide.py
    shoulder_volume.py
  pipelines/
    whole_arm.py
  ir/
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
  tests/
```

普通 `auxBone` 和 `hoAux` 不互相导入具体生成器。可共享的只有无状态数学、Name Allocator 和 Blender 上下文工具。
HoAux 导出 IR 的 model、schema、写入、解析、验证、资源图、能力表和空间解析都归 `hoAux/ir` 所有；`Exporter` 只能调用其公开入口，不得另存一份 HoAux schema 或 mapper。

## 18. 实施阶段

### Phase 0：冻结契约

- 确认八段流水线的最终顺序；
- 冻结 Name Table、稳定 Key 和默认名称模板的边界；
- 冻结 `DEF/TRK/DIR` 的 deform 规则；
- 冻结系统集合树、collectionKey 与多集合成员规则；
- 冻结 Source IR ResourceRecord、图边和 capability 命名；
- 完成 writer/parser 往返样例，确认 Blender 原始字段不会丢失；
- 先通过 `LOCAL`、`LOCAL_WITH_PARENT`、owner orientation correction 和 Driver 局部角的合成矩阵预演。

### Phase 1：系统骨架

- HoAux 骨 PropertyGroup；
- Armature 清单与 Source IR 快照模型；
- Name Table 与 Name Allocator；
- Collection Registry、嵌套集合和 additive 多集合成员 API；
- 按需 Source IR 快照与资源闭包查询；
- capability 推导、聚合和 unsupported 报告；
- HoAux 总览；
- 分区启停；
- 无权重删除；
- 暂不实现具体生成模块。

### Phase 2：预览与事务

- 通用 Preview Model；
- Draw Handler 生命周期；
- 生成预检；
- 事务创建和失败回滚。

### Phase 3：DIR 与信号

- Shared DIR 注册表；
- `ABS_0_TO_90`；
- `ABS_45_TO_90`；
- Blender Driver 后端；
- 单元和场景测试。

### Phase 4：逐模块实现

建议先实现 Shoulder Volume。它能一次验证：

- 共享 DIR；
- TRK 可调轨道；
- DEF 输出；
- Copy Rotation + Copy Location；
- Driver influence；
- 分区启停；
- 删除。

随后实现 Twist，用于补齐 Stretch To 和分段权重。

### Phase 5：整臂流水线

- 八段顺序；
- 单段和全量预览；
- 生成下一段；
- 全量生成；
- 依赖状态显示；
- 左右镜像。

### Phase 6：Unity 后端

未来阶段，当前 HoAux 目标只完成接口、空间预演和测试数据，不修改 Unity 工程。

- Unity 读取 Source IR 与 Export Binding Overlay；
- 每个 Animator/skeleton root 一个 `HoAuxRig`，骨上不挂 HoAux 运行时组件；
- 中央等效组件、直接 Transform Binding Table 与虚拟 pose buffer；
- 按资源引用图和约束栈顺序一比一求值；
- 导出专用尾端子骨与 Export Binding Table；
- Blender/Unity 矩阵黄金测试。

## 19. 首版验收标准

1. 生成和删除全过程对 Mesh、顶点组和权重零写入。
2. 新生成的 `DEF` 开启 deform，`TRK/DIR` 关闭 deform；主骨 `use_deform` 保持用户设置不变。
3. 所有生成骨可在 HoAux 列表中按 Pipeline/Module 查看。
4. 任意模块可以独立关闭和恢复。
5. 删除一个模块不会误删共享 DIR 或其他模块数据。
6. 删除整条流水线时移除身份明确的系统骨、集合和 FCurve；无法确认的对象保留并在结果中列出。
7. 预览取消不产生任何 Blender 数据块变化。
8. 同名非系统骨存在时不自动接管，由 Name Allocator 分配其他显示名称。
9. 左右流水线可以同时存在且互不影响。
10. Blender 和 Unity 在规定测试姿态下输出一致。
11. IR writer/parser 往返一致；未知 schema 或缺失结构主键被拒绝，当前断裂引用保留为 `UNRESOLVED`，尚未实现的能力保留原始 payload 并明确报告。
12. 从任意 Module 或 HoAux 骨执行资源闭包查询，都能找到它拥有、使用和依赖的全部骨、约束、Driver、变量与共享资源。
13. 每根新骨进入模块集合和对应过滤集合；生成、重建、删除均不移除用户已有集合成员关系。
14. Unity 每个骨架只需要一个 `HoAuxRig`；骨和尾端锚点保持纯 Transform，一条 Source IR 记录对应一条中央运行记录。

## 20. 实现前待确认

1. 八段默认流水线的最终先后顺序。
2. 用户调整 TRK 后，是否需要提供“保存为预设”，还是重建时直接丢弃调整。
3. Unity 首版只接受样例使用的 `NO_VOLUME + SWING_Y` Stretch/Aim 组合；其他组合待单独验证后扩展 schema。
4. HoAux 约束的默认显示名称需要多强的可读性；系统身份始终由 Name Table 决定。
