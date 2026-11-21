# 普通 Rig IR v2/v3 退役

日期：2026-11-21。状态：已完成。本轮按用户新要求覆盖此前执行计划中保留 v2/v3 的决定；两端只支持 v4，不迁移旧工程。

## 实施边界

- Blender 删除旧 schema/model、分类 writer、版本选择和旧辅助骨属性推导语义的兼容路径。v4 所需 RNA 原始采集与 binding context 迁入 `RigConstraints/source/`，不保留旧 exporter facade。
- Unity 删除 v2/v3 JSON 读取及结构校验，删除伪装成 schema 3 的 v4 投影。v4 planner 直接生成内部 execution plan，保留 sourceId／semanticId、执行屏障、最终绑定、所有权和已有数值求值器。
- 旧协议专属测试和活跃文档退役；保留有价值的原始参数、骨所有权、MCH、数值与回滚断言，并迁到 v4。
- v4 的未知字段保留、注册表摘要、语义／实现版本与严格准入继续生效。协议扩展与参数域能力仍须验证，不能因去除旧兼容而放松。
- Twist/Fan 当前后端的 `LEGACY` fidelity 是保真等级，不是接受 v3 文件；除非对应数值实现已另行验证，不更名为 Exact。
- 不改大型 `BoneTools/hoAux/`、Driver、用户资产或其他并行工作。当前导出器正在其他任务中拆包，基于其实际文件布局改本轮相关部分。

## 分步提交和验收

- [x] Blender raw/context/aim 公共采集分目录，移除旧模块、元数据推导和 HoFBX 版本分支。
- [x] Unity v4 原生 planner / execution plan；移除旧 DTO、读取、分类校验和迁移 UI。
- [x] 测试迁移：纯数据、旧版本拒绝、作者生命周期、完整 HoFBX、三后端装配／回滚和局部数值。
- [x] 同步 registry／测试矩阵，更新当前文档，删除失效入口，记录实际证据。

回归至少包括 Blender 4.5.8／5.2.0 合成数据、v4 reader/planner、真实 HoFBX→Unity 隔离工程、Copy Rotation Raw/MCH/Prefab/Merge/首帧与稳定帧。不得为了退役而将已有失败断言直接删除。旧 v2/v3 输入应明确拒绝；不提供修复或自动迁移。

## 提交记录

| 模块 | 提交 |
| --- | --- |
| Blender v4 原始采集／Aim 公共 API | `54595a0c`（执行文档与抽取同时落库） |
| Blender 删除旧 writer／版本开关／元数据猜测 | `fa2a6be3` |
| Blender 回归迁移及合成 direct oracle | `b5f5904c`、`a08cb15d` |
| Unity 唯一 v4 Planner／内部执行计划 | `89742a6` |
| 语义调度与执行屏障前移 Planner | `a959203` |
| 删除旧证据／条件与协议测试 | `de41430`、`9000bdf` |
| HoBs 测试改为 v4 | `b87c1c6` |
| 注册表与数值回归 | Blender `522baa32`、Unity `de3cae7` |

## 最终证据

- 两版 Blender（4.5.8／5.2.0）各 13 个脚本通过：完整注册／注销、RNA 全类型、binding、copyR、metadata、source facts、v4-only 操作器、最终 binding completion、ownership、e2e、MCH、review、review edges。review edges 各 17 检查；completion 16 检查并验证 writer 前最终矩阵误差为 0。
- 纯 Python `RigConstraints/tests` 27 项通过，包含旧 schema／旧证据拒绝与 registry/test matrix 引用；独立 source／Aim 共 8 项通过。
- Unity reader／planner 99 检查（含 Python 实际 HoFBX 产物）通过；新隔离项目 `IRv4OnlyImport-52` 37 项导入检查通过，覆盖三后端装配、重复导入、旧输入拒绝、回滚、Undo、报告及 Prefab 隔离。
- 两版实际 HoFBX Local Copy Rotation 各 16,188 次测量、0 失败；Raw／MCH／不同骨轴／Prefab／缺引用恢复／Merge／首帧与稳定帧／非法根拒绝和恢复继续通过。最大误差位置 1.477e-6 m、旋转 0.050589°、缩放 3.046e-6。
- 新的 Copy Location／世界 Copy Rotation／Armature／Aim 合成 fixture 各 8 owner × 25 姿态，实际 HoFBX 导出；两版 Unity 各 800 条记录（400 HoAux 断言、400 Standard 近似观察），0 失败。HoAux 按源语义声明通道，最大位置 7.343e-7 m、旋转 5.761e-5°；Armature fixture 的声明为 positionOnly，不把未承诺的仿射旋转／缩放计成精确测量。Direct 初次采样为第 2 个 native 更新帧；真正首求值由 Local 测试覆盖。
- HoBs `RunSynthetic` 通过：三后端 empty 清理、手工内容保护、重复导入、unknown／malformed／unsupported 不清已有装配和非空正例；旧角色 v3 资产不转换、不运行、不提供兼容。
- 权威 registry SHA256：`f942fa9280234bb1ff9ca9895571bbad501fafb3dee1104258d5cecfbba3d76`；Unity 副本按字节一致，覆盖表 `--check` 通过。

本地结果均在 Unity ignored `.research/`：`CopyROnlyV4-45`／`-52`、`DirectOnlyV4-final2-45`／`-52`、`IRv4OnlyImport-52`、`HoBsV4Migration`。不提交生成物与用户资产。

## 保留的边界

`HoConstraintExecutionPlan` 是唯一 v4 reader 生成的短寿命内部对象，不作为输入文件协议或防任意进程内代码修改的安全 API。预览和应用分别重新读取 TextAsset，验证指纹／注册表，并重新构建完整来源覆盖的 plan；不复用可变预览。大型 HoAux／Driver 未改。VRC 为 shim 结构验证，真实 SDK／客户端数值仍未宣称通过。UI 完成注册／RNA／布局逻辑验证，没有视觉截图证据。
