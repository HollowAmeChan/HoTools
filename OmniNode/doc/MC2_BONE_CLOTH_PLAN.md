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
| Triangle Bending | `test_blender_mc2_bone_product_bending.py`、`test_blender_mc2_bone_product_volume_bending.py` | dihedral kind 已锁定 stiffness `0/1` 真实响应、record hit/correction 和 fixed 静置；signed-volume 已锁定真实 marker/kind、逐帧符号不翻转、体积有界和 600 帧双跑 |

## 删除签字状态

1. 旧 Bone constraint runner 的唯一数值证据已全部迁入产品 runner；中立 Armature/几何 helper 已由产品测试直接拥有，读取旧 slot/context 的断言已淘汰。
2. 产品、公开节点和 debug 可达性审计为零；`solver.py`、`native_context.py`、`interaction_scope.py`、`specs.py` 与纯旧 runner 已删除。
3. BoneCloth 不再单独阻塞旧 owner 删除；native V0 ABI/TU、专用头文件和直接 V0 native tests 也已删除。剩余工作与 Mesh/BoneSpring 共用：执行 E7-S、P6 合同收口和最终双 ABI/Blender 验收；全部门禁关闭后物理删除本文档。

## 删除门槛

- capability matrix 的 BoneCloth 字段和 invariant 只由 DomainV1、共享 kernel 或产品 runner 覆盖。
- 旧 Bone runner 不再承担唯一数值 oracle，也不再导入 mixed runner 或读取 `slot.data["native_context"]`。
- Python 3.13 / Blender 5.2 的产品事务、长程确定性、debug-off 和失败回滚全部通过。
- 4.5/py311 在旧面删除和 E7-S 基本完成前保持冻结。
