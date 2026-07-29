# PMX 2.0 刚体接入研究记录

日期：2026-07-29

用途：记录协议复读、现有 HoTools/Jolt 代码审计和实施方案尚待验证的技术点。

## 已冻结结论

1. 生产输入永久只接受精确 PMX 2.0。
2. PMX 是现有 `rigid` 域的一种 source adapter，运行时只使用 `rigid_jolt`。
3. 不引入 Bullet，不新增 `rigid_mmd` solver，不复制通用刚体属性。
4. reader、canonical DTO、坐标/字段转换必须宿主无关，先于 Blender 和 native 接线完成。
5. PMX index 是文件内权威引用；稳定 source/index identity 取代名称和 pointer。
6. 骨骼 index `-1` 与 Joint 端点 `-1` 都是合法未绑定/world 语义。
7. Spring6DOF 的 hard frame/limits 与连续 spring 分开验证；逐轴 spring 未通过 Jolt fixture 前不宣称接入完成。
8. 生产解析器独立实现；本机 `mmd_tools` 只作研究 oracle，不作运行依赖。

## 本机研究输入

以下路径只用于 2026-07-29 的只读研究，不写入生产默认值：

| 用途 | 路径 | 使用边界 |
| --- | --- | --- |
| PMX 2.0 格式说明 | `D:\_SOFTWARE\MMD_FLOWS\PmxEditor_0273\Lib\PMX仕様\PMX仕様.txt` | 逐段复读二进制结构和物理字段 |
| 模型规模样本 | `E:\BaiduSyncdisk\大师` | 只读盘点，不提交模型或纹理 |
| `mmd_tools` parser | `C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\mmd_tools` | 交叉检查字段，不复制 GPL 实现 |
| HoTools 研究区 | `_research/mmd` | 保留可复现探针，JSON 结果默认忽略 |

资源和产品输入均为 PMX 2.0，这是本轮设计的冻结前提。

## PMX 2.0 协议复读结果

### 文件级规则

- binary、little endian；文本由头部选择 UTF-16LE 或 UTF-8。
- 固定头部是 magic、`float32` version、8 字节 global data。
- additional UV 为 `0..4`；顶点、纹理、材质、骨骼、Morph、刚体六类 index width 分别为 `1/2/4`。
- 顶点 index 为 unsigned；其它 index 为 signed，`-1` 可表示无引用。
- 段落固定为模型信息、顶点、面、纹理、材质、骨骼、Morph、表示枠、刚体、Joint、EOF。
- 所有 count 是 `int32`，内部记录可变长。只取物理数据也必须完整走过前置段，不能从文件尾搜索。

### 刚体记录

```text
names
bone index
group + non-collision uint16 mask
shape + size
world position + Euler rotation radians
mass + move attenuation + rotation attenuation + bounce + friction
mode 0/1/2
```

形状为 sphere/box/capsule。mode `0` 是骨骼追随，mode `1` 是动态，mode `2` 是动态并进行 bone 位置校正。

### Joint 记录

Joint type 必须为 `0`，随后是 A/B rigid index、world pose、三轴平移上下限、三轴旋转上下限、三轴移动 spring 和三轴旋转 spring。任一端点为 `-1` 表示 world endpoint；双端均为 `-1` 时记录合法但对物理世界无作用。

### 骨骼物理相关字段

物理 binding 至少需要 bone index、parent index、transform layer、flags 和 `0x1000` 物理后变形。仅保存刚体记录不足以正确安排 mode writeback。

完整协议预演和错误边界已经写入正式文档 [MMD_PMX20_PROTOCOL_CONTRACT.md](../OmniNode/PhysicsWorld/rigid/docs/MMD_PMX20_PROTOCOL_CONTRACT.md)。

## 盘点探针修订

`_research/mmd/pmx_inventory.py` 的用途是规模盘点与完整解析 smoke。当前 schema 3 做了以下修正：

- 保留版本原始 IEEE bits，精确比较 `0x40000000`，不再用一位小数格式化分类。
- 独立校验 17 字节头部、编码、additional UV 和六个 index widths。
- 绕过 `mmd_tools` 高层 loader 的 partial-model 容错。
- 临时关闭 `Joint.load` 对截断尾部的补零行为。
- 要求 parser 游标精确等于文件长度。
- 校验物理枚举、引用范围和有限数值。
- 合法 `-1` 统一按 `unbound` 统计。
- 输出 probe/parser hash、生成时间、版本 bits 和 complete-parse 计数。

2026-07-29 结果：

| 项目 | 数量 |
| --- | ---: |
| 候选路径 | 324 |
| 精确头部 | 323 |
| 完整解析到 EOF | 322 |
| 刚体 | 57,691 |
| Joint | 81,369 |
| sphere / box / capsule | 3,908 / 28,267 / 25,516 |
| mode `0 / 1 / 2` | 7,536 / 39,514 / 10,641 |
| 未绑定骨骼的刚体 | 533 |
| 一个 world endpoint 的 Joint | 126 |
| 两个 world endpoint 的 Joint | 863 |

一个 sidecar 在 magic 处失败；一个模型在合法 Joint 段后有 124 个零字节，严格 EOF 合同将其拒绝。成功解析的 81,369 条 Joint type 全为 `0`。

## HoTools 当前代码审计

### 已有通用能力

- Jolt body 已有 sphere/box/capsule、质量、摩擦、恢复、线性/角 damping、group/mask、kinematic target、force/impulse、sleep/CCD、sensor、query 和 debug/result 路径。
- 约束已有 `SIX_DOF`、逐轴 Free/Fixed/Limited、motor state 与 position/orientation target。
- PhysicsWorld 已有 `world.implicit_objects` 和 `rigid.generated_constraint` 的稳定 registration/sync/prune 模式。
- `simulation_order_key` 已与 pointer-based runtime identity 分离。

### 必须先补的通用缺口

- `RigidBodySpec` 构造仍要求 Blender Object，默认 slot ID 来自 `obj_ptr/data_ptr`。
- 尚无 `rigid.generated_body` 的 implicit 生命周期。
- `ConstraintSpec` 只保存 target pointers，Jolt adapter 用 pointer 前缀解析 body。
- result/query/command/writeback 的部分路径仍假设 body 有 Object。
- SixDOF motor spring 的公共参数仍是共享值，无法保留六轴不同 spring constant。
- 没有 `pmx_bone_index -> PoseBone stable identity` 的显式绑定合同。

这些是通用基础设施问题，不构成新增物理解算器的理由。

## PMX 2.0 到 Jolt 的核心映射

| 源字段 | 目标语义 | 当前判断 |
| --- | --- | --- |
| rigid index/name | stable slot + metadata | index 派生身份，名称只显示 |
| bone index | binding table | 原值保留；`-1` 合法 |
| group/mask | Jolt group + allow mask | `group+1`，`(~mask)&0xffff` |
| sphere | radius | `size.x` 经单位缩放 |
| box | half-extents | PMX size 经 basis permutation，不重复除二 |
| capsule | radius + cylinder half-height | `size.x`、`size.y/2`，轴需 fixture |
| mode `0` | KINEMATIC 或 unbound STATIC | binding resolver 提供 target |
| mode `1` | DYNAMIC + full writeback | 未绑定仍可模拟 |
| mode `2` | DYNAMIC + correction writeback | body type 不另建枚举 |
| Joint world pose | A/B local frames | `inverse(body0) * joint0`；单 world endpoint 建 frame，双 world endpoint 保留 no-op |
| hard limits | SixDOF axes | frame/limit fixture 后派生 |
| six spring constants | per-axis position motor candidate | 校准门卫，不能直接复制共享值 |
| attenuation | Jolt damping | 校准门卫，保留源值 |

PMX Joint 不提供“连接体禁碰撞”字段，adapter 应设置 `disable_collisions=False` 并让 group/mask 决定碰撞。

## Jolt 资料与尚待验证点

官方 [SixDOFConstraintSettings](https://jrouwe.github.io/JoltPhysics/class_six_d_o_f_constraint_settings.html) 和 [SixDOFConstraint](https://jrouwe.github.io/JoltPhysics/class_six_d_o_f_constraint.html) 是当前 native 设计依据：每轴可设 Free/Fixed/Limited 和 motor；limit spring settings 只覆盖平移轴；position/orientation targets 有各自 constraint-space 约定。

必须用 fixture 回答，而不是继续文档推测：

1. PMX basis、Euler 顺序和 model root 的唯一转换矩阵。
2. capsule 轴与 `size.y` 到 Jolt cylinder half-height 的边界。
3. 反向 limit span 的确定语义。
4. 非恒等 A/B frame 下 translation/rotation position motor 的目标空间。
5. spring constant 到 `StiffnessAndDamping` 的单位、默认 damping 和 cap。
6. move/rotation attenuation 在固定 `dt/substep` 下的转换。
7. mode `2` 的 body-to-bone correction 与 IK/物理后变形时序。

## 许可与测试资产

- JoltPhysics 使用 MIT；继续复用仓库已有 native 集成。
- `mmd_tools` 使用 GPLv3；研究只观察格式字段和行为，生产 reader 不复制其代码。
- 测试提交手工/生成的最小 PMX 2.0 binary、canonical JSON 和通用 Jolt fixture。
- 本机模型、纹理、盘点 JSON 和外部 checkout 不进入仓库。
