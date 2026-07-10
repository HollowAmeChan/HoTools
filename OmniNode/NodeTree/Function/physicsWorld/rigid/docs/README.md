# Rigid/Jolt Solver 用户文档

这里是 `physicsWorld/rigid` solver 随代码维护的用户文档。文档描述 HoTools 当前真正暴露的能力，不把 Jolt 原生支持但 binding 尚未接入的功能算作已支持。

建议阅读顺序：

1. [约束快速上手](CONSTRAINT_QUICKSTART.md)：从两个刚体和一个 Empty 开始。
2. [约束类型参考](CONSTRAINT_REFERENCE.md)：六种已接入约束的自由度、轴、限制和 motor。
3. [约束调试绘制](DEBUG_DRAW_GUIDE.md)：读懂 viewport 中的颜色和图形。

权威外部参考：

- [Jolt Physics：Constraints](https://jrouwe.github.io/JoltPhysics/index.html#constraints)
- [Jolt Physics Samples](https://github.com/jrouwe/JoltPhysics/tree/master/Samples/Tests/Constraints)

## 当前边界

HoTools 当前支持 `FIXED / POINT / DISTANCE / HINGE / SLIDER / CONE`。Jolt 原生还提供 SwingTwist、SixDOF、Path、Gear、RackAndPinion、Pulley 和 Vehicle；这些类型尚未进入 HoTools 的公共 spec、binding 和调试绘制器。

运行时约束结果位于 `rigid_constraint_state` result stream。用户和其它 solver 不应读取 Jolt constraint handle。
