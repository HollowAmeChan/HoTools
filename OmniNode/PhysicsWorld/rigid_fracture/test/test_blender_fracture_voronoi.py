# -*- coding: utf-8 -*-
"""Blender 4.5/5.2 acceptance for the uniform Voronoi fracture preview."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


HOTOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), *("..",) * 4))
PW_ROOT = os.path.join(HOTOOLS, "OmniNode", "PhysicsWorld")
for path in (os.path.dirname(HOTOOLS), HOTOOLS):
    if path not in sys.path:
        sys.path.insert(0, path)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.PhysicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


registry = importlib.import_module("HoTools.OmniNode.PhysicsWorld.blender_registry")
rigid_properties = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid.properties")
fracture_properties = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.properties")
fracture = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.authoring")
fracture_gn = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.geometry_nodes")


def _register():
    registry.unregister_all_blender_property_domains()
    registry.register_blender_property_domain(
        "fracture_voronoi_asset_test",
        fracture_properties.RIGID_FRACTURE_BLENDER_PROPERTIES,
    )
    registry.register_blender_property_domain(
        "fracture_voronoi_rigid_test",
        rigid_properties.RIGID_BLENDER_PROPERTIES,
    )


def _cube_mesh():
    vertices = [
        (x, y, z)
        for x, y, z in (
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        )
    ]
    faces = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    mesh = bpy.data.meshes.new("VoronoiFractureCubeMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    return mesh


def main():
    _register()
    try:
        source = bpy.data.objects.new("VoronoiFractureCube", _cube_mesh())
        bpy.context.scene.collection.objects.link(source)
        bpy.context.view_layer.objects.active = source
        source.select_set(True)

        props = source.hotools_rigid_fracture
        props.enabled = True
        modifier = fracture.ensure_fracture_preview_modifier(source)
        fracture_gn.set_voronoi_modifier_inputs(
            modifier,
            density=3,
            seed=7,
            randomness=0.72,
        )
        fracture.ensure_product_collection(source)

        rigid = source.hotools_rigid_body
        rigid.mass = 24.0
        rigid.friction = 0.28
        rigid.restitution = 0.12
        rigid.start_deactivated = True

        pieces = fracture.refresh_fracture_products(source)
        assert len(pieces) == 27, len(pieces)
        world_vertices = [
            piece.matrix_world @ vertex.co
            for piece in pieces
            for vertex in piece.data.vertices
        ]
        outer_minimum = tuple(min(point[axis] for point in world_vertices) for axis in range(3))
        outer_maximum = tuple(max(point[axis] for point in world_vertices) for axis in range(3))
        assert all(abs(value + 1.0) < 1.0e-5 for value in outer_minimum), outer_minimum
        assert all(abs(value - 1.0) < 1.0e-5 for value in outer_maximum), outer_maximum
        assert props.fracture_method == fracture_gn.FRACTURE_METHOD_VORONOI_UNIFORM
        assert props.piece_id_attribute == fracture_gn.FRACTURE_PIECE_ID_ATTRIBUTE
        assert fracture_gn.fracture_method_from_group(modifier.node_group) == props.fracture_method
        assert any(node.bl_idname == "GeometryNodeObjectInfo" for node in modifier.node_group.nodes)
        assert not any(node.bl_idname == "GeometryNodeMeshBoolean" for node in modifier.node_group.nodes)
        assert props.cutter_object is not None
        assert tuple(props.cutter_object["hotools_voronoi_counts"]) == (3, 3, 3)
        assert any(
            node.bl_idname == "GeometryNodeStoreNamedAttribute"
            and node.inputs["Name"].default_value == fracture_gn.FRACTURE_PIECE_ID_ATTRIBUTE
            for node in modifier.node_group.nodes
        )

        ids = {piece.hotools_rigid_fracture_piece.piece_id for piece in pieces}
        assert len(ids) == len(pieces)
        assert all(piece.hotools_rigid_fracture_piece.volume > 0.0 for piece in pieces)
        total_volume = sum(
            piece.hotools_rigid_fracture_piece.volume
            for piece in pieces
        )
        assert abs(total_volume - 8.0) < 1.0e-5, total_volume
        assert all(piece.hotools_rigid_fracture_piece.mass_fraction > 0.0 for piece in pieces)
        authored_masses = tuple(piece.hotools_rigid_body.mass for piece in pieces)
        assert abs(sum(authored_masses) - 24.0) < 1.0e-4, (
            len(pieces), sum(authored_masses)
        )
        assert all(abs(piece.hotools_rigid_body.friction - 0.28) < 1.0e-6 for piece in pieces)
        assert all(abs(piece.hotools_rigid_body.restitution - 0.12) < 1.0e-6 for piece in pieces)
        assert all(piece.hotools_rigid_body.start_deactivated for piece in pieces)

        rigid.mass = 120.0
        rigid.friction = 0.9
        assert tuple(piece.hotools_rigid_body.mass for piece in pieces) == authored_masses
        assert all(abs(piece.hotools_rigid_body.friction - 0.28) < 1.0e-6 for piece in pieces)

        count = fracture.delete_fracture_products(source)
        assert count == len(pieces)
        assert props.product_collection is None and props.product_status == "EMPTY"
        print(
            "[PASS] managed uniform Voronoi fracture: "
            f"pieces={count}, fixed_snapshot=1, fixed_id=1"
        )
    finally:
        registry.unregister_blender_property_domain("fracture_voronoi_rigid_test", force=True)
        registry.unregister_blender_property_domain("fracture_voronoi_asset_test", force=True)


if __name__ == "__main__":
    main()
