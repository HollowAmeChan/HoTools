#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HoTools i18n 字符串提取器 / string extractor.

AST 扫描插件源码，收集所有*含中文*的可翻译字符串：
  - ``bl_label`` / ``bl_description`` 类属性
  - 调用关键字 ``text=`` / ``name=`` / ``description=``
  - ``EnumProperty(items=[...])`` 元组里的标签(下标1)与描述(下标2)
  - ``self.report({...}, "…")`` 的文案(第2个位置参数)

生成主键集，并**合并**写入 ``locales/en_US.py`` 与 ``locales/ja_JP.py`` 作为
``key -> ""`` 桩：已有译文一律保留、绝不覆盖；源码中已消失但仍有人工译文的键
作为 orphan 保留并在报告中标注。键即中文原文，逐字保存（不做归一化），以保证
与运行期 ``tr("中文原文")`` 精确匹配。重复运行幂等。

本脚本刻意*不*导入 i18n 包（其会引入 bpy），可在 Blender 之外直接运行。

用法（任意工作目录）:
    python i18n/tools/extract.py            # 写入桩 + 覆盖率报告
    python i18n/tools/extract.py --dry-run  # 只报告，不写文件
    python i18n/tools/extract.py --check    # CI: 若文件需更新则以 1 退出
"""

import argparse
import ast
import json
import os
import re
import sys

# i18n/tools/extract.py -> 插件根目录
ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
LOCALES_DIR = os.path.join(ADDON_ROOT, "i18n", "locales")
TARGET_LOCALES = ("en_US", "ja_JP")

# 不扫描的目录：第三方库、原生工程、构建产物、VCS/IDE、本 i18n 包自身、资产库。
EXCLUDE_DIRS = {
    "_Lib", "_native", "_build", "_dist", "build", "dist",
    ".git", ".github", "__pycache__", ".gitnexus", ".claude",
    ".vscode", ".idea", "i18n", "HoAssets",
}

KW_NAMES = {"text", "name", "description"}      # 可翻译的调用关键字
ATTR_NAMES = {"bl_label", "bl_description"}      # 可翻译的类属性

# 含 Han 表意文字即视为中文键（标点/全角符号单独出现不计）。
_HAN = re.compile(r"[㐀-鿿豈-﫿\U00020000-\U0002a6df]")

# 各语言文件头部（保留人类可读的语言标注）。
_HEADERS = {
    "en_US": ('English (US) translations: { "中文原文": "English text", ... }.',
              'English'),
    "ja_JP": ('日本語 translations: { "中文原文": "日本語", ... }.',
              '日本語'),
}


def has_cjk(s):
    return isinstance(s, str) and bool(_HAN.search(s))


def norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


# --- 源码扫描 ----------------------------------------------------------------

class _Collector(ast.NodeVisitor):
    def __init__(self):
        self.keys = set()       # 去重后的中文键
        self.hits = 0           # 命中总次数（含重复，用于报告）
        self.by_cat = {"bl_label/desc": 0, "text/name/desc": 0,
                       "enum item": 0, "report()": 0, "tr() call": 0}

    def _add(self, val, cat):
        if has_cjk(val):
            self.keys.add(val)
            self.hits += 1
            self.by_cat[cat] += 1

    def visit_Assign(self, node):
        v = node.value
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in ATTR_NAMES:
                    self._add(v.value, "bl_label/desc")
        self.generic_visit(node)

    def visit_Call(self, node):
        for kw in node.keywords:
            if kw.arg in KW_NAMES and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                self._add(kw.value.value, "text/name/desc")
            elif kw.arg == "items":
                self._enum_items(kw.value)
        fname = node.func.id if isinstance(node.func, ast.Name) else (
            node.func.attr if isinstance(node.func, ast.Attribute) else None)
        # self.report({...}, "msg")
        if fname == "report":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, str):
                self._add(node.args[1].value, "report()")
        # 已包裹的调用 tr("…") / tr_iface("…") / i18n.tr("…")，post-wrap 的权威键源。
        elif fname in ("tr", "tr_iface") and node.args:
            self._tr_call(node)
        self.generic_visit(node)

    def _tr_call(self, node):
        a0 = node.args[0]
        if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str) and has_cjk(a0.value)):
            return
        ctxt = None
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                and isinstance(node.args[1].value, str):
            ctxt = node.args[1].value
        for kw in node.keywords:
            if kw.arg == "ctxt" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                ctxt = kw.value.value
        self.keys.add((ctxt, a0.value) if ctxt else a0.value)
        self.hits += 1
        self.by_cat["tr() call"] += 1

    def _enum_items(self, val):
        if not isinstance(val, (ast.List, ast.Tuple)):
            return  # 动态 enum（callable）跳过
        for elt in val.elts:
            if isinstance(elt, (ast.Tuple, ast.List)):
                for idx in (1, 2):  # label, description
                    if idx < len(elt.elts):
                        e = elt.elts[idx]
                        if isinstance(e, ast.Constant) and isinstance(e.value, str):
                            self._add(e.value, "enum item")


def iter_py_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def scan(root):
    col = _Collector()
    skipped = []
    for path in iter_py_files(root):
        try:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            # 容忍源码里残留的 BOM(U+FEFF)，否则 ast.parse 会报非打印字符。
            tree = ast.parse(src.replace("﻿", ""), filename=path)
        except (SyntaxError, UnicodeDecodeError) as exc:
            skipped.append((os.path.relpath(path, root), exc))
            continue
        col.visit(tree)
    return col, skipped


# --- locale 读写 -------------------------------------------------------------

def read_existing(path):
    """从 locale 文件里取 ``translations`` 字典（AST literal_eval，不导入）。"""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "translations":
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return {}
    return {}


def _sort_key(k):
    # str 键与 (ctxt, msgid) 元组键分组排序，互不比较。
    return (1,) + tuple(k) if isinstance(k, tuple) else (0, k)


def _fmt_key(k):
    if isinstance(k, tuple):
        return "(" + ", ".join(json.dumps(x, ensure_ascii=False) for x in k) + ")"
    return json.dumps(k, ensure_ascii=False)


def merge(master, existing):
    """master 键取已有译文或空串；源码已无但仍有人工译文的键作为 orphan 保留。"""
    out = {k: existing.get(k, "") for k in master}
    orphans = []
    for k, v in existing.items():
        if k not in master and v:
            out[k] = v
            orphans.append(k)
    return out, orphans


def render(locale, mapping):
    summary, label = _HEADERS[locale]
    lines = [
        "# -*- coding: utf-8 -*-",
        '"""{}'.format(summary),
        "",
        "由 i18n/tools/extract.py 自动维护：键由提取器写入；译文请人工填写空串值，",
        "已有译文不会被覆盖。重跑：python i18n/tools/extract.py",
        '"""',
        "",
        "translations = {",
    ]
    for k in sorted(mapping, key=_sort_key):
        lines.append("    {}: {},".format(_fmt_key(k), json.dumps(mapping[k], ensure_ascii=False)))
    lines.append("}")
    return "\n".join(lines) + "\n"


# --- 报告与主流程 ------------------------------------------------------------

def near_duplicates(keys):
    groups = {}
    for k in keys:
        groups.setdefault(norm_ws(k), []).append(k)
    return {n: ks for n, ks in groups.items() if len(ks) > 1}


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="HoTools i18n string extractor")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    ap.add_argument("--check", action="store_true",
                    help="CI: 若任一 locale 文件需更新则以 1 退出")
    ap.add_argument("--quiet", action="store_true", help="精简输出")
    args = ap.parse_args(argv)

    col, skipped = scan(ADDON_ROOT)
    master = col.keys
    total = len(master)

    print("HoTools i18n 提取报告 / extraction report")
    print("=" * 52)
    print("扫描根目录 : {}".format(ADDON_ROOT))
    print("命中文案   : {} 处 -> {} 个唯一中文键".format(col.hits, total))
    if not args.quiet:
        for cat, n in col.by_cat.items():
            print("    {:<16}: {}".format(cat, n))
    if skipped:
        print("跳过(解析失败): {} 个文件".format(len(skipped)))
        for rel, exc in skipped:
            print("    ! {} ({})".format(rel, type(exc).__name__))

    dups = near_duplicates(master)
    if dups:
        print("近似重复(仅空白差异) : {} 组".format(len(dups)))
        if not args.quiet:
            for norm, ks in list(dups.items())[:10]:
                print("    ~ {!r} <- {} 个变体".format(norm, len(ks)))

    changed = False
    for locale in TARGET_LOCALES:
        path = os.path.join(LOCALES_DIR, locale + ".py")
        existing = read_existing(path)
        mapping, orphans = merge(master, existing)
        translated = sum(1 for k in master if existing.get(k))
        pct = (translated / total * 100.0) if total else 100.0
        content = render(locale, mapping)
        on_disk = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        needs_update = content != on_disk

        print("-" * 52)
        print("{}: {}/{} 已翻译 ({:.1f}%)  orphan={}  {}".format(
            locale, translated, total, pct, len(orphans),
            "需更新" if needs_update else "最新"))

        if needs_update:
            changed = True
            if not (args.dry_run or args.check):
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(content)
                print("    -> 已写入 {}".format(os.path.relpath(path, ADDON_ROOT)))

    print("=" * 52)
    if args.check:
        print("CHECK:", "需要更新（请重跑提取器并提交）" if changed else "最新")
        return 1 if changed else 0
    if args.dry_run:
        print("DRY-RUN: 未写入任何文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
