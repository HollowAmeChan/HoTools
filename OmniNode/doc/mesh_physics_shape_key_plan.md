# Mesh Physics Node Plan

## Goal

在 `OmniNode/NodeTree/Function/Physics.py` 中增加第一版真正基于网格的物理模拟节点。

第一版目标是验证节点接口、runtime cache、shape key 写回和简单 XPBD/PBD solver 流程，不做碰撞、不做自碰撞、不接 Magicacloth2 内核。

## Current Socket Prerequisite

`_OmniVertexGroup` socket 已调整为类似 Bone socket 的直接选择方式：

- socket 内部保存 `mesh_object`
- socket 内部保存 `group_name`
- 未连接时通过 UI 先选 Mesh Object，再从该物体的 `vertex_groups` 中搜索顶点组
- runtime `default_value` 返回真实 `bpy.types.VertexGroup`
- 已连接时继续作为运行时占位 socket 传递真实顶点组对象

这样 mesh 物理节点可以直接接收 pin 顶点组，不需要额外接 `objectGetVertexGroupByName`。

## Node Interface

建议第一版节点名：

```python
meshShapeKeyXPBD(
    cache_state: _OmniCache,
    obj: bpy.types.Object,
    pin_group: _OmniVertexGroup,
    shape_key_name: str,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 6,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
    damping: float = 0.02,
    stretch_compliance: float = 0.0,
    bend_compliance: float = 0.001,
) -> tuple[_OmniCache, bpy.types.Object, int, int]
```

输出建议：

- `cache`: 下一帧模拟状态
- `obj`: 被写入 shape key 的物体
- `vertex_count`: 参与模拟的顶点数
- `constraint_count`: 约束数量

## Data Ownership

不要直接写 `obj.data.vertices[i].co`。

写回目标只允许是指定名称的 shape key：

- 若 shape key 不存在，节点创建它
- 若 shape key 存在，节点复用它
- 建议自动把目标 shape key 的 `value` 设为 `1.0`
- Basis/base mesh 只读，用于建立 rest positions 和拓扑约束
- `reset=True` 时把目标 shape key 坐标批量恢复成 Basis 坐标，并重建 cache

这样用户可以通过删除/禁用/调低 shape key 恢复模型，不会破坏原始网格。

## Shape Key Write Strategy

使用 Blender 批量 API 写入：

```python
shape_key.data.foreach_set("co", positions.reshape(-1))
obj.data.update()
obj.update_tag()
```

要求：

- `positions` 使用 `numpy.ndarray`
- dtype 优先 `float32`
- shape 为 `(vertex_count, 3)`
- 写入前用 `np.ascontiguousarray(positions, dtype=np.float32)`
- 不在每个顶点循环里写 `key.data[i].co`

## Cache Schema

cache 内建议保留 numpy 加速数据。`OmniRuntimeState._snapshot_value()` 当前对未知对象会尝试 `.copy()`，numpy array 会被保留为 numpy copy，适合 runtime cache。

建议结构：

```python
{
    "version": 1,
    "kind": "MESH_SHAPE_KEY_XPBD",
    "frame": int | None,
    "object_name": str,
    "object_ptr": int,
    "shape_key_name": str,
    "vertex_count": int,
    "topology_key": tuple,
    "pin_group_name": str,
    "rest_positions": np.ndarray,       # (n, 3), local space, float32
    "positions": np.ndarray,            # (n, 3), local space, float32
    "prev_positions": np.ndarray,       # (n, 3), local space, float32
    "inv_masses": np.ndarray,           # (n,), float32; pinned vertices are 0
    "edge_i": np.ndarray,               # (m,), int32
    "edge_j": np.ndarray,               # (m,), int32
    "edge_rest": np.ndarray,            # (m,), float32
    "bend_i": np.ndarray,               # optional first version
    "bend_j": np.ndarray,
    "bend_rest": np.ndarray,
}
```

`topology_key` 建议包含：

- object pointer 或 mesh datablock pointer
- vertex count
- edge count
- polygon count
- edge vertex index pairs hash 或 tuple

只要拓扑、顶点数、shape key 名、pin 组名变化，就重建 cache。

## Pin Group Semantics

第一版使用硬 pin：

- `pin_group` 为空时，不固定任何顶点
- 顶点在 pin group 中权重大于 `0.0` 时，`inv_mass = 0.0`
- 其他顶点 `inv_mass = 1.0`
- pinned 顶点每次 step 前强制回到 `rest_positions`

后续可以扩展成软 pin：

- 使用 pin 权重插值 inverse mass
- 增加 pin compliance
- 增加 pin target shape key 或 animated target

## Solver Flow

每次节点执行代表推进一帧。

流程：

1. 校验 `obj` 是 Mesh Object
2. 校验或创建目标 shape key
3. 校验 `pin_group` 属于该物体
4. 读取当前帧 `frame_current`
5. 判断 cache 是否匹配当前拓扑、shape key、pin group
6. 若 `reset=True` 或 cache 不匹配，基于 Basis 坐标重建 cache
7. 若跳帧、倒放或重复执行同一帧，恢复 shape key 为 rest positions，返回空 cache，不在本次执行内重建状态
8. 若 `enabled=False`，只透传 cache，不推进 solver
9. 按 `substeps` 推进：
   - 预测位置：`positions += (positions - prev_positions) * (1 - damping) + gravity * dt^2`
   - 固定 pin 顶点
   - 迭代距离约束
   - 可选迭代简单 bend 约束
   - 更新 `prev_positions`
10. 批量写入目标 shape key
11. 返回下一帧 cache

## Frame Continuity

与基础 `springBoneBase` 一致，mesh solver 第一版只接受严格连续帧推进。

- cache 中的 `frame` 是上一次成功推进的帧。
- 当 `cached_frame is not None` 且 `current_frame != cached_frame + 1` 时，判定为跳帧、倒放或重复执行同一帧。
- 命中该条件时，节点应把目标 shape key 批量恢复到 `rest_positions`，返回 `None` 作为 cache，清除 `positions`、`prev_positions`、约束 lambda 等全部运行状态。
- 下一次正常执行由 cache miss 重新建状态。
- 这样不会把旧速度带入新的时间位置。

## Constraint Model

第一版只需要两类约束：

### Stretch

从 mesh edges 生成距离约束。

XPBD 距离约束：

```text
C = length(x_i - x_j) - rest_length
alpha = compliance / dt^2
dlambda = (-C - alpha * lambda) / (w_i + w_j + alpha)
x_i += w_i * dlambda * n
x_j -= w_j * dlambda * n
```

第一版可以不跨帧保存 lambda，每次 substep/iteration 内临时数组即可。这样实现更简单，但 compliance 的物理一致性弱一些；后续需要更稳定的 XPBD 行为时再把 lambda 放进 cache。

### Bend

第一版建议使用简单距离式 bend：

- 对共享一条边的两个三角面，取两个 opposite vertex
- 对这两个 opposite vertex 建距离约束
- rest length 使用 Basis 坐标距离

这不是完整二面角 bending，但足够作为低风险第一版。

## Performance Notes

必须使用 numpy 存状态：

- positions
- prev_positions
- inv_masses
- constraint indices
- rest lengths

约束求解第一版可以 Python loop over constraints，因为 XPBD 投影有写冲突，纯 numpy 向量化会引入并行投影语义变化。性能预期：

- 1k 到 5k vertices 可用于交互验证
- 10k+ vertices 可能需要降低 iterations/substeps
- 后续如需性能，应迁移 solver 到 Magicacloth2 内核或独立 native module

写回必须批量 `foreach_set`，避免逐顶点 Python setter。

## Blender Boundaries

第一版限制：

- 只支持 Object Mode 下的 base mesh
- 不从 evaluated mesh 建拓扑
- 不支持运行时拓扑变化
- 不支持 edit mode 直接写回
- 不处理现有 shape key 动画冲突
- 不处理 Armature/Modifier 后结果
- 不做碰撞

如果物体存在目标 shape key，节点只覆盖该 shape key 的坐标，不改 Basis。

## Recommended Implementation Steps

1. 增加 `_MeshPhysics` helper class
2. 增加 mesh/object/shape key 校验函数
3. 增加 numpy 读取 Basis 坐标函数
4. 增加 shape key 创建和 `foreach_set` 写回函数
5. 增加 pin group -> `inv_masses` 构建函数
6. 增加 edge/bend constraint 构建函数
7. 增加 cache match/rebuild 逻辑
8. 增加 solver step
9. 增加 `@omni` 节点包装函数
10. 用一个简单 grid mesh 在 Blender 中手测：
    - 无 pin 时整体下落
    - 顶边 pin 时布料下垂
    - reset 恢复 shape key
    - 跳帧会清空 cache / 状态，不继承旧速度

## Follow-up Version

第二版可考虑：

- soft pin
- per-vertex weight mass
- wind force
- collision snapshot 接入
- self collision
- lambda cache
- target shape key bake
- Magicacloth2 backend adapter
