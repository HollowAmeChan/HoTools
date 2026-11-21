# 私有 FBX 后端验证记录

验证日期：2026-11-21。Blender 4.5.8 LTS，Unity 6000.3.15f1，Windows。

## 自动化验证

- `tests/test_fbx_backend_cleanup.py`：20 项内存树契约测试，覆盖姿态合并、冲突保留、
  不同骨架、部分姿态、外部引用、未知元数据、非有限矩阵、压缩零权重、极小非零权重、
  全空 Skin、Definitions 更新、无部分写入及幂等性。
- `tests/test_fbx_upstream_snapshot.py`：检查固定依赖的来源哈希与唯一上游接入块。
- `tests/test_blender_fbx_private_backend.py`：同一场景包含两套同名骨骼、四个蒙皮网格、
  非均匀物体缩放、已有姿态、四个 ShapeKey、UV 和顶点色；分别比较默认轴向、关闭轴向转换、
  厘米缩放三组官方/私有导出结果。除目标 Pose/空 Cluster 外，保留对象逐项一致；绑定矩阵
  集合、有效连接、骨骼与表情完整。每组清除 48 个空 Cluster，合并 2 个 Pose。
- 上述三组 FBX 在 Unity 中逐组导入；层级、网格、有效蒙皮与表情的语义指纹均一致。

17 个已有 Blender 回归脚本全部通过：`fbx_curves`、`fbx_constraints`、`fbx_shared_mesh`、
`fbx_data_transfer`、`fbx_data_transfer_domains`、`fbx_hidden_modifiers`、`fbx_leaf_bones`、
`fbx_multiple_armatures`、`fbx_mch_local_rotation`、`fbx_shapekey_gn`、`fbx_export_scope_warning`、
`hofbx_v4`、`hofbx_completion_edges`、`bone_collection_inheritance`、`bs_export_targets`、
`apply_rest_pose`、`module_split`。文件均位于 `tests/test_blender_*.py`。

## 羽啾固定快照

原始 FBX SHA-256：`6959d9bbc16ac70e71e4f87dfc5258da1db06c4a05d94d4ed6f1ec7f0330cef1`。
全部操作针对独立副本；原文件及其 meta 没有修改。

| 指标 | 原始快照 | 生产清理函数输出 |
| --- | ---: | ---: |
| 文件字节数 | 64,084,620 | 10,052,732 |
| FBX 骨骼数 | 1,387 | 1,387 |
| Unity 顶点数 | 123,812 | 123,812 |
| 表情数 | 91 | 91 |
| FBX Pose 数 | 46 | 5 |
| FBX PoseNode 数 | 58,342 | 1,434 |
| 空 Cluster 数 | 56,880 | 0 |
| Unity 实际强制导入时间 | 155.550 秒 | 3.476 秒 |

生产实现按骨架隔离，保留四份独立 shape-only Pose；没有为了追求最少 Pose 数而全局混并。
原始 42 份骨架 BindPose 合并为 1 份，删除 56,908 条重复 PoseNode。

先用 `verify_fbx_cleanup_snapshot.py` 经过实际私有编码器和生产清理函数验证：所有保留对象
的属性指纹、完整绑定矩阵集合和有效连接均相同。随后在独立干净 Unity 项目中，用原 meta
设置执行 `ForceSynchronousImport | ForceUpdate`，避免把缓存命中误当作导入加速。

Unity 数据指纹同时包含全部层级路径与局部变换、网格顶点、法线、切线、UV0、三角形、
按骨骼路径归一后的实际权重与绑定矩阵、全部表情名称/帧权重/位置/法线/切线增量。
原始与生产输出的 SHA-256 均为：

`04F052C3BAC66B8B3118715A4D8E2E657C6D2CED108BA2A37781AA0F2339A115`。

Humanoid Avatar 仍为 `isValid=true`、`isHuman=true`。此核对不等同于 Avatar 内部序列化
逐字节相同，也不包含材质外观渲染或完整动画播放测试。FBX 级别的保留对象比较覆盖其余
未清理的数据，例如材质、更多 UV 通道和顶点色。
