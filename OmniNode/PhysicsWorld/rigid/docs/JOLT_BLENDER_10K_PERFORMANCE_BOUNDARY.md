# Jolt 1 万刚体 Blender 侧性能边界

本文档记录当前 HoTools 刚体物理世界在 Blender 5.2、Windows 11、py313 后端上的
1 万刚体边界测量。目标是回答一个工程问题：在不考虑碰撞复杂度的稳态场景中，
Blender 侧读入、结果处理和写回还需要多少时间，以及优化应该做到哪里。

## 测量条件

- Blender：5.2.0 LTS，`D:\Blender\blender-5.2.0-windows-x64\blender.exe`
- 后端：Jolt，单线程，当前 py313 native module
- 刚体：10000 个动态球体，间隔 2 Blender 单位，不发生接触
- 物理世界：`substeps=1`，场景输出帧率为 24 FPS，因此 `dt=1/24`
- 每帧写回：10000 个刚体的 transform delta
- 测量：丢弃首帧初始化影响后，连续 6 个稳态帧；时钟为 `time.perf_counter`
- scope：额外测量每帧从 Collection 重建批次的成本，避免复用 scope 掩盖 Blender 读入

本测量只用于边界判断，不是性能门禁。Blender 视图、渲染、修改器和其他节点未纳入。

## 结果

稳态逐帧观测范围如下，范围比单一平均值更能反映 Blender 的调度抖动：

| 阶段 | 稳态观测 | 说明 |
| --- | ---: | --- |
| `scene.frame_set` | 130--151 ms | Blender 对 1 万对象的帧评估成本 |
| 每帧重建 scope | 11--14 ms | Collection 枚举、transform 批量读取和 scope 打包 |
| `physicsWorldBegin` | 52--61 ms | 物理世界读入、缓存交换和 slot 解析 |
| Jolt native `step` | 0.81--0.97 ms | 无接触稳态；不包含首次 broad phase 建立 |
| 结果发布 | 约 30--77 ms | native 状态批量读取、Python 结果对象发布 |
| Blender 写回 | 84--96 ms | 10000 个对象的 transform 写回，`write_count=10000` |
| 总计 | 334--403 ms | 从 `frame_set` 到 commit，包含写回 |

已有基准脚本的 5 个样本给出相同数量级：写回 P50 约 `81 ms`，不含写回的
Blender 侧流水线 P50 约 `232 ms`。单独的详细探针由于包含每帧 scope 重建，
稳态总时间 P50 约 `369 ms`；二者差异主要来自 Blender 帧评估和结果发布的抖动，
不是 Jolt 求解差异。

## 边界结论

在当前写回策略下，1 万刚体的稳态成本不是 Jolt 求解，而是 Blender 侧：

1. 单独写回就需要约 `85--90 ms`，已经超过 60 FPS 的 `16.67 ms` 帧预算约 5 倍。
2. 加上帧评估、物理世界读入和结果发布，空接触场景也约为 `0.35 s/帧`，只能达到
   大约 3 FPS 的数量级。
3. scope 每帧读取只有十几毫秒，不是当前第一优化目标；继续微调 Python 枚举不能
   把 1 万刚体带回实时范围。
4. 下一阶段的有效优化边界应放在统一的 C++/RNA 批量写回、减少无需变化对象的写回、
   以及避免 Blender 对 1 万对象逐个触发依赖图更新。若仍保持“每帧写回全部对象”，
   继续优化 Jolt 开关不会解决主要瓶颈。

## 发现的容量前提

### Jolt 临时分配器

原实现固定使用 8 MiB `TempAllocatorImpl`。在约 2350 个刚体的 `step()` 内就会耗尽并
触发原生崩溃，导致 1 万刚体无法测量。现在临时工作区按
`max_bodies`、`max_body_pairs`、`max_contact_constraints` 的容量自适应，最低 8 MiB，
并限制在 Jolt `uint` 可表达范围内。1 万无接触刚体可稳定完成测量。

### Contact event 缓冲

现有接触事件结果缓冲默认上限为 8192。1 万刚体同时接触地面时会发生事件溢出，
因此不能把该场景当作“完整接触事件”基准。它是另一个结果通道容量问题，和 Blender
transform 写回边界分开处理；需要接触压力测试时，应先明确事件截断策略并单独记录溢出。

## 后续优化停止线

在下列工作完成前，不应继续以 Jolt 内部优化开关作为主要方向：

- C++ 侧直接消费和批量透传 transform 结果；
- Blender 侧批量写回，避免每个对象重复 `update_tag()` 或等价依赖图刷新；
- 对静止、睡眠、未变化对象提供可验证的增量写回策略；
- 将 `scene.frame_set` 的依赖图评估成本从物理节点统计中单独剥离。

达到上述边界后，再用相同基准比较 Jolt 多线程、岛拆分、接触缓存和睡眠策略，
才不会把 Blender 侧固定成本误判为 solver 性能问题。
