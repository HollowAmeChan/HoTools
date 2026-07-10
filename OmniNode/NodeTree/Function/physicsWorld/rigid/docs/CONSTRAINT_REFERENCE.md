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

## 类型细节

### Fixed

锁定 A/B 的相对位置和相对旋转，相当于移除全部六个自由度。独立 A/B frame 不一致时，solver 会努力恢复创建时定义的 frame 关系。它不是把两个物体合并成一个刚体，仍会产生约束冲量。

### Point

使两个 anchor point 重合，移除三个平移自由度，但不限制相对旋转。若你需要限制球窝关节的摆角或扭转范围，Point 不够，应等待/使用未来的 SwingTwist 或 SixDOF。

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

使两个 point 重合，并限制两侧 twist axis 之间的夹角不超过 half cone angle。它不限制绕 twist axis 的扭转，因此不能替代完整肩关节。需要 twist min/max 时应使用未来的 SwingTwist。

## 通用参数

- `constraint_priority`：同一 island 中更高优先级的约束先求解；只在确有依赖次序时使用。
- `solver_velocity_steps` / `solver_position_steps`：0 表示采用世界默认值，非零表示该约束 override。
- `draw_constraint_size`：只改变调试 glyph 大小，不改变物理行为；Slider/Distance 的物理 limit 仍按真实长度绘制。
- `disable_collisions`：HoTools pair-filter policy，不是 Jolt constraint 字段。
- `breakable` / `breaking_threshold`：HoTools 在 step 后读取 lambda/impulse 并禁用约束，不是 Jolt 独立约束类型。

## Jolt 原生但 HoTools 尚未接入

| Jolt 类型 | 能力 | 接入前置 |
|---|---|---|
| SwingTwist | 肩关节式 swing/twist limit、friction、motor | 扩展 spec、orientation motor 与专用 cone/twist debug |
| SixDOF | 六轴分别 Free/Fixed/Limited、每轴 motor/friction | 轴数组 schema、per-axis result 与调试器 |
| Path | Hermite spline path、path fraction、motor | 路径资源生命周期与曲线调试 |
| Gear | 连接两个 hinge 的齿轮比 | constraint-to-constraint 引用拓扑 |
| RackAndPinion | hinge 与 slider 的线性/角度比例 | constraint-to-constraint 引用拓扑 |
| Pulley | 两固定点、绳长与 ratio | world fixed points 与绳路调试 |
| Vehicle | 虚拟轮/履带车辆系统 | 独立 vehicle domain，不并入通用约束面板 |

来源：[Jolt 官方约束总览](https://jrouwe.github.io/JoltPhysics/index.html#constraints)。
