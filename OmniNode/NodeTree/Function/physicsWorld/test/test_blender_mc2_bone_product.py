"""Blender integration for HoTools ordered-chain BoneCloth product topology."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import mathutils
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")
PYTHON_ABI = "py313" if sys.version_info >= (3, 13) else "py311"
NATIVE_PACKAGE = os.path.join(HOTOOLS, "_Lib", PYTHON_ABI, "HotoolsPackage")

for module_name in tuple(sys.modules):
    if (
        module_name == "HoTools"
        or module_name.startswith("HoTools.")
        or module_name == "hotools_native"
    ):
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
solver = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver")
debug = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug")
topology_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
bone_frame_input = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_frame_input"
)
product_authoring = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_bone_authoring"
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

print(f"MC2 current source: {product_solver.__file__}")
print(f"MC2 current native: {hotools_native.__file__}")
assert os.path.commonpath((HOTOOLS, os.path.abspath(product_solver.__file__))) == HOTOOLS
assert os.path.commonpath((NATIVE_PACKAGE, os.path.abspath(hotools_native.__file__))) == NATIVE_PACKAGE


def _product_armature(
    name: str,
    chain_count: int,
    chain_length: int,
    x_offset: float,
    *,
    connect_children: bool = True,
):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    parent = data.edit_bones.new("Parent")
    parent.head = (x_offset, 0.0, 0.0)
    parent.tail = (x_offset, 0.0, 1.0)
    for chain_index in range(chain_count):
        x = x_offset + float(chain_index) - float(chain_count - 1) * 0.5
        previous = parent
        for depth in range(chain_length):
            bone = data.edit_bones.new(f"Chain{chain_index}_{depth}")
            bone.head = (x, 0.0, 1.0 + depth)
            bone.tail = (x, 0.0, 2.0 + depth)
            bone.parent = previous
            bone.use_connect = connect_children and depth > 0
            previous = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _multi_control_armature(name: str, control_count: int, chain_count: int, chain_length: int):
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
            x = x_base + float(chain_index)
            previous = parent
            for depth in range(chain_length):
                bone = data.edit_bones.new(
                    f"Group{control_index}_Chain{chain_index}_{depth}"
                )
                bone.head = (x, 0.0, 1.0 + depth)
                bone.tail = (x, 0.0, 2.0 + depth)
                bone.parent = previous
                bone.use_connect = depth > 0
                previous = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _oriented_chain_armature(name: str):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    parent = data.edit_bones.new("Parent")
    parent.head = (0.0, 0.0, 0.0)
    parent.tail = (0.0, 0.0, 1.0)
    offsets = (
        (1.0, 0.35, 0.20),
        (0.85, -0.25, 0.45),
        (0.70, 0.55, -0.15),
        (0.55, -0.40, 0.30),
    )
    for chain_index in range(2):
        head = parent.tail + mathutils.Vector((0.0, chain_index * 0.55, chain_index * 0.1))
        previous = parent
        for depth, offset in enumerate(offsets):
            bone = data.edit_bones.new(f"Chain{chain_index}_{depth}")
            bone.head = head
            bone.tail = head + mathutils.Vector(offset)
            bone.parent = previous
            bone.use_connect = depth > 0
            bone.roll = 0.2 + depth * 0.35 + chain_index * 0.15
            head = bone.tail.copy()
            previous = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _dispose_armature(obj) -> None:
    data = obj.data
    if obj.mode != "OBJECT":
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.data.objects.remove(obj, do_unlink=True)
    if data.users == 0:
        bpy.data.armatures.remove(data)


def _matrix_delta(left, right) -> float:
    return max(
        abs(float(left[row][column]) - float(right[row][column]))
        for row in range(4)
        for column in range(4)
    )


rig_a = _product_armature("MC2_ProductRigA", 3, 3, -3.0)
rig_b = _product_armature("MC2_ProductRigB", 2, 3, 3.0)
rig_c = _multi_control_armature("MC2_ProductRigC", 2, 2, 3)
rig_d = _product_armature(
    "MC2_ProductRigD_Free",
    1,
    3,
    20.0,
    connect_children=False,
)
rig_e = _oriented_chain_armature("MC2_ProductRigE_ZeroGravity")
rig_f = _multi_control_armature("MC2_ProductRigF_MultiRequest", 2, 1, 3)
rig_e.location = (1.5, -2.0, 0.75)
rig_e.rotation_mode = "XYZ"
rig_e.rotation_euler = (0.45, -0.3, 0.65)
bpy.context.view_layer.update()
world = None
product_world = None
spring_product_world = None
multi_request_world = None
try:
    tasks, task_names = nodes._physicsMC2BoneClothTaskV0Oracle(
        [
            {"armature": rig_a, "bone": "Parent"},
            {"armature": rig_b, "bone": "Parent"},
        ],
        connection_mode=1,
    )
    assert task_names.splitlines() == [task.task_id for task in tasks]
    assert len(tasks) == 2
    assert tuple(task.setup_options.connection_model for task in tasks) == (
        "hotools_product",
        "hotools_product",
    )
    assert tuple(task.setup_options.connection_mode for task in tasks) == (1, 1)
    assert tuple(len(task.sources) for task in tasks) == (3, 2)
    assert all(task.profile.spring_enabled is False for task in tasks)

    independent_control_tasks, independent_task_names = nodes._physicsMC2BoneClothTaskV0Oracle(
        [
            {"armature": rig_c, "bone": "Parent0"},
            {"armature": rig_c, "bone": "Parent1"},
        ],
        profile=parameters.make_mc2_particle_profile(
            gravity_direction=(1.0, 0.0, 0.0),
            wind_influence=0.0,
        ),
        connection_mode=1,
    )
    assert independent_task_names.splitlines() == [
        task.task_id for task in independent_control_tasks
    ]
    assert len(independent_control_tasks) == 2
    assert len({task.task_id for task in independent_control_tasks}) == 2
    assert tuple(len(task.sources) for task in independent_control_tasks) == (2, 2)
    assert tuple(
        tuple(source["root_bone"] for source in task.sources)
        for task in independent_control_tasks
    ) == (
        ("Group0_Chain0_0", "Group0_Chain1_0"),
        ("Group1_Chain0_0", "Group1_Chain1_0"),
    )
    independent_topologies = tuple(
        topology_module.build_mc2_topology_spec(task)
        for task in independent_control_tasks
    )
    assert tuple(item.particle_count for item in independent_topologies) == (6, 6)
    assert all(item.bone_connection.triangles for item in independent_topologies)

    feedback_world = world_types.PhysicsWorldCache()
    feedback_world.generation = 1
    feedback_world.frame_context.generation = 1
    feedback_world.frame_context.dt = 1.0 / 60.0
    feedback_world.frame_context.raw_dt = 1.0 / 60.0
    feedback_bone_names = tuple(
        bone_name
        for task in independent_control_tasks
        for source in task.sources
        for bone_name in source["bones"]
    )
    animation_bases = {
        bone_name: rig_c.pose.bones[bone_name].matrix_basis.copy()
        for bone_name in feedback_bone_names
    }
    try:
        for frame in (1, 2):
            feedback_world.frame_context.frame = frame
            returned, ready, _status = solver.step_mc2(
                feedback_world,
                independent_control_tasks,
            )
            assert returned is feedback_world and ready is True
            assert writeback.writeback_bone_transforms(feedback_world) == 12
            bpy.context.view_layer.update()

        assert any(
            _matrix_delta(
                rig_c.pose.bones[bone_name].matrix_basis,
                animation_bases[bone_name],
            ) > 1.0e-5
            for bone_name in feedback_bone_names
        ), "fixture must produce a non-identity physical writeback"
        feedback_result = feedback_world.result_streams["bone_transform"][0]
        assert feedback_result["rotation_only_connected_count"] == 8
        assert feedback_result["position_rotation_count"] == 4
        feedback_plan = feedback_world.solver_slots[
            feedback_result["slot_id"]
        ].data["writeback_plan"]
        assert feedback_plan["rotation_only_connected_count"] == 8
        assert feedback_plan["position_rotation_count"] == 4
        feedback_records = tuple(
            (record, matrix_basis)
            for batch in feedback_plan["batches"]
            for record, matrix_basis in zip(
                batch["records"], batch["matrix_bases"]
            )
        )
        assert all(
            matrix_basis.translation.length <= 1.0e-8
            for record, matrix_basis in feedback_records
            if record["motion_mode"] == "rotation_only_connected"
        )
        feedback_debug = debug._output_payload(
            feedback_world.solver_slots[feedback_result["slot_id"]],
            {"positions": np.empty((0, 3), dtype=np.float32)},
        )
        assert feedback_debug["rotation_only_connected_count"] == 8
        assert feedback_debug["position_rotation_count"] == 4
        assert len(feedback_debug["writeback_motion_modes"]) == 12

        physical_bases = {
            bone_name: rig_c.pose.bones[bone_name].matrix_basis.copy()
            for bone_name in feedback_bone_names
        }
        for bone_name, animation_basis in animation_bases.items():
            rig_c.pose.bones[bone_name].matrix_basis = animation_basis
        bpy.context.view_layer.update()
        expected_inputs = tuple(
            bone_frame_input.build_mc2_bone_frame_input(
                task,
                topology,
                frame=3,
                generation=feedback_world.generation,
            )
            for task, topology in zip(independent_control_tasks, independent_topologies)
        )
        for bone_name, physical_basis in physical_bases.items():
            rig_c.pose.bones[bone_name].matrix_basis = physical_basis
        bpy.context.view_layer.update()
        restored_inputs = tuple(
            bone_frame_input.build_mc2_bone_frame_input(
                task,
                topology,
                frame=3,
                generation=feedback_world.generation,
                world=feedback_world,
            )
            for task, topology in zip(independent_control_tasks, independent_topologies)
        )
        for expected_input, restored_input in zip(expected_inputs, restored_inputs):
            np.testing.assert_allclose(
                restored_input.world_positions,
                expected_input.world_positions,
                atol=1.0e-6,
            )
            np.testing.assert_allclose(
                restored_input.raw_pose_matrices,
                expected_input.raw_pose_matrices,
                atol=1.0e-6,
            )

        feedback_world.frame_context.frame = 3
        returned, ready, _status = solver.step_mc2(
            feedback_world,
            independent_control_tasks,
        )
        assert returned is feedback_world and ready is True
        assert all(
            _matrix_delta(
                rig_c.pose.bones[bone_name].matrix_basis,
                physical_bases[bone_name],
            ) <= 1.0e-6
            for bone_name in feedback_bone_names
        ), "MC2 frame input adapter must not mutate Blender pose state"

        assert writeback.writeback_bone_transforms(feedback_world) == 12
        animated_bone_name = feedback_bone_names[1]
        animated_basis = mathutils.Matrix.Rotation(0.01, 4, "X")
        rig_c.pose.bones[animated_bone_name].matrix_basis = animated_basis
        bpy.context.view_layer.update()
        animated_task = independent_control_tasks[0]
        animated_topology = independent_topologies[0]
        animated_names = tuple(
            bone_name
            for source in animated_task.sources
            for bone_name in source["bones"]
        )
        animated_index = animated_names.index(animated_bone_name)
        pre_animation_test_bases = {
            bone_name: rig_c.pose.bones[bone_name].matrix_basis.copy()
            for bone_name in feedback_bone_names
        }
        for bone_name, animation_basis in animation_bases.items():
            rig_c.pose.bones[bone_name].matrix_basis = animation_basis
        rig_c.pose.bones[animated_bone_name].matrix_basis = animated_basis
        bpy.context.view_layer.update()
        direct_animated_input = bone_frame_input.build_mc2_bone_frame_input(
            animated_task,
            animated_topology,
            frame=4,
            generation=feedback_world.generation,
        )
        for bone_name, current_basis in pre_animation_test_bases.items():
            rig_c.pose.bones[bone_name].matrix_basis = current_basis
        bpy.context.view_layer.update()
        filtered_animated_input = bone_frame_input.build_mc2_bone_frame_input(
            animated_task,
            animated_topology,
            frame=4,
            generation=feedback_world.generation,
            world=feedback_world,
        )
        np.testing.assert_allclose(
            filtered_animated_input.raw_pose_matrices[animated_index],
            direct_animated_input.raw_pose_matrices[animated_index],
            atol=1.0e-6,
        )
        feedback_world.frame_context.frame = 4
        returned, ready, _status = solver.step_mc2(
            feedback_world,
            independent_control_tasks,
        )
        assert returned is feedback_world and ready is True
        assert _matrix_delta(
            rig_c.pose.bones[animated_bone_name].matrix_basis,
            animated_basis,
        ) <= 1.0e-6, "current-frame animation input was overwritten by MC2 restore"
    finally:
        feedback_world.omni_cache_dispose("bone_feedback_regression_complete")

    zero_world = world_types.PhysicsWorldCache()
    zero_world.generation = 1
    zero_world.frame_context.generation = 1
    zero_world.frame_context.dt = 1.0 / 60.0
    zero_world.frame_context.raw_dt = 1.0 / 60.0
    zero_task = nodes._physicsMC2BoneClothTaskV0Oracle(
        [{"armature": rig_e, "bone": "Parent"}],
        profile=parameters.make_mc2_particle_profile(
            gravity=0.0,
            damping=0.0,
            bending_stiffness=1.0,
            angle_restoration_enabled=True,
            angle_restoration_stiffness=1.0,
            angle_restoration_velocity_attenuation=0.0,
            angle_limit_enabled=False,
            max_distance_enabled=False,
            backstop_enabled=False,
            wind_influence=0.0,
        ),
    )[0][0]
    zero_topology = topology_module.build_mc2_topology_spec(zero_task)
    zero_initial_input = bone_frame_input.build_mc2_bone_frame_input(
        zero_task,
        zero_topology,
        frame=1,
        generation=zero_world.generation,
    )
    zero_initial_bases = {
        pose_bone.name: pose_bone.matrix_basis.copy()
        for pose_bone in rig_e.pose.bones
        if pose_bone.name.startswith("Chain")
    }
    max_zero_basis_delta = 0.0
    try:
        for frame in range(1, 11):
            zero_world.frame_context.previous_frame = frame - 1 if frame > 1 else None
            zero_world.frame_context.frame = frame
            zero_world.frame_context.same_frame = False
            zero_world.frame_context.continuous = frame > 1
            zero_world.frame_context.dt = 1.0 / 60.0
            zero_world.frame_context.raw_dt = 1.0 / 60.0
            returned, ready, _status = solver.step_mc2(
                zero_world,
                [zero_task],
                dt=1.0 / 60.0,
            )
            assert returned is zero_world and ready is True
            zero_slot = zero_world.solver_slots[zero_task.task_id]
            step_basic, _step_rotations = zero_slot.data[
                "native_context"
            ].read_step_basic()
            np.testing.assert_allclose(
                step_basic,
                zero_initial_input.world_positions,
                atol=1.0e-5,
            )
            np.testing.assert_allclose(
                zero_slot.data["result_candidate"].world_positions,
                zero_initial_input.world_positions,
                atol=1.0e-5,
            )
            assert writeback.writeback_bone_transforms(zero_world) == 8
            bpy.context.view_layer.update()
            basis_deltas = {
                bone_name: _matrix_delta(
                    rig_e.pose.bones[bone_name].matrix_basis,
                    initial_basis,
                )
                for bone_name, initial_basis in zero_initial_bases.items()
            }
            max_zero_basis_delta = max(max_zero_basis_delta, *basis_deltas.values())
        assert max_zero_basis_delta <= 1.0e-5, max_zero_basis_delta
    finally:
        zero_world.omni_cache_dispose("bone_zero_gravity_restoration_complete")

    free_world = world_types.PhysicsWorldCache()
    free_world.generation = 1
    free_world.frame_context.generation = 1
    free_world.frame_context.dt = 1.0 / 60.0
    free_world.frame_context.raw_dt = 1.0 / 60.0
    free_task = nodes._physicsMC2BoneClothTaskV0Oracle([
        {"armature": rig_d, "bone": "Parent"},
    ])[0][0]
    try:
        free_plan = None
        for frame in (1, 2):
            free_world.frame_context.frame = frame
            returned, ready, _status = solver.step_mc2(free_world, [free_task])
            assert returned is free_world and ready is True
            free_result = free_world.result_streams["bone_transform"][0]
            assert free_result["rotation_only_connected_count"] == 0
            assert free_result["position_rotation_count"] == 3
            free_plan = free_world.solver_slots[
                free_result["slot_id"]
            ].data["writeback_plan"]
            assert writeback.writeback_bone_transforms(free_world) == 3
            bpy.context.view_layer.update()

        assert free_plan is not None
        assert free_plan["rotation_only_connected_count"] == 0
        assert free_plan["position_rotation_count"] == 3
        free_records = tuple(
            (record, matrix_basis)
            for batch in free_plan["batches"]
            for record, matrix_basis in zip(
                batch["records"], batch["matrix_bases"]
            )
        )
        assert all(
            record["motion_mode"] == "position_rotation"
            for record, _matrix_basis in free_records
        )
        assert any(
            matrix_basis.translation.length > 1.0e-5
            for _record, matrix_basis in free_records[1:]
        ), "disconnected BoneCloth fixture must produce particle-driven translation"
        for record, matrix_basis in free_records:
            actual_translation = record["pose_bone"].matrix_basis.translation
            assert (actual_translation - matrix_basis.translation).length <= 1.0e-6
    finally:
        free_world.omni_cache_dispose("bone_free_translation_complete")

    spring_tasks, spring_task_names = nodes._physicsMC2BoneSpringTaskV0Oracle([
        {"armature": rig_a, "bone": "Chain0_0"},
        {"armature": rig_b, "bone": "Chain0_0"},
    ])
    assert spring_task_names.splitlines() == [task.task_id for task in spring_tasks]
    assert len(spring_tasks) == 2
    assert all(task.profile.spring_enabled is False for task in spring_tasks)
    assert tuple(
        topology_module.build_mc2_topology_spec(task).particle_count
        for task in spring_tasks
    ) == (3, 3)

    topology_a = topology_module.build_mc2_topology_spec(tasks[0])
    assert topology_a.connection_model == "hotools_product"
    assert topology_a.particle_count == 9
    assert topology_a.bone_connection.root_order == (0, 3, 6)
    assert topology_a.bone_connection.triangles

    world = world_types.PhysicsWorldCache()
    world.generation = 1
    world.frame_context.frame = 1
    world.frame_context.generation = 1
    world.frame_context.dt = 1.0 / 60.0
    world.frame_context.raw_dt = 1.0 / 60.0
    returned, ready, _status = solver.step_mc2(world, tasks)
    assert returned is world and ready is True
    assert set(world.solver_slots) == {task.task_id for task in tasks}
    assert len(world.result_streams["bone_transform"]) == 2

    slot_a = world.solver_slots[tasks[0].task_id]
    slot_b = world.solver_slots[tasks[1].task_id]
    assert slot_a.data["bone_static"].connection_model == "hotools_product"
    assert len(slot_a.data["bone_static"].final_proxy.triangles) > 0
    assert len(slot_b.data["bone_static"].final_proxy.triangles) > 0
    assert slot_a.data["bone_static"].bending.record_count > 0
    assert slot_b.data["bone_static"].bending.record_count > 0
    inspect_a = slot_a.data["native_context"].inspect()
    inspect_b = slot_b.data["native_context"].inspect()
    assert inspect_a["bone_triangle_output_count"] == 1
    assert inspect_b["bone_triangle_output_count"] == 1
    assert inspect_a["bending_record_count"] == slot_a.data["bone_static"].bending.record_count
    assert inspect_b["bending_record_count"] == slot_b.data["bone_static"].bending.record_count
    assert (
        slot_a.data["native_context"].bending_signature
        == slot_a.data["bone_static"].bending.bending_signature
    )
    assert (
        slot_b.data["native_context"].bending_signature
        == slot_b.data["bone_static"].bending.bending_signature
    )
    assert writeback.writeback_bone_transforms(world) == 15

    first_candidate = slot_a.data["result_candidate"]
    first_context = slot_a.data["native_context"]
    first_inspect = first_context.inspect()
    result_identities = {
        channel: tuple(id(item) for item in items)
        for channel, items in world.result_streams.items()
    }
    assert debug.request_mc2_debug_capture(
        world,
        filters={"show_topology": True, "show_output": True},
    ) == 2

    rig_b.scale = (0.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    world.frame_context.frame = 2
    try:
        solver.step_mc2(world, tasks)
    except ValueError as exc:
        assert "zero scale" in str(exc)
    else:
        raise AssertionError("second task preparation failure must abort the whole MC2 step")

    assert slot_a.data["result_candidate"] is first_candidate
    assert slot_a.data["native_context"] is first_context
    assert slot_a.data["native_context"].inspect() == first_inspect
    assert {
        channel: tuple(id(item) for item in items)
        for channel, items in world.result_streams.items()
    } == result_identities

    rig_b.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    returned, ready, _status = solver.step_mc2(world, tasks)
    assert returned is world and ready is True
    assert slot_a.data["native_context"] is first_context
    assert slot_a.data["result_candidate"].revision == first_candidate.revision + 1
    product_debug = slot_a.data["_debug_draw_snapshot"]["topology"]
    assert len(product_debug["longitudinal_edges"]) > 0
    assert len(product_debug["lateral_edges"]) > 0
    assert product_debug["chain_indices"].flags.writeable is False
    product_output = slot_a.data["_debug_draw_snapshot"]["output"]
    assert product_output["writeback_target_kind"] == "bone"
    assert set(product_output["writeback_targets"]) == set(
        slot_a.data["bone_static"].final_proxy.vertex_identities
    )
    assert writeback.writeback_bone_transforms(world) == 15

    native_contexts = tuple(
        world.solver_slots[task.task_id].data["native_context"]
        for task in tasks
    )
    interaction = world.backend_resources[solver.MC2_INTERACTION_RESOURCE_KEY]
    world.publish_result(channel="foreign_test", solver="rigid", marker="keep")
    original_step_group = solver.MC2NativeInteractionV0.step_group

    def _step_group_then_fail(self, *args, **kwargs):
        original_step_group(self, *args, **kwargs)
        raise RuntimeError("injected failure after native group step")

    solver.MC2NativeInteractionV0.step_group = _step_group_then_fail
    world.frame_context.frame = 3
    try:
        solver.step_mc2(world, tasks)
    except RuntimeError as exc:
        assert "after native group step" in str(exc)
    else:
        raise AssertionError("post-mutation failure must abort the MC2 step")
    finally:
        solver.MC2NativeInteractionV0.step_group = original_step_group

    assert not any(slot.kind == "mc2" for slot in world.solver_slots.values())
    assert all(context.disposed for context in native_contexts)
    assert interaction.disposed is True
    assert solver.MC2_INTERACTION_RESOURCE_KEY not in world.backend_resources
    assert world.consume_results(solver="mc2") == []
    assert len(world.consume_results(channel="foreign_test", solver="rigid")) == 1
    assert world.replace_required is True

    world.omni_cache_dispose("bone_product_multi_armature_complete")
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    world.frame_context.frame = 1
    world.frame_context.generation = 1
    world.frame_context.dt = 1.0 / 60.0
    world.frame_context.raw_dt = 1.0 / 60.0

    first_group_sources = [
        {
            "armature": rig_a,
            "root_bone": f"Chain{chain_index}_0",
            "bones": [f"Chain{chain_index}_{depth}" for depth in range(3)],
        }
        for chain_index in (0, 1)
    ]
    second_group_sources = [{
        "armature": rig_a,
        "root_bone": "Chain2_0",
        "bones": [f"Chain2_{depth}" for depth in range(3)],
    }]
    first_group_task = nodes._physicsMC2BoneClothTaskV0Oracle(
        first_group_sources,
        profile=parameters.make_mc2_particle_profile(damping=0.1),
        connection_mode=1,
    )[0][0]
    second_group_task = nodes._physicsMC2BoneClothTaskV0Oracle(
        second_group_sources,
        profile=parameters.make_mc2_particle_profile(damping=0.4),
        connection_mode=1,
    )[0][0]
    component_tasks = [first_group_task, second_group_task]
    returned, ready, _status = solver.step_mc2(world, component_tasks)
    assert returned is world and ready is True
    assert len(world.solver_slots) == 2
    assert len(world.result_streams["bone_transform"]) == 1
    merged_result = world.result_streams["bone_transform"][0]
    assert merged_result["component_count"] == 2
    assert set(merged_result["task_ids"]) == {task.task_id for task in component_tasks}
    assert merged_result["bone_count"] == 9
    owner_slot = world.solver_slots[merged_result["slot_id"]]
    assert owner_slot.data["writeback_plan"]["component_count"] == 2
    assert len(owner_slot.data["writeback_plan"]["batches"]) == 2
    assert writeback.writeback_bone_transforms(world) == 9

    stable_candidate = world.solver_slots[first_group_task.task_id].data[
        "result_candidate"
    ]
    stable_result_ids = {
        channel: tuple(id(item) for item in items)
        for channel, items in world.result_streams.items()
    }
    overlapping_task = nodes._physicsMC2BoneClothTaskV0Oracle(
        [first_group_sources[1], second_group_sources[0]],
        profile=parameters.make_mc2_particle_profile(damping=0.7),
        connection_mode=1,
    )[0][0]
    world.frame_context.frame = 2
    try:
        solver.step_mc2(world, [first_group_task, overlapping_task])
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError("overlapping Bone components must fail before world commit")
    assert world.solver_slots[first_group_task.task_id].data[
        "result_candidate"
    ] is stable_candidate
    assert {
        channel: tuple(id(item) for item in items)
        for channel, items in world.result_streams.items()
    } == stable_result_ids

    product_requests, product_names = nodes.physicsMC2BoneClothTask(
        [
            {"armature": rig_c, "bone": "Parent0"},
            {"armature": rig_c, "bone": "Parent1"},
        ],
        profile=parameters.make_mc2_particle_profile(
            gravity_direction=(1.0, 0.0, 0.0),
            wind_influence=0.0,
        ),
        connection_mode=1,
    )
    assert len(product_requests) == 1
    product_request = product_requests[0]
    assert len(product_request.plan.active_partitions) == 2
    assert product_names == product_slot.make_mc2_product_slot_id(
        product_request.setup_type,
        product_request.domain_signature,
    )
    assert all(
        partition.setup_options.connection_model == "hotools_product"
        and partition.setup_options.self_collision_radius_model == "derived_radius"
        for partition in product_request.plan.active_partitions
    )
    cross_armature_requests, cross_armature_names = nodes.physicsMC2BoneClothTask(
        [
            {"armature": rig_a, "bone": "Parent"},
            {"armature": rig_b, "bone": "Parent"},
        ],
        connection_mode=1,
    )
    assert len(cross_armature_requests) == 2
    assert cross_armature_names.splitlines() == [
        product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        for request in cross_armature_requests
    ]
    disabled_requests, disabled_names = nodes.physicsMC2BoneClothTask(
        [{"armature": rig_c, "bone": "Parent0"}],
        enabled=False,
    )
    assert disabled_requests == [] and disabled_names == ""
    product_world = world_types.PhysicsWorldCache()
    product_world.generation = 1
    product_world.frame_context.frame = 1
    product_world.frame_context.generation = 1
    product_world.frame_context.dt = 1.0 / 60.0
    product_world.frame_context.raw_dt = 1.0 / 60.0
    product_world.frame_context.time_scale = 1.0
    product_world.collider_snapshot = {"frame": 1, "colliders": []}
    returned, ready, _status = nodes.physicsMC2Step(
        product_world,
        product_requests,
    )
    assert returned is product_world and ready is True
    product_slot_id = product_slot.make_mc2_product_slot_id(
        product_request.setup_type,
        product_request.domain_signature,
    )
    unified_slot = product_world.solver_slots[product_slot_id]
    unified_owner = unified_slot.data["owner"]
    assert unified_owner.compiled.program.partition_count == 2
    assert unified_owner.compiled.program.particle_count == 12
    assert unified_owner.inspect()["fragment_cache"]["schema"] == (
        "mc2_bone_fragment_cache_v1"
    )
    assert "spec" not in unified_slot.data
    assert "native_context" not in unified_slot.data
    assert "bone_static" not in unified_slot.data
    unified_result = product_world.result_streams["bone_transform"][0]
    assert unified_result["setup_type"] == "bone_cloth"
    assert unified_result["bone_count"] == 12
    assert unified_result["component_count"] == 2
    assert unified_result["rotation_only_connected_count"] == 8
    assert unified_result["position_rotation_count"] == 4
    assert unified_result["domain_signature"] == (
        unified_owner.compiled.program.domain_signature
    )
    unified_plan = unified_slot.data["writeback_plan"]
    assert unified_plan["component_count"] == 2
    assert len(unified_plan["batches"]) == 2
    assert all(
        matrix_basis.translation.length <= 1.0e-8
        for batch in unified_plan["batches"]
        for record, matrix_basis in zip(batch["records"], batch["matrix_bases"])
        if record["motion_mode"] == "rotation_only_connected"
    )
    assert len(
        product_world.backend_resources[
            bone_frame_input.MC2_BONE_FRAME_STATE_KEY
        ]["bones"]
    ) == 12
    assert writeback.writeback_bone_transforms(product_world) == 12

    product_world.frame_context.frame = 2
    product_world.frame_context.restart_required = False
    product_world.frame_context.reset_requested = False
    product_world.frame_context.dt = 1.0 / 30.0
    product_world.frame_context.raw_dt = 1.0 / 30.0
    product_world.collider_snapshot["frame"] = 2
    returned, ready, _status = nodes.physicsMC2Step(
        product_world,
        product_requests,
    )
    assert returned is product_world and ready is True
    assert product_world.solver_slots[product_slot_id] is unified_slot
    assert unified_slot.data["owner"] is unified_owner
    assert unified_slot.data["last_sync"].native_domain_reused
    assert unified_slot.data["last_sync"].fragment_cache_hits == 2
    assert unified_slot.data["scheduled_frame"].schedule.update_count > 0
    assert unified_slot.data["completed_substeps"] == (
        unified_slot.data["scheduled_frame"].schedule.update_count
    )
    assert len(product_world.result_streams["bone_transform"]) == 1
    assert writeback.writeback_bone_transforms(product_world) == 12

    spring_product_requests, spring_product_names = nodes.physicsMC2BoneSpringTask(
        [{
            "armature": rig_a,
            "root_bone": "Chain0_0",
            "bones": tuple(f"Chain0_{depth}" for depth in range(3)),
        }],
        collided_by_groups=1,
    )
    assert len(spring_product_requests) == 1
    spring_product_request = spring_product_requests[0]
    assert spring_product_names == product_slot.make_mc2_product_slot_id(
        spring_product_request.setup_type,
        spring_product_request.domain_signature,
    )
    spring_product_world = world_types.PhysicsWorldCache()
    spring_product_world.generation = 1
    spring_product_world.frame_context.frame = 3
    spring_product_world.frame_context.generation = 1
    spring_product_world.frame_context.dt = 1.0 / 60.0
    spring_product_world.frame_context.raw_dt = 1.0 / 60.0
    spring_product_world.frame_context.time_scale = 1.0
    spring_product_world.collider_snapshot = {
        "frame": 3,
        "colliders": [
            {
                "key": "product-sphere",
                "type": "SPHERE",
                "primary_group": 1,
                "center": (100.0, 0.0, 0.0),
                "radius": 1.0,
            },
            {
                "key": "product-plane",
                "type": "PLANE",
                "primary_group": 1,
                "center": (0.0, 0.0, -100.0),
                "normal": (0.0, 0.0, 1.0),
            },
        ],
    }
    returned, ready, _status = nodes.physicsMC2Step(
        spring_product_world,
        spring_product_requests,
    )
    assert returned is spring_product_world and ready is True
    spring_product_slot_id = product_slot.make_mc2_product_slot_id(
        spring_product_request.setup_type,
        spring_product_request.domain_signature,
    )
    spring_unified_slot = spring_product_world.solver_slots[
        spring_product_slot_id
    ]
    assert spring_unified_slot.data["collider_frame"].collider_count == 1
    spring_product_result = spring_product_world.result_streams[
        "bone_transform"
    ][0]
    assert spring_product_result["setup_type"] == "bone_spring"
    assert spring_product_result["bone_count"] == 3
    assert spring_unified_slot.data["writeback_plan"]["batches"][0][
        "source_kind"
    ] == "bone_spring"
    assert writeback.writeback_bone_transforms(spring_product_world) == 3

    multi_requests = tuple(
        product_authoring.make_mc2_bone_cloth_product_request(
            [{"armature": rig_f, "bone": f"Parent{control_index}"}],
            setup_options=parameters.make_mc2_setup_options(
                "bone_cloth",
                connection_mode=1,
            ),
        )
        for control_index in range(2)
    )
    assert all(len(request.plan.active_partitions) == 1 for request in multi_requests)
    multi_request_world = world_types.PhysicsWorldCache()
    multi_request_world.generation = 1
    multi_request_world.frame_context.frame = 1
    multi_request_world.frame_context.generation = 1
    multi_request_world.frame_context.dt = 1.0 / 60.0
    multi_request_world.frame_context.raw_dt = 1.0 / 60.0
    multi_request_world.frame_context.time_scale = 1.0
    multi_request_world.collider_snapshot = {"frame": 1, "colliders": []}
    returned, ready, multi_status = product_solver.step_mc2_products(
        multi_request_world,
        multi_requests,
    )
    assert returned is multi_request_world and ready is True
    assert "域 2" in multi_status
    multi_slot_ids = tuple(
        product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        for request in multi_requests
    )
    multi_slots = tuple(
        multi_request_world.solver_slots[slot_id] for slot_id in multi_slot_ids
    )
    multi_owners = tuple(slot.data["owner"] for slot in multi_slots)
    assert all(owner.compiled.program.partition_count == 1 for owner in multi_owners)
    assert all(owner.compiled.program.particle_count == 3 for owner in multi_owners)
    assert len(multi_request_world.result_streams["bone_transform"]) == 1
    multi_result = multi_request_world.result_streams["bone_transform"][0]
    primary_slot_id = min(multi_slot_ids)
    secondary_slot_id = max(multi_slot_ids)
    assert multi_result["slot_id"] == primary_slot_id
    assert multi_result["bone_count"] == 6
    assert multi_result["component_count"] == 2
    assert set(multi_result["task_ids"]) == {
        request.plan.active_partitions[0].stable_id for request in multi_requests
    }
    primary_plan = multi_request_world.solver_slots[primary_slot_id].data[
        "writeback_plan"
    ]
    secondary_plan = multi_request_world.solver_slots[secondary_slot_id].data[
        "writeback_plan"
    ]
    assert primary_plan["component_count"] == 2
    assert primary_plan["bone_count"] == 6
    assert len(primary_plan["batches"]) == 2
    assert secondary_plan["bone_count"] == 3
    assert len(
        multi_request_world.backend_resources[
            bone_frame_input.MC2_BONE_FRAME_STATE_KEY
        ]["bones"]
    ) == 6
    assert writeback.writeback_bone_transforms(multi_request_world) == 6

    multi_request_world.frame_context.frame = 2
    multi_request_world.frame_context.restart_required = False
    multi_request_world.frame_context.reset_requested = False
    multi_request_world.frame_context.dt = 1.0 / 30.0
    multi_request_world.frame_context.raw_dt = 1.0 / 30.0
    multi_request_world.collider_snapshot["frame"] = 2
    returned, ready, _status = product_solver.step_mc2_products(
        multi_request_world,
        multi_requests,
    )
    assert returned is multi_request_world and ready is True
    assert tuple(
        multi_request_world.solver_slots[slot_id].data["owner"]
        for slot_id in multi_slot_ids
    ) == multi_owners
    assert all(
        multi_request_world.solver_slots[slot_id].data["last_sync"].native_domain_reused
        for slot_id in multi_slot_ids
    )
    assert len(multi_request_world.result_streams["bone_transform"]) == 1
    assert writeback.writeback_bone_transforms(multi_request_world) == 6
finally:
    if world is not None:
        world.omni_cache_dispose("bone_product_test_cleanup")
    if product_world is not None:
        product_world.omni_cache_dispose("bone_domain_product_test_cleanup")
    if spring_product_world is not None:
        spring_product_world.omni_cache_dispose(
            "bone_spring_domain_product_test_cleanup"
        )
    if multi_request_world is not None:
        multi_request_world.omni_cache_dispose(
            "bone_multi_request_product_test_cleanup"
        )
    _dispose_armature(rig_a)
    _dispose_armature(rig_b)
    _dispose_armature(rig_c)
    _dispose_armature(rig_d)
    _dispose_armature(rig_e)
    _dispose_armature(rig_f)


print("MC2 HoTools BoneCloth product topology/multi-task atomic step: PASS")
