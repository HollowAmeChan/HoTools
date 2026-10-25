# Ho 手工加权附着框架：约束导出契约草案

状态：2026-10-25 的可行性验证与历史提案。当前生产契约见 [IR v3](IR_V3.md)，保留 v2 读取含义。本文的早期验证边界不自动代表后续所有后端已实测。

后续决策：常用类型先直通，详见 [常用约束直通 IR 与三后端方案](DIRECT_CONSTRAINT_IMPORT_CONTRACT.md)。COPY_LOCATION、COPY_ROTATION、ARMATURE 拟独立成为已知直通类型；未标记的 Damped Track／Locked Track 继续 unknown。本文关于完整 frame profile 的建议保留为未来生成工具方向，不再作为前三类已知认领的前置条件。

## 目标与术语

以 `WTD-summer.blend / Armature / CTR_C1_ChestAddon` 为首个真实样例。用户明确：参考点的骨骼权重是手工填写的，不对应某个真实网格顶点；验收目标是复现 Blender 当前行为。

名称采用 **Weighted Attachment Frame（手工加权附着框架）**。不要求顶点索引、真实三角面或网格拓扑，也不在导入时自动重刷权重、归一到身体表面或改变父级。

## 样例实际结构

闭包包含 12 根骨、13 条约束。上游是 hips、spine、chest、breast_L、breast_R；7 根被约束骨如下：

| 骨 | 按原顺序求值的约束 |
| --- | --- |
| REF_C1_ChestAddon_P | Armature：breast_L=0.5、breast_R=0.5 |
| REF_C1_ChestAddon_U | Armature：breast_L=0.5、breast_R=0.5 |
| REF_C1_ChestAddon_R | Armature：breast_L=0.5、breast_R≈0.3 |
| REF_C1_ChestAddon_L | Armature：breast_R=0.5、breast_L≈0.3 |
| DIR_C1_ChestAddon_R | Copy Location(P)、Damped Track(R, +X)、Locked Track(U, -Z, Lock X) |
| DIR_C1_ChestAddon_L | Copy Location(L)、Damped Track(P, +X)、Locked Track(U, -Z, Lock X) |
| CTR_C1_ChestAddon | Copy Location(P)、Copy Rotation(DIR_R, 1)、Copy Rotation(DIR_L, 0.5) |

全部参考点和定向骨都保留作者设置的 chest 父级。原始数据用 float32 表达，因此 0.3 不应在事实层强行改写。

实际受输出骨控制的是“上衣蝴蝶结”，1911 个原始顶点。此次提取了该网格及上述骨骼闭包，未导出整个人物的材质、其他衣服或物理系统。

## 需要保持的语义

### 1. Armature 点：绑定位置与约束前的位置分开

所有矩阵在骨架对象局部坐标系计算，物体到世界变换只施加一次。

设第 i 个目标骨的静置矩阵为 B_i、当前矩阵为 M_i(t)，归一化源权重为 a_i。令 x_pre(t) 为被约束骨进入 Armature 约束之前的头部位置，则本样例的点结果为：

```text
x(t) = Σ a_i · M_i(t) · inverse(B_i) · x_pre(t)
a_i  = w_i / Σ w_i
```

本样例点骨的 matrix_basis 为单位矩阵，约束前位置可从保留的父级求出：

```text
x_pre(t) = M_parent(t) · inverse(B_parent) · x_bind
```

因此不能把所有 Armature 约束一概降级为“各源骨下的固定偏移点加权”。后者只复现固定绑定位置的点，不能原样复现本样例保留的动态父级影响。这不是对作者设置的纠正，也不能据此认定作者的虚拟附着点错误。

此处只输出点的位置；只有后续读取者都使用头部位置时，才允许不求参考骨完整的旋转和缩放。若存在 Copy Transforms、复制参考骨旋转、尾部目标或对子级完整矩阵的依赖，当前 profile 不得认领。

### 2. 两个三角框架独立定义轴向

保存每套框架的 origin、aimTarget、upTarget、带符号的 aimAxis、upAxis 和 lockAxis。不能根据左右名字自动镜像，也不能把两套框架的原点都改为 P。

本样例右侧是 P→R、P→U；左侧是 L→P、L→U。两套结果朝向一致后才进行旋转混合。实际 upAxis 是 **-Z**，不能硬编码为教程里的 +Y。

未来有显式生成标记的 frame profile 可考虑认领完整影响度的 Damped Track + Locked Track 组合，锁定轴必须对应第一步的跟踪轴；当前未标记组合仍保持 unknown。

### 3. 旋转混合保留栈顺序

本样例先完整复制右侧朝向，再以 influence=0.5 向左侧朝向插值。不要把两条顺序约束直接解释成两个 0.5 的 Blender 约束。

在当前“两条全轴 WORLD→WORLD、REPLACE、第一条 influence=1”的受限情况，Unity 原生双源 RotationConstraint 的权重可映射为 `(1-t, t)`。更长的栈、部分轴、反相、其他 mix 或第一条 influence≠1 不在本轮证明范围内。

轴向换算必须依据 FBX 导入后每根骨的绑定基底，不可仅交换欧拉角 XYZ 或只按骨名猜正负。

### 4. 时序是契约的一部分

依赖顺序：输入姿态 → Armature 点 → 框架位置／Aim → 输出位置／旋转混合 → 消费者。

Unity 原生 Aim 的 WorldUpObject 需要显式加入依赖。在本次 Unity 6 实测中，仅填写 WorldUpObject 会出现第一帧读旧点；额外把 upTarget 以 **零权重 source** 加入 Aim 后，第一轮和第六轮求值一致。

自定义点求值器不能凭 LateUpdate 名称推断时序。本次独立原型把点计算插到 `ConstraintManagerUpdate` 之前，才保证与后续原生约束在同一轮生效。生产实现必须与 HoAuxRig、Warudo 动捕／物理及其他 PlayerLoop 使用者协调，不直接复制验证原型的全局安装方式。

物理链使用单独的附着父级，不能让物理与约束同时写同一 Transform；物理输入骨何时更新需要另做集成验证。

## 与现有 IR 的边界

当前 `ConstraintIRExporter` 会把本样例 13 条手工约束列入 `unknownConstraints`，保留原始参数以及 `references.targets`。这符合现有保守规则。

Unity 的 `BlenderConstraintInfo` 目前没有 references 字段，其 parameters 也未覆盖 Armature／跟踪轴参数。因此“Blender JSON 有信息”不代表当前 Unity 导入器已经能消费它们。现有解析器仍只认领 Parent/MCH、Twist、Fan 等已知关系。

未来生成工具可新增受限的 `weighted-attachment-frame/v1` profile；通用三类直通先按新方案独立推进：

- 先完整识别依赖闭包，再按 `(ownerBone, stackIndex)` 认领原始约束；一个约束只认领一次。
- 事实层继续保留源对象、源骨、栈序、原始权重、空间、静音、影响度、轴与多源 references，不由 exporter 预选 Unity 后端。
- 提案结构记录 `graphId / outputs / bindSpace / points / frames / rotationStacks / consumedConstraintKeys / requiredCapabilities`；正式字段及 schemaVersion 尚未发布。
- 点记录至少包含静置头部、约束前父级、绑定矩阵身份、源骨及原始权重、normalization、Armature 选项。
- 导入计划明确显示每张图的后端：原生可等价、Ho 求值器可等价、未验证、不支持；不得部分导入后宣称整张图成功。
- 未识别的其他约束继续 Unknown／跳过；不恢复任意原始约束的自动导出执行。

第一版仅考虑：同骨架、有限非负且总和大于零的权重、Preserve Volume／Envelope 关闭、普通骨、head_tail=0、约束点无独立 pose 动画／driver、受支持的全轴 world copy 与完整跟踪组合。B-Bone、多骨架、负权重、零总权重、部分影响度、退化框架、非均匀／负缩放和剪切必须明确拒绝或标为未验证，不能静默近似。

## 预处理与绑定矩阵

当前 HoFBX 会应用姿态、矫正物体变换、生成 MCH，并在这些步骤后导出 IR。新 profile 必须与**最终导出 FBX 的绑定状态**一致。

需要同时明确原始身份和导出身份：原骨→MCH／导出骨的映射、静置矩阵的采样阶段、轴基底、对象空间、父级及预处理设置。不可从一份应用姿态前的 JSON 配另一份应用姿态后的 FBX 猜绑定关系。

本轮用原始静置骨架闭包 FBX 验证，没有验证 HoFBX 全部默认预处理组合。正式接线前必须补这一项，尤其是非静置导出、MCH 生成和重复导入。

## 后端结论

| 后端 | 本轮结论 |
| --- | --- |
| Unity + 小型 Armature 点求值器 + 原生 Position/Aim/Rotation | 已测原样行为，见验证报告；原型不是生产组件 |
| Unity 纯原生约束，固定绑定点 profile | 另设去除 REF 父级的 Blender 对照副本验证通过；这不是原工程的等价替换 |
| VRC 原生约束 | 未实测，也未证明动态父级的 Armature 点已可等价降级；自定义点脚本不可上传 Avatar |
| Warudo | 本轮未启动 Warudo；Unity 原型可作为后续 Mod 集成候选，不等于已完成 Warudo 动捕／物理验证 |

VRC 后续可以研究局部求解的辅助层级来保持约束前父级语义，但在目标 SDK／客户端跑过同一套逐帧测试前，不标记支持。

## 验收与证据

Blender 4.5.8 LTS → FBX → Unity 6000.3.15f1，真实 PlayMode 原生约束求值与 CPU BakeMesh。

样本：60 组，其中 59 组为旋转、位移、均匀缩放和组合姿态，另 1 组非均匀缩放作为已知不等价的压力测试。每组检查 7 根派生骨、24 个实际网格探针，并比较第一轮与第六轮求值。另对 root_motion 加了 Unity 外层物体的平移／旋转／均匀缩放协变检查。

验收阈值：位置 0.02 mm、角度 0.05°、缩放向量误差 0.0002；非均匀缩放压力样本单独列出，不计为通过样本。

记录原始逐样本 JSON、提取 FBX、Blender 采样脚本、Unity 原型／验证脚本与 unitypackage。角度误差以双精度相对四元数 atan2 计算，避免 Quaternion.Angle 的小角度截断掩盖误差。Unity 2021.3.18f1 因本机许可证未激活未能运行，不计入支持版本。

生产代码尚未启用：先保留可复现证据和本草案，再实现图识别、契约字段、目标后端及默认 HoFBX 预处理回归。

## 参考

- [Blender Armature Constraint](https://docs.blender.org/manual/en/latest/animation/constraints/relationship/armature.html)
- [Blender Locked Track](https://docs.blender.org/manual/en/latest/animation/constraints/tracking/locked_track.html)
- [Unity ConstraintManagerUpdate](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/PlayerLoop.PreLateUpdate.ConstraintManagerUpdate.html)
- [Unity BakeMesh](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/SkinnedMeshRenderer.BakeMesh.html)
