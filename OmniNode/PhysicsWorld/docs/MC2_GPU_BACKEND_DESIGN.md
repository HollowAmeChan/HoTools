# MC2 GPU 后端设计

本文是 MC2 E6 的唯一实施入口，定义 GPU 后端的产品边界、数据与 pass 映射、CPU 隔离、碰撞算法、设备差异、失败语义、性能门槛和分阶段交付。节点装配与统一域合同见 `MC2_NODE_SIMULATION_DESIGN.md`，当前 CPU 产品事实见 `MC2_BLUEPRINT.md`，长期性能事实见 `MC2_DEEP_OPTIMIZATION_STRATEGY.md`。

## 当前起点

MC2 已有一个完整、可独立运行的 CPU DomainV1：三种 setup 共用统一 product request、compiled domain、固定 mixed pass、whole-domain self、logical output 和多目标事务。P6 已把逻辑 SoA、pass 依赖、dirty span、动态容量、单向 IO、请求式 debug 和数值 tolerance 固定为机器合同，但尚未创建 GPU runtime、GPU 资源或产品 backend 选择。

其中 BoneSpring 是 CPU 代码中尚未删除的 legacy setup，不属于 E6 GPU 交付范围。GPU capability、provider、shader、fixture、shadow 对拍和验收矩阵只覆盖 MeshCloth 与 BoneCloth；不得为了复刻 BoneSpring 的固定参数裁剪或 soft-sphere limit 增加第三套 GPU 分支。需要 MC2 骨链时使用 BoneCloth Line，需要兼容性弹簧骨时使用 SpringBone VRM。本文后续提到三种 setup 共享 pass 或 BoneSpring 限制的段落只描述当前 CPU 输入事实，不能解释为 GPU 支持要求。

E6 的任务是新增一个消费相同逻辑合同的 GPU backend。它不是把 CPU solver 改写成“CPU/GPU 共用内核”，也不是逐步用 GPU 分支侵入 `mc2_domain_cpu`。

## 第一原则：GPU 不得影响 CPU 解算器

这是 E6 的最高优先级硬合同：

1. CPU DomainV1 继续拥有自己的状态、内存布局、算法、pass 顺序、native ABI、计时路径和性能基线。
2. GPU 后端只共享后端中立的输入合同和 logical output 合同，不共享可变粒子状态、scratch、candidate/contact 容器或执行 owner。
3. 不为了复用 GPU 代码重构 CPU 热循环，不在 CPU pass 中加入设备判断、虚调用、dispatch 描述、GPU 对齐填充或 staging 管理。
4. GPU SDK、驱动或运行库缺失时，CPU native 必须仍可独立构建、加载、测试和运行；基础模块不得静态依赖可选 GPU runtime。
5. backend 选择发生在 domain allocation 之前。一个 live slot 只能拥有一种 backend；禁止在同一帧中途从 GPU 偷跑 CPU pass。
6. GPU 失败不得透明调用 CPU 继续该帧。设备丢失、容量溢出或 kernel 失败必须回滚 staged GPU step、零发布并报告错误；若用户随后选择 CPU，应创建或恢复一个具有明确 generation 的 CPU domain。
7. shadow 对拍必须从同一冻结输入分别驱动两个独立 owner。GPU shadow 结果只用于比较，不能修改 CPU state、CPU output 或 Blender 写回。
8. 每个 E6 批次都必须证明 CPU-only 构建、CPU 数值和 CPU 性能没有回归。GPU 获得收益不能抵偿 CPU 回归。
9. GPU 专用 key、padding、indirect dispatch、sort workspace 和派生表只在 GPU allocation 后生成；CPU request 不构造、不上传、不 hash 这些数据。
10. 仅为 GPU 增加的数据不得扩大普通 CPU frame capture 或热更新工作量。确需扩展 logical schema 时使用版本化可选字段，并证明 CPU 未选择该能力时不产生数组、分配、扫描或分支扩散。

## 所有权结构

```text
Blender / Physics World 主线程
  -> MC2ProductRequestV1
  -> capture / compile
  -> MC2CompiledDomainProgramV1
  -> MC2DomainParameterPacketV1
  -> MC2DomainFramePacketV1
       |                         |
       v                         v
  CPU backend owner         GPU backend owner
  CPU 私有布局/状态          device 私有布局/状态
  mc2_domain_cpu ABI        GPU provider ABI
       |                         |
       +------ logical output ---+
                    |
                    v
       同一结果校验与多目标事务
```

共享层只描述 logical identity、dtype、shape、space、读写集、容量规则和输出语义。physical layout、kernel、排序库、队列、descriptor、barrier、设备内存和同步原语全部属于 GPU provider 私有实现。

### 文件和构建隔离

- `mc2_domain_cpu.*` 与现有 CPU binding 是冻结的 CPU owner。
- GPU 实现放入独立 translation unit、独立 provider/loader 和独立可选构建目标；不能把 GPU 头文件传播到 CPU translation unit。
- 公共头文件只允许包含稳定 POD/view、错误码和 provider 边界，不允许包含 CUDA/Vulkan/DirectX/Metal 类型。
- provider discovery 必须是显式能力查询。未安装、版本不符或设备不支持都只表示 GPU 不可用，不能改变 CPU 注册结果。
- 首个原型只面向 Python 3.13 / Blender 5.2 的隔离环境。任何共享合同、loader 或打包变更仍需验证 py311/py313 的 CPU-only 路径；阶段出口再执行完整双 ABI 门禁。

### Provider 边界

GPU provider 的最小职责固定为：

```text
probe()                       -> capability / device report
create_domain(program)       -> staged GPU owner
update_parameters(packet)    -> dirty-span upload
update_frame(packet)         -> frame/collider upload
step(step_request)           -> staged logical output
read_output(output_request)  -> 一次最终 readback
read_debug(debug_request)    -> 请求式 snapshot
dispose()                    -> fence 后释放全部 device resource
```

provider API 只接收 typed buffer view、schema/version、shape/stride、revision 和普通错误码。它不接收 `bpy`、节点、NumPy ownership callback 或 CPU context pointer。`create_domain`、layout replacement 和容量增长都先构造 staged owner，只有完整验证成功后才替换 live GPU owner。

后端选择属于 slot allocation policy，不进入 compiled program signature。相同 logical domain 可以分别创建 CPU owner 和 GPU owner；backend identity 进入 runtime slot/resource key、diagnostic 和 benchmark，但不改变 authoring identity 或 output map。

## 后端中立输入与资源生命周期

GPU 直接消费 P6 已冻结的逻辑包：

| 输入 | 生命周期 | GPU 行为 |
|---|---|---|
| compiled program | topology/layout revision | 分配并上传静态 particle、constraint、primitive、partition 和 output map；仅 staged replacement 改布局。 |
| parameter packet | parameter revision | 按 dirty span 更新连续参数或离散策略，不重建无关静态表。 |
| frame packet | frame/generation | 上传 TaskReference、Center/Anchor/Teleport、逐 partition frame 与动态 collider。 |
| debug request | 单次真实 step | 只为声明的 `request_writes` 分配或读取旁路记录。 |
| logical output | 最终 substep | 每个 request 只回读一次；host 完整校验后参与公共事务。 |

资源状态至少区分：

- persistent static：topology、constraint indices/rest、primitive indices、logical identity、output map；
- persistent parameter：partition/particle/constraint 参数；
- persistent state：position、rotation、velocity、Center/Teleport/history；
- frame upload：transform、frame policy、collider SoA；
- substep transient：grid、candidate、contact、correction、scan/sort workspace；
- request-only observation：debug snapshot、详细计时和工作量计数；
- final readback：logical position/rotation/validity，不包含中间 contact 数据。

禁止每帧重传完整静态 topology，禁止 substep 中间回读，禁止让 Blender 对象或 NumPy owner 进入 kernel 生命周期。

## 固定执行顺序

GPU 必须实现与 CPU 产品相同的逻辑顺序：

```text
StepBasic prepare
  -> TaskReference / Teleport
  -> Center frame shift
  -> Center
  -> Center inertia
  -> Integration
  -> Tether
  -> Distance A
  -> Angle
  -> Bending
  -> external Point / Edge
  -> Distance B
  -> Motion
  -> whole-domain self
  -> post / history
  -> logical output
```

GPU 可以在一个逻辑 pass 内融合 kernel，也可以把一个 pass 拆成多个 dispatch，但不能跨越具有可观察读写依赖的 pass 重排。融合是 physical implementation，不改变 debug 名称、计时归属或 CPU reference 顺序。

### Pass 的差异化实现

| pass | GPU 形态 | 写冲突与门槛 |
|---|---|---|
| StepBasic / Integration / post | 每 particle 一线程 | 独占写，最适合首批闭环。 |
| Center / Teleport / frame shift | 每 partition 或 particle view | partition history 独立；frame shift 每帧只消费一次。 |
| Tether | 每 particle/constraint | 目标与 rest 来源必须与 StepBasic 完全一致。 |
| Distance / Angle / Bending | 静态 batch/color 或确定性 gather-reduce | 不能无序原地写共享粒子；不能借 Jacobi 改算法。 |
| external Point | 每 particle | collider scope 与 friction 先在 device 冻结。 |
| external Edge | 每 edge/contact | 共享端点需要确定性 reduction。 |
| whole-domain self | sort/scan/emit + 类型分流 + reduction | 见下节；是首个主要性能目标。 |
| logical output | 每 logical element scatter | 只生成后端中立输出，不直接生成 Blender mutation。 |

MeshCloth、BoneCloth 和 BoneSpring 共享逻辑 pass 顺序，但只 dispatch compiled program 中真实存在的表。BoneSpring 不因 GPU 化获得未声明的 self、Motion 或 collider 类型；BoneCloth 的 triangle/rotation output 和 BoneSpring 的 Line/SPHERE 限制继续由 capability 与表为空共同约束，不能在 shader 中偷偷补功能。

## Whole-domain self 的 GPU 设计

“求交”必须拆成四个独立阶段，不能用一个总耗时掩盖算法差异：

1. broadphase：primitive AABB、grid key、cell run 和候选 pair 枚举；
2. narrowphase：Edge-Edge 最近线段、Point-Triangle 最近点、厚度与预测位移判定、法线与符号；
3. contact solve：四轮投影、修正累积和粒子应用；
4. confirmed intersection：独立 Edge-Triangle 穿插历史与请求式 debug。

### 首版 broadphase

首版保持 CPU 的 uniform grid 和过滤语义，不先换成另一套碰撞模型：

```text
primitive SoA
  -> 并行生成 cell key
  -> radix sort(key, primitive)
  -> 建立 cell run
  -> 每个 source primitive 统计候选数量
  -> exclusive scan
  -> 并行 emit canonical candidate key
  -> radix sort / unique
  -> EE 与 PT 类型分流
```

这把 CPU 的 `count-grow-emit` 合同映射为 GPU 的 `count-scan-emit`。输出必须有稳定 canonical key；容量不足时只允许在硬上限内增长并重跑 emit，禁止 silent truncate。

uniform grid 对布料的近似统一边长和半径通常合适。LBVH/radix tree 只作为后续可替换 broadphase：当规模测试证明 primitive 尺度差异、过密 cell、probe 或 pair visit 使 Grid 曲线失控时，才用相同 fixture 比较构建、遍历、候选集和总帧时间。不能只比较树构建 kernel。

### 首版 narrowphase

- EE 和 PT 使用独立 candidate buffer 与 kernel，避免类型分支占据同一 wave/warp。
- 首版复现 CPU float32、退化分支、单一半径、预测位移阈值、法线/符号和 half 量化，不引入新的 epsilon。
- 先执行保守且便宜的平方距离/AABB 上界，只有 profiling 证明拒绝覆盖率足够高才保留；不能增加分支后只报告单个理想资产。
- Pin Point、全部固定 Edge/Triangle、共享粒子、一环拓扑、partition owner、双向 self policy 和 group/mask 过滤必须与 CPU exact。
- CPU candidate/contact key 与 count 是工作量合同。GPU 不能通过漏发候选获得表面加速。

### Contact solve 与确定性

当前 contact 会对共享粒子写 correction，不能直接用无序浮点 atomic 宣称等价。允许的首版方案是：

- 保留整数定点 sum/count，在证明范围不会溢出的设备上使用整数 atomic；或
- 按 particle key 排序后做确定性 segmented reduction；或
- 使用静态颜色/批次，但必须证明没有改变迭代语义。

Edge-Edge 当前复用 contact 建立时的 `s/t/normal`，Point-Triangle 在轮次中重算最近点和三角形法线；GPU 首版保持该差异。把 Gauss-Seidel 风格过程改成 Jacobi、改变轮数或更换 barrier/contact 模型都属于数值算法变更，不能混入后端移植。

### 研究算法的使用边界

- I-Cloth 的增量空间哈希、时空一致性和 GPU impact-zone 证明了整条 collision pipeline 常驻 GPU 的价值，可作为后续 contact cache 研究方向。
- Karras 的并行 radix tree/LBVH 是 broadphase 备选，不替代 EE/PT narrowphase。
- Tight-Inclusion、Root-Parity 等稳健 CCD 用于退化、高速穿透和漏检 fixture 的离线 oracle；首版产品不以完整 CCD 替换当前离散接触。
- IPC/C-IPC/GIPC 会改变 barrier energy、求解器、收敛和摩擦语义，只能作为未来独立数值里程碑，不能作为 E6 等价移植中的“几何库替换”。
- 外部实现不得取得 MC2 数据、状态或产品 owner；许可证、设备限制和依赖必须在 provider 选择前独立审计。

研究入口：

- I-Cloth：<https://doi.org/10.1145/3272127.3275005>
- GPU/LBVH：<https://research.nvidia.com/publication/2012-06_maximizing-parallelism-construction-bvhs-octrees-and-k-d-trees>
- Continuous Collision Detection：<https://continuous-collision-detection.github.io/>
- IPC Toolkit：<https://ipctk.xyz/>
- C-IPC：<https://ipc-sim.github.io/C-IPC/>
- GIPC：<https://doi.org/10.1145/3643028>

## 设备和 API 差异

第一版 provider 必须显式报告能力，不能假定所有 GPU 一致：

| 能力 | 影响 |
|---|---|
| storage buffer 最大尺寸与 alignment | 决定单 domain 上限和 SoA padding；padding 只存在于 physical layout。 |
| subgroup/wave 宽度 | 影响 scan、reduction 和分支效率；不能写死 32。 |
| int32/int64 atomic | 决定定点累积和 key/count 实现；缺失时使用排序归并或拒绝能力。 |
| radix sort/scan 实现 | 属于 provider 私有库；结果顺序仍须满足 canonical key 合同。 |
| queue/fence 模型 | 决定上传、dispatch、readback overlap；同步点必须进入产品计时。 |
| device loss/reset | 必须使 staged step 失败并释放/失效 GPU owner，不能留下半提交结果。 |
| shader/compiler float 行为 | 必须验证 NaN、subnormal、FMA、half 和转换差异；不得默认开启破坏 reference 的 fast-math。 |

CUDA 专用研究可以用于原型，但不能把 NVIDIA-only 类型写进后端中立合同。产品 backend/API 选择应由目标设备覆盖、Blender 进程共存、分发许可、调试工具和实测收益共同决定。

## 调试与计时

- debug-off 不分配 debug buffer、不复制中间态、不回读 candidate/contact，也不改变 dispatch 图。
- timing-off 不读取 GPU timestamp query，不建立明细容器；只允许常数级开关。
- timing-on 至少报告 capture、upload、queue wait、各逻辑 pass、readback、output build 和 publish；kernel 总和不能代替产品整帧。
- self 计时必须报告 primitive、grid、candidate count/scan/emit/sort、EE/PT narrowphase、contact compact、四轮 solve 和 intersection。
- GPU 工作量统计与 CPU 使用同名逻辑指标；设备私有指标可以追加，但不能替代 candidate/contact exact 项。
- 请求式 debug snapshot 只能观察真实 production pass 的旁路记录，不能另跑一套“可视化求解”。

## 失败、容量与事务

candidate、contact 和 intersection 采用 staged transaction：

1. count 得到 required；
2. 与组合硬上限比较；
3. 容量不足时增长 provider 私有 buffer；
4. 重跑 emit；
5. 只有全部 pass、readback 和 output validation 成功才发布新状态。

任何 overflow、非有限值、device loss、timeout、shader failure、readback mismatch 或 output target 失效都必须零发布。错误报告至少包含 backend、device、domain/generation、pass、required/capacity 和恢复动作。禁止把失败后的部分 GPU state 当作下一帧起点。

## 性能基线与成功条件

同机代表场景基线为 1800 粒子、两个 Mesh partition、495 collider、三个 substep：CPU timing-off 中位数约 `26.78 ms`，其中 solve `22.73 ms`，GPU 无法直接消除的 host floor 约 `4.27 ms`。whole-domain self 中 candidate 约 `14.74 ms`，contact 建立与四轮求解合计约 `6.53 ms`。这些数字用于 E6 同机决策，不是跨设备承诺。

首版 2k 级预演为 GPU 数值 `3-8 ms`、上传/同步/readback `0.5-1.5 ms`、产品整帧 `7.8-13.8 ms`；成熟 persistent/fused 路径目标约 `7-9 ms`。`4.27 ms` host floor 推出的数学上限不是验收目标。

GPU 只有同时满足下列条件才可进入产品选择：

- CPU-only 路径的数值、性能、二进制依赖和加载行为无回归；
- `2k/10k/50k/100k` 的产品整帧和内存曲线均有记录，规模增长明显优于 CPU；
- 报告包含上传、同步、readback、host transaction，不只报告 kernel；
- candidate/contact/filter/Pin/owner 决策 exact，浮点结果满足固定 fixture 的逐 pass tolerance 与 global cap；
- debug-off、timing-off、失败回滚、dispose、rewind/reset、多 target 原子性和长期 soak 均成立；
- GPU runtime 缺失时 CPU build/load/execute 完整成立。

### 数值分层

CPU/GPU 对拍不使用一个模糊的最终位置容差：

- exact：schema、identity、partition/output mapping、topology、pass presence/order、Pin/primitive participation、owner/group/mask 过滤、candidate/contact canonical key 与 count、容量和 overflow 决策；
- per-pass tolerance：Center/Teleport、constraint correction、contact geometry、velocity/history 和 output 各自使用固定 fixture 声明；
- global cap：position/rotation component `atol=rtol=5e-4`，velocity `atol=2e-3`、`rtol=5e-3`，且全部值有限；
- deterministic repeat：同设备、同 provider、同输入重复执行的工作量必须 exact，数值满足固定 repeat contract；
- cross-device：只允许在上述分层内存在可解释浮点差异，不得放宽 exact 工作量或失败语义。

某个 fixture 需要超过 global cap 时，必须作为数值设计变更单独审查，不能由 provider 或设备白名单私自放宽。

## E6 实施批次

### E6-A：可选 provider 骨架

建立独立构建、能力发现、device 枚举、错误域、资源计数和 dispose。只运行上传/回读 micro fixture，不接产品节点，不修改 CPU owner。退出时 CPU-only 环境完全不加载 GPU runtime。

### E6-B：离线闭环数值原型

从固定 compiled-domain/frame fixture 创建 GPU owner，实现 StepBasic、Integration 和 Distance 的最小闭环，产生 logical output；CPU owner独立运行同一输入并对拍。此阶段不从 GPU 中途调用 CPU pass，也不进入 Blender 写回。

### E6-C：Whole-domain self

实现 primitive、uniform grid、count-scan-emit candidate、稳定去重、EE/PT narrowphase、contact compact、四轮确定性 reduction 和 intersection。先证明 candidate/contact 工作量等价，再评价性能；LBVH 和新 CCD 不进入首版。

### E6-D：完整 mixed pass

按固定顺序补齐 Center/Teleport、Tether、Angle、Bending、external、Distance B、Motion 和 post/history。每补一个逻辑 pass，先跑该 pass fixture，再跑完整 CPU-only 回归和 GPU closed-loop 对拍。

### E6-E：产品 shadow

在显式开发开关下，CPU 继续作为唯一发布 backend；GPU 使用复制的冻结输入运行并生成不发布的比较报告。shadow 不得共享 mutable state，不得常驻普通用户路径，也不得把双倍计算包装成产品 fallback。

### E6-F：显式 GPU 产品 backend

通过独立 backend 选择创建 GPU slot，接入一次 logical output readback、多 request 求解和公共多目标事务。CPU 与 GPU 是并列产品 backend，不是一个 solver 内的分支热循环。

### E6-G：产品化收尾

删除原型专用复制、临时 readback、shadow UI 和已经失去用途的诊断适配；保留固定 fixture、provider 能力测试和 CPU/GPU 对拍。更新蓝本为稳定事实，阶段过程只留 Git。

## 每批验收顺序

1. CPU-only build/load，确认没有 GPU 动态依赖。
2. CPU native、DomainV1、产品事务、debug-off 和性能门禁。
3. GPU provider 生命周期、资源泄漏、错误注入和容量回滚。
4. 当前新增 pass 的 fixed fixture 与 CPU reference 对拍。
5. 完整 GPU closed-loop、工作量、数值和确定性重复跑。
6. Blender 5.2 隔离验收，明确排除默认 HoTools 备份并加载当前 py313 产物。
7. 阶段出口执行共享合同的双 ABI CPU 门禁；GPU 支持矩阵按实际 provider 单独记录。
8. 单独提交代码、测试和稳定文档更新，不把多个未验证 pass 合并成一次大迁移。

## 禁止事项

- 为 GPU 复用而改写 CPU 算法、状态布局或 pass 顺序。
- 在 `mc2_domain_cpu` 热路径加入 backend 分支或虚接口。
- CPU/GPU 共享 mutable particle/contact/history buffer。
- 每个 substep 在 host/device 之间往返。
- 设备失败后静默切 CPU 继续当前 generation。
- 用无序浮点 atomic、fast-math 或减少候选掩盖不等价。
- 把 debug/timing buffer变成 production 常驻 ABI。
- 把 CUDA、shader、descriptor 或队列类型写入 authoring/compiled logical contract。
- 在首版同时更换 Grid、CCD、contact model 和 solver；算法研究必须独立立项并可回滚。
