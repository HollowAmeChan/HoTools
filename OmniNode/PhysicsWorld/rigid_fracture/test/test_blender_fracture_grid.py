# -*- coding: utf-8 -*-
"""Blender 5.2 acceptance for the managed grid fracture generator."""

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
        "fracture_grid_asset_test",
        fracture_properties.RIGID_FRACTURE_BLENDER_PROPERTIES,
    )
    registry.register_blender_property_domain(
        "fracture_grid_rigid_test",
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
    mesh = bpy.data.meshes.new("GridFractureCubeMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    return mesh


def main():
    _register()
    try:
        source = bpy.data.objects.new("GridFractureCube", _cube_mesh())
        bpy.context.scene.collection.objects.link(source)
        bpy.context.view_layer.objects.active = source
        source.select_set(True)

        props = source.hotools_rigid_fracture
        props.enabled = True
        modifier = fracture.ensure_default_fracture_modifier(source)
        fracture_gn.set_grid_modifier_inputs(modifier, counts=(3, 2, 2), gap=0.04)
        fracture.ensure_product_collection(source)

        rigid = source.hotools_rigid_body
        rigid.mass = 24.0
        rigid.friction = 0.28
        rigid.restitution = 0.12
        rigid.start_deactivated = True

        pieces = fracture.refresh_fracture_products(source)
        assert len(pieces) == 12, len(pieces)
        assert props.piece_id_attribute == fracture_gn.FRACTURE_PIECE_ID_ATTRIBUTE
        assert fracture_gn.is_managed_fracture_group(modifier.node_group)
        assert any(
            node.bl_idname == "GeometryNodeMeshBoolean"
            for node in modifier.node_group.nodes
        )
        assert any(
            node.bl_idname == "GeometryNodeStoreNamedAttribute"
            and node.inputs["Name"].default_value == fracture_gn.FRACTURE_PIECE_ID_ATTRIBUTE
            for node in modifier.node_group.nodes
        )

        ids = {piece.hotools_rigid_fracture_piece.piece_id for piece in pieces}
        assert len(ids) == 12
        assert all(piece.hotools_rigid_fracture_piece.volume > 0.0 for piece in pieces)
        assert all(piece.hotools_rigid_fracture_piece.mass_fraction > 0.0 for piece in pieces)
        assert abs(sum(piece.hotools_rigid_body.mass for piece in pieces) - 24.0) < 1.0e-5
        assert all(abs(piece.hotools_rigid_body.friction - 0.28) < 1.0e-6 for piece in pieces)
        assert all(abs(piece.hotools_rigid_body.restitution - 0.12) < 1.0e-6 for piece in pieces)
        assert all(piece.hotools_rigid_body.start_deactivated for piece in pieces)

        props.mass_mode = "DENSITY"
        props.density = 125.0
        fracture.apply_piece_defaults(source)
        expected_mass = sum(
            piece.hotools_rigid_fracture_piece.volume * props.density
            for piece in pieces
        )
        actual_mass = sum(piece.hotools_rigid_body.mass for piece in pieces)
        assert abs(actual_mass - expected_mass) < 1.0e-4, (actual_mass, expected_mass)
        print(
            "[PASS] managed grid fracture: "
            f"pieces={len(pieces)}, total_mass={actual_mass:.6f}, fixed_id=1"
        )
    finally:
        registry.unregister_blender_property_domain("fracture_grid_rigid_test", force=True)
        registry.unregister_blender_property_domain("fracture_grid_asset_test", force=True)


if __name__ == "__main__":
    main()
