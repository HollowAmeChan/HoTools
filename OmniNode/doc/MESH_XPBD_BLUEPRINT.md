# Mesh XPBD 基础 Solver 蓝本

本文定义 Physics World 中独立 `mesh_xpbd` solver 的迁移目标、数值合同、冻结边界和验收顺序。它不是旧节点说明，也不继承 MC2 的产品域。公共生命周期、碰撞、结果流和写回规则以 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 为准。

## 产品定位

Mesh XPBD 保留，但只保留为一个干净、可读、可扩展 Physics World 的基础纯 Mesh solver 蓝本：

- 它解决单个 Mesh 的粒子距离约束，不承担 MC2 的融合域、对象收集、自碰撞和 GPU 路线。
- 它与 SpringBone VRM 一样是独立 solver module，不是 MC2 setup。
- 它验证 Mesh topology、native context、公共碰撞和 GN 写回的最小完整生命周期。
- 生产验收后冻结能力和数值语义。未来高级 XPBD 改良另起 solver id，不在这个基线上不断加分支。

旧 `网格物理-XPBD` / `网格物理-XPBD-CPP` 只是迁移输入，不是行为权威。旧实现的私有 cache、场景扫描、直接 GN 写回和伪 CPP 入口均不得进入新模块。

## 用户链路

最终节点链路固定为：

```text
XPBD网格对象 / XPBD网格自定义对象
  -> XPBD网格任务
  -> XPBD模拟步 + Physics World
  -> Physics Writeback
  -> Physics World Commit
```

普通对象节点只接收统一物理面板中已开启“简单布料”的对象，并读取 `Object.hotools_mesh_collision` 中 XPBD 声明消费的 Pin、半径顶点组和外碰接受掩码；面板 `enabled` 只作 authoring 过滤，不进入 task/spec 签名。自定义对象节点只读取 socket，不受该面板开关影响，默认掩码为 `0`。对象层不携带数值 solver 参数，任务层为一个或多个对象统一附加粒子半径、碰撞开关、顺从度、迭代、阻尼和重力。

第一版仍不建立 MC2 式融合域和域收集。基础 XPBD 不做网格之间的融合、自碰或共享约束，因此对象与任务分层是必要的 authoring 一致性，而 domain/collector 会制造没有运行语义的空抽象。

## 冻结能力范围

进入冻结里程碑前必须完成：

- source Mesh 静态拓扑与 Basis/reference rest position；modifier 改变顶点身份不属于基础 solver；
- Object `matrix_world` 动画与世界空间惯性；
- 二值 Pin 顶点组；
- 逐顶点外碰半径组；
- 真正 XPBD edge stretch；
- 明确命名为“对边顶点距离”的基础 bend，不伪称 dihedral bending；
- 公共 Physics World `SPHERE`、`CAPSULE`、`PLANE`、`BOX` collider snapshot；
- 16 组外碰接受掩码，默认 `0`，即默认不与任何外部对象碰撞；
- 公共 `GN_ATTRIBUTE_CHANNEL` offset 写回；
- slot/native context 生命周期、same-frame 重发布、暂停、重启、dispose 和 debug；
- 单对象及多任务事务验证、生产 `.blend` 回归和连续播放 soak。

明确不属于基础 solver：

- self collision 或 mesh-mesh collision；
- 体积软体、压力、撕裂、塑性；
- CCD、复杂摩擦或接触流形；
- dihedral/各向异性等高级弯曲；
- GPU backend；
- MC2 domain fusion、collector 和 setup 语义。

这些能力会改变数据布局、数值预期或产品边界，必须由新 solver 承担。

## 数值合同

所有距离约束都使用带累计乘子的严格 XPBD 更新。对约束 `C(x)`：

```text
alpha_tilde = compliance / dt_substep^2
delta_lambda = (-C(x) - alpha_tilde * lambda) /
               (sum_i(w_i * |grad_i C|^2) + alpha_tilde)
lambda += delta_lambda
x_i += w_i * grad_i(C) * delta_lambda
```

要求：

- `lambda` 在每个 substep 开始时清零，在该 substep 的 iterations 间累计；
- 不能退化成没有 `-alpha_tilde * lambda` 的 PBD 式投影；
- compliance 为 `0` 时是硬约束；
- stretch 和 bend 分别持有独立 lambda 数组；
- 固定粒子 inverse mass 为 `0`，移动粒子第一版统一为 `1`；
- 零长度约束、非有限输入和退化三角形必须有确定行为，不能产生 NaN；
- damping 表示每个 Physics World 场景帧的速度阻尼，native 按实际 substep 数转换；
- 旧节点 preset 不直接继承。默认值只能在双 ABI fixture 和 Blender 生产场景校准后冻结。

基础 bend 从共享三角边两侧的 opposite vertices 构造距离约束。名称、debug 和统计必须都写“opposite-vertex distance bend”，避免把它描述成未实现的二面角模型。

## 坐标与拓扑

- rest local position 来自 Basis/reference Mesh；solver 常驻 position/previous position 使用世界空间。
- 写回只发布 `current_world - rest_world` 转换后的 object-local offset，不修改 mesh vertex、Basis 或 shape key。
- object transform 变化时重新派生 rest world、约束长度和世界半径；动态粒子位置保持世界空间惯性。
- topology signature 必须覆盖 source Mesh vertex/edge、用于 bend 的 loop triangulation、rest source identity，不能只比较数量或 edge hash。
- Pin、radius vertex group 和 reference position 变化是静态数组 dirty；数值参数与碰撞掩码是 context 参数 dirty；拓扑变化使用 staged replacement。

`MeshXpbdTaskSpec.topology_identity` 只表达 Object/Data 身份。完整 evaluated mesh 内容签名由后续 topology adapter 生成，不能用指针身份代替内容失效检测。

## Physics World 生命周期

- task 先全部校验，再创建、更新或裁剪 slot；重复 source 是输入错误。
- `slot_id = mesh_xpbd:{object_ptr}:{data_ptr}`，参数变化不创建新 slot。
- solver 只消费 `world.frame_context`，不自行读取 Scene FPS 或判断连续帧。
- same-frame 与 `dt <= 0` 不推进 native，但必须重新发布上一结果，不能清空输出。
- restart 从当前 reference pose 冷启动 position/previous position，并清零 lambda/速度历史。
- collider 只来自 `world.collider_snapshot`；不扫描 `bpy.context.scene`、visible objects 或骨架。
- 默认 `collided_by_groups = 0` 是明确的 opt-in 外碰语义，不是“全部组”的哨兵值。
- solver step 不写 Blender。真实 GN attribute/modifier 和 `update_tag` 由公共 writeback 管理。
- Cache Delete、runtime clear、load/undo、插件注销和不兼容 native 版本必须 dispose native context。
- `XPBD可视化调试` 的 draw store 与 viewport handler 通过 solver module 的 `world_dispose_handlers` 归属当前 world owner；跳帧产生的 cache replace、Cache Delete 和 `OmniRuntimeState.clear_all()` 必须按 world identity 清理旧条目，最后一个条目消失时移除 handler。

## Native 边界

新后端只有一个纯 nanobind context API：

- typed contiguous ndarray 输入输出；
- C++ context 持有 topology、rest data、position、previous position、lambda 和可热更新参数；
- native 不导入 `bpy`、不保存 Blender pointer、不写 GN、不拥有模块级可变全局状态；
- Python 不保留平行数值 solver；测试 oracle 可以是小型离线公式，但不得成为运行 fallback；
- 不恢复旧 `PyMethodDef` / `PyBuffer` 绑定；
- 双 ABI 必须分别验证 import、context create/step/dispose、数值 golden 和异常边界。

建议 API 形状：

```text
mesh_xpbd_create_context(static_arrays, parameters) -> Context
Context.update_static(...)
Context.update_parameters(...)
Context.step(frame_input, collider_arrays) -> positions/stats
Context.reset(frame_input)
Context.stats() -> dict
Context.dispose()
```

最终名称以 native binding 实现为准，但禁止同时暴露 Python/CPP 两个产品节点。

## Result、Writeback 与 Debug

- 每个成功 task 发布一条 `GN_ATTRIBUTE_CHANNEL` 公共 mesh vertex offset command。
- command 使用公共 `make_gn_offset_writeback`，目标 identity、vertex count 和 offset shape 在任何 Blender mutation 前完整校验。
- 多 task 任一失败时，本轮不得产生部分 Blender 写回。
- stats/debug 是请求驱动；关闭时不额外复制 topology、particle 或 collider 数组。
- debug 至少公开 frame decision、slot status、particle/stretch/bend/collider counts、step time、non-finite guard 和 native context generation。
- debug 观察 production pass，不另跑一遍 shadow solver。
- `XPBD可视化调试` 独立位于模拟步下游；任一视图开启后才请求下一次 solver 捕获，全部关闭时清除快照并移除视口 draw handler。
- 调试节点不拥有第二套帧生命周期。world owner 被 runtime 替换或销毁时，即使节点本帧没有再次执行，注册表调度的 dispose hook 也必须清除其冻结快照和视口 handler。
- 可视化覆盖 Move/Pin 粒子、当前三角面、Stretch/Bend 相对 rest 误差、rest 偏移、表面法线、任务重力、逐粒子半径、实际消费的四类公共碰撞体，以及最终位置的接触接近/残余穿透审计。
- 任务筛选、每类显示上限、约束误差阈值、接触边距和显示缩放只影响调试读取与绘制，不进入 solver 参数或 dirty key。

## 分阶段验收与删除

1. **合同**：模块可发现、任务规格严格校验、能力与删除清单进入测试；不暴露未工作的节点。
2. **Native 数值核**：严格 XPBD context、四类 collider 数组合同、纯 C++ 与双 Python ABI golden。
3. **World vertical slice**：topology、slot、frame context、result/writeback、debug、节点和 dispose 闭环。
4. **生产验收**：固定 fixture、`OMNI测试.blend` 或等价生产场景、跳帧/暂停/同帧、变换、拓扑 dirty、多任务事务、soak。
5. **旧路径删除**：一次删除 `_MeshPhysics`、`_MeshPhysicsCppBackend`、两个旧节点、私有 `_OmniCache` payload、`XPBDDelta`/`xpbd_delta` 和悬空 native 名称；不保留运行兼容层。
6. **冻结**：记录最终参数默认值、ABI/layout version、能力矩阵和性能基线。此后只修 bug、兼容性和确定性，不扩张产品范围。

截至 2026-08-01，阶段 1 到 4 已完成。生产验收使用 Blender 4.5.8 只读加载 `OMNI测试.blend`，在其中真实 8 顶点 `Cube` 上连续运行 180 帧：177 次 native step、2 次有意 reset、公共平面碰撞、逐帧 GN 写回、同帧重发布、零 dt 暂停、world restart、参数热更新和 `matrix_world` 动画均保持单一 slot/context；最终最大局部 offset 约 `0.5881`，全程有限。对应回归脚本为 `mesh_xpbd/test/test_blender_production_soak.py`。

dirty/lifecycle 回归同时覆盖：孤立顶点导致的 particle-count topology replacement、Basis/reference 静态 reset、纯数值参数热更新、矩阵参考系更新保留惯性、generation replacement、task prune 和 world dispose。阶段 5 完成前仍不得标记为冻结。

完成 XPBD 删除后，再审计 `_native` 中未被现有 Physics World solver 消费的旧规划。SpringBone VRM 与 MC2 仍在使用的 raw `PyObject*` bridge 只能列入后续 nanobind 迁移，不能因“旧”而误删。

旧路径删除审计（2026-08-01）已完成：`Function/Physics.py` 中的 `_MeshPhysics`、`_MeshPhysicsCppBackend`、`_run_mesh_xpbd_node`、`meshPhysicsXPBD`、`meshPhysicsXPBDCpp`、`XPBDDelta`、`xpbd_delta` 和私有 `_OmniCache` 写回均已移除；函数注册回归确认旧两个节点不存在，新对象/自定义对象/任务/模拟步/可视化调试五节点存在。双 ABI 的实际 `hotools_native` 导出均只提供 `MeshXpbdContextV1` 与 `mesh_xpbd_create_context_v1`，旧 `solve_mesh_delta_xpbd` / `solve_mesh_shape_key_xpbd` 没有定义或导出。共享 MC2、SpringBone VRM、Jolt 和 property-curve native 单元未触碰。
