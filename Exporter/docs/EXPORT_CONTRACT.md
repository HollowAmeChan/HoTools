# HoTools 导出契约

本文档记录 Blender 导出器与 HoUnityTools 导入器之间的骨架、MCH 和约束语义。导出器对 FBX 使用临时场景修改；普通导出结束后通过 Undo 恢复工程。

## MCH 流程

`generateMCH` 是骨属性和导出端的唯一 MCH 开关。打开后，勾选的主骨统一执行以下步骤：

1. 在清零主骨前复制 head、tail、roll，创建 `MCH_<主骨名>`。
2. MCH 使用主骨原来的父级，与主骨同级；原始子骨仍直接挂在主骨下，MCH 不插入形变父子链。
3. 所有 MCH 创建完成后，清除主骨相对父级的静置局部旋转，并清除主骨 Pose 变换。
4. 在 MCH 上创建 Blender `CHILD_OF` 约束，目标为主骨，影响为 1，启用位置和旋转、禁用缩放，并设置绑定姿态逆矩阵。
5. 指向已生成主骨的原有约束和驱动改指对应 MCH；自动生成的 MCH `CHILD_OF` 不参与这次改指，避免变成自引用。

导出的结构示意：

```text
Parent
|- Main
|  `- Child
`- MCH_Main
```

MCH 是主骨的旁路骨，不是 Child 的父骨。它通过正向 Parent 关系跟随主骨并保留绑定偏移，不使用“反向运动”。Unity 的 `ParentConstraint` 同样在导入绑定姿态时保持偏移。

## 约束 JSON

约束 JSON 不是 FBX 的内嵌数据，而是旁边 `HoFBX` 文件夹中的附加文件。只有开启 `exportUnityMetadata`（自动元数据）或 `exportBoneConstraint`（手动约束 JSON）时才会生成；只开启 `generateMCHBones` 而关闭这两个选项时，FBX 仍会有 Blender `CHILD_OF`，但不会写旁边的 JSON。

所有同一骨架内部的 Blender `CHILD_OF` 约束都走同一条语义路径，包括自动生成的 MCH 约束和用户手动创建的 Parent/Child Of 约束：

```json
{
  "type": "Child",
  "semantic": "parent",
  "targetPath": "Main",
  "weight": 1.0,
  "space": {"source": "world", "target": "world"},
  "maintainOffset": true
}
```

当前契约类型名必须是 `Child`。HoUnityTools 将其分派为 Unity `ParentConstraint`；不要改成 `Parent`。`maintainOffset` 是契约中的明确意图，旧版 `ConstraintInfo` 即使忽略这个未知字段，导入器仍会通过 `ActivateAndPreserveOffset` 保持偏移。

Parent 语义只负责位置和旋转。Unity `ParentConstraint` 不驱动缩放；需要缩放时必须另写一个明确的 `Scale` 约束，不能从 `Child` 语义推断。

## Aux 特例

目前只有 Fan 和 Twist 属于有意保留的 Aux 特例。它们的 Blender 约束存在空间、轴向、权重拆分和多种构造方案，不能直接按通用约束复制到 Unity。

### Fan

Fan、FanSingle、FanSide 统一退化为世界到世界、全轴的 Unity `RotationConstraint`。当前契约不表达其他 owner/target 空间组合。

### Twist

Twist 不完整复制 Blender 约束，而是退化为每根辅助骨一条世界到世界的 Unity `RotationConstraint`，只约束 Y 轴。JSON 的 `sourceBone` 仅记录蒙皮权重拆分来源，不是 Unity 约束 source。Twist 的 Blender 辅助骨生成端不依赖导出器中间对象。

Fan/Twist 的目标引用在 MCH 流程中会按现有规则转移到 MCH；这属于 Aux 特例，不应扩散到普通 `CHILD_OF`。

## 分析与映射

`ConstraintAnalyzer` 直接返回 Fan、Twist、Parent 等语义约束列表。导出器不再创建 `TwistChainGroup` 这类只分组又立即展开的中间对象。`UnityConstraintMapper` 逐条把语义映射成 `Rotation` 或 `Child` JSON。

HoUnityTools 先应用 Humanoid 映射，再读取约束 JSON，按 `boneName` 和 `targetPath` 找到 Transform，创建或复用 Unity 约束，保持偏移后激活并锁定。

## 回归不变量

- MCH 与主骨共享原父级，主骨的原始子骨链不变。
- MCH 不形变，主骨清零后仍通过 Parent 约束保留原始绑定朝向。
- 每条自动生成关系都是真实 Blender `CHILD_OF`，并输出为 JSON `type: "Child"`。
- Parent 关系不形成 MCH 自引用或 Child 反向动力。
- Fan/Twist 的世界空间和 Twist 的 Y 轴退化规则保持稳定。
