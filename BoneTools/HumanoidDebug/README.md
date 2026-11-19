# 人型动画调试

动画库位于本模块的 `animations/`，直接读取其中的 Unity 文本格式
Humanoid `.anim`。添加文件或子文件夹后点击刷新即可。

主插件安装包不含官方动画。进入 Blender 偏好设置 → 插件 → HoTools，
在“人型调试动画（可选）”中点击“下载动画包”；也可安装从同一 GitHub
Release 下载的 `HoTools-Humanoid-Animations-<版本>.zip`。
动画解压到本模块的 `animations/VRM/`，完成后自动刷新，播放时直接读取
`.anim`，不访问网络或 ZIP。下载、解压和移除在后台进行，可以取消。
移除只处理官方包记录的原始动画，用户添加或修改过的文件会保留。
自己的动画建议放到 `animations/` 的其他位置。

播放使用已保存的 T-Pose 标定。肌肉值按 Unity 默认的非对称角度范围，
经摆动与扭转组合转换为骨骼姿态；肘、膝的伸直基准、手指的张开基准、
上下肢之间的扭转分配和左右手坐标转换分别处理。缺失的 UpperChest
曲线合并到 Chest，缺失 Chest 时合并到 Spine。

RootQ 表示肩、髋共同定义的身体朝向；RootT 使用身体质量中心和归一化
高度，不能直接作为 Hips 的增量位移。质量中心使用通用人体分段权重。
Avatar 自定义肌肉限位和 Animator 的目标 IK 求解尚未接入。

预览暂时停用目标骨架的 Action、NLA、驱动和姿态约束，并临时切换到
姿态显示。停止、切换动作、保存、打开文件或撤销时恢复原姿态、输入、
显示模式、场景帧率和时间轴。播放期间不创建 Action 或关键帧。
帧更新及恢复处理器在打开 `.blend` 后继续有效。

实现以本机 Unity 2022.3 的 HumanTrait / HumanPoseHandler 作独立数值
对照；插件运行时只依赖 Blender。回归测试：

- `tests/test_blender_humanoid_muscles.py`：带父子关系和不同骨骼滚转的
  骨架、标准 Unity 映射、肘膝基准、多轴组合、坐标转换和可选躯干骨。
- `tests/test_blender_humanoid_debug.py`：文件库、播放控制、帧数设置、
  状态恢复，以及重新打开工程后的帧更新。
- `tests/test_humanoid_animation_pack.py`：独立包、下载校验、路径检查、
  安装失败回滚、自定义动画保护和移除。
- `tests/test_blender_humanoid_animation_pack.py`：按钮注册、后台任务、
  进度、取消、安装完成后自动刷新和失败提示。

上述测试在 Blender 的后台模式运行。用户工程的测试与渲染也在独立
后台进程进行，不向工程文件保存预览结果。
