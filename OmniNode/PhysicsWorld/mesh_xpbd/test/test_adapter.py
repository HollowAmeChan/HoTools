"""Mesh XPBD source topology、reference 与 common collider adapter 测试。"""

from __future__ import annotations

import importlib
import os
import sys
import types

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


class _Collection(list):
    def foreach_get(self, name, output):
        values = []
        for item in self:
            value = getattr(item, name)
            values.extend(tuple(value) if hasattr(value, "__iter__") else (value,))
        output[:] = values


class _Value:
    def __init__(self, **values):
        self.__dict__.update(values)


class _Data:
    def __init__(self, pointer=201):
        self._pointer = pointer
        self.vertices = _Collection([
            _Value(co=(0, 0, 0), groups=[]),
            _Value(co=(1, 0, 0), groups=[]),
            _Value(co=(1, 1, 0), groups=[]),
            _Value(co=(0, 1, 0), groups=[]),
        ])
        self.edges = _Collection([
            _Value(vertices=(0, 1)),
            _Value(vertices=(1, 2)),
            _Value(vertices=(2, 3)),
            _Value(vertices=(0, 3)),
            _Value(vertices=(0, 2)),
        ])
        self.loop_triangles = _Collection([
            _Value(vertices=(0, 1, 2)),
            _Value(vertices=(0, 2, 3)),
        ])
        self.shape_keys = None

    def as_pointer(self):
        return self._pointer

    def calc_loop_triangles(self):
        return None


class _Groups(dict):
    pass


class _Object:
    def __init__(self, pointer=101, data=None):
        self._pointer = pointer
        self.data = data or _Data()
        self.type = "MESH"
        self.name = self.name_full = "AdapterMesh"
        self.vertex_groups = _Groups()
        self.matrix_world = np.identity(4, dtype=np.float32)

    def as_pointer(self):
        return self._pointer


def test_topology_includes_basis_edges_triangulation_and_bend_pair():
    source = _Object()
    task = specs.MeshXpbdTaskSpec(source)
    topology = topology_module.build_mesh_xpbd_topology(task)
    assert topology.particle_count == 4
    assert topology.stretch_indices.shape == (5, 2)
    assert topology.loop_triangles.shape == (2, 3)
    assert topology.bend_indices.tolist() == [[1, 3]]
    assert all(not value.flags.writeable for value in (
        topology.rest_local_positions,
        topology.stretch_indices,
        topology.loop_triangles,
        topology.bend_indices,
        topology.inverse_masses,
        topology.local_collision_radii,
    ))

    source.data.loop_triangles = _Collection([
        _Value(vertices=(0, 1, 3)),
        _Value(vertices=(1, 2, 3)),
    ])
    changed = topology_module.build_mesh_xpbd_topology(task)
    assert changed.topology_signature != topology.topology_signature

    source.data.loop_triangles = _Collection([
        _Value(vertices=(0, 1, 2)),
        _Value(vertices=(0, 2, 3)),
    ])
    source.data.vertices.append(_Value(co=(2, 2, 0), groups=[]))
    isolated_vertex = topology_module.build_mesh_xpbd_topology(task)
    assert isolated_vertex.particle_count == 5
    assert isolated_vertex.topology_signature != topology.topology_signature


def test_pin_and_radius_groups_are_resolved_into_static_arrays():
    source = _Object()
    source.vertex_groups["Pin"] = _Value(index=2)
    source.vertex_groups["Radius"] = _Value(index=3)
    source.data.vertices[0].groups = [_Value(group=2, weight=1.0)]
    source.data.vertices[1].groups = [_Value(group=3, weight=0.5)]
    task = specs.MeshXpbdTaskSpec(
        source,
        pin_enabled=True,
        pin_vertex_group="Pin",
        collision_enabled=True,
        collision_radius=0.2,
        radius_vertex_group="Radius",
        collided_by_groups=1,
    )
    topology = topology_module.build_mesh_xpbd_topology(task)
    np.testing.assert_array_equal(topology.inverse_masses, (0, 1, 1, 1))
    np.testing.assert_allclose(topology.local_collision_radii, (0, 0.1, 0, 0))

    source.data.vertices[2].co = (2, 2, 0)
    reference_changed = topology_module.build_mesh_xpbd_topology(task)
    assert reference_changed.topology_signature == topology.topology_signature
    assert reference_changed.static_signature != topology.static_signature


def test_reference_frame_transforms_positions_radii_and_offsets():
    source = _Object()
    task = specs.MeshXpbdTaskSpec(
        source,
        collision_enabled=True,
        collision_radius=0.25,
    )
    topology = topology_module.build_mesh_xpbd_topology(task)
    source.matrix_world = np.asarray((
        (2, 0, 0, 10),
        (0, 3, 0, 20),
        (0, 0, 4, 30),
        (0, 0, 0, 1),
    ), dtype=np.float32)
    frame = topology_module.build_mesh_xpbd_reference_frame(topology, source)
    np.testing.assert_allclose(frame.rest_world_positions[2], (12, 23, 30))
    np.testing.assert_allclose(frame.world_collision_radii, np.ones(4))
    moved = np.array(frame.rest_world_positions, copy=True)
    moved[:, 0] += 2.0
    local = frame.local_offsets(moved)
    np.testing.assert_allclose(local, np.tile((1, 0, 0), (4, 1)))


def _collider_owner(pointer):
    return _Object(pointer=pointer, data=_Data(pointer + 1000))


def test_common_snapshot_packs_all_shapes_and_zero_mask_is_empty():
    source = _Object()
    other = _collider_owner(501)
    snapshot = {
        "frame": 8,
        "colliders": [
            {"key": "sphere", "owner": other, "type": "SPHERE", "center": (0, 0, 0), "radius": 1, "primary_group": 1},
            {"key": "capsule", "owner": other, "type": "CAPSULE", "center": (0, 0, 0), "segment_a": (-1, 0, 0), "segment_b": (1, 0, 0), "radius": 0.5, "primary_group": 1},
            {"key": "plane", "owner": other, "type": "PLANE", "center": (0, 0, 0), "normal": (0, 0, 2), "primary_group": 1},
            {"key": "box", "owner": other, "type": "BOX", "center": (0, 0, 0), "box_axis_x": (1, 0, 0), "box_axis_y": (0, 2, 0), "box_axis_z": (0, 0, 3), "primary_group": 1},
            {"key": "self", "owner": source, "type": "SPHERE", "center": (0, 0, 0), "radius": 9, "primary_group": 1},
        ],
    }
    empty = colliders.build_mesh_xpbd_collider_frame(snapshot, source, 0)
    assert empty.collider_count == 0
    packed = colliders.build_mesh_xpbd_collider_frame(snapshot, source, 1)
    assert packed.collider_count == 4
    assert packed.collider_types.tolist() == [0, 1, 2, 3]
    np.testing.assert_allclose(packed.collider_segment_a[2], (0, 0, 1))
    assert packed.collider_radii[3] == 3.0


def test_native_owner_rebuild_update_reset_step_and_dispose():
    assert native.is_available()
    source = _Object()
    task = specs.MeshXpbdTaskSpec(source, gravity_power=0.0)
    topology = topology_module.build_mesh_xpbd_topology(task)
    reference = topology_module.build_mesh_xpbd_reference_frame(topology, source)
    collider_frame = colliders.build_mesh_xpbd_collider_frame({}, source, 0)
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
    assert owner.stats()["particle_count"] == 4
    owner.update_parameters(specs.MeshXpbdTaskSpec(source, iterations=4))
    owner.update_reference(topology, reference)
    owner.dispose()
    assert owner.ready is False


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"Mesh XPBD adapter: {len(tests)} passed")
