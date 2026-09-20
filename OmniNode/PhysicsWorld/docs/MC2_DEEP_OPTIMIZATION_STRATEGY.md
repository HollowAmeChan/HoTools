# MC2 深度优化策略

本文维护 MC2 的长期性能事实、测量方法、CPU 优化边界和算法研究入口。GPU 后端的实现、隔离和验收统一写入 `MC2_GPU_BACKEND_DESIGN.md`；产品结构见 `MC2_BLUEPRINT.md`，节点与编译流水线见 `MC2_NODE_SIMULATION_DESIGN.md`。单次 runner、逐提交结果和临时实验只留在测试输出、benchmark 产物与 Git。

## 当前结论

- CPU DomainV1 是长期正确性 reference 和完整产品 backend，不因 E6 启动而改写。
- P4 CPU 粒子域并发不实施，也不预埋 worker、job DAG、grain threshold 或并发 debug 协议。
- 普通 Mesh 热帧复用只读 observation/static fragment；拓扑、属性、对象身份或保守审计失配时按合同重建。
- 多 partition 只运行一个 external/whole-domain self 流水，不允许恢复多 context aggregate。
- debug 与 timing 都是请求式观察；关闭时不创建记录、不 readback、不读取阶段时钟。
- E6 前 host 与调度层已经完成收益审计，低于阈值的小项不再增加旁路、缓存或 owner。
- 当前最大并行数值面是 whole-domain self 的 candidate、contact geometry 和四轮投影；求交算法研究与 GPU 化不是二选一。

## 性能测量合同

所有性能结论必须基于产品 DomainV1，并固定 Blender 版本、资产、帧段、warmup、substep、collider scope、self 模式和编译配置。至少报告：

- 产品顶层：输入、采集、同步、Frame、solve、result、readback、publish；
- CPU mixed pass：Teleport、Center、Integration、Tether、Distance A/B、Angle、Bending、external、Motion、whole-domain self、post；
- self 内部：Primitive、Grid、confirmed intersection、Candidate、Contact 和四轮 solve；
- Candidate 内部：probe/run、pair visit、各类拒绝、emit、sort/unique、flatten；
- 工作量：particle、constraint、primitive、candidate、contact、collider、复制字节和容量峰值；
- 统计：同工作量 P50/P95，不用单帧最好值代替。

timing-off 必须继续调用无计时完整 pipeline 和无计时 native ABI。计时本身不请求 debug snapshot，也不为尚未消费的字段预先计算 hash、格式化字符串或构造明细容器。

## CPU 稳定性能事实

1. Mesh observation 命中时复用 immutable raw snapshot、topology signature 和 static fragment；无法证明 revision 完整时只对该 source 保守重扫。
2. native output 已是目标 dtype/shape 的连续数组，host 只做一次受控只读所有权拷贝；禁止逐标量转 Python tuple 后重建数组。
3. Sphere/Capsule collider 输入使用 float32 标量量化，避免逐 collider 创建短命 NumPy vector；Plane/Box 保持既定 float32 几何运算顺序。
4. collider frame signature 只在 debug/test 实际读取时计算；普通 Frame 不扫描九组 SoA 生成未消费 digest。
5. Pin Point 与全部固定 Edge/Triangle 不进入 self primitive/candidate/contact；部分固定 Edge/Triangle 保留，以维持 Pin 边界附近连续碰撞面。
6. 外碰只使用冻结的 `collided_by_groups`；whole-domain self 才把自身主组并入有效 mask。两者不能在 authoring 层混成一个含义。
7. Grid target 以 AABB 中心建立索引，source query 已按最大 target 半尺寸扩张；当前一倍最大 edge AABB 尺度覆盖性成立。更粗尺度会放大 AABB 晚拒绝，更细尺度可能增加 probe，任何改变都必须用真实分布验证。
8. Candidate 的 raw/unique 接近一时，排序去重不是主要冗余；应先查看 cell 覆盖、pair visit 和 AABB 晚拒绝。
9. 静态 target split、typed collider bridge 等低于当前阈值的小项不增加长期缓存或 trusted 旁路。

## E6 开工基线

同机隔离 Blender 5.2 的代表场景为 1800 粒子、两个 Mesh partition、495 collider、三个 substep。timing-off 五次中位数约 `26.78 ms`；请求式阶段中 solve 约 `22.73 ms`、Frame `3.06 ms`、采集 `0.72 ms`、结果 `0.34 ms`，其余顶层约 `0.12 ms`。GPU solver 无法直接消除的 host floor 约 `4.27 ms`。

solve 内部的代表分布：

| 数值阶段 | 代表耗时 | GPU 价值 |
|---|---:|---|
| whole-domain self Candidate | `14.74 ms` | 最高；约 179 万 pair visit，适合并行 broadphase/filter/emit。 |
| Contact geometry | 约 `4.00 ms` | 高；EE/PT 可分流为独立 narrowphase kernel。 |
| 四轮 contact projection | 约 `2.50 ms` | 高；需要确定性 correction reduction。 |
| 其余 solve | 约 `1.5 ms` | 在完整 mixed pass 阶段覆盖。 |

首版 2k 级预演为 GPU 数值 `3-8 ms`、upload/sync/readback `0.5-1.5 ms`，产品整帧 `7.8-13.8 ms`，约为当前 `1.9-3.4x`。persistent buffer 和融合 dispatch 成熟后目标约 `7-9 ms`、`3-4x`。把 solve 假设成零成本得到的 `6.3x` 只是 Amdahl 数学上限，不是产品承诺。

这些绝对毫秒只服务同机 E6 决策；稳定验收看固定 fixture、工作量一致性、P50/P95、内存和规模曲线。

## CPU 优化边界

CPU 不承担 GPU 前置重构。允许继续实施的 CPU 优化必须同时满足：

- profiling 指向明确热点，且收益高于新增所有权和维护成本；
- 不改变 pass 顺序、float32/half 语义、退化分支、候选过滤和确定性；
- 不引入 GPU 对齐、设备抽象、virtual dispatch 或 staging；
- debug-off、timing-off 和普通热帧无额外工作；
- 可以独立回滚，并由相同工作量证明收益。

P4 CPU 并发保持关闭。Distance、Bending、Angle、Edge 和 self contact 都可能写共享粒子；颜色组、Jacobi、线程局部累积和 merge 会改变应用顺序、收敛或调试所有权。未来只有在目标平台无法使用 GPU、固定 profiling 证明 CPU 是阻塞项且候选 kernel 能保持数值合同的情况下，才通过独立 RFC 重开。

## 求交与接触算法研究

### 术语拆分

- broadphase：空间索引和潜在 pair 枚举；
- narrowphase：EE/PT 最近几何、厚度和运动阈值；
- contact solve：接触修正与共享粒子归并；
- CCD/intersection：连续轨迹或确认穿插，不等同于离散半径接触。

当前最大的 `Candidate` 耗时属于 broadphase/filter，不会因为替换一个最近点 C++ 函数而消失。成熟几何库主要影响 narrowphase 和 CCD；GPU 可以覆盖上述全部数值阶段，因此仍有显著收益。

### 当前 CPU reference

- Edge-Edge：最近线段参数、平方距离、法线、预测位移阈值、half `s/t/normal`；四轮中复用初建参数。
- Point-Triangle：Voronoi 区域最近点、重心坐标、厚度与运动判定、三角形法线和方向；投影轮次重算几何。
- 过滤：Pin/固定 primitive、共享粒子、一环邻接、partition owner、双向 self policy、group/mask。
- 输出：canonical candidate/contact key、稳定排序、单一半径模型和定点 correction sum/count。

任何新算法先作为同 fixture 对照，不取得产品 owner。不得用默认 epsilon、double 精度、不同退化选择、无序并行输出或改变 contact normal 的库结果替换 CPU reference。

### 候选方向

| 方向 | 解决问题 | 当前定位 |
|---|---|---|
| uniform spatial hash + radix sort/scan | 布料尺度相对统一时的 GPU broadphase | E6 首版；保持当前语义。 |
| LBVH/radix tree | primitive 尺度和空间分布高度不均时的 broadphase | 规模曲线证明 Grid 失控后再比较。 |
| 类型分离 EE/PT | 降低 narrowphase 分支发散，改善 SoA/SIMD | GPU 首版；CPU 只在独立收益证据下考虑。 |
| 平方距离保守早退 | 在 sqrt/法线前拒绝大量远 pair | 先测拒绝覆盖率，避免增加低命中分支。 |
| incremental contact/cache | 利用帧间和迭代间一致性 | GPU 等价成立后的优化，不进入首版。 |
| Tight-Inclusion/Root-Parity CCD | 稳健退化和高速穿透 | 测试 oracle 与未来独立能力。 |
| IPC/C-IPC/GIPC | barrier contact 与新的非线性求解 | 完整数值模型变更，不是 E6 移植优化。 |

研究资料统一由 `MC2_GPU_BACKEND_DESIGN.md` 维护，本文只保存决策。

## 数据布局方向

- logical program 保持后端中立 POD/SoA；physical layout 由各 backend 私有。
- uniform 参数保留标量，只有真实差异才物化 dense buffer。
- primitive、candidate 和 contact 按类型分表；identity/filter 与数值 payload 分离。
- 排序只搬 key/index，避免反复物理重排所有大 SoA；是否值得改 CPU 必须单独测量。
- transient buffer 按峰值复用，只清理有效范围；容量增长和硬溢出遵循 staged transaction。
- Release/LTO/SIMD 优化不得通过 fast-math 破坏有限性、Teleport、退化分支或 tolerance。

## 规模曲线

GPU 路线的价值首先是增长斜率，而不是只压低 2k 场景。验收规模至少覆盖 `2k/10k/50k/100k`，并记录：

- `ms/frame`、`ms/substep`；
- particle/constraint/primitive/pair 吞吐；
- candidate/contact 峰值与 buffer 容量；
- device resident、scratch、upload、readback 内存；
- kernel、queue wait 和 host transaction 占比；
- 过密 cell、溢出和 device failure 行为。

self candidate 可能呈超线性增长。任何只改善小场景、却使局部拥挤或大规模内存曲线失控的方案都不能成为产品默认。

## 性能与正确性门禁

每项优化必须保持：

- 单线程 CPU reference 长期可独立运行；
- CPU 产品数值、性能和加载不被 GPU 工作影响；
- 结构约束不跨 partition，self/filter/Pin 工作量符合合同；
- Center/Teleport/Anchor history 按 partition 隔离；
- debug/timing 关闭态零额外记录与 readback；
- allocation、overflow、non-finite、reset/rewind 和多 target 失败零部分发布；
- benchmark 工作量完整，不以减少 candidate/contact 或关闭能力伪造收益；
- 外部库、GPU API 和设备类型不进入 MC2 authoring 或 Physics World 公共合同。

## 不再维护的过程信息

已完成的 E0-E7、逐批旧文件删除、binding 数量变化、单次 digest、runner 数量和每次命名收敛不再写入性能策略。当前代码事实由架构审计和测试维护；需要追溯时查看 Git。本文后续只在性能事实、算法边界或长期门槛改变时更新。

## 外部依据

- Blender Python API，Python Threads are Not Supported：<https://docs.blender.org/api/current/info_gotchas_threading.html>
- MagicaCloth2 Performance：<https://magicasoft.jp/en/mc2_performance/>
- GPU、碰撞和 CCD 研究入口见 `MC2_GPU_BACKEND_DESIGN.md`。
