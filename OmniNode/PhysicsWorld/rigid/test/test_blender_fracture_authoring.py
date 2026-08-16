# -*- coding: utf-8 -*-
"""Blender 5.2 explicit rigid-fracture authoring acceptance."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types

import bpy


HOTOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), *('..',) * 4))
ADDONS = os.path.dirname(HOTOOLS)
PW_ROOT = os.path.join(HOTOOLS, "OmniNode", "PhysicsWorld")
for path in (ADDONS, HOTOOLS):
    if path not in sys.path:
        sys.path.insert(0, path)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.PhysicsWorld", PW_ROOT),
):
    if package_name not in sys.modules:
        module = types.ModuleType(package_name)
        module.__path__ = [package_path]
        module.__package__ = package_name
        sys.modules[package_name] = module


registry = importlib.import_module("HoTools.OmniNode.PhysicsWorld.blender_registry")
rigid_properties = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid.properties")
fracture_properties = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.properties")
fracture = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.authoring")
fracture_resolver = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.resolver")
physics_scope = importlib.import_module("HoTools.OmniNode.PhysicsWorld.scope")
physics_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")
rigid_scope_sync = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid.scope_sync")


def _box_geometry(center, half_extents=(0.45, 0.45, 0.45)):
    cx, cy, cz = center
    hx, hy, hz = half_extents
    vertices = [
        (cx + sx * hx, cy + sy * hy, cz + sz * hz)
        for sx, sy, sz in (
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        )
    ]
    faces = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    return vertices, faces


def _set_boxes(mesh, centers):
    vertices = []
    faces = []
    for center in centers:
        box_vertices, box_faces = _box_geometry(center)
        offset = len(vertices)
        vertices.extend(box_vertices)
        faces.extend(tuple(offset + index for index in face) for face in box_faces)
    mesh.clear_geometry()
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)


def _register():
    registry.unregister_all_blender_property_domains()
    registry.register_blender_property_domain(
        "fracture_asset_test",
        fracture_properties.RIGID_FRACTURE_BLENDER_PROPERTIES,
    )
    registry.register_blender_property_domain(
        "fracture_rigid_test",
        rigid_properties.RIGID_BLENDER_PROPERTIES,
    )


def _cleanup():
    registry.unregister_blender_property_domain("fracture_rigid_test", force=True)
    registry.unregister_blender_property_domain("fracture_asset_test", force=True)


def main():
    _register()
    blend_path = os.path.join(tempfile.gettempdir(), "hotools_fracture_authoring.blend")
    try:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        source_mesh = bpy.data.meshes.new("FractureSourceMesh")
        _set_boxes(source_mesh, ((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
        source = bpy.data.objects.new("FractureSource", source_mesh)
        bpy.context.scene.collection.objects.link(source)
        bpy.context.view_layer.objects.active = source
        source.select_set(True)

        props = source.hotools_rigid_fracture
        props.enabled = True
        fracture.ensure_default_fracture_modifier(source)
        fracture.ensure_product_collection(source, bpy.context.scene)

        pieces1 = fracture.refresh_fracture_products(source)
        assert len(pieces1) == 2
        assert props.product_status == "READY" and props.product_revision == 1
        assert all(piece.hotools_rigid_body.enabled for piece in pieces1)
        assert all(piece.hotools_rigid_body.shape_type == "BOX" for piece in pieces1)
        assert all(piece.hotools_rigid_body.start_deactivated for piece in pieces1)

        edited_id = pieces1[0].hotools_rigid_fracture_piece.piece_id
        pieces1[0].hotools_rigid_body.mass = 7.25
        pieces1[0].hotools_rigid_fracture_piece.breakable = False
        pieces2 = fracture.refresh_fracture_products(source)
        edited = next(piece for piece in pieces2 if piece.hotools_rigid_fracture_piece.piece_id == edited_id)
        assert abs(edited.hotools_rigid_body.mass - 7.25) < 1.0e-6
        assert edited.hotools_rigid_fracture_piece.breakable is False
        assert props.product_revision == 2

        old_names = {piece.name for piece in pieces2}
        old_revision = props.product_revision
        old_modifier_name = props.modifier_name
        props.modifier_name = "missing modifier"
        try:
            fracture.refresh_fracture_products(source)
            raise AssertionError("invalid modifier must fail")
        except fracture.FractureAssetError:
            pass
        assert props.product_status == "READY"
        assert props.product_revision == old_revision
        assert {piece.name for piece in fracture.managed_pieces(source)} == old_names
        props.modifier_name = old_modifier_name

        _set_boxes(source_mesh, ((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (3.0, 0.0, 0.0)))
        source.update_tag()
        bpy.context.view_layer.update()
        pieces3 = fracture.refresh_fracture_products(source)
        assert len(pieces3) == 3 and props.product_revision == 3
        edited = next(piece for piece in pieces3 if piece.hotools_rigid_fracture_piece.piece_id == edited_id)
        assert abs(edited.hotools_rigid_body.mass - 7.25) < 1.0e-6

        source.hotools_rigid_body.enabled = True
        ordinary_mesh = bpy.data.meshes.new("OrdinaryRigidMesh")
        _set_boxes(ordinary_mesh, ((0.0, 4.0, 0.0),))
        ordinary = bpy.data.objects.new("OrdinaryRigid", ordinary_mesh)
        bpy.context.scene.collection.objects.link(ordinary)
        ordinary.hotools_rigid_body.enabled = True
        ordinary.hotools_rigid_body.shape_type = "BOX"

        resolved, metadata, signature = fracture_resolver.resolve_fracture_scope_objects(
            (source, ordinary),
        )
        assert source not in resolved and ordinary in resolved
        assert set(pieces3).issubset(set(resolved)) and len(resolved) == 4
        assert len(metadata) == 3 and len(signature) == 1

        scope = physics_scope.make_scope(
            objects=(source, ordinary),
            include_passive_collision=False,
            include_bone_collision=False,
            include_rigid_body=True,
            include_rigid_constraint=False,
        )
        world = physics_types.PhysicsWorldCache()
        world.frame_context.registration_refresh_required = True
        rigid_scope_sync.collect_rigid_specs_from_scope(world, scope)
        rigid_slots = [slot for slot in world.solver_slots.values() if slot.kind == "rigid_body"]
        assert len(rigid_slots) == 4
        assert all(slot.data["spec"].obj is not source for slot in rigid_slots)
        slot_index = world.backend_resources[fracture_resolver.FRACTURE_SLOT_INDEX_RESOURCE_KEY]
        assert len(slot_index) == 3
        product_batches = world.exchange[physics_scope.PHYSICS_SCOPE_COLLECTION_BATCH_CHANNEL]
        assert len(product_batches) == 1
        assert product_batches[0]["collection"] == props.product_collection
        assert product_batches[0]["object_count"] == 3

        world.frame_context.registration_refresh_required = False
        rigid_scope_sync.collect_rigid_specs_from_scope(world, scope)
        assert len(world.solver_slots) == 4

        props.product_revision += 1
        try:
            fracture_resolver.resolve_fracture_scope_objects((source, ordinary))
            raise AssertionError("stale product revision must block simulation")
        except fracture.FractureAssetError:
            pass
        props.product_revision -= 1

        fracture.set_fracture_visibility(source, "PIECES")
        assert source.hide_get() is True and all(not piece.hide_get() for piece in pieces3)
        fracture.set_fracture_visibility(source, "SOURCE")
        assert source.hide_get() is False and all(piece.hide_get() for piece in pieces3)
        fracture.set_fracture_visibility(source, "BOTH")

        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        source = bpy.data.objects["FractureSource"]
        pieces = fracture.validate_fracture_manifest(source)
        assert len(pieces) == 3
        assert source.hotools_rigid_fracture.product_revision == 3
        print("[PASS] rigid fracture authoring + scope: source excluded, 3 pieces, round-trip valid")
    finally:
        _cleanup()
        if os.path.exists(blend_path):
            os.remove(blend_path)


if __name__ == "__main__":
    main()
