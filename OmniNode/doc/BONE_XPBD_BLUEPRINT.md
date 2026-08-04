# Bone XPBD 基础领域蓝本

本文记录 Physics World 中独立 `bone_xpbd` solver 的当前理念、已落地纵切面、明确限制和下一阶段边界。公共帧时间、slot、结果流、写回和资源释放规则以 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 为准；MC2 为什么不继续承担双端 fixed 骨链，见 `MC2_BONECLOTH_BILATERAL_ENDPOINT_PLAN.md`。

截至 2026-08-04，`bone_xpbd` 已是注册表可发现的实验性 vertical slice，不再是“尚未实现”的规划项；但它还没有 Field 消费、逐粒子碰撞掩码、独立 weld 约束或 rod/shape-matching 约束，因此不能标记为冻结产品。

## 1. 产品定位

Bone XPBD 把骨链视为 Mesh XPBD 的离散骨段版本：骨骼代表一段由两个粒子定义的几何区域，模拟图由最终 rest 几何建立，而不是由 Blender 父子方向或 MC2 depth 建立。

首版坚持以下原则：

- 每根实际模拟骨骼都有显式 `BoneSegment(head_particle, tail_particle)`；不能用 `source + 1`、父骨或 child 顺序推导 tail。
- 几何上严格共点的端点可以共享同一粒子；是否共点只由显式输入和 rest 几何决定。
- solver 图没有 `depth`、单一 `root`、tether root 特权或父到子的单向传播。
- Bone Pin 固定该骨段的 head 和 tail；根骨不会被自动固定。
- Tail 吸附只控制输出姿态，不改变粒子拓扑、Pin 或数值求解。
- 首版复用现有 Mesh XPBD 的 stateful native distance context，不复制第二套 Python 数值 solver，也不为了 Bone 新建同构 C++ kernel。
- solver step 只发布公共 Bone 批写回命令；真实 `PoseBone.matrix_basis` 由 Physics World 公共 writeback 执行。

这套语义服务于双端 fixed、无单根方向、希望左右边界对称影响的离散链。符合经典单根 baseline 的开放骨链仍可使用 MC2 BoneCloth；VRM 资产语义仍归 SpringBone VRM；刚体加关节仍归 Jolt。三者不能通过参数名伪装成同一个产品。

## 2. 当前用户链路

Bone XPBD 自己注册四个节点；数值推进复用现有公共 `XPBD模拟步`，不再注册第五个 Bone 专用 solver 节点：

```text
实际 Bone 列表
  -> Bone XPBD对象（读取公共 Bone 面板 Pin）
     或 Bone XPBD自定义对象（socket 显式覆盖 Pin）
  -> Bone XPBD任务
  -> XPBD模拟步的“XPBD域任务”输入 + Physics World
  -> Physics Writeback

XPBD模拟步 + Physics World
  -> Bone XPBD可视化调试
```

- `Bone XPBD对象`只接受显式 Bone socket 集合。输入表示真实模拟骨，不解释为 MC2 控制骨，也不隐式扩张成整条父子链。
- `Bone XPBD自定义对象`使用 socket 为该对象中的 Bone 显式提供统一 Pin 值，不再回读面板 Pin；面板对象与自定义对象是两种完整且互斥的属性来源。
- `Bone XPBD任务`附加 Tail 吸附、统一外碰、统一粒子半径、阻尼、stretch/bend compliance、迭代和重力。
- `XPBD模拟步`的“XPBD域任务”输入可以同时接收多个强类型 Mesh XPBD task 与 Bone XPBD task。入口先按任务类型完整校验和分流，再调用对应 domain；它不会把两类 payload 猜测或强制转换成同一种任务。
- 统一的是用户可见的调度入口、失败清理和 Physics World 结果提交，不是 native 状态所有权。每个 task 仍拥有独立稳定 slot 与 native context，不存在跨 task 约束、自碰或融合 context。
- `Bone XPBD可视化调试`按需读取 production slot 的冻结快照，不运行 shadow solver。

本阶段保留原 `physicsMeshXpbdSolver` 函数名与节点 `bl_idname`，但模拟步第二个输入的 socket identifier 由 Mesh 专用的 `mesh_tasks` 改为通用的 `xpbd_tasks`。这是一次已记录的破坏性节点合同调整：已有实验性 XPBD 树需要重新连接该输入并重新编译，不保留隐藏 alias 或 payload 兼容层。

这一链路没有 Python 数值 fallback。Python 只负责 Blender 输入解析、强类型调度、slot 生命周期、结果发布与显式调试；粒子积分和约束求解只走共享 native XPBD context。

## 3. 显式 BoneSegment 与几何共点共享

### 3.1 静态记录

当前 `BoneXpbdSegment` 为每根骨骼保存：

```text
BoneXpbdSegment {
    bone_name
    parent_name       # 只供 Blender 姿态反算/记录，不生成物理方向
    pose_index
    head_particle
    tail_particle
    rest_length
}
```

`endpoint_particles[N, 2]` 是权威端点映射。写回、调试和未来约束都必须读这张表，不能根据粒子连续编号猜测端点。

### 3.2 当前共点算法

拓扑构造先为每根骨生成两个 raw endpoint，再在不同骨段端点之间比较 Armature rest 几何：

1. 距离小于等于 `weld_tolerance` 的端点可以进入同一个并查集；任何 union 都必须保证同一骨段的 head/tail 不会直接或借第三端点传递落入同一分量。
2. 每个集合压缩成一个真实粒子；其 rest position 是集合内 raw endpoint 的平均值。
3. 每根骨段生成一条无向 stretch pair。
4. 两个骨段恰好共享一个粒子时，在两个非共享端点之间生成一条二阶 distance bend。

默认连续的 `N` 段共点链因此得到 `N + 1` 个粒子，但每根骨仍显式映射两个索引。非共点骨即使互为父子也不会被连接；父子排列不会生成新的物理边。

当前产品严格拒绝任一输入骨骼 `use_connect=True`。Blender 的 Connected Bone 把子骨 head 硬绑定到父骨 tail，无法同时兑现“每骨由模拟 head/tail 世界位置独立反算平移和旋转”的写回契约；因此注册阶段直接报错，用户必须先关闭 `use_connect`。这不是求解器中的特殊拓扑模式，也不会退化为 MC2 的 rotation-only 写回。

当前字段名 `weld_shared_endpoints=True` 表示“几何共点时直接共享同一粒子”，不是“独立 `2N` 端点再增加 weld 约束”。当前 `joint_constraint_count` 为 `0`，native 也只有 stretch 和 bend 两组 compliance/lambda。该内部开关尚未作为节点 socket 暴露；在没有第三类 weld/joint 约束前，不能把独立 `2N` 模式描述成已支持产品。

### 3.3 无 depth 与无父级方向

`parent_name` 只在最终 Blender 局部矩阵反算中帮助解析父目标；它不参与：

- 粒子合并；
- stretch/bend 生成；
- inverse mass；
- root/depth/tether；
- 约束求解顺序或权重。

当前二阶 bend 是共享关节两侧端点间的普通距离约束，不是角度约束、二面角、扭转、杆单元或 shape matching。节点、统计和调试必须保持这个名称边界。

## 4. Pin、逐帧姿态与 Tail 吸附

### 4.1 Pin 双端语义

面板对象的 Pin 从 Physics World 公共 `Bone.hotools_collision.pin` 及隐式 Bone override 解析；自定义对象则完全采用 socket 提供的显式 Pin，不二次回读面板。一个对象只使用其中一种属性来源。某根骨为 Pin 时：

- `head_particle` 和 `tail_particle` 的 inverse mass 都设为 `0`；
- 共点粒子只存在一份，因此相邻骨共享的该端点也成为 Fixed；
- 不自动固定集合根骨，也不把 Pin 转换成 depth 权重；
- 末骨无需额外“终端粒子继承”补丁，因为末骨 tail 本来就是显式端点。

Bone-level Pin 当前就是整段固定。未来若需要只固定 head 或 tail，必须新增端点级公开属性和静态签名，不能暗改现有 bool 的含义。

拓扑必须另外保存逐骨段的只读 `segment_pins`，并让它参与 static signature。不能通过“该骨两个端点当前是否都是 Fixed”反推骨级 Pin：共享端点可能让一根 Move 骨的两个粒子都因相邻 Pin 而变成 Fixed，但这根骨仍不拥有 Pin 的完整姿态硬目标。

共享焊接粒子同时收到 Pin 与 Move 端点贡献时，运动学目标只取拥有显式 `segment_pins` 身份的 Pin，Move 不能参与平均或覆盖。多个显式 Pin 指向同一粒子时，它们的场景世界目标必须在当前数值尺度的浮点可表示精度内一致，否则 prepare 显式报冲突；不得用 rest 共点容差、`weld_tolerance` 或目标平均掩盖不一致。

Pin 开关属于静态拓扑/质量身份。它改变即使没有改变最终 `inverse_masses` 数组，也必须触发 staged replacement，重建 topology、native context 与 Pin 锚点；该切换不承诺沿用旧速度或做到无缝过渡。

### 4.2 Pin 最终 Pose 优先

Pin 不只是两个质量为零的粒子，也是独立于所选父骨求解结果的完整最终姿态硬锚。锚点内部以 Armature Pose 空间矩阵保存；因此父骨后续移动不会拖动自身通道未被直接编辑的 Pin，但当帧 `Armature.matrix_world` 仍作为外层变换生效，乘上它以后才得到场景世界目标。每帧必须按以下顺序构造输出：

1. 先根据本帧 topology 得到明确的骨级 `segment_pins`，再开始反馈采集；
2. 先由当前 RNA `location / rotation / scale` 通道得到 canonical basis；restart 必须结合本批完整父目标图递归重建最终 Pose，禁止在同一回调中读取可能尚未刷新的 `PoseBone.matrix`；
3. Pin 首次进入、restart 或自身 L/R/S 通道发生真实外部修改时，刷新该骨的完整 Armature Pose 锚点；只有父骨变化或上一帧 solver 写回时，不得被动改写这份独立锚点；
4. 先把所有 Pin 骨的完整 Pose 放进最终目标表，Pin 输出完整硬 Pose，不经过 `head -> tail` 方向重建，也不受 Tail 吸附开关影响；
5. 再从模拟粒子重建非 Pin 骨；
6. 同一 Armature 的完整最终目标表就绪后，统一反算全部 `matrix_basis`，最后由公共 writeback 原子提交。

因此“先固定 Pin”指先建立完整目标图，不是先逐根写入 Blender 再读取父子结果。后者会重新引入顺序依赖和 solver 自反馈。

当前反馈身份只覆盖 PoseBone 的直接 L/R/S 通道，不消费 Constraint/IK 求值后的最终矩阵。注册集合中的任一 PoseBone 含任意 Constraint/IK 时，当前版本必须显式拒绝，不能静默忽略、冻结成错误锚点，或回退为读取 evaluated `PoseBone.matrix`。

### 4.3 Moving Pin 不改变 rest

Bone XPBD 复用 `MeshXpbdContextV1`。共享 native context 已把两类位置拆开：

- `rest_positions`：建立 stretch/bend rest length，只在静态 reference 更新时改变；
- `pin_positions`：Fixed 粒子当前待消费的动画目标，通过 `update_pin_targets()` 更新；
- `last_step_pin_positions`：上一次成功完成真实 step 后的 Pin 目标，只由 step 提交，不由属性同步提交。

`update_pin_targets()` 会立即把 inverse mass 为 `0` 的 position/previous position 同步到当前目标，并递增 `pin_target_update_count`，使暂停帧和 same-frame 只读结果不会滞后；但它不前移 `last_step_pin_positions`。真实 step 的第 `i` 个子步使用 `i / substeps`，从上一次成功消费的目标线性推进到当前目标，最后一个子步精确到达当前目标；只有整次 step 成功且结果有限时才提交新的历史。same-frame 重复更新只覆盖当前待消费目标，不能把前一次更新伪装成已经模拟过的时间。reset/reference replacement 会同步两端历史，避免冷启动插值穿过旧世界状态。

这条时间语义同时保证高速动画 Pin 不会在第一个子步瞬移并向相邻自由粒子注入单次大约束冲量。它不调用 `update_reference()`，不重建 constraint rest length。Bone adapter 在正常帧先提交当前逻辑动画姿态的 moving Pin，再推进 native；restart 则从当前逻辑姿态 reset，并再次提交 Pin 目标。

这项分离是 Bone XPBD 能复用 Mesh XPBD kernel 的必要条件。禁止为移动 Pin 每帧重建 topology/rest，也禁止在 Python 逐粒子采样后修改 native position。

### 4.4 Tail 吸附

`tail_follow` 默认开启，且只作用于非 Pin 骨：

- 平移始终来自模拟 `head_particle`；
- 开启时，以模拟 `head -> tail` 方向对齐骨骼 Y 轴，并从输入姿态保留参考 roll/scale；
- 关闭时，仍写模拟 head 平移，但保留输入旋转；tail 粒子仍参与 stretch、bend、Pin、碰撞和积分。
- Pin 骨始终直接采用完整最终 Pose，不通过粒子线段重新推导旋转或平移。

因此 Tail 吸附是输出姿态策略，不是“是否创建 tail 粒子”、是否连接骨链或是否固定端点的开关。

## 5. 共享 XPBD native 数值边界

当前 Bone adapter直接调用：

```text
mesh_xpbd_create_context_v1(
    world_positions,
    inverse_masses,
    stretch_indices,
    bend_indices,
    collision_radii,
    damping,
    stretch_compliance,
    bend_compliance,
    iterations,
)
```

底层保持严格 XPBD 累计 lambda、每个 substep 清零 lambda、iterations 内累计、compliance 为 0 时硬距离约束的 Mesh XPBD 合同。Bone 只提供不同的拓扑、逐帧端点输入和姿态输出，不新增平行 kernel。

参数变化走 native hot update；拓扑、Pin 或半径变化走 staged context replacement。native context 不保存 Blender pointer，不写 PoseBone，不读取父级或 depth。

## 6. Physics World slot、反馈与公共批写回

### 6.1 Slot 与帧决策

每个显式 Bone 集合使用稳定 `bone_xpbd:{armature_ptr}:{armature_data_ptr}:{source_signature}` slot。当前生命周期包括：

- 全批只读 prepare topology、pose frame、collider frame，并为需要替换的 task 预建 context；
- generation、restart、topology、Pin/半径或 native owner 失效时 staged replacement；
- 纯参数变化热更新；
- same-frame 和 `dt <= 0` 只读并重发，不推进数值状态；
- task 删除时 prune/dispose slot；
- 任一 attempted task 失败时清除本 solver 的 partial result，dispose 本批 attempted slot，下一次冷建；
- world dispose 释放 native owner，调试 store 由 solver 注册的 dispose hook 清理。

公共 `XPBD模拟步`可以在一次调用中处理多个 Mesh/Bone 强类型 task，但各 task 是独立 context。共享入口不意味着共享粒子域，当前尚无跨 task 约束、自碰或锁步融合 context。

### 6.2 写回反馈隔离

PoseBone 当前 RNA 可能仍包含 Bone XPBD 上一帧写回。如果把它当成新动画输入，会形成“读自己的输出再积分”的反馈。`bone_xpbd.frame_state` 因此记录 source、Pin 的独立 `source_pose_matrix`、pending 与 confirmed basis：

- solver 发布 result 时只建立 pending 指纹；公共 Bone 写回整组成功后产生 `bone_writeback_receipt_v1`，下一次采集只有匹配该 receipt 才把 pending 提升为 confirmed；
- 写回身份通过 `location / rotation / scale` 独立通道重建的 canonical basis 比较，不直接比较可能含 shear、受父级非均匀 scale 重解释的 `PoseBone.matrix_basis`；
- 当前通道 basis 与上一份 confirmed 写回相同时，采集逻辑输入姿态而不是把 solver 输出当动画；Pin 同时恢复自己的完整最终 Pose 锚点；
- 用户动画真正改变自身 L/R/S canonical basis 时，以新输入为准；Pin 据此刷新独立 Armature Pose 锚点，所选父骨结果单独变化不算 Pin 自身编辑；
- frame jump 可以只转移轻量 feedback 状态，不复制 slot/native/result；
- restart 清理后只从当前 RNA 独立 L/R/S 通道 basis 与本批完整父目标图递归重建 source/Pin 最终 Pose；禁止读取同一回调中可能陈旧的 `PoseBone.matrix`。单位矩阵也是合法输入，不能用“是否为单位矩阵”猜测并恢复旧 source；
- reset、scope restart 和 dispose 清理反馈。

反馈 stage 与结果发布一起原子提交 pending；parse、prepare、family 或发布中途失败必须保留进入本批前的反馈 owner。公共写回失败不产生 receipt，因此不能前移 confirmed，也不能把仍留在 Blender 的旧物理输出误认成新动画 source。同帧重复发布使用单调 `publication_id`，旧 receipt 不能确认新 pending。匹配键同时包含 Armature 对象/数据双指针；公共 receipt store 每个 solver/slot 只保留最新成功项，但不得按任意全局数量上限淘汰尚未消费的 slot 成功凭据。当前 receipt 随 Physics World 生命周期释放；未来若清理已确认或已删除 slot，只能按显式确认/失效身份精确删除。

### 6.3 公共 Bone 批写回

solver 先放入同一 Armature 上所有 Pin 骨的完整最终 Pose，再生成非 Pin 目标；所有 task 的目标 Pose matrix 合并完成后，才统一反算每根 `PoseBone.matrix_basis`。这样 Pin 不受粒子线段的欠约束旋转重建影响，子骨反算也能看到同批父骨的目标矩阵，而不是依赖 Blender 中尚未写入的中间状态。

成功 task 发布 `bone_transform_batch` 到公共 `bone_transform` result channel；`Physics Writeback` 才实际写 Blender。solver 不 inline 写 PoseBone；`use_connect=True` 已在注册阶段拒绝，因此不存在 MC2 rotation-only 回退。任一目标重叠、引用失效或发布失败，本批不得产生部分 Blender 写回，也不得产生成功 receipt。receipt 只保存 solver/slot/transaction/publication/Armature 双指针等纯值身份，不持有 RNA、plan 或 matrix。

当前严格合同要求每根写回骨的 Pose 祖先链只使用有限、非零、均匀 scale；叶骨自身的有限非奇异 L/R/S 不属于这条早期禁令。即使 `inherit_scale` 理论上能够隔离部分父缩放，首版也不建立例外。对象注册和每帧 feedback 准备都会检查祖先链，注册后被动画改成非法值也会在 native step 前显式报错。

最终目标表完成后，每根骨先反算 `matrix_basis`，再分解并重建 Blender 实际可保存的 canonical L/R/S basis，最后用同一份完整父目标表正向重建 Pose。round-trip 最大矩阵误差超过数值容差时，prepare 必须以“需要 shear、超出 Blender L/R/S 可表示范围”拒绝整批写回，不能发布近似 basis。这样未选祖先、继承模式或其它 evaluated 变换造成的不可表示 shear 也不能静默破坏 Pin；工具层矩阵换算能够往返某个输入，不等于 Bone XPBD 注册合同承诺接受该输入。

### 6.4 跨 solver 同骨目标所有权

本阶段只保证 Bone XPBD 自己的同 Armature 多 task 目标合并、重叠拒绝和批写回原子性；它没有实现 Bone XPBD、MC2、SpringBone 或未来 solver 同时写同一 PoseBone 时的公共所有权仲裁。现有 result stream 的发布顺序覆盖行为不是所有权模型，图作者目前必须避免跨 solver 重复解算同一骨骼。

正式仲裁必须在 Physics World 公共契约中统一定义 owner identity、优先级或冲突错误、作用域、调试信息、Bake/Record 语义和生命周期，再由所有 Bone writer 一起接入。不得只在 Bone XPBD 内加入私有抢占规则，也不得把该后续项写成当前已支持能力。

## 7. 碰撞合同

当前 Bone XPBD 复用 Mesh XPBD 的公共 collider frame，来源只能是 `PhysicsWorldCache.collider_snapshot`。已接四类外碰：`SPHERE`、`CAPSULE`、`PLANE`、`BOX`。

首版碰撞语义有意保持简单：

- `particle_radius` 是 task 统一半径；关闭碰撞时所有粒子半径为 0。
- `collided_by_groups` 是 task 统一 16-bit mask；`0` 明确表示不接受外部碰撞。
- 同一 Armature 的公共 Bone collider 只排除本 task 正在模拟的 Bone，不应把整副 Armature 的其它 collider 一并删掉。
- native context 当前接收一个 task mask，没有逐粒子/逐骨 mask。

因此公共 Bone 面板上每骨的 `collided_by_groups` 尚未逐粒子保真进入 Bone XPBD。需要该能力时应扩展 native per-particle mask 数组及 static dirty 合同，不能在 Python 按骨拆 context 或把多个 mask 合并成伪精确结果。

## 8. Field 接入边界

当前节点、task、adapter 和 native step 都没有 Field 输入；`BONE_XPBD_SOLVER_DECLARATION.planned_produces` 只把公共 Wind 原生响应列为计划。任何文档或 UI 都不得把 Bone XPBD 描述为已经吃风场。

正确的后续接入方式是：

1. 从 Physics World 公共 field runtime cache 借用 `NativeFieldRuntimeV1` handle，并在 native 调用内取得 `shared_ptr` lease。
2. native context 持有可复用的 Field sample scratch/output，不把 positions 读回 Python。
3. 每个真实 XPBD substep 用当前 native positions 采样，并使用 `frame_context.sample_time_seconds` 与 FPS 派生的 `frame_step_dt/substep` 时间；禁止墙钟和私有累计时钟。
4. Bone 粒子没有 Mesh surface normal，首版响应应定义为通用空气速度到粒子速度的各向同性耦合，不直接复制 MC2 的法线/切线表面模型。
5. 强度为 0 时完全跳过 runtime acquisition/sample，并保持确定 no-op。

Field evaluator、Volume、scope、participation 和生命周期继续归 Physics World 所有。Bone XPBD 只能声明并消费公共 ABI，不能复制 evaluator 或新增私有 wind 参数。

## 9. 运行中调试

当前 `Bone XPBD可视化调试` 只在用户开启任一视图后请求下一次 production step 捕获；solver 每步一次性消费请求，节点仍开启时会在下游重新请求下一步，节点删除或停止执行后不会遗留持续读回：

- 当前 world positions；
- Move/Fixed inverse mass；
- 明确的骨级 `segment_pins`；
- 显式 BoneSegment head/tail；
- 二阶 distance bend；
- frame decision、Tail 吸附、粒子/骨段数与 native stats。

全部视图关闭时清除 capture 和 draw store；world 销毁时同步移除对应 store/handler。调试节点不读 native 私有 handle，不重跑求解，也不根据 Blender 父子骨猜测模拟图。

尚未完成的调试项包括逐约束残差、共点集合/weld 状态、实际碰撞接触、逐粒子 mask 和 Field contribution。它们必须来自 production native 快照，不能由最终姿态反推。

## 10. 双端固定数值探针与算法边界

对当前共享 XPBD distance context 做过一个离线 13 点直链探针：两端 Fixed，使用硬相邻 stretch 与硬二阶邻点 distance，重力开启，4 substeps、64 iterations，运行 120 帧后：

- 中点 Z 下垂约 `0.146`（观测值约 `-0.1463`）；
- 最大相邻段长度误差约 `0.001`。

该探针说明两件事：

1. 当前 context 可以稳定运行共享端点、双端 Fixed 的链，且局部长度误差已经很小。
2. “局部长度几乎正确”不等于“全局形状像杆”。顺序 Gauss-Seidel 的相邻/二阶距离约束在有限迭代、重力和长波形变下仍允许可见中段下垂。

这个数字目前是设计探针，不是冻结 golden：对应 fixture、单位、dt 和产品默认参数尚未完整固化到仓库，不能把 `0.146` 直接当作所有链的验收阈值。

后续增强有明确边界：

- **Multiscale chord**：增加 2、4、8...跨度的无向 chord distance，可以加速长波误差传播并改善双端对称；但它会改变材料刚度、约束数和性能，不能偷偷塞进现有 bend 默认值。若进入产品，必须有独立构造规则、compliance、stats/debug 和 golden。
- **Rod/shape matching**：需要显式弯曲、方向 frame、可能的 twist 和杆段形状保持时，应新增 native constraint family 或新的 context layout。仅用 head/tail 两点不能唯一确定绕轴 roll。
- **不做的方案**：不恢复 depth/tether 单根方向，不在 Python 每帧拉直中段，不用极高 iterations 掩盖错误模型，也不为双端链回头改 MC2。

首版 vertical slice 的验收目标是几何和生命周期正确，不承诺任意长链都具备杆刚度。只有固化 S0（零重力 rest）、重力下垂、镜像对称、长度残差和规模性能后，才能决定 multiscale chord 是否足够，还是需要正式 rod solver。

## 11. 当前能力矩阵

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 显式 BoneSegment | 已实现 | 每骨稳定 head/tail 索引 |
| 几何共点共享 | 已实现 | rest tolerance 合并为同一粒子；不是 weld 约束 |
| 无 depth/父级方向拓扑 | 已实现 | parent 只参与最终 basis 反算 |
| Pin 双端 | 已实现 | 公共 Bone Pin；显式 `segment_pins` 身份；根不自动 fixed |
| Moving Pin | 已实现 | 共享 native `update_pin_targets()`；成功帧之间按子步插值，不改 rest length |
| Pin 完整最终 Pose | 已实现 | 独立 Armature Pose 硬锚；Armature 对象变换仍生效；Pin 先进入目标表，不走 head-tail 重建；全表统一反算 basis |
| Pin 锚点刷新与 restart | 已实现 | 仅自身 L/R/S 外部修改刷新；restart 从通道 basis 与完整父目标图重建，不读陈旧 `PoseBone.matrix` |
| 共享粒子 Pin 冲突 | 已实现 | 显式 Pin 优先于 Move；多个 Pin 只允许浮点精度内一致，否则 prepare 报错 |
| Pin 开关切换 | 静态重建 | 进入 static signature 与 staged replacement；不承诺无缝保留旧动态历史 |
| Tail 吸附 | 已实现 | 默认开；只控制非 Pin 骨的输出旋转吸附 |
| XPBD stretch/bend | 已实现 | 严格累计 lambda；bend 为二阶 distance |
| 强类型统一 XPBD 模拟步 | 已实现 | 一个现有 `XPBD模拟步`接 Mesh/Bone task；先校验分流，不设 Bone 专用 solver 节点 |
| 多 Bone task 单步 | 已实现 | 每 task 独立 slot/context，无跨 task 约束 |
| `use_connect=True` | 明确拒绝 | 注册阶段报错；不提供 rotation-only 或隐式断开兼容 |
| 选中 PoseBone Constraint/IK | 明确拒绝 | 当前只消费直接 L/R/S 通道，不读取 evaluated Pose 作为隐式兼容 |
| 写回骨祖先非均匀/奇异 Pose scale | 明确拒绝 | 注册与逐帧准备检查祖先链；叶骨自身及其它有效目标另做 L/R/S 往返验证 |
| Physics World slot/事务 | 已实现 | staged replacement、same-frame、restart、prune、失败丢弃 |
| 公共 Bone 批写回 | 已实现 | 同 Armature 先合并目标再反算 basis |
| 写回反馈隔离 | 已实现 | pending/confirmed + 公共成功 receipt；失败不前移指纹 |
| 最终 Pose L/R/S 可表示性 | 已实现预检 | 完整目标图反算后做 canonical basis round-trip；需要 shear 的整批写回显式拒绝 |
| 运行调试节点 | 基础已实现 | 一次性请求；粒子、Fixed、segment、bend、状态；残差等仍缺 |
| 四类公共外碰 | 已实现 | task 统一半径与 16-bit mask |
| 逐粒子/逐骨碰撞 mask | 未实现 | 需要 native 数组 ABI |
| Field/Wind 原生子步消费 | 未实现 | 必须直接接公共 runtime，不走 Python sampler |
| 跨 solver 同骨所有权仲裁 | 后续公共契约 | 当前禁止图中重复目标；不能在 Bone XPBD 私有实现 |
| 独立 `2N + weld` | 未实现 | 当前没有第三类 joint/weld 约束 |
| Multiscale chord | 研究项 | 先固化对称/下垂/性能 fixture |
| Rod/shape matching/twist | 不属于当前 kernel | 需要新增 native constraint family/layout |

## 12. 下一阶段优先级与验收

1. py311/py313 隔离构建、C++ core 与 `update_pin_targets` 数值/ABI 回归已经通过；两个 ABI 的发布库均已覆盖，并从 Blender 4.5.8 安装路径复跑导入、反馈、节点、写回和属性注册闭环。
2. Blender 双端 Fixed 自动闭环已覆盖创建、连续 step、same-frame、暂停、回帧 restart、Tail 吸附开关、`use_connect=True` 拒绝、多 task、task prune 和失败事务；`OMNI测试.blend` 的直接 Pin、中控父骨与真实 13 骨注册形态各完成 360 帧高速运动自动 soak。交互式甩动仍需作为发布前人工验收保留。
3. 把 13 点探针写成可重复 fixture，记录零重力 rest、重力下垂、左右镜像误差、最大 stretch/bend residual、iterations/substeps 曲线和耗时。
4. 将公共 Field Wind 接到 native XPBD substep，同时给 Mesh XPBD 使用相同响应 ABI；先做 no-op、确定性和作用域矩阵，再开放 UI。
5. 依据探针决定是否增加独立 multiscale chord；只有它无法满足目标时才设计 rod/shape-matching layout。
6. 逐粒子碰撞 mask、接触调试和 Field contribution 调试随对应 native ABI 一起完成，不先做 Python 伪实现。

冻结前至少满足：所有输入骨均为 `use_connect=False`，父子级重排但最终 rest 几何相同时模拟图不变；Pin 双端和 Tail 吸附语义稳定；双端链左右镜像误差有量化门槛；Field 采样全在 native 子步；所有结果通过公共批写回；两套 Python ABI、Blender 4.5.8 产品场景和长时间 soak 均有记录。跨 solver 同骨所有权仲裁在公共合同落地前，不计为 Bone XPBD 私有完成项。

## 13. 实现入口

- Domain 声明：`OmniNode/PhysicsWorld/bone_xpbd/declaration.py`
- 对象与任务：`object_spec.py`、`specs.py`、`authoring.py`
- 显式端点拓扑：`topology.py`
- 逐帧姿态与 Tail 吸附：`pose.py`
- 共享 native adapter：`native.py`
- Slot、结果事务与调试捕获：`solver.py`
- 写回反馈：`feedback.py`
- 公共 Bone 批写回计划：`results.py`
- 用户节点与视口调试：`nodes.py`、`debug_draw.py`
- 共享 native context：`_native/include/hotools_mesh_xpbd.hpp`、`_native/src/mesh_xpbd.cpp`、`_native/src/mesh_xpbd_bindings.cpp`
- 当前合同测试：`bone_xpbd/test/test_contract.py`、`bone_xpbd/test/test_blender_solver_writeback.py`、`_native/tests/test_mesh_xpbd_core.cpp`、`_native/tests/test_mesh_xpbd_native.py`
