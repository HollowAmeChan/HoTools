# MC2 BoneSpring 统一域删除前计划

## 目标与边界

BoneSpring 与 BoneCloth 共用同一个 `DomainV1` backend 和 Bone 产品 collector，只保留 Line 骨链、spring-specific 参数归一化、Sphere-only 外碰和 PoseBone 写回限制。它不是第二套 solver，也不拥有独立 pass 顺序。

- 一个 Armature 对应一个可观察统一域；同 Armature 多链是域内 partition，跨 Armature 才产生多个 request。
- 对象整体变换属于 Center；骨根动画参考的突变属于 task-reference pass。
- 输入由产品 Bone frame packet 提供，输出由统一 Bone writeback transaction 发布。
- 包装限制必须在 runtime 参数合同中显式归零或固定，不能靠无效 topology 偶然不产生结果。
- 产品路径不得恢复旧 task owner、native context、hidden task 或普通 aggregate。

## 固定包装合同

| 能力 | BoneSpring 产品合同 | 删除前状态 |
| --- | --- | --- |
| Distance | stiffness 固定为 `0.5`，authoring 输入不得改变有效值或轨迹 | 已有产品证据 |
| Tether | 使用 Line setup 的共享记录与边界，不产生第二套 spring kernel | 已有产品证据 |
| Bending | stiffness/method 强制为零；Line topology 不进入 Bending pass | `test_blender_mc2_bone_product_bending.py` 已锁定输入 profile 不产生 Bending table、有效 record 或 solve count，并完成 600 帧双跑 |
| Self collision | mode/sync/thickness 强制为零；不建立 primitive/cache/radius self 合同 | `test_blender_mc2_bone_spring_product_restrictions.py` 已锁定敌对输入保留在 request，但 compiled self 参数和静态表为空、debug 无记录，且轨迹与关闭输入一致 |
| Gravity、Motion/Backstop | 按 setup 合同关闭，不列为缺失能力 | 同一限制 runner 已锁定 compiled 参数归零和敌对/关闭输入长程轨迹等价 |
| Angle Restoration/Limit | 使用共享 kernel 和 BoneSpring 有效参数 | 已有 target/rest、边界与响应证据 |
| External collision | 只接受 Sphere，并消费 soft collision limit | 已有过滤、响应和确定性证据 |
| Rotation/writeback | 使用统一 Bone output 与事务 | 已有目标集合、多 request 和失败回滚证据 |

## 删除签字状态

1. 有价值的 topology/参数 helper 已由产品测试拥有；依赖旧 context 内部计数的断言已淘汰。
2. capability matrix 已把强制关闭字段归入包装限制，并由 BoneSpring 自身产品证据覆盖，不借用 BoneCloth self/Bending 证据。
3. Python 旧 owner、hidden task、普通 aggregate 入口、native V0 ABI/TU、专用头文件与纯旧测试均已删除。剩余工作与 Mesh/BoneCloth 共用：执行 E7-S Python 文件职责收敛与兼容层清理、P6 合同收口和最终双 ABI/Blender 验收；全部门禁关闭后物理删除本文档。

## 删除门槛

- 每项公开能力或包装限制都有 shared kernel、DomainV1、product collector 或参数表 oracle。
- BoneSpring 产品/测试入口不导入 mixed runner、`MC2TaskSpec` 或 `MC2NativeContextV0`。
- Python 3.13 / Blender 5.2 的长程确定性、事务、debug-off 和限制输入隔离全部通过。
- 4.5/py311 只在旧面删除和 E7-S 基本完成后恢复做最终双 ABI 收尾。
