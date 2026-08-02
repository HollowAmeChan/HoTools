# Physics World Field / Volume 与风场契约

> 状态：Field/WindV0 native runtime 已启用，`air_velocity` 已由 MC2 CPU Domain 直接消费
> 归属：`OmniNode/PhysicsWorld`
> 当前主线：公共 Field/Volume、统一 Wind Field、显式可视化与 MC2 响应
> 核心命名：公开对象称为 **Field**，空间载体称为 **Volume**；不建立 `ForceField` 领域。

当前实现快照（2026-08-02）：

- 已有独立 `PhysicsWorld/field/` component、`FieldSpecV0`/`FieldSnapshotV0`、schema/capability 单一事实源和 `physics.field` manifest 对账；World Begin 同轮把有效场编译为公共 `NativeFieldRuntimeV1` 并原子提交到 world cache；
- 已有 Field 类型层（V0 仅 Wind）、原生 Empty 挂载与集中面板、sphere/box、确定性四维 value noise、多 octave turbulence、reference/batch sampler、selected/combined vector overlay 及 vector/scalar/SDF/matrix channel 可视化注册表；
- Blender Empty 启用后解析为 `ACTIVE` Field；`air_velocity` channel 状态为 `ACTIVE`，MC2 CPU product 是当前已注册 consumer；
- 已有公共 native registry、单调 `uint64` handle、标准 Field evaluator、调用方持有的输出/scratch 与显式 participation；MC2 Domain 静态持有 partition 作用域上下文，每个子步直接从自身当前位置在 C++ 内采样，Python/native 边界不传粒子数据；
- MC2 子步 Python 只传 runtime handle 与 Physics World sample time 两个标量；native 采样发生在任何 solver mutation 前，响应 pass 位于 Center inertia 之后、Integration 之前；
- MC2 创作侧只保留 `field_wind_enabled` 与 `field_wind_strength`。旧七个 MC2 wind 参数已从 preset/profile/runtime ABI/节点接口删除，不保留隐藏兼容路径；
- 作者预览固定为 `AUTHOR_STATIC`、`t=0`，只在属性/depsgraph/file-state 变化时重建，不按帧展示 turbulence；运行态由请求驱动的“场-运行可视化调试”节点读取 live native runtime 与 World FrameContext；
- Blender 输出时间统一由 `PhysicsWorld/world_time.py` 解释，时间矩阵覆盖 24/30/60、30000/1001、暂停、同帧、reset、跳帧、倒放和子步；
- `.blend` 往返、undo/redo、动画求值、禁用/删除 manifest 对账、reset/seek/substep 与确定性矩阵已有后台验收；reserved channel 没有显式 values 时只报告状态，不伪造 sampler 或数值 glyph。
- seek/cache 的持久恢复属于公共 World cache 合同；当前非连续 seek 仍按现有 World 冷启动语义处理，不另造 Field 私有时间轴。

## 1. 已确定的架构决策

1. Field 是可按世界位置和物理时间采样的空间数据，不预设它一定表示力。
2. 用户界面先选择 Field 类型；V0 只有 `WIND` 类型。Wind 类型内部不建立“定向风”和“紊流风”类型、preset 或 mode 枚举。
3. Wind 类型输出 `air_velocity` 向量通道，单位为 `m/s`。无量纲 `turbulence` 参数控制同一个基础风是否叠加空间与时间采样：
   - `turbulence = 0`：纯定向风；
   - `turbulence > 0`：基础风上叠加确定性的时空扰动。
4. Volume V0 只实现 sphere 和 box：
   - sphere 从中心到边界具有固定的简单衰减；
   - box 内部恒定、边界外归零，不做衰减。
5. 衰减暂按 Volume 输出空间权重、Field evaluator 乘到最终 channel 的方式实现；这只是 V0 临时权能划分，尚未冻结成通用 Field 结论。
6. MC2 不识别“定向”或“紊流”类型。它只借用公共 runtime handle，并在 native Domain 内为当前粒子采样合成后的 `air_velocity_world[N, 3]`。
7. 旧 MC2 七个 wind 字段没有形成可用能力，现已被删除。公共 Field 拥有风源参数，MC2 只拥有“是否响应”与“响应强度”。
8. HoTools Wind Field 的目标是成为 MC2 wind 的能力超集，而不是把其简化实现原样迁入公共层。
9. Field 是 Physics World 的持久物理属性。Empty 是首版创作载体，属性进入现有集中物理面板，运行时通过 `world.implicit_objects` 注册。
10. 作者预览与运行调试是两个明确边界：作者预览固定 `AUTHOR_STATIC/t=0`；运行调试必须直接调用与 consumer 相同的 native evaluator，并以当前 World FrameContext 为时间真值。任何公开参数占位都必须显示自身 Volume、采样结果或明确的 `preview_only/reserved` 状态。
11. Field 的契约、Volume、生成器、采样、注册、诊断和可视化共同组成独立领域，必须在 `PhysicsWorld/field/` 下单独成包。

因此序列化、采样、可视化和 native ABI 中都只有一种 Wind Field。turbulence 只是它的一个连续参数。

## 2. 当前范围

本文负责：

- Field/Volume 的公共身份、通道、单位、坐标和采样契约；
- Empty 创作、集中面板、注册、生命周期和诊断；
- `air_velocity` 的基础方向及可选 turbulence 生成；
- 多 Field 的确定性叠加；
- MC2 旧 wind 字段删除结论与新响应边界；
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
FieldSpecV0 / FieldSnapshotV0             # 公共只读编译输入/边界元数据
        |
        v
NativeFieldRuntimeV1                      # world cache 资源 owner
        |
        +--> native consumer evaluator
        +--> 请求驱动 runtime debug

Python reference sampler                  # golden/differential/作者工具，不进 solver 热路径
~~~

相关文档：

- [Architecture](../ARCHITECTURE.md)
- [Physics Simulation Pipeline Contract](./PHYSICS_SIMULATION_PIPELINE_CONTRACT.md)
- [Physics World Implementation Status](./PHYSICS_WORLD_IMPLEMENTATION_STATUS.md)

### 3.2 MC2 本地实现审计

旧实现曾保存以下七个字段：

~~~text
wind_influence
wind_frequency
wind_turbulence
wind_blend
wind_synchronization
wind_depth_weight
moving_wind
~~~

审计确认这些字段只有存储和传递，没有方向、Volume、世界位置、物理时间或逐粒子空气速度输入，也没有 native 数值消费。继续隐藏或迁移它们只会保留一套无效语言，因此当前实现已经整体删除：

- [parameters.py](../PhysicsWorld/mc2/parameters.py) 的 `MC2ParticleProfileSpec` 不再声明七个字段；
- [presets.py](../PhysicsWorld/mc2/presets.py) 不再读取或生成旧 `wind` 块；
- [runtime_parameters.py](../PhysicsWorld/mc2/runtime_parameters.py) 的 runtime ABI 不再包含七个字段；
- MC2 三类 profile 节点不再公开、隐藏或转发七个字段；
- 新路径不提供兼容映射，也不从旧标量猜测 Field source。

替代它们的是一条完整且单向的数据路径：

~~~text
Physics World Field/WindV0
  -> World Begin 编译 NativeFieldRuntimeV1
  -> MC2 Domain 借用 runtime handle
  -> native 从 Domain-owned positions 采样 air_velocity + participation
  -> field_wind_enabled * field_wind_strength
  -> native HoTools Wind Response V0
~~~

当前结论：

| 问题 | 结论 |
|---|---|
| 旧七字段是否仍存在？ | 否。preset、profile、runtime ABI 与节点接口都已删除。 |
| 定向风与紊流是否使用两条 MC2 路径？ | 否。二者都是逐粒子 `air_velocity`；`turbulence` 只改变公共 Field 的采样结果。 |
| 当前 Field 是否改变 MC2 模拟？ | 是。native evaluator 报告参与且响应强度非零时，会在 Integration 前修改动态粒子的持久速度。 |
| MC2 是否拥有风速、方向、Volume 或 turbulence 参数？ | 否。MC2 只拥有响应开关与 `0..20 1/s` 的响应强度。 |

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

这里的“超集”指数据契约、采样表达力、生命周期和可复用性，不表示 V0 会照搬 MC2 的全部 zone mode。V0 明确只实现 sphere 和 box；global/radial 等未覆盖语义在资产迁移时必须显式诊断，不能用大 box 或普通 directional 结果静默冒充。

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
  status                      # 运行规格状态；不是用户可编辑 RNA
  field_type                  # Field 类型；V0 只有 WIND
  channel_id = "air_velocity"
  generator_id = "analytic.wind.v0"
  volume: VolumeSpecV0
    shape                     # SPHERE / BOX
    world_transform
    attenuation_policy_version
  wind: WindPayloadV0
  scope: FieldScopeV0
    solver_ids[]
    collection_ids[]
    include_ids[]
    exclude_ids[]
    collision_groups[]
  blend_weight               # add 合成的数值权重
  priority                   # 决定遍历顺序
  config_signature
  value_signature
  signature
~~~

硬约束：

1. config signature 包含 ABI、`field_id`/`source_id`、Field/channel/generator ID、Volume 配置、noise 版本、scope 和 priority；value signature 包含 enabled/status、blend weight、transform 和 Wind 数值。channel 的单位与 rank 由独立注册表绑定到稳定 channel ID。
2. payload 只包含有限数值、枚举、元组和稳定引用。
3. 同一 Snapshot 内按 `priority`、再按 `field_id` 排序。
4. NaN、Inf、奇异 transform、非法 bounds 或不支持的 ABI 必须产生诊断。
5. unsupported/invalid Field 不得静默变成一个“看似成功”的零效果。
6. consumer 不得通过对象名、UI preset 名或 Blender 类型猜测 channel 语义。
7. Blender 创作适配器只为有效且已启用的 Empty 生成 `ACTIVE` 规格；`PREVIEW_ONLY`、`RESERVED` 和 `INVALID` 保留为纯规格/诊断状态，不增加一个让用户手工切换的“状态”属性。

### 4.3 Channel 注册表与占位规则

V0 注册表：

| Channel | Rank | Unit | Field 状态 | 有显式采样值时的可视化模式 |
|---|---|---|---|---|
| `air_velocity` | vector | m/s | active | 箭头格、Volume 边界 |
| `acceleration` | vector | m/s² | reserved | 箭头格、Volume 边界 |
| `mask` | scalar | 0..1 | reserved | 颜色/透明度切片 |
| `density` | scalar | kg/m³ | reserved | 颜色切片、等值预览 |
| `temperature` | scalar | K | reserved | 颜色切片 |
| `pressure` | scalar | Pa | reserved | 颜色切片 |
| `sdf` | scalar | m | reserved | 零等值采样点、正负颜色 |
| `normal` | vector | unitless | reserved | 表面向量 |
| `tensor` | matrix | explicit | reserved | Volume 边界和 reserved 状态 |

规则：

- `active`：sampler、visualizer 和至少一个 consumer 契约都已完成；V0 的 `air_velocity` 已由 MC2 CPU product 消费。
- `preview_only`：参数、sampler 和 visualizer 可用，但不宣称改变模拟。
- `reserved`：只保证 schema/迁移；若没有可信采样器，不公开伪造的数值箭头。
- reserved channel 没有显式 values 时只显示 reserved 状态与 Field 自身的 Volume 边界；表中的数值可视化模式只供未来真实 evaluator 或显式运行调试节点复用。
- 一个类型只有参数、却没有边界可视化和状态提示时，不得进入集中面板。
- consumer 支持状态属于 Field 的诊断；创作属性本身不让用户伪装或覆盖能力状态。

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

- V0 的 turbulence 坐标固定为世界空间，空间尺度使用米。
- Volume mask 随 Empty transform 移动；噪声图案本身不因 Empty 非均匀缩放而变形。
- Blender 输出设置是唯一基础时钟：`scene_fps = render.fps / render.fps_base`，`raw_dt = 1 / scene_fps`。`fps_base` 不得被忽略。
- `timeline_time_seconds` 仍是 Physics World 对 Blender 时间线的公共描述，但 Field 作者预览不消费它。作者预览固定 `AUTHOR_STATIC`、`sample_time_seconds=0`，因此拖动帧、播放或改变输出 fps 都不会让 turbulence 预览逐帧变化。
- `sample_time_seconds` 是 Physics World 按实际 `frame_step_dt = raw_dt * world_time_scale` 连续累计的模拟时间；暂停不推进，same-frame 不重复累计，restart 不按帧差追赶。
- 动画属性和 Empty transform 在 World Begin 的 evaluated frame 收集并编译进 native runtime；MC2 对第 `update_index` 个固定子步使用以下唯一公式：

  ~~~text
  t = sample_time_seconds
    + frame_step_dt * update_index / scheduled_frame.schedule.update_count
  ~~~

  其中 `sample_time_seconds` 与 `frame_step_dt` 来自当前 `PhysicsFrameContext`，后者最终由 Blender 输出设置的 `render.fps / render.fps_base` 派生。MC2 固定更新频率只决定本帧 `update_count`，不建立第二条 Field 时间轴。
- reset 后物理时间回到同一起点；相同 seed、参数、位置和时间必须返回相同向量。
- 不读取 wall clock、随机全局状态或线程调度顺序。
- frame seek、cache read 和 bake 最终必须恢复同一 `sample_time_seconds` 语义；当前非连续 seek 只冷启动归零，不宣称已经完成 cache 恢复。

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

sphere 使用单一半径语义；如果 Empty 出现非均匀 scale，V0 必须诊断并拒绝，不能悄悄变成未声明的 ellipsoid。box 可以使用三个轴向尺寸。

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

V0 不增加 curve、inner radius、per-channel attenuation 或 box falloff 参数。只把 `sphere_linear_v0` / `box_none_v0` 作为有版本的临时 evaluation policy；公共 ABI 稳定前必须重新审视以上问题。

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

当前持久属性：

~~~text
Object.hotools_field
Scene.ho_field_overlay_show
Scene.ho_field_overlay_mode
Scene.ho_field_overlay_show_bounds
Scene.ho_field_overlay_density
Scene.ho_field_overlay_glyph_scale
~~~

首版规则：

- 用户自行创建 Blender Empty，再在集中 Physics 面板启用 Field；Field 不提供创建对象 operator；
- 属性存放在 Object PropertyGroup 中，支持 save/load/undo/animation；`field_type` 先于类型参数解析，V0 只有 `WIND`；
- Field 注册节点或公共收集阶段把纯数据 payload 写入 `world.implicit_objects["physics.field"]`；
- `field_id` 使用持久 UUID；首次启用且缺失时自动生成，对象改名不改变身份。World Begin 发现复制导致的重复 ID 时按 scope 顺序保留首个对象，并给后续可写对象自动重签；高级区按钮保留为用户显式重签入口；
- Physics Object Scope 提供默认开启的 Field 注册开关。删除、禁用、关闭注册或对象引用失效时，必须通过 manifest 对账移除旧 ID，并提交与本帧同 generation/frame/time 的零场 Snapshot/runtime；
- solver 和 sampler 不直接持有 Blender Object 引用。

当前公共 names：

~~~text
FIELD_OBJECT_TAG = "physics.field"
FIELD_SNAPSHOT_CACHE_KEY_V0 = "field_snapshot_v0"
FIELD_NATIVE_RUNTIME_CACHE_KEY_V1 = "field_native_runtime_v1"
FIELD_DIAGNOSTICS_CHANNEL = "physics.field.diagnostics"
FIELD_STATS_CHANNEL = "physics.field.stats"
~~~

这些常量进入公共 `PhysicsWorld/field/names.py`，不散落在 MC2 或其它 consumer 私有模块。

### 7.2 Snapshot、native runtime 与标准 evaluator

`FieldSnapshotV0` 是 World Begin 编译边界和调试边界元数据，不是 solver 每子步的数据包。它保存按确定顺序排列的 FieldSpec、frame/generation/帧起始 sample time、config/value signature、已验证 transform/Volume/scope、诊断及算法版本。

同一次 component collector 事务把 Snapshot 编译为公共 `NativeFieldRuntimeV1`：

~~~text
World Begin collector
  -> stage FieldSpecV0[]
  -> build FieldSnapshotV0
  -> compile FieldRuntimeV1
  -> world.runtime_cache["field_native_runtime_v1"] = NativeFieldRuntimeV1
~~~

- native registry 使用进程内单调递增且不复用的 `uint64` handle；`0` 永远无效。consumer 只在一次 native 调用内借用 runtime，不保存指针或取得所有权。MC2 Domain 的借用窗口严格限制在 `prepare_field_wind -> step/cancel`；no-op prepare、成功 step 与异常 cancel 后 inspect 必须报告 handle=0，确保 Field 被删除或 runtime 替换时没有 stale identity。V1 binding 当前依赖 CPython GIL 串行化 registry 的 create/update/sample/dispose；在释放 GIL、引入 native worker 或异步 GPU 消费之前，registry 必须升级为显式同步并让每次调用持有 `shared_ptr` lease，禁止继续返回可能被并发 dispose 的裸引用。
- config/value signature 相同的连续帧复用同一 runtime，只热更新 snapshot signature、generation、frame 与帧起始 sample time；任一配置或数值变化先创建 staged runtime，全部 world 提交成功后替换旧 owner，失败时回滚并释放 staged owner。
- Cache Delete、world replacement、runtime clear 与插件注销都必须通过 `NativeFieldRuntimeV1.omni_cache_dispose()` 幂等释放 registry entry；不得留下模块级隐藏 owner。
- native 标准 evaluator 接受只读位置 view、显式 sample time、粒子到 consumer context 的索引 view，以及调用方持有的输出和 `FieldSampleScratchV1`；输出至少包含 `air_velocity_world` 与独立 `participation`。所有累加结果必须先整批验证为有限且可由 `float32` 表示，再一次写入调用方输出；任一元素失败时不得留下半批新值或把样本标记为有效。MC2 可直接传 Domain-owned float32 positions，并在预热后复用 N 规模 scratch/buffer。
- evaluator 先按 Field 固定顺序和 consumer scope 建表，再执行各 Field 自己的标准采样函数；Sphere linear 与 Box hard-boundary 属于版本化 Volume policy，Wind turbulence 属于版本化 generator。这个 evaluator/scratch/view 边界也是未来 SIMD/GPU 实现需要保持的 logical contract，GPU 可改变物理布局但不能改变 channel、scope、participation、顺序和时间语义。

Python 标量/批量 sampler 继续用于 golden、differential tests、诊断和作者工具，不再进入 solver 热路径。运行态调试只通过公开 native owner 的 inspect/sample API 读取真实 runtime。

### 7.3 Dirty 与 cache

- generator、shape、scope、channel、transform、速度或 turbulence 数值变化：重编译并 staged replacement `FieldRuntimeV1`；
- 只有 generation/frame/帧起始时间变化且 config/value signature 相同：原 runtime 只更新帧元数据，不重新上传 Field 定义；
- 时间在子步内推进：Python 只传新的 scalar sample time，native evaluator 直接使用；不触发 Field runtime 或 MC2 topology rebuild；
- MC2 partition identity、对象/Collection/碰撞组上下文变化：consumer contexts 必须随 staged Domain 一起配置；上下文语义变化强制 staged replacement，配置失败释放新 Domain 并保持旧 owner/slot/调度状态不变；Field runtime 不复制 consumer 粒子数据；
- MC2 响应开关/强度变化：参数更新时同步 Domain response buffer；每子步不重复展开；
- cache/bake 签名必须包括 FieldSnapshot signature、sample cadence、participation 语义和 noise algorithm version。

## 8. 集中面板与显式可视化

### 8.1 创建与属性面板

继续使用 [ui/panels.py](../PhysicsWorld/ui/panels.py) 中的 `OBJECT_PT_Hotools_PhysicsPanel`，增加 Field toggle 和子面板，不建立独立顶层面板。

当前面板结构以简洁为优先：

~~~text
HoTools 物理
  场 [toggle，仅 Empty]
  场
    类型: 风
    体积
      形状: 球形 | 方形
    风（仅当类型 = 风）
      风速
      紊流
      紊流细节（仅当紊流 > 0，默认折叠）
        空间尺度 / 时间频率 / 叠加层数
        频率倍率 / 幅值衰减 / 随机种子
    高级属性（默认折叠）
      场 ID 修复
      混合权重 / 优先级
      作用域过滤
~~~

用户自行创建 Blender Empty，再打开集中面板中的“场”开关；没有 Field 创建 operator。面板总是先显示类型，再显示该类型内部的体积和参数。方向由 Empty 旋转和 viewport 箭头表达，不再增加一个容易与 transform 冲突的 XYZ 方向属性。混合权重、优先级、consumer/Collection/对象/碰撞组过滤全部归入默认折叠的高级属性，不占用基础工作流。

### 8.2 作者预览与运行态调试

作者预览是创作注册状态的静态视图，固定规则为：

- `time_source="AUTHOR_STATIC"`、`sample_time_seconds=0`；不注册 `frame_change` handler，不随播放或时间线位置逐帧展示 turbulence；
- 属性、transform、depsgraph、load/undo/redo 或 overlay 设置变化时才重建冻结绘制批次；
- 显示 sphere/box 真实 bounds、Sphere 线性权重层、Box 硬边界、Empty local +Z、selected/combined 的 `t=0` 箭头，以及 active/preview/reserved/invalid 状态；
- glyph scale/density 只改变显示，不改变采样值。作者预览可以使用 Python reference sampler，但不能声称代表某个正在推进的 world 子步。

运行态由物理世界调试分类下的“场-运行可视化调试”节点负责：

- 节点请求未打开 `Volume边界` 或 `空气速度` 时，不读 world cache、不采样、不安装 draw handler；
- 打开后严格核对 `PhysicsWorldCache.generation`、`PhysicsFrameContext`、`FieldSnapshotV0` 签名和 native inspect；边界只借用与 runtime 同签名的 Snapshot，运行身份与数值真值来自 live `NativeFieldRuntimeV1`；
- 空气速度调用 native evaluator，时间固定取本次 World FrameContext 的帧起始 `sample_time_seconds`，并按独立 participation 过滤箭头；不重新扫描 Scene、不读取 RNA 推算运行值；
- 当前简洁节点不提供 Object/Collection/碰撞组 consumer context。存在这些高级 scope 的 Field 时只画边界并明确拒绝风箭头，不能伪造“全局 MC2 partition”；
- World Begin 使旧批次失效；world dispose、cache clear、load 和插件注销必须移除对应 draw store/handler。

运行态调试的验收原则是：同一 runtime、位置、consumer context 和 sample time 下，调试 native sample 与 solver 调用的 evaluator 完全相同。显示层可为可读性裁剪箭头长度，但不能改变方向、相对幅值或 turbulence 相位。

这个节点同时建立通用物理运行调试合同：凡是碰撞、约束、场或其它能力需要“裸读正在运行的真实状态”，都必须有请求驱动的专有调试节点，从所属 native/world owner 的 inspect/read API 读取 production truth；作者预览、RNA、重算近似或普通 world 文本摘要不能替代。目前只实现 Field，运行中碰撞等专有节点作为后续公共能力记录，不在本阶段伪造。

## 9. MC2 消费契约

### 9.1 MC2 只传 runtime 身份与时间

紊流按空间变化，因此数值仍然是逐粒子向量；但逐粒子位置和结果都留在 C++。生产 ABI 固定为：

~~~text
Python per fixed substep
  field_runtime = {
    handle: uint64,
    sample_time_seconds: float64,
  }

MC2 DomainV1 native
  Domain-owned world_positions_f32[N,3]
  + particle_partition_index[N]
  + static FieldSampleContextV1[P]
  + FieldRuntimeV1(handle)
  -> reusable air_velocity_f32[N,3]
  -> participation_u8[N]
~~~

约束：

- Python/native 子步边界只接受 `handle` 与 `sample_time_seconds` 两个标量，不允许粒子位置、空气速度、signature bytes、request 列表或 Python callback 回流；
- product slot 在 native step 前验证 runtime 的 `generation`、`frame` 和帧起始 `sample_time_seconds` 与当前 World/frame packet 完全一致；过期或已释放 handle 在 solver mutation 和 scheduler commit 前失败；
- 每个 fixed 子步的 native prepare 直接读取上一成功子步已提交的 Domain-owned world positions，在任何 Teleport/Center/Integration mutation 前调用公共 evaluator；
- 采样时刻只由 Physics World 的 Blender 输出帧时间派生：`sample_time_seconds + frame_step_dt * update_index / update_count`。不得使用 MC2 fixed 累加器、帧号、时间线作者预览或墙钟；
- Domain 静态同步时一次上传每个 partition 的 consumer context。Mesh 使用源 Object 名，Bone 使用 Armature 名，Collection 使用 `users_collection` 名称，低 16 位碰撞组映射为公共组；粒子到 partition 的索引由 compiled program 持有。context 配置属于 Domain static staged transaction，不允许先替换 live owner 再补写；context 语义变化即使 compiled program 可复用，也必须创建并配置新 Domain，成功后才原子替换；
- 无 runtime、无有效 Field、全部 response 为零或全部未参与都是合法 fast path；响应全零时不得调用 evaluator，也不得产生 N 规模 Python/native 搬运；
- MC2 native 只看最终 `air_velocity`、独立 participation 与自身 response strength，不分支判断 Field generator/preset；
- runtime identity/time 属于 frame/substep value，不进入 MC2 topology key。consumer contexts 只随 Domain static identity 同步，response 只随 parameter update 同步。

### 9.2 native 接入边界

MC2 接入分成两个 native 职责：

~~~text
Public FieldRuntimeV1 evaluator
  Domain position/context views + time + caller-owned scratch/output
  -> air_velocity_world[N,3] + participation[N]

HoTools MC2 Wind Response V0
  air_velocity + participation + particle velocity/normal + response strength
  -> MC2 integration contribution
~~~

不能把 `air_velocity` 直接当作 acceleration 相加；它的单位和物理意义不同。本地 MC2 2.18.1 源码只用于核对接入阶段、旧字段和回归边界，不作为 HoTools 的 wind 数值模板。V0 使用独立、版本化的相对空气速度松弛模型：

~~~text
relative_velocity = air_velocity - cloth_state_velocity
normal_part       = dot(relative_velocity, normal) * normal
tangent_part      = relative_velocity - normal_part
coupled_velocity  = normal_part + 0.15 * tangent_part
alpha             = 1 - exp(-response_strength_per_second * dt)
cloth_state_velocity += alpha * coupled_velocity
~~~

约束：

- `response_strength_per_second` 非负，单位 `1/s`；`0` 表示没有响应；指数形式保证响应不会因 MC2 子步划分不同而改变目标速度或越过空气速度；
- 法线耦合固定为 `1.0`，切向耦合固定为 `0.15`，V0 不为它们增加 UI；法线退化时回退为各向同性相对速度；
- 固定粒子不响应；该 pass 修改积分使用的持久速度，并位于 Center inertia 后、Integration 前；
- V0 不读取 collision friction、depth 或任何旧 MC2 wind 参数；公共 Field 已经负责方向、速度、Volume、衰减、turbulence 和多场合成；
- MC2 创作面只公开 `field_wind_enabled` 开关和 `field_wind_strength` 强度。开关关闭时该 partition 的逐粒子强度为零，默认强度为 `1.0 1/s`，有效范围为 `0..20 1/s`；旧 wind 字段不存在，也不参与任何映射。

当前产品子步顺序已经冻结为：

1. Python 校验 World/runtime 身份并只提交 handle 与固定子步时间；
2. native `prepare_field_wind` 在任何 solver mutation 前，从 Domain-owned positions 和静态 consumer contexts 调用公共 evaluator；
3. `TaskReferenceTeleport -> CenterFrameShift -> Center -> CenterInertia`；
4. 对 `participation != 0` 且 response 非零的粒子执行 `FieldWindResponse`；
5. 执行 `Integration`，再进入后续约束、碰撞和 post passes。

Field participation 与数值零已经分离。作用域不匹配、Volume 外或没有任何有效 Field 时 participation 为 0，MC2 把有效 response 置零；如果多个参与 Field 精确抵消出零向量，participation 仍为 1，可表达“空气速度为零但布料应向静止空气收敛”。禁止重新用 epsilon 或向量零值猜测参与状态。

### 9.3 旧七字段的删除结论

以下七项已从 HoTools MC2 的 preset、profile、runtime ABI 和节点接口删除：

~~~text
wind_influence
wind_frequency
wind_turbulence
wind_blend
wind_synchronization
wind_depth_weight
moving_wind
~~~

删除原则：

- 无效字段不以“隐藏兼容数据”的形式继续占用架构和测试成本；
- 不提供旧字段到公共 Field 或 MC2 响应的自动迁移；
- Field 负责 `speed_mps`、方向、Volume、衰减、turbulence、时间采样、作用域和多场合成；
- MC2 只负责 `field_wind_enabled` 与 `field_wind_strength`；
- profile、preset 和 runtime 不接受七个旧字段作为输入；依赖它们的旧资产必须由用户重新创作公共 Field，不做自动迁移、近似风或 fallback。

## 10. Consumer Capability

Field core 不为任一 solver 私有化。每个 consumer 必须声明：

~~~python
FIELD_CAPABILITY = {
    "source_capability_id": "field_air_velocity",
    "channel_id": "air_velocity",
    "rank": "vector",
    "unit": "m/s",
    "source_kinds": ("analytic",),
    "volume_shapes": ("sphere", "box"),
    "sample_mode": "per_particle",
    "sample_phase": "pre_substep",
    "value_space": "world",
    "response": "hotools_relative_air_velocity_v0",
    "runtime": "PhysicsWorld.FieldRuntimeV1",
    "runtime_abi_version": 1,
    "solver_abi": "scalar_handle_and_world_time_only",
    "particle_data_crossing_python_native": 0,
    "implementation_status": "native_direct_cpu_product_v1",
}
~~~

最小诊断：

~~~text
FIELD_UNSUPPORTED_CHANNEL
FIELD_UNSUPPORTED_SOURCE
FIELD_UNSUPPORTED_SAMPLE_MODE
FIELD_OUT_OF_SCOPE
FIELD_INVALID_SPEC
FIELD_INVALID_RUNTIME
FIELD_PREVIEW_ONLY
FIELD_CONSUMER_NOT_REGISTERED
FIELD_VOLUME_NON_UNIFORM_SPHERE
FIELD_ATTENUATION_POLICY_UNSUPPORTED
~~~

任何额外 consumer 都只能通过独立 capability 声明采样 mode、phase、单位与自身 response。公共 Field 层不能把 `m/s` 自动转换成 `m/s²`，也不能替 consumer 猜测响应模型。

## 11. 代码所有权：Field 必须单独成包

Field 已同时包含持久属性、公共 ABI、Volume、生成器、批量采样、可视化、生命周期和 consumer capability，复杂度足以形成 Physics World 下的一级领域包。它不能继续堆在公共杂项模块，也不能位于任何具体 consumer 的私有包中：

~~~text
OmniNode/PhysicsWorld/field/
  __init__.py
  names.py
  channels.py
  specs.py
  diagnostics.py
  properties.py
  implicit_objects.py
  volume.py
  wind.py
  sampling.py
  native.py
  capabilities.py
  visualization.py
  debug_draw.py
  test/
~~~

现有公共 UI 目录只负责集中面板和 Field ID 修复；对象创建使用 Blender 原生 Empty，consumer adapter 只保留转换：

~~~text
PhysicsWorld/field/*         # authoring-neutral Field ABI、native owner、reference sampler 与调试
PhysicsWorld/ui/*            # 集中面板与 Field ID 修复入口
PhysicsWorld/mc2/*           # MC2 consumer context、runtime调度与response mapping
PhysicsWorld/<consumer>/*    # 其它 consumer 的 capability 与 response mapping
_native/src/field_runtime.*  # 公共Field registry/evaluator/scratch
_native/src/mc2_domain_cpu.* # MC2 Domain直接消费公共runtime
~~~

依赖方向必须固定：

1. `field/specs.py`、`field/volume.py`、`field/wind.py` 和 reference sampler 不依赖 `mc2` 或具体 solver。
2. `field/properties.py` 和公共 UI adapter 负责 bpy 边界；纯 spec/sampler 不持有 bpy。
3. consumer 只能通过 Field 公共导出读取 spec/sample，不能导入 Field UI 或修改 Field Asset。
4. 公共 native evaluator 形成独立 `field_runtime_v1` ABI；MC2 只借用 handle 并传 Domain-owned views，不能复制 Field 算法或取得 runtime 所有权。
5. 新目录、模块职责和注册顺序必须同步进入 [Architecture](../ARCHITECTURE.md) 及 Physics World 注册表文档。

当前同时保留可读的 Python 标量/batch reference 与生产 native evaluator，并逐样本做差分对比。Python 路径只服务 golden、诊断和作者工具；solver 热路径不得恢复 Python sampler。未来 CPU SIMD 或 GPU 版本必须共享 Field 定义、版本、scope、participation、固定遍历顺序和 golden，物理布局与 scratch owner 可以独立。

## 12. 当前实现状态与剩余闸门

### 12.1 已落地：Field core 与创作

- `FieldSpecV0`、`FieldSnapshotV0`、channel registry、diagnostics 和确定性签名；
- 独立 `PhysicsWorld/field/` 领域包与 `physics.field` implicit object manifest 对账；
- 用户手建 Empty、集中面板、类型优先显示、持久 Field ID、save/load/undo/animation；
- sphere 线性衰减、box 硬边界、作用域、加法合成、`AUTHOR_STATIC/t=0` 作者预览与请求驱动运行可视化；
- 有值的 `air_velocity` 为 `ACTIVE`，其余 channel 只做不伪造数值的 `RESERVED` 占位。

### 12.2 已落地：WindV0

- 单一 `analytic.wind.v0` 生成器和 world-space `air_velocity`；
- `turbulence=0` uniform fast path 与 `turbulence>0` 的确定性四维、多 octave 时空采样；
- 单点 reference、批量 sampler 与 visualizer 共用同一数值定义；
- sphere/box Volume、scope、priority/field ID 固定顺序和 blend weight；
- 时间只来自 Physics World 对 Blender 输出帧率的解释。

### 12.3 已落地：MC2 CPU product consumer

- `mc2_field_air_velocity` capability，状态为 `native_direct_cpu_product_v1`；
- World Begin 公共 `NativeFieldRuntimeV1`、单调 `uint64` handle、transactional replacement 与 world cache dispose；
- Domain 静态 consumer contexts、参数热更新 response buffer、逐 logical particle/逐 fixed substep 的 native direct sample；
- 子步 Python/native 只跨越 handle 与严格 World sample time，粒子位置、空气速度和 participation 全部留在 C++；
- MC2 profile 只公开 `field_wind_enabled` 和 `field_wind_strength`；
- native 相对空气速度响应、固定粒子跳过、退化法线回退和 Center inertia -> Field wind -> Integration 顺序；
- 无 Field/关闭响应/未参与的 no-op 路径，participation 与精确零向量分离，以及 runtime 身份/时序错误在 native mutation 前失败；
- 三 setup 的600帧双轮产品矩阵已经验证有限性、确定性、响应关闭位级no-op、均匀风响应、精确作用域和Blender输出FPS派生的子步时间；`field_wind_response` capability 状态为`verified`；
- 旧七个 MC2 wind 字段已删除，不存在兼容层或第二套公开风参数。

### 12.4 仍需保留的闸门

- 公共 World cache 对非连续 seek/cache read 的持久时间恢复；
- Blender scene unit 到米的正式公共所有权；V0 仍明确采用 `1 Blender unit = 1 m` 的 provisional policy；
- attenuation、blend 与多 channel 权重的长期所有权；
- participation 当前是 evaluator 的 `u8` 输出；若未来需要连续权重，必须决定它与 Volume attenuation/blend 的关系，而不是重新复用空气速度零值；
- 大粒子数、不同 partition 数下 native evaluator、scratch 复用与 Field wind pass 的分项性能；Python/native 粒子数据穿越必须保持为零；
- Python batch/reference 与 native evaluator 的 golden sample 一致性，以及未来 SIMD/GPU evaluator 的确定性/容差合同。
- MC2 live Domain 的完整子步数值 rollback 尚未成立；Field prepare 与 runtime/time 校验只保证在首次 solver mutation 前失败。公开产品入口会 dispose 本批 attempted owners，恢复 feedback，并在后续调用冷建新 owner；但低层 `step_mc2_product_substep()` 仍没有失败状态或原地重试门禁，只有明确发生在 native mutation 前的失败才可安全重试。该门禁属于 MC2 通用事务，不由 Field 私自补丁。

## 13. 测试矩阵

Field identity/lifecycle：

- stable ID、rename、duplicate、delete、disable、undo、save/load；
- implicit object manifest 对账；
- config/value signature 分离；
- scene reload、addon unregister/register；
- active、preview_only、reserved、invalid diagnostics；Blender RNA 不公开状态开关。

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

- box 内不同位置、不同时间返回同一基础向量；sphere 内方向不变、幅值只按线性 Volume 权重变化；
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

- 三 setup 的600帧双轮确定性、响应关闭位级no-op、均匀风与逐setup精确作用域；
- absent Field 保持当前数值 parity，全部 response 为零不调用 evaluator；
- stale/invalid/disposed runtime handle 在任何 solver mutation 与 scheduler commit 前拒绝；
- uniform wind 的方向和幅值；
- turbulence 在同一 cloth 内产生逐粒子差异；
- Domain static consumer contexts 与 partition 粒子映射完整且稳定；
- frame/substep 时间推进；
- reset、seek、cache read；
- 不同 partition 数量结果一致；
- 旧七字段在 profile、preset、runtime ABI 和节点接口中均不存在；
- participation=0 不产生响应；participation=1 且合成空气速度精确为零时保留静止空气响应；
- evaluator 输出超出 `float32` 或出现非有限值时整批拒绝，调用方输出与 MC2 sample-valid 状态不部分提交；
- ABI 结构断言每子步 Python 只传 handle/time，且不存在位置 readback、Python sampler、逐粒子 packet 或 N 规模 response 展开；
- 1k/16k/64k 粒子、1/8/32 partition 的 native sample/response 分项耗时、预热后分配与工作量计数。

可重复基准入口为 `_native/tests/benchmark_field_runtime_native.py`。它直接创建
MC2 Domain，先提交一帧 Domain-owned positions，之后热循环只调用
`prepare_field_wind(handle, sample_time)` 与 `step_prepared_field_wind(dt)`；默认矩阵覆盖
`disabled`、`scope-miss`、uniform、sphere、turbulence 与 sparse Volume。基准不得把
位置读回或 Python sampler 纳入热循环；结果保存 JSON Lines 后再比较同一 ABI/机器的
中位数、P95、sample/apply 计数和 `field_sample_buffer_valid`。

可视化与调试：

- 作者预览跨帧始终报告 `AUTHOR_STATIC/t=0`，没有 `frame_change` handler；
- 运行调试关闭时 cache read、native sample 和 draw handler 均为零；
- 开启后核对 native inspect、World FrameContext 与同签名边界快照；stale runtime 必须清空旧批次并报错；
- 高级作用域没有 consumer context 时拒绝空气速度箭头；
- World Begin、dispose、cache clear、load/unregister 清理对应 draw store。

## 14. 实现参考

这些资料只提供接口或算法参考，不直接成为运行时依赖：

| 资料 | 参考价值 |
|---|---|
| [OpenVDB](https://github.com/AcademySoftwareFoundation/openvdb) | 后续 sparse Volume、采样和缓存表示 |
| [FastNoise2](https://github.com/Auburn/FastNoise2) | SIMD coherent noise 的实现与性能参考 |
| [FastNoiseLite](https://github.com/Auburn/FastNoiseLite) | 小型、可移植的版本化 noise 参考 |
| [Houdini Volume docs](https://www.sidefx.com/docs/houdini/model/volumes.html) | Field/Volume 数据模型和可视化 |
| [Magica Cloth 2 Wind docs](https://magicasoft.jp/mc2_magicacloth_wind/) | MC2 source/cloth response 语义与验收参考 |

采用任何第三方 noise/storage 实现前，必须单独审计许可证、确定性、CPU 架构一致性、Blender 打包成本和长期 ABI；公共 `FieldSpecV0` 不依赖第三方对象模型。

## 15. V0 已冻结事项与明确质疑点

已冻结并进入代码与测试的事项：

1. `noise_algorithm_version=0` 使用确定性的四维 value noise、固定 hash、octave seed 递进和 float32 输出；reference 与 batch 路径必须保持 golden sample 一致。
2. Wind source 输出 world-space `air_velocity`，MC2 response strength 为 `0..20 1/s`，法线/切向耦合固定为 `1.0/0.15`。
3. Field runtime 在任何 solver mutation 前从 MC2 Domain-owned positions 采样；响应在 Center inertia 后、Integration 前应用，固定粒子不响应。
4. 旧七个 MC2 wind 字段、Python 位置 readback、Python 子步 sampler 和逐粒子桥接对象已删除且不映射；Field 与 MC2 子步之间只有 runtime handle 与严格 World sample time 两个标量。
5. native evaluator 输出独立 `participation`，零向量不再兼任“未参与”；调用方持有输出与 scratch，生产路径不跨 Python/native 搬运 N 规模粒子数据。
6. 作者预览固定 `AUTHOR_STATIC/t=0`；运行态调试必须请求驱动并读取 live native runtime + World FrameContext。

仍需明确保留、不能被当前实现掩盖的质疑点：

1. attenuation 最终由 Volume、generator 还是 channel mapping 拥有，以及它在 blend 前后的顺序。V0 暂用 `effective = volume_weight * raw`，不得据此提前扩展曲线 UI。
2. V1 已用离散 participation 区分未参与与精确零向量；仍未冻结的是是否需要连续 participation/weight、它与 attenuation/blend 的先后顺序，以及 MC2 是否只消费离散参与。
3. scene unit scale 到米的公共入口尚未冻结；当前 `1 Blender unit = 1 m` 只能作为有诊断的 provisional policy。
4. native scratch/output 的容量增长、对齐、线程模型与未来 GPU staging 需要用规模/partition 矩阵决定；当前 registry 的 GIL 串行假设不能延伸到释放 GIL、native worker 或异步 GPU，跨线程前必须采用显式同步与 `shared_ptr` 调用租约。无论实现如何变化，Python/native 子步边界都不得恢复 N 规模粒子数据穿越。
5. 非连续 seek/cache read 必须由公共 World cache 恢复同一 `sample_time_seconds`；Field 不建立私有补偿时钟。
6. 高级作用域当前使用对象/Armature 名、Collection 名和公共碰撞组号。若以后需要抗重命名的资产引用，必须显式升级 scope schema，不能悄悄改变 V0 名称匹配语义。
