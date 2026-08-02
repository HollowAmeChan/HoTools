# OmniNode 物理世界当前实现状态

本文只记录 Physics World 各 domain 当前成立的边界、主要缺口和全局优先级。公共结构规则见 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；solver 的详细产品、算法和后端设计由各自蓝本维护；历史过程只留 Git。

## 当前系统边界

```text
Cache Read
  -> Physics Object Scope
  -> Physics World Begin
  -> implicit object / explicit product build
  -> solver step(s)
  -> result stream / exchange
  -> Physics Writeback
  -> Physics Bake
  -> Physics World Commit
  -> Cache Write
```

- `PhysicsWorldCache` 统一持有 frame context、scope、collider snapshot、implicit object registry、solver slots、exchange、result streams 和 backend resources。
- solver 是 `physicsWorld/<domain>/` 下的可发现模块；私有 topology、backend context 和跨帧状态只存在于自己的 slot。
- solver step 发布 result/exchange，不直接写 Blender；Object、PoseBone 和 mesh offset 由公共 writeback 应用。
- Cache Delete、runtime cache clear、不兼容重编译和插件注销必须释放 world/slot/backend owner；solver 的模块级调试资源通过注册表声明的 world dispose hook 同步释放，公共 world 不点名具体 solver。兼容重编译按 solver 签名合同决定复用、热更新或 staged replacement。
- 显式产品域和通用 implicit object 是两种合法装配方式。一个 solver 选择其中一种后，不得在运行时混用两套字段解析。

## 当前目录与所有权

```text
physicsWorld/
  blender.py                 # 物理 RNA/UI 根生命周期
  blender_registry.py        # domain 注册、依赖与失败回滚
  registry.py                # component/solver 发现与装卸
  world_time.py              # Blender 输出帧率到公共秒数的唯一换算入口
  bake/                      # 通用 Bake 后端与 session
  collision/                 # Object/Bone collider 共享 capability
  field/                     # Volume、Wind、快照、native runtime、Empty创作、诊断与公共输入
  simple_cloth/              # 简单布料RNA、BasePose/Scene归属与独占GN输出owner
  spring_vrm/                # VRM SpringBone
  rigid/                     # Rigid/Jolt
  mc2/                       # 一个 solver，三种 setup
    setups/
      mesh_cloth/
      bone_cloth/
      bone_spring/
  mesh_xpbd/                 # 独立基础纯 Mesh XPBD
  ui/
```

| 稳定 Blender 路径 | owner |
|---|---|
| `Bone.hotools_collision` | `physicsWorld.collision` |
| `Object.hotools_object_collision` | `physicsWorld.collision` |
| `Object.hotools_mesh_collision` | `physicsWorld.simple_cloth` |
| `Object.hotools_field` | `physicsWorld.field` |
| `Object.hotools_rigid_body` | `physicsWorld.rigid` |
| `Object.hotools_rigid_constraint` | `physicsWorld.rigid` |
| `Scene.ho_*` 物理 UI 字段 | `physicsWorld.ui` |

属性 schema、PropertyGroup、binding 和注册权只存在于 Physics World。world cache 与 solver slot 不跨帧保存 live PropertyGroup。

## Domain 状态

| Domain | 当前状态 | 已成立边界 | 主要缺口/入口 |
|---|---|---|---|
| World core | 可用 | `fps/fps_base` 公共时间入口；raw/dt、timeline/sample/frame-step/substep 时间；Begin/Commit、component先于solver的scope collector、slot/resource/result/exchange、writeback、dispose、debug snapshot | 补齐全部 solver 的统一时间矩阵；为 seek/cache 冻结 sample time 恢复合同；建立真实跨 solver 交互闭环 |
| Physics Bake | Bone + PC2 Mesh + Clear vertical slice 可用 | 公共 Bake 节点、Action/PC2、manifest、播放和清理 | 见 `PHYSICS_BAKE_NODE_BLUEPRINT.md` |
| Collision | 可用 | Object/Bone schema、RNA、group mask、公共 snapshot 与 capability | 继续消除 solver 私有重复 resolver |
| Simple Cloth | 可用 | 公共RNA/capability、面板/自定义对象资源准备、按Scene独立HoPhysicsCache、Outliner可追踪且视口隐藏的BasePose、共享GN output；BasePose副本删除已知拓扑修改器并关闭Object级物理开关，保留纯形变与Geometry Nodes，GN若改变顶点数由final-proxy校验报错；MC2/XPBD step不创建Blender资源 | 继续把新增Mesh solver统一接到该对象边界，不复制资源生命周期 |
| Field | 公共 authoring/静态预览、native runtime 与 MC2 CPU 产品消费 active | 独立共享component；原生Empty启用工作流且作者侧有效源直接解析为`ACTIVE`，Field类型层V0仅Wind；Sphere中心到边界线性衰减、Box硬边界无内部衰减；Physics Object Scope有默认开启的场注册开关；World Begin自动修复可写重复UUID，并将 `FieldSnapshotV0` 编译为 `NativeFieldRuntimeV1`；删除/禁用/关闭注册提交零场runtime，身份暂存后规格解析不二次回读RNA ID且其余失效读取转为诊断，native registry以`shared_ptr`调用租约延迟析构，MC2 prepare只在调用内持有runtime lease并于step/cancel后清零身份handle；统一Wind+turbulence、标准 C++ evaluator、显式 participation、单调 handle 与 staged lifecycle；作者预览固定 `AUTHOR_STATIC/t=0`，运行态由“场-运行可视化调试”节点直接读 live runtime；MC2 三 setup 的 native Domain-owned 采样、600帧双轮确定性、开关 no-op、均匀响应、精确作用域及活动场删除后继续运行已验证 | `PREVIEW_ONLY`仅保留给程序化预览规格；Volume权重与参与权重是否拆分为连续权重、Scene单位换算、seek/cache sample time恢复仍未冻结；未来碰撞等运行态必须按专用调试节点合同补齐；见`PHYSICS_FIELD_VOLUME_BLUEPRINT.md` |
| SpringBone VRM | world-aware vertical slice 可用 | 隐式骨链、native context、slot、碰撞、result、PoseBone writeback、debug、dispose | 后续能力扩展和性能维护 |
| Rigid/Jolt | vertical slice 可用 | body/constraint、scope、result/writeback、query/event/debug、dispose、soak 与 golden | 统一零 dt 行为；Path 和高级 shape/query |
| MC2 | 三 setup 统一域 CPU 产品可用；公共 Field native 风产品链已接通；BoneCloth 阶段里程碑完成；E6 GPU 设计已立项 | MeshCloth 消费公共 simple_cloth 对象/BasePose/GN资源，solver step不创建Blender数据；三setup显式域分区；Domain 静态同步注册 partition consumer contexts，参数更新上传逐粒子响应，fixed 子步 Python 只传 runtime handle 与 World sample time，native 从 Domain-owned positions 调用标准 evaluator 并在 Center inertia 后、Integration 前应用；MC2只持有“响应场风”开关与0..20响应强度，旧七个wind参数、位置读回、Python sampler、逐粒子 packet ABI 已删除且无兼容；native evaluator 输出独立 participation；三setup公共Field风600帧产品矩阵已标记`verified`；终端粒子、双写回、DomainV1 mixed pass、whole-domain self、多目标事务、产品debug及Teleport/碰撞历史闭环；CPU是独立长期reference | native scratch/output 的容量、线程与 GPU staging 尚未冻结；连续 participation/weight、attenuation 权责、GPU入口见`MC2_GPU_BACKEND_DESIGN.md` |
| Mesh XPBD | World vertical slice、生产 soak 与旧路径删除审计通过，待冻结矩阵最终记录 | 面板/自定义对象适配器消费公共simple_cloth对象并在solver前准备GN资源；source Mesh topology/reference、累计 lambda nanobind context、四类公共 collider、slot/debug、事务化 GN result/writeback；可视化 draw store/handler 已接入注册表驱动的 world owner 销毁链，跳帧替换与 runtime clear 不留残影；时间矩阵、dirty、dispose 和 `OMNI测试.blend` 180 帧验收通过；旧双节点、私有 cache/writeback 与悬空 ABI 已移除；不建立无运行语义的融合域 | 记录最终 ABI/layout、能力矩阵与性能基线后冻结；见 `MESH_XPBD_BLUEPRINT.md` |

Field -> MC2 CPU 产品链当前为 active：World Begin 发布 `FieldSnapshotV0` 并编译 `NativeFieldRuntimeV1` 到 world cache；MC2 Domain 静态同步作用域上下文与响应，fixed substep 只传 `handle + sample_time_seconds`，native 以 `sample_time_seconds + frame_step_dt * update_index / update_count` 从 Domain-owned 当前粒子位置采样，作用域按 Object/Armature 名、Collection 名与公共碰撞组低 16 位执行，并在 Center inertia 后应用响应。独立 participation 区分未参与和精确抵消；旧七个 MC2 wind 参数、Python 位置读回、sampler、packet 和兼容数据均已删除。

Field/MC2 静态事务已经补强：consumer contexts 随 staged Domain 一起配置，上下文语义变化强制 replacement，配置失败保持旧 owner/slot/调度状态；evaluator 在整批结果有限且可由 `float32` 表示后才同时提交空气速度与 participation，失败时 MC2 sample buffer 继续无效。registry 已用 `shared_ptr` lease 保住在途调用，map 访问当前依赖 CPython GIL 串行；未来释放 GIL、native worker 或异步 GPU 前仍须增加经过 Blender 验收且不使用 MSVC `std::mutex` 的显式同步。

MC2 仍有独立于 Field 的低层事务缺口：live Domain 进入 mutating pass 后没有完整子步数值 rollback，后续 pass 异常时 scheduler 未提交不等于 native state 可原地重试。公开产品入口已经摘除并 dispose 本批 attempted slots、恢复 Bone feedback，后续调用冷建 owner；但低层 `step_mc2_product_substep()` 仍缺少失败状态与原地重试门禁，只有明确在 mutation 前失败才可安全重试。

运行态调试合同：只有明确请求的专用调试节点才可读取 live native 状态；当前“场-运行可视化调试”核对 World FrameContext、runtime inspect 与同签名 snapshot，关闭时不读 cache、不采样也不发布绘制批次，高级 scope 缺少消费上下文时只画边界。全局 draw handler 首次请求时懒注册，在 World Begin、store 替换和 world dispose 之间保持稳定并允许空 store 休眠，只在 load/unregister 的组件停机边界注销，避免可见 View3D 正在回调时移除句柄。Physics World 已增加统一宿主求值门禁：Field/MC2 adapter 在 `frame_change_post` 内复用 handler 传入的短生命周期 depsgraph，Simple Cloth/BasePose 校验及 Bone/Jolt restart 清理只读当前状态或打更新标签，不再重入 `rna_ViewLayer_update_tagged` 或 `Context.evaluated_depsgraph_get()`；4.5.8 下“播放中复制场、编译、删除复制对象”的 CDB 精确复现已通过。碰撞、接触和其它裸读能力未来必须各自提供同类专用节点，不能由作者预览、Blender RNA 或通用快照猜测。

## 当前优先级

1. Field 公共 authoring/preview、MC2 CPU 产品接入和三 setup 的600帧长期能力矩阵均已成立；当前只冻结 Volume 衰减与参与权重的后续权责，不再恢复旧 MC2 wind 参数。
2. MC2 E6 只允许新增独立 GPU backend。CPU DomainV1 的算法、状态、ABI、加载和性能是冻结基线，GPU 工作不能以任何理由造成 CPU 回归。
3. E6 先建立可选 provider、CPU-only 加载隔离和固定 fixture 闭环，再实现 whole-domain self 与完整 mixed pass；不能从产品节点直接开始拼 GPU 分支。
4. GPU 成功必须以产品整帧、上传/同步/readback、工作量等价、设备失败和规模曲线判断，不能只报告 kernel 时间。
5. Rigid/Jolt 优先清除私自 dt fallback，并继续补公共时间合同。
6. Bake 与 Field 继续保持公共 owner，不进入任一 solver 私有目录。
7. Mesh XPBD 已按 `MESH_XPBD_BLUEPRINT.md` 以独立 solver 重写；生产验收和旧路径删除审计完成，最终冻结前只保留合同矩阵与性能基线记录。

## 公共验收门槛

- 架构审计：依赖方向、私有边界、注册根、结果通道、backend owner 和 native binding 无未解释违规。
- 生命周期：创建、热更新、staged replacement、失败回滚、dispose、undo/load 和插件注销不泄漏资源。
- 事务：多个 solver/request/target 在 mutation 前完整验证，失败时零部分写回。
- Debug：关闭时无额外 record/readback；开启时只观察真实 production pass。
- Native：CPU-only 构建和加载不依赖任何可选 GPU runtime；双 ABI 按各 solver 阶段门槛验证。
- Blender：隔离默认备份模块，确认加载当前工作树源码和对应 native 产物。

## 文档维护

本文的 domain 行只回答“当前处于什么状态、缺什么、去哪里看”。单个 solver 的能力明细、fixture、实施批次、性能数字、删除清单和提交结果不得追加到本文。
