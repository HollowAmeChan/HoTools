# OmniNode BoneCloth 解算器任务大纲

更新日期：2026-07-04

本文是 BoneCloth 解算器的设计蓝图与任务清单，不是完成记录。实现推进后，稳定项应逐步迁进 `MC2_DESIGN_AND_WORKSHEET.md` 的完成度表，本文只保留待做项和设计约定。

MC2 源码对照根目录：`D:\Unity_Fork\MagicaCloth2`
HoTools MeshCloth 现状：`OmniNode/NodeTree/Function/physicsMC2`
SpringBone 骨骼写回参考：`OmniNode/NodeTree/Function/Physics.py` 的 `_BonePhysics`

## 一、目标与范围

### 核心诉求

用户痛点：链骨（hair/tail/skirt 骨链）用现有 SpringBone 或 Line 连接时，只有纵向父子约束，缺横向约束，相邻链之间会穿插、飘散、失去布料整体感。

本任务的核心目标是**还原 MC2 BoneCloth 的 `AutomaticMesh` 自动横向连接**：根据骨骼在空间中的间隔，自动在相邻骨链的同深度骨骼之间生成横向 line 和三角形约束，让多条独立骨链表现为一整片布料。

### 明确要做

1. 单开新节点 `boneClothMC2`（Python 参考）与 `boneClothMC2Cpp`（C++ 后端），与 `meshClothMC2` 平行，不改动现有 MeshCloth 节点。
2. 骨骼 → 粒子采样层（新 I/O adapter）。
3. MC2 四种 `BoneConnectionMode` 拓扑生成，重点是 `AutomaticMesh`。
4. 粒子 → 骨骼旋转写回层（复用 `_BonePhysics` 的 matrix_basis 写回地基）。
5. solver 数组层最大化复用 MeshCloth：距离、角度、弯曲、tether、碰撞、惯性、motion、post。

### 明确不做（本期）

1. **不做 AutomaticMesh 自动横向连接**：拓扑结果对用户是黑盒，无法在节点图里可视化调试，用户无法直观知道哪两根链被连在一起。顺序连接（用户控制 root 列表顺序）可预期、可调试，足以解决横向约束缺失的痛点，暂不引入自动拓扑猜测。
2. 不做 MC2 BoneSpring（那是 Line-only + 各骨独立碰撞的另一套语义，留后续）。
3. 不改 MeshCloth 既有对齐结果；BoneCloth 走独立 builder，只共享 solver kernel。
4. 不做 render mesh 高低模映射；BoneCloth 直接驱动骨骼。
5. 不搬 MC2 全局 TeamManager / 多 center 调度，沿用 OmniNode per-node cache。


## 二、MC2 BoneCloth 机制拆解

### 2.1 BoneConnectionMode 四种模式

来源：`Runtime/Manager/Render/RenderSetupData.cs` L63-80
`Runtime/VirtualMesh/Function/VirtualMeshInputOutput.cs` L478-880

| 模式 | 含义 | HoTools 目标 |
|---|---|---|
| `Line = 0` | 只做纵向父子连接，无横向约束 | **实现**，多链各自独立悬垂的场景 |
| `AutomaticMesh = 1` | 根据 Transform 间隔自动生成横向网格连接 | **不实现**：拓扑黑盒，无法调试 |
| `SequentialLoopMesh = 2` | 按 Root 列表顺序顺次连接，首尾成环 | **实现**，环形裙摆/围脖 |
| `SequentialNonLoopMesh = 3` | 同上但首尾不连 | **实现（核心目标）**，刘海/披肩/尾巴 |

**用户通过 root 列表的顺序直接控制横向连接走向**，不依赖自动拓扑推断。`SequentialNonLoopMesh` 是解决链骨横向缺失的主要模式；`SequentialLoopMesh` 适用于环形布料；`Line` 作为退化 fallback。

**BoneSpring** 是另一个 `SetupType`（非 `BoneCloth`），强制走 `Line` 模式，本期不做。

### 2.2 顺序连接算法（SequentialLoop / SequentialNonLoop）

来源：`VirtualMeshInputOutput.cs` L528-880（顺次连接分支）

HoTools 只实现 Sequential 分支，算法大幅简化：

**纵向边（主边）**
对每条 root 链做 DFS，把每根骨骼与其父骨骼连边，得到 `main_edges`（纵向父子边集合）。

**横向边（顺次连接）**
直接按用户传入 `root_bones` 列表的下标顺序配对，**不做任何距离查找**。用户填入的列表顺序就是横向连接的顺序，与骨骼的空间位置无关。

```
对每对相邻链索引 (i, i+1)：
  chain_i.bones[depth] ↔ chain_{i+1}.bones[depth]
  两边都有对应深度的骨骼时直接连一条横向边。
  某条链到达叶子骨（depth 不足）时，该深度及以下不连横向，各自只有纵向约束。
SequentialLoop 额外连接 (chain_last, chain_0) 的横向。
```

**好处：** 骨骼名通常带有序号（如 `hair_01`, `hair_02`, `hair_03`），用户按顺时针或逆时针序填入 root 列表就能精确控制布料面的走向，完全透明，无黑盒。

**三角形生成（与 MC2 保持一致）**
从 `main_edges`（纵向）+ 横向边中枚举三角形候选：
- 角度 < 120°（`ProxyMeshBoneClothTriangleAngle`）
- 必须至少包含 1 条主边（纵向）
- 不允许三顶点跨越三条不同的 root 链

未进入三角形的边作为独立 line 约束。

> **为什么不做 AutomaticMesh：** MC2 源码（`VirtualMeshInputOutput.cs` L542-612）的贪心排序与环形判断依赖绝对空间位置，用户无从得知最终生成的横向连接是哪些，调试困难。顺序连接的用户心智模型简单：**"我按什么顺序填 root 列表，横向就按那个顺序连"**。

### 2.3 粒子 ↔ 骨骼对应关系

MC2 BoneCloth 中每个 Transform 对应一个粒子，粒子同时有位置（position）和旋转（rotation）。旋转写回时走 `SimulationPostProxyMeshUpdateLine`（`VirtualMeshManager.cs` L790）：

- 有 `baseLine`（纯 line 路径）时，按 baseline 从 root 沿链走，用 `rotationalInterpolation` 系数对旋转做平均化。
- 有 triangle 时，由三角形面法线直接控制旋转，不再走 baseline 平均。

HoTools 的对应策略见下文 §3.5。

### 2.4 BoneCloth 特有参数（MC2 侧）

来源：`Runtime/Cloth/ClothSerializeData.cs` L74-93，`ClothParameters.cs` L63

| 参数 | 类型 | 含义 |
|---|---|---|
| `rootBones` | `List<Transform>` | 多条骨链的根骨骼列表 |
| `connectionMode` | `BoneConnectionMode` | 连接模式枚举 |
| `rotationalInterpolation` | `float (0..1)` | baseline 路径的旋转平均化插值率；0 = 完全由父控制，1 = 完全由子粒子方向控制 |


## 三、HoTools 架构设计与复用边界

### 3.1 模块组织

BoneCloth 作为独立子包，放置在：

```
OmniNode/NodeTree/Function/physicsBoneCloth/
  __init__.py          ← @omni 节点声明，对齐 physicsMC2/__init__.py 格式
  bone_build.py        ← 骨骼 → 粒子拓扑构建（新增；对应 mesh_build.py）
  bone_io.py           ← 骨骼读取 / 姿态写回（新增；含自动横向连接生成）
  state.py             ← BoneClothRuntimeOwner + BoneTopologyState（新增，参考 state.py）
  runtime/
    controller.py      ← 节点运行中控（新增；对齐 physicsMC2/runtime/controller.py 分层）
    restart.py         ← 冷启动重置（新增）
    timing.py          ← debug timing（复用或轻量新增）
  backends/
    selector.py        ← backend 分派（初期只 Python，后期加 CPP）
```

solver kernel、constraints、inertia、collision、baseline、params、math_utils、native_bridge 等全部**直接 import physicsMC2 内的对应模块**，不复制代码。

### 3.2 直接复用的模块（import physicsMC2）

| 模块 | 复用方式 |
|---|---|
| `physicsMC2/solver.py` `solve_meshcloth()` | 直接调用；BoneCloth 的粒子数组与 MeshCloth 格式一致 |
| `physicsMC2/constraints.py` | 直接复用所有约束构建函数 |
| `physicsMC2/baseline.py` | 直接复用 baseline/depth/root 计算 |
| `physicsMC2/inertia.py` | 直接复用；BoneCloth 有同样的惯性/teleport 需求 |
| `physicsMC2/collision.py` | 直接复用碰撞快照与约束投影 |
| `physicsMC2/runtime_params.py` | 参数曲线采样完全复用 |
| `physicsMC2/params.py` | 参数 slot 复用 |
| `physicsMC2/constants.py` | 系统常量复用 |
| `physicsMC2/math_utils.py` | 数学工具复用 |
| `Physics.py` `_BonePhysics` | 骨链采集 `collect_bone_names`、`pose_matrix_from_tail_world`、`matrix_basis_from_pose_matrix` 全部复用 |

### 3.3 新增的核心模块（bone_build.py）

职责：把多条骨链采样成粒子 + 约束数组，同时实现 AutomaticMesh 横向连接生成。

主要函数：

```python
def collect_bone_chains(
    armature_obj, root_bone_names: list[str]
) -> list[dict]:
    """对每条 root 骨链做 DFS，返回骨链列表，每条链含骨名、深度、父子关系。"""

def sample_bone_particles(
    armature_obj, chains: list[dict], scene_frame: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    从当前帧骨架姿态采样粒子：
      positions  : (N, 3) world-space head 位置
      rotations  : (N, 4) world-space 四元数
      depths     : (N,)   整数深度
    """

def build_bone_topo(
    armature_obj, chains: list[dict], connection_mode: int,
    positions: np.ndarray
) -> dict:
    """
    生成拓扑数组，connection_mode:
      0 = Line（纵向父子），1 = AutomaticMesh，2 = SequentialLoop，3 = SequentialNonLoop
    返回 {
      'edges': np.ndarray (M, 2),          # line 约束边
      'triangles': np.ndarray (K, 3),      # triangle 约束面
      'roots': np.ndarray (R,),            # root 粒子索引
      'depths': np.ndarray (N,),           # 每粒子深度
      'parent_indices': np.ndarray (N,),   # 纵向父粒子索引（-1 = root）
      'main_edges': set[tuple],            # 纵向主边集合，供 triangle 筛选使用
    }
    """
```

AutomaticMesh 的六步算法直接在 `build_bone_topo` 内实现，对应 MC2 `VirtualMeshInputOutput.cs` L542-880，三角角度阈值 `120°`（对应 `ProxyMeshBoneClothTriangleAngle`）。

### 3.4 新增的核心模块（bone_io.py）

职责：骨架输入读取 + 模拟结果写回骨骼旋转。

```python
def read_bone_base_pose(armature_obj, bone_names: list[str]) -> np.ndarray:
    """读取骨骼当前 world-space head 作为 base pose 粒子位置。"""

def write_bone_rotations(
    armature_obj, bone_names: list[str],
    display_positions: np.ndarray,
    rotational_interpolation: float,
    parent_indices: np.ndarray,
    depths: np.ndarray,
    edges: np.ndarray,
):
    """
    把模拟后的粒子位置转回骨骼旋转并写入 matrix_basis。

    对 Line 路径（有 baseline）：
      按 root → leaf 顺序，用下一个粒子位置的方向向量，
      调用 _BonePhysics.pose_matrix_from_tail_world 生成目标 PoseBone matrix，
      rotational_interpolation 控制 lerp 程度，
      最后调用 _BonePhysics.matrix_basis_from_pose_matrix 写回。

    对 Triangle 路径（已生成三角形）：
      由三角面法线驱动旋转（后期任务，初版先只做 Line 路径）。
    """
```

### 3.5 BoneCloth 粒子 ↔ 骨骼对应约定

1. 每根骨骼 head 对应一个粒子，粒子位置 = 骨骼 head world-space。
2. 叶子骨没有子骨，其 tail 虚拟粒子用来做骨骼方向计算，**不参与物理推进**（设为 fixed）。
3. root 骨对应 pin 粒子（固定粒子），inertia 由它的 world 运动驱动，不做物理推进。
4. 写回时：对每个非 root 粒子，用 `display_positions[i]` 和 `display_positions[parent[i]]` 的差向量计算方向，复用 `_BonePhysics.pose_matrix_from_tail_world` 生成目标姿态，再用 `matrix_basis_from_pose_matrix` 写入 `pose_bone.matrix_basis`。


## 四、分阶段任务清单

### P0：地基打通（目标：能跑出基础布料效果）

#### P0-1 目录骨架与节点声明

- [ ] 创建 `physicsBoneCloth/` 目录结构（`__init__.py`、`bone_build.py`、`bone_io.py`、`state.py`、`runtime/`、`backends/`）。
- [ ] 在 `physicsBoneCloth/__init__.py` 用 `@omni` 声明 `boneClothMC2` 节点：
  - 输入：`缓存`、`骨架对象`（`bpy.types.Object`）、`根骨骼列表`（`list[_OmniBone]`）、`连接模式`（`int 0-2`，默认 `1 = SequentialNonLoop`）、`旋转插值`（`float 0-1`）、`场景`、`启用`、`重置`，以及所有与 meshClothMC2 共用的物理参数（阻尼、距离、角度、弯曲、tether、惯性、碰撞……）。
  - 输出：`缓存`、`骨架对象`、`骨骼数`、`约束数`。
- [ ] 节点名定义：`bl_label = "骨骼布料-MC2"`。

#### P0-2 骨骼 → 粒子采样（bone_build.py 初版）

- [ ] 实现 `collect_bone_chains(armature_obj, root_bone_names)` 对多条 root 做 DFS，返回带 `{name, depth, parent_index, chain_index}` 的扁平骨骼列表。
- [ ] 实现 `sample_bone_particles(armature_obj, flat_bones)` 读取 world-space head 位置。
- [ ] Line 模式拓扑生成（`connection_mode=0`）：纯父子边，无横向。
- [ ] 把 root 骨设为 pin（固定粒子），其余粒子 mass = 1.0。
- [ ] 在 P0 阶段只完成 Line 模式，验证粒子数组格式与 `solve_meshcloth` 入口兼容。

#### P0-3 运行中控骨架（runtime/controller.py）

- [ ] 复制 MeshCloth controller 的框架：缓存命中/重建、冷启动、solver 调用。
- [ ] 主要差异点：`build_topo()` 调用 `bone_build.py` 而非 `mesh_build.py`；不读取 mesh，只读骨架。
- [ ] BoneClothRuntimeOwner 实现 `omni_cache_dispose`，内部持有 `BoneTopologyState`。

#### P0-4 骨骼旋转写回（bone_io.py Line 路径初版）

- [ ] 实现 `write_bone_rotations()` Line 路径：按 root→leaf 顺序对每根骨调用 `_BonePhysics.pose_matrix_from_tail_world`，再调用 `matrix_basis_from_pose_matrix` 写入 `pose_bone.matrix_basis`。
- [ ] rotational_interpolation = 1.0 时完全由粒子方向控制；= 0.0 时维持 base pose 方向（lerp）。
- [ ] 最后调用 `pose.bones.foreach_set("matrix_basis", ...)` 批量写回，对齐 SpringBone 现有写回方式。

#### P0-5 P0 验收标准

- 单条骨链 `connection_mode=0`（Line），布料能跑出基础悬垂效果。
- Python/C++ parity 测试对象创建，格式对齐。
- debug_output 打印骨骼数、约束数、首帧 max position delta。


### P1：顺序横向连接（目标：多链骨横向约束跑通）

#### P1-1 SequentialNonLoopMesh 拓扑生成（connection_mode=1）

- [ ] 在 `bone_build.py` 的 `build_bone_topo()` 实现 `connection_mode=1`（`SequentialNonLoop`）：
  - 按 `root_bones` 列表下标顺序，对相邻链 `(i, i+1)` 的同深度骨骼配对连横向边。
  - 深度不等长时只连 `min(len_a, len_b)` 层，多出的末端骨不连横向。
  - 主边（纵向父子边）通过 DFS 遍历每条链得到，存入 `main_edges`。
  - 三角形生成：枚举纵向 + 横向边的三角形候选，角度 < 120°、必须含至少 1 条主边、不跨三条链。
  - 未进三角形的边作为独立 line 约束。
- [ ] 把 `edges`、`triangles`、`main_edges` 存入 `BoneTopologyState`。
- [ ] `connection_mode` 枚举映射：`0 = Line, 1 = SequentialNonLoop, 2 = SequentialLoop`（去掉 AutomaticMesh，重新编号以保持用户界面简洁）。

#### P1-2 SequentialLoopMesh（connection_mode=2）

- [ ] 在 P1-1 基础上增加首末链横向连接：`(last_chain, first_chain)` 同深度骨骼配对，与中间相邻链逻辑相同。
- [ ] `loop_connection` 标志控制，不需要另写独立分支。

#### P1-3 三角约束接入 solver

- [ ] 确认 `solve_meshcloth` 的 bend/angle 约束对 BoneCloth 生成的三角形有效（MeshCloth 已支持，验证索引格式一致即可）。
- [ ] `BoneTopologyState` 同时携带 `edges`（line 约束）和 `triangles`（三角约束），对应 `MC2TopologyState` 扩展方式。

#### P1-4 P1 验收标准

- 三条以上骨链在 `SequentialNonLoop` 模式下生成横向约束，布料表面不再各链独立飘散。
- debug_output 可见模式切换前后约束数的差异（Line vs Sequential）。
- 环形（`SequentialLoop`）和非环形（`SequentialNonLoop`）各自测试一个场景通过。
- 拓扑结果可预期：用户改变 root 列表顺序能直接观察到横向连接方向改变。


### P2：骨骼写回完善 + inertia/BasePose 语义

#### P2-1 rotatonal_interpolation 对齐 MC2

- [ ] Line 路径写回支持 `rotational_interpolation` 插值：
  `target_rot = lerp(base_pose_rot, sim_driven_rot, rotational_interpolation)`
  对应 `VirtualMeshManager.cs` L817 的 `averageRate = param.rotationalInterpolation`。
- [ ] 叶子骨（没有子骨）的方向由 `tail_virtual_particle` 提供，不写入物理推进但参与旋转计算。

#### P2-2 BasePose 对齐

- [ ] BoneCloth 的 BasePose 是骨架当前帧的 animated bone pose（骨骼 head world-space），由 Armature + 所有修改器评估后读取，而不是静止 rest pose。
- [ ] 与 MeshCloth 的"双对象读写分离"不同，BoneCloth 的 base pose **直接读当前骨架的 evaluated pose**，不另开只读代理对象（骨骼 head 没有 GN delta 写回问题）。
- [ ] `animation_pose_ratio` 语义：distance rest lerp 在 BoneCloth 中对应骨骼长度（骨与骨之间的 rest 距离），等于每帧与初始 rest length 之间的插值。

#### P2-3 inertia/teleport 对齐

- [ ] BoneCloth 使用与 MeshCloth 相同的 `inertia.py` 惯性计算；center 参考点取 root 骨的 world 位置。
- [ ] 多条 root 骨时，inertia 的 world 运动取所有 root 的平均位移（与 MC2 的 CenterData 语义一致）。
- [ ] teleport 检测：若任一 root 骨帧间位移或旋转超过阈值，触发 teleport 重置。

#### P2-4 P2 验收标准

- BoneCloth 在角色快速移动时惯性表现正确（不飘移、不抖动）。
- `rotational_interpolation = 0` 时骨骼几乎不旋转，`= 1` 时完全跟随粒子方向。
- 前后 BasePose 变换骨架（做动作后）骨布料能正确跟随 base pose 重新稳定。

### P3：稳定性、碰撞 + C++ 后端

#### P3-1 碰撞接入

- [ ] 复用 `physicsMC2/collision.py` 的 collider 快照和约束投影。
- [ ] BoneCloth 碰撞半径来源：从每根参与模拟的骨骼的 `hotools_collision.radius`（与 SpringBone 同来源），不另开 mesh 顶点组。
- [ ] 碰撞 group filter 复用 MeshCloth 机制，不重新设计。

#### P3-2 self collision（缓做）

- [ ] BoneCloth 粒子数量通常远少于 MeshCloth（10-100 个），brute-force point-line 距离检测在大多数场景下足够，暂不接 grid broadphase。
- [ ] 后期如果有密集骨网格场景需求，再评估复用 `mc2_self_collision.cpp`。

#### P3-3 C++ 后端（boneClothMC2Cpp）

- [ ] solver kernel 层：因为 BoneCloth 与 MeshCloth 共用 `solve_meshcloth` 参数结构，`solve_meshcloth_mc2()` 的 C++ 核心直接可用。
- [ ] 只需要在 `bone_io.py` 里在 C++ solver 调用前完成粒子数组的打包，在 solver 调用后完成骨骼旋转写回；写回始终在 Python 侧执行（C++ 不碰 `bpy`）。
- [ ] `boneClothMC2Cpp` 节点声明：复用与 `boneClothMC2` 完全相同的 meta，只修改 `bl_label` 和 backend tag，对应 MeshCloth 的 `meshClothMC2Cpp` 模式。

#### P3-4 P3 验收标准

- Python/C++ parity 测试：同场景同参数下 12 帧 max/RMS delta = 0（对齐 MeshCloth 的测试标准）。
- 碰撞球/胶囊体与骨骼布料正确交互，无穿插。
- 性能：10 条 8 骨链（80 粒子）+ AutomaticMesh 拓扑，每帧 handler 时间 < 5ms（Python）。


## 五、关键设计决策与风险

### 5.1 节点输入：多根骨 + 连接模式

**决策：采用 `list[_OmniBone]` 多重输入作为 `root_bones`，加一个 `int` 枚举 `connection_mode`（0/1/2）。**

`connection_mode` 枚举：
- `0 = Line`：只有纵向父子边，无横向约束
- `1 = SequentialNonLoop`：按列表顺序连接相邻链，首尾不成环（**默认值**）
- `2 = SequentialLoop`：同上但首末链额外成环，用于裙子/围脖等封闭环形

**去掉 AutomaticMesh：** 自动拓扑猜测的结果对用户是黑盒，OmniNode 当前也没有可视化拓扑的交互，出了问题无法定位。顺序模式的心智模型简单——"root 列表顺序 = 布料面横向走向"——用户只需调整列表顺序就能完全掌控拓扑。

理由（复用边界不变）：
- `list[_OmniBone]` 对应 MC2 `SerializeData.rootBones: List<Transform>`，语义一一对应。
- 一次性知道所有根骨才能做顺序连接和三角形生成，不适合在节点图里分多步组合。

**风险：** 用户如果想对不同链用不同参数（刚性、阻尼差异化），目前无法支持。这是有意简化，与 MC2 BoneCloth 统一参数的设计一致。

### 5.2 写回骨骼旋转：仅改方向还是完整 LocRotScale

**决策：只改方向（旋转），保留 base pose 的缩放和 head 偏移，不改 loc。**

理由：
- 粒子模拟的是骨骼 head 的世界位置，骨骼实际平移由父骨的 tail = 子骨的 head 自然决定（connected 骨）。
- 直接把粒子 `display_position` 当 head 写回 loc 会破坏 `use_connect` 骨骼的 connected 关系，引发抽搐。
- 与 MeshCloth 的 GN delta 写回不同，BoneCloth 不需要 delta 容器对象，直接写 `matrix_basis` 即可（与 SpringBone 写回路径完全一致）。
- 参考：`_BonePhysics.pose_matrix_from_tail_world`（`Physics.py` L583）只改旋转不改 loc，这是 HoTools 已验证的稳定路径。

### 5.3 叶子骨与虚拟 tail 粒子

**决策：叶子骨的 tail 方向由 `rest bone length` 估算，作为不参与物理推进的虚拟粒子，仅用于写回方向计算。**

理由：
- MC2 BoneCloth 对 end bone（无子骨）不单独做粒子，其方向由 parent→self 向量外推估算。
- HoTools 的 SpringBone 也有相同约定：骨链末端骨骼方向由模拟的 "virtual tail" 提供，不写入物理推进数组。
- 叶子骨 tail 粒子 `pin = True`（或直接不纳入 solver 粒子，写回时外推）。推荐**不纳入 solver**，写回时用 `head + rest_direction * bone_length` 外推，避免增加不必要粒子。

### 5.4 AutomaticMesh 三角角度阈值

**决策：初版对齐 MC2 固定值 `120°`（`ProxyMeshBoneClothTriangleAngle`），后续可暴露为用户参数。**

风险：稀疏骨链（链间距很大、骨链层数很少）时三角形几乎全部被 120° 阈值剔除，退化为纯 line 效果。此时用户应该改用 `connection_mode=0`（Line）。这与 MC2 的行为一致，不是 bug。

### 5.5 多 root 骨架 BasePose

**决策：BoneCloth 的 base pose 直接读当前帧 evaluated armature pose（骨骼 head world pos），每帧同步，不另开只读代理对象。**

理由：骨骼位置没有 GN delta 写回反馈环问题（写回对象是 `pose_bone.matrix_basis`，读取 base pose 是从 evaluated depsgraph 读骨骼世界矩阵，两者没有循环依赖）。与 MeshCloth 必须双代理隔离的原因不同，BoneCloth 可以直接单对象。

**风险：** 若用户在同一骨架上同时有 BoneCloth 和 GN 修改器写 bone，可能出现求值顺序问题。初版记录为已知限制，不在 P0-P1 处理。


## 六、文件地图

| 文件 | 职责 |
|---|---|
| `physicsBoneCloth/__init__.py` | `@omni` 节点声明：`boneClothMC2` / `boneClothMC2Cpp`，socket 默认值，节点 label |
| `physicsBoneCloth/bone_build.py` | 骨骼链采集、粒子采样、AutomaticMesh 拓扑生成（四种 connection_mode） |
| `physicsBoneCloth/bone_io.py` | 骨骼 base pose 读取、模拟结果写回 matrix_basis（Line 路径 + 后期 Triangle 路径） |
| `physicsBoneCloth/state.py` | `BoneClothRuntimeOwner`、`BoneTopologyState`（边表、三角表、深度、根骨索引、主边集合） |
| `physicsBoneCloth/runtime/controller.py` | 节点运行中控：cache 命中/重建、冷启动、base pose 同步、collider 快照、solver 调用、写回 |
| `physicsBoneCloth/runtime/restart.py` | 首帧 / reset / 非连续帧冷启动状态重置 |
| `physicsBoneCloth/runtime/timing.py` | debug timing，与 MC2 同格式 |
| `physicsBoneCloth/backends/selector.py` | backend 分派（Python / CPP） |
| `physicsMC2/solver.py` | **共用**，不修改，直接 import |
| `physicsMC2/constraints.py` | **共用**，不修改，直接 import |
| `physicsMC2/inertia.py` | **共用**，不修改，直接 import |
| `physicsMC2/collision.py` | **共用**，不修改，直接 import |
| `Physics.py` `_BonePhysics` | **共用**写回工具，不修改，直接 import |

## 七、踩坑预判

### 7.1 骨链深度不对齐时的横向配对

顺序连接时，相邻两条链可能骨骼数不同（一条 5 骨、另一条 3 骨）。横向边只配对到 `min(depth_a, depth_b)` 层，更深的骨只有纵向约束，无横向。**预防策略**：文档里提示用户尽量让各链骨数一致；debug_output 输出各链深度，便于用户检查。

### 7.2 connected 子骨与 matrix_basis 写回

Blender 的 `use_connect = True` 的骨骼不能直接批量写 `PoseBone.matrix`，必须通过 `matrix_basis`。`_BonePhysics.matrix_basis_from_pose_matrix` 已经正确处理了这个问题，但写回顺序必须从 root 到 leaf（父先于子），否则子骨会参考旧父矩阵计算错误。`write_bone_rotations` 里要保证按深度升序写入。

### 7.3 多根骨的 center/inertia 参考点

MeshCloth 的 center 是代理 mesh 对象的 matrix_world origin。BoneCloth 有多条 root 骨，中心点的选择影响 world/local inertia 的计算。初版策略：取所有 root 骨 head 的平均世界位置作为 center origin。后期若有必要可以暴露一个 `anchor_obj` 参数覆盖。

### 7.4 动态骨架拓扑（骨骼增删）

BoneCloth 的拓扑缓存 key 应包含骨骼名称列表的 hash，骨骼增删时强制重建。运行中不支持热改骨架结构，与 MeshCloth 不支持运行中改 mesh 的约定一致。

### 7.5 三角形约束在极端骨链布局下的退化

若两条相邻链的骨骼间距非常大（比链内骨骼间距大很多），三角形的角度会超过 120° 而全部被剔除，退化为纯 line 效果。这种情况下横向约束仍然存在（line 边），但没有面弯曲约束。**预防策略**：debug_output 输出生成的三角形数量，若为 0 且骨链间距过大，提示用户调整骨链布局。

### 7.6 叶子骨 tail 外推精度

叶子骨的 tail 方向用 `rest bone direction * bone_length` 外推估算。若骨骼 rest pose 与当前 animated pose 方向差异极大（超过 90°），外推方向会有明显偏差。初版接受这个限制，记录为已知精度边界；后期若有需求可考虑从上一帧的粒子速度方向做惯性外推。

## 八、与 MC2 源码的对应关系

| HoTools 实现 | 对应 MC2 源码 |
|---|---|
| `bone_build.py:collect_bone_chains` DFS 遍历 | `VirtualMeshInputOutput.cs` L483-492（Line DFS）|
| `bone_build.py:build_bone_topo` 顺序横向配对 | `VirtualMeshInputOutput.cs` L528-533（Sequential 分支逻辑）|
| `bone_build.py` 三角形生成 + 120° 阈值 | `VirtualMeshInputOutput.cs` L769-848；`SystemDefine.cs` L149 `ProxyMeshBoneClothTriangleAngle` |
| `bone_build.py` main_edges 概念 | `VirtualMeshInputOutput.cs` L653 `mainEdgeSet`（三角形至少含 1 条主边）|
| `bone_io.py:write_bone_rotations` | `VirtualMeshManager.cs` L790-860（`SimulationPostProxyMeshUpdateLine`）|
| `rotational_interpolation` 参数 | `ClothParameters.cs` L63；`VirtualMeshManager.cs` L817 `averageRate`|
| `connection_mode` 枚举（0/1/2） | `RenderSetupData.cs` L63-80 `BoneConnectionMode`（对应 Line / SequentialNonLoop / SequentialLoop）|
| root 列表驱动顺序连接 | `VirtualMeshInputOutput.cs` L528-533（`sequentialConnection` 标志分支）|
| AutomaticMesh | **不实现**（参考来源：`VirtualMeshInputOutput.cs` L542-612）|

<!-- APPEND-DONE -->







