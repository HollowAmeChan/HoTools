# MC2 验收总表

更新日期：2026-07-16

基线：MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

本文是新 `physicsWorld.mc2` 的**完成度与验收结论单一事实源**。它按可交付能力切片，不按源码文件或提交记录展开。未完成工作顺序见 `MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`，源码 producer/consumer、边界特化与 oracle 细节见 `MC2_SOURCE_DATAFLOW_WORKSHEETS.md`。

## 写作边界

- **应该写**：每个能力切片的当前结论、支持域、已有证据、剩余差异、是否阻塞V1-R，以及结论变更日期。
- **不应该写**：实现过程、下一步操作细节、公式/源码逐行语义、踩坑展开、公共Physics World架构或提交历史。
- **内容路由**：未完成工作的顺序与退出条件写`MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`；源码事实、特化、故意差异和冲突处理写`MC2_SOURCE_DATAFLOW_WORKSHEETS.md`；跨solver公共规则写`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；历史过程只留Git。
- **更新原则**：只有代码和相应层级证据已经成立，才能更新本文结论；不能把计划、推测或邻近能力写成完成事实。

## 验收范围

当前目标是 `V1-R`（restricted realtime）：单一 MC2 solver、MeshCloth/BoneCloth/BoneSpring 三种 setup、单 final-proxy Mesh、Bone Line 安全域、外部 Point/Edge collider、单 cloth self collision、实时 Mesh/Bone writeback。

以下不阻塞 `V1-R`：Bake、通用力场、self collision sync/inter-cloth、Bone imported triangle、MC2 reduction/render mapping。它们必须保持明确的未支持状态，不能由现有能力外推为已完成。

## 状态口径

| 状态 | 含义 |
|---|---|
| `完全对齐` | 声明域内已有直接 Tier A 证据，且 Host、native、Blender 生产链全部闭环。 |
| `限定域对齐` | 明确限制输入域后满足“完全对齐”；限制外不宣称支持。 |
| `实现完成/证据缺口` | 生产链已接通，但缺独立 Tier A 或仍有源码语义待核账。 |
| `产品收尾` | 数值能力已具备，尚缺真实资产、稳定性、性能或旧路径清理验收。 |
| `未来扩展` | 不在 `V1-R` 范围，当前必须保持 inactive。 |
| `拒绝` | 已知输入域不成立，在进入 native 前显式报错。 |

“完全对齐”只描述表中写明的范围，不表示完整复制 Unity object、job、render mapping 或 editor 层。

## 总览

| ID | 能力切片 | 当前结论 | 已有证据 | 剩余差异/退出条件 | 阻塞 V1-R |
|---|---|---|---|---|---|
| C-01 | 单 solver / 三 setup / 单 native context | 完全对齐 | declaration、slot/context 双 ABI、staged replace、dispose/soak | 保持无 Python fallback、无隐藏全局 owner | 否 |
| C-02 | 帧生命周期、same-frame、reset、失败回滚 | 完全对齐 | py313 lifecycle + Blender 5.1 首帧/连续帧/倒放/重建 | 无 | 否 |
| C-03 | scheduler、多子步、一次提交 | 完全对齐 | Tier A scheduler + py313 + Blender 5.1 单/三子步 | 无 | 否 |
| C-04 | N2 参数 ABI 与热更新 | 限定域对齐 | 两组 Tier A 参数 dump、slot 热更新 | wind 与 sync 字段仅兼容占位，不计 active 能力 | 否 |
| C-05 | Center/Inertia、anchor、teleport、signed component | 限定域对齐 | Tier A Center/step fixtures + py313 + Blender 5.1 | 仅支持已声明的无 shear、非零 scale 域 | 否 |
| S-01 | Mesh final proxy、UV/Pin、拓扑签名 | 限定域对齐 | Tier A static fixtures + staged native upload + Blender 5.1 | 单 final proxy；UV seam 与拓扑变化按契约拒绝/重建 | 否 |
| S-02 | Mesh baseline 与双对象 BasePose | 限定域对齐 | Tier A baseline/rotation + py313 + Blender 5.1 GN链 | 每 vertex 属于 triangle；禁止反馈与改拓扑 modifier | 否 |
| S-03 | Bone connection 与 Line static | 限定域对齐 | 8组 Tier A connection + 3组 Line/rotation fixtures + Blender 5.1 | Automatic/Sequential 只接受最终无 triangle membership | 否 |
| S-04 | BoneCloth Line 与 BoneSpring setup | 限定域对齐 | shared static/native/result 链、N2 override、Blender 5.1 | BoneSpring 固定 Line、Sphere-only；不扩张到 triangle | 否 |
| S-05 | Bone imported triangle | 拒绝 | 固定源码证明全零 UV 导致 tangent/basis 退化 | 未来若改变产品策略，必须先建立真实 producer/oracle | 否 |
| N-01 | prediction、Pin、constraint 顺序与 post | 完全对齐 | Tier A 双子步顺序 + native V0 + Blender 5.1 | 无 | 否 |
| N-02 | Tether | 完全对齐 | 直接Tier A runtime + py313 native + Blender 5.1 production solve | stretch/compression、Fixed/missing-root gate与velocity-reference attenuation均闭环 | 否 |
| N-03 | Distance | 完全对齐 | 7组static、2组ordered runtime、Tier A双子步frame与native双阶段执行 | correction按0.3 attenuation进入velocity-reference，post消费并跨子步提交 | 否 |
| N-04 | Angle | 完全对齐 | 直接Tier A runtime + py313 native/V0 + Blender 5.1 Mesh/Bone solve | 双baseline、Fixed root、Restoration+Limit、falloff/attenuation与scratch clear均闭环 | 否 |
| N-05 | Triangle Bending | 完全对齐 | 3组 Tier A runtime + static role/order + native fixed-point sum | 无 | 否 |
| N-06 | Motion | 实现完成/证据缺口 | py313 kernel/V0 + Blender 5.1 Fixed Mesh | 补独立 Tier A Motion substep fixture | 是 |
| K-01 | 外部 Point/Edge collider | 限定域对齐 | py313 四 primitive/数值 + Blender 5.1 Mesh/Bone | 当前声明域不含完整 Unity collider component lifecycle | 否 |
| K-02 | BoneSpring soft sphere | 限定域对齐 | py313 数值 + Blender 5.1 production | 只接受 Sphere 与 spring 专用 limit 语义 | 否 |
| K-03 | Self primitive/grid/hash/broadphase | 限定域对齐 | raw/Tier A static + py313 hash/candidate + Blender 5.1 | 单 cloth FullMesh 域 | 否 |
| K-04 | Self EE/PT contact、4轮 solve/sum | 限定域对齐 | half contact、手算 fixed-point、后续 substep fixtures | 单 cloth FullMesh 域 | 否 |
| K-05 | Self 跨帧 Intersect | 限定域对齐 | py313 三帧反馈 + Blender 5.1 final-substep gate | 单 cloth、固定分片调度 | 否 |
| K-06 | Self sync/inter-cloth | 未来扩展 | 参数只保存、不消费 | 需要多体 ownership、质量汇总、sync 与调度 oracle | 否 |
| O-01 | Mesh result transaction 与 GN writeback | 完全对齐 | candidate/envelope、发布回滚、拓扑失败恢复、Blender 5.1 | 无 | 否 |
| O-02 | Bone result transaction 与 PoseBone writeback | 限定域对齐 | stable identity、parent-local plan、批次回滚、signed component Blender 5.1 | 与 S-03/S-04 相同的 Line/transform 限定域 | 否 |
| O-03 | `mc2_stats_v0` | 完全对齐 | schema、聚合、稳定排序、事务回滚 | stats 不得替代真实 writeback ready 语义 | 否 |
| P-01 | V1-R 直接 oracle 闭环 | 产品收尾 | static/runtime主体、Distance/Tether/Angle direct runtime已有Tier A | 关闭 N-06 | 是 |
| P-02 | 真实生产资产验收 | 产品收尾 | 自动化最小场景已覆盖 Mesh/Bone/collider/self | 固定代表性 MeshCloth、BoneCloth、BoneSpring 资产并记录预期与失败边界 | 是 |
| P-03 | 稳定性与性能门禁 | 产品收尾 | context 双 ABI soak、dispose 与后台测试已存在 | 增加 V1-R 混合场景长时 soak、重建/清缓存循环与性能基线 | 是 |
| P-04 | 旧 MC2 路径删除 | 产品收尾 | 新 solver 不调用旧 package | 删除旧节点/package/full-core/context/shadow pipeline；确认无 registry/asset fallback | 是 |
| P-05 | declaration 验收开关 | 产品收尾 | `mc2` 已注册并发布三类结果 | P-01..P-04 全关后将 `solver_acceptance_blocker` 改为 `False` | 是 |
| X-01 | Bake/export | 未来扩展 | `supports_bake=False` | 独立冻结 bake 时间轴、缓存与导出契约 | 否 |
| X-02 | 通用力场（含 wind） | 未来扩展 | N2 仅保留兼容字段 | 等待 Physics World 公共力场快照，再接 adapter/native/oracle | 否 |

## 当前验收结论

`V1-R` 的主体数值与 Blender 生产链已经成形，当前不是继续横向扩功能，而是关闭 **1 个数值证据项 + 2 个产品验收项 + 旧路径删除 + acceptance flag**。在这些项目关闭前，`solver_acceptance_blocker=True` 保持正确。

当前开放阻塞：

1. `N-06`：Motion 独立 Tier A substep fixture。
2. `P-02`：三 setup 代表性真实资产验收。
3. `P-03`：混合场景 soak、资源循环与性能门禁。
4. `P-04`：旧 MC2 路径删除。
5. `P-05`：关闭 declaration acceptance blocker。

## 更新规则

1. 任何改变能力完成度、支持域或验收阻塞的 MC2 提交，必须同步更新本表对应行。
2. 新测试只有在证明该行所需层级时才能改变结论；shape/count、自洽测试或旧 solver 输出不能把状态升级为“完全对齐”。
3. 现有文档互相冲突时，本表先降级为“实现完成/证据缺口”，再以固定 MC2 source 与新 oracle 核账；不得选择较乐观的描述直接结案。
4. 长篇执行记录不再承载总体完成度。完成项从“当前切入点”移出后，只在本表保留结论与证据摘要。
5. 每次验收冲刺先关闭本表的阻塞行，不因未来扩展项增加而改变 `V1-R` 范围。
