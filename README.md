# HoTools

HoTools 是一组面向 Blender 角色、模型、贴图、动画和自动化流程的工具集合。插件按模块组织，常用工具会出现在 3D 视图侧栏 `HoTools`、右键菜单、属性面板或 OmniNode 节点图里。

反馈 QQ 群：`1017402879`。进群问题请填写自己的 B 站昵称，问题和建议尽量在群里集中反馈。

作者 B 站：空洞hollow

```text
https://space.bilibili.com/60340452
```

在线文档：

```text
https://hollowamechan.github.io/HotoolsDoc-Quartz/
```

文档不定期更新，最新功能通常会先在群内快速演示。

## Linux x86_64 支持状态

当前 Linux 目标为 Blender 4.5（Python 3.11）和 Blender 5.2
（Python 3.13）。阶段 1 已提供插件注册与纯 Python 工具兼容层；阶段 2 已
提供可复现的 Pillow、cffi、pycparser、pypinyin 与 OIDN Linux 依赖组装流程。

生成目录不提交到 Git。使用与目标 Blender ABI 匹配的 Python 执行：

```bash
python3.11 tools/assemble_linux_python_deps.py \
  --abi py311 --python /path/to/python3.11
/path/to/blender-5.2/python/bin/python3.13 \
  tools/assemble_linux_python_deps.py \
  --abi py313 --python /path/to/blender-5.2/python/bin/python3.13
```

输出分别位于 `_Lib/py311/linux-x86_64` 和
`_Lib/py313/linux-x86_64`。阶段 3 的原生构建命令见 `_native/README.md`，
可生成 `hotools_native`、`hotools_jolt` 与 `hotools_boolean` 的 ABI 专用 Linux
`.so`。OIDN CPU 设备已随 `pyoidn` 提供。暂不支持 Linux ARM64。

直接生成 Linux 安装包（不下载或启动 Blender）：

```bash
python tools/build_release_zip.py --abi py311 --platform linux-x86_64 \
  --output _dist/HoTools-Blender-4.5-Linux-x86_64.zip
python tools/build_release_zip.py --abi py313 --platform linux-x86_64 \
  --output _dist/HoTools-Blender-5.2-Linux-x86_64.zip
```

发布前必须用本机已有的目标 Blender 验收安装包。命令会使用临时 Blender 用户
目录，不修改日常配置，也不会下载 Blender：

```bash
python tools/verify_blender_release.py /path/to/blender \
  _dist/HoTools-Blender-4.5-Linux-x86_64.zip py311
python tools/verify_blender_release.py /path/to/blender \
  _dist/HoTools-Blender-5.2-Linux-x86_64.zip py313
```

本机装有目标 Blender 时，可执行注册验收：

```bash
blender --background --factory-startup --python tests/test_blender_module_split.py
```

## 开发者文档

根 README 主要面向用户。开发、架构和 native 构建细节请看：

- `OmniNode/ARCHITECTURE.md`
- `_native/README.md`
- `.releaseignore`
- `tools/build_release_zip.py`
- `.github/workflows/release.yml`
