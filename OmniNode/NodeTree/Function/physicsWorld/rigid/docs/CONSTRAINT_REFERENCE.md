# 约束类型参考

## 当前已接入类型

| 类型 | 保留的自由度 | 主要参数 | 典型用途 |
|---|---|---|---|
| `FIXED` | 无 | A/B frame | 焊接、固定到世界 |
| `POINT` | 3 个旋转自由度 | A/B point | 球窝点、链节连接点 |
| `DISTANCE` | 除点间距离外均自由 | min/max distance、limit spring | 拉杆、绳长、软距离 |
| `HINGE` | 绕本地 Z 单轴旋转 | 角度 limit、spring、friction torque、angular motor | 门轴、轮轴、机械关节 |
| `SLIDER` | 沿本地 Z 单轴平移 | 线性 limit、spring、friction force、linear motor | 活塞、抽屉、滑轨 |
| `CONE` | cone 范围内 swing，twist 自由 | half cone angle | 摆锤、简化球窝角限制 |
| `SWING_TWIST` | 椭圆锥或金字塔范围内 swing，有限或自由 twist | swing type、两个 swing half angle、twist min/max、friction torque、双 motor | 肩关节、受限球窝、布偶关节 |
| `SIX_DOF` | 六个轴分别 Free、Fixed 或 Limited | 六轴模式、六轴 min/max、旋转 swing type | 复合机械关节、自定义平移旋转边界 |

## 类型细节

### Fixed

锁定 A/B 的相对位置和相对旋转，相当于移除全部六个自由度。独立 A/B frame 不一致时，solver 会努力恢复创建时定义的 frame 关系。它不是把两个物体合并成一个刚体，仍会产生约束冲量。

### Point

使两个 anchor point 重合，移除三个平移自由度，但不限制相对旋转。若你需要限制球窝关节的摆角或扭转范围，应使用 SwingTwist；需要逐轴控制六个自由度时仍需等待 SixDOF。

### Distance

限制两点距离处于 `[distance_min, distance_max]`。`min == max` 是刚性拉杆；区间形式允许两点在范围内自由靠近/远离。limit spring 会软化到边界后的纠正。

### Hinge

锁定三个平移和两个旋转自由度，只允许绕 frame Z 旋转。frame X 定义角度零位。支持：

- 角度最小/最大限制；
- limit spring；
- friction torque；
- Velocity/Position angular motor；
- 当前角度、limit lambda、motor lambda 输出。

### Slider

锁定全部旋转和垂直于 frame Z 的两个平移自由度，只允许沿 Z 平移。支持：

- 线性最小/最大限制；
- limit spring；
- friction force；
- Velocity/Position linear motor；
- 当前位置、limit lambda、motor lambda 输出。

### Cone

使两个 point 重合，并限制两侧 twist axis 之间的夹角不超过 half cone angle。它不限制绕 twist axis 的扭转，因此不能替代完整肩关节。需要 twist min/max 时应使用 SwingTwist。

### SwingTwist

使两个 anchor point 重合，并分别限制摆动和扭转。HoTools frame 的本地 Z 是 twist axis，本地 X 是 plane axis；这两个轴会映射到 Jolt 的 twist/plane frame。当前支持：

- `swing_type = CONE`：用 `swing_normal_half_angle` 与 `swing_plane_half_angle` 定义椭圆摆动锥；纯绕本地 X 的摆动受 normal 半角限制，纯绕本地 Y 的摆动受 plane 半角限制；
- `swing_type = PYRAMID`：用相同的两个半角定义金字塔式摆动边界；
- `twist_min_angle` / `twist_max_angle`：限制绕本地 Z 的扭转范围；
- `max_friction_torque`：限制阻碍相对旋转的最大摩擦力矩；
- `swing_motor_state` / `twist_motor_state`：分别启用摆动和扭转的速度或位置 motor；
- `swing_twist_target_angular_velocity`：HoTools 约束 frame 局部 XYZ 目标角速度，其中 Z 是 twist axis；
- `swing_twist_target_rotation`：HoTools 约束 frame 中的目标欧拉姿态；
- `motor_frequency` / `motor_damping` / `motor_torque_limit`：两个 motor 共用的弹簧和力矩限制；
- 当前相对旋转值以及 position、swing、twist、limit、motor lambda 结果。

Jolt 内部 constraint space 的轴序为 `Twist / (Plane×Twist) / Plane`。binding 会把 HoTools 局部 XYZ 显式映射为 Jolt `(Z, -Y, X)`；用户不需要手工重排或翻转目标分量。

### SixDOF

以约束 frame 的本地 XYZ 作为三个平移轴和三个旋转轴。每个轴可设为：

- `FREE`：该轴不施加约束；
- `FIXED`：该轴固定到 A/B frame 的相对零位；
- `LIMITED`：该轴限制在对应 min/max 范围内。

每个平移轴的 friction 值是最大摩擦力 N，每个旋转轴的 friction 值是最大摩擦力矩 N·m；0 表示该轴无摩擦。

显式 Empty 属性、生成约束节点、`ConstraintSpec`、Jolt adapter、state/lambda、逐轴 friction 和专用调试绘制已接入。旋转 Y/Z 同时受限时，`six_dof_swing_type` 控制椭圆锥或金字塔边界。当前逐轴 spring/motor 和逐轴 current-value result 尚未接入。

## 通用参数

- `constraint_priority`：同一 island 中更高优先级的约束先求解；只在确有依赖次序时使用。
- `solver_velocity_steps` / `solver_position_steps`：0 表示采用世界默认值，非零表示该约束 override。
- `draw_constraint_size`：只改变调试 glyph 大小，不改变物理行为；Slider/Distance 的物理 limit 仍按真实长度绘制。
- `disable_collisions`：HoTools pair-filter policy，不是 Jolt constraint 字段。
- `breakable` / `breaking_threshold`：HoTools 在 step 后读取 lambda/impulse 并禁用约束，不是 Jolt 独立约束类型。

## Jolt 原生但 HoTools 尚未接入

| Jolt 类型 | 能力 | 接入前置 |
|---|---|---|
| Path | Hermite spline path、path fraction、motor | 路径资源生命周期与曲线调试 |
| Gear | 连接两个 hinge 的齿轮比 | constraint-to-constraint 引用拓扑 |
| RackAndPinion | hinge 与 slider 的线性/角度比例 | constraint-to-constraint 引用拓扑 |
| Pulley | 两固定点、绳长与 ratio | world fixed points 与绳路调试 |
| Vehicle | 虚拟轮/履带车辆系统 | 独立 vehicle domain，不并入通用约束面板 |

来源：[Jolt 官方约束总览](https://jrouwe.github.io/JoltPhysics/index.html#constraints)。
