"""Behavioral checks for the workflow's exact-commit kernel cache."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import coloros_cache
from project import sha256


class KernelCacheTests(unittest.TestCase):
    commit = "a" * 40

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.built = Path(temp.name)
        for name in coloros_cache.FILES:
            (self.built / name).write_text(name, encoding="utf-8")
        manifest = {
            "source_commit": self.commit,
            "os": "coloros",
            "device": "oneplus-9-pro",
            "source_mode": "offline-locked-trees",
            "compile_verified": True,
            "image_sha256": sha256(self.built / "Image"),
            "config_sha256": sha256(self.built / "kernel.config"),
        }
        (self.built / "build.json").write_text(json.dumps(manifest), encoding="utf-8")

    def cache(self, command, commit=None):
        coloros_cache.run(command, self.built, commit or self.commit)

    def test_same_commit_checked_and_different_commit_rejected(self):
        self.cache("record")
        self.cache("check")
        with self.assertRaisesRegex(ValueError, "this ColorOS Nix build"):
            self.cache("check", "b" * 40)

    def test_mutated_symbol_file_rejected(self):
        self.cache("record")
        (self.built / "System.map").write_text("different", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest or provenance mismatch"):
            self.cache("check")

    def test_foreign_file_even_boot_rejected(self):
        self.cache("record")
        (self.built / "boot.img").write_bytes(b"not cached")
        with self.assertRaisesRegex(ValueError, "file inventory"):
            self.cache("check")

    def test_symlink_never_accepted(self):
        self.cache("record")
        (self.built / "System.map").rename(self.built.parent / (self.built.name + ".map"))
        moved = self.built.parent / (self.built.name + ".map")
        self.addCleanup(moved.unlink)
        (self.built / "System.map").symlink_to(moved)
        with self.assertRaisesRegex(ValueError, "regular nonempty"):
            self.cache("check")


if __name__ == "__main__":
    unittest.main()
