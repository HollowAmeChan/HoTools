# 刚体公共 Native 写回契约

本契约描述 Jolt 刚体结果进入 Blender 公共写回层时的反算边界。它属于
`PhysicsWorld` 的公共事务，不属于 Jolt solver 的私有实现。

## 数据语义

- solver 结果是绝对世界位置 `position` 与绝对世界旋转 `rotation_wxyz`。
- Blender 写回层保存的是对象的 `delta_location`、`delta_rotation_euler` 或
  `delta_rotation_quaternion`。
- 因此必须计算：
  `delta_location = solved_world_location - rest_location`；
  `delta_rotation = inverse(rest_rotation) * solved_world_rotation`。
- `rest_rotation` 按对象的 rotation mode 从批量快照恢复，不能读取本帧已经写入的
  delta，避免重复累加。

## Native ABI

`hotools_native.compute_rigid_delta_columns_v2` 接受连续的 `float32`/`int32` 列式数组，
一次处理一个 Collection 中的所有活动刚体，返回：

1. `delta_locations [N, 3]`；
2. `delta_eulers [N, 3]`，仅 Euler 模式使用；
3. `delta_quaternions [N, 4]`，Quaternion/Axis-Angle 模式使用。

Euler 分解使用 Blender 相同的六种旋转顺序和退化处理规则。native 不访问 Blender
RNA、依赖图或 Python 对象。

## Python 责任

Python 侧只做以下工作：

1. 从当前 PhysicsWorld 事务结果构造一次 native 输入；
2. 用列式 NumPy 结果回填 Collection 的三个 delta 属性；
3. 对实际写入对象调用 `Object.update_tag()`，通知 Blender 依赖图刷新；
4. 维护 touched 集合，以便 reset/dispose 时统一清除 delta。

native ABI 不可用或输入校验失败时允许回退到原有 Python 逐对象路径，并在刚体写回
诊断中记录 `native_delta_failed`。回退是兼容措施，不得成为默认路径。

## 性能基线

在 Blender 5.2、1536 个刚体接触地面的基准中，写回 P50 从约 15.8 ms 降至约
11.3 ms。剩余耗时主要来自 Blender 的 `foreach_set` 和必要的 `update_tag()`；不能
为了省去通知而删除后者，否则依赖图中的 evaluated pose 会保持旧值。
