# UV 功能交付与验证

验证日期：2026-10-13；2026-10-14 补充象限适配修复及取消堆叠验证。
实际版本：Blender 4.5.8 LTS（d7359176d0d3）与 5.2.0 LTS（fbe6228777e7）。
测试使用独立 `--background --factory-startup` 进程，不修改用户当前场景或偏好。

## 功能与证据

| 用户要求 | 当前实现 | 直接验证 |
| --- | --- | --- |
| 镜像所选 UV，支持 X/Y，独立于内置变换轴心 | `transform.py` 镜像操作符，`uv_math.py` 直接反射坐标 | 两次镜像复原、各编辑器 pivot、UV 光标/自定义中心、U/V、多物体、同步开关 |
| 平移所选 UV，方向与距离 | ±U/±V，UV/像素距离 | 往返、四方向、非正方形图像、缺图取消、状态与其他层不变 |
| 沿轴对齐与 Alt+A 失效修复 | 公共对齐函数；`ho.align_uv` 保留，右键有独立入口 | 多物体、平均值按独立 UV 点、隐藏点、5.2 精细选择、光标轴向、原生快捷键注册 |
| 线展开，支持兼容多内部线，避免受切向影响倒置 | 真实选中边 → 多开链 → UV 框架/区域锚点 → 原生展开 | 同岛多内部线、镜像/旋转、两种展开方法、U/V/保留方向、三角/混合/五边形/带洞岛 |
| 直化岛，阈值可控 | 局部转角与全链偏差筛选，边界/内部线，共享交点联合拟合 | 圆弧排除、阈值与尺度、三角网格行列斜线同时直化、边界-only、保留方向/轴向 |
| 单模式拓扑堆叠，强制顶点对齐，考虑镜像 | 图双射后复制所有主岛点，内部点偏差不阻止修正 | 非对称镜像、重新编号、内部点强修、孔洞、错拓扑排除、主岛、多分组、共享 mesh |
| 紧急：本象限中线翻转到另一半 | 每个可见岛按其整数 UV 象限中线反射 | 第一象限、其他 UDIM、负象限、U/V、部分网格面选择可用、未显示 UV 不变 |
| 象限适配支持同步，按 AABB 中心居中后尽量填满 | 公共选区读取 + AABB 居中等比适配，默认第一象限 | 两版选择模式、长方形短边留白对称、多物体整体 AABB、未显示点保护、单点/直线、边距与 Undo/Redo |
| 取消堆叠，横向/纵向/跨象限排列 | 可见岛 AABB 间距排列；跨象限保留首岛，其余统一 +1U | 模式/同步/选择组合、不同 AABB 尺寸、首岛、+1U 后其他岛保持重叠、实际角点精确平移、回滚与 Undo/Redo |
| UV 独立 Shift+S 游标饼 | `HO_MT_uv_cursor_pie` 与独立 UV Editor 键位，共享原游标饼开关 | 八槽 UV-only、原生吸附、同步开关、二维游标与 3D 游标隔离、开关清理及原 3D 饼回归 |
| 公共层仔细处理两版 UV 同步 API，自带测试 | `mesh_uv.py`、`uv_state.py`，能力检测与层级恢复顺序 | 同步开关、5.2 有效/失效状态、点/边/面/岛、多物体、pin/seam、其他 UV 层、失败回滚与 Undo/Redo |

堆叠保持精确对应。此前尝试的微量偏移已按用户纠正撤回，不作为当前实现的一部分。
线展开的闭环/分叉不强行压直，同岛多条不相交开链可同时处理。
自动直化默认保留方向，轴向吸附作为明确参数；不可兼容或不收敛的线网不写入。
完整岛展开会检查隐藏/未完整显示的范围；日常象限翻转按编辑器可见岛处理。

## 验证结果

| 测试 | 4.5.8 | 5.2.0 |
| --- | --- | --- |
| 纯算法：`test_uv_math.py`、`test_uv_topology.py`、`test_uv_chains.py`、`test_uv_unstack.py` | Python 3.11：50 通过 | Python 3.13：50 通过 |
| `test_blender_uv_topology_stack.py` | 18 通过，1 项新版选择测试跳过 | 19 通过 |
| `test_blender_uv_transform.py` | 26 通过，1 项新版选择测试跳过 | 27 通过 |
| `test_blender_uv_straighten.py` | 18 通过 | 18 通过 |
| `test_blender_pies.py` | 10 通过 | 10 通过 |
| `test_blender_uv_unstack.py` | 11 通过 | 11 通过 |
| `test_blender_uv_cursor_pie.py` | 8 通过，1 项新版选择测试跳过 | 9 通过 |

每版有 94 项原生集成测试；4.5 的三项跳过仅针对它不具备的 5.x 精细 UV 同步状态。
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
```

5.2 的集成测试使用同样命令，将 Blender 可执行文件路径换为
`D:\Blender\blender-5.2.0-windows-x64\blender.exe`。

插件重新加载后，新操作符通过 UV 编辑器右键 → HoTools 或 F3 使用；参数在 F9 中调整。
具体用法分别见 `TOPOLOGY_STACK.md`、`UV_UNSTACK.md`、`UV_TRANSFORM.md`、`UV_STRAIGHTEN.md`。
