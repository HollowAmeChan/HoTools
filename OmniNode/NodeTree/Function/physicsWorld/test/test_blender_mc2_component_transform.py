"""Blender component-transform contract for parented MC2 negative scale."""

from __future__ import annotations

import importlib
import math
import os
import sys
import types

import bpy
from mathutils import Matrix, Quaternion
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")

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


frame_input = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.frame_input"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)


def _update_depsgraph():
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return depsgraph


def _linear(matrix) -> np.ndarray:
    return np.asarray(
        [[float(matrix[row][column]) for column in range(3)] for row in range(3)],
        dtype=np.float64,
    )


def _expect_snapshot_value_error(source, base_obj, signature, frame, message: str) -> None:
    depsgraph = _update_depsgraph()
    try:
        frame_input.read_base_pose_frame_snapshot(
            source,
            base_obj,
            mesh_topology_signature=signature,
            frame=frame,
            depsgraph=depsgraph,
            cache={},
        )
    except ValueError as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"expected ValueError containing {message!r}")


def test_parented_negative_scale_component_transform():
    parent = None
    source = None
    base_obj = None
    physics_blender.register()
    try:
        parent = bpy.data.objects.new("MC2_ComponentParent", None)
        bpy.context.scene.collection.objects.link(parent)
        mesh = bpy.data.meshes.new("MC2_ComponentSourceMesh")
        mesh.from_pydata(
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            (),
            ((0, 1, 2),),
        )
        source = bpy.data.objects.new("MC2_ComponentSource", mesh)
        bpy.context.scene.collection.objects.link(source)
        source.parent = parent
        source.matrix_parent_inverse = Matrix.Identity(4)

        parent.location = (2.0, -1.0, 3.0)
        parent.rotation_euler = (0.0, math.radians(30.0), 0.0)
        parent.scale = (2.0, 1.5, 0.75)
        source.location = (0.0, 0.0, 0.0)
        source.rotation_euler = (0.0, 0.0, 0.0)
        source.scale = (-1.0, 1.0, 1.0)

        signature = base_pose.mesh_topology_signature(source)
        base_obj = base_pose.ensure_base_pose_proxy(
            source,
            expected_mesh_topology_signature=signature,
        )
        assert base_obj.parent == parent
        depsgraph = _update_depsgraph()
        snapshot = frame_input.read_base_pose_frame_snapshot(
            source,
            base_obj,
            mesh_topology_signature=signature,
            frame=1,
            depsgraph=depsgraph,
            cache={},
        )
        np.testing.assert_allclose(
            snapshot.component_world_position,
            parent.location,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            snapshot.component_world_scale,
            (-2.0, 1.5, 0.75),
            atol=1.0e-6,
        )
        rotation = snapshot.component_world_rotation_xyzw
        rotation_matrix = Quaternion(
            (rotation[3], rotation[0], rotation[1], rotation[2])
        ).to_matrix()
        reconstructed = _linear(rotation_matrix.to_4x4()) @ np.diag(
            snapshot.component_world_scale
        )
        np.testing.assert_allclose(
            reconstructed,
            snapshot.source_world_linear,
            atol=1.0e-6,
        )
        evaluated_base = base_obj.evaluated_get(depsgraph)
        expected_positions = np.asarray(
            [
                tuple(evaluated_base.matrix_world @ vertex.co)
                for vertex in evaluated_base.data.vertices
            ],
            dtype=np.float32,
        )
        np.testing.assert_allclose(
            snapshot.animated_base_world_positions,
            expected_positions,
            atol=1.0e-6,
        )

        parent.scale = (2.0, 1.0, 0.5)
        source.rotation_euler = (0.0, math.radians(45.0), 0.0)
        base_obj.rotation_euler = source.rotation_euler
        _expect_snapshot_value_error(source, base_obj, signature, 2, "shear-free")

        parent.scale = (-1.0, 1.0, 1.0)
        source.rotation_euler = (0.0, 0.0, 0.0)
        source.scale = (1.0, 1.0, 1.0)
        base_obj.rotation_euler = source.rotation_euler
        base_obj.scale = source.scale
        _expect_snapshot_value_error(
            source,
            base_obj,
            signature,
            3,
            "negative scale inherited from a parent",
        )
    finally:
        if base_obj is not None:
            mesh = base_obj.data
            bpy.data.objects.remove(base_obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        if source is not None:
            mesh = source.data
            bpy.data.objects.remove(source, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        if parent is not None:
            bpy.data.objects.remove(parent, do_unlink=True)
        if physics_blender.is_registered():
            physics_blender.unregister()


def main():
    test_parented_negative_scale_component_transform()
    print("MC2 parented negative-scale component transform: PASS")


if __name__ == "__main__":
    main()
