# Physics World Field / Volume 与风场契约

> 状态：设计规划，尚未实现
> 归属：`OmniNode/PhysicsWorld`
> 当前主线：公共 Field/Volume、统一 Wind Field、MC2 消费契约
> 核心命名：公开对象称为 **Field**，空间载体称为 **Volume**；不建立 `ForceField` 领域。

## 1. 已确定的架构决策

1. Field 是可按世界位置和物理时间采样的空间数据，不预设它一定表示力。
2. 用户界面只提供一个 Wind Field，不建立“定向风”和“紊流风”类型、preset 或 mode 枚举。
3. Wind Field 输出 `air_velocity` 向量通道，单位为 `m/s`。无量纲 `turbulence` 参数控制同一个基础风是否叠加空间与时间采样：
   - `turbulence = 0`：纯定向风；
   - `turbulence > 0`：基础风上叠加确定性的时空扰动。
4. Volume V0 只实现 sphere 和 box：
   - sphere 从中心到边界具有固定的简单衰减；
   - box 内部恒定、边界外归零，不做衰减。
5. 衰减暂按 Volume 输出空间权重、FieldSampler 乘到最终 channel 的方式实现；这只是 V0 临时权能划分，尚未冻结成通用 Field 结论。
6. MC2 不识别“定向”或“紊流”类型，只接收每个粒子在当前子步采样、合成后的 `air_velocity_world[N, 3]`。
7. MC2 现有七个 wind 字段只是来自 MC2 ClothParameters 的响应/兼容占位；当前 native 没有数值消费，不能据此宣称已支持任何风场。
8. HoTools Wind Field 的目标是成为 MC2 wind 的能力超集，而不是把其简化实现原样迁入公共层。
9. Field 是 Physics World 的持久物理属性。Empty 是首版创作载体，属性进入现有集中物理面板，运行时通过 `world.implicit_objects` 注册。
10. 可视化必须调用与 consumer 相同的 Field sampler。任何公开参数占位都必须显示自身 Volume、采样结果或明确的 `preview_only/reserved` 状态。
11. Field 的契约、Volume、生成器、采样、注册、诊断和可视化共同组成独立领域，必须在 `PhysicsWorld/field/` 下单独成包。

因此序列化、采样、可视化和 native ABI 中都只有一种 Wind Field。turbulence 只是它的一个连续参数。

## 2. 当前范围

本文负责：

- Field/Volume 的公共身份、通道、单位、坐标和采样契约；
- Empty 创作、集中面板、注册、生命周期和诊断；
- `air_velocity` 的基础方向及可选 turbulence 生成；
- 多 Field 的确定性叠加；
- MC2 现有 wind 预留字段审计；
- MC2 每粒子风速输入及 native 接入边界；
- 通用标量、向量、SDF 和矩阵 Field 的占位及可视化规则；
- 回归、确定性和性能闸门。

本文不负责：

- 立即实现 dense grid、OpenVDB 或 GPU Field kernel；
- 完整流体、热传导或空气动力学系统；
- Blender 内置 Force Field 数据到公共 ABI 的直接映射；
- 用 Field 替代一次性的 force、impulse、activate 或 event command；
- 在 FieldSpec 中保存 bpy 对象、native handle、C++ 指针或 Python callback。

## 3. 调研结论

### 3.1 与现有 Physics World 契约的关系

现有架构已经给出了 Field 应遵守的边界：

- 持久、可签名、可懒更新的物理对象进入 `world.implicit_objects`；
- 单帧命令进入 `world.exchange`；
- solver 结果进入 `world.result_streams`；
- solver 只读取公开 spec/snapshot，不读取其他 solver 的私有状态；
- Physics World Begin 不应把持久 Field 当作 frame scratch 清空；
- solver step 和 native callback 不直接读取或写入 Blender。

因此 Field Asset、运行快照和 consumer 输入应是三层对象：

~~~text
Empty / Volume 上的 Field 属性
        |
        v
world.implicit_objects["physics.field"]   # 持久注册
        |
        v
FieldSpecV0 / FieldSnapshotV0             # 公共只读数据
        |
        v
FieldSampler                              # 标量或批量采样
        |
        +--> visualizer
        +--> registered consumer adapter
~~~

相关文档：

- [Architecture](../ARCHITECTURE.md)
- [Physics Simulation Pipeline Contract](./PHYSICS_SIMULATION_PIPELINE_CONTRACT.md)
- [Physics World Implementation Status](./PHYSICS_WORLD_IMPLEMENTATION_STATUS.md)

### 3.2 MC2 本地实现审计

本地 MC2 已保存以下七个字段：

~~~text
wind_influence
wind_frequency
wind_turbulence
wind_blend
wind_synchronization
wind_depth_weight
moving_wind
~~~

它们的当前路径是：

1. [presets.py](../PhysicsWorld/mc2/presets.py) 从 preset 的 `wind` 块读取七个标量。
2. [parameters.py](../PhysicsWorld/mc2/parameters.py) 把它们保存到 `MC2ParticleProfileSpec`，只做范围归一化。
3. [runtime_parameters.py](../PhysicsWorld/mc2/runtime_parameters.py) 把它们写入 runtime ABI v0 的 `float_values`。
4. [domain_collect.py](../PhysicsWorld/mc2/domain_collect.py) 和 [domain_compile.py](../PhysicsWorld/mc2/domain_compile.py) 把全部 float ABI 字段放入 partition parameter table。
5. [cpu_native_kernel.py](../PhysicsWorld/mc2/cpu_native_kernel.py) 在配置 native domain 时没有选择任何 wind 列。
6. [domain_ir.py](../PhysicsWorld/mc2/domain_ir.py) 的当前 frame packet 没有 field/wind 输入。
7. [capability_matrix.py](../PhysicsWorld/mc2/test/capability_matrix.py) 明确把这些字段归为 `wind_hidden`。
8. [declaration.py](../PhysicsWorld/mc2/declaration.py) 没有声明 Field 输入。
9. native integration 只绑定时间步、simulation power、velocity weight 和 gravity；[mc2_kernels.cpp](../../_native/src/mc2_kernels.cpp) 的积分路径只使用阻尼、重力和已有粒子状态。

仓库历史中的 `_native/src` 也从未出现 `wind_influence` 或 `wind_turbulence` 的数值实现。

明确结论：

| 问题 | 结论 |
|---|---|
| 现有预留是否支持定向风？ | 否。缺少方向/速度向量、Volume、变换和采样输入。 |
| 现有预留是否支持紊流风？ | 否。还缺位置、物理时间、seed、空间尺度、算法版本和逐粒子向量。 |
| 七个字段现在是否改变模拟？ | 否。它们在进入 native 前被丢弃。 |
| 七个字段是否还有价值？ | 有。可用于 preset 兼容和 MC2 布料侧响应迁移，但不能充当 Field source。 |

### 3.3 MC2 原始风模型给出的启示

对 MC2 2.18.1 本地只读参考源和官方文档的核对表明：

- Wind Zone 负责方向、主风速、空间范围、衰减和源端 turbulence；
- Cloth wind 参数负责 influence、frequency、turbulence、blend、synchronization、depth weight 和 moving wind；
- 运行时先得到基础方向与幅值，再按粒子位置和时间计算波动/噪声，最后形成粒子所见的风向量；
- turbulence 是基础风上的时空变化，不是另一种单位、另一条 native 输入或另一套物理对象。

这与本文的统一模型一致：

~~~text
Wind = base air_velocity
     + turbulence * layered spatial-temporal variation

turbulence = 0  -> pure directional result
turbulence > 0  -> spatial-temporal variation is present
~~~

参考：

- [Magica Cloth 2 Wind Zone](https://magicasoft.jp/mc2_windzone_component/)
- [Magica Cloth 2 Cloth Wind](https://magicasoft.jp/mc2_magicacloth_wind/)
- [Magica Cloth 2 wind introduction](https://magicasoft.jp/en/wind-start-2/)
- [Magica Cloth 2 release notes](https://magicasoft.jp/en/release-note-2/)

本设计只借鉴语义和数据边界，不复制 MC2 实现代码。

### 3.4 HoTools 必须成为能力超集

MC2 的 wind 实现适合作为行为参考，但它的 source 和 cloth response 都紧贴 MC2 自身。公共 Field 若只复刻这一层，会立即形成另一个 solver 私有 wind 系统。

目标差异：

| 维度 | MC2 参考实现 | HoTools Wind Field 目标 |
|---|---|---|
| 数据所有权 | MC2 Wind Zone / Cloth 私有状态 | Physics World 公共 Field Asset 与 Snapshot |
| 身份 | component/zone 运行身份 | 稳定 `field_id`、签名和迁移版本 |
| 输出 | MC2 内部风结果 | 显式 `air_velocity`、world space、m/s |
| turbulence | 紧凑的波动/噪声调节 | 可版本化的 seed、空间尺度、时间频率和多 octave 采样 |
| 多场 | MC2 zone 选择与 addition | 公共 scope、确定顺序和 channel 合成 |
| 时间 | MC2 内部推进 | Physics World 时间、reset/seek/cache 可复现 |
| 可视化 | component/solver 范围内 | 与 consumer 完全相同的公共 sampler |
| 消费 | MC2 专用 | capability 声明和批量 Sample Batch |
| 诊断 | MC2 参数状态 | active/preview/reserved/invalid 与逐 consumer 报告 |

这里的“超集”指数据契约、采样表达力、生命周期和可复用性，不表示 P0 会照搬 MC2 的全部 zone mode。P0 明确只实现 sphere 和 box；global/radial 等未覆盖语义在资产迁移时必须显式诊断，不能用大 box 或普通 directional 结果静默冒充。

### 3.5 Houdini 可借鉴的边界

Houdini 把 Field 表示为空间 Volume：标量或向量数据以显式名称和类型存在，solver 与 visualizer 读取同一份数据。HoTools 应借鉴这四点：

- channel 名称、rank、semantic 和 unit 必须显式；
- 解析 Volume 与体素 Volume 共享采样接口；
- consumer 必须声明它接受什么 channel 和采样方式；
- visualizer 不维护第二份近似公式。

参考：

- [Houdini Scalar Field DOP](https://www.sidefx.com/docs/houdini/nodes/dop/sopscalarfield.html)
- [Houdini Volume Geometry](https://www.sidefx.com/docs/houdini/nodes/sop/volume.html)
- [Houdini Volume Visualizer](https://www.sidefx.com/docs/houdini/visualizers/volume.html)

## 4. 公共 Field 模型

### 4.1 术语

| 概念 | 含义 |
|---|---|
| Field Asset | Blender 中可保存、撤销和动画的创作属性 |
| Volume | Field 的空间边界和衰减载体 |
| Channel | 可采样数据的 ID、rank、semantic、unit 和坐标空间 |
| Generator | 根据位置、时间和参数生成 channel 值的公共算法 |
| FieldSpec | 从 Blender 收集后得到的不可变、可序列化描述 |
| FieldSnapshot | 某帧已求值的 FieldSpec 集合及签名 |
| Sample Batch | consumer 在一组位置和同一物理时刻得到的连续数组 |
| Consumer Response | consumer 把 channel 转成自身力、速度或约束输入的规则 |

Generator 和 Consumer Response 必须分开。风场负责回答“这里的空气速度是多少”，MC2 负责回答“这块布如何响应这股风”。

### 4.2 FieldSpecV0

~~~text
FieldSpecV0
  abi_version
  field_id                    # 稳定 UUID，不使用对象名
  source_id
  enabled
  status                      # active / preview_only / reserved / invalid

  source
    storage_kind              # analytic / dense_grid_reserved / sparse_grid_reserved
    generator_id              # analytic.wind.v0 / ...
    algorithm_version

  volume
    shape                     # sphere / box
    coordinate_space          # world / object_local
    world_transform
    local_bounds
    outside_policy            # zero
    attenuation_policy_version # V0 provisional, not a public curve system

  channels[]
    channel_id
    semantic
    rank                      # scalar / vector / matrix
    unit
    value_space               # world / object_local
    sample_mode

  scope
    solver_ids[]
    collection_ids[]
    include_ids[]
    exclude_ids[]
    collision_groups[]

  blend
    operation                 # add in V0
    weight
    priority

  time
    simulation_time_source
    evaluation_version

  payload
  visualization
~~~

硬约束：

1. `field_id`、generator/channel ID、算法版本、单位、Volume、attenuation policy、scope 和 payload 都进入签名。
2. payload 只包含有限数值、枚举、元组和稳定引用。
3. 同一 Snapshot 内按 `priority`、再按 `field_id` 排序。
4. NaN、Inf、奇异 transform、非法 bounds 或不支持的 ABI 必须产生诊断。
5. unsupported/invalid Field 不得静默变成一个“看似成功”的零效果。
6. consumer 不得通过对象名、UI preset 名或 Blender 类型猜测 channel 语义。

### 4.3 Channel 注册表与占位规则

首版注册表建议：

| Channel | Rank | Unit | Field 状态 | 默认可视化 |
|---|---|---|---|---|
| `air_velocity` | vector | m/s | active 主线 | 箭头格、流线预览、Volume 边界 |
| `acceleration` | vector | m/s² | preview_only | 箭头格、Volume 边界 |
| `mask` | scalar | 0..1 | preview_only | 颜色/透明度切片 |
| `density` | scalar | kg/m³ | preview_only | 颜色切片、等值预览 |
| `temperature` | scalar | K | preview_only | 颜色切片 |
| `pressure` | scalar | Pa | preview_only | 颜色切片 |
| `sdf` | scalar | m | preview_only | 零等值面、正负颜色 |
| `normal` | vector | unitless | preview_only | 表面向量 |
| `tensor` | matrix | explicit | reserved | Volume 边界和 reserved 状态 |

规则：

- `active`：sampler、visualizer 和至少一个 consumer 契约都已完成。
- `preview_only`：参数、sampler 和 visualizer 可用，但不宣称改变模拟。
- `reserved`：只保证 schema/迁移；若没有可信采样器，不公开伪造的数值箭头。
- 一个类型只有参数、却没有边界可视化和状态提示时，不得进入集中面板。
- consumer 支持状态属于 Field 的诊断，不改变 Field 本身是否可以被创建和预览。

## 5. WindV0：一个生成器，turbulence 是参数

### 5.1 统一 payload

~~~text
WindPayloadV0
  channel_id = "air_velocity"
  generator_id = "analytic.wind.v0"

  base
    direction_axis = LOCAL_POS_Z
    speed_mps
    turbulence                 # 0..1

  turbulence_sampling
    spatial_scale_m
    temporal_frequency_hz
    octaves
    lacunarity
    gain
    seed_u32
    noise_algorithm_version
~~~

公共约束：

- `speed_mps >= 0`，方向只由 Empty 的旋转决定；
- local +Z 经去除 scale/shear 的旋转变换后得到单位世界方向；
- Empty scale 只影响 Volume，不改变风速；
- `turbulence` 是 `0..1` 的无量纲连续参数，不是类型开关；
- `spatial_scale_m > epsilon`；
- `temporal_frequency_hz >= 0`；
- `octaves` 首版限制在 `1..8`；
- seed 和算法版本必须进入 Field 签名及 bake/cache 元数据；
- `turbulence = 0` 走 uniform fast path，不求值任何 noise；
- `turbulence > 0` 时才启用高级采样参数。

Field 资产、generator ID 和 channel 始终不变。调整 turbulence 只是 value dirty，不发生类型迁移或 consumer 重新注册。

### 5.2 采样定义

设：

- `p` 为采样点的世界坐标；
- `t` 为 Physics World 的连续物理时间，单位秒；
- `m(p)` 为 Volume V0 产生的临时 `0..1` 空间权重；
- `d` 为 Empty local +Z 对应的单位世界方向；
- `s` 为 `speed_mps`；
- `u` 为 `0..1` 的 `turbulence`；
- `N_i(p, t, seed)` 为第 `i` 层零均值、有限、有版本的三维向量噪声。

~~~text
W = sum(gain ^ i), i = 0 .. octaves - 1

delta(p, t) =
  s * u / W
  * sum(
      gain ^ i
      * N_i(
          p / spatial_scale * lacunarity ^ i,
          t * temporal_frequency,
          seed,
          i
        )
    )

V_wind(p, t) = m(p) * (s * d + delta(p, t))
~~~

`u = 0` 时定义 `delta = 0`，结果自然退化为纯定向风，不需要 generator 分支或另一种 Field 类型。

`N_i` 的具体 hash/noise 算法必须先版本化并建立 golden samples，之后不能在同一算法版本下“优化”出不同结果。首版不要求 curl noise、湍流谱或流体散度约束；这些属于更专门的生成器，而不是 `WindV0` 的隐式行为。

### 5.3 空间与时间语义

- P0 的 turbulence 坐标固定为世界空间，空间尺度使用米。
- Volume mask 随 Empty transform 移动；噪声图案本身不因 Empty 非均匀缩放而变形。
- 动画属性和 Empty transform 在 evaluated frame 收集；子步内的 turbulence 使用连续的 Physics World 时间求值。
- reset 后物理时间回到同一起点；相同 seed、参数、位置和时间必须返回相同向量。
- 不读取 wall clock、随机全局状态或线程调度顺序。
- frame seek、cache read 和 bake 必须恢复同一 `sample_time_seconds` 语义。

## 6. Volume 与多 Field 叠加

### 6.1 V0 只实现两种 Volume

| Shape | 语义 |
|---|---|
| `sphere` | 中心权重为 1，沿归一化半径线性衰减，到边界为 0 |
| `box` | box 内权重恒为 1，box 外为 0，边界不做衰减 |

V0 固定 `outside_policy=zero`。repeat、clamp 和由外部 grid 决定的边界行为不进入首版。

临时参考定义：

~~~text
sphere:
  rho = normalized_radius(position_world)  # center=0, boundary=1
  m(p) = clamp(1 - rho, 0, 1)

box:
  m(p) = 1 if position_world is inside box else 0
~~~

sphere 使用单一半径语义；如果 Empty 出现非均匀 scale，P0 必须诊断并拒绝，不能悄悄变成未声明的 ellipsoid。box 可以使用三个轴向尺寸。

Volume shape 与向量方向正交：

- sphere + `turbulence=0` 仍返回同一方向；
- box + `turbulence>0` 仍按每个世界位置采样；
- 径向、涡旋或吸引等模式以后必须使用新的 generator ID，不能由 shape 暗中改变。

### 6.2 衰减权能仍是待定项

V0 暂时采用最小流水线：

~~~text
raw_value = generator.sample_raw(position, time)
weight = volume.sample_weight(position)
effective_value = weight * raw_value
~~~

这意味着 sphere 暂时同时衰减基础风和 turbulence 的最终合成向量；box 的 `weight` 在内部恒为 1。serialized `speed_mps`、`turbulence` 等源参数本身不会被改写。

这一规则足够完成首版和可视化，但不能直接推广成所有 Field 的永久语义。必须保留以下质疑：

1. attenuation 应由通用 Volume 拥有，还是由每个 generator 拥有？
2. 对 Wind 而言，它应乘最终 `air_velocity`，还是分别作用于 base speed 与 turbulence？
3. 一个多 channel Field 是否共享一个 attenuation weight，还是每个 channel 单独声明？
4. attenuation 应在 Field blend 之前还是之后执行；override 等操作加入后顺序如何定义？
5. sphere 是否需要 full-strength inner radius、曲线或 smoothstep，还是固定线性已经足够？
6. visualizer、debug 和 consumer 是否需要同时访问 raw value 与 effective value？

P0 不增加 curve、inner radius、per-channel attenuation 或 box falloff 参数。只把 `sphere_linear_v0` / `box_none_v0` 作为有版本的临时 evaluation policy；公共 ABI 稳定前必须重新审视以上问题。

### 6.3 Field 合成

`air_velocity` V0 只支持加法：

~~~text
V_total(p, t) =
  sum(field.blend.weight * field.sample(p, t))
~~~

合成规则：

1. 先 scope/bounds culling；
2. 按 `priority`、`field_id` 固定遍历顺序；
3. disabled、out-of-scope 和 outside Field 不参与；
4. 紊流内部的 octave 叠加与多个 Field 之间的叠加都必须确定；
5. 任一 Field 产生非法值时，标记该 Field invalid，并发出带 `field_id` 的诊断；
6. override/max/min 不进入 V0，避免向量场合并语义不清。

多个 Wind Field 仍可叠加，但单个 Wind Field 已同时表达基础风和 turbulence，不要求用户创建配对对象。

## 7. 生命周期与运行时数据

### 7.1 创作与注册

建议持久属性：

~~~text
Object.hotools_field
Scene.hotools_field_overlay
~~~

首版规则：

- Field 创建操作默认生成 Empty；
- 属性存放在 Object PropertyGroup 中，支持 save/load/undo/animation；
- Field 注册节点或公共收集阶段把纯数据 payload 写入 `world.implicit_objects["physics.field"]`；
- `field_id` 使用持久 UUID，对象改名不改变身份；
- 删除、禁用或取消注册必须通过同 stable ID 的 manifest 对账移除；
- solver 和 sampler 不直接持有 Blender Object 引用。

建议公共 names：

~~~text
PHYSICS_FIELD_OBJECT_TAG = "physics.field"
PHYSICS_FIELD_DIAGNOSTICS_CHANNEL = "physics.field.diagnostics"
PHYSICS_FIELD_STATS_CHANNEL = "physics.field.stats"
~~~

最终常量进入公共 `PhysicsWorld/names.py` 或 `PhysicsWorld/field/names.py`，不散落在 MC2/Jolt 私有模块。

### 7.2 Snapshot 与 Sample Batch

`FieldSnapshotV0` 是某个 evaluated frame 的只读 Field 集合，保存：

- 按确定顺序排列的 FieldSpec；
- frame/generation/sample time；
- config signature 和 value signature；
- 已验证的 world transform/bounds；
- channel/consumer capability 诊断；
- sampler algorithm versions。

Snapshot 不预先保存所有 consumer 的粒子向量。consumer 在自己的子步位置上请求批量采样：

~~~text
sample_batch(
  snapshot,
  channel_id="air_velocity",
  positions_world_f32[N, 3],
  sample_time_seconds
)
  -> values_world_f32[N, 3], diagnostics, stats
~~~

标量 reference sampler 与批量 sampler 必须做 differential tests。visualizer 也调用同一接口，只是传入 viewport sample lattice。

### 7.3 Dirty 与 cache

- generator、shape、scope 或 channel 变化：Field registry/config dirty；
- transform、速度、turbulence 参数或动画值变化：Field value dirty；
- 时间推进：只使 time-dependent sample cache 失效，不触发 MC2 topology rebuild；
- consumer 粒子数量/顺序变化：使该 consumer 的 sample buffer 失效；
- cache/bake 签名必须包括 FieldSnapshot signature、sample cadence 和 noise algorithm version。

## 8. 集中面板与显式可视化

### 8.1 创建与属性面板

继续使用 [ui/panels.py](../PhysicsWorld/ui/panels.py) 中的 `OBJECT_PT_Hotools_PhysicsPanel`，增加 Field toggle 和子面板，不建立独立顶层面板。

建议创建入口：

~~~text
创建物理 Field
  风场
~~~

建议面板结构：

~~~text
HoTools 物理
  Field
    Enabled / Status / Field ID
    Volume
      Shape: Sphere | Box
      Size
      Sphere Attenuation: Linear (V0, read-only)
    Channel
      air_velocity
    Wind
      Speed
      Turbulence
      Advanced Turbulence Sampling
        Spatial Scale
        Temporal Frequency
        Octaves
        Seed
    Scope
    Blend Weight / Priority
    Visualization
    Consumer Report
~~~

方向由 Empty 旋转和 viewport 箭头表达，不再增加一个容易与 transform 冲突的 XYZ 方向属性。

### 8.2 可视化契约

可视化层至少提供：

- sphere/box 的真实 bounds；
- sphere 的中心、外边界和实际线性权重变化；
- box 的硬边界，并且不绘制不存在的 falloff；
- Empty local +Z 的主方向箭头；
- `air_velocity` 的采样箭头格；
- `turbulence > 0` 时显示当前 Physics World 时间的实际采样；
- selected Field 与 combined Field 两种预览；
- glyph scale/density 控制只改变显示，不改变采样值；
- active、preview_only、reserved、invalid 和 unsupported consumer 状态；
- stale/no-snapshot 诊断，不用 RNA 属性猜测当前数值。

验收原则：

~~~text
visualizer_sample(position, time)
==
consumer_field_sampler(position, time)
~~~

允许显示层为了可读性裁剪箭头长度，但必须保留统一比例或图例，不能改变方向、相对幅值或 turbulence 相位。

## 9. MC2 消费契约

### 9.1 输入必须是每粒子向量

紊流按空间变化，因此不能把风降级为每个 partition 一个 `[P, 3]` 向量。MC2 adapter 必须在 domain 的每个活动粒子世界位置采样：

~~~text
MC2FieldSamplePacketV0
  abi_version
  field_snapshot_signature
  sample_time_seconds
  particle_count
  air_velocity_world_f32[N, 3]
~~~

约束：

- `N` 与 compiled domain 的粒子索引和数量完全一致；
- 数据是连续的 world-space float32，单位 `m/s`；
- 每个 simulation substep 在积分前采样当前粒子位置；
- 没有有效 `air_velocity` Field 是合法 absent，native 使用零贡献 fast path；
- packet 存在但版本、数量、stride 或有限性错误时是 invalid，不能静默当作无风；
- packet 属于 frame/substep value，不进入 topology key；
- MC2 native 只看最终向量，不分支判断 generator/preset。

建议用新的 frame ABI 版本引用 `MC2FieldSamplePacketV0`，不要把数组塞进现有 per-partition parameter table。

### 9.2 native 接入边界

MC2 接入分成两个职责：

~~~text
Public FieldSampler
  positions_world + time
  -> air_velocity_world[N, 3]

MC2 Wind Response
  air_velocity + particle velocity/normal/depth + cloth response
  -> MC2 integration contribution
~~~

不能把 `air_velocity` 直接当作 acceleration 相加；它的单位和物理意义不同。MC2 native 需要独立 wind pass，并以 MC2 参考行为建立验收。当前 native domain 已拥有位置、世界法线和真实速度数据，但 integration view 尚未把它们接到 wind path。

最小启用顺序：

1. 扩展 frame ABI，验证 `[N, 3]` buffer 和 absent/invalid 行为。
2. 增加无响应的 debug capture，确认粒子顺序、坐标和单位。
3. 实现 MC2 wind response，先打通 `turbulence=0` 的 uniform wind。
4. 用同一 native path 输入 `turbulence>0` 的 spatial-temporal samples。
5. 完成无风 parity、方向、幅值、逐粒子差异、reset/seek 和 partition-invariance 测试后，才解除 `wind_hidden`。

### 9.3 七个兼容字段的归属

以下七项全部处于“已保存、native 未消费”状态。新架构中的建议归属是：

| 现有字段 | MC2 原始意图 | 新架构归属 |
|---|---|---|
| `wind_influence` | 布料受风强度 | MC2 Consumer Response |
| `wind_frequency` | 布料侧时间变化倍率 | legacy 兼容；新 Field 的频率由 `temporal_frequency_hz` 定义 |
| `wind_turbulence` | 布料侧 turbulence 倍率 | legacy 兼容；新 Field 的源强度由公共 `turbulence` 定义 |
| `wind_blend` | 规则波与噪声混合 | legacy 兼容；公共算法由 `noise_algorithm_version` 固定 |
| `wind_synchronization` | 粒子/基线间相位协调 | MC2 专属兼容 sampling policy，不进入 Field source |
| `wind_depth_weight` | 沿布料深度衰减 | MC2 Consumer Response |
| `moving_wind` | 由布料/根节点移动产生的相对风 | MC2 内部响应，不是外部 Field |

迁移原则：

- 保留 preset/profile/runtime 字段，避免破坏已有资产；
- 在对应 native 数值路径和测试完成前继续隐藏；
- 不在 Field 面板复制这七个属性；
- 新 Field workflow 不用七个标量反推方向、Volume 或 turbulence；
- legacy 与 public Field 同时存在时必须有明确的合成和诊断，不能双重计算而不提示。

## 10. Consumer Capability

Field core 不为任一 solver 私有化。每个 consumer 必须声明：

~~~python
FIELD_CAPABILITY = {
    "channel_id": "air_velocity",
    "rank": "vector",
    "unit": "m/s",
    "source_kinds": ("analytic",),
    "volume_shapes": ("sphere", "box"),
    "sample_mode": "per_particle",
    "sample_phase": "pre_substep",
    "value_space": "world",
    "response": "mc2_wind",
}
~~~

最小诊断：

~~~text
FIELD_UNSUPPORTED_CHANNEL
FIELD_UNSUPPORTED_SOURCE
FIELD_UNSUPPORTED_SAMPLE_MODE
FIELD_OUT_OF_SCOPE
FIELD_INVALID_SPEC
FIELD_INVALID_SAMPLE_PACKET
FIELD_PREVIEW_ONLY
FIELD_CONSUMER_NOT_REGISTERED
FIELD_LEGACY_WIND_PRESENT
FIELD_VOLUME_NON_UNIFORM_SPHERE
FIELD_ATTENUATION_POLICY_UNSUPPORTED
~~~

Jolt 仍是 consumer，而不是 Field owner。它可以通过独立 capability 消费 `acceleration`，或在定义了明确刚体空气阻力响应后消费 `air_velocity`；公共 Field 层不能把 `m/s` 自动转换成 `m/s²`。

## 11. 代码所有权：Field 必须单独成包

Field 已同时包含持久属性、公共 ABI、Volume、生成器、批量采样、可视化、生命周期和 consumer capability，复杂度足以形成 Physics World 下的一级领域包。它不能继续堆在公共杂项模块，也不能位于 `rigid` 或 `mc2`：

~~~text
OmniNode/PhysicsWorld/field/
  __init__.py
  names.py
  specs.py
  diagnostics.py
  properties.py
  implicit_objects.py
  volume.py
  wind.py
  sampling.py
  capabilities.py
  visualization.py
  test/
~~~

现有公共 UI 目录负责面板和创建 operator；consumer adapter 只保留转换：

~~~text
PhysicsWorld/field/*         # authoring-neutral Field ABI 与 sampler
PhysicsWorld/ui/*            # 集中面板与创建入口
PhysicsWorld/mc2/*           # MC2 sample packet 与 response mapping
PhysicsWorld/rigid/*         # Jolt capability 与 response mapping
_native/src/*                # 只有性能或 MC2 integration 需要的批量 kernel
~~~

依赖方向必须固定：

1. `field/specs.py`、`field/volume.py`、`field/wind.py` 和 reference sampler 不依赖 `mc2`、`rigid` 或具体 solver。
2. `field/properties.py` 和公共 UI adapter 负责 bpy 边界；纯 spec/sampler 不持有 bpy。
3. `mc2`、`rigid` 只能通过 Field 公共导出读取 spec/sample，不能导入 Field UI 或修改 Field Asset。
4. native 公共 sampler 如有必要也应形成独立 `field_*` ABI；MC2 native 只接收 Sample Batch。
5. 新目录、模块职责和注册顺序必须同步进入 [Architecture](../ARCHITECTURE.md) 及 Physics World 注册表文档。

首版应保留可读的标量 reference sampler，再实现批量路径并逐样本对比。只有性能数据证明必要时，才把公共 turbulence sampler 下沉到 native；下沉后 Python preview、batch sampler 和 native 必须共享 golden samples 与算法版本。

## 12. 实现分期与闸门

### F0：Field core、Empty 与可视化

交付：

- `FieldSpecV0`、`FieldSnapshotV0`、names 和 diagnostics；
- 独立 `PhysicsWorld/field/` 领域包及清晰依赖边界；
- `physics.field` implicit object 注册；
- Empty PropertyGroup、单一 Wind Field 创建入口和集中面板；
- sphere linear attenuation、box hard boundary 和 scope；
- vector/scalar/SDF 的公共 visualizer 框架；
- active/preview_only/reserved/invalid 状态。

闸门：不接任何 consumer，也能创建、保存、加载、撤销、动画、禁用、删除和可靠预览 Field。

### F1：WindV0

交付：

- `air_velocity` channel；
- `analytic.wind.v0`；
- 单一 Wind Field 和连续 `turbulence` 参数；
- 版本化多 octave 时空采样；
- 单点与批量 sampler；
- selected/combined overlay；
- reset、seek、substep 和 determinism tests。

闸门：相同 FieldSnapshot、位置、时间和 seed 在 reference/batch/visualizer 中得到相同结果。

### F2：MC2 Field bridge

交付：

- MC2 capability declaration；
- `MC2FieldSamplePacketV0` 及 frame ABI 版本升级；
- 每粒子、每子步 `air_velocity_world[N,3]`；
- native wind response；
- `turbulence=0` 与 `turbulence>0` 共用同一输入路径；
- wind_hidden 迁移诊断和兼容测试。

闸门：`turbulence=0` 与 `turbulence>0` 都真实改变 MC2 数值结果；关闭 Field 时保持当前结果 parity；partition 划分不改变采样。

### F3：迁移与性能

交付：

- 七个 legacy 字段的冻结映射表；
- 旧 preset migration；
- culling、uniform fast path 和 sample buffer reuse；
- 性能统计及 bake/cache signature；
- 需要时再评估 native noise 或 sparse Volume storage。

闸门：没有第二套公开 wind 属性；没有隐藏的 wall-clock/随机状态；没有因 Field value 更新触发 MC2 topology rebuild。

## 13. 测试矩阵

Field identity/lifecycle：

- stable ID、rename、duplicate、delete、disable、undo、save/load；
- implicit object manifest 对账；
- config/value signature 分离；
- scene reload、addon unregister/register；
- unsupported、preview_only、invalid diagnostics。

Volume：

- sphere 中心权重 1、边界权重 0 和线性中点；
- box 内部权重 1、外部权重 0 和硬边界；
- sphere 非均匀 scale 必须拒绝并诊断；
- Empty rotation、box 非均匀 scale 和奇异 transform；
- sphere 不改变基础风向量方向；
- sphere 暂时等比衰减 base 与 turbulence 的最终向量；
- serialized wind 参数不被 attenuation 改写；
- scope include/exclude 和多 Field culling。

`turbulence=0`：

- Volume 内不同位置、不同时间返回同一基础向量；
- Empty 旋转只改变方向，不改变幅值；
- 单位和 scene scale policy；
- 多 Field 加法及固定遍历顺序。

`turbulence>0`：

- 同 seed/位置/时间可重复；
- 改变位置产生空间变化；
- 改变物理时间产生连续变化；
- reset/seek 重现；
- octave、gain、lacunarity 和 turbulence 边界；
- reference/batch/visualizer golden samples；
- 单线程/多线程与不同 batch 分块结果一致。

MC2：

- absent Field 保持当前数值 parity；
- invalid packet 被拒绝并诊断；
- uniform wind 的方向和幅值；
- turbulence 在同一 cloth 内产生逐粒子差异；
- particle reorder/count mismatch；
- frame/substep 时间推进；
- reset、seek、cache read；
- 不同 partition 数量结果一致；
- legacy preset 与 public Field 的组合诊断；
- 2k/10k/50k 粒子的 sampler、上传和 native wind pass 分项耗时。

## 14. 实现参考

这些资料只提供接口或算法参考，不直接成为运行时依赖：

| 资料 | 参考价值 |
|---|---|
| [OpenVDB](https://github.com/AcademySoftwareFoundation/openvdb) | 后续 sparse Volume、采样和缓存表示 |
| [FastNoise2](https://github.com/Auburn/FastNoise2) | SIMD coherent noise 的实现与性能参考 |
| [FastNoiseLite](https://github.com/Auburn/FastNoiseLite) | 小型、可移植的版本化 noise 参考 |
| [JoltPhysics](https://github.com/jrouwe/JoltPhysics) | 刚体 consumer 的 force/impulse 接口边界 |
| [Houdini Volume docs](https://www.sidefx.com/docs/houdini/model/volumes.html) | Field/Volume 数据模型和可视化 |
| [Magica Cloth 2 Wind docs](https://magicasoft.jp/mc2_magicacloth_wind/) | MC2 source/cloth response 语义与验收参考 |

采用任何第三方 noise/storage 实现前，必须单独审计许可证、确定性、CPU 架构一致性、Blender 打包成本和长期 ABI；公共 `FieldSpecV0` 不依赖第三方对象模型。

## 15. 实施前必须冻结的细节

以下事项必须在实现或 ABI 冻结前形成可测试结论。第一项是有意保留的架构质疑点：它不阻塞 V0 prototype，但阻塞稳定 Field ABI。

1. attenuation 最终由 Volume、generator 还是 channel mapping 拥有，以及它在 blend 前后的顺序。V0 暂用 `effective=volume_weight*raw`，但不得据此提前扩展曲线 UI。
2. `noise_algorithm_version=0` 的确切算法、hash、float 精度和 golden samples。
3. scene unit scale 到米的统一入口，不能由 MC2 和 visualizer 各自换算。
4. MC2 wind response 对 `wind_influence`、`wind_depth_weight` 和 legacy 字段的逐项映射。
5. sample buffer 的所有权、对齐、stride、生命周期和 frame transaction 失败策略。
6. turbulence 每子步采样的性能预算，以及 uniform Field 的预合并 fast path。

Field core prototype 可以按文中临时 attenuation policy 开始；对外 ABI、visualizer 和 MC2 bridge 的正式验收必须记录以上六项的冻结版本。
