# Jolt 多线程运行契约

Jolt 多线程已经进入真实节点链路。Native 直接构造默认 `worker_threads=0`；Jolt 世界设置当前默认 `worker_threads=1`。本文件只维护现行线程模型、Blender 进程边界和验收规则，不保存探针施工阶段、临时 pyd 对照或单次机器耗时。

## 资源导航

- 产品优先级：[Jolt Physics 产品化路线图](../../../doc/JOLT_PHYSICS_BACKGROUND_ANALYSIS.md)
- 世界设置：[JOLT_SETTINGS_REFERENCE.md](JOLT_SETTINGS_REFERENCE.md)
- Blender 兼容约束：[Native Jolt 兼容文档](../../../../_native/docs/JOLT_BLENDER_COMPAT.md)
- 性能测量：[JOLT_PERFORMANCE_OPTIMIZATION.md](JOLT_PERFORMANCE_OPTIMIZATION.md)
- 永久构建配置：`_native/CMakeLists.txt`
- Native 实现：`_native/src/jolt_rigid.cpp`
- Python adapter：`OmniNode/PhysicsWorld/rigid/backends/jolt.py`
- Native/Blender 测试：`_native/tests/`、`OmniNode/PhysicsWorld/rigid/test/`
- [Jolt JobSystem](https://jrouwe.github.io/JoltPhysics/class_job_system.html)
- [Jolt PhysicsSystem](https://jrouwe.github.io/JoltPhysics/class_physics_system.html)
- [Jolt Architecture](https://github.com/jrouwe/JoltPhysics/blob/master/Docs/Architecture.md)

## 当前语义

| 设置 | Native job system | 更新方式 |
|---:|---|---|
| `worker_threads = 0` | `JobSystemSingleThreaded` | 构造 world 时选择 |
| `worker_threads > 0` | `JobSystemThreadPool` | 构造 world 时固定 worker 数 |

- `worker_threads` 进入 world setting signature；变化时销毁旧 adapter/world 并重建，不在运行中的 `PhysicsSystem` 上替换 job system。
- `JoltWorld.worker_threads` 返回实际配置，供 diagnostics 和测试读取。
- 多线程只发生在同步的 `JoltWorld.step()` 内。方法返回前，本次 Jolt jobs 必须结束，结果必须已经进入 native-owned snapshot。
- 不承诺不同 worker 数之间 bitwise 一致；公共语义按 fixture 容差比较，同时保持 body、constraint 和 event 的稳定排序。
- worker 数不是性能等级。小场景或低接触场景可能因调度成本变慢，必须用真实 Object 场景 A/B。

## 所有权边界

```text
Blender 主线程
  -> Python adapter / PhysicsWorld cache
      -> JoltWorld
          -> PhysicsSystem
          -> TempAllocator
          -> JobSystemSingleThreaded 或 JobSystemThreadPool
          -> ContactListener / native event buffer
  -> result stream
  -> 公共 Object writeback
```

- Blender RNA、depsgraph、Object/Collection、节点执行和写回只在 Blender 主线程访问。
- Jolt worker 不得调用 Python、nanobind、Blender API，也不得持有 Python 对象回调。
- 每个 world 同时只能执行一个 `PhysicsSystem::Update`；body、shape、constraint 和 listener 结构变更在 step 外完成。
- `clear()`、reset、adapter replacement 和析构必须先阻止新 step，等待全部 jobs 完成，再释放 listener、body、constraint、allocator 和 system。
- World generation 变化后，旧 snapshot、contact event 和 native handle 不得进入新 world。
- 多 world 并发不是当前公共能力；未来若需要，必须由 PhysicsWorld 调度层另立所有权和生命周期合同。

## Contact 与结果

ContactListener 可能在 Jolt worker 上回调，因此回调阶段只能写 native-owned 的固定布局缓冲：

- 不创建 Python 容器，不解析 Blender identity，不直接发布 result stream。
- 可使用每线程 buffer；step 结束后由 owner 合并。
- 合并结果按稳定 body pair/contact key 规范化，主线程再生成 added/persisted/removed 状态。
- Overflow 必须计数和诊断；clear/reset 后 buffer 为空，旧 generation 事件全部丢弃。
- Transform、constraint state 和 event 都在 `step()` 返回后由 adapter 读取，不暴露 worker 中间态。

## Blender 兼容约束

目标 Blender 进程曾在未修补的 Jolt STL mutex 路径中于 `PhysicsSystem::Init` 崩溃；单线程与线程池都会触发，因此不能把问题归因于 `JobSystemThreadPool`。现行长期约束是：

- `_native/CMakeLists.txt::hotools_patch_jolt_mutex` 配置阶段幂等应用 Win32 `CRITICAL_SECTION` / `SRWLOCK` patch；布局不匹配时配置直接失败。
- Jolt extension 使用与 Blender Python extension 一致的动态 CRT，并关闭 AVX/AVX2、Profiler 和 DebugRenderer。
- 全局类型注册和模块初始化不依赖 `std::call_once`。
- 独立 Python 或 native probe 不能替代真实 Blender 进程的构造、step、clear 和 dispose 测试。

详细调用栈、构建 owner 和 Jolt 升级流程只在 `JOLT_BLENDER_COMPAT.md` 维护，本文件不复制调查流水。

## GIL 与进程边界

当前产品语义把 `step()` 视为同步调用。只有 benchmark 证明 GIL 是独立瓶颈后，才允许在纯 native `Update + snapshot` 区间释放 GIL；进入前所有输入必须复制到 native，离开后才能创建 Python 对象。

独立 Jolt host 进程不是当前路线。只有进程内线程池在双 ABI、Blender 生命周期或崩溃隔离上无法满足门禁时，才单独设计带 version、generation、frame、timeout 和 restart 的进程协议；它不能作为绕过 Object 批写回问题的性能捷径。

## 性能策略

- 默认产品配置与 `1/2/4/8` worker A/B 分开报告，记录实际 worker 数。
- 使用相同 Object manifest、初态、帧序列、world settings 和 contact 数。
- 分别报告 native step、body sync、result publish、Object writeback、depsgraph 的 P50/P95 和内存高水位。
- 先解决当前 Object 稳定表和批写回瓶颈；只有 `native_step_ms` 成为主要成本后，worker tuning 才进入主优化方向。
- 性能收益不得以确定性、接触完整性、生命周期或错误诊断退化为代价。

## 验收门槛

| 门 | 要求 |
|---|---|
| ABI | py311/py313 的 native 与 Blender smoke 均通过 |
| 生命周期 | 重复 `step -> reset -> clear -> destroy` 无崩溃、悬挂 job 或旧 handle |
| 结构变更 | step 外增删 body/constraint；replacement 后完整重同步 |
| 事件 | contact 状态机稳定，overflow 可诊断，clear 后为空 |
| 数值 | 单线程与多线程在 fixture 声明容差内一致 |
| 性能 | 相同 case 报告各 worker 数的 P50/P95，不只报告平均值 |
| Blender | 打开、播放、跳帧、删除对象、关闭文件无 native crash |

资源路径、默认值或线程边界变化时更新本文。单次探针数值、通过次数和修复过程只进入机器产物与 Git。
