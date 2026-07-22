# -*- coding: utf-8 -*-
"""Physics World source revision 与内部 GN 写回屏蔽的 Blender 5.2 验收。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
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


physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
source_revisions = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.source_revisions"
)
gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
)


def _make_mesh_object():
    mesh = bpy.data.meshes.new("PWSourceRevisionMesh")
    mesh.from_pydata(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        (),
        ((0, 1, 2),),
    )
    source = bpy.data.objects.new("PWSourceRevisionObject", mesh)
    bpy.context.scene.collection.objects.link(source)
    bpy.context.view_layer.update()
    return source


def _revision_pair(source):
    source_revision, data_revision, cacheable = source_revisions.source_revision_pair(source)
    assert cacheable is True
    return source_revision, data_revision


def _edit_first_vertex(source, x: float) -> None:
    source.data.vertices[0].co.x = float(x)
    source.data.update()
    source.update_tag()
    bpy.context.view_layer.update()


def main() -> None:
    physics_blender.register()
    source = _make_mesh_object()
    try:
        initial = _revision_pair(source)
        _edit_first_vertex(source, 0.125)
        external = _revision_pair(source)
        assert external[0] > initial[0]
        assert external[1] > initial[1]

        reservation = source_revisions.reserve_internal_geometry_update(source)
        assert reservation is not None
        try:
            gn_offset.write_gn_local_offsets(
                source,
                np.zeros((len(source.data.vertices), 3), dtype=np.float32),
            )
            bpy.context.view_layer.update()
        except Exception:
            source_revisions.cancel_internal_geometry_update(reservation)
            raise
        internal = _revision_pair(source)
        assert internal == external, (external, internal)

        _edit_first_vertex(source, 0.25)
        final = _revision_pair(source)
        assert final[0] > internal[0]
        assert final[1] > internal[1]
        assert source_revisions.source_revision_tracker().inspect()[
            "pending_source_count"
        ] == 0
        print("Physics World source revisions Blender acceptance: PASS")
    finally:
        physics_blender.unregister()
        bpy.data.objects.remove(source, do_unlink=True)


if __name__ == "__main__":
    main()
