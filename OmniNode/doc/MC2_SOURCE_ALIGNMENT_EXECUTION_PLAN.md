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

当前目标是 `V1-R` restricted realtime：

- 一个 `mc2` solver，MeshCloth、BoneCloth、BoneSpring 三种 setup，共用一套 native context/step/result 生命周期。
- 单 final-proxy Mesh、双对象 BasePose、Bone Line 安全域、外部 Point/Edge collider、单 cloth self collision。
- Mesh 发布 object-local GN offset；Bone 发布 stable bone identity 的 parent-local transform plan；真实 Blender 写入只由公共 writeback 执行。
- Python 只拥有 Blender snapshot、immutable spec、slot/context 生命周期、packing、result transaction 和 debug；数值 solver 只有 C++ 一份。

以下不进入本轮验收：Bake、通用力场、self sync/inter-cloth、Bone imported triangle、MC2 reduction/render mapping。它们保持 inactive/rejected，不能借由邻近能力宣称支持。

## 当前执行顺序

状态只在 `MC2_ACCEPTANCE_MAP.md` 修改；本表只规定下一步和结束条件。

| 顺序 | 对应项 | 工作 | 退出条件 |
|---|---|---|---|
| 1 | N-06 | 生成 Motion 独立 Tier A substep fixture，不修改不同 scope 的旧 fixture。 | 以固定 source producer输入直接对拍 native consumer；py313 与 Blender 5.1 回归保持通过。 |
| 2 | P-02 | 建立 MeshCloth、BoneCloth Line、BoneSpring 三类代表性 Blender 资产。 | 固定输入、支持域、预期结果和拒绝边界；后台可重复执行并输出稳定诊断。 |
| 3 | P-03 | 建立 V1-R 混合场景稳定性与性能门禁。 | 长时多帧、static rebuild、参数热更新、reset、清缓存、dispose 循环无泄漏/陈旧结果；记录可重复性能基线。 |
| 4 | P-04 | 删除旧 MC2 节点、Python reference、native full-core/context、兼容 cache 与 shadow pipeline。 | registry、节点、import、运行时与资产入口均无 fallback；新测试不加载旧实现。 |
| 5 | P-05 | 关闭 solver acceptance blocker。 | P-01..P-04 全部关闭，`solver_acceptance_blocker=False`，完整 Python 3.13 与 Blender 5.1 门禁通过。 |

不得在第 1 至 3 项尚未形成事实前提前删除可用于定位的旧代码；也不得让旧代码成为新测试 oracle 或运行 fallback。删除提交必须独立、可审查。

## 交付规则

1. 一次提交只关闭一个 acceptance row或一个明确的公共契约冲突。
2. 改变完成度、支持域或阻塞状态时，同提交更新 `MC2_ACCEPTANCE_MAP.md`；纯实现细节不在本文追加“已完成”段落。
3. 新发现的源码陷阱、Blender特化、故意差异或冲突规则写入 worksheet，并给出稳定ID或明确标题。
4. source-aligned声明必须有固定producer/consumer、输入域和Tier A；Tier B/C只能证明局部分支或回归。
5. 测试环境固定为 Python 3.13 和 Blender 5.1 `--background --factory-startup`；不使用 Blender 4.5 作为MC2验收环境。
6. 风险较高的native改动同时验证raw ABI、Python host和Blender生产链；文档-only变更至少执行`git diff --check`。
