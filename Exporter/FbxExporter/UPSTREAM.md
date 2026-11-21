# 官方 FBX 后端来源与升级

本目录将官方后端固定为 HoTools 的私有依赖，不注册第二套 Blender 导出操作器。
Blender 自带的 `export_scene.fbx` 保持原状；HoFBX 通过 `backend.py` 直接调用私有后端。

## 来源

- Blender 4.5.8 LTS，构建哈希 `d7359176d0d3`。
- 官方发行包 `4.5/scripts/addons_core/io_scene_fbx`，FBX IO 版本 `5.13.1`。
- 输出格式版本 `7400`。
- `_vendor/` 中五个官方实现文件的原始 SHA-256 记录在 `upstream.json`。
- 保留原文件作者与 SPDX 声明，许可证文本为 `_vendor/LICENSE.txt`。
- `_vendor/__init__.py` 仅保留上游 `bl_info` 元数据，供文件头使用，不包含 UI 或注册逻辑。

固定维护的五个文件是 `export_fbx_bin.py`、`fbx_utils.py`、`encode_bin.py`、
`data_types.py`、`fbx_utils_threading.py`。导入器不是运行时依赖，不复制进发布包。

## 受控的上游实现改动

`_vendor/export_fbx_bin.py` 在所有压缩工作线程退出后、`encode_bin.write` 之前增加：

```python
# HoTools: always normalize the completed tree before encoding (see ../UPSTREAM.md).
from ..cleanup import optimize_fbx_tree
optimize_fbx_tree(root)
```

`fbx_skeleton_from_armature` 为实际导出的 Empty 父节点保留蒙皮 Mesh 的局部变换：

```python
# HoTools: exported Empty grouping parents keep a real local transform (see ../UPSTREAM.md).
if ob_obj.parent and ob_obj.parent.type == 'EMPTY' and ob_obj.has_valid_parent(objects):
    ob_obj.parented_to_armature = False
```

上游将所有蒙皮 Mesh 标成世界空间，但只在直接父级为该 Armature 时断开父连接。
保留 Empty 分组后，Mesh→Empty 连接仍存在，世界矩阵若再当局部矩阵导出会重复应用父变换。
此补丁仅覆盖实际保留的 Empty 父节点；Skin／Cluster 仍使用显式的全局绑定矩阵。

清理实现放在 `cleanup.py`。参数与坐标轴适配放在 `backend.py`；它保留官方
`ExportFBX.execute` 构建 `global_matrix` 的约定。场景预处理、侧车元数据与撤销恢复
仍由 `operator.py` 负责。禁止临时替换安装目录里的官方函数或编码器。

## 更新步骤

1. 选定目标 Blender 版本，整体更新上述五个文件，记录构建版本和原始哈希；
   同步检查其相对导入及 `bl_info`，新增依赖随同维护。
2. 重新应用上述写盘前调用及 Empty 父节点局部空间补丁，不把清理算法散写进官方各个导出函数。
3. 对照新版本的 `ExportFBX.execute` 检查 `backend.py` 的参数、轴向与单位处理。
4. 检查 `FBXElem` 标量、数组编码以及压缩线程边界。`cleanup.py` 读取的是完成编码的
   内存属性，不应在数组仍是压缩任务占位符时运行。
5. 运行下列单元测试、Blender 对照和现有 HoFBX 回归，再在 Unity 验证同一资产的导入。
   四个未改变的上游实现文件应与来源在归一化换行后一致；导出文件移除上述两个接入块后
   也应一致。`test_fbx_upstream_snapshot.py` 检查归一化哈希，兼容 Git 的跨平台换行转换；
   原始文件字节哈希另行保留为来源记录。

```powershell
python tests/test_fbx_backend_cleanup.py
python tests/test_fbx_upstream_snapshot.py
blender -b --factory-startup --python-exit-code 1 --python tests/test_blender_fbx_private_backend.py
```

对于真实慢文件，可以用只写独立输出的验证脚本复现生产清理：

```powershell
blender -b --factory-startup --python-exit-code 1 --python tests/verify_fbx_cleanup_snapshot.py -- INPUT.fbx OUTPUT.fbx
```

它会比较所有保留对象的属性、绑定矩阵集合、连接关系，并生成验证 JSON。
模型、生成的 FBX、Unity Library 和原始 Profiler 采样均不入库。

## 清理的兼容边界

- 只合并骨骼 UUID 集合相同、版本相同且所有重复 Node 矩阵逐字节一致的全局 BindPose。
  相同骨骼名称不能代替 UUID；冲突姿态、部分骨架、独立骨架、纯物体/形态键姿态保持独立。
- 保留被 Connections 引用的 Pose、带额外元数据的 Pose，以及无法确认格式的姿态。
- 空 Cluster 必须没有任何非零权重、只有标准骨骼到 Skin 的连接、没有额外用户数据，
  并且其骨骼绑定矩阵已在保留姿态中唯一保存。极小、负值或非有限的非零权重都不会被当作零清除。
- 一个 Skin 若完全没有有效权重，则保留其 Cluster，避免改变导入器的兜底行为或渲染器类型。
- 不删除骨骼、网格、形态键或动画曲线，不改变有效权重。
- 依据实际剩余对象同步 Pose/Deformer Definitions 计数、总数和受影响的 Connections，
  同时纠正上游对 shape-only Pose、多网格 Skin 的计数遗漏。
- 先完成计划与结构校验，再修改数据树；未知结构保守保留。

验证范围和实测数据见 [VALIDATION.md](VALIDATION.md)。
