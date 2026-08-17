# -*- coding: utf-8 -*-
"""Exercise the user's fracture scene through the real OmniNode frame pipeline."""

from __future__ import annotations

import argparse
import importlib
import math
import os
import sys
import types

import bpy


HOTOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), *("..",) * 4))
DEFAULT_PROJECT = r"C:\Users\hhh12\Desktop\破碎.blend"
ACCEPTANCE_ASSET = os.path.join(
    HOTOOLS,
    "OmniNode",
    "PhysicsWorld",
    "rigid",
    "test",
    "assets",
    "jolt_fracture_user_project.blend",
)
PYTHON_ABI = f"py{sys.version_info.major}{sys.version_info.minor}"
NATIVE_PACKAGE = os.path.join(HOTOOLS, "_Lib", PYTHON_ABI, "HotoolsPackage")
os.environ["HOTOOLS_NATIVE_TEST_DIR"] = NATIVE_PACKAGE
for path in (NATIVE_PACKAGE, os.path.dirname(HOTOOLS), HOTOOLS):
    if path not in sys.path:
        sys.path.insert(0, path)

# Avoid importing the broad HoTools root add-on; register only OmniNode and PhysicsWorld.
hotools_package = types.ModuleType("HoTools")
hotools_package.__path__ = [HOTOOLS]
hotools_package.__package__ = "HoTools"
sys.modules["HoTools"] = hotools_package


physics_blender = importlib.import_module("HoTools.OmniNode.PhysicsWorld.blender")
omninode = importlib.import_module("HoTools.OmniNode")
fracture = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.authoring")
fracture_gn = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.geometry_nodes")


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--verify-file", action="store_true")
    parser.add_argument("--baseline-manual", action="store_true")
    parser.add_argument("--baseline-auto", action="store_true")
    parser.add_argument("--authoring-flow", action="store_true")
    return parser.parse_args(argv)


def _describe_project():
    print("PROJECT_SCENE", bpy.context.scene.name, bpy.context.scene.frame_start, bpy.context.scene.frame_end)
    for obj in bpy.context.scene.objects:
        rigid = getattr(obj, "hotools_rigid_body", None)
        print(
            "PROJECT_OBJECT",
            obj.name_full,
            obj.type,
            tuple(round(float(value), 4) for value in obj.dimensions),
            tuple(round(float(value), 4) for value in obj.matrix_world.translation),
            bool(getattr(rigid, "enabled", False)) if rigid else None,
            str(getattr(rigid, "body_type", "")) if rigid else None,
            str(getattr(rigid, "shape_type", "")) if rigid else None,
        )
    for tree in bpy.data.node_groups:
        if getattr(tree, "bl_idname", "") != "OmniNodeTree":
            continue
        print(
            "PROJECT_TREE",
            tree.name_full,
            bool(tree.is_execution_enabled),
            bool(tree.is_frame_run_enabled),
            len(tree.nodes),
            len(tree.links),
        )
        for node in tree.nodes:
            print("PROJECT_NODE", node.name, node.bl_idname, node.label)
            for socket in node.inputs:
                value = getattr(socket, "default_value", "<none>")
                if hasattr(value, "to_tuple"):
                    value = tuple(value)
                elif not isinstance(value, (str, bytes, bpy.types.ID)):
                    try:
                        value = tuple(value)
                    except TypeError:
                        pass
                print(
                    "PROJECT_INPUT",
                    node.name,
                    socket.name,
                    repr(value),
                    bool(socket.is_linked),
                )
        for link in tree.links:
            print(
                "PROJECT_LINK",
                link.from_node.name,
                link.from_socket.name,
                "->",
                link.to_node.name,
                link.to_socket.name,
            )


def _reset_deltas(objects):
    for obj in objects:
        obj.delta_location = (0.0, 0.0, 0.0)
        obj.delta_rotation_euler = (0.0, 0.0, 0.0)
        obj.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        obj.delta_scale = (1.0, 1.0, 1.0)
        obj.update_tag()


def _configure_project():
    scene = bpy.context.scene
    source = bpy.data.objects["墙"]
    ball = bpy.data.objects["撞击球"]
    ground = bpy.data.objects["地板"]

    source_rigid = source.hotools_rigid_body
    source_rigid.enabled = True
    source_rigid.body_type = "DYNAMIC"
    source_rigid.shape_type = "BOX"
    source_rigid.mass = 800.0
    source_rigid.friction = 0.62
    source_rigid.restitution = 0.02
    source_rigid.linear_damping = 0.12
    source_rigid.angular_damping = 0.16
    source_rigid.start_deactivated = True
    source_rigid.allow_sleeping = True

    props = source.hotools_rigid_fracture
    props.enabled = True
    modifier = fracture.ensure_fracture_preview_modifier(source)
    fracture_gn.set_voronoi_modifier_inputs(
        modifier,
        density=8,
        seed=17,
        randomness=0.35,
        gap=0.055,
    )
    fracture.ensure_product_collection(source, scene)
    pieces = list(fracture.refresh_fracture_products(source))
    assert 32 <= len(pieces) <= 48, len(pieces)
    dynamic_pieces = []
    static_pieces = []
    for piece in pieces:
        rigid = piece.hotools_rigid_body
        rigid.enabled = True
        position = piece.matrix_world.translation
        is_impact_island = (
            abs(float(position.x) - float(ball.matrix_world.translation.x)) < 9.0
            and abs(float(position.z) - float(ball.matrix_world.translation.z)) < 12.0
        )
        rigid.body_type = "DYNAMIC" if is_impact_island else "STATIC"
        rigid.shape_type = "BOX"
        # Until convex-hull bodies land, use a conservative proxy so adjacent
        # irregular Voronoi AABBs do not overlap before the impact.
        rigid.shape_half_extents = tuple(
            max(float(value) * 0.36, 0.01) for value in piece.dimensions
        )
        rigid.start_deactivated = is_impact_island
        rigid.allow_sleeping = True
        piece["hotools_acceptance_role"] = "impact" if is_impact_island else "anchor"
        (dynamic_pieces if is_impact_island else static_pieces).append(piece)
    assert 4 <= len(dynamic_pieces) <= 12, len(dynamic_pieces)

    ball_rigid = ball.hotools_rigid_body
    ball_rigid.enabled = True
    ball_rigid.body_type = "DYNAMIC"
    ball_rigid.shape_type = "SPHERE"
    ball_rigid.shape_radius = max(float(ball.dimensions.x) * 0.5, 0.01)
    ball_rigid.mass = 60.0
    ball_rigid.friction = 0.32
    ball_rigid.restitution = 0.04
    ball_rigid.gravity_factor = 0.0
    ball_rigid.allow_sleeping = False
    ball_rigid.motion_quality = "LINEAR_CAST"
    ball_rigid.linear_velocity = (0.0, 24.0, 0.0)

    ground_rigid = ground.hotools_rigid_body
    ground_rigid.enabled = True
    ground_rigid.body_type = "STATIC"
    ground_rigid.shape_type = "PLANE"

    tree = bpy.data.node_groups["Omni节点图"]
    velocity_node = tree.nodes.get("刚体命令-设置速度")
    assert velocity_node is not None
    velocity_node.inputs["目标刚体"].default_value = ball
    velocity_node.inputs["线速度"].default_value = (0.0, 24.0, 0.0)
    velocity_node.inputs["角速度"].default_value = (0.0, 0.0, 0.0)

    scene.frame_start = 1
    scene.frame_end = 120
    scene.frame_set(1)
    _reset_deltas([ball, *pieces])
    fracture.set_fracture_visibility(source, "PIECES")
    scene["hotools_acceptance"] = "jolt_fracture_user_project_v1"
    scene["hotools_piece_count"] = len(pieces)
    scene["hotools_dynamic_piece_count"] = len(dynamic_pieces)
    scene["hotools_static_piece_count"] = len(static_pieces)
    scene["hotools_source_project"] = DEFAULT_PROJECT
    bpy.context.view_layer.update()
    os.makedirs(os.path.dirname(ACCEPTANCE_ASSET), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=ACCEPTANCE_ASSET)
    return tree, source, ball, pieces


def _run_omninode_acceptance(tree, source, ball, pieces):
    runtime_state = importlib.import_module("HoTools.OmniNode.OmniRuntimeState")
    runtime_state.clear_all()
    tree.is_execution_enabled = True
    # Background Blender does not dispatch the UI frame handler reliably.
    # Invoke the exact cached tree entry point once per frame instead.
    tree.is_frame_run_enabled = False
    tree.compile_cached(force=True)

    scene = bpy.context.scene
    scene.frame_set(1)
    tree.debug_runtime_trace = False
    first_result = tree.run_frame_cached()
    first_world = next(iter(first_result.values()))
    assert first_world.runtime_cache("solver_registry_errors") is None
    assert len(first_world.solver_slots) == len(pieces) + 2
    initial_ball = ball.matrix_world.translation.copy()
    initial = {
        piece.name_full: piece.matrix_world.translation.copy()
        for piece in pieces
    }
    preimpact_max = 0.0
    for frame in range(2, scene.frame_end + 1):
        scene.frame_set(frame)
        tree.run_frame_cached()
        if frame == 30:
            preimpact_max = max(
                (piece.matrix_world.translation - initial[piece.name_full]).length
                for piece in pieces
            )

    displacements = {
        piece.name_full: (piece.matrix_world.translation - initial[piece.name_full]).length
        for piece in pieces
    }
    moved = [name for name, distance in displacements.items() if distance > 0.10]
    ball_distance = (ball.matrix_world.translation - initial_ball).length
    assert source not in fracture.validate_fracture_manifest(source)
    assert preimpact_max < 1.0e-4, preimpact_max
    assert ball_distance > 45.0, ball_distance
    dynamic_pieces = [
        piece for piece in pieces
        if piece.get("hotools_acceptance_role") == "impact"
    ]
    static_pieces = [
        piece for piece in pieces
        if piece.get("hotools_acceptance_role") == "anchor"
    ]
    moved_static = [
        piece.name_full for piece in static_pieces
        if displacements[piece.name_full] > 1.0e-6
    ]
    assert 1 <= len(moved) <= len(dynamic_pieces), {
        "moved": len(moved),
        "pieces": len(pieces),
        "maximum": max(displacements.values()),
    }
    assert not moved_static, moved_static
    assert all(
        math.isfinite(float(value))
        for obj in [ball, *pieces]
        for value in obj.matrix_world.translation
    )
    print(
        "[PASS] user project through OmniNode: "
        f"pieces={len(pieces)}, moved={len(moved)}, "
        f"anchors={len(static_pieces)}, "
        f"preimpact={preimpact_max:.6f}, ball_distance={ball_distance:.3f}, "
        f"asset={ACCEPTANCE_ASSET}"
    )


def _loaded_acceptance_asset():
    scene = bpy.context.scene
    assert scene.get("hotools_acceptance") == "jolt_fracture_user_project_v1"
    source = bpy.data.objects["墙"]
    ball = bpy.data.objects["撞击球"]
    pieces = list(fracture.validate_fracture_manifest(source))
    assert len(pieces) == int(scene["hotools_piece_count"])
    assert source.hide_get() is True
    _reset_deltas([ball, *pieces])
    scene.frame_set(1)
    bpy.context.view_layer.update()
    return bpy.data.node_groups["Omni节点图"], source, ball, pieces


def _run_original_baseline(*, manual: bool):
    runtime_state = importlib.import_module("HoTools.OmniNode.OmniRuntimeState")
    tree_module = importlib.import_module("HoTools.OmniNode.OmniNodeTree")
    scene = bpy.context.scene
    tree = bpy.data.node_groups["Omni节点图"]
    ball = bpy.data.objects["撞击球"]
    simulated = [
        obj for obj in scene.objects
        if bool(getattr(getattr(obj, "hotools_rigid_body", None), "enabled", False))
    ]
    assert len(simulated) == 3, [obj.name_full for obj in simulated]
    for obj in simulated:
        props = getattr(obj, "hotools_rigid_fracture", None)
        if props is None or not bool(getattr(props, "enabled", False)):
            continue
        collection = getattr(props, "product_collection", None)
        collection_objects = []
        if collection is not None:
            for item in collection.all_objects:
                piece = getattr(item, "hotools_rigid_fracture_piece", None)
                collection_objects.append((
                    item.name_full,
                    bool(getattr(piece, "managed", False)) if piece else None,
                    str(getattr(piece, "owner_asset_id", "") or "") if piece else None,
                    int(getattr(piece, "product_revision", 0)) if piece else None,
                ))
        print(
            "BASELINE_FRACTURE",
            obj.name_full,
            f"asset_id={str(getattr(props, 'asset_id', '') or '')!r}",
            f"revision={int(getattr(props, 'product_revision', 0))}",
            f"status={str(getattr(props, 'product_status', ''))!r}",
            f"collection={getattr(collection, 'name_full', None)!r}",
            f"objects={collection_objects!r}",
        )
    runtime_state.clear_all()
    _reset_deltas(simulated)
    scene.frame_set(1)
    initial = ball.matrix_world.translation.copy()
    tree.is_execution_enabled = True
    tree.is_frame_run_enabled = not manual
    tree.compile_cached(force=True)
    handler_registered = (
        tree_module._omni_frame_change_post in bpy.app.handlers.frame_change_post
    )
    assert handler_registered

    handler_calls = []

    def _frame_probe(probe_scene, _depsgraph=None):
        handler_calls.append(int(probe_scene.frame_current))

    bpy.app.handlers.frame_change_post.append(_frame_probe)
    first_world = None
    if manual:
        result = tree.run_frame_cached()
        first_world = next(iter(result.values()))
    try:
        for frame in range(2, 61):
            scene.frame_set(frame)
            if manual:
                tree.run_frame_cached()
    finally:
        bpy.app.handlers.frame_change_post.remove(_frame_probe)
    distance = (ball.matrix_world.translation - initial).length
    if first_world is not None:
        print(
            "BASELINE_WORLD",
            f"slots={len(first_world.solver_slots)}",
            f"errors={first_world.runtime_cache('solver_registry_errors')!r}",
        )
    print(
        "BASELINE_RUNTIME",
        "manual" if manual else "auto",
        f"handler={handler_registered}",
        f"handler_calls={len(handler_calls)}",
        f"distance={distance:.6f}",
        f"delta={tuple(round(float(value), 6) for value in ball.delta_location)}",
    )
    assert distance > 1.0, distance


def _run_original_authoring_flow():
    scene = bpy.context.scene
    source = next(
        obj for obj in scene.objects
        if bool(getattr(getattr(obj, "hotools_rigid_fracture", None), "enabled", False))
    )
    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    modifier = fracture.ensure_fracture_preview_modifier(source)
    fracture_gn.set_voronoi_modifier_inputs(
        modifier,
        density=5,
        seed=11,
        randomness=0.55,
        gap=0.04,
    )
    fracture.ensure_product_collection(source, scene)
    pieces = tuple(fracture.refresh_fracture_products(source))
    assert len(pieces) > 1
    manifest = fracture.validate_fracture_manifest(source)
    assert {
        piece.hotools_rigid_fracture_piece.piece_id for piece in manifest
    } == {
        piece.hotools_rigid_fracture_piece.piece_id for piece in pieces
    }
    count = fracture.delete_fracture_products(source)
    assert count == len(pieces)
    assert source.hotools_rigid_fracture.product_collection is None
    print(
        "[PASS] original project fracture authoring flow: "
        f"Blender={bpy.app.version_string}, source={source.name_full}, pieces={len(pieces)}"
    )


def main():
    args = _parse_args()
    project = os.path.abspath(args.project)
    if not os.path.isfile(project):
        raise FileNotFoundError(project)
    physics_blender.register()
    omninode.register()
    bpy.ops.wm.open_mainfile(filepath=project)
    if args.probe:
        _describe_project()
        return
    if args.baseline_manual or args.baseline_auto:
        _run_original_baseline(manual=bool(args.baseline_manual))
        return
    if args.authoring_flow:
        _run_original_authoring_flow()
        return
    if args.verify_file:
        tree, source, ball, pieces = _loaded_acceptance_asset()
    else:
        tree, source, ball, pieces = _configure_project()
    _run_omninode_acceptance(tree, source, ball, pieces)


if __name__ == "__main__":
    main()
