# OmniNode Runtime Cache 增强方案

更新日期：2026-06-17

本文记录围绕 Bullet 刚体后端接入时暴露出的 runtime cache 设计问题，并沉淀为一套通用 cache 增强方案。目标不是给 Bullet 单独新增 GraphNode，而是在不破坏现有 Cache Read / Cache Write / Cache Delete 使用方式的前提下，让 runtime cache 能保存需要显式销毁的资源型对象。

最终结论：第一版增强两件事：**资源销毁协议** 和 **内部写入意图**。销毁能力属于 cache value 本身；本次写入到底是替换 owner 还是确认原地 mutation，属于 Cache Write 本次收到的 value wrapper。判脏、重建、运行和资源内部状态可信度，都应由生产该 cache 的高封装解算器节点自己负责，不能交给 runtime cache 黑箱处理。

## 背景

OmniNode 当前架构里，普通业务节点由 `@omni(...)` 函数生成，跨帧状态通过 GraphNode 里的 runtime cache 读写节点显式流动。当前 cache 语义足够支持 SpringBone、Mesh XPBD、MC2 这类状态：

- Cache Read 读取上一轮 committed value。
- 函数节点根据输入和旧 cache 计算 next cache。
- Cache Write 把 next cache 写入 pending cache。
- root run 成功后提交 pending cache。
- root run 失败时丢弃 pending cache。

这种模式适合“值式状态”：dict、list、numpy array、mathutils 值、Blender 数据块引用等。问题出现在 Bullet 这类长期物理世界对象上。

Bullet 的最佳使用方式通常是长期持有一个 world：

- `btDiscreteDynamicsWorld`
- rigid bodies
- constraints
- broadphase overlap cache
- collision manifolds
- solver warm-start / island 状态

这些状态不是一份容易复制、dump、rollback 的普通 dict，而是分散在整个 native world 对象及其子对象里。它更像一个长期活着的运行时资源。

## 设计目标

1. 不给 Bullet 单独新增专用 GraphNode。
2. 不改变现有用户图的基本接法：`Cache Read -> 物理节点 -> Cache Write`。
3. 不给 Cache Write 新增 mode socket，避免让用户理解底层写入策略，也避免改变旧图 socket 拓扑。
4. 保留普通值 cache 的整值替换行为，保证旧节点兼容。
5. runtime cache 只补“资源销毁”能力和“写入意图解释”能力，不补通用判脏、重建或成功运行回调。
6. 解算器节点作为高封装功能块，继续拥有构建、运行、判定异常、清理和重建的完整职责。
7. runtime cache 只负责生命周期边界：覆盖、删除、清空、失败丢弃、插件注销。
8. 资源型 cache 的增量更新不通过 dict merge / patch 表达，而是由资源 owner 对象内部原地 mutation 表达。

## 不采用的方案

### 方案 A：每帧重建 Bullet world，只缓存 snapshot

形式：

```python
{
    "kind": "bullet_snapshot",
    "frame": 120,
    "topology_key": "...",
    "body_specs": ...,
    "joint_specs": ...,
    "positions": ...,
    "rotations": ...,
    "linear_velocity": ...,
    "angular_velocity": ...,
}
```

每帧由 Python / C++ 根据 snapshot 临时创建 Bullet world，step 后再输出新 snapshot。

优点：

- 完全符合现有 cache 语义。
- rollback、delete、dump 都简单。
- C++ 不保存跨帧对象。

缺点：

- 无法利用 Bullet 长期 world 的 broadphase、manifold、solver warm-start 等内部状态。
- 每帧重建 world 有额外成本。
- 和 Bullet 的自然使用方式不匹配。

结论：可以作为最稳的 fallback 或调试路径，但不应作为高性能长期方案的唯一形态。

### 方案 B：新增 Bullet 专用 GraphNode

把 Bullet world 做成一个改变执行上下文或 resource lifetime 的特殊 GraphNode。

优点：

- 架构边界非常显式。
- 生命周期、debug、clear 可以做成专用逻辑。

缺点：

- 过早把一个业务后端抬升为图语义。
- 违反“业务复杂不等于 GraphNode”的原则。
- 后续其他资源型模块仍会重复遇到同类问题。

结论：不优先采用。Bullet 暴露的是通用 runtime cache 能力缺口，不应先做成 Bullet 专用图节点。

### 方案 C：Cache Write 暴露写入模式 socket

例如给 Cache Write 增加 `replace / patch / resource` 输入。

优点：

- 模式可见。
- 调试时容易强制指定行为。

缺点：

- 改变节点 socket 拓扑，影响旧图和编译缓存稳定性。
- 把底层 cache 策略暴露给用户，增加操作复杂度。
- 大多数场景下写入行为应由 value 的生产节点决定，而不是由用户手动连线决定。

结论：不新增 mode socket。必要时可以保留高级面板属性，例如 `Auto / Force Replace`，但默认不暴露为图连接。

### 方案 D：完整 cache mutation IR / resource IR

把 `write_cache(key, value)` 升级成一套完整 op 系统：

- put
- patch
- managed_resource
- delete
- clear_namespace

优点：

- 扩展性强。
- 可以统一描述 patch、resource、事务和 debug。

缺点：

- 当前需求还没有必要做到完整 IR。
- 容易把 runtime cache 做成半个数据库。
- merge、append、compare-and-swap 等语义会快速膨胀。
- 会把解算器自己的业务状态机拆到外部 runtime 层，反而降低封装性。

结论：作为未来方向保留，但第一版不做完整 IR。先做更小的销毁协议。

### 方案 E：所有 cache value 都加 tag

例如：

```python
{
    "__omni_cache_tag__": "managed_resource",
    "resource_type": "bullet_world",
    "resource_id": "...",
}
```

优点：

- `OmniRuntimeState` 可以通过 tag 识别特殊资源。
- dump 时可以显示更明确的类型。

缺点：

- 对当前需求不是必需。
- cache 基本只在对应节点链路里流动，误用风险不高。
- 如果只是为了销毁资源，duck typing 的 `dispose` 协议更直接。

结论：第一版不强制 tag。未来如果需要 debug 分类或跨模块资源 registry，再考虑内部 marker 或 wrapper 类型。

### 方案 F：runtime cache 负责标脏和成功提交回调

曾考虑过给 cache value 增加：

```python
omni_cache_on_commit()
omni_cache_mark_dirty(reason)
```

结论：不采用。

原因：

- “状态是否脏”是业务判断，不是 cache 系统能通用判断的事情。
- Bullet / cloth / GPU buffer 的脏状态规则不同，放到 runtime cache 会变成黑箱。
- 解算器节点本来就是 TA 编写的高封装功能块，应该拥有完整的构建、运行、异常判定、清理和重建职责。
- 当前物理节点已经在每次 step 前处理跳帧、倒放、reset、topology 变化等异常，Bullet 也应沿用这个模式。

因此 runtime cache 不负责给资源标脏，也不负责在成功提交时清脏。资源是否需要清理重建，由生产它的解算器节点在 step 前自行判定，并且判定到异常后应立刻清理并重建。

### 方案 G：靠 `old_value is new_value` 隐式判断写入方式

曾考虑过让 runtime cache 在提交时判断：

```python
if old_value is not new_value:
    dispose(old_value)
```

这样正常连续帧输出同一个 `BulletWorldCache` 对象时不会销毁，重建后输出新对象时会销毁旧对象。

结论：不作为唯一语义。

原因：

- 这是一种隐式猜测，调试时不够清楚。
- 如果节点每帧 new 一个 wrapper 但指向同一个 native world，runtime 会误判为替换并销毁仍在使用的 world。
- 如果两个 wrapper 共享同一资源所有权，`is` 判断不能表达真实 owner 关系。
- 资源型 cache 的增量更新应由本次写入意图明确说明，而不是让 runtime 根据对象 identity 猜。

因此第一版应引入内部写入意图 wrapper：`replace` 和 `mutate`。

## 最终推荐方案：销毁协议 + 写入意图

不改变 Cache Write 节点接口，不强制 cache value tag，不新增 GraphNode。增强点分两层：

1. cache value 自身可以提供 `omni_cache_dispose(reason)`，声明如何释放自己持有的资源。
2. 本次写入的 value 可以包一层内部 `OmniCacheWriteIntent`，声明这是替换绑定还是确认原地 mutation。

这两层不要混在一起。资源对象只负责资源所有权和销毁；写入意图只负责这一次 Cache Write 的语义。

### 核心约定

runtime cache 可以保存普通值，也可以保存带销毁方法的对象。

普通值：

```python
dict
list
tuple
numpy.ndarray
mathutils.Vector
mathutils.Matrix
Blender datablock reference
```

资源型值：

```python
class BulletWorldCache:
    world_id: str
    frame: int
    topology_key: str

    def omni_cache_dispose(self, reason: str) -> None:
        ...
```

该方法不要求继承基类，使用 duck typing：

```python
dispose = getattr(value, "omni_cache_dispose", None)
if callable(dispose):
    dispose(reason)
```

不要依赖 Python `__del__`。GC 时机不稳定，Blender 退出、插件注销和节点图清 cache 时都需要显式释放。

### 写入意图

Cache Write 节点不新增 socket，但 `value` 可以是一个内部 wrapper：

```python
class OmniCacheWriteIntent:
    def __init__(self, mode: str, value):
        self.mode = mode
        self.value = value
```

提供 helper：

```python
def cache_replace(value):
    return OmniCacheWriteIntent("replace", value)

def cache_mutate(value):
    return OmniCacheWriteIntent("mutate", value)
```

没有 wrapper 的普通旧 value，默认等价于：

```python
cache_replace(value)
```

第一版只需要两种 mode。

#### `replace`

表示把 cache key 绑定到新 value。若旧 value 是资源对象且将被替换，runtime cache 在提交覆盖时调用旧 value 的 `omni_cache_dispose("replace")`。

适用场景：

- 普通 dict/list 状态整块写回。
- 第一次构建 Bullet cache。
- reset / 跳帧 / topology 变化 / settings 变化后重建 Bullet world。
- 从一个资源 owner 切换到另一个资源 owner。

#### `mutate`

表示 value 已经由业务节点原地更新，本次 Cache Write 只是确认该 key 继续绑定同一个 owner。

适用场景：

- Bullet 正常连续帧复用同一个 world owner。
- persistent solver 内部原地 step。
- GPU buffer / 外部进程句柄等资源对象原地更新状态。

`mutate` 不应触发旧 value dispose。Runtime 可以校验 committed value 是否就是 intent.value；如果不是，第一版建议报错或降级为明确错误，而不是静默当成 replace。这样能尽早暴露“每帧 new wrapper 指向同一资源”的错误设计。

### 为什么写入意图不做成资源对象方法

不建议让资源对象定义一堆写入方法，例如：

```python
cache.omni_cache_write_mode()
cache.omni_cache_merge(...)
cache.omni_cache_patch(...)
```

原因：

- 写入方式是“这一次写入”的语义，不是资源对象永久属性。
- 同一个资源对象在不同场景下可能被 replace，也可能被 mutate。
- 把所有写入模式都塞进资源对象，会让资源对象越来越臃肿，也无法覆盖所有未来写入种类。
- Cache Write 只需要识别一个小型 intent wrapper，语义更清楚。

因此分层为：

```text
Cache value:
  资源所有权和 dispose

Cache write intent:
  本次写入是 replace 还是 mutate

Cache Write node:
  不暴露模式，只解码 intent
```

### `omni_cache_dispose(reason)`

第一版唯一必须支持的资源生命周期 hook。用于释放 cache value 背后的外部资源。

调用场景：

- committed value 被新 value 覆盖。
- Cache Delete 删除某个 key。
- clear namespace。
- clear root tree。
- clear all。
- root run 失败后丢弃 pending value。
- addon unregister 清理 runtime cache。

示例 reason：

```text
replace
delete
clear_namespace
clear_root_tree
clear_all
run_failed
unregister
```

### 不提供通用标脏协议

不提供：

```python
omni_cache_mark_dirty(reason)
omni_cache_on_commit()
```

如果资源对象内部需要类似 dirty / valid / generation 的字段，那是该资源对象和生产节点的私有实现细节。runtime cache 不读、不写、不解释这些字段。

## 为什么这种方案足够

当前 OmniNode 物理节点的常规接法是：

```text
Cache Read -> 物理节点 -> Cache Write -> output chain
```

编译器从 output node 反向收集可达子图，物理节点和 Cache Write 通常在同一条依赖链上。实际风险主要来自链路开头或物理节点自身报错：

- 如果物理节点之前的节点报错，物理节点不会 step。
- 如果物理节点自身报错，错误会直接显示 bug state。
- 如果物理节点后面只有 Cache Write 和输出节点，后置失败面很小。

因此没有必要为 Bullet world 做昂贵的“事务式 clone world”，也没有必要让 runtime cache 统一维护 dirty 状态。解算器节点每次 step 前自检即可：

```text
cache missing
frame jump
reset
topology changed
settings changed
native world invalid
```

命中异常时，解算器节点直接销毁旧资源并重建。这个职责属于解算器节点，而不是用户层面、Cache Write 节点或 runtime cache 黑箱。

## `OmniRuntimeState` 需要增强的点

当前 `write_cache(context, key, value)` 是 key 级整值写入。增强后仍保持整值写入，但在覆盖、删除和清理阶段处理销毁 hook。

### 写入阶段

Cache Write 执行时先把输入值解码为写入意图。pending cache 记录 intent，而不是裸 value。

```python
def decode_write_intent(value):
    if isinstance(value, OmniCacheWriteIntent):
        return value
    return OmniCacheWriteIntent("replace", value)


def write_cache(context, key, value):
    if context is None:
        return

    intent = decode_write_intent(value)
    namespace = context.namespace()
    context.run.pending.setdefault(namespace, {})[key] = intent
```

普通旧节点输出裸 value，自动成为 replace：

```python
return next_cache
```

资源型节点正常连续帧输出 mutate：

```python
cache.step(...)
return cache_mutate(cache)
```

资源型节点重建时输出 replace：

```python
old_cache.omni_cache_dispose("rebuild")
return cache_replace(new_cache)
```

### 成功提交 pending writes

伪代码：

```python
def commit_pending_writes(run):
    for namespace, pending_intents in run.pending.items():
        target = committed.setdefault(namespace, {})
        for key, intent in pending_intents.items():
            old_value = target.get(key)

            if intent.mode == "replace":
                new_value = snapshot_or_keep_resource(intent.value)
                if old_value is not None and old_value is not new_value:
                    dispose_value(old_value, reason="replace")
                target[key] = new_value
                continue

            if intent.mode == "mutate":
                if old_value is not intent.value:
                    raise RuntimeError("cache_mutate value is not the committed cache owner")
                target[key] = old_value
                continue

            raise RuntimeError(f"unknown cache write mode: {intent.mode}")
```

`old_value is not new_value` 在这里只是 replace 提交时的最后安全检查，不再负责判断写入语义。写入语义来自 intent。

### 删除 / 清空

伪代码：

```python
def commit_deletes(run):
    for namespace in run.deleted_namespaces:
        for value in committed.get(namespace, {}).values():
            dispose_value(value, reason="clear_namespace")
        remove_namespace(namespace)

    for namespace, keys in run.deleted_keys.items():
        for key in keys:
            dispose_value(committed[namespace].get(key), reason="delete")
            remove_key(namespace, key)
```

### root run 失败

root run 失败时，只 dispose 本轮 pending value：

```python
def rollback_pending(run):
    for value in all_pending_values(run):
        dispose_value(value, reason="run_failed")
    clear_pending()
```

不对 committed value 做 mark dirty。若某个解算器节点选择对 committed resource 做原地 mutation，它必须自己在下一次 step 前检测资源状态是否仍可信，必要时自行重建。

### `_snapshot_value` 的处理

现有 `_snapshot_value()` 会尽量 copy value。对带销毁 hook 的资源对象，第一版建议不 copy，直接保存对象引用：

```python
if has_dispose_hook(value):
    return value
```

原因：

- Bullet world 资源本来就不适合复制。
- 如果强行 copy，可能复制出一个只有 Python wrapper 没有 native resource 所有权的危险对象。
- 生命周期由 `omni_cache_dispose()` 明确管理。

## Bullet 刚体后端如何使用

Bullet 节点仍是普通函数节点外观：

```text
输入：
  cache_state: _OmniCache
  armature_obj
  rigid_body_settings
  joint_settings
  scene
  enabled
  reset
  substeps

输出：
  cache_state: _OmniCache
  affected_bones
  armature_obj
  body_count
  joint_count
```

内部流程：

```text
1. 校验 armature / settings。
2. 计算 topology_key / settings_key。
3. 如果 cache 缺失、reset、跳帧、topology 变化、settings 变化或 world 无效：
   - 由 Bullet 节点调用旧 cache 的 dispose 或 registry destroy。
   - 根据当前骨骼姿态和设置重建 Bullet world。
4. 同步 kinematic / pinned 骨骼。
5. step Bullet world。
6. 读取 body transform。
7. 批量计算目标 pose matrix。
8. 写回 PoseBone.matrix_basis。
9. 更新 cache.frame 等业务字段。
10. 正常复用时返回 cache_mutate(cache)，重建时返回 cache_replace(new_cache)。
```

Bullet cache 对象示意：

```python
class BulletWorldCache:
    kind = "hotools.bullet_world_cache"
    schema = 1

    def __init__(self, world_id, topology_key, settings_key):
        self.world_id = world_id
        self.topology_key = topology_key
        self.settings_key = settings_key
        self.frame = None
        self.body_count = 0
        self.joint_count = 0

    def omni_cache_dispose(self, reason: str):
        BulletWorldRegistry.destroy(self.world_id)
```

如果 Bullet 节点判定旧 world 无效，它可以直接：

```python
old_cache.omni_cache_dispose("rebuild")
new_cache = BulletWorldCache(...)
```

或者通过自己的 helper 封装：

```python
cache = BulletSolver.ensure_world(cache, specs, frame)
```

这个清理重建行为属于 Bullet 节点内部，不交给 Cache Write、用户连接或 runtime cache 自动推断。

## Bullet 节点完整运行链路

### 编译阶段

用户图仍然按普通 cache 闭环连接：

```text
CacheRead -> Bullet刚体解算节点 -> CacheWrite -> Output
```

编译器不理解 Bullet，也不理解 Bullet world。它只看到普通节点和 cache 节点：

```text
CacheReadCall
OpCall(Bullet刚体解算节点)
CacheWriteCall
Output
```

因此不需要为 Bullet 在 `OmniCompiler` 里新增特殊 emitter，也不需要新增 GraphNode。

### 第一帧 / cache 缺失

执行器跑到 `CacheReadCall`：

```text
读 cache key。
没有 committed cache。
输出 None。
```

执行 Bullet 节点：

```text
cache_state is None。
根据骨骼生成 body spec。
根据骨骼关系生成 joint spec。
创建 Bullet world。
创建 BulletWorldCache。
初始化 world 里的刚体和约束。
step 或初始化当前帧。
写回骨骼 pose。
输出 cache_replace(BulletWorldCache)。
```

执行 `CacheWriteCall`：

```text
解码为 replace intent。
pending cache 记录 key -> replace(BulletWorldCache)。
```

root run 成功：

```text
finish_run 提交 pending。
committed cache[key] = BulletWorldCache。
```

### 正常连续帧

执行器跑到 `CacheReadCall`：

```text
读到上一帧 committed 的 BulletWorldCache。
输出同一个 cache owner 对象。
```

执行 Bullet 节点：

```text
检查 frame 连续。
检查 topology_key 未变。
检查 settings_key 未变。
检查 world 仍有效。
判定可以复用。
同步 kinematic / pinned 骨骼输入。
调用 Bullet world.step()。
读取 transform / velocity。
换算并写回 PoseBone.matrix_basis。
更新 cache.frame / body_count / joint_count 等业务字段。
输出 cache_mutate(cache)。
```

执行 `CacheWriteCall`：

```text
解码为 mutate intent。
确认 committed cache[key] 就是该 cache owner。
pending 记录“保持此 owner 绑定”。
不 dispose 旧对象。
```

root run 成功：

```text
finish_run 提交 mutate intent。
cache key 仍然指向同一个 BulletWorldCache。
```

### 跳帧 / reset / topology 变化 / world 无效

执行器仍然先通过 `CacheReadCall` 读出旧 cache。Bullet 节点自己判定旧 world 不能复用：

```text
frame 不连续。
或 reset=True。
或骨骼拓扑变化。
或刚体/关节参数变化。
或 native world 无效。
```

Bullet 节点内部处理：

```text
old_cache.omni_cache_dispose("rebuild")。
根据当前骨骼和参数重建 Bullet world。
创建 new_cache。
初始化 / step。
写回骨骼 pose。
输出 cache_replace(new_cache)。
```

`CacheWriteCall` 只看到 replace intent：

```text
pending 记录 key -> replace(new_cache)。
```

root run 成功提交：

```text
committed cache[key] 从 old_cache 换成 new_cache。
runtime 尝试 dispose old_cache。
old_cache 已在节点内部 dispose 过，所以 dispose 必须幂等。
```

### 用户手动清 cache

用户执行 Cache Delete、clear runtime cache 或插件注销时：

```text
OmniRuntimeState 找到 committed cache value。
如果 value 有 omni_cache_dispose(reason)，调用它。
从 committed cache 删除对应 value。
```

用户不需要知道 Bullet world 如何释放。

### 报错情况

如果 Bullet 节点之前的节点报错：

```text
Bullet 节点不会执行。
world 不会 step。
pending cache 不会写。
```

如果 Bullet 节点自身报错：

```text
节点 bug state 报错。
本轮 pending 不提交。
```

如果 Bullet 节点已经 step，但后面极少数节点报错，第一版不做事务式 world clone。下一次 Bullet 节点 step 前仍由业务逻辑检查 frame / topology / world validity，不可信就清理重建。
## Cache Write 节点保持不变

Cache Write 节点不新增输入 socket。

保留：

```text
cache_key
value
enable
```

原因：

- 用户不需要理解 replace / patch / resource。
- 旧图不会因为 socket 变化失效。
- 编译器仍然只看到同一种 CacheWriteCall。
- value 是否资源型，只影响 runtime 清理时是否调用 `omni_cache_dispose()`。

高级调试需求可以以后加 UI 属性，但不作为第一版必要条件：

```text
write_policy: Auto / Force Replace
```

默认 `Auto`，且不影响 socket。

## Patch / Merge 是否需要

当前结论：第一版不需要。

原因：

- Bullet world 的关键问题不是 dict 部分字段覆盖，而是 native resource 销毁。
- 现有节点通常是读旧 cache，算出完整 next cache，再写回。
- Shallow merge / deep merge 在 list、numpy、mathutils、Blender datablock、resource object 上语义复杂，容易变成半个数据库。

未来如果确实需要路径级更新，可以追加一个内部 patch value 协议，但不要先做成公开写入模式。

第一版先只支持：

```text
replace intent      绑定新 value / 替换 owner
mutate intent       确认现有 owner 已被原地更新
dispose lifecycle   资源销毁
```

## Debug 和清理

资源型 cache 需要可观察性，但不要求一开始做复杂 inspector。

第一版可选 hook：

```python
def omni_cache_debug_snapshot(self) -> dict:
    return {
        "kind": self.kind,
        "world_id": self.world_id,
        "frame": self.frame,
        "body_count": self.body_count,
        "joint_count": self.joint_count,
    }
```

Cache Dump 遇到该 hook 时输出 debug snapshot，否则继续输出普通 `_snapshot_value()` 结果。

清理入口继续使用现有 Cache Delete / clear runtime cache operator。因为 `OmniRuntimeState` 会在 delete / clear 时调用 `omni_cache_dispose()`，所以不需要 Bullet 专用清理节点。插件注销时也应调用 `clear_all()`，释放所有 resource cache。

## 实施步骤

### Step 1：定义 dispose helper

在 `OmniRuntimeState.py` 内部增加私有 helper：

```python
def _has_cache_dispose(value) -> bool
def _dispose_cache_value(value, reason: str) -> None
def _debug_cache_value(value)
```

### Step 2：调整 `_snapshot_value()`

带 `omni_cache_dispose` 的对象不 copy，直接返回。

### Step 3：覆盖 / delete / clear 时调用 dispose

增强：

- `finish_run()` 成功提交 pending writes 时，覆盖旧值前 dispose old。
- `delete_cache()` 提交成功时 dispose deleted value。
- `clear_namespace()` 提交成功时 dispose namespace 内所有 value。
- `clear_all()` / `clear_root_tree()` 立即 dispose 对应 committed value。

### Step 4：失败时处理 pending value

root run failed 时 dispose pending values。不处理 committed value 的 dirty 状态。

### Step 5：Cache Dump 支持 debug snapshot

如果 cache value 有 `omni_cache_debug_snapshot()`，dump 输出该结果。

### Step 6：Bullet 节点使用销毁协议

Bullet 后端实现时不需要改 GraphNode：

- cache value 是 `BulletWorldCache` 对象。
- 对象内部持有 `world_id` 或 pybind/native world wrapper。
- 每次 step 前由 Bullet 节点自检 frame / topology / settings / world validity。
- 判定异常时，Bullet 节点自己清理并重建。
- delete / clear / overwrite 时由 runtime 调用 dispose。

## 需要写进架构约定的边界

1. runtime cache 允许保存带 `omni_cache_dispose()` 的对象。
2. 这类对象只在当前 Python 会话可靠，不做文件持久化。
3. 带销毁 hook 的对象由生产它的节点负责状态合法性检查和重建。
4. `OmniRuntimeState` 只负责 cache 生命周期边界，不理解具体 Bullet / GPU / solver 语义。
5. Cache Write 节点保持自动语义，不暴露 mode socket。
6. 若未来某个资源需要改变编译 IR、执行上下文或跨 namespace 调度，才重新评估是否需要 GraphNode。

## 最终结论

Bullet 暴露的问题不是“现有 cache 不能写入特殊值”，而是两件事：资源型 value 的销毁没有显式协议，以及原地 mutation 与 owner 替换需要明确区分。因此第一版增强不需要新增 GraphNode、写入模式 socket、完整 resource IR、强制 tag、通用标脏或成功提交 hook。

推荐方案是：

```text
保持 Cache Read / Cache Write / Cache Delete 节点形态不变。
保持普通值 cache 的 replace 语义不变。
新增内部 cache_replace / cache_mutate 写入意图，不暴露为 socket。
为资源型 cache value 增加 duck-typed dispose hook。
由 OmniRuntimeState 在覆盖、删除、清空、失败丢弃边界调用 dispose。
由资源生产节点负责 step 前自检、跳帧、topology 变化、清理和重建。
```

这套方案同时适用于 Bullet world、未来 native cloth persistent solver、GPU buffer、外部进程句柄等长期运行资源，并且不会把单个业务后端抬升为专用图节点。


