# -*- coding: utf-8 -*-
"""Generate and verify the Blender 5.2 Jolt partial wall fracture asset."""

from __future__ import annotations

import argparse
import importlib
import math
import os
import sys
import types

import bpy
from mathutils import Vector


HOTOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), *('..',) * 4))
ASSET_PATH = os.path.join(
    HOTOOLS,
    "OmniNode",
    "PhysicsWorld",
    "rigid",
    "test",
    "assets",
    "jolt_fracture_wall.blend",
)
PYTHON_ABI = f"py{sys.version_info.major}{sys.version_info.minor}"
NATIVE_PACKAGE = os.path.join(HOTOOLS, "_Lib", PYTHON_ABI, "HotoolsPackage")
os.environ["HOTOOLS_NATIVE_TEST_DIR"] = NATIVE_PACKAGE
for path in (NATIVE_PACKAGE, os.path.dirname(HOTOOLS), HOTOOLS):
    if path not in sys.path:
        sys.path.insert(0, path)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.Function", os.path.join(HOTOOLS, "OmniNode", "Function")),
    ("HoTools.OmniNode.PhysicsWorld", os.path.join(HOTOOLS, "OmniNode", "PhysicsWorld")),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


registry = importlib.import_module("HoTools.OmniNode.PhysicsWorld.registry")
physics_scope = importlib.import_module("HoTools.OmniNode.PhysicsWorld.scope")
world_api = importlib.import_module("HoTools.OmniNode.PhysicsWorld.world")
writeback = importlib.import_module("HoTools.OmniNode.PhysicsWorld.writeback")
rigid_solver = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid.solver")
rigid_results = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid.results")
rigid_specs = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid.specs")
fracture = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.authoring")
fracture_gn = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.geometry_nodes")
fracture_resolver = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.resolver")


SIM_COLLECTION = "Jolt Fracture Acceptance"
SOURCE_NAME = "Wall Fracture Source"
BALL_NAME = "Impact Ball"
GROUND_NAME = "Ground"


def _box_geometry(center, half_extents):
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


def _mesh_from_boxes(name, boxes):
    vertices = []
    faces = []
    for center, half_extents in boxes:
        box_vertices, box_faces = _box_geometry(center, half_extents)
        offset = len(vertices)
        vertices.extend(box_vertices)
        faces.extend(tuple(offset + index for index in face) for face in box_faces)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    return mesh


def _new_material(name, color, metallic=0.0, roughness=0.55):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    material.metallic = metallic
    material.roughness = roughness
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = (*color, 1.0)
        principled.inputs["Metallic"].default_value = metallic
        principled.inputs["Roughness"].default_value = roughness
    return material


def _link_only(obj, collection):
    for current in tuple(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)


def _look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _configure_rigid_box(obj, *, body_type, half_extents, start_deactivated=False):
    props = obj.hotools_rigid_body
    props.enabled = True
    props.body_type = body_type
    props.shape_type = "BOX"
    props.shape_half_extents = tuple(max(float(value), 0.001) for value in half_extents)
    props.mass = 1.0
    props.friction = 0.58
    props.restitution = 0.04
    props.linear_damping = 0.08
    props.angular_damping = 0.12
    props.start_deactivated = bool(start_deactivated and body_type == "DYNAMIC")


def build_asset(path=ASSET_PATH):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in tuple(bpy.data.collections):
        if collection.users == 0:
            bpy.data.collections.remove(collection)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 90
    scene.frame_set(1)
    scene.render.fps = 60
    scene.render.fps_base = 1.0
    scene["hotools_acceptance"] = "jolt_fracture_wall_v1"

    simulation_collection = bpy.data.collections.new(SIM_COLLECTION)
    scene.collection.children.link(simulation_collection)

    source_mesh = _mesh_from_boxes(
        "Wall Fracture Source Mesh",
        [((0.0, 0.0, 2.5), (0.30, 3.5, 2.5))],
    )
    source = bpy.data.objects.new(SOURCE_NAME, source_mesh)
    simulation_collection.objects.link(source)
    source.hotools_rigid_fracture.enabled = True
    modifier = fracture.ensure_fracture_preview_modifier(source)
    fracture_gn.set_voronoi_modifier_inputs(
        modifier,
        density=7,
        seed=0,
        randomness=0.0,
    )
    source.hotools_rigid_body.mass = 35.0
    source.hotools_rigid_body.start_deactivated = True
    fracture.ensure_product_collection(source, scene)
    pieces = fracture.refresh_fracture_products(source)
    assert len(pieces) == 35

    static_material = _new_material("Wall Static Frame", (0.19, 0.24, 0.28), metallic=0.08)
    breakable_material = _new_material("Wall Breakable Core", (0.66, 0.22, 0.08), metallic=0.03)
    dynamic_pieces = []
    static_pieces = []
    for piece in pieces:
        position = piece.matrix_world.translation
        is_dynamic = abs(float(position.y)) < 1.05 and 1.35 < float(position.z) < 3.65
        half_extents = tuple(float(value) * 0.5 for value in piece.dimensions)
        _configure_rigid_box(
            piece,
            body_type="DYNAMIC" if is_dynamic else "STATIC",
            half_extents=half_extents,
            start_deactivated=is_dynamic,
        )
        piece["hotools_acceptance_role"] = "breakable" if is_dynamic else "anchor"
        piece.data.materials.clear()
        piece.data.materials.append(breakable_material if is_dynamic else static_material)
        piece.color = (0.66, 0.22, 0.08, 1.0) if is_dynamic else (0.19, 0.24, 0.28, 1.0)
        (dynamic_pieces if is_dynamic else static_pieces).append(piece)
    assert len(dynamic_pieces) == 9 and len(static_pieces) == 26

    source.hotools_rigid_body.enabled = True
    source.hotools_rigid_body.body_type = "STATIC"
    source.hotools_rigid_body.shape_type = "BOX"
    source.hotools_rigid_body.shape_half_extents = (0.30, 3.5, 2.5)

    ground_mesh = _mesh_from_boxes("Ground Mesh", [((0.0, 0.0, -0.30), (7.0, 5.0, 0.30))])
    ground = bpy.data.objects.new(GROUND_NAME, ground_mesh)
    simulation_collection.objects.link(ground)
    _configure_rigid_box(ground, body_type="STATIC", half_extents=(7.0, 5.0, 0.30))
    ground.data.materials.append(_new_material("Ground Material", (0.055, 0.065, 0.075), metallic=0.2))

    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.34, location=(-6.0, 0.0, 2.46))
    ball = bpy.context.object
    ball.name = BALL_NAME
    _link_only(ball, simulation_collection)
    ball.data.materials.append(_new_material("Impact Ball Material", (0.05, 0.32, 0.74), metallic=0.7, roughness=0.22))
    ball.color = (0.05, 0.32, 0.74, 1.0)
    ball_props = ball.hotools_rigid_body
    ball_props.enabled = True
    ball_props.body_type = "DYNAMIC"
    ball_props.shape_type = "SPHERE"
    ball_props.shape_radius = 0.34
    ball_props.mass = 10.0
    ball_props.friction = 0.35
    ball_props.restitution = 0.08
    ball_props.linear_velocity = (14.0, 0.0, 0.0)
    ball_props.gravity_factor = 0.0
    ball_props.allow_sleeping = False
    ball_props.motion_quality = "LINEAR_CAST"

    camera_data = bpy.data.cameras.new("Acceptance Camera")
    camera = bpy.data.objects.new("Acceptance Camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (-13.0, -3.5, 6.0)
    camera.data.lens = 48.0
    _look_at(camera, (-1.5, 0.0, 2.25))
    scene.camera = camera

    light_data = bpy.data.lights.new("Acceptance Key", "AREA")
    light_data.energy = 800.0
    light_data.shape = "DISK"
    light_data.size = 5.0
    light = bpy.data.objects.new("Acceptance Key", light_data)
    scene.collection.objects.link(light)
    light.location = (-4.0, -4.5, 8.0)
    _look_at(light, (0.0, 0.0, 2.0))

    scene.world.color = (0.018, 0.024, 0.032)
    target_piece = min(dynamic_pieces, key=lambda obj: (obj.matrix_world.translation - Vector((0.0, 0.0, 2.46))).length)
    scene["hotools_target_piece_id"] = target_piece.hotools_rigid_fracture_piece.piece_id
    scene["hotools_piece_count"] = len(pieces)
    scene["hotools_dynamic_piece_count"] = len(dynamic_pieces)
    scene["hotools_static_piece_count"] = len(static_pieces)
    fracture.set_fracture_visibility(source, "PIECES")

    text = bpy.data.texts.get("JOLT_FRACTURE_ACCEPTANCE") or bpy.data.texts.new("JOLT_FRACTURE_ACCEPTANCE")
    text.clear()
    text.write(
        "Blender 5.2 / Python 3.13 acceptance asset.\n"
        "The hidden Wall Fracture Source owns the GN modifier and Product Collection.\n"
        "Run test_blender_fracture_wall.py to execute and verify the Jolt pipeline.\n"
    )
    bpy.context.view_layer.objects.active = ball
    ball.select_set(True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path


def _position_map(objects):
    return {obj.name_full: obj.matrix_world.translation.copy() for obj in objects}


def _max_displacement(objects, initial):
    return max((obj.matrix_world.translation - initial[obj.name_full]).length for obj in objects)


def _reset_object_deltas(objects):
    for obj in objects:
        obj.delta_location = (0.0, 0.0, 0.0)
        obj.delta_rotation_euler = (0.0, 0.0, 0.0)
        obj.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        obj.delta_scale = (1.0, 1.0, 1.0)
        obj.update_tag()
    bpy.context.view_layer.update()


def verify_loaded_asset(*, label="run"):
    scene = bpy.context.scene
    assert scene.get("hotools_acceptance") == "jolt_fracture_wall_v1"
    source = bpy.data.objects[SOURCE_NAME]
    ball = bpy.data.objects[BALL_NAME]
    source_props = source.hotools_rigid_fracture
    assert source_props.schema_version == fracture.FRACTURE_SCHEMA_VERSION
    assert fracture_gn.is_managed_fracture_group(
        source.modifiers[source_props.modifier_name].node_group
    )
    pieces = list(fracture.validate_fracture_manifest(source))
    dynamic_pieces = [obj for obj in pieces if obj.get("hotools_acceptance_role") == "breakable"]
    static_pieces = [obj for obj in pieces if obj.get("hotools_acceptance_role") == "anchor"]
    assert len(pieces) == 35 and len(dynamic_pieces) == 9 and len(static_pieces) == 26
    assert source.hide_get() is True
    _reset_object_deltas(pieces + [ball])
    scene.frame_set(1)

    simulation_collection = bpy.data.collections[SIM_COLLECTION]
    scope = physics_scope.make_scope(
        collections=(simulation_collection,),
        include_passive_collision=False,
        include_bone_collision=False,
        include_rigid_body=True,
        include_rigid_constraint=False,
        include_hidden=True,
    )
    initial_dynamic = _position_map(dynamic_pieces)
    initial_static = _position_map(static_pieces)
    ball_slot_id = rigid_specs.build_rigid_body_spec(ball).slot_id
    target_piece_id = str(scene["hotools_target_piece_id"])

    cache_state = None
    observed_piece_contacts = set()
    preimpact_displacement = None
    body_count = 0
    final_diagnostics = {}
    final_world = None
    for frame in range(1, 91):
        scene.frame_set(frame)
        world, _current_frame, _collider_count, restart = world_api.physicsWorldBegin(
            cache_state=cache_state,
            scene=scene,
            object_scope=scope,
            enabled=True,
        )
        body_count, _step_ms = rigid_solver.step_rigid_bodies(world, enabled=True)
        slot_index = world.backend_resources.get(
            fracture_resolver.FRACTURE_SLOT_INDEX_RESOURCE_KEY,
            {},
        )
        events = rigid_results.iter_rigid_contact_event_results(
            world,
            frame=scene.frame_current,
            generation=world.generation,
        )
        for event in events:
            slots = {event.get("body_a_slot_id"), event.get("body_b_slot_id")}
            if ball_slot_id not in slots:
                continue
            for slot_id in slots:
                metadata = slot_index.get(slot_id)
                if metadata is not None:
                    observed_piece_contacts.add(str(metadata["piece_id"]))

        writeback.apply_all_writebacks(world, restart=restart)
        bpy.context.view_layer.update()
        if frame == 10:
            preimpact_displacement = _max_displacement(dynamic_pieces, initial_dynamic)
        final_diagnostics = dict(world.backend_resources.get("_writeback_rigid_diagnostics", {}))
        cache_state, _stats, _valid = world_api.physicsWorldCommit(world, enabled=True)
        final_world = world

    assert body_count == 37, f"expected 35 pieces + ball + ground, got {body_count}"
    assert preimpact_displacement is not None and preimpact_displacement < 1.0e-5
    assert target_piece_id in observed_piece_contacts, {
        "target": target_piece_id,
        "contacts": sorted(observed_piece_contacts),
    }

    dynamic_displacements = {
        obj.name_full: (obj.matrix_world.translation - initial_dynamic[obj.name_full]).length
        for obj in dynamic_pieces
    }
    moved_dynamic = [name for name, distance in dynamic_displacements.items() if distance > 0.08]
    max_static_displacement = _max_displacement(static_pieces, initial_static)
    assert 1 <= len(moved_dynamic) <= len(dynamic_pieces), dynamic_displacements
    assert max(dynamic_displacements.values()) > 0.30, dynamic_displacements
    assert max_static_displacement < 1.0e-6
    assert final_diagnostics.get("fallback_reason", "") == "", final_diagnostics
    assert int(final_diagnostics.get("sparse_collection_count", 0)) >= 2, final_diagnostics

    for obj in pieces + [ball]:
        assert all(math.isfinite(float(value)) for value in obj.matrix_world.translation)

    print(
        f"[PASS] Jolt fracture wall {label}: "
        f"bodies={body_count}, contacts={len(observed_piece_contacts)}, "
        f"moved_dynamic={len(moved_dynamic)}, anchors={len(static_pieces)}, "
        f"batch_sparse={final_diagnostics.get('sparse_collection_count')}"
    )
    if final_world is not None:
        final_world.omni_cache_dispose("fracture_wall_acceptance")
    return {
        "body_count": body_count,
        "contacts": tuple(sorted(observed_piece_contacts)),
        "moved_dynamic": len(moved_dynamic),
        "anchors": len(static_pieces),
    }


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--verify-file", default="")
    return parser.parse_args(argv)


def main():
    args = _parse_args()
    registry.register_physics_world_blender_properties()
    try:
        if args.verify_file:
            bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args.verify_file))
        elif args.generate or not bpy.data.objects.get(SOURCE_NAME):
            build_asset(ASSET_PATH)
        first = verify_loaded_asset(label="initial")
        replay = verify_loaded_asset(label="replay")
        assert replay == first, {"initial": first, "replay": replay}
    finally:
        registry.unregister_physics_world_blender_properties()


if __name__ == "__main__":
    main()
