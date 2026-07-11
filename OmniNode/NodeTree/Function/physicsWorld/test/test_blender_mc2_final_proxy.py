# -*- coding: utf-8 -*-
"""Blender adapter regression tests for MC2 MeshCloth final-proxy extraction."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


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


base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
final_proxy = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.final_proxy"
)


def _assign_identity_uvs(mesh) -> None:
    uv_layer = mesh.uv_layers.new(name="MC2_UV")
    coords = {
        0: (0.0, 0.0),
        1: (1.0, 0.0),
        2: (1.0, 1.0),
        3: (0.0, 1.0),
    }
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = coords[vertex_index]


def _make_object(name: str, faces) -> object:
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        (),
        faces,
    )
    mesh.update()
    _assign_identity_uvs(mesh)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _remove_object(obj) -> None:
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def test_ngon_proxy_keeps_original_vertices() -> None:
    obj = _make_object("MC2_FinalProxyNgon", ((0, 1, 2, 3),))
    try:
        topology_signature = base_pose.mesh_topology_signature(obj)
        result = final_proxy.build_blender_mesh_final_proxy(
            obj,
            task_id="mc2:mesh_cloth:blender_ngon",
            expected_mesh_topology_signature=topology_signature,
        )

        assert result.proxy.vertex_count == 4
        assert len(result.proxy.triangles) == 2
        assert max(max(triangle) for triangle in result.proxy.triangles) == 3
        assert tuple(result.proxy.vertex_identities) == (
            "mesh:v0",
            "mesh:v1",
            "mesh:v2",
            "mesh:v3",
        )
    finally:
        _remove_object(obj)


def test_vertex_group_pin_uses_same_vertex_indices() -> None:
    obj = _make_object("MC2_FinalProxyPin", ((0, 1, 2, 3),))
    try:
        group = obj.vertex_groups.new(name="Pin")
        group.add((1, 3), 1.0, "REPLACE")

        result = final_proxy.build_blender_mesh_final_proxy(
            obj,
            task_id="mc2:mesh_cloth:blender_pin",
            pin_enabled=True,
            pin_vertex_group="Pin",
        )

        assert list(result.proxy.vertex_attributes) == [0x82, 0x81, 0x82, 0x81]
    finally:
        _remove_object(obj)


def test_shared_vertex_with_multiple_loop_uvs_is_rejected() -> None:
    obj = _make_object("MC2_FinalProxyUvSeam", ((0, 1, 2), (0, 2, 3)))
    try:
        uv_layer = obj.data.uv_layers.active
        for polygon in obj.data.polygons:
            for loop_index in polygon.loop_indices:
                if obj.data.loops[loop_index].vertex_index == 0 and polygon.index == 1:
                    uv_layer.data[loop_index].uv = (0.25, 0.25)

        try:
            final_proxy.build_blender_mesh_final_proxy(
                obj,
                task_id="mc2:mesh_cloth:blender_uv_seam",
            )
        except ValueError as exc:
            assert "multiple loop UVs" in str(exc)
            assert "split the proxy vertex" in str(exc)
        else:
            raise AssertionError("UV seam on one Blender vertex must be rejected")
    finally:
        _remove_object(obj)


TESTS = (
    ("n-gon final proxy keeps original vertices", test_ngon_proxy_keeps_original_vertices),
    ("vertex group pin uses same indices", test_vertex_group_pin_uses_same_vertex_indices),
    ("shared vertex UV seam is rejected", test_shared_vertex_with_multiple_loop_uvs_is_rejected),
)


def main() -> None:
    passed = 0
    for name, test in TESTS:
        test()
        passed += 1
        print(f"[PASS] {name}")
    print(f"{passed}/{len(TESTS)} passed")


if __name__ == "__main__":
    main()
