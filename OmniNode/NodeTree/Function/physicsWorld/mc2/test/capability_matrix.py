"""MC2 product requirements and the Blender evidence that actually exists."""

from __future__ import annotations


ALL_SETUPS = ("mesh_cloth", "bone_cloth", "bone_spring")
CLOTH_SETUPS = ("mesh_cloth", "bone_cloth")


def capability_gaps(capability):
    evidence = tuple(capability["evidence"])
    covered_setups = set().union(*(item["setups"] for item in evidence))
    exercised_fields = set().union(*(item["fields"] for item in evidence))
    verified_invariants = set().union(*(item["invariants"] for item in evidence))
    return {
        "setups": set(capability["required_setups"]) - covered_setups,
        "fields": set(capability["owned_fields"]) - exercised_fields,
        "invariants": set(capability["required_invariants"]) - verified_invariants,
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
        "required_invariants": (
            "finite", "deterministic", "bounded_velocity", "zero_force_rest",
            "candidate_frame_progresses", "writeback_targets_present",
        ),
        "evidence": ({
            "runner": "test_blender_mc2_mixed_output_soak.py::main",
            "frames": 900,
            "setups": ALL_SETUPS,
            "fields": ("gravity", "damping"),
            "invariants": (
                "finite", "deterministic", "candidate_frame_progresses",
                "writeback_targets_present",
                "parameter_hot_update_in_place",
            ),
        },),
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
            "teleport_keep_reset_all_setups_exact",
            "teleport_zero_substep_immediate", "teleport_reset_pose_exact",
        ),
        "evidence": ({
            "runner": "test_blender_mc2_mixed_output_soak.py::main",
            "frames": 900,
            "setups": ALL_SETUPS,
            "fields": ("teleport_distance", "teleport_mode"),
            "invariants": (
                "finite", "deterministic", "teleport_keep_reset_all_setups_exact",
                "teleport_zero_substep_immediate", "teleport_reset_pose_exact",
                "teleport_nonunit_positive_scale", "real_writeback_each_frame",
            ),
        },),
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
        ),
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_distance_tether_soak",
            "frames": 900,
            "setups": ("mesh_cloth",),
            "fields": ("distance_stiffness",),
            "invariants": ("finite", "rest_length_bounded", "parameter_hot_update_in_place"),
        },),
        "status": "gap",
    },
    {
        "id": "triangle_bending",
        "required_setups": ("mesh_cloth",),
        "owned_fields": ("bending_stiffness", "bending_method"),
        "required_invariants": (
            "finite", "deterministic", "signed_volume_stable", "fixed_particles_static",
        ),
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_bending_soak",
            "frames": 900,
            "setups": ("mesh_cloth",),
            "fields": ("bending_stiffness",),
            "invariants": ("finite", "bending_response_changes", "solve_branch_exact"),
        },),
        "status": "gap",
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
        ),
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_angle_restoration_rest_soak",
            "frames": 900,
            "setups": ("mesh_cloth",),
            "fields": ("use_angle_restoration", "angle_restoration_stiffness"),
            "invariants": ("finite", "zero_force_rest", "parameter_hot_update_in_place"),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_angle_constraints",
            "frames": 900,
            "setups": ("bone_cloth", "bone_spring"),
            "fields": ("use_angle_restoration", "angle_restoration_stiffness"),
            "invariants": (
                "finite", "bone_deterministic", "bone_branch_transition_stable",
                "bounded_zero_force_drift", "connected_disconnected_writeback",
            ),
        },),
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
            "invariants": ("finite", "limit_bounded"),
        }, {
            "runner": "test_blender_mc2_bone_constraint_soak.py::bone_angle_constraints",
            "frames": 900,
            "setups": ("bone_cloth", "bone_spring"),
            "fields": ("angle_limit_stiffness", "use_angle_limit", "angle_limit"),
            "invariants": (
                "finite", "bone_deterministic", "bone_branch_transition_stable",
                "bounded_zero_force_drift", "connected_disconnected_writeback",
            ),
        },),
        "status": "gap",
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
            "runner": "test_blender_mc2_constraint_soak.py::_motion_base_soak",
            "frames": 900,
            "setups": ("mesh_cloth",),
            "fields": (
                "backstop_radius", "motion_stiffness", "normal_axis",
                "use_max_distance", "use_backstop", "max_distance", "backstop_distance",
            ),
            "invariants": (
                "finite", "motion_base_exact", "constraint_boundary_bounded",
                "parameter_hot_update_in_place",
            ),
        },),
        "status": "gap",
    },
    {
        "id": "external_collision",
        "required_setups": ALL_SETUPS,
        "owned_fields": (
            "collision_dynamic_friction", "collision_static_friction",
            "collision_mode", "radius", "collision_limit_distance",
        ),
        "required_invariants": (
            "finite", "deterministic", "task_scope_exact", "contact_response_bounded",
        ),
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_task_collider_scope_soak",
            "frames": 600,
            "setups": ("mesh_cloth",),
            "fields": ("collision_mode", "radius"),
            "invariants": ("finite", "task_scope_exact"),
        },),
        "status": "gap",
    },
    {
        "id": "self_collision",
        "required_setups": CLOTH_SETUPS,
        "owned_fields": (
            "self_collision_mode", "self_collision_sync_mode",
            "self_collision_thickness", "cloth_mass",
        ),
        "required_invariants": (
            "finite", "deterministic", "cross_task_scope_exact", "contact_cache_bounded",
        ),
        "evidence": ({
            "runner": "test_blender_mc2_constraint_soak.py::_self_interaction_soak",
            "frames": 1800,
            "setups": ("mesh_cloth",),
            "fields": ("self_collision_mode", "self_collision_sync_mode"),
            "invariants": (
                "finite", "cross_task_candidates_present", "contact_cache_bounded",
                "parameter_hot_update_in_place",
            ),
        },),
        "status": "gap",
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
    "angle_restoration_target", "center_teleport", "task_external_colliders",
    "particle_radius", "self_primitives", "self_grid", "self_candidates",
    "self_contacts", "final_output_offset",
)


MC2_DEBUG_ACCEPTANCE_RUNNER = "test_blender_mc2_debug_draw.py"
