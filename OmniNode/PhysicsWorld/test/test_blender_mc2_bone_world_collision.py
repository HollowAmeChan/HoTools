"""BoneCloth consumes shared Physics World simple-collision semantics."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(NODETREE, "PhysicsWorld")
PYTHON_ABI = "py313" if sys.version_info >= (3, 13) else "py311"
NATIVE_PACKAGE = os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    os.path.join(HOTOOLS, "_Lib", PYTHON_ABI, "HotoolsPackage"),
)

for module_name in tuple(sys.modules):
    if (
        module_name == "HoTools"
        or module_name.startswith("HoTools.")
        or module_name == "hotools_native"
    ):
        sys.modules.pop(module_name, None)
os.environ["HOTOOLS_NATIVE_TEST_DIR"] = NATIVE_PACKAGE
for path in (NATIVE_PACKAGE, HOTOOLS, os.path.dirname(HOTOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", NODETREE),
    ("HoTools.OmniNode.Function", FUNCTION),
    ("HoTools.OmniNode.PhysicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module

physics_blender = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.blender"
)
physics_nodes = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.nodes"
)
mc2_nodes = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.nodes"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.parameters"
)
product_slot = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.product_slot"
)
debug_draw = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.debug_draw"
)


def _make_armature():
    data = bpy.data.armatures.new("MC2WorldCollisionData")
    armature = bpy.data.objects.new("MC2WorldCollision", data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    control = data.edit_bones.new("Control")
    control.head = (0.0, 0.0, 0.0)
    control.tail = (0.0, 0.0, 0.2)
    parent = control
    for index in range(3):
        bone = data.edit_bones.new(f"Chain{index}")
        bone.head = (0.0, index * 0.25, 0.2)
        bone.tail = (0.0, (index + 1) * 0.25, 0.2)
        bone.parent = parent
        bone.use_connect = False
        parent = bone
    static = data.edit_bones.new("StaticCollider")
    static.head = (0.03, 0.25, 0.2)
    static.tail = (0.03, 0.45, 0.2)
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    return armature


def _make_simple_collider():
    collider = bpy.data.objects.new("MC2WorldSimpleCollider", None)
    collider.location = (0.03, 0.25, 0.2)
    collider.empty_display_type = "SPHERE"
    bpy.context.scene.collection.objects.link(collider)
    props = collider.hotools_object_collision
    props.enabled = True
    props.collision_type = "SPHERE"
    props.radius = 0.08
    props.primary_collision_group = 7
    return collider


def _remove_object(obj) -> None:
    if obj is None:
        return
    data = getattr(obj, "data", None)
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and not data.users:
        bpy.data.armatures.remove(data)


debug_uid = "mc2-bone-world-collision"
world = None
armature = None
collider = None
registered_here = not physics_blender.is_registered()
if registered_here:
    physics_blender.register()
try:
    armature = _make_armature()
    collider = _make_simple_collider()
    default_objects, default_count = mc2_nodes.physicsMC2BoneClothCustomObject(
        [{"armature": armature, "bone": "Control"}],
    )
    assert default_count == 1
    assert default_objects[0].explicit_properties.collided_by_groups == 0
    custom_objects, count = mc2_nodes.physicsMC2BoneClothCustomObject(
        [{"armature": armature, "bone": "Control"}],
        collided_by_groups=1 << (7 - 1),
    )
    assert count == 1
    assert custom_objects[0].explicit_properties.collided_by_groups == 64
    for name in ("Chain0", "Chain1", "Chain2"):
        props = armature.data.bones[name].hotools_collision
        props.collision_type = "SPHERE"
        props.radius = 0.025
        props.primary_collision_group = 3
        props.collided_by_groups = 64
    static_props = armature.data.bones["StaticCollider"].hotools_collision
    static_props.collision_type = "SPHERE"
    static_props.radius = 0.08
    static_props.primary_collision_group = 7
    objects, count = mc2_nodes.physicsMC2BoneClothObject(
        [{"armature": armature, "bone": "Control"}],
    )
    assert count == 1
    assert objects[0].explicit_properties.collided_by_groups == 0
    assert (
        objects[0].explicit_properties.particle_collision_mask_source
        == "bone_collision_mask"
    )
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.0,
        stabilization_time_after_reset=0.0,
        radius=0.025,
        collision_mode=1,
        collision_friction=0.0,
        self_collision_mode=0,
    )
    partitions, _partition_ids = mc2_nodes.physicsMC2BoneClothTask(
        objects,
        profile=profile,
        connection_mode=0,
        teleport_mode=0,
    )
    requests, _report = mc2_nodes.physicsMC2BoneCollector(partitions)
    request = requests[0]
    assert request.plan.active_partitions[0].setup_options.collided_by_groups == 0

    scene = bpy.context.scene
    scope = physics_nodes.physicsObjectScope(
        [armature, collider],
        include_passive_collision=True,
        include_bone_collision=True,
        include_rigid_body=False,
        include_rigid_constraint=False,
    )
    scene.frame_set(1)
    world, frame, collider_count, _restart = physics_nodes.physicsWorldBegin(
        None,
        scene,
        scope,
    )
    assert frame == 1 and collider_count == 5
    assert len(world.collider_snapshot["colliders"]) == 5
    returned, ready, status = mc2_nodes.physicsMC2Step(
        world,
        requests,
        simulation_frequency=30,
        max_simulation_count_per_frame=1,
    )
    assert returned is world and ready is True, status

    slot_id = product_slot.make_mc2_product_slot_id(
        request.setup_type,
        request.domain_signature,
    )
    slot = world.solver_slots[slot_id]
    assert slot.data["collection"].draft.external_collision_masks == (0,)
    assert slot.data["collider_frame"].collider_count == 2
    assert slot.data["owner"].compiled.fragments[0].particle_external_collision_masks.tolist() == [64] * 4
    assert debug_draw.update_mc2_debug_draw_store(
        debug_uid,
        world,
        True,
        show_collision=True,
        show_collision_contacts=True,
        show_radii=True,
    ) is not None

    scene.frame_set(2)
    world, frame, collider_count, _restart = physics_nodes.physicsWorldBegin(
        world,
        scene,
        scope,
    )
    assert frame == 2 and collider_count == 5
    returned, ready, status = mc2_nodes.physicsMC2Step(
        world,
        requests,
        simulation_frequency=30,
        max_simulation_count_per_frame=1,
    )
    assert returned is world and ready is True, status
    slot = world.solver_slots[slot_id]
    second_positions = slot.data["owner"].read_output().world_positions
    assert abs(float(second_positions[1, 0])) > 0.05
    snapshot = slot.data.get("_debug_draw_snapshot")
    assert isinstance(snapshot, dict), slot.data.get("_debug_capture_state")
    collision = snapshot["collision"]
    assert collision["collision_masks"].tolist() == [0]
    assert collision["particle_collision_masks"].tolist() == [64] * 4
    assert collision["colliders"]["collided_by_groups"] == 64
    assert set(collision["colliders"]["keys"]) == {
        f"obj:{int(collider.as_pointer())}:0",
        (
            f"bone:{int(armature.as_pointer())}:"
            f"{int(armature.data.as_pointer())}:StaticCollider"
        ),
    }
    contacts = snapshot["native"]["external_contacts"]
    assert int(contacts["temporal"]["active_count"]) > 0
    normals = np.asarray(
        slot.data["owner"].read_debug_state()["world_normals"],
        dtype=np.float32,
    )
    assert float(np.max(np.linalg.norm(normals, axis=1))) > 1.0e-5

    debug_draw.update_mc2_debug_draw_store(
        debug_uid,
        world,
        True,
        show_collision=True,
        show_collision_contacts=True,
        show_radii=True,
    )
    draw_state = debug_draw.mc2_debug_draw_store_snapshot(debug_uid)
    assert draw_state is not None and int(draw_state["batch_count"]) > 0
finally:
    debug_draw.clear_mc2_debug_draw_store(node_uid=debug_uid)
    if world is not None:
        world.omni_cache_dispose("MC2 shared simple collision cleanup")
    _remove_object(collider)
    _remove_object(armature)
    if registered_here:
        physics_blender.unregister()


print("MC2 BoneCloth shared simple collision: PASS")
