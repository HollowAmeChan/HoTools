"""physicsWorld.rigid - Rigid/Jolt 领域包。"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "JOLT_STEP_WRITER_ID": ".names",
    "RIGID_BACKEND_RESOURCE_KEY": ".names",
    "RIGID_BODY_COMMANDS_CHANNEL": ".names",
    "RIGID_BODY_REGISTER_WRITER_ID": ".names",
    "RIGID_BODY_SLOT_KIND": ".names",
    "RIGID_CONSTRAINT_REGISTER_WRITER_ID": ".names",
    "RIGID_CONSTRAINT_SLOT_KIND": ".names",
    "RIGID_DEBUG_DRAW_MODE": ".names",
    "RIGID_GENERATED_CONSTRAINT_OBJECT_TAG": ".names",
    "RIGID_JOLT_WORLD_SETTING_OBJECT_TAG": ".names",
    "RIGID_MATERIAL_PRESET_OBJECT_TAG": ".names",
    "RIGID_RAGDOLL_PROXY_OBJECT_TAG": ".names",
    "RIGID_SOLVER_ID": ".names",
    "RIGID_SOLVER_STATS_CHANNEL": ".names",
    "RIGID_TRANSFORM_CHANNEL": ".names",
    "RIGID_BODY_CAPABILITY": ".capabilities",
    "RIGID_BODY_CAPABILITY_ID": ".capabilities",
    "RIGID_BODY_COMMAND_CAPABILITY": ".capabilities",
    "RIGID_BODY_COMMAND_CAPABILITY_ID": ".capabilities",
    "RIGID_CAPABILITIES": ".capabilities",
    "RIGID_CONSTRAINT_CAPABILITY": ".capabilities",
    "RIGID_CONSTRAINT_CAPABILITY_ID": ".capabilities",
    "RIGID_JOLT_WORLD_SETTING_CAPABILITY": ".capabilities",
    "RIGID_JOLT_WORLD_SETTING_CAPABILITY_ID": ".capabilities",
    "RIGID_UPDATE_FREQUENCY_TABLE": ".capabilities",
    "RIGID_JOLT_CAPABILITY_BACKLOG": ".declaration",
    "RIGID_SOLVER_DECLARATION": ".declaration",
    "RIGID_DEBUG_DRAW_MODES": ".debug",
    "install_rigid_slot_debug_snapshot": ".debug",
    "rigid_backend_debug_snapshot": ".debug",
    "rigid_debug_summary_for_world": ".debug",
    "rigid_slot_debug_snapshot": ".debug",
    "rigid_declaration_debug_dict": ".declaration",
    "RigidBodySpec": ".specs",
    "ConstraintSpec": ".specs",
    "build_rigid_body_spec": ".specs",
    "build_constraint_spec": ".specs",
    "register_rigid_bodies": ".solver",
    "register_constraints": ".solver",
    "collect_rigid_specs_from_scope": ".scope_sync",
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
