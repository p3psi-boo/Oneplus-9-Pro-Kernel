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

    def test_ranet3_requires_stock_tun_policy_routing_and_built_in_nftables(self):
        for firmware in device("oneplus-9-pro")["firmware"].values():
            stock = ROOT / firmware["config"]
            with self.subTest(stock=stock.name), tempfile.TemporaryDirectory() as temp:
                cfg = pathlib.Path(temp) / ".config"
                cfg.write_bytes(stock.read_bytes())
                droidspaces.merge_config(cfg)
                droidspaces.verify_config(cfg, stock)
                original = cfg.read_text()
                for name in (*droidspaces.RANET3_BASE, "CONFIG_NF_TABLES",
                             "CONFIG_NF_TABLES_SET", "CONFIG_NF_TABLES_INET",
                             "CONFIG_NFT_CT", "CONFIG_NFT_COUNTER"):
                    cfg.write_text(original.replace(f"{name}=y", f"# {name} is not set"))
                    with self.assertRaisesRegex(ValueError, name):
                        droidspaces.verify_config(cfg, stock)

    def test_requires_builtin_ch347t_and_linked_probe(self):
        firmware = device("oneplus-9-pro")["firmware"]["coloros"]
        stock = ROOT / firmware["config"]
        with tempfile.TemporaryDirectory() as temp:
            out = pathlib.Path(temp)
            cfg = out / ".config"
            cfg.write_bytes(stock.read_bytes())
            droidspaces.merge_config(cfg)
            droidspaces.verify_config(cfg, stock)
            cfg.write_text(cfg.read_text().replace("CONFIG_USB_CH347T_MPHSI=y",
                                                  "CONFIG_USB_CH347T_MPHSI=m"))
            with self.assertRaisesRegex(ValueError, "CONFIG_USB_CH347T_MPHSI"):
                droidspaces.verify_config(cfg, stock)
            system_map = out / "System.map"
            system_map.write_text("ffffff8008010000 t ch34x_usb_probe.cfi\n")
            droidspaces.verify_ch347t_linked(out)
            system_map.write_text("ffffff8008010000 t unrelated_probe\n")
            with self.assertRaisesRegex(ValueError, "Built-in CH347T"):
                droidspaces.verify_ch347t_linked(out)

    def test_protocol_crc_fails_closed_before_the_full_build(self):
        with tempfile.TemporaryDirectory() as temp:
            output = pathlib.Path(temp)
            report = output / "net/oplus_modules/data_module/built-in.a.symversions"
            report.parent.mkdir(parents=True)
            report.write_text("__crc_register_netlink_request = 0x8ed24291;\n")
            droidspaces.verify_protocol_crc(output)
            for invalid in ("__crc_register_netlink_request = 0x862bd52e;\n", "", report.read_text() * 2):
                report.write_text(invalid)
                with self.assertRaisesRegex(ValueError, "CRC mismatch"):
                    droidspaces.verify_protocol_crc(output)

    def test_rejects_other_models_and_kernel_drift(self):
        with self.assertRaisesRegex(ValueError, "not been reviewed"):
            droidspaces.require_device(device("oneplus-9"))
        changed = device("oneplus-9-pro")
        changed["kernel"]["commit"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "not been reviewed"):
            droidspaces.require_device(changed)


if __name__ == "__main__":
    unittest.main()
