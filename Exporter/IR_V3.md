# Ho Rig Constraint IR v3

实现日期：2026-10-25。schema=`hotools.rig-constraint-ir`，schemaVersion=`3`。Unity 消费端同时接受 v2/v3；v2 不自动重解释旧 unknown。

## 认领与事实

顺序为严格 MCH → 显式 Aux → 显式 Aim → 常用类型 → unknown。每个 `(ownerBone, stackIndex)` 只认领一次。

| relationType | 内容 |
| --- | --- |
| MCH_BINDING / AUX_CONSTRAINT | 延续既有关系 |
| DIRECT_CONSTRAINT | COPY_LOCATION、COPY_ROTATION、ARMATURE，不要求 Ho 标记 |
| AIM_BINDING | 有合法 Ho 标记的相邻 DAMPED_TRACK＋LOCKED_TRACK，另附独立 Aim 旋转语义 |

类型已知不等于所有参数都能执行。原始参数、空间、目标、栈序、多源权重继续保留；缺引用或参数超范围在导入计划中诊断，不重新塞回 unknown。

未标记或签名不匹配的跟踪约束继续 unknown，不按名称猜组合。

## 顶层新增字段

保留 v2 原有所有字段，新增 `aimBindings`（可为空）与 `bindingContext`。

bindingContext 使用 `space=BLENDER_ARMATURE`、`matrixLayout=ROW_MAJOR`。objectMatrix、每骨 restMatrix／poseBasis 均为 16 个有限浮点数。骨记录包含 boneName、parentBone、inheritScale、connected、positionOnly、hasPoseAnimation。

`positionOnly` 是保守的消费者分析结果，不按 REF 等名称设置；有子骨、网格权重组、骨父级对象或完整矩阵消费者时，不作位置-only 优化。自定义运行时脚本不在静态分析保证内。

`hasPoseAnimation` 检查 Blender 的 action／NLA／driver；Unity 另检查可识别的 Humanoid／Transform 动画输入。

HoFBX 的配套 JSON 补 `fbxBoneAxes=Y_X`，对应其固定 Y 主轴、X 次轴。中立独立快照不假定任意 FBX 使用该预设；稀疏／共线骨架可据配套信息校验方向基底。

## Aim 只负责旋转

Aim 使用 owner **进入该操作时的位置**，指向 targetBone，并用 upBone 相对 owner 的方向确定 roll。它不改变位置，不定义网格三角形，不要求来源是 LBS。

```json
{
  "ownerBone": "AimControl",
  "semanticType": "AIM",
  "semanticVersion": 1,
  "targetBone": "Target",
  "upBone": "UpReference",
  "upMode": "OBJECT_POSITION",
  "aimAxis": "TRACK_X",
  "upAxis": "TRACK_NEGATIVE_Z",
  "muted": false,
  "constraintStackIndices": [1, 2]
}
```

此处 `[1,2]` 可以位于独立 Copy Location 之后，也可以完全没有位置约束、使用 `[0,1]`。Aim IR 没有 originBone；位置由前序操作或父级提供。

### 生成工具填写的属性

在 owner 的 `bone.hotools_boneprops.auxBone` 上填写：

```text
isAuxBone = True
auxType = AIM
aimVersion = 1
sourceBones = [瞄准目标骨名, 上方向参考骨名]
constraintNames 包含 Damped Track 与 Locked Track 的实际名称
```

sourceBones 只有两个旋转角色，不包括中心／活动点。constraintNames 是生成约束的所有权登记，也可以包含独立生成的 Copy Location；只有登记的跟踪对合并为 Aim，Copy Location 仍作为 DIRECT_CONSTRAINT。

v1 要求：两个登记的跟踪约束实际相邻、Damped→Locked、WORLD→WORLD、influence=1、head_tail=0、无 B-Bone、静音状态一致；引用属于当前骨架且匹配两个角色；两个带符号 track axis 不同轴，Locked 的 lock axis 等于第一条跟踪轴。owner／target／up 身份互异。

标记损坏或版本不支持时不吞掉事实：跟踪约束继续 unknown，独立复制约束仍可按类型认领。未来三点生成工具只需分别生成位置操作和这个通用 Aim 标记。

## Armature 与绑定

原始多源保留在 `constraint.references.targets[]`：

```json
{"rnaType":"ArmatureConstraintTarget","properties":{
  "target":{"name":"Armature","rnaType":"Object"},
  "subtarget":"breast_L","weight":0.5
}}
```

不在事实层覆写权重；后端按有限正总和归一化。MCH 预处理同时重映射普通 subtarget、Armature 多源及 Aim 的目标角色，绑定快照对应最终导出骨。

## 三后端与边界

| 语义 | Standard | HoAuxRig | VRC |
| --- | --- | --- | --- |
| Copy Location | PositionConstraint 阶段 | 位置插值 | VRCPositionConstraint 阶段 |
| Copy Rotation | RotationConstraint 阶段 | Slerp | VRCRotationConstraint 阶段 |
| Armature | 多源 Parent 刚性近似 | 加权仿射矩阵，位置-only 或可表示 TRS 写回 | 多源 VRCParent 刚性近似 |
| Aim | AimConstraint | 独立旋转求解 | VRCAimConstraint |

原生 helper 继承前一阶段输入；零权重 source 显式记录前序／up 依赖。复制约束使用零偏移，不烘保持初始偏移。

首版通用复制限当前骨架、完整 XYZ、WORLD→WORLD、无反相／offset／tail／B-Bone，旋转为 REPLACE。Armature 限线性混合，无 Preserve Volume／Envelope／Current Location、完整或零影响度。

owner 以静置局部姿态加动态父级作为输入：单位 poseBasis、FULL 继承、无独立 owner 动画；复制位置／Armature 不处理连接骨。来源骨和父级可以动画。

已实测 Standard 的 0.3 旋转影响度与 Blender Slerp 不一致。非端点／非 0.5 的原生旋转标为 NativeApproximation；VRC 也不预先保证同值等价。Ho 端保留 Slerp。

Ho 在 rig-space 虚拟矩阵缓冲区按依赖与栈序求值，避免上一帧输出反馈。实际层级不能表示的剪切不静默当成精确 TRS，停止该写回并设置 LastDirectError；退化 Aim 也会诊断。

预览区分已知可映射、原生近似、设置不支持、数据无效、静音／零影响及 unknown。存在未知栈屏障、循环、缺目标或手工冲突时，不擅自重排或覆盖；Ho 首版不跨既有 Aux/MCH 层与新通用栈做反馈重排。上游仍有 unknown 时会提示只读取 Unity 当前姿态，不宣称整图完整。

清理旧导入前预检；意外装配失败撤销本次操作。helper／挂点有所有权标记，重导入和切模式保留手工子物体及未登记组件。

## 验证入口

- Python：`Exporter/tests/test_constraint_export.py`、`Exporter/tests/test_constraint_ir_v3.py`。
- Blender 4.5/5.2：`tests/test_blender_constraint_ir_v3.py`、`tests/test_blender_rig_constraint_export_e2e.py`，另有 Aux 所有权与 FBX 开关回归。
- WTD fixture：后台加载用户 `.blend`，运行 `tests/export_wtd_ir_v3_fixture.py -- 输出目录`，不保存原工程。
- Unity：HoUnityTools 的 `Tests~/ConstraintIRV3/Run.ps1 -Fixture ... -TestVrcApiShim`，使用新隔离工程检查 v2/v3、Aim、序列化、清理、回滚、复制栈与网格数值。

VRC API shim 只验证反射／序列化装配，不能代替真实 SDK／客户端。Warudo 时序与物理链仍需目标宿主验证；三点／LBS 生成工具不属于本次实现。
