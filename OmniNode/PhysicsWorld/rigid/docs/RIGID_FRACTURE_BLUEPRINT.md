# Jolt 刚体破碎资产蓝本

本文冻结 HoTools 第一阶段刚体破碎的产品流程、当前地基、缺口、运行时语义和验收出口。它只描述 Blender Object 模式；凸包、Full Mesh、Cluster、动态 GN 实例和运行时拓扑生成保留扩展位置，但不进入第一条可用链。

## 资源导航

- [Jolt Physics 产品化路线图](../../../doc/JOLT_PHYSICS_BACKGROUND_ANALYSIS.md)：刚体域总方向、能力边界和阶段顺序。
- [Physics World 公共管线契约](../../../doc/PHYSICS_SIMULATION_PIPELINE_CONTRACT.md)：Scope、生命周期、result、cache 和 writeback 的公共规则。
- [Physics World 当前状态](../../../doc/PHYSICS_WORLD_IMPLEMENTATION_STATUS.md)：所有 solver 的当前阶段。
- [刚体文档入口](README.md)：Jolt 设置、约束、测试、性能和专项文档。
- [Jolt 测试策略](JOLT_TEST_STRATEGY.md)：fixture、oracle、Blender acceptance 和 release 门禁。
- [Jolt Blender 兼容约束](../../../../_native/docs/JOLT_BLENDER_COMPAT.md)：native 构建、ABI 和线程边界。

成熟工作流参考：

- [Houdini RBD Configure](https://www.sidefx.com/docs/houdini/nodes/sop/rbdconfigure.html)：active、animated、sleeping、最小激活冲量和 collision proxy。
- [Houdini RBD Constraints](https://www.sidefx.com/docs/houdini/destruction/constraints.html)：碎块身份与独立约束网络。
- [Cinema 4D Voronoi Fracture](https://help.maxon.net/c4d/s24/en-us/Content/html/OMOGRAPH_FRACTUREVORONOI.html)：参数化生成、显式更新和独立碎块。
- [Cinema 4D Dynamics Trigger](https://help.maxon.net/c4d/2025/en-us/Content/html/TRIGIDBODY-RIGIDBODY_PBD_CUSTOM_START_GROUP.html)：碰撞触发和动力学接管。
- [Maya Bullet Shatter](https://help.autodesk.com/cloudhelp/2022/ENU/Maya-SimulationEffects/files/GUID-D407C32E-975E-4394-B5A7-614EA051A17F.htm)：预破碎、Rigid Set 和 Initially Sleeping。
- [Unreal Chaos Destruction](https://dev.epicgames.com/documentation/unreal-engine/destruction-overview?lang=en-US)：Geometry Collection、Cluster、连接图和 strain。
- [NVIDIA Blast](https://github.com/NVIDIAGameWorks/Blast)：预破碎 chunk、support graph、bond 和 actor split。
- [Jolt ContactListener](https://jrouwe.github.io/JoltPhysicsDocs/5.2.0/class_contact_listener.html)：接触回调的线程与 body lock 边界。

资源导航是永久内容，后续清理不得删除。

## 第一目标

用户在 Object 物理大面板中启用“刚体破碎”，调节 GN，显式刷新为受管理的独立 Mesh Objects，隐藏本体，然后按普通对象运行 Jolt。最终第一条 acceptance 必须交付一个可打开的 `.blend`：球撞击墙体后，撞击区域的可破碎块被激活并离开静止姿态，未命中的锚定墙块保持不动。

第一阶段的实体关系固定为：

```text
Source Object
  Object.hotools_rigid_fracture
  Geometry Nodes / modifier authoring
            |
            | explicit Refresh Products
            v
Managed Product Collection
  Piece Object + Mesh
  Object.hotools_rigid_fracture_piece
  Object.hotools_rigid_body
            |
            | fracture scope resolver
            v
ordinary RigidBodySpec rows
            |
            v
Jolt -> rigid_transform batch -> ordinary Object writeback
```

Source 是资产 owner，不是破碎后的物理 body。Piece 是普通 Blender Object，也是第一阶段唯一的模拟实体和写回目标。

## 地基审计

### 已可直接复用

| 能力 | 当前实现 | 结论 |
|---|---|---|
| Object 级刚体属性 | `rigid/schema.py`、`properties.py`、统一物理面板 | 可为碎块写入普通 `hotools_rigid_body` |
| Collection 批范围 | `scope.py` 冻结 `Collection.all_objects`、Object/Data 指针和 transform 列 | 可复用碎块批读取与写回顺序 |
| Rigid spec/slot | `build_rigid_body_spec()`、稳定 solver slot、结构脏重建 | Piece 不需要第二套 Jolt spec |
| Jolt body/constraint | 7 种基础 shape、11 种约束、批结果和命令 | 第一测试可用 BOX 碎块，不依赖 convex |
| 激活命令 | adapter/native 已有 `set_body_active` / `activate_body` | 可在安全步边界显式激活已有 body |
| 接触事件 | native 记录 add/persist/remove、body slot、normal、penetration 和 points | 足够做无冲量阈值的首次命中和范围选择 |
| 生命周期 | restart、same-frame、dispose、scope prune、统一 delta writeback | 可复用，不建立破碎私有写回 |
| Blender 测试 | native、adapter、后台 Blender、save/reopen 与性能门禁 | 可以增加生成 `.blend` 的端到端 acceptance |
| evaluated mesh 读取 | Physics Bake、MC2 和 GN probes 已验证 `evaluated_get().to_mesh()` | 可作为显式刷新时的 mesh snapshot 入口 |

### 地基落实状态

| 项目 | 当前事实 | 冻结边界 |
|---|---|---|
| 破碎持久属性 | Source/Piece PropertyGroup 已独立注册并通过 round-trip | 由 `physicsWorld.rigid_fracture` 组件持有 |
| GN 产物事务 | 已实现 evaluated mesh 连通块拆分、受管替换、失败保留旧 READY 产物 | 默认 GN 必须输出已 Realize 的面几何 |
| 产品身份 | 已有 asset ID、piece ID、revision、fingerprint 和 manifest 校验 | Object/Data pointer 仍只作本次运行 slot |
| Source 排除 | resolver 已无条件排除启用破碎的 Source | Source 即使同时启用普通刚体也不双注册 |
| 链接集合展开 | 已私有展开 owner/revision 匹配 Piece，并发布 Product Collection 批次 | 公共 Scope 与其他 solver 不被改写 |
| 初始休眠 | `start_deactivated` 已贯通 RNA/spec/adapter/py313 native | Dynamic 使用 `DontActivate`，碰撞可在 Jolt 内自动唤醒 |
| 接触身份 | 已建立 `slot -> asset/piece` 反向索引 | 接触结果仍沿用普通刚体事件通道 |
| 局部激活 | 第一 acceptance 使用 Jolt 接触自动唤醒命中 Piece | 半径、邻接传播和 assembly policy 进入 F4 |
| 冲量阈值 | `OnContactAdded` 发生在求解前，当前事件不含求解冲量 | 第一 acceptance 不承诺 impulse threshold；后续单独扩展 native 观测 |
| 作者操作到缓存失效 | 刷新成功后已清理统一 runtime cache | 下一次 Begin 会完整重建刚体注册 |
| 破碎测试资产 | `jolt_fracture_wall.blend` 已生成，并通过磁盘重开与同进程 reset 重放 | 可执行脚本是 pass/fail oracle，`.blend` 是用户检查资产 |

结论：第一条 Object 破碎链已经贯通，不需要更换 solver、scope、result 或 writeback 架构。F0-F3 完成后，下一阶段是局部传播、结构约束和规模化 Object 表，而不是运行时 GN 拓扑生成。

## 冻结产品语义

### Source 属性

新增 `Object.hotools_rigid_fracture`，由独立的 `physicsWorld.rigid_fracture` core component 持有；`physicsWorld.rigid` 只消费其 resolver。实现目录固定为：

- `rigid_fracture/properties.py`：Source/Piece 持久属性；
- `rigid_fracture/geometry_nodes.py`：受管规则切块 GN 与固定身份属性；
- `rigid_fracture/authoring.py`：Collection、刷新事务、体积质量与作者操作；
- `rigid_fracture/resolver.py`：rigid 私有 Scope 展开与 slot 身份索引；
- `rigid/scope_sync.py`：消费 resolver，继续生成普通 `RigidBodySpec`。

第一版字段：

| 分组 | 字段 |
|---|---|
| Identity | `enabled`、`asset_id`、`schema_version` |
| Generator | `modifier_name`；`piece_id_attribute=hotools_piece_id` 与 `split_mode=CONNECTED_COMPONENT` 是隐藏内部契约 |
| Products | `product_collection`、`product_revision`、`product_status`、`product_fingerprint` |
| Mass | `mass_mode=SOURCE_MASS/DENSITY`、`density`；`SOURCE_MASS` 读取本体普通刚体质量 |
| Physics template | 类型、摩擦、弹性、阻尼、重力倍率、睡眠等直接读取本体 `hotools_rigid_body`；v1 `piece_*` 字段只隐藏保留旧文件数据 |
| Activation | 半径、阈值和 assembly policy 在实现支持前不注册 |

Modifier 不是 Blender ID，持久引用使用 Source 内的 modifier name；节点组可以作为诊断信息，但不能替代 modifier identity。Product Collection 使用 `PointerProperty(Collection)`。

`product_status` 至少包含：

- `EMPTY`：尚未生成；
- `READY`：manifest、fingerprint 和对象集合一致；
- `OUTDATED`：Source、modifier、GN 参数或 mesh 变化；
- `ERROR`：最后一次刷新失败，旧 READY 产物是否仍有效必须单独记录。

### Piece 属性

新增只由工具写入的 `Object.hotools_rigid_fracture_piece`：

- `owner_asset_id`
- `piece_id`
- `product_revision`
- `managed`
- `breakable`
- `volume`
- `mass_fraction`

Piece 的质量、shape、过滤、阻尼、重力、睡眠等仍存入普通 `Object.hotools_rigid_body`。刷新和“同步到现有碎块”以本体刚体为模板重新写入；质量按闭合网格世界空间体积分配。刷新完成后仍可逐块修改，但下次显式同步或刷新会回到本体模板。Piece metadata 不复制整套刚体字段。

### 所有权规则

- 一个 Piece 只能有一个 fracture owner。
- Product Collection 可以包含用户对象，但 resolver 只接纳 `managed=True` 且 owner ID 匹配的 Piece。
- Source 启用 fracture 后，即使同时启用普通 rigid body，也不进入 Jolt；UI 显示诊断，不产生双碰撞。
- Source 隐藏只影响显示，不决定物理参与。Scope 对 Collection 默认包含隐藏对象，因此 Source 排除必须是显式业务规则。
- Product Collection 为空、owner 冲突、piece ID 重复、revision 过期或非 Mesh managed Piece 都阻止模拟，不回退到 Source。

## 面板工作流

Object 物理大面板增加“刚体破碎”开关和子面板。用户流程冻结为：

1. 在 Source 上启用刚体破碎。
2. 点击“创建规则切块节点”，或选择已有 Geometry Nodes modifier。
3. 创建或链接 Product Collection。
4. 调节 GN 参数并观察 Source 的 evaluated 结果。
5. 点击“刷新碎块产物”。
6. 检查产物数量、状态、revision 和诊断。
7. 使用“仅显示本体 / 仅显示碎块 / 同时显示”控制作者视图。
8. 选择“仅显示碎块”后运行现有 Physics World 图。

必须提供的命令：

- 创建默认规则切块 GN；
- 使用/定位现有 GN modifier；
- 创建并链接 Product Collection；
- 刷新碎块产物；
- 显示本体、显示碎块、隔离碎块；
- 选择全部受管 Piece；
- 将本体物理属性同步到现有 Piece；
- 检查资产状态。

“刷新产物”和“同步到现有碎块”是两个命令。刷新是明确的资产重建操作，会重新应用本体模板并按体积重算质量；普通参数调整只有在用户点击同步后才覆盖当前产物。

### 默认规则切块 GN

默认生成器使用包围盒规则网格与精确 Mesh Boolean 交集，提供 `X 切块`、`Y 切块`、`Z 切块` 和 `碎块间隙` 四个输入。间隙保证布尔结果成为互不连通的面岛；输出端用 Mesh Island Index 在 FACE 域写入固定整数属性 `hotools_piece_id`。属性名不是用户选项，刷新时也会强制恢复固定值。此生成器是第一种内置切块算法，不替代用户自定义 GN。

## 显式刷新事务

第一版刷新只在 Blender 主线程、用户显式 Operator 和非模拟步骤内执行：

1. 校验 Source、modifier、Product Collection 和当前模式。
2. 读取 evaluated mesh；默认 GN 必须在输出前 Realize Instances。
3. 按 `CONNECTED_COMPONENT` 拆分；为将来的 `REALIZED_INSTANCE` 保留 enum，但未实现时不得伪装成功。
4. 只读取固定 FACE/INT 属性 `hotools_piece_id` 作为 piece ID；自定义 GN 未输出该属性时按确定性的连通块顺序生成后备 ID。
5. 在临时 Collection 创建独立 Mesh/Object，复制正确 world transform。
6. 校验 finite、非空面、piece 数量、ID 唯一性和所有权冲突。
7. 所有新 Piece 应用本体 `hotools_rigid_body` 模板；`SOURCE_MASS` 按体积占比分配本体总质量，`DENSITY` 按世界空间体积乘材料密度计算。
8. 原子提交新 manifest 和 Product Collection；只删除旧 manifest 明确拥有且仍标记 managed 的对象。
9. revision 递增，模拟 cache 失效，请求下一次 Begin 重建刚体注册。
10. 任一步失败时删除临时资源，旧 READY 产品保持原样。

第一版不承诺从任意未 Realize 的第三方 GN 输出恢复实例身份。默认 GN 和文档模板必须满足输出契约；其它网络不满足时明确失败。

## Scope 与运行时装配

破碎解析是 rigid domain 的 authoring adapter，不是新 solver：

```text
PhysicsObjectScope
  -> fracture owner scan
  -> validate asset manifests
  -> exclude Source owners
  -> expand managed Piece Objects from linked Collections
  -> ordinary build_rigid_body_spec()
  -> existing Jolt slot/adapter/result/writeback
```

Resolver 必须在普通 rigid body collector 之前完成。它输出稳定顺序的 Piece 视图、`slot -> asset/piece` 索引和 Product Collection transform batch。不得把 Product Collection 的所有对象无条件塞进 scope，也不得改变其它 solver 看到的公共 Scope。

刷新或 manifest revision 变化属于结构变化：清除旧 Piece slots、contact snapshot 和刚体 native world，再按新稳定顺序注册。仅修改 Piece 的热参数仍服从现有 rigid signature 与命令规则。

## 激活与局部破碎

必须区分三种状态：

- `ARMED`：产品语义，Piece 已注册但尚未获准运动；
- `SLEEPING/INACTIVE`：Jolt body 激活状态；
- `ACTIVE`：Jolt 正在积分的动态 body。

休眠不是结构强度，Fixed constraint 也不是资产激活状态。第一 acceptance 只验证预破碎对象的接触激活，不声称已经实现胶合、材料强度或 Cluster。

第一阶段增加普通刚体字段 `start_deactivated`：

- `False`：按当前行为 Active 创建；
- `True`：Dynamic body 使用 `EActivation::DontActivate` 加入 Jolt；Static 忽略；
- body 仍进入 broadphase，可以被活动刚体碰撞并由 Jolt 在求解内唤醒；
- restart/rewind 重新回到作者指定的初始激活状态。

自动唤醒解决第一碰撞的同一步冲量传递，避免 Python 在接触回调中修改 body。显式半径或邻接传播只能在 `Update` 返回后的安全边界排队执行，因此允许一帧/一外部子步延迟；如果未来要求内部子步级传播，需要把 native 调度改为外层逐子步 `Update`。

当前 ContactListener 回调中 body 被锁定，禁止创建、删除或修改物理状态。回调只记录普通值事件；GN 求值、Blender 对象操作和 Jolt body 事务都不能发生在回调线程。

### 第一 acceptance 的局部定义

首个墙体测试不依赖尚未实现的冲量阈值或 bond graph：

- 墙由 BOX Piece Objects 组成；
- 外圈/支撑 Piece 为 `STATIC`；
- 中央可破碎区域为 `DYNAMIC + start_deactivated`；
- 球为带初速度和 CCD 的 Dynamic Sphere；
- 球直接命中的中央 Piece 在 Jolt 求解内激活；中央邻近 Piece 是否被接触岛带动由 fixture 明确固定；
- 外圈 Static Piece 必须保持原位，从而保证结果是局部破坏而不是整墙坠落。

这条 acceptance 验证资产、resolver、初始非激活、接触、结果和 Object 写回的完整链。半径传播、约束断裂和真正的动态受力破坏进入后续切片。

## 实施切片

### F0：合同与地基门禁（已完成）

- 冻结本文、公共 pipeline 入口和测试出口。
- 增加 `start_deactivated` 到 spec/adapter/native，但默认保持当前 Active 行为。
- 新增 native、adapter、Blender fixture：非激活体不受重力位移，活动球命中后同一步或下一可观察帧激活。
- 本轮实现、构建、测试和 `.blend` 保存统一使用 Blender 5.2 / Python 3.13；py311 兼容验证暂缓，不作为 F0-F3 门槛。

出口：现有 golden 默认轨迹不变；初始激活语义有独立 oracle。

### F1：资产属性与显式刷新（已完成）

- 新增 Source/Piece PropertyGroup、面板和 Operators。
- 实现默认 GN、evaluated mesh snapshot、连通块拆分、manifest 和原子替换。
- 实现 Source/Piece 显示控制、属性保留和 cache 失效。

出口：不运行 solver 也能反复刷新同一资产；失败不污染场景；save/reopen 后身份和状态仍成立。

### F2：运行时展开（已完成）

- fracture resolver 排除 Source 并展开受管 Piece。
- Product Collection 发布自己的批 transform/writeback 边界。
- 增加重复 owner、过期 revision、非法对象和 scope 生命周期测试。

出口：所有参与模拟的对象仍是普通 Object；Source 永不与 Piece 双注册。

### F3：球撞墙 acceptance（已完成）

- 生成默认墙体破碎 GN 资产并显式刷新。
- 保存 `rigid/test/assets/jolt_fracture_wall.blend`。
- 后台打开该文件运行完整 Physics World，验证碰撞前静止、命中后局部激活、外圈不动、结果 finite、reset 可重放。
- 测试脚本负责重建/验证资产；`.blend` 供用户直接打开检查。

出口：测试非零失败；通过时报告 Source/Piece 数、命中 Piece、激活/位移数量和未移动锚点数。

### F4：局部传播与结构

- contact point 半径、邻接岛和每步最大激活数；
- 可断 Fixed constraints、强度、锚定和断裂事件；
- 有明确 oracle 后再增加 impulse threshold；
- 大规模碎块的事件过滤、批激活和性能门槛。

### F5：后续表示

- `CONVEX_HULL` 和 `FULL_MESH_STATIC` 独立 shape 切片；
- intact compound/cluster 与 Piece island split；
- GN instances result carrier；
- 接触位置驱动的预烘焙 variant，最后才是运行时 GN 拓扑生成。

## 测试矩阵

| 层 | 必测内容 |
|---|---|
| 纯 Python/schema | 字段默认值、enum、manifest 校验、duplicate ID、状态转换 |
| Native | `DontActivate`、重力静止、碰撞唤醒、reset、active/sleeping readback |
| Adapter | Blender 5.2 / py313 下的 spec 映射、批注册混合 Active/Inactive、slot identity、事件映射 |
| Blender authoring | 规则切块 GN、固定 ID、刷新、拆岛、体积质量、本体模板同步、失败回滚、Undo、save/reopen |
| Blender pipeline | Source 排除、Piece 展开、隐藏无关、Collection batch、writeback |
| Acceptance | 球撞墙局部破碎、外圈静止、finite、repeat/reset |
| 性能 | Piece 数、body sync、contact publish、writeback、depsgraph 和内存 |

`.blend` 是用户验收资产，不替代可执行 oracle。测试脚本必须能从空场景创建同等资产，并能后台打开保存后的文件再次验证。

## 明确后置

第一 acceptance 前不实现：

- 自动凸分解；
- Dynamic Full Mesh；
- Path、Vehicle、Soft Body、Ragdoll；
- runtime GN 求值或接触回调内修改 Blender；
- GN instance 直接模拟/写回；
- Chaos/Blast 级 Cluster、bond stress 和碎块 actor split；
- 没有可验证冲量来源的“破碎强度”滑块。

这些能力不得以未生效 UI、占位成功状态或静默近似进入第一阶段。

## 文档维护

- 本文是刚体破碎的唯一详细产品合同。
- 总路线图只保留摘要、阶段和本文链接，不复制字段表与验收步骤。
- 公共 pipeline 只记录跨 solver 的 Scope、owner、生命周期和写回边界。
- 当前状态页只记录一行阶段与主要缺口。
- 单次测试输出、日期流水账和提交说明只留在测试产物与 Git。
