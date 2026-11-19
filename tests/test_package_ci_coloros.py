"""Exercise qualification to ZIP using small stand-ins for the boot image and repacker."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import droidspaces
import package_ci_coloros as pipeline
import package_twrp as packager
from project import device, save, sha256


class ColorOSPipelineTests(unittest.TestCase):
    commit = "1" * 40
    image = b"example qualified boot image"

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.built = self.root / "built"
        self.qualified = self.root / "qualified"
        self.stock = self.root / "boot.img"
        self.output = self.root / "delivery"
        self.built.mkdir()
        self.stock.write_bytes(b"stand-in stock boot")
        self.device = device("oneplus-9-pro")
        self.fw = self.device["firmware"]["coloros"]
        self.fw["stock_boot_size"] = len(self.image)
        self.enterContext(patch.object(pipeline, "device", return_value=self.device))
        self.enterContext(patch.object(packager, "device", return_value=self.device))
        stock = ROOT / self.fw["config"]
        config = self.built / "kernel.config"
        config.write_bytes(stock.read_bytes())
        droidspaces.merge_config(config)
        (self.built / "Image").write_bytes(b"example kernel")
        (self.built / "System.map").write_text("example stock symbol map")
        lock = json.loads((ROOT / "tools.lock.json").read_text())
        self.manifest = {key: self.device[key] for key in ("kernel", "vendor", "resukisu")}
        self.manifest.update({
            "device": "oneplus-9-pro", "os": "coloros", "firmware": self.fw["build_id"],
            "compile_verified": True, "droidspaces": droidspaces.profile(),
            "image_sha256": sha256(self.built / "Image"), "config_sha256": sha256(config),
            "kernel_release": self.fw["kernel_release"], "source_commit": self.commit,
            "source_mode": "offline-locked-trees", "offline_source_trees": lock["offline_source_trees"],
            "compiler_lock": lock["android_clang"],
        })
        save(self.built / "build.json", self.manifest)
        self.repack_calls = self.enterContext(patch.object(pipeline, "run", side_effect=self.repack))

    def repack(self, *argv):
        self.assertEqual(argv[1], ROOT / "scripts/repack.py")
        self.assertEqual(argv[argv.index("--stock") + 1], self.stock)
        self.assertEqual(argv[argv.index("--stock-sha256") + 1], self.fw["stock_boot_sha256"])
        output = argv[argv.index("--output") + 1]
        output.mkdir()
        boot = output / "boot.img"
        boot.write_bytes(self.image)
        result = copy.deepcopy(self.manifest)
        result.update({
            "abi_compatible": True, "partition_layout": "a/b", "boot_sha256": sha256(boot),
            "stock_boot_sha256": self.fw["stock_boot_sha256"],
            "module_signature_check": {"passed": True},
            "export_crc_check": {
                "passed": True, "missing": [], "mismatch": {}, "stock_exports": 13797,
                "matching": 13797, "image_sha256": self.manifest["image_sha256"],
                "system_map_sha256": sha256(self.built / "System.map"),
            },
        })
        save(output / "build.json", result)

    def qualify(self):
        pipeline.qualify(self.built, self.stock, self.qualified, self.commit)

    def package(self, source_commit=None):
        upstream = self.root / "anykernel-fixture"
        with patch.object(packager, "upstream_files",
                          return_value=({"tools/busybox": b"test upstream bytes"}, {"commit": packager.PIN})):
            return pipeline.package(self.built, self.qualified, self.output,
                                    source_commit or self.commit, "42", upstream)

    def test_qualification_is_reused_and_zip_binds_exact_identity(self):
        self.qualify()
        output = self.package()
        self.assertEqual(self.repack_calls.call_count, 1)
        with zipfile.ZipFile(output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read("boot.img"), self.image)
            self.assertEqual(archive.read("guard.sh"), (ROOT / "scripts/twrp/guard.sh").read_bytes())
            self.assertIn(self.fw["stock_boot_sha256"].encode(), archive.read("firmware.conf"))
            qualified = json.loads((self.qualified / "build.json").read_text())
            manifest = json.loads(archive.read("build.json"))
            self.assertEqual(manifest["qualification"], qualified)
            self.assertEqual(manifest["source_commit"], self.commit)
            self.assertEqual(manifest["ci_run"], "42")
            self.assertEqual(qualified["qualification_origin"]["build_manifest_sha256"],
                             sha256(self.built / "build.json"))
            checksums = dict(line.split("  ")[::-1]
                             for line in archive.read("SHA256SUMS").decode().splitlines())
            self.assertEqual(set(checksums), set(archive.namelist()) - {"SHA256SUMS"})
            for file, digest in checksums.items():
                self.assertEqual(hashlib.sha256(archive.read(file)).hexdigest(), digest)
        self.assertEqual(output.with_suffix(".zip.sha256").read_text(),
                         sha256(output) + "  " + output.name + "\n")

    def test_no_qualification_with_wrong_source_or_toolchain(self):
        with self.assertRaisesRegex(ValueError, "another source commit"):
            pipeline.qualify(self.built, self.stock, self.qualified, "2" * 40)
        save(self.built / "build.json", dict(self.manifest, compiler_lock={}))
        with self.assertRaisesRegex(ValueError, "locked Nix"):
            self.qualify()
        self.repack_calls.assert_not_called()
        self.assertFalse(self.qualified.exists())

    def test_qualification_fetches_only_when_stock_is_absent(self):
        self.stock.unlink()
        with patch.object(pipeline, "fetch",
                          side_effect=lambda firmware, path: path.write_bytes(b"fetched stand-in")) as fetch:
            self.qualify()
        fetch.assert_called_once_with(self.fw, self.stock)
        self.assertTrue(self.qualified.exists())

    def test_package_rejects_mutated_qualification(self):
        self.qualify()
        path = self.qualified / "build.json"
        manifest = json.loads(path.read_text())
        for field, match in (("qualification_origin", "matching locked build identity"),
                             ("export_crc_check", "13,797")):
            with self.subTest(field=field):
                changed = copy.deepcopy(manifest)
                if field == "qualification_origin":
                    del changed[field]
                else:
                    changed[field]["matching"] = 1
                save(path, changed)
                with self.assertRaisesRegex(ValueError, match):
                    self.package()
        save(path, manifest)
        (self.qualified / "boot.img").write_bytes(b"tampered boot")
        with self.assertRaisesRegex(ValueError, "Qualified boot changed"):
            self.package()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.repack_calls.call_count, 1)

    def test_package_rejects_changed_build_manifest(self):
        self.qualify()
        (self.built / "build.json").write_bytes((self.built / "build.json").read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "matching locked build identity"):
            self.package()

    def test_direct_packager_requires_coloros_export_count(self):
        self.qualify()
        path = self.qualified / "build.json"
        result = json.loads(path.read_text())
        del result["qualification_origin"]
        del result["export_crc_check"]["stock_exports"]
        save(path, result)
        with self.assertRaisesRegex(ValueError, "13,797"):
            packager.qualify(self.built, self.qualified, "coloros")


if __name__ == "__main__":
    unittest.main()
