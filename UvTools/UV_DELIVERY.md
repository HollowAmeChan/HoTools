# UV 功能交付与验证

验证日期：2026-10-13；2026-10-14 补充象限适配、取消堆叠、重叠岛连选、UV 边界 seam 及长度均化验证。
2026-10-19 补充直化岛的拓扑四边化与混合求解回滚验证。
2026-10-21 补充拓扑堆叠的活动对象目标优先和多目标分配验证。
实际版本：Blender 4.5.8 LTS（d7359176d0d3）与 5.2.0 LTS（fbe6228777e7）。
测试使用独立 `--background --factory-startup` 进程，不修改用户当前场景或偏好。

## 功能与证据

| 用户要求 | 当前实现 | 直接验证 |
| --- | --- | --- |
| 镜像所选 UV，支持 X/Y，独立于内置变换轴心 | `transform.py` 镜像操作符，`uv_math.py` 直接反射坐标 | 两次镜像复原、各编辑器 pivot、UV 光标/自定义中心、U/V、多物体、同步开关 |
| 平移所选 UV，方向与距离 | ±U/±V，UV/像素距离 | 往返、四方向、非正方形图像、缺图取消、状态与其他层不变 |
| 沿轴对齐与 Alt+A 失效修复 | 公共对齐函数；`ho.align_uv` 保留，右键有独立入口 | 多物体、平均值按独立 UV 点、隐藏点、5.2 精细选择、光标轴向、原生快捷键注册 |
| 线展开，支持兼容多内部线，避免受切向影响倒置 | 真实选中边 → 多开链 → UV 框架/区域锚点 → 原生展开 | 同岛多内部线、镜像/旋转、两种展开方法、U/V/保留方向、三角/混合/五边形/带洞岛 |
| 直化岛，四边形优先、阈值可控 | 四边形主体生成矩形行列，末端三角尖点居中并按 3D 高度延伸；其他拓扑联合阈值约束 | 完全拉直/摆正、单尖/三角扇/双端、旋转/镜像、3D 高度/缩放、面积/中心、原 pin、孔洞/L 形、混合拓扑与回滚 |
| 单模式拓扑堆叠，强制顶点对齐，考虑镜像 | 活动对象先确定各组目标，来源比较匹配误差，直接复制最终主岛全部点 | 非对称镜像、重新编号、内部点强修、活动面优先、多目标歧义/稳定顺序、共享 mesh、预算与写回回滚 |
| 紧急：本象限中线翻转到另一半 | 每个可见岛按其整数 UV 象限中线反射 | 第一象限、其他 UDIM、负象限、U/V、部分网格面选择可用、未显示 UV 不变 |
| 象限适配支持同步，按 AABB 中心居中后尽量填满 | 公共选区读取 + AABB 居中等比适配，默认第一象限 | 两版选择模式、长方形短边留白对称、多物体整体 AABB、未显示点保护、单点/直线、边距与 Undo/Redo |
| 取消堆叠，按重叠工作区横向/纵向/跨象限排列 | 实际 UV 面积交叠分组；每区各自保留首岛，区内 AABB 排列或其余统一 +1U | 独立工作区、部分重叠传递、凹岛/孔洞空白排除、单岛允许、跨区允许重叠、模式/同步、角点精确平移、回滚与 Undo/Redo |
| UV 独立 Shift+S 游标饼 | `HO_MT_uv_cursor_pie` 与独立 UV Editor 键位，共享原游标饼开关 | 八槽 UV-only、原生吸附、同步开关、二维游标与 3D 游标隔离、开关清理及原 3D 饼回归 |
| 所选 Mesh 全部活动 UV 岛边界追加 seam | `seams.py`，逐网格检测共享边两端 UV 与折叠重叠边界，立即执行 | 物体/多物体编辑模式、不同活动 UV、隐藏/未选面、同步开关、原 seam 保留、共享 mesh、形态键与回滚/Undo/Redo |
| UV 线长度均化，固定端点、按 3D 边长比例拉直 | `length.py` 真实 UV 开链 + 世界变换下的网格边长，直接写中间点 | 两端每个角点精确保留、多线/岛/物体、非均匀缩放、UV 接缝两侧、精细同步与回退、原生 Undo/Redo 和失败回滚 |
| 公共层仔细处理两版 UV 同步 API，自带测试 | `mesh_uv.py`、`uv_state.py`，能力检测与层级恢复顺序 | 同步开关、5.2 有效/失效状态、点/边/面/岛、多物体、pin/seam、其他 UV 层、失败回滚与 Undo/Redo |

堆叠保持精确对应。此前尝试的微量偏移已按用户纠正撤回，不作为当前实现的一部分。
共享网格边的镜像岛完全重合后，堆叠/取消堆叠按共享边的 UV 面朝向分片，
可恢复被原生 Ctrl+L 连选并被普通 UV 连续性检测合并的重叠岛。
真实两版测试覆盖原生 Ctrl+L → 重复拓扑堆叠 → 三种取消堆叠排列，同步开关均通过。
原生连选行为未替换；正常连续岛、整体镜像岛及反向网格面不会因此误拆。
线展开的闭环/分叉不强行压直，同岛多条不相交开链可同时处理。
自动直化默认摆正到最近 U/V 轴，保留镜像朝向；“保留线方向”可明确选择。
三角斜线网无法全部吸轴时先联合直化，再将主行列框架整体摆正，不压塌斜线。
不可兼容或不收敛的线网不写入。新调用不沿用旧版本 KEEP 方向缓存。
直化岛默认四边形优先；规则四边形行列直接写回，无展开器后处理，不受近直线
检测阈值限制。其他拓扑或仅边界直化仍使用阈值路径；结果报告分别列出两类岛数。
完整岛展开会检查隐藏/未完整显示的范围；日常象限翻转按编辑器可见岛处理。

## 验证结果

| 测试 | 4.5.8 | 5.2.0 |
| --- | --- | --- |
| 纯算法：`test_uv_math.py`、`test_uv_topology.py`、`test_uv_chains.py`、`test_uv_unstack.py`、`test_uv_length.py`、`test_uv_overlap.py`、`test_uv_quad.py` | Python 3.11：84 通过 | Python 3.13：84 通过 |
| `test_blender_uv_topology_stack.py` | 26 通过，1 项新版选择测试跳过 | 27 通过 |
| `test_blender_uv_transform.py` | 26 通过，1 项新版选择测试跳过 | 27 通过 |
| `test_blender_uv_straighten.py` | 41 通过 | 41 通过 |
| `test_blender_pies.py` | 10 通过 | 10 通过 |
| `test_blender_uv_unstack.py` | 21 通过 | 21 通过 |
| `test_blender_uv_cursor_pie.py` | 8 通过，1 项新版选择测试跳过 | 9 通过 |
| `test_blender_uv_seams.py` | 16 通过 | 16 通过 |
| `test_blender_uv_length.py` | 13 通过，2 项新版选择测试跳过 | 15 通过 |

每版有 166 项原生集成测试；4.5 的五项跳过仅针对它不具备的 5.x 精细 UV 同步状态。
测试的 `injected ... failure` 报告来自故意注入失败，以验证坐标/用户状态回滚。

复现命令：

```powershell
& 'D:\Blender\blender-4.5.8-windows-x64\4.5\python\bin\python.exe' -m unittest discover -s tests -p 'test_uv_*.py'
& 'D:\Blender\blender-5.2.0-windows-x64\5.2\python\bin\python.exe' -m unittest discover -s tests -p 'test_uv_*.py'

& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/test_blender_uv_topology_stack.py
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/test_blender_uv_transform.py
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/test_blender_uv_straighten.py
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/test_blender_pies.py
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/test_blender_uv_unstack.py
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/test_blender_uv_cursor_pie.py
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/test_blender_uv_seams.py
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/test_blender_uv_length.py
```

5.2 的集成测试使用同样命令，将 Blender 可执行文件路径换为
`D:\Blender\blender-5.2.0-windows-x64\blender.exe`。

插件重新加载后，新操作符通过 UV 编辑器右键 → HoTools 或 F3 使用；参数在 F9 中调整。
具体用法分别见 `TOPOLOGY_STACK.md`、`UV_UNSTACK.md`、`UV_TRANSFORM.md`、`UV_STRAIGHTEN.md`。
活动 UV 边界标记 seam 的入口与范围见 `UV_SEAMS.md`。
固定端点的 3D 比例长度均化见 `UV_LENGTH.md`。
