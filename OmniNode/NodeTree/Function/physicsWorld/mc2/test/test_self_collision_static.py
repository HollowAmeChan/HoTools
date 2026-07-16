import os
import sys
import types

import numpy as np

MC2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MC2_ROOT)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = os.path.dirname(NODETREE)
HOTOOLS = os.path.dirname(OMNINODE)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

from HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.self_collision_static import (
    FLAG_ALL_FIX,
    FLAG_FIX0,
    FLAG_FIX1,
    FLAG_IGNORE,
    MC2SelfCollisionStaticMetadata,
    build_mc2_self_collision_static,
    pack_mc2_self_collision_static,
)
from HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.static_data import (
    make_mc2_proxy_static_spec,
)


def test_source_ordered_primitive_flags_indices_and_depths():
    proxy = make_mc2_proxy_static_spec(
        task_id="self-static",
        setup_type="mesh_cloth",
        vertex_identities=("v0", "v1", "v2", "v3"),
        local_positions=((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)),
        local_normals=((0, 0, 1),) * 4,
        local_tangents=((1, 0, 0),) * 4,
        uvs=((0, 0), (1, 0), (0, 1), (1, 1)),
        vertex_attributes=(0x01, 0x02, 0x00, 0x82),
        edges=((0, 1), (1, 2)),
        triangles=((0, 1, 3),),
    )
    spec = build_mc2_self_collision_static(proxy, (0.0, 0.25, 0.5, 1.0))
    assert (spec.point_count, spec.edge_count, spec.triangle_count) == (4, 2, 1)
    assert spec.particle_indices == (
        (0, -1, -1), (1, -1, -1), (2, -1, -1), (3, -1, -1),
        (0, 1, -1), (1, 2, -1), (0, 1, 3),
    )
    assert spec.primitive_flags == (
        FLAG_FIX0 | FLAG_ALL_FIX,
        0,
        FLAG_FIX0 | FLAG_ALL_FIX | FLAG_IGNORE,
        0,
        (1 << 24) | FLAG_FIX0,
        (1 << 24) | FLAG_FIX1 | FLAG_IGNORE,
        (2 << 24) | FLAG_FIX0,
    )
    np.testing.assert_allclose(
        spec.primitive_depths,
        (0.0, 0.25, 0.5, 1.0, 0.125, 0.375, 1.25 / 3.0),
        atol=1.0e-7,
    )
    packed = pack_mc2_self_collision_static(spec)
    assert packed["primitive_flags"].dtype == np.uint32
    assert packed["particle_indices"].shape == (7, 3)
    assert all(not value.flags.writeable for value in packed.values())


def test_line_proxy_registers_only_edge_primitives():
    proxy = make_mc2_proxy_static_spec(
        task_id="self-line",
        setup_type="bone_cloth",
        vertex_identities=("root", "tip"),
        local_positions=((0, 0, 0), (0, 1, 0)),
        local_normals=((0, 1, 0),) * 2,
        local_tangents=((0, 0, 1),) * 2,
        uvs=((0, 0),) * 2,
        vertex_attributes=(0x01, 0x02),
        edges=((0, 1),),
        triangles=(),
    )
    spec = build_mc2_self_collision_static(proxy, (0.0, 1.0))
    assert (spec.point_count, spec.edge_count, spec.triangle_count) == (0, 1, 0)
    assert spec.particle_indices == ((0, 1, -1),)


def test_staged_registration_returns_metadata_without_host_primitive_arrays():
    proxy = make_mc2_proxy_static_spec(
        task_id="self-staged",
        setup_type="mesh_cloth",
        vertex_identities=("v0", "v1", "v2"),
        local_positions=((0, 0, 0), (1, 0, 0), (0, 1, 0)),
        local_normals=((0, 0, 1),) * 3,
        local_tangents=((1, 0, 0),) * 3,
        uvs=((0, 0), (1, 0), (0, 1)),
        vertex_attributes=(0x01, 0x02, 0x02),
        edges=((0, 1), (1, 2), (2, 0)),
        triangles=((0, 1, 2),),
    )
    depths = (0.0, 0.5, 1.0)
    full = build_mc2_self_collision_static(proxy, depths)

    class StagedContext:
        primitive_count = -1

        def update_self_collision_derived(self, derived):
            self.primitive_count = len(derived["primitive_flags"])

    context = StagedContext()
    staged = build_mc2_self_collision_static(
        proxy,
        depths,
        native_context=context,
    )
    assert isinstance(staged, MC2SelfCollisionStaticMetadata)
    assert staged.static_signature == full.static_signature
    assert staged.primitive_count == context.primitive_count == 7
    assert not hasattr(staged, "primitive_flags")
    try:
        pack_mc2_self_collision_static(staged)
    except TypeError as exc:
        assert "full" in str(exc)
    else:
        raise AssertionError("native-owned Self metadata was accepted by the host packer")


if __name__ == "__main__":
    test_source_ordered_primitive_flags_indices_and_depths()
    test_line_proxy_registers_only_edge_primitives()
    test_staged_registration_returns_metadata_without_host_primitive_arrays()
    print("PASS MC2 self-collision static registration")
