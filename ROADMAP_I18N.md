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

1. resolves the *effective locale* (addon pref, or Blender's locale when pref is `AUTO`), and
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

- **Key = Chinese source string.** Lowest migration friction, graceful fallback, mirrors Blender's msgid model. (Stable symbolic keys were considered and rejected: they'd require touching 1000+ sites *and* writing a zh dict before anything renders.)
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

### Phase 0 — Decisions & inventory  ✅ (this doc)
- [x] Switch scope: **independent per-addon**.
- [x] Initial locales: `zh_HANS` (base) + `en_US` + `ja_JP`.
- [x] Key strategy: Chinese source as msgid.
- [x] Confirm string surface count via extractor dry-run. Measured 2026-06-25 (HoTools sources only, excluding vendored `_Lib/` and `_native/tests`):

  | Surface | Count | Notes |
  |---|---:|---|
  | `bl_label=` | 495 | |
  | `bl_description=` | 172 | |
  | **operator labels subtotal** | **667** | matches the ~666 estimate |
  | `text="…"` | 494 | 506 raw − 12 vendored `cffi` |
  | property `name="…"` | 458 | 510 raw − 50 `_Lib` (PIL/cffi/pycparser) − 2 `_native` tests; includes some non-UI `name=` kwargs |
  | property `description="…"` | 188 | excludes `bl_description` |
  | `self.report(…)` | 405 | call sites; not all carry a literal string |
  | **gross total** | **≈ 2212** | upper bound; `name=`/`report()` over-count non-translatable + duplicate strings |

  Core translatable surface (`bl_label`/`bl_description` + `text=`) ≈ **1161**, confirming the doc's ~1100+ estimate. Heaviest files: `UvTools/baker.py`, `FastOperators.py`, `VertexGroupTools/vertexGroupOperators.py`, `PhysicsTools/collision*.py`, `ShapekeyTools/operators.py`, and the `OmniNode/NodeTree/Function/*` node functions. Enum item labels still need the Phase 2 AST extractor for an exact count (regex undercounts inline tuple labels).

### Phase 1 — i18n foundation (no behavior change)  ✅ (2026-06-25)
- [x] Build `i18n/` package: `manager.py` (locale resolution + dict merge + `bpy.app.translations.register`), `__init__.py` API, `locales/` (`zh_HANS`/`en_US`/`ja_JP` empty stub dicts + `all_dicts()`).
- [x] Add `hoTools_language` `EnumProperty` to `AddonPreference`; selector drawn at the **top** of `draw()`. `update=` calls `i18n.reload()`.
- [x] Wire `i18n.register()` / `i18n.unregister()` into root `register()`/`unregister()` in [__init__.py](__init__.py) — registers **first** (before classes/feature modules), unregisters **last** (after `OmniNode.unregister()`), so `tr()` is live throughout.
- [x] Unit-smoke (`i18n/` logic, bpy stubbed): `tr("任意中文")` → key when no locale data; `AUTO` → `bpy.app.translations.locale`; explicit pref overrides AUTO; `zh_CN`→`zh_HANS` / unknown→base normalization; `ctxt` lookup; translated value + missing fallback. 10/10 pass.
- **Exit:** addon loads unchanged in Blender, language selector visible, everything still Chinese. ✅ (Chinese default holds — `tr()` returns the Chinese key until Phase 3 wraps call sites and Phase 2 fills the dicts.)

**Phase 1 notes for Phase 3:** `tr` accepts an optional `ctxt`; lookup tries `(ctxt, msgid)` then plain `msgid`. `tr_iface` is currently an alias of `tr`. `current_locale()` is cached; `reload()` clears the cache and tag-redraws all areas. The `bpy.app.translations` bridge (`_register_bpy_translations`) is wired but a no-op while dicts are empty (registers nothing) — it activates automatically once Phase 2 populates `en_US`/`ja_JP`.

### Phase 2 — Extraction tooling  ✅ (2026-06-25)
- [x] [i18n/tools/extract.py](i18n/tools/extract.py): **AST** scan (not regex) for `bl_label`/`bl_description` class attrs, `text=`/`name=`/`description=` call kwargs, `EnumProperty(items=[...])` labels (idx 1) + descriptions (idx 2), and `self.report({...}, "…")` messages. Filters to **Han-containing** strings only (the Chinese key model), so ASCII identifiers aren't pulled in. Keys stored **verbatim** (no whitespace normalization) to guarantee exact runtime `tr()` match; near-duplicates are *reported*, not merged. Merges into `en_US.py`/`ja_JP.py` as `key -> ""` stubs, **never clobbering** existing values; source-removed-but-translated keys retained as **orphans**. Tolerates stray BOMs; skips unparseable files with a warning. Standalone script — deliberately does **not** import the `i18n` package (no `bpy`), runs outside Blender.
- [x] Coverage report: per-locale `translated/total (%)`, orphan count, per-category hit breakdown, near-dup groups, skipped files. `--dry-run` (report only) and `--check` (CI: exit 1 if stale) modes.
- **Exit:** ✅ first run wrote 1204 stub keys to each locale; rerun is idempotent (`--check` → `最新`, exit 0). Merge/roundtrip/orphan/CJK logic unit-tested (10/10).

**Measured (2026-06-25):** **1515 hits → 1204 unique Chinese keys** — `bl_label/desc` 424, `text/name/desc` 763, `enum item` 87, `report()` 241. Both `en_US`/`ja_JP` at 0/1204 (0%) — translation values are hand-filled next. (Unique-key 1204 < the Phase 0 raw site count because the AST scan dedups, ignores ASCII-only strings, and only counts string-literal `report()` args.)

**Run:** `python i18n/tools/extract.py` (rerun after adding any new Chinese string). `i18n/tools/` is dev-only — add to the release-workflow excludes in Phase 5.

### Phase 3 — Static UI migration (panels & operators, per-module)  🚧 in progress
Order by user visibility / size. One module per PR; **run GitNexus `impact` before editing each module's registered symbols** (per repo rules) and `detect_changes` before commit.

**Progress:**
- [x] **1. `__init__.py`** (2026-06-25) — `OP_register_asset_library` (§4 pattern: `description()` classmethod + wrapped `report()`), `AddonPreference.draw()` call-site `text=i18n.tr(...)` on operator + props. 9 keys filled in `en_US`/`ja_JP`. Compiles; end-to-end `tr()` verified (en/ja/zh fallback + bridge). Language enum *item* labels left untranslated by design (each is its own language's endonym).
- [ ] 2. `PhysicsTools` · [ ] 3. `ShapekeyTools`/`VertexGroupTools`/`VertexColorTools` · [ ] 4. `BoneTools`/`UvTools`/`MeshTools` · [ ] 5. `FastOperators.py` · [ ] 6. `AnimationTools`/`Exporter`/`NameMapping`/`Checker`/`Rbf`/`exIcon`

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

### Phase 4 — OmniNode (dynamic) localization
OmniNode generates node labels/sockets from `@omni` functions (see [OmniNode/ARCHITECTURE.md](OmniNode/ARCHITECTURE.md)). Translation must happen at **node draw/registration time**, not in the compiled IR (IR is cached and language-independent — keep it that way).
- [ ] Localize `@omni` `label`/category and socket display names via `tr()` at the draw layer (`OmniNodeDraw.py` / node `draw_label`), keying off the function's Chinese name.
- [ ] Confirm `_COMPILED_TREE_CACHE` is **not** invalidated by language change (labels are display-only; compilation keys must stay locale-independent). Language switch must not silently force recompiles or touch the runtime cache.
- [ ] Localize `OmniNodeOperator.py` / panel strings (Phase 3 pattern).
- **Exit:** node editor labels/sockets localized; compile & runtime caches behave identically across languages.

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

| Risk | Mitigation |
|---|---|
| 1000+ edit sites → high regression surface | Per-module PRs; GitNexus `impact`/`detect_changes` gate each (repo rule); Chinese fallback means a missed wrap degrades gracefully, not breaks. |
| `bl_label` frozen at register time | Use `description()` classmethod + call-site `text=tr()` (§4). |
| OmniNode IR cache pollution by locale | Translate only at draw layer; never key compilation/runtime cache on locale (§4 / Phase 4). |
| Identical Chinese word, different translations | `ctxt` param on `tr()`. |
| Duplicate/near-duplicate source strings inflate dict | Extractor reports duplicates; normalize whitespace on key. |
| Translation drift as code changes | Idempotent extractor + coverage report in CI/PR checklist. |
| Release zip omits `i18n/` | Explicit check in Phase 5 against the workflow excludes. |

---

## 6. Out of scope (v1)

- Translating the C++ native backend (`_native/`) — it touches no UI strings.
- RTL languages / pluralization rules.
- Crowd-sourced/online translation pipeline (locale files are hand-edited Python dicts for now).
- Translating bundled asset names in `HoAssets/`.
