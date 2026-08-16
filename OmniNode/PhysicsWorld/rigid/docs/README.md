# PhysicsWorld 刚体文档

这里是 `PhysicsWorld/rigid` 随代码维护的文档入口。当前刚体求解器使用 Jolt；PMX 2.0 作为现有刚体域的 source adapter 接入，不增加第二个 backend。

产品方向、资源导航和实施顺序以 [Jolt Physics 产品化路线图](../../../doc/JOLT_PHYSICS_BACKGROUND_ANALYSIS.md) 为准。近期只模拟和写回 Blender Objects：Geometry Nodes 结果先通过显式创作操作应用、Realize 并拆分为独立 Objects，再进入现有刚体链。凸包、Full Mesh 和 GN runtime instances 均不是当前第一里程碑。

## 现有 Jolt 文档

1. [刚体破碎资产蓝本](RIGID_FRACTURE_BLUEPRINT.md)：GN 显式刷新、受管 Piece、Scope 展开、初始激活和球撞墙验收。
2. [Jolt 设置参考](JOLT_SETTINGS_REFERENCE.md)：当前设置、更新类别和下一批候选。
3. [约束快速上手](CONSTRAINT_QUICKSTART.md)：从两个刚体和一个 Empty 开始。
4. [约束类型参考](CONSTRAINT_REFERENCE.md)：自由度、轴、限位、spring、motor 和明确排除项。
5. [约束调试绘制](DEBUG_DRAW_GUIDE.md)：Viewport 颜色和图形含义。
6. [Jolt 语义测试策略](JOLT_TEST_STRATEGY.md)：fixture、oracle、确定性、golden 和门禁。
7. [性能优化契约](JOLT_PERFORMANCE_OPTIMIZATION.md)：当前热点、测量顺序和 Object 批路径。
8. [Object 写回性能边界](JOLT_WRITEBACK_PERFORMANCE_BOUNDARY.md)：列式结果、Collection 批写回和后续边界。

当前通用后端已经接入 `FIXED`、`POINT`、`DISTANCE`、`HINGE`、`SLIDER`、`CONE`、`SWING_TWIST`、`SIX_DOF`、`PULLEY`、`GEAR` 和 `RACK_AND_PINION`。运行结果进入 `rigid_transform`、`rigid_constraint_state`、contact/sensor/query/stats streams；外部模块不读取 Jolt handle。

近期约束工作只补这十一种类型的参数、运行时控制、诊断和节点拆分。`Path`、Vehicle、Soft Body 和 Ragdoll 长期排除在当前路线之外。

## PMX 2.0 接入文档

按以下顺序阅读：

1. [永久协议合同与端到端预演](MMD_PMX20_PROTOCOL_CONTRACT.md)：精确头部、完整二进制游标、物理记录、合法 `-1` 和原子提交。
2. [PMX 2.0 到 Jolt 接纳矩阵](MMD_JOLT_ACCEPTANCE_MATRIX.md)：逐字段状态、当前通用缺口和 Spring6DOF 校准门卫。
3. [刚体接入架构](MMD_RIGID_SOLVER_DESIGN.md)：reader、DTO、稳定身份、generated specs、骨骼 binding 和运行时所有权。
4. [实施计划](MMD_RIGID_IMPLEMENTATION_PLAN.md)：从独立 reader 到 conversion、通用基础设施、Jolt、骨骼、bake 和性能的阶段出口。
5. [研究记录](../../../../_research/MMD_EXTERNAL_RESEARCH_NOTES.md)：本机协议来源、代码审计、盘点规模和待验证实验。

## 已冻结方向

- 永久只接受精确 PMX 2.0；版本、完整结构和 EOF 在创建 DTO 前严格校验。
- PMX 是 `rigid_jolt` 的 source adapter，不是 `rigid_mmd` solver；不引入 Bullet。
- 生产 reader 独立实现并完整走过所有前置段；`mmd_tools` 只作研究 oracle。
- canonical DTO 保存全部刚体和 Joint 原字段；转换结果必须可追溯到 source/index/field。
- 先补通用 `rigid.generated_body`、显式 body slot ID 和 constraint target slot ID，再接 PMX 运行态。
- mode `0` 映射为 bound `KINEMATIC` 或 unbound `STATIC`；mode `1/2` 使用 `DYNAMIC`，差异位于统一 bone writeback resolver。
- bone index `-1` 和 Joint endpoint `-1` 是合法语义，不按坏引用处理。
- Spring6DOF 的 frame/limits 与逐轴 motor spring 必须分别通过 fixture；未校准时不允许静默丢 spring。
- MMD UI 放在完整运行链、诊断、reset/bake 和性能门卫之后，只显示 source、binding、profile 和错误，不复制通用刚体属性。

外部参考：

- [Jolt Physics Constraints](https://jrouwe.github.io/JoltPhysics/index.html#constraints)
- [Jolt SixDOFConstraintSettings](https://jrouwe.github.io/JoltPhysics/class_six_d_o_f_constraint_settings.html)
- [Jolt Physics Samples](https://github.com/jrouwe/JoltPhysics/tree/master/Samples/Tests/Constraints)
