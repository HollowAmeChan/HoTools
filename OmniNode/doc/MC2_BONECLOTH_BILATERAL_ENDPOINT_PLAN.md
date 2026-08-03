# BoneCloth 双端点与双边界链规划

> 状态：调研与设计规划
>
> 目标：明确每根骨骼的端点语义，解释双端 fixed 链中段塌软的来源，并确定 MC2、Mesh XPBD 与未来杆链解算路径的边界。

## 1. 结论摘要

### 最新路线决策

双端 fixed 骨链不再作为 MC2 BoneCloth 的内部改造目标。MC2 保留当前面向 MeshCloth 和拓扑深度的语义；双端点、双边界和杆链约束放入新的 `bone_xpbd` 领域。这样不会为了一个特殊拓扑破坏 MC2 的主路径，也能让 XPBD 的合规性、累计 lambda 和迭代结构服务于更多软体对象。

`bone_xpbd` 不是临时旁路，而是 PhysicsWorld 下的正式 solver domain：

- 与普通 Mesh XPBD 共享 XPBD 数值核心和生命周期。
- 一个模拟步可以消费多个 XPBD 域任务，并在同一 PhysicsWorld cache 中统一提交和输出。
- 场通过 PhysicsWorld 的统一 field registry 进入 XPBD frame packet；Mesh XPBD 和 Bone XPBD 都消费同一份场采样结果。
- 显式碰撞体和隐式碰撞体都走 PhysicsWorld 的对象注册，不在 solver 内部偷偷读取 Blender 对象。
- Node 注册、静态编译、帧输入、运行缓存、结果写回和运行中 debug node 与 MC2 保持同一层级的契约。

当前 MC2 BoneCloth 提供轻量的 `tail_absorption` 输出开关，默认开启。开启时，静态注册阶段把 `output_source_elements -> output_endpoint_source_elements` 编译成一对一的专用 child 图，让骨骼 tail 只朝向为它记录的下一粒子；它不复用 baseline 父子图，也不会在分支处平均多个 child。关闭时保留粒子平移和三角面姿态，但不再用记录端点修正骨骼轴向。该开关不新增粒子、不改变 `N + 1` 共享端点布局，也不改 depth、tether 或任何 solver 约束。

未来 `bone_xpbd` 的 tail 吸附属于显式 `head_particle/tail_particle` 写回契约，不能与 MC2 这个输出开关混为一谈。前者允许每根骨骼拥有独立端点；后者只是在现有 MC2 共享端点拓扑上选择是否消费已经记录的下一粒子。

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

### 2.2 当前写回仍必须以端点对为最终几何来源

写回骨骼时，骨骼的世界头部和世界尾部应该直接来自对应模拟端点。Blender 的父子层级只用于把世界姿态反算为 `PoseBone.matrix_basis`，不应再次决定模拟线段的长度、方向或尾端位置。

这也解释了过去出现的“尾端突出”“末端上一根骨骼没有旋转吸附”等现象：只要写回过程中重新依赖父链，就会把模拟端点几何重新折叠回 Blender 的层级语义。

### 2.3 MC2 的深度是结构数据，不只是 UI 曲线

本地 `D:\Unity_Fork\MagicaCloth2` 的关键语义如下：

- `VirtualMeshProxy.CreateTransformBaseLine()` 以 Transform 父子层级创建 BoneCloth baseline。
- `CreateVertexRootAndDepth()` 为移动点寻找单一 root，并沿单条路径累计 root length 生成 depth。
- `TetherConstraint` 每个移动点只保存一个 `vertexRootIndex`，约束只朝该 root 投影。
- integration、inertia、mass、damping、wind 等阶段会读取 depth。
- distance、angle、bending 的逆质量和摩擦权重也会读取 depth 或其偏移量。

本项目的 native 构造虽然已经改为从最终 proxy 图生成 baseline，并用固定边界的图距离修正 depth，但当前仍保留单 parent、单 root 的运行时结构；并且 parent depth 权重仍然高于固定边界距离。它比原生 Transform baseline 更接近 MeshCloth，但还不是双边界模型。

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

`head_particle` 和 `tail_particle` 可以在严格共点时指向同一物理点，也可以指向两个独立物理点；这个选择必须由拓扑构造显式决定，不能由 Blender 的 parent/use_connect 隐式决定。

### 4.2 共点策略需要显式化

未来有两种合法实现，先通过测试选择，不在当前代码中偷偷混用：

1. **规范化共点**：真实几何完全共点时复用一个粒子，另加 segment/joint 元数据保证两根骨骼的端点关系。
2. **独立端点 + weld 约束**：每根骨骼拥有独立 head/tail 粒子，再用显式 weld 或 joint 约束保持共点。

对 `use_connect=False`，默认不能因为父子关系就合并端点。只有 rest pose 几何和拓扑规则明确要求共点时才允许复用。MC2 不为此增加新的端点模式。

### 4.3 pin 语义

骨骼 pin 是端点属性：

- pin 的骨骼默认同时固定其 head 和 tail。
- 末端补充粒子继承末端骨骼 pin。
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

- 当前共享端点的 BoneCloth。
- 显式端点映射但仍使用 MC2 单 root 的 BoneCloth。
- 相同粒子、边和 fixed 边界的 MeshCloth/未来 XPBD 试验图。

只有当三组对照的残差、耗时和中段偏移都有记录后，才能判断问题主要来自端点模型、MC2 depth，还是 solver 收敛。

## 6. 分阶段实现路线

### 阶段 A：固定 MC2 边界，建立迁移诊断

- 保持 MC2 的现有 `N 个骨骼头 + 终端粒子` 和单 root 语义，不在 MC2 内引入 2N 端点。
- MC2 只增加 `tail_absorption` 写回开关；它必须默认开启，并进入 setup signature，但不得进入 solver 参数表或改变静态拓扑。
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

### 阶段 C：实现 `bone_xpbd` 基础领域

推荐顺序：

1. 在 Mesh XPBD 生命周期上增加 `bone_xpbd` setup adapter、static fragment、frame packet 和 output target。
2. 每根骨骼注册显式 head/tail 粒子；拓扑使用 segment stretch、二阶 bend、pin 和可选 weld。
3. 将 `tail 吸附`作为写回和姿态输入语义，而不是 solver 内部的隐式父子关系。
4. 一个 XPBD 模拟步支持多个 mesh/bone 域任务，统一生成 field sampling batch、collision object batch 和 output cache。
5. 所有显式/隐式碰撞对象统一走 PhysicsWorld registry；Python 只负责注册与调度，采样和约束在 native 侧执行。
6. 增加运行中 `Bone XPBD Debug` node，显示真实端点、stretch/bend 残差、pin/weld 状态、tail 吸附状态和场采样贡献。

这些改动属于 XPBD domain 的图和约束扩展，不是 Python 侧补丁；运行中的采样和缓存仍必须由 C++ 持有。

### 阶段 D：XPBD 与 MC2/场的统一能力

`bone_xpbd` 完成基础领域后，再把它与普通 Mesh XPBD、MC2 和 Field registry 做能力矩阵：

- 粒子：显式 segment endpoints。
- 约束：stretch、左右边界、二阶 bend、可选 twist。
- 数值：XPBD compliance、累计 lambda、substep/iteration。
- 输入：统一 field sample、显式/隐式 object registry、多任务 batch。
- 输出：同一套 `BoneSegment` 端点写回契约。

Mesh XPBD 目前是 Mesh 输入的独立 vertical slice，没有 Bone adapter，不能直接替换当前 BoneCloth。它的 XPBD compliance/lambda、迭代结构和场输入契约将作为 `bone_xpbd` 的数值基础。

Jolt 仍保持刚体/关节领域，不作为该软体链问题的直接替代。

## 7. 需要保留的设计质疑

以下问题在没有 S0-S5 数据前不应提前定案：

- 每根骨骼是否应使用独立的 2 个粒子，还是严格共点处复用粒子并用 weld 约束。
- 双端 fixed 的 tether 是“两个固定边界的距离上限”，还是只保留结构边和弯曲约束而不使用 tether。
- depth 是否只作为可视化/高级材料 profile，还是允许用户显式启用 solver mass weighting。
- 骨骼扭转是否需要第三类方向参考；单纯 head/tail 两点只能确定轴向，不能唯一确定绕轴 roll。
- 两端固定链的“中间软”有多少是物理材料表现，多少是约束迭代不足；两者必须通过零重力和残差读数区分。
- 同一 graph component 内多个 fixed 岛屿的 root、tether 和写回所有权如何定义。

## 8. 验收标准

MC2 阶段的验收对象只是 `tail_absorption` 输出开关，不是内部端点重构：默认开启、可关闭、设置进入稳定签名，关闭后模拟粒子和约束结果不变，仅写回姿态不再消费下一粒子。后续 `bone_xpbd` 的验收仍要求显式 tail 粒子参与 XPBD 求解，但写回可选择不强制吸附到 Blender 骨骼姿态。

端点和求解器扩展完成后，至少满足：

- 每根骨骼都有稳定、可序列化的 `head_particle/tail_particle` 映射。
- 端点 pin 的语义不依赖 Blender 父子级，末端粒子继承正确。
- 改变 Blender 父子组织但保持最终 proxy 图不变时，模拟结果不变，只有局部矩阵反算路径可以变化。
- S0 中 rest pose 不自发塌陷；S2 的下垂由明确的 bend/compliance 参数解释，而不是隐藏 depth 权重。
- 双端 fixed 链的左右边界影响对称；调试数据能显示每个粒子到两侧边界的贡献。
- 关闭 depth profile 曲线不会继续隐式改变 BoneCloth 的 solver mass/constraint weighting，除非用户显式开启高级选项。
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
