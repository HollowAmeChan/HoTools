# 普通辅助骨、copyR 与约束 IR 审查

本说明对应普通 HoTools 辅助骨与 HoFBX。大型 HoAux 模块、Driver 和其未来导出不在此流程中。

## 裙子根跟随大腿

1. 选中骨架，在姿态或编辑模式选中需要跟随的裙子根骨。
2. 打开 HoTools → 骨骼工具 → 辅助骨 → copyR。
3. 目标选择同骨架的大腿骨；默认 Target=`Local Space (Owner Orientation)`、Owner=`Local Space`，调整跟随强度。
4. 点击创建／更新。工具创建 Copy Rotation，同时把其身份、角色、版本和名称登记到该骨的 HoTools 语义组。
5. 使用 HoFBX 导出配套 FBX 与约束 JSON；Unity 使用支持 v4 的 HoTools 并选择 HoAux 后端导入。

copyR 不创建额外骨，不改变原骨的父级、静置方向或权重。默认只负责 XYZ 全轴、Replace 的旋转跟随。Local 和 Local Owner Orientation 是不同语义：前者复制各自骨轴的局部旋转，后者补偿两根骨的静置轴差异。父级的运动仍各自由骨架继承，不把目标父级的独立运动重复复制到 owner。

当前作者入口在每根 owner 上管理一条 copyR，重复执行会更新这一条。IR 和运行时可表达有序多条旋转操作；多实例作者 UI 不属于本轮入口。

新局部契约要求作者 owner 为中立静置输入且无独立动画，owner／target 都开启旋转继承、使用 FULL 缩放继承；来源和父级可以动画。若应用姿态或 owner 的 MCH 预处理改变了原始局部参考，Unity 会报告不支持的重放条件。开启“应用约束”将结果固化到 FBX 时，也不能再次把同一约束导入运行，否则会重复作用。

Unity HoAux 通用约束的骨架根及其祖先需保持正均匀缩放和有效 TRS。零缩放、负缩放、非均匀或剪切会暂停该求值并报告原因；恢复有效变换后可继续。

copyR 的移除和普通辅助骨总览中的分组／全部移除，会保留用户原骨和权重，只删除准确登记的生成约束及对应登记。启停只作用登记成员，不静音同骨上的手工约束。遇到登记损坏会拒绝批量删除，请先检查原因。

需要新 Copy Rotation 时请使用 copyR 入口。手工创建的 Copy Rotation 仍作为原始事实保留，但在新作者流程中不会自动被接管或补登记为 copyR。旧 v2/v3 文件保持原解释。

## 骨架级检查

打开 Properties → 骨架数据 → **HoTools 约束 IR 审查**，退出编辑模式后点击“检查 / 刷新”。结果分为：

- **损坏**：已登记成员缺失／改名／类型不符、顺序或角色错误、重复认领、目标或关联骨缺失等；列表说明原因。
- **已知**：当前事实和登记可解释为某个语义。此状态不代表所有 Unity 后端均有实现。
- **Unknown**：源事实保留，但当前没有适用语义翻译。未登记的手工 Copy Rotation 也在这里。

点击骨骼图标可定位 owner。检查只读，不改变姿态、参数、名称或登记。面板显示上次检查时间；手工修改后重新点击刷新。它不注册自动同步或自动修复。共享 Armature datablock 的多个对象分别保存检查结果；工具修改共享登记会使相关缓存失效。

勾选 `generateMCH` 只声明导出时生成 MCH，源工程中没有 MCH 骨不算损坏。大型 HoAux 生成骨单独计数为排除，不混入本轮 Unknown 或损坏列表。

## 导出和导入结果

HoFBX 的 JSON 选项可明确选择约束 IR 版本。v3 用于兼容旧导入器；v4 保存三层关联信息：

1. **sources**：作者实际约束及参数、目标与顺序；未知类型也保留。
2. **semantics**：已登记的 Twist、Fan、Aim、MCH、copyR 组合／操作，以及可直接翻译的基本约束，均引用原始 source。
3. **implementationBindings**：各 Unity 后端的实现 ID、契约版本与选择策略。

最终骨名、MCH 目标替换、父级、静置矩阵和 FBX 骨轴另存于 binding overlay；不会覆盖作者原始目标。不要将另一份 FBX、应用姿态或 MCH 处理前后的 JSON 混用。

Unity 预览按选择的后端显示适用实现、保真范围和失败原因。源文件、注册表、契约或绑定不匹配会在清理既有装配前被拒绝。重导入仅处理工具登记的组件和 helper，保留手工内容。成功导入保存实现选择及源指纹，供之后追溯。

Standard／VRC 的某些映射只能近似 Blender。默认不自动采用近似；需要时在 HoFBX v4 明确开启“允许原生约束近似”，产物会记录这一策略。Twist／Fan 的既有 legacy 契约单独记录，不能据此认定其所有参数域精确等价。VRC shim 测试也不等于真实 SDK／客户端数值验证。

## 维护者入口

- 执行与验收：[EXECUTION_PLAN.md](EXECUTION_PLAN.md)
- v4 字段、版本与指纹：[FORMAT_V4.md](FORMAT_V4.md)
- 自动生成的全类型／实现／进度表：[COVERAGE.md](COVERAGE.md)
- 更新覆盖表：`python -m RigConstraints.registry --write`
- 检查表漂移：`python -m RigConstraints.registry --check`
- 输出实现／条件／测试入口和观察轴的机器可读矩阵：`python -m RigConstraints.registry --matrix`

注册表是唯一权威源，Unity 按字节分发同一文件。增加实现时需要登记参数域、上下文条件和测试证据；单纯增加类型行不计作功能已完成。
