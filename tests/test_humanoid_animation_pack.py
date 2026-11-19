"""Optional pack build/download/install/update/remove checks without Blender."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PACK = load_module("animation_pack_test", ROOT / "BoneTools/HumanoidDebug/animation_pack.py")
BUILD = load_module("animation_pack_build_test", ROOT / "tools/build_animation_zip.py")


class AnimationPackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "repo/BoneTools/HumanoidDebug/animations/VRM"
        self.source.mkdir(parents=True)
        self.alpha = self.source / "Alpha.anim"
        self.beta = self.source / "sub/Beta.anim"
        self.beta.parent.mkdir()
        self.alpha.write_bytes(b"AnimationClip:\n  m_Name: Alpha\n")
        self.beta.write_bytes(b"AnimationClip:\n  m_Name: Beta\n")
        self.archive = self.root / "HoTools-Humanoid-Animations-v1.zip"
        self.manifest = BUILD.build_animation_zip(self.root / "repo", self.archive, "v1")
        self.library = self.root / "addon/animations"
        self.target = self.library / PACK.PACK_DIRECTORY

    def rewrite_zip(self, *, transform_manifest=None, transform_entry=None):
        with zipfile.ZipFile(self.archive) as archive:
            entries = [(info, archive.read(info)) for info in archive.infolist()]
        with zipfile.ZipFile(self.archive, "w") as archive:
            for info, content in entries:
                if info.filename == PACK.MANIFEST_NAME and transform_manifest:
                    manifest = json.loads(content)
                    transform_manifest(manifest)
                    content = json.dumps(manifest).encode()
                if transform_entry:
                    info, content = transform_entry(info, content)
                archive.writestr(info, content)

    def test_install_and_remove_preserve_user_animations(self):
        self.library.mkdir(parents=True)
        custom = self.library / "User.anim"
        custom.write_bytes(b"user animation")
        PACK.install_archive(self.archive, self.library)
        extra = self.target / "Extra.anim"
        extra.write_bytes(b"additional user animation")
        self.assertEqual((self.target / "Alpha.anim").read_bytes(), self.alpha.read_bytes())
        self.assertEqual(PACK.installed_info(self.library), {
            "managed": True, "complete": True, "count": 2, "version": "v1",
        })
        (self.target / "sub/Beta.anim").write_bytes(b"edited official animation")

        result = PACK.uninstall(self.library)

        self.assertEqual(result, {"removed": 1, "preserved": 1})
        self.assertFalse((self.target / "Alpha.anim").exists())
        self.assertEqual(custom.read_bytes(), b"user animation")
        self.assertEqual(extra.read_bytes(), b"additional user animation")
        self.assertEqual((self.target / "sub/Beta.anim").read_bytes(), b"edited official animation")
        self.assertFalse((self.target / PACK.INSTALLED_MANIFEST).exists())

    def test_update_replaces_official_files_and_removes_obsolete_files(self):
        PACK.install_archive(self.archive, self.library)
        extra = self.target / "Extra.anim"
        extra.write_bytes(b"user animation")
        self.alpha.write_bytes(b"updated Alpha animation")
        self.beta.unlink()
        BUILD.build_animation_zip(self.root / "repo", self.archive, "v2")

        PACK.install_archive(self.archive, self.library)

        self.assertEqual((self.target / "Alpha.anim").read_bytes(), self.alpha.read_bytes())
        self.assertFalse((self.target / "sub/Beta.anim").exists())
        self.assertEqual(extra.read_bytes(), b"user animation")
        self.assertEqual(PACK.installed_info(self.library)["version"], "v2")

    def test_modified_official_file_is_protected_from_overwrite(self):
        PACK.install_archive(self.archive, self.library)
        destination = self.target / "Alpha.anim"
        destination.write_bytes(b"edited by user")
        with self.assertRaisesRegex(ValueError, "自定义动画"):
            PACK.install_archive(self.archive, self.library)
        self.assertEqual(destination.read_bytes(), b"edited by user")

    def test_hash_failure_leaves_previous_installation_intact(self):
        PACK.install_archive(self.archive, self.library)
        previous = (self.target / PACK.INSTALLED_MANIFEST).read_bytes()
        self.rewrite_zip(transform_entry=lambda info, content: (
            info, b"x" * len(content) if info.filename.endswith("Alpha.anim") else content
        ))
        with self.assertRaisesRegex(ValueError, "校验失败"):
            PACK.install_archive(self.archive, self.library)
        self.assertEqual((self.target / "Alpha.anim").read_bytes(), self.alpha.read_bytes())
        self.assertEqual((self.target / PACK.INSTALLED_MANIFEST).read_bytes(), previous)

    def test_failed_commit_rolls_back_every_file(self):
        PACK.install_archive(self.archive, self.library)
        old_alpha = (self.target / "Alpha.anim").read_bytes()
        old_beta = (self.target / "sub/Beta.anim").read_bytes()
        previous = (self.target / PACK.INSTALLED_MANIFEST).read_bytes()
        self.alpha.write_bytes(b"new Alpha")
        self.beta.write_bytes(b"new Beta")
        BUILD.build_animation_zip(self.root / "repo", self.archive, "v2")
        original_replace = Path.replace
        failed = False

        def fail_once(path, target):
            nonlocal failed
            if not failed and path.name == "Beta.anim" and "new" in path.parts:
                failed = True
                raise OSError("simulated disk failure")
            return original_replace(path, target)

        with patch.object(Path, "replace", fail_once):
            with self.assertRaisesRegex(OSError, "simulated"):
                PACK.install_archive(self.archive, self.library)
        self.assertTrue(failed)
        self.assertEqual((self.target / "Alpha.anim").read_bytes(), old_alpha)
        self.assertEqual((self.target / "sub/Beta.anim").read_bytes(), old_beta)
        self.assertEqual((self.target / PACK.INSTALLED_MANIFEST).read_bytes(), previous)
        self.assertFalse(list(self.library.parent.glob(".hotools-animations-*")))

    def test_cancelled_operation_leaves_existing_files(self):
        PACK.install_archive(self.archive, self.library)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(PACK.CancelledError):
            PACK.install_archive(self.archive, self.library, cancel=cancel)
        self.assertEqual((self.target / "Alpha.anim").read_bytes(), self.alpha.read_bytes())

    def test_reinstall_repairs_damaged_metadata_and_lfs_placeholders(self):
        self.target.mkdir(parents=True)
        (self.target / "Alpha.anim").write_bytes(
            b"version https://git-lfs.github.com/spec/v1\n"
        )
        self.assertEqual(PACK.installed_info(self.library)["count"], 0)
        PACK.install_archive(self.archive, self.library)
        (self.target / PACK.INSTALLED_MANIFEST).write_bytes(b"{damaged metadata")
        PACK.install_archive(self.archive, self.library)
        self.assertTrue(PACK.installed_info(self.library)["complete"])
        self.assertEqual((self.target / "Alpha.anim").read_bytes(), self.alpha.read_bytes())

    def test_manifest_rejects_unsafe_paths_duplicates_and_limits(self):
        for name in ("../escape.anim", "/escape.anim", "C:/escape.anim",
                     "sub\\escape.anim", "CON.anim", "sub/./Alpha.anim"):
            with self.subTest(name=name):
                manifest = json.loads(json.dumps(self.manifest))
                manifest["files"][0]["path"] = name
                with self.assertRaises(ValueError):
                    PACK.validate_manifest(manifest)
        manifest = json.loads(json.dumps(self.manifest))
        manifest["files"][1]["path"] = "alpha.anim"
        with self.assertRaises(ValueError):
            PACK.validate_manifest(manifest)
        manifest = json.loads(json.dumps(self.manifest))
        manifest["files"][0]["size"] = PACK.MAX_FILE_BYTES + 1
        with self.assertRaises(ValueError):
            PACK.validate_manifest(manifest)

    def test_archive_rejects_symlinks_and_unlisted_files(self):
        def symlink(info, content):
            if info.filename.endswith("Alpha.anim"):
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            return info, content

        self.rewrite_zip(transform_entry=symlink)
        with self.assertRaisesRegex(ValueError, "文件无效"):
            PACK.install_archive(self.archive, self.library)
        BUILD.build_animation_zip(self.root / "repo", self.archive, "v1")
        with zipfile.ZipFile(self.archive, "a") as archive:
            archive.writestr("../escape.anim", b"escape")
        with self.assertRaisesRegex(ValueError, "不一致"):
            PACK.install_archive(self.archive, self.library)
        self.assertFalse((self.root / "escape.anim").exists())

    def test_builder_requires_real_lfs_data_and_nonempty_library(self):
        self.alpha.write_bytes(b"version https://git-lfs.github.com/spec/v1\n")
        with self.assertRaisesRegex(ValueError, "git lfs pull"):
            BUILD.build_animation_zip(self.root / "repo", self.archive, "v1")
        self.alpha.unlink()
        self.beta.unlink()
        with self.assertRaises(ValueError):
            BUILD.build_animation_zip(self.root / "repo", self.archive, "v1")

    def test_release_asset_matches_installed_plugin_tag(self):
        name = self.archive.name
        release = {"assets": [
            {"name": "HoTools-v1-Blender-4.5-py311.zip"},
            {"name": name, "size": self.archive.stat().st_size,
             "browser_download_url": "https://github.com/HollowAmeChan/HoTools/releases/download/v1/" + name},
        ]}
        metadata = {"release_tag": "v1", "animation_pack_asset": name}
        with patch.object(PACK.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(release).encode())) as request:
            result = PACK.release_asset(metadata)
        self.assertEqual(result["name"], name)
        self.assertTrue(request.call_args.args[0].full_url.endswith("/releases/tags/v1"))
        release["assets"][1]["browser_download_url"] = "https://example.com/animations.zip"
        with patch.object(PACK.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(release).encode())):
            with self.assertRaisesRegex(ValueError, "下载地址"):
                PACK.release_asset(metadata)

    def test_download_verifies_size_digest_and_installs(self):
        payload = self.archive.read_bytes()
        asset = {"browser_download_url": "https://github.com/example.zip",
                 "size": len(payload),
                 "digest": "sha256:" + hashlib.sha256(payload).hexdigest()}
        with (
            patch.object(PACK, "release_asset", return_value=asset),
            patch.object(PACK.urllib.request, "urlopen", return_value=io.BytesIO(payload)),
        ):
            PACK.download_and_install(self.library, metadata={})
        self.assertTrue(PACK.installed_info(self.library)["complete"])
        with (
            patch.object(PACK, "release_asset", return_value=asset),
            patch.object(PACK.urllib.request, "urlopen", return_value=io.BytesIO(payload[:-10])),
        ):
            with self.assertRaisesRegex(ValueError, "不完整"):
                PACK.download_and_install(self.library, metadata={})
        self.assertEqual((self.target / "Alpha.anim").read_bytes(), self.alpha.read_bytes())


if __name__ == "__main__":
    unittest.main()
