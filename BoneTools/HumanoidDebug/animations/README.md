# 人型调试动画库

此文件夹是 `HumanoidDebug` 模块的动画库。`VRM/` 保存 44 条从用户提供的
`VRMA动画.zip` 解压的 Unity Humanoid `.anim`，保留原始文件内容。
发布时这些文件会单独打成可选动画 ZIP，主插件安装包不携带动画。
用户可在 HoTools 插件偏好设置中下载并自动解压，也可从本地 ZIP 安装。

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

GitHub 自动发布会下载并缓存动画源文件，生成两套主插件 ZIP 和一套通用的
`HoTools-Humanoid-Animations-<版本>.zip`。后者包含动画清单及 SHA256 校验，
插件完成下载和校验后解压到 `VRM/`。使用发布包无需安装 Git LFS。
