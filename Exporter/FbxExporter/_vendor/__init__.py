# SPDX-FileCopyrightText: 2011-2023 Blender Foundation
# SPDX-License-Identifier: GPL-2.0-or-later

"""Private exporter backend; no bpy operator registration. See ../UPSTREAM.md."""

bl_info = {
    "name": "FBX format",
    "author": "Campbell Barton, Bastien Montagne, Jens Restemeier, @Mysteryem",
    "version": (5, 13, 1),
    "blender": (4, 5, 0),
    "location": "File > Import-Export",
    "description": "FBX IO meshes, UVs, vertex colors, materials, textures, cameras, lamps and actions",
    "warning": "",
    "doc_url": "{BLENDER_MANUAL_URL}/addons/import_export/scene_fbx.html",
    "support": 'OFFICIAL',
    "category": "Import-Export",
}
