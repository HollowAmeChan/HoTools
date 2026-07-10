"""统一 Physics World 的 MC2 solver domain。

MeshCloth、BoneCloth 和 BoneSpring 是同一个 MC2 solver 的三种 setup；
Python/C++ 仅是 backend 选择，不形成独立 solver。
"""

from __future__ import annotations

from importlib import import_module


SOLVER_MODULE = {
    "domain": "mc2",
    "solver_id": "mc2",
    "declaration": ".declaration:MC2_SOLVER_DECLARATION",
    "nodes": (".nodes",),
    "capabilities": ".capabilities:MC2_CAPABILITIES",
    "debug_draw_modes": ".debug:MC2_DEBUG_DRAW_MODES",
    "property_dependencies": ("collision", "mesh_cloth"),
}


_EXPORTS = {
    "MC2_BACKEND_AUTO": ".names",
    "MC2_BACKEND_CPP": ".names",
    "MC2_BACKEND_PYTHON": ".names",
    "MC2_BONE_RESULT_CHANNEL": ".names",
    "MC2_DEBUG_DRAW_MODE": ".names",
    "MC2_MESH_RESULT_CHANNEL": ".names",
    "MC2_SETUP_BONE_CLOTH": ".names",
    "MC2_SETUP_BONE_SPRING": ".names",
    "MC2_SETUP_MESH_CLOTH": ".names",
    "MC2_SETUP_TYPES": ".names",
    "MC2_SLOT_KIND": ".names",
    "MC2_SOLVER_ID": ".names",
    "MC2_STATS_CHANNEL": ".names",
    "MC2_CAPABILITIES": ".capabilities",
    "MC2_SETUP_PROFILE_CAPABILITY": ".capabilities",
    "MC2_SETUP_PROFILE_CAPABILITY_ID": ".capabilities",
    "MC2_UPDATE_FREQUENCY_TABLE": ".capabilities",
    "MC2_SOLVER_DECLARATION": ".declaration",
    "MC2_DEBUG_DRAW_MODES": ".debug",
    "MC2TaskSpec": ".specs",
    "build_mc2_task_specs": ".specs",
    "make_mc2_task_spec": ".specs",
    "normalize_mc2_backend": ".specs",
    "normalize_mc2_setup_type": ".specs",
    "MC2_FRAMEWORK_STATUS": ".solver",
    "step_mc2": ".solver",
    "iter_mc2_results": ".results",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = sorted(_EXPORTS)
