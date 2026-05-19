---
name: blender-live-inspector
description: Inspect Blender or Goo Engine scenes live through bpy for material, object, texture, Goo-node, and IR-diff checks without exporting a full JSON bundle. Use when a .blend can be opened by Blender/Goo and AI needs fast live queries, verification against exported HoTools IR, or confirmation that official Blender vs Goo runtime data differs.
---

# Blender Live Inspector

Use this skill when the user wants live Blender/Goo evidence instead of only reading exported JSON. Prefer small live queries first, then export or compare IR only when the answer needs an archive.

## Runtime Rule

Run the inspector with the same Blender dialect that authored the file:

- Official Blender material: use the matching official `blender.exe`.
- Goo material: use Goo Engine's `blender.exe`.
- If the user gives a Goo `blender-launcher.exe`, look for sibling `blender.exe` and use that for backend work.

If Goo materials are opened in official Blender, fork nodes may become `NodeUndefined`. Treat that as a runtime mismatch, not necessarily bad source data.

## Backend Command Pattern

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'D:\Asset\scene.blend' --python 'C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools\SpecialTools\blender_live_inspector.py' -- --mode materials --pretty
```

Backend rules:

- Use PowerShell call operator `&` and quote every path, especially paths with Chinese characters or spaces.
- Keep the separator `--` before inspector arguments. Arguments after it belong to `blender_live_inspector.py`, not Blender.
- Use absolute paths when running from Codex or another project. Do not assume the current directory is HoTools.
- Use `--factory-startup` by default to avoid user add-on logs and startup state. Drop it only when the `.blend` needs a user add-on to register custom nodes or custom data.
- Add Blender's `--disable-autoexec` for untrusted files. This is safer, but may hide scripted setup or driver side effects.
- Do not use `blender-launcher.exe` for automation if it produces no stdout; use the real `blender.exe`.
- Store temporary command output outside the add-on folder if a file is needed. The inspector itself prints JSON and writes no cache files.
- If Blender logs surround the JSON, parse the final JSON object instead of treating all stdout as clean JSON.

## Main Modes

- `--mode app`: runtime metadata, version, binary path, Goo/source flavor hint.
- `--mode scene`: object/material counts, UVs, attributes, color attributes, modifier types.
- `--mode materials`: compact list of node materials with node/image/group/Goo signal counts.
- `--mode material --material "Name"`: live material summary including images, groups, context inputs, color transforms, annotations, and Goo/fork signals.
- `--mode node --material "Name" --node "Screenspace"`: find matching nodes and print sockets/defaults.
- `--mode compare-material-ir --material "Name" --ir "material_ir.json"`: build live Material IR in memory and compare counts, node types, groups, images, and Goo nodes against exported JSON.

Add `--no-groups` for faster root-only inspection on very large node graphs.

Use `--limit N` with `--mode node` when a substring matches many nodes.

## Backend Tactics

Start cheap:

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode app --pretty
```

Then inspect scene scale:

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode scene --pretty
```

For huge files, list materials without nested groups first:

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode materials --no-groups --pretty
```

Then deep-inspect only the target:

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode material --material 'M_actor_bounda_cloth_02.001' --pretty
```

Search semantic node families by short substrings:

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode node --material 'M_actor_bounda_cloth_02.001' --node 'Screenspace' --limit 20 --pretty
```

Good node search terms: `Shader Info`, `Screenspace`, `Depth`, `Rim`, `MatCap`, `Rain`, `Attribute`, `UV`, `Geometry`, `Object`, `Camera`, `ColorRamp`, `Curve`, `Normal`, `Tangent`, `Outline`.

Compare live data against an exported Material IR before drawing migration conclusions:

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode compare-material-ir --material 'M_actor_bounda_cloth_02.001' --ir 'C:\Users\hhh12\Desktop\M_actor_bounda_cloth_02_001.json' --pretty
```

Interpret compare results:

- `match: true`: exported IR and live graph agree structurally.
- `count_diffs`: node/tree/link/image/group counts changed, or one side omitted groups.
- `node_type_diff`: look for Goo nodes becoming `NodeUndefined` or custom nodes changing type.
- `image_diff`: texture names, paths, color spaces, packed state, or source metadata changed.
- `group_diff`: node group names changed or nested groups were skipped.

## Analysis Workflow

1. Run `--mode app` first. Confirm Blender/Goo version and source flavor.
2. Run `--mode scene` or `--mode materials` to choose a target material.
3. Run `--mode material` for the target material.
4. If a node family matters, run `--mode node` with a focused substring such as `Shader Info`, `Screenspace`, `MatCap`, `Rain`, `Attribute`, `UV`, or `Rim`.
5. If exported JSON exists, run `--mode compare-material-ir` before blaming the converter. A mismatch may mean the JSON is stale, exported by the wrong runtime, or exported with different group settings.

## Pure Backend Troubleshooting

- If the process exits with no JSON, check whether the executable is a launcher. Retry with the adjacent `blender.exe`.
- If Goo nodes are undefined, rerun with Goo Engine's `blender.exe` and record both runtime versions.
- If material names include spaces, dots, Chinese text, or duplicate suffixes, copy the exact name from `--mode materials`.
- If background loading is slow, avoid full `--mode material` on all materials. Query `materials --no-groups`, then inspect only suspicious materials.
- If a file requires add-ons, remove `--factory-startup` after confirming `--mode app` with factory startup. Record that add-ons affected the result.
- If stdout contains warnings, keep the JSON evidence and summarize the warnings separately.
- If the user only needs "what changed since export", use `compare-material-ir`; do not export another full scene bundle first.
- If the user asks for migration risk, combine live findings with Material IR helpers. Live inspector proves what Blender/Goo currently sees; IR helpers provide richer offline audit text.

## Boundaries

- Live inspector is a query tool, not the canonical archive.
- Full JSON IR remains the source for offline conversion, reproducibility, and sharing.
- Live comparison intentionally checks structural evidence, not pixel-perfect render equivalence.
- BSDF, Goo lighting, screen-space color/depth, and render pipeline behavior still require Unity shader/pipeline review.

## Related Files

- Script: `SpecialTools/blender_live_inspector.py`
- Material IR helper: `SpecialTools/material_ir_ai.py`
- Scene/Object helper: `SpecialTools/object_scene_ir_ai.py`
- Joint helper: `SpecialTools/ir_joint_ai.py`
