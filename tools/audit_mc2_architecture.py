"""Report MC2 Python/C++ ownership and dependency facts.

This is a read-only architecture audit. It intentionally uses Python's AST for
Python modules and only uses regular expressions for C++ include/binding facts.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import importlib.util
import json
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
MC2_ROOT = REPO_ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "mc2"
NATIVE_ROOT = REPO_ROOT / "_native" / "src"
NATIVE_FILES = (
    "hotools_native.cpp",
    "mc2_bindings.cpp",
    "mc2_context_v0.cpp",
    "mc2_context_readback.cpp",
    "mc2_fingerprint.cpp",
    "mc2_kernels.cpp",
    "mc2_static_build.cpp",
    "mc2_self_collision.cpp",
)
LEGACY_TERMS = (
    "HOTOOLS_ENABLE_LEGACY_MC2",
    "Function.physicsMC2MeshCloth",
    "Function.physicsMC2BoneCloth",
    "create_meshcloth_mc2_context",
    "solve_meshcloth_mc2",
    "solve_mc2_bonecloth_io",
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(MC2_ROOT)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return "mc2" + ("." + ".".join(parts) if parts else "")


def _production_python_files() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in MC2_ROOT.rglob("*.py")
            if "test" not in path.relative_to(MC2_ROOT).parts
            and "__pycache__" not in path.parts
        )
    )


def _call_name(call: ast.Call) -> str:
    value = call.func
    parts = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _resolve_import(module_name: str, path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        imported = node.module or ""
    else:
        package = module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]
        try:
            imported = importlib.util.resolve_name(
                "." * node.level + (node.module or ""),
                package,
            )
        except (ImportError, ValueError):
            return None
    return imported if imported == "mc2" or imported.startswith("mc2.") else None


def _function_facts(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    forwarded_call = None
    body = node.body
    if len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call):
        forwarded_call = _call_name(body[0].value)
    return {
        "name": node.name,
        "line": node.lineno,
        "forwarded_call": forwarded_call,
    }


def _strongly_connected_components(edges: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(name: str) -> None:
        nonlocal index
        indices[name] = index
        lowlinks[name] = index
        index += 1
        stack.append(name)
        on_stack.add(name)
        for dependency in sorted(edges.get(name, ())):
            if dependency not in edges:
                continue
            if dependency not in indices:
                visit(dependency)
                lowlinks[name] = min(lowlinks[name], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[name] = min(lowlinks[name], indices[dependency])
        if lowlinks[name] != indices[name]:
            return
        component = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == name:
                break
        if len(component) > 1:
            components.append(sorted(component))

    for name in sorted(edges):
        if name not in indices:
            visit(name)
    return sorted(components)


def _python_facts() -> dict:
    modules = {}
    edges: dict[str, set[str]] = defaultdict(set)
    private_imports = []
    forwarders = []
    for path in _production_python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        module_name = _module_name(path)
        imports = []
        functions = []
        classes = []
        reexport_count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = _resolve_import(module_name, path, node)
                if imported is not None:
                    imports.append(imported)
                    edges[module_name].add(imported)
                    for alias in node.names:
                        if alias.name.startswith("_") and alias.name != "__future__":
                            private_imports.append({
                                "module": module_name,
                                "line": node.lineno,
                                "dependency": imported,
                                "name": alias.name,
                            })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fact = _function_facts(node)
                functions.append(fact)
                if fact["forwarded_call"]:
                    forwarders.append({"module": module_name, **fact})
            elif isinstance(node, ast.ClassDef):
                classes.append({"name": node.name, "line": node.lineno})
            elif isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "_EXPORTS" for target in node.targets):
                    if isinstance(node.value, ast.Dict):
                        reexport_count = len(node.value.keys)
        edges.setdefault(module_name, set())
        docstring = ast.get_docstring(tree) or ""
        modules[module_name] = {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "lines": len(source.splitlines()),
            "doc": docstring.splitlines()[0] if docstring else "",
            "imports": sorted(set(imports)),
            "functions": functions,
            "classes": classes,
            "reexport_count": reexport_count,
        }
    return {
        "module_count": len(modules),
        "line_count": sum(module["lines"] for module in modules.values()),
        "modules": modules,
        "edges": {name: sorted(dependencies) for name, dependencies in sorted(edges.items())},
        "cycles": _strongly_connected_components(edges),
        "private_imports": sorted(private_imports, key=lambda item: (item["module"], item["line"])),
        "forwarders": sorted(forwarders, key=lambda item: (item["module"], item["line"])),
    }


def _cpp_facts() -> dict:
    files = {}
    include_pattern = re.compile(r'^#include\s+"([^"]+)"', re.MULTILINE)
    binding_pattern = re.compile(
        r'\b[A-Za-z_][A-Za-z0-9_]*\.def\s*\(\s*"([^"]+)"'
    )
    pyobject_pattern = re.compile(r'^PyObject\*\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', re.MULTILINE)
    for filename in NATIVE_FILES:
        path = NATIVE_ROOT / filename
        source = path.read_text(encoding="utf-8")
        files[filename] = {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "lines": len(source.splitlines()),
            "internal_includes": sorted(include_pattern.findall(source)),
            "python_bindings": binding_pattern.findall(source),
            "pyobject_entry_points": pyobject_pattern.findall(source),
        }
    return {
        "translation_unit_count": len(files),
        "line_count": sum(item["lines"] for item in files.values()),
        "files": files,
    }


def _legacy_hits() -> list[dict]:
    roots = (MC2_ROOT, NATIVE_ROOT, REPO_ROOT / "_native" / "CMakeLists.txt")
    hits = []
    for root in roots:
        paths = (root,) if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file() or "test" in path.parts or "__pycache__" in path.parts:
                continue
            if path.suffix not in {".py", ".cpp", ".hpp", ".txt"} and path.name != "CMakeLists.txt":
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            for term in LEGACY_TERMS:
                if term in source:
                    hits.append({"path": path.relative_to(REPO_ROOT).as_posix(), "term": term})
    return sorted(hits, key=lambda item: (item["path"], item["term"]))


def build_report() -> dict:
    return {
        "schema": "hotools_mc2_architecture_audit_v0",
        "python": _python_facts(),
        "cpp": _cpp_facts(),
        "legacy_hits": _legacy_hits(),
    }


def _print_summary(report: dict) -> None:
    python = report["python"]
    cpp = report["cpp"]
    print(f"Python production: {python['module_count']} modules, {python['line_count']} lines")
    print(f"Python dependency cycles: {len(python['cycles'])}")
    print(f"Python private imports: {len(python['private_imports'])}")
    print(f"Python one-call forwarders: {len(python['forwarders'])}")
    print(f"C++ MC2/module shell: {cpp['translation_unit_count']} units, {cpp['line_count']} lines")
    for name, facts in cpp["files"].items():
        print(
            f"  {name}: {facts['lines']} lines, "
            f"{len(facts['python_bindings'])} bindings, "
            f"{len(facts['pyobject_entry_points'])} PyObject entries"
        )
    print(f"Legacy production hits: {len(report['legacy_hits'])}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print the full JSON report")
    parser.add_argument("--check", action="store_true", help="fail on cycles or legacy production hits")
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_summary(report)
    if args.check and (report["python"]["cycles"] or report["legacy_hits"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
