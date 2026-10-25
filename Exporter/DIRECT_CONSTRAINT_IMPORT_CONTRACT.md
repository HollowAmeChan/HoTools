# 常用约束直通 IR 与三后端导入方案

状态：2026-10-25 契约设计，尚未修改生产 exporter／importer。本文替代上一份附着框架草案中“先识别整张三点图，才认领常用约束”的建议。上一轮的数值验证与边界仍然有效。

## 1. 分开三种判断

1. **IR 类型已知**：知道这是 Blender 的什么约束，原始语义能够明确描述。
2. **后端可处理**：目标后端支持这条约束的具体参数、空间、源与栈上下文。
3. **整体行为完整**：它依赖的骨、上游约束和通道也已经实现。

knownConstraints 不再等于“HoTools 生成的 Aux／MCH 约束”。手工创建的常用约束同样可以已知；后端不支持的设置也不倒退成 unknown。

| Blender 类型 | IR 分类 | 当前方案 |
| --- | --- | --- |
| COPY_LOCATION | 已知直通 | 保留原始参数、空间和目标 |
| COPY_ROTATION | 已知直通 | 保留原始参数、空间和栈序 |
| ARMATURE | 已知直通 | 保留源列表、原始权重、选项和绑定上下文 |
| DAMPED_TRACK | unknown | 没有显式生成关系时不认领 |
| LOCKED_TRACK | unknown | 没有显式生成关系时不认领 |
| 其他未有明确映射的类型 | unknown | 延续现有保守规则 |

即使已知类型存在缺目标、空源列表、非法数值或后端不支持的空间，也仍然是已知类型；在验证层报告“数据无效／后端不支持”，不能以缺省值静默执行。

## 2. IR 结构与迁移

建议发布 **schemaVersion=3**。v2 的 Unity 验证器明确只接受两种 relationType，不能在原版本号下悄悄加入新关系。

继续使用 knownConstraints，增加：

```json
{
  "ownerBone": "Follower",
  "relationType": "DIRECT_CONSTRAINT",
  "constraint": {
    "stackIndex": 0,
    "name": "Copy Location",
    "constraintType": "COPY_LOCATION",
    "targetObjectName": "Armature",
    "targetBoneName": "Target",
    "parameters": {
      "influence": 1.0,
      "mute": false,
      "owner_space": "WORLD",
      "target_space": "WORLD",
      "use_x": true,
      "use_y": true,
      "use_z": true,
      "invert_x": false,
      "invert_y": false,
      "invert_z": false,
      "head_tail": 0.0,
      "use_offset": false
    },
    "references": {}
  }
}
```

不新增与 knownConstraints 重复的 directConstraints 事实列表。认领顺序：严格 MCH → 显式 Aux 关系 → 剩余三类常用约束 → unknown。键仍是 `(ownerBone, stackIndex)`，不靠显示名称去重。

新 reader 同时接受 v2/v3。v2 保持原认领语义；v3 才接受 DIRECT_CONSTRAINT。旧 reader 拒绝 v3 并提示升级。不能只更新 exporter，让当前 importer 误收或静默漏项。

ARMATURE 的 references.targets 必须保留每项 target、subtarget、weight，包括 0.3 的原始浮点值。归一化属于求值规则，不覆写源数据；空列表、总和为零、非有限值需诊断。

绑定上下文必须对应最终导出的 FBX：相关 owner／source／parent 的静置矩阵、父级与导出身份、骨架对象空间，以及 MCH／应用姿态后的映射。通用 IR 不提前把 ARMATURE 改写成 ParentConstraint。

## 3. 三后端对应表

| IR 原类型 | Standard：Unity 内置 | HoAux：单一 HoRig 中控 | VRC：SDK 原生约束 |
| --- | --- | --- | --- |
| COPY_LOCATION | PositionConstraint | 新 CopyLocation 操作 | VRCPositionConstraint |
| COPY_ROTATION | RotationConstraint | 新 CopyRotation 操作 | VRCRotationConstraint |
| ARMATURE | 多源 ParentConstraint 的刚性映射；满足条件才可标等价 | 新 Armature 操作，计算原始 Blender 加权矩阵语义 | 多源 VRCParentConstraint 的刚性映射；满足条件才可标等价 |
| 未标记 DAMPED_TRACK／LOCKED_TRACK | 跳过并展示 unknown | 跳过并展示 unknown | 跳过并展示 unknown |

以上是适配目标，不是所有参数均已实现。Standard／VRC 的刚性 Parent 映射是一个有边界的后端契约，不能把它宣传成任意 ARMATURE 的无损直通。已知类型与等价性报告分离。

### 3.1 Copy Location

首批直接映射：WORLD→WORLD、XYZ 全开、无反相、head_tail=0、无 B-Bone、Offset 关闭。influence 原值保留，由后端按约束前输入混合；静音按不执行处理。

约束激活时保持 **零偏移**。现有 MCH／Fan 装配路径会烘保持偏移，不能原封不动复用；COPY_LOCATION 的 Replace 不应变成“保持初始距离的跟随”。

部分轴、反相、Local／Pose／Custom 空间、head_tail 和 Offset 应逐项增加适配与数值测试；在支持前预览明确列为已知但不支持，不丢掉原始字段。

### 3.2 Copy Rotation

首批直接映射：WORLD→WORLD、XYZ 全开、无反相、REPLACE。原始 Euler order 保留；不能据此把其他模式自动改为 Replace。

全影响度、单条约束可以映射到单源 RotationConstraint，零旋转偏移。若 FBX 导入后 source／owner 使用不同的局部轴基底，需要补偿 helper，不得直接复制不等价的本地数值。

顺序约束不能作为彼此无关的组件随意叠加：

```text
R0 = 约束前朝向
R1 = blend(R0, target_A, t1)
R2 = blend(R1, target_B, t2)
```

Standard／VRC 使用阶段 helper 保留上一阶段输出；只在已证明可等价折叠的情形减少 helper。例如第一条 t1=1、第二条 t2=t 的两条全轴 Replace，可候选为双源 `(1-t,t)`；前一轮只实测 t=0.5，其他 t 值需补测试。

Ho 后端在虚拟姿态缓冲区按 stackIndex 顺序执行。Add、Before／After Original、部分轴和跨空间是独立能力，不能因同属 COPY_ROTATION 就宣称支持。

### 3.3 Armature 与多重父级

它在概念上属于多源绑定／多重父级，但在线性混合、Preserve Volume／Envelope 关闭的情况下，Blender 的原始运算是加权骨变换作用于约束前的 owner：

```text
D(t)     = Σ normalize(w_i) · M_i(t) · inverse(B_i)
M_out(t) = D(t) · M_pre(t)
```

源矩阵、owner 的约束前父级、前序约束以及 Preserve Volume／Envelope 等选项都参与语义。完整结果可能包含缩放或剪切。

一个简单反例：两个源分别绕同轴 +60°／-60°、各权重 0.5。矩阵线性混合可以让该平面方向缩为 0.5，而只混合位置／旋转的 ParentConstraint 不会自动产生这一缩放。Unity 官方也明确 ParentConstraint 不影响缩放。

**Standard 契约：**

- 对刚性多父级映射，建立所有 source、归一化权重和每源绑定偏移。不能把多源 weight 合并成总体 influence，也不能给所有 source 相同默认权重。
- 不用 Add Parent→Activate 代替正确的绑定数据；逐源偏移必须来自配套静置状态。
- 固定绑定点、刚性 source、且仅消费点位置时，可以建立位置等价的子集；按绑定偏移得到每源候选点，再加权位置。该路径不声称参考骨完整矩阵等价。
- 动态 M_pre、Preserve Volume、需要保留的混合缩放／剪切等不在简单 Parent 映射的等价子集内。计划必须标为 `NativeApproximation` 或 `Unsupported`，而不是 `Unknown`。

**Ho 契约：**

- 给现有中控增加独立的 Armature 操作，不复用只维护刚性偏移的 Parent 操作。
- 同一 rigSpace 计算每源 bind inverse、原始权重的归一化、owner 前序状态，物体到世界的变换只施加一次。
- 在虚拟矩阵缓冲区保存仿射结果，避免中途转 Quaternion／TRS 丢失信息；仅在写回实际 Transform 时处理可表达性。
- 若最终结果存在不能由既定层级表达的剪切，不能把简单 TRS 分解当作已证明等价。v1 可以先支持可表示结果；位置-only 的优化必须由消费者分析或显式语义确认，不能根据 REF 名字擅自丢通道。
- 上一轮已证明的是该工程四个点的位置求值与下游组合，并未证明完整通用 Armature 骨矩阵。

**VRC 契约：**

- 使用 VRCParentConstraint 的逐源 offset／weight，或在位置等价子集中使用辅助点＋VRCPositionConstraint。
- 仍保持集中挂点＋TargetTransform 指向被驱动骨的现有结构，生成 helper 则另外记录所有权。
- 不附带运行时 C#。动态 M_pre 的精确重建可研究 SolveInLocalSpace 的辅助层级，但在 SDK 实测前不列入 Exact。
- 若本次预览采用刚性 Parent 语义，明确显示其与 Blender Armature 的差异；不能因为组件存在就标为无损。

## 4. UI 与依赖处理

导入计划至少区分：

- `Exact`：当前参数与上下文已有等价实现与测试。
- `NativeApproximation`：类型可对应，但采用目标原生刚性语义，差异明确列出。
- `Unsupported`：类型已认识，但设置或上下文不可处理。
- `Invalid`：缺引用、非法数值、循环依赖等数据问题。
- `Unknown`：当前没有认领该原始类型／生成关系。

静音与零影响度另标为不执行。不能把 Unsupported／Invalid 再塞回 Unknown。

WTD 样例按新认领规则应当得到 **9 条 DIRECT_CONSTRAINT、4 条 unknown**：4 个 Armature、3 个 Copy Location、2 个 Copy Rotation 已知；两组 Damped／Locked 共 4 条继续 unknown。

这并不代表整套胸前饰品已经能够完整导入。DIR 的旋转仍依赖 unknown，最终 Copy Rotation 只能复制 Unity 当前实际存在的 DIR 朝向。预览应提示“上游旋转未实现”；手工在 Unity 补过对应 Aim 后，也可以由这两条已知复制约束继续工作。

同一 owner 上存在 unknown 的栈屏障时，不能把它前后的已知操作擅自重排、折叠；必要时将相关段标为 Unsupported 上下文。循环、缺目标和部分导入的数量必须明确展示。

## 5. Ho 中控执行与生成资源的管理

扩展 HoAuxRig 时保留现有组件／序列化值兼容；可以逐步把界面称为 Ho Rig，但无需为了三类直通另造一个中控。

新操作需要 stackIndex、源列表、绑定上下文和显式基础姿态策略。现有 RestoreOwnersToBindPose 是 Aux 骨的固定输入语义，不能直接用于每帧被 Animator 驱动的通用 owner。v1 可先限制 owner 无独立动画，保留其动态父级；支持动画 owner 前需解决输入快照与上一帧输出反馈。

Standard／VRC 的阶段 helper、偏移 helper 和约束挂点都需要导入标记、导出身份和回收规则。重导入、切后端、撤销时只清本工具生成的数据，保留手工组件及用户加到 helper 上的内容。

VRC 桥目前只覆盖 Parent／Rotation，且 sources 接口未充分表达逐源权重；需增加 Position、带权 source、明确 offset 语义。统一调用 ApplyConfigurationChanges 并记录 Prefab override；不能用烘保持偏移的 Activate 覆盖 Copy 的零偏移。

## 6. 未来三点工具的标记

未来快速生成工具只补“复杂组合的语义认领”，不是这三类常用约束获得 known 身份的前提。

优先使用持久的 Ho 骨属性，与现有 Aux 做法一致：`kind / version / graphId / role / sourceBones / involvedBones / constraintNames`。左右框架的 origin、aimTarget、upTarget、带符号轴必须显式记录。

约束显示名称可作为可读标签或受限旧版迁移线索，不作为唯一稳定身份。手工重命名后仍应靠属性和关系确认。无标记的 Damped／Locked 不因名字类似或恰好挨在一起就自动被拼成 Aim。

有合法生成标记后再新增 frame 的已知关系／解析器，认领相应跟踪约束；坏标记、缺引用或被编辑破坏的生成关系需要诊断，不能静默补猜。

## 7. 实施位置与验收顺序

1. Blender：ConstraintIR 的 v3 版本与已知类型注册；ConstraintIRExporter 在 MCH／Aux 后认领三类通用约束，并补多源、绑定上下文与无 RNA 的测试序列化。
2. Unity 事实层：ConstraintConfig 读取 references.targets／Armature 参数／绑定上下文；验证器接受 v2/v3 和受限 DIRECT_CONSTRAINT，仍检查分类唯一性。
3. Unity 计划层：新增 CopyLocation／CopyRotation／Armature 计划项与每后端能力状态；Unknown 不作为后端不支持的兜底类型。
4. Standard／VRC：先接全轴 world copy 的零偏移与顺序 helper，再接明确的 Armature 刚性映射及能力提示；Ho 后端补独立操作和基础姿态策略。
5. 数值回归：复制约束的 influence 0／0.3／0.5／1、两条以上栈序、非零初始偏移、动态父级、不同轴基底；Armature 的单源／多源、非归一化权重、动态 owner pre-state、缩放／剪切反例；Damped／Locked 保持 unknown。
6. 集成回归：真实 HoFBX 默认姿态／MCH 预处理、重复导入、切三后端、Prefab 序列化、撤销和安全清理。VRC 没有 SDK／运行时证据时状态仍是未验证，不拿 Unity 原生结果替代。

本设计不把未来 frame 工具列为本轮前置条件，也不因为三类类型直通就承诺支持任意参数与任意 Blender 约束。

## 参考

- [Blender Armature Constraint](https://docs.blender.org/manual/en/latest/animation/constraints/relationship/armature.html)
- [Unity Parent Constraint](https://docs.unity3d.com/6000.0/Documentation/Manual/class-ParentConstraint.html)
- [VRC Constraints API](https://creators.vrchat.com/common-components/constraints/constraints-api/)
