# OmniNode 核心测试

此目录集中维护跨模块的 OmniNode 测试，包括编译、执行、运行时状态、注册合同
和计时。运行时模块旁不得放置 `test_*.py` 文件。

业务域专用测试应放在所属目录中，例如：

- `PhysicsWorld/test/`
- `PhysicsWorld/rigid/test/`
- `PhysicsWorld/spring_vrm/test/`

使用 Blender 的 Python 环境运行核心测试：

```powershell
blender --background --factory-startup --python OmniNode/tests/test_runtime_timing.py
blender --background --factory-startup --python OmniNode/tests/test_blender_package_layout.py
blender --background --factory-startup --python OmniNode/tests/test_blender_compile_cache_lifecycle.py
blender --background --factory-startup --python OmniNode/tests/test_blender_mute_passthrough_contract.py
blender --background --factory-startup --python OmniNode/tests/test_blender_reference_guard.py
blender --background --factory-startup --python OmniNode/tests/test_blender_function_registration.py
```

测试必须从 `__file__` 推导仓库路径，不得使用机器相关的绝对路径。
