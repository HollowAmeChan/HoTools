"""Shared Blender 5.2 setup helpers for MC2 product acceptance tests."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")
if sys.version_info < (3, 13):
    raise RuntimeError("MC2 产品验收只允许 Python 3.13 / Blender 5.2")
PYTHON_ABI = "py313"
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

for path in (HOTOOLS, os.path.dirname(HOTOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

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


physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
debug_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug"
)
bone_frame_input = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_frame_input"
)
mesh_frame_input = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.frame_input"
)
topology_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)
writeback = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback"
)
hotools_native = importlib.import_module("hotools_native")

print(f"MC2_PRODUCT_TEST_HELPER_SOURCE {__file__}")
print(f"MC2_PRODUCT_TEST_HELPER_NATIVE {hotools_native.__file__}")
assert os.path.commonpath((HOTOOLS, os.path.abspath(__file__))) == HOTOOLS
assert os.path.commonpath(
    (NATIVE_PACKAGE, os.path.abspath(hotools_native.__file__))
) == NATIVE_PACKAGE


def make_armature(name, x_offset, scale):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    obj.location.x = x_offset
    obj.scale = (scale, scale, scale)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    control = data.edit_bones.new("Control")
    control.head = (0.0, -0.12, 0.0)
    control.tail = (0.0, 0.0, 0.0)
    parent = control
    for index in range(5):
        bone = data.edit_bones.new("Root" if index == 0 else f"Bone{index}")
        bone.head = (0.0, index * 0.12, 0.02 * index)
        bone.tail = (0.015 * index, (index + 1) * 0.12, 0.02 * (index + 1))
        bone.parent = parent
        bone.use_connect = index > 0 and index != 3
        parent = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def remove_object(obj) -> None:
    if obj is None:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is None or data.users:
        return
    if isinstance(data, bpy.types.Mesh):
        bpy.data.meshes.remove(data)
    elif isinstance(data, bpy.types.Armature):
        bpy.data.armatures.remove(data)


def set_frame(world, frame, generation, *, raw_dt=None) -> None:
    context = world.frame_context
    context.previous_frame = frame - 1 if frame > 1 else None
    context.frame = frame
    context.same_frame = False
    context.continuous = frame > 1
    frame_dt = 1.0 / 90.0 if raw_dt is None else float(raw_dt)
    context.raw_dt = frame_dt
    context.dt = frame_dt
    context.time_scale = 1.0
    context.generation = generation
    world.generation = generation


__all__ = [
    "bone_frame_input", "debug_module", "mesh_frame_input", "names", "nodes",
    "parameters", "physics_blender", "remove_object", "set_frame",
    "topology_module", "world_types", "writeback", "make_armature",
]
