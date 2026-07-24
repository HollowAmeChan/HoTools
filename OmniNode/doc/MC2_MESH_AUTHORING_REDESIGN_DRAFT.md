# MC2 MeshCloth 节点组装重构临时评审稿

> 状态：已完成评审并授权实施；实现完成且正式蓝本同步后删除本临时稿。
>
> 目的：记录 2026-07-25 讨论形成的 MeshCloth authoring 新模式。评审通过后，先把结论同步到正式蓝本，再按分步提交实施。

## 一、重构结论

MC2 MeshCloth 不再同时维护“显式 partition + sparse override + Physics World 隐式 registry”三层组装路径。所有 MeshCloth 对象都先归一化成同一种带完整显式属性的对象描述，再由同一个 Mesh 域节点组合粒子属性和区域属性，生成完整 Mesh 分区；所有分区最终只通过 `MC2 Mesh域收集`进入 MC2 模拟步。

Physics World 仍负责 frame、scope、collider、solver slot、结果事务和公共生命周期，但 MC2 MeshCloth authoring 不再消费 `world.implicit_objects`，不再需要 MC2 专用或通用隐式注册节点。

最终公开链路：

```text
路径 A：读取对象面板

Object / List[Object]
  -> MC2 MeshCloth对象
  -> MC2MeshObjectSpec
```

```text
路径 B：节点值完全替代对象面板

Object / List[Object]
  -> MC2 MeshCloth自定义对象
  -> MC2MeshObjectSpec
```

```text
共同后半段

MC2MeshObjectSpec ─┐
粒子配置 ──────────┼─> MC2 MeshCloth域 -> Mesh分区
区域属性 ──────────┘                       │
                                          v
                                  MC2 Mesh域收集
                                          │
                                          v
                                       MC2域
                                          │
                                          v
                              Physics World + MC2模拟步
```

## 二、三类属性及唯一所有者

### 1. 显式对象属性

显式对象属性描述“这个 Blender Mesh 以什么 source 形态参与 MeshCloth”。权威字段来自 `setups/mesh_cloth/schema.py::MESH_COLLISION_RNA_FIELDS`，当前包括：

| 字段 | 当前界面名称 | 新模式所有者 |
|---|---|---|
| `mc2_base_pose_proxy` | BasePose只读对象 | `MC2MeshObjectSpec` |
| `radius_vertex_group` | 半径顶点组 | `MC2MeshObjectSpec` |
| `pin_enabled` | Pin启用 | `MC2MeshObjectSpec` |
| `pin_vertex_group` | Pin顶点组 | `MC2MeshObjectSpec` |
| `primary_collision_group` | 主碰撞组 | `MC2MeshObjectSpec`，外部碰撞与域内自碰共用 |
| `collided_by_groups` | 被碰撞组 | `MC2MeshObjectSpec`，外部碰撞与域内自碰共用 |

两种对象节点必须消费同一份 schema：

- `MC2 MeshCloth对象`读取 Object 面板的完整值。
- `MC2 MeshCloth自定义对象`把同一组字段完整暴露为 socket；未连接 socket 使用 schema/node 默认值，不回退读取 Object 面板。

禁止重新引入逐字段 `unset`、面板回退或 ordered patch。自定义对象是完整显式属性替代，不是稀疏补丁。

当前 schema 中表示“参与简单布料”的裸 `enabled`不再进入新对象合同，并在实现时删除。对象是否参与模拟由节点连线决定，节点是否执行由 OmniNode mute 决定；对象、域、collector 和注册中间态均不再保留第二套参与/执行状态。`pin_enabled`、`self_collision_enabled`等具体物理功能开关不在该删除范围内。

### 2. 粒子属性

粒子属性只由 `MC2 MeshCloth粒子配置`拥有，例如半径、半径曲线、重力、阻尼、约束刚度、摩擦、自碰撞开关和其他可退化到逐粒子的参数。

固定规则：

- MeshCloth 只公开一个粒子半径模型。
- self thickness 继续由粒子半径按既定比例派生，不重新公开独立自碰半径。
- `自碰撞`开关属于粒子配置；`跨物体自碰撞`决定同一域内不同 partition 是否交互，属于区域/whole-domain 策略，不继续混在粒子配置中。
- 粒子配置节点不持有 Object、Anchor、Teleport、区域过滤或 Physics World。

### 3. 区域属性

区域属性只由 `MC2 MeshCloth域`拥有，当前候选字段包括：

- Anchor；
- Normal Axis；
- Anchor / World / Local / Depth Inertia；
- 移动惯性平滑；
- World / Local 移动和旋转速度限制；
- Teleport 模式、距离和旋转阈值；
- Cloth Mass；
- 跨物体自碰撞；
- 真正属于 whole-domain 或 partition 交互策略的过滤字段；

底层仍可把区域值展开为 per-partition 或 per-particle SoA。公开接口保持区域级表达，是有意降低 authoring 自由度以提升可读性，不是后端能力倒退。

## 三、公开节点最终职责

### 1. `MC2 MeshCloth对象`

输入：

- `Object / List[Object]`。

输出：

- `List[MC2MeshObjectSpec]`；
- 可选对象数量和校验状态。

行为：

- 展平对象列表；
- 只接受 Mesh Object；
- 从 Object 面板完整读取 `MESH_COLLISION_RNA_FIELDS`；
- 生成稳定 source identity 和显式属性签名；
- 不生成 partition，不读取粒子/区域配置，不接收 Physics World。

### 2. `MC2 MeshCloth自定义对象`

输入：

- `Object / List[Object]`；
- 与 `MESH_COLLISION_RNA_FIELDS`一一对应的完整 sockets。

输出：

- 与上一节点完全相同的 `List[MC2MeshObjectSpec]`；
- 可选对象数量和校验状态。

行为：

- sockets 完全替代面板属性；
- Object 仅提供 Mesh 数据、变换、身份和写回目标；
- 不读取 Object 上的 MeshCloth 面板值；
- 同一节点输入多个对象时，对整组对象应用同一套显式属性；需要不同值时使用多个节点。

该节点不是 partition override，不得沿用当前 `MC2 Mesh覆盖`的输入/输出合同。名称不得继续暗示它会修改一个既有 partition。

### 3. `MC2 MeshCloth粒子配置`

保持统一 `MC2ParticleProfileSpec`输出。只审查并修正错误归类的区域字段，不在本次重构中改变已经验收的数值默认值和底层参数 ABI。

### 4. `MC2 MeshCloth域`

输入：

- `List[MC2MeshObjectSpec]`，禁止裸 `bpy.types.Object`；
- `MC2ParticleProfileSpec`；
- 区域属性。

输出：

- `List[MC2MeshPartitionSpec]`或等价的完整 setup partition 描述；
- 域/区域标识和装配前状态。

行为：

- 对每个对象描述组合唯一粒子配置和区域配置；
- 生成完整 partition，不保留 collector defaults；
- 不读取 Object 面板，不读取 Physics World，不访问 native；
- 一个域节点表示“一组对象共享同一套粒子与区域策略”；
- 不再直接输出 fused `MC2ProductRequestV1`。

### 5. `MC2 Mesh域收集`

输入：

- 一个或多个完整 Mesh 分区列表。

输出：

- `MC2域`（`MC2ProductRequestV1`或其正式后继类型）；
- 装配报告。

只允许：

- flatten；
- 稳定排序；
- setup/type/schema 校验；
- stable ID 和写回 owner 冲突检查；
- Require-Fusion 兼容性检查；
- 构造一个统一 MeshCloth domain request。

明确禁止：

- 输入或读取 Physics World；
- 读取 `world.implicit_objects`；
- 提供粒子、Anchor、Task、过滤或启用默认值；
- 逐字段覆盖、patch 或来源优先级合并；
- 为冲突对象猜测优先级；
- 创建 solver slot、native context 或 Blender capture 数组。

名称固定为 `MC2 Mesh域收集`，直接表达“MeshCloth域输出连接到这里”；不再使用泛化且连接方向不清楚的 `MC2 Mesh收集器`。

### 6. `MC2模拟步`

继续接收 Physics World 和一个或多个完整 `MC2域`。MC2 declaration 不再声明消费 MeshCloth implicit object tag。现有 whole-domain、scheduler、DomainV1、结果事务和写回合同不因 authoring 重构改变。

## 四、核心数据合同

建议新增 setup-specific authoring 类型，名称可在实现前统一：

```python
@dataclass(frozen=True)
class MC2MeshObjectSpec:
    source_object: object
    source_identity: str
    explicit_properties: MC2MeshExplicitPropertiesSpec
    property_origin: str  # "panel" | "socket"
    signature: str
```

约束：

- `source_identity`只由底层 Blender Object 的稳定身份决定；不得包含节点 ID、producer ID、列表位置或属性来源。
- 面板节点和自定义节点包裹同一个 Object 时必须得到相同 `source_identity`。
- `property_origin`只用于 debug，不参与覆盖优先级。
- spec 保存 Object 引用、BasePose 引用、顶点组名称和显式标量，不提前保存完整顶点数组或 native handle。
- Mesh topology、顶点组权重和 depsgraph 结果仍由统一主线程 capture 冻结。

完整 Mesh partition 至少组合：

```text
MC2MeshObjectSpec
+ MC2ParticleProfileSpec
+ MC2MeshRegionSpec / MC2TaskParametersSpec
+ setup options
-> complete MC2MeshPartitionSpec
```

实现可以在过渡期复用 `MC2PartitionEntry`名字，但新合同中每个 Mesh entry 必须是完整值：不依赖 `MC2_UNSET`、collector defaults、`origin=implicit`或 `patches`。

## 五、身份、重复与冲突规则

1. 同一个底层 Object 在一个最终 collector 输入中只能出现一次。
2. 同一个 Object 同时通过面板对象节点和自定义对象节点进入时明确失败，不定义隐藏覆盖顺序。
3. 用户需要替代面板属性时，必须在图上用自定义对象节点替换面板对象节点。
4. 同一 Object 进入两个不同 Mesh 域也默认失败，因为会争用同一 Mesh 输出 owner。未来若出现合法多实例需求，必须先增加独立输出 target 和显式 instance identity，不能复用节点 producer 顺序。
5. 对象列表的输入顺序不得成为物理身份；collector 使用稳定 identity 排序或保留已经冻结的确定性顺序。
6. 重命名 authoring 节点、移动节点或重建节点不得改变 Object/partition identity。

## 六、更新与重建语义

| 变化 | 预期处理 |
|---|---|
| 节点位置、节点显示名 | 不改变任何物理签名 |
| 面板显式标量、显式属性 socket | 更新 object/partition config signature |
| 粒子配置数值、区域参数数值 | parameter hot update；不得伪造 topology 变化 |
| 顶点组名称或 BasePose source | static/source signature 变化，按现有 staged replacement 规则处理 |
| Mesh topology、Object/Data identity、输出 target | static/program rebuild |
| 对象从域列表加入或移除 | domain membership 变化，staged replacement |
| collector 输入顺序变化但成员相同 | 不得仅因顺序变化产生不同物理身份 |

面板属性更新必须可靠触发面板对象节点重新求值，或被统一 source observation/capture signature 检测。不能依赖 Object Python 引用身份变化，否则 registry 删除后仍可能留下新的“同对象属性修改不生效”问题。

## 七、计划删除的当前中间态

本次重构目标删除：

- 当前只把 Object 转成空 `MC2PartitionEntry`的 `MC2 Mesh对象`行为；节点本身改造成面板对象适配器。
- 当前 `MC2 Mesh覆盖`公开节点和 `override_mc2_mesh_partition_entries()` Mesh 专用路径。
- `MC2 Mesh隐式注册`公开节点。
- `register_mc2_mesh_partition_entries()`、`collect_implicit_mc2_mesh_partition_entries()`和 MC2 Mesh implicit tag。
- Mesh collector 的 `物理世界`、`包含隐式`和全部 `默认*`输入；节点随后改名为 `MC2 Mesh域收集`。
- Mesh collector 内的 implicit/explicit 优先级、字段 owner 合并和默认补全。
- MeshCloth对象、域、collector 和隐式注册中间态用于“参与/执行”的裸 `enabled`输入/字段；对象成员资格只由连线决定，执行开关只使用节点 mute。
- 当前 `MC2 MeshCloth域`直接接收裸 Object 并直接输出 request 的简化旁路。
- 对应产品声明、节点菜单、测试、蓝本和状态文档中的旧路径。

共享 `MC2PartitionPatchSpec`、`MC2_UNSET`、origin/owner/history 不能在本次直接全局删除。必须先检查 BoneCloth、BoneSpring 和非 Mesh 测试是否仍有真实消费者；只有全仓引用归零或完成对应替代后才能在后续 E7-S 清理提交中删除。

## 八、实施顺序草案

1. 先冻结新 authoring 类型、schema 转换和身份测试，不改公开节点。
2. 从 `MESH_COLLISION_RNA_FIELDS`生成/校验面板对象和自定义对象两套输入，证明同值产生等价 `MC2MeshObjectSpec`。
3. 改造 `MC2 MeshCloth域`：只接收包装对象，输出完整 Mesh partitions。
4. 简化 Mesh collector 并改名为 `MC2 Mesh域收集`：只接收完整 partitions，并证明同一编译域和现有产品请求数值等价。
5. 让 `MC2模拟步`只消费 collector 输出，移除 MC2 Mesh implicit registry 消费。
6. 删除旧 `MC2 Mesh覆盖`、隐式注册、collector defaults 和直接 Object 域旁路。
7. 仓库级审查共享 patch/unset/provenance 兼容层，能删的进入 E7-S，仍被 Bone 路径使用的明确保留原因。
8. 更新正式蓝本、实现状态、架构文档和节点连线示例；临时文档完成使命后删除。

每一步独立提交，并在提交前运行对应自动化。当前普通开发/验收使用 Python 3.13 和 Blender 5.2；按现有约束暂停 Blender 4.5 编译测试，直到旧代码最终删除收尾确有必要。Blender 5.2 验收前必须确认加载的是当前工作树，而不是默认 HoTools 备份。

## 九、开工前必须审定的问题

### 1. 碰撞组统一合同（已审定）

当前中间态存在：

- 面板显式属性：`primary_collision_group` / `collided_by_groups`，范围分别为 `1..16`和 16-bit mask；
- partition/collector 中间态：`collision_group` / `collision_mask`，使用单个 uint32 bit 和 uint32 mask。

代码审计确认两者当前进入了不同运行时通道：

- `collided_by_groups`进入 `external_collision_masks`，筛选 Physics World collider snapshot 中的外部碰撞体；
- `collision_group` / `collision_mask`进入 whole-domain self collision 的 owner group/mask，筛选不同 Mesh partition 之间的自碰交互；
- `primary_collision_group`属于公共 16 组 collider 属性体系；当前 MC2 Mesh 自碰分区过滤没有直接复用它。

新合同不再把这视为两套独立 authoring 语义。`primary_collision_group`和`collided_by_groups`是唯一公开碰撞组来源；whole-domain self collision 使用同一组语义：在有效 `collided_by_groups`中加入对象自己的 `primary_collision_group`，随后按现有拓扑合同执行共享 particle 和一环邻接剔除。当前 uint32 `collision_group` / `collision_mask`中间态应改为消费这份统一 16 组合同，或在编译边界做无损展开，不再公开第二组相似 sockets。

`MC2 MeshCloth自定义对象`可以直接公开这两个字段并提供 schema 默认值，因为使用该节点本身已经明确表达“由节点值替代面板”。默认值不是 collector fallback，也不产生字段合并。

### 2. 启用状态（已审定）

MeshCloth authoring 中所有表示“参与/执行状态”的裸 `enabled`输入和成员字段删除：

- 对象是否进入 domain 只由节点连接和对象列表成员资格决定；
- 节点临时关闭统一使用 OmniNode mute；
- 不在 Object spec、partition、domain、collector 或 solver request 中保留并行启用状态；
- 当前面板 `简单布料/enabled`若只承担旧参与开关，则随新对象合同删除；若 UI 仍需折叠面板，应改成纯 UI 状态并明确不得进入物理签名。
- `pin_enabled`、`self_collision_enabled`和其他有独立物理含义的功能开关继续由各自属性层拥有，不使用 node mute 替代。

### 3. 节点公开名称

候选名称：

- `MC2 MeshCloth对象`：读取面板；
- `MC2 MeshCloth自定义对象`：socket 完整替代面板；
- `MC2 MeshCloth粒子配置`；
- `MC2 MeshCloth域`；
- `MC2 Mesh域收集`。

公开名称固定为 `MC2 MeshCloth对象`和`MC2 MeshCloth自定义对象`。不继续使用“覆盖”，避免暗示存在上游 partition patch。

### 4. Object 列表能力

建议两个对象适配节点都接受 Object 或嵌套 Object list。自定义对象节点对整组应用相同属性；单对象差异由多个节点表达。若 OmniNode 当前 socket 类型无法稳定表达同一 typed spec 的 list 合并，需要先补一条最小 typed-list 合同，不得退回 `list[Any]`加运行时猜测。

## 十、验收门槛

### 纯 Python / authoring

- 面板适配器完整读取 schema，字段缺失明确失败。
- 自定义适配器完全忽略面板值。
- 两种适配器在字段值相同时产生相同 source identity 和等价显式属性签名。
- Mesh 域拒绝裸 Object、非 Mesh 和错误 setup spec。
- 相同对象重复进入域/collector 明确失败。
- collector 不导入或访问 `PhysicsWorldCache`，不读取 implicit registry。
- collector 输入完整性、排序、fusion 和报告具有确定性。
- MeshCloth公开节点不再暴露用于参与/执行的裸 `enabled`socket；mute 后不产生有效下游域。

### 双 ABI / native

- authoring 重构不改变现有后端参数字段、dtype、shape 和传递顺序；若必须改变，单独提交并更新双 ABI 测试。
- 单对象、多对象 whole-domain、self collision、碰撞过滤、Anchor/Teleport 和多目标事务保持数值与行为等价。
- 参数变化仍命中 hot update，topology/membership 变化仍命中 staged replacement。

### Blender 5.2

- 两种对象节点可创建、重建和正确刷新节点名。
- Object/list 连接、粒子配置、域、collector、模拟步完整执行。
- 面板属性与 socket 属性来源可从状态/debug 中辨认。
- 修改面板属性或自定义 socket 后，签名和模拟更新符合第六节。
- 当前工作树与 5.2 默认备份的加载来源经过明确检查。

### 删除审查

- MC2 declaration 不再列出 `MC2 Mesh覆盖`和 `MC2 Mesh隐式注册`，collector 名称更新为 `MC2 Mesh域收集`。
- MC2 Mesh 路径不再引用 implicit tag、registry collect/register 或 collector defaults。
- 节点菜单、产品测试和全部正式文档中不存在旧连线示例。
- 删除后进行一次专门的中间态兼容逻辑 review，不把可移除的 patch、owner、origin、unset 和迁移命名留到 E6 GPU 阶段。

## 十一、评审结论栏

开始实现前需要确认：

- [x] 接受“MC2 MeshCloth 全部走 collector，不使用 Physics World implicit registry”。
- [x] 接受两个对象适配节点输出同一种严格 `MC2MeshObjectSpec`。
- [x] 接受自定义对象完整替代面板，不提供 sparse fallback。
- [x] 接受 Mesh 域只输入包装对象并输出完整 partitions。
- [x] 接受 collector 重复 stable ID 直接报错，不提供覆盖优先级。
- [x] 使用统一 16 组碰撞合同，不公开第二套 group/mask authoring。
- [x] 删除 MeshCloth authoring 的全部参与/执行类 `enabled`状态，统一使用连接和 mute。
- [x] collector 公开名称使用 `MC2 Mesh域收集`。
- [x] 对象节点名称使用 `MC2 MeshCloth对象`和`MC2 MeshCloth自定义对象`。
