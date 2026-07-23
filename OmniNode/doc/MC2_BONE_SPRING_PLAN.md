# MC2 BoneSpring 统一域计划

## 当前状态（2026-07-23）

公共 Blender 5.2 / Python 3.13 产品测试 helper 已从旧 mixed runner 解耦，并固定使用当前 `py313` native 包。BoneSpring 的约束、Angle/Motion、外碰和摩擦产品 runner 已完成 600/900 帧双跑；这些 runner 已成为迁移中的有效证据。旧约束 soak 仍仅用于迁移盘点；任何 V0 task、hidden task 或 `native_context` 断言都不能作为产品通过证据。能力矩阵完成产品态替换和删除前审计前，不删除 BoneSpring 旧 owner。

## 旧断言迁移清单

| 旧符号 | 当前产品证据 | 状态 |
| --- | --- | --- |
| `bone_angle_constraints`、`bone_angle_limit` | `test_blender_mc2_bone_product_angle_motion.py` | 已有 600 帧数值边界；精确 target/rest 断言仍需补齐 |
| `bone_external_collision`、`bone_friction_response` | `test_blender_mc2_bone_product_collision_soak.py` | 已有 600 帧筛选、响应、摩擦和确定性 |
| `bone_distance_tether` | `test_blender_mc2_bone_product_constraint_soak.py` | 已有 topology、参数 SoA、finite 和 900 帧确定性 |
| `bone_gravity_axes_falloff`、`bone_angle_restoration_attenuation`、`bone_angle_restoration_falloff`、`bone_self_collision` | 暂无完整产品 runner | 保留为删除前缺口，不得由旧 V0 soak 继续宣称通过 |

## 目标

BoneSpring 与 BoneCloth 共用同一套 DomainV1 粒子域和产品 collector，只保留 spring-specific authoring、拓扑和参数包装。任何粒子状态或执行顺序差异都必须落在共享合同或明确的 BoneSpring 参数表中。

## 固定边界

- 一个 Armature 对应一个统一 domain；同 Armature 多链是 domain 内 partition，跨 Armature 才是多个 product request。
- 输入由 `bone_frame_input.py` 生成，输出由统一 Bone writeback transaction 提交；不得恢复旧 task owner、native context 或普通 aggregate。
- component pose 由 Armature object 提供。对象整体变换交给 Center；骨根 animated reference 的不连续变化交给 task-reference pass。
- BoneSpring 允许的限制只包括 spring-specific 拓扑/参数/authoring 约束；不能改变 DomainV1 的 shared pass order、self policy、事务提交和调试边界。

## Oracle 归属

| 行为 | 最终断言归属 |
| --- | --- |
| spring source、骨骼拓扑、partition 顺序 | BoneSpring static fragment/topology tests |
| 骨骼姿态方向与 root reference | shared bone orientation kernel、task-reference product runner |
| spring distance/tether/bending 参数 | shared constraint kernel 与 BoneSpring 参数合同 |
| Center、Teleport、碰撞、whole-domain self、history | DomainV1 与统一 capability matrix |
| writeback、回滚、generation/scheduler 生命周期 | product frame/slot owner tests |

旧 BoneSpring 约束 soak 若通过 mixed runner 或 `native_context` 读取内部计数，只能作为迁移清单，不能作为删除后的验收依据。

## 实施顺序

1. 以统一 Bone product collector 覆盖 BoneSpring 单 Armature、多链 partition、root Teleport Reset/Keep、spring 参数更新和写回事务。
2. 把 BoneSpring 仍复用的测试构造 helper 移到不依赖旧 owner 的公共产品测试模块；把内部 inspect 断言改为公开 owner/debug/readback 合同。
3. 在 Python 3.13 / Blender 5.2 执行 600 帧双跑，单独验证 spring 参数变化不会破坏 task/Center 顺序和 history。
4. 完成旧路径可达性审计，移除 `solver.py`、`native_context.py`、`interaction_scope.py`、`shadow_pipeline.py` 与 `MC2TaskSpec` 的 BoneSpring 入口。
5. 删除旧 BoneSpring hidden task、普通 aggregate 和 V0 binding；紧接着执行 E7-S，删除不再需要的兼容翻译层。

## 删除门槛

- BoneSpring 每一项公开行为都有 shared kernel、DomainV1 或 product collector oracle。
- BoneSpring runner 不再读取 `slot.data["native_context"]`，不再导入 mixed runner。
- capability matrix 的 BoneSpring 字段和 invariant 均由统一产品证据覆盖。
- 删除旧实现后，Python 3.13 / Blender 5.2 全量验收无未解释 CPU 回归；4.5/py311 仅在最终双 ABI 收尾时恢复。
