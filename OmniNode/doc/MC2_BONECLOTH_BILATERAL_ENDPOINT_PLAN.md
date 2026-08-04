# BoneCloth 双端点与双边界链规划

> 状态：MC2 边界与源码回退已冻结，py311/py313 发布库均已更新并通过安装路径回归；Bone XPBD 实验性 vertical slice 与统一 XPBD 调度入口已落地；Field、multiscale chord/rod 与生产冻结仍待完成
>
> 目标：明确每根骨骼的端点语义，解释双端 fixed 链中段塌软的来源，并确定 MC2、Mesh XPBD 与未来杆链解算路径的边界。

## 1. 结论摘要

### 最新路线决策

双端 fixed 骨链不再作为 MC2 BoneCloth 的内部改造目标。MC2 已恢复并冻结经典 Transform baseline、单 root/depth、Line 姿态输出和 Connected rotation-only 兼容语义；双端点、双边界和杆链约束放入新的 `bone_xpbd` 领域。这样不会为了一个特殊拓扑破坏 MC2 的主路径，也能让 XPBD 的合规性、累计 lambda 和迭代结构服务于更多软体对象。

`bone_xpbd` 不是临时旁路，而是 PhysicsWorld 下的正式 solver domain：

- 与普通 Mesh XPBD 共享 XPBD 数值核心和生命周期。
- 现有 `XPBD模拟步`可以消费多个强类型 Mesh/Bone XPBD 域任务，并在同一 PhysicsWorld cache 中统一提交和输出；每个 task 仍持有独立 slot/native context，不表示已建立融合粒子域。
- 场接入路线已冻结为 PhysicsWorld 公共 native runtime；当前 Mesh XPBD/Bone XPBD 尚未消费 Field，后续必须在 native XPBD 子步从当前粒子位置采样，不能恢复 Python sampler。
- 显式碰撞体和隐式碰撞体都走 PhysicsWorld 的对象注册，不在 solver 内部偷偷读取 Blender 对象。
- Node 注册、静态编译、帧输入、运行缓存、结果写回和运行中 debug node 与 MC2 保持同一层级的契约。
- Python 不提供备用粒子求解器；它只负责 Blender 边界、任务分流、生命周期、结果发布与调试，数值推进只发生在共享 native XPBD context。

骨骼的 tail 吸附是 `bone_xpbd` 的输入开关：默认开启，表示骨骼 tail 参与端点姿态吸附；关闭时仍保留 tail 粒子和拓扑，只是不把 tail 的模拟姿态强制吸附回 Blender 骨骼，从而允许用户处理头尾不连续或需要独立尾端的骨链。

MC2 BoneCloth 不提供该开关，也不为双端链增加特殊 depth、tether、写回或端点模式。继续保留的独立修复只有：真实 Bone Pin 进入 Fixed、末骨 Pin 传给 solver 终端粒子，以及回帧/重启时清除旧写回反馈。

当前问题不是单一参数没有调好，而是三个结构同时叠加：

1. 当前 BoneCloth 对外已经暴露了每根骨骼的起点和终点索引，但静态粒子仍按“每根骨骼一个头部粒子，加整条链一个终端粒子”存储。骨骼之间的端点由图连接共享，不是每根骨骼都拥有一对独立且明确的 `(head, tail)` 端点。
2. MC2 的 baseline、parent、tether 和部分约束权重是单根路径语义。对一个两端 fixed 的链，中间粒子只有一个 root 和一个 parent，无法表达“同时受左右两个固定边界约束”的对称距离。
3. 关闭用户可见的深度曲线，只会关闭曲线采样；native 侧仍会把 depth 用于惯性、阻尼、质量、tether root、距离约束逆质量和弯曲约束逆质量。因此中段仍可能比端部软。

所以目前不应直接判断“MC2 完全不能做 BoneCloth”，也不应立即用 Jolt 替换它。更准确的判断是：

- MeshCloth 形态、开放骨链和带明确固定根的离散表面，MC2 仍可作为现有解算路径。
- 两端固定、近似一维、要求中段保持杆/绳形态的对象，MC2 的单根深度模型不是理想模型；该对象进入新的 `bone_xpbd`，不再通过 MC2 内部补丁解决。
- Jolt 是刚体和关节解算器，不是 MC2 的布料替代品。把每根骨骼做成刚体再串 joint 是另一种产品语义，暂不作为本问题的直接方案。

## 2. 当前实现的事实

### 2.1 端点并非真正的 `2N` 粒子

当前主要路径位于：

- `OmniNode/PhysicsWorld/mc2/topology.py`
- `OmniNode/PhysicsWorld/mc2/setups/bone_cloth/static_build.py`
- `OmniNode/PhysicsWorld/mc2/setups/bone_cloth/static_fragment.py`

静态构造过程对一条包含 `N` 根真实骨骼的链大致生成：

```text
真实粒子：bone_0.head, bone_1.head, ..., bone_(N-1).head
终端粒子：bone_(N-1).tail
```

输出层再把第 `i` 根骨骼映射到 `particle[i]` 和 `particle[i + 1]`。因此“每根骨骼使用两个模拟点”在输出接口上成立，但目前的存储契约仍是 `N + 1` 个共享端点，而不是每根骨骼独立的 `(head_i, tail_i)` 记录。

这个共享设计对于严格共点的连续链是节省粒子的，但它隐含了一个危险假设：下一根骨骼的头部就是上一根骨骼真实的尾部。对 `use_connect=False` 的骨骼、非共点骨骼、分支图和未来横向连接，这个假设不能继续作为隐式规则。

### 2.2 当前写回保持经典兼容语义

MC2 BoneCloth 继续使用 Line baseline 的 child 图和 `rotational_interpolation/root_rotation` 派生姿态。`use_connect=False` 的骨写回位置与旋转；`use_connect=True` 的骨受 Blender 固定骨长和父尾子头关系约束，只写回旋转。该模式不能保证每根骨骼的 head/tail 都精确贴合两个独立模拟端点，这是冻结的兼容限制，不再在 MC2 内修补。

需要以两个最终世界粒子严格反算每根骨骼平移、轴向与 roll 的对象，必须使用 `bone_xpbd` 的显式 `BoneSegment(head_particle, tail_particle)` 输出契约。

### 2.3 MC2 的深度是结构数据，不只是 UI 曲线

本地 `D:\Unity_Fork\MagicaCloth2` 的关键语义如下：

- `VirtualMeshProxy.CreateTransformBaseLine()` 以 Transform 父子层级创建 BoneCloth baseline。
- `CreateVertexRootAndDepth()` 为移动点寻找单一 root，并沿单条路径累计 root length 生成 depth。
- `TetherConstraint` 每个移动点只保存一个 `vertexRootIndex`，约束只朝该 root 投影。
- integration、inertia、mass、damping、wind 等阶段会读取 depth。
- distance、angle、bending 的逆质量和摩擦权重也会读取 depth 或其偏移量。

本项目的 BoneCloth native 构造保持经典 Transform baseline：parent/root/depth 来自输入骨链父级，proxy edges 在稳定 ABI 中保留，但不参与 BoneCloth depth。终端 fixed 只固定该终端粒子，不会把整条链改写成双固定边界距离场。

### 2.4 当前求解迭代对长双端链不够强

`cpu_native_kernel.py` 的主顺序是：

```text
积分 -> tether -> distance -> angle -> bending -> distance -> motion
```

全局结构约束目前只有一轮固定调度，distance 只是前后各执行一次，angle 自身有内部迭代，但没有一个对整组结构约束反复收敛的统一 substep/iteration 循环。对于长链的两端边界，约束误差需要从两端向中间传播，多轮迭代不足时，中段会表现出明显柔软。

若链没有三角形，通常也没有 MeshCloth 意义上的面弯曲约束；它主要依靠距离和角度约束。关闭角度恢复或把角度刚度设得很低后，在重力下出现 U 形下垂是物理结果，不应直接当作 bug。但在零重力、静态端点和完全匹配 rest pose 的测试中，仍然出现大幅中段误差，就属于模型或实现问题。

## 3. 双端 fixed 的问题分类

需要把现象分成三类，否则容易用错误的参数掩盖不同问题。

### A. 几何映射错误

- 骨骼真实 tail 没有独立的模拟端点。
- 输出端点通过 `source + 1` 隐式推导。
- 写回时再次使用 Blender 父链，导致端部或中间骨骼偏离模拟线段。
- 终端粒子 pin 继承、输出粒子索引或缓存失效。

这类问题应在静态注册、输出映射和写回契约中解决，与刚度参数无关。

### B. 双边界约束表达不足

- 一个移动粒子只有一个 root 和一条 tether 路径。
- 中间粒子没有“到左固定边界”和“到右固定边界”的双重约束。
- parent depth 的方向性会让左侧影响优先传播到右侧，反之则不对称。

这类问题需要改图数据和约束语义，不能只调 depth curve。

### C. 数值收敛或材料参数不足

- 长链只有少量全局迭代。
- 距离约束允许较大误差，角度恢复刚度偏低。
- 质量、阻尼、惯性或 bending inverse mass 通过 depth 把中段变软。
- 在有重力时，真实材料本来就会下垂。

这类问题需要在受控测试中测量残差，再决定是增加迭代、改 compliance，还是调整材料默认值。

## 4. `bone_xpbd` 端点契约

### 4.1 显式端点映射

`bone_xpbd` 的静态数据不允许依赖 `source + 1` 推导，而是为每根真实骨骼保存明确的记录：

```text
BoneSegment {
    bone_id
    head_particle
    tail_particle
    rest_head_world
    rest_tail_world
    fixed_head
    fixed_tail
}
```

每个有效骨段的 `head_particle` 和 `tail_particle` 是两个显式端点；不同骨段的端点在 rest 几何严格共点时可以指向同一物理粒子。共享关系必须由拓扑构造显式决定，不能由 Blender 的 parent/use_connect 隐式决定。

### 4.2 共点策略需要显式化

当前产品已经选择第一种实现；第二种只保留为未来独立约束扩展，不能在当前代码中偷偷混用：

1. **当前：规范化共点**。真实 rest 几何在容差内共点时直接复用一个粒子；每根骨仍保留显式 segment 端点索引。
2. **未来候选：独立端点 + weld 约束**。每根骨骼拥有独立 head/tail 粒子，再用显式 weld 或 joint 约束保持共点；当前 native 尚无该约束族。

Bone XPBD 只接受 `use_connect=False`。任一输入骨 `use_connect=True` 都在注册阶段报错，因为 Blender 的 Connected 位置约束与显式 head/tail 世界姿态写回不兼容；不会为它提供 rotation-only 特判或静默断开。对合法输入，父子关系本身不会合并端点，只有 rest pose 几何和拓扑规则明确要求共点时才允许复用。MC2 不为此增加新的端点模式。

### 4.3 pin 语义

骨骼 pin 是端点属性：

- pin 的骨骼默认同时固定其 head 和 tail。
- 末端无需“补充粒子继承”特判：末骨 tail 本来就是显式端点，随该骨 Pin 一起固定。
- 如果未来允许只固定一端，必须在端点层面表达，而不是复用一个 bone-level bool。

### 4.4 写回语义

每根骨骼写回时：

1. 读取其 `head_particle` 和 `tail_particle` 的最终世界位置。
2. 用两点直接构造骨骼世界平移和方向。
3. 用骨骼静态 roll/参考轴补齐绕骨轴的旋转。
4. 将完整世界矩阵反算到 PoseBone 局部矩阵。

任何父子层级遍历只允许出现在 Blender 矩阵反算阶段，不允许参与模拟几何推导。

## 5. 受控诊断矩阵

在改解算器之前，先建立最小可重复测试。所有测试都应从 PhysicsWorld cache/native readback 取得数据，不能在 Python 侧另写一套采样或修正器。

### 5.1 几何和数值基线

测试对象：直线链 `N = 2, 4, 8, 16`，两端 fixed，所有骨骼 `use_connect=False`，rest pose 与模拟初始 pose 完全一致。

逐项记录：

- 两端固定误差。
- 每条 segment 的 rest length 误差。
- 中点到直线/基线的偏移。
- 每个关节的角度误差。
- particle 的 parent、root、depth、到左/右 fixed 的图距离。
- tether 是否命中、修正量和目标 root。
- distance、angle、bending 每轮的最大修正量。
- 实际全局结构迭代次数和耗时。

### 5.2 场景组

| 场景 | 重力 | 角度恢复 | tether | depth 权重 | 目的 |
| --- | --- | --- | --- | --- | --- |
| S0 | 关闭 | 关闭 | 关闭 | 关闭 | 验证静态 rest pose 不自发塌陷 |
| S1 | 关闭 | 开启 | 关闭 | 关闭 | 单看角度约束能否保持双端直线 |
| S2 | 开启 | 开启 | 关闭 | 关闭 | 测量材料导致的真实下垂 |
| S3 | 开启 | 开启 | 开启 | 关闭 | 判断单 root tether 是否引入方向性 |
| S4 | 开启 | 开启 | 开启 | 开启 | 对比现有深度质量/惯性影响 |
| S5 | 开启 | 开启 | 开启 | 开启 | 与 MeshCloth 等粒子数的窄条带结果对比 |

S0 是分界测试：如果 S0 中段仍然明显偏离 rest pose，优先修几何映射、端点共享或约束收敛；不能先改材料默认值。

### 5.3 对照对象

至少需要三组对照：

- 冻结的经典 MC2 BoneCloth，只作为限制基线。
- 共享端点或 weld 的 `bone_xpbd` 方案。
- 独立 2N 端点的 `bone_xpbd` 方案，以及相同粒子/边/fixed 边界的 Mesh XPBD 对照。

只有当三组对照的残差、耗时和中段偏移都有记录后，才能判断问题主要来自端点模型、MC2 depth，还是 solver 收敛。

## 6. 分阶段实现路线

### 阶段 A：固定 MC2 边界，建立迁移诊断

- 保持 MC2 的现有 `N 个骨骼头 + 终端粒子` 和单 root 语义，不在 MC2 内引入 2N 端点。
- 不再修改 MC2 的 baseline、depth、tether、Line 姿态、Connected 写回或公开参数；MC2 只接受回归修复，不接受双端特化。
- 增加一份只读诊断，记录双端链在 MC2 中的残差和限制，用作 `bone_xpbd` 的对照基线。
- 固化 S0-S5 的自动测试和一份最小 Blender 工程。
- 记录当前版本基线，包括帧耗时和各约束修正量。

阶段 A 完成前，不调整 MC2 默认刚度，也不把双端对象偷偷切换到 MC2 的特殊分支。

### 阶段 B：建立跨 solver 的端点写回契约

- 在 PhysicsWorld 公共契约中定义 `BoneSegment(head_particle, tail_particle)`，由 `bone_xpbd` 实现，不改 MC2 的内部粒子布局。
- 结果写回一律使用显式 head/tail 对；Blender 父子层级只参与世界矩阵反算。
- `tail 吸附`作为显式输入开关，默认开启；关闭时 tail 仍是 solver 粒子，但不写回 tail 吸附姿态。
- 明确独立端点、共点 weld、pin 继承以及删除/重建生命周期。
- 用非共点、分支和双端 fixed 工程验证父子层级不再改变 `bone_xpbd` 模拟几何。

### 阶段 C：实现 `bone_xpbd` 基础领域（实验纵切面已落地）

当前已经完成：

1. 独立 `bone_xpbd` domain 与四个 Bone 节点：面板对象、自定义对象、任务、可视化调试。Bone task 接入现有共享 `XPBD模拟步`，不另设 Bone solver 节点。
2. 每根骨显式 `head_particle/tail_particle`；rest 几何共点直接共享粒子，segment stretch 与共享关节两侧的二阶 distance bend 均为无向约束，不生成 depth/root/父到子方向。
3. 公共 Bone Pin 或自定义对象 socket Pin 同时固定该骨的两个端点；共享 Mesh XPBD native context 增加独立 moving Pin target，不改变 constraint rest length；`use_connect=True` 在注册阶段严格拒绝。
4. `Tail吸附`默认开启且可关闭，只控制 head->tail 输出旋转；同一 Armature 的全部目标先合并，再由公共 Bone batch writeback 反算 basis。
5. 每个任务拥有 PhysicsWorld slot/context，已覆盖 staged replacement、same-frame、暂停、restart、task prune、失败丢弃和上一帧写回反馈隔离；共享 `XPBD模拟步`可强类型分流并推进多个独立 Mesh/Bone task。
6. 公共 collider snapshot 的四类外碰和请求驱动的真实运行端点/Fixed/segment/bend 调试已接通。

当前仍未完成：

- 几何共点目前是直接合并粒子，不是独立 `2N + weld`；native 没有第三类 weld/joint constraint。
- 外碰半径和 16-bit mask 仍是 task 统一值，不是逐骨/逐粒子 mask。
- Mesh XPBD 与 Bone XPBD 已共用一个用户可见模拟步，但没有组成跨类型融合 native domain，也没有跨 task 约束或自碰。
- Field Wind 尚未接入 XPBD native 子步，调试也没有场贡献。
- MC2、SpringBone 与 Bone XPBD 同时目标同一 PoseBone 时，公共 owner 仲裁尚未定义；当前必须由图作者避免重复目标，不能把 result 发布顺序覆盖当成正式能力。
- 当前只有局部 stretch 与二阶 distance bend，不等价于 rod/shape matching。13 点双端 fixed 探针在 4 substeps、64 iterations、120 帧后仍有约 `0.146` 中点下垂，最大相邻长度误差约 `0.001`；后续先固化 fixture，再决定 multiscale chord 或正式 rod 约束。

当前实现与后续验收的权威细节转入 `BONE_XPBD_BLUEPRINT.md`。这些能力必须继续属于 XPBD domain 的 native 图和约束扩展，不能回到 MC2 depth 特化或 Python 逐帧修形。

### 阶段 D：XPBD 与 MC2/场的统一能力

`bone_xpbd` 完成基础领域后，再把它与普通 Mesh XPBD、MC2 和 Field registry 做能力矩阵：

- 粒子：显式 segment endpoints。
- 约束：stretch、左右边界、二阶 bend、可选 twist。
- 数值：XPBD compliance、累计 lambda、substep/iteration。
- 输入：统一 field sample、显式/隐式 object registry、多任务 batch。
- 输出：同一套 `BoneSegment` 端点写回契约。

Mesh XPBD 与 Bone XPBD 当前共享 `XPBD模拟步`和底层 XPBD distance context，但仍是两类强类型任务和独立 slot/context。这个统一入口不能直接替换 MC2 BoneCloth，也不表示两者已经拥有跨 task 约束或融合粒子域。

Jolt 仍保持刚体/关节领域，不作为该软体链问题的直接替代。

## 7. 需要保留的设计质疑

以下问题在没有 S0-S5 数据前不应提前定案：

- 独立 `2N + weld` 是否值得新增第三类约束族；当前产品已冻结为严格共点处直接共享粒子。
- 双端 fixed 的 tether 是“两个固定边界的距离上限”，还是只保留结构边和弯曲约束而不使用 tether。
- 骨骼扭转是否需要第三类方向参考；单纯 head/tail 两点只能确定轴向，不能唯一确定绕轴 roll。
- 两端固定链的“中间软”有多少是物理材料表现，多少是约束迭代不足；两者必须通过零重力和残差读数区分。
- 跨 solver 同一 PoseBone 的目标所有权如何由 Physics World 公共仲裁。该合同必须同时覆盖 owner identity、冲突策略、调试、Bake/Record 与生命周期，不在 Bone XPBD 内私自实现。

## 8. 验收标准

本阶段验收对象是 `bone_xpbd`，不是 MC2 内部端点重构。`tail 吸附`必须默认开启且可关闭；关闭后 tail 仍参与 XPBD 求解，但写回不得强制把 tail 吸附到 Blender 骨骼姿态。

端点和求解器扩展完成后，至少满足：

- 每根骨骼都有稳定、可序列化的 `head_particle/tail_particle` 映射。
- 端点 Pin 的语义不依赖 Blender 父子级，末骨 tail 作为显式端点随该骨一起固定。
- 所有输入骨均为 `use_connect=False`；改变 Blender 父子组织但保持最终 proxy 图不变时，模拟结果不变，只有局部矩阵反算路径可以变化。
- S0 中 rest pose 不自发塌陷；S2 的下垂由明确的 bend/compliance 参数解释，而不是隐藏 depth 权重。
- 双端 fixed 链的左右边界影响对称；调试数据能显示每个粒子到两侧边界的贡献。
- Bone XPBD 不产生或消费 depth；MC2 的 depth 行为只作为冻结对照，不得迁移进 Bone XPBD 参数。
- 运行时所有数据来自 PhysicsWorld cache/native readback，Python 只负责注册、调度和显式调试显示。
- 需要更强杆链语义时，有清晰的独立 XPBD/rod 迁移边界，不把 Jolt、MC2 和 Mesh XPBD 的所有权混在一起。

## 9. 参考实现位置

- 项目 BoneCloth 静态拓扑：`OmniNode/PhysicsWorld/mc2/topology.py`
- 项目 BoneCloth 静态构造：`OmniNode/PhysicsWorld/mc2/setups/bone_cloth/static_build.py`
- 项目 BoneCloth 输出映射：`OmniNode/PhysicsWorld/mc2/setups/bone_cloth/static_fragment.py`
- 项目 MC2 native depth/约束：`_native/src/mc2_static_build.cpp`、`_native/src/mc2_domain_cpu.cpp`
- 项目 CPU 调度：`OmniNode/PhysicsWorld/mc2/cpu_native_kernel.py`
- 项目 Mesh XPBD 契约：`OmniNode/doc/MESH_XPBD_BLUEPRINT.md`
- 本地 MC2 baseline：`D:\Unity_Fork\MagicaCloth2\Runtime\VirtualMesh\Function\VirtualMeshProxy.cs`
- 本地 MC2 tether：`D:\Unity_Fork\MagicaCloth2\Runtime\Cloth\Constraints\TetherConstraint.cs`
- 本地 MC2 距离/角度约束：`D:\Unity_Fork\MagicaCloth2\Runtime\Cloth\Constraints\DistanceConstraint.cs`、`AngleConstraint.cs`
