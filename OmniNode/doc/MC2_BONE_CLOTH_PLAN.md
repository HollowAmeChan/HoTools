# MC2 BoneCloth 统一域删除前计划

## 目标与边界

BoneCloth 只保留 Armature authoring、骨链拓扑、动画姿态采集和 PoseBone 写回职责。粒子状态、Center/Anchor/Teleport、约束、外碰、whole-domain self、post/history、调试快照和结果事务全部由统一 `DomainV1` 产品路径拥有。

- 一个 Armature 对应一个可观察统一域；同一 Armature 的多条骨链是域内 partition。
- 跨 Armature 才产生多个 `MC2ProductRequestV1`，并由同一次 Physics World 事务提交。
- 对象整体变换属于 Center；骨根动画参考的突变属于 task-reference pass。
- 输出只能通过 Bone writeback transaction 发布；失败不能部分写入 PoseBone、owner、scheduler、frame state 或 result。
- 产品路径不得导入或回退到 `MC2TaskSpec`、旧 solver、`MC2NativeContextV0`、hidden task 或普通 aggregate。

## Oracle 归属

| 行为 | 最终归属 | 删除前状态 |
| --- | --- | --- |
| 骨名、链、横向 triangle、partition/source identity | `MC2BoneStaticFragmentV1` 与 topology tests | 已成立 |
| 动画姿态、StepBasic、骨骼方向和 root reference | shared bone orientation、product bone frame 与 task-reference tests | 已成立 |
| Center/Anchor/Teleport、Reset/Keep、零 substep | DomainV1 与产品 Center/Teleport tests | 已成立 |
| Distance/Tether | shared kernel、产品 constraint record 与参数响应 tests | 已成立 |
| Angle Restoration/Limit、Motion/Backstop、target/rest | shared kernel、产品 record 与边界 tests | 已成立 |
| 外碰、摩擦、过滤和半径 | compiled collider POD、shared kernel 与产品 collision tests | 已成立 |
| 同 Armature 跨 source self、cache/radius | whole-domain self owner 与产品 self tests | 已成立 |
| connected/disconnected 写回、多 request 和失败回滚 | product output、Bone writeback transaction 与 slot tests | 已成立 |
| Triangle Bending | `test_blender_mc2_bone_product_bending.py` | dihedral kind 已锁定 stiffness `0/1` 真实响应、record hit/correction、fixed 静置与 600 帧双跑；signed-volume 长程分支仍是缺口 |

## 删除前剩余工作

1. 为 BoneCloth Bending 补齐 signed-volume 长程分支；dihedral method、四角色 record、fixed 粒子、非零响应和确定性已由独立产品 runner 固定。
2. 逐条映射旧 Bone constraint runner 的剩余断言；中立 Armature/几何 helper 迁到产品测试公共模块，读取 `native_context` 或旧 slot 的断言直接淘汰。
3. 运行产品、公开节点和 debug 可达性审计，确认 BoneCloth 不再依赖 `solver.py`、`native_context.py`、`interaction_scope.py`、`specs.py` 或 V0 binding。
4. 与 Mesh/BoneSpring 共用同一 E7-CPU 删除批次移除旧 owner、hidden task、普通 aggregate 和 V0 ABI；随后执行 E7-S 简化。

## 删除门槛

- capability matrix 的 BoneCloth 字段和 invariant 只由 DomainV1、共享 kernel 或产品 runner 覆盖。
- 旧 Bone runner 不再承担唯一数值 oracle，也不再导入 mixed runner 或读取 `slot.data["native_context"]`。
- Python 3.13 / Blender 5.2 的产品事务、长程确定性、debug-off 和失败回滚全部通过。
- 4.5/py311 在旧面删除和 E7-S 基本完成前保持冻结。
