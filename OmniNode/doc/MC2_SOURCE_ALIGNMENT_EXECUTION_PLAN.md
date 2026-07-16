# MC2 实施与验收执行计划

更新日期：2026-07-17

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
| 1 | P-09 | 独立提交删除旧MC2节点/package、旧context/BoneCloth IO源文件与legacy binding；保留共享`mc2_kernels`、V0/static/self实现。 | 删除后完整Python 3.13、Blender 5.1、Tier A、代表性资产、debug、混合soak和性能门禁通过；仓库搜索无遗留入口或fallback。 |
| 2 | P-10 | P-09关闭后，将MC2 declaration的`solver_acceptance_blocker`改为`False`。 | P-01..P-09及全部阻塞能力行关闭，完整发布门禁通过。 |

## 阶段约束

1. P-04至P-08期间禁止删除旧实现文件或旧公开入口；旧代码是产品语义、性能和依赖审计的输入。
2. “固定MC2 source对齐”与“可替代HoTools旧产品”是两种不同结论。Tier A source oracle不能单独关闭产品替代项。
3. 性能比较必须使用同一资产、同一Blender版本、同一帧序列和等价功能配置；只测新实现的绝对耗时不能证明替代优势。
4. C++迁移以测量结果为依据。逐帧大数组遍历、打包、转换和数值热点优先；一次性拓扑构建若非瓶颈，可保留在Python以维持清晰边界。
5. 旧路径删除必须是P-08明确放行后的独立、可审查提交，不能与语义修复、性能优化或架构重构混在一起。
6. 旧实现中真实可用的产品能力默认必须保留或改进。若决定缩小支持域，必须有明确产品决策、用户可见拒绝行为和迁移说明；不能用“新架构未实现”本身作为拒绝理由。
7. Debug沿用SpringBone VRM蓝本的隐式请求模型：正常模拟不承担中间态readback，renderer不能根据当前RNA或最终结果反推backend过程；MC2复杂度通过语义层、过滤器和按需buffer表达，不通过新增一组中间态接线节点表达。
8. P-05代码整理不得夹带数值、参数默认值、更新频率或支持域变化；任何行为变化必须拆回对应能力行单独验收。
9. P-06a..P-06e每一步都必须遵循“先固定oracle与profile、再增加native producer、切换生产consumer、删除Python producer/packer/转发、复验、独立提交”的顺序；不得等全部迁移结束后才集中清垃圾。
10. native内部自产自用的数据不得为了沿用旧Python spec而回读到host；允许跨边界的逐顶点大数组只有Blender原始输入、公开结果和显式请求的debug快照。

## 交付规则

1. 一次提交只关闭一个 acceptance row或一个明确的公共契约冲突。
2. 改变完成度、支持域或阻塞状态时，同提交更新 `MC2_ACCEPTANCE_MAP.md`；纯实现细节不在本文追加“已完成”段落。
3. 新发现的源码陷阱、Blender特化、故意差异或冲突规则写入 worksheet，并给出稳定ID或明确标题。
4. source-aligned声明必须有固定producer/consumer、输入域和Tier A；Tier B/C只能证明局部分支或回归。
5. 测试环境固定为 Python 3.13 和 Blender 5.1 `--background --factory-startup`；不使用 Blender 4.5 作为MC2验收环境。
6. 风险较高的native改动同时验证raw ABI、Python host和Blender生产链；文档-only变更至少执行`git diff --check`。
