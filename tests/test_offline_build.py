import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from build import adapt_gitless_ksu_version, build, checkout_local, offline_build_env, stage_gitless_source, verify_gitless_source
from toolchain import compiler_tree_sha256, configure, local_git, local_revision


class OfflineInputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.commit("first")
        self.commit("second")
        self.head = self.git("rev-parse", "HEAD")
        self.git("tag", "legacy-tag")
        self.git("checkout", "--detach", self.head)

    def git(self, *args):
        return local_git(self.source, *args)

    def commit(self, value):
        (self.source / "tracked").write_text(value)
        self.git("add", "tracked")
        self.git("commit", "-qm", value)

    def test_stages_only_pinned_committed_tree_without_tags(self):
        (self.source / "tracked").write_text("dirty must not be staged")
        (self.source / "untracked").touch()
        dest = self.root / "stage"
        checkout_local(self.source, self.head, dest, full_history=True)
        self.assertEqual((dest / "tracked").read_text(), "second")
        self.assertFalse((dest / "untracked").exists())
        self.assertEqual(local_git(dest, "rev-list", "--count", "HEAD"), "2")
        self.assertEqual(local_git(dest, "tag"), "")

    def test_accepts_shallow_kernel_but_never_shallow_resukisu(self):
        shallow = self.root / "shallow"
        subprocess.run(["git", "clone", "--depth=1", self.source.as_uri(), shallow],
                       check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, "complete Git history"):
            checkout_local(shallow, self.head, self.root / "ksu", full_history=True)
        staged = self.root / "kernel"
        checkout_local(shallow, self.head, staged)
        self.assertEqual(local_revision(staged, self.head), staged)
        self.assertEqual(local_git(staged, "rev-parse", "--is-shallow-repository"), "true")

    def test_gitless_source_rejects_wrong_pin_and_changed_tree(self):
        path = self.root / "gitless"
        path.mkdir()
        sample = path / "tracked"
        sample.write_text("pinned")
        commit = "2" * 40
        lock = {"commit": commit, "tree_sha256": compiler_tree_sha256(path)}
        verify_gitless_source(path, commit, lock, "vendor")
        with self.assertRaisesRegex(ValueError, "No matching Gitless lock"):
            verify_gitless_source(path, "3" * 40, lock, "vendor")
        dest = self.root / "stage"
        sample.chmod(0o444)
        stage_gitless_source(path, dest)
        (dest / "tracked").write_text("editor can patch copy")
        self.assertEqual(sample.read_text(), "pinned")
        self.assertFalse((dest / ".git").exists())
        with self.assertRaisesRegex(ValueError, "locked digest"):
            verify_gitless_source(dest, commit, lock, "vendor")

    def test_gitless_resukisu_replaces_only_version_probes(self):
        kbuild = self.root / "staged-ksu/kernel/Kbuild"
        kbuild.parent.mkdir(parents=True)
        before = "GIT_BIN := git\n"
        after = "# call subst to process placeholders\n# Build options\n"
        kbuild.write_text(before + "LOCAL_GIT_EXISTS := original probes\n" + after)
        lock = {"commit": "39faf94a" + "0" * 32, "tree_sha256": compiler_tree_sha256(kbuild.parent.parent),
                "revision_count": 4537, "tag": "v4.1.0"}
        kbuild.write_text(kbuild.read_text() + "# changed trackable source\n")
        adapt_gitless_ksu_version(kbuild.parent.parent, lock)
        result = kbuild.read_text()
        self.assertTrue(result.startswith(before))
        self.assertIn(after, result)
        self.assertNotIn("LOCAL_GIT_EXISTS", result)
        self.assertIn("KSU_LOCAL_VERSION := 4537", result)
        self.assertIn("KSU_COMMIT_SHA := 39faf94a-dirty", result)
        self.assertIn("KSU_TAG_NAME := v4.1.0", result)

    def test_wrong_or_partial_inputs_fail_before_fetch(self):
        with self.assertRaisesRegex(ValueError, "commit mismatch"):
            checkout_local(self.source, "0" * 40, self.root / "stage")
        with self.assertRaisesRegex(ValueError, "require all four"):
            build("oneplus-9-pro", kernel_source=self.source)
        with self.assertRaisesRegex(ValueError, "locked offline inputs"):
            build("oneplus-9-pro", prepare_sources_command=self.root / "hook")

    def test_offline_environment_pins_build_timestamp_and_blocks_git_network(self):
        with mock.patch.dict(os.environ, {"GIT_ALLOW_PROTOCOL": "https", "GIT_DIR": "/tmp/no"}):
            env = offline_build_env(self.source, "946684800")
        self.assertEqual(env["KBUILD_BUILD_TIMESTAMP"], "Sat Jan 01 00:00:00 UTC 2000")
        self.assertEqual(env["SOURCE_DATE_EPOCH"], "946684800")
        self.assertEqual(env["GIT_ALLOW_PROTOCOL"], "file")
        self.assertNotIn("GIT_DIR", env)

    def test_plain_clang_requires_locked_content_symlinks_and_executable_modes(self):
        root = self.root / "plain"
        install = root / "clang"
        binary = install / "bin/clang"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\necho Pinned clang v11\n")
        binary.chmod(0o555)
        linker = binary.parent / "lld"
        linker.symlink_to("clang")
        digest = compiler_tree_sha256(install)

        lock_root = self.root / "lock-root"
        lock_root.mkdir()
        (lock_root / "tools.lock.json").write_text(json.dumps({"android_clang": {
            "commit": "0" * 40, "directory": "clang", "tree_sha256": digest,
            "version_string": "Pinned clang v11",
        }}))
        hook = self.root / "adapt-plain"
        hook.write_text('#!/bin/sh\nprintf "echo Adapted\\n" >> "$1/bin/clang"\n')
        hook.chmod(0o755)

        with mock.patch("toolchain.ROOT", lock_root), mock.patch.dict(os.environ):
            configure("sm8350", source=root, work_root=self.root / "work", prepare_command=hook)
            self.assertEqual(compiler_tree_sha256(install), digest)
            linker.unlink()
            linker.symlink_to("missing")
            with self.assertRaisesRegex(ValueError, "locked tree digest"):
                configure("sm8350", source=root)
            linker.unlink()
            linker.symlink_to("clang")
            binary.chmod(0o444)
            with self.assertRaisesRegex(ValueError, "locked tree digest"):
                configure("sm8350", source=root)
            binary.chmod(0o755)
            binary.write_text("different contents")
            with self.assertRaisesRegex(ValueError, "locked tree digest"):
                configure("sm8350", source=root)

    def test_clang_checks_local_commit_and_tracked_files(self):
        binary = self.source / "locked-clang/bin/clang"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\necho Pinned clang v11\n")
        binary.chmod(0o755)
        self.git("add", "locked-clang")
        self.git("commit", "-qm", "Test toolchain")
        lock = {"android_clang": {"commit": self.git("rev-parse", "HEAD"),
                                  "directory": "locked-clang",
                                  "version_string": "Pinned clang v11"}}
        toolchain_root = self.root / "toolchain-root"
        toolchain_root.mkdir()
        (toolchain_root / "tools.lock.json").write_text(json.dumps(lock))
        with mock.patch("toolchain.ROOT", toolchain_root), mock.patch.dict(os.environ):
            original = binary.read_bytes()
            self.assertEqual(configure("sm8350", source=self.source), lock["android_clang"])
            hook = self.root / "adapt"
            hook.write_text('#!/bin/sh\nprintf "echo Adapted\\n" >> "$1/bin/clang"\n')
            hook.chmod(0o755)
            configure("sm8350", source=self.source, work_root=self.root / "work", prepare_command=hook)
            staged = pathlib.Path(os.environ["PATH"].split(os.pathsep)[0]) / "clang"
            self.assertNotEqual(staged, binary)
            self.assertIn("Adapted", staged.read_text())
            self.assertEqual(binary.read_bytes(), original)
            with self.assertRaisesRegex(ValueError, "requires the locked"):
                configure("sm8350", prepare_command=hook)
            binary.write_text("modified")
            with self.assertRaises(subprocess.CalledProcessError):
                configure("sm8350", source=self.source)


if __name__ == "__main__":
    unittest.main()
