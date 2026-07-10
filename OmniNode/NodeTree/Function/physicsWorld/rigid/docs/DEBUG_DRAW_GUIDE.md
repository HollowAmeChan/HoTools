# 约束调试绘制指南

“Jolt刚体可视化调试”只消费 `ConstraintSpec`、solver slot 和 `rigid_constraint_state` 的纯快照，不调用 Jolt 原生 renderer，也不暴露 native handle。

当前版本的 frame/limit glyph 使用 adapter 创建约束时实际消费的 `ConstraintSpec` world frame；angle/position/distance 与 lambda 使用 step 后的 `rigid_constraint_state`。因此约束语义和动态标量是真实输入/输出，但 native 当前 A/B world frame 的逐帧 readback 仍是下一阶段工作。snapshot 会明确给出 `constraint_frame_source=constraint_spec_backend_input` 和 `constraint_runtime_frame_readback=false`，不会把 authored frame 冒充为 native 动态 frame。

## 颜色

| 颜色 | 含义 |
|---|---|
| 黄色 | anchor、约束 frame、允许运动轴或基本形状 |
| 橙红色 | limit 区间、角度边界、距离壳或 cone 边界 |
| 洋红色 | motor target 或 motor 方向 |
| 青色 | 当前求解值（Hinge angle、Slider position、Distance value） |
| 红色 | 无 target、自引用、broken 等问题 |

## 各类型图形

- Fixed：A/B frame 三轴及对应轴桥接。frame 朝向不一致会直接显现。
- Point：anchor 加三环球，表示点被锁定但三轴旋转自由。
- Distance：A/B 连线，加以 A 为中心的 min/max 精确半径球壳；青色壳是当前距离。
- Hinge：Z 轴直线、X 零位参考、角度 limit 弧和边界辐条；青色辐条是当前角，洋红辐条是 Position motor 目标。
- Slider：Z 轴滑轨、min/max 端点刻度；青色刻度是当前位置，洋红刻度/箭头是 motor 目标。
- Cone：Z twist axis、half-angle cone 边界和自由 twist 小环。

## 模块边界

约束语义绘制位于 `rigid/constraint_debug/`，每个约束类型一个 renderer。公共 `rigid/debug_draw.py` 只负责：

- 从 world slot/result stream 取纯快照；
- 按颜色聚合线段；
- 维护 Blender viewport draw handler。

新增约束时必须同时增加：spec/binding、result state（若有动态值）、`constraint_debug` renderer、本文档和测试。未知类型会退化为通用 anchor frame，并出现在 snapshot 的 `unknown_constraint_types` 中，不会静默假装已支持。
