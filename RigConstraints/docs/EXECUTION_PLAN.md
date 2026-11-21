# 普通 Rig 约束 IR 与辅助骨登记重构执行计划

日期：2026-11-21（Asia/Shanghai）

状态：执行中；先独立提交本文，再建立目标并按阶段实施。

范围仓库：HoTools（Blender）与 HoUnityTools（Unity）。本文是本轮执行和验收的主记录。

## 1. 目标和非目标

将现有普通 Rig Constraint IR v3 重构为三层关联数据：Blender 源事实、可验证语义、Unity 实现契约引用；另维护一份机器可读的实现注册表。全类型目录、导入预览、执行规划、测试矩阵和覆盖率使用相同条目。既有数值实现和兼容行为保留并迁移，不一次性重写所有求值器。

同时补齐普通辅助骨的作者态生命周期：生成时在 owner 骨的 HoTools 属性中登记有序约束语义组；删除或清除身份时注销；骨架数据属性页提供手动完整性审查。

本轮明确排除：

- `BoneTools/hoAux/` 大型复杂辅助骨模块、其独立 Source IR、Driver/FCurve、未来导出后端；不迁移、不桥接，不改变其生成规则。
- 为全部 Blender 约束立即实现 Unity 求值；未实现的类型和参数域必须有明确状态。
- 自动监测改名、自动修复引用、按相似名称或类型猜测接回、常驻 depsgraph 同步。
- 在用户打开的角色工程中批量改写资产、保存用户 `.blend`、更换既有绑定或清理无关文件。

普通 Twist/Fan/Aim/MCH 与 Unity 现有 HoAuxRig 后端属于本轮；它们不等于上述被排除的 Blender 大型 HoAux 模块。

## 2. 已确认的现状

- `Exporter/ConstraintIR.py`、`ConstraintIRExporter.py` 保存 v3；`knownConstraints/unknownConstraints`、`aimBindings`、`mchBindings` 混合了事实与关系分类。
- `BoneTools/boneProperty.py` 已有 `auxBone`、关联骨及 owner 局部 `constraintNames` 登记，以及统一生成/清理入口；新逻辑不能继续堆入此文件。
- Twist 已一次登记 Copy Rotation + Stretch To；Fan 三种变体共享生成路径；Aim 显式接纳 Damped Track + Locked Track；MCH 在导出副本中生成 Child Of。
- Unity 当前三类 Direct 是 Copy Location、Copy Rotation、Armature；MCH/Twist/Fan/Aim 有既有组合路径。参数域、栈屏障、输入姿态和写回限制必须保持明确。
- Unity 当前固定字段 DTO 不能充当所有未来原始参数的无损载体；新增源事实表示必须保留未知字段。
- Unity 仓库现有未跟踪 `Editor/HoCamera.meta`、`Runtime/HoCamera.meta`；Blender 工作区可能有用户编辑。每次提交只暂存本轮明确文件。

## 3. 目录和所有权

Blender 新建独立公共包，按实际职责分批增加文件，不预建空模块：

```text
RigConstraints/
  __init__.py                 # 稳定公开入口，不触发 bpy 注册
  model.py / codec.py         # 纯数据与无损 JSON
  registry/                  # 唯一权威目录/语义/实现契约和读取器
  source/                    # 当前 Blender 事实采集
  semantics/                 # 基础翻译与有版本的组合规则
  binding/                   # 作者态到最终 FBX 的身份/矩阵映射
  validation/                # 结构、引用、组完整性、能力/规划
  blender/                   # PropertyGroup、登记生命周期、手动审查 UI
  compat/                    # v2/v3 和旧 aux 元数据适配
  tests/                     # 纯 Python 测试
  docs/                      # 本计划、契约、自动生成的覆盖表
```

`boneProperty.py` 保留既有公开类/函数名和注册接线，委托新包完成新职责；旧模块不被突然删除。`Exporter` 负责导出时序与文件写入接线，不持有第二份语义/后端规则。

Unity 使用 `Runtime/RigConstraints/ConstraintIR/` 存放纯数据/codec/版本契约，使用 `Editor/HoFbxImport/ConstraintIR/` 存放 registry 校验、规划和适配。既有 runtime 求值器继续位于现有分目录。导入窗口和 `HoDirectConstraintImporter` 逐步变成外观/兼容层，不再追加大型分支。

## 4. 必须冻结的数据契约

### 4.1 源事实

- 新格式沿用 `schema=hotools.rig-constraint-ir`，新增 `schemaVersion=4`。v2/v3 继续可读并保持原解释。
- `sources[]` 统一保存每条原始约束一次：快照局部 sourceId、owner、原始类型、栈位置、全部可序列化参数、对象/骨/集合引用以及源版本。
- 不再按 known/unknown 物理分开源事实；未知参数及未来原始类型在两端往返保留。
- sourceId 仅保证本次快照唯一，不承诺任意改名、重排后的稳定约束身份。
- 声明 `captureStage`。作者态事实应在 MCH/骨轴预处理前捕获；最终 FBX 引用、父级、rest/bind 矩阵、骨轴和 MCH 重定向放入独立 binding overlay。过渡快照若只代表预处理后状态，必须明确标记，不能伪称作者态。
- 不采集被排除的大型 HoAux owner 的约束；边界检查不得给其写属性或调用其导出器。其他普通约束的外部依赖保留事实并明确诊断。

### 4.2 语义

- `semantics[]` 使用 `sourceIds[]` 引用源事实，包含语义 ID/版本、翻译规则 ID/版本、来源证据、参数、读写通道和必要的顺序/依赖。
- 基础语义与用途注释分开。按本轮后续作者入口决定，新增 Copy Rotation 必须从普通辅助骨 `copyR` 入口创建并当场登记；未登记的手工 Copy Rotation 保留事实并显示 Unknown，不在审查/导出时猜测补写。旧 v2/v3 已导出数据维持原解释。
- 组合规则统一登记：Twist=Copy Rotation + Stretch To；Aim=Damped Track + Locked Track；Fan 和 MCH 迁移为相应规则。Aim 不再拥有特殊顶层数据通路。
- 组合是否成立由结构契约验证。原始成员永远保留；选用组合执行时禁止同时执行其原子实现。
- UnknownSemantic、Invalid、完整但后端不支持分别报告；不得因无法装配而删除源事实。

### 4.3 实现注册表与第三列

- 注册表唯一权威源随 Blender 包维护，Unity 分发生成副本并验证版本/摘要；两端不能各自手工维护不同规则表。
- 条目包含 implementationId/contractVersion、支持的语义版本、backendId、结构化参数域/上下文条件、宿主能力要求、生成物及所有权、保真范围、失败/fallback 策略、测试引用和验证证据。
- 导出产物中的实现引用与最终导入计划只允许引用已注册契约；禁止执行 JSON 内任意脚本、反射类型名或命令。
- 区分文件 schema、语义版本、翻译/registry 版本、实现契约版本。输入指纹覆盖实际源参数/语义/绑定，排除 exportTime 等易变字段。
- 将翻译状态、实现可用性、Exact/Approximate 保真声明、Untested/Passed/Failed 证据分开；静音/零权重属于执行状态。
- 默认不将 Exact 静默降级为近似。找不到固定契约、版本不符或输入指纹过期时报告原因并保护现有装配。
- preview 和 apply 使用同一计划；运行环境差异必须在装配前重新校验。

## 5. 作者态登记与删除

- 在 `hotools_boneprops` 增加可扩展的普通约束语义组集合；旧 `auxBone` 字段在兼容窗口保留。
- 组记录最少包含登记版本、语义 ID/版本、生成来源、成员角色、owner 局部约束名、预期类型/顺序与语义所需关联信息。
- 不在骨属性中镜像一整份实时原始约束参数。事实始终读取当前 Blender 数据，允许编辑的 influence、静音等按各契约处理。
- 统一登记 API 由实际生成器调用；Twist 两条成员一起提交，Fan 继承路径复用，Aim 显式接纳，MCH 在导出副本生成完成后登记。
- 老文件通过只读兼容解释或显式迁移接入；打开、审查或导出不能偷偷把未知记录重建为新语义。
- 删除整个 Bone 时登记自然消失；保留 Bone 的清除/移除通过统一 reset/unregister API 清理对应登记，不能删除用户未登记约束。
- 不建立第二份永久骨架级登记清单。审查缓存按具体 Armature Object 隔离，同一 Armature datablock 的不同对象不能串结果。
- 其他存活骨对被删骨的悬空引用由审查报告，不自动改写。

## 6. 骨架级手动审查

- Properties → 骨架数据，同级新增默认折叠的“HoTools 约束 IR 审查”。
- 明确“检查/刷新”按钮和上次检查时间；draw 不扫描全骨架，不注册常驻同步 handler。
- 汇总及折叠列表：损坏、已知、Unknown。详情只需 owner 骨、约束/组合名、原因和定位骨骼入口。
- 检查缺失/失配成员、错误类型、必要顺序、重复认领、关联骨/目标丢失、无效版本和组合契约；不按名称相似或栈位置自动接回。
- 元数据完好、语义已知、Unity 可执行是不同判断。没有 Ho 标记的普通已知约束不能一律归 Unknown。
- `generateMCH` 只是导出生成计划，当前没有 MCH 骨不算损坏。
- 明确排除大型 HoAux 模块；其记录不混入本轮 Unknown 或损坏统计。

## 7. 阶段、提交和完成定义

每阶段结束更新本文证据并提交本轮文件；跨仓库提交记录对应哈希。用户已经授权实施，不再逐阶段请求许可。

### P0 执行计划

- [x] 本文独立提交，记录基线与范围（本提交）。
- [x] 提交成功后创建目标模式 objective；不设置用户未要求的 token budget。

### P1 公共契约与全类型目录

- [x] 新包、v4 纯数据 model/codec/校验、无损未知字段。
- [x] 按 Blender RNA 建全约束类型目录，标记 owner 适用域；未实现语义明确 Unknown。
- [x] 注册已有 Direct/MCH/Twist/Fan/Aim 语义和三后端契约；分开当前实现和验证证据。
- [x] 从同一 registry 生成可读三列表/实现表/覆盖进度，测试确保生成物不漂移。

### P2 普通辅助骨登记与清理

- [x] 新元数据组和统一生命周期 API，兼容旧 PropertyGroup/测试最小对象。
- [ ] Twist/Fan/Aim/MCH 实际生成接入；更新和重复生成不重复登记（前三项已完成；MCH 导出 caller 在 P5 接线）。
- [x] 清除身份、移除生成物、一键删除清理闭环；旧数据不自动修复。
- [x] 普通辅助骨额外功能新增 `copyR`，直接作用于选中的既有 owner，创建 Copy Rotation 同时登记语义；入口、分组、启停与删除沿用普通辅助骨工作流。删除仅移除登记约束和语义，保留原骨、父级、静置姿态与权重。

### P3 手动审查面板

- [ ] 可测试的只读 scanner 与分类、对象级临时缓存。
- [ ] 骨架数据折叠面板、手动刷新、计数/原因/定位、未检查状态。
- [ ] 用户改名/删除/重排/缺目标及 MCH 计划的正反例；复杂 HoAux 被排除。

### P4 Unity v4 消费与兼容规划

- [ ] 无损 v4 reader、registry 摘要/契约校验、v2/v3 兼容适配。
- [ ] 新计划表达三列并迁移已有后端装配；未知/不适用/未验证原因可追溯。
- [ ] 保持未知栈屏障、依赖/环、旧层反馈边界、所有权、安全清理、回滚和 prefab 序列化。
- [ ] 拆目录后更新隔离测试复制范围，确认实际编译新代码。

### P5 HoFBX 接线与端到端

- [ ] 预处理前源快照、预处理后 binding overlay、版本化实现引用输出。
- [ ] 两端 reader/writer 及现有三后端端到端通过后才默认写 v4；保留明确 v3 兼容选项。
- [ ] 验证新格式包含所有源事实、组合引用、固定实现和完整诊断；重导入不重复创建。

### P6 裙子用例与最终验收

- [ ] HoAux 通用 Copy Rotation 分别实现 LOCAL→LOCAL 和 LOCAL_OWNER_ORIENT→LOCAL；保留原 WORLD 契约。
- [ ] 不同静置骨轴、左右、动态父级、0/.3/.5/1 influence、连续栈、MCH/FBX 骨轴、序列化和首帧/稳定帧数值验证。
- [ ] Standard/VRC 未实现的新空间继续明确 Unsupported；不为整类约束虚标 Exact。
- [ ] 更新使用文档、覆盖矩阵、迁移说明和阶段证据；全部必需回归通过才标记目标完成。

## 8. 验证方法

- 纯 Python：codec 往返、未知字段、版本/重复 ID/悬空引用、registry 一致性、组合重叠和状态判定。
- Blender 4.5.8/5.2：后台 factory-startup 创建合成骨架，生成/重复生成/保存重开/删除/手动编辑/审查/导出；不保存用户源工程。
- 既有重点：`Exporter/tests/test_constraint_export.py`、`test_constraint_ir_v3.py`；`tests/test_blender_aux_constraint_ownership.py`、`test_blender_constraint_ir_v3.py`、`test_blender_rig_constraint_export_e2e.py`、`test_blender_fbx_mch_local_rotation.py`、`test_blender_fbx_constraints.py`。
- Unity：新隔离项目使用现有 `Tests~/ConstraintIRV3/Run.ps1` 的 fixture/运行时数值方式扩展 v4 回归；不启动或保存 BreakWarudo 用户场景。
- 数值参考来自 Blender 实际求值，不能由被测 Unity 实现自己生成预期值。基准目标：位置 1e-4 m、旋转 0.1°、可表示缩放 1e-4；退化/剪切/非均匀缩放按契约拒绝并测试诊断。
- VRC shim 只证明装配/序列化，真实 SDK/客户端缺证据时保持 Untested，不能宣称已验证等价。
- UI 验证注册/注销和布局逻辑；若无法在当前实际 Blender UI 完成视觉验证，明确记录该限制，不伪造截图/通过结论。

## 9. 实施记录

| 阶段 | 状态 | 提交/测试证据 |
| --- | --- | --- |
| P0 | 已提交，目标 active | 文档提交 `22f1234b`；Blender 基线 `7b17a08f`；Unity 基线 `b406882` |
| P1 | 已提交 `d3ee3d41` | 29 类型、7 语义、23 实现契约；17 项 codec/registry 测试通过；coverage --check 通过；LF 固定避免摘要漂移 |
| P2 | 作者态及 copyR 完成（本阶段提交）；MCH caller 待 P5 | Blender 4.5.8/5.2.0 `CONSTRAINT_METADATA_OK`、`COPY_R_OK`；旧 ownership/v3/e2e/bone_pose_operations 两版 8 项通过；精准启停/删除不动既有骨与手工约束；元数据成员定义复用 registry |
| P3 | 代码完成，分步验证/提交中 | Blender 4.5.8/5.2.0 `CONSTRAINT_REVIEW_OK`；记录在后续提交 |
| P4–P6 | 实施中 | Unity 无损 reader/适配与局部旋转数值验证并行推进；尚未切默认 v4 |

失败后先读取实际状态再修复；不盲重试写入。不提交用户既有改动、私有模型、商业源码、临时测试产物或运行时缓存。

### 开发前测试基线

2026-11-21，Blender 4.5.8 LTS 与 5.2.0 LTS：`test_blender_aux_constraint_ownership.py`、`test_blender_constraint_ir_v3.py`、`test_blender_rig_constraint_export_e2e.py` 均通过。`test_blender_fbx_mch_local_rotation.py` 两版均在第 263 行发生既有 StopIteration：该测试仍从 unknownConstraints 寻找已被 v3 归入 knownConstraints 的 ARMATURE。实施时修正此滞后预期并继续完成其数值断言，不能把原有失败归因于本轮代码。

### 作者入口补充（2026-11-21）

用户要求普通辅助骨新增 copyR 类型，避免通过手工添加再补登记。auxType=`COPY_R`，显示名=`copyR`，复用 `COPY_ROTATION@1` 语义并记录生成器 `hotools.aux.copy_r`。必须在操作成功时整体登记，不产生中间 Unknown 再修复。现有骨的接纳与工具生成骨的所有权分开，组记录 `ownsBone`；copyR 和显式接纳的 Aim 为 false，删除原骨只对确实由生成器拥有的骨生效。此条覆盖早先“手工复制旋转自动基础翻译”的建议，不改变旧格式行为。
