# Jolt 多线程调查与实施契约

状态：根因调查已完成，当前生产后端仍使用 `JobSystemSingleThreaded`；线程池实现已在隔离 pyd 中通过 Blender 验证。

本文只讨论 Jolt 刚体后端的运行线程模型、构建稳定性和进程隔离边界。它不把 Blender 的 UI、depsgraph、节点编译或物理写回搬到 worker 线程。

## 结论摘要

Jolt 已经原生支持多线程。`PhysicsSystem::Update` 接收 `JobSystem*`，官方样例使用 `JobSystemThreadPool`；`JobSystemSingleThreaded` 只是把同一套 job 接口立即在当前线程执行。参考：[Jolt JobSystem](https://jrouwe.github.io/JoltPhysics/class_job_system.html)、[Jolt PhysicsSystem](https://jrouwe.github.io/JoltPhysics/class_physics_system.html) 和官方 [Architecture](https://github.com/jrouwe/JoltPhysics/blob/master/Docs/Architecture.md)。

此前一次新的 pyd 构建在 Blender 4.5.8 中于 `PhysicsSystem::Init` 的 `MSVCP140!Thrd_yield` 路径崩溃，而不是 nanobind 导入阶段。追溯后确认 FetchContent 使用的 Jolt 源码丢失了 HoTools 原有的 Win32 `Mutex.h` 修补，导致 Blender 的 `tbbmalloc_proxy.dll` 环境再次进入 `std::mutex` 路径。旧的可用 pyd 与新产物的 PE 链接器版本均为 14.44；因此当前证据不支持“必须换成 14.29 工具链”是根因。修补已固化到 `_native/CMakeLists.txt`，生产 pyd 在隔离验证完成前仍不替换。

本阶段的决策是：先做 ABI 兼容的进程内线程池探针，再做可关闭的 native 线程池实现；只有在构建兼容性或 Blender 进程稳定性仍无法满足验收时，才实现独立 Jolt host 进程。

## 当前边界

当前 `JoltWorld` 的所有权关系如下：

```text
Blender 主线程
  Python adapter / PhysicsWorld cache / writeback
      -> JoltWorld owner
          -> PhysicsSystem
          -> TempAllocator
          -> JobSystemSingleThreaded
          -> ContactListener
```

- Blender RNA、depsgraph、对象变换、节点图和写回只能在主线程访问。
- `JoltWorld` 内部可以拥有 worker，但 worker 不得调用 Python、nanobind、Blender API 或持有 Python 对象的回调。
- `step()` 必须是同步边界：返回前所有 Jolt worker 都已完成，结果已进入 native snapshot；Python 只在返回后读取快照。
- `clear()`、重置、替换和析构必须先阻止新的 step，再等待/加入所有 worker，之后才能释放 listener、body、constraint、allocator 和 PhysicsSystem。
- 每个 world 只允许一个正在执行的 `PhysicsSystem::Update`。多 world 可以在未来由更高层调度，但不能让同一个 world 并发 step。
- contact 事件先写 native-owned 的线程安全缓冲区，step 结束后统一排序、归一化并交给 Python；worker 不直接触碰 Python 容器。

## Jolt 线程模型的事实

Jolt 的 job 接口由 `JobSystem` 抽象；官方 `JobSystemThreadPool` 提供 worker、job freelist、barrier 和 semaphore，`PhysicsSystem::Update` 在碰撞检测、约束求解等阶段提交可并行 job。官方架构说明明确指出，同一组内的更新不依赖顺序，因此可以并行化。

这不意味着任意 Jolt API 都可以并发调用：

- world 的结构变更仍需在 step 外完成，并遵守 Jolt 的 body/constraint 生命周期规则。
- `PhysicsSystem::Update` 期间不得由另一个线程修改 body、shape、constraint registry 或 contact listener 的配置。
- worker 数量不是越多越好。Jolt 的 `max_jobs`、`max_barriers` 和 worker 数需要作为 native 配置，并限制在物理 world 内，不能读取 Blender UI 状态作为线程同步。
- 多线程结果不应承诺跨线程数 bitwise determinism。验收应使用物理语义容差，并额外记录稳定排序后的 trace。

## 已知风险与处理

### 1. 构建/CRT ABI 与 Mutex 路径

Blender 4.5.8 的进程环境仍要求 pyd、Jolt 和 CRT 边界保持一致；但本轮对照实验显示，实际崩溃来自 Jolt `Mutex.h` 的 STL Win32 实现，而不是线程池本身或链接器版本。应把“构建产物能在 Blender 中构造并销毁 `JoltWorld`”作为第一道门，而不是只运行独立 Python 测试。

每次切换线程模型前都要执行：

1. 独立 exe ABI 探针：初始化 Jolt、创建/销毁 thread pool、创建 PhysicsSystem、运行固定 fixture。
2. Blender background smoke：在真实 Blender Python 中 import、构造、step、clear、销毁。
3. `模拟.blend` 的打开、跳帧、重置、对象删除 smoke。
4. py311 和 py313 分别验证；不能用一个 ABI 的结果替代另一个。

构建脚本必须保持 `/MD`、Jolt 与扩展相同的 CRT 约定；不要为了线程池单独引入 `/MT` 或混用 Jolt 头文件与静态库。`Mutex.h` 的 Win32 修补由 CMake 自动执行，任何 mutex、semaphore、allocator 配置变化都要在上述三层 smoke 后才允许合入。

### 本轮调查结论

- 未修补的 Jolt 源码：单线程和线程池 pyd 都在 `PhysicsSystem::Init` 进入 `MSVCP140!Thrd_yield` 后崩溃；跳过模块初始化只能证明导入本身不是原因。
- 对当前 Jolt 源码应用 Win32 `CRITICAL_SECTION/SRWLOCK` 修补并全量重编 Jolt 后，单线程 Blender smoke 通过。
- 同一静态库下，固定 2 worker 的线程池 pyd 完成 128 个动态刚体、120 步模拟、清理流程；连续 5 次 Blender 后台运行均通过。
- py313 隔离线程池 pyd 在 Blender 5.2.0 中完成导入、120 步模拟和清理流程。
- 独立 native 探针的 1/2/4 worker、256/1024 body 对照均通过；当前机器上 4 worker 的 1024 body 用例较单线程更快，但 2 worker 的收益不稳定，不能提前承诺线性加速。
- 旧 Git pyd 与新 pyd 的 PE linker version 都是 14.44；本机没有可用的 14.29 工具集，因此当前不再把安装旧工具链作为首要修复动作。

### 2. ContactListener 与事件缓冲

listener 的回调发生在 Jolt worker 线程。当前的记录逻辑必须明确“写入阶段”和“读取阶段”：

- 回调只写固定布局的 native event buffer，不持有 Python 引用。
- 可以使用每线程 buffer，step 结束时由 owner 合并；这样比让每个 contact 回调争用一个全局锁更适合高接触场景。
- 合并时按 `(body_a, body_b, contact_key)` 稳定排序，状态机在主线程一次性生成 added/persisted/removed。
- `clear/reset` 先停止接受新事件，再清空 buffer；旧 generation 的事件不得泄漏到新 world。

### 3. Python GIL 与写回

第一版不释放 `step()` 的 GIL，先证明线程池和生命周期稳定。只有在 benchmark 证明 GIL 是主要瓶颈后，才允许把纯 native 的 `Update + snapshot` 包在 GIL release 区间；进入该区间前必须确保参数已经复制到 native，离开后才能创建 Python 对象或访问 adapter。

## 分阶段实施

### 阶段 A：稳定性基线与自动修补

- 保持生产 `JobSystemSingleThreaded`。
- 固化同一 fixture 的位置、速度、接触和约束 trace。
- 为 native build 记录编译器、CRT、Jolt commit、Python ABI 和 Blender 版本。
- 配置阶段验证并应用 Jolt `Mutex.h` Win32 修补。
- 增加构造/step/clear/析构的 Blender smoke，失败即阻断后续线程实验。

### 阶段 B：独立原生线程池探针

增加 `hotools_jolt_thread_probe`（默认关闭，不生成 pyd）。探针只链接 Jolt，循环测试 worker 数 `1、2、4`（受机器核心数限制），验证：

- 空 world、自由落体、静态地面+动态球、接触事件和约束 fixture。
- 线程池析构后无存活 worker、无 allocator 泄漏、无悬挂 job。
- 同一线程数重复运行的 trace 稳定；不同线程数只要求在物理容差内一致。
- 运行 1/128/1024 bodies 与接触场景的 P50/P95 step 时间，记录并行收益和调度开销，不能仅凭平均值承诺加速。

探针失败时不要改 Blender adapter；先修 Jolt 构建或线程生命周期。

当前探针结果（VS 2022、Jolt 5.2.0、Release、py311-jolt 构建目录）：

| bodies | workers | steps | elapsed |
|---:|---:|---:|---:|
| 256 | 1 | 120 | 9.55 ms |
| 256 | 2 | 120 | 8.96 ms |
| 256 | 4 | 120 | 9.27 ms |
| 1024 | 1 | 120 | 29.49--29.98 ms |
| 1024 | 2 | 120 | 31.23--31.87 ms |
| 1024 | 4 | 120 | 26.78--27.83 ms |

1024 body case 连续重复三次通过，包含静态地面、动态球、重力、碰撞、位置有限性检查和 body 清理。Blender 4.5.8 的现有稳定 pyd 也通过 import、构造、step、平面碰撞和 clear smoke；这次没有替换 pyd，因此该结果只证明 Jolt 本体线程池和当前构建链可行，不代表生产 adapter 已经启用多线程。

随后用同一份源码生成两个临时 pyd 做对照：

- 线程池实验 pyd（固定 2 worker）在 Blender 构造阶段崩溃，栈为 `MSVCP140.dll!Thrd_yield`。
- 不启用线程池、只使用 `JobSystemSingleThreaded` 的新编译 pyd 也在同一位置崩溃，栈相同。
- Git 中原有、已经验证过的 pyd 仍然通过 Blender smoke。

以上对照在补丁前复现了 `MSVCP140.dll!Thrd_yield`，而在补丁后单线程和线程池均通过；因此崩溃不能归因于 `JobSystemThreadPool`。旧 pyd 与新 pyd 同为 linker 14.44，工具链版本不是当前首要变量。

### 阶段 C：可关闭的进程内线程池

在 `JoltWorld` 增加显式 runtime setting：`worker_threads=0` 表示单线程，正数表示固定 worker 数，`-1` 表示受上限约束的自动值。默认仍为 `0`，直到所有验收通过。

- `JobSystemThreadPool` 的生命周期严格属于 `JoltWorld`。
- 构造时创建，销毁时先停止 world，再 join worker；不允许静态线程池跨 world 共享。
- runtime setting 变更走 world replacement，不在运行中的 world 原地换线程池。
- Python 端只提交标量配置和批量输入；不把 worker callback 暴露到 Python。
- 调试节点读取 step 结束后的 native snapshot，不读取 worker 中的中间状态。

### 阶段 D：进程后端（备用）

只有阶段 B/C 在 ABI 或 Blender 稳定性上无法通过时才实现独立 host，例如 `HoToolsJoltHost.exe`。首版采用同步请求/响应，不做异步帧管线：

```text
父进程 Blender
  request(version, generation, frame, dt, substeps, commands)
      -> 子进程 Jolt host
  response(generation, frame, body snapshot, contacts, stats, diagnostics)
```

- 子进程不加载 Blender、不持有 RNA、不得回调父进程。
- 协议必须有版本、generation、frame 和 payload 长度；父进程拒绝过期响应。
- 父进程负责启动、超时、终止和重启；子进程崩溃只能变成 solver error，不能带崩 Blender。
- reset、jump、clear、replace 都是显式命令，子进程同时清理 Jolt cache、contact buffer、debug snapshot 和增量变换。
- 进程通信和序列化有固定成本。小场景通常不值得，优先面向大 body/contact 场景或崩溃隔离。

## 验收门槛

进入下一阶段必须同时满足：

| 门 | 要求 |
|---|---|
| ABI | py311/py313 的独立探针与 Blender smoke 均通过 |
| 生命周期 | 连续 `step -> reset -> clear -> destroy` 1000 次无崩溃、无悬挂线程 |
| 结构变更 | step 外增删 body/constraint，step 内无竞态或旧 generation 事件 |
| 事件 | contact 状态机顺序稳定，overflow 可诊断，clear 后为空 |
| 数值 | 单线程基线与多线程结果在 fixture 声明容差内一致 |
| 性能 | 用相同 trace 报告 1/2/4/8 worker 的 P50/P95，不能只看平均值 |
| Blender | 打开、播放、跳帧、删除对象、关闭文件全程无 native crash |

## 当前明确不做

- 不在 worker 线程调用 Blender API、Python callback 或节点执行器。
- 不为了追求多线程而修改 PhysicsWorld 公共时间、reset、writeback 协议。
- 不在没有独立探针和 Blender smoke 的情况下直接替换生产 pyd。
- 不现在实现进程协议；它是经过阶段 B/C 仍不能满足稳定性时的隔离后端。
