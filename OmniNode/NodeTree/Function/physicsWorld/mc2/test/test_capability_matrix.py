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
MC2_ROOT = BLENDER_TEST_ROOT.parent / "mc2"


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


def test_product_execution_boundary_has_no_v0_owner_imports():
    """产品执行边界不得重新依赖待删除的 V0 owner 模块。"""

    root = MC2_ROOT
    forbidden = {
        ".specs",
        ".solver",
        ".native_context",
        ".interaction_scope",
        ".shadow_pipeline",
    }
    for filename in (
        "nodes.py",
        "product_solver.py",
        "setups/mesh_cloth/authoring.py",
        "setups/mesh_cloth/product.py",
        "setups/bone_cloth/authoring.py",
        "setups/bone_cloth/product.py",
    ):
        path = root / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append(("." * node.level) + module)
        assert not (set(imports) & forbidden), (filename, set(imports) & forbidden)


def test_python_v0_owner_modules_and_task_adapters_are_deleted():
    """E7-CPU 后生产树只允许 resolved partition 与产品 domain owner。"""

    removed_modules = {
        "specs.py",
        "solver.py",
        "native_context.py",
        "interaction_scope.py",
        "shadow_pipeline.py",
        "bone_rotation.py",
    }
    assert not {path.name for path in MC2_ROOT.iterdir()} & removed_modules

    forbidden_symbols = {
        "MC2TaskSpec",
        "build_mc2_task_specs",
        "make_mc2_task_spec",
        "build_mc2_topology_spec",
        "prepare_static_inputs_for_task",
        "static_input_fingerprint_for_task",
        "prepare_observed_static_inputs",
        "build_mc2_bone_cloth_static_for_task",
        "build_mc2_mesh_cloth_static_for_task",
        "build_mc2_mesh_cloth_static",
        "build_mc2_bone_frame_input",
        "build_mc2_mesh_frame_input",
        "build_mc2_mesh_frame_input_for_task",
        "capture_requested_mc2_debug",
        "MC2ResultCandidateV1",
        "make_mc2_result_candidate",
        "make_mc2_mesh_result",
        "make_mc2_bone_result",
        "make_mc2_stats_result",
        "iter_mc2_stats_results",
        "get_mc2_stats_result",
        "MC2CenterStaticMetadata",
        "MC2DistanceStaticMetadata",
        "MC2BendingStaticMetadata",
        "MC2SelfCollisionStaticMetadata",
        "MC2BoneClothStaticMetadata",
        "compact_native_static",
        "MC2BoneNativeData",
        "MC2MeshBaselineMetadata",
        "MC2MeshBaselineNativeData",
        "MC2MeshProxyNativeMetadata",
        "MC2MeshProxyNativeData",
        "MC2MeshFinalizerNativeMetadata",
        "MC2MeshFinalizerNativeData",
        "compact_native_baseline",
        "compact_native_finalizer",
        "MC2MeshFusedCPUOwnerV1",
        "MC2FusedMeshFramePublishResultV1",
        "MC2FusedMeshSubstepResultV1",
        "MC2FusedMeshSlotSyncResultV1",
        "sync_mc2_mesh_fused_slot",
        "step_mc2_mesh_fused_substep",
        "capture_and_publish_mc2_mesh_fused_frame",
        "build_mc2_mesh_fused_output_batch",
        "publish_mc2_mesh_fused_output_transaction",
        "MC2RuntimeParametersV0",
        "build_mc2_mesh_domain_draft",
        "build_mc2_mesh_domain_collider_frame",
        "_product_slot_id",
        "compile_mc2_mesh_static_fragment",
        "all_mc2_setup_adapters",
        "every_vertex_has_triangle",
    }
    production = [
        path
        for path in MC2_ROOT.rglob("*.py")
        if "test" not in path.relative_to(MC2_ROOT).parts
    ]
    for path in production:
        source = path.read_text(encoding="utf-8")
        assert "native_context" not in source, path
        assert "native_owner_kind" not in source, path
        tree = ast.parse(source, filename=str(path))
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not defined & forbidden_symbols, (path, defined & forbidden_symbols)
    assert not (MC2_ROOT / "setups" / "mesh_cloth" / "static_build.py").exists()
    names_source = (MC2_ROOT / "names.py").read_text(encoding="utf-8")
    assert "MC2_SLOT_KIND" not in names_source
    assert "MC2_INTERACTION_RESOURCE_KEY" not in names_source
    assert "MC2_STATS_CHANNEL" not in names_source
    product_slot_source = (MC2_ROOT / "product_slot.py").read_text(encoding="utf-8")
    assert "MC2_FUSED_MESH_SLOT_KIND" not in product_slot_source
    assert "MC2_FUSED_MESH_SLOT_ID" not in product_slot_source
    assert "publish_mc2_mesh_fused_frame" not in product_slot_source
    product_solver_source = (MC2_ROOT / "product_solver.py").read_text(
        encoding="utf-8"
    )
    assert "MC2_BONE_FRAME_STATE_KEY" not in product_solver_source
    assert "backend_resources" not in product_solver_source
    domain_compile_source = (MC2_ROOT / "domain_compile.py").read_text(encoding="utf-8")
    domain_collect_source = (MC2_ROOT / "domain_collect.py").read_text(
        encoding="utf-8"
    )
    assert "MC2MeshDomainDraftV1" not in domain_collect_source
    for name in (
        "single_fragment",
        "fragment",
        "single_effective_parameter_signature",
        "effective_parameter_signature",
    ):
        assert f"def {name}(" not in domain_compile_source


def test_compatibility_runners_are_deleted():
    removed = {
        "test_blender_mc2_bone_constraint_soak.py",
        "test_blender_mc2_bone_frame.py",
        "test_blender_mc2_bone_static.py",
        "test_blender_mc2_final_proxy.py",
        "test_blender_mc2_base_pose.py",
        "test_blender_mc2_mixed_output_soak.py",
    }
    assert not {path.name for path in BLENDER_TEST_ROOT.iterdir()} & removed
    acceptance = (MC2_ROOT / "test" / "acceptance_assets_v1.json").read_text(
        encoding="utf-8"
    )
    assert not any(name in acceptance for name in removed)


def test_capability_matrix_has_no_legacy_constraint_runner_evidence():
    source = (BLENDER_TEST_ROOT.parent / "mc2" / "test" / "capability_matrix.py").read_text(
        encoding="utf-8"
    )
    legacy = [
        line.strip()
        for line in source.splitlines()
        if "test_blender_mc2_constraint_soak.py::" in line
        or "test_blender_mc2_bone_constraint_soak.py::" in line
    ]
    assert legacy == []


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
    assert not self_collision["setups"]
    assert not self_collision["fields"]
    assert not self_collision["invariants"]
    assert "cross_source_scope_exact@bone_cloth" not in self_collision["invariants"]
    assert "cross_task_scope_exact@bone_cloth" not in self_collision["invariants"]
    assert "contact_cache_bounded@bone_cloth" not in self_collision["invariants"]
    assert "single_radius_model_consistent@bone_cloth" not in self_collision["invariants"]
    assert not any(self_collision.values())
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
    assert not tether["setups"]
    assert not tether["fields"]
    assert not tether["invariants"]
    assert not any(tether.values())
    assert by_id["tether_and_distance"]["status"] == "verified"

    bending = capability_gaps(by_id["triangle_bending"])
    assert "bending_method@mesh_cloth" not in bending["fields"]
    assert "bending_method@bone_cloth" not in bending["fields"]
    assert "deterministic@mesh_cloth" not in bending["invariants"]
    assert "deterministic@bone_cloth" not in bending["invariants"]
    assert "bending_response_changes@bone_cloth" not in bending["invariants"]
    assert "solve_branch_exact@bone_cloth" not in bending["invariants"]
    assert "signed_volume_stable@bone_cloth" not in bending["invariants"]
    assert not any("bone_spring" in item for item in bending["fields"])
    assert not any("bone_spring" in item for item in bending["invariants"])
    assert not any(bending.values())
    assert by_id["triangle_bending"]["status"] == "verified"

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
