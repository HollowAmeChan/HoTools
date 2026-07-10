# Rigid/Jolt 语义测试

本目录实现 `../docs/JOLT_TEST_STRATEGY.md` 定义的可执行测试架构。

当前切片（`native_binding_v1`）：

- 严格加载 `hotools_jolt_fixture_v1` JSON；
- 按 fixture id 固定刚体创建顺序和命令顺序；
- 输出包含原始 float32 位模式的规范化刚体/contact trace；
- 提供自由落体、恒速运动和冲量解析 oracle；
- 验证阻尼、速度上限和六个 allowed DOF 位的刚体参数语义；
- 支持七种已接入约束的 schema、state trace 和基础自由度 oracle；
- 验证 Fixed 相对变换、Point 锚点/旋转自由、Distance 区间收敛；
- 验证 Hinge 只绕局部 Z、Slider 只沿局部 Z、Cone swing/twist 语义；
- 验证 SwingTwist 的椭圆摆角和本地 Z 扭转限制彼此独立；
- 按 Jolt `FrequencyAndDamping` 隐式欧拉公式复算 Distance/Hinge/Slider 弹簧；
- 解析验证 Hinge/Slider 摩擦，以及速度/位置电机的限幅和收敛轨迹；
- 验证不同质量或转动惯量的双动态体反作用与总动量守恒；
- 验证 contact/sensor 状态机、接触几何字段和传感器非阻挡运动；
- 验证 RayCast 最近命中、解析几何、sensor/ignore 过滤和安全 miss；
- 解析验证 restitution 正碰、平面库仑摩擦和双向 collision mask；
- 验证旋转约束 frame、shape offset/rotation 与高速 LINEAR_CAST CCD；
- 验证独立 A/B anchor、约束禁碰删除恢复及 draw size 非物理性；
- 使用全新世界执行逐位重放检查；
- 在十个全新进程中验证 canonical physical hash 稳定；
- 输出 JSONL trace、断言报告和机器可读 manifest；
- 使用匹配的 native 模块在 CPython 3.11 和 3.13 下运行。

当前切片尚未实现：

- Cone/SwingTwist 旋转 frame 与独立 A/B frame 组合；
- adapter parity runner；
- Blender 端到端 runner；
- 断裂语义、跨 ABI 报告和已批准 golden。

使用两个全新世界运行全部 P0 fixture：

```powershell
& 'C:\Users\hhh12\AppData\Local\Programs\Python\Python313\python.exe' `
  run_native_semantics.py --tag p0 --repeat 2
```

使用 Blender 内置 Python 运行 py311 ABI：

```powershell
& 'D:\Blender\Blender 4.5\4.5\python\bin\python.exe' `
  run_native_semantics.py --tag p0 --repeat 2
```

只运行当前约束切片：

```powershell
& 'D:\Blender\Blender 4.5\4.5\python\bin\python.exe' `
  run_native_semantics.py --tag constraint --repeat 2
```

测试产物默认写入 `C:\tmp\hotools_jolt_test\<run-id>`，并且绝不会自动更新
golden 基线。

刚体始终按 fixture id 排序创建。同一 frame/phase 的 timeline 命令按 JSON
数组中的显式顺序执行；改变此顺序属于有意修改输入，并会反映在 physical hash 中。

约束 fixture 要求 native 模块提供 `get_constraint_state` 以及独立 A/B anchor
参数。旧 ABI 会明确失败；`_native/tests/run_all.py` 中的约束矩阵则会报告 SKIP，
不会把 ABI 缺失误报成物理通过。

contact/query fixture 还要求 `get_contact_events` 与 `cast_ray`。原生测试入口会把
旧 ABI 明确报告为 SKIP，并继续保留基础刚体矩阵的独立结果。
