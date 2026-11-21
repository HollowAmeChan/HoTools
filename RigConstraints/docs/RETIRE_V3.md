# 普通 Rig IR v2/v3 退役

日期：2026-11-21。状态：执行中。本轮按用户新要求覆盖此前执行计划中保留 v2/v3 的决定；两端只支持 v4，不迁移旧工程。

## 实施边界

- Blender 删除旧 schema/model、分类 writer、版本选择和旧辅助骨属性推导语义的兼容路径。v4 所需 RNA 原始采集与 binding context 迁入 `RigConstraints/source/`，不保留旧 exporter facade。
- Unity 删除 v2/v3 JSON 读取及结构校验，删除伪装成 schema 3 的 v4 投影。v4 planner 直接生成内部 execution plan，保留 sourceId／semanticId、执行屏障、最终绑定、所有权和已有数值求值器。
- 旧协议专属测试和活跃文档退役；保留有价值的原始参数、骨所有权、MCH、数值与回滚断言，并迁到 v4。
- v4 的未知字段保留、注册表摘要、语义／实现版本与严格准入继续生效。协议扩展与参数域能力仍须验证，不能因去除旧兼容而放松。
- Twist/Fan 当前后端的 `LEGACY` fidelity 是保真等级，不是接受 v3 文件；除非对应数值实现已另行验证，不更名为 Exact。
- 不改大型 `BoneTools/hoAux/`、Driver、用户资产或其他并行工作。当前导出器正在其他任务中拆包，基于其实际文件布局改本轮相关部分。

## 分步提交和验收

- [ ] Blender raw/context/aim 公共采集分目录，移除旧模块、元数据推导和 HoFBX 版本分支。
- [ ] Unity v4 原生 planner / execution plan；移除旧 DTO、读取、分类校验和迁移 UI。
- [ ] 测试迁移：纯数据、旧版本拒绝、作者生命周期、完整 HoFBX、三后端装配／回滚和局部数值。
- [ ] 同步 registry／测试矩阵，更新当前文档，删除失效入口，记录实际证据。

回归至少包括 Blender 4.5.8／5.2.0 合成数据、v4 reader/planner、真实 HoFBX→Unity 隔离工程、Copy Rotation Raw/MCH/Prefab/Merge/首帧与稳定帧。不得为了退役而将已有失败断言直接删除。旧 v2/v3 输入应明确拒绝；不提供修复或自动迁移。
