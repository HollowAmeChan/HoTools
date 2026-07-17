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

P-09/P-10已按验收表关闭，P-11事实审计已产出；当前执行项为P-12。下表保留完整收尾顺序，重组必须按审计处理项逐步提交。

| 顺序 | 对应项 | 工作 | 退出条件 |
|---|---|---|---|
| 1 | P-09 | 独立删除旧MC2节点/package、`mc2_context.*`、`mc2_bonecloth_io.cpp`、legacy binding与只服务旧ABI的测试；保留共享`mc2_kernels`、新context/static/self实现。 | 删除提交只做机械移除和必要接线修正；构建无legacy选项/符号，仓库搜索可核验保留/删除清单。 |
| 2 | P-10 | 建立删除后的正确性基线。 | `build.bat 313` native-only增量构建；raw context/static、26/26纯MC2、8资产/7脚本、180帧soak、debug、dispose与失败事务通过；不得依赖已删测试或ABI。 |
| 3 | P-11 | 反向审计全部生产Python文件、native translation unit、公开ABI和文档事实。 | 提交逐文件职责表、import/include/call图和“文档声明→实现owner→测试”矩阵；每个无职责转发、重复状态、跨层依赖、巨型owner和迁移残名都有明确处理项。 |
| 4 | P-12 | 按审计结果重组Python目录和文件，不夹带产品/数值变化。 | 六类职责边界成立；合并只改名/只重导出/共同变化的碎片，生产import DAG无环，setup专属与公共runtime不交叉持有状态；逐步提交并逐步复验。 |
| 5 | P-13 | 重组C++ binding/context/kernel文件并完成单一context原子化。 | MC2 binding从通用module shell分离；context按lifecycle/static/frame-step/interaction/debug职责拆分，kernel/static/self owner明确；删除无意义的legacy/v0命名和适配层，不恢复host round-trip。 |
| 6 | P-14 | 对重组后的Python+C++执行依赖、ABI、状态所有权和垃圾代码终审。 | 旧路径、fallback、shadow state、反向测试依赖、跨层private访问和无职责forwarder为零；创建/更新/step/read/free事务与失败回滚各有唯一owner和门禁。 |
| 7 | P-15 | 将三份MC2专项迁移文档合并成稳定维护蓝本。 | 新`MC2_BLUEPRINT.md`结构对齐SpringBone蓝本；只写当前事实、职责、决策、设计和扩展约束，不保留阶段流水；删除旧三文档并更新status/contract/architecture链接。 |
| 8 | P-16 | 增加最终热点benchmark并执行维护态事实总审计。 | 小/中/大Mesh与Bone覆盖cold/config/geometry/hot/debug；输出阶段耗时、分配和粗粒度阈值。蓝本逐条可由代码/测试证明后关闭全部阻塞并设置`solver_acceptance_blocker=False`。 |

## 目标职责分区

此表是P-11审计的目标分类，不预先决定最终文件名。最终蓝本必须把每个保留文件映射到且只映射到一个主要owner。

| 层 | 应该拥有 | 禁止拥有 |
|---|---|---|
| Public / authoring | 节点surface、declaration、schema/property、稳定名称和输入规范化 | slot、native handle、逐帧数值状态 |
| Blender adapters | Object/Armature raw snapshot、BasePose、frame input、delta/writeback adapter | 约束数值算法、跨task调度 |
| Runtime orchestration | profile+task identity、prepare、slot/context生命周期、all-task transaction、scheduler | bpy写回、第二份particle/static状态 |
| Native boundary | 连续buffer校验、context ABI调用、owner capsule与只读结果/debug readback | Blender RNA、产品节点语义、Python数值solver |
| Result / debug | candidate/envelope、writeback plan、隐式debug请求和冻结快照 | 当前RNA反推、任意native private访问 |
| Oracle / test | Tier A/B固定算法、fixture和benchmark harness | 被生产runtime import、兼容fallback |
| C++ binding | nanobind参数/异常/模块注册 | solver状态、数值producer |
| C++ context | static/dynamic持久状态、step事务、interaction聚合、按需readback、生命周期 | Python对象图、重复kernel实现 |
| C++ kernels | static producer、constraint/self/collision/post数值 | ABI注册、host缓存、产品identity |

## 阶段约束

1. P-09删除和P-10删除后基线已关闭；P-11审计必须以当前无legacy源码、ABI和测试依赖的工作树为起点，并与后续重组分开提交。
2. “固定MC2 source对齐”与“可替代HoTools旧产品”是两种不同结论。Tier A source oracle不能单独关闭产品替代项。
3. 性能比较必须使用同一资产、同一Blender版本、同一帧序列和等价功能配置；只测新实现的绝对耗时不能证明替代优势。
4. C++迁移以测量结果为依据。逐帧大数组遍历、打包、转换和数值热点优先；一次性拓扑构建若非瓶颈，可保留在Python以维持清晰边界。
5. 旧路径删除必须是P-08明确放行后的独立、可审查提交，不能与语义修复、性能优化或架构重构混在一起。
6. 旧实现中真实可用的产品能力默认必须保留或改进。若决定缩小支持域，必须有明确产品决策、用户可见拒绝行为和迁移说明；不能用“新架构未实现”本身作为拒绝理由。
7. Debug沿用SpringBone VRM蓝本的隐式请求模型：正常模拟不承担中间态readback，renderer不能根据当前RNA或最终结果反推backend过程；MC2复杂度通过语义层、过滤器和按需buffer表达，不通过新增一组中间态接线节点表达。
8. P-12/P-13代码整理不得夹带数值、参数默认值、更新频率或支持域变化；行为变化必须独立登记、验证和提交。
9. 每次重组遵循“先记录职责/依赖、移动或合并、删除旧入口、静态搜索、分层测试、提交”的顺序；不得一次大搬家后再集中修import。
10. native内部自产自用的数据不得为了沿用旧Python spec而回读到host；允许跨边界的逐顶点大数组只有Blender原始输入、公开结果和显式请求的debug快照。

## 交付规则

1. 一次提交只关闭一个 acceptance row或一个明确的公共契约冲突。
2. 改变完成度、支持域或阻塞状态时，同提交更新 `MC2_ACCEPTANCE_MAP.md`；纯实现细节不在本文追加“已完成”段落。
3. 新发现的源码陷阱、Blender特化、故意差异或冲突规则写入 worksheet，并给出稳定ID或明确标题。
4. source-aligned声明必须有固定producer/consumer、输入域和Tier A；Tier B/C只能证明局部分支或回归。
5. 测试环境固定为 Python 3.13 和 Blender 5.1 `--background --factory-startup`；不使用 Blender 4.5 作为MC2验收环境。
6. 风险较高的native改动同时验证raw ABI、Python host和Blender生产链；文档-only变更至少执行`git diff --check`。
7. P-11与P-14的审计结论必须来自可重复脚本/搜索/测试，不接受仅凭文件名或人工浏览宣称“干净”。
8. P-15合并前旧三文档继续履行当前职责；合并提交必须原子更新所有文档路由，不能留下两个权威入口。
