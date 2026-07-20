# OmniNode Core Tests

This directory owns cross-cutting OmniNode tests for compilation, execution,
runtime state, registration contracts, and timing. Runtime modules must not
contain adjacent `test_*.py` files.

Domain-specific tests stay with their owner, for example:

- `NodeTree/Function/physicsWorld/test/`
- `NodeTree/Function/physicsWorld/rigid/test/`
- `NodeTree/Function/physicsWorld/spring_vrm/test/`

Run the core suite with Blender's Python environment:

```powershell
blender --background --factory-startup --python OmniNode/tests/test_runtime_timing.py
blender --background --factory-startup --python OmniNode/tests/test_blender_compile_cache_lifecycle.py
blender --background --factory-startup --python OmniNode/tests/test_blender_mute_passthrough_contract.py
```

Tests must derive repository paths from `__file__`; machine-specific absolute
paths are not allowed.
