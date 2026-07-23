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
| Self collision | mode 强制为零；不建立 primitive/cache/radius self 合同 | 待补输入隔离与 debug 空状态签字 |
| Gravity、Motion/Backstop | 按 setup 合同关闭，不列为缺失能力 | 已有参数合同，待统一签字表核对 |
| Angle Restoration/Limit | 使用共享 kernel 和 BoneSpring 有效参数 | 已有 target/rest、边界与响应证据 |
| External collision | 只接受 Sphere，并消费 soft collision limit | 已有过滤、响应和确定性证据 |
| Rotation/writeback | 使用统一 Bone output 与事务 | 已有目标集合、多 request 和失败回滚证据 |

## 删除前剩余工作

1. 用公开 product request 同时改变 Bending/self/Motion/gravity 等被禁止输入，证明 compiled parameter、debug record 和轨迹都遵守固定包装合同。
2. 将旧 BoneSpring runner 中仍有价值的 topology/参数 helper 迁到产品测试公共模块；删除依赖 `native_context` 内部计数的断言。
3. 确认 capability matrix 不把被强制关闭的字段登记为待实现功能，也不以 BoneCloth self/Bending 证据代替 BoneSpring 限制证据。
4. 与 Mesh/BoneCloth 共用同一 E7-CPU 删除批次移除旧 owner、hidden task、普通 aggregate 和 V0 ABI；随后执行 E7-S 简化。

## 删除门槛

- 每项公开能力或包装限制都有 shared kernel、DomainV1、product collector 或参数表 oracle。
- BoneSpring 产品/测试入口不导入 mixed runner、`MC2TaskSpec` 或 `MC2NativeContextV0`。
- Python 3.13 / Blender 5.2 的长程确定性、事务、debug-off 和限制输入隔离全部通过。
- 4.5/py311 只在旧面删除和 E7-S 基本完成后恢复做最终双 ABI 收尾。
