# PMX 2.0 到 Jolt 的接纳矩阵

状态：重新评估后的实现门卫；日期：2026-07-29

前置合同：[MMD_PMX20_PROTOCOL_CONTRACT.md](MMD_PMX20_PROTOCOL_CONTRACT.md)

## 1. 结论

PMX 2.0 作为一种 source 进入现有 `rigid` 域，最终只生成通用 `RigidBodySpec`、`ConstraintSpec` 和骨骼 binding metadata。运行时仍只有一个 `rigid_jolt` 后端。

格式层可以做到原始字段完整保留；物理层不承诺与其它求解器逐帧轨迹相同。坐标基底、胶囊轴、衰减和六轴弹簧必须经过独立 fixture 冻结，不能用“字段名字相似”代替验证。

## 2. 判定词汇

本矩阵不再使用“兼容等级”描述其它格式，只记录 PMX 2.0 字段在本实现中的状态：

- `PRESERVED`：二进制原值逐字段保存在 canonical DTO 和诊断快照中。
- `DERIVED`：由冻结的纯函数进行索引、枚举、单位、坐标或 frame 转换，可由 fixture 重算。
- `CALIBRATION_REQUIRED`：Jolt 有候选能力，但数值模型或坐标空间尚需实验门卫；未通过前不能进入 runtime-ready。
- `REJECTED`：违反 PMX 2.0 合同或无法形成确定语义，整个 source 原子拒绝。

实现就绪度另行记录：

- `AVAILABLE`：当前通用 spec/native 已有消费路径。
- `GENERIC_GAP`：Jolt 可表达，但 HoTools 通用刚体基础设施尚未接线。
- `BINDING_GAP`：需要 PMX source identity、骨骼映射或 writeback resolver。
- `CALIBRATION_GATE`：必须先由无宿主 fixture 冻结转换。

## 3. 当前代码缺口

| 缺口 | 当前事实 | 必须先完成的通用修正 | 就绪度 |
| --- | --- | --- | --- |
| 独立 reader | 尚无生产级 PMX 2.0 reader | 完整顺序解析、精确版本门卫、EOF 与资源预算校验 | `GENERIC_GAP` |
| source-generated body | `RigidBodySpec` 构造仍要求 Blender Object，`slot_id` 来自 pointer | 允许显式稳定 `slot_id`、独立 `simulation_order_key` 和 `obj=None` | `GENERIC_GAP` |
| 隐式对象注册 | 已有 `rigid.generated_constraint`，没有对称的 generated body 生命周期 | 增加 `rigid.generated_body` 注册、同步、裁剪和 dispose | `GENERIC_GAP` |
| 约束端点 | `ConstraintSpec` 只保存 `target_a_ptr/target_b_ptr`，adapter 用 pointer 前缀查 body | 增加 `target_a_slot_id/target_b_slot_id`，精确 ID 优先、pointer fallback 保持旧路径 | `GENERIC_GAP` |
| 无 Object 结果链 | result/query/command/writeback 的部分路径仍假设 `obj_ptr != 0` | 全链路允许 `obj_ptr=0`，以 slot ID 为权威身份 | `GENERIC_GAP` |
| 骨骼身份 | 没有 `pmx_bone_index -> PoseBone stable identity` 注册表 | source prepare 时建立显式映射并检测歧义 | `BINDING_GAP` |
| 六轴弹簧 | native 有逐轴 SixDOF motor，但公共 spec 的 spring 参数仍是共享值 | 增加六轴独立 motor spring mode/stiffness/damping | `GENERIC_GAP` |
| 转换 profile | PMX、Blender、Jolt 的 basis/单位和 motor frame 尚未冻结 | 建立纯转换 kernel 与合成 fixture | `CALIBRATION_GATE` |

所以接入顺序必须是 reader 和纯转换 kernel 在前，通用 generated body/slot 引用在中，最后才是 Blender binding 与 UI。

## 4. 刚体接纳矩阵

| PMX 2.0 输入 | 目标语义 | 判定 | 就绪度 | 处理规则 |
| --- | --- | --- | --- | --- |
| PMX rigid index | body `slot_id`、排序 key | `DERIVED` | `GENERIC_GAP` | 身份由 `source_id + rigid_index` 生成；名称不参与身份 |
| 名称 | source metadata | `PRESERVED` | `AVAILABLE` | 只用于显示和定位诊断 |
| bone index | binding metadata | `PRESERVED` | `BINDING_GAP` | 非 `-1` 先验证范围，再解析到显式骨骼映射 |
| bone index `-1` | unbound policy | `DERIVED` | `BINDING_GAP` | 合法；不创建虚假骨骼 |
| group `0..15` | `rigid_collision_group` `1..16` | `DERIVED` | `AVAILABLE` | `target_group = source_group + 1` |
| non-collision mask | `rigid_collides_with_groups` | `DERIVED` | `AVAILABLE` | `allow_mask = (~source_mask) & 0xffff`，沿用现有双向 filter |
| sphere size | `SPHERE.shape_radius` | `DERIVED` | `CALIBRATION_GATE` | `radius = unit_scale * size.x`；其余分量仍保留供审计 |
| box size | `BOX.shape_half_extents` | `DERIVED` | `CALIBRATION_GATE` | PMX 三轴半尺寸经 basis permutation 和单位缩放后直接作为 half-extents |
| capsule size | `CAPSULE.radius/half_height` | `DERIVED` | `CALIBRATION_GATE` | `radius=size.x`，圆柱段 `half_height=size.y/2`；局部轴由单一 basis profile 转换 |
| world position/rotation | body initial transform | `DERIVED` | `CALIBRATION_GATE` | Euler radian 只在 conversion kernel 中转 quaternion；叠加 model root transform |
| mass | `RigidBodySpec.mass` | `PRESERVED` | `AVAILABLE` | mode `1/2` 必须满足动态 body 合法域；不自动改 mode |
| zero move/rotation attenuation | zero linear/angular damping | `DERIVED` | `AVAILABLE` | 精确零可直接保持为零 |
| nonzero move/rotation attenuation | linear/angular damping | `CALIBRATION_REQUIRED` | `CALIBRATION_GATE` | 保存源值；公式由固定步长衰减 fixture 冻结后才写目标字段 |
| bounce | restitution | `DERIVED` | `AVAILABLE` | 保留源值；目标合法域与越界策略显式校验 |
| friction | friction | `DERIVED` | `AVAILABLE` | 保留源值；材质组合规则沿用 Jolt world，不承诺轨迹等同 |
| mode `0` + bound bone | `KINEMATIC` | `DERIVED` | `BINDING_GAP` | 每帧从骨骼 world pose 生成 kinematic target，不写回 body result |
| mode `0` + unbound | `STATIC` | `DERIVED` | `GENERIC_GAP` | 无输入源时保持初始 world transform |
| mode `1` | `DYNAMIC` + full pose writeback | `DERIVED` | `BINDING_GAP` | 未绑定时仍模拟，只禁用骨骼 writeback |
| mode `2` | `DYNAMIC` + rotation/position-correction writeback | `DERIVED` | `BINDING_GAP` | body 与 mode `1` 相同，差异仅在 resolver |

PMX 2.0 没有 sleep、CCD、sensor、gravity factor 或独立 allowed-DOF 字段。source adapter 使用冻结 import profile 的通用默认值，但必须把“默认值来源”写进 conversion snapshot；不能伪装成 PMX 原字段。

### 4.1 形状门卫

形状转换至少要通过以下无宿主 fixture：

1. 单位 root 下 sphere、box、capsule 的 AABB 与 debug geometry。
2. 非单位 model root scale 先烘成 shape 参数，禁止把非均匀 Object scale留给 native 猜测。
3. 三个 PMX 基轴分别映射到 Jolt world，验证 box extent 没有重复除二。
4. capsule 在非恒等旋转下验证局部轴、圆柱段长度和总高。
5. 非正尺寸、NaN/Inf 和超预算尺寸在提交前拒绝。

## 5. Joint 接纳矩阵

| PMX 2.0 输入 | 目标语义 | 判定 | 就绪度 | 处理规则 |
| --- | --- | --- | --- | --- |
| Joint index/name | constraint stable ID/metadata | `PRESERVED` + `DERIVED` | `GENERIC_GAP` | ID 使用 `source_id + joint_index` |
| type `0` | `constraint_type=SIX_DOF` | `DERIVED` | `AVAILABLE` | 任意其它值是合同错误，整个 source 拒绝 |
| rigid A/B index | target body slot IDs | `DERIVED` | `GENERIC_GAP` | 非 `-1` 精确解析到已生成 body slot |
| 单个 endpoint `-1` | world endpoint | `DERIVED` | `GENERIC_GAP` | 合法；另一端 body 约束到显式 world frame |
| 两个 endpoint 均为 `-1` | inert Joint record | `PRESERVED` + `DERIVED` | `AVAILABLE` | 合法 no-op；保留 snapshot，不生成 `ConstraintSpec` 或 native handle |
| 非空但无法解析的 target slot | 无 | `REJECTED` | `GENERIC_GAP` | 不得沿用“查找失败即 world”的现有 fallback |
| world position/rotation | local frame A/B | `DERIVED` | `CALIBRATION_GATE` | 由 joint world transform 与 body initial world transforms 求局部 frame |
| translation limits | SixDOF translation axes | `DERIVED` | `CALIBRATION_GATE` | 单位和 basis 统一转换；不在 parser 中交换上下限 |
| rotation limits | SixDOF rotation axes | `DERIVED` | `CALIBRATION_GATE` | 保持 radian；验证 Euler 轴和 Jolt constraint frame |
| zero-width limit | `FIXED` axis | `DERIVED` | `CALIBRATION_GATE` | 只在冻结 epsilon 下判断 |
| ordered nonzero span | `LIMITED` axis | `DERIVED` | `CALIBRATION_GATE` | 直接保留上下限方向 |
| 反向 limit span | 未冻结 | `CALIBRATION_REQUIRED` | `CALIBRATION_GATE` | 不擅自当成 free 或交换；先用协议/行为 fixture 确定 |
| zero spring constant | motor `OFF` | `DERIVED` | `CALIBRATION_GATE` | 该轴只保留 hard limit |
| nonzero linear spring | translation position motor candidate | `CALIBRATION_REQUIRED` | `CALIBRATION_GATE` | 平衡点候选为 joint frame 零位 |
| nonzero angular spring | rotation position motor candidate | `CALIBRATION_REQUIRED` | `CALIBRATION_GATE` | 平衡姿态候选为 joint frame identity |
| linked-body collision | 无 PMX 字段 | import default | `AVAILABLE` | `disable_collisions=False`；由 group/mask 决定，不凭连接关系关碰撞 |

## 6. 六轴弹簧重新评估

Jolt SixDOF 的 hard limit、每轴 motor 和 position/orientation target 足以构成候选实现，但不能据此直接宣布等价：

- `mLimitsSpringSettings` 只覆盖平移软限位，不是 PMX 六轴连续回正弹簧的完整表达。
- PMX 为六个轴分别存储弹簧常数；当前 HoTools 的 motor frequency/damping 是共享字段，会抹掉轴间差异。
- PMX Joint 没有提供 damping 和 force/torque cap；这些值必须来自显式 profile，不能从 spring constant 猜出唯一答案。
- Jolt 平移 motor 与旋转 motor 使用的 constraint space 不完全相同；恒等姿态下通过并不能证明旋转 body/frame 后仍正确。

候选通用扩展只增加普通 SixDOF 也能使用的字段：

```text
six_dof_motor_states[6]          # 已有，继续复用
six_dof_motor_spring_modes[6]    # 新增
six_dof_motor_stiffness[6]
six_dof_motor_damping[6]
```

优先使用 `StiffnessAndDamping`，因为 PMX 提供的是弹簧常数而不是频率。现有共享 force/torque limit 可以先作为 profile cap；没有证据前不把逐轴 cap 放入关键路径。

### 6.1 校准矩阵

| fixture | 断言 |
| --- | --- |
| identity frames，单一平移轴 | 正负位移产生朝零位的恢复方向，其它轴无 motor 力 |
| identity frames，单一旋转轴 | 正负角偏移产生朝 identity 的恢复力矩 |
| body A/B 非恒等旋转 | motor 轴仍对应 PMX joint frame，不随错误 body space 漂移 |
| world + body 两种端点顺序 | 交换 A/B 后 frame 和恢复方向符合明确约定 |
| world + world | 记录保留为 no-op，constraint/handle 数量不增加 |
| 六轴不同 stiffness | native 收到六个独立值，结果快照不折叠成共享参数 |
| 不同质量/惯量比 | profile damping 行为稳定且无爆炸 |
| fixed `dt` 与 substep 变化 | 参数转换的时间尺度被记录，重复运行可重放 |
| 与 hard limit 同时启用 | motor 平衡点、limit clamp 和 debug state 一致 |

只有全部门卫通过，Spring6DOF 才从 `CALIBRATION_REQUIRED` 升为 `DERIVED`。若实验失败，正确结果是停止 runtime 接入并重新选择通用 Jolt 表达，不是静默丢弃弹簧。

## 7. 通过标准

- PMX 2.0 的每个刚体和 Joint 原字段在 DTO/debug snapshot 中可追溯。
- 所有 `DERIVED` 字段都有纯函数和 golden fixture，转换不依赖 Blender 场景状态。
- 合法未绑定骨骼和 world endpoint 保持可运行，不误报为坏引用。
- generated body、显式 target slot ID 和 `obj_ptr=0` 全链路先作为通用能力落地。
- Spring6DOF 校准门卫通过前，不发布“物理接入完成”状态。
- PMX body 与普通 Jolt body 在同一 world 中共享碰撞过滤、step、query、debug、reset、bake 和 dispose。
- 不新增 MMD 专属物理字段副本、native handle 所有者或 solver slot。
