# 人型调试动画库

此文件夹随 `HumanoidDebug` 模块提供，内置 44 条从用户提供的
`VRMA动画.zip` 解压的 Unity Humanoid `.anim` 动画，保留原始文件内容。

添加动作时，将 Unity Humanoid `.anim` 文件放入此文件夹，然后点击
人型动画调试面板中动作下拉框旁的“刷新动画”按钮。支持子文件夹，
同名文件可以分放在不同子文件夹中；文件名或路径不同即可分别选用。
“打开动画文件夹”按钮可直接定位到这里。

仅扫描 `.anim` 文件，扩展名不区分大小写。无需提供 `.meta`、
Animator Controller 或 ZIP，也无需设置素材路径。
当前解析器读取 Unity 文本格式 AnimationClip 中的 Humanoid 肌肉曲线。

## 源码仓库

此目录下的 `.anim` 由 Git LFS 跟踪。安装 Git LFS 后正常克隆或拉取即可；
已有源码检出可执行 `git lfs install --local`、`git lfs pull` 下载完整动画。
新增动画正常 `git add`、`git commit`，文件内容会自动进入 LFS。

GitHub 自动发布会下载并缓存动画，安装 ZIP 内仍是完整的 `.anim` 文件。
使用发布的安装包无需安装 Git LFS。
