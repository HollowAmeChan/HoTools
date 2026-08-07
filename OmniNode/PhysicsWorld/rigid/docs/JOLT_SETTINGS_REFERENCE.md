# Jolt 设置

`Jolt设置` 是刚体 solver 私有的集中设置节点。它不修改 PhysicsWorld 公共帧上下文，
也不把 Jolt 的内部类型暴露到其它 solver。

## 当前设置

| 设置 | 默认值 | 作用 |
| --- | ---: | --- |
| 重力 | `(0, 0, -9.81)` | Jolt 刚体世界重力 |
| 最大刚体数 | `1024` | native world 容量，变化会重建 world |
| 最大刚体对 | `4096` | BroadPhase pair 容量，变化会重建 world |
| 最大接触约束 | `2048` | 接触约束容量，变化会重建 world |
| 子步数 | `1` | 只作用于 Jolt `Update`，不进入公共帧上下文 |
| 速度迭代 | `10` | Jolt 全局速度 solver 迭代次数 |
| 位置迭代 | `2` | Jolt 全局位置 solver 迭代次数 |
| 工作线程 | `1` | `0` 表示由 Jolt 自动选择；大于零表示线程池工作线程数 |
| 记录接触事件 | 开 | 是否保存完整 Added/Persisted/Removed 接触快照 |

容量、线程数、迭代次数和接触事件开关变化时，适配器会重建 native Jolt world，
并按当前 solver slot 顺序重新注册刚体和约束。重建发生在下一次真实模拟步之前。

## 额外候选项

这些参数暂不进入面板，避免设置节点变成 Jolt 内部参数总表：

- speculative contact distance、penetration slop、max penetration distance：影响接触容错，属于高级稳定性调参。
- deterministic simulation、large island splitter、manifold reduction：属于全局算法策略，应先有对照测试再暴露。
- TempAllocator 大小：属于 native 内存策略，不应由普通用户调节。
- 接触事件详细点集、事件上限：调试/事件通道设置，后续可以拆成高级调试设置。

当前优先保证节点简单：模拟步、求解迭代、线程池和接触采集是第一批可验证的世界级开关。
