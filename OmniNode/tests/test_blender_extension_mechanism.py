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


def test_switch_toggles_categories_and_lifecycle():
    """启用 → 禁用 → 再启用：分类与扩展生命周期同步切换。"""
    from HoTools.OmniNode.PhysicsWorld import blender as physics_blender

    register.set_disabled_extensions(())
    OmniNode.register()
    try:
        assert physics_blender.is_registered(), "启用态应注册物理 Blender 生命周期"
        assert register.find_extension_spec("PhysicsWorld") is not None
        assert any(
            category.identifier == "PHYSICS_WORLD"
            for category in register._registry.node_categories
        )

        register.set_disabled_extensions(("PhysicsWorld",))
        register.apply_extension_switch()
        assert not physics_blender.is_registered(), "禁用态不应注册物理生命周期"
        assert register.find_extension_spec("PhysicsWorld") is None
        assert not any(
            category.identifier == "PHYSICS_WORLD"
            for category in register._registry.node_categories
        ), "禁用后扩展分类应离开 Add 菜单"
        descriptor = register.find_extension_descriptor("PhysicsWorld")
        assert descriptor.status == "disabled" and descriptor.disabled_by_user
        assert descriptor.error == "", "禁用不是错误"

        register.set_disabled_extensions(())
        register.apply_extension_switch()
        assert physics_blender.is_registered(), "重新启用后生命周期应恢复"
        assert register.find_extension_spec("PhysicsWorld") is not None
        assert any(
            category.identifier == "PHYSICS_WORLD"
            for category in register._registry.node_categories
        ), "重新启用后扩展分类应回到 Add 菜单"
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


def test_unregister_is_idempotent():
    """重复反注册必须是安全的。

    扩展开关改成"延迟重建"后，一次切换可能先后经过定时器与插件卸载两条路径，
    因此 unregister() 会被调用第二次；重复反注册不得抛异常，也不得破坏状态。
    """
    register.set_disabled_extensions(())
    OmniNode.register()
    try:
        assert register.iter_registered_node_classes(), "应先处于已注册状态"
        OmniNode.unregister()
        assert register.iter_registered_node_classes() == ()
        OmniNode.unregister()  # 第二次：不应抛异常
        assert register.iter_registered_node_classes() == ()
        OmniNode.register()
        assert register.iter_registered_node_classes(), "重复反注册后仍应能重新注册"
    finally:
        register.set_disabled_extensions(())
        OmniNode.unregister()


def test_extension_switch_keeps_live_node_instances():
    """切换扩展不得反注册节点类：已有工程里的节点实例必须完好。

    这是踩过的崩溃点——撤掉 Node 类型注册后，工程里该类型的活实例悬空，之后
    任何访问（哪怕只是读 tree.nodes）都是 EXCEPTION_ACCESS_VIOLATION。
    因此开关只重建 Add 菜单分类，类型注册保持不动。
    """
    import bpy

    tree_module = importlib.import_module("HoTools.OmniNode.OmniNodeTree")
    assert hasattr(register, "apply_extension_switch"), "缺少扩展开关入口"

    register.set_disabled_extensions(())
    OmniNode.register()
    tree = None
    try:
        tree = bpy.data.node_groups.new("SwitchProbeTree", tree_module.OmniNodeTree.__name__)
        for idname in (
            "HO_OmniNode_physicsWorldBegin",
            "HO_OmniNode_physicsMC2Step",
        ):
            tree.nodes.new(idname)
        tree.doing_initNode = False
        before_classes = len(register.iter_registered_node_classes())
        before_nodes = [node.bl_idname for node in tree.nodes]
        assert before_nodes, "树里应有物理节点"

        register.set_disabled_extensions(("PhysicsWorld",))
        register.apply_extension_switch()
        assert (
            len(register.iter_registered_node_classes()) == before_classes
        ), "禁用扩展不得反注册节点类"
        assert [node.bl_idname for node in tree.nodes] == before_nodes, (
            "已有节点实例必须完好"
        )
        assert register.find_extension_spec("PhysicsWorld") is None, "扩展应处于禁用态"
        assert not any(
            category.identifier == "PHYSICS_WORLD"
            for category in register._registry.node_categories
        ), "扩展分类应从 Add 菜单移除"
        tree.update()  # 切完之后树仍要能正常回调

        register.set_disabled_extensions(())
        register.apply_extension_switch()
        assert [node.bl_idname for node in tree.nodes] == before_nodes
        assert register.find_extension_spec("PhysicsWorld") is not None, "重新启用应生效"
        assert any(
            category.identifier == "PHYSICS_WORLD"
            for category in register._registry.node_categories
        ), "扩展分类应回到 Add 菜单"
        assert (
            len(register.iter_registered_node_classes()) == before_classes
        ), "反复切换不得累积重复注册"
    finally:
        register.set_disabled_extensions(())
        if tree is not None:
            try:
                bpy.data.node_groups.remove(tree)
            except Exception:
                pass
        OmniNode.unregister()


def test_package_layout_nested_and_flat_both_resolve():
    """包目录定位必须按磁盘事实，而不是清单字面值。

    真实踩过：扩展仓库的 `extension.json` 里写着 `package: "PhysicsWorld"`，
    而扩展目录名也叫 `PhysicsWorld`，早先的实现把这种情况折叠成 "."，于是去找
    `<目录>/omninode_registration.py`——文件明明在
    `<目录>/PhysicsWorld/omninode_registration.py`，却被判"未找到注册模块"，
    实机表现为"红色不可用：未找到注册模块：PhysicsWorld/omninode_registration.py"。

    嵌套（仓库默认）与扁平（包内容直接铺开）两种形态都必须解析正确。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # 嵌套布局：extension.json 与 PhysicsWorld/ 同级，注册模块在包目录里
        nested = _write_extension(
            root, "PhysicsWorld",
            manifest={"identifier": "PhysicsWorld", "package": "PhysicsWorld"},
        )
        (nested / "PhysicsWorld").mkdir()
        (nested / "PhysicsWorld" / "omninode_registration.py").write_text(
            _SPEC_SOURCE.format(identifier="PhysicsWorld", order=1), encoding="utf-8"
        )
        package_name, package_dir, registration = register._resolve_extension_package(
            nested, {"identifier": "PhysicsWorld", "package": "PhysicsWorld"}
        )
        assert package_name == "PhysicsWorld", package_name
        assert package_dir == nested / "PhysicsWorld", package_dir
        assert registration.is_file(), registration

        # 扁平布局：注册模块与 extension.json 同目录
        flat = _write_extension(
            root, "FlatExt",
            manifest={"identifier": "FlatExt", "package": "FlatExt"},
            source=_SPEC_SOURCE.format(identifier="FlatExt", order=2),
        )
        package_name, package_dir, registration = register._resolve_extension_package(
            flat, {"identifier": "FlatExt", "package": "FlatExt"}
        )
        assert package_name == ".", package_name
        assert package_dir == flat, package_dir
        assert registration.is_file(), registration

        # 清单省略 package，但存在同名包目录（注册模块在包目录里）
        inferred = _write_extension(
            root, "Inferred", manifest={"identifier": "Inferred"}
        )
        (inferred / "Inferred").mkdir()
        (inferred / "Inferred" / "omninode_registration.py").write_text(
            _SPEC_SOURCE.format(identifier="Inferred", order=3), encoding="utf-8"
        )
        package_name, _package_dir, registration = register._resolve_extension_package(
            inferred, {"identifier": "Inferred"}
        )
        assert package_name == "Inferred", package_name
        assert registration.is_file(), registration

        # 三种布局都要能被完整发现（不是只解析路径）
        descriptors = register._discover_omninode_extensions(search_roots=(root,))
        by_id = {d.identifier: d for d in descriptors}
        for identifier in ("PhysicsWorld", "FlatExt", "Inferred"):
            assert identifier in by_id, sorted(by_id)
            assert by_id[identifier].available, (identifier, by_id[identifier].error)


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
