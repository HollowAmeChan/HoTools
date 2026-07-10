# SpringBone Solver 蓝本验收报告

日期：2026-07-10

基线：`main@b78d783` 加本轮审查修复

环境：Blender 4.5.0 / CPython 3.11 / Windows / Release native backend

## 验收结论

当前结论：**不通过，允许继续作为迁移蓝本开发，但不能作为已验收 solver 宣布完成。**

阻塞项：

1. 骨骼碰撞覆写的 `length / offset / primary_collision_group` 尚未进入实际 bone collider snapshot，只进入 resolver/debug；不能计为物理功能通过。
2. bake/export 还没有可重复烘焙与导出闭环。

## 本轮代码审查

### 已修复

| 严重度 | 问题 | 修复与验证 |
|---|---|---|
| P0 | legacy 35 参数 ABI 会被后续数组覆盖 `bone_count`；context ABI 未校验 dtype/长度，错误 buffer 可触发 C++ 越界访问 | 两套 ABI 统一校验 float32/int32/uint8、连续性、精确长度、parent index、schema 和输出 buffer；新增拒绝错误输入测试 |
| P1 | Solver 节点 `substeps` 被 `frame_context.substeps` 永久遮蔽，UI 参数不生效 | solver 输入成为 SpringBone 权威子步数，限制为 1-16；测试直接截获真实 native 调用并验证值为 5 |
| P1 | 非均匀 Object scale 使用 XYZ 平均缩放估算骨长 | 改为 `matrix_world.to_3x3() @ rest_vec` 的真实轴向世界长度；`(2,1,3)` 缩放下 Z 轴骨长回归通过 |
| P1 | 没有 Debug Node 时仍每帧分配数组并执行 `spring_vrm_read_debug` | 改成请求状态机：Debug Node 在 slot 留一次性请求，后续推进帧由 solver 消费并清除；节点移除后最多额外采样一帧 |
| P2 | dynamic context 保存并重填从未传入 C++ 的 target matrix/quaternion 数组 | 删除死 buffer 和重复矩阵打包 |
| P2 | 每骨每帧构造完整 `BoneCollisionProfile` 并重复扫描 override registry | solver 热路径一次构建 override index，只解析 C++ 实际消费的 type/radius/mask；公共 resolver 保持完整语义 |
| P1 | 新路径逐骨构造/复制 result dict，统一写回再逐骨解析 16-float matrix 和骨骼目标 | `slot.data.writeback_plan` 落地为跨帧复用的批次计划；result stream 每 slot 只发布一个 batch envelope，逐骨兼容结果按需展开；写回按 armature 通过一次 `foreach_set` 提交 |
| P2 | 连续帧重复解析 PoseBone records、维护未传入 context ABI 的 Python current/prev tail 状态 | topology 由 slot id 保证时复用 records；current/prev tail 只在 reset/debug readback 更新，不再进入正常播放热路径 |

### 仍未解决

#### 已解除：新架构性能回退

`writeback_plan` 批次化后，128 骨代表轮次的阶段中位数由：

| 阶段 | ms/frame |
|---|---:|
| Physics World Begin（含 `scene.frame_set`） | 0.68 |
| 隐式对象注册 | 0.07 |
| SpringBone solver wall time | 2.50 |
| 统一写回 | 0.53 |
| Commit | 0.01 |

下降到：

| 阶段 | ms/frame |
|---|---:|
| Physics World Begin（含 `scene.frame_set`） | 0.57 |
| 隐式对象注册 | 0.06 |
| SpringBone solver wall time | 1.48 |
| 统一写回 | 0.22 |
| Commit | < 0.01 |

最终纯 envelope 实现下，128 骨总耗时中位数稳定在 `2.347-2.395 ms`，旧路径为 `2.158-2.180 ms`，三轮独立 Blender 进程倍率为 `1.079x-1.099x`，已通过 `<= 1.15x` 门槛。

#### 已解除：隐式对象残留

采用 OmniNode 根树级生命周期取舍，不为注册节点增加 source lease。注册节点没有 `always_run`，输入未变时由懒求值跳过，当前编译图内的 registry 持续复用；一次真正的编译成功后，`OmniNodeTree.compile_cached()` 清空该根树全部 runtime cache，active 注册节点在新图首次运行时重新填充 registry。

因此删除、静音、改接注册节点或改变 stable id 后，只要成功重编译，旧 world、旧 implicit entry、solver slot 和 native context 会一起 dispose；其他根树不受影响。编译缓存命中不会清理，编译失败也保留旧 runtime 状态。框架回归 3/3 覆盖成功编译、缓存命中和编译失败边界，SpringBone 现有 cache dispose 回归覆盖 world 内部 registry/slot/native 清理。

#### P1：骨骼碰撞字段只部分落地

真实 C++ 消费：

- `pin` -> context static `pinned`
- `collision_type` -> 决定 hit sphere 是否启用
- `radius` -> `hit_radii`
- `collided_by_groups` -> 碰撞过滤 mask

尚未进入物理快照：

- `length`
- `offset`
- `primary_collision_group`

后三项当前可以改变 resolver/debug 图形，但不会改变 SpringBone 的实际外部 bone collider 行为。

## 性能对比

场景：单骨架、单链、无 collider、1 substep、debug capture 关闭；每轮 warmup 40 帧，测量 300 帧，共 3 个独立 Blender 进程。

| 模拟骨数 | 旧架构 median ms | 新架构 median ms | 新/旧倍率范围 | 新架构 FPS |
|---:|---:|---:|---:|---:|
| 8 | 0.268-0.276 | 0.347-0.356 | 1.260x-1.292x | 2811-2883 |
| 32 | 0.753-0.754 | 0.851-0.856 | 1.129x-1.136x | 1169-1176 |
| 128 | 2.158-2.180 | 2.347-2.395 | 1.079x-1.099x | 417-426 |

批次化前同机代表数据为 8/32/128 骨 `0.480 / 1.241 / 3.731 ms`；本轮继续下降约 `26% / 31% / 37%`。8 骨仍有 world 固定成本，但验收约定的 128 骨迁移门槛已通过。

32 collider 补充矩阵（300 帧，P50/P95）：

| 模拟骨数 | 旧 P50/P95 ms | 新 P50/P95 ms | P50 新/旧 | 门槛 |
|---:|---:|---:|---:|---:|
| 32 | 1.065 / 1.196 | 1.197 / 1.378 | 1.124x | PASS (`<= 1.25x`) |
| 128 | 2.387 / 2.679 | 2.632 / 2.934 | 1.103x | PASS (`<= 1.25x`) |

建议门槛：

- 正确性：旧/新 native 参数矩阵逐帧误差 `<= 2e-5`。
- 性能：128 骨、无碰撞时新路径不高于旧路径 `1.15x`；带 32 collider 时不高于 `1.25x`。
- 稳定性：连续 10,000 帧 native context/slot/buffer 数量不增长。

复现：

```powershell
$env:SPRING_BENCH_SIZES='8,32,128'
$env:SPRING_BENCH_WARMUP='40'
$env:SPRING_BENCH_FRAMES='300'
$env:SPRING_BENCH_COLLIDERS='0' # 设为 32 可复现 collider 矩阵
& 'D:\Blender\Blender 4.5\blender.exe' --background --factory-startup --python `
  'OmniNode\NodeTree\Function\physicsWorld\spring_vrm\benchmark_blender_spring_vrm.py'
```

## 功能参数测试矩阵

状态定义：`PASS` 已自动真实运行；`PARTIAL` 仅部分字段进入物理；`BLOCKED` 已知架构缺口；`NOT RUN` 尚无自动证据。

| ID | 域 | 参数/场景 | 真实运行判据 | 状态 |
|---|---|---|---|---|
| P-01 | Chain | stiffness_force | wrapper 截获 C++ 实参；旧/新 ABI 多帧对拍 | PASS |
| P-02 | Chain | drag_force | wrapper 截获 C++ 实参；旧/新 ABI 多帧对拍 | PASS |
| P-03 | Chain | gravity_dir | C++ 实参方向一致；重力产生对应偏转 | PASS |
| P-04 | Chain | gravity_power | C++ 实参一致；0 与非 0 结果可区分 | PASS |
| P-05 | Solver | substeps 1-16 | 节点值真实进入 `spring_vrm_step` | PASS |
| P-06 | Spec | 参数上下界 | stiffness/gravity >= 0、drag 0-1、substeps 1-16 | PASS |
| P-07 | Runtime | 热改刚度/阻尼/重力 | slot/context 不重建，下一帧实参更新 | PASS |
| P-08 | Time | scene fps/fps_base -> dt | 默认 24 fps 实测 dt=1/24 | PASS |
| P-09 | Time | time_scale=0 / 负值 | 不产生非有限值，暂停语义明确 | NOT RUN |
| P-10 | Time | 倒放 | restart，不推进 Verlet | NOT RUN |
| T-01 | Topology | 单链 | root 排除，模拟 2 骨，发布 2 项 | PASS |
| T-02 | Topology | 同 world 两骨架 | 2 个隔离 slot、4 个写回项 | PASS |
| T-03 | Topology | 同骨架多链 | 无重叠时分别推进 | NOT RUN |
| T-04 | Topology | 重复 root | 明确拒绝，不静默覆盖 | NOT RUN |
| T-05 | Topology | 模拟骨重叠 | 明确拒绝，不双写 | NOT RUN |
| T-06 | Topology | 分叉骨链 | parent index/use_connect 与预期一致 | NOT RUN |
| T-07 | Topology | 运行中改拓扑 | 旧 context dispose，新 context 只建一次 | NOT RUN |
| T-08 | Transform | 非均匀 Object scale | 骨长按骨轴世界变换计算 | PASS |
| T-09 | Transform | 负缩放/镜像 | 长度、旋转和 box handedness 稳定 | NOT RUN |
| T-10 | Transform | 零长度骨 | 不崩溃、不发布 NaN | NOT RUN |
| C-01 | Bone profile | legacy pin | pinned 骨不发生 basis 偏转 | PASS |
| C-02 | Bone profile | override pin | reset 后进入 C++ static `pinned` | PASS |
| C-03 | Bone profile | collision_type | NONE 禁用 hit sphere，SPHERE/CAPSULE 启用 | PARTIAL |
| C-04 | Bone profile | radius | override 值进入 C++ `hit_radii` | PASS |
| C-05 | Bone profile | collided_by_groups | override 值进入 C++ mask 并参与过滤 | PASS |
| C-06 | Bone profile | length | 改变真实 bone capsule 长度 | BLOCKED |
| C-07 | Bone profile | offset | 改变真实 bone collider 中心 | BLOCKED |
| C-08 | Bone profile | primary_collision_group | 改变真实 bone collider group | BLOCKED |
| C-09 | Bone profile | override disabled | 回退 legacy profile | PASS |
| C-10 | Registry | 删除/改名注册链并重编译 | 旧 stable id 不再被 solver 消费 | PASS |
| C-11 | Registry | 删除 override 注册节点并重编译 | 新图首次运行回退 legacy | PASS |
| W-01 | World collider | sphere | snapshot -> C++，尾端推出 | PASS |
| W-02 | World collider | capsule | snapshot -> C++，尾端推出 | PASS |
| W-03 | World collider | plane | snapshot -> C++，尾端推出 | PASS |
| W-04 | World collider | box | snapshot -> C++，尾端推出 | PASS |
| W-05 | World collider | group mismatch | 不发生碰撞响应 | PASS |
| W-06 | World collider | self-chain filter | 自身骨 collider 不重复作为外部 collider | PASS |
| W-07 | World collider | 运动 collider | 每帧 snapshot 失效并更新几何 | NOT RUN |
| L-01 | Lifecycle | 首帧/reset | 发布当前 pose，不推进 | PASS |
| L-02 | Lifecycle | 连续帧 | context/buffer/slot 复用 | PASS |
| L-03 | Lifecycle | 跳帧 | reset 且该帧不推进 | PASS |
| L-04 | Lifecycle | same frame | 不推进，重发缓存 result | PASS |
| L-05 | Lifecycle | scope prune | stale slot dispose | PASS |
| L-06 | Lifecycle | cache delete/clear_all | C++ capsule 与 bpy 引用释放 | PASS |
| L-07 | Lifecycle | 10,000 帧 soak | handle/buffer/内存无增长 | NOT RUN |
| D-01 | Debug | 无 Debug Node | 不调用 debug readback | PASS |
| D-02 | Debug | 下一帧请求状态机 | request -> consume -> clear | PASS |
| D-03 | Debug | 四类 collider 和组颜色 | C++ snapshot 与绘制一致 | PASS |
| R-01 | Result | bone_transform schema | channel/source/slot/frame/generation 完整 | PASS |
| R-02 | Writeback | PoseBone.matrix_basis | solver 不直写，统一节点写回 | PASS |
| R-03 | Writeback | 批量 writeback_plan | 预分配并避免逐骨 dict/matrix 重解析 | PASS |
| R-04 | Bake | bake/export | 可重复烘焙并导出 | BLOCKED |
| A-01 | ABI | legacy/context 数值一致 | 4 组参数、碰撞、多帧误差 <= 2e-5 | PASS |
| A-02 | ABI | 错误 dtype/shape/count | Python exception，不进入 C++ 越界 | PASS |
| A-03 | ABI | Blender 5.x / py313 | 重新构建并运行同一矩阵 | NOT RUN |
| F-01 | Perf | 8/32/128 骨无碰撞 | 三轮 300 帧统计 | PASS |
| F-02 | Perf | 32/128 骨 + 32 collider | 新/旧同场景 P50/P95 | PASS |
| F-03 | Perf | 多骨架 | 1/8/32 armature 扩展曲线 | NOT RUN |
| F-04 | Perf | Debug capture | off/continuous/one-shot 成本 | NOT RUN |

## 已执行回归

- Blender SpringBone 集成：27/27 通过。
- OmniNode 编译/runtime cache 生命周期：3/3 通过；覆盖成功编译仅清当前根树、编译缓存命中保留运行态、编译失败保留运行态和旧编译结果。
- Native 全套：17 个测试文件，0 skipped，0 failed。
- SpringBone legacy/context 参数矩阵：4 组、每组 6 帧，误差阈值 `2e-5`。
- Release py311 native 重新编译成功。

## 下一验收批次

1. 决定 `length/offset/primary_collision_group` 是本期实现 bone collider snapshot，还是从当前节点 UI 暂时隐藏。
2. 补同骨架多链、分叉、拓扑热改、运动 collider、soak 和 py313。
3. 落地 bake/export，再做最终 solver 验收。
