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
        assert set(field_setups).issubset(capability["owned_fields"])
        assert all(
            set(setups).issubset(capability["required_setups"])
            for setups in field_setups.values()
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
    assert "zero_force_rest@bone_cloth" in angle_restoration["invariants"]
    assert "zero_force_rest@bone_spring" in angle_restoration["invariants"]

    angle_limit = capability_gaps(by_id["angle_limit"])
    assert "limit_bounded@mesh_cloth" not in angle_limit["invariants"]
    assert "limit_bounded@bone_cloth" in angle_limit["invariants"]
    assert "limit_bounded@bone_spring" in angle_limit["invariants"]

    integration = capability_gaps(by_id["integration_and_pose_blend"])
    assert "gravity@mesh_cloth" not in integration["fields"]
    assert "gravity@bone_cloth" not in integration["fields"]
    assert "gravity@bone_spring" not in integration["fields"]
    assert "rotational_interpolation@bone_cloth" in integration["fields"]
    assert "rotational_interpolation@bone_spring" in integration["fields"]

    external = capability_gaps(by_id["external_collision"])
    assert "radius@mesh_cloth" not in external["fields"]
    assert "radius@bone_cloth" in external["fields"]
    assert "radius@bone_spring" in external["fields"]
