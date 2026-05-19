---
name: compositor-node-ir
description: Export, inspect, audit, or evolve HoTools Compositor Node IR for Blender/Goo scene compositor node trees, including Render Layers, Image/Movie/Mask inputs, Composite/Viewer/File outputs, color correction, blur/defocus/denoise/glare/lens effects, keying, cryptomatte, masks, and transform nodes. Use when the user asks about post-processing as Blender compositor nodes, not render settings.
---

# Compositor Node IR

Use this skill for Blender/Goo **合成节点 / Compositor nodes**. Do not include Cycles/Eevee render settings, color management, camera settings, or viewport effects unless the user explicitly asks for a separate renderer/pipeline audit.

## Export

Run inside the matching Blender/Goo runtime:

```powershell
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --factory-startup --background 'scene.blend' --python 'C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools\SpecialTools\compositor_node_ir.py' -- --output 'C:\Temp\scene.compositor_node.json' --format JSON
```

Use the Node Editor panel `HoTools > Compositor Node IR` when working interactively in a Compositor node tree.

## Helper

- `python SpecialTools/compositor_node_ir_ai.py scene.compositor_node.json --mode preview`: compact human-readable overview.
- `python SpecialTools/compositor_node_ir_ai.py scene.compositor_node.json --mode summary`: node/link/type counts.
- `python SpecialTools/compositor_node_ir_ai.py scene.compositor_node.json --mode io`: input and output nodes.
- `python SpecialTools/compositor_node_ir_ai.py scene.compositor_node.json --mode effects`: color/filter/keying/transform groups.
- `python SpecialTools/compositor_node_ir_ai.py scene.compositor_node.json --mode audit`: migration/bake risks.

## What To Preserve

- `CompositorNodeRLayers`: render-pass dependency. Record it, but do not infer render settings from it.
- `CompositorNodeImage`, `MovieClip`, `Mask`, `Texture`: external data dependencies and color space/path metadata.
- `Composite`, `Viewer`, `SplitViewer`, `OutputFile`: output targets and file-output side effects.
- Color nodes: curves, color balance/correction, hue/saturation, exposure, gamma, tonemap, color ramp.
- Filter/effect nodes: blur, bokeh blur, defocus, denoise, glare, lens distortion, vector blur, sun beams, kuwahara.
- Matte/keying nodes: cryptomatte, chroma/color/distance/luma matte, keying, keying screen, color spill.
- Transform nodes: translate, rotate, scale, crop, flip, stabilize, map UV.
- Frames, labels, custom colors, muted nodes, drivers, group nodes, socket defaults, links.

## Blender Source Lookup

Use the runtime version from IR before reading source. Prefer the matching branch/tag, for example `blender-v4.5-release`, over `main`.

Official source roots:

- GitHub mirror: `https://github.com/blender/blender`
- Upstream project: `https://projects.blender.org/blender/blender`

Fast paths:

- Compositor node definitions: `source/blender/nodes/composite/nodes/node_composite_*.cc`
- Compositor node registration: `source/blender/nodes/composite/node_composite_tree.cc`
- Compositor operations/evaluator: `source/blender/compositor/`
- Python node operators/UI helpers: `scripts/startup/bl_operators/node.py`

Lookup rule: convert `CompositorNodeGlare` to likely `node_composite_glare.cc`, `CompositorNodeDenoise` to `node_composite_denoise.cc`, and `CompositorNodeCryptomatteV2` to the cryptomatte compositor source. Use source only to confirm sockets and semantics; keep the exported IR as the evidence for a specific asset.

## Boundary

This IR describes the compositor graph. It does not serialize renderer settings, view transform/look, pass enable flags, render engine, camera, or output resolution. If a compositor depends on Render Layers passes that are not enabled in Blender, the graph can be structurally correct while the render result still differs.

## Files

- Exporter: `SpecialTools/compositor_node_ir.py`
- AI helper: `SpecialTools/compositor_node_ir_ai.py`
