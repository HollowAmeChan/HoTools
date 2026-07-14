"""统一 Physics World 的 MC2 solver domain。

MeshCloth、BoneCloth 和 BoneSpring 是同一个 MC2 solver 的三种 setup；
新路径只面向一个共享 native context，不公开 backend 选择。
"""

from __future__ import annotations

from importlib import import_module


COMPONENT_MODULE = {
    "component_id": "mc2",
    "kind": "solver_adapter",
    "depends_on": ("collision",),
    "capabilities": ".setups.mesh_cloth.capabilities:MESH_CLOTH_CAPABILITIES",
    "blender_properties": ".setups.mesh_cloth.properties:MESH_CLOTH_BLENDER_PROPERTIES",
}


SOLVER_MODULE = {
    "domain": "mc2",
    "solver_id": "mc2",
    "declaration": ".declaration:MC2_SOLVER_DECLARATION",
    "nodes": (".nodes",),
    "capabilities": ".capabilities:MC2_CAPABILITIES",
    "debug_draw_modes": ".debug:MC2_DEBUG_DRAW_MODES",
}


_EXPORTS = {
    "MC2_DEBUG_DRAW_MODE": ".names",
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
    "MESH_COLLISION_CAPABILITY": ".setups.mesh_cloth.capabilities",
    "MESH_COLLISION_CAPABILITY_ID": ".setups.mesh_cloth.capabilities",
    "MESH_CLOTH_CAPABILITIES": ".setups.mesh_cloth.capabilities",
    "MESH_COLLISION_RNA_FIELDS": ".setups.mesh_cloth.schema",
    "MESH_CLOTH_BLENDER_PROPERTIES": ".setups.mesh_cloth.properties",
    "PG_Hotools_MeshCollision": ".setups.mesh_cloth.properties",
    "MC2_SOLVER_DECLARATION": ".declaration",
    "MC2_DEBUG_DRAW_MODES": ".debug",
    "MC2TaskSpec": ".specs",
    "build_mc2_task_specs": ".specs",
    "make_mc2_task_spec": ".specs",
    "normalize_mc2_setup_type": ".specs",
    "MC2CurveSpec": ".parameters",
    "MC2EffectiveParametersSpec": ".parameters",
    "MC2ParticleProfileSpec": ".parameters",
    "MC2SetupOptionsSpec": ".parameters",
    "MC2SolverSettingsSpec": ".parameters",
    "make_mc2_curve_spec": ".parameters",
    "make_mc2_effective_parameters": ".parameters",
    "make_mc2_particle_profile": ".parameters",
    "make_mc2_setup_options": ".parameters",
    "make_mc2_solver_settings": ".parameters",
    "MC2RuntimeParametersV0": ".runtime_parameters",
    "make_mc2_runtime_parameters": ".runtime_parameters",
    "pack_mc2_runtime_parameters": ".runtime_parameters",
    "sample_mc2_curve16": ".runtime_parameters",
    "MC2FrameInputSpec": ".frame_state",
    "MC2FrameSyncResult": ".frame_state",
    "make_mc2_frame_input": ".frame_state",
    "plan_mc2_frame_sync": ".frame_state",
    "sync_mc2_frame_input": ".frame_state",
    "MC2FrameSchedule": ".scheduler",
    "MC2TimeSchedulerState": ".scheduler",
    "build_mc2_bone_frame_input": ".setups.bone_frame_input",
    "build_mc2_mesh_frame_input_for_task": ".setups.mesh_cloth.frame_input",
    "MC2CenterFramePoseSpec": ".center_state",
    "MC2CenterFrameShiftInputSpec": ".center_state",
    "MC2CenterFrameShiftResult": ".center_state",
    "MC2CenterPersistentState": ".center_state",
    "MC2CenterStaticSpec": ".center_state",
    "build_mc2_center_static": ".center_state",
    "evaluate_mc2_center_frame_shift": ".center_state",
    "pack_mc2_center_static": ".center_state",
    "MC2NativeContextV0": ".native",
    "MC2BoneConnectionSpec": ".bone_connection",
    "build_mc2_bone_connection": ".bone_connection",
    "MC2BoneLineRotationResult": ".bone_rotation",
    "evaluate_mc2_bone_line_rotation": ".bone_rotation",
    "MC2SourceTopologySpec": ".topology",
    "MC2TopologySpec": ".topology",
    "build_mc2_topology_spec": ".topology",
    "MC2SlotRuntimeState": ".state",
    "MC2ParticleBuffer": ".state",
    "MC2BendingStaticSpec": ".bending_static",
    "build_mc2_bending_static": ".bending_static",
    "make_mc2_bending_static_spec": ".bending_static",
    "pack_mc2_bending_static": ".bending_static",
    "MC2DistanceStaticSpec": ".distance_static",
    "build_mc2_distance_static": ".distance_static",
    "make_mc2_distance_static_spec": ".distance_static",
    "pack_mc2_distance_static": ".distance_static",
    "MC2InitialStateSpec": ".initial_state",
    "build_mc2_bone_initial_state": ".initial_state",
    "build_mc2_initial_state": ".initial_state",
    "build_mc2_mesh_initial_state": ".initial_state",
    "MC2SetupAdapterContract": ".setups.contracts",
    "MC2_BONE_CLOTH_SETUP_ADAPTER": ".setups",
    "MC2_BONE_SPRING_SETUP_ADAPTER": ".setups",
    "MC2_MESH_CLOTH_SETUP_ADAPTER": ".setups",
    "MC2_SETUP_ADAPTERS": ".setups",
    "all_mc2_setup_adapters": ".setups",
    "get_mc2_setup_adapter": ".setups",
    "MC2_FRAMEWORK_STATUS": ".solver",
    "step_mc2": ".solver",
    "MC2_PUBLIC_RESULT_SCHEMA_VERSION": ".results",
    "iter_mc2_results": ".results",
    "make_mc2_mesh_result": ".results",
    "publish_mc2_result_transaction": ".results",
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
