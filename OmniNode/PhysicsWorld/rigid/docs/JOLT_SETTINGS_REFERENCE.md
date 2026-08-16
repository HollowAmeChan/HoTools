# Jolt 世界设置参考

`Jolt设置` 是 `rigid_jolt` 私有的集中设置节点。它不修改 Physics World 公共时间合同，也不把 Jolt 内部类型暴露给其它 solver。

产品方向见 [Jolt Physics 产品化路线图](../../../doc/JOLT_PHYSICS_BACKGROUND_ANALYSIS.md)。当前字段以 `implicit_objects["rigid_jolt.world_setting"]` 持久注册，由 `implicit_objects.py`、`backends/jolt.py` 和 `_native/src/jolt_rigid.cpp` 映射。

## 当前设置

| 设置 | 默认值 | 当前更新类别 | 作用 |
|---|---:|---|---|
| 重力 | `(0, 0, -9.81)` | Hot | Jolt 刚体世界重力 |
| 最大刚体数 | `1024` | Rebuild | `PhysicsSystem::Init` body 容量 |
| 最大刚体对 | `4096` | Rebuild | broadphase pair 容量 |
| 最大接触约束 | `2048` | Rebuild | contact constraint 容量 |
| 子步数 | `1` | Hot scheduler | 只作用于 Jolt `Update`，不改变公共 FrameContext |
| 速度迭代 | `10` | Rebuild（当前实现） | 全局 velocity solver iterations |
| 位置迭代 | `2` | Rebuild（当前实现） | 全局 position solver iterations |
| 工作线程 | `1` | Rebuild | `0` 为 `JobSystemSingleThreaded`；正数为 Jolt 线程池 worker 数 |
| 记录接触事件 | 开 | Rebuild | 是否保存 Added/Persisted/Removed 事件快照 |
| 确定性模拟 | 开 | Rebuild（当前实现） | `PhysicsSettings.mDeterministicSimulation` |
| 约束 Warm Start | 开 | Rebuild（当前实现） | 复用上一帧 constraint impulse |
| 刚体对缓存 | 开 | Rebuild（当前实现） | 复用满足容差的 body-pair collision result |
| 流形归并 | 开 | Rebuild（当前实现） | 合并接触法线相近的 manifold |
| 大岛拆分 | 开 | Rebuild（当前实现） | 把大 island 拆成可并行 batch |
| 世界睡眠 | 开 | Rebuild（当前实现） | 全局允许 body sleeping |

`Rebuild（当前实现）` 表示这些值当前属于 adapter runtime signature，变化后创建新的 native Jolt world 并按稳定 Object/constraint slot 顺序重注册。Jolt API 中可通过 `SetPhysicsSettings` 安全热更新的字段，后续可以在有回归后从 rebuild signature 拆出；文档不能提前把“Jolt 原生可设置”写成“HoTools 已热更新”。

## 选择与冲突

- 多个设置对象按 `priority`、最后生效帧和 registry 顺序选择一个最终设置。
- `source_id` 提供稳定 authoring identity；同一来源更新替换旧签名，不无限累积。
- 没有设置节点时使用上表默认值。
- 设置变化只影响 `rigid_jolt`，不修改其它 solver 的 gravity、substeps 或线程策略。
- Same-frame 只同步待处理设置或重发结果，不额外推进时间。

## 下一批候选

候选来自本地 Jolt 5.2.0 `Jolt/Physics/PhysicsSettings.h`。公开节点使用米、秒、角度等产品单位；adapter 负责转换 squared distance、cosine 等 native 存储形式。

### Contact

| 产品字段 | Jolt 字段 | 默认值 |
|---|---|---:|
| Baumgarte | `mBaumgarte` | `0.2` |
| 推测接触距离 | `mSpeculativeContactDistance` | `0.02 m` |
| 穿透容许量 | `mPenetrationSlop` | `0.02 m` |
| 单次最大穿透修正 | `mMaxPenetrationDistance` | `0.2 m` |
| 弹性响应最低相对速度 | `mMinVelocityForRestitution` | `1.0 m/s` |

### CCD

| 产品字段 | Jolt 字段 | 默认值 |
|---|---|---:|
| Linear Cast 启用阈值 | `mLinearCastThreshold` | `0.75` |
| Linear Cast 最大穿透比例 | `mLinearCastMaxPenetration` | `0.25` |

### Sleep

| 产品字段 | Jolt 字段 | 默认值 |
|---|---|---:|
| 入睡等待时间 | `mTimeBeforeSleep` | `0.5 s` |
| 睡眠点速度阈值 | `mPointVelocitySleepThreshold` | `0.03 m/s` |

### Cache 与 Manifold

- body-pair cache 最大相对位移和旋转。
- warm-start contact point 保留距离。
- sub-shape manifold 合并的最大法线夹角。
- manifold 平面判定容差。

公开时应使用距离/角度字段，不能把 `mBodyPairCacheMaxDeltaPositionSq`、`mBodyPairCacheCosMaxDeltaRotationDiv2` 等实现表示直接搬到 socket。

### 调度与 Debug-only

- `mMaxInFlightBodyPairs`、step listener batch size 和并行阈值只在真实大规模基准证明需要时开放。
- `mCheckActiveEdges` 等 debug switch 只进入专家/测试 profile，不进入普通设置节点。
- TempAllocator 大小属于 native 内存策略，不作为项目 authoring 字段。

## V2 设计

`JoltWorldSettingsV2` 建议分为：

```text
Basic      gravity / substeps / solver iterations
Capacity   AUTO | MANUAL + capacity fields
Runtime    worker threads / contact recording
Contact    tolerance and correction profile
CCD        global linear-cast policy
Sleep      global sleep thresholds
Cache      pair/manifold/warm-start tolerances
Debug      measured expert switches
```

- 每个高级分组支持 `JOLT_DEFAULT / CUSTOM`，旧工程默认仍得到当前轨迹。
- 字段元数据必须标注 `HOT / REBUILD / SCHEDULER`，节点、signature、adapter 和 debug 共用该表。
- `AUTO` 容量只根据已经完整验证的 Object/constraint manifest 加固定 headroom；容量不足才 rebuild。`MANUAL` 保留给测试、复现和严格资源预算。
- 新开关先进入 A/B fixture；没有性能或稳定性证据时保持 Jolt 默认值，不把设置面板变成内部字段总表。
