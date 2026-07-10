# Physics World 外部物理属性所有权迁移规划

日期：2026-07-10

状态：实施中；Phase 0/1/2/3/4/5 已完成，下一步为 Phase 6 MC2/BoneCloth 目录归并

范围：顶层 `PhysicsTools` 持有的持久物理属性、注册生命周期、面板、操作器、碰撞预览和 MeshCloth Blender I/O；后续把 MC2/BoneCloth 包并入 `physicsWorld`。

## 结论

“Physics World 持有属性”分为三层，不能理解为把 Blender `PropertyGroup` 实例长期塞进 `PhysicsWorldCache`：

```text
Blender ID 数据块
  保存稳定 RNA 路径和原始用户值
  Bone.hotools_collision / Object.hotools_* / Scene.ho_*
          |
          v
Physics World component
  持有 capability schema、PropertyGroup class、binding 声明和注册生命周期
          |
          v
resolver / spec builder
  生成普通 profile/spec、签名和数组快照
          |
          v
PhysicsWorldCache / solver slot
  只持有归一化运行时数据，不持有 PropertyGroup 作为长期事实源
```

最终只有 Physics World 的 Blender lifecycle 可以注册或注销物理 RNA。UI、solver、preview 和旧节点都是消费者，不再定义属性，也不再决定注册顺序。

## 当前盘点

`PhysicsTools/physicsProperty.py` 当前混合了四个不同领域：

| 当前类型 / binding | 当前消费者 | 最终语义 owner |
|---|---|---|
| `PG_Hotools_ObjectCollision` / `Object.hotools_object_collision` | Physics World collider snapshot、SpringBone、MeshCloth、旧 XPBD、碰撞预览 | `physicsWorld.collision` 共享 capability |
| `PG_Hotools_BoneCollision` / `Bone.hotools_collision`（目前已在 `spring_vrm`） | SpringBone、BoneCloth、MeshCloth、scope、面板/预览 | `physicsWorld.collision` 共享 capability，不属于 SpringBone 私有域 |
| `PG_Hotools_MeshCollision` / `Object.hotools_mesh_collision` | 旧 XPBD、MC2 MeshCloth、scope、面板/预览、base-pose proxy | `physicsWorld.mesh_cloth` solver/domain capability |
| `PG_Hotools_RigidBody` / `Object.hotools_rigid_body` | `physicsWorld.rigid` scope/spec/UI/tests | `physicsWorld.rigid` solver capability |
| `PG_Hotools_RigidConstraint` / `Object.hotools_rigid_constraint` | `physicsWorld.rigid` scope/spec/UI/tests | `physicsWorld.rigid` solver capability |
| `Scene.ho_collision_overlay_*`、`Scene.ho_bone_collision_show_*` | 面板、header、GPU preview | `physicsWorld.ui` 的 Blender UI state，不进入 solver capability |
| Operator 自身的 `Bool/Enum/FloatProperty` | 单次 UI 命令参数 | Operator class 自持，不进入持久属性 registry |

顶层 `PhysicsTools` 的其它文件也不是同一领域：

| 当前文件 | 最终位置 |
|---|---|
| `physicsUtils.py` | 碰撞组常量/位操作进入 `physicsWorld/collision/groups.py`；选择与 UI helper 进入 `physicsWorld/ui/` |
| `physicsOperators.py` | `physicsWorld/ui/operators.py`，只消费 capability/resolver |
| `physicsPanel.py` | `physicsWorld/ui/panels.py` |
| `collisionPreview.py` | `physicsWorld/ui/collision_preview.py` |
| `meshClothBasePose.py` | `physicsWorld/mesh_cloth/base_pose.py` |
| `deltaOutput.py` | `physicsWorld/mesh_cloth/delta_output.py` |
| `PhysicsTools/__init__.py` | 由 `physicsWorld/blender.py` 和 component registry 取代，最终删除 |

## 所有权规则

### 共享 capability

满足以下任一条件的属性进入 Physics World 共享域：

- 被两个或以上 solver 消费；
- 在 world Begin/scope 阶段就必须解析；
- 表达跨 solver 的公共碰撞、过滤组或对象身份语义。

因此 `object_collision`、`bone_collision` 和 16 组 collision mask 归 `physicsWorld.collision`。SpringBone、MeshCloth、BoneCloth 只声明 `consumes_capabilities`，不能复制字段表或持有 RNA class。

### Solver 私有 capability

只影响单个 solver 的规格、拓扑或后端同步策略的属性留在 solver domain：

- `mesh_collision` -> `physicsWorld.mesh_cloth`
- `rigid_body` / `rigid_constraint` -> `physicsWorld.rigid`

solver capability 是字段语义、默认值、RNA metadata 和 update policy 的唯一事实源。PropertyGroup class 由 capability 生成或严格审计，面板不得另存一份默认值/枚举表。

### UI state

碰撞叠加层开关、展开状态和 preview mode 不是物理规格。它们可以继续存于 `Scene.ho_*`，但定义与注册属于 `physicsWorld.ui`。UI state 不进入 solver declaration，不参与 world generation/signature。

## 稳定存储契约

第一轮迁移保留以下路径、字段 identifier、字段类型和 enum identifier：

```text
Bone.hotools_collision
Object.hotools_object_collision
Object.hotools_mesh_collision
Object.hotools_rigid_body
Object.hotools_rigid_constraint
Scene.ho_collision_overlay_*
Scene.ho_bone_collision_show_*
```

PropertyGroup 的 Python module 可以改变，class 名称第一轮也保持不变。迁移期间禁止同时注册旧 class 和新 class；同一 owner/name 永远只有一个 binding。

这不是为旧节点保留兼容路径，而是低成本保留 `.blend` 原始数据。以后如需重命名持久路径，必须单独设计版本化 data migration，不能和目录迁移混在同一提交。

## 最终目录

```text
physicsWorld/
  __init__.py
  blender.py                    # HoTools 根插件调用的唯一 register/unregister 入口
  registry.py                   # component/solver 发现与运行入口
  blender_registry.py           # domain 级 class/binding/hook 生命周期与回滚日志

  collision/
    __init__.py
    capabilities.py             # object_collision、bone_collision、group mask
    properties.py               # 两个 PG class + Object/Bone binding 声明
    profiles.py                 # PropertyGroup/override -> immutable profile
    groups.py                   # 组数、mask、颜色和纯位操作

  mesh_cloth/
    __init__.py                 # solver/component descriptor
    capabilities.py
    properties.py               # PG_Hotools_MeshCollision
    base_pose.py
    delta_output.py
    mc2/                        # 后续由 physicsMC2MeshCloth 迁入

  bone_cloth/
    mc2/                        # 后续由 physicsMC2BoneCloth 迁入

  rigid/
    capabilities.py
    properties.py               # PG_Hotools_RigidBody / RigidConstraint
    ...                         # 当前 rigid solver 文件保持

  spring_vrm/
    ...
    # 不再定义 BoneCollision PG；只消费 collision capability

  ui/
    __init__.py
    properties.py               # Scene overlay/editor state
    operators.py
    panels.py
    collision_preview.py
```

## Component registry

现有 `registry.py` 只发现 solver，而且 Blender 属性注册是全局一次性列表。需要增加 component 层，不能把共享 collision 和 UI 假装成 solver。

建议 descriptor 最小结构：

```python
{
    "component_id": "collision",
    "kind": "core",             # core | solver | ui
    "depends_on": (),
    "blender_properties": ".properties:BLENDER_PROPERTIES",
    "register_hooks": (),
    "unregister_hooks": (),
}
```

内置依赖图：

```text
collision (core)
  <- spring_vrm
  <- mesh_cloth
  <- bone_cloth

rigid (solver)
mesh_cloth (solver)
spring_vrm (solver)
bone_cloth (solver)

collision + rigid + mesh_cloth + spring_vrm + bone_cloth
  <- physics_ui
```

registry 必须具备：

1. 按 domain/component 记录已注册 class、binding 和 hook，不使用全局 all-or-nothing early-return。
2. 注册前预检所有 `(owner, name)` 冲突、class 重复、依赖缺失和 binding 类型。
3. 依赖拓扑顺序注册、逆序注销；共享 component 使用引用计数或显式 dependents 检查。
4. `register_solver_module()` 在 Blender lifecycle 已启动时能立即注册该 solver 的属性；`unregister_solver_module()` 只释放该 domain。
5. domain 注册失败只回滚该 domain 的 journal。core collision 失败视为物理世界启动失败；可选 solver 失败应禁用该 solver 并保留其它 domain。
6. binding 不只支持 PointerProperty；Scene Bool/Enum 等由声明中的 property factory + kwargs 统一创建。

## 根插件生命周期

Physics UI 和持久属性目前不依赖用户是否启用 OmniNode，因此迁移后仍应随 HoTools 主插件注册，而不是随 `hoTools_OmniNodeFeatures_enable` 开关消失。

目标调用关系：

```text
HoTools.register()
  -> physicsWorld.blender.register()       # 总是执行
       -> register core/solver properties
       -> register physics UI classes
       -> install preview handler/header
  -> OmniNode.register()                   # 仅在功能开关启用时注册节点系统
```

从 HoTools 根模块导入嵌套的 `physicsWorld.blender` 会先执行 `OmniNode/__init__.py`，因此必须先把 `OmniNode/__init__.py` 改为轻量 lazy import：顶层不再导入 `OmniNodeRegister`，相关模块只在 `OmniNode.register()` 内导入。否则属性注册会意外加载全部节点、native backend 和 GPU/UI 模块。

注销顺序固定为：preview/header -> panel/operator/UI state -> solver bindings/classes -> shared bindings/classes。重复 register/unregister 必须幂等或给出明确错误，不能残留 RNA。

## 运行时数据边界

迁移完成后，scope 和 solver 不应把 live `PropertyGroup` 作为跨帧事实源：

```text
PropertyGroup
  -> resolve_object_collision_profile / resolve_bone_collision_profile
  -> CollisionProfile(signature, plain values)
  -> PhysicsColliderSource.profile
  -> collider_snapshot/native arrays
```

Rigid 已经通过 `RigidBodySpec/ConstraintSpec` 接近该边界；MeshCloth 应形成 `MeshClothSpec`。`PhysicsColliderSource.props` 最终改为 `profile`，避免 PropertyGroup class 移动、RNA 注销或 UI 热改让旧 world cache 持有过期对象。

显式 RNA 和隐式 override 必须进入同一个 resolver，再生成同一种 profile/spec；solver 不允许分别实现两套字段解释。

## 分阶段实施

### Phase 0：契约冻结与测试夹具

- 记录五个稳定 binding 的完整 RNA fingerprint：字段名、类型、默认值、min/max/soft range、enum identifier、pointer poll。
- 建立旧 class 保存 `.blend`、新 class 重开验证的迁移测试；覆盖非默认值、bitmask、Object pointer 和全部 rigid constraint 字段。
- 建立重复 register/unregister、domain 失败回滚和 OmniNode 开关不影响物理属性的生命周期测试。

### Phase 1：component/blender registry

- 新增 domain 级 registration journal、依赖图和 binding factory。
- 先让现有 SpringBone property descriptor 通过新 registry 注册，行为不变。
- 此阶段不移动 PropertyGroup，验证新旧 registry 结果完全一致后删除旧全局列表。

### Phase 2：共享 collision 所有权

- 将 BoneCollision capability/class 从 `spring_vrm` 移到 `physicsWorld.collision`。
- 将 ObjectCollision capability/class 从 `PhysicsTools` 移到 `physicsWorld.collision`。
- SpringBone declaration 改为消费共享 capability；scope、preview、MC2 和旧 XPBD 改用共享 resolver/constants。
- 保留 `Bone.hotools_collision` 与 `Object.hotools_object_collision`。

### Phase 3：Rigid 属性原子化

- 把 `PG_Hotools_RigidBody/Constraint` 移到 `rigid/properties.py`。
- 将 `rigid/capabilities.py` 从摘要表扩展为完整 RNA schema，消除当前 capability 与 PropertyGroup 两份字段事实源。
- `rigid.SOLVER_MODULE` 声明 `blender_properties`，测试不再 import `PhysicsTools.physicsProperty`。

### Phase 4：MeshCloth 属性与 Blender I/O

- 建立 `physicsWorld.mesh_cloth` component/solver domain。
- 移动 `PG_Hotools_MeshCollision`、base-pose proxy 与 delta output。
- 旧 XPBD、MC2 MeshCloth 和面板统一改 import；保留 `Object.hotools_mesh_collision`。

### Phase 5：UI 与根生命周期

- 移动 panels/operators/preview/Scene UI state。
- 轻量化 `OmniNode/__init__.py`，根 HoTools 改调 `physicsWorld.blender.register/unregister`。
- 删除 `PhysicsTools` 注册入口，再确认全仓没有 `PhysicsTools` import 后删除目录。

### Phase 6：MC2/BoneCloth 目录归并

- `physicsMC2MeshCloth` -> `physicsWorld/mesh_cloth/mc2`。
- `physicsMC2BoneCloth` -> `physicsWorld/bone_cloth/mc2`。
- presets、tests、runtime、backend 和 node module descriptor 一起移动；不保留长期包别名。
- 独立修复并跑通 MC2 scene parity 后再删除旧目录。

每个 Phase 单独提交。允许短期 import adapter，但禁止双 RNA binding、双 schema 或双注册入口；adapter 必须在 Phase 5/6 结束时删除。

## 验收矩阵

### 数据与 RNA

- 五个持久 binding 的 `.blend` 往返数据逐字段一致。
- class/module 移动前后 RNA fingerprint 一致。
- Scene overlay 状态路径保持，注销后所有 owner attr 消失。
- 每个 component 可独立注册/注销；共享依赖不会被提前释放。

### 行为

- Object/Bone collider 生成的 profile、signature、world collider arrays 与迁移前一致。
- SpringBone Blender suite、py311/py313 native suite 全绿。
- Rigid Blender/Jolt suite 与 semantic fixture matrix 全绿。
- MC2 MeshCloth/BoneCloth、scene parity、base-pose/delta output 全绿。
- 面板编辑、批量碰撞组操作、渐变半径和 GPU preview 在交互 Blender 中通过。

### 架构

- `rg "PhysicsTools"` 在运行时代码中为零；历史文档可保留说明。
- `physicsWorld` 以外没有物理 PropertyGroup class 或物理 RNA binding。
- solver/UI 不复制 capability 默认值、enum 和范围。
- `PhysicsWorldCache`/solver slot 不跨帧保存 `PropertyGroup` 实例。
- OmniNode 关闭时物理属性/UI 仍存在；重新开启不会重复注册。

## 明确不做

- 不迁移旧 SpringBone 节点图，不增加 missing-node 兼容类。
- 不在目录迁移中重命名稳定 RNA 路径。
- 不让 UI component 进入 solver declaration 或 world generation。
- 不一次性搬完所有文件后再测试；按 property core、solver domain、UI、MC2 四个边界逐段关闭。

## 开始实现的第一刀

第一刀只做 Phase 0 + Phase 1：先建立 RNA fingerprint/`.blend` 夹具和 domain registration journal，让现有 SpringBone binding 通过新 component registry 完成注册/注销。验证通过后才移动 Bone/Object collision class。这样后续每次文件移动都只是 owner 替换，不再同时修改注册基础设施。

## 2026-07-10 Phase 0/1 实施记录

已完成：

- 新增 `physicsWorld/blender_registry.py`，按 domain 保存 class/binding/dependency/registration order，不再用全局 class/binding 一次性列表。
- 支持 Pointer/Bool/Enum/Float/FloatVector/Int/String/Collection binding factory，owner 可以是 `bpy.types` 对象或类型名。
- 注册前检查依赖、owner/name 冲突、重复 class 和同 domain 声明漂移；注册中失败按该 domain journal 逆序回滚。
- domain 被其它 domain 依赖时拒绝提前注销；插件整体注销按真实注册逆序强制释放。
- 现有 `register_solver_blender_properties()` 已改走 domain registry；runtime `register_solver_module()`/`unregister_solver_module()` 在 lifecycle 活跃时会立即注册/释放本 solver 的 RNA。
- 冻结 BoneCollision、ObjectCollision、MeshCollision、RigidBody、RigidConstraint 五个 PropertyGroup 的完整 annotation contract hash 与字段列表。
- `.blend` 夹具会给五个 PropertyGroup 的全部 96 个字段写入非默认值，包含 bitmask、FloatVector、Mesh/Object pointer；保存后注销/重注册 class 与 binding，再重开文件逐字段比对。

验证：

- property registry / RNA contract / `.blend` roundtrip：`4/4`
- Blender SpringBone：`36/36`
- 真实 `PhysicsTools.register()/unregister()` 通过，现有 Object/Bone/Scene binding 无泄漏
- `py_compile`、目标 diff check 通过

当前刻意未做：MeshCollision、RigidBody/Constraint 与 Scene UI state 仍位于原模块，根注册入口仍是 `PhysicsTools`。

## 2026-07-10 Phase 2 实施记录

已完成：

- 新增 `physicsWorld.collision` core component；Bone/Object collision capability、PropertyGroup class、RNA binding、碰撞组数量/mask/颜色均由该 component 唯一持有。
- `Bone.hotools_collision` 与 `Object.hotools_object_collision` 的稳定路径、class 名、字段顺序、RNA metadata 与 enum identifier 保持不变；旧 `PhysicsTools.physicsProperty.PG_Hotools_ObjectCollision` 仅保留惰性 import adapter，不存在双 class 或双 binding。
- SpringBone 删除私有 `properties.py`，declaration 改为 `consumes_capabilities=["bone_collision"]`；resolver、隐式覆写、节点和 debug draw 全部消费共享 schema/常量。
- component registry 现在可解析并合并共享 capability，同时拒绝两个 component 重复拥有同一 capability identifier。
- `PhysicsTools.physicsUtils` 的碰撞组私有名字改为共享常量别名，旧 UI/preview 消费方无需同步改名但不再复制事实表。
- Rigid 与 MC2 Blender 夹具改从 canonical collision owner 导入；MC2 scene parity 同时对齐当前 solver keyword 参数和 `MC2RuntimeOwner` 生命周期。

验证：

- property registry / capability ownership / RNA contract / `.blend` roundtrip：`5/5`
- 真实 `PhysicsTools.register()/unregister()`：通过，Object/Bone/Mesh/Rigid binding 无泄漏
- Blender SpringBone：`36/36`
- Blender Rigid/Jolt：`24/24`
- MC2 Blender scene parity：collision mode 1/2 均通过；最大 Python/C++ delta 分别为 `1.1e-7` / `0`

Phase 2 提交边界：当时 Rigid 与 MeshCloth 的 PropertyGroup 所有权尚未移动；UI/preview 文件也尚未迁入 `physicsWorld.ui`，根调用入口仍由 `PhysicsTools` 触发。随后 Phase 3 第一刀只迁移 Rigid class/binding，不同时搬 UI。

## 2026-07-10 Phase 3 第一刀实施记录

已完成：

- `PG_Hotools_RigidBody` 与 `PG_Hotools_RigidConstraint` 原样迁入 `physicsWorld.rigid.properties`，两个稳定 Object binding 改由 rigid solver domain 注册。
- rigid descriptor 声明 `property_dependencies=("collision",)`；完整注册顺序变为 `collision -> rigid`，运行中卸载其它 solver 不影响这两个 binding。
- `PhysicsTools.physicsProperty` 不再定义 Rigid PropertyGroup，只保留惰性旧导入适配；`PhysicsTools.register()` 不再注册/注销 Rigid class 或 binding。
- Rigid Blender 夹具与属性契约夹具均改从 canonical owner 导入；旧 import adapter identity 也进入回归。

验证：

- 五个 PropertyGroup RNA contract hash 与 `.blend` 96 字段往返：`5/5`
- 真实 `PhysicsTools.register()/unregister()`：通过，domain 顺序为 `collision -> rigid`
- Blender Rigid/Jolt：`24/24`

Phase 3 第二刀已关闭：

- 新增不导入 `bpy` 的 `rigid.schema`，完整保存 34 个 RigidBody 与 37 个 RigidConstraint 字段的 property factory、RNA metadata、默认值、范围、单位和 enum identifier。
- `rigid.properties` 只从 schema 生成两个 PropertyGroup；`rigid.capabilities` 从同一 schema 投影完整 71 字段能力表，并只额外叠加 solver update policy。
- 新增 schema/RNA/capability 三方逐字段一致性测试；原冻结 contract hash 无变化，证明生成式重构没有改变持久 RNA。

Phase 3 已完成。下一步进入 Phase 4：建立 `physicsWorld.mesh_cloth` domain，迁移 `PG_Hotools_MeshCollision`、base-pose proxy 与 delta output；不在同一刀移动 MC2 整包。

## 2026-07-10 Phase 4 第一刀实施记录

已完成：

- 新增 `physicsWorld.mesh_cloth` solver domain，声明对共享 collision component 的属性依赖。
- `PG_Hotools_MeshCollision` 的 11 字段 schema、capability、PropertyGroup class 与 `Object.hotools_mesh_collision` binding 全部迁入该 domain。
- `mc2_base_pose_proxy` 的 Object pointer 与 mesh-only poll 被纯 schema 标识并在 Blender 层还原；原 RNA contract hash 保持不变。
- `PhysicsTools.physicsProperty` 已变为纯惰性 import adapter，不再定义任何 PropertyGroup；`PhysicsTools.register()` 不再直接注册任何物理持久 class/binding。
- MC2 scene parity 夹具改从 canonical mesh_cloth owner 导入。

验证：

- property registry / schema ownership / RNA contract / `.blend` roundtrip：`7/7`
- 完整注册顺序：`collision -> rigid -> mesh_cloth`，真实 PhysicsTools lifecycle 通过
- MC2 Blender scene parity：collision mode 1/2 均通过

Phase 4 尚未关闭：下一刀迁移 `meshClothBasePose.py` 与 `deltaOutput.py` 到 `physicsWorld.mesh_cloth`，旧 PhysicsTools 文件只保留短期 import adapter；随后统一 Physics.py、MC2 blender_io/runtime 和 UI operator/panel 的 canonical import。

Phase 4 第二刀已关闭：

- `deltaOutput.py` 与 `meshClothBasePose.py` 的唯一实现迁入 `physicsWorld.mesh_cloth.delta_output/base_pose`。
- Physics.py、MC2 blender_io/runtime、PhysicsTools operator/panel 全部改用 canonical import；旧 PhysicsTools 两文件只保留惰性属性适配。
- 生命周期测试真实创建 Mesh、delta point attribute、GN 后置修改器与 BasePose 只读代理，并验证旧/新 import identity、拓扑一致性、缓存标志和 RNA pointer 写回。
- MC2 scene parity 两种碰撞模式保持通过。

Phase 4 已完成。下一步进入 Phase 5：迁移 PhysicsTools panel/operator/collision preview 与 Scene UI state，建立 `physicsWorld.blender` 根注册入口并轻量化 `OmniNode.__init__`。

## 2026-07-10 Phase 5 实施记录

已完成：

- panel、operator、collision preview、UI utils 与 10 个稳定 Scene RNA 全部迁入 `physicsWorld.ui`；UI binding 作为 `physics_ui` domain 依赖 collision/rigid/mesh_cloth。
- 新增 `physicsWorld.blender` 唯一根生命周期；HoTools 根插件直接调用它，不再导入 PhysicsTools。
- `OmniNode.__init__` 改为惰性加载 `OmniNodeRegister/OmniNodeTree` 并增加状态守卫；OmniNode 关闭时插件 enable/disable 不加载整套节点、Native 与节点 GPU 模块。
- 删除只剩兼容适配的 `PhysicsTools` 目录；Python 运行时代码中的 `PhysicsTools` 引用为零。
- 更新 rewind 夹具到 canonical Rigid property owner，并同步现行 world result API。

验证：

- property registry/schema/RNA/`.blend` roundtrip：`7/7`
- Physics World Blender/UI 两轮 register/unregister：通过，domain 顺序 `collision -> rigid -> mesh_cloth -> physics_ui`
- SpringBone `36/36`、Rigid/Jolt `24/24`、MC2 scene parity mode 1/2、rewind/same-frame/prune：全部通过
- 隐藏的真实 Blender `addon_enable/addon_disable("HoTools")`：退出码 0；PhysicsTools 未加载，OmniNodeRegister 在功能关闭时未加载，所有 Object/Bone/Scene RNA 注销完整

Phase 5 已完成。下一步进入 Phase 6：把 `physicsMC2MeshCloth` 与 `physicsMC2BoneCloth` 归并到 `physicsWorld/mesh_cloth/mc2` 和 `physicsWorld/bone_cloth/mc2`，按包逐个更新 descriptor、测试与 import，不保留长期包别名。
