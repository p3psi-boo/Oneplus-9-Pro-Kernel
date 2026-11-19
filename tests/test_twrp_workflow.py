"""Guardrails for the ColorOS-only Nix production workflow."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TwrpWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = ROOT / ".github/workflows"
        cls.text = (cls.workflows / "droidspaces.yml").read_text()

    def test_default_branch_builds_coloros_only(self):
        for value in ("  push:\n    branches: [oneplus-9-pro]", "  coloros:",
                      "if: github.ref == 'refs/heads/oneplus-9-pro'", "ref: ${{ github.sha }}"):
            self.assertIn(value, self.text)
        for forbidden in ("pull_request:", "pull_request_target:", "build-twrp", "oxygenos",
                          "matrix:", "nix_coloros:", "python3 scripts/build.py",
                          "actions/download-artifact"):
            self.assertNotIn(forbidden, self.text)
        for legacy in ("build.yml", "boot.yml"):
            self.assertFalse((self.workflows / legacy).exists())

    def test_only_locked_nix_build_can_feed_the_packager(self):
        for value in ("sandbox-fallback = false", "--option sandbox true --option sandbox-fallback false",
                      "--no-update-lock-file", ".#coloros-kernel", '"source_mode"',
                      'm.get("source_mode") == "offline-git"', '"--built", "out/nix-coloros"'):
            self.assertIn(value, self.text)
        self.assertNotIn("continue-on-error", self.text)

    def test_only_manual_dispatch_produces_twrp_zip(self):
        for value in ("package_twrp:", "type: boolean", "default: false",
                      "name: twrp-experimental-oneplus-9-pro-coloros-nix-",
                      "out/twrp-delivery/*.zip.sha256", "if-no-files-found: error"):
            self.assertIn(value, self.text)
        gate = "if: success() && github.event_name == 'workflow_dispatch' && inputs.package_twrp"
        self.assertEqual(self.text.count(gate), 2)

    def test_read_only_no_publish_or_secrets(self):
        self.assertIn("contents: read", self.text)
        self.assertIn("persist-credentials: false", self.text)
        for forbidden in ("secrets.", "contents: write", "gh release", "git push"):
            self.assertNotIn(forbidden, self.text)

    def test_exact_stock_qualification_precedes_output(self):
        order = (".#coloros-kernel", "scripts/fetch_oneplus9pro_stock_boot.py --os coloros",
                 '"scripts/repack.py"', 'report.get("matching") != 13797',
                 "Upload qualified kernel files", '"scripts/package_twrp.py"',
                 "Upload the ColorOS TWRP ZIP and checksum")
        positions = [self.text.index(x) for x in order]
        self.assertEqual(positions, sorted(positions))
        for value in ('fw["stock_boot_sha256"]', 'lock["commit"]', '"--source-commit", head',
                      '"--qualified", "out/qualified-coloros"'):
            self.assertIn(value, self.text)
        self.assertNotIn("out/qualified-coloros/boot.img", self.text)

    def test_nix_external_sources_have_real_hashes(self):
        flake = json.loads((ROOT / "flake.lock").read_text())
        self.assertRegex(flake["nodes"]["nixpkgs"]["locked"]["rev"], r"^[0-9a-f]{40}$")
        sources = json.loads((ROOT / "nix/sources-lock.json").read_text())
        self.assertEqual(set(sources), {"kernel", "vendor", "resukisu", "clang"})
        for digest in sources.values():
            self.assertRegex(digest, r"^sha256-[A-Za-z0-9+/]{43}=$")
            self.assertNotEqual(digest, "sha256-" + ("A" * 43) + "=")

    def test_embedded_python_is_valid(self):
        lines = self.text.splitlines()
        starts = [i for i, line in enumerate(lines) if line.strip() == "python3 - <<'PY'"]
        self.assertEqual(len(starts), 2)
        for start in starts:
            end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "PY")
            compile("\n".join(line[10:] for line in lines[start + 1:end]), "<workflow>", "exec")


if __name__ == "__main__":
    unittest.main()
