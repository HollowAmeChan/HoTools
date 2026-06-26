# ROADMAP — 多语言支持 / Multilingual Support

Status: **Planned**
Target: HoTools 2.3.0 · Blender 4.5 / Python 3.11
Default language: **简体中文 (zh_HANS)** · Initial locales: `zh_HANS` (base), `en_US`, `ja_JP`

---

## 1. Goal

Make every user-facing string in HoTools translatable, with:

- **Default = Chinese.** Chinese source text stays in the code and acts as the translation key (msgid). If a translation is missing, the UI falls back to Chinese automatically.
- **Per-addon language switch** in the addon Preferences panel that affects **only HoTools**, not Blender's global UI.
- **`AUTO` default** that inherits Blender's current UI language (`bpy.app.translations.locale`) when the user hasn't chosen an explicit language.

### Why a custom wrapper (design decision)

Blender's native `bpy.app.translations` only translates against Blender's **global** locale (`preferences.view.language`). It cannot show HoTools in English while the rest of Blender is in Chinese. Because we want an **independent per-addon** switch (confirmed requirement), we introduce a thin lookup layer `tr()` that:

1. resolves the _effective locale_ (addon pref, or Blender's locale when pref is `AUTO`), and
2. looks the string up in our own locale dictionaries, falling back to the Chinese key.

We still **also** register the same dictionaries with `bpy.app.translations.register()` so that any string we cannot easily wrap (some auto-translated enum/tooltip contexts, OmniNode socket labels) gets best-effort native translation when the addon language follows Blender.

---

## 2. Target architecture

```
HoTools/
  i18n/
    __init__.py          # public API: tr(), tr_iface(), current_locale(),
                         #             register(), unregister(), reload()
    manager.py           # locale resolution, dict merge, pref/AUTO logic,
                         #     bpy.app.translations.register hookup
    locales/
      __init__.py
      zh_HANS.py         # base / msgid reference (may be empty: key == value)
      en_US.py           # { "中文原文": "English text", ... }
      ja_JP.py           # { "中文原文": "日本語", ... }
    tools/
      extract.py         # scan source -> emit/update locale stub dicts
```

### Public API (stable surface every module imports)

```python
from ..i18n import tr            # tr("中文原文") -> localized str (key fallback)
# panels:        layout.label(text=tr("信息"))
# operators:     bl_label = ...  # see §4 for the operator pattern
```

- **Key = Chinese source string.** Lowest migration friction, graceful fallback, mirrors Blender's msgid model. (Stable symbolic keys were considered and rejected: they'd require touching 1000+ sites _and_ writing a zh dict before anything renders.)
- Optional translation **context** (`ctxt`) param for disambiguating identical Chinese words that translate differently.
- `current_locale()` returns the resolved locale; `reload()` is called by the pref `update=` callback so switching language redraws immediately.

### Preference (in `AddonPreference`, `__init__.py`)

```python
hoTools_language: EnumProperty(
    name="语言 / Language",
    items=[
        ('AUTO',    "自动 (跟随 Blender)", ""),
        ('zh_HANS', "简体中文",            ""),
        ('en_US',   "English",            ""),
        ('ja_JP',   "日本語",             ""),
    ],
    default='AUTO',
    update=lambda self, ctx: i18n.reload(),
)
```

Drawn at the **top** of `AddonPreference.draw()`.

---

## 3. Phases

### Phase 0 — Decisions & inventory ✅ (this doc)

- [x] Switch scope: **independent per-addon**.
- [x] Initial locales: `zh_HANS` (base) + `en_US` + `ja_JP`.
- [x] Key strategy: Chinese source as msgid.
- [x] Confirm string surface count via extractor dry-run. Measured 2026-06-25 (HoTools sources only, excluding vendored `_Lib/` and `_native/tests`):

  | Surface                      |      Count | Notes                                                                                             |
  | ---------------------------- | ---------: | ------------------------------------------------------------------------------------------------- |
  | `bl_label=`                  |        495 |                                                                                                   |
  | `bl_description=`            |        172 |                                                                                                   |
  | **operator labels subtotal** |    **667** | matches the ~666 estimate                                                                         |
  | `text="…"`                   |        494 | 506 raw − 12 vendored `cffi`                                                                      |
  | property `name="…"`          |        458 | 510 raw − 50 `_Lib` (PIL/cffi/pycparser) − 2 `_native` tests; includes some non-UI `name=` kwargs |
  | property `description="…"`   |        188 | excludes `bl_description`                                                                         |
  | `self.report(…)`             |        405 | call sites; not all carry a literal string                                                        |
  | **gross total**              | **≈ 2212** | upper bound; `name=`/`report()` over-count non-translatable + duplicate strings                   |

  Core translatable surface (`bl_label`/`bl_description` + `text=`) ≈ **1161**, confirming the doc's ~1100+ estimate. Heaviest files: `UvTools/baker.py`, `FastOperators.py`, `VertexGroupTools/vertexGroupOperators.py`, `PhysicsTools/collision*.py`, `ShapekeyTools/operators.py`, and the `OmniNode/NodeTree/Function/*` node functions. Enum item labels still need the Phase 2 AST extractor for an exact count (regex undercounts inline tuple labels).

### Phase 1 — i18n foundation (no behavior change) ✅ (2026-06-25)

- [x] Build `i18n/` package: `manager.py` (locale resolution + dict merge + `bpy.app.translations.register`), `__init__.py` API, `locales/` (`zh_HANS`/`en_US`/`ja_JP` empty stub dicts + `all_dicts()`).
- [x] Add `hoTools_language` `EnumProperty` to `AddonPreference`; selector drawn at the **top** of `draw()`. `update=` calls `i18n.reload()`.
- [x] Wire `i18n.register()` / `i18n.unregister()` into root `register()`/`unregister()` in [**init**.py](__init__.py) — registers **first** (before classes/feature modules), unregisters **last** (after `OmniNode.unregister()`), so `tr()` is live throughout.
- [x] Unit-smoke (`i18n/` logic, bpy stubbed): `tr("任意中文")` → key when no locale data; `AUTO` → `bpy.app.translations.locale`; explicit pref overrides AUTO; `zh_CN`→`zh_HANS` / unknown→base normalization; `ctxt` lookup; translated value + missing fallback. 10/10 pass.
- **Exit:** addon loads unchanged in Blender, language selector visible, everything still Chinese. ✅ (Chinese default holds — `tr()` returns the Chinese key until Phase 3 wraps call sites and Phase 2 fills the dicts.)

**Phase 1 notes for Phase 3:** `tr` accepts an optional `ctxt`; lookup tries `(ctxt, msgid)` then plain `msgid`. `tr_iface` is currently an alias of `tr`. `current_locale()` is cached; `reload()` clears the cache and tag-redraws all areas. The `bpy.app.translations` bridge (`_register_bpy_translations`) is wired but a no-op while dicts are empty (registers nothing) — it activates automatically once Phase 2 populates `en_US`/`ja_JP`.

### Phase 2 — Extraction tooling ✅ (2026-06-25)

- [x] [i18n/tools/extract.py](i18n/tools/extract.py): **AST** scan (not regex) for `bl_label`/`bl_description` class attrs, `text=`/`name=`/`description=` call kwargs, `EnumProperty(items=[...])` labels (idx 1) + descriptions (idx 2), and `self.report({...}, "…")` messages. Filters to **Han-containing** strings only (the Chinese key model), so ASCII identifiers aren't pulled in. Keys stored **verbatim** (no whitespace normalization) to guarantee exact runtime `tr()` match; near-duplicates are _reported_, not merged. Merges into `en_US.py`/`ja_JP.py` as `key -> ""` stubs, **never clobbering** existing values; source-removed-but-translated keys retained as **orphans**. Tolerates stray BOMs; skips unparseable files with a warning. Standalone script — deliberately does **not** import the `i18n` package (no `bpy`), runs outside Blender.
- [x] Coverage report: per-locale `translated/total (%)`, orphan count, per-category hit breakdown, near-dup groups, skipped files. `--dry-run` (report only) and `--check` (CI: exit 1 if stale) modes.
- **Exit:** ✅ first run wrote 1204 stub keys to each locale; rerun is idempotent (`--check` → `最新`, exit 0). Merge/roundtrip/orphan/CJK logic unit-tested (10/10).

**Measured (2026-06-25):** **1515 hits → 1204 unique Chinese keys** — `bl_label/desc` 424, `text/name/desc` 763, `enum item` 87, `report()` 241. Both `en_US`/`ja_JP` at 0/1204 (0%) — translation values are hand-filled next. (Unique-key 1204 < the Phase 0 raw site count because the AST scan dedups, ignores ASCII-only strings, and only counts string-literal `report()` args.)

**Run:** `python i18n/tools/extract.py` (rerun after adding any new Chinese string). `i18n/tools/` is dev-only — add to the release-workflow excludes in Phase 5.

### Phase 3 — Static UI migration (panels & operators, per-module) ✅ (2026-06-26)

Order by user visibility / size. One module per PR; **run GitNexus `impact` before editing each module's registered symbols** (per repo rules) and `detect_changes` before commit.

**Progress:**

- [x] **1. `__init__.py`** (2026-06-25) — `OP_register_asset_library` (§4 pattern: `description()` classmethod + wrapped `report()`), `AddonPreference.draw()` call-site `text=i18n.tr(...)` on operator + props. 9 keys filled in `en_US`/`ja_JP`. Compiles; end-to-end `tr()` verified (en/ja/zh fallback + bridge). Language enum _item_ labels left untranslated by design (each is its own language's endonym).
- [x] **2. `PhysicsTools`** (2026-06-25) — all 8 files. `collisionPanel.py` (labels + bare-`prop()` `text=tr(name)` + f-string splits), `collisionOperators.py` (9 ops: §4 `description()` classmethods, `report()` constants wrapped, dynamic reports → `tr("…{n}…").format()` templates, `invoke_props_dialog` draw labels, call-site operator button `text=`), `collisionPreview.py` panel. `collisionProperty.py`/`collisionUtils.py` need **no source edits** (frozen `name=`/`description=`/enum flow via native bridge; panel call-sites cover the independent switch). **96 high-visibility keys** filled EN+JA (titles, buttons, prop labels, enum items, status messages, operator tooltips); long paragraph-length property descriptions left as graceful-fallback stubs. All 8 compile; extractor idempotent (1215 keys, orphan=0); end-to-end `tr()` + `{n}` template verified.
- [ ] 3. `ShapekeyTools`/`VertexGroupTools`/`VertexColorTools` —
  - **VertexColorTools ✅** (2026-06-25: panel + 7 operators across `ops_base`/`ops_templates`/`ops_utils`/`bake_normal`; `description()` classmethods, `report()`/`RuntimeError` wrapped, f-string→`{i}` templates, 37 keys EN+JA; all compile, idempotent). _Known minor gap: `bake_normal.MODE_ITEMS` dialog labels left unwrapped (dynamic loop var, not auto-extractable)._
  - **ShapekeyTools 🚧** (2026-06-25: `__init__` panel title + `manager.py` reorder `report()` wrapped; 15 manager keys translated EN+JA. **Pending: `operators.py` (~82 KB, ~49 sites), `transfer.py` (~18), `multiObjectFlow.py` (~9), and `description()`/call-site `text=` for manager's 13 icon-only list ops.** _Gap: `ho_ShapekeyToolsPanel_Mod` enum-`expand` labels `管理`/`传递` aren't extractable/call-site-overridable → native-bridge only._)
  - **VertexGroupTools ✅** (`vertexGroupOperators.py`: codemod-wrapped, 83 `text=`/`report` + 20 `description()`).
- [x] **4. `BoneTools`/`UvTools`/`MeshTools` ✅ · 5. `FastOperators.py` ✅ · 6. `AnimationTools`/`Exporter`/`NameMapping`/`Checker`/`Rbf`/`exIcon` ✅** — completed 2026-06-26 via verified codemod (see below).

**Phase 3 completion (2026-06-26).** Remaining modules wrapped with a conservative, idempotent **AST/regex codemod** (`scratchpad/wrap_tr.py` + `fstr_tr.py` + `robust_fstr.py`), each pass `ast.parse`-validated before write, then `py_compile` on all 120 addon files + extractor `--check`:

- **`text="…"` / `.report({…}, "…")` constant literals** → `tr(...)` (CJK-gated, triple-quote/f-string-safe, idempotent — already-wrapped sites never re-match).
- **Operator `bl_description = "…"`** → added a §4 `@classmethod description()` returning `tr(...)` (guarded against duplicates).
- **Dynamic f-strings** in `text=`/`report` → `tr("…{0}…").format(...)` templates: simple fields via regex, complex (format-specs/subscripts/conversions) via an **AST converter** using `ast.unparse` + UTF-8 byte→char span mapping.
- **`OmniNode/NodeTree/GraphNode.py`** (missed in Phase 4) also wrapped.
- `bl_label`-only strings (icon buttons, enum-`expand` items, property `name=`/`description=`, socket-type labels) are **not** call-site-wrapped by design — they're frozen at register and localize via the `bpy.app.translations` native bridge in AUTO/follow-Blender mode (the dicts are filled, so this works). Independent-switch tooltip localization for pure icon-ops is the documented residual gap.
- **Result:** all 120 files compile; extractor idempotent, **orphan=0**, **1336 keys** (the +84 new f-string templates are stubbed for translation). Coverage 1252/1336 (93.7%) — the stubs are the only untranslated keys.

**Earlier per-module notes (modules 1–3, hand-wrapped):**

**Coverage after module 2:** 105/1215 keys translated (8.6%). **Translation-scope decision:** with 1215 keys (many paragraph-length tooltips), each module fills the _visible_ surface (titles/buttons/labels/enum/messages/operator tooltips) now; long descriptive `description=` strings stay as stubs and fall back to Chinese gracefully — a dedicated translation pass (or OpenCode delegation, per CLAUDE.md) can complete them later. **Dev helper:** `scratchpad/fill.py` applies a `{key:(en,ja)}` mapping via the extractor's own render (stays idempotent); not shipped.

**Extractor enhancement (required by this phase):** wrapping a literal in `tr()` removes it from the `text=`/`report()` literal patterns, so [extract.py](i18n/tools/extract.py) now **also harvests `tr()`/`tr_iface()`/`i18n.tr()` call arguments** (incl. positional/`ctxt=`). Without this, every wrapped `report()`-only string becomes an orphan. Verified: post-wrap `__init__.py` keeps all keys live (1204, orphan=0).

> **Note (this session):** GitNexus MCP tools are not connected here, so the mandated `impact`/`detect_changes` gate could not be run for module 1. The edits are string-wrapping only (no idname/signature/registration changes), but rerun the gate before merging.

Migration unit per module:

- Wrap `layout.label/operator/prop(text=…)` and dynamic `report()` strings with `tr(...)`.
- For operators, adopt the operator pattern in §4.
- Fill `en_US` / `ja_JP` for that module's keys.

Suggested sequence:

1. `__init__.py` (Preferences UI, asset-library operator)
2. `PhysicsTools` (`collisionPanel.py` is the largest panel surface)
3. `ShapekeyTools`, `VertexGroupTools`, `VertexColorTools`
4. `BoneTools`, `UvTools`, `MeshTools`
5. `FastOperators.py` (large single file — budget extra time)
6. `AnimationTools`, `Exporter`, `NameMapping`, `Checker`, `Rbf`, `exIcon`

- **Exit:** all static panels/operators render in selected language; Chinese unchanged at default.

### Phase 4 — OmniNode (dynamic) localization ✅ (2026-06-26)

OmniNode generates node labels/sockets from `@omni` functions (see [OmniNode/ARCHITECTURE.md](OmniNode/ARCHITECTURE.md)). Translation must happen at **node draw/registration time**, not in the compiled IR (IR is cached and language-independent — keep it that way).

- [x] **Node header labels** — `OmniNode.draw_label()` ([OmniNode/NodeTree/OmniNode.py](OmniNode/NodeTree/OmniNode.py)) now returns `tr(bl_label)` at draw time. Display-only: never mutates `self.name` (compile/cache key), never touches caches. Graceful fallback unit-tested 6/6 — untranslated → exact old behavior (`self.name`); translated → localized label with Blender auto-suffix (`.001`) and user F2-renames preserved.
- [x] **Socket display names** — all custom sockets in [OmniNodeSocket.py](OmniNode/NodeTree/OmniNodeSocket.py) wrap `layout.label(text=tr(self.name))` / `prop(..., text=tr(text))` in `draw()`. Sockets keep their real `name`/`identifier` (compile keys) untouched.
- [x] **Confirmed cache invariant** — compile cache key is `f"tree:{int(tree.as_pointer())}"` (pointer-based, locale-independent); compiler keys on `node.name`/`socket.identifier`. `i18n.reload()` only clears the *locale* cache + tag-redraws; it never calls `clear_compile_cache()` or touches `_COMPILED_TREE_CACHE`/runtime cache. **Language switch forces no recompile and does not touch runtime cache.**
- [x] **Operator/panel strings (Phase 3 pattern)** — [OmniNodeOperator.py](OmniNode/NodeTree/OmniNodeOperator.py) (12 `description()` classmethods, constant + `{name}`/`{n}` template reports, sidebar draw labels), [OmniNodePanel.py](OmniNode/OmniNodePanel.py) (all buttons), [OmniNodeTree.py](OmniNode/NodeTree/OmniNodeTree.py) (tree IO + debug panel), `OmniCurveSocketPresetPopup` (`description()` + error msgs). All compile; extractor idempotent (1238 keys, orphan=0).
- **Exit:** ✅ node editor labels/sockets localized; compile & runtime caches behave identically across languages.

**Phase 4 gaps (native-bridge only, frozen-at-register — not call-site localizable):** Add-menu node-item labels via `nodeitems_utils` (`OmniNodeRegister.py`); socket-type `bl_label`s in the socket-type menus; node category labels are already English/neutral so out of the Chinese-key model. These translate only when the addon follows Blender's locale (AUTO). The new OmniNode keys (14) are stubbed for later translation.

### Phase 5 — QA, docs, release

- [ ] Manual matrix: each locale × `AUTO`(Blender zh/en) × switch-at-runtime redraw.
- [ ] Verify fallback: untranslated key → Chinese, never blank/error.
- [ ] Verify global Blender language is **untouched** by the addon switch.
- [ ] Coverage report ≥ target (e.g. 100% en_US, ≥90% ja_JP) — gaps fall back gracefully.
- [ ] Update [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md): how to add a translatable string, run the extractor, add a locale.
- [ ] Confirm `i18n/` ships (it lives under the addon root; not in the release-workflow exclude list — verify against [.github/workflows/release.yml](.github/workflows/release.yml)). `i18n/tools/` may be excluded as dev-only.
- [ ] Bump `bl_info` version → 2.3.0.

---

## 4. Operator label pattern (gotcha)

`bl_label` / `bl_description` are **class attributes evaluated at registration time**, so `tr()` there freezes the language at register and won't react to a runtime switch. Use Blender's per-instance hooks instead:

```python
class OP_Foo(Operator):
    bl_idname = "ho.foo"
    bl_label = "做某事"            # Chinese key, also the msgid
    bl_description = "执行某事"

    @classmethod
    def description(cls, context, properties):
        return tr("执行某事")       # re-evaluated each tooltip

    # menu/button labels: pass text=tr("做某事") at the call site
```

- Button/menu text: prefer `layout.operator("ho.foo", text=tr("做某事"))` at the **call site** (re-evaluated every redraw) over relying on `bl_label`.
- `report()` strings: wrap inline — `self.report({'INFO'}, tr("已完成"))`.
- Keep the Chinese on the class attribute too, so it doubles as the `bpy.app.translations` msgid and the AUTO/native path still works.

---

## 5. Risks & mitigations

| Risk                                                 | Mitigation                                                                                                                                      |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 1000+ edit sites → high regression surface           | Per-module PRs; GitNexus `impact`/`detect_changes` gate each (repo rule); Chinese fallback means a missed wrap degrades gracefully, not breaks. |
| `bl_label` frozen at register time                   | Use `description()` classmethod + call-site `text=tr()` (§4).                                                                                   |
| OmniNode IR cache pollution by locale                | Translate only at draw layer; never key compilation/runtime cache on locale (§4 / Phase 4).                                                     |
| Identical Chinese word, different translations       | `ctxt` param on `tr()`.                                                                                                                         |
| Duplicate/near-duplicate source strings inflate dict | Extractor reports duplicates; normalize whitespace on key.                                                                                      |
| Translation drift as code changes                    | Idempotent extractor + coverage report in CI/PR checklist.                                                                                      |
| Release zip omits `i18n/`                            | Explicit check in Phase 5 against the workflow excludes.                                                                                        |

---

## 6. Out of scope (v1)

- Translating the C++ native backend (`_native/`) — it touches no UI strings.
- RTL languages / pluralization rules.
- Crowd-sourced/online translation pipeline (locale files are hand-edited Python dicts for now).
- Translating bundled asset names in `HoAssets/`.
