# 自动 T-Pose 与 Unity 对齐

`boneTPose.py` 的自动按钮使用 `humanoid_tpose_solver.py`，基于 Humanoid 映射校正全身、手掌和全部手指。生成结果仍进入临时预览，可微调后保存；已有标定不会被自动覆盖。预览临时暂停动画、驱动和约束，切换到 POSE 显示；结束后恢复输入、姿态和原显示模式。

算法以 Unity `AvatarSetupTool.MakePoseValid` 的行为为目标：

- 全身按 Humanoid 顺序处理，骨盆调整后重算身体朝向；躯干、腿、脚、手臂各自拥有方向与容差。
- 上臂/前臂允许 5° 偏差。超差时旋转比例为 `clamp01(1.05 - tolerance / angle)`，保留与 Unity 相同的容差残余。
- 用映射子关节的位置判断方向，手掌优先使用中指近节。比较平面、父关节实际方向与 Unity 一致。
- 四指指向手外侧，拇指向外且向前。近节容差 10°，中节和远节 5°，逐节计算父方向参考空间。
- 小角度四元数调整在 dot≥0.95 时使用归一化线性插值，其他角度使用球面插值，与实测 Unity 原生分支一致。
- 修正大腿/小腿时保持脚的原世界旋转；最后按腿长和脚/趾位置校正骨盆居中及高度。
- 末端没有子骨时使用 Blender 显式骨尾，与 HoFBX 叶骨一致；存在多个实际子骨且没有有效映射子关节时跳过方向猜测。

`validate()` 返回逐骨超差、骨盆位置误差及总误差。自动生成后仍有超差时在操作报告中提示骨骼，用户可手动微调。一次校正的误差结果与 Unity 一样受骨架结构影响，不通过反复校正强制凑成零。

坐标使用 HoFBX 世界映射 `(-x, z, -y)`；支持旋转、位移和统一缩放的骨架。没有腿等映射时使用与 Unity 相同的身份身体朝向。关节方向只由映射和父子结构决定，不依赖 Blender 骨滚转。

验证：

- `tests/test_blender_humanoid_tpose.py`：预览恢复、REST 显示恢复、标定保存、元数据和静置重设。
- HoUnityTools `Tests~/HoBsCorrective/run_auto_tpose_validation.ps1`：三组独立全身/弯指骨架对比安装的 Unity 编辑器实际求解器，覆盖旋转物体、骨滚转、辅助中间骨和缺失映射。
- 羽啾 53 映射实测：最大局部旋转差约 0.000253°，Unity 最终方向校验误差为 0。原模型和原工程不写入测试结果。

参考行为：[Unity 官方源码](https://github.com/Unity-Technologies/UnityCsReference/blob/9d487cab41b00c50af020b56d27a3c768d54f770/Editor/Mono/Inspector/Avatar/AvatarSetupTool.cs#L1085)。Unity 自动 T-Pose 是容差校正，不是唯一标准姿态；导出与导入仍忠实使用用户最终保存的 T-Pose。
