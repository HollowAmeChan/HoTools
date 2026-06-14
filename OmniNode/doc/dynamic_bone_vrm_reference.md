# OmniNode Dynamic Bone / VRM SpringBone Reference

本文记录对本地 UniVRM 包的 SpringBone 实现研究，并据此补充 OmniNode 动骨系统设计。

参考代码来自：

- `D:\Unity_Project\BREAK_URP\Packages\com.vrmc.univrm`
- `com.vrmc.univrm/package.json`: `0.131.0`
- 主要文件：
  - `Runtime/SpringBone/VRMSpringBone.cs`
  - `Runtime/SpringBone/VRMSpringBoneColliderGroup.cs`
  - `Runtime/SpringBone/Logic/SpringBoneSystem.cs`
  - `Runtime/SpringBone/Logic/SpringBoneJointInit.cs`
  - `Runtime/SpringBone/Logic/SpringBoneJointState.cs`
  - `Runtime/SpringBone/Logic/SphereCollider.cs`
  - `Runtime/SpringBone/Jobs/FastSpringBoneReplacer.cs`
  - `Runtime/SpringBone/Jobs/FastSpringBoneService.cs`

同一工程里的 `com.vrmc.gltf` 与 `com.vrmc.vrm` 还包含 VRM 1.0 / SpringBoneJobs 的通用碰撞实现，可作为胶囊、平面、inside collider 的后续扩展参考：

- `com.vrmc.gltf/Runtime/SpringBoneJobs/SpringBoneCollision.cs`
- `com.vrmc.gltf/Runtime/SpringBoneJobs/Blittables/BlittableCollider.cs`
- `com.vrmc.gltf/Runtime/SpringBoneJobs/Blittables/BlittableColliderType.cs`
- `com.vrmc.vrm/Runtime/Components/Vrm10Runtime/Springbone/FastSpringBoneBufferFactory.cs`

## 1. UniVRM 0.x SpringBone 的核心模型

UniVRM 0.x 的 `VRMSpringBone` 是一个高封装组件，不要求用户搭复杂物理图。组件本身持有：

- `m_stiffnessForce`
- `m_gravityPower`
- `m_gravityDir`
- `m_dragForce`
- `m_center`
- `RootBones`
- `m_hitRadius`
- `ColliderGroups`
- `ExternalForce`
- `m_updateType`

执行入口是 `LateUpdate`、`FixedUpdate` 或 `ManualUpdate`。`DefaultExecutionOrder(11000)` 表示它故意晚于普通动画/IK 执行，这一点对应 Blender 中应尽量在帧更新后段写回 pose。

它内部不把每条链拆成一个 solver，而是由 `SpringBoneSystem` 维护所有 joint 状态。

### 1.1 SceneInfo

UniVRM 把每次求解所需的外部上下文包装为 `SceneInfo`：

- root bones
- center transform
- collider groups
- external force

对 OmniNode 的启发：主 solver 节点应该接收一组 chain setting 和一个 collision world，而不是让用户拼低层状态流。

### 1.2 SpringBoneSettings

UniVRM 的设置是组件级的：

- stiffness
- drag
- gravity direction
- gravity power
- hit radius
- runtime scaling support

我们的设计因为需要“每条链独立设置”，应把这些参数放到 `SpringChainSetting` 节点中。主 solver 接收 `list[_OmniSpringChainSetting]`，每条链独立使用自己的参数。

### 1.3 Joint 初始化

`SpringBoneSystem.SetupRecursive` 会为 root 下每个 Transform 创建 joint：

- 有子物体时，用第一个 child 的 local position 当 tail 方向。
- 没有子物体时，生成一个虚拟 child：沿当前骨骼方向延伸固定距离 `0.07 * UniformedLossyScale()`。
- 保存：
  - 初始 local rotation
  - bone axis
  - bone length
  - current tail
  - previous tail

我们的 Blender 版本已经使用 PoseBone head/tail，所以不需要 Unity 的虚拟 child 规则作为主路径。但如果遇到零长度叶骨或 leaf target 不明确，可以参考这个逻辑生成一个 fallback tail。

### 1.4 Verlet 推进公式

UniVRM 的 `SpringBoneJointInit.VerletIntegration` 核心公式是：

```text
nextTail =
    currentTail
    + (currentTail - prevTail) * (1 - dragForce)
    + parentRotation * localRotation * boneAxis * stiffnessForce * deltaTime * scalingFactor
    + (gravityDir * gravityPower + externalForce) * deltaTime * scalingFactor
```

然后强制恢复骨长：

```text
nextTail = head + normalize(nextTail - head) * boneLength
```

这和我们现有 `springBoneBase` 的方向一致。需要继续保持：

- tail 状态在世界空间或 center 空间保存。
- 每步先 Verlet，再骨长约束。
- 碰撞后再次骨长约束。

### 1.5 Center 空间

`SpringBoneJointState` 可以把 current/prev tail 存在 center local space 中：

- `Init(center, transform, localChildPosition)`
- `Make(center, currentTail, nextTail)`
- `ToWorld(center)`

这能减少角色整体移动时的拖尾异常。我们现在 `springBoneBase` 用 world space cache，短期可以继续，但后续建议增加 `center` 概念：

- 默认 center = armature object
- 或允许 solver 输入 center object/bone
- state 中保存 center transform version 或 center-space tail

对 Blender 版本来说，center-space 会比纯 world-space 更接近 VRM 行为。

## 2. UniVRM 0.x 碰撞模型

`VRMSpringBoneColliderGroup` 只支持 sphere collider：

```text
collider center = colliderGroup.transform.TransformPoint(collider.Offset)
collider radius = max(lossyScale.x, lossyScale.y, lossyScale.z) * collider.Radius
```

`SphereCollider.TryCollide` 使用 joint hit radius 与 collider radius 之和：

```text
jointRadius = settings.HitRadius * transform.UniformedLossyScale()
minDistance = jointRadius + colliderRadius
```

如果：

```text
length(nextTail - colliderCenter)^2 <= minDistance^2
```

则推出：

```text
normal = normalize(nextTail - colliderCenter)
posFromCollider = colliderCenter + normal * minDistance
```

然后 SpringBoneSystem 再做一次骨长约束：

```text
nextTail = head + normalize(posFromCollider - head) * boneLength
```

### 2.1 对 OmniNode 的碰撞结论

短期最稳实现：

- 每个模拟骨的 tail 看作一个有半径的粒子。
- `SpringChainSetting.hit_radius` 对应 VRM `m_hitRadius`。
- collider 先支持 sphere。
- capsule 可以紧跟着支持，因为我们已有骨骼/物体 capsule authoring 属性。
- 每次碰撞推出后恢复骨长。

注意边界：

- 当 `nextTail == colliderCenter` 时 normalize 会退化。实现时要用 fallback normal，例如当前骨方向、rest axis 或 `(0, 0, 1)`。
- 多 collider 顺序会影响结果。先接受这个行为，后续如有需要可做迭代次数。

## 3. VRM 1.0 / SpringBoneJobs 扩展参考

`com.vrmc.gltf` 的 `SpringBoneCollision` 支持：

- Sphere
- Capsule
- Plane
- SphereInside
- CapsuleInside

`BlittableCollider` 的数据字段是：

- `offset`
- `tailOrNormal`
- `radius`
- `colliderType`
- `transformIndex`

这说明 VRM10 把 collider 做成可批处理数据，不再依赖 MonoBehaviour 层级对象实时遍历。对我们有两个启发：

1. `CollisionWorldFromScene` 应输出纯数据快照，而不是直接把 Blender object/bone 当作运行时唯一数据源。
2. `DynamicBoneSolver` 内部应消费 collider spec，不要在每个 joint 求解时反复遍历场景属性。

### 3.1 Sphere

外部球碰撞：

```text
r = joint.radius + collider.radius * colliderScale
if length(nextTail - center)^2 <= r^2:
    pos = center + normalize(nextTail - center) * r
    nextTail = head + normalize(pos - head) * boneLength
```

### 3.2 Capsule

VRM10 的 capsule 碰撞等价于：

1. 计算 collider segment 的最近点。
2. 对最近点做 sphere 碰撞。
3. 碰撞后恢复骨长。

代码里通过 segment direction、dot 与 segment length 判断 head 半球、tail 半球、中段最近点。我们的实现可以使用更直接的 closest-point-on-segment：

```text
t = dot(point - a, b - a) / length_squared(b - a)
t = clamp(t, 0, 1)
closest = a + (b - a) * t
```

### 3.3 Plane / inside colliders

Plane 和 inside variants 暂不建议第一版实现。它们适合后续扩展，因为当前 HoTools authoring 层已经有 sphere/capsule，且 VRM 0.x 也只用 sphere。

## 4. OmniNode 目标设计

当前原则：

- 不做 `GraphNode`。
- 不加 `stateful=True`。
- 不改编译指令。
- 用普通 function node + 普通 socket marker 类型完成。
- 用户图上可以每条链一个 setting 节点，但最终只有一个骨架级 solver。

推荐图结构：

```text
Armature Object
  -> Bone From Name
  -> BoneChain From Root
  -> Spring Chain Setting
       \
        -> Dynamic Bone Solver.chain_settings  # multi input
       /
  -> BoneChain From Root
  -> Spring Chain Setting

Scene
  -> Collision World From Scene
  -> Dynamic Bone Solver.collision_world
```

也允许：

```text
Dynamic Bone Solver(scene=None, collision_world=None)
```

如果 `collision_world` 未连接，solver 自己从 `scene` 或 `bpy.context.scene` 收集。

## 5. 新增 Socket / Marker 类型

在 `OmniNodeSocketMapping.py` 增加 marker：

```python
class _OmniCollisionWorld:
    def __init__():
        return

class _OmniSpringChainSetting:
    def __init__():
        return
```

在 `OmniNodeSocket.py` 增加：

```python
class OmniNodeSocketCollisionWorld(NodeSocket):
    bl_label = "CollisionWorld-Omni"
    bl_idname = "OmniNodeSocketCollisionWorld"
    default_value: bpy.props.StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.10, 0.55, 0.75, 1.0)


class OmniNodeSocketSpringChainSetting(NodeSocket):
    bl_label = "SpringChainSetting-Omni"
    bl_idname = "OmniNodeSocketSpringChainSetting"
    default_value: bpy.props.StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.70, 0.42, 0.22, 1.0)
```

注册到 socket class list，并加入 `SKT_DIC`：

```python
_OmniCollisionWorld: OmniNodeSocketCollisionWorld
_OmniSpringChainSetting: OmniNodeSocketSpringChainSetting
```

## 6. 新增节点设计

全部放在 `OmniNode/NodeTree/Function/Physics.py`，通过 `@omni(enable=True)` 注册。

### 6.1 Bone From Name

用于从 armature + root name 生成 `_OmniBone`：

```python
def boneFromName(
    armature_obj: bpy.types.Object,
    bone_name: str,
) -> _OmniBone
```

行为：

- 校验 armature。
- 校验 bone 存在。
- 输出 `_BonePhysics.bone_socket_value(armature_obj, bone_name)`。

### 6.2 BoneChain From Root

保留现有 `boneChainFromRoot`。

需要注意：当前 `include_branches=True` 会把 root 下所有子层级收集成一个 chain list。对于多分支骨骼，后续 solver 内部要明确这是“树状链”还是“扁平骨列表”。短期可以要求动骨 root 不要包含分叉，或在 setting 中保留 `include_branches` 语义。

### 6.3 Spring Chain Setting

每条链一个 setting 节点：

```python
def springChainSetting(
    bone_chain: _OmniBoneChain,
    enabled: bool = True,
    stiffness_force: float = 1.0,
    drag_force: float = 0.4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 0.0,
    hit_radius: float = 0.02,
    collision_margin: float = 0.0,
    collided_by_groups: int = 0,
) -> _OmniSpringChainSetting
```

输出 dict：

```python
{
    "version": 1,
    "armature": armature_obj,
    "root_bone": root_name,
    "bones": list(chain["bones"]),
    "enabled": bool(enabled),
    "stiffness_force": max(stiffness_force, 0.0),
    "drag_force": clamp(drag_force, 0.0, 1.0),
    "gravity_dir": Vector(...),
    "gravity_power": max(gravity_power, 0.0),
    "hit_radius": max(hit_radius, 0.0),
    "collision_margin": max(collision_margin, 0.0),
    "collided_by_groups": int(mask),
}
```

### 6.4 Collision World From Scene

```python
def collisionWorldFromScene(
    scene: bpy.types.Scene = None,
    include_bone_colliders: bool = True,
    include_object_colliders: bool = True,
) -> _OmniCollisionWorld
```

输出 dict：

```python
{
    "version": 1,
    "frame": scene.frame_current,
    "colliders": [
        {
            "type": "SPHERE" | "CAPSULE",
            "owner_type": "BONE" | "OBJECT",
            "owner": object,
            "bone": bone_name or "",
            "primary_group": int,
            "center": Vector,
            "radius": float,
            "segment_a": Vector or None,
            "segment_b": Vector or None,
        }
    ],
}
```

短期规则：

- 骨骼 collider 从 `Bone.hotools_collision` 读取。
- 物体 collider 从 `Object.hotools_object_collision` 读取。
- `SPHERE`: 计算 world center 和 radius。
- `CAPSULE`: 计算 world segment endpoints 和 radius。
- 按 `primary_collision_group` 记录 group。

### 6.5 Dynamic Bone Solver

```python
def dynamicBoneSolver(
    armature_obj: bpy.types.Object,
    chain_settings: list[_OmniSpringChainSetting],
    collision_world: _OmniCollisionWorld = None,
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
) -> tuple[list[_OmniBone], bpy.types.Object]
```

`chain_settings` 是 multi input。solver 直接收集，不需要 hub 节点。

## 7. Dynamic Bone Solver 状态

不使用 Omni runtime cache。短期使用 `Physics.py` 模块级私有状态：

```python
_DYNAMIC_BONE_STATE = {}
_DYNAMIC_BONE_FRAME_WRITERS = {}
```

key 建议：

```python
(
    "dynamic_bone_solver",
    int(armature_obj.as_pointer()),
    topology_hash,
)
```

由于普通 function node 当前拿不到 node 实例，短期不能用 node uid。为避免同一 armature 被多个 solver 同帧写入：

- 在本帧记录 `armature_pointer -> writer_count`。
- 同一帧第二个 solver 写同一 armature 时抛错或 warning 后跳过。

state 结构：

```python
{
    "version": 1,
    "frame": current_frame,
    "armature_name": armature_obj.name_full,
    "topology_hash": "...",
    "chains": {
        root_bone: {
            "bones": [...],
            "joints": {
                bone_name: {
                    "current_tail": Vector,
                    "prev_tail": Vector,
                    "length": float,
                    "init_axis_local": Vector,
                    "init_axis_parent": Vector,
                    "init_rotation": Quaternion,
                    "init_scale": Vector,
                    "init_matrix_basis": Matrix,
                }
            }
        }
    }
}
```

## 8. Solver 算法

每帧执行：

1. 校验 armature。
2. 展平 `chain_settings`。
3. 过滤非本 armature 的 setting。
4. 按 `root_bone` 建 map。
5. 如果重复 root，报错。不要按 multi input 顺序覆盖，因为 OmniNode multi input 顺序不是视觉顺序。
6. 计算 topology hash：
   - armature pointer
   - root bone list
   - 每条 setting 的 bones list
7. 判断 reset：
   - 用户 reset
   - disabled 后重新 enabled
   - 无 state
   - state version 不匹配
   - topology hash 不匹配
   - 当前帧不是上一帧 + 1
8. reset 时从当前 pose 初始化所有 joint。
9. 获得 collision world：
   - 优先使用输入 `collision_world`
   - 其次从 `scene`
   - 最后从 `bpy.context.scene`
10. 对每个 substep：
    - 对每条 chain、每个 joint 做 Verlet。
    - 约束骨长。
    - 按 group mask 过滤 colliders。
    - sphere/capsule 碰撞推出。
    - 碰撞后再次约束骨长。
    - 生成目标 pose matrix。
11. 所有 chain 算完后统一写 `PoseBone.matrix_basis`。
12. 保存 next state。
13. 输出 affected bones 和 armature。

## 9. 碰撞求解细节

### 9.1 group mask

已有 authoring 属性：

- collider: `primary_collision_group`
- bone collider: `collided_by_groups`

对 setting 节点：

- `collided_by_groups == 0` 可以解释为“不碰撞任何 group”或“使用骨骼属性”。建议第一版明确为“不碰撞任何 group”，避免隐式行为。
- 如果希望默认碰撞，可在节点默认值设为全部 group mask。

检查：

```python
def can_collide(setting, collider):
    group = int(collider["primary_group"])
    return bool(setting["collided_by_groups"] & (1 << (group - 1)))
```

### 9.2 sphere collider

```text
min_dist = hit_radius + collider.radius + collision_margin
delta = next_tail - collider.center
if length(delta) < min_dist:
    pushed = collider.center + safe_normal(delta, fallback_axis) * min_dist
    next_tail = head + normalize(pushed - head) * joint.length
```

### 9.3 capsule collider

```text
closest = closest_point_on_segment(next_tail, segment_a, segment_b)
min_dist = hit_radius + collider.radius + collision_margin
delta = next_tail - closest
if length(delta) < min_dist:
    pushed = closest + safe_normal(delta, fallback_axis) * min_dist
    next_tail = head + normalize(pushed - head) * joint.length
```

### 9.4 自碰撞排除

第一版建议：

- 如果 collider 是同一个 armature 的 bone collider，且 collider bone 属于当前 chain，跳过。
- 链间碰撞暂不做，后续加 `enable_chain_collision`。

## 10. 与现有 springBoneBase 的关系

现有 `springBoneBase` 已经实现：

- chain cache
- world-space tail state
- Verlet
- bone length constraint
- 批量生成 target pose matrix
- 最后统一写 matrix_basis

新 solver 不应复制粘贴一份完全独立逻辑，而应逐步抽出内部工具：

- build joint init
- read/write joint state
- rest axis
- target head
- pose matrix from tail
- matrix basis conversion
- collision projection

短期可以在 `Physics.py` 内复用 `_BonePhysics` 方法。

## 11. 与 UniVRM 的设计差异

### 11.1 每条链参数

UniVRM 0.x 是一个 `VRMSpringBone` 组件持有多个 root bones，所有 root 共用参数。

OmniNode 设计为每条链一个 `SpringChainSetting` 节点。这样更适合节点图表达，也避免在一个节点里做复杂表格 UI。

### 11.2 一个骨架一个 solver

UniVRM 0.x 每个组件自己 update。FastSpringBoneJobs 则通过 `FastSpringBoneService` 把多个 SpringBone buffer 合并并统一 LateUpdate。

OmniNode 更接近 FastSpringBone 的思想：setting 节点分散表达，主 solver 统一求解和写回。

### 11.3 碰撞体来源

UniVRM collider group 是组件引用数组。OmniNode 的碰撞体来自 Blender bone/object property authoring，并在每帧生成 `CollisionWorld` 快照。

## 12. 落地顺序

建议分阶段：

1. 新增 `_OmniSpringChainSetting`、`_OmniCollisionWorld` marker 与 socket。
2. 新增 `boneFromName`。
3. 新增 `springChainSetting`。
4. 新增 `collisionWorldFromScene`，先支持 sphere，随后支持 capsule。
5. 新增 `dynamicBoneSolver`，先复用无碰撞求解，再加入 sphere/capsule。
6. 加同 armature 多 solver 检测。
7. 加调试输出：
   - affected bone count
   - chain count
   - collider count
   - reset reason
8. 后续再考虑 center-space state、substeps、chain collision、VRM10 inside/plane。

## 13. 风险与约束

- 当前普通 function node 拿不到 node 实例，因此 solver 私有状态不能以 node uid 作为 key。短期按 armature + topology hash 管理。
- Multi input 顺序不可作为覆盖语义。
- Blender PoseBone 写回比 Unity Transform 更敏感，必须继续坚持“先算完所有 target matrix，再统一写 matrix_basis”。
- frame jump 必须 reset 或恢复初始姿态，不能沿用旧速度。
- 碰撞后如果 normal 退化，必须使用 fallback normal，避免 NaN。

## 14. 推荐第一版范围

第一版目标：

- 用户一条链一个 setting 节点。
- 主 solver 一个 multi input 收集所有 setting。
- scene/object/bone sphere + capsule collider。
- 无链间自碰撞。
- 不改 GraphNode。
- 不改 Omni compiler。
- 不使用通用 runtime cache。

这版已经能覆盖 99% 骨架内部动骨效果，并且保留后续向 VRM10 SpringBoneJobs 扩展的路径。

## 15. MagicaCloth2 对未来粒子模拟的启示

补充参考路径：

- `D:\Unity_Fork\MagicaCloth2`
- `ResearchDocs~/01_file_structure.md`
- `ResearchDocs~/02_runtime_flow.md`
- `Runtime/Cloth/MagicaCloth.cs`
- `Runtime/Manager/Cloth/ClothManager.cs`
- `Runtime/Manager/Team/TeamManager.cs`
- `Runtime/Manager/Simulation/SimulationManager.cs`

MagicaCloth2 和 VRM SpringBone 的定位不同。SpringBone 更接近“少量链条 + 骨架输出”，MagicaCloth2 则是“批量粒子 + 约束 + manager 调度”。它对我们后续做粒子模拟的价值主要在底层结构，而不是节点表面形态。

MagicaCloth2 的关键结构：

- authoring component 只负责提供配置和生命周期入口。
- cloth / team / simulation manager 分层管理运行对象。
- 粒子位置、旧位置、速度、碰撞法线等运行数据放在连续 buffer 中。
- reset、prebuild、simulate、commit 等阶段有明确调度时机。
- team 是重要的运行边界，用于控制启停、重置、更新模式、自碰撞等状态。

对 OmniNode 的结论：

1. 动态骨第一版仍然应该保持“骨架一个主 solver + 每条链一个 setting node”的高封装设计。
2. 未来粒子模拟不要照搬动态骨的节点形态。
3. 粒子系统应该有独立的 manager / scheduler / buffer 层。
4. 粒子节点更适合输出 emitter、team、constraint、collision spec，而不是直接持有重运行状态。
5. 运行状态应该继续是 solver / manager 私有状态，不应暴露成公共 runtime cache。

未来粒子系统可以先预留这些内部概念：

- `Emitter`
- `Team`
- `ParticleState`
- `ConstraintState`
- `CollisionState`
- `Build`
- `Reset`
- `Simulate`
- `Commit`

长期拆分建议：

- spring bone：链式、骨架中心、参数少、输出 pose bone。
- particle cloth：批处理、buffer 中心、约束密集、调度显式。

因此 OmniNode 可以保持同一种高层 authoring 哲学，但执行模型要分开：

- function node 负责简单创建配置。
- solver node 负责暴露用户能理解的执行入口。
- 重型粒子模拟由底层 manager / buffer 系统负责。
