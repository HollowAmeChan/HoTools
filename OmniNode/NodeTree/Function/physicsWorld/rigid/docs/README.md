# Rigid/Jolt Solver 用户文档

这里是 `physicsWorld/rigid` solver 随代码维护的用户文档。文档描述 HoTools 当前真正暴露的能力，不把 Jolt 原生支持但 binding 尚未接入的功能算作已支持。

建议阅读顺序：

1. [约束快速上手](CONSTRAINT_QUICKSTART.md)：从两个刚体和一个 Empty 开始。
2. [约束类型参考](CONSTRAINT_REFERENCE.md)：八种已接入约束的自由度、轴、限制和 motor。
3. [约束调试绘制](DEBUG_DRAW_GUIDE.md)：读懂 viewport 中的颜色和图形。
4. [Jolt 语义测试策略与验收矩阵](JOLT_TEST_STRATEGY.md)：定义 fixture、oracle、确定性、golden、门禁和完整测试矩阵。

权威外部参考：

- [Jolt Physics：Constraints](https://jrouwe.github.io/JoltPhysics/index.html#constraints)
- [Jolt Physics Samples](https://github.com/jrouwe/JoltPhysics/tree/master/Samples/Tests/Constraints)

## 当前边界

HoTools 当前支持 `FIXED / POINT / DISTANCE / HINGE / SLIDER / CONE / SWING_TWIST / SIX_DOF`。其中 SixDOF 已接显式与生成约束、六轴 Free/Fixed/Limited、范围、逐轴 friction、逐轴 motor、三平移轴 limit spring、六轴 current-value result 和专用调试绘制。Pulley 已完成 native binding 与 S1 解析验收，公共 spec、属性和调试绘制待接；Path、Gear、RackAndPinion 和 Vehicle 尚未进入公共链路。

运行时约束结果位于 `rigid_constraint_state` result stream。用户和其它 solver 不应读取 Jolt constraint handle。

当前 native/Blender 回归通过只代表 API、管线和生命周期覆盖。物理语义结论以 `JOLT_TEST_STRATEGY.md` 的独立 semantic matrix 为准；尚未进入 S2/S3 或稳定性矩阵的能力不能只凭链路测试宣称已完整验收。
