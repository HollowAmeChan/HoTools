"""粘贴形态键的尽力匹配支线。

拓扑不一致时（删了点、合并了物体……）粘贴不再直接放弃，而是尽量把位移对上。
按用途拆开，算子层只负责弹窗与写值：

- :mod:`~HoTools.ShapekeyTools.paste.geometry`：匹配用的无状态几何原语——基型坐标、
  按顶点平均 UV、KD-tree、包围盒、按模型原点分左右象限。这些能力原本长在
  ``transfer.ShapeKeyTransfer`` 里，抽出来给两边共用；
- :mod:`~HoTools.ShapekeyTools.paste.matcher`：``ShapekeyPasteMatch``——剪贴板协议
  （只存源物体引用，不存几何快照）、源引用校验、拓扑体检、点序/世界位置/UV 三种映射。

这里不做聚合导入：``matcher`` 会拉进 ``bpy``，而 ``geometry`` 除 ``shapekey_utils``
外没有别的前置依赖，保持各取所需。
"""

__all__ = ()
