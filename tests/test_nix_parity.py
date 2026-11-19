import json
import pathlib
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import check_nix_parity as parity
import droidspaces
from project import ROOT, device, sha256


class NixParityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        self.native, self.nix = self.root / "native", self.root / "nix"
        self.native.mkdir()
        self.nix.mkdir()
        self.stock, self.map = self.root / "stock", self.root / "stock.map"
        self.data = device(parity.DEVICE)
        self.firmware = self.data["firmware"][parity.ROM]
        self.release = parity.branded_release(self.firmware["kernel_release"])
        self.fixture(self.stock, self.map, self.release)
        self.pins = mock.patch.multiple(parity, STOCK_IMAGE_SHA256=sha256(self.stock),
                                        STOCK_MAP_SHA256=sha256(self.map), STOCK_EXPORT_COUNT=2)
        self.pins.start()
        self.addCleanup(self.pins.stop)
        for directory in (self.native, self.nix):
            config = directory / "kernel.config"
            # A small valid synthetic configuration avoids duplicating stock's
            # explicit not-set entries and includes the required base options.
            vals = droidspaces.values(droidspaces.CONFIG.read_text())
            baseline = droidspaces.values((ROOT / self.firmware["config"]).read_text())
            vals.update((key, "y") for key in droidspaces.RANET3_BASE)
            vals.update((key, baseline.get(key, "n")) for key in droidspaces.PROTECTIONS)
            vals["CONFIG_FONT_8x16"] = "y"
            config.write_text("\n".join(f"{k}={v}" for k, v in vals.items()) + "\n")
            self.fixture(directory / "Image", directory / "System.map", self.release)
            self.manifest(directory)

    @staticmethod
    def fixture(image, symbol_map, release, crc=0xABCDEF01, second="bar"):
        data = bytearray(512)
        for offset, name_offset, name in ((32, 100, "foo"), (44, 110, second)):
            struct.pack_into("<i", data, offset + 4, name_offset - offset - 4)
            data[name_offset:name_offset + len(name)] = name.encode()
        struct.pack_into("<II", data, 56, 0x12345678, crc)
        banner = f"Linux version {release} (tester@ci) (clang) #1 SMP\n".encode()
        data[160:160 + len(banner)] = banner
        image.write_bytes(data)
        symbol_map.write_text("0000 T _text\n0020 R __start___ksymtab\n"
                              f"0020 R __ksymtab_foo\n002c R __ksymtab_{second}\n"
                              "0038 R __stop___ksymtab\n0038 R __start___kcrctab\n")

    def manifest(self, directory):
        document = {k: self.data[k] for k in ("kernel", "vendor", "resukisu")}
        document.update(device=parity.DEVICE, os=parity.ROM, firmware=self.firmware["build_id"],
                        kernel_release=self.release, stock_kernel_release=self.firmware["kernel_release"],
                        kernel_release_suffix=parity.SUFFIX, droidspaces=parity.profile(),
                        compile_verified=True, stock_config_supplied=True,
                        image_sha256=sha256(directory / "Image"),
                        config_sha256=sha256(directory / "kernel.config"))
        for field, patch in (("patch_sha256", "op9.patch"),
                             ("vendor_patch_sha256", "vendor-oneplus-9.patch"),
                             ("compat_patch_sha256", "compat-sm8350.patch")):
            document[field] = sha256(ROOT / "patches" / patch)
        (directory / "build.json").write_text(json.dumps(document))

    def run_compare(self):
        return parity.compare(self.native, self.nix, self.stock, self.map)

    def test_binary_and_config_format_differences_do_not_fail(self):
        image = self.nix / "Image"
        image.write_bytes(image.read_bytes() + b"Different build bytes")
        config = self.nix / "kernel.config"
        config.write_text("# Different comments\n" + "\n".join(reversed(config.read_text().splitlines()))
                          .replace("CONFIG_MODULE_SIG=n", "# CONFIG_MODULE_SIG is not set") + "\n")
        self.manifest(self.nix)
        result = self.run_compare()
        self.assertTrue(result["passed"])
        self.assertNotEqual(result["native"]["image_sha256"], result["nix"]["image_sha256"])
        self.assertNotEqual(result["native"]["config_sha256"], result["nix"]["config_sha256"])
        self.assertEqual(result["native"]["settings_sha256"], result["nix"]["settings_sha256"])

    def test_non_profile_setting_change_fails(self):
        with (self.nix / "kernel.config").open("a") as stream:
            stream.write("CONFIG_TEST_EXTRA=y\n")
        self.manifest(self.nix)
        result = self.run_compare()
        self.assertFalse(result["passed"])
        self.assertEqual(result["config"]["differences"], {"CONFIG_TEST_EXTRA": {"native": None, "nix": "y"}})

    def test_each_build_must_match_stock(self):
        self.fixture(self.native / "Image", self.native / "System.map", self.release, second="baz")
        self.fixture(self.nix / "Image", self.nix / "System.map", self.release, crc=1)
        self.manifest(self.native)
        self.manifest(self.nix)
        result = self.run_compare()
        self.assertFalse(result["passed"])
        self.assertEqual(result["native"]["stock_abi"]["missing"], ["bar"])
        self.assertEqual(result["nix"]["stock_abi"]["mismatch"]["bar"]["built"], "0x00000001")

    def test_untrusted_stock_map_fails_before_export_comparison(self):
        self.map.write_text(self.map.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "Stock map"):
            self.run_compare()

    def test_embedded_release_must_match_manifest(self):
        self.fixture(self.nix / "Image", self.nix / "System.map", "other-release")
        self.manifest(self.nix)
        with self.assertRaisesRegex(ValueError, "embedded kernel release"):
            self.run_compare()

    def test_manifest_must_match_build_bytes(self):
        with (self.nix / "kernel.config").open("a") as stream:
            stream.write("# After build\n")
        with self.assertRaisesRegex(ValueError, "config_sha256"):
            self.run_compare()

    def test_duplicate_config_setting_is_rejected(self):
        with (self.nix / "kernel.config").open("a") as stream:
            stream.write("# CONFIG_FONT_8x16 is not set\n")
        self.manifest(self.nix)
        with self.assertRaisesRegex(ValueError, "Duplicate kernel config setting"):
            self.run_compare()

    def test_same_directory_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "separate artifact directories"):
            parity.compare(self.native, self.native, self.stock, self.map)
