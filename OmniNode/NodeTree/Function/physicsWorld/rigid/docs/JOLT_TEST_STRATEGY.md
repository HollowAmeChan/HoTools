# Rigid/Jolt 语义测试策略与验收矩阵

日期：2026-07-10

状态：设计基线。实现完成前，不得把现有回归通过解释为“Rigid/Jolt 物理语义已验收”。

适用版本：HoTools `rigid_jolt`、Jolt Physics `v5.2.0`、Blender 4.5。当前 native backend 使用 `JobSystemSingleThreaded`。

## 结论

当前 Jolt 测试覆盖了不少功能，但还没有形成独立、可复用的**物理语义验收体系**。

现有 native 与 Blender 测试可以证明：模块能创建、推进和销毁世界；spec、adapter、result stream、writeback 和生命周期基本贯通；自由落体、落地、约束、contact、sensor、RayCast、断裂和独立 A/B frame 的功能链路可运行。

它们不能系统证明：

- 每个 HoTools 参数与 Jolt v5.2.0 的真实语义一致；
- 每种已接约束真正移除/保留了文档声明的自由度；
- limit、spring、friction、motor、质量、阻尼、CCD、sleep 和过滤的数值行为正确；
- 同一输入可稳定重放，Blender 枚举变化不会改变 Jolt 添加顺序；
- Jolt、binding、adapter、Blender 写回中哪一层导致轨迹偏差；
- 升级 Jolt、编译器或 ABI 后，哪些变化合理、哪些是回归。

所以 `native 30/30`、`Blender 23/23` 继续作为 API/链路回归；物理验收必须由本文定义的 semantic matrix 单独给出结论。

### 2026-07-10 实现状态

可执行切片 `physicsWorld/rigid/test/` 已落地：

- `hotools_jolt_fixture_v1` 严格 JSON schema；
- `native_binding_v1` runner，按 fixture body id 稳定创建刚体；
- position/rotation/velocity/active/sleeping 的 canonical JSONL trace 与原始 float32 bit pattern；
- 每个 fixture 使用两个全新 `JoltWorld` 做 bitwise trace 重放；
- `finite_all`、半隐式自由落体、零重力恒速、冲量质量关系与显式 body state oracle；
- 48 个 P0 fixture，覆盖刚体参数、形状、碰撞、过滤、事件、查询和约束；
- 七种已接入约束均有 schema、state trace 和独立物理 oracle；
- Fixed 相对变换、Point 锚点重合/自由旋转、Distance 区间残差收敛 oracle；
- Hinge 局部 Z 单轴旋转、Slider 局部 Z 单轴平移、Cone swing/twist oracle；
- Hinge 正负角度 limit、Slider 正负线性 limit 的双向撞限 oracle；
- py311/py313 各自 48/48 S1 通过，并在各 ABI 内完成同进程双世界逐位重放；py311 已完成十个新进程 physical hash 稳定检查；
- `_native/tests/test_jolt_semantic_matrix.py` 已接入现有 native test discovery。

当前 S1 已验收 body 积分/阻尼/速度上限/DOF、shape offset/rotation、七种约束的基础语义、Distance/Hinge/Slider 数值行为、SwingTwist 摆角/扭转限制、动态-动态反作用、碰撞恢复/摩擦/filter/CCD，以及 contact 状态机和 RayCast 几何语义。复杂 Cone/SwingTwist A/B frame 组合、SwingTwist orientation motor、adapter parity、Blender E2E、跨 ABI 报告和 golden 尚未实现，不能据此宣称完整 Jolt 语义通过。

## 验收边界

同一份声明式 fixture 必须能经过三条路径并产生相同格式的规范化 trace：

```text
fixture.json
  ├─ native runner  -> hotools_jolt.JoltWorld -> trace
  ├─ adapter runner -> RigidBodySpec / ConstraintSpec -> JoltAdapter -> trace
  └─ Blender runner -> 属性 / scope / world / writeback -> trace
```

| 层 | 目标 | 可以证明什么 |
|---|---|---|
| S0 Contract | spec、单位、默认值、归一化、非法输入 | 公共协议明确且稳定 |
| S1 Native semantics | 直接调用 `JoltWorld` | binding 创建的 Jolt body/constraint 具有目标行为 |
| S2 Adapter parity | spec + adapter 与 S1 对拍 | 公共语义正确映射到 native ABI |
| S3 Blender E2E | 后台 Blender 跑完整管线 | 属性、scope、生命周期、result、writeback 最终一致 |

S1 是物理 case 的主层；S2、S3 复用同一 fixture 和断言，不能各写一套含糊场景。

## Oracle：什么叫正确

每个 case 必须声明 oracle，禁止只写“位置变了”“没有飞走”或“看起来合理”。优先级如下：

1. **解析 oracle**：无碰撞积分、冲量动量关系、恒速、射线几何、理想自由度等直接计算。
2. **Jolt 官方语义 oracle**：从本地 v5.2.0 的 `UnitTests/Physics` 与 `Samples/Tests` 提炼场景和判据，例如 Hinge/Slider/Distance spring、CCD、Sensor、determinism。只移植行为，不复制 Jolt 实现。
3. **差分 oracle**：S2/S3 与 S1 在相同 fixture、时间步和添加顺序下比较 trace。
4. **不变量/变形 oracle**：复杂接触使用自由度残差、守恒关系、对称性以及旋转/平移后的等价性。
5. **版本化 golden trace**：只检测已验收行为是否漂移，不能单独证明正确。

解析、官方语义、不变量或差分失败时，不允许更新 golden 让测试变绿。

不采用 viewport 截图、当前实现首次输出、没有中间轨迹的单个最终帧、或 Blender/Bullet 对拍作为权威 oracle。Blender/Bullet 只能提供趋势参考，并不定义 Jolt 语义。

### 与 SpringBone 蓝本的关键差异

SpringBone 迁移时有 legacy/context 两条 ABI 和旧/新路径，可以做逐帧数值 parity；Jolt 没有一套可信的 HoTools 旧 solver 可作为总 oracle。若只是让 adapter 与当前 `JoltWorld` 对拍，只能证明两层一致，不能证明 binding 里 Hinge 轴、spring 参数或质量映射就是对的。

所以 Jolt 沿用 SpringBone 的 fixture、矩阵、后台 Blender、soak 和性能方法，但正确性核心必须改成“解析行为 + Jolt v5.2.0 官方 unit-test 语义 + 自由度不变量”。三层差分负责定位映射错误，不能替代独立语义 oracle。

## Fixture 协议

场景由数据描述，runner 只构建、推进、采样和断言。建议首版 JSON：

```json
{
  "schema": "hotools_jolt_fixture_v1",
  "id": "FREE-001",
  "title": "zero-damping free fall",
  "source": "analytic",
  "tags": ["p0", "body", "gravity"],
  "world": {
    "gravity": [0.0, 0.0, -9.81],
    "dt": 0.016666666666666666,
    "substeps": 1,
    "frames": 120
  },
  "bodies": [
    {
      "id": "ball",
      "type": "DYNAMIC",
      "shape": {"type": "SPHERE", "radius": 0.5},
      "position": [0.0, 0.0, 10.0],
      "mass": 2.0,
      "linear_damping": 0.0,
      "angular_damping": 0.0,
      "allow_sleeping": false
    }
  ],
  "timeline": [],
  "sample_frames": [0, 1, 2, 30, 60, 120],
  "assertions": [
    {"kind": "semi_implicit_free_fall", "body": "ball", "position_abs": 0.00002, "velocity_abs": 0.00002},
    {"kind": "finite_all"}
  ]
}
```

协议要求：

- body、constraint、command 都有 fixture 内唯一稳定字符串 id；
- body/constraint 进入 Jolt 前按 stable id 排序，禁止依赖 collection、dict 或 pointer 枚举顺序；
- timeline 明确命令位于 `pre_step` 或 `post_step`；
- 显式写出影响结果的值，不依赖 UI 默认值；
- 角度为弧度，长度为米，质量为千克，时间为秒，冲量为 N·s；
- `source` 必须是 `analytic`、`jolt_unit_test:<name>`、`metamorphic:<rule>` 或 `approved_golden:<id>`；
- runner 拒绝未知字段、重复 id、非有限值和无效引用。

## Trace、规范化与容差

每个采样帧输出一条 JSONL，至少包含：

```text
fixture_id, runner, frame, dt, substeps
bodies[id] = position, rotation_wxyz, linear_velocity, angular_velocity, active, sleeping
constraints[id] = enabled, value_kind, current_value, position/rotation/limit/motor lambda,
                  lambda_max_abs, broken
contacts = state, body_a, body_b, sensor flags, normal, penetration, points
queries = query_id, hit, body_id, position, normal, fraction, distance
stats = body_count, constraint_count, contact counts, overflow, step_ms
```

规范化规则：

- body、constraint、query 按 stable id 排序；contact 先规范化 body pair 再排序；
- quaternion 归一化并固定半球，优先 `w >= 0`；接近零的 `-0.0` 变为 `0.0`；
- NaN/Inf 立即失败，不进入容差比较；
- event 默认比较规范化集合与状态机，不依赖 callback 到达顺序；
- trace 同时保留原始 float bit pattern，用于同构建确定性检查；
- `step_ms` 不进入 physical hash，只进入性能产物。

| 类型 | 默认判据 |
|---|---|
| bool、enum、count、stable id、event state | 精确相等 |
| 同进程两个新 world、同一 binary/config | body/constraint 原始 float bitwise 相等 |
| py311/py313、S1/S2/S3 | `abs <= abs_tol + rel_tol * max(abs(a), abs(b))` |
| position/length | case 按尺度声明；1m 级首版通常 `2e-5 m` |
| velocity | case 声明；首版通常 `2e-5 m/s` 或 `rad/s` |
| rotation | 最短 quaternion 夹角；首版通常 `2e-5 rad` |
| 约束 | anchor 距离、锁定轴位移、限制超量、相对旋转等物理残差 |
| 长轨迹 | 关键帧 + 最大残差 + RMS，不能只比最终帧 |

容差属于 fixture/oracle，不是 runner 全局常量。扩大容差必须说明物理原因。

## 首版语义矩阵

`现有弱覆盖` 表示测试跑到功能但判据不足以验收；`仅创建` 表示只证明对象能建出来。

### 自由运动、刚体参数与 Shape

| ID | 场景 | 核心判据 | Oracle | 优先级 | 当前 |
|---|---|---|---|---|---|
| FREE-001 | 零阻尼自由落体 | 多关键帧位置/速度符合固定步长积分；XY 不漂移 | 解析 | P0 | PASS (S1) |
| FREE-002 | 零重力恒速/恒角速 | 速度不变，位置和旋转线性 | 解析 | P0 | 部分：线性 PASS (S1) |
| FREE-003 | gravity factor `0/0.5/1/2` | 加速度按比例缩放 | 解析/变形 | P0 | PASS (S1) |
| BODY-001 | 线性冲量、质量 `1/2/10` | `delta_v = J/m` | 解析 | P0 | 部分：mass 2 PASS (S1) |
| BODY-002 | angular impulse | 方向正确且符合 shape inertia 响应 | Jolt/解析 | P1 | 现有弱覆盖 |
| BODY-003 | 恒力/torque | 单步和多步速度变化正确 | 解析/Jolt | P0 | 已实现 |
| BODY-004 | linear/angular damping `0/0.1/1` | 逐帧符合 Jolt 阻尼公式 | Jolt/解析 | P0 | 已实现 |
| BODY-005 | max linear/angular velocity | 超限输入按向量模长钳制并保持方向 | Jolt | P0 | 已实现 |
| BODY-006 | allowed DOFs 六轴逐轴锁定 | 锁轴残差在容差内，未锁轴可动 | 不变量 | P0 | 已实现 |
| BODY-007 | sleeping、唤醒、禁用 sleep | 显式状态转换、冲量唤醒和禁用 sleep 正确 | Jolt | P0 | 已实现 |
| SHAPE-001 | sphere/box/capsule/cylinder | 支撑高度及 Capsule/Cylinder 默认 Y 轴符合 Jolt | 解析/Jolt | P0 | 已实现 |
| SHAPE-002 | tapered capsule/cylinder | 两端半径方向及旋转后命中正确 | 解析/Jolt | P1 | 仅创建 |
| SHAPE-003 | plane local XY/+Z | 旋转后世界法线与命中点正确 | 解析 | P0 | 已实现 |
| SHAPE-004 | shape offset + rotation | body 原点与 RayCast 几何分离正确 | 解析/差分 | P0 | 已实现 |
| SHAPE-005 | 非法/退化尺寸 | fixture 协议在进入 native 前明确拒绝 | Contract | P0 | 已实现 |

### 碰撞、材质、CCD、过滤与事件

| ID | 场景 | 核心判据 | Oracle | 优先级 | 当前 |
|---|---|---|---|---|---|
| COLL-001 | 无摩擦正碰，restitution `0/0.5/1` | 法向速度符合质量/恢复系数关系 | 解析 | P0 | 已实现 |
| COLL-002 | 平面摩擦 `0/0.5/1` | 锁定旋转后逐帧符合库仑摩擦解析轨迹 | 解析/Jolt | P0 | 已实现 |
| COLL-003 | dynamic/static/kinematic 配对 | static 不动；kinematic 正确推动 dynamic | Jolt | P0 | 已实现 |
| COLL-004 | sensor 穿越 | added/persisted/removed 完整且不阻挡轨迹 | Jolt SensorTests | P0 | 已实现 |
| COLL-005 | DISCRETE vs LINEAR_CAST 高速薄墙 | 离散可穿透、CCD 命中并产生正确事件 | Jolt MotionQualityLinearCastTests | P0 | 已实现 |
| FILTER-001 | 第 1/16 组双向 mask 边界 | 只有双方 mask 均允许时碰撞 | HoTools/Jolt | P0 | 已实现 |
| FILTER-002 | constraint disable collisions | 约束存在时无接触，删除后恢复 | HoTools | P0 | 已实现 |
| FILTER-003 | 多约束 pair-filter 引用计数 | 删除最后一个约束时才恢复碰撞 | HoTools | P0 | 已实现 |
| EVENT-001 | contact 状态机 | added -> persisted -> removed，字段有界 | Jolt | P0 | 已实现 |
| EVENT-002 | sensor result channel | 状态机完整且不改变穿越轨迹 | HoTools/Jolt | P0 | 已实现 |
| EVENT-003 | overflow | 计数准确、内存有界、后续帧恢复 | HoTools | P1 | 缺失 |

### 七种约束

每种约束至少覆盖 `body-body`、`body-world`、共享 world frame、独立 local A/B frame 和旋转 frame。不能只检查 `constraint_count == 1`。

| ID | 场景 | 核心判据 | Oracle | 优先级 | 当前 |
|---|---|---|---|---|---|
| FIXED-001 | Fixed 受重力/冲量 | 相对位置/旋转保持，六自由度残差有界 | 不变量 | P0 | PASS (S1) |
| POINT-001 | Point 受离轴冲量 | anchors 重合，相对旋转可自由变化 | 不变量 | P0 | PASS (S1) |
| DIST-001 | `min == max` 刚性杆 | 距离收敛到目标且横向自由 | 解析/Jolt | P0 | PASS (S1) |
| DIST-002 | `[min,max]` 区间 | 区间内无纠正，越界纠正至最近边界 | Jolt | P0 | PASS (S1) |
| DIST-003 | limit spring | 多帧轨迹与 Jolt DistanceConstraintTests 同义 case 一致 | Jolt official | P0 | 已实现 |
| HINGE-001 | Hinge 自由度 | 三平移、两旋转锁定，只绕 frame Z 转 | 不变量 | P0 | PASS (S1) |
| HINGE-002 | angular min/max | 正负方向撞限，超量和速度有界 | Jolt | P0 | PASS (S1) |
| HINGE-003 | limit spring | 角轨迹与 Jolt HingeConstraintTests 同义 case 一致 | Jolt official | P0 | 已实现 |
| HINGE-004 | velocity motor | 目标角速度与 motor lambda 正确 | Jolt | P0 | 已实现 |
| HINGE-005 | position motor | 位置弹簧轨迹与目标角度正确 | Jolt official | P0 | 已实现 |
| HINGE-006 | friction torque | 角速度按最大摩擦 torque 衰减 | 解析/Jolt | P0 | 已实现 |
| SLIDER-001 | Slider 自由度 | 两横向平移和全部旋转锁定，只沿 frame Z 移动 | 不变量 | P0 | PASS (S1) |
| SLIDER-002 | linear min/max | 正负方向撞限，位置/速度符合官方 case | Jolt official | P0 | PASS (S1) |
| SLIDER-003 | limit spring | 位置轨迹与官方同义 case 一致 | Jolt official | P0 | 已实现 |
| SLIDER-004 | friction force | 速度/位置符合力上限解析结果 | 解析/Jolt | P0 | 已实现 |
| SLIDER-005 | velocity motor | 目标速度与 force limit 正确 | Jolt official | P0 | 已实现 |
| SLIDER-006 | position motor | 位置弹簧轨迹与目标位置正确 | Jolt official | P0 | 已实现 |
| CONE-001 | cone swing limit | anchor 重合，swing 不超 half angle | 不变量 | P0 | PASS (S1) |
| CONE-002 | twist 自由 | 绕 twist axis 不被错误锁死 | 不变量 | P0 | PASS (S1) |
| SWING_TWIST-001 | 摆角与扭转限制 | anchor 重合；纯摆动与纯扭转分别收敛到声明边界，非目标轴残差有界 | 不变量/Jolt | P0 | PASS (S1) |
| SWING_TWIST-002 | Pyramid 轴映射与摩擦 | 本地 X/Y 分别命中 normal/plane 半角；摩擦力矩按惯量解析衰减并产生 lambda | 解析/Jolt official | P0 | PASS (S1) |
| PAIR-001 | 不同质量 Distance spring | 两端轨迹正确且总线动量守恒 | 解析/Jolt | P0 | 已实现 |
| PAIR-002 | 不同质量 Slider motor | 限力反作用与质量倒数成比例，总动量守恒 | 解析/Jolt | P0 | 已实现 |
| PAIR-003 | 不同转动惯量 Hinge motor | 限矩反作用正确，总角动量守恒 | 解析/Jolt | P0 | 已实现 |
| FRAME-001 | 独立 A/B anchors | body 原点不同且 shape offset 时 anchor 仍正确 | 解析/差分 | P0 | 已实现 |
| FRAME-002 | frame 旋转/轴约定 | HoTools local Z 与 Jolt Hinge/Slider axis 映射正确 | 变形 | P0 | 已实现 |
| CONS-001 | solver step override | 低/高迭代残差排序正确，0 使用默认 | Jolt | P1 | 缺失 |
| CONS-002 | priority | 冲突依赖链中改变顺序且结果可重复 | Jolt | P2 | 缺失 |
| CONS-003 | draw size | 只改 debug geometry，不改 physical hash | 变形 | P0 | 已实现 |
| BREAK-001 | impulse threshold | 仅真实 step 后按 `lambda_max_abs` 断裂 | HoTools | P0 | 现有弱覆盖 |
| BREAK-002 | dt 与 same-frame | 阈值不被误当力；same-frame 不重复判定 | HoTools | P0 | 现有弱覆盖 |

### Query、生命周期、确定性、稳定性

| ID | 场景 | 核心判据 | Oracle | 优先级 | 当前 |
|---|---|---|---|---|---|
| QUERY-001 | closest RayCast | 最近命中及位置/法线/fraction 符合球体解析几何 | 解析 | P0 | 已实现 |
| QUERY-002 | sensor/ignore filter | 过滤后选下一最近命中；零方向安全 miss | 解析 | P0 | 已并入 QUERY-001 |
| LIFE-001 | 首帧/same-frame/jump/back/reset | 只在真实连续帧 step，重发不改 native state | HoTools | P0 | 已覆盖 |
| LIFE-002 | transform/shape/constraint 热改 | 热更/重建边界正确，状态续接明确 | Contract/差分 | P0 | 链路已覆盖 |
| LIFE-003 | prune/delete/dispose | native 数量回零，Blender delta 清理 | Contract | P0 | 已覆盖 |
| DET-001 | 两个新 world 同步重放 | 每帧原始 float bitwise 相等 | Jolt determinism | P0 | 已实现 |
| DET-002 | 同 fixture 跨进程运行 10 次 | canonical physical hash 一致 | Jolt determinism | P0 | 已实现 |
| DET-003 | Blender scope 枚举随机打乱 | stable-id 排序后 API 调用序与 trace 不变 | HoTools | P0 | 缺失 |
| DET-004 | py311/py313 | schema 完全一致，trace 在容差内一致 | 差分 | P0 | 两 ABI 各自 48/48；自动容差差分报告缺失 |
| SOAK-001 | 10,000 帧堆叠/约束链 | 无 NaN、资源不增长、残差不失控 | 不变量 | P0 release | 缺失 |
| PERF-001 | 1/128/1024 bodies | step、pipeline、writeback 的 P50/P95 | benchmark | P1 | 缺失 |
| PERF-002 | 32/256 constraints + contacts | P50/P95、接触数、内存高水位 | benchmark | P1 | 缺失 |

## 组合矩阵

基础 case 固定最小场景；交互问题使用 pairwise，并保留高风险三元组合。

```text
body pair       = static-dynamic / dynamic-dynamic / kinematic-dynamic / body-world
shape           = sphere / box / capsule / cylinder / tapered shapes / plane
frame           = shared world / separate A-B / rotated / shape-offset
dt              = 1/24 / 1/60 / 1/120
substeps        = 1 / 2 / 4
motion quality  = discrete / linear-cast
sleep           = on / off
scale regime    = 0.01 m / 1 m / 100 m
```

固定高风险组合：

- high speed + thin collider + DISCRETE/LINEAR_CAST；
- separate anchors + shape offset + rotated body；
- breakable + disable collisions + 多约束引用计数；
- kinematic driver + sleeping dynamic + sensor；
- motor + limit + friction；
- frame jump/reset + pending command + result re-publish。

## 确定性定义

Jolt 确定性要求相同输入、API 调用顺序、配置和兼容构建条件。HoTools 必须把这些前提变成测试事实。

1. **D0 同进程**：两个新 `JoltWorld` 同 fixture，每帧 bitwise 相等；PR 阻断。
2. **D1 同构建跨进程**：同 binary、同机器重复 10 次，physical hash 相等；nightly/release 阻断。
3. **D2 跨 ABI/平台**：py311/py313 容差对拍；只有启用并记录 `CROSS_PLATFORM_DETERMINISTIC` 构建时，才宣称跨平台 bitwise 确定。

单线程 job system 不自动保证 HoTools 确定性。body/constraint 收集和 timeline command 都必须有稳定排序键。physical hash 不包含 handle、pointer、耗时或日志顺序。

### 当前实现的确定性风险

这不是纯理论缺口：当前 `rigid/solver.py`、`rigid/scope_sync.py` 和 `rigid/backends/jolt.py` 多处直接按 `world.solver_slots` / `_body_handles` 的 dict 插入顺序迭代；而 `RigidBodySpec.slot_id`、`ConstraintSpec.slot_id` 又包含 Blender pointer。pointer 适合当前进程内防止身份复用，却不适合作为跨进程模拟顺序。

因此不能简单写 `sorted(slot_id)` 就宣称解决。需要给 body/constraint 增加独立的 `simulation_order_key`：

```text
runtime identity     = pointer-based slot_id，负责本进程生命周期和去重
simulation order key = 可序列化的语义身份，负责 Jolt add/remove/command 顺序
```

Blender 显式对象的首版 order key 可由 library path、object `name_full`、data `name_full` 和 domain tag 组成；generated constraint 还需包含 producer tree/node 的持久 id 与 endpoint order key。重名、缺失持久 id 或 order-key 冲突必须明确报错，不能回退到 pointer 排序。DET-003 应在修改顺序策略前先写成失败测试，再以其作为修复门禁。

## Golden 管理

```text
rigid/test/goldens/
  jolt-5.2.0_windows-x64_release/
    <fixture-id>.json.zst
    manifest.json
```

manifest 记录 Jolt version/commit、native build id、编译器与关键 build flags、adapter/spec schema、fixture hash、runner version、批准 commit/reviewer/reason。

普通测试命令绝不更新 golden。独立 `--approve-golden` 命令必须产出旧/新关键帧、最大误差、RMS、事件差异和 hash 摘要。Jolt 升级新建目录，不能覆盖旧基线。

## Runner 目录与接口

```text
physicsWorld/rigid/test/
  fixtures/{p0,constraints,collisions,lifecycle}/
  schema.py
  canonical.py
  assertions.py
  fixture_runtime.py
  run_native_semantics.py
  run_blender_semantics.py
  compare_traces.py
  benchmark_blender_rigid.py
  goldens/
```

要求：

- 不以手工 `.blend` 作为主要 fixture；Blender runner 从 JSON 建场景；
- 产物默认写 `C:\tmp\hotools_jolt_test\<run-id>`，不污染 add-on；
- 三层共用 schema、canonical 和 assertions；
- 失败保留 fixture、manifest、trace、diff 和 Blender 日志；
- Blender 使用 `--background --factory-startup`，显式设置 fps、单位、frame、随机种子；
- 支持 `--id`、`--tag`、`--runner`、`--repeat`、`--artifact-dir`；
- 非零退出码表示失败，同时输出机器可读 JSON 汇总。

建议命令：

```powershell
python OmniNode\NodeTree\Function\physicsWorld\rigid\test\run_native_semantics.py `
  --tag p0 --repeat 2 --artifact-dir C:\tmp\hotools_jolt_test

& 'D:\Blender\Blender 4.5\blender.exe' --background --factory-startup --python `
  'OmniNode\NodeTree\Function\physicsWorld\rigid\test\run_blender_semantics.py' -- `
  --tag p0 --artifact-dir C:\tmp\hotools_jolt_test
```

## 门禁

| Lane | 内容 | 目标时间 | 失败处理 |
|---|---|---:|---|
| PR-fast | S0 + S1 P0 微场景；S3 最小落体/约束/生命周期 | 2 分钟内 | 阻断 |
| PR-full（rigid 变更） | 全 P0、native/adapter 差分、Blender P0 | 10 分钟内 | 阻断 |
| Nightly | 全矩阵、pairwise、10 次确定性、性能采样 | 可较长 | 保留产物并阻断次日合并 |
| Release | py311 + py313、10,000 帧 soak、性能门槛、golden 审核 | 发布前 | 阻断发布 |
| Jolt-upgrade | 旧/新版本 trace 差分、官方语义 case、人工批准 | 升级专用 | 禁止静默 rebaseline |

性能门槛在首轮稳定测量后冻结。冻结前只采集数据；冻结后分别约束 native step P50/P95、完整 Blender pipeline P50/P95 和资源高水位。

## 落地顺序

### Phase 0：试验台

- 建 schema、canonical trace、通用 assertions、artifact manifest；
- 将现有自由落体、落地、RayCast、contact、生命周期迁入 fixture；
- 保留旧入口直到新 runner 稳定；不增加“语义已通过”结论。

完成标准：一个 fixture 能在 S1/S2/S3 三层运行并产生可比较 trace。

### Phase 1：P0 刚体语义

- 完成 FREE/BODY/SHAPE/COLL/FILTER/DET 的 P0；
- 固定 stable-id 添加顺序；
- 建 py311/py313 差分与同进程 bitwise 重放。

完成标准：基础刚体可声明“参数与 Jolt v5.2.0 语义已验收”。

### Phase 2：约束验收

- 按 Fixed -> Point -> Distance -> Hinge -> Slider -> Cone -> SwingTwist 完成矩阵；
- 每种先做自由度残差，再 limit/spring/friction/motor，再 frame 和断裂交互；
- 从 Jolt v5.2.0 unit tests 提炼 Hinge/Slider/Distance 数值 case。

完成标准：`CONSTRAINT_REFERENCE.md` 每条已支持能力都链接至少一个自动 case ID。

### Phase 3：稳定性与性能

- pairwise/high-risk 组合；
- 10,000 帧 soak、堆叠、约束链、overflow；
- body/constraint/contact 性能矩阵；
- 冻结 release 门槛和首版 golden。

完成标准：正式报告分别给出语义、确定性、稳定性、性能结论，不用一个通过数掩盖不同维度。

## 新能力 Definition of Done

新增参数、shape、constraint 或 query 同时满足以下条件才算完成：

1. 公共语义、单位、默认值和 Jolt 映射已记录；
2. fixture schema 能表达；
3. 至少一个正向 case 和一个边界/反向 case；
4. S1 有明确 oracle，S2 或 S3 至少有一层差分；
5. result/debug 不泄漏 native handle，same-frame 不推进；
6. dirty signature 与热更/重建有测试；
7. 评估 determinism/golden 变化；
8. 进入热路径时加入性能矩阵。

## 权威参考

- 本地 Jolt v5.2.0：`_native/build/vs2022-py311/_deps/joltphysics-src`
- Jolt determinism：`Docs/Architecture.md` 的 `Deterministic Simulation`
- Jolt 官方测试：`UnitTests/Physics/*ConstraintTests.cpp`、`SensorTests.cpp`、`MotionQualityLinearCastTests.cpp`、`PhysicsDeterminismTests.cpp`
- HoTools 物理流程：`OmniNode/doc/PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`
- HoTools Jolt 能力分析：`OmniNode/doc/JOLT_PHYSICS_BACKGROUND_ANALYSIS.md`
- HoTools 约束语义：`CONSTRAINT_REFERENCE.md`
