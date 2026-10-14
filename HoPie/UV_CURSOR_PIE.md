# UV 专用 Shift+S 游标饼

重新加载插件后，启用现有游标饼开关，在 UV 网格编辑模式按 **Shift+S**。
UV 编辑器使用 `HO_MT_uv_cursor_pie`，3D 视图继续使用原 `HO_MT_cursor_pie`。

| 槽位 | 功能 |
| --- | --- |
| 左 | UV 游标到选中 UV |
| 右 | 选中 UV 到 UV 游标 |
| 下 | 直接编辑 UV 游标二维坐标 |
| 上 | 选中 UV 吸附像素 |
| 左上 | UV 游标归零到 `(0, 0)` |
| 右上 | 选中 UV 整体偏移到游标，保持相对形状 |
| 左下 | 选中 UV 吸附到相邻未选 UV |
| 右下 | UV 游标吸附像素 |

采用 Blender 原生 `uv.snap_cursor` / `uv.snap_selected`，操作 UV 编辑器的
二维游标，不修改 3D 游标。支持两版 UV 同步与非同步选择。
像素吸附使用当前图像；可在底部坐标区直接输入 UV 游标位置。

两个上下文沿用同一个游标饼开关。启用时分别注册 3D 与 UV 的 Shift+S；禁用
时清理两处绑定，不替换其他模式的菜单内容。

测试：`tests/test_blender_uv_cursor_pie.py` 两版各 9 项（4.5 跳过一项新版精细
同步选择测试），验证键位路由、八槽布局、原生吸附与 3D 游标保护；
`tests/test_blender_pies.py` 两版各 10 项通过，验证开关清理与原 3D 行为。
