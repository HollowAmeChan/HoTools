# MC2 实施与验收执行计划

更新日期：2026-07-16

源码基线：`D:\Unity_Fork\MagicaCloth2`，MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

本文只维护新 `physicsWorld.mc2` **尚未完成工作的顺序、输入和退出条件**，不再保存已完成能力的流水。当前真实完成度见 `MC2_ACCEPTANCE_MAP.md`，历史过程见 Git。

## 写作边界

- **应该写**：仍未完成的交付、执行顺序、所需输入、退出条件、测试环境和提交约束。
- **不应该写**：已完成能力的长篇描述、完成度结论、源码公式/陷阱、稳定架构契约、逐提交记录或临时测试数字。
- **内容路由**：真实完成度写`MC2_ACCEPTANCE_MAP.md`；源码语义、边界特化、差异和冲突写`MC2_SOURCE_DATAFLOW_WORKSHEETS.md`；公共架构写`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；已关闭工作的过程只留Git。
- **删除原则**：某项退出条件关闭后，从本文执行表移除，只在验收总表保留结论；不得改写成“最近完成”章节。

## 文档路由

| 文档 | 唯一职责 |
|---|---|
| `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` | Physics World 跨 solver 架构、生命周期、声明、exchange 与 writeback 公共契约。 |
| `PHYSICS_WORLD_IMPLEMENTATION_STATUS.md` | 各 domain 的一页式当前状态与全局优先级。 |
| `MC2_ACCEPTANCE_MAP.md` | MC2 每个能力切片的真实完成度、对齐结论、证据和 V1-R 阻塞。 |
| 本文 | MC2 当前未完成工作的执行顺序与退出条件。 |
| `MC2_SOURCE_DATAFLOW_WORKSHEETS.md` | 固定 MC2 源码事实、危险顺序、Blender 特化、故意差异与冲突处理。 |
| Git | 提交过程、历史阶段、已经关闭的临时问题和测试流水。 |

状态冲突时不选择较乐观的描述：先把验收总表对应项降为“实现完成/证据缺口”，再按固定 MC2 source、Tier A oracle、公共架构契约和生产链依次核账。

## 固定范围

当前目标是 `V1-R` restricted realtime，并在删除旧实现前取得明确的**替代资格**：

- 一个公开`mc2` solver step一次收集并处理当前输入中的全部对象/task；MeshCloth、BoneCloth、BoneSpring三种setup共享调度与结果事务，但每个active task独立持有slot/native context。MC2 component在HoTools中的产品映射是“粒子参数profile + task”的组合，不暴露为多个component step。
- 单 final-proxy Mesh、双对象 BasePose、Bone Line 安全域、外部 Point/Edge collider、单 cloth self collision。
- Mesh 发布 object-local GN offset；Bone 发布 stable bone identity 的 parent-local transform plan；真实 Blender 写入只由公共 writeback 执行。
- Python 只拥有 Blender snapshot、immutable spec、slot/context 生命周期、packing、result transaction 和 debug；数值 solver 只有 C++ 一份。
- 新实现不仅要对齐固定MC2 source，还要覆盖HoTools旧产品实际依赖的语义，证明真实生产链可替代、性能不退化、代码边界可维护，并在文件级不依赖待删除实现。

以下不进入本轮验收：Bake、通用力场、Bone imported triangle、MC2 reduction/render mapping。它们保持 inactive/rejected，不能借由邻近能力宣称支持。跨物体self collision已进入替代资格审计，不再作为未来项绕过。

## 当前执行顺序

状态只在 `MC2_ACCEPTANCE_MAP.md` 修改；本表只规定下一步和结束条件。

| 顺序 | 对应项 | 工作 | 退出条件 |
|---|---|---|---|
| 1 | D-01 | 建立与SpringBone VRM蓝本同型的全隐式MC2 debug链。debug请求自动发现world内MC2 slots，不要求用户为中间约束接线；按请求在下一推进帧读取backend真实中间态，并由solver-owned renderer按语义层筛选绘制。 | 至少覆盖Bone纵/横连接与分组、Fixed/Move、普通/自碰半径、自碰primitive/grid/candidate/contact/intersection、MaxDistance/Backstop、teleport判定、Center/world/local变换抵消、负缩放、外部碰撞和writeback目标；关闭debug时无逐帧readback。 |
| 2 | P-05 | 完整审查新实现的实际运行链、代码组织与数学层，并执行不改变行为的纯整理。逐功能区确认生产入口、静态/逐帧路径、状态所有权、异常/重建/释放、死代码和测试专用路径；合并无意义参数转发层、过碎文件、同名math包装和重复buffer/helper。 | 审查矩阵覆盖三setup与公共runtime；不存在“测试可达但生产不可达”的能力；纯整理前后fixture、生产资产和性能结果一致；内部调用直达唯一实现，保留的wrapper都具有真实边界职责。 |
| 3 | P-06 | 建立新旧同资产、同帧、同参数的性能对比，并据数据审计Python/C++边界；K-06已冻结的单cloth/自动跨物体scope基准作为输入，不再重开ListObj产品决策。分别测量首次构建、静态重建、逐帧prepare/pack/native sync/step/debug readback/result readback/writeback、内存与分配。 | 代表性小/中/大资产有可重复基线；新实现逐帧性能不得劣于旧实现，目标是有明确优势；所有热点都有保留Python、批量化或迁入C++的书面决定和验证结果。 |
| 4 | P-07 | 完成文件级与ABI级独立化。区分可保留的共享数值kernel与必须删除的旧node/package/context/ABI，并把共享代码移交给新owner。 | 新registry、节点、生产runtime、测试和构建不import/加载旧Python package、旧context或旧公开ABI；保留的C++ kernel已归入新命名与所有权，删除候选清单可机械核验。 |
| 5 | P-08 | 执行替代资格总门禁。使用代表性真实资产复验产品语义、数值、生命周期、debug、性能、错误域和用户工作流。 | P-04..P-07及K-06/K-07/D-01全部关闭；不存在未决的必须保留旧特化；新实现相对旧实现至少具备产品灵活性、可观测性、架构可维护性和实测性能优势，形成明确的“允许删除”结论。 |
| 6 | P-09 | 独立提交删除旧MC2实现与旧入口。 | 删除后完整Python 3.13、Blender 5.1、Tier A、代表性资产、debug、混合soak和性能门禁通过；仓库搜索无遗留入口或fallback。 |
| 7 | P-10 | 关闭solver acceptance blocker。 | P-01..P-09及全部阻塞能力行关闭，`solver_acceptance_blocker=False`，完整发布门禁通过。 |

## 阶段约束

1. P-04至P-08期间禁止删除旧实现文件或旧公开入口；旧代码是产品语义、性能和依赖审计的输入。
2. “固定MC2 source对齐”与“可替代HoTools旧产品”是两种不同结论。Tier A source oracle不能单独关闭产品替代项。
3. 性能比较必须使用同一资产、同一Blender版本、同一帧序列和等价功能配置；只测新实现的绝对耗时不能证明替代优势。
4. C++迁移以测量结果为依据。逐帧大数组遍历、打包、转换和数值热点优先；一次性拓扑构建若非瓶颈，可保留在Python以维持清晰边界。
5. 旧路径删除必须是P-08明确放行后的独立、可审查提交，不能与语义修复、性能优化或架构重构混在一起。
6. 旧实现中真实可用的产品能力默认必须保留或改进。若决定缩小支持域，必须有明确产品决策、用户可见拒绝行为和迁移说明；不能用“新架构未实现”本身作为拒绝理由。
7. Debug沿用SpringBone VRM蓝本的隐式请求模型：正常模拟不承担中间态readback，renderer不能根据当前RNA或最终结果反推backend过程；MC2复杂度通过语义层、过滤器和按需buffer表达，不通过新增一组中间态接线节点表达。
8. P-05代码整理不得夹带数值、参数默认值、更新频率或支持域变化；任何行为变化必须拆回对应能力行单独验收。

## 交付规则

1. 一次提交只关闭一个 acceptance row或一个明确的公共契约冲突。
2. 改变完成度、支持域或阻塞状态时，同提交更新 `MC2_ACCEPTANCE_MAP.md`；纯实现细节不在本文追加“已完成”段落。
3. 新发现的源码陷阱、Blender特化、故意差异或冲突规则写入 worksheet，并给出稳定ID或明确标题。
4. source-aligned声明必须有固定producer/consumer、输入域和Tier A；Tier B/C只能证明局部分支或回归。
5. 测试环境固定为 Python 3.13 和 Blender 5.1 `--background --factory-startup`；不使用 Blender 4.5 作为MC2验收环境。
6. 风险较高的native改动同时验证raw ABI、Python host和Blender生产链；文档-only变更至少执行`git diff --check`。
