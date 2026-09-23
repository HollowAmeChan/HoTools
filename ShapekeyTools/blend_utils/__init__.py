"""形态键混合矩阵的内部工具包。

按用途拆开，主文件只负责“编排”：

- :mod:`~HoTools.ShapekeyTools.blend_utils.blend_space_math`：纯数学（无 ``bpy``，
  可被 Blender 之外的单元测试直接导入）——Delaunay 剖分、混合权重、坐标映射；
- :mod:`~HoTools.ShapekeyTools.blend_utils.blend_func`：功能工具——权重求值缓存、
  形态键读写、坐标点/物体取值、权重写入报告；
- :mod:`~HoTools.ShapekeyTools.blend_utils.draw_func`：绘制工具——GPU 图元、
  文字、颜色插值。

这里不做 ``from .x import *`` 之类的聚合导入：``blend_func`` / ``draw_func`` 会拉进
``bpy``，而 ``blend_space_math`` 要保持零依赖，避免纯 Python 测试被牵连。
"""

__all__ = ()
