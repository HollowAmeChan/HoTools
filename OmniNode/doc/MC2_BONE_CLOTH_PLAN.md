# MC2 BoneCloth 统一域计划

## 当前状态（2026-07-23）

公共 Blender 5.2 / Python 3.13 产品测试 helper 已从旧 mixed runner 解耦，并固定使用当前 `py313` native 包。BoneCloth/BoneSpring 的约束、Angle/Motion、外碰和摩擦产品 runner 已完成 600/900 帧双跑；这些 runner 已成为迁移中的有效证据。旧约束 soak 的主体仍然是迁移清单：它调用的 V0 task 已被产品入口拒绝，因此本阶段不把它当作通过证据，也不删除旧 owner。下一步必须把能力矩阵中仍指向该 soak 的每一项改为产品 request、DomainV1 或共享 kernel 证据，再执行删除前审计。

## 旧断言迁移清单

| 旧符号 | 当前产品证据 | 状态 |
| --- | --- | --- |
| `bone_angle_constraints`、`bone_angle_limit`、`bone_motion_constraints` | `test_blender_mc2_bone_product_angle_motion.py` | 已有 600 帧数值边界；Angle target/rest 由请求式 native record 对照同一 StepBasic pose，并由 BoneCloth/BoneSpring 各自双跑锁定 |
| `bone_external_collision`、`bone_friction_response` | `test_blender_mc2_bone_product_collision_soak.py` | 已有 600 帧筛选、响应、摩擦和确定性 |
| `bone_distance_tether`、`bone_triangle_bending` | `test_blender_mc2_bone_product_constraint_soak.py`、`test_blender_mc2_bone_product_distance_tether.py` | Distance/Tether 已锁定实际 stiffness 有序、真实 hit/correction、rest/bound 和 600 帧双跑；Bending 边界响应仍是缺口 |
| `bone_gravity_axes_falloff` | `test_blender_mc2_bone_product_angle_motion.py::test_bone_product_gravity_axes_falloff` | 已锁定 gravity、归一化三轴方向、falloff、600 帧 finite/deterministic、轴向速度与 falloff 比例 |
| `bone_rotation_output_controls` | `test_blender_mc2_bone_product_angle_motion.py::test_bone_product_rotation_output_controls` | BoneCloth/BoneSpring 均已验证 rotation 参数 ABI、fixed/move/leaf 目标集合与位置不变性 |
| `bone_self_collision` | `test_blender_mc2_bone_product_constraint_soak.py::test_bone_product_self_collision_domain_contract`、`test_bone_product_self_collision_cross_source_scope_and_cache` | 已锁定 derived-radius、cloth mass、whole-domain self step；同域双 source partition 的真实跨 partition contact、逐帧有界 cache 和 radius consistency 已由 900 帧双跑关闭 |

## 目标

BoneCloth 只作为统一 MC2 DomainV1 的产品包装层存在。包装层负责 Armature、骨骼 authoring 限制、写回和 Blender 事务；Physics World 负责 domain owner、粒子状态、约束、Center、Teleport、碰撞、whole-domain self 和结果发布。

## 固定边界

- 一个 Armature 对应一个统一 domain；同一 Armature 的多条骨链在同一 domain 内按 partition 编译。
- 跨 Armature 才产生多个独立 product request；包装层不得把多 Armature 偷合并成一个 domain。
- BoneCloth 使用 `bone_frame_input.py` 读取骨架姿态，使用 `product_bone_frame.py` 生成统一 frame packet；不得重新引入 task-local native context。
- BoneCloth 的 component pose 由 Armature object 提供，骨骼根姿态属于 animated reference；对象整体位移/旋转由 Center 处理，根姿态突变由 task-reference pass 处理。
- 输出只能通过 Bone writeback transaction 提交；失败时 owner、scheduler、bone frame state 和 output candidate 必须保持原值。

## Oracle 归属

| 行为 | 最终断言归属 |
| --- | --- |
| 拓扑、bone 名称、source index | `MC2BoneStaticFragmentV1` 与 topology tests |
| 骨骼姿态到粒子旋转 | `mc2_bone_frame_orientations_v1` 与 bone frame tests |
| root reference Teleport、Reset/Keep、速度参考 | DomainV1 task-reference native tests 与 Blender 5.2 product runner |
| Center、约束、碰撞、self、post/history | 共享 kernel、DomainV1 golden 和 capability matrix |
| Blender 写回、回滚、同代参数更新 | Bone product frame/slot owner tests |

旧 mixed runner 只能在 helper 迁移期间作为历史对照，不得继续作为 BoneCloth oracle，也不得读取 `native_context`、旧 solver slot 或 hidden task。

## 实施顺序

1. 让 BoneCloth product runner 覆盖统一 domain 的单 Armature、多链 partition、root Teleport Reset/Keep、写回回滚和确定性双跑。
2. 将仍被 `test_blender_mc2_bone_constraint_soak.py` 导入的几何/Armature 构造 helper 移到产品测试公共 helper；测试断言改读 owner、DomainV1 或公开 candidate。
3. 在 Python 3.13 / Blender 5.2 完成 600 帧双跑、零 substep、对象整体变换与骨根变换隔离验收。
4. 运行架构可达性审计，确认 BoneCloth 产品路径不再依赖 `solver.py`、`native_context.py`、`interaction_scope.py`、`shadow_pipeline.py` 或 `MC2TaskSpec`。
5. 删除旧 BoneCloth hidden task、普通 aggregate 和 V0 binding；随后执行 E7-S，清理迁移期 fallback/compat 分支。

## 删除门槛

- BoneCloth product runner 的全部断言已有 DomainV1/shared-kernel/product collector 归属。
- `test_blender_mc2_bone_constraint_soak.py` 不再导入 mixed runner 或访问 `slot.data["native_context"]`。
- capability matrix 中 BoneCloth 的每个声明均由统一产品 runner 或共享合同覆盖。
- 仅在上述条件满足后才允许删除旧 BoneCloth owner/hidden-task 路径。
