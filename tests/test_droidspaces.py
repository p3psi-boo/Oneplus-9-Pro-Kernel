import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import droidspaces
from project import ROOT, device, sha256


class DroidspacesProfileTests(unittest.TestCase):
    def test_overlay_replaces_duplicate_stock_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / ".config"
            path.write_text("# CONFIG_DEVTMPFS is not set\nCONFIG_DEVTMPFS=m\n"
                            "CONFIG_MODULE_FORCE_LOAD=y\nCONFIG_ENV_SENTINEL=42\n")
            droidspaces.merge_config(path)
            result = path.read_text()
            self.assertEqual(result.count("CONFIG_DEVTMPFS"), 1)
            self.assertEqual(result.count("CONFIG_MODULE_FORCE_LOAD"), 1)
            self.assertIn("CONFIG_DEVTMPFS=y\n", result)
            self.assertIn("# CONFIG_MODULE_FORCE_LOAD is not set\n", result)
            self.assertIn("CONFIG_ENV_SENTINEL=42\n", result)
            droidspaces.merge_config(path)
            self.assertEqual(path.read_text(), result)

    def test_checks_both_registered_stock_seeds(self):
        profile = device("oneplus-9-pro")
        droidspaces.require_device(profile)
        for rom, firmware in profile["firmware"].items():
            with self.subTest(rom=rom), tempfile.TemporaryDirectory() as temp:
                stock = ROOT / firmware["config"]
                self.assertEqual(sha256(stock), firmware["config_sha256"])
                cfg = pathlib.Path(temp) / ".config"
                cfg.write_bytes(stock.read_bytes())
                droidspaces.merge_config(cfg)
                droidspaces.verify_config(cfg, stock)
                original = cfg.read_text()
                for old, new in (("CONFIG_IPC_NS=y", "# CONFIG_IPC_NS is not set"),
                                 ("CONFIG_CFI_CLANG=y", "# CONFIG_CFI_CLANG is not set"),
                                 ("# CONFIG_MODULE_FORCE_LOAD is not set", "CONFIG_MODULE_FORCE_LOAD=y"),
                                 ("# CONFIG_CGROUP_PIDS is not set", "CONFIG_CGROUP_PIDS=y")):
                    cfg.write_text(original.replace(old, new))
                    with self.assertRaises(ValueError):
                        droidspaces.verify_config(cfg, stock)
                self.assertEqual(sha256(stock), firmware["config_sha256"])

    def test_rejects_other_models_and_kernel_drift(self):
        with self.assertRaisesRegex(ValueError, "not been reviewed"):
            droidspaces.require_device(device("oneplus-9"))
        changed = device("oneplus-9-pro")
        changed["kernel"]["commit"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "not been reviewed"):
            droidspaces.require_device(changed)


if __name__ == "__main__":
    unittest.main()
