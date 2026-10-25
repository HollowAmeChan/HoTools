# HoTools Rig 约束中立 IR 契约

本文档定义 Blender 导出器输出的 Rig 约束中间表示。该 IR 只描述 Blender 作者态和 FBX 临时导出态中实际存在的骨、标记、约束及引用，不负责选择 Unity 组件，不负责执行 VRC 兼容降级，也不把 Blender 约束提前翻译成最终运行时方案。

IR 的固定标识为：

```text
schema = hotools.rig-constraint-ir
schemaVersion = 3
```

版本 3 增加常用约束直通、独立 Aim 旋转语义和绑定上下文。当前 Unity 端同时读取中立 IR v2/v3，v2 不自动重解释 unknown；旧 Unity 映射 JSON 仍不兼容，不做字段猜测。具体新增字段、生成工具属性与后端范围见 [IR v3](../IR_V3.md)。

旁路清单版本固定为 `3.0`，约束文件条目的 `kind` 固定为
`rigConstraintIR`。不保留旧 `constraints` 条目或旧字段兼容层。

## MCH 流程

`bone.hotools_boneprops.generateMCH` 是骨级 MCH 意图的唯一事实来源。启用 FBX 导出器的 MCH 预处理后，勾选的主骨执行以下临时变换：

1. 在清零主骨前复制 `head`、`tail` 和 `roll`，创建 `MCH_<主骨名>`。
2. MCH 使用主骨原来的父级，与主骨同级；原始子骨仍直接挂在主骨下，MCH 不插入形变父子链。
3. 所有 MCH 创建完成后，清除主骨相对父级的静置局部旋转，并清除主骨 Pose 变换。
4. 指向已生成主骨的同骨架既有约束、Armature 多目标、Aim 属性的目标角色和 Driver 骨目标改指对应 MCH。
5. 在 MCH PoseBone 上创建 Blender `CHILD_OF` 约束，名称统一为 `HoTools_MCH_Parent`，目标为原主骨，影响为 1，启用位置和旋转、禁用缩放，并设置绑定姿态逆矩阵。
6. 在 MCH data Bone 上写入 `auxType=MCH`、原主骨 `sourceBones`，并把该约束的实际名称登记到 `constraintNames`。这是约束所有权事实，不靠骨名、名称前缀或全局同名搜索反推。

导出态结构如下：

```text
Parent
|- Main
|  `- Child
`- MCH_Main
```

MCH 是主骨的非形变旁路骨，不是原始 Child 的父骨。普通导出中的这些场景修改是临时的，导出结束后由现有 Undo 流程恢复工程。

IR 必须先从所有 `data.bones` 采集 `generateMCH=True` 的原骨名，再读取临时导出态中的 MCH 约束。不得用 `MCH_` 名称前缀、骨骼集合或约束存在性反推 `mchEnabledBones`。

## 顶层结构

顶层对象固定包含以下字段：

```json
{
  "schema": "hotools.rig-constraint-ir",
  "schemaVersion": 3,
  "exportTime": "2026-08-03T00:00:00Z",
  "armatureName": "Armature",
  "mchEnabledBones": [],
  "mchBindings": [],
  "auxBones": [],
  "knownConstraints": [],
  "unknownConstraints": [],
  "aimBindings": [],
  "bindingContext": {
    "space": "BLENDER_ARMATURE",
    "matrixLayout": "ROW_MAJOR",
    "objectMatrix": [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],
    "bones": []
  }
}
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `schema` | 固定为 `hotools.rig-constraint-ir`。 |
| `schemaVersion` | 当前输出 `3`，Unity 读取 `2/3`。不认识版本的消费者必须拒绝猜测解析。 |
| `exportTime` | 导出快照时间，使用 UTC ISO 8601 字符串。 |
| `armatureName` | 当前 Armature 对象名。 |
| `mchEnabledBones` | 当前骨架中 `generateMCH=True` 的 data Bone 名称列表。 |
| `mchBindings` | 临时导出态中被严格识别出的 MCH `CHILD_OF` 绑定。 |
| `auxBones` | 由 `auxBone.isAuxBone` 明确标记的全部辅助骨（包括 MCH）及其自描述元数据、已认领原始约束。 |
| `knownConstraints` | 被 MCH/Aux/Aim 关系或三类常用类型认领的原始约束全集；通用直通不伪造 `auxType`。 |
| `unknownConstraints` | 全骨架扫描后未被任何已知关系认领的约束；每条带 owner、原因和原始约束。 |
| `aimBindings` | 只负责旋转的 Aim 语义，不包含 LBS 或位置绑定。 |
| `bindingContext` | 最终导出态的空间、对象矩阵、每骨静置／pose basis、父级和输入／消费者事实。 |

列表使用稳定顺序：骨记录按骨名排序，约束沿 PoseBone 约束栈顺序。`sourceBones` 保留作者写入顺序；其他列表去重时保留第一次出现的位置。

## 原始约束记录

`mchBindings` 和 `auxBones[].constraints` 中的约束都保存为原始 Blender 记录，不使用 `Rotation`、`Child`、`Parent` 等目标引擎类型。最小公共结构为：

```json
{
  "stackIndex": 0,
  "name": "Blender constraint name",
  "constraintType": "COPY_ROTATION",
  "targetObjectName": "Armature",
  "targetBoneName": "TargetBone",
  "parameters": {
    "mute": false,
    "influence": 1.0
  },
  "references": {}
}
```

`constraintType` 和 `parameters` 保留 Blender 枚举和值。`parameters` 通过 Blender RNA 采集当前版本所有可写、可 JSON 序列化且非对象引用的字段，包括但不限于：

- Copy Rotation 的 owner/target space、mix mode、轴开关、反转开关和 offset；
- Stretch To 的 head/tail、rest length、volume、keep axis、bulge 及其限制；
- Child Of 的位置/旋转/缩放轴开关和 inverse matrix；
- 其他约束类型当前可序列化的类型专用参数。

主 `target/subtarget` 从 RNA 参数中拆出，分别存入 `targetObjectName` 和
`targetBoneName`。其他 Pointer/Collection（例如 `space_object`、IK pole 或
Armature Constraint 多目标）按 RNA 字段名递归保存到 `references`，ID 数据块至少保存
`rnaType/name`，集合项保存其标量字段和嵌套引用。约束自定义属性若存在则另存为
`customProperties`。未知类型或未知枚举值必须保留原值并交给消费者报告，不能在
Blender 导出阶段静默丢弃、改名或降级。

## MCH 绑定识别

`mchBindings` 只接受同时满足以下条件的 PoseBone 约束：

1. `constraint.type == "CHILD_OF"`；
2. owner data Bone 明确标记 `auxBone.isAuxBone=true` 且 `auxType=MCH`；
3. 约束名存在于 owner 的 `auxBone.constraintNames`；
4. `constraint.target` 是当前 Armature 对象；
5. owner 的 `sourceBones` 必须恰好为仅含 `constraint.subtarget` 的单元素列表，并且该 source 同时存在于当前 Armature data Bone 和 `mchEnabledBones`。

不得把任意 `CHILD_OF`、任意 `MCH_` 前缀骨或用户创建的同名约束归入 `mchBindings`。MCH 骨可以改名，识别仍只依赖显式所有权元数据。每条绑定结构为：

```json
{
  "sourceBone": "Main",
  "mchBone": "MCH_Main",
  "constraint": {
    "stackIndex": 0,
    "name": "HoTools_MCH_Parent",
    "constraintType": "CHILD_OF",
    "targetObjectName": "Armature",
    "targetBoneName": "Main",
    "parameters": {
      "mute": false,
      "influence": 1.0
    }
  }
}
```

其中 `sourceBone` 来自约束的 `subtarget`，`mchBone` 来自约束 owner PoseBone。`mchEnabledBones` 与 `mchBindings` 是两类独立事实：前者记录作者开关，后者记录当前快照中实际识别到的绑定。导出器不应为两者不一致而伪造或删除记录。

## Aux 识别

Aux 的唯一身份条件是对应 data Bone 上：

```text
bone.hotools_boneprops.auxBone.isAuxBone == true
```

骨名、集合名、`_twist_`、`_fan_` 和孤立的约束显示名称都不是身份条件。每根 Aux（包括 `auxType=MCH`）都在 `auxBones` 中输出一条自描述记录：

```json
{
  "boneName": "upper_arm_twist_01.L",
  "auxType": "TWIST",
  "sourceBones": ["upper_arm.L"],
  "constraintNames": [
    "HoTools_TWIST_CopyRotation",
    "HoTools_TWIST_StretchTo"
  ],
  "involvedBones": [
    "upper_arm.L",
    "upper_arm_twist_01.L",
    "forearm.L"
  ],
  "constraints": []
}
```

采集规则：

1. `auxType` 原样读取 `auxBone.auxType`。必须保留 `FAN`、`FAN_SINGLE`、`FAN_SIDE`、`TWIST` 和未来新增值，不在 Blender 端归并。
2. `sourceBones` 按集合原顺序读取 `auxBone.sourceBones`，仅略过空字符串，不排序、不合并重复项，也不从父子关系或名称补全。失效名称仍保留为作者态字符串。
3. Blender 4.5 的 Constraint 不支持自定义 ID 属性，因此 Aux 生成器创建或复用约束时，必须使用统一显示名称，并把 Blender 最终分配的实际名称登记到 owner 的 `auxBone.constraintNames`。未登记的同名约束视为用户数据，生成器不能复用、覆盖或接受 Blender 自动追加的名称；发生名称冲突时直接报错并终止本次生成。重新生成完成后再原子替换登记列表；只有 Aux 身份发生变化时才先清空旧登记，删除 Aux 标记时同时清空。
4. 普通 Aux 的 `constraints` 只反查当前 PoseBone 栈中被 `constraintNames` 明确认领的约束，并逐条保存原始类型、栈索引、目标和类型专用参数。跨对象目标仍保留原始对象名；只有同骨架目标才进入 `involvedBones`。
5. 具有相同原始 `auxType` 和完全相同有序 `sourceBones` 的普通 aux 骨属于同一采集组。该分组只用于计算关联范围，不改变逐骨记录结构。

约束名称只是一根 owner 骨内部的引用键：解析时必须先由属性找到 Aux 骨，再在该 PoseBone 自己的约束栈内查找 `constraintNames`；禁止跨骨骼全局搜索同名约束。MCH、AIM 不走普通 Aux 认领路径，其 `auxBones[]` 的 `constraints` 固定为空，必须经过各自严格签名。签名不完整的 MCH 仍进 unknown；无效 Aim 标记不认领跟踪对，但独立常用约束仍可按类型直通。

## 常用直通与 Aim

剩余的 COPY_LOCATION、COPY_ROTATION、ARMATURE 以 `DIRECT_CONSTRAINT` 认领，不要求生成标记，也不因设置超出某个后端能力而改叫 unknown。所有原始参数仍保留，数据无效或后端不支持由导入计划报告。

`auxType=AIM`、`aimVersion=1` 的骨以两个有序 `sourceBones` 指定 target／up；在 owner 的 `constraintNames` 中登记相邻 Damped Track＋Locked Track。仅这两条旋转约束以 `AIM_BINDING` 认领，另在 `aimBindings` 写出语义；同骨的 Copy Location 仍独立直通。所有权登记可以包含其他生成约束，不会将它们混入 Aim 语义。

Aim 不定义中心点、网格三角形或 LBS，不包含 `originBone`。未标记的 Damped／Locked 继续 unknown，不能仅靠相邻或显示名称猜组合。精确检查规则见 [IR v3](../IR_V3.md)。

中立 IR 不输出 Unity `RotationConstraint` 或 `ParentConstraint`，不把 Fan 预先压成全轴世界空间旋转，也不决定 Twist 是否只取 Y 轴。Copy Rotation 与 Stretch To 即使共同构成当前 Twist，也应以各自原始 Blender 约束记录保留；是否在目标端合并成一个功能由导入解析器决定。

## 已知与未知约束划分

划分流程固定如下：

1. 先认领严格 MCH，再按普通 Aux 的 owner-local 所有权认领；AIM 通过独立严格签名认领相邻旋转对，剩余三类常用类型直通。
2. 一条约束的快照身份是 `(ownerBone, stackIndex)`；所有已认领身份写入同一集合，
   因此同一约束不能被两个关系重复输出。
3. 随后遍历当前 Armature 的每根 PoseBone 及其完整约束栈。已认领项输出到
   `knownConstraints`；其余未注册类型／关系不做猜测，输出到 `unknownConstraints`。
4. `knownConstraints` 与 `unknownConstraints` 必须互斥，二者并集必须等于扫描时
   Armature 上的全部 PoseBone 约束。导入器据此可以明确预览哪些关系会被解析、哪些会跳过。

v3 的 relationType 为 `MCH_BINDING`、`AUX_CONSTRAINT`、`DIRECT_CONSTRAINT`、`AIM_BINDING`。原始约束事实保持完整；Aim 旋转对另有语义记录。它们均不提前选择 Unity 组件或降级模式。

本流程不读取旧版隐式约定。旧 Aux 缺少登记时不能冒充生成关系；三类常用类型可以直接已知，其余未注册类型仍未知。错误 MCH／失效 Aim 不由普通 Aux 路径兜底。

同样的所有权规则适用于骨本身。Twist 重建只能替换
`isAuxBone=true`、`auxType=TWIST` 且 `sourceBones` 完整匹配的旧生成骨；名称相似的
普通骨会被报告为冲突，创建直接终止。MCH 只复用显式匹配当前 source 且使用标准名称
的 MCH 骨，普通同名骨、非标准名称或多个显式 MCH 都会中止，不任意选择。

## involvedBones

每根普通 Aux 记录的 `involvedBones` 是其采集组实际涉及的同骨架骨名集合，按以下顺序稳定去重：

1. 该组的有序 `sourceBones`；
2. 按骨名排序的同组普通 aux 骨；
3. 按同组 PoseBone 顺序和约束栈顺序遇到的同骨架约束 `subtarget`。

第三项仅在 `constraint.target` 是当前 Armature 且 `subtarget` 非空时加入。跨对象目标仍保存在原始约束记录中，但不能以裸骨名混入本骨架的 `involvedBones`。经过 MCH 临时改指后，目标若已变为本骨架的 MCH 骨，则 `involvedBones` 忠实记录该 MCH 目标；导出器不反向猜回原目标。

## HoAux 边界

HoAux 与普通 aux 是两套独立系统。`hoAux.isHoAuxBone`、Pipeline、Module、`DEF/TRK/DIR`、Driver 和共享 DIR 继续由 `BoneTools/hoAux/ir` 的独立 Source IR 表达，不能混入本契约的 `auxBones` 后再伪装成普通 Fan/Twist。

HoAux 骨没有普通 aux 的 `sourceBones`。导出器不得从骨父级、约束 target、Driver target、模块名或显示名称推导并写入伪造的 `sourceBones`。HoAux 涉及的骨和资源应从其独立资源图的 owner、target、Driver variable 和依赖闭包得到。

## 导入端职责

目标端导入器读取的是事实快照，而不是已决定的落地指令。导入约束前必须生成预览列表，至少展示：

- 原始 owner 骨、aux 类型和 Blender 约束类型；
- 原始 target、空间、轴和 influence；
- 当前选择的解析器或兼容模式；
- 预计创建、合并、忽略或降级成的目标端对象；
- 缺骨、未知参数、能力不足和歧义警告。

Standard、VRC 兼容解析、Twist 只取 Y 轴、Fan 的实现方式及 HoAuxRig 模式都属于导入端策略。切换模式后必须重新计算预览；这些选择不回写、不篡改中立 IR。Blender 导出器只保证原始事实足以让不同导入策略重新决策。

## 回归不变量

- 顶层 `schema/schemaVersion` 固定且可严格验证。
- `mchEnabledBones` 只来自 `generateMCH`，`mchBindings` 只来自严格签名的同骨架 MCH `CHILD_OF`。
- MCH 与主骨共享原父级，主骨的原始子骨链不变，MCH 不形变。
- Aux（包括 MCH）只由 data Bone 的 `auxBone.isAuxBone` 识别，并保留原始 `auxType/sourceBones/constraintNames`。
- Aux 的约束类型、栈顺序、目标、空间、轴和类型专用参数不在导出时降级。
- 已知/未知集合按 `(ownerBone, stackIndex)` 互斥去重，并完整覆盖当前 PoseBone 约束栈。
- 签名不完整的 MCH 约束只能进入未知集合，不能由普通 Aux 路径兜底认领。
- 中立 IR 不包含 Unity `Rotation`、`Child` 或其他最终组件选择。
- Twist 的 Y 轴退化和 HoAux 模式选择只发生在导入预览及落地阶段。
- HoAux 始终使用独立 Source IR，不伪造普通 aux 的 `sourceBones`。
