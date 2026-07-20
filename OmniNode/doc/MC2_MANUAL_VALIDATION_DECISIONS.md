# MC2 手动验收问题与产品决策

更新日期：2026-07-20

本文档记录本轮 Blender 手动验收推翻或质疑的 MC2 产品结论，并作为重新实施前的决策清单。旧 solver 已经移除，不属于本文范围。当前 `MC2_BLUEPRINT.md` 中“九个能力族均 verified / 无发布阻断项”的结论在本文问题关闭前暂停成立；自动测试只能证明其断言覆盖的内部状态，不能覆盖本轮发现的可解释性、高速穿模、自碰静置和真实交互结果。

## 写作边界

- **应该写**：可复现的手测反例、当前代码/MC2 源码事实、用户真正要判断的问题、已确定或待确定的产品决策、实施顺序与行为验收证据。
- **不应该写**：旧 solver 迁移历史、逐提交流水账、稳定实现的完整说明、通用 Physics World 合同、仅为通过现有测试而设计的内部断言。
- **内容路由**：决策关闭并成为稳定事实后合入 `MC2_BLUEPRINT.md`；OmniNode 通用编译/运行缓存合同写入 `../ARCHITECTURE.md`；公共物理流水线规则写入 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；历史只留 Git。
- **退出条件**：所有决策有结论，行为反例有真实 Blender 复测，自动矩阵按新产品要求重开并重新闭环后，删除本文档。

## 总体结论

本轮问题不能归为“再补一些绘制图元”。当前 debug 设计以内部数组和算法名为中心，主要证明“某份数据存在”，没有稳定回答用户的四个问题：

1. 这个功能当前是否启用并实际参与了求解？
2. 哪些粒子/约束正在接近阈值、已经触发或已经被钳制？
3. 粒子原本想怎样运动，最终又被哪一步阻止或改向？
4. 当前看到的是参考姿态、候选、接触、几何穿插，还是最终修正结果？

后续 debug 的一级产品视图应优先表达结果与原因；StepBasic、空间网格和 primitive 等原始中间态保留为二级高级视图。不能再以“batch 非空、颜色存在、快照可读”作为视觉语义验收。

## 决策总表

| ID | 状态 | 决策 | 当前建议 |
|---|---|---|---|
| D-01 | **代码已关闭，待最终手测** | Teleport 判定模型 | 整task统一触发；首Fixed/物体原点；Reset/Keep重定基全部动画与collider插值历史，清理接触状态 |
| D-02 | **分段实施中** | Debug 一级信息架构 | 重力、速度、选中深度、Tether/Distance记录结果与其余约束pass correction已接通；Bending/Angle记录身份、Center分层量与接触时间层仍待实施 |
| D-03 | **代码已实现，待手测** | 外部碰撞结果表达 | “碰撞情况”保留形状；“实际接触”按需捕获真实Point/Edge contact、修正与活动collider |
| D-04 | **人工已验证** | 自碰静置质量标准 | 单层布料无final几何穿插且扰动完全收敛；剩余contact只位于代理真实拥挤区，接触区域保持静止 |
| D-05 | **已决策，代码已迁移** | 参数从 Profile 移到 Task 的规则 | Teleport、组件惯性、Normal Axis、自碰交互质量归Task；粒子材料/逐深度约束留Profile；无双owner |
| D-06 | **方向已决策** | 重编译后的运行缓存保留 | 只在可证明 namespace/owner 合同时保留；不能只比较数组范围 |
| D-07 | **代码已关闭** | 无 consumer 参数是否公开 | `centrifugal_acceleration` 无 production consumer，已从全部公开 Profile/Task 节点及 preset 移除；内部 ABI 固定为0 |
| D-08 | **人工已验证** | Baseline depth 审计 | Mesh以4:1混入Fixed边界表面距离并单调保护；Depth inertia使用1.5次指数；非均匀减面实测确认旋转带动更自然且横向等高线偏移明显受抑制 |
| D-09 | **代码已实现，待界面复验** | 参数说明载体 | Profile/Task 长注释由实际字段 metadata 自动生成表格并由注册测试防漂移；socket tooltip 保留短摘要和枚举映射 |
| D-10 | **代码已修复，待手测** | 非连通 MeshCloth 碰撞可视化完整性 | 根因是`max_items`按数组前缀截断；现按连通分量公平分配预算并在分量内均匀抽样 |

## P0：Teleport 回退与高速穿模

### 已确定的产品结论

逐粒子 Teleport 是一次产品实验，手测结果不理想，现决定回退。MC2 原版在 `TeamManager.SimulationCalcCenterAndInertiaAndWind()` 中使用整个 component 的 `frameDeltaVector` 和 `frameDeltaAngle`，距离或角度任一超过阈值即给整个 team 设置 Reset 或 Keep。OmniMC2 仍保持整个 task 统一触发，不扩张逐粒子阈值、局部触发或逐粒子状态 UI。

OmniMC2 的判定基准明确采用**最终 proxy 顺序中的首个 Fixed 粒子**；比较该粒子前后两帧的动画/base world pose。若 task 没有任何 Fixed 粒子，则回退为模拟对象原点的 world pose；Bone task 使用 Armature Object 原点。这个选择必须稳定且可解释，不允许按距离、当前接触或哈希顺序每帧更换。任一位移或旋转阈值触发后，Reset/Keep 仍作用于整个 task。该规则是 Blender 产品层相对 MC2 Team Center 的明确差异点。

### 当前实现与未关闭问题

- C++生产路径已改为`apply_task_teleport`：只读取最终proxy顺序中的首个Fixed；无Fixed时读取对象原点。一次判定只返回一个任务级结果，旧逐粒子扫描、局部状态修改及逐粒子debug数组已经移除。
- Keep触发后除整体搬运state/velocity reference/StepBasic/Motion base外，还把`old_dynamic`重定基为本帧dynamic、把old component pose重定基为当前pose，并令collider old shape等于current shape；第一post-teleport substep因此不会在传送前后姿态或collider之间再次插值/扫掠。
- Reset由solver在同一帧调用native reset，对齐本帧dynamic并清零速度、摩擦、碰撞法线、self和输出历史。Keep保留并旋转真实物理速度，但清零摩擦、碰撞法线，撤销外碰debug contact、bone output、task内self和world interaction历史；传送位移本身不进入速度。
- 自动矩阵现已覆盖三setup任务级首Fixed/物体原点、非基准粒子不触发、Reset/Keep整task结果、同帧interaction失效与下一帧重建、Keep非零速度精确保留，以及900/1200/1800帧确定性与速度上限。它仍没有证明真实collider另一侧不会出现传送路径造成的高速穿模。
- 手测已给出反例：触发 Reset/Keep 后仍可能高速穿模，说明缓存/时序清理链不完整，或者同帧碰撞体与粒子历史没有按 MC2 原版一起重置。
- 现有阈值/状态绘制停在旧位置并只变色，是逐粒子实验的直接产物。回退后应改成单个判定基准的身份、旧姿态、新姿态、距离/角度阈值与 task 状态。
- 当前阈值/状态绘制已经改为单个task判定基准、旧/新位置、阈值、实测位移与None/Keep/Reset颜色；不再申请逐粒子debug数组。

### 必须对照 MC2 重审的状态

Reset 和 Keep 不能只改 `state_positions/state_velocities`。至少逐项对照并证明以下状态的处理顺序：

- `next/current/old/base/velocity-reference` 粒子位置与旋转；
- 保存速度、真实速度、位移、摩擦、静摩擦、碰撞法线；
- Center 的 old/current frame pose、平滑速度、惯性 shift 和 stabilization 权重；
- collider 的 frame/old/now pose 与 Reset flag；
- task 内 self primitive、grid、candidate、contact、intersection flag/history；
- 跨 task interaction aggregate、participant old positions、contact/intersection history；
- zero-substep、跳帧、暂停和同帧重复执行时的触发与清理时机；
- Reset 与 Keep 的差别：Reset 回到当帧动画姿态并清速度，Keep 搬运已有形状但不得保留由传送本身制造的高速速度。

### 新验收标准

- MeshCloth、BoneCloth、BoneSpring 分别覆盖基准平移和旋转阈值，Reset/Keep 各一组；有多个 Fixed 时必须证明只使用稳定的首个 Fixed。
- 每种 setup 都覆盖“存在 Fixed”和“无 Fixed 回退物体原点”；移动非基准粒子不得单独触发，移动基准必须触发整个 task。
- 触发当帧即完成处理，不能等下一视觉帧；zero-substep 也必须正确。
- 有静态和移动 collider；大位移后不得出现由旧粒子或旧 collider history 造成的高速穿透。
- task 内自碰和跨 task 自碰分别验证历史已失效，下一帧可正常重新建 contact。
- debug 只画一个 task 级判定：基准类型与 proxy index、旧/新 pose、距离阈值、角度阈值、实际测量和最终状态。
- 自动回归把传送帧`frame_interpolation`设为0.25，并证明Keep后的第一substep Motion BasePosition已完整位于新姿态，而不是传送路径25%处；Blender BasePose同时覆盖无Fixed物体原点Keep/Reset与3-substep结果。
- 自动测试必须增加“碰撞体另一侧无高速粒子”“触发后实际速度有界”等外部结果断言，不能再只查内部 reset 数组。

## P0：自碰误报、闪烁与持续微动

### 当前事实

- MC2 FullMesh 自碰不是单一接触算法，而是 Point-Triangle、Edge-Edge contact 加独立 Intersect 检测/修正。
- MC2 源码将该功能标为 Beta2；fork 中 contact 固定迭代 4 次，Intersect 分批检测，`SelfCollisionIntersectDiv = 2`。
- 旧debug曾把本帧Edge-Triangle broadphase record全部画成洋红，导致候选被误解为最终穿插。当前final阶段会原地剔除未通过线段-三角形测试的record，debug专用readback也只允许读取final结果；洋红现表示最终确认命中。红箭头来自普通contact结果；边界附近在厚度范围内也可能形成contact。
- 手测反例仍然有效：拓扑无交叉、无非流形的干净单层网格中，红色 contact 箭头主要密集出现在顶点密度较高区域，并伴随持续微动；这与洋红 intersection record 是两个问题。现有 long-run 只断言有 contact/intersection 和数值有限，没有证明密度无关性、误报率、接触 churn 或可见静置质量。
- 生产审计确认一个直接根因：旧过滤只拒绝primitive共享同一个particle，没有拒绝两个primitive的particle由真实proxy edge直接相邻。密集单层曲面因此会把本应由结构约束维持的一环邻居送入EE/PT contact，也会送入独立intersection记录。
- 当前native在self static上传时从final proxy edges一次性生成排序去重的粒子邻接键；task内candidate和intersection共同拒绝共享粒子或一环邻接的primitive。该表不进入逐帧构建，不产生debug payload，也不应用于不同owner的跨task interaction。
- 3.11完整context runner已经覆盖：断开的远邻Edge-Edge与Point-Triangle仍产生接触；一环相连的Edge-Edge、Point-Triangle及Edge-Triangle intersection全部被排除；原跨帧真实穿插历史仍保留。该证据关闭“一环完全未过滤”的实现缺口，但不能替代原密集单层模型的人工静置复测。
- 实际密集单层模型最终复验确认：final过滤后洋红几何穿插完全消失；红色contact只剩在代理本身真实拥挤的区域，布料及这些接触区域均完全收敛且不再运动。该证据确认一环缺口是原持续扰动的主要根因，并关闭D-04当前产品阻断。红箭头表示有效接触法线而非持续修正量，静止时保留不等于solver仍在注入运动。
- 洋红线的规律闪烁不是优先归因于浮点随机性。生产路径按`frame % 2`每帧只检测grid排序后索引为奇数或偶数的Edge，目的是把昂贵的Edge-Triangle检测摊到两帧；record又在每次检测前清空，因此真实命中也只会在其分片被扫描的帧出现。普通EE/PT contact不使用该二分节奏。若同一奇偶相位、相同输入仍随机翻转，才继续审计浮点边界。
- 新帧开始生成穿插候选时必须立即撤销上一帧的`self_intersect_flags_ready`，本帧final测试完成后再发布。上一帧particle flags可继续供solver内部历史使用，但debug专用readback不得用旧ready读取新record；该发布时序已经进入native门卫与自动回归。

### 需要先做的审计

1. 用完全平面、轻微弯曲、开边界、闭合裙摆、双层重叠五类最小网格，记录 primitive/candidate/contact/intersection 数量与身份变化。
2. 相邻 triangle、共享 edge、共享 vertex和同一 primitive的一环排除已实现并有正反自动回归；下一步继续审计二环/厚度相关近邻和同面近共面结构，不能无依据扩大固定k-ring。
3. 核对 Blender 代理三角方向、法线、负缩放、非流形边和重复顶点是否制造假 intersection；已确认干净样例无非流形或拓扑交叉时，不得继续把密集区红箭头归因于坏拓扑。
4. 分开统计“新建 contact”“持续 contact”“失效 contact”“intersection 新增/消失”，不能只看总数。
5. 比较 self off/on 在零重力、无动画、无外碰时的 RMS 速度、最大位移、能量衰减和 600/1800 帧稳定值。
6. 判断微动来自接触厚度、交叉修正、缓存抖动、约束顺序还是 inverse mass/cloth mass。
7. 对同一 world-space 曲面做低/中/高三档重拓扑，保持材质、厚度和外形不变，比较单位面积 candidate/contact、RMS 速度与 contact churn；顶点变密本身不得让接触数量或修正能量失控。
8. 记录 self thickness 与局部一环边长的比例，复验已完成的一环排除是否足以阻止同一连续曲面在密集区互相排斥；若仍失败，再以局部厚度/边长证据评估自适应k-ring，并检查同一几何接触是否被 PT/EE 或多个 primitive 重复累计。

### 已确认的产品标准 D-04

“单层无穿插布料应收敛到不可见微动”是当前硬标准，而不是把FullMesh持续扰动解释为正常副作用。实际模型已满足：final intersection为零、可见运动完全收敛、剩余contact仅与真实拥挤几何一致。末300帧RMS速度、最大漂移、contact churn和密度分档继续作为未来自动回归量化项，不再阻断当前D-04人工关闭；双层抑制仍不得替代单层稳定性证据。

### Debug 重组

- 一级 `自碰接触`：只显示当前实际施加修正的 contact、法线、修正量和参与质量。
- 一级 `几何交叉`：已只显示final线段-三角形测试确认命中的记录；洋红表示“几何穿越命中”，不是普通接触或broadphase record。
- 高级 `自碰形状`、`宽相网格`、`宽相候选`：保留给算法审计，默认关闭。
- 高级 `穿插扫描候选`：低亮度表达当前奇/偶Edge分片及broadphase record。若提供稳定观察，只能在renderer合并最近两帧并按年龄淡出，必须标注为两帧观察窗，不能冒充本帧solver状态。
- 每种模式显示本帧新增/持续/失效状态，避免闪烁被误读成稳定接触。
- 若 debug 关闭，不得生产 contact 明细、intersection 线段或额外 readback；求解本来必需的缓存不算 debug，但不能为绘制复制整份数组。

## P1：Debug 信息架构重做

### D-02：一级按用户问题组织（分段实施中）

建议把当前按数组名排列的开关重组为以下一级视图：

| 一级视图 | 用户要回答的问题 | 主要视觉编码 |
|---|---|---|
| 运动趋势 | 粒子想往哪动，实际往哪动，哪一步阻止了它 | 积分速度、真实位移速度、两者差向量；限速/阻尼/约束钳制标红 |
| 结构约束 | 哪条 Distance/Tether/Bending 正在修正 | 只突出超限或本帧实际修正的记录；修正量决定颜色/宽度 |
| 动画空间限制 | MaxDistance/Backstop 当前范围和触发情况 | 动画 BasePose、曲线采样后的范围、当前粒子、实际投影箭头 |
| 角度约束 | 当前角、目标角、上限和本帧修正是多少 | 当前/目标向量、角弧、淡锥；触发时红色修正弧 |
| 惯性与重力 | 原始 component 运动如何变成应用到粒子的量 | raw、平滑/限速后、最终 applied 三层向量；触发限值标红 |
| 碰撞形状 | 什么形状可能与什么形状碰 | 当前已有的 Point/Edge/Collider surface 视图 |
| 实际接触 | 本帧哪里真的在互相排斥 | 接触点、法线、穿深/修正；有 active contact 的 collider 标红 |
| 自碰结果 | 当前 contact 与 geometric intersection 是否合理 | 结果视图，不默认显示 grid/candidate |
| 最终输出 | 最终真正写回 Blender 的偏移是什么 | 保留现有模式 |

StepBasic、Motion Base、primitive、grid、candidate 等放入“高级中间态”。大段 `omni_description` 可放表格和完整解释；socket tooltip 保持短句，避免 Blender 截断。

约束结果导向的第一段已经接通：Tether、Distance、Angle、Bending、Motion 各有独立请求位；C++只在请求后的真实substep中保存对应pass的pre-position与实际position delta。冻结顺序固定为`Tether -> Distance A -> Angle -> Bending -> Distance B -> Motion`，Distance保留两次独立修正，不能相加后因方向相反而抵消。Python只为ready位分配稀疏数组并冻结只读结果，renderer把非零correction从真实pass原点画成红箭头；debug关闭或单模式未请求的兄弟pass不分配buffer、不readback。

记录级第二段已经覆盖Tether与Distance。Tether以每个Move粒子的稳定`vertex/root`为记录，冻结pass前两端位置、上下限、ratio、signed error、near/active状态和真实correction，renderer只画active/near记录。Distance保留A/B两个phase及有向`record_index/owner/target`；C++在临时位置副本重放该phase并保存每条记录经owner平均后的实际贡献，记录按`phase+owner`求和必须还原生产pass粒子correction。真实context仍只由未改写的production solver写入，debug重放不得改变模拟轨迹。

Bending、Angle与Motion当前仍是**逐pass、逐粒子聚合结果**。它们能回答“这个pass把哪些粒子从哪里移动了多少”，还不能回答具体哪条Bending quad、Angle Restoration/Limit子分支或Motion MaxDistance/Backstop负责，也没有这些模式的记录级near-limit和误差归一化。Angle Restoration与Angle Limit目前共用真实Angle pass correction，不能仅凭该箭头归因到其中一个子分支。

### D-08：逐粒子 Baseline Depth（优先实施）

用户已通过深度色带确认：整体纵向连续不代表横向等深线正确。非均匀减面会让同一几何高度经过不同拓扑层、斜边和parent path，原版沿parent累计边长的depth因此产生横向偏移；Center惯性的`1-depth²`又在末端放大这种差异。该手测证据足以支持受控产品差异，但不支持删除parent/root结构。

高级 `粒子深度` 模式的第一版已实现，生产depth采用以下OmniMC2差异并已通过实际非均匀减面模型人工复验：

- 每个有效粒子显示真实 `baseline_depths` 的 `0..1` 色带；Fixed 明确显示为根，Move 点必须能肉眼比较近根与远端。
- 同时显示稳定的 `root_index`/根归属边界；多 Fixed 区域不能只靠一条全局渐变掩盖归属切换。
- 高亮 parent-child 深度逆序、局部突跳、Move 粒子无可达 Fixed、零长度链及同一局部区域异常跨根等诊断项。无 Fixed 时当前 baseline 不会生成物体原点根；所有 Move 的 `root=-1/depth=0` 必须被明确标为无根，不能和 Teleport 的物体原点回退混淆。
- 默认点视图保持轻量；选中/抽样粒子时才显示数值、parent 线、累计路径长度和归一化分母，避免全屏文字与连线。
- 该模式首先复用 solver 已有的 static depth/root/parent 数据；只有用户显式请求高级诊断时才组装绘制 payload，不得为了 debug 在 C++ 常驻生产另一份深度。

当前实现从 C++ context 按需读取 solver 已有的 parent/root/depth：蓝到橙表示归一化深度，粉色表示 Fixed，紫色表示无根 Move，黄色表示 ZeroDistance，白线表示至少含一个 Move 的实际拓扑边跨越 root，橙线表示局部深度突跳，纯红点/线表示 parent 非法、root 不一致或深度逆序。Fixed-Fixed 邻边不画成 root 边界，正常 depth=1 也不使用非法红色。`max_items`只截断绘制，不参与拓扑有效性判定。`深度粒子索引`指定一个粒子后，以紫色高亮其完整 parent 路径；累计长度、两种原始depth分量和归一化分母的数值标注仍是增强项，不影响已经完成的D-08生产depth人工结论。

Mesh生产depth保留原parent-chain几何depth为主项，再计算沿proxy边到全部Fixed的多源最短表面距离depth，以`4:1`混合并沿parent做单调保护；Bone不应用该修正。Depth inertia的生产权重从MC2源码`1-depth²`改为`1-depth^1.5`，减少末端附近小depth偏差造成的视觉放大。固定MC2 fixture仍保存平方公式作为source oracle，生产测试必须显式验证OmniMC2差异，不能篡改来源证据。

人工验收结果：同一份非均匀减面布料在旋转带动时，末端响应明显更自然；原先由拓扑密度和斜边路径造成的横向等深线偏移也得到明显抑制。该结果确认当前`4:1 + 1.5次指数`可以作为产品默认值，但不表示depth问题已经没有后续设计空间。

Depth是后续可持续调优的设计面。候选项包括parent depth与Fixed边界距离的混合比例、惯性指数、按root/component归一化、显式depth顶点组以及更细的路径代价；当前默认值先作为内部合同固定，不立即暴露socket。任何调优都必须按consumer矩阵同时复验阻尼、半径、Distance/Angle、Motion/Backstop、自碰厚度、Center深度惯性与最终输出，不能只以色带或单一动作观感决定。

肉眼与最小场景证据取得后，再分别评估：父链建立是否应使用累计拓扑边长代价、方向连续性与长度如何联合、全 task 最大值是否应改为按 root/component 归一化，以及是否需要构建后的反向/单调一致性修正。反向修正目前是候选，不是既定答案；任何改法都必须同时检查阻尼、半径、Distance/Angle、Motion/Backstop 曲线和深度惯性等全部 consumer。

最小审计矩阵至少包含：同一曲面的均匀/非均匀重拓扑、跨区域长边或三角斜边、多个 Fixed 岛且链长差异很大、相同拓扑仅旋转组件，以及相同 world 形状改变细分密度。每个场景对比当前“拓扑层 + 方向连续性”父链、累计边长候选父链与只做构建后一致性检查三条路径；先验证 root 身份稳定、沿 parent 单调、局部变化连续和旋转不改变 static depth，再比较最终运动。不得用最终看起来更顺眼替代这些不变量。

### 参数长说明与蓝本同步（代码已实现，待界面复验）

三种粒子配置节点允许在 `omni_description` 中使用长文本和表格；用户无需只靠易截断的 socket tooltip 理解参数。`MC2_BLUEPRINT.md` 的粒子属性表是语义基准，每个 setup 节点只展示自己实际公开且有效的字段，内容必须同步说明用途、单位/范围、实际 consumer、曲线/depth 采样、无效条件、相关 debug 模式。socket tooltip 只保留短摘要和枚举映射。

Profile与Task节点的长说明现在由各自实际公开字段的label和`input_init.description`自动生成表格；注册测试逐字段验证tooltip内容进入长说明，并验证各setup不会展示不属于自己的字段。蓝本继续承担更完整的consumer、setup差异与无效条件事实；字段公开性或consumer变化时，蓝本与结构化metadata必须在同一提交更新。

### 所有模式的共同门禁

- **不能静默空白**：模式无输出时必须能区分“功能关闭、字段为零、该 setup 不支持、没有 Motion 属性、无活动记录、快照尚未捕获”。表达可以放在节点状态/长说明，不伪造几何。
- **结果优先**：范围几何用低亮度；真正触发/钳制/修正用高亮红色；接近阈值用黄色；未触发用低饱和色。
- **曲线必须可见**：曲线采样结果应直接改变每粒子的长度、半径、颜色或透明度，不能只画统一形状。
- **硬约束必须可见**：红色必须来自该 pass 的真实 pre/post correction 或 active flag，不能仅用最终位置反推，因为后续 pass 会覆盖证据。
- **限制噪声**：默认只画 active/near-limit，支持 task filter、最大项、步进抽样和选择粒子；不得默认把所有 root-to-particle 线画满屏。
- **显式生产**：新增 correction/contact/limit debug 数据只能由 debug 节点显式请求；C++ 在对应 pass 临时采集，冻结后 readback，不常驻生产第二套结果。
- **行为验收**：截图像素非空不是验收。每个模式需要一个人为可读的最小场景和数值 oracle，证明颜色/形状对应真实触发。

## 各模式问题与待办

### StepBasic

当前 StepBasic 是结构约束参考姿态：每个 substep 先从动画 base 初始化；当 `animation_pose_ratio < 1` 时，Move 后代会按 baseline 局部父子关系重建，再按比例混回动画姿态。它不是模拟粒子位置，也不是 Motion BasePosition。

- 如果只动画子骨且 `animation_pose_ratio=0`，StepBasic 后代不完全跟随该子骨动画可能是合同结果。
- 如果 component/root 的动画 base 已移动而 StepBasic 整体仍不动，则是捕获/更新 bug。
- 描述必须说明它用于 Distance、Tether、Angle 和 Bone 输出的结构参考，而不是“当前动画姿态”。
- 验收覆盖 object/root 移动、子骨动画、`animation_pose_ratio=0/0.5/1` 和暂停/多 substep。

### 有效重力与重力衰减

当前绘制在每个Move粒子处重复同一组组件级向量：灰色为`gravity_strength * scale_ratio`，绿色为再乘`gravity_ratio`后的实际有效重力，长度均乘`0.02`。因此衰减前后差异可以直接比较，但不能误读为逐粒子重力衰减；Center朝向与初始/world重力的dot产生的是一个全task `gravity_ratio`。

- 不能假装存在逐粒子重力衰减。
- 灰/绿箭头已经同时表达raw与effective gravity；每个Move粒子上的数值相同，只为提供空间直觉。
- `gravity_falloff=0/1`、Center 旋转 0/90/180 度必须能直观看到有效长度变化。
- Angle Restoration 的 `restoration_gravity_falloff` 是另一条参数，必须在 Angle Restoration 模式显示其最终 strength，不与普通重力箭头混用。

### 保存速度与真实速度

当前语义可以保留，但必须改名和解释：

- **积分速度**（当前“保存速度”）：下一 substep 用于预测的动量速度；由阻尼、重力、摩擦、速度上限和约束对 velocity reference 的修正共同决定。
- **实际位移速度**（当前“真实速度”）：本 substep 最终位置减开始位置再除以 `dt`，包含约束投影后的真实移动。
- 两者差值正是用户判断“想动但被约束、摩擦或限速挡住”的主要信号。

当前已增加黄色的“实际位移速度终点到积分速度终点”差向量；积分速度达到`particle_speed_limit`时改为红色。阻尼不伪装成硬钳制，Fixed粒子没有非零箭头。下一步仍需把不同pass造成差值的真实来源拆开，不能仅凭最终差向量猜测约束责任。

### Distance

Distance 是 PBD/位置投影约束，不是向粒子施加牛顿力。它根据当前边长与 StepBasic/rest 长度误差移动粒子，随后通过 post-step 位置差形成下一步速度，因此会间接改变运动趋势。

Distance现在直接消费A/B phase的有向record结果，不再用最终边长反推pass。每条记录包含稳定index、owner/target、phase前两端位置、有效rest/current length、signed/normalized error、near/active状态和经owner平均后的真实贡献；红箭头与红/蓝线只来自实际active/near记录。A/B不合并，因此碰撞后第二次钳制与第一次修正不会互相抵消。后续增强只剩记录抽样/选择、phase视觉区分和刚度曲线的颜色/透明度编码。

### Tether

当前从 root 到每个粒子画当前线和最小/最大圆环，形成截图中的大量放射线与圆，信息密度失控。

Tether已归因到稳定`vertex/root`记录：默认只显示接近/超过最短或最长界限的记录，pass前当前线、对应边界环与真实correction高亮；未触发且远离边界的root放射线不再铺满屏。后续只需增加选择记录/数值overlay与更紧凑的带/端帽表达。Tether限制的是相对baseline root的整体伸缩，不是相邻边，也不是弹簧力。

### Bending

当前整块 quad 仍画紫/青/红线；新增红箭头显示Bending pass真实逐粒子correction，但无法归因到具体quad，也看不到当前角与rest角。待办：角度记录画共享边、两面法线、rest/current角弧和记录级correction；volume记录单独显示体积误差；默认只画active/near-limit。弯曲刚度为0或topology没有triangle时必须明确无效原因。

### Motion Base、MaxDistance 与 Backstop

MC2 源码明确规定 MaxDistance/Backstop 始终相对动画 BasePose 计算，不受模拟粒子位置驱动。Backstop 球应跟随动画 base 的位置/旋转和法线轴，但不跟随被约束后的粒子。`backstop_distance_curve` 与 `max_distance_curve` 按 `depth²` 采样。

- 粒子移动、动画 base 不动：Backstop 不动是正确行为。
- 动画 base 已移动而 Backstop 不动：需要修复 frame capture/update。
- Motion 当前什么都不画时，优先检查开关、曲线是否为零、setup 是否 BoneSpring、粒子是否有可用 Motion 属性和快照是否在有效 substep 捕获。
- Motion pass的真实逐粒子projection correction现在以红箭头显示。待办：同时画 BasePose、当前粒子和范围；曲线直接体现在每粒子球心/半径；把correction归因到MaxDistance或Backstop，并在接近边界时显示near-limit。

### Angle Limit

当前范围锥仍不显示当前角度或超出多少；新增红箭头来自真实Angle pass逐粒子correction，不能区分Restoration与Limit各自贡献。待办：范围锥降为淡背景；画当前向量、层级目标、当前角弧和limit弧；记录子分支active/near-limit，接近上限为黄。`angle_limit_curve`必须直接改变每粒子的limit弧/锥，`angle_limit_stiffness<1`必须显示“部分修正”而不是假装硬夹死。

### Center、Anchor、惯性与限速

当前 `show_center` 混合组件、Anchor、frame shift 和若干惯性线，仍不能回答 raw movement 如何经过 Anchor 抵消、平滑、World/Local/Depth inertia 与速度限制后成为最终粒子 shift。

待办：分层画 raw component delta、Anchor 抵消、平滑/限速后的 delta、最终 applied shift；移动/旋转限速实际触发时标红；Depth inertia 用粒子颜色或 applied vector 长度表达。Anchor 仍是 task 的 Object 输入，不扩展为通用隐式类型。

### Normal Axis

Normal Axis 是局部 `+/-X/Y/Z` 经 Motion Base rotation 转到世界空间后的方向，当前主要影响 Backstop。它应合入 Motion Base/Backstop 视图，用短方向箭头和正反色表达；不能单独画一堆与功能无关的基轴。

### Centrifugal Acceleration

production context step 没有调用独立 `apply_centrifugal_velocity_mc2` kernel，因此该字段不能作为可用产品参数。现在三个 Profile、三个 Task 节点及其公开 preset 均不包含 `centrifugal_acceleration`；`MC2TaskParametersSpec`、runtime float layout 与 native ABI 仅为兼容保留该槽位，所有公开构造路径保持默认0。Blender property registry 与纯 Python owner 回归同时锁定“公开面无字段、ABI值为0”，接入真实 production consumer 前不得重新公开，也不为它制作 debug。

### Cloth Mass

MC2 `cloth_mass` 只影响自碰/跨布料接触的 inverse mass 权重，不是普通重力或积分的粒子质量。同一 task 内它通常是统一值，Fixed 和摩擦还会进一步改变接触权重。

待办：在自碰接触视图用颜色/点大小显示最终 contact inverse mass 或相对“谁推动谁”，而不是泛称粒子更重；跨 task contact 必须同时显示双方权重。若参数最终移到 Task，名称应强调“自碰质量/交互质量”。

### 曲线参数总表

| 曲线 | 应归入的 debug | 可视编码 |
|---|---|---|
| Damping | 运动趋势 | 积分速度衰减比例/颜色，不伪装为硬钳制 |
| Radius | 碰撞形状 | 实际球/胶囊半径；优化绘制性能 |
| Distance stiffness | 结构约束 | correction 强度、透明度 |
| Angle restoration stiffness | Angle Restoration | target 箭头强度/颜色 |
| Angle limit | Angle Limit | 每粒子 limit 弧/锥大小 |
| Max distance | 动画空间限制 | 每粒子允许球半径 |
| Backstop distance | 动画空间限制 | 每粒子球心偏移 |
| Collision limit | BoneSpring 接触 | soft-sphere 允许位移范围 |
| Self thickness | 自碰形状/接触 | primitive 厚度及实际接触阈值 |

## P1：外部碰撞“实际接触”模式 D-03

`碰撞情况`继续只画可参与碰撞的Point/Edge proxy与collider形状；独立`实际接触`已经接通真实kernel结果，不再从最终normal或位置差反推。

新增反例 D-10：同一个 MeshCloth task 含多个互不连通的网格分量时，`碰撞情况`只画出部分分量，截图中约缺少一半碰撞代理。审计确认final proxy、位置、属性、半径和全局边数组均完整；renderer却在Point模式取前`max_items`个顶点、Edge模式取前`max_items`条边。分量按索引连续排列时，前一分量会吃完预算，后序分量整块消失。当前renderer先从完整final proxy建立连通分量，再保证预算足够时每个分量至少一个样本，并把剩余预算按候选数量分配后在各分量内部均匀抽样。Blender debug runner已覆盖双分量Point/Edge预算分配；真实截图场景仍需手测关闭D-10。

- C++ Point/Edge kernel只在`show_collision_contacts`显式请求时记录primitive kind/index、collider index、接触位置、法线和实际correction；关闭时请求位为false且记录数组为空。
- 请求在下一真实substep前写入context，完成后只读冻结到slot snapshot；same-frame和zero-substep不得伪造contact。
- renderer把接触点、法线、correction和active Point/Edge primitive标红，并只把本帧参与接触的collider表面改红；普通`碰撞情况`中的非活动collider保持蓝色。
- task筛选发生在slot请求与绘制两侧；每个slot只显示自己实际上传并命中的collider identity。
- native Point与Edge单测覆盖真实非零correction和debug-off零记录；Blender隔离模式覆盖请求、冻结、只读数组和至少一个实际contact成功出图。

尚未实现的时间层信息是contact新增/持续/失效与churn计数；它属于D-02一级结果信息架构，不得用闪烁绘制假装完成。性能验收仍要比较debug off/on，胶囊/Edge密集场景单独测量；debug-off零生产是当前硬门禁。

## P2：参数 Profile/Task 归属 D-05

产品决策已经冻结并完成代码迁移。迁移改变authoring owner和UI复用心智，不改变native `ClothParameters` ABI字段顺序，也不把这些值加入task identity或static fingerprint；它们仍通过同一个parameter hot update进入已有slot/context。

### 已执行字段表

| 分组 | 字段 | 最终owner | 产品节点 | 原因与consumer |
|---|---|---|---|---|
| Teleport | `teleport_mode/distance/rotation` | `MC2TaskParametersSpec` | M/C/S Task | 单基准、整task状态转换；不属于逐粒子材料 |
| 组件World/Anchor惯性 | `anchor_inertia`、`world_inertia`、`movement_inertia_smoothing`、`movement_speed_limit`、`rotation_speed_limit` | `MC2TaskParametersSpec` | M/C/S Task | 处理task整体frame/Anchor运动，Center frame shift消费 |
| 组件Local/Depth惯性 | `local_inertia`、`local_movement_speed_limit`、`local_rotation_speed_limit`、`depth_inertia` | `MC2TaskParametersSpec` | M/C/S Task | fixed-step Center correction；depth只是该task内修正权重，不是可复用粒子材料曲线 |
| 离心修正 | `centrifugal_acceleration` | `MC2TaskParametersSpec` | 暂不公开 | 归属组件惯性组，但D-07确认production无consumer；保持ABI默认0直到接通 |
| Motion法线 | `normal_axis` | `MC2TaskParametersSpec` | M/C Task | task的动画姿态轴约定；BoneSpring关闭Motion所以不显示 |
| 自碰交互质量 | `cloth_mass` | `MC2TaskParametersSpec` | M/C Task | task内/跨task接触双方修正比例；BoneSpring关闭自碰所以不显示 |
| 粒子材料与约束 | Gravity、Blend、稳定时间、阻尼、半径、Particle Speed Limit、Distance/Bending/Angle、Motion范围、碰撞摩擦、自碰开关/厚度 | `MC2ParticleProfileSpec` | 按setup裁剪的Profile | 可复用动态风格、逐深度曲线或直接逐粒子/约束consumer |
| task身份/拓扑/输出 | source、Anchor Object、连接模式、碰撞组、输出旋转、启用 | `MC2TaskSpec`/`MC2SetupOptionsSpec` | 对应Task | 已有task身份、拓扑或输出策略，不进入粒子/修正参数块 |

### 唯一owner与preset合同

- `MC2ParticleProfileSpec`不再保存上述Task字段；`MC2TaskSpec.task_parameters`是运行时唯一authoring owner，`make_mc2_runtime_parameters(profile, setup_options, task_parameters)`不得回退偷读Profile。
- Task参数变化只改变`parameter_signature`并走hot update；不得改变`task_id/source_signature/topology_signature/config_signature`，也不得重建proxy/baseline/self topology。
- 三种Profile节点不再显示Task字段。MeshCloth/BoneCloth Task显示Normal Axis、组件惯性、Teleport和自碰交互质量；BoneSpring Task只显示真实消费的组件惯性与Teleport。
- 官方MC2 JSON preset保留同名preset，但按owner拆成Profile部分和Task部分；用户在两个节点应用同名preset即可还原完整源预设。离心力因无consumer不进入公开Task preset。
- 不增加Profile override、Task override优先级或隐藏迁移副本；避免同一值出现两个可编辑来源。

### 自动证据

- `test_task_parameter_ownership.py`锁定Profile无旧字段、runtime唯一读取Task字段、Task参数hot update不改变身份/拓扑/config。
- Blender property registry锁定三个Profile/Task节点的socket子集、枚举说明、preset裁剪和`MC2TaskSpec` schema version 3。
- D-05不需要修改或重编native ABI；现有native参数与Center/Teleport/interaction回归继续验证运行语义。

## P2：重编译保留运行缓存 D-06

### 当前事实

`OmniNodeTree.compile_cached(force=True)` 在新 graph 成功编译并替换 compile cache 后，无条件调用 `OmniRuntimeState.clear_root_tree(self)`。因此点击“编译”总会 dispose Physics World 和所有 root runtime cache。编译失败会保留旧 graph 与 runtime cache；普通 cache hit 也会保留。

MC2 solver 本身已有 task id、参数签名和 static fingerprint，可在下一次运行中区分 hot update、局部 static refresh 和 context rebuild。全树重编译先销毁 world，使这套细粒度机制失去作用，确实妨碍边看效果边调参。

### 不采用“数组范围相同就保留”

仅比较数组长度无法证明安全：节点删除/替换、group path 改变、batch item 重排、对象身份变化、cache owner 类型变化、ABI/schema 变化都可能在相同长度下复用错误状态。

### 建议方案

1. 编译仍先事务性生成新 graph；失败时保持现状。
2. 新旧 graph 生成 runtime-cache compatibility manifest，至少包含稳定 node runtime UID、group/batch namespace path、cache producer 类型与 contract version、owner kind/schema。
3. 对兼容 namespace 保留 committed owner；删除或不兼容 namespace 定向 dispose；无法证明时回退整 root clear。
4. 参数/socket 默认值改变但 cache 节点和路径不变时保留 Physics World，让 solver 的 task/parameter/static fingerprint 决定 hot update 或 rebuild。
5. batch 不能只按 index/长度判断；需要稳定 item identity，无法提供时该 batch namespace 清理。
6. compile graph 的寄存器数组仍由新 graph 自己初始化；保留的是显式 runtime cache owner，不是旧寄存器值。

### 验收矩阵

- 只改 MC2 数值：world identity 保留，参数 revision 增加，模拟连续。
- 改曲线但不改 topology：按参数合同 hot update，不卡回首帧。
- 改 mesh/bone topology：world 可保留，但对应 MC2 slot 安全 rebuild。
- 节点重排/改显示位置：缓存保留。
- 增删不相关分支：只影响对应 namespace。
- 删除/替换 Cache、Physics World 或 solver 节点：旧 owner 定向 dispose。
- group path 改变、batch reorder/length 相同但身份变化：不得错误复用。
- 编译失败：旧 graph 和 runtime cache 完整保留。
- 无兼容 manifest 的旧节点：保守清理，不猜测。

安全优先级高于连续预览，但“每次成功编译全清”不再是唯一安全策略。

## 实施顺序

1. **已冻结决策**：D-04自碰质量与D-08深度已经人工关闭；D-05参数归属已经决策并完成owner迁移。D-01/D-03/D-07代码已关闭或接通，D-02正在分段实施，D-06方向已定，D-09代码已实现待界面复验。
2. **粒子深度调试（已实现并完成首轮手测）**：以显式按需模式展示真实 depth/root/parent 和异常项；首轮非均匀减面验证已确认4:1边界距离修正与1.5次惯性指数有效，后续继续按consumer矩阵调优。
3. **重开验收状态**：自碰静置已经按新不变量重新验收；Teleport和debug usability仍保持撤销verified，等待对应反例关闭。
4. **Teleport 回退（代码已替换，待真实复验）**：任务级首Fixed/对象原点判定、整task Reset/Keep、跨interaction失效和单参考debug已接通；仍需用高速平移/旋转、zero-substep与真实collider关闭反例。
5. **自碰密度最小场景审计（当前关闭）**：一环误碰根因已修，final结果debug已纠正，真实单层模型已收敛；密度量化转为未来回归，不继续无依据扩大k-ring。
6. **非连通碰撞绘制 D-10（代码已修复，待手测）**：已确认renderer前缀截断并改为分量公平抽样；双分量Point/Edge自动回归已通过。
7. **Debug 基础数据合同（结构约束继续关闭）**：五类约束的六个有序pass已稀疏捕获；Tether/Distance已增加稳定记录identity、active/near与真实贡献，debug-off零buffer/零readback；Bending/Angle/Motion记录原因和contact时间层继续实施。
8. **一级视图重画**：运动趋势、结构约束、Motion/Backstop、Angle、惯性、实际接触、自碰结果。
9. **参数长说明同步（代码已实现，待界面复验）**：Profile/Task节点表格由实际字段metadata生成，注册测试防止字段说明漂移；socket只保留短摘要。
10. **参数归属审计（已完成）**：字段表、唯一owner、节点裁剪、preset拆分和hot-update证据已经接通。
11. **兼容重编译缓存**：作为 OmniNode 通用能力单独设计、测试和提交。
12. **真实手动复验**：使用本轮截图资产与最小场景，逐项由用户判断可读性；再跑性能和长跑矩阵。

## 完成定义

- 用户无需阅读 C++ 名词就能从一级 debug 判断启用、接近阈值、触发、修正和最终结果。
- 所有高级中间态都有准确空间/时间语义，静止或不跟随时能解释是合同还是 bug。
- 粒子深度模式能定位 root、连续渐变、局部逆序/突跳与无可达 Fixed，并据此关闭或证实远端异常的 depth 假设。
- Teleport 恢复单基准、整 task 触发模型，并在真实碰撞场景阻止传送产生的高速穿模。
- **已完成**：单层自碰静置质量达标；final洋红intersection为零，剩余红色contact仅位于真实拥挤区且完全收敛。
- 曲线、硬钳制、惯性、法线轴和自碰质量均能在对应结果模式中被观察。
- debug 关闭时不存在为绘制新增的常驻生产、复制或 readback。
- 参数 UI 归属有逐字段事实表，不凭节点拥挤程度迁移。
- 安全兼容的重编译保留 runtime owner；不兼容变化仍可靠 dispose。
