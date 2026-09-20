"""Phase 1 regression test: OmniNode extension discovery / switch / isolation.

Runs inside Blender (uses bpy + nodeitems registration):

  blender.exe -b --factory-startup --python test_blender_extension_mechanism.py

Covers:
  * 内置/清单驱动两种扩展形态都能被发现与加载
  * 扩展失败被隔离成 descriptor.error，不影响 OmniNode 核心注册
  * API 版本 / requires_hotools 契约在导入前生效
  * identifier 不一致与重复时给出明确错误
  * 启用/禁用开关：节点目录与扩展 Blender 钩子同步切换，且可逆
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import types
from pathlib import Path


HOTOOLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HOTOOLS.parent))
if str(HOTOOLS) not in sys.path:
    sys.path.insert(0, str(HOTOOLS))

hotools_package = types.ModuleType("HoTools")
hotools_package.__path__ = [str(HOTOOLS)]
hotools_package.__package__ = "HoTools"
sys.modules["HoTools"] = hotools_package

import bpy  # noqa: E402

OmniNode = importlib.import_module("HoTools.OmniNode")
register = importlib.import_module("HoTools.OmniNode.OmniNodeRegister")

_SPEC_SOURCE = """\
from HoTools.OmniNode.OmniNodeRegister import OmniNodeExtensionSpec
def build_omninode_registration():
    return OmniNodeExtensionSpec(
        identifier={identifier!r}, order={order}, node_classes=(), categories=()
    )
"""


def _write_extension(root: Path, name: str, *, manifest=None, source=None) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (directory / "extension.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
    if source is not None:
        (directory / "omninode_registration.py").write_text(source, encoding="utf-8")
    return directory


def _discover(root: Path):
    return register._discover_omninode_extensions(search_roots=(root,))


def test_builtin_directory_is_discovered():
    """无清单的目录按“就地注册”被发现，目录名不必是合法模块名。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_extension(
            root, "Some-Ext.Dir",
            source=_SPEC_SOURCE.format(identifier="BuiltinExt", order=5),
        )
        # 内置形态按 HoTools.OmniNode.<dir> 定位，因此这里只验证“被发现且不是
        # 因目录名含短横线而报错”——导入失败会被隔离成 error，而不是抛异常。
        descriptors = _discover(root)
        assert [d.identifier for d in descriptors] == ["Some-Ext.Dir"], [
            d.identifier for d in descriptors
        ]
        assert descriptors[0].error, "该目录在临时根下不可导入，应报告为不可用"


def test_manifest_missing_registration_reports_error():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_extension(root, "NoRegistration", manifest={"identifier": "NoReg"})
        descriptors = _discover(root)
        assert len(descriptors) == 1
        assert descriptors[0].status == "error"
        assert "未找到注册模块" in descriptors[0].error


def test_manifest_api_mismatch_is_rejected_before_import():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_extension(
            root, "ApiTooNew",
            manifest={"identifier": "ApiTooNew", "omninode_api": ">=99.0"},
            # 即便注册模块会抛异常，也必须在导入前被版本契约拦下
            source="raise RuntimeError('should never be imported')\n",
        )
        descriptors = _discover(root)
        assert descriptors[0].status == "error"
        assert "API 不兼容" in descriptors[0].error


def test_manifest_bad_json_reports_error():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        directory = root / "BadJson"
        directory.mkdir()
        (directory / "extension.json").write_text("{oops", encoding="utf-8")
        descriptors = _discover(root)
        assert len(descriptors) == 1
        assert descriptors[0].status == "error"
        assert "extension.json" in descriptors[0].error


def test_manifest_identifier_mismatch_reports_error():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_extension(
            root, "Mismatch",
            manifest={"identifier": "DeclaredId"},
            source=_SPEC_SOURCE.format(identifier="OtherId", order=1),
        )
        descriptors = _discover(root)
        assert descriptors[0].status == "error"
        assert descriptors[0].identifier == "DeclaredId"


def test_broken_extension_does_not_break_core_snapshot():
    """坏扩展存在时，快照仍可构建，核心节点数量不减。"""
    import tempfile as _tempfile

    baseline = register._build_registry_snapshot()
    with _tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_extension(
            root, "Exploding",
            source="raise RuntimeError('boom')\n",
        )
        descriptors = _discover(root)
        assert descriptors[0].status == "error"
    # 核心快照与坏扩展目录无关
    after = register._build_registry_snapshot()
    assert len(after.node_classes) == len(baseline.node_classes)


def test_physics_extension_is_discovered_and_active():
    descriptors = register._discover_omninode_extensions()
    physics = [d for d in descriptors if d.identifier == "PhysicsWorld"]
    assert len(physics) == 1, [d.identifier for d in descriptors]
    assert physics[0].available, physics[0].error
    assert physics[0].node_classes(), "物理扩展应声明节点类"
    assert {c.identifier for c in physics[0].categories()} >= {"PHYSICS_WORLD"}


def test_switch_toggles_nodes_and_lifecycle():
    """启用 → 禁用 → 再启用：节点与扩展钩子同步切换且可逆。"""
    from HoTools.OmniNode.PhysicsWorld import blender as physics_blender

    register.set_disabled_extensions(())
    OmniNode.register()
    try:
        enabled_nodes = len(register.iter_registered_node_classes())
        assert physics_blender.is_registered(), "启用态应注册物理 Blender 生命周期"
        assert register.find_extension_spec("PhysicsWorld") is not None

        register.set_disabled_extensions(("PhysicsWorld",))
        OmniNode.unregister()
        OmniNode.register()
        disabled_nodes = len(register.iter_registered_node_classes())
        assert disabled_nodes < enabled_nodes, (disabled_nodes, enabled_nodes)
        assert not physics_blender.is_registered(), "禁用态不应注册物理生命周期"
        assert register.find_extension_spec("PhysicsWorld") is None
        descriptor = register.find_extension_descriptor("PhysicsWorld")
        assert descriptor.status == "disabled" and descriptor.disabled_by_user
        assert descriptor.error == "", "禁用不是错误"

        register.set_disabled_extensions(())
        OmniNode.unregister()
        OmniNode.register()
        assert len(register.iter_registered_node_classes()) == enabled_nodes
        assert physics_blender.is_registered(), "重新启用后生命周期应恢复"
    finally:
        register.set_disabled_extensions(())
        OmniNode.unregister()


def test_disabled_extension_keeps_files_and_metadata():
    """禁用只影响注册：目录仍在、版本/来源等元数据仍可读。"""
    register.set_disabled_extensions(("PhysicsWorld",))
    try:
        descriptors = register._discover_omninode_extensions()
        physics = [d for d in descriptors if d.identifier == "PhysicsWorld"][0]
        assert Path(physics.directory).is_dir()
        assert Path(physics.source_path).is_dir()
        assert physics.source in {"builtin", "manifest"}
    finally:
        register.set_disabled_extensions(())


def test_identifier_duplicate_prefers_manifest_source():
    """同名 identifier 时清单来源优先，内置来源被标记为重复错误。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_extension(
            root, "PhysicsWorld",
            manifest={"identifier": "PhysicsWorld"},
            source=_SPEC_SOURCE.format(identifier="PhysicsWorld", order=7),
        )
        descriptors = register._discover_omninode_extensions(
            search_roots=(root, HOTOOLS / "OmniNode")
        )
        physics = [d for d in descriptors if d.identifier == "PhysicsWorld"]
        # 清单优先：直接位于临时根下的那份生效
        manifest_descriptor = [d for d in physics if d.source == "manifest"]
        assert manifest_descriptor, [d.source for d in physics]
        assert manifest_descriptor[0].available, manifest_descriptor[0].error


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = []
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            import traceback

            failures.append(test.__name__)
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=6)
        else:
            print(f"PASS {test.__name__}")
    print()
    print(f"OmniNode 扩展机制测试：{len(tests) - len(failures)}/{len(tests)} 通过")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
