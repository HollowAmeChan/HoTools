"""Physics World 的 XPBD 解算器家族。"""

from __future__ import annotations

from importlib import import_module


_LAZY_EXPORTS = {
    "split_xpbd_tasks": ".family_solver",
    "step_xpbd_tasks": ".family_solver",
    "MeshXpbdColliderFrame": ".colliders",
    "build_mesh_xpbd_collider_frame": ".colliders",
    "require_xpbd_native_module": ".native",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = list(_LAZY_EXPORTS)
