# Rig Constraint IR v4 开发契约

本文件与 EXECUTION_PLAN.md 配套。下列键为 Blender/Unity 联调的共同接口；新增可选键须保留未知字段。值中的 `...` 仅为说明，不能写入实际产物。

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
    "ruleId": "direct.copy_rotation", "ruleVersion": 1,
    "evidence": "RAW_TYPE", "parameters": {}
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
- evidence 是 `RAW_TYPE`、`GENERATED`、`EXPLICIT` 或 `LEGACY`，不作为执行权限。
- backendId 使用现有 `Standard`、`HoAux`、`Vrc`。实现 ID 的 backend 前缀使用 lowercase；id 不含 @version，版本单独存整数。
- 首批契约 ID：每后端的 `.copy_location.world`、`.copy_rotation.world`、`.armature.linear`、`.mch.parent`、`.twist.legacy`、`.fan.legacy`、`.aim.object_position`；HoAux 额外有 `hoaux.copy_rotation.local`、`hoaux.copy_rotation.owner_orient`。登记不等于已实现或已验证。
- implementationBindings 为导出候选或已锁定的选择；selection=`CANDIDATE`/`LOCKED`。同语义同后端可多个候选，LOCKED 至多一项。陌生契约/版本不得自动改选。
- 已有 Twist/Fan 的特定 legacy 实现候选显式写 `fallbackPolicy=ALLOW_LEGACY` 以保留其契约；这不允许 Exact 失败后自动换近似实现。Armature 的原生近似仍需显式 `ALLOW_APPROXIMATE`，默认 `EXACT_ONLY`。
- registry 独立管理 constraintTypes、semanticDefinitions、implementations。每实现包含 id、contractVersion、semanticType、semanticVersion、backendId、conditions（结构化受控条件）、availability、fidelity、verification、artifacts、testSuites。
- 已有 world Direct 的条件保留当前全 XYZ/Replace、owner 输入等边界；新 local 两项在通过 Unity 数值验收前 availability=`PLANNED`，不能提前可执行。
- bindings.constraintMap 是最终导出引用覆盖，只覆写明确提供的键；references 若提供则代表最终引用集合。source constraint 始终保持原值。
- 导出预处理新增的 MCH 约束以 captureStage=`EXPORT_GENERATED` 追加 source；实际作者约束不重复追加。root captureStage 仍说明作者采集阶段。
- sourceContext 存作者态骨架上下文；bindings.bindingContext 使用现有最终 FBX BindingContext 字段约定。独立作者快照可没有最终 bindings，不可据此装配 Unity。
- inputFingerprint 为对文档去掉 exportTime/inputFingerprint 后稳定排序 JSON 的 SHA-256；列表顺序保留，参数数值不随意舍入。哈希用于检测，不替代契约条件验证。
- codec/model/registry 只依赖标准库，不依赖 bpy。骨骼登记、review 和 exporter 独立读取这些公共接口。
- 不新增、修改、导出大型 BoneTools/hoAux 的 Source IR 或 Driver；扫描跳过其明确标记的 owner。

## 骨骼登记公共 API

新 `RigConstraints.blender.metadata` 接收 PoseBone/Constraint，不反向 import boneProperty：

- `register_group(pose_bone, semantic_type, constraints, *, generator_id='', semantic_version=1, roles=None)`：所有成员就绪后整体更新，幂等。
- `clear_groups(data_bone)`：仅清本轮普通语义组；不动大型 hoAux 元数据。
- `reset_aux_info(data_bone)`：清旧 auxBone 及普通语义组。
- `iter_groups(data_bone)`：给 source/semantic reader 和 review 的只读标准字典视图；旧元数据通过只读 legacy 适配。
- 持久集合挂 `hotools_boneprops.constraintGroups`；PropertyGroup 类及依赖清单由 `RigConstraints.blender.properties` 提供，boneProperty 负责引入该集合并按顺序注册。

统一组字段：groupId、semanticType、semanticVersion、generatorId、ownsBone、members[]；成员字段：constraintName、constraintType、role、order。角色：Twist=`rotation/stretch`；Aim=`aim/up`；Fan/copyR=`rotation`；MCH=`parent`。显式接纳既有骨的 copyR/Aim 不拥有该骨。

旧 `_register_aux_constraint/_replace_aux_constraints` 保留旧 constraintNames API；后者根据已知 auxType 在完整成员提交时调用 register_group。最小旧测试 PG 没有新集合时仍可使用旧登记，不抛异常。

copyR 作者入口新增 auxType=COPY_R；生成时写 COPY_ROTATION@1 组和 group.copy_r@1 翻译规则。未登记的手工 COPY_ROTATION 只保留源事实，不在审查或导出中自动接纳。旧 v2/v3 Direct Copy Rotation 数据保持旧解释。
