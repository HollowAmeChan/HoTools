from .capability_matrix import (
    ALL_SETUPS,
    MC2_DEBUG_ACCEPTANCE_LAYERS,
    MC2_DEBUG_ACCEPTANCE_RUNNER,
    MC2_INACTIVE_FIELD_GROUPS,
    MC2_LONG_RUN_CAPABILITY_MATRIX,
)
from ..runtime_parameters import (
    MC2_RUNTIME_CURVE_FIELDS,
    MC2_RUNTIME_FLOAT_FIELDS,
    MC2_RUNTIME_INT_FIELDS,
)


def test_long_run_matrix_owns_every_runtime_field_once():
    expected = set(
        MC2_RUNTIME_FLOAT_FIELDS
        + MC2_RUNTIME_INT_FIELDS
        + MC2_RUNTIME_CURVE_FIELDS
    )
    owners = {}
    for capability in MC2_LONG_RUN_CAPABILITY_MATRIX:
        assert capability["id"]
        assert set(capability["setups"]).issubset(ALL_SETUPS)
        assert int(capability["frames"]) >= 600
        runner = str(capability["runner"])
        assert runner.startswith("test_blender_mc2_")
        assert "_soak.py::" in runner
        assert {"finite", "deterministic"}.issubset(capability["invariants"])
        for field in capability["fields"]:
            assert field not in owners, (field, owners[field], capability["id"])
            owners[field] = capability["id"]
    for group, fields in MC2_INACTIVE_FIELD_GROUPS.items():
        assert group.endswith("_hidden")
        for field in fields:
            assert field not in owners, (field, owners[field], group)
            owners[field] = group
    assert set(owners) == expected, sorted(expected.symmetric_difference(owners))


def test_debug_acceptance_layers_are_explicit_and_unique():
    assert MC2_DEBUG_ACCEPTANCE_RUNNER == "test_blender_mc2_debug_draw.py"
    assert len(MC2_DEBUG_ACCEPTANCE_LAYERS) == len(set(MC2_DEBUG_ACCEPTANCE_LAYERS))
    assert {
        "motion_base_position",
        "angle_restoration_target",
        "task_external_colliders",
        "final_output_offset",
    }.issubset(MC2_DEBUG_ACCEPTANCE_LAYERS)
