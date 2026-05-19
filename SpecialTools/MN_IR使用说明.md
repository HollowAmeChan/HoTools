# Material Node IR 使用说明

这个工具用于把 Blender 材质节点树导出成 AI 和脚本都容易理解的中间格式，方便后续做 glTF 材质迁移、Unity Shader Graph 对接、材质差异分析、贴图/色彩空间检查。

## 你会得到什么

导出器可以生成两类文件：

- `.json`：完整 IR，适合 AI、脚本、转换工具读取。这是最重要的源文件。
- `.md`：给人和 AI 快速阅读的摘要，不保证包含所有细节。

一般建议先导出 `JSON + Markdown`。真正做转换判断时，以 JSON 为准。

## 在 Blender 里导出

1. 打开 Blender，启用 HoTools 插件。
2. 选中带材质的物体，确保它有一个正在使用节点的材质。
3. 打开 `Shader Editor`。
4. 按 `N` 打开右侧侧栏。
5. 找到 `HoTools > Material Node IR`。
6. 选择：
   - `JSON`：只导出完整机器可读数据。
   - `MD`：只导出 AI 阅读摘要。
   - `Export JSON + Markdown`：两个都导出，推荐。

如果材质没有启用节点，面板会提示无法导出。

## 在外部项目里快速查看

`SpecialTools/material_ir_ai.py` 是无 Blender 依赖的纯 Python 文件，可以复制到其他项目使用。它只依赖 Python 标准库。

常用命令：

```powershell
python SpecialTools/material_ir_ai.py material_ir.json --mode context
python SpecialTools/material_ir_ai.py material_ir.json --mode summary
python SpecialTools/material_ir_ai.py material_ir.json --mode pbr
python SpecialTools/material_ir_ai.py material_ir.json --mode images
python SpecialTools/material_ir_ai.py material_ir.json --mode source
python SpecialTools/material_ir_ai.py material_ir.json --mode source --source-profile goo
python SpecialTools/material_ir_ai.py material_ir.json --mode goo
python SpecialTools/material_ir_ai.py material_ir.json --mode audit
python SpecialTools/material_ir_ai.py material_ir.json --mode preview
python SpecialTools/material_ir_ai.py material_ir.json --mode annotations
python SpecialTools/material_ir_ai.py material_ir.json --mode colors
```

各模式用途：

- `context`：生成一段适合直接贴给 AI 的材质上下文。
- `summary`：输出节点数量、节点类型统计、贴图列表等 JSON 摘要。
- `pbr`：尝试提取根层 Principled BSDF 到 glTF PBR 的候选来源。
- `images`：分析贴图、色彩空间、路径、格式、重复引用、采样方式、packed/dirty 状态。
- `source`：按 IR 里的 Blender 版本生成官方 Blender 源码对照链接。
- `goo`: check whether the material may come from Goo Engine/forked Blender, and output Goo source search hints.
- `cleanup`：找出没有连接到输出节点的“可能垃圾节点”。
- `groups`：特别分析节点组、接口、内部未使用节点、内部驱动器。
- `annotations`：分析 Blender 节点编辑器里的 Frame 框、节点 label、节点自定义颜色。
- `colors`: analyze ColorRamp and RGB/Float/Vector Curve nodes. If detail is missing, re-export from Blender with the updated exporter.
- `drivers`：判断 value/default socket 是否存在驱动器，不展开驱动器内容。
- `inputs`：找 UV、Object Info、Attribute、Geometry、Vertex Color 等上下文输入节点。
- `audit`：一次性输出迁移前最常用的综合检查，推荐先跑。
- `preview`：输出适合对话界面快速展示的预估报告，包括节点树能力、设计意图、迁移变化、风险和边界。

## 推荐的 AI 分析顺序

1. 如果用户只想快速了解，先跑：

```powershell
python SpecialTools/material_ir_ai.py material_ir.json --mode preview
```

2. 如果要正式分析，再跑：

```powershell
python SpecialTools/material_ir_ai.py material_ir.json --mode audit
```

3. 如果 audit 里出现对应问题，再细看：

```powershell
python SpecialTools/material_ir_ai.py material_ir.json --mode cleanup
python SpecialTools/material_ir_ai.py material_ir.json --mode groups
python SpecialTools/material_ir_ai.py material_ir.json --mode annotations
python SpecialTools/material_ir_ai.py material_ir.json --mode colors
python SpecialTools/material_ir_ai.py material_ir.json --mode images
python SpecialTools/material_ir_ai.py material_ir.json --mode drivers
python SpecialTools/material_ir_ai.py material_ir.json --mode inputs
```

解释边界：

- `preview` 是给对话界面看的快速预估，不是最终转换计划。
- `cleanup` 只说明节点没有流向输出，不代表一定可以删。可能是备注、临时实验、Frame、或者作者有意保留。
- `groups` 对节点组要更谨慎，因为组内输入/输出、内部默认值、内部驱动器都可能影响最终材质。
- `annotations` 会把 Frame 框、节点 label、自定义颜色当作作者留下的语义线索。Frame 里的节点很可能应该一起解释或一起迁移为 Shader Graph 注释/子图。
- `colors` 会检查 ColorRamp 和 RGB/Float/Vector Curve。复杂调色需要色标/曲线点；如果提示缺少 detail，请重新从 Blender 导出。
- `images` 会检查重复贴图、采样方式、色彩空间、packed 和 dirty。贴图用途不要只看文件名，要看链接到哪个 socket。
- `drivers` 只判断有没有驱动器。当前版本不解析驱动器表达式，也不求值。
- `inputs` 会标出 UV、Object Info、Attribute、Geometry 等上下文依赖。这些信息可能超出材质 IR 本身，需要 mesh、object 或导入器额外支持。

## 查看 Blender 官方源码

Blender 是开源的，很多节点可以直接对照官方源码理解。推荐流程：

1. 先看 IR 的 `blender_version`，例如 `[4, 5, 0]` 对应源码标签 `v4.5.0`。
2. 如果你的 Blender 是 4.5 LTS 的更高补丁版，优先用实际导出版本的标签，例如 `v4.5.9`。
3. 运行：

```powershell
python SpecialTools/material_ir_ai.py material_ir.json --mode source
```

4. 输出里会给每类节点的官方链接：
   - GitHub mirror：适合快速打开和搜索。
   - projects.blender.org：Blender 官方上游仓库。

源码对照时要注意边界：

- Math、Vector Math、Map Range、Mix、ColorRamp、Noise、Voronoi、Wave、Bump、Normal Map 这类节点通常比较适合看源码后迁移。
- BSDF、Volume、Add Shader、Mix Shader、Output 这类节点涉及渲染管线、光照、BRDF、采样、色彩管理，很难靠单个节点源码精确迁移。
- 对 BSDF 类节点，通常只提取可确认的 PBR 输入来源；完整外观应标记为 `needs-review`。
- 源码用于解释节点行为，最终迁移判断仍然要以当前导出的 IR 为证据。

## Goo Engine 支持

很多复杂配布可能来自 Goo Engine 改版 Blender。用户可以主动告诉 AI：

```text
这个材质可能是 Goo Engine / Goo Blender 做的，请用 HoTools 的 --mode goo 和 --source-profile goo 做源码对照。
```

如果用户不知道，AI 也会保守提示：

- 如果 IR metadata 里有 Goo 字样，会提示强疑似 Goo。
- 如果出现官方 Blender 映射不到的 ShaderNode，会提示可能是 Goo/fork 节点。
- 如果出现 toon、matcap、NPR、anime 这类命名线索，会提示可能来自 Goo/NPR 工作流，但不会当成事实。

常用命令：

```powershell
python SpecialTools/material_ir_ai.py material_ir.json --mode goo
python SpecialTools/material_ir_ai.py material_ir.json --mode source --source-profile goo
python SpecialTools/material_ir_ai.py material_ir.json --mode source --source-profile both
```

Goo 仓库：

```text
https://github.com/dillongoostudios/goo-engine/tree/goo-engine-main
```

边界：Goo/NPR 的渲染效果可能依赖 fork 里的 EEVEE/渲染管线行为，不能只靠节点 socket 精确迁移。

## 推荐给 AI 的一句话

如果 AI 能访问这个工具目录，直接这样说：

```text
请使用 HoTools/SpecialTools/skills/material-node-ir/SKILL.md 作为规则，用 HoTools/SpecialTools/material_ir_ai.py 读取我提供的 material IR JSON。所有 Blender 到 glTF/Unity 的判断必须基于 JSON 证据；不确定的地方标记为 needs-review，不要脑补。
```

如果 AI 只能看到导出的 JSON 和 Markdown，可以这样说：

```text
这是 Blender 材质节点导出的 HoTools Material Node IR。请先阅读 JSON，Markdown 只当摘要。请分析它如何迁移到 glTF/Unity：列出可直接映射的 PBR 字段、需要 Shader Graph/自定义 shader 的节点、贴图色彩空间风险、以及所有不确定项。不要把没有证据的猜测当成结论。
```

## 分析 glTF/Unity 迁移的指令模板

```text
请基于这个 HoTools Material Node IR JSON 做 Blender 到 Unity/glTF 材质迁移分析。

输出格式：
1. 材质概览：材质名、主要 shader 节点、贴图数量。
2. glTF PBR 映射表：baseColor、metallic、roughness、normal、alpha、emission 每项的来源。
3. Unity 导入建议：每张贴图的用途、sRGB/Linear 建议、Normal Map 设置建议。
4. 需要人工确认的节点：列出 Math、Mix、ColorRamp、Bump、NormalMap、NodeGroup 等不能安全直译的部分。
5. 官方源码对照：如需要，请使用 --mode source 给出的 Blender 官方源码链接；说明你检查的 Blender tag。
6. 风险：列出会导致 Blender 与 Unity 效果不一致的地方。

规则：
- 只使用 JSON 中存在的信息。
- 没有证据时写 needs-review。
- 不要假设贴图命名一定正确。
- Markdown 摘要只能辅助阅读，不能替代 JSON。
- BSDF/Volume/Shader 闭包节点不要声称可以精确迁移，只能做边界说明或提取明确 PBR 输入。
```

## 快速预估指令模板

```text
请基于这个 HoTools Material Node IR JSON，先给用户一个对话界面可读的快速预估。

请覆盖：
1. 这个节点树大概具备什么能力。
2. 你推断它的材质设计意图是什么。
3. 迁移到 glTF/Unity 后最可能发生哪些变化。
4. 哪些内容风险高，哪些内容只是边界说明。
5. 下一步应该跑哪些详细检查。

规则：
- 这是预估，不是最终转换计划。
- 只根据 JSON 和 helper 输出判断。
- 对 BSDF/Volume/Shader 闭包节点说明边界，不承诺视觉完全一致。
- 对节点组、图像色彩空间、驱动器、上下文输入、未连接节点要特别提示。
- 对 Frame 框、节点注释、节点颜色要作为作者意图提示，不要忽略。
- 对 ColorRamp、RGB Curves、Float/Vector Curves 要检查是否有具体色标/曲线点；没有就要求重新导出。
```

## 让 AI 生成转换代码的指令模板

```text
请基于这个 HoTools Material Node IR JSON，生成一个材质转换计划和代码草案。

目标平台：Unity。
目标形式：先生成可审查的映射数据结构，不要直接写入 Unity 工程。

要求：
- 输入是 HoTools Material Node IR JSON。
- 输出一个包含材质名、贴图引用、PBR 字段来源、Unity 导入设置建议、needs-review 列表的 JSON。
- 对不能安全转换的节点保留原始 node name、bl_idname、输入来源链路。
- 不要丢弃无法识别的节点。
- 代码只使用标准库，除非我明确允许依赖。
```

## 让 AI 查问题的指令模板

```text
请检查这个 HoTools Material Node IR JSON，找出为什么导入 Unity 后材质可能不一致。

重点检查：
- Base Color、Alpha、Metallic、Roughness、Normal、Emission 的来源是否清楚。
- Image Texture 的 colorspace 是否符合用途。
- Image Texture 是否重复使用，采样方式、extension、projection 是否会影响 Unity 表现。
- 是否存在 ColorRamp、Mix、Math、Bump、NormalMap、NodeGroup 等需要特殊处理的节点。
- 是否存在未连接到输出的节点；只列出，不要直接要求删除。
- 是否存在节点组内部逻辑、内部未使用节点或内部驱动器。
- 是否存在 Frame 框、节点 label、节点自定义颜色；这些可能表示作者希望一起看的逻辑区域。
- 是否存在 ColorRamp、RGB Curves、Float/Vector Curves；如果缺少色标/曲线点，需要重新导出。
- 是否存在被驱动的 value/default socket；只判断有无，不解析驱动器内容。
- 是否存在 UV、Object Info、Attribute、Geometry、Vertex Color、Tangent 等上下文输入节点。
- 是否有 socket 默认值在 Blender 中重要但 glTF/Unity 可能丢失。
- 是否有链接链路太复杂，应该人工复核。

请按严重程度排序，并给出每条问题对应的 node name 和 socket name。
```

## 最佳实践

- 给 AI 时优先提供 `.json`，再提供 `.md`。
- 复杂材质要保留完整节点组导出，不要只截屏。
- 贴图色彩空间不要只靠文件名判断，以 IR 里的 `image.colorspace` 为证据。
- AI 输出迁移结论时，要求它标明每个判断来自哪个 node/socket/link。
- 第一次做自动转换时，先生成“转换计划 JSON”，确认后再写 Unity 侧资产或 Shader Graph。

## 文件位置

- Blender 导出器：`SpecialTools/material_node_ir.py`
- 外部 AI 辅助脚本：`SpecialTools/material_ir_ai.py`
- AI skill：`SpecialTools/skills/material-node-ir/SKILL.md`
- IR schema 参考：`SpecialTools/skills/material-node-ir/references/ir-schema.md`
