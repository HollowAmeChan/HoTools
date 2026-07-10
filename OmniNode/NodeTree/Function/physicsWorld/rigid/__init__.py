"""physicsWorld.rigid - 刚体/Jolt 领域包。"""

from __future__ import annotations

from importlib import import_module


SOLVER_MODULE = {
    "domain": "rigid",
    "solver_id": "rigid_jolt",
    "declaration": ".declaration:RIGID_SOLVER_DECLARATION",
    "nodes": (".nodes",),
    "capabilities": ".capabilities:RIGID_CAPABILITIES",
    "blender_properties": ".properties:RIGID_BLENDER_PROPERTIES",
    "property_dependencies": ("collision",),
    "debug_draw_modes": ".debug:RIGID_DEBUG_DRAW_MODES",
    "scope_restart_handlers": (
        ".scope_sync:clear_scope_dynamic_rigid_deltas",
    ),
    "scope_collectors": (
        ".scope_sync:collect_rigid_specs_from_scope",
    ),
}


_EXPORTS = {
    "JOLT_STEP_WRITER_ID": ".names",
    "RIGID_BACKEND_RESOURCE_KEY": ".names",
    "RIGID_BODY_COMMANDS_CHANNEL": ".names",
    "RIGID_BODY_REGISTER_WRITER_ID": ".names",
    "RIGID_BODY_SLOT_KIND": ".names",
    "RIGID_CONSTRAINT_REGISTER_WRITER_ID": ".names",
    "RIGID_CONSTRAINT_STATE_CHANNEL": ".names",
    "RIGID_CONTACT_EVENT_CHANNEL": ".names",
    "RIGID_CONSTRAINT_SLOT_KIND": ".names",
    "RIGID_DEBUG_DRAW_MODE": ".names",
    "RIGID_GENERATED_CONSTRAINT_OBJECT_TAG": ".names",
    "RIGID_JOLT_WORLD_SETTING_OBJECT_TAG": ".names",
    "RIGID_MATERIAL_PRESET_OBJECT_TAG": ".names",
    "RIGID_RAGDOLL_PROXY_OBJECT_TAG": ".names",
    "RIGID_SOLVER_ID": ".names",
    "RIGID_SOLVER_STATS_CHANNEL": ".names",
    "RIGID_SENSOR_EVENT_CHANNEL": ".names",
    "RIGID_QUERY_RESULT_CHANNEL": ".names",
    "RIGID_TRANSFORM_CHANNEL": ".names",
    "RIGID_QUERY_WRITER_ID": ".names",
    "RIGID_BODY_CAPABILITY": ".capabilities",
    "RIGID_BODY_CAPABILITY_ID": ".capabilities",
    "RIGID_BODY_COMMAND_CAPABILITY": ".capabilities",
    "RIGID_BODY_COMMAND_CAPABILITY_ID": ".capabilities",
    "RIGID_CAPABILITIES": ".capabilities",
    "RIGID_CONSTRAINT_CAPABILITY": ".capabilities",
    "RIGID_CONSTRAINT_CAPABILITY_ID": ".capabilities",
    "RIGID_JOLT_WORLD_SETTING_CAPABILITY": ".capabilities",
    "RIGID_JOLT_WORLD_SETTING_CAPABILITY_ID": ".capabilities",
    "RIGID_QUERY_CAPABILITY": ".capabilities",
    "RIGID_QUERY_CAPABILITY_ID": ".capabilities",
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
    "PG_Hotools_RigidBody": ".properties",
    "PG_Hotools_RigidConstraint": ".properties",
    "RIGID_BLENDER_PROPERTIES": ".properties",
    "RIGID_BODY_RNA_FIELDS": ".schema",
    "RIGID_CONSTRAINT_RNA_FIELDS": ".schema",
    "RIGID_RNA_SCHEMAS": ".schema",
    "ConstraintSpec": ".specs",
    "build_rigid_body_spec": ".specs",
    "build_constraint_spec": ".specs",
    "register_rigid_bodies": ".solver",
    "register_constraints": ".solver",
    "collect_rigid_specs_from_scope": ".scope_sync",
    "perform_rigid_ray_cast": ".queries",
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
