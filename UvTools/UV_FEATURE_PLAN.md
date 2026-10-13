# UV 工具调查与实现方案

调查日期：2026-10-13。范围：调查与规划六项功能，并建立可复现的兼容基线。
随后按用户要求提前实现“拓扑堆叠”，仅提供同形状同点数的强制顶点对齐。
实现与用法见 `stack.py`、`TOPOLOGY_STACK.md`。持续目标阶段又完成镜像、平移及
对齐修复，见 `transform.py`、`UV_TRANSFORM.md`。线展开与阈值直化也已实现，
见 `straighten.py`、`unwrap.py`、`UV_STRAIGHTEN.md`；下文保留初次调查和设计依据。

## 结论与优先级

六项都值得做，但不能把选择解析、岛识别、链路排序分别复制到六个操作符里。
先建立并测试 `Utils/mesh_uv.py`。用户更新优先级后，拓扑堆叠已提前独立实现；
镜像、平移、现有对齐修复、线展开与自动直化已完成对应实现及两版验证。

最有价值的是：同步开关两边行为可靠、多物体一致、展开不无故翻面、对称堆叠有
稳定且可指定的对应关系。镜像和平移难度低；多线约束和对称岛匹配是主要难点。

## 本机调查与复现

实际运行的版本：

- `D:/Blender/blender-4.5.8-windows-x64/blender.exe`：4.5.8 LTS，hash d7359176d0d3。
- `D:/Blender/blender-5.2.0-windows-x64/blender.exe`：5.2.0 LTS，hash fbe6228777e7。

可复现脚本：`tools/probe_uv_compat.py`。使用独立的 `--background --factory-startup`
进程，不加载或修改用户当前场景。它包含 API 契约测试，并记录现有对齐缺陷。
缺陷观察不是未来功能的验收测试，脚本成功退出不表示对齐功能正常。
最终 API 契约测试：4.5.8 为 4 项通过、1 项因该版本无同步有效性 API 跳过；
5.2.0 为 5 项全部通过。原始缺陷记录如下。
下表与 Alt+A 缺陷清单为初次调查时的修复前记录；持续目标阶段已修复这些对齐
问题，当前回归结果见 `UV_TRANSFORM.md`，探针现在会记录修复后的行为。

| 场景 | 4.5.8 | 5.2.0 |
| --- | --- | --- |
| 关闭同步，多物体同时编辑 | 只改变活动物体 | `BMLoopUV.select` 缺失，报错 |
| 开启同步，隐藏面与可见面共享选中顶点 | 隐藏面 UV 被误改 | 同样被误改 |
| 没有 UV 层时执行对齐 | 隐式创建 UV 层 | 同样隐式创建 |
| 同步开启，保留一条缝某一侧的精细 UV 选择 | 旧版本不能表示相同选择语义 | 只选角点 0、1，却改动角点 1、3；3 未选中 |

### Alt+A 对齐问题

实际操作符在 `HoPie/AlignPie.py` 的 `AlignUV`，不在 `UvTools/operators.py`。
快捷键由 `HoPie/_Register.py::_register_align_keymaps` 注册到 `UV Editor`。

代码确认与实测确认的问题：

1. `execute()` 只使用 `context.active_object`，未遍历多物体编辑数据。
2. 非同步分支使用 `loop[uv_layer].select`，该 API 在 5.0 被移除。
3. 同步分支从所有选中网格顶点取得 `vert.link_loops`，不检查隐藏面，也不尊重
   5.2 已有效保存的精细 UV 选择。4.5 缝两侧同时被选则是旧同步模式的正常语义。
4. 空选区直接 `CANCELLED`，没有解释，用户感受是“点了没反应”。
5. `poll()` 只检查 `IMAGE_EDITOR`，未区分 UV 编辑和普通图像显示；UV 层使用
   `verify()`，会意外创建。应检查活动 UV 层并明确提示。
6. `VIEW` 模式中的光标按钮把“水平”传给 U、“垂直”传给 V。
   如果标签意思是把线变水平/垂直，就正好反了：水平应固定 V，垂直应固定 U。
7. 平均值直接平均 face-corner，面数较多的 UV 顶点贡献更大；需明确默认按
   UV 拓扑顶点平均，不把重复角点当多份权重。

Blender 默认 UV 键表也将 Alt+A 绑定到取消选择；HoTools 使用 `head=True` 注册，
单看注册代码没有明显错误。是否在用户现场被其他插件、用户键表或饼菜单开关
覆盖，尚未验证。不能把这个可能性当成已复现根因。后续 GUI 验收要区分
“菜单没打开”和“菜单打开但操作没改变 UV”。

### UVToolkit

同时发现旧 addon 与 `extensions/blender_org/uv_toolkit`，两套都检查过。

`straighten_island.py` 的流程为：调用 `toolkit_distribute` 把选中链拉直，固定线，
临时设置岛边界 seam，再调用 `bpy.ops.uv.unwrap`。它需要关闭 UV 同步，还会
逐个切换对象/编辑模式。扩展版增加了尊重原有 pin 的选项，但状态恢复没有
`try/finally`，失败可能留下临时状态。

`utils/uv_utils.py::get_sorted_uv_edge_loops` 把 UV 坐标本身当图顶点，使用
`set.pop()` 取起始边，再按坐标找角点。重合但无拓扑连接的 UV 可能被当成同一个
点，遍历顺序也没有稳定约定。共线 pin 不能独自确定岛在线的哪一侧。

这些是源码确认的风险。用户描述的特定对称岛倒置，尚未用原始模型复现；目前
不能断言唯一原因是网格切向或某一条代码。我们应在新算法里独立控制 UV 朝向，
并将倒置、旋转 180°、局部翻面分别检测。

`stack_similar_islands.py` 以若干数量统计及 UV 包围盒尺寸筛选，主要通过平移使
中心重合；没有建立完整顶点对应、旋转或反射求解。该实现不能保证镜像岛精确叠合。

### UVPackmaster 4

本机 `extensions/user_default/uvpackmaster4/spipeline/engine/similarity_utils.py`
明确把 `flipping_enable` 传入相似性匹配，同时传入 `match_3d_axis`、
`correct_vertices`、`adjust_scale` 等参数。

因此不能评价为 UPM“不支持镜像”。官方文档的 Align Similar (Stack) 支持
Flipping Enable。可先核对：是否允许翻转、相似性模式是否合适、是否启用了
不适合当前几何的 Match 3D Axis、是否希望启用 Correct Vertices，以及 Stack
Groups 是否排除了目标。未读取用户当前 UPM 设置，也未运行其商业引擎。

## RizomUV 值得借鉴的功能

截至调查日期，官方 changelog 最新条目标为 2026-10-07 的 2027.0.598。
以下为功能公开描述，不是其内部算法说明；HoTools 设计是我们自己的推导。

| 功能 | 对本次需求的价值 |
| --- | --- |
| 边约束与修改约束后重新求解 | 将“拉直目标”与“周围展开”分开，可共享到手动线展开和自动直化 |
| Align Borders | 支持角度阈值与可选预定向，非常接近自动直化边界的需求 |
| TopoCopy | 建立岛之间的对应后传递 UV 编辑，比只叠包围盒更有价值 |
| Align UV to 3D | 有 +U/-U/+V/-V 与回退轴；可以作为明确开启的朝向工具，勿变成线展开的默认依赖 |
| 像素对齐与按组/岛分别变换 | 平移单位与镜像中心的实用扩展，优先级低于选择正确性 |

建议借鉴约束、主岛传递和方向明确这三个工作方式。自动切缝、GPU 打包、完整
Trimsheet/Hotspot 系统本轮不需要铺开；它们是独立项目。

## 公共函数与模块边界

建议布局（实现时创建）：

```text
Utils/mesh_uv.py                  Blender UV 数据、选择兼容、岛与链拓扑
Utils/uv_math.py                  无 bpy 的二维几何；有多个消费者时再拆出来
UvTools/operators.py             镜像、平移等轻量操作符与菜单接入
HoPie/AlignPie.py                 保留 ho.align_uv 薄入口，委托公共对齐实现
UvTools/straighten.py             线约束、自动候选识别、直化操作符
UvTools/unwrap.py                 展开后端、临时状态、结果校验与回滚
UvTools/stack.py                  岛匹配、反射策略、主岛与写回
Utils/uv_chains.py                多开链、方向框架、自动候选与共享交点拟合
Utils/uv_state.py                 原生展开过程的 UV/选择/pin/seam 状态事务
tests/test_uv_math.py             镜像、平移、对齐算法
tests/test_uv_topology.py         岛匹配与顶点对应算法
tests/test_uv_chains.py           线与直化算法
tests/test_blender_uv_transform.py 两版点变换、象限翻转及旧对齐入口
tests/test_blender_uv_topology_stack.py 两版拓扑堆叠与状态保护
tests/test_blender_uv_straighten.py 两版原生线展开、直化及异常恢复
```

复杂文件随实际规模拆分，先避免为每个微小功能制造模块。
`mesh_uv.py` 不注册操作符，不导入 HoPie 或 UvTools，也不隐式调用 bpy.ops。
由 UV 模块拥有实现，HoPie 只引用共享操作符或使用薄入口；避免两套对齐逻辑。
迁移注册时保持 `ho.align_uv` 只注册一次，同时验证独立开启/关闭 UV 模块与饼菜单。

### `mesh_uv.py` 的最小公共接口草案

| 接口 | 契约 |
| --- | --- |
| `iter_edit_uv_meshes(context)` | 遍历编辑态网格并按 mesh 数据去重；只读取活动层，不自动建 UV |
| `read_uv_selection(bm, uv_layer, settings)` | 返回可见面范围内的所选角点、真实所选 UV 边、面；保留各自含义 |
| `build_uv_topology(bm, uv_layer, epsilon)` | 构建角点到 UV 顶点映射、UV 边、面邻接、岛边界 |
| `collect_uv_islands(topology, face_scope)` | 在给定范围中返回连通岛，并标记是否为被可见范围截断的岛 |
| `trace_uv_chains(topology, selected_edges)` | 拆分多条线，返回有序顶点、闭环/分叉/退化信息；不静默丢边 |
| `snapshot_uv_state(...)` / `restore_uv_state(...)` | 保存 UV 坐标、选择、pin、seam 与同步有效性等；不替代 Undo |
| `apply_uv_coordinates(...)` | 有限数值与范围校验后写坐标，仅更新有改动的网格 |

不要给选择接口加过多模糊布尔开关。操作符应显式选择“只移动选中 UV”或
“扩展到选中线所在的完整岛”，而不是让公共函数猜。

拓扑必须以 mesh 连接关系和 UV 连续性共同判断。跨共享边时，两个端点的 UV 都
连续才能连接两侧的面。`edge.seam` 不是唯一标准：已标 seam 但尚未展开，UV 仍
可能连续；未标 seam 的 UV 也可能已经断开。两个无连接的岛坐标重叠不能合并。
UV 顶点也不能仅靠坐标 hash 合并，必须属于连续的 face-corner 扇区。

相等容差与功能阈值分开：前者只处理浮点表示误差，后者控制“多像直线/多像岛”。
不要用四位小数四舍五入来代替拓扑。记录稳定键与索引只在一次编辑会话中有效；
切换模式或改拓扑后重建，不保留失效 BMesh/BMLoop 引用。
本轮新增 UV 层测试也观察到两版都会使已有 BMLoop 包装引用失效；新增/移除
CustomData 层后应重新取得角点与层引用，不能只防备编辑模式切换。

## 4.5 / 5.2 选择兼容契约

官方 5.0 Python API 变更与本机两版探针共同确认：

| 数据 | 4.5 | 5.2 |
| --- | --- | --- |
| 坐标与 pin | `loop[uv_layer].uv / pin_uv` | 本机仍使用相同接口 |
| UV 顶点/边选择 | `loop[uv_layer].select / select_edge` | `loop.uv_select_vert / uv_select_edge` |
| UV 面选择 | 从角点与选择模式推导 | `face.uv_select` |
| UV 选择存储 | 每个 UV 层各自保存 | UV 层之间共享 |
| 同步状态 | 从 mesh 选择解释 | 还必须检查 `bm.uv_select_sync_valid` |

5.2 的 `uv_select_mode` 只含 VERTEX/EDGE/FACE，岛选择改为独立的
`use_uv_select_island` 开关；本轮实现与集成测试覆盖该差异。

适配原则：

1. 用能力检测选择后端，版本号用于诊断与测试，不散落在六个操作符里。
2. 4.5 同步开启：按有效 mesh 点/边/面模式解释，过滤隐藏几何；缝的两侧受
   mesh 同步限制，不能承诺只改其中一侧。
3. 5.2 同步开启且 `uv_select_sync_valid=True`：保留精细 UV 选择，不能重新
   从 mesh 展开全部相邻角点。
4. 5.2 同步开启但有效性为 False：按 mesh 模式解释当前选择；若需要编辑选择，
   明确初始化与 flush，而不是每次读取都强行 `uv_select_sync_from_mesh()`。
5. 同步关闭：两版都限制在可见、已选 mesh 面内，使用各自 UV 选择接口；正确
   解释 VERTEX/EDGE/FACE/ISLAND。ISLAND 模式也不能让重叠岛混为一岛。
6. 边模式取“真实选中的 UV 边”，不要把任意两个选中端点间的边都算作线约束。
7. 写选择使用相应后端的 setter/flush；5.2 的同步来回调用会影响 mesh 选择和
   精细 UV 状态，须验证调用顺序与完整恢复。纯坐标变换无需改变选择。
8. 同步开关、选择模式与 Sticky 模式是用户状态。需要临时更改的展开后端使用
   快照及 `try/finally`；多 UV 层不能按旧版方式恢复新版共享选择。

真实 GUI 的“切换同步前后”仍需专门验收；后台主动构造选择状态不能替代交互测试。

## 六项功能的行为与算法

### 1. 镜像所选 UV

独立计算坐标，不调用内置 transform mirror/resize；这样不受编辑器 pivot、
光标位置和 transform orientation 的隐式状态影响。

- X/U：`u' = 2 * center_u - u`，V 不变；Y/V 同理。
- UI 写“翻转 U（左右）/翻转 V（上下）”，避免“绕 X 轴镜像”的歧义。
- 默认中心为所选 UV 包围盒中心，可选固定坐标、UV 光标、原点；这些是明确
  参数，和 Blender 的当前变换 pivot 解耦。
- 默认全部所选 UV 一起处理，可选每岛中心；共享数据去重、多物体不重复执行。
- 坐标改动不动 mesh 几何，不改变 pin 标记。显式镜像允许 UV 有向面积变号。

验收：任意 pivot 设置下结果一致；镜像两次复原；中心点不动；UDIM、负 UV、
单点/零宽范围可用；未选角点不变。

### 2. 平移所选 UV

- 方向 +U/-U/+V/-V；距离非负，以方向给符号，避免双负号。
- 首版提供 UV 单位（1 为一格 UDIM）；像素单位可作为同阶段小扩展。
- 像素距离按 U 使用宽、V 使用高换算；图像尺寸不可用时明确取消或要求尺寸。
- 后续可扩展自定义二维方向；先不增加与当前需求无关的模态交互。
- 直接加偏移，不受 pivot、网格切向或朝向影响。

验收：往返复原；0 距离明确处理；跨 UDIM 不截断；非正方形图像像素换算正确。

### 3. 沿轴对齐所选 UV

- 固定 U 得垂直线，固定 V 得水平线；分开写清“固定哪个坐标”和“结果朝向”。
- 保留 MIN/MAX/AVERAGE/ZERO/CURSOR；默认整体选区，可选每条链/每岛分别。
- 默认平均按独立 UV 拓扑顶点统计，不按角点出现次数。
- 沿用 `ho.align_uv`，Alt+A、右键与搜索入口共用同一套解析逻辑。
- 无选区/缺层/不合适编辑器给明确提示。此操作只对齐所选点，不自动展开周边。

验收：上述已复现缺陷全部转成回归测试；补充两版各种选择模式以及 VIEW 标签。

### 4. 线展开所选 UV 岛

建议将其定义为“所选 UV 边链成为直线约束，所属岛的其余区域重新展开”。
多个岛、同一岛多条不相连的开链可以支持；不是简单对全部选中点做一次投影。

流程：

1. 从真实选中边构造 UV 图与有序链；稳定选端点，不以 mesh 切向或 set 顺序
   确定朝向。按原 UV 方向选择最小旋转，近似竖直/45°等情况有确定的规则。
2. 默认保留原 UV 边长比例与链中点，拉直到最近 U/V 轴；也可选择维持端点
   连线或自定义轴。模型边长比例是显式选项，不能默认掺入网格方向。
3. 同一 UV 顶点的多个角点一致写入约束；多条链的公共节点要一起求目标，
   不能后写的链覆盖前一条。无冲突的多链先支持。
4. 用明确的临时 pin、目标面选择与必要边界隔离调用展开。允许使用 Blender
   的 ANGLE_BASED/CONFORMAL 后端；用户要求独立算法的是镜像，不必立即自研
   完整参数化求解器。不同后端若无法满足方向与恢复契约，再考虑自研。
5. 若约束全共线，几何仍有两侧/反射歧义：在变换后的原 UV 框架中选一个
   可靠离线点作为方向锚点，内部线隔开的区域分别锚定；优先尊重已有非共线 pin。不可仅固定一条线就
   声称不会翻面。不能增加有效锚点或约束冲突时跳过并报告原因。
6. 保存原 UV 朝向，检查结果有限值、约束残差、退化和相对原始有向面积翻转。
   整岛反射、180°旋转和局部折叠分别处理；最终不靠一律旋转 180°“修正”。
7. 只提交通过验证的岛；失败岛坐标回滚。恢复所有临时状态，撤销作为一个步骤。

初版边界：闭环无法在保留有效面的前提下整体压成一条线，应报告需要开链或切口。
分叉及相交链要检测约束是否可兼容；先支持不相交/相容多链，不保证任意线网。
被隐藏/不可见范围截断的岛默认整岛跳过，避免偷偷改不可见区域。
原 pin 与拉直目标冲突默认保留 pin 并解释失败；可提供明确的忽略原 pin 选项。

验收：对称与非对称岛、镜像原 UV、三角/四边形/混合拓扑、多条内部线、
不同端点索引与面遍历顺序、pin 冲突、隐藏截断、多物体和求解失败恢复。

### 5. 直化岛

与线展开共用约束后端，但多一个“发现近直线”的步骤。不能把所有局部相邻边
角度小的链压直，否则圆弧密集细分后每段角度都小，也会被误判成直线。

- 阈值至少有局部转角上限，加全链拟合的最大横向偏差/链长及总方向变化校验。
- 提供保留原线方向和吸附 U/V 轴；“接近直线”和“接近坐标轴”是两个不同条件。
- UI 以角度阈值为主要参数，高级项提供归一化偏差，避免尺度改变行为。
- 先覆盖边界、度数为 2 的链，以及能可靠识别对边延续的内部四边形行列。
  分叉处要有置信度和冲突检测，不保证任意三角化网格自动猜中所有设计线。
- 仅处理所选岛；发现候选、检查约束、统一求解，一次提交。
- 当前通过阈值、是否包含内部线及失败原因控制线集；候选预览是可选的后续扩展。
- 默认保留方向，多个方向的共享点联合拟合，三角网格的行、列、斜线可同时直化。

验收：直线轻微噪声、圆弧、阶梯、尖角、短碎边、不同细分密度和 UV 尺度；
阈值边界行为、多候选冲突、内部链与边界共同求解。

### 6. 拓扑堆叠（已优先实现）

按用户新要求只做一种行为：同形状、同点数且面连接对应的岛，所有顶点强制
复制到主岛，不提供只做刚性变换或其他模式。

- 首组优先以活动物体的所选活动面所在岛为主岛；其他同类岛自动分组。
- 主岛保持不动；自动匹配旋转、镜像和等比尺寸差异。
- 用边界形状识别“同形状”，不以内部 UV 点偏差阻止强制修正。
- 基于顶点邻接特征剪枝，再从种子面的有序顶点对应传播完整面连接关系，
  验证顶点/面双射；不仅比较点数或包围盒。
- 形状容差为归一化后边界点最大偏差占主岛边界包围盒对角线的比例，默认 5%。
- 成功后直接写主岛全部 UV 坐标，含内部点和已固定点；pin 标记等用户状态保留。
- 对称候选按边界残差、全部点残差、最小旋转和稳定顺序选择，无 mesh 切向依赖。
- 只处理所选 UV 所在的完整可见岛；无匹配、隐藏/显示不完整或非流形岛跳过。
- 匹配超过工作量限制时明确取消，尚未写入任何坐标；写回失败恢复原角点坐标。

实现位置：`Utils/mesh_uv.py` 为真实 UV 拓扑与两版选择读取，
`Utils/uv_topology.py` 为无 bpy 的对应算法，`UvTools/stack.py` 为操作符。
由 `UvTools/operators.py` 统一注册并接入右键菜单。

## 测试与交付顺序

1. 拓扑堆叠与公共层（已先实现）：测试两版同步/非同步与选择模式、镜像与
   内部点修正、主岛、隐藏岛、其他层、共享 mesh、失败回滚和 Undo/Redo。
2. 镜像、平移、对齐：后续完成数值测试、选择保护、多物体/共享 mesh、Undo 与
   Alt+A GUI 验收；同时审查适配到象限等现有 UV 选择使用点。
3. 线展开（已实现）：状态事务、方向/翻面验证及同岛多条不相交内部线。
4. 自动直化（已实现）：复用上一步，覆盖阈值、圆弧误判与多方向共享交点；
   候选预览不属于本次六项功能的必需内容，保留为后续扩展。
5. 拓扑堆叠只按当前单一功能需求维护与优化，不扩展其他堆叠模式。

基础选择矩阵覆盖：两版 × 同步开关 × 点/边/面（非同步另含岛）；以及 5.2
同步有效/失效、混合 mesh 选择模式、Sticky 三模式、切层、空选区、隐藏几何、
部分可见岛、多物体、共享 mesh、缺失 UV。结果应核对完整坐标与选择/pin/seam
状态，不能只断言操作符返回 FINISHED。

纯算法测试可检验镜像两次/平移往返不变量、与 face-corner 排列无关、容差边界、
图对应及反射残差。展开集成必须测试 pin、翻面、异常恢复与未参与岛不变。
GUI 测试涵盖真实点选、框选后切换同步、Alt+A 打开菜单、按钮、F9 和 Undo/Redo。

本轮探针命令：

```powershell
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --background --factory-startup --python-exit-code 1 --python tools/probe_uv_compat.py
& 'D:\Blender\blender-5.2.0-windows-x64\blender.exe' --background --factory-startup --python-exit-code 1 --python tools/probe_uv_compat.py
```

输出保存在本地 `_research/uv/probe_4.5.8.json` 与 `probe_5.2.0.json`，该研究输出
目录被现有 gitignore 排除；可复现探针与本方案纳入普通源码位置。

## 官方资料

- [Blender 5.0 Python API 选择存储变更](https://developer.blender.org/docs/release_notes/5.0/python_api/)
- [Blender 5.0 UV 选择说明](https://docs.blender.org/manual/en/5.0/editors/uv/selecting.html)
- [Blender BMesh 官方源码](https://github.com/blender/blender/blob/main/source/blender/python/bmesh/bmesh_py_types.cc)
- [RizomUV changelog：约束、Align Borders、对齐与像素工具](https://www.rizomuv.com/changelog/)
- [RizomUV 2025：Align UV to 3D、像素对齐](https://www.rizomuv.com/feature/rizomuv-2025-whats-new/)
- [RizomUV TopoCopy](https://www.rizomuv.com/feature/rizomuv-2020-winter-release/)
- [UVPackmaster 4 Aligning：Flipping Enable 等参数](https://uvpackmaster.com/doc4/blender/4.0.0/35-aligning-functionalities/)

API 网站部分版本页在调查时未能读取，具体 4.5/5.2 行为以上述本机真实运行与
API 对象文档为准，不将 main 分支源码直接当作两个已安装版本的验收结果。
