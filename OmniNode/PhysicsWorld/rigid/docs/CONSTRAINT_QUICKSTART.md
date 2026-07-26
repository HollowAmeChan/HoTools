# 约束快速上手

## 最短工作流

1. 给参与模拟的物体配置 HoTools 刚体和碰撞形状。至少一个物体应为 Dynamic；连接到静止世界时，约束的一侧可以为空。
2. 创建一个 Empty 作为约束点。它的位置是 anchor，旋转是 constraint frame。
3. 在 Empty 的刚体约束属性中选择 Target A、Target B 和约束类型。
4. 把刚体与约束 Empty 纳入同一 Physics World object scope，并启用刚体与刚体约束收集。
5. 在节点链中运行“刚体模拟步”，需要写回时再运行统一 Physics Writeback。
6. 在模拟步之后连接“Jolt刚体可视化调试”，打开“显示约束”和“显示问题”。

也可以使用“刚体生成约束属性 → 刚体生成约束注册”创建不带 Empty 的持久隐式约束。它会进入同一 `ConstraintSpec` 和调试链路。

## Empty 的轴怎么读

当前 binding 对 Hinge、Slider 和 Cone 使用同一约定：

- Empty 本地 `Z`：Hinge 旋转轴、Slider 平移轴、Cone twist axis。
- Empty 本地 `X`：Hinge/Slider normal axis；对 Hinge 来说也是角度零位参考方向。
- Empty 本地 `Y`：补齐右手坐标系。

因此“位置正确但运动方向不对”通常不是 solver 失效，而是 Empty 的本地 Z 轴没有对准预期方向。先打开约束调试绘制检查轴和 limit 图形。

## Shared frame 与独立 A/B frame

- `SHARED_WORLD`：A/B 使用同一个世界 anchor frame，适合常规铰链和滑轨。
- 独立 A/B frame：两个刚体各自使用不同世界 frame，适合初始 anchor 不重合、需要明确相对 frame 的生成约束。

调试图会同时显示 A/B anchor；两点分离时会画连接线。若模拟开始就猛烈弹开，优先检查两侧 frame 是否表达了你真正想锁定的相对关系。

## Limit、Spring 与 Motor

- Hinge limit 单位是弧度，最小值在 `[-π, 0]`，最大值在 `[0, π]`。
- Slider 与 Distance limit 使用 Blender/Jolt 世界长度单位；项目应尽量采用米制尺度。
- limit spring 的 frequency 必须小于等于物理步频的一半；60 Hz 模拟时不要把 frequency 设得高于 30 Hz。阻尼 1 接近临界阻尼。
- Hinge motor 使用 torque limit；Slider motor 使用 force limit。目标在正确但物体不动时，通常是力/扭矩上限相对质量或惯量太小。
- Position motor 会追逐目标位置/角度；Velocity motor 会追逐相对速度/角速度。

## 常见问题

- 两个 target 都为空：约束没有可连接对象，调试层会标红。
- Target 指向约束 Empty 自身：这是无效自引用，调试层会标红。
- 连接物体互相抖动：检查 `disable_collisions`，必要时禁用连接对之间的直接碰撞。
- 约束逐渐漂移：适度增加 position steps；不要一开始把所有约束的 override 拉满。
- 约束突然失效：检查 `rigid_constraint_state.broken`、`breaking_impulse` 与 `breaking_threshold`。断裂是 HoTools 基于上一物理步 lambda/impulse 的策略。
- 当前角度/位置看似不对：Hinge/Slider 的 current value 相对约束 frame 定义，不是物体世界 Euler 或世界坐标。
