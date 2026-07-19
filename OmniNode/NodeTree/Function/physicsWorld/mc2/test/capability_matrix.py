"""MC2 product requirements and the Blender evidence that actually exists."""

from __future__ import annotations


ALL_SETUPS = ("mesh_cloth", "bone_cloth", "bone_spring")
CLOTH_SETUPS = ("mesh_cloth", "bone_cloth")


def capability_gaps(capability):
    evidence = tuple(capability["evidence"])
    covered_setups = set().union(*(item["setups"] for item in evidence))
    exercised_field_setups = {}
    for item in evidence:
        for field in item["fields"]:
            exercised_field_setups.setdefault(field, set()).update(item["setups"])
    field_requirements = {
        field: set(capability.get("field_setups", {}).get(
            field, capability["required_setups"]
        ))
        for field in capability["owned_fields"]
    }
    field_gaps = {
        f"{field}@{setup}"
        for field, setups in field_requirements.items()
        for setup in setups
        if setup not in exercised_field_setups.get(field, set())
    }
    verified_invariant_setups = {}
    for item in evidence:
        for invariant in item["invariants"]:
            verified_invariant_setups.setdefault(invariant, set()).update(item["setups"])
    invariant_requirements = {
        invariant: set(capability.get("invariant_setups", {}).get(
            invariant, capability["required_setups"]
        ))
        for invariant in capability["required_invariants"]
    }
    invariant_gaps = {
        f"{invariant}@{setup}"
        for invariant, setups in invariant_requirements.items()
        for setup in setups
        if setup not in verified_invariant_setups.get(invariant, set())
    }
    return {
        "setups": set(capability["required_setups"]) - covered_setups,
        "fields": field_gaps,
        "invariants": invariant_gaps,
    }


MC2_LONG_RUN_CAPABILITY_MATRIX = (
    {
        "id": "integration_and_pose_blend",
        "required_setups": ALL_SETUPS,
        "owned_fields": (
            "gravity", "gravity_direction_x", "gravity_direction_y",
            "gravity_direction_z", "gravity_falloff",
            "stabilization_time_after_reset", "blend_weight",
            "rotational_interpolation", "root_rotation", "damping",
        ),
        "field_setups": {
            "gravity": CLOTH_SETUPS,
            "gravity_direction_x": CLOTH_SETUPS,
            "gravity_direction_y": CLOTH_SETUPS,
            "gravity_direction_z": CLOTH_SETUPS,
            "gravity_falloff": CLOTH_SETUPS,
            "rotational_interpolation": ("bone_cloth", "bone_spring"),
            "root_rotation": ("bone_cloth", "bone_spring"),
        },
        "required_invariants": (
            "finite", "deterministic", "bounded_velocity", "zero_force_rest",
            "candidate_frame_progresses", "writeback_targets_present",
            "stabilization_blend_ramp_exact",
        ),
        "evidence": ({
            "runner": "test_blender_mc2_mixed_output_soak.py::main",
            "frames": 900,
            "setups": ALL_SETUPS,
            "fields": (
                "gravity", "damping", "stabilization_time_after_reset",
                "blend_weight",
            ),
            "invariants": (
                "finite", "deterministic", "candidate_frame_progresses",
                "writeback_targets_present",
                "parameter_hot_update_in_place",
                "stabilization_blend_ramp_exact",
                "bounded_velocity",
            ),
        }, {
            "runner": "test_blender_mc2_constraint_soak.py::_angle_restoration_rest_soak",
            "frames": 900,
            "setups": ("mesh_cloth",),
            "fields": (),
            "invariants": ("finite", "deterministic", "zero_force_rest"),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_angle_constraints",
            "frames": 900,
            "setups": ("bone_cloth", "bone_spring"),
            "fields": (),
            "invariants": ("finite", "deterministic", "zero_force_rest"),
        }, {
            "runner": "test_blender_mc2_constraint_soak.py::mesh_gravity_axes_falloff",
            "frames": 600,
            "setups": ("mesh_cloth",),
            "fields": (
                "gravity", "gravity_direction_x", "gravity_direction_y",
                "gravity_direction_z", "gravity_falloff", "damping",
            ),
            "invariants": ("finite", "deterministic"),
        }),
        "status": "gap",
    },
    {
        "id": "center_inertia_and_teleport",
        "required_setups": ALL_SETUPS,
        "owned_fields": (
            "anchor_inertia", "world_inertia", "movement_inertia_smoothing",
            "movement_speed_limit", "rotation_speed_limit", "local_inertia",
            "local_movement_speed_limit", "local_rotation_speed_limit",
            "depth_inertia", "particle_speed_limit", "teleport_distance",
            "teleport_rotation", "teleport_mode",
        ),
        "required_invariants": (
            "finite", "deterministic", "same_frame_stable",
            "object_keep_reset_all_setups_detected",
            "object_teleport_zero_substep_immediate",
            "object_reset_pose_exact",
            "particle_teleport_bidirectional_exact",
            "particle_keep_offset_exact",
            "particle_keep_velocity_cleared",
            "particle_reset_step_history_exact",
            "particle_reset_self_history_invalidated",
            "particle_subset_scope_exact",
            "bone_root_teleport_detected",
            "teleport_debug_layers_isolated",
            "particle_speed_limit_bounded_and_active",
            "world_translation_inertia_ordered",
            "world_movement_smoothing_active",
            "world_movement_limit_active",
            "world_rotation_limit_active",
            "center_controls_no_implicit_debug_readback",
        ),
        "invariant_setups": {
            "bone_root_teleport_detected": ("bone_cloth", "bone_spring"),
            "particle_reset_self_history_invalidated": CLOTH_SETUPS,
        },
        "evidence": (
            {
                "runner": "test_blender_mc2_mixed_output_soak.py::main",
                "frames": 900,
                "setups": ALL_SETUPS,
                "fields": (
                    "particle_speed_limit", "teleport_distance",
                    "teleport_rotation", "teleport_mode",
                ),
                "invariants": (
                    "finite", "deterministic", "same_frame_stable",
                    "object_keep_reset_all_setups_detected",
                    "object_teleport_zero_substep_immediate",
                    "object_reset_pose_exact",
                    "particle_teleport_bidirectional_exact",
                    "particle_keep_offset_exact",
                    "particle_keep_velocity_cleared",
                    "particle_reset_step_history_exact",
                    "particle_subset_scope_exact",
                    "bone_root_teleport_detected",
                    "teleport_debug_layers_isolated",
                    "particle_speed_limit_bounded_and_active",
                    "teleport_nonunit_positive_scale", "real_writeback_each_frame",
                ),
            },
            {
                "runner": "test_blender_mc2_bone_constraint_soak.py::bone_self_collision",
                "frames": 900,
                "setups": ("bone_cloth",),
                "fields": ("teleport_distance", "teleport_mode"),
                "invariants": (
                    "finite", "deterministic",
                    "particle_reset_self_history_invalidated",
                ),
            },
            {
                "runner": "test_blender_mc2_constraint_soak.py::_self_interaction_soak",
                "frames": 1800,
                "setups": ("mesh_cloth",),
                "fields": ("teleport_distance", "teleport_mode"),
                "invariants": (
                    "finite", "deterministic",
                    "particle_reset_self_history_invalidated",
                ),
            },
            {
                "runner": (
                    "test_blender_mc2_mixed_output_soak.py::"
                    "center_world_controls"
                ),
                "frames": 600,
                "setups": ALL_SETUPS,
                "fields": (
                    "world_inertia", "movement_inertia_smoothing",
                    "movement_speed_limit", "rotation_speed_limit",
                ),
                "invariants": (
                    "finite", "deterministic",
                    "world_translation_inertia_ordered",
                    "world_movement_smoothing_active",
                    "world_movement_limit_active",
                    "world_rotation_limit_active",
                    "center_controls_no_implicit_debug_readback",
                ),
            },
        ),
        "known_gap": (
            "Production now evaluates every particle animation base and supplements Mesh "
            "object motion with native component-pose history. The 900-frame product runner "
            "covers object/root events, bidirectional exact subset Keep/Reset, triggered Keep "
            "velocity clearing, StepBasic alignment and isolated debug. BoneCloth task-local "
            "and MeshCloth cross-task self histories are invalidated in the zero-substep "
            "Teleport frame and rebuild on later substeps. The remaining independent "
            "Center inertia fields retain product evidence gaps."
        ),
        "status": "gap",
    },
    {
        "id": "tether_and_distance",
        "required_setups": CLOTH_SETUPS,
        "owned_fields": (
            "tether_compression_limit", "tether_stretch_limit",
            "distance_velocity_attenuation", "distance_stiffness",
        ),
        "required_invariants": (
            "finite", "deterministic", "rest_length_bounded", "fixed_particles_static",
            "tether_range_bounded",
        ),
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_distance_tether_soak",
            "frames": 900,
            "setups": ("mesh_cloth",),
            "fields": (
                "tether_compression_limit", "tether_stretch_limit",
                "distance_velocity_attenuation", "distance_stiffness",
            ),
            "invariants": (
                "finite", "deterministic", "rest_length_bounded",
                "fixed_particles_static", "tether_range_bounded",
                "parameter_hot_update_in_place",
            ),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_distance_tether",
            "frames": 900,
            "setups": ("bone_cloth",),
            "fields": (
                "tether_compression_limit", "tether_stretch_limit",
                "distance_velocity_attenuation", "distance_stiffness",
            ),
            "invariants": (
                "finite", "deterministic", "rest_length_bounded",
                "fixed_particles_static", "tether_range_bounded",
                "parameter_hot_update_in_place",
                "connected_disconnected_writeback",
            ),
        },),
        "status": "verified",
    },
    {
        "id": "triangle_bending",
        "required_setups": CLOTH_SETUPS,
        "owned_fields": ("bending_stiffness", "bending_method"),
        "required_invariants": (
            "finite", "deterministic", "signed_volume_stable", "fixed_particles_static",
        ),
        "invariant_setups": {
            "signed_volume_stable": ("bone_cloth",),
        },
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_bending_soak",
            "frames": 900,
            "setups": ("mesh_cloth",),
            "fields": ("bending_stiffness", "bending_method"),
            "invariants": (
                "finite", "deterministic", "fixed_particles_static",
                "bending_response_changes", "solve_branch_exact",
            ),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_triangle_bending",
            "frames": 900,
            "setups": ("bone_cloth",),
            "fields": ("bending_stiffness", "bending_method"),
            "invariants": (
                "finite", "deterministic", "signed_volume_stable",
                "fixed_particles_static", "bending_response_changes",
                "connected_disconnected_writeback",
            ),
        }),
        "status": "verified",
    },
    {
        "id": "angle_restoration",
        "required_setups": ALL_SETUPS,
        "owned_fields": (
            "angle_restoration_velocity_attenuation",
            "angle_restoration_gravity_falloff", "use_angle_restoration",
            "angle_restoration_stiffness",
        ),
        "required_invariants": (
            "finite", "deterministic", "zero_force_rest", "target_direction_exact",
            "velocity_attenuation_response_ordered",
            "gravity_falloff_response_ordered",
            "center_input_reachable",
        ),
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_angle_restoration_rest_soak",
            "frames": 900,
            "setups": ("mesh_cloth",),
            "fields": ("use_angle_restoration", "angle_restoration_stiffness"),
            "invariants": (
                "finite", "deterministic", "zero_force_rest",
                "target_direction_exact", "parameter_hot_update_in_place",
            ),
        }, {
            "runner": "test_blender_mc2_constraint_soak.py::mesh_angle_restoration_response",
            "frames": 600,
            "setups": ("mesh_cloth",),
            "fields": ("angle_restoration_velocity_attenuation",),
            "invariants": ("finite", "velocity_attenuation_response_ordered"),
        }, {
            "runner": "test_blender_mc2_constraint_soak.py::mesh_angle_restoration_falloff",
            "frames": 600,
            "setups": ("mesh_cloth",),
            "fields": ("angle_restoration_gravity_falloff",),
            "invariants": ("finite", "gravity_falloff_response_ordered"),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_angle_restoration_attenuation",
            "frames": 600,
            "setups": ("bone_cloth", "bone_spring"),
            "fields": ("angle_restoration_velocity_attenuation",),
            "invariants": (
                "finite", "velocity_attenuation_response_ordered",
                "connected_disconnected_writeback",
            ),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_angle_constraints",
            "frames": 900,
            "setups": ("bone_cloth", "bone_spring"),
            "fields": ("use_angle_restoration", "angle_restoration_stiffness"),
            "invariants": (
                "finite", "deterministic", "bone_branch_transition_stable",
                "zero_force_rest", "target_direction_exact",
                "connected_disconnected_writeback",
            ),
        },),
        "known_gap": (
            "MC2 task nodes do not expose or derive a user-reachable Team Center/Anchor; "
            "manual frame-input evidence cannot close center_input_reachable."
        ),
        "status": "gap",
    },
    {
        "id": "angle_limit",
        "required_setups": ALL_SETUPS,
        "owned_fields": ("angle_limit_stiffness", "use_angle_limit", "angle_limit"),
        "required_invariants": (
            "finite", "deterministic", "limit_bounded", "branch_transition_stable",
        ),
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_angle_limit_soak",
            "frames": 1200,
            "setups": ("mesh_cloth",),
            "fields": ("angle_limit_stiffness", "use_angle_limit", "angle_limit"),
            "invariants": (
                "finite", "deterministic", "limit_bounded",
                "branch_transition_stable", "parameter_hot_update_in_place",
            ),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_angle_limit",
            "frames": 900,
            "setups": ("bone_cloth", "bone_spring"),
            "fields": ("angle_limit_stiffness", "use_angle_limit", "angle_limit"),
            "invariants": (
                "finite", "deterministic", "limit_bounded",
                "branch_transition_stable", "parameter_hot_update_in_place",
                "connected_disconnected_writeback",
            ),
        },),
        "status": "verified",
    },
    {
        "id": "motion_max_distance_backstop",
        "required_setups": CLOTH_SETUPS,
        "owned_fields": (
            "backstop_radius", "motion_stiffness", "normal_axis",
            "use_max_distance", "use_backstop", "max_distance", "backstop_distance",
        ),
        "required_invariants": (
            "finite", "deterministic", "motion_base_exact", "constraint_boundary_bounded",
        ),
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::motion_base_deterministic",
            "frames": 900,
            "setups": ("mesh_cloth",),
            "fields": (
                "backstop_radius", "motion_stiffness", "normal_axis",
                "use_max_distance", "use_backstop", "max_distance", "backstop_distance",
            ),
            "invariants": (
                "finite", "deterministic", "motion_base_exact",
                "constraint_boundary_bounded",
                "parameter_hot_update_in_place",
            ),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_motion_constraints",
            "frames": 900,
            "setups": ("bone_cloth",),
            "fields": (
                "backstop_radius", "motion_stiffness", "normal_axis",
                "use_max_distance", "use_backstop", "max_distance", "backstop_distance",
            ),
            "invariants": (
                "finite", "deterministic", "motion_base_exact",
                "constraint_boundary_bounded", "parameter_hot_update_in_place",
                "connected_disconnected_writeback",
            ),
        },),
        "status": "verified",
    },
    {
        "id": "external_collision",
        "required_setups": ALL_SETUPS,
        "owned_fields": (
            "collision_dynamic_friction", "collision_static_friction",
            "collision_mode", "radius", "collision_limit_distance",
        ),
        "field_setups": {
            "collision_limit_distance": ("bone_spring",),
            "collision_dynamic_friction": CLOTH_SETUPS,
            "collision_static_friction": CLOTH_SETUPS,
        },
        "required_invariants": (
            "finite", "deterministic", "task_scope_exact", "contact_response_bounded",
            "friction_response_ordered",
        ),
        "invariant_setups": {
            "friction_response_ordered": CLOTH_SETUPS,
        },
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_task_collider_scope_soak",
            "frames": 600,
            "setups": ("mesh_cloth",),
            "fields": ("collision_mode", "radius"),
            "invariants": (
                "finite", "deterministic", "task_scope_exact",
                "contact_response_bounded",
            ),
        }, {
            "runner": "test_blender_mc2_constraint_soak.py::mesh_friction_response",
            "frames": 600,
            "setups": ("mesh_cloth",),
            "fields": (
                "collision_dynamic_friction", "collision_static_friction",
            ),
            "invariants": ("finite", "friction_response_ordered"),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_external_collision",
            "frames": 900,
            "setups": ("bone_cloth",),
            "fields": ("collision_mode", "radius"),
            "invariants": (
                "finite", "deterministic", "task_scope_exact",
                "contact_response_bounded",
                "parameter_hot_update_in_place",
                "connected_disconnected_writeback",
            ),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_friction_response",
            "frames": 600,
            "setups": ("bone_cloth",),
            "fields": (
                "collision_dynamic_friction", "collision_static_friction",
            ),
            "invariants": (
                "finite", "friction_response_ordered",
                "connected_disconnected_writeback",
            ),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_external_collision",
            "frames": 900,
            "setups": ("bone_spring",),
            "fields": ("collision_mode", "radius", "collision_limit_distance"),
            "invariants": (
                "finite", "deterministic", "task_scope_exact",
                "contact_response_bounded",
                "parameter_hot_update_in_place", "soft_collision_limit_bounded",
            ),
        },),
        "status": "verified",
    },
    {
        "id": "self_collision",
        "required_setups": CLOTH_SETUPS,
        "owned_fields": (
            "self_collision_mode", "self_collision_sync_mode",
            "self_collision_thickness", "cloth_mass",
        ),
        "field_setups": {
            "self_collision_sync_mode": ("mesh_cloth",),
        },
        "required_invariants": (
            "finite", "deterministic", "cross_task_scope_exact", "contact_cache_bounded",
            "single_radius_model_consistent",
        ),
        "invariant_setups": {
            "cross_task_scope_exact": ("mesh_cloth",),
        },
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_self_interaction_soak",
            "frames": 1800,
            "setups": ("mesh_cloth",),
            "fields": (
                "self_collision_mode", "self_collision_sync_mode",
                "self_collision_thickness", "cloth_mass",
            ),
            "invariants": (
                "finite", "deterministic", "cross_task_scope_exact",
                "cross_task_candidates_present", "contact_cache_bounded",
                "single_radius_model_consistent",
                "parameter_hot_update_in_place",
            ),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_self_collision",
            "frames": 900,
            "setups": ("bone_cloth",),
            "fields": (
                "self_collision_mode", "self_collision_thickness", "cloth_mass",
            ),
            "invariants": (
                "finite", "deterministic", "contact_cache_bounded",
                "parameter_hot_update_in_place", "connected_disconnected_writeback",
                "single_radius_model_consistent",
            ),
        }),
        "status": "verified",
    },
)


MC2_INACTIVE_FIELD_GROUPS = {
    "source_abi_no_production_consumer_hidden": (
        "distance_culling_length", "distance_culling_fade_ratio",
        "use_distance_culling", "centrifugal_acceleration",
    ),
    "wind_hidden": (
        "wind_influence", "wind_frequency", "wind_turbulence", "wind_blend",
        "wind_synchronization", "wind_depth_weight", "moving_wind",
    ),
    "spring_hidden": (
        "spring_power", "spring_limit_distance", "spring_normal_limit_ratio",
        "spring_noise",
    ),
}


MC2_DEBUG_ACCEPTANCE_LAYERS = (
    "topology", "attributes", "motion_base_position", "motion_limits",
    "angle_restoration_target", "center", "teleport_threshold_direction",
    "teleport_trigger_status", "task_external_colliders",
    "particle_radius", "self_primitives", "self_grid", "self_candidates",
    "self_contacts", "final_output_offset",
)


MC2_DEBUG_ACCEPTANCE_RUNNER = "test_blender_mc2_debug_draw.py"
