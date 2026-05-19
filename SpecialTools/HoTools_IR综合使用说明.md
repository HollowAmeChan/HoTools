# HoTools IR 综合使用说明

这套工具用于把 Blender / Goo Engine 里的材质、物体、场景信息整理成 AI 和迁移脚本都能理解的证据。它现在有两条路线：

- 导出 IR：生成 JSON / Markdown，适合归档、分享、离线分析、批量转换。
- Live Inspector：直接通过 Blender/Goo 的 `bpy` 查询当前 `.blend`，适合快速检索、确认 Goo 节点、检查导出 JSON 是否过期。

两条路线不是互相替代。IR 是稳定证据包，Live Inspector 是快速取证和对照工具。

## 什么时候用哪一个

用 Material Node IR：

- 需要完整记录一个材质节点树。
- 要给另一个 AI 或外部项目分析。
- 要做 glTF / Unity / lilToon / lilPBR 的可审计迁移计划。
- 要保留 ColorRamp、RGB Curve、图片色彩空间、节点组、Frame 注释等细节。

用 Object Scene IR：

- 材质依赖 UV、Attribute、Vertex Color、Tangent、Geometry、物体层级、材质槽。
- 要检查 mesh 是否真的有 `RainID`、`custom_normal`、`smoothnormalWS` 等属性。
- 要看 Shape Key、Modifier、Geometry Nodes modifier 是否影响迁移。

用 Geometry Nodes IR：

- 物体上有 `NODES` / Geometry Nodes modifier。
- 要看几何节点组内部结构、字段、属性读写、实例、采样、烘焙节点。
- 要分析 Simulation / Repeat / For Each / Closure 这类 zone 节点。
- 要判断程序化几何应该直接迁移、烘焙成 mesh，还是在 Unity 侧写运行时逻辑。

用 Scene Bundle：

- 要一次性打包整场景的 object scene 和所有引用材质。
- 要把场景里的 Geometry Nodes modifier 图也一起带上。
- 要做全场景迁移审计。
- 能接受文件很大。复杂角色场景可能超过 100MB。

用 Live Inspector：

- 只想快速知道当前 `.blend` 里有哪些材质、节点、贴图、属性。
- 觉得 Scene Bundle 太大，不想每次导 100MB。
- 想确认 Goo Engine 节点是否被官方 Blender 降级成 `NodeUndefined`。
- 想检查 live 数据和已经导出的 JSON 是否一致。

## Blender 里导出

启用 HoTools 后：

1. 选中目标物体或打开目标场景。
2. 在 Shader Editor 或 View3D 侧栏找到 HoTools 的 IR 面板。
3. 单材质用 Material Node IR。
4. 场景/物体上下文用 Object Scene IR。
5. 整体迁移评估用 Scene Bundle。

建议：

- 单材质优先导 JSON，Markdown 只当摘要。
- 大场景不要每次都导 Scene Bundle，先用 Live Inspector 或单独导重点材质。
- Goo 工程要用 Goo Engine 打开和导出，官方 Blender 可能丢失 fork 节点类型。

## 外部分析命令

Material Node IR：

```powershell
python SpecialTools/material_ir_ai.py material_ir.json --mode preview
python SpecialTools/material_ir_ai.py material_ir.json --mode audit
python SpecialTools/material_ir_ai.py material_ir.json --mode images
python SpecialTools/material_ir_ai.py material_ir.json --mode groups
python SpecialTools/material_ir_ai.py material_ir.json --mode annotations
python SpecialTools/material_ir_ai.py material_ir.json --mode colors
python SpecialTools/material_ir_ai.py material_ir.json --mode inputs
python SpecialTools/material_ir_ai.py material_ir.json --mode goo
python SpecialTools/material_ir_ai.py material_ir.json --mode source --source-profile goo
```

Object / Scene IR：

```powershell
python SpecialTools/object_scene_ir_ai.py object_scene.json --mode preview
python SpecialTools/object_scene_ir_ai.py object_scene.json --mode audit
python SpecialTools/ir_joint_ai.py --scene-bundle scene.scene_asset.json --mode preview
```

Geometry Nodes IR：

```powershell
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\geometry_node_ir.py' -- --scope SCENE --output 'scene.geometry_node.json' --format JSON
python SpecialTools/geometry_node_ir_ai.py asset.geometry_node.json --mode preview
python SpecialTools/geometry_node_ir_ai.py asset.geometry_node.json --mode summary
python SpecialTools/geometry_node_ir_ai.py asset.geometry_node.json --mode zones
python SpecialTools/geometry_node_ir_ai.py asset.geometry_node.json --mode effects
python SpecialTools/geometry_node_ir_ai.py asset.geometry_node.json --mode audit
```

常用顺序：

1. `preview`：给人快速看大概。
2. `audit`：正式迁移前综合检查。
3. `images`：贴图、色彩空间、packed/dirty、采样方式。
4. `groups`：节点组接口和内部结构。
5. `annotations`：Frame、label、节点颜色，理解作者意图。
6. `colors`：ColorRamp / RGB Curve / Float Curve / Vector Curve。
7. `inputs`：UV、Attribute、Geometry、Object、Camera、Tangent 等上下文依赖。
8. `goo`：Goo/fork 节点、NPR 命名、未知节点。
9. `zones`：几何节点里的 Simulation / Repeat / For Each / Closure 执行结构。
10. `effects`：几何节点对属性、实例、采样、材质、最终 mesh 的影响。

## Live Inspector 用法

Live Inspector 必须运行在 Blender/Goo 的 Python 里。用哪个 runtime 很重要：

- 普通 Blender 文件：用对应版本官方 Blender。
- Goo 文件：用 Goo Engine 的 `blender.exe`。

示例：

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'D:\Asset\scene.blend' --python 'C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools\SpecialTools\blender_live_inspector.py' -- --mode app --pretty
```

`--factory-startup` 可以避免后台模式里其它用户插件刷日志或报错。只有当某个 `.blend` 必须依赖用户插件注册自定义节点/数据时，才去掉它。

查看场景摘要：

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode scene --pretty
```

列出材质：

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode materials --pretty
```

查看单个材质：

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode material --material "M_actor_bounda_cloth_02.001" --pretty
```

搜索节点：

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode node --material "M_actor_bounda_cloth_02.001" --node "Screenspace" --pretty
```

比较 live 材质和已导出的 Material IR：

```powershell
& 'D:\Blender\Goo-Engine 4.4\blender.exe' --factory-startup --background 'scene.blend' --python 'SpecialTools\blender_live_inspector.py' -- --mode compare-material-ir --material "M_actor_bounda_cloth_02.001" --ir "C:\Users\hhh12\Desktop\M_actor_bounda_cloth_02_001.json" --pretty
```

比较结果里重点看：

- `match`：结构摘要是否一致。
- `count_diffs`：节点数、树数、链接数、图片数、组数是否变了。
- `node_type_diff`：节点类型是否变了，尤其 Goo 节点是否变成 `NodeUndefined`。
- `image_diff`：贴图名、路径、色彩空间是否变了。
- `group_diff`：节点组是否缺失或替换。

## Geometry Nodes 注意事项

Geometry Nodes IR 会记录 modifier 引用的 node group、节点、链接、接口、嵌套组、modifier 自定义输入参数，以及 zone 对。

Zone 节点不是普通节点：

- Simulation Zone 有状态和帧/缓存语义，迁移到 Unity 通常需要烘焙或重写运行时逻辑。
- Repeat Zone 是循环结构，能保留结构证据，但不能直接承诺 glTF 或 Unity 自动等价。
- For Each Geometry Element Zone 依赖元素域和几何迭代，通常需要按最终 mesh 结果迁移。
- Closure Zone 是较新的过程抽象，先保存结构并标记 `needs-review`。

如果目标是 Unity：

- 简单 Set Position / Set Material / Store Named Attribute 可以考虑导出 evaluated mesh 或转换成 Unity mesh 处理。
- Instance 类节点迁移前要确认是否 Realize Instances。
- Named Attribute / Capture Attribute / Store Named Attribute 要对照 Object Scene IR 里的 mesh attributes / color attributes。
- Raycast / Sample / Proximity 等节点通常不能直接进 glTF，需要烘焙或 Unity 侧脚本。

## Goo Engine 注意事项

Goo 文件要优先用 Goo Engine live inspector 或 Goo 导出的 IR。

如果用官方 Blender 打开 Goo 工程，可能出现：

- `ShaderNodeShaderInfo` 变成 `NodeUndefined`
- `ShaderNodeScreenspaceInfo` 变成 `NodeUndefined`
- Goo/NPR 光照、屏幕空间、半兰伯特、深度 rim 等语义丢失

这类节点不代表原工程坏了，而是 runtime 不匹配。迁移报告里要写清楚：

- 哪个 runtime 读取到了真实节点。
- 哪个 runtime 只看到 undefined。
- Unity 侧是否有对应的 shader / RendererFeature / depth color pass。

## 迁移到 Unity lilToon / lilPBR 的建议

角色、二次元、Goo PBRToon 材质通常优先看 lilToon：

- Base/Diffuse -> `_MainTex`
- Alpha -> cutout / transparent
- Normal -> `_BumpMap`
- MatCap -> `_MatCapTex`
- Rim / Fresnel -> Rim 参数
- Shadow / Ramp -> Shadow 色、边界、渐变或 LUT
- Outline 材质 -> lilToon outline 路线

偏物理、布料、湿润、雨水、各向异性时看 lilPBR：

- Packed PBR/Mask -> `_PBRMap` 或拆通道
- Metallic / Smoothness / AO -> 对应 channel 设置
- Wetness / Rain -> `_WetnessMode`、`_WetnessMask`、`_WetnessBumpMap`、`_RainScale`
- Anisotropy -> `_AnisotropyDirection`、`_AnisotropyMask`
- Screen Space AO / Reflection -> 需要项目 URP 管线支持

不能直接承诺自动还原：

- BSDF / Shader closure
- Goo `Shader Info`
- Goo `Screenspace Info`
- Scene Color / Scene Depth
- 复杂节点组里自定义光照模型
- RGB Curve / ColorRamp 造成的 look-dev 差异

## 给 AI 的推荐指令

快速评估：

```text
请使用 HoTools 的 IR 工具分析这个 Blender/Goo 材质迁移到 Unity 的可能性。
如果有 JSON，先跑 material_ir_ai.py 的 preview/audit/images/groups/inputs/goo。
如果有 .blend，可以用 blender_live_inspector.py 通过匹配的 Blender/Goo runtime 做 live 查询。
请区分：可以直接映射到 lilToon/lilPBR 的内容、需要 mapper 规则的内容、需要 Unity 自定义 shader/pipeline 的内容。
所有结论都要引用 node/socket/image/attribute 证据，不确定写 needs-review。
```

检查导出是否过期：

```text
请用 blender_live_inspector.py 的 compare-material-ir 检查当前 .blend 里的 live 材质和我提供的 Material IR JSON 是否一致。
重点看节点类型、Goo 节点、图片色彩空间、节点组、节点/链接数量是否发生变化。
如果不一致，请说明是导出过期、runtime 不匹配，还是材质本身被改过。
```

Goo 工程：

```text
这是 Goo Engine / Goo Blender 工程。请不要只按官方 Blender 节点理解。
先确认 app/source_flavor_hint 和 live inspector 中的 Goo 节点。
对 Shader Info、Screenspace Info、DepthRim、Toon、MatCap、Rain 等节点做迁移边界说明。
```

## 文件位置

- Material exporter: `SpecialTools/material_node_ir.py`
- Object/scene exporter: `SpecialTools/object_scene_ir.py`
- Geometry Nodes exporter: `SpecialTools/geometry_node_ir.py`
- Live inspector: `SpecialTools/blender_live_inspector.py`
- Material helper: `SpecialTools/material_ir_ai.py`
- Object helper: `SpecialTools/object_scene_ir_ai.py`
- Geometry Nodes helper: `SpecialTools/geometry_node_ir_ai.py`
- Joint helper: `SpecialTools/ir_joint_ai.py`
- Material skill: `SpecialTools/skills/material-node-ir/SKILL.md`
- Object skill: `SpecialTools/skills/object-scene-ir/SKILL.md`
- Live inspector skill: `SpecialTools/skills/blender-live-inspector/SKILL.md`

## 最佳实践

- JSON/Scene Bundle 用来留证，Live Inspector 用来快速问问题。
- Goo 工程用 Goo runtime，官方 Blender 只做基础节点参考。
- 大场景先 live 查，再导重点材质，最后才导全量 bundle。
- 迁移 lilToon/lilPBR 前，先生成可审查的 mapping JSON，不要直接写 Unity 资产。
- 所有自动判断都要能回到 node、socket、image、object attribute 证据。
