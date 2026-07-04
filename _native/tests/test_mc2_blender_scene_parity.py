import copy
import os
import sys
import types
from pathlib import Path

import bpy
import mathutils
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
NATIVE_TEST_DIR = os.environ.get("HOTOOLS_NATIVE_TEST_DIR")
if NATIVE_TEST_DIR:
    sys.path.insert(0, NATIVE_TEST_DIR)


def ensure_package(name, path):
    module = sys.modules.get(name)
    if module is not None:
        return module
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    sys.modules[name] = module
    return module


ensure_package("HoTools", ROOT)
ensure_package("HoTools.PhysicsTools", ROOT / "PhysicsTools")
ensure_package("HoTools.OmniNode", ROOT / "OmniNode")
ensure_package("HoTools.OmniNode.NodeTree", ROOT / "OmniNode" / "NodeTree")
ensure_package("HoTools.OmniNode.NodeTree.Function", ROOT / "OmniNode" / "NodeTree" / "Function")
ensure_package(
    "HoTools.OmniNode.NodeTree.Function.physicsMC2MeshCloth",
    ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsMC2MeshCloth",
)

from bpy.props import PointerProperty  # noqa: E402
from HoTools.PhysicsTools.physicsProperty import (  # noqa: E402
    PG_Hotools_BoneCollision,
    PG_Hotools_MeshCollision,
    PG_Hotools_ObjectCollision,
)
from HoTools.OmniNode.NodeTree.Function.physicsMC2MeshCloth import collision, mesh_build, solver, state as mc2_state  # noqa: E402
from HoTools.OmniNode.NodeTree.Function.physicsMC2MeshCloth.constants import MC2SystemConstants  # noqa: E402


def ensure_physics_props():
    if hasattr(bpy.types.Object, "hotools_mesh_collision"):
        return
    for cls in (PG_Hotools_BoneCollision, PG_Hotools_ObjectCollision, PG_Hotools_MeshCollision):
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass
    bpy.types.Bone.hotools_collision = PointerProperty(type=PG_Hotools_BoneCollision)
    bpy.types.Object.hotools_object_collision = PointerProperty(type=PG_Hotools_ObjectCollision)
    bpy.types.Object.hotools_mesh_collision = PointerProperty(type=PG_Hotools_MeshCollision)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def make_grid_object(cols=5, rows=5, spacing=0.22):
    vertices = []
    faces = []
    x_offset = (cols - 1) * spacing * 0.5
    for row in range(rows):
        for col in range(cols):
            vertices.append((col * spacing - x_offset, 0.0, -row * spacing))
    for row in range(rows - 1):
        for col in range(cols - 1):
            i = row * cols + col
            faces.append((i, i + 1, i + cols + 1, i + cols))
    mesh = bpy.data.meshes.new("MC2ParityGridMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("MC2ParityGrid", mesh)
    bpy.context.collection.objects.link(obj)
    obj.shape_key_add(name="Basis")

    pin_group = obj.vertex_groups.new(name="PinTop")
    pin_group.add(list(range(cols)), 1.0, "ADD")

    props = obj.hotools_mesh_collision
    props.enabled = True
    props.radius = 0.045
    props.pin_enabled = True
    props.pin_vertex_group = "PinTop"
    props.collided_by_groups = 1
    props.self_collision_enabled = True
    props.self_collision_surface_thickness = 0.005
    props.mass = 0.0
    return obj


def make_collider():
    collider = bpy.data.objects.new("MC2ParityMovingSphere", None)
    bpy.context.collection.objects.link(collider)
    props = collider.hotools_object_collision
    props.collision_type = "SPHERE"
    props.radius = 0.18
    props.primary_collision_group = 1
    return collider


def make_box_collider():
    collider = bpy.data.objects.new("MC2ParityBox", None)
    bpy.context.collection.objects.link(collider)
    props = collider.hotools_object_collision
    props.collision_type = "BOX"
    props.box_size = (0.6, 0.6, 0.6)
    props.offset = (0.15, -0.2, 0.0)
    props.primary_collision_group = 1
    return collider


def clone_state(value):
    result = {}
    for key, item in value.items():
        if isinstance(item, np.ndarray):
            result[key] = item.copy()
        elif isinstance(item, dict):
            result[key] = copy.deepcopy(item)
        else:
            result[key] = item
    return result


def build_initial_state(obj):
    mesh_light = mesh_build.mesh_light_key(obj)
    mesh_signature = mesh_build.mesh_signature_key(obj)
    output_key = "MC2Delta"
    config = mesh_build.config_key(obj, output_key, mesh_signature, 0.0)
    state = mc2_state.build_state(obj, output_key, mesh_light, mesh_signature, config, 0.0)
    assert "self_collision_inv_masses" in state
    assert "self_collision_enabled" in state
    assert "self_collision_surface_thickness" in state
    assert "self_collision_mass" in state
    return state


def scene_colliders(scene):
    snapshot = collision.build_collision_snapshot_from_scene(scene, True, True, False)
    return list(snapshot.get("colliders") or [])


def stretch_error(state):
    positions = np.ascontiguousarray(state["display_positions"], dtype=np.float32)
    edge_i = np.ascontiguousarray(state["edge_i"], dtype=np.int32)
    edge_j = np.ascontiguousarray(state["edge_j"], dtype=np.int32)
    edge_rest = np.abs(np.ascontiguousarray(state["edge_rest"], dtype=np.float32))
    if len(edge_i) == 0:
        return 0.0
    lengths = np.linalg.norm(positions[edge_i] - positions[edge_j], axis=1)
    return float(np.max(np.abs(lengths - edge_rest)))


def collision_count(state):
    normals = np.ascontiguousarray(state["collision_normals"], dtype=np.float32)
    if normals.size == 0:
        return 0
    return int(np.count_nonzero(np.linalg.norm(normals, axis=1) > MC2SystemConstants.EPSILON))


def solve_one(state, obj, scene, colliders, cpp, collider_collision_mode):
    func = solver.solve_meshcloth_native_core if cpp else solver.solve_meshcloth
    return func(
        state,
        obj,
        scene,
        2,
        3,
        mathutils.Vector((0.0, -1.0, 0.0)),
        5.0,
        0.03,
        0.85,
        0.35,
        0.2,
        80.0,
        0.75,
        0.0,
        0.4,
        0.0,
        0.1,
        0.0,
        5.0,
        720.0,
        -1.0,
        -1.0,
        4.0,
        0,
        0.5,
        90.0,
        0.0,
        0.0,
        0.0,
        0.18,
        collider_collision_mode,
        None,
        colliders,
    )


def run_parity_for_mode(collider_collision_mode):
    ensure_physics_props()
    clear_scene()
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.fps_base = 1.0

    cloth = make_grid_object()
    collider = make_collider()
    box_collider = make_box_collider()
    bpy.context.view_layer.update()
    initial = build_initial_state(cloth)
    py_state = clone_state(initial)
    cpp_state = clone_state(initial)

    max_delta = 0.0
    max_rms = 0.0
    max_stretch_delta = 0.0
    max_collision_delta = 0
    for frame in range(1, 13):
        scene.frame_set(frame)
        collider.location = (0.12 * np.sin(frame * 0.55), -0.18, -0.42 + frame * 0.01)
        box_collider.rotation_euler = (0.0, 0.0, frame * 0.07)
        bpy.context.view_layer.update()
        colliders = scene_colliders(scene)

        py_state = solve_one(py_state, cloth, scene, colliders, False, collider_collision_mode)
        cpp_state = solve_one(cpp_state, cloth, scene, colliders, True, collider_collision_mode)

        delta = np.ascontiguousarray(py_state["display_positions"] - cpp_state["display_positions"], dtype=np.float32)
        frame_max = float(np.max(np.linalg.norm(delta, axis=1)))
        frame_rms = float(np.sqrt(np.mean(np.sum(delta * delta, axis=1))))
        max_delta = max(max_delta, frame_max)
        max_rms = max(max_rms, frame_rms)
        max_stretch_delta = max(max_stretch_delta, abs(stretch_error(py_state) - stretch_error(cpp_state)))
        max_collision_delta = max(max_collision_delta, abs(collision_count(py_state) - collision_count(cpp_state)))

    print(
        "MC2 Blender scene parity: "
        f"collision_mode={collider_collision_mode} frames=12 "
        f"max_delta={max_delta:.8f} rms={max_rms:.8f} "
        f"stretch_delta={max_stretch_delta:.8f} collision_count_delta={max_collision_delta}"
    )
    if max_delta > 5e-4 or max_rms > 2e-4:
        raise AssertionError(f"display position parity failed: max={max_delta} rms={max_rms}")
    if max_stretch_delta > 5e-4:
        raise AssertionError(f"stretch error parity failed: {max_stretch_delta}")
    if max_collision_delta != 0:
        raise AssertionError(f"collision count parity failed: {max_collision_delta}")


def run_parity():
    for collider_collision_mode in (1, 2):
        run_parity_for_mode(collider_collision_mode)


if __name__ == "__main__":
    run_parity()
