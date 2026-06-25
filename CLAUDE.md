# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

HoTools is a **Blender add-on** (`bl_info` version 2.2.0, target Blender **4.5** / Python **3.11**) — a large toolset for character/model/texture/animation workflows. It is loaded by Blender as a package; there is no standalone "run" entry point. Most code is Python operators/panels registered into Blender; a C++ native backend (`hotools_native`) accelerates a few physics hot paths.

Code, comments, UI strings, and the architecture docs are predominantly in **Chinese**. Match the surrounding language when editing user-facing strings and comments.

## Architecture

### Add-on registration (top level)

[__init__.py](__init__.py) is the add-on root. On import it appends `_Lib` and the Python-version-specific `_Lib/py311` (or `py313`) — plus `_Lib/<ver>/HotoolsPackage` (native runtime) — to `sys.path`, since Blender does not resolve nested module folders during install.

Each feature lives in its own top-level package, and every package exposes module-level `register()` / `unregister()`. The root `register()` calls each in turn. **To add or remove a feature module, wire it into both `register()` and `unregister()` in [__init__.py](__init__.py).** Two features are gated behind add-on preferences (`AddonPreference`) and registered conditionally: `OmniNode` (`hoTools_OmniNodeFeatures_enable`) and `exIcon` (`hoTools_enableExIcon`).

Feature packages: `FastOperators` (modeling/view), `BoneTools`, `PhysicsTools` (collision props + XPBD consumers), `ShapekeyTools`, `VertexGroupTools`, `VertexColorTools`, `UvTools`, `MeshTools`, `AnimationTools`, `Checker`, `NameMapping`, `Exporter`, `Rbf`, `exIcon`, and `OmniNode`. `HoAssets/` holds the bundled Blender asset library (registered via the `ho.register_asset_library` operator). `FastOperators.py` is an unusually large (~120 KB) single-file module of fast modeling operators.

Operators follow Blender's `bl_idname` convention, mostly namespaced `ho.*`.

### OmniNode (the node system)

`OmniNode/` is an optional node-based automation system built on Blender's `NodeTree`. It is the most architecturally involved part of the codebase — **read [OmniNode/ARCHITECTURE.md](OmniNode/ARCHITECTURE.md) before changing anything under `OmniNode/NodeTree/`.** Key invariants you must respect:

- **Functions generate nodes by default.** Business nodes are plain Python functions in `NodeTree/Function/*.py` marked `@omni(enable=True, ...)`; sockets come from the function signature (`list[T]` ⇒ multi-input). New functionality should almost always be a new function node, not a new `GraphNode`.
- **Compile vs. execute are separate.** `OmniCompiler` walks backward from `is_output_node` nodes, topo-sorts the reachable subgraph, and emits a `CompiledGraph` of IR (`OmniIR.py`). `OmniExecutor` runs only the IR — it never traverses Blender links at runtime. Nodes not connected to an output node never execute.
- **`GraphNode` is an IR-level exception**, only for things that change compilation/execution semantics (groups, batching, runtime cache, control flow, debug). Adding one means coordinated edits across `GraphNode.py`, `OmniIR.py`, `OmniCompiler.py`, `OmniExecutor.py`, and debug/timing.
- **Two distinct caches.** `_COMPILED_TREE_CACHE` caches `CompiledGraph` to avoid recompiling each frame; **runtime cache** (`OmniRuntimeState.py`, accessed only via Cache Read/Write/Delete/Dump GraphNodes) holds cross-frame business state. Clearing one does not affect the other. Any edit that changes nodes/sockets/links/tree-IO must clear the compile cache. Tree entry points: `compile_cached()`, `run()`, `run_compiled()`, `run_frame_cached()`, `clear_compile_cache()`.
- Runtime cache is session-only; cross-frame temp state must never hide in module globals, node fields, closures, or C++ statics.

### Native backend

`_native/` holds **only** C++ source, CMake project, and tests — never shipped runtime artifacts. Built `.pyd`/`.pdb` go to `_Lib/py311/HotoolsPackage` (Blender 4.1+/Py3.11) and `_Lib/py313/HotoolsPackage` (Blender 5.1+/Py3.13), which is what ships. Python prepares all Blender data (validation, `foreach_get`/`foreach_set`, runtime cache) and the C++ layer only crunches plain numeric arrays — it must not touch `bpy` or hold Blender pointers / cross-frame state. The pattern is **parallel nodes**: a Python blueprint node (`网格物理-XPBD`) and a `-CPP` node with identical I/O and cache semantics. See [_native/README.md](_native/README.md).

## Translate rule

No need to manual edit on the Claude working season. These translating jobs will be handled by other tool.

## Commands

There is no test runner, linter, or build step for the Python add-on itself — it is exercised by loading it in Blender. Iterating means reloading the add-on in Blender (Edit > Preferences > Add-ons), or installing the release zip.

### Native build (Windows / Visual Studio 2022)

Presets live in [_native/CMakePresets.json](_native/CMakePresets.json). The machine-specific tool paths in the docs (`D:\Microsoft Visual Studio\2022\...`, Blender Python paths) are environment-dependent — adjust to the local machine.

```powershell
# Configure (py311 for Blender 4.5, or py313 for Blender 5.1)
cmake --preset vs2022-py311
# Build Release (must specify the Release build preset for multi-config generators)
cmake --build --preset vs2022-py311-release
```

```powershell
# Native smoke test (use Blender's bundled Python, NOT system python)
& "<blender>\python\bin\python.exe" _native\tests\test_mesh_xpbd_native.py
# Import verification
& "<blender>\python\bin\python.exe" -c "import sys; sys.path.insert(0, r'<addon>\_Lib\py311\HotoolsPackage'); import hotools_native; print(hotools_native)"
```

The `.pyd` must be built against Blender's own Python ABI — do not use a default `python` / `py -3.11`.

### Release packaging

The Blender install zip is produced **only** by GitHub Actions on push to `main` (or manual dispatch) — see [.github/workflows/release.yml](.github/workflows/release.yml). It `rsync`s a clean `HoTools/` tree (excluding `.git`, `.github`, IDE dirs, `__pycache__`, `_native/`, `_build/`, `_dist/`, build dirs) into a timestamped `HoTools-YYYYMMDD-HHMMSS.zip`. Note `_Lib/*/HotoolsPackage` is **not** excluded — native runtime artifacts must ship. `.gitignore` only prevents local mis-commits; the workflow's excludes decide what users install. Do not hand-zip releases.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **HoTools** (15435 symbols, 32879 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/HoTools/context` | Codebase overview, check index freshness |
| `gitnexus://repo/HoTools/clusters` | All functional areas |
| `gitnexus://repo/HoTools/processes` | All execution flows |
| `gitnexus://repo/HoTools/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
