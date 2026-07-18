"""Executable MC2 long-run capability coverage contract."""

from __future__ import annotations


ALL_SETUPS = ("mesh_cloth", "bone_cloth", "bone_spring")
CLOTH_SETUPS = ("mesh_cloth", "bone_cloth")


MC2_LONG_RUN_CAPABILITY_MATRIX = (
    {
        "id": "integration_and_pose_blend",
        "setups": ALL_SETUPS,
        "frames": 900,
        "runner": "test_blender_mc2_mixed_output_soak.py::mixed_three_setup",
        "fields": (
            "gravity", "gravity_direction_x", "gravity_direction_y",
            "gravity_direction_z", "gravity_falloff",
            "stabilization_time_after_reset", "blend_weight",
            "rotational_interpolation", "root_rotation", "damping",
        ),
        "invariants": ("finite", "deterministic", "bounded_velocity", "zero_force_rest"),
    },
    {
        "id": "center_inertia_and_teleport",
        "setups": ALL_SETUPS,
        "frames": 900,
        "runner": "test_blender_mc2_mixed_output_soak.py::mixed_three_setup_keep_reset",
        "fields": (
            "distance_culling_length", "distance_culling_fade_ratio",
            "anchor_inertia", "world_inertia", "movement_inertia_smoothing",
            "movement_speed_limit", "rotation_speed_limit", "local_inertia",
            "local_movement_speed_limit", "local_rotation_speed_limit",
            "depth_inertia", "centrifugal_acceleration", "particle_speed_limit",
            "teleport_distance", "teleport_rotation", "use_distance_culling",
            "teleport_mode",
        ),
        "invariants": (
            "finite", "deterministic", "same_frame_stable",
            "teleport_keep_reset_all_setups_exact",
        ),
    },
    {
        "id": "tether_and_distance",
        "setups": CLOTH_SETUPS,
        "frames": 900,
        "runner": "test_blender_mc2_constraint_soak.py::distance_tether",
        "fields": (
            "tether_compression_limit", "tether_stretch_limit",
            "distance_velocity_attenuation", "distance_stiffness",
        ),
        "invariants": ("finite", "deterministic", "rest_length_bounded", "fixed_particles_static"),
    },
    {
        "id": "triangle_bending",
        "setups": ("mesh_cloth",),
        "frames": 900,
        "runner": "test_blender_mc2_constraint_soak.py::triangle_bending",
        "fields": ("bending_stiffness", "bending_method"),
        "invariants": ("finite", "deterministic", "signed_volume_stable", "fixed_particles_static"),
    },
    {
        "id": "angle_restoration",
        "setups": ALL_SETUPS,
        "frames": 1200,
        "runner": "test_blender_mc2_constraint_soak.py::angle_restoration",
        "fields": (
            "angle_restoration_velocity_attenuation",
            "angle_restoration_gravity_falloff",
            "use_angle_restoration", "angle_restoration_stiffness",
        ),
        "invariants": ("finite", "deterministic", "zero_force_rest", "target_direction_exact"),
    },
    {
        "id": "angle_limit",
        "setups": ALL_SETUPS,
        "frames": 1200,
        "runner": "test_blender_mc2_constraint_soak.py::angle_limit",
        "fields": ("angle_limit_stiffness", "use_angle_limit", "angle_limit"),
        "invariants": ("finite", "deterministic", "limit_bounded", "branch_transition_stable"),
    },
    {
        "id": "motion_max_distance_backstop",
        "setups": CLOTH_SETUPS,
        "frames": 900,
        "runner": "test_blender_mc2_constraint_soak.py::motion_base_backstop",
        "fields": (
            "backstop_radius", "motion_stiffness", "normal_axis",
            "use_max_distance", "use_backstop", "max_distance",
            "backstop_distance",
        ),
        "invariants": ("finite", "deterministic", "motion_base_exact", "constraint_boundary_bounded"),
    },
    {
        "id": "external_collision",
        "setups": ALL_SETUPS,
        "frames": 1200,
        "runner": "test_blender_mc2_constraint_soak.py::task_external_colliders",
        "fields": (
            "collision_dynamic_friction", "collision_static_friction",
            "cloth_mass", "collision_mode", "radius", "collision_limit_distance",
        ),
        "invariants": ("finite", "deterministic", "task_scope_exact", "contact_response_bounded"),
    },
    {
        "id": "self_collision",
        "setups": CLOTH_SETUPS,
        "frames": 1800,
        "runner": "test_blender_mc2_constraint_soak.py::cross_task_self",
        "fields": (
            "self_collision_mode", "self_collision_sync_mode",
            "self_collision_thickness",
        ),
        "invariants": ("finite", "deterministic", "cross_task_scope_exact", "contact_cache_bounded"),
    },
)


MC2_INACTIVE_FIELD_GROUPS = {
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
    "topology",
    "attributes",
    "motion_base_position",
    "motion_limits",
    "angle_restoration_target",
    "center_teleport",
    "task_external_colliders",
    "particle_radius",
    "self_primitives",
    "self_grid",
    "self_candidates",
    "self_contacts",
    "final_output_offset",
)


MC2_DEBUG_ACCEPTANCE_RUNNER = "test_blender_mc2_debug_draw.py"
