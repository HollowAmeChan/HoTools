"""Blender product-only integration for BoneCloth and BoneSpring domains."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")
PYTHON_ABI = "py313" if sys.version_info >= (3, 13) else "py311"
NATIVE_PACKAGE = os.path.join(HOTOOLS, "_Lib", PYTHON_ABI, "HotoolsPackage")

for module_name in tuple(sys.modules):
    if module_name == "HoTools" or module_name.startswith("HoTools.") or module_name == "hotools_native":
        sys.modules.pop(module_name, None)
os.environ["HOTOOLS_NATIVE_TEST_DIR"] = NATIVE_PACKAGE
sys.path[:] = [
    value
    for value in sys.path
    if os.path.normcase(os.path.abspath(value or os.curdir))
    != os.path.normcase(os.path.abspath(NATIVE_PACKAGE))
]
sys.path.insert(0, NATIVE_PACKAGE)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


nodes = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes")
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
debug = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug")
bone_frame_input = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_frame_input"
)
product_authoring = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_cloth.authoring"
)
product_solver = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_solver"
)
product_slot = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_slot"
)
world_types = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.types")
writeback = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback")
hotools_native = importlib.import_module("hotools_native")

print(f"MC2_BONE_PRODUCT_SOURCE {product_solver.__file__}")
print(f"MC2_BONE_PRODUCT_NATIVE {hotools_native.__file__}")
assert os.path.commonpath((HOTOOLS, os.path.abspath(product_solver.__file__))) == HOTOOLS
assert os.path.commonpath((NATIVE_PACKAGE, os.path.abspath(hotools_native.__file__))) == NATIVE_PACKAGE


def _armature(name: str, control_count: int, chain_count: int, chain_length: int):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for control_index in range(control_count):
        x_base = float(control_index) * 10.0
        parent = data.edit_bones.new(f"Parent{control_index}")
        parent.head = (x_base, 0.0, 0.0)
        parent.tail = (x_base, 0.0, 1.0)
        for chain_index in range(chain_count):
            x = x_base + float(chain_index) - float(chain_count - 1) * 0.5
            previous = parent
            for depth in range(chain_length):
                bone = data.edit_bones.new(f"Group{control_index}_Chain{chain_index}_{depth}")
                bone.head = (x, depth * 0.18, 1.0 + depth * 0.04)
                bone.tail = (x + depth * 0.01, (depth + 1) * 0.18, 1.04 + depth * 0.04)
                bone.parent = previous
                bone.use_connect = depth > 0
                previous = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _remove_armature(obj) -> None:
    if obj is None:
        return
    try:
        name = obj.name
        data = obj.data
    except ReferenceError:
        return
    if name not in bpy.data.objects:
        return
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and not data.users:
        bpy.data.armatures.remove(data)


def _set_frame(world, frame: int, *, dt=1.0 / 60.0) -> None:
    context = world.frame_context
    context.previous_frame = frame - 1 if frame > 1 else None
    context.frame = frame
    context.same_frame = False
    context.continuous = frame > 1
    context.restart_required = frame == 1
    context.reset_requested = False
    context.dt = float(dt)
    context.raw_dt = float(dt)
    context.time_scale = 1.0
    context.generation = 1
    world.generation = 1
    world.collider_snapshot = {"frame": frame, "colliders": []}


def _slot_id(request) -> str:
    return product_slot.make_mc2_product_slot_id(
        request.setup_type, request.domain_signature
    )


def _run(world, requests, frame: int, *, dt=1.0 / 60.0):
    _set_frame(world, frame, dt=dt)
    returned, ready, status = nodes.physicsMC2Step(world, list(requests))
    assert returned is world and ready is True, status
    slots = tuple(world.solver_slots[_slot_id(request)] for request in requests)
    assert all("native_context" not in slot.data and "spec" not in slot.data for slot in slots)
    assert all(np.all(np.isfinite(slot.data["owner"].read_output().world_positions)) for slot in slots)
    return slots


class _FakeMatrix:
    def __init__(self, value):
        self.value = value

    def copy(self):
        return _FakeMatrix(self.value)


class _FakePoseBone:
    def __init__(self, value, fail_value=None):
        self._matrix_basis = _FakeMatrix(value)
        self.fail_value = fail_value

    @property
    def matrix_basis(self):
        return self._matrix_basis

    @matrix_basis.setter
    def matrix_basis(self, value):
        if self.fail_value is not None and value.value == self.fail_value:
            raise RuntimeError("injected bone writeback failure")
        self._matrix_basis = value.copy()


class _NoForeachPoseBones:
    def foreach_get(self, _name, _values):
        raise TypeError("foreach unavailable")


def test_bone_product_batch_writeback_rollback_contract() -> None:
    first = _FakePoseBone("old-first")
    second = _FakePoseBone("old-second", fail_value="new-second")
    updates = (
        (first, 0, _FakeMatrix("new-first"), "First"),
        (second, 1, _FakeMatrix("new-second"), "Second"),
    )
    try:
        writeback._apply_bone_basis_updates(
            _NoForeachPoseBones(), updates, [0.0] * 32
        )
    except RuntimeError as exc:
        assert "injected bone writeback failure" in str(exc)
    else:
        raise AssertionError("batch writeback failure was not propagated")
    assert first.matrix_basis.value == "old-first"
    assert second.matrix_basis.value == "old-second"


rig_multi = _armature("MC2ProductMultiPartition", 2, 2, 3)
rig_a = _armature("MC2ProductCrossA", 1, 3, 3)
rig_b = _armature("MC2ProductCrossB", 1, 2, 3)
rig_spring = _armature("MC2ProductSpring", 1, 1, 3)
rig_requests = _armature("MC2ProductMultiRequest", 2, 1, 3)
worlds = []
try:
    test_bone_product_batch_writeback_rollback_contract()
    cloth_profile = parameters.make_mc2_particle_profile(
        gravity_direction=(1.0, 0.0, 0.0),
        wind_influence=0.0,
        max_distance_enabled=True,
        max_distance=0.03,
        backstop_enabled=True,
        backstop_radius=0.01,
        angle_limit_enabled=True,
        angle_limit=30.0,
    )
    requests, names = nodes.physicsMC2BoneClothTask(
        [
            {"armature": rig_multi, "bone": "Parent0"},
            {"armature": rig_multi, "bone": "Parent1"},
        ],
        profile=cloth_profile,
        connection_mode=1,
    )
    assert len(requests) == 1
    request = requests[0]
    assert len(request.plan.active_partitions) == 2
    assert names == _slot_id(request)
    assert all(
        partition.setup_options.connection_model == "hotools_product"
        and partition.setup_options.self_collision_radius_model == "derived_radius"
        for partition in request.plan.active_partitions
    )
    disabled, disabled_names = nodes.physicsMC2BoneClothTask(
        [{"armature": rig_multi, "bone": "Parent0"}], enabled=False
    )
    assert disabled == [] and disabled_names == ""

    cloth_world = world_types.PhysicsWorldCache()
    worlds.append(cloth_world)
    cloth_slot = _run(cloth_world, requests, 1)[0]
    cloth_owner = cloth_slot.data["owner"]
    assert cloth_owner.compiled.program.partition_count == 2
    assert cloth_owner.compiled.program.particle_count == 12
    assert cloth_owner.inspect()["fragment_cache"]["schema"] == "mc2_bone_fragment_cache_v1"
    result = cloth_world.result_streams["bone_transform"][0]
    assert result["bone_count"] == 12 and result["component_count"] == 2
    assert result["rotation_only_connected_count"] == 8
    assert result["position_rotation_count"] == 4
    assert len(cloth_slot.data["writeback_plan"]["batches"]) == 2
    assert len(
        cloth_world.backend_resources[bone_frame_input.MC2_BONE_FRAME_STATE_KEY]["bones"]
    ) == 12
    assert writeback.writeback_bone_transforms(cloth_world) == 12

    assert debug.request_mc2_debug_capture(
        cloth_world,
        filters={
            "show_output": True,
            "show_depth": True,
            "show_step_basic": True,
            "show_gravity": True,
            "show_distance": True,
            "show_tether": True,
            "show_bending": True,
            "show_motion": True,
            "show_angle_restoration": True,
            "show_angle_limit": True,
        },
    ) == 1
    assert _run(cloth_world, requests, 2, dt=1.0 / 30.0)[0] is cloth_slot
    assert cloth_slot.data["owner"] is cloth_owner
    assert cloth_slot.data["last_sync"].native_domain_reused
    snapshot = cloth_slot.data["_debug_draw_snapshot"]
    output = snapshot["output"]
    translation = np.asarray(output["translation_applied"], dtype=np.uint8)
    assert np.count_nonzero(translation == 0) == 8
    assert np.count_nonzero(translation == 1) == 4
    assert snapshot["topology"]["baseline_root_indices"].shape == (12,)
    assert snapshot["motion"]["step_basic_positions"].shape == (12, 3)
    for name in ("distance", "tether", "bending", "angle_restoration", "angle_limit"):
        records = snapshot["constraint_records"][name]
        assert len(records["states"]) > 0
    assert writeback.writeback_bone_transforms(cloth_world) == 12

    cross_requests, cross_names = nodes.physicsMC2BoneClothTask(
        [
            {"armature": rig_a, "bone": "Parent0"},
            {"armature": rig_b, "bone": "Parent0"},
        ],
        connection_mode=1,
    )
    assert len(cross_requests) == 2
    assert cross_names.splitlines() == [_slot_id(item) for item in cross_requests]
    cross_world = world_types.PhysicsWorldCache()
    worlds.append(cross_world)
    cross_slots = _run(cross_world, cross_requests, 1)
    assert len(cross_slots) == 2
    assert sum(result["bone_count"] for result in cross_world.result_streams["bone_transform"]) == 15
    assert writeback.writeback_bone_transforms(cross_world) == 15

    spring_requests, spring_names = nodes.physicsMC2BoneSpringTask(
        [{
            "armature": rig_spring,
            "root_bone": "Group0_Chain0_0",
            "bones": tuple(f"Group0_Chain0_{depth}" for depth in range(3)),
        }],
        profile=parameters.make_mc2_particle_profile(
            angle_limit_enabled=True, angle_limit=15.0
        ),
        collided_by_groups=1,
    )
    assert len(spring_requests) == 1 and spring_names == _slot_id(spring_requests[0])
    spring_world = world_types.PhysicsWorldCache()
    worlds.append(spring_world)
    spring_slot = _run(spring_world, spring_requests, 1)[0]
    spring_result = spring_world.result_streams["bone_transform"][0]
    assert spring_result["setup_type"] == "bone_spring"
    assert spring_result["bone_count"] == 3
    assert spring_slot.data["writeback_plan"]["batches"][0]["source_kind"] == "bone_spring"
    assert writeback.writeback_bone_transforms(spring_world) == 3

    multi_requests = tuple(
        product_authoring.make_mc2_bone_cloth_product_request(
            [{"armature": rig_requests, "bone": f"Parent{control_index}"}],
            setup_options=parameters.make_mc2_setup_options(
                "bone_cloth", connection_mode=1
            ),
        )
        for control_index in range(2)
    )
    multi_world = world_types.PhysicsWorldCache()
    worlds.append(multi_world)
    _set_frame(multi_world, 1)
    returned, ready, status = product_solver.step_mc2_products(multi_world, multi_requests)
    assert returned is multi_world and ready is True, status
    multi_slots = tuple(multi_world.solver_slots[_slot_id(item)] for item in multi_requests)
    multi_owners = tuple(slot.data["owner"] for slot in multi_slots)
    assert all(owner.compiled.program.partition_count == 1 for owner in multi_owners)
    merged = multi_world.result_streams["bone_transform"][0]
    assert merged["bone_count"] == 6 and merged["component_count"] == 2
    assert writeback.writeback_bone_transforms(multi_world) == 6
    _set_frame(multi_world, 2, dt=1.0 / 30.0)
    returned, ready, status = product_solver.step_mc2_products(multi_world, multi_requests)
    assert returned is multi_world and ready is True, status
    assert tuple(slot.data["owner"] for slot in multi_slots) == multi_owners
    assert all(slot.data["last_sync"].native_domain_reused for slot in multi_slots)
    assert writeback.writeback_bone_transforms(multi_world) == 6
finally:
    for world in worlds:
        world.omni_cache_dispose("mc2 bone product-only cleanup")
    for armature in (rig_multi, rig_a, rig_b, rig_spring, rig_requests):
        _remove_armature(armature)


print("MC2 BoneCloth/BoneSpring product-only integration: PASS")
