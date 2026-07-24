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
    "mc2_fingerprint.cpp",
    "mc2_frame_orientations.cpp",
    "mc2_kernels.cpp",
    "mc2_static_build.cpp",
    "mc2_self_collision.cpp",
    "mc2_whole_domain_self.cpp",
    "mc2_domain_cpu.cpp",
    "mc2_domain_cpu_bindings.cpp",
)
LEGACY_TERMS = (
    "HOTOOLS_ENABLE_LEGACY_MC2",
    "Function.physicsMC2MeshCloth",
    "Function.physicsMC2BoneCloth",
    "create_meshcloth_mc2_context",
    "solve_meshcloth_mc2",
    "solve_mc2_bonecloth_io",
    "call_legacy",
    "old physicsMC2 packages remain active",
    "mc2_interaction_v0",
    "capture_requested_mc2_debug",
    "_mc2_bone_frame_state_v0",
    "mc2.hotspot_timing.v0",
    "no_python_fallback",
    "legacy_policy",
    "legacy E3 path",
)
PURE_NATIVE_FILES = (
    "mc2_kernels.cpp",
    "mc2_kernels.hpp",
    "mc2_self_collision.cpp",
    "mc2_static_build.cpp",
    "mc2_static_build.hpp",
    "mc2_domain_cpu.hpp",
    "mc2_domain_cpu.cpp",
)
PYTHON_NATIVE_TERMS = ("Python.h", "PyObject", "nanobind")
ALLOWED_FORWARDERS = {
    ("mc2.bending_static", "record_count"),
    ("mc2.bone_connection", "_triangle"),
    ("mc2.bone_connection", "_distance"),
    ("mc2.bone_connection", "_length_squared"),
    ("mc2.bone_static", "_tuple_vectors"),
    ("mc2.center_state", "fixed_count"),
    ("mc2.center_state", "_shift_position_f32"),
    ("mc2.center_state", "_matrix_tuple"),
    ("mc2.collider_frame", "collider_count"),
    ("mc2.debug_draw", "_triangle_mesh"),
    ("mc2.debug_draw", "_primitive_pair_visible"),
    ("mc2.distance_static", "record_count"),
    ("mc2.domain_ir", "_readonly_uint"),
    ("mc2.domain_ir", "_readonly_float"),
    ("mc2.domain_ir", "make_mc2_span_view"),
    ("mc2.domain_ir", "record_count"),
    ("mc2.domain_ir", "primitive_count"),
    ("mc2.domain_ir", "vertex_count"),
    ("mc2.domain_ir", "particle_count"),
    ("mc2.domain_ir", "partition_count"),
    ("mc2.domain_ir", "row_count"),
    ("mc2.domain_ir", "field_count"),
    ("mc2.cpu_backend", "create_mc2_cpu_backend_domain"),
    ("mc2.domain_owner", "_make_report_values"),
    ("mc2.domain_owner", "read_constraint_debug_state"),
    ("mc2.reference_step", "_partition_vector"),
    ("mc2.reference_step", "partition_float"),
    ("mc2.reference_step", "partition_uint_value"),
    ("mc2.frame_compile", "vertex_count"),
    ("mc2.setups.mesh_cloth.product", "_canonical_source_identity"),
    ("mc2.setups.mesh_cloth.product", "world_gravity_directions"),
    ("mc2.setups.mesh_cloth.product", "vertex_count"),
    ("mc2.setups.mesh_cloth.static_fragment", "_matrix_columns"),
    ("mc2.setups.mesh_cloth.fragment_cache", "hit_count"),
    ("mc2.setups.mesh_cloth.fragment_cache", "build_count"),
    ("mc2.setups.mesh_cloth.fragment_cache", "entry_count"),
    ("mc2.frame_state", "particle_count"),
    ("mc2.frame_state", "make_mc2_frame_input"),
    ("mc2.nodes", "_product_name_output"),
    ("mc2.nodes", "_task_parameter_presets"),
    ("mc2.nodes", "_make_task_parameters"),
    ("mc2.parameters", "_clamp"),
    ("mc2.parameters", "_non_negative"),
    ("mc2.parameters", "_canonical_json"),
    ("mc2.parameters", "_signature"),
    ("mc2.parameters", "signature"),
    ("mc2.parameters", "_default_curve"),
    ("mc2.parameters", "debug_dict"),
    ("mc2.partition_specs", "signature"),
    ("mc2.partition_specs", "make_mc2_partition_patch"),
    ("mc2.partition_specs", "active_partitions"),
    ("mc2.setups.bone_cloth.authoring", "task_sources"),
    ("mc2.setups.bone_cloth.product", "world_gravity_directions"),
    ("mc2.product_slot", "_is_product_collection"),
    ("mc2.runtime_parameters", "_multiply_float32"),
    ("mc2.scheduler", "_f32"),
    ("mc2.scheduler", "debug_dict"),
    ("mc2.self_collision_static", "primitive_count"),
    ("mc2.setups.mesh_cloth.final_proxy", "_tuple_vectors"),
    ("mc2.setups.bone_cloth.fragment_cache", "hit_count"),
    ("mc2.setups.bone_cloth.fragment_cache", "build_count"),
    ("mc2.setups.bone_cloth.static_fragment", "baseline"),
    ("mc2.setups.mesh_cloth.frame_input", "vertex_count"),
    ("mc2.static_data", "vertex_count"),
    ("mc2.timing", "_metric"),
    ("mc2.topology", "build_mc2_mesh_source_topology"),
    ("mc2.topology", "build_mc2_bone_source_topology"),
}

E7S_PYTHON_RESPONSIBILITY_MODULES = {
    "package_shell": frozenset((
        "mc2",
        "mc2.setups",
        "mc2.setups.bone_cloth",
        "mc2.setups.bone_spring",
        "mc2.setups.mesh_cloth",
    )),
    "identity_capability": frozenset((
        "mc2.capabilities",
        "mc2.declaration",
        "mc2.domain_capabilities",
        "mc2.names",
        "mc2.source_identity",
        "mc2.setups.contracts",
        "mc2.setups.mesh_cloth.capabilities",
        "mc2.setups.mesh_cloth.schema",
    )),
    "immutable_contract": frozenset((
        "mc2.domain_ir",
        "mc2.parameters",
        "mc2.partition_specs",
        "mc2.product_request",
        "mc2.results",
        "mc2.runtime_parameters",
        "mc2.static_data",
    )),
    "compile_stage": frozenset((
        "mc2.bending_static",
        "mc2.bone_connection",
        "mc2.bone_static",
        "mc2.collider_frame",
        "mc2.distance_static",
        "mc2.domain_collect",
        "mc2.domain_compile",
        "mc2.frame_compile",
        "mc2.mesh_baseline",
        "mc2.mesh_topology_identity",
        "mc2.self_collision_static",
        "mc2.topology",
        "mc2.setups.bone_cloth.static_build",
        "mc2.setups.bone_cloth.static_fragment",
        "mc2.setups.mesh_cloth.base_pose",
        "mc2.setups.mesh_cloth.final_proxy",
        "mc2.setups.mesh_cloth.static_fragment",
    )),
    "runtime_owner": frozenset((
        "mc2.center_state",
        "mc2.domain_owner",
        "mc2.frame_state",
        "mc2.product_slot",
        "mc2.setups.bone_cloth.fragment_cache",
        "mc2.setups.mesh_cloth.fragment_cache",
    )),
    "solver_execution": frozenset((
        "mc2.cpu_backend",
        "mc2.product_scheduler",
        "mc2.product_solver",
        "mc2.reference_step",
        "mc2.scheduler",
    )),
    "native_bridge": frozenset((
        "mc2.cpu_native_kernel",
        "mc2.native",
    )),
    "blender_product_boundary": frozenset((
        "mc2.anchor",
        "mc2.domain_output",
        "mc2.nodes",
        "mc2.presets",
        "mc2.source_observation_blender",
        "mc2.setups.bone_cloth.authoring",
        "mc2.setups.bone_cloth.product",
        "mc2.setups.bone_frame_input",
        "mc2.setups.mesh_cloth.authoring",
        "mc2.setups.mesh_cloth.delta_output",
        "mc2.setups.mesh_cloth.frame_input",
        "mc2.setups.mesh_cloth.product",
        "mc2.setups.mesh_cloth.properties",
        "mc2.setups.mesh_cloth.source_capture",
    )),
    "observation": frozenset((
        "mc2.debug",
        "mc2.debug_draw",
        "mc2.source_observation",
        "mc2.timing",
    )),
}
E7S_ALLOWED_ZERO_INBOUND_MODULES = {
    "mc2": "Physics World package manifest",
    "mc2.declaration": "SOLVER_MODULE declaration entry",
    "mc2.nodes": "SOLVER_MODULE node registry entry",
    "mc2.setups.mesh_cloth.properties": "COMPONENT_MODULE Blender properties entry",
}
E7S_EXTERNAL_ENTRY_MODULES = frozenset((
    "mc2",
    "mc2.capabilities",
    "mc2.debug",
    "mc2.declaration",
    "mc2.nodes",
    "mc2.setups.mesh_cloth.capabilities",
    "mc2.setups.mesh_cloth.properties",
    "mc2.source_observation_blender",
))

E7_LEGACY_MODULES = frozenset((
    "mc2.solver",
    "mc2.specs",
    "mc2.native_context",
    "mc2.interaction_scope",
))
E7_PRODUCT_RUNTIME_ROOTS = ("mc2.product_solver",)
E7_PUBLIC_NODE_ROOTS = ("mc2.nodes",)
E7_DEBUG_ROOTS = ("mc2.debug", "mc2.debug_draw")
E7_LEGACY_BINDING_PREFIXES = ("mc2_context_v0_", "mc2_interaction_v0_")
E7_LEGACY_BINDING_NAMES = frozenset((
    "mc2_build_bone_registration_rotations_v0",
    "mc2_optimize_triangle_direction_v0",
    "mc2_build_mesh_fallback_tangents_v0",
    "mc2_build_bone_rest_frames_v0",
    "mc2_build_bone_vertex_to_transform_rotations_v0",
    "mc2_build_bone_transform_baseline_derived_v0",
    "mc2_build_mesh_final_proxy_derived_v1",
    "mc2_build_mesh_baseline_derived_v0",
    "mc2_build_baseline_pose_depth_derived_v0",
    "mc2_build_distance_derived_v0",
    "mc2_build_bending_derived_v0",
    "mc2_build_self_collision_derived_v0",
    "mc2_build_center_static_derived_v0",
))
E7_LEGACY_TRANSLATION_UNITS = frozenset((
    "mc2_context_core.cpp",
    "mc2_context_frame_step.cpp",
    "mc2_context_interaction.cpp",
    "mc2_context_readback.cpp",
    "mc2_context_static.cpp",
))
E7_LEGACY_HEADERS = frozenset((
    "mc2_context_helpers.hpp",
    "mc2_context_internal.hpp",
))
E7S_PYTHON_MERGE_TARGETS = {
    "mc2.product_authoring": "mc2.setups.mesh_cloth.authoring",
    "mc2.product_collect": "mc2.setups.mesh_cloth.product",
    "mc2.product_frame": "mc2.setups.mesh_cloth.product",
    "mc2.product_bone_authoring": "mc2.setups.bone_cloth.authoring",
    "mc2.product_bone_collect": "mc2.setups.bone_cloth.product",
    "mc2.product_bone_frame": "mc2.setups.bone_cloth.product",
    "mc2.setups.mesh_cloth.static_build": "mc2.setups.mesh_cloth.static_fragment",
}
E7S_ALLOWED_VERSIONED_V0_IDENTITIES = frozenset((
    "mc2_center_static_v0",
    "mc2_bone_writeback_plan_v0",
))
E7S_MIGRATION_V0_PATTERN = re.compile(r"(?i)(?:\bv0\b|_v0\b)")
E7S_MIGRATION_WORD_PATTERN = re.compile(
    r"(?i)\b(?:legacy|fallback|shadow|compat|compatibility)\b"
)
ALLOWED_BINDING_OVERLOADS = frozenset((
    "mc2_domain_cpu_v1_configure_whole_domain_self",
))

FORBIDDEN_PRODUCT_FUNCTIONS = {
    ("mc2.interaction_scope", "explicit_partner_pairs"),
    ("mc2.nodes", "physicsMC2ParticleProfile"),
    ("mc2.nodes", "physicsMC2SolverSettings"),
}
FORBIDDEN_SOLVER_SETTING_FIELDS = {"substeps", "iterations"}
TASK_SOURCE_SOCKET_CONTRACTS = {
    "physicsMC2MeshClothTask": ("mesh_objects", "list[bpy.types.Object]"),
    "physicsMC2BoneClothTask": ("control_bones", "list[_OmniBone]"),
    "physicsMC2BoneSpringTask": ("root_bones", "list[_OmniBone]"),
}
PROFILE_NODE_PARAMETER_CONTRACTS = {
    "physicsMC2MeshClothProfile": {
        "required": {"gravity", "collision_mode", "self_collision_enabled"},
        "forbidden": {
            "spring_enabled", "spring_power", "collision_limit_distance",
            "wind_influence", "moving_wind",
        },
    },
    "physicsMC2BoneClothProfile": {
        "required": {"gravity", "collision_mode", "self_collision_enabled"},
        "forbidden": {
            "spring_enabled", "spring_power", "collision_limit_distance",
            "wind_influence", "moving_wind",
        },
    },
    "physicsMC2BoneSpringProfile": {
        "required": {"collision_limit_distance"},
        "forbidden": {
            "gravity", "collision_mode", "self_collision_enabled",
            "self_collision_interaction", "max_distance_enabled", "backstop_enabled",
            "spring_enabled", "spring_power", "spring_limit_distance",
            "spring_normal_limit_ratio", "spring_noise",
            "wind_influence", "moving_wind",
        },
    },
}
TASK_BITMASK_CONTRACTS = {
    "physicsMC2BoneClothTask": "collided_by_groups",
    "physicsMC2BoneSpringTask": "collided_by_groups",
}
FORBIDDEN_MESH_RNA_FIELDS = {
    "radius",
    "self_collision_enabled",
    "self_collision_surface_thickness",
    "mass",
}
FORBIDDEN_WORLD_SCOPE_FIELD = "include_" "mesh_collision"
WORLD_SCOPE_CONTRACT_FILES = (
    REPO_ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "nodes.py",
    REPO_ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "scope.py",
    REPO_ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "types.py",
)
E0_DOMAIN_MODULE_IMPORTS = {
    "mc2.domain_ir": frozenset((
        "__future__",
        "dataclasses",
        "hashlib",
        "json",
        "numpy",
    )),
    "mc2.domain_capabilities": frozenset((
        "__future__",
        "dataclasses",
        "mc2.domain_ir",
    )),
}


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


def _resolved_import_name(module_name: str, path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module or ""
    else:
        package = module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]
        try:
            return importlib.util.resolve_name(
                "." * node.level + (node.module or ""),
                package,
            )
        except (ImportError, ValueError):
            return None


def _resolve_import(module_name: str, path: Path, node: ast.ImportFrom) -> str | None:
    imported = _resolved_import_name(module_name, path, node)
    if imported is None:
        return None
    return imported if imported == "mc2" or imported.startswith("mc2.") else None


def _is_test_module(name: str) -> bool:
    return any(part in {"test", "tests"} for part in name.split("."))


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


def _reachable_modules(edges: dict[str, set[str]], roots: tuple[str, ...]) -> set[str]:
    reachable = set()
    pending = list(roots)
    while pending:
        module = pending.pop()
        if module in reachable:
            continue
        reachable.add(module)
        pending.extend(edges.get(module, ()))
    return reachable


def _python_facts() -> dict:
    modules = {}
    edges: dict[str, set[str]] = defaultdict(set)
    top_level_edges: dict[str, set[str]] = defaultdict(set)
    private_imports = []
    forwarders = []
    test_imports = []
    raw_readback_calls = []
    persistent_array_fields = []
    product_boundary_violations = []
    migration_v0_violations = []
    migration_word_violations = []
    seen_profile_nodes = set()
    for path in _production_python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        module_name = _module_name(path)
        for line_number, line in enumerate(source.splitlines(), start=1):
            candidate = line
            for identity in E7S_ALLOWED_VERSIONED_V0_IDENTITIES:
                candidate = candidate.replace(identity, "")
            if E7S_MIGRATION_V0_PATTERN.search(candidate):
                migration_v0_violations.append({
                    "module": module_name,
                    "line": line_number,
                    "text": line.strip(),
                })
            if E7S_MIGRATION_WORD_PATTERN.search(line):
                migration_word_violations.append({
                    "module": module_name,
                    "line": line_number,
                    "text": line.strip(),
                })
        for statement in tree.body:
            if isinstance(statement, ast.ImportFrom):
                dependency = _resolve_import(module_name, path, statement)
                if dependency is not None:
                    top_level_edges[module_name].add(dependency)
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    if alias.name == "mc2" or alias.name.startswith("mc2."):
                        top_level_edges[module_name].add(alias.name)
        imports = []
        functions = []
        classes = []
        reexport_count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = _resolve_import(module_name, path, node)
                resolved = _resolved_import_name(module_name, path, node)
                if resolved is not None and _is_test_module(resolved):
                    test_imports.append({
                        "module": module_name,
                        "line": node.lineno,
                        "dependency": resolved,
                    })
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
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_test_module(alias.name):
                        test_imports.append({
                            "module": module_name,
                            "line": node.lineno,
                            "dependency": alias.name,
                        })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fact = _function_facts(node)
                functions.append(fact)
                if (module_name, fact["name"]) in FORBIDDEN_PRODUCT_FUNCTIONS:
                    product_boundary_violations.append({
                        "module": module_name,
                        "line": node.lineno,
                        "name": fact["name"],
                    })
                if fact["forwarded_call"]:
                    forwarders.append({"module": module_name, **fact})
                socket_contract = TASK_SOURCE_SOCKET_CONTRACTS.get(fact["name"])
                if module_name == "mc2.nodes" and socket_contract is not None:
                    parameter_name, annotation = socket_contract
                    parameter = next(
                        (item for item in node.args.args if item.arg == parameter_name),
                        None,
                    )
                    actual = (
                        ast.unparse(parameter.annotation)
                        if parameter is not None and parameter.annotation is not None
                        else ""
                    )
                    if actual != annotation:
                        product_boundary_violations.append({
                            "module": module_name,
                            "line": node.lineno,
                            "name": f"{fact['name']}.{parameter_name}:{actual or 'missing'}",
                        })
                profile_contract = PROFILE_NODE_PARAMETER_CONTRACTS.get(fact["name"])
                if module_name == "mc2.nodes" and profile_contract is not None:
                    seen_profile_nodes.add(fact["name"])
                    parameter_names = {item.arg for item in node.args.args}
                    for name in sorted(profile_contract["required"] - parameter_names):
                        product_boundary_violations.append({
                            "module": module_name,
                            "line": node.lineno,
                            "name": f"{fact['name']}.missing:{name}",
                        })
                    for name in sorted(profile_contract["forbidden"] & parameter_names):
                        product_boundary_violations.append({
                            "module": module_name,
                            "line": node.lineno,
                            "name": f"{fact['name']}.forbidden:{name}",
                        })
                bitmask_parameter = TASK_BITMASK_CONTRACTS.get(fact["name"])
                if module_name == "mc2.nodes" and bitmask_parameter is not None:
                    parameter = next(
                        (item for item in node.args.args if item.arg == bitmask_parameter),
                        None,
                    )
                    actual = (
                        ast.unparse(parameter.annotation)
                        if parameter is not None and parameter.annotation is not None
                        else ""
                    )
                    if actual != "_OmniBitMask":
                        product_boundary_violations.append({
                            "module": module_name,
                            "line": node.lineno,
                            "name": f"{fact['name']}.{bitmask_parameter}:{actual or 'missing'}",
                        })
            elif isinstance(node, ast.ClassDef):
                classes.append({"name": node.name, "line": node.lineno})
                if node.name == "MC2SolverSettingsSpec":
                    for field in node.body:
                        if (
                            not isinstance(field, ast.AnnAssign)
                            or not isinstance(field.target, ast.Name)
                        ):
                            continue
                        if field.target.id in FORBIDDEN_SOLVER_SETTING_FIELDS:
                            product_boundary_violations.append({
                                "module": module_name,
                                "line": field.lineno,
                                "name": field.target.id,
                            })
                if node.name.endswith("State"):
                    for field in node.body:
                        if not isinstance(field, ast.AnnAssign) or not isinstance(field.target, ast.Name):
                            continue
                        annotation = ast.unparse(field.annotation)
                        if "ndarray" in annotation:
                            persistent_array_fields.append({
                                "module": module_name,
                                "class": node.name,
                                "field": field.target.id,
                                "line": field.lineno,
                            })
            elif isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "_EXPORTS" for target in node.targets):
                    if isinstance(node.value, ast.Dict):
                        reexport_count = len(node.value.keys)
            elif isinstance(node, ast.Call):
                call_name = _call_name(node)
                leaf = call_name.rpartition(".")[2]
                if leaf.startswith("mc2_context_v0_read") and module_name != "mc2.native_context":
                    raw_readback_calls.append({
                        "module": module_name,
                        "line": node.lineno,
                        "call": call_name,
                    })
        edges.setdefault(module_name, set())
        top_level_edges.setdefault(module_name, set())
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
        if module_name == "mc2.setups.mesh_cloth.schema":
            for node in tree.body:
                if not isinstance(node, ast.Assign) or not any(
                    isinstance(target, ast.Name) and target.id == "MESH_COLLISION_RNA_FIELDS"
                    for target in node.targets
                ):
                    continue
                for declaration in ast.literal_eval(node.value):
                    name = str(declaration.get("name") or "")
                    if name in FORBIDDEN_MESH_RNA_FIELDS:
                        product_boundary_violations.append({
                            "module": module_name,
                            "line": node.lineno,
                            "name": name,
                        })
    for name in sorted(set(PROFILE_NODE_PARAMETER_CONTRACTS) - seen_profile_nodes):
        product_boundary_violations.append({
            "module": "mc2.nodes",
            "line": 0,
            "name": f"missing_profile_node:{name}",
        })
    product_runtime_reachable = _reachable_modules(
        top_level_edges, E7_PRODUCT_RUNTIME_ROOTS
    )
    public_node_reachable = _reachable_modules(top_level_edges, E7_PUBLIC_NODE_ROOTS)
    debug_reachable = _reachable_modules(top_level_edges, E7_DEBUG_ROOTS)
    legacy_inbound_imports = [
        {"module": module, "dependency": dependency}
        for module, dependencies in sorted(edges.items())
        for dependency in sorted(dependencies)
        if dependency in E7_LEGACY_MODULES
    ]
    e7s_merge_sources = sorted(set(modules) & set(E7S_PYTHON_MERGE_TARGETS))
    e7s_projected_modules = (
        set(modules) - set(E7S_PYTHON_MERGE_TARGETS)
    ) | {
        target
        for source, target in E7S_PYTHON_MERGE_TARGETS.items()
        if source in modules
    }
    forwarder_keys = {
        (item["module"], item["name"])
        for item in forwarders
    }
    responsibility_by_module = {}
    duplicate_responsibilities = []
    for responsibility, module_names in E7S_PYTHON_RESPONSIBILITY_MODULES.items():
        for module_name in module_names:
            previous = responsibility_by_module.get(module_name)
            if previous is not None:
                duplicate_responsibilities.append({
                    "module": module_name,
                    "responsibilities": sorted((previous, responsibility)),
                })
            responsibility_by_module[module_name] = responsibility
    production_module_names = set(modules)
    classified_module_names = set(responsibility_by_module)
    inbound_counts = {module_name: 0 for module_name in production_module_names}
    for dependencies in edges.values():
        for dependency in dependencies:
            if dependency in inbound_counts:
                inbound_counts[dependency] += 1
    zero_inbound_modules = {
        module_name
        for module_name, count in inbound_counts.items()
        if count == 0
    }
    allowed_zero_inbound_modules = set(E7S_ALLOWED_ZERO_INBOUND_MODULES)
    externally_reachable_modules = _reachable_modules(
        edges, tuple(sorted(E7S_EXTERNAL_ENTRY_MODULES))
    )
    return {
        "module_count": len(modules),
        "line_count": sum(module["lines"] for module in modules.values()),
        "reexport_count": sum(module["reexport_count"] for module in modules.values()),
        "modules": modules,
        "edges": {name: sorted(dependencies) for name, dependencies in sorted(edges.items())},
        "top_level_edges": {
            name: sorted(dependencies)
            for name, dependencies in sorted(top_level_edges.items())
        },
        "cycles": _strongly_connected_components(edges),
        "private_imports": sorted(private_imports, key=lambda item: (item["module"], item["line"])),
        "forwarders": sorted(forwarders, key=lambda item: (item["module"], item["line"])),
        "unexpected_forwarders": sorted(
            (
                item
                for item in forwarders
                if (item["module"], item["name"]) not in ALLOWED_FORWARDERS
            ),
            key=lambda item: (item["module"], item["line"]),
        ),
        "stale_forwarder_allowances": [
            {"module": module, "name": name}
            for module, name in sorted(ALLOWED_FORWARDERS - forwarder_keys)
        ],
        "test_imports": sorted(test_imports, key=lambda item: (item["module"], item["line"])),
        "raw_readback_calls": sorted(
            raw_readback_calls,
            key=lambda item: (item["module"], item["line"]),
        ),
        "persistent_array_fields": sorted(
            persistent_array_fields,
            key=lambda item: (item["module"], item["line"]),
        ),
        "product_boundary_violations": sorted(
            product_boundary_violations,
            key=lambda item: (item["module"], item["line"], item["name"]),
        ),
        "e7s_migration_v0": {
            "allowed_versioned_identities": sorted(
                E7S_ALLOWED_VERSIONED_V0_IDENTITIES
            ),
            "violations": sorted(
                migration_v0_violations,
                key=lambda item: (item["module"], item["line"]),
            ),
        },
        "e7s_migration_words": sorted(
            migration_word_violations,
            key=lambda item: (item["module"], item["line"]),
        ),
        "e7s_python_layout": {
            "merge_targets": dict(sorted(E7S_PYTHON_MERGE_TARGETS.items())),
            "remaining_merge_sources": e7s_merge_sources,
            "remaining_merge_source_count": len(e7s_merge_sources),
            "projected_module_count": len(e7s_projected_modules),
        },
        "e7s_python_responsibilities": {
            "counts": {
                responsibility: len(module_names)
                for responsibility, module_names
                in sorted(E7S_PYTHON_RESPONSIBILITY_MODULES.items())
            },
            "missing_modules": sorted(
                production_module_names - classified_module_names
            ),
            "stale_modules": sorted(
                classified_module_names - production_module_names
            ),
            "duplicate_modules": sorted(
                duplicate_responsibilities,
                key=lambda item: item["module"],
            ),
        },
        "e7s_zero_inbound_modules": {
            "allowed": dict(sorted(E7S_ALLOWED_ZERO_INBOUND_MODULES.items())),
            "actual": sorted(zero_inbound_modules),
            "unexplained": sorted(
                zero_inbound_modules - allowed_zero_inbound_modules
            ),
            "stale_allowances": sorted(
                allowed_zero_inbound_modules - zero_inbound_modules
            ),
        },
        "e7s_external_reachability": {
            "roots": sorted(E7S_EXTERNAL_ENTRY_MODULES),
            "reachable_count": len(
                production_module_names & externally_reachable_modules
            ),
            "unreachable_modules": sorted(
                production_module_names - externally_reachable_modules
            ),
            "stale_roots": sorted(
                set(E7S_EXTERNAL_ENTRY_MODULES) - production_module_names
            ),
        },
        "e7_cpu": {
            "legacy_modules": sorted(E7_LEGACY_MODULES),
            "product_runtime_roots": list(E7_PRODUCT_RUNTIME_ROOTS),
            "product_runtime_reachable_legacy": sorted(
                product_runtime_reachable & E7_LEGACY_MODULES
            ),
            "public_node_roots": list(E7_PUBLIC_NODE_ROOTS),
            "public_node_reachable_legacy": sorted(
                public_node_reachable & E7_LEGACY_MODULES
            ),
            "legacy_inbound_imports": legacy_inbound_imports,
            "debug_roots": list(E7_DEBUG_ROOTS),
            "debug_reachable_legacy": sorted(
                debug_reachable & E7_LEGACY_MODULES
            ),
            "legacy_lazy_imports": sorted(
                (
                    item for item in legacy_inbound_imports
                    if item["dependency"]
                    not in top_level_edges.get(item["module"], set())
                ),
                key=lambda item: (item["module"], item["dependency"]),
            ),
        },
    }


def _e0_domain_boundary_hits() -> list[dict]:
    hits = []
    for module_name, allowed_imports in E0_DOMAIN_MODULE_IMPORTS.items():
        path = MC2_ROOT / f"{module_name.rpartition('.')[2]}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                resolved = _resolved_import_name(module_name, path, node)
                if resolved is not None:
                    names.append(resolved)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            for imported in names:
                if imported not in allowed_imports:
                    hits.append({
                        "module": module_name,
                        "line": node.lineno,
                        "kind": "unexpected_import",
                        "dependency": imported,
                    })

    allowed_consumers = {
        "mc2.domain_ir": frozenset((
            "mc2.domain_capabilities",
            "mc2.setups.mesh_cloth.source_capture",
            "mc2.setups.mesh_cloth.static_fragment",
            "mc2.domain_compile",
            "mc2.cpu_backend",
            "mc2.frame_compile",
            "mc2.cpu_native_kernel",
            "mc2.domain_output",
            "mc2.reference_step",
            "mc2.setups.mesh_cloth.authoring",
            "mc2.setups.mesh_cloth.product",
            "mc2.setups.bone_cloth.authoring",
            "mc2.setups.bone_cloth.product",
            "mc2.product_scheduler",
            "mc2.product_slot",
            "mc2.results",
            "mc2.setups.mesh_cloth.fragment_cache",
        )),
        "mc2.domain_capabilities": frozenset((
            "mc2.cpu_backend",
            "mc2.domain_owner",
        )),
    }
    for path in _production_python_files():
        module_name = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            dependencies = []
            if isinstance(node, ast.ImportFrom):
                dependency = _resolve_import(module_name, path, node)
                if dependency is not None:
                    dependencies.append(dependency)
            elif isinstance(node, ast.Import):
                dependencies.extend(alias.name for alias in node.names)
            for dependency in dependencies:
                if dependency not in allowed_consumers or module_name == dependency:
                    continue
                if module_name not in allowed_consumers[dependency]:
                    hits.append({
                        "module": module_name,
                        "line": node.lineno,
                        "kind": "premature_production_consumer",
                        "dependency": dependency,
                    })
    return sorted(
        hits,
        key=lambda item: (
            item["module"], item["line"], item["kind"], item["dependency"]
        ),
    )


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
    api_source = (NATIVE_ROOT / "mc2_api.hpp").read_text(encoding="utf-8")
    api_symbols = pyobject_pattern.findall(api_source)
    binding_symbols = [
        symbol
        for facts in files.values()
        for symbol in facts["python_bindings"]
    ]
    native_tree = ast.parse((MC2_ROOT / "native.py").read_text(encoding="utf-8"))
    required_symbols = []
    for node in native_tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "MC2_REQUIRED_NATIVE_SYMBOLS"
                for target in node.targets
            )
        ):
            required_symbols = list(ast.literal_eval(node.value))
            break
    definition_counts = defaultdict(list)
    for path in sorted(NATIVE_ROOT.glob("*.cpp")):
        source = path.read_text(encoding="utf-8")
        for symbol in pyobject_pattern.findall(source):
            if symbol in api_symbols:
                definition_counts[symbol].append(path.name)
    api_definition_violations = [
        {"symbol": symbol, "definitions": definition_counts[symbol]}
        for symbol in api_symbols
        if len(definition_counts[symbol]) != 1
    ]
    binding_contract_violations = {
        "duplicate_bindings": sorted({
            symbol for symbol in binding_symbols
            if binding_symbols.count(symbol) > 1
            and symbol not in ALLOWED_BINDING_OVERLOADS
        }),
        "duplicate_required": sorted({
            symbol for symbol in required_symbols if required_symbols.count(symbol) > 1
        }),
        "required_missing_bindings": sorted(set(required_symbols) - set(binding_symbols)),
        "api_missing_required": sorted(
            set(api_symbols) - set(required_symbols) - E7_LEGACY_BINDING_NAMES
        ),
    }
    pure_native_violations = []
    for filename in PURE_NATIVE_FILES:
        source = (NATIVE_ROOT / filename).read_text(encoding="utf-8")
        for term in PYTHON_NATIVE_TERMS:
            if term in source:
                pure_native_violations.append({"file": filename, "term": term})
    legacy_bindings = sorted(
        symbol for symbol in binding_symbols
        if symbol.startswith(E7_LEGACY_BINDING_PREFIXES)
        or symbol in E7_LEGACY_BINDING_NAMES
    )
    legacy_required = sorted(
        symbol for symbol in required_symbols
        if symbol.startswith(E7_LEGACY_BINDING_PREFIXES)
        or symbol in E7_LEGACY_BINDING_NAMES
    )
    return {
        "translation_unit_count": len(files),
        "line_count": sum(item["lines"] for item in files.values()),
        "files": files,
        "api_symbol_count": len(api_symbols),
        "binding_symbol_count": len(binding_symbols),
        "required_symbol_count": len(required_symbols),
        "api_definition_violations": api_definition_violations,
        "binding_contract_violations": binding_contract_violations,
        "pure_native_violations": pure_native_violations,
        "e7_cpu": {
            "legacy_bindings": legacy_bindings,
            "legacy_required_symbols": legacy_required,
            "legacy_translation_units": sorted(
                name
                for name in E7_LEGACY_TRANSLATION_UNITS
                if (NATIVE_ROOT / name).exists()
            ),
            "legacy_headers": sorted(
                name for name in E7_LEGACY_HEADERS
                if (NATIVE_ROOT / name).exists()
            ),
        },
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


def _world_scope_product_hits() -> list[dict]:
    hits = []
    for path in WORLD_SCOPE_CONTRACT_FILES:
        source = path.read_text(encoding="utf-8")
        if FORBIDDEN_WORLD_SCOPE_FIELD in source:
            hits.append({
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "term": FORBIDDEN_WORLD_SCOPE_FIELD,
            })
    return hits


def build_report() -> dict:
    return {
        "schema": "hotools_mc2_architecture_audit_v0",
        "python": _python_facts(),
        "cpp": _cpp_facts(),
        "legacy_hits": _legacy_hits(),
        "world_scope_product_hits": _world_scope_product_hits(),
        "e0_domain_boundary_hits": _e0_domain_boundary_hits(),
    }


def _print_summary(report: dict) -> None:
    python = report["python"]
    cpp = report["cpp"]
    print(f"Python production: {python['module_count']} modules, {python['line_count']} lines")
    print(f"Python dependency cycles: {len(python['cycles'])}")
    print(f"Python private imports: {len(python['private_imports'])}")
    print(f"Python lazy re-exports: {python['reexport_count']}")
    print(
        f"Python one-call forwarders: {len(python['forwarders'])} classified, "
        f"{len(python['unexpected_forwarders'])} unexpected, "
        f"{len(python['stale_forwarder_allowances'])} stale allowances"
    )
    print(f"Python production test imports: {len(python['test_imports'])}")
    print(f"Python raw readback boundary violations: {len(python['raw_readback_calls'])}")
    print(f"Python persistent ndarray state fields: {len(python['persistent_array_fields'])}")
    print(f"Python product boundary violations: {len(python['product_boundary_violations'])}")
    print(
        "E7-S migration V0 terms: "
        f"{len(python['e7s_migration_v0']['violations'])} violations, "
        f"{len(python['e7s_migration_v0']['allowed_versioned_identities'])} "
        "versioned identities"
    )
    print(
        "E7-S migration words: "
        f"{len(python['e7s_migration_words'])} violations"
    )
    print(
        "E7 product runtime reachable legacy modules: "
        f"{len(python['e7_cpu']['product_runtime_reachable_legacy'])}"
    )
    print(
        "E7 public node reachable legacy modules: "
        f"{len(python['e7_cpu']['public_node_reachable_legacy'])}"
    )
    print(
        "E7 debug reachable legacy modules: "
        f"{len(python['e7_cpu']['debug_reachable_legacy'])}"
    )
    print(
        "E7-S Python layout: "
        f"{python['e7s_python_layout']['remaining_merge_source_count']} merge sources, "
        f"{python['e7s_python_layout']['projected_module_count']} projected modules"
    )
    responsibility_report = python["e7s_python_responsibilities"]
    print(
        "E7-S Python responsibilities: "
        f"{sum(responsibility_report['counts'].values())} classified, "
        f"{len(responsibility_report['missing_modules'])} missing, "
        f"{len(responsibility_report['stale_modules'])} stale, "
        f"{len(responsibility_report['duplicate_modules'])} duplicate"
    )
    zero_inbound_report = python["e7s_zero_inbound_modules"]
    print(
        "E7-S Python zero-inbound roots: "
        f"{len(zero_inbound_report['actual'])} allowed, "
        f"{len(zero_inbound_report['unexplained'])} unexplained, "
        f"{len(zero_inbound_report['stale_allowances'])} stale allowances"
    )
    external_reachability = python["e7s_external_reachability"]
    print(
        "E7-S Python external reachability: "
        f"{external_reachability['reachable_count']} reachable, "
        f"{len(external_reachability['unreachable_modules'])} unreachable, "
        f"{len(external_reachability['stale_roots'])} stale roots"
    )
    print(f"C++ MC2/module shell: {cpp['translation_unit_count']} units, {cpp['line_count']} lines")
    for name, facts in cpp["files"].items():
        print(
            f"  {name}: {facts['lines']} lines, "
            f"{len(facts['python_bindings'])} bindings, "
            f"{len(facts['pyobject_entry_points'])} PyObject entries"
        )
    print(f"Legacy production hits: {len(report['legacy_hits'])}")
    print(f"Physics World scope product violations: {len(report['world_scope_product_hits'])}")
    print(f"E0 domain boundary violations: {len(report['e0_domain_boundary_hits'])}")
    print(
        f"C++ API definitions: {cpp['api_symbol_count']} symbols, "
        f"{len(cpp['api_definition_violations'])} ownership violations"
    )
    binding_violation_count = sum(
        len(items) for items in cpp["binding_contract_violations"].values()
    )
    print(
        f"MC2 binding contract: {cpp['binding_symbol_count']} registered, "
        f"{cpp['required_symbol_count']} production-required, "
        f"{binding_violation_count} violations"
    )
    print(f"C++ pure-native Python dependencies: {len(cpp['pure_native_violations'])}")
    print(
        f"E7 native legacy surface: {len(cpp['e7_cpu']['legacy_bindings'])} bindings, "
        f"{len(cpp['e7_cpu']['legacy_translation_units'])} translation units, "
        f"{len(cpp['e7_cpu']['legacy_headers'])} headers"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print the full JSON report")
    parser.add_argument("--check", action="store_true", help="fail on architecture boundary violations")
    parser.add_argument(
        "--e7-product-check",
        action="store_true",
        help="fail when the product runtime graph reaches a legacy MC2 owner",
    )
    parser.add_argument(
        "--e7-public-import-check",
        action="store_true",
        help="fail when importing public MC2 nodes reaches a legacy MC2 owner",
    )
    parser.add_argument(
        "--e7-debug-import-check",
        action="store_true",
        help="fail when MC2 debug modules import a legacy MC2 owner",
    )
    parser.add_argument(
        "--e7s-python-layout-check",
        action="store_true",
        help="fail while planned E7-S Python merge-source modules still exist",
    )
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_summary(report)
    if args.check:
        failures = (
            report["python"]["cycles"],
            report["python"]["private_imports"],
            report["python"]["reexport_count"],
            report["python"]["unexpected_forwarders"],
            report["python"]["stale_forwarder_allowances"],
            report["python"]["test_imports"],
            report["python"]["raw_readback_calls"],
            report["python"]["persistent_array_fields"],
            report["python"]["product_boundary_violations"],
            report["python"]["e7s_migration_v0"]["violations"],
            report["python"]["e7s_migration_words"],
            report["python"]["e7s_python_responsibilities"]["missing_modules"],
            report["python"]["e7s_python_responsibilities"]["stale_modules"],
            report["python"]["e7s_python_responsibilities"]["duplicate_modules"],
            report["python"]["e7s_zero_inbound_modules"]["unexplained"],
            report["python"]["e7s_zero_inbound_modules"]["stale_allowances"],
            report["python"]["e7s_external_reachability"]["unreachable_modules"],
            report["python"]["e7s_external_reachability"]["stale_roots"],
            report["cpp"]["api_definition_violations"],
            tuple(
                item
                for items in report["cpp"]["binding_contract_violations"].values()
                for item in items
            ),
            report["cpp"]["pure_native_violations"],
            report["cpp"]["e7_cpu"]["legacy_bindings"],
            report["cpp"]["e7_cpu"]["legacy_required_symbols"],
            report["cpp"]["e7_cpu"]["legacy_translation_units"],
            report["cpp"]["e7_cpu"]["legacy_headers"],
            report["legacy_hits"],
            report["world_scope_product_hits"],
            report["e0_domain_boundary_hits"],
        )
        if any(failures):
            raise SystemExit(1)
    if args.e7_product_check and report["python"]["e7_cpu"]["product_runtime_reachable_legacy"]:
        raise SystemExit(1)
    if (
        args.e7_public_import_check
        and report["python"]["e7_cpu"]["public_node_reachable_legacy"]
    ):
        raise SystemExit(1)
    if args.e7_debug_import_check and report["python"]["e7_cpu"]["debug_reachable_legacy"]:
        raise SystemExit(1)
    if (
        args.e7s_python_layout_check
        and report["python"]["e7s_python_layout"]["remaining_merge_sources"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
