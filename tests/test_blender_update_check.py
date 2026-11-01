"""Blender regression checks for metadata-only HoTools update checks."""

import io
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import bpy


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class UpdateCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load only these modules so unrelated tools cannot prevent the checks.
        cls.updater = load_module("hotools_update_check_test", ROOT / "updater.py")
        cls.application = load_module(
            "hotools_update_restart_test", ROOT / "ProjectTools" / "application.py"
        )
        cls.updater.register()
        bpy.utils.register_class(cls.application.OP_RestartBlender)

    @classmethod
    def tearDownClass(cls):
        bpy.utils.unregister_class(cls.application.OP_RestartBlender)
        cls.updater.unregister()

    def setUp(self):
        self.prefs = SimpleNamespace(
            hoTools_update_status="尚未检查",
            hoTools_update_current="",
            hoTools_update_latest="",
        )
        prefs_patch = patch.object(self.updater, "_prefs", return_value=self.prefs)
        prefs_patch.start()
        self.addCleanup(prefs_patch.stop)
        self.metadata = {
            "version": "2026.10.01",
            "release_tag": "v2026.10.01",
            "repository": self.updater.DEFAULT_REPOSITORY,
            "channel": "stable",
        }

    def check_release(self, release, expected_status):
        response = io.BytesIO(json.dumps(release).encode("utf-8"))
        with (
            patch.object(self.updater, "read_version_info", return_value=self.metadata),
            patch.object(
                self.updater.urllib.request, "urlopen", return_value=response
            ) as request,
        ):
            self.assertEqual(bpy.ops.ho.check_for_update(), {"FINISHED"})
        request.assert_called_once()
        self.assertEqual(
            request.call_args.args[0].full_url,
            "https://api.github.com/repos/HollowAmeChan/HoTools/releases/latest",
        )
        self.assertEqual(request.call_args.kwargs, {"timeout": 15})
        self.assertEqual(
            self.prefs.hoTools_update_current, self.metadata["release_tag"]
        )
        self.assertEqual(self.prefs.hoTools_update_latest, release["tag_name"])
        self.assertIn(expected_status, self.prefs.hoTools_update_status)

    def test_new_release_does_not_require_a_matching_package(self):
        for assets in ([], [{"name": "unrelated.zip"}]):
            with self.subTest(assets=assets):
                self.check_release(
                    {"tag_name": "v2026.11.01", "assets": assets}, "手动安装"
                )

    def test_same_and_older_releases_do_not_prompt_an_update(self):
        for tag in ("v2026.10.01", "v2026.09.01"):
            with self.subTest(tag=tag):
                self.check_release({"tag_name": tag}, "已是最新版本")

    def test_development_build_skips_network_and_clears_remote_version(self):
        self.prefs.hoTools_update_latest = "previous-release"
        with (
            patch.object(
                self.updater,
                "read_version_info",
                return_value={"version": "dev", "release_tag": "dev"},
            ),
            patch.object(self.updater.urllib.request, "urlopen") as request,
        ):
            self.assertEqual(bpy.ops.ho.check_for_update(), {"FINISHED"})
        request.assert_not_called()
        self.assertEqual(self.prefs.hoTools_update_latest, "")
        self.assertIn("跳过", self.prefs.hoTools_update_status)

    def test_network_errors_remain_visible(self):
        with patch.object(
            self.updater,
            "check_for_update",
            side_effect=self.updater.urllib.error.URLError("network unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "检查更新失败"):
                bpy.ops.ho.check_for_update()
        self.assertIn("检查失败", self.prefs.hoTools_update_status)

    def test_missing_release_tag_is_reported_as_failure(self):
        with (
            patch.object(self.updater, "read_version_info", return_value=self.metadata),
            patch.object(self.updater, "_request_json", return_value={}),
        ):
            with self.assertRaisesRegex(RuntimeError, "GitHub release has no tag"):
                bpy.ops.ho.check_for_update()
        self.assertIn("检查失败", self.prefs.hoTools_update_status)

    def test_installation_entry_points_are_removed(self):
        with self.assertRaises((KeyError, RuntimeError)):
            bpy.ops.ho.install_update.get_rna_type()
        self.assertFalse((ROOT / "update_helper.py").exists())

    def test_ordinary_restart_still_launches_blender(self):
        with (
            patch.object(self.application, "_launch_detached") as launch,
            patch.object(bpy.app.timers, "register") as timer,
        ):
            self.assertEqual(
                bpy.ops.ho.restart_blender(confirm_restart=True), {"FINISHED"}
            )
        launch.assert_called_once_with([bpy.app.binary_path])
        timer.assert_called_once()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
