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
        "required_setups": ALL_SETUPS,
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
