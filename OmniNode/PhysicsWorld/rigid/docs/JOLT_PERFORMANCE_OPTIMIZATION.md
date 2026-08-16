# Jolt 刚体性能优化契约

本文记录 `PhysicsWorld/rigid` 的性能测量入口、已成立结论和优化顺序。产品优先级见 [Jolt Physics 产品化路线图](../../../doc/JOLT_PHYSICS_BACKGROUND_ANALYSIS.md)，公共批结果和写回规则见 [Physics World 管线契约](../../../doc/PHYSICS_SIMULATION_PIPELINE_CONTRACT.md)。

近期性能对象是 Blender Objects：GN/modifier 结果先通过显式创作操作应用并拆分成 Objects，再进入 Jolt。直接 GN runtime instance 模拟不属于当前优化阶段。

## 资源导航

- 真实节点图基准：`test/benchmark_blender_rigid.py`
- 冻结阈值：`test/performance_thresholds.json`
- Native soak：`test/run_native_soak.py`
- Object 写回边界：`JOLT_WRITEBACK_PERFORMANCE_BOUNDARY.md`
- 10k Blender 边界：`JOLT_BLENDER_10K_PERFORMANCE_BOUNDARY.md`
- 多线程调查：`JOLT_MULTITHREADING_INVESTIGATION.md`
- 优化开关 A/B：`JOLT_OPTIMIZATION_SWITCH_AB.md`
- 本机真实工程复核入口：`C:\Users\hhh12\Desktop\模拟.blend`；路径变化时只更新本文，不写进运行时代码。

## 当前结论

- Jolt native step 在现有 body-only 和 contact-heavy 基准中不是总帧主瓶颈。
- Transform 和 contact/sensor 已使用 `PhysicsResultBatch`；默认 solver 热路径不逐刚体/逐事件物化公开 dict。
- Collection 写回可直接消费列式 transform 快照并调用公共 native delta 反算。
- 大规模场景的剩余成本主要在 Object body 同步、Physics World 阶段、Blender RNA/Collection 写回和 depsgraph，而不是继续微调 Jolt 内核。
- 接触密集 synthetic 基准中，native step、pipeline 和 writeback 必须一起报告；只报告 kernel 时间无效。

当前 representative 探索值只用于判断热点，不替代 `performance_thresholds.json`：1536 个动态刚体接触地面时，native step P50 约 `2.9 ms`、pipeline P50 约 `30.7 ms`、writeback P50 约 `8.0 ms`。10k 无接触 Object 场景的写回边界见专项文档，两种基准不可直接混成同一阈值。

## 默认路径

`physicsRigidSolver` 的热点耗时调试默认关闭。关闭时：

- 不读取 `perf_counter`；
- 不创建分段计时 dict；
- 不改变 Jolt step、接触事件、result stream 或缓存顺序；
- 不改变重建条件、物理参数或写回目标。

开启后，计时写入当前帧 `rigid_solver_stats.timing`，不得参与 spec signature、cache key 或物理分支。

## 计时 Schema

`timing.schema = jolt_rigid_step_timing_v1`，单位固定为毫秒：

| 阶段 | 边界 |
|---|---|
| `settings_sync_ms` | 世界设置与隐式约束同步 |
| `body_sync_ms` | Object slot 排序、运动学更新和 body 注册 |
| `constraint_sync_ms` | 显式约束同步 |
| `command_apply_ms` | 当前帧命令消费 |
| `native_step_ms` | `JoltWorld.step` 调用边界 |
| `contact_snapshot_stage_ms` | O(1) 事件计数与惰性快照登记 |
| `contact_snapshot_decode_ms` | 默认 solver 热路径固定为 0；消费者读取时才解码 |
| `breakable_policy_ms` | 约束断裂策略 |
| `transform_publish_ms` | 列式 transform 批发布 |
| `constraint_publish_ms` | 约束状态发布 |
| `contact_publish_ms` | contact/sensor 批登记 |

公共基准还必须记录 Physics World Begin/Commit、writeback、depsgraph/frame-set、body/constraint/contact 数和进程内存。`step_ms` 是 native 业务统计，不能覆盖调用边界的 `native_step_ms`。

## 优化顺序

### 1. Object 资产与 Manifest

GN 应用/拆分先建立稳定生成 Objects、piece identity 和 Collection manifest。基准必须使用与产品相同的 Object 集，不能用脱离资产链的临时数组推导 Blender 总成本。

### 2. Stable Body Table

- 冷启动或结构变化提交完整、确定性排序的 Object body manifest。
- Native 长期持有稳定 row、Jolt handle 和输出行映射。
- 稳定帧只批量提交运动学 transform、热参数和命令，不在 Python 全量重建 body 描述。
- 删除、替换和 body type/shape 变化形成结构事务，并同步处理引用约束。
- 只有 table revision 变化时重建 `slot_id/object_ptr/native row` 映射。

约 1500 个稳定 Objects 的暂定目标仍为 `body_sync_ms` P50 不高于 `0.5 ms`、P95 不高于 `1.0 ms`。冷注册单独计量，不得藏进稳定帧样本。

### 3. 公共 Collection 写回

- Dense Collection 继续直接消费列式快照，只对实际变化列写入并按公共合同通知 Blender。
- Sparse Collection 保留已验证路径，不把 dense 的 changed-only 筛选无条件推广。
- 继续减少 Python 事务对象、重复索引和临时分配；不建立 Jolt 私有 RNA 旁路。
- 每项优化必须验证 restart、jump、rewind、delete、scope replacement 和 delta 清理。

### 4. Jolt 设置 A/B

只有 `body_sync`、result publish 和 Object writeback 收敛后，且真实接触密集工程证明 `native_step_ms` 成为主要成本，才评估 worker、solver iterations、sleep、body-pair cache、manifold 和 advanced contact settings。

一次只改变一个设置，使用相同 manifest、初态、帧序列和接触数量，报告性能与 physical trace 差异。不能把非确定性或较差稳定性只描述成“更快”。

### 5. GN Runtime Instances

不在当前阶段实施。只有 Object/depsgraph 经上述优化后仍是主瓶颈，并且 stable instance identity、约束端点、命令、bake、Source/Runtime carrier 和公共 writeback 合同都已冻结，才另建蓝本与等价基准。

## 验收

- 使用真实 OmniNodeTree 和公共 writeback，不用 adapter 微基准替代产品结论。
- 每个 case 记录 warmup、样本数、平均、P50、P95、max、内存高水位和错误计数。
- 结构冷启动、稳定帧、接触密集帧和删除/替换帧分开统计。
- Native trace、result 逻辑计数、same-frame、restart 和双 ABI determinism 不退化。
- 阈值只在 `performance_thresholds.json` 冻结；本文不追加每次运行日志。
