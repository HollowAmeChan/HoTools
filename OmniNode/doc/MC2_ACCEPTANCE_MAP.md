# MC2 验收总表

更新日期：2026-07-17

基线：MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

本文是新 `physicsWorld.mc2` 的**完成度与验收结论单一事实源**。它按可交付能力切片，不按源码文件或提交记录展开。未完成工作顺序见 `MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`，源码 producer/consumer、边界特化与 oracle 细节见 `MC2_SOURCE_DATAFLOW_WORKSHEETS.md`。

## 写作边界

- **应该写**：每个能力切片的当前结论、支持域、已有证据、剩余差异、是否阻塞V1-R，以及结论变更日期。
- **不应该写**：实现过程、下一步操作细节、公式/源码逐行语义、踩坑展开、公共Physics World架构或提交历史。
- **内容路由**：未完成工作的顺序与退出条件写`MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`；源码事实、特化、故意差异和冲突处理写`MC2_SOURCE_DATAFLOW_WORKSHEETS.md`；跨solver公共规则写`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；历史过程只留Git。
- **更新原则**：只有代码和相应层级证据已经成立，才能更新本文结论；不能把计划、推测或邻近能力写成完成事实。

## 验收范围

当前目标是 `V1-R`（restricted realtime）：单一 MC2 solver、MeshCloth/BoneCloth/BoneSpring 三种 setup、单 final-proxy Mesh、MC2 source Bone Line与HoTools ordered-chain BoneCloth产品拓扑、外部 Point/Edge collider、单 cloth self collision、实时 Mesh/Bone writeback。

以下不阻塞 `V1-R`：Bake、通用力场、Bone imported triangle、MC2 reduction/render mapping。它们必须保持明确的未支持状态，不能由现有能力外推为已完成。跨物体self collision已进入产品替代范围，由K-06阻塞删除准入。

上述source范围不等于旧HoTools产品替代范围。删除旧实现还必须通过P-04..P-08；旧实现中实际可用但超出当前source restricted范围的能力，只有在明确产品决策、可见拒绝行为和迁移说明成立后，才允许作为故意缩域处理。

## 状态口径

| 状态 | 含义 |
|---|---|
| `完全对齐` | 声明域内已有直接 Tier A 证据，且 Host、native、Blender 生产链全部闭环。 |
| `限定域对齐` | 明确限制输入域后满足“完全对齐”；限制外不宣称支持。 |
| `实现完成/证据缺口` | 生产链已接通，但缺独立 Tier A 或仍有源码语义待核账。 |
| `产品收尾` | 数值能力已具备，尚缺真实资产、稳定性、性能或旧路径清理验收。 |
| `待审计` | 已有实现或局部证据，但尚未完成产品语义、生产可达性、性能或独立性核账，不能据此宣称可替代旧实现。 |
| `未来扩展` | 不在 `V1-R` 范围，当前必须保持 inactive。 |
| `拒绝` | 已知输入域不成立，在进入 native 前显式报错。 |

“完全对齐”只描述表中写明的范围，不表示完整复制 Unity object、job、render mapping 或 editor 层。

## 总览

| ID | 能力切片 | 当前结论 | 已有证据 | 剩余差异/退出条件 | 阻塞 V1-R |
|---|---|---|---|---|---|
| C-01 | 单solver step / 多task / task-owned context | 完全对齐 | task规整去重、全量只读prepare、一次world写事务、per-task slot/context、staged replace、dispose/soak | MC2 component映射为profile+task组合；一次step处理全部active tasks，各task状态隔离且任一prepare失败不产生半更新 | 否 |
| C-02 | 帧生命周期、same-frame、reset、失败回滚 | 完全对齐 | py313 lifecycle + Blender 5.1 首帧/连续帧/倒放/重建 | 无 | 否 |
| C-03 | scheduler、多子步、一次提交 | 完全对齐 | Tier A scheduler + py313 + Blender 5.1 单/三子步 | 无 | 否 |
| C-04 | N2 参数 ABI 与热更新 | 限定域对齐 | 两组 Tier A 参数 dump、slot 热更新 | wind 与 sync 字段仅兼容占位，不计 active 能力 | 否 |
| C-05 | Center/Inertia、anchor、teleport、signed component | 限定域对齐 | Tier A Center/step fixtures + py313 + Blender 5.1 | 仅支持已声明的无 shear、非零 scale 域 | 否 |
| S-01 | Mesh final proxy、UV/Pin、拓扑签名 | 限定域对齐 | Tier A static fixtures + staged native upload + Blender 5.1 | 单 final proxy；UV seam 与拓扑变化按契约拒绝/重建 | 否 |
| S-02 | Mesh baseline 与双对象 BasePose | 限定域对齐 | Tier A baseline/rotation + py313 + Blender 5.1 GN链 | 每 vertex 属于 triangle；禁止反馈与改拓扑 modifier | 否 |
| S-03 | Bone connection 与产品拓扑 | 限定域对齐 | 8组Tier A source connection + HoTools链序/成环/拒绝fixture + Blender 5.1多链static/native/atomic writeback | `mc2_source`保持Line/imported-triangle拒绝域；`hotools_product`支持按名称/链组/节点顺序的纵横连接与稳定UV triangle；viewport显示由D-01跟踪 | 否 |
| S-04 | BoneCloth Line 与 BoneSpring setup | 限定域对齐 | shared static/native/result 链、N2 override、Blender 5.1 | BoneSpring 固定 Line、Sphere-only；不扩张到 triangle | 否 |
| S-05 | Bone imported triangle | 拒绝 | 固定源码证明全零 UV 导致 tangent/basis 退化 | 未来若改变产品策略，必须先建立真实 producer/oracle | 否 |
| N-01 | prediction、Pin、constraint 顺序与 post | 完全对齐 | Tier A 双子步顺序 + native V0 + Blender 5.1 | 无 | 否 |
| N-02 | Tether | 完全对齐 | 直接Tier A runtime + py313 native + Blender 5.1 production solve | stretch/compression、Fixed/missing-root gate与velocity-reference attenuation均闭环 | 否 |
| N-03 | Distance | 完全对齐 | 7组static、2组ordered runtime、Tier A双子步frame与native双阶段执行 | correction按0.3 attenuation进入velocity-reference，post消费并跨子步提交 | 否 |
| N-04 | Angle | 完全对齐 | 直接Tier A runtime + py313 native/V0 + Blender 5.1 Mesh/Bone solve | 双baseline、Fixed root、Restoration+Limit、falloff/attenuation与scratch clear均闭环 | 否 |
| N-05 | Triangle Bending | 完全对齐 | 3组 Tier A runtime + static role/order + native fixed-point sum | 无 | 否 |
| N-06 | Motion | 完全对齐 | 直接Tier A runtime + py313 native/V0 + Blender 5.1 Fixed Mesh | MaxDistance、Backstop、depth²采样、rotated axis、Fixed/InvalidMotion与0.95 attenuation闭环 | 否 |
| K-01 | 外部 Point/Edge collider | 限定域对齐 | py313 四 primitive/数值 + Blender 5.1 Mesh/Bone | 当前声明域不含完整 Unity collider component lifecycle | 否 |
| K-02 | BoneSpring soft sphere | 限定域对齐 | py313 数值 + Blender 5.1 production | 只接受 Sphere 与 spring 专用 limit 语义 | 否 |
| K-03 | Self primitive/grid/hash/broadphase | 限定域对齐 | raw/Tier A static + py313 hash/candidate + Blender 5.1 | 单 cloth FullMesh 域 | 否 |
| K-04 | Self EE/PT contact、4轮 solve/sum | 限定域对齐 | half contact、手算 fixed-point、后续 substep fixtures | 单 cloth FullMesh 域 | 否 |
| K-05 | Self 跨帧 Intersect | 限定域对齐 | py313 三帧反馈 + Blender 5.1 final-substep gate | 单 cloth、固定分片调度 | 否 |
| K-06 | 跨物体self collision scope | 完全对齐 | 单一solver step先同步全部active task slot，再由world-owned interaction context锁步执行跨owner grid/broadphase、EE/PT、4轮solve与跨帧intersect；Blender raw/生产验收覆盖自动scope、group/mask、动态增删和dispose | 产品节点只暴露开关；零mask自动全互碰，非零mask双方握手分区，不暴露ListObj。4 cloth自动与显式all-pairs有相同14607峰值candidate/14223 contact，自动mean 0.675ms且无Python partner resolver | 否 |
| K-07 | 普通碰撞半径与self thickness产品模型 | 完全对齐 | source模式保留独立thickness oracle；公开Mesh产品移除第二厚度/曲线输入，固定从唯一`radius × 顶点组`派生`radius * 0.25` | 3606 primitive双层grid中派生0.005与source候选/接触完全相同且约1.1..1.3ms；直接复用0.02 radius约24.1..24.3ms。外部collider不能覆盖EE/PT/intersect，因此不替代self primitive | 否 |
| O-01 | Mesh result transaction 与 GN writeback | 完全对齐 | candidate/envelope、发布回滚、拓扑失败恢复、Blender 5.1 | 无 | 否 |
| O-02 | Bone result transaction 与 PoseBone writeback | 限定域对齐 | stable identity、parent-local plan、批次回滚、signed component及同Armature多component合并 Blender 5.1 | component骨名必须不重叠；同目标按全部target pose重算parent-local plan并一次写回 | 否 |
| O-03 | `mc2_stats_v0` | 完全对齐 | schema、聚合、稳定排序、事务回滚 | stats 不得替代真实 writeback ready 语义 | 否 |
| D-01 | 全隐式中间态debug | 完全对齐 | `physicsMC2DebugDraw`自动发现world内MC2 slots；请求仅在下一真实native advance冻结slot/context与world interaction中间态，renderer只消费只读快照；Blender 5.1验收覆盖零readback、same-frame保留请求、Bone纵横连接、Motion、Keep Teleport、负缩放、外部碰撞、自碰全阶段、RNA隔离和dispose | 语义层覆盖Topology/Fixed-Move/Motion/Center/Collision/Self/Output；无中间态socket，无请求时`debug_readback_count=0` | 否 |
| P-01 | V1-R 直接 oracle 闭环 | 完全对齐 | static/runtime主体及Distance/Tether/Angle/Motion direct runtime均有Tier A | 无 | 否 |
| P-02 | 真实生产资产验收 | 完全对齐 | V1-R结构化manifest + Blender 5.1七脚本门禁，覆盖八资产/三setup | Mesh、跨物体self、全隐式debug、Bone source Line、BoneCloth产品链、BoneSpring soft sphere及final-proxy/component拒绝域均可重复执行 | 否 |
| P-03 | 新链路混合 soak 与绝对性能门禁 | 完全对齐 | Blender 5.1三setup混合180帧：2次hot update/rebuild/reset/same-frame、6 context释放 | 170样本mean 4.44ms、p95 5.02ms、max 6.43ms；这里只证明新链路稳定且低于自身ceiling，不代表优于旧实现 | 否 |
| P-04 | 旧产品语义与新实现替代审计 | 完全对齐 | profile+task component、全量prepare/失败原子性、per-task context、HoTools链组产品拓扑、同Armature多component合并写回及Blender 5.1生产fixture | 跨物体self collision与半径模型分别由K-06/K-07决策；隐式可视化由D-01关闭，不再回退产品语义 | 否 |
| P-05 | 新实现生产可达性、代码与math审计 | 完全对齐 | 三setup与world common runtime生产矩阵覆盖static/frame/state/error/dispose/result；八资产/三setup Blender生产门禁、混合soak与Tier A证明真实入口；math旧名aliases及无职责Mesh final-proxy包装已删除 | `profile + task`是slot/context component；`bone_rotation.py`明确为测试oracle且不是fallback；保留wrapper均拥有setup、Blender snapshot、cache、校验或事务职责 | 否 |
| P-06 | 新旧性能对比与C++边界审计 | 完全对齐 | large Mesh/Bone热帧约`5.47/6.06ms`，旧CPP约`7.03/19.33ms`；首构约`20.16/18.01ms`，快`31.72x/19.20x`；180帧混合soak mean/p95/max约`2.94/3.56/4.01ms`。逐帧与static热点的派生/消费均归native，平行host particle shadow和完整static上传fallback已删除 | Blender raw snapshot保留为任意authoring变化检测边界；config只重建Center，topology/geometry/Pin按依赖矩阵全量重建，UV-only保守全量重签是非阻塞优化 | 否 |
| P-07 | 文件与ABI独立化 | 完全对齐 | 共享数值代码归入`mc2_kernels.cpp/.hpp`；旧full-array solve、旧context、旧BoneCloth IO和全部11个旧ABI已物理删除，构建系统不再存在legacy选项 | 保持`mc2_kernels`、V0/static/self为新Physics World唯一native实现，不得恢复兼容导出 | 否 |
| P-08 | 替代资格总门禁 | 完全对齐 | P-01..P-07、K-06/K-07与D-01全部关闭；8资产/7脚本复验、180帧soak、新旧同场benchmark及OFF独立构建通过 | 产品语义可替代、自动交互与单半径模型清晰、全隐式debug可观测、新链性能有优势且文件/ABI可独立；明确允许进入P-09删除 | 否 |
| P-09 | 旧 MC2 路径删除 | 已关闭 | 旧Mesh/Bone节点package、`mc2_context.*`、`mc2_bonecloth_io.cpp`、legacy binding/测试及旧替代benchmark已删除；共享kernel和新V0/static/self保留。11份官方MC2 JSON预设迁入新粒子配置节点，且不恢复第二套self厚度输入 | 负向搜索保持旧package、构建选项和11个旧ABI为零 | 否 |
| P-10 | 删除后正确性基线 | 已关闭 | `311 native`与`313 native`均只增量构建`hotools_native`且无Jolt；18/18 native/raw、26/26纯MC2、Blender 4.5属性契约9/9、5.1代表资产8项/7脚本及180帧soak通过。无UV fingerprint、geometry/topology分类和unresolved source边界已由测试冻结 | P-11重组不得依赖已删测试、ABI或package | 否 |
| P-11 | 代码事实与职责审计 | 已关闭 | AST/include审计固定45个生产Python模块约16.8k行、1个16模块依赖环、5个private import、106+11项lazy re-export及确认的math/signature/delta转发；C++ 5单元约14.7k行，通用shell 89 binding、context 50个Python入口。逐文件/translation-unit职责表和声明→owner→测试矩阵已写入worksheet | P-12按表逐项消除barrel/private/重复helper并重组Python；P-13拆binding/context且不改变数值 | 否 |
| P-12 | Python模块重组 | 已关闭 | 删除117项无消费者lazy export、private helper访问和无职责forwarder；setup builder改为稳定标识，native loader/context分层，candidate并入results，slot state并入frame owner | 生产44模块约16.6k行，审计为0 import环/0 private import/0 re-export桶/0 legacy命中；3.11纯MC2、raw owner及Blender 4.5 Mesh/Bone/interaction/debug/属性/生命周期通过 | 否 |
| P-13 | C++原子化与文件重组 | 已关闭 | 通用module shell、MC2 binding、ABI声明、context core/lifecycle、static、frame-step、interaction、readback、fingerprint、static producer与数值kernel均有唯一translation-unit owner；纯internal state不含Python对象或shadow，native中间态保持自产自用 | Python 3.11 native-only增量构建只生成`hotools_native`且无Jolt；native `26/26`及Blender 4.5 Mesh `7/7`、Bone frame、负缩放component、跨物体interaction 5项通过 | 否 |
| P-14 | 依赖与洁净度终审 | 已关闭 | 可重复审计固定0 import环/private import/lazy re-export/未分类转发/生产测试反向依赖/raw readback越界/持久ndarray state shadow/legacy命中；47个context API单一定义，74注册/59生产要求符号无缺失重复，纯native owner零Python依赖 | native上传、生命周期、result publish、多任务准备和Bone writeback失败事务均有专项回滚测试；3.11 native `26/26`及Blender 4.5交互5项、Bone多任务原子步通过 | 否 |
| P-15 | MC2稳定蓝本合一 | 执行中 | 当前验收表、执行计划、worksheet仍含迁移流水 | 仿照`SPRINGBONE_VRM_BLUEPRINT.md`生成单一`MC2_BLUEPRINT.md`，只保留当前事实、职责表、产品决策、数据流、性能边界与扩展检查表；删除三份专项迁移文档并更新全部路由 | 是 |
| P-16 | 热点性能与维护态总门禁 | 待执行 | P-06只有替代期总体benchmark | 增加可重复热点测试，分别覆盖raw snapshot/fingerprint、static cold/change rebuild、frame prepare、all-task group step、result/writeback、debug request；固定环境/资产/粗粒度阈值。事实复核通过后才将`solver_acceptance_blocker=False` | 是 |
| X-01 | Bake/export | 未来扩展 | `supports_bake=False` | 独立冻结 bake 时间轴、缓存与导出契约 | 否 |
| X-02 | 通用力场（含 wind） | 未来扩展 | N2 仅保留兼容字段 | 等待 Physics World 公共力场快照，再接 adapter/native/oracle | 否 |

### P-06d 阶段证据

Bone生产prepare已建立短生命周期`MC2BoneRawSnapshot`，fingerprint、Line/product connection和Bone static共享names/parents/head-tail/rest matrices；同一task内的相同Armature只遍历一次name/parent，并用Blender `foreach_get`一次读取head/tail/matrix后按source稳定骨名切片。`matrix_local`的Blender列主序展平在snapshot边界固定转置，显式oracle与compact生产signature一致。生产Topology只保留`bone_names`与轻量身份，不再二次读取RNA、冻结每骨dict或在static/frame路径`_thaw`。26/26纯MC2与Blender Bone static/product/frame通过。large Bone外层首建约`99.0ms`，profile step约`12.1ms`，snapshot约`2.04ms`，frame input约`2.85ms`，逐帧均值约`6.50ms`且为旧CPP的`3.10x`；Python分配峰值约531KB，slot常驻NumPy仍约43KB。P-06d仍未关闭；下一步将Bone orientation/transform、Distance、Center和Self直接收入native staged context。

Bone rest matrix的正交化、transform quaternion、local normal和local tangent已由`mc2_build_bone_rest_frames_v0` bulk kernel唯一生产，finalized orientation到vertex-to-transform rotation也已由`mc2_build_bone_vertex_to_transform_rotations_v0`批量生产；Python逐骨matrix/quaternion/rotate/multiply转发已从生产static builder删除。Tier A、Blender Bone static/product和26/26纯MC2通过。large Bone首建本轮约`100.4ms`，与bulk snapshot后基线同档，这两步为职责迁移而非性能关闭证据。native验证使用`build.bat 313 native`，只增量编译/链接`hotools_native`，无Jolt target且无clean。P-06d剩余Bone registration owner、Distance、Center、Self的staged owner收口。

Bone children ranges/data与transform baseline flags/ranges/data已由`mc2_build_bone_transform_baseline_derived_v0`按source顺序的native DFS唯一生产，Python `_source_children/_dense_ranges/_flatten/_build_transform_baselines`已删除。Tier A fixed-prefix/line-chain/normal-adjustment、product topology和Blender static/rebuild/writeback通过。large Bone首建约`78.8ms`，为旧CPP的`4.34x`；逐帧均值约`6.34ms`，为旧CPP的`3.23x`。P-06d下一步将pose-depth合并到同一Bone producer并产出可直接move的Baseline/registration owner，再收口Distance/Center/Self。

Bone pose-depth已合并进同一transform-baseline producer，一次产出final attributes/root/depth/local pose与children/baseline数组；生产路径返回10个受限命名owner capsules，Proxy注册后Baseline vectors直接move进context。`owned_static_take_count=1`且消费后slot registration为空由Blender static/rebuild固定。large Bone首建约`75.9ms`，为旧CPP的`4.59x`。当前slot仍保留完整Bone tuple spec，因此P-06d下一步先压缩Proxy/Finalizer/Baseline/Bone metadata，再让Distance/Center/Self同批消费transient native arrays。

Bone native注册成功后，生产slot现已把完整`MC2BoneClothStaticBuildResult`压缩为`MC2BoneClothStaticMetadata`：仅保留稳定bone identities、Proxy attributes/edges/triangles、Baseline debug depths、各阶段count/signature和产品连接模式；rest pose、Finalizer adjacency/bind、Baseline parent/child/local-pose、Bone rotation arrays以及Distance/Center/Self明细不再常驻。结果写回直接读取`final_proxy.vertex_identities`，不再通过`bone.proxy`间接依赖完整spec。26/26纯MC2、Blender Bone static/product/frame及全隐式debug通过；large Bone首建约`74.96ms`，为旧CPP的`4.54x`，热帧约`6.13ms`，为旧CPP的`3.15x`。`host_numpy_bytes`约`72.9KB`包含此前tuple口径未统计的必要debug ndarray，不能与旧约43KB直接解释为总host内存增长。P-06d仍未关闭：Distance/Center/Self当前仍以transient完整spec构造并上传，下一步必须改成同批native owner消费。

Bone staged初始化现已拆为`Proxy/Baseline -> Distance/Center/Self -> Bone registration`：Proxy/Baseline就绪后，Distance、Center与Self producer直接把9组受限owner vectors move进同一context，不再构造或通过packer上传完整constraint spec；`owned_static_take_count=4`固定Baseline及三类constraint各一次真实接管，生产metadata没有`distance_targets/fixed_indices/primitive_flags`。Center staged分支也不再先tuple化native输出，Self depth不再tuple往返。26/26纯MC2、Blender Bone static/product/frame/全隐式debug通过；large Bone首建约`65.89ms`，为旧CPP的`5.18x`，热帧约`6.11ms`，为旧CPP的`3.25x`。P-06d剩余主边界为Bone registration的8组数组仍由Python最小packer构造后上传。

Bone Final Proxy producer现按owner mode直接产出Proxy 7组vectors与Finalizer registration 6组vectors，Bone rotation producer再产出adjustment/vertex-to-transform 2组vectors；context分别一次接管Proxy和Bone registration，使`owned_static_take_count=6`。Python `update_bone_static`已删除缺owner时的packer/copy fallback，缺任何Proxy/Baseline/Bone owner直接失败；完整`pack_mc2_bone_registration_static`只保留Tier A/oracle。native使用`build.bat 313 native`增量编译，仅构建`hotools_native`且无clean/Jolt target。raw native Bone ABI、26/26纯MC2、Blender Mesh BasePose/Bone static/product/全隐式debug通过。large Bone首建约`65.12ms`，为旧CPP的`5.25x`；热帧本轮约`6.60ms`，仍为旧CPP的`2.95x`。P-06d仍未关闭：同次prepare还构造完整Proxy/Finalizer/Baseline/Bone tuple spec作为transient，下一步应建立staged Bone native data并删除这棵生产派生树，而非继续增加转发。

Finalizer、Baseline与Bone static签名已从`json.dumps`完整tuple payload改为固定标签、稳定字段顺序、固定dtype连续字节的流式SHA-256；Mesh staged/no-context与Bone显式/生产共用同一签名函数，旧JSON签名树和私有重复helper已删除。26/26纯MC2、Blender Mesh BasePose/Bone static/product通过。large Bone首建约`59.27ms`，为旧CPP的`5.81x`；热帧约`6.12ms`，为旧CPP的`3.16x`。这一步解除staged ndarray载体必须重建tuple树才能维持signature一致的阻塞；P-06d下一步删除生产完整spec构造。

Bone staged构建现返回`MC2BoneNativeData`，内部直接复用`MC2MeshProxyNativeData`、`MC2MeshFinalizerNativeData`与`MC2MeshBaselineNativeData`连续数组；完整`MC2ProxyStaticSpec/MC2ProxyFinalizerStaticSpec/MC2BaselineStaticSpec/MC2BoneStaticSpec`仅在无context Tier A/oracle构造。Finalizer/Baseline/Bone签名直接消费这些arrays，constraint producer同次消费后context接管owner，slot再压缩为metadata，不再建立生产immutable派生树。26/26纯MC2、Blender Bone static/product/frame/全隐式debug通过。large Bone首建约`21.05ms`，为旧CPP的`16.17x`；热帧约`6.25ms`，为旧CPP的`3.10x`。P-06d剩余清理项是static assembly的transform/UV/position小型list/tuple转发与生产可达性复查。

P-06d已关闭：Bone static assembly直接拼接snapshot的positions/matrices/parents，rest kernel输出直接进入native data，Fixed/Move、roots与产品UV保持数组，不再逐骨append transform/normal/tangent tuple；staged入口强制要求共享raw snapshots，缺失即失败，不能落入`_flatten_bone_records`或完整spec分支。生产可达性搜索确认完整spec构造、packer与冻结payload仅属于无context oracle。26/26纯MC2、Blender Bone static/product/frame通过；large Bone首建约`18.06ms`，为旧CPP的`18.97x`；热帧约`6.15ms`，为旧CPP的`3.14x`。下一阶段进入P-06e变化重建收口。

P-06e第一子项已完成：Bone `config=8`不再运行完整static builder。新staged context从旧context复制Proxy/Baseline/Bone/Distance/Bending/Self六类static，在native内只重建Center并生成与现有oracle完全一致的SHA-256；Python只接收fixed count/signature metadata。Blender cold/incremental Center及整体static signature一致，计数固定为`static_clone_count=6 / center_static_rebuild_count=1 / owned_static_take_count=0`。small/medium/large config重建约`1.75/2.99/6.20ms`，相对进入基线`2.09/5.14/12.24ms`；P-06e仍需Mesh config及geometry/surface/topology复用矩阵。

P-06e config分类已闭环：同一native API现支持Mesh/Bone，Mesh复制Proxy/Baseline/Distance/Bending/Self五类static并复用frame producer bind rotations重建Center；cold/incremental `debug_dict`一致，计数固定为`clone=5 / center rebuild=1 / owner take=0`。small/medium/large Mesh config约`1.57/2.56/5.08ms`，large相对同轮surface全量重建`20.96ms`快约`4.12x`。下一子项是geometry/surface/topology受影响producer矩阵。

P-06e已关闭：依赖矩阵确认topology改变邻接/primitive/identity，geometry改变全部rest/orientation/constraint输入，Pin改变Fixed/Move并传播到全部相关producer，均不能复用完整static类别；Bone surface恒定。UV-only数值约束不变，但七类metadata通过Proxy signature保持身份一致性，现阶段保守全量重签/重建；large实测约`20.50ms`，与Pin `20.50ms`相同，仍比旧CPP `657.63ms`快约`32x`。新增UV子指纹/重签ABI属于非阻塞优化，不作为旧solver删除门槛。下一阶段P-06f总体性能与生产边界审计。

P-06f代码边界清理第一项完成：调用图确认`MC2InitialStateSpec`、`MC2ParticleBuffer`、`sync_mc2_frame_input`及setup `initial_state_builder`已不被生产solver使用，且与native context重复持有完整particle history。该平行状态链、lazy exports、declaration/capability伪字段与过时测试已删除；`MC2FrameInputSpec`、只读`plan_mc2_frame_sync`和轻量`MC2SlotRuntimeState`保留。26/26纯MC2及Blender Mesh/Bone static/BasePose/product/全隐式debug通过。

P-06f代码边界清理第二项完成：`MC2NativeContextV0.update_mesh_static`、Proxy/Baseline完整spec上传、Mesh frame spec repack与Bone Distance/Center/Self fallback已删除。交互测试及self radius/scope benchmark改为与生产相同的“先建staged context、builder直接owner-move”路径；Bone registration现在缺任何staged metadata立即失败。生产`native.py`除小型runtime parameter block外不再import static packer。Blender交互、自碰半径、scope与Bone static门禁通过。

P-06最终结论（取代上方汇总表中P-06的“待审计”历史状态）：P-06a..P-06f全部关闭。最终large Mesh/Bone热帧约`5.47/6.06ms`，旧CPP约`7.03/19.33ms`；首构约`20.16/18.01ms`，分别快`31.72x/19.20x`；Mesh Pin/UV重建约`20.64/20.31ms`，Bone rest约`18.43ms`，Mesh/Bone config约`5.00/6.25ms`。180帧三setup混合soak mean/p95/max约`2.94/3.56/4.01ms`，2次hot update/rebuild/reset/same-frame与6次context释放通过。生产对旧Python package零依赖、无host particle shadow、无完整static pack fallback；Blender raw snapshot是必须的authoring检测边界，其派生和消费均归native。下一阶段P-07文件/ABI独立化。

P-07已关闭：旧文件名`mc2.cpp/hotools_mc2.hpp`已改为新owner名`mc2_kernels.cpp/.hpp`；旧数组solve、旧context与旧BoneCloth IO统一受`HOTOOLS_ENABLE_LEGACY_MC2`控制。`OFF`独立模块仍具备全部新`_REQUIRED_SYMBOLS`，raw V0/static及26/26纯MC2通过，且不导出`create_meshcloth_mc2_context`、两类旧context solve、旧数组solve或旧BoneCloth IO。P-09删除候选与必须保留的共享kernel边界已可机械核验，下一阶段进入P-08替代资格总门禁。

P-08已放行：Blender 5.1按manifest重跑7/7生产脚本并覆盖8个验收资产；180帧三setup混合soak mean/p95/max为`2.738/3.110/3.460ms`，2次hot update/rebuild/reset/same-frame与6次context释放通过。同轮large Mesh/Bone热帧约`5.386/6.086ms`，旧CPP约`6.976/19.215ms`，快`1.30x/3.16x`；首构约`19.749/17.865ms`，快`32.30x/19.24x`。Bone产品横向连接、跨物体自动self scope、单一派生self厚度、全隐式debug、统一all-task step、C++自产自用及文件/ABI独立边界均无开放决策。结论为：新Physics World MC2具备替代旧HoTools MC2的产品、性能与架构资格，允许从下一独立提交开始P-09删除。

## 当前验收结论

`V1-R` 的产品替代资格已由P-08放行，P-09/P-10删除与基线、P-11职责审计、P-12 Python重组、P-13 C++原子化和P-14洁净度终审均已关闭。当前进入 **P-15 MC2稳定蓝本合一**，随后完成热点基线；全部关闭前`solver_acceptance_blocker=True`保持正确。

当前开放阻塞：

1. `P-15`：单一稳定蓝本及全部文档路由收口。
2. `P-16`：热点性能基线与维护态总门禁。

## 更新规则

1. 任何改变能力完成度、支持域或验收阻塞的 MC2 提交，必须同步更新本表对应行。
2. 新测试只有在证明该行所需层级时才能改变结论；shape/count、自洽测试或旧 solver 输出不能把状态升级为“完全对齐”。
3. 现有文档互相冲突时，本表先降级为“实现完成/证据缺口”，再以固定 MC2 source 与新 oracle 核账；不得选择较乐观的描述直接结案。
4. 长篇执行记录不再承载总体完成度。完成项从“当前切入点”移出后，只在本表保留结论与证据摘要。
5. 每次验收冲刺先关闭本表的阻塞行，不因未来扩展项增加而改变 `V1-R` 范围。
