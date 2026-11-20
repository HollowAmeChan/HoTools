# Humanoid 映射与 T-Pose

`*_humanoid.json` 的 `version: "2.0"` 同时保存映射和 Blender 的 T-Pose 标定。
仍由已有的 Humanoid 导出、导入步骤处理，不新增文件或开关。

每个 `armatures[]` 保留原有 `armatureName/bones`。已保存标定时追加 `tPose`：

- `space: "BONE_REST_LOCAL"`：变换相对于最终 FBX 的静置骨骼局部矩阵。
- `fbxBoneAxes: "Y_X"`、`rotationRepresentation: "quaternion-xyzw"`。
- `bones[]` 包含完整参考骨架，每项为 `boneName/parentName/restPosition/position/rotation/scale`。

令静置的父骨局部矩阵为 `R`、参考姿态的父骨局部矩阵为 `P`，导出的 TRS 为
`D = inverse(R) * P`。`restPosition` 为 `R` 的平移，用于导入端匹配 FBX 单位缩放。
HoFBX Y_X 转 Unity 时，D 的位置镜像 X，四元数镜像 Y/Z；Unity 再以 FBX 原始静置变换
组合 D，写入 `HumanDescription.skeleton`，同时应用原有 Humanoid 映射并重建 Avatar。
原网格 bindposes、模型静置姿态和修型键零姿态均不参与修改。

标定来源固定为各骨骼已保存的 `humanoidTPoseMatrixBasis`，不读取当前动画帧，
也不重新运行自动 T-Pose。导出器在预处理前捕获标定，在应用姿态、MCH、叶骨和物体变换
处理后重新换算到实际导出骨架；新叶骨继承父骨的参考变换。

没有标定时只导出映射；已有部分标定但映射骨缺失时中止导出，提示重新保存完整标定。
导入端在骨名、父级、变换格式或 Avatar 无效时明确报错；不会用自动 T-Pose 覆盖作者标定。
重复导入始终基于 FBX 模型原始静置数据计算，避免累积旋转。

Blender 回归：`tests/test_blender_humanoid_tpose.py`。
跨引擎坐标和实际角色回归：HoUnityTools 的 `Tests~/HoBsCorrective/README.md`。
