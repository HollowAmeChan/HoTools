from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mc2.interaction_scope import build_mc2_interaction_scope
from mc2.parameters import make_mc2_particle_profile
from mc2.parameters import make_mc2_setup_options
from mc2.runtime_parameters import make_mc2_runtime_parameters
from mc2.specs import make_mc2_task_spec


class _Data:
    def __init__(self, pointer):
        self.pointer = pointer

    def as_pointer(self):
        return self.pointer


class _Source:
    type = "MESH"

    def __init__(self, pointer, group=1, mask=0):
        self.pointer = pointer
        self.data = _Data(pointer + 1000)
        self.name = self.name_full = f"Mesh{pointer}"
        self.hotools_mesh_collision = SimpleNamespace(
            primary_collision_group=group,
            collided_by_groups=mask,
        )

    def as_pointer(self):
        return self.pointer


def _task(pointer, group=1, mask=0, sync=2):
    return make_mc2_task_spec(
        "mesh_cloth",
        [_Source(pointer, group, mask)],
        profile=make_mc2_particle_profile(self_collision_sync_mode=sync),
    )


def test_zero_mask_is_automatic_all_interaction() -> None:
    tasks = [_task(30), _task(10), _task(20)]
    scope = build_mc2_interaction_scope(tasks, primitive_counts={task.task_id: 7 for task in tasks})
    assert tuple(item.task_id for item in scope.participants) == tuple(
        sorted(task.task_id for task in tasks)
    )
    assert len(scope.pairs) == 3
    assert scope.debug_dict()["primitive_count"] == 21


def test_nonzero_masks_require_a_mutual_group_handshake() -> None:
    group1 = _task(10, group=1, mask=1 << 1)
    group2 = _task(20, group=2, mask=1 << 0)
    wildcard = _task(30, group=3, mask=0)
    blocked = _task(40, group=4, mask=1 << 4)
    scope = build_mc2_interaction_scope([blocked, wildcard, group2, group1])
    assert (group1.task_id, group2.task_id) in scope.pairs or (
        group2.task_id, group1.task_id
    ) in scope.pairs
    assert all(blocked.task_id not in pair for pair in scope.pairs)
    assert all(wildcard.task_id not in pair for pair in scope.pairs)


def test_disabled_sync_tasks_do_not_enter_the_scope() -> None:
    active = _task(10)
    inactive = _task(20, sync=0)
    scope = build_mc2_interaction_scope([inactive, active])
    assert tuple(item.task_id for item in scope.participants) == (active.task_id,)
    assert scope.pairs == ()


def test_product_radius_model_derives_self_thickness_from_radius() -> None:
    profile = make_mc2_particle_profile(radius=0.04, self_collision_thickness=0.003)
    source_runtime = make_mc2_runtime_parameters(
        profile,
        make_mc2_setup_options("mesh_cloth"),
    ).debug_dict()
    product_runtime = make_mc2_runtime_parameters(
        profile,
        make_mc2_setup_options(
            "mesh_cloth",
            self_collision_radius_model="derived_radius",
        ),
    ).debug_dict()
    assert all(
        abs(value - 0.003) < 1.0e-7
        for value in source_runtime["curve_values"]["self_collision_thickness"]
    )
    assert all(
        abs(value - 0.01) < 1.0e-7
        for value in product_runtime["curve_values"]["self_collision_thickness"]
    )


TESTS = (
    ("automatic wildcard scope", test_zero_mask_is_automatic_all_interaction),
    ("mutual group mask", test_nonzero_masks_require_a_mutual_group_handshake),
    ("sync disabled exclusion", test_disabled_sync_tasks_do_not_enter_the_scope),
    ("derived self radius", test_product_radius_model_derives_self_thickness_from_radius),
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"[PASS] {name}")
    print(f"{len(TESTS)}/{len(TESTS)} passed")
