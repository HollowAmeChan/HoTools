# Physics World 通用 Bake 节点蓝图

更新日期：2026-07-20

本文定义 Physics World 通用 Bake 节点、关键帧记录、Mesh 缓存、跳帧清理、播放代理和文件生命周期的产品与实现合同。它服务 MC2、Rigid/Jolt、SpringBone 和未来 solver，不把 Bake 做成 MC2 私有功能。

公共 result/writeback 边界仍以 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 为权威；MC2 的 BasePose、final proxy 和 Bone 输出语义仍以 `MC2_BLUEPRINT.md` 为权威。本文只负责把这些结果稳定记录到 Blender Action 或外部几何缓存。

## 结论摘要

第一版按以下决策实施：

1. 新增独立的 `Physics Bake` 普通函数节点，固定接在 `Physics Writeback` 之后、`Physics World Commit` 之前。
2. Bake 与 Writeback 消费同一批当前帧公共结果；Bake 不重新扫描场景猜测物理参与者，也不读取 backend-private native handle。
3. Bone、Object delta 和未来 Object transform 写入专用 Bake Action，只处理结果流中真实出现的对象或骨骼，不扫描整个 Armature。
4. Mesh 第一版使用两个相邻的受管 Geometry Nodes modifier：共享实时后置位移 `Set Position` 在前，共享直通 `GeometryNodeBake` 缓存层在后。缓存层按对象启用/禁用，文件留存与播放状态完全分离。
5. 每个对象使用自己的 cache modifier bake entry 和独立目录。Blender 4.5 对普通 Bake 节点只提供单节点 operator，因此多对象要逐对象调度、逐对象确认提交，不能误用只处理 Simulation Zone 的批量 operator。
6. GN Bake 是 Blender 工程内部主缓存；PC2 保留为可选的可恢复/兼容工作后端；Alembic 仍由显式 `Finalize Physics Cache` 生成，承担多对象交付和交换。
7. GN 磁盘缓存为 Blender 私有 `.blob/.json` 数据，必须保存 `.blend` 后才能 Bake，不承诺跨 Blender 版本或第三方 DCC 读取。MDD 不实现，USD/USDC 保留实验后端，`PointCache/ptcache` 不接入。
8. Bake 不使用 Physics World 的 `restart_required` 或跳帧分类控制清理。清理由独立 `Clear Physics Bake` 节点在用户指定帧显式触发，默认第 1 帧，并可通过 mute/enable 关闭。
9. Bake 自己用 manifest 的 `last_recorded_frame` 判断“从后段回到控制帧”。到达控制帧时可以写/校正起始基线并请求暂停；任意跳到非控制帧不自动清动画。
10. 显式清理必须以精确 participant manifest 为依据。Bone 只清真实物理骨，Object 只清真实物理对象，Mesh 只处理本 Bake session 拥有的文件和修改器。
11. Bake 文件夹内必须有原子更新的 sidecar manifest。它是跨 world 重建、首帧回填、崩溃恢复、路径回填和精确清理的权威，不把 Bake session 状态藏进 module global。

## 目标与非目标

目标：

- 每帧记录公共 Bone transform 结果。
- 每帧记录 Object 增量变换；公共 Object transform channel 落地后记录完整 Object transform。
- 可选记录 topology-preserving Mesh 最终顶点位置，默认关闭。
- 一次 Bake 可覆盖多个 Armature、Object 和 Mesh。
- 支持同帧幂等、连续帧追加、当前帧覆盖、向前跳、向后跳、倒放、reset 和中断恢复。
- 自动维护 Mesh 缓存修改器路径，但不在 live simulation 期间产生反馈。
- 不误伤未参与物理的对象、骨骼、Action 曲线、文件或修改器。

非目标：

- 第一版不记录碰撞、统计、debug primitive、速度或 solver 私有状态。
- 第一版不支持拓扑变化 Mesh；MC2 当前本来就是 topology-preserving。
- 第一版不把多个 Mesh 写进同一个增量工作文件。
- 第一版不在 Bake Node 内直接持续写 Alembic。
- 第一版不替用户做最终 FBX/glTF/Unity 导出。
- 第一版不恢复旧 `骨骼姿态K帧` 节点的“输入一批 Bone 并读取现场姿态”语义。

## 当前代码事实与前置缺口

当前公共写回实际有三类：

| 当前来源 | 当前写回目标 | Bake 目标 |
|---|---|---|
| `rigid_transform` | `Object.delta_location` 与 delta rotation | Object Offset Action |
| `bone_transform` / `bone_transform_batch` | `PoseBone.matrix_basis` | Armature Bake Action |
| `gn_attribute` / `mesh_vertex_offset` | `hotools_physics_offset` + GN Set Position | GN Bake final geometry；可选 PC2 absolute local positions |

当前分支没有独立的公共 `object_transform` 写回 command。Rigid/Jolt 发布 solver-specific `rigid_transform`，统一写回再把它解释为 Object delta。通用 Bake 落地前应先把 Object 写回规范化成公共 command：

```text
object_delta_transform
object_transform
```

两者都必须声明：

- target object identity；
- frame / generation / writer identity；
- value space；
- 真实拥有的 transform components；
- reset/clear policy；
- 可用于 Bake 的稳定 target id。

不能让 Bake 永久依赖 `rigid.results` 的私有字段，否则未来其他 solver 输出 Object transform 时会再造一条路径。

旧 `keyframePoseBones` 可以继续作为非 Physics World 工具。新节点复用它已经验证过的 PoseBone location、三种 rotation mode 和 scale 插帧机制，但不能复用它的目标发现语义：Bake 必须从当前 frame/generation 的 Physics World result 精确取得真实物理骨，不能对用户传入的整个骨架笼统 K 帧。

## 节点表面

### 已落地 Bone + Mesh 阶段

当前代码已注册以下真实 OmniNode：

```python
def physicsBake(
    world: object,
    cache_directory: str = "//physics_bake",
    file_prefix: str = "PhysicsBake",
    frame_start: int = 1,
    frame_end: int = 250,
    bake_bones: bool = True,
    bake_mesh: bool = False,
    use_mesh_cache: bool = False,
    enabled: bool = True,
) -> tuple[object, int, int, str]:
    ...
```

`bake_bones` 在连续帧从当前 frame/generation 的 `bone_transform` 和 batch result 精确解析 Armature/PoseBone。每个 Armature 首次复制已有 Action 或创建新 Action，打上 session ownership 标记并绑定；后续帧复用同一 Action。未出现在 result 中的骨骼不会新增物理曲线。

`bake_mesh` 是边沿触发：False 重新武装，True 只排队一次。节点从当前 frame/generation 的 GN result stream 精确解析 Mesh target，timer 在本轮树执行返回后逐对象调用 `geometry_node_bake_single`。多 Mesh 时仅第一遍完整时间轴允许记录 Action，后续遍只写当前 Mesh cache。原子 manifest 状态依次为 `BAKING -> COMPLETE/PARTIAL/FAILED`；只有 `COMPLETE` 才允许 `use_mesh_cache=True`。

当前 Bone 后端为兼容旧节点的第一条生产竖切，仍统一 K location、当前 rotation mode 与 scale。result 尚未携带 component ownership，因此 component-aware keying 仍是未完成项。独立 Clear 节点与 Bone boundary baseline 已落地；Object Action 和 Bake 自有回绕暂停仍未提供 socket。

### 完整目标表面

后续完整节点目标：

```python
def physicsBake(
    world: object,
    cache_directory: str,
    file_prefix: str = "PhysicsBake",
    boundary_frame: int = 1,
    stop_on_return: bool = True,
    bake_bones: bool = True,
    bake_mesh: bool = False,
    use_mesh_cache: bool = False,
    bake_object_offset: bool = True,
    bake_object_transform: bool = True,
    enabled: bool = True,
) -> tuple[object, int, int, str]:
    ...
```

完整目标 UI 名称：

| 参数 | UI | 默认值 | 语义 |
|---|---|---:|---|
| `world` | 物理世界 | 必填 | 当前帧统一 world owner |
| `cache_directory` | 缓存文件夹 | 必填 | manifest、每对象 GN cache 子目录、可选 PC2 和最终 ABC 的根目录；支持 `//` |
| `file_prefix` | 统一文件前缀 | `PhysicsBake` | 多对象文件、Action 和 manifest 的统一命名根 |
| `boundary_frame` | 烘焙边界帧 | `1` | 首帧基线、回绕检测和自动暂停使用的帧；不硬编码第 0 帧 |
| `stop_on_return` | 回到边界帧时暂停 | `True` | manifest 已有更高已提交帧后再次到达边界帧时，请求停止时间轴 |
| `bake_bones` | Bake Bone | `True` | 记录 Bone result target |
| `bake_mesh` | Bake Mesh | `False` | 通过后置位移 GN Bake 记录 final geometry；后端可切换为 PC2 fallback |
| `use_mesh_cache` | Use Mesh Cache | `False` | 每对象启用缓存 modifier；False 显示 live，但不删除或修改缓存 |
| `bake_object_offset` | Bake Object Offset | `True` | 记录 delta transform |
| `bake_object_transform` | Bake Object Transform | `True` | 记录公共 full transform command；当前无此结果时为零写入 |
| `enabled` | 启用 | `True` | False 时只透传 world，不写 Action 或文件 |

输出：

| 输出 | 内容 |
|---|---|
| 物理世界 | 原样透传，继续连接 Commit |
| 关键帧数量 | 本次实际插入或覆盖的目标 component 数量 |
| Mesh 样本数量 | 本次成功提交的 Mesh sample 数量 |
| 状态 | 简洁状态或错误文本；详细信息进入 world debug snapshot |

`bake_object_transform` 先进入节点合同，避免以后增加 socket 破坏已保存节点树；在公共 full transform command 落地前，它只是没有消费者，不允许退回读取任意 `Object.matrix_world`。

配套清理节点：

```python
def clearPhysicsBake(
    world: object,
    cache_directory: str,
    file_prefix: str = "PhysicsBake",
    clear_frame: int = 1,
    animation_clear_mode: int = 2,
    mesh_cache_policy: int = 0,
    finalize_cache_policy: int = 0,
    clear_live_output: bool = True,
    pause_timeline: bool = True,
    enabled: bool = True,
) -> tuple[object, int, int, str]:
    ...
```

UI 名称固定为 `Clear Physics Bake` / `清除物理Bake动画`。它是普通函数节点，用户可以直接 mute，也可以用 `enabled` socket 控制。它只在：

```text
enabled == True and scene.frame_current == clear_frame
```

时执行，不读取 `world.frame_context.restart_required`，不判断倒放，不判断是否跳到其他非零帧。重复执行必须幂等。

清理策略使用普通整数 socket，而不是为这一组局部选项增加专用 socket 类型，也不把“清动画”与“删昂贵缓存”绑成一个 bool。节点说明和各 socket description 必须同步显示编号语义：

| 输入 | 选项 | 默认值 | 语义 |
|---|---|---|---|
| `animation_clear_mode` | `0` 当前帧 / `1` 当前帧及之后 / `2` 整个 Session | `2` | 只清本 session 的 Bone/Object Bake 曲线；不碰源 Action |
| `mesh_cache_policy` | `0` 保留 / `1` 标记失效 / `2` 删除 Session | `0` | GN/PC2 工作缓存默认保留；PC2 可截断，GN 只能标 stale 后整段重烘 |
| `finalize_cache_policy` | `0` 保留 / `1` 标记失效 / `2` 删除 Session | `0` | 最终 ABC 默认保留；是否标 stale 或删除由用户决定 |
| `clear_live_output` | bool | `True` | 清 manifest participant 的当前 Bone/Object/GN 写回值，不删除动画/文件 |
| `pause_timeline` | bool | `True` | 清理事务完成后请求暂停 |

当前实现已经注册真实节点和三个 `0..2` 整数策略。Bone 支持三种 Action 清理范围、重新绑定源 Action、精确 live participant 清零、无关键帧 boundary baseline，以及首次 `clear_frame + 1` 自动回填。GN 支持保留、只标 stale 和调用 Blender single-delete 删除整个受管 entry；保留模式不改缓存文件。上游 Bake 在同一次树执行中刚排队的 Mesh request 会由 Clear 取消，避免清理后立即重烘。finalize 策略只处理 manifest 已声明的最终文件；在 ABC producer 落地前通常为零目标。

硬规则：

- `KEEP` 必须真的不改文件、不截断文件、不把 modifier 路径清空。
- `DELETE_SESSION` 只删除 manifest 明确拥有且 canonical path 位于 cache directory 内的文件。
- animation、GN/PC2 工作缓存、finalized cache 三类留存权彼此独立，不能因为用户清了一类就顺手清其他类。
- GN Bake 的公开删除粒度是整个 entry。`INVALIDATE_FROM_CLEAR_FRAME` 只在 manifest 标记该帧后的 GN cache stale，不改私有 `.blob/.json`；下次确认重烘时才调用 single delete 并重建整段。
- 自动回到 boundary frame 只负责记录/暂停，永远不隐式执行上述清理策略。

## 固定执行顺序

用户图固定为：

```text
Physics World Begin
  -> solver(s)
  -> Physics Writeback
  -> Physics Bake
  -> Clear Physics Bake       # 可选，通常只在重置烘焙时启用
  -> Physics World Commit
  -> Cache Write
```

理由：

- solver 只发布 result，不直接写 Blender。
- Writeback 负责把公共 command 精确应用到 RNA target。
- Bake 记录 Writeback 已确认应用的相同 target/value。
- Clear Physics Bake 只在指定帧按用户选择处理该 session 拥有的动画、GN/PC2 工作缓存、finalized cache 和 live output。
- Commit 最后提交 world owner，保持现有 runtime cache 事务边界。

Bake 不允许通过“当前 PoseBone 看起来发生变化”推断结果。Writeback 应生成当前帧 `WritebackReceiptV1`，Bake 只消费 receipt 与公共 mesh sample provider。

建议 receipt：

```python
{
    "schema": "physics_writeback_receipt_v1",
    "frame": 120,
    "generation": 8,
    "result_revision": 17,
    "recordable": True,
    "writeback_reason": "solver_result",
    "targets": (
        {
            "writeback_type": "bone_transform",
            "target_id": "...",
            "owner_ptr": 123,
            "bone_name": "Hair_03",
            "components": ("rotation_quaternion",),
        },
        ...
    ),
}
```

receipt 是当前帧 scratch，不跨帧保存，不替代 result stream。它回答“本帧哪些公共结果已经真实应用到哪些 Blender 属性”，从而防止 Bake 和 Writeback 对 target resolver、rotation mode、connected bone translation 等规则各写一份。

Writeback 的生命周期清零必须发布 `recordable=False, writeback_reason="lifecycle_clear"`。Bake 默认不把这种清零动作 K 成动画；Clear 节点可以消费它解析精确 live target。只有 solver 的正式可记录结果或 boundary baseline 才能进入 Action/Mesh cache。

若节点顺序错误、receipt 缺失或 receipt 的 frame/generation 与 world 不一致，Bake 必须明确报错并保持文件/Action 不变，不能退化为读取现场状态。

## 首帧、回绕与时间轴控制

OmniNode 当前注册在 Blender `frame_change_post`。因此场景已经停在第 1 帧时直接按播放，第一次自动执行通常发生在第 2 帧。这是框架时序事实，Bake 必须显式处理，不能要求用户接受“烘焙永远从第 2 帧开始”。

Bake 控制只使用以下 session 数据：

```text
current_frame
boundary_frame
manifest.last_recorded_frame
manifest.boundary_baseline_revision
```

不使用 Physics World 的 jump/reverse/restart 分类。

规则：

- `same_frame=True`：普通 Bake sample 幂等；Clear 节点仍可按显式 enable + frame 条件幂等执行。
- 第一次有效结果发生在 `boundary_frame + 1` 且边界帧尚未提交：Bake 先用清理节点捕获的 boundary baseline 回填边界帧，再写当前帧。
- 当前帧等于 boundary frame，且 manifest 没有更高已提交帧：这是初始化/手动运行，不自动暂停。
- 当前帧等于 boundary frame，且 `last_recorded_frame > boundary_frame`：这是 Bake session 自己定义的“返回边界”，写入或校正边界基线后请求暂停；不关心它在 Physics World 中被归类为倒放还是跳帧。
- 跳到任意非 boundary frame：不自动清 Action，不自动删 PC2，不自动暂停；只按文件连续性规则决定当前样本能否覆盖/追加。

`returning_to_boundary` 必须用本帧写入前的 manifest 计算。固定顺序是：读取旧 `last_recorded_frame` -> 判定返回边界 -> 写/校正 boundary baseline -> 提交本帧事务 -> 发暂停请求。不能先把 `last_recorded_frame` 更新成 boundary frame 再判断。

### Boundary baseline

Clear 节点在指定帧按以下顺序建立干净基线：

1. 从 manifest 与当前 writeback receipt 的并集解析精确 participant。
2. 按 `animation_clear_mode` 处理本 Bake session 拥有的关键帧。
3. 按 `mesh_cache_policy` 和 `finalize_cache_policy` 分别处理文件；默认 `KEEP` 不改文件。
4. `clear_live_output=True` 时清除这些 target 的 live Bone/Object/GN physics output。
5. 让 Blender 更新到没有物理残留的基础动画姿态。
6. 保存 Bone/Object boundary transform snapshot；Mesh 基线保存为独立二进制 sidecar，不把大数组写进 JSON。
7. 更新 `boundary_baseline_revision`，然后按需请求暂停。

baseline snapshot 不是关键帧，也不是正式 PC2 sample，因此用户执行清理后场景中不会残留一个恶心的“清零 K 帧”。用户 mute Clear 节点并开始播放后，Bake 在首次第 2 帧执行时才把该 snapshot 转成正式第 1 帧关键帧/PC2 sample。

如果缺少有效 boundary baseline，Bake 不允许拿第 2 帧结果冒充第 1 帧。它应报错并要求用户在 boundary frame 启用一次 Clear 节点或手动运行一次 Bake 初始化。

### 暂停时间轴

函数节点不能在 `frame_change_post` 执行栈内直接调用 `bpy.ops.screen.animation_cancel`。Bake/Clear 只发布一次 `TimelineStopRequest`；OmniNode 帧处理器在整棵树成功执行完后，通过 `bpy.app.timers.register(..., first_interval=0.0)` 延迟到下一 UI tick，再对实际处于播放状态的 window/screen 使用 context override 停止时间轴。

这样可以保证：

- Bake、Clear、Commit 和 Cache Write 已经全部完成；
- 不在 frame handler 内重入 screen operator；
- 多窗口时只停止真正播放的 screen；
- background/render 模式没有可播放 screen 时安全 no-op。

### 用户工作流

推荐操作固定为：

1. 开启 OmniNode 每帧运行，把场景调到 `clear_frame`，默认第 1 帧。
2. 保持 Clear 节点启用并手动编译/运行一次。节点按用户策略清动画或保留/处理缓存，清 live physics output，捕获 boundary baseline，然后暂停。
3. mute Clear 节点，保持 Bake 节点启用，从第 1 帧开始播放。
4. 第一次自动回调发生在第 2 帧时，Bake 先从 baseline 回填第 1 帧，再写第 2 帧；之后连续记录。
5. 时间轴从高帧回到第 1 帧时，Bake 用写入前 manifest 识别返回边界，写/校正第 1 帧并在事务完成后暂停。Clear 已 mute，因此 Action、GN/PC2 和 ABC 都不会被自动删除。
6. 重新烘焙时 unmute Clear，按需要选择动画/PC2/ABC 留存策略，在第 1 帧运行一次；再 mute Clear 并播放。

这个流程把“是否留存缓存”明确交给用户，同时消除第 0/1 帧生命周期清零被误 K 成残余动画的问题。

## 精确 participant 身份

“不能误伤没有物理的骨”是硬约束，不是测试阶段再补的优化。

每个 Bake target 必须有跨 world 重建稳定的 identity：

```text
Object:
  scene/library identity + persistent object bake UUID

Bone:
  armature object UUID + armature data UUID + bone bake UUID

Mesh sample:
  source object UUID + mesh data UUID + topology signature + writer id
```

运行时 pointer 只用于快速 resolver，不能写成 manifest 的唯一身份。第一次 Bake 可在真实 target 上生成 HoTools 私有 UUID custom property；已有 UUID 必须复用。复制对象或骨架导致 UUID 冲突时，scope/build 阶段必须检测并重新分配副本身份。

manifest 记录本 session 曾经真正提交过的 target。跳帧后即使 world 被 `PhysicsWorldBegin` 替换、当前 reset 帧没有 ready result，也能从 manifest 找到需要清理的精确对象与骨骼，禁止退回“遍历整个 armature.pose.bones”。

## Bone 关键帧后端

### Action 所有权

第一版固定使用专用 Bake Action：

```text
{prefix}_{armature_object}_PhysicsBake
```

创建 session 时：

1. Armature 有 active Action 时复制该 Action，保留所有非物理动画曲线。
2. 没有 active Action 时创建空 Action。
3. 把复制/新建 Action 绑定到该 Armature object。
4. manifest 记录 source action、bake action 和 owner UUID。
5. 后续帧只复用同一个 Bake Action，不能每帧复制。

这比直接修改源 Action 安全，也比只创建物理曲线的空 Action 更容易保持未参与物理骨的原动画。第一版不自动改 NLA 堆栈；需要 NLA 叠加的资产由后续专用产品决策处理。

### 记录 component

Bone command 应声明 `owned_components`。Bake 只记录 solver/writeback 真正拥有的分量：

- rotation-only：只记录当前 rotation mode 对应的 rotation property；
- position + rotation：增加 location；
- scale：只有公共 command 明确拥有 scale 时才记录，不能因为矩阵可分解就默认 K scale。

MC2 connected bone 的 `rotation_only_connected` 不应产生 location 曲线；disconnected bone 的 `position_rotation` 必须保留非零 location。SpringBone 若只拥有旋转，也不能生成 location/scale 曲线。

rotation property 按 PoseBone 当前 mode 记录：

```text
QUATERNION -> rotation_quaternion
AXIS_ANGLE -> rotation_axis_angle
other      -> rotation_euler
```

必须处理 quaternion sign continuity，避免相邻帧 `q` 与 `-q` 造成无意义曲线翻转。Euler 模式使用兼容上一帧的分解结果，避免 2π 跳变。

### 精确清理

clear 只能操作 manifest 登记过的：

- armature Bake Action；
- 精确 PoseBone data path；
- 精确 owned component；
- 当前 session 拥有的帧区间。

Blender 4.5 Action 已有 layered action/slot 语义。实现必须通过 owner 对应 slot/channelbag 找到 FCurve，不能假设所有曲线永远只在 legacy `Action.fcurves` 平面集合。该部分必须有 Blender 4.5 background 测试。

## Object 关键帧后端

每个 Object 使用专用 Action：

```text
{prefix}_{object}_PhysicsBake
```

Object Offset：

- key `delta_location`；
- 根据 rotation mode key `delta_rotation_quaternion` 或 `delta_rotation_euler`；
- 不 key delta scale，除非公共 command 未来明确拥有它。

Object Transform：

- 只消费公共 `object_transform` command；
- world-space result 必须先由公共 writeback helper 按 parent、parent inverse 和 rotation mode 转成真实本地 RNA value；
- Bake 记录 receipt 中已应用的 location/rotation/scale component；
- 不直接 K `matrix_world`。

Object delta 和 full transform 可同时存在，但同一 target/component 同帧只能有一个 writer。冲突必须在公共 result transaction 阶段拒绝，不能由 Bake 按节点顺序决定赢家。

## Mesh 要记录什么

`gn_attribute` 中的 `local_offsets` 不能直接写进 PC2。PC2/MDD/Mesh Sequence Cache 播放的是顶点位置，不知道 HoTools 的 offset 属性语义。

最终 sample 必须是：

```text
final_object_local_positions = animated_base_object_local_positions + final_local_offsets
```

MC2 的 animated base 来自 BasePose evaluated mesh，不能用 source 原始 `Mesh.vertices` 替代，否则 Armature、Shape Key 等 topology-preserving 基础动画会丢失。

通用 result 不应为了 Bake 永久多复制一份 `float32[N,3]` base positions。推荐增加按需 provider registry：

```python
@register_mesh_bake_sample_provider("mc2.mesh_cloth_v1")
def build_mc2_mesh_bake_sample(world, result) -> MeshBakeSampleV1:
    ...
```

Mesh result envelope 增加小型 descriptor：

```python
{
    "mesh_bake_provider": "mc2.mesh_cloth_v1",
    "mesh_bake_token": "stable task/frame token",
}
```

provider 可以访问自己 domain 的公开 adapter/slot 数据，但必须返回通用只读 DTO：

```python
MeshBakeSampleV1(
    target_id: str,
    frame: int,
    generation: int,
    vertex_count: int,
    topology_signature: str,
    object_local_positions: np.ndarray,  # float32[N,3], readonly
)
```

Bake 核心只消费 DTO，不 import MC2 private module。没有 provider、identity 不匹配、topology 变化、buffer 非有限或顶点数变化时，该 Mesh sample 明确失败；不能改为求值 source object 猜一个结果。

### MC2 provider 的计算

MC2 已持有：

- `animated_base_world_positions`；
- source world linear transform；
- component world position；
- public final object-local offsets；
- topology signature。

provider 用同一帧 snapshot 把 base world positions 还原到 source object local，再加 final offsets。它不得重新求值带物理 GN output 的 source object，否则会把本帧物理位移重复叠加。

## Mesh 格式评估

| 格式 | Blender 播放 | 增量逐帧写 | 精确覆盖单帧 | 多对象单文件 | 压缩/体积 | 依赖 | 决策 |
|---|---|---|---|---|---|---|---|
| PC2 | Mesh Cache modifier | 很适合 | 固定偏移，可直接覆盖 | 否 | 无压缩，约 `12*N*F` bytes | 无 | 可选恢复/兼容后端 |
| MDD | Mesh Cache modifier | 可行 | 可计算偏移 | 否 | 无压缩，另有 time table | 无 | 不实现，收益低于 PC2 |
| Alembic Ogawa | Mesh Sequence Cache | 不适合节点逐帧直写 | 通常需重写 archive | 是 | 面向几何缓存，通常更适合交付 | Blender exporter 或 C++ Alembic | Finalize 格式 |
| USDC | Mesh Sequence Cache | PXR 可写 time samples | 语义上可 Clear/Set | 是 | crate 较紧凑，实际资产需 benchmark | Blender bundled `pxr` | 实验后端 |
| GN Bake | NodesModifier | operator 控制整段求值 | Blender 单节点删除/重烘 | 每 modifier | Blender 私有 `.blob/.json` | Blender operator/context | 第一版内部主缓存 |
| PointCache | 对应内置 simulator | 无通用 writer | 无 | 否 | 内置压缩 | 私有 simulator integration | 不可用 |

### PC2 为什么仍作为可选后端

MC2 MeshCloth 已保证顶点数量和顺序稳定，正好满足 PC2 的核心前提。虽然第一版内部播放改用 GN Bake，PC2 writer 仍有独立价值：

- 只依赖 `struct`、`os` 和已有 numpy；
- 每帧常量内存写一个连续 `float32[N,3]` sample；
- 通过固定 header 和 sample stride 精确 seek；
- 在向后跳时截断逻辑尾部；
- 每个对象独立失败和恢复；
- 直接由 Blender `MESH_CACHE` modifier 播放。

主要代价是文件大。估算：

```text
100,000 vertices * 1,000 frames * 3 * 4 bytes = 1.2 GB / object
```

因此 PC2 是明确可读、可随机覆盖的 fallback，不应伪装成理想归档。GN Bake 无法满足恢复、格式审计或版本兼容要求时可以切换到 PC2；需要交付或长期保存时仍转 Alembic。

### 为什么不选 MDD

MDD 同样依赖稳定 vertex order，也基本是未压缩 positions。它支持独立 time table，但当前 Bake 以 Blender 整帧采样，PC2 的 start frame + sample rate 已足够。维护两个几乎同能力 writer 只会扩大跳帧、端序和测试矩阵。

### 为什么 Alembic 只做 Finalize

Blender 4.5 内置 Alembic exporter 能按 start/end 导出最终 evaluated mesh，且一个 archive 可容纳多个对象。它适合在 PC2 已完整、Mesh Cache playback 已启用后做整段转换。

但 Alembic archive 不适合节点每帧随机追加/覆盖；Python 环境也没有通用 `alembic` module。直接绑定 Alembic C++ 会新增较大的构建、ABI、授权和分发面。第一版没有必要承担这些成本。

Finalize 应是显式 operator，而不是 Bake Node 在最后一帧隐式启动长任务。operator 只导出本 manifest 的 playback targets，完成后校验 archive 路径和帧范围，不改变 GN/PC2 工作缓存，除非用户另行选择清理。

### USD/USDC 的结论

本机 Blender 4.5.0 已验证：

- bundled Python 含 `pxr`；
- `UsdGeom.Mesh.points` 可写 time sample；
- 已有 sample 可 `ClearAtTime` 后覆盖；
- Blender `CacheFile + Mesh Sequence Cache` 能读取该 USDC 并在不同帧得到正确 positions。

它是可信的后续候选，但首版不选它，原因是：

- PXR Stage 长时间持有大量 time samples 的内存与保存成本尚未在代表资产上测量；
- `BlendData.cache_files` 没有直接 `new/load` API，本机需要 `bpy.ops.cachefile.open` 创建 datablock；
- 插件需要承担 PXR 版本差异和 stage 生命周期；
- PC2 的流式常量内存和固定 offset 更容易先把跳帧/恢复合同做正确。

只有在大资产 benchmark 证明 USDC 的每帧 Set/Save、随机改写、文件膨胀、reload 和 viewport 性能满足门槛后，才可把它升级为可选工作后端。

## PC2 文件合同

每个 Mesh 一个文件：

```text
{directory}/{prefix}_{safe_object_name}_{target_id_short}.pc2
```

统一 manifest：

```text
{directory}/{prefix}.hotools-bake.json
```

临时与 journal：

```text
{prefix}.hotools-bake.json.tmp
{prefix}.frame-{frame}.journal
```

文件命名不能只用 object name；重名、重命名和 library object 都必须靠 target UUID 消歧。

PC2 只记录 object-local absolute positions。坐标不做 Blender/Unity 换轴，不乘 object transform，不记录 normals、UV、attribute 或 topology。

header/session 必须固定：

- vertex count；
- start frame；
- sample rate；
- topology signature；
- target UUID；
- scene FPS 与 `fps_base`；
- position space；
- writer schema/version。

PC2 自身不能保存全部这些 HoTools 元数据，因此 manifest 是必需文件，不是可选 debug 输出。

## 任意跳帧、覆盖与用户留存权

Bake 不因 Physics World 报告 jump/reverse/reset 自动删除任何动画或文件。任意跳到非 boundary frame 时只处理当前写入请求：

- 当前帧已有 key/sample：精确覆盖本 session 的当前帧数据；
- 当前帧是连续尾部下一帧：追加；
- 向后跳到已有 PC2 范围：允许从当前帧开始逐帧覆盖，尚未重烘的后续 sample 保留但在 manifest 标记为 dirty；
- 向前跳导致 PC2 出现未定义 gap：拒绝 Mesh 写入，提示回到连续帧；不使用零值、上一帧或 reset 结果填洞；
- Bone/Object Action 可以形成稀疏 key，但只更新实际当前帧，不自动删区间；
- topology、vertex count、FPS、space 或 target identity 变化时停止写该 target，等待用户在 Clear 节点明确选择 cache policy。

用户在 Clear 节点显式选择：

```text
animation_clear_mode:
  TRIGGER_FRAME_ONLY      只抹掉控制帧上的残余/起始 key
  FROM_CLEAR_FRAME        清当前帧及之后的本 session key
  SESSION_ALL             清本 session 的全部 Bone/Object Bake key

mesh_cache_policy:
  KEEP                    GN/PC2 文件完全保留，只更新 manifest 状态
  INVALIDATE_FROM_CLEAR_FRAME
                          PC2 保留连续前缀并截断；GN 只标 stale，文件保持不变
  DELETE_SESSION          用 single delete 删除本 session 的 GN entry；
                          或删除 manifest 精确拥有的 PC2 文件

finalize_cache_policy:
  KEEP                    ABC 完全保留
  MARK_STALE              文件保留，但 manifest 标记不再对应当前工作缓存
  DELETE_SESSION          删除本 session 拥有的最终文件
```

这里的“清空”只清本 Bake session 拥有的数据。不能调用：

```text
clear all PoseBone transforms
clear all Armature keyframes
delete all GN/.pc2/.abc files in directory
reset all objects in Physics Object Scope
```

显式 reset、timeline jump、Bake clear 三者完全分开。Physics World 可以按自己的规则重建和清 live output；Bake 是否保留历史只由 Clear 节点的显式用户输入决定。

## Manifest 与帧事务

manifest 建议 schema：

```json
{
  "schema": "hotools_physics_bake_v1",
  "session_id": "uuid",
  "prefix": "Shot010_Physics",
  "blend_file": "absolute-or-empty",
  "scene": "Scene",
  "fps": 24.0,
  "frame_start": 1,
  "frame_end": 250,
  "boundary_frame": 1,
  "boundary_baseline_revision": 3,
  "last_common_committed_frame": 120,
  "dirty_ranges": [],
  "targets": {},
  "actions": {},
  "finalize": {"alembic": null, "stale": true}
}
```

每帧多 target 写入不是文件系统原子事务，使用 journal：

1. 验证全部 keyframe targets 和 Mesh samples，先不写。
2. 写 `{frame}.journal`，状态为 `PREPARED`，列出本帧全部预期 target。
3. 写 Action keys 和 PC2 samples。
4. 把 manifest 更新到新 committed frame，先写 `.tmp`，flush 后 `os.replace`。
5. 删除 journal。

启动或下一帧发现残留 journal 时：

- 该帧视为未提交；
- 移除本 session 在该帧已插入的 keys；
- PC2 回退到所有 target 的最后共同 committed 边界；
- 不信任“某个对象文件已经多一帧”这种部分成功状态。

manifest 不保存大顶点数组，只保存身份、路径、范围、签名、状态和校验信息。

## 修改器与代理对象扩展

扩展 MC2 BasePose lifecycle，但不要改变 BasePose 的只读职责。建议新增共享 helper，而不是把 writer 塞进 `base_pose.py` 的 evaluated snapshot 逻辑：

```text
mesh_cloth/base_pose.py       BasePose read proxy，仅负责基础动画读取
physicsWorld/bake/mesh.py     通用 Mesh bake sample/PC2 writer
physicsWorld/bake/playback.py 缓存修改器与 live/baked 模式切换
```

对 source/write object 确保两个相邻且固定名字的共享 GN modifier：

```text
HoTools 物理后置位移
  Group Input -> Named Attribute -> Set Position -> Group Output

HoTools 物理网格缓存
  Group Input -> HoTools Physics Bake -> Group Output
```

配置 Bake session 时检查并修正：

- 两个 modifier 都是 `NODES`；live offset 位于 topology-preserving base stack 之后，cache modifier 紧跟其后；
- 两个 node group 分别校验 owner/schema，cache group 只允许 Geometry 直通 Bake；
- 每对象 bake entry 使用 custom frame range、`ANIMATION`、`DISK` 和独立目录；
- manifest 记录 object UUID、modifier name 和目录；`session_uid/bake_id` 只在调用 operator 前即时解析；
- `use_mesh_cache=False` 同时关闭 cache modifier 的 viewport/render，但保留全部文件与 entry；
- `use_mesh_cache=True` 启用 cache modifier，Bake 输出隔离上游 live 变化；
- 删除 entry 后关闭 cache modifier，恢复前一层 live `Set Position` 输出。

这使 live simulation 和 cache playback 通过对象自己的 modifier 显隐互斥，避免：

```text
Baked final geometry -> GN physics offset again
```

PC2 fallback 才创建独立且带 session tag 的 Mesh Cache modifier；切回 live 时恢复 manifest 记录的修改器状态，绝不删除用户自己的其他 Mesh Cache modifier。

路径优先保存 Blender 相对路径 `//`；真正写文件前统一 `bpy.path.abspath`，manifest 同时记录 display path 和 canonical absolute path。未保存 `.blend` 使用相对路径时必须明确报错或要求绝对文件夹。

## Blender 内置磁盘缓存结论

### PointCache/ptcache

Blender 4.5 RNA 暴露：

- `PointCache.filepath`；
- `use_disk_cache` / `use_external`；
- frame range / step；
- `NO/LIGHT/HEAVY` compression；
- baked/baking/outdated 状态。

`bpy.ops.ptcache.bake` 也可以由插件调用。但这些入口驱动的是已注册的 Cloth、Soft Body、Particle 等内置 simulator cache owner，没有公开 API 接受任意 `float32[N,3]` 并写入一个通用 PointCache。MC2 不是 Blender 内置 point-cache simulator，因此不能靠填 filepath 后调用 operator 获得可用缓存。

结论：不接 ptcache，不依赖 Blender 私有 C API 注入。除非未来愿意维护 Blender patch 或正式上游扩展，否则这条路不应进入插件生产方案。

### Geometry Nodes Bake

Blender 4.5 `NodesModifier` 暴露 `bake_directory`、`bake_target` 和 bake collection；`bpy.ops.object.geometry_node_bake_single(session_uid, modifier_name, bake_id)` 可调用。

2026-07-20 的 Blender 4.5 background spike 已验证：

1. 生产链路采用两个相邻 modifier：`Physics Offset(Set Position)` 后接 `Physics Mesh Cache(GeometryNodeBake)`。缓存 modifier 启用时直接输出 final Geometry，修改 live offset 不再改变结果；禁用时 Blender 跳过缓存层并显示实时后置位移。
2. `geometry_node_bake_single` 会从自定义 `frame_start` 精确驱动到 `frame_end`，触发 `frame_change_post`，并在结束后恢复调用前帧。`1..3` 测试收到的 distinct frame events 精确为 `[1, 2, 3]`，所以显式 Mesh Bake 不存在“永远从第 2 帧才写”的问题。
3. 磁盘结果按帧生成 `.blob + .json`；保存并重新打开 `.blend` 后仍能回放。调用 `geometry_node_bake_delete_single` 会删除该 entry 拥有的数据并恢复 live 链路。
4. 两个对象可以共享同一个 cache node group，但 `bake_id` 只作当前 modifier entry 的运行时句柄，可能在 node group 增加用户时重新生成。operator 调用前必须即时解析；ownership 由稳定 target id、object `session_uid`、modifier entry 和独立目录共同确定。逐对象删除 A 不影响 B。
5. `bpy.ops.object.simulation_nodes_cache_bake(selected=True)` 只负责 Simulation Zone，实测不会 Bake 普通 `GeometryNodeBake`。Blender 4.5 没有普通 Bake 节点的公开 multi-object operator，因此 N 个 Mesh target 需要 N 次 `geometry_node_bake_single`，也就是 N 次帧范围求值。

据此，GN Bake 升级为 Blender 内部主路径，但有以下硬边界：

- `.blend` 必须先保存；未保存文件需先提示用户保存，不能静默切换临时路径。
- 每对象目录必须由 `{prefix}/{target_uuid}` 生成，不能让多个 entry 共用一个目录。
- Bake、Delete、Pack、Unpack 都必须按精确 `session_uid/modifier_name/bake_id` 调用并记录 manifest；不能把目录级删除当作正常清理方式。
- manifest 不得把 `bake_id` 当作跨结构变化的稳定身份；每次 operator 前从当前 cache modifier 重新解析。
- `Use Mesh Cache` 只切换 cache modifier 的 `show_viewport/show_render`，不 mute 共享 Bake node，不改目录、不删除文件。
- Blender 4.5 RNA 没有公开 `NodesModifierBake.is_baked`。产品节点启用缓存前必须用 manifest 完整状态、entry ownership 和目录文件校验；底层显隐 helper 不得冒充完成状态。
- GN 私有磁盘格式不能作为交换合同，也不能承诺跨 Blender 版本；交付仍显式导出 Alembic。
- 多对象重复时间轴求值可能成为主成本，必须用代表资产 benchmark。若成本不可接受，PC2 单次 live 播放采样仍是 fallback。
- schema 2 的组合 `Set Position -> Bake` 迁移时，原 modifier 和 Bake node 原位保留为 cache 层并改名，在它前面新建 live offset 层；不得替换 Bake node 或丢失 entry。

### GN Bake 调度合同

`Physics Bake` 函数节点运行在 `frame_change_post` 调用链中，不能在节点函数内部直接调用 `geometry_node_bake_single`，否则会递归推进时间轴和重入同一棵 OmniNode 树。节点只发布一次 `GeometryBakeRequest`；树执行成功返回后，由 UI operator 或 `bpy.app.timers` 启动 coordinator。

coordinator 状态至少包含：

```text
session_id
target_queue
active_target_id
phase = PREPARE / BAKING / FINALIZE / FAILED / CANCELLED
record_actions = True only for the first full timeline pass
suppress_clear_node = True while operator owns the timeline
```

固定流程：

1. `PREPARE` 校验 `.blend` 已保存、全部 target/目录/entry/manifest 合法，并要求 Clear 的一次性用户策略已经完成。
2. 按稳定 target id 排序，对每个 Mesh 调一次 `geometry_node_bake_single`。operator 自己驱动完整帧范围；节点检测到 coordinator active 后只执行 solver、writeback 和记录，不再发布嵌套 request。
3. 第一遍可以同时写 Bone/Object Action；后续 Mesh 遍只覆盖当前 active Mesh cache，禁止重复清 Action，也不再次执行 Clear。是否允许幂等覆盖 Action 留作 debug 开关，不作为生产默认。
4. 每个 entry 成功后立即校验磁盘文件和 Blender bake 状态，再原子更新 manifest。某对象失败时停止队列，已经成功的对象保留为 `PARTIAL`，不谎报整 session 完成，也不自动删除用户缓存。
5. 最后一项成功后恢复原场景帧、选择和 active object，标记 `COMPLETE`；取消则标记 `CANCELLED` 并保留已完成 entry，由用户决定删除或继续。

这里的显式 GN Mesh Bake 与“用户自己播放时间轴逐帧记录 Action/PC2”是两种执行模式。前者由 operator 从第 1 帧开始，因此不需要 frame2 回填；后者仍遵守本文的 boundary baseline/回绕合同。

## 依赖规划

第一版运行依赖：

- Python 标准库：`os`、`struct`、`json`、`uuid`、`pathlib`、`tempfile`；
- 项目已有 numpy；
- Blender RNA、`GeometryNodeBake`、`NodesModifier.bakes` 和相关单节点 operators。

不新增 pip wheel，不新增 native ABI，不复制 Alembic/OpenUSD 动态库。

Alembic finalize 使用 Blender 内置 `bpy.ops.wm.alembic_export`。operator context、selection 和 scene frame range 必须显式 override/恢复，且默认 `as_background_job=False` 以便拿到同步成功/失败结果。

实验 USDC 使用 Blender bundled `pxr`，必须 capability detect；没有 `pxr` 时隐藏后端而不是安装网络依赖。

若将来决定直接写 Alembic：

- 优先复用 Blender 自带 Alembic 能力或单独 helper process；
- 不把 Alembic C++ 类型泄漏到 hotools native 公共 ABI；
- 先冻结许可证、DLL 体积、Blender 4.5/5.1 ABI、异常恢复和多对象 writer benchmark；
- direct ABC writer 仍不能承诺随机单帧覆盖。

## 失败与安全边界

以下情况必须在任何 Action/Mesh cache 写入前失败：

- world/frame context 无效；
- Writeback receipt 缺失或过期；
- cache directory 不可解析或不可写；
- prefix 归一化后为空；
- target identity 冲突；
- Mesh provider 缺失；
- topology/vertex count/space 不匹配；
- sample 含 NaN/Inf；
- 同一 target/component 有多 writer；
- manifest 属于不同 blend/scene 且未显式接管。

一个 target 写失败时，本帧整体不提交。不能返回“写了 7/8 个对象也算成功”。

禁止自动删除 cache directory。删除只允许按 manifest 列出的精确文件，并再次校验 canonical path 仍位于用户输入的 cache directory 内。

## 性能预算

Bake 默认不启用 Mesh，因为 Mesh IO 很可能高于 MC2 native step。

应独立统计：

```text
receipt validation
keyframe resolve/insert
mesh sample provider
GN operator/frame evaluation 或 PC2 write/flush
manifest transaction
modifier ensure
```

目标原则：

- Bake 关闭时零大数组复制、零文件系统访问。
- 只 Bake Bone/Object 时不调用 Mesh provider。
- GN 主路径不得额外构造第二份 final positions；PC2 fallback 每 target 每帧最多生成一个连续 `float32[N,3]` sample。
- 不为写 PC2 创建 Python tuple list；numpy contiguous buffer 直接写。
- modifier ensure 使用 tag/name 快速定位，不每帧全场景扫描。
- manifest 可以每帧原子更新，但不能把大 result dump 成 JSON。

代表性 benchmark 至少覆盖：

- 256/1024 Bone；
- 128/1024 Object；
- 10k/100k/500k vertices；
- 1/8/32 Mesh targets；
- 连续追加、当前帧覆盖、向后截断、崩溃恢复；
- live writeback 与 PC2 playback viewport。

## 建议模块布局

```text
physicsWorld/
  bake/
    __init__.py
    nodes.py              # @omni 节点表面
    session.py            # manifest、journal、target identity
    receipts.py           # writeback receipt schema/validation
    keyframes.py          # Action、slot/channelbag、component keying
    mesh_samples.py       # provider registry + MeshBakeSampleV1
    gn_bake.py            # GN entry配置、单对象调度、delete/pack/unpack
    pc2.py                # 可选PC2 header/read/write/overwrite/truncate
    playback.py           # GN/PC2 live与baked状态切换
    finalize.py           # Alembic finalize operator helper
    debug.py              # bake snapshot/status
```

domain 只注册 provider：

```text
physicsWorld/mc2/setups/mesh_cloth/bake_provider.py
```

公共 Bake 模块不得 import `mc2.*`、`rigid.*` 或 `spring_vrm.*` 私有实现；domain descriptor/registry 负责装载 provider。

## 分阶段实施

### Phase 0：公共合同前置

1. 把 Object delta/full transform 规范成公共 writeback command。
2. Writeback 产出带 `recordable/writeback_reason` 的 `WritebackReceiptV1`。
3. 增加树执行完成后的 `TimelineStopRequest` 调度，不在 `frame_change_post` 内直接停播放。
4. 定义稳定 target UUID 和 duplicate audit。
5. 定义 Bake declaration/capability 字段，不立刻宣称 solver `supports_bake=True`。

完成门槛：三类现有写回结果都能得到精确 receipt；生命周期清零均为不可记录；后台和 UI 模式下 TimelineStopRequest 不重入 handler。

### Phase 1：Bone/Object Action Bake

当前已完成：

1. `物理烘焙` 节点、独立 `bake/` 包和共享 session manifest。
2. 每个 Armature 的专用 Action copy/create/bind，后续帧稳定复用。
3. 从当前 frame/generation 的单条与 batch Bone result 精确解析 participant。
4. 沿用旧骨骼 K 帧节点的三种 rotation mode 插帧机制，并覆盖 location/rotation/scale。
5. GN 多 Mesh 调度仅允许第一遍完整时间轴记录 Action。
6. 独立 `清除物理Bake动画` 节点、三个整数留存策略和精确 participant live 清理。
7. Bone boundary baseline capture、首次第 2 帧回填第 1 帧；清理帧不留清零关键帧。
8. 部分清理后临时恢复源 Action，避免后续 Bake key 向前外推形成残余姿态。

本 Phase 剩余：

1. result/receipt 携带真实 component ownership 后实现 Bone component-aware keying。
2. Object delta keying。
3. 接入 full object transform command，但允许当前无 producer。
4. Object/PC2 boundary baseline 与跨格式公共 snapshot。
5. manifest 自有回绕检测、Bake 侧暂停请求和 journal 恢复。

完成门槛：未参与物理的 Bone/Object 曲线逐项不变；connected/disconnected bone、三种 rotation mode、parented object、同帧和双 world 通过后台测试；停在第 1 帧开始播放时最终 Action 同时拥有正确第 1、2 帧；从高帧回到第 1 帧后在完整事务结束后暂停。

### Phase 2：Geometry Nodes Mesh Bake

当前已完成：

1. 固化相邻的 live offset 与 cache modifier schema，并实现 schema 2 组合组保留 Bake node/entry 的拆分迁移。
2. 注册真实 `物理烘焙` OmniNode；`bake_mesh` 边沿触发，mute 只透传 world。
3. 实现每对象持久 UUID、唯一目录、原子 manifest、保存 `.blend` 前置检查。
4. 实现 timer 延迟启动、`geometry_node_bake_single` 逐对象调度、active 重入保护、帧/选择恢复和失败状态。
5. 实现 `use_mesh_cache` 的 COMPLETE 校验；live/cache 切换不修改缓存文件。
6. Clear 的 GN KEEP、INVALIDATE_FROM_CLEAR_FRAME、DELETE_SESSION；删除前校验 manifest/entry 路径一致。

本 Phase 剩余：

1. UI 可取消、进度汇报与取消后的精确 PARTIAL 恢复。
2. pack/unpack 与取消后恢复；Clear 节点的默认策略保持 KEEP。
3. 对 1/8/32 Mesh targets 做重复 depsgraph 求值成本 benchmark。
4. duplicate UUID 的全场景 audit，不只处理同一请求内冲突。

完成门槛：保存/重开后的 GN cache 每帧顶点与 live MC2 result 逐点一致；关闭/开启 cache modifier 不改磁盘数据且立即切换 live/baked；多个共享 node group 的对象使用独立目录，删除一个不影响其他对象；未保存 blend、取消、写盘失败、节点组 schema 变化均不留下伪完成状态。

### Phase 2B：PC2 Fallback

1. 实现 PC2 writer/reader oracle 与 MeshBakeSample provider registry。
2. 实现 MC2 BasePose + final offset provider。
3. 实现多 Mesh manifest、事务和路径回填。
4. ensure Mesh Cache modifier 与 live/playback 互斥。

完成门槛：Blender 实际用 Mesh Cache modifier 回放的每帧顶点与 live MC2 result 在 object local 空间逐点一致；向后跳、当前帧覆盖、拓扑变化和崩溃恢复通过。只有 GN 多对象重复求值成本、版本迁移或恢复能力不满足生产要求时，才默认切换此后端。

### Phase 3：Alembic Finalize

1. 显式 operator，从 manifest 选择 playback targets。
2. 逐 target 使用已完成的 GN Bake playback；PC2 session 则启用 PC2 playback 并禁用 live GN offset。
3. 调 Blender Alembic exporter 生成一个 archive。
4. 新场景/后台重新导入 ABC，逐帧对拍 Mesh positions。
5. 保留 GN/PC2 工作缓存，manifest 记录 ABC freshness。

完成门槛：多对象、负帧、非 24 FPS、父级变换和相对路径 round-trip 通过。

### Phase 4：实验后端

- USDC direct writer benchmark 与 Blender round-trip。
- 评估未来 Blender 是否新增普通 Bake 节点 multi-object/batch API；有公开能力后再把 N 次帧遍历收敛成一次。

## 测试矩阵

### 纯 Python/Tier A

- PC2 header 端序、frame offset、append、overwrite、truncate。
- manifest schema、路径归一化、UUID 冲突、atomic replace。
- journal partial failure recovery。
- quaternion continuity、Euler compatibility。
- target/component writer conflict。

### Blender 4.5 background

- `keyframe_insert` 对 Action slot/layer 的实际行为。
- 只清精确物理 Bone，未参与骨全部数据不变。
- MC2 connected bone 不生成 location；disconnected bone 保留 location。
- Object Euler/Quaternion delta round-trip。
- parented full transform round-trip。
- Mesh Cache modifier PC2 播放。
- GN Bake 精确驱动自定义帧范围并在结束后恢复原帧。
- GN Bake 保存/重开仍读取磁盘数据；delete 后恢复 live 后置位移。
- 多对象共享 node group、独立目录、逐对象 Bake/delete ownership。
- `simulation_nodes_cache_bake` 不得被当作普通 Bake 节点批量 API。
- MC2 animated Armature/Shape Key BasePose + physics offset 对拍。
- live/playback modifier 互斥，无双重 offset。
- `//` 路径、未保存 blend、重名对象、多场景。
- 停在第 1 帧播放时首次 post handler 位于第 2 帧，但 Bake 正确回填第 1 帧。
- `last_recorded_frame > boundary_frame` 后回到边界帧会暂停；跳到任意其他帧不会触发 Clear。
- Clear 节点 mute/disabled 时零清理；enabled 且命中 clear frame 时按三个策略分别执行。
- `mesh_cache_policy=KEEP` 与 `finalize_cache_policy=KEEP` 对文件内容、长度、mtime 和 modifier filepath 均零修改。

### 生命周期

- Cache Delete、clear_all、addon unregister 不删除已提交用户 Bake 文件。
- 只有用户选择 `DELETE_SESSION` 才删除 manifest 拥有文件；默认 KEEP。
- world replacement 后仍能从 manifest 精确恢复 participant、baseline 和留存策略。
- 写盘失败、Action 插入失败、modifier ensure 失败均不提交半帧。

### 性能

- Bake 全关与当前 writeback 基线无可测回退。
- Bone/Object 大批量 K 帧耗时独立统计。
- GN Bake 10k/100k/500k 顶点、1/8/32 对象的单对象 IO 与重复全时间轴求值统计。
- PC2 fallback 10k/100k/500k 顶点的 provider/write/flush 分离统计。
- Alembic finalize 单独计时，不混进逐帧 solver ceiling。

## 已决策项与仍需实测项

已决策：

- 通用 Physics World 节点，不做 MC2 私有 Bake。
- Writeback 后执行并消费 receipt/result，不读现场猜测。
- 专用 Action，保护源 Action 和未参与物理骨。
- Geometry Nodes Bake 为第一版 Blender 内部 Mesh 工作缓存。
- 受管 cache modifier 紧跟 live Set Position modifier，直接缓存其最终 Geometry。
- 普通 Bake 节点按对象逐次调 operator，每对象独立目录；Simulation Zone 的批量 operator 不适用。
- PC2 保留为恢复、审计和性能 fallback，不是默认路径。
- Alembic 为显式 finalize 交付格式。
- MDD 不实现。
- ptcache 不接。
- Mesh 默认关闭。
- manifest/journal 是生产必需品。
- Bake/Clear 控制不依赖 Physics World 跳帧分类。
- boundary frame 默认 1；第一次自动执行在第 2 帧时回填第 1 帧基线。
- 返回 boundary frame 可选自动暂停，但绝不自动清动画或文件。
- 清理是独立、可 mute 的节点；动画、GN/PC2 工作缓存、finalized cache 留存策略由用户分别选择。
- 外部缓存默认 KEEP，系统不得隐式删除。

仍需实现前 spike/benchmark 确认：

- Blender 4.5 layered Action 的最高效范围删除路径。
- 大批量关键帧是否需要从 `keyframe_insert` 升级为批量 FCurve writer。
- GN Bake 在代表性多 Mesh 资产上重复求值的总耗时、取消延迟和磁盘体积。
- GN 私有 cache 跨 Blender patch/minor 版本迁移策略，以及 Pack/Unpack 的工程工作流。
- PC2 fallback modifier 在代表性多 Mesh 资产上的 viewport IO 上限。
- Alembic exporter 对当前修改器栈、负帧、父级 transform 的 exact round-trip 参数。
- USDC 每帧 Save、随机覆盖后的文件膨胀和内存上限。
- 是否值得实现一个临时聚合 Geometry 的单 modifier Bake 以减少多对象帧遍历；在证明 identity、拓扑拆分和内存收益前不进入生产。

这些是实测门槛，不改变第一版架构方向。

## Blender 4.5 核对记录与官方入口

2026-07-20 在本机 Blender 4.5.0（build hash `8cb6b388974a`）直接检查 RNA：

- `MeshCacheModifier.cache_format` 仅有 `MDD/PC2`。
- `MeshSequenceCacheModifier` 有 `cache_file/object_path/read_data`。
- `CacheFile` 支持 filepath、sequence、frame override、prefetch、object paths。
- `PointCache` 有磁盘、external、compression 和 frame range 属性，但无任意 sample 写入函数。
- `bpy.ops.ptcache.bake` 只有 bake 控制，不接收顶点 buffer。
- `bpy.ops.wm.alembic_export` 支持 start/end、selected、normals、UV、evaluation mode 等。
- bundled `pxr` 可用，通用 Python `alembic` module 不可用。
- `GeometryNodeBake` 默认具有 Geometry item；`NodesModifier.bakes` 为每 modifier 提供对应 entry。
- `geometry_node_bake_single` 会驱动完整自定义帧范围并恢复原帧；磁盘 cache 保存/重开可读，single delete 恢复 live 输出。
- `simulation_nodes_cache_bake(selected=True)` 只处理 Simulation Zone，不处理普通 `GeometryNodeBake`。

官方资料：

- Blender Python API: `https://docs.blender.org/api/current/bpy.types.MeshCacheModifier.html`
- Blender Python API: `https://docs.blender.org/api/current/bpy.types.MeshSequenceCacheModifier.html`
- Blender Python API: `https://docs.blender.org/api/current/bpy.types.CacheFile.html`
- Blender Python API: `https://docs.blender.org/api/current/bpy.types.PointCache.html`
- Blender Python API: `https://docs.blender.org/api/current/bpy.ops.ptcache.html`
- Blender Python API: `https://docs.blender.org/api/current/bpy.types.GeometryNodeBake.html`
- Blender Python API: `https://docs.blender.org/api/current/bpy.types.NodesModifier.html`
- Blender Geometry Nodes Baking manual: `https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/baking.html`
- Blender 4.5 Alembic manual: `https://docs.blender.org/manual/en/4.5/files/import_export/alembic.html`
- Blender Mesh Cache manual: `https://docs.blender.org/manual/en/latest/modeling/modifiers/modify/mesh_cache.html`
- Blender Mesh Sequence Cache manual: `https://docs.blender.org/manual/en/latest/modeling/modifiers/modify/mesh_sequence_cache.html`
- OpenUSD `UsdGeomMesh`: `https://openusd.org/dev/api/class_usd_geom_mesh.html`

## 最终推荐链路

```text
Live simulation
  result streams
    -> Physics Writeback
         -> WritebackReceiptV1
    -> Physics Bake
         -> dedicated Actions (Bone/Object)
         -> shared GN Set Position modifier
         -> per-object enabled/disabled GN Bake modifier
         -> per-object GN cache directory + atomic manifest
         -> optional MC2 MeshBakeSampleV1 -> PC2 fallback
         -> optional TimelineStopRequest at boundary return
    -> Clear Physics Bake (optional, user-controlled)
         -> animation clear mode
         -> independent GN/PC2/ABC retention policies
         -> boundary baseline snapshot
    -> Physics World Commit

Playback
  base modifier stack
    -> managed GN Bake output (primary)
    -> or HoTools PC2 Mesh Cache (fallback)

Delivery
  validated GN/PC2 playback targets
    -> explicit Finalize Physics Cache
    -> one Alembic archive
```

这条路径让 Blender 自己的 GN Bake 直接缓存后置位移后的最终 Geometry，省掉额外代理修改器和双重 offset 切换；PC2 保留为恢复/兼容 fallback，Alembic 负责最终交付。Writeback receipt 和 manifest 保证 Bake 永远只作用于真实物理 target。是否保留 Action、GN/PC2 工作缓存和最终 ABC 则始终由用户在 Clear 节点分别决定。
