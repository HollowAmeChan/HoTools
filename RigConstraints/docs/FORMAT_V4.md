# Rig Constraint IR v4 开发契约

本文件与 RETIRE_V3.md 配套。Blender／Unity 只支持 v4，旧版输入直接拒绝。下列键为 Blender/Unity 联调的共同接口；新增可选键须保留未知字段。值中的 `...` 仅为说明，不能写入实际产物。

```json
{
  "schema": "hotools.rig-constraint-ir",
  "schemaVersion": 4,
  "armatureName": "Rig",
  "exportTime": "RFC3339 UTC",
  "blenderVersion": "4.5.8",
  "captureStage": "AUTHORING",
  "registry": {"id": "hotools.rig-constraints.registry", "version": 1, "sha256": "..."},
  "sources": [{
    "sourceId": "c0", "ownerBone": "Owner", "ownerKind": "BONE",
    "captureStage": "AUTHORING",
    "constraint": {
      "stackIndex": 0, "name": "Copy Rotation", "constraintType": "COPY_ROTATION",
      "targetObjectName": "Rig", "targetBoneName": "Target",
      "parameters": {}, "references": {}
    }
  }],
  "semantics": [{
    "semanticId": "s0", "semanticType": "COPY_ROTATION", "semanticVersion": 1,
    "ownerBone": "Owner", "sourceIds": ["c0"],
    "ruleId": "group.copy_r", "ruleVersion": 1,
    "evidence": "GENERATED", "parameters": {}
  }],
  "implementationBindings": [{
    "semanticId": "s0", "backendId": "HoAux",
    "implementationId": "hoaux.copy_rotation.world", "contractVersion": 1,
    "selection": "CANDIDATE", "fallbackPolicy": "EXACT_ONLY"
  }],
  "bindings": {
    "captureStage": "POSTPROCESS",
    "boneMap": [{"sourceBone": "Target", "exportBone": "MCH_Target"}],
    "constraintMap": [{
      "sourceId": "c0", "ownerBone": "Owner", "stackIndex": 0,
      "targetObjectName": "Rig", "targetBoneName": "MCH_Target"
    }],
    "bindingContext": {}
  },
  "sourceContext": {},
  "inputFingerprint": "..."
}
```

## 约定

- sourceId/semanticId 在一次快照内唯一；所有原始约束保留一次。新类型不认识时保留源事实，无语义记录即 UnknownSemantic。
- semanticType 首批为 `COPY_LOCATION`、`COPY_ROTATION`、`ARMATURE`、`MCH`、`TWIST`、`FAN`、`AIM`；均 semanticVersion=1。Fan 的原 auxType 放 parameters.auxType。
- parameters 对普通组合至少存 sourceBones、auxType。Aim 另存 targetBone/upBone/aimAxis/upAxis/upMode/muted，位置不属于 Aim。
- evidence 是 `RAW_TYPE`、`GENERATED` 或 `EXPLICIT`，不作为执行权限。
- backendId 使用现有 `Standard`、`HoAux`、`Vrc`。实现 ID 的 backend 前缀使用 lowercase；id 不含 @version，版本单独存整数。
- 首批契约 ID：每后端的 `.copy_location.world`、`.copy_rotation.world`、`.armature.linear`、`.mch.parent`、`.twist.legacy`、`.fan.legacy`、`.aim.object_position`；HoAux 额外有 `hoaux.copy_rotation.local`、`hoaux.copy_rotation.owner_orient`。登记不等于已实现或已验证。
- implementationBindings 为导出候选或已锁定的选择；selection=`CANDIDATE`/`LOCKED`。同语义同后端可多个候选，LOCKED 至多一项。陌生契约/版本不得自动改选。
- 已有 Twist/Fan 的特定 legacy 实现候选显式写 `fallbackPolicy=ALLOW_LEGACY` 以保留其契约；这不允许 Exact 失败后自动换近似实现。Armature 的原生近似仍需显式 `ALLOW_APPROXIMATE`，默认 `EXACT_ONLY`。
- HoFBX v4 的“允许原生约束近似”显式导出选项为 Standard/Vrc 候选写 `ALLOW_APPROXIMATE`，同时保留根 `importPolicy.allowNativeApproximation`。不开启则继续拒绝不满足精确保真域的原生实现；HoAux 不受此选项影响。
- registry 独立管理 constraintTypes、semanticDefinitions、implementations。每实现包含 id、contractVersion、semanticType、semanticVersion、backendId、conditions（结构化受控条件）、availability、fidelity、verification、artifacts、testSuites。
- 已有 world Direct 的条件保留当前全 XYZ/Replace、owner 输入等边界；Local 两项按注册表中的已通过数值验收域执行，超出条件不得自动放宽。
- bindings.constraintMap 是最终导出引用覆盖，只覆写明确提供的键；references 若提供则代表最终引用集合。source constraint 始终保持原值。
- 导出预处理新增的 MCH 约束以 captureStage=`EXPORT_GENERATED` 追加 source；实际作者约束不重复追加。root captureStage 仍说明作者采集阶段。
- sourceContext 存作者态骨架上下文；bindings.bindingContext 使用现有最终 FBX BindingContext 字段约定。独立作者快照可没有最终 bindings，不可据此装配 Unity。
- 骨架上下文的每骨新增 `inheritRotation` 布尔，原值来自 Blender `use_inherit_rotation`。新 v4 局部复制旋转要求作者／最终 owner 和 target 都显式为 true、inheritScale=FULL，并保持父身份及父的世界静置参考；缺证据不能自动升级为精确实现。旧版本输入不接入规划。
- 最终 bindingContext 在清除约束与 fixObjectTransform 后、FBX 写出前采集。保留清约束前的保守消费者分析，不能因消费者暂被删除便丢弃完整矩阵输出需求。
- 根 `exportOptions` 记录 `appliedConstraints`、`appliedArmaturePose`、`fixedObjectTransform`。约束已固化时不自动重放；作者 owner poseBasis 不因最终 applyPose 清零而被伪装成中立输入。
- inputFingerprint 为对文档去掉 exportTime/inputFingerprint 后稳定排序 JSON 的 SHA-256；列表顺序保留，参数数值不随意舍入。哈希用于检测，不替代契约条件验证。
- codec/model/registry 只依赖标准库，不依赖 bpy。骨骼登记、review 和 exporter 独立读取这些公共接口。
- 不新增、修改、导出大型 BoneTools/hoAux 的 Source IR 或 Driver；扫描跳过其明确标记的 owner。
- HoAux 通用 Copy Location／Copy Rotation／Armature／Aim 的 `conditions.rigSpace=FINITE_POSITIVE_UNIFORM_TRS` 要求运行时根矩阵有限、可分解且无剪切，缩放为正且均匀；祖先负缩放也拒绝。恢复有效根变换后重新计算。该运行时检查不等于 JSON 规划已经验证了当前场景。
- 注册表 `testSuiteDefinitions` 定义测试入口和实际观察轴；实现的 `testSuites` 必须引用有效定义。`python -m RigConstraints.registry --matrix` 输出实现、条件、证据和测试定义的关联 JSON；不会执行注册表内命令，也不把轴集合冒充已测试的全部笛卡尔积。

## 骨骼登记公共 API

新 `RigConstraints.blender.metadata` 接收 PoseBone/Constraint，不反向 import boneProperty：

- `register_group(pose_bone, semantic_type, constraints, *, generator_id='', semantic_version=1, roles=None)`：所有成员就绪后整体更新，幂等。
- `clear_groups(data_bone)`：仅清本轮普通语义组；不动大型 hoAux 元数据。
- `reset_aux_info(data_bone)`：清当前 auxBone 身份及普通语义组。
- `iter_groups(data_bone)`：给 source/semantic reader 和 review 的只读标准字典视图；只读取显式 constraintGroups，不从其他骨属性推导语义。
- 持久集合挂 `hotools_boneprops.constraintGroups`；PropertyGroup 类及依赖清单由 `RigConstraints.blender.properties` 提供，boneProperty 负责引入该集合并按顺序注册。

统一组字段：groupId、semanticType、semanticVersion、generatorId、ownsBone、members[]；成员字段：constraintName、constraintType、role、order。角色：Twist=`rotation/stretch`；Aim=`aim/up`；Fan/copyR=`rotation`；MCH=`parent`。显式接纳既有骨的 copyR/Aim 不拥有该骨。

`_replace_aux_constraints` 在完整成员提交时调用 register_group。constraintNames 仅作为当前生成器的精确约束索引，不再充当缺少 constraintGroups 时的语义依据；缺少集合时明确报错。

copyR 作者入口新增 auxType=COPY_R；生成时写 COPY_ROTATION@1 组和 group.copy_r@1 翻译规则。未登记的手工 COPY_ROTATION 只保留源事实，不在审查或导出中自动接纳。Copy Rotation 只按明确登记的 v4 语义规划。

## 两端实现入口

Blender 原始采集由 `RigConstraints.source` 提供：`capture_constraint`、`capture_binding_context`、`capture_parameters`、`capture_references`、`capture_custom_properties`；均返回字典。`capture_armature` 组合作者快照，`semantics.inspect_aim_pair` 提供显式 Aim 接纳验证。Exporter 仅负责导出时序与写出，不提供其他版本 writer。

Unity `HoConstraintIrPlanner.Build(document, registry, backendId)` 返回 `HoConstraintIrPlanningResult`；其中 `Plan` 为不序列化的 `HoConstraintExecutionPlan`。源事实 DOM 始终权威；plan 的 operations / barriers 带 sourceId，组合带 semanticId/semanticType，finalBindings 提供场景装配上下文。它不再伪造 schema 3 或维护 known/unknown 第二套文件分类。
