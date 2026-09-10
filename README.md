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

## 版本与更新

插件根目录的 `version_info.json` 是独立于 Blender `bl_info` 的版本元数据，发布 ZIP 会在 GitHub Actions 中自动写入时间戳版本、发布标签和提交号。安装插件后，在 Blender 的插件偏好设置中可以查看当前版本，点击“检查 HoTools 更新”获取 GitHub 最新发布版；确认后会自动下载当前 Blender Python ABI 对应的 ZIP、卸载旧版本、安装新版本并重启 Blender。重启前请先保存未保存的文件。

## 开发者文档

根 README 主要面向用户。开发、架构和 native 构建细节请看：

- `OmniNode/ARCHITECTURE.md`
- `_native/README.md`
- `.releaseignore`
- `tools/build_release_zip.py`
- `.github/workflows/release.yml`
