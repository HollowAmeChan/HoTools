"""Mesh XPBD topology/reference/native adapter 的 Blender 4.5 验收。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
from mathutils import Matrix
import numpy as np


MESH_XPBD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MESH_XPBD_ROOT)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
OMNINODE = os.path.dirname(FUNCTION)
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", FUNCTION),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

specs = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mesh_xpbd.specs")
topology_module = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.topology"
)
colliders = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.colliders"
)
native = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mesh_xpbd.native")


def test_real_blender_mesh_adapter_roundtrip():
    mesh = bpy.data.meshes.new("MeshXpbdAdapterMesh")
    mesh.from_pydata(
        ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)),
        (),
        ((0, 1, 2), (0, 2, 3)),
    )
    mesh.update()
    source = bpy.data.objects.new("MeshXpbdAdapterObject", mesh)
    bpy.context.scene.collection.objects.link(source)
    collider_mesh = bpy.data.meshes.new("MeshXpbdAdapterColliderMesh")
    collider = bpy.data.objects.new("MeshXpbdAdapterCollider", collider_mesh)
    bpy.context.scene.collection.objects.link(collider)
    try:
        source.shape_key_add(name="Basis")
        pin = source.vertex_groups.new(name="Pin")
        pin.add((0,), 1.0, "REPLACE")
        radius = source.vertex_groups.new(name="Radius")
        radius.add((1,), 0.5, "REPLACE")
        source.matrix_world = Matrix((
            (2.0, 0.0, 0.0, 10.0),
            (0.0, 3.0, 0.0, 20.0),
            (0.0, 0.0, 4.0, 30.0),
            (0.0, 0.0, 0.0, 1.0),
        ))
        task = specs.MeshXpbdTaskSpec(
            source,
            pin_enabled=True,
            pin_vertex_group="Pin",
            collision_enabled=True,
            collision_radius=0.2,
            radius_vertex_group="Radius",
            collided_by_groups=1,
            gravity_power=0.0,
        )
        topology = topology_module.build_mesh_xpbd_topology(task)
        reference = topology_module.build_mesh_xpbd_reference_frame(topology, source)
        assert topology.particle_count == 4
        assert topology.stretch_indices.shape == (5, 2)
        assert topology.bend_indices.tolist() == [[1, 3]]
        np.testing.assert_array_equal(topology.inverse_masses, (0, 1, 1, 1))
        np.testing.assert_allclose(topology.local_collision_radii, (0, 0.1, 0, 0))
        np.testing.assert_allclose(reference.rest_world_positions[2], (12, 23, 30))

        snapshot = {
            "frame": 1,
            "colliders": [{
                "key": "adapter:sphere",
                "owner": collider,
                "type": "SPHERE",
                "center": (100, 100, 100),
                "radius": 1.0,
                "primary_group": 1,
            }],
        }
        collider_frame = colliders.build_mesh_xpbd_collider_frame(
            snapshot, source, task.collided_by_groups
        )
        owner = native.MeshXpbdNativeContext()
        owner.rebuild(topology, reference, task)
        owner.reset(reference)
        positions = owner.step(
            delta_time=1.0 / 24.0,
            substeps=1,
            gravity_direction=task.gravity_direction,
            gravity_power=task.gravity_power,
            colliders=collider_frame,
            collided_by_groups=task.collided_by_groups,
        )
        np.testing.assert_allclose(positions, reference.rest_world_positions)
        owner.dispose()
    finally:
        bpy.data.objects.remove(source, do_unlink=True)
        bpy.data.objects.remove(collider, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        bpy.data.meshes.remove(collider_mesh)


if __name__ == "__main__":
    test_real_blender_mesh_adapter_roundtrip()
    print("PASS test_real_blender_mesh_adapter_roundtrip")
