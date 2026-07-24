# OmniNode 物理世界当前实现状态

本文只记录 Physics World 各 domain **当前成立的边界、主要未完成项和全局优先级**。公共结构规则见 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；solver稳定事实由各自蓝本维护；历史过程由Git保存。

MC2专项入口：稳定产品/实现/维护合同见`MC2_BLUEPRINT.md`；当前阶段只看本文MC2 domain行。

## 写作边界

- **应该写**：各domain的一页式当前状态、已经成立的系统边界、主要未完成项和Physics World全局优先级。
- **不应该写**：单个solver的能力明细、数值公式、fixture清单、实施步骤、源码差异、调试过程或逐提交历史。
- **内容路由**：公共结构规则写`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；MC2稳定事实写`MC2_BLUEPRINT.md`；OmniNode编译/缓存框架写`../ARCHITECTURE.md`；历史只留Git。
- **摘要原则**：domain行只回答“处于什么阶段、主要缺什么、去哪里看”，不在表后追加solver专项补充段落。

## 当前系统边界

```text
Cache Read
  -> Physics Object Scope
  -> Physics World Begin
  -> implicit object / spec build
  -> solver step(s)
  -> result stream / exchange
  -> Physics Writeback
  -> Physics Bake
  -> Physics World Commit
  -> Cache Write
```

- `PhysicsWorldCache`统一持有frame context、scope、collider snapshot、implicit object registry、solver slots、exchange、result streams和backend resources。
- solver是`physicsWorld/<domain>/`下可发现模块；私有topology、native context和运行状态只存在于自己的slot。
- solver step发布result/exchange，不直接写Blender；Object、PoseBone和mesh offset由公共writeback应用。
- Cache Delete、runtime cache clear、不兼容成功重编译和插件注销必须释放world/slot/backend owner；兼容重编译保留world，并由solver签名合同处理热更新或slot重建。

## 当前目录与所有权

```text
physicsWorld/
  blender.py                 # 物理RNA/UI根生命周期
  blender_registry.py        # domain注册journal、依赖和失败回滚
  registry.py                # component/solver发现与装卸
  gn_offset.py               # 共享GN顶点最终offset
  bake/                      # 通用Bake后端与session协调
    session.py               # 路径、target UUID、原子manifest
    bones.py                 # 精确Bone result -> 专用Action
    pc2.py                   # 逐帧PC2 writer、manifest与Mesh Cache播放
    clear.py                 # 用户控制的Action/cache/live清理与baseline
  collision/                 # Object/Bone collider共享capability
  spring_vrm/                # VRM SpringBone
  rigid/                     # Rigid/Jolt
  mc2/                       # 一个solver，三种setup
    setups/
      mesh_cloth/
      bone_cloth/
      bone_spring/
  ui/
```

| 稳定Blender路径 | owner |
|---|---|
| `Bone.hotools_collision` | `physicsWorld.collision` |
| `Object.hotools_object_collision` | `physicsWorld.collision` |
| `Object.hotools_mesh_collision` | `physicsWorld.mc2.setups.mesh_cloth` |
| `Object.hotools_rigid_body` | `physicsWorld.rigid` |
| `Object.hotools_rigid_constraint` | `physicsWorld.rigid` |
| `Scene.ho_*`物理UI字段 | `physicsWorld.ui` |

属性schema、PropertyGroup、binding和注册权只存在于Physics World；UI消费capability/resolver。world cache与solver slot不跨帧保存live PropertyGroup。

## Domain 状态

| Domain | 当前状态 | 已成立边界 | 主要未完成项/入口 |
|---|---|---|---|
| World core | 可用 | Begin按Blender `fps/fps_base`统一生产raw_dt/dt；Begin/Commit、scope、slot/resource/result/exchange、channel registry、writeback、dispose、debug snapshot；共享GN ensure按builder结构contract判定代码差异，不只依赖整数schema，显式refresh可原位修复场景资源 | 统一时间验收矩阵仍需覆盖全部solver；跨solver交互仍需真实业务闭环 |
| Physics Bake | Bone + PC2 Mesh + Clear vertical slice可用 | `物理烘焙`与`清除物理Bake动画` OmniNode及“物理世界”正常添加菜单、world/目录/前缀同序直连、单条/batch Bone精确Action、源Action恢复、Bone首帧baseline回填、三类独立整数留存策略、真实GN writeback target逐帧PC2、每对象独立文件与并行IO、受管Mesh Cache开关、KEEP/精确truncate/delete、v2原子manifest、保存重开回放 | Bone component ownership、Object Action、Bake回绕暂停、Object/PC2 baseline、journal恢复、topology signature与多Mesh性能门槛；GN Bake经人工生产验收后已否决，总合同见`PHYSICS_BAKE_NODE_BLUEPRINT.md` |
| Collision | 可用 | Object/Bone schema、RNA、group mask、公共snapshot与capability | 继续消除solver私有重复resolver |
| 通用力场 | 未来兼容区 | ownership固定归Physics World；solver只消费公共数值快照 | channel/schema/采样布局和首个active vertical slice均未冻结 |
| SpringBone VRM | world-aware vertical slice完成 | 隐式骨链、native context、slot、碰撞、result、PoseBone writeback、debug、dispose | 后续能力扩展和性能维护 |
| Rigid/Jolt | vertical slice可用，P0门禁闭环 | body/constraint spec、resource、scope、result/writeback、query/event/debug、dispose、soak与golden | 清除`frame_context.dt <= 0`时私自回退`1/60`的时间合同偏差；Path及剩余高级shape/query |
| MC2 | 三种 setup 的统一域产品路径可用；E7-CPU 的 Python/native 旧面均已删除 | E0-E5-B、P0、P1-B、E4/P2 已闭环；`MC2ProductRequestV1`、DomainV1 whole-domain mixed pass、三 setup collector、多目标事务、产品 debug 和 Bone writeback 已成立；能力矩阵 9/9 verified；Python V0 owner、68 个 native V0 binding、5 个 context TU、2 个专用头文件及纯旧测试已删除 | 执行 E7-S、P6 合同收口和最终双 ABI 验收；全部门禁关闭后退役 BoneCloth/BoneSpring 过程计划文档 |
| Mesh XPBD | 旧路径 | 仅作简单布料参考 | 决定迁移或删除，不维持第二套布料语义 |

通用力场当前没有active能力。wind只是未来kind；MC2中的`wind_*`兼容字段不代表场输入、采样或native消费。

## 当前优先级

MC2 已完成 E7-CPU native 删除，当前进入 E7-S。统一 MC2ProductRequestV1、DomainV1 whole-domain 执行、三种 setup collector、事务写回和请求驱动调试已经成立；9 个能力族的产品数值门禁全部通过；旧 Python task/solver/context/interaction owner、native V0 ABI/TU/专用头文件与纯旧测试均已删除，剩余工作集中在删除后需要审查的兼容参数、结果翻译、资源键和迁移命名。

后续只按以下逻辑批次推进：

1. capability matrix 已不再引用旧 Mesh/Bone constraint runner；Mesh Bending、Angle Limit、Distance/Tether、Collider scope、Friction 和 whole-domain self 均由 Blender 5.2 产品 runner 提供真实数值响应。
2. BoneCloth/BoneSpring 的独立数值与包装限制前置签字已经关闭；topology/setup/frame 中立合同已经归入真实职责模块，旧 Python owner、hidden task、普通 aggregate 入口和兼容 runner 已删除。
3. 68 个 native V0 binding、5 个 `mc2_context_*` 翻译单元、2 个专用头文件、`mc2_api.hpp` 声明/CMake 残留和直接 V0 native tests 已删除；4 个 frame/static 中立 API 与 DomainV1 产品 ABI 已保留并通过 py313/Blender 5.2 验收。
4. E7-S 已把六个顶层 setup 产品钩子按真实 owner/lifecycle 归位为四个 setup 模块，生产模块由 72 个变为 70 个；文件数量不是 KPI，符合 Physics World 原子化标准的依赖根、合同、独立阶段和 owner 保持独立。
5. E7-S 已删除可选 `native_context` 参数，并把仅存于当前 world 内存的 Bone frame 与 hotspot timing `v0` 资源键改为职责名且不保留兼容读取；继续逐项清理双 schema/result 翻译、无调用 forwarder 和误导命名，途中只按真实依赖证据新增合并项。
6. `mc2_bone_writeback_plan_v0` 经审计是公共 Bone result/writeback 边界的唯一活动 schema，不是兼容层；保留其版本身份。产品多 request 失败回滚改为调用 Bone frame owner 的 checkpoint，不再跨模块读写 setup 私有资源键。
7. 首次后续依赖审计已删除无调用方的 Mesh 旧 `static_build.py` owner 与两个 task frame adapter，生产模块当前为 69 个。
8. 第二次后续依赖审计已删除旧 debug slot/interaction 聚合器、`mc2_interaction_v0` resource key 与 renderer 兼容分支；产品 debug 只消费 fused product snapshot。
9. 第三次后续依赖审计已删除旧 result candidate、单目标 result、stats aggregate/schema 与无 producer 的 MC2 stats channel；公共事务只发布 GN 与 Bone shared product results。
10. 第四次后续依赖审计已删除四个约束 static builder 与 Bone 产品静态装配器的 staged metadata、compact 转换和对应可选 `native_context` 参数；剩余 Mesh proxy/baseline 与 Bone native-owned 壳继续独立审计。
11. E7-S 按职责与调用图审计、单批所有权变更、架构门禁、产品验收和独立提交循环推进；允许途中发现新的合并点，但不合并符合 Physics World 原子化标准的独立合同、阶段、owner 或边界模块。
12. 第五次后续依赖审计已删除剩余 native-owned proxy/finalizer/baseline/Bone DTO、registration capsule、`native_owner_kind` 与生产侧全部 `native_context` 参数；native 中立派生 API 与完整 static spec 合同继续保留。
13. 产品 slot 已删除仅供旧测试使用的 Mesh fused 默认 slot wrapper；统一 sync/frame/substep/capture 入口只接受显式产品 slot identity，Mesh output batch/transaction 的准确命名继续单独收敛。
14. Mesh output batch/transaction 与 Python slot 常量已完成 `mesh_product` 命名收敛；底层 slot identity、事务、执行顺序和数值 digest 保持不变。
15. 当前运行参数产品类型已统一为 `MC2RuntimeParameters`；packed ABI 0、字段布局和签名不变，旧 `MC2RuntimeParametersV0` 不保留兼容别名。
16. compiled-domain 已删除四个 E1 单 partition compatibility/shadow 属性，只保留多 partition 的真实 fragment 与参数签名集合。
17. 12 个 static/frame 中立 native helper 已去除版本后缀并重新编译 py313 pyd；旧符号为 0、新符号完整，正式 DomainV1 ABI 版本名不变。
18. 三份 Bone compatibility runner 已删除，验收资产直接指向真实产品 runner，并通过 Bone 产品集成、BoneSpring 599 帧限制与 BoneCloth 900 帧约束 soak。
19. 两份 Mesh final-proxy/BasePose 门面和一份 mixed-output/Center 串行门面也已删除；6 个旧 runner 由不存在性门禁禁止回流，验收资产直接指向真实产品 runner。
20. P6 只冻结 backend-neutral data/pass/buffer/IO 合同。不实施 P4 CPU 并发，不实现 E6 GPU，不允许为未来 GPU 引入无法解释的 CPU 回归。
21. 旧代码删除、E7-S 和 P6 合同复核完成后，才恢复 Python 3.11 / Blender 4.5 做最终双 ABI 与 Blender 收尾验收。

当前开发和常规验收只使用 Python 3.13 / Blender 5.2，并确认实际工作树源码与 _Lib/py313 native 产物一致。4.5/py311 在旧代码删除收尾前保持冻结。

## 公共验收门槛

- 架构审计：依赖环、私有边界、产品/公开节点/调试旧模块可达性和 native binding 合同均无未解释违规。
- 纯 Python：DomainV1、共享 kernel、product collector、事务写回和能力矩阵的独立断言通过。
- Blender 5.2：--factory-startup 产品节点、三 setup、多 source whole-domain、multi-target rollback、debug snapshot 和 600/900 帧确定性通过。
- 删除阶段：旧 Python/native 面完全不可达后，才运行最终 4.5/py311 双 ABI；P6 只验合同，不以 GPU 实现作为本阶段验收项。

## 文档维护规则

本文只保留稳定边界、当前缺口和全局优先级。单次提交、单次 runner、临时性能数字和调试过程只留在 Git、测试输出或 benchmark 结果中；MC2 详细合同和删除清单统一维护在 MC2_BLUEPRINT.md。
