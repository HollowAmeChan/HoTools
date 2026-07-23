import ast
from pathlib import Path

from .capability_matrix import (
    ALL_SETUPS,
    MC2_DEBUG_ACCEPTANCE_LAYERS,
    MC2_DEBUG_ACCEPTANCE_RUNNER,
    MC2_INACTIVE_FIELD_GROUPS,
    MC2_LONG_RUN_CAPABILITY_MATRIX,
    capability_gaps,
)
from ..runtime_parameters import (
    MC2_RUNTIME_CURVE_FIELDS,
    MC2_RUNTIME_FLOAT_FIELDS,
    MC2_RUNTIME_INT_FIELDS,
)


BLENDER_TEST_ROOT = Path(__file__).resolve().parents[2] / "test"


def _runner_symbol_exists(runner):
    filename, symbol = runner.split("::", 1)
    path = BLENDER_TEST_ROOT / filename
    assert path.is_file(), path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert symbol in symbols, (runner, sorted(symbols))


def test_long_run_matrix_separates_requirements_from_real_evidence():
    expected = set(
        MC2_RUNTIME_FLOAT_FIELDS + MC2_RUNTIME_INT_FIELDS + MC2_RUNTIME_CURVE_FIELDS
    )
    owners = {}
    for capability in MC2_LONG_RUN_CAPABILITY_MATRIX:
        assert capability["id"]
        assert set(capability["required_setups"]).issubset(ALL_SETUPS)
        field_setups = capability.get("field_setups", {})
        invariant_setups = capability.get("invariant_setups", {})
        assert set(field_setups).issubset(capability["owned_fields"])
        assert set(invariant_setups).issubset(capability["required_invariants"])
        assert all(
            set(setups).issubset(capability["required_setups"])
            for setups in field_setups.values()
        )
        assert all(
            set(setups).issubset(capability["required_setups"])
            for setups in invariant_setups.values()
        )
        assert capability["evidence"]
        for item in capability["evidence"]:
            _runner_symbol_exists(item["runner"])
            assert int(item["frames"]) >= 600
            assert set(item["setups"]).issubset(capability["required_setups"])
            assert set(item["fields"]).issubset(capability["owned_fields"])
            assert "finite" in item["invariants"]
        for field in capability["owned_fields"]:
            assert field not in owners, (field, owners[field], capability["id"])
            owners[field] = capability["id"]
        gaps = capability_gaps(capability)
        complete = not any(gaps.values())
        assert capability["status"] == ("verified" if complete else "gap"), (
            capability["id"], gaps,
        )
    for group, fields in MC2_INACTIVE_FIELD_GROUPS.items():
        assert group.endswith("_hidden")
        for field in fields:
            assert field not in owners, (field, owners[field], group)
            owners[field] = group
    assert set(owners) == expected, sorted(expected.symmetric_difference(owners))


def test_debug_acceptance_layers_are_inventory_not_coverage_claims():
    assert (BLENDER_TEST_ROOT / MC2_DEBUG_ACCEPTANCE_RUNNER).is_file()
    assert len(MC2_DEBUG_ACCEPTANCE_LAYERS) == len(set(MC2_DEBUG_ACCEPTANCE_LAYERS))


def test_setup_local_evidence_cannot_close_another_setup():
    by_id = {item["id"]: item for item in MC2_LONG_RUN_CAPABILITY_MATRIX}
    angle_restoration = capability_gaps(by_id["angle_restoration"])
    assert "zero_force_rest@mesh_cloth" not in angle_restoration["invariants"]
    assert "zero_force_rest@bone_cloth" not in angle_restoration["invariants"]
    assert "zero_force_rest@bone_spring" not in angle_restoration["invariants"]
    assert "target_direction_exact@bone_cloth" not in angle_restoration["invariants"]
    assert "target_direction_exact@bone_spring" not in angle_restoration["invariants"]
    assert "target_direction_exact@mesh_cloth" not in angle_restoration["invariants"]
    assert "deterministic@bone_cloth" not in angle_restoration["invariants"]
    assert "deterministic@bone_spring" not in angle_restoration["invariants"]
    assert "deterministic@mesh_cloth" not in angle_restoration["invariants"]
    assert "angle_restoration_velocity_attenuation@mesh_cloth" not in angle_restoration["fields"]
    assert "angle_restoration_velocity_attenuation@bone_cloth" not in angle_restoration["fields"]
    assert "angle_restoration_velocity_attenuation@bone_spring" not in angle_restoration["fields"]
    assert "angle_restoration_gravity_falloff@mesh_cloth" not in angle_restoration["fields"]
    assert "velocity_attenuation_response_ordered@mesh_cloth" not in angle_restoration["invariants"]
    assert "velocity_attenuation_response_ordered@bone_cloth" not in angle_restoration["invariants"]
    assert "velocity_attenuation_response_ordered@bone_spring" not in angle_restoration["invariants"]
    assert "gravity_falloff_response_ordered@mesh_cloth" not in angle_restoration["invariants"]
    assert "gravity_falloff_response_ordered@bone_cloth" not in angle_restoration["invariants"]
    assert "gravity_falloff_response_ordered@bone_spring" not in angle_restoration["invariants"]
    assert not any(
        item.startswith("center_input_reachable@")
        for item in angle_restoration["invariants"]
    )
    assert not any(angle_restoration.values())
    assert by_id["angle_restoration"]["status"] == "verified"

    self_collision = capability_gaps(by_id["self_collision"])
    assert self_collision["setups"] == set()
    assert self_collision["fields"] == set()
    assert self_collision["invariants"] == set()
    assert by_id["self_collision"]["status"] == "verified"

    angle_limit = capability_gaps(by_id["angle_limit"])
    assert "limit_bounded@mesh_cloth" not in angle_limit["invariants"]
    assert "limit_bounded@bone_cloth" not in angle_limit["invariants"]
    assert "limit_bounded@bone_spring" not in angle_limit["invariants"]
    assert "deterministic@bone_cloth" not in angle_limit["invariants"]
    assert "deterministic@bone_spring" not in angle_limit["invariants"]
    assert "deterministic@mesh_cloth" not in angle_limit["invariants"]
    assert "branch_transition_stable@mesh_cloth" not in angle_limit["invariants"]

    integration = capability_gaps(by_id["integration_and_pose_blend"])
    assert "gravity@mesh_cloth" not in integration["fields"]
    assert "gravity@bone_cloth" not in integration["fields"]
    assert "gravity@bone_spring" not in integration["fields"]
    assert "rotational_interpolation@bone_cloth" not in integration["fields"]
    assert "rotational_interpolation@bone_spring" not in integration["fields"]
    assert "root_rotation@bone_cloth" not in integration["fields"]
    assert "root_rotation@bone_spring" not in integration["fields"]
    assert "gravity_direction_x@bone_cloth" not in integration["fields"]
    assert "gravity_direction_y@bone_cloth" not in integration["fields"]
    assert "gravity_direction_z@bone_cloth" not in integration["fields"]
    assert "gravity_falloff@bone_cloth" not in integration["fields"]
    assert not any(
        field.startswith("blend_weight@")
        or field.startswith("stabilization_time_after_reset@")
        for field in integration["fields"]
    )
    assert not any(
        invariant.startswith("stabilization_blend_ramp_exact@")
        for invariant in integration["invariants"]
    )
    assert not any(
        invariant.startswith("bounded_velocity@")
        or invariant.startswith("zero_force_rest@")
        for invariant in integration["invariants"]
    )
    assert not integration["setups"]
    assert not integration["fields"]
    assert not integration["invariants"]
    assert by_id["integration_and_pose_blend"]["status"] == "verified"

    teleport = capability_gaps(by_id["center_inertia_and_teleport"])
    assert not any(
        invariant.startswith("object_keep_reset_all_setups_detected@")
        or invariant.startswith("object_teleport_zero_substep_immediate@")
        or invariant.startswith("object_reset_pose_exact@")
        or invariant.startswith("bone_root_teleport_detected@")
        or invariant.startswith("teleport_debug_layers_isolated@")
        for invariant in teleport["invariants"]
    )
    assert "particle_reset_self_history_invalidated@mesh_cloth" not in teleport[
        "invariants"
    ]
    assert "particle_reset_self_history_invalidated@bone_cloth" not in teleport[
        "invariants"
    ]
    assert "particle_reset_self_history_invalidated@bone_spring" not in teleport[
        "invariants"
    ]
    assert "bone_root_teleport_detected@mesh_cloth" not in teleport["invariants"]
    assert "bone_root_teleport_detected@bone_cloth" not in teleport["invariants"]
    assert "bone_root_teleport_detected@bone_spring" not in teleport["invariants"]
    for invariant in (
        "task_teleport_single_reference_exact",
        "particle_keep_offset_exact",
        "particle_keep_velocity_preserved",
        "particle_reset_step_history_exact",
        "particle_subset_scope_exact",
    ):
        assert all(
            f"{invariant}@{setup}" not in teleport["invariants"]
            for setup in ("mesh_cloth", "bone_cloth", "bone_spring")
        )
    assert "particle_speed_limit@mesh_cloth" not in teleport["fields"]
    assert "particle_speed_limit@bone_cloth" not in teleport["fields"]
    assert "particle_speed_limit@bone_spring" not in teleport["fields"]
    assert not any(
        invariant.startswith("particle_speed_limit_bounded_and_active@")
        for invariant in teleport["invariants"]
    )
    for field in (
        "world_inertia", "movement_inertia_smoothing", "movement_speed_limit",
        "rotation_speed_limit",
    ):
        assert not any(
            gap.startswith(f"{field}@") for gap in teleport["fields"]
        )
    for invariant in (
        "world_translation_inertia_ordered",
        "world_movement_smoothing_active",
        "world_movement_limit_active",
        "world_rotation_limit_active",
        "center_controls_no_implicit_debug_readback",
    ):
        assert not any(
            gap.startswith(f"{invariant}@") for gap in teleport["invariants"]
        )
    for field in (
        "local_inertia", "local_movement_speed_limit",
        "local_rotation_speed_limit", "depth_inertia",
    ):
        assert not any(
            gap.startswith(f"{field}@") for gap in teleport["fields"]
        )
    for invariant in (
        "local_inertia_endpoints_exact",
        "local_movement_limit_active",
        "local_rotation_limit_active",
        "depth_inertia_particle_ordered",
    ):
        assert not any(
            gap.startswith(f"{invariant}@") for gap in teleport["invariants"]
        )
    assert not any(teleport.values())
    assert by_id["center_inertia_and_teleport"]["status"] == "verified"

    tether = capability_gaps(by_id["tether_and_distance"])
    assert not any(tether.values())

    bending = capability_gaps(by_id["triangle_bending"])
    assert "bending_method@mesh_cloth" not in bending["fields"]
    assert "bending_method@bone_cloth" not in bending["fields"]
    assert "deterministic@mesh_cloth" not in bending["invariants"]
    assert "deterministic@bone_cloth" not in bending["invariants"]
    assert not any("bone_spring" in item for item in bending["fields"])
    assert not any("bone_spring" in item for item in bending["invariants"])
    assert not any(bending.values())

    external = capability_gaps(by_id["external_collision"])
    assert "radius@mesh_cloth" not in external["fields"]
    assert "radius@bone_cloth" not in external["fields"]
    assert "radius@bone_spring" not in external["fields"]
    assert "collision_limit_distance@bone_spring" not in external["fields"]
    assert "collision_limit_distance@mesh_cloth" not in external["fields"]
    assert "collision_limit_distance@bone_cloth" not in external["fields"]
    assert "contact_response_bounded@mesh_cloth" not in external["invariants"]
    assert "contact_response_bounded@bone_cloth" not in external["invariants"]
    assert "contact_response_bounded@bone_spring" not in external["invariants"]
    assert "task_scope_exact@bone_cloth" not in external["invariants"]
    assert "task_scope_exact@bone_spring" not in external["invariants"]
    assert "deterministic@mesh_cloth" not in external["invariants"]
    assert "friction_response_ordered@mesh_cloth" not in external["invariants"]
    assert "friction_response_ordered@bone_cloth" not in external["invariants"]
    assert "friction_response_ordered@bone_spring" not in external["invariants"]
    assert not any(external.values())

    motion = capability_gaps(by_id["motion_max_distance_backstop"])
    assert not motion["setups"]
    assert not motion["fields"]
    assert "motion_base_exact@mesh_cloth" not in motion["invariants"]
    assert "motion_base_exact@bone_cloth" not in motion["invariants"]
    assert "deterministic@mesh_cloth" not in motion["invariants"]
    assert "deterministic@bone_cloth" not in motion["invariants"]
    assert not any(motion.values())
