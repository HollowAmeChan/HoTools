# Jolt 优化开关与测量记录

## 目的

Jolt 的物理系统级优化开关现在通过集中式 `Jolt 世界设置` 暴露。它们属于高级实验属性，默认值全部保持 Jolt 的默认语义；修改后会改变设置签名并重建 native Jolt 世界，再重新注册刚体和约束。

当前开关：

- `deterministic_simulation`：确定性模拟。
- `constraint_warm_start`：约束 Warm Start。
- `use_body_pair_contact_cache`：刚体对接触缓存。
- `use_manifold_reduction`：接触流形归并。
- `use_large_island_splitter`：大岛拆分。
- `allow_sleeping`：世界级休眠。

这些开关不是 Python 每步采样参数，运行时只在 Jolt 世界创建或重建阶段下沉到 C++ 的 `PhysicsSettings`。

## A/B 结果

测试环境：Blender 5.2 无界面启动，1536 个刚体的合成接触场景，预热 3 次、采样 5 次。比较的是 native Jolt step 的 P50，关闭单个开关的结果如下：

| 配置 | native step P50 | 结论 |
| --- | ---: | --- |
| 默认开关全部开启 | 约 2.89 ms | 基准 |
| 关闭确定性模拟 | 约 2.93 ms | 没有收益 |
| 关闭约束 Warm Start | 约 3.65 ms | 变慢 |
| 关闭刚体对接触缓存 | 约 3.93 ms | 变慢 |
| 关闭接触流形归并 | 约 3.63 ms | 变慢 |
| 关闭大岛拆分 | 约 4.16 ms | 变慢 |
| 关闭世界级休眠 | 约 3.79 ms | 变慢 |

因此当前不改变默认开关，不建议为了“优化”盲目关闭这些选项。确定性模拟关闭也没有在此场景产生可测收益。

同一场景的线程数比较显示，native step P50 在 4 个 worker 时约 2.00 ms，1 个 worker 约 3.05 ms，8 个 worker 回升到约 2.26 ms。线程数仍应按工程规模和机器核数单独测量，暂不修改节点默认值。

## 后续

下一轮优化应基于真实工程的分阶段计时，重点区分 broad phase、接触求解、写回和 Blender 依赖图刷新。只有在目标场景中稳定获益的开关，才考虑调整默认值。
