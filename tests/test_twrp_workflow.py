"""Guardrails for the native workflow and its opt-in Nix packaging path."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TwrpWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / ".github/workflows/droidspaces.yml").read_text()
        cls.native, cls.nix = cls.text.split("\n  nix_coloros:\n")
        cls.packager = (ROOT / "scripts/package_ci_coloros.py").read_text()

    def test_builds_only_default_branch_and_packages_by_dispatch(self):
        for value in ("type: boolean", "default: false", "  push:\n    branches: [oneplus-9-pro]",
                      "if: github.ref == 'refs/heads/oneplus-9-pro'",
                      "github.event_name == 'workflow_dispatch' && inputs.package_twrp"):
            self.assertIn(value, self.native)
        for forbidden in ("pull_request:", "pull_request_target:", "build-twrp"):
            self.assertNotIn(forbidden, self.text)
        self.assertIn("ref: ${{ github.sha }}", self.native)
        self.assertIn("ref: ${{ github.sha }}", self.nix)

    def test_only_coloros_can_package_without_duplicate_native_package(self):
        gate = next(line.strip() for line in self.native.splitlines()
                    if line.strip().startswith("PACKAGE_TWRP:"))
        self.assertIn("matrix.rom == 'coloros' &&", gate)
        self.assertIn("!inputs.nix_coloros", gate)
        self.assertEqual(self.native.count("if: env.PACKAGE_TWRP == 'true'"), 2)
        self.assertIn("name: twrp-experimental-oneplus-9-pro-coloros-", self.native)
        self.assertIn("name: twrp-experimental-oneplus-9-pro-coloros-nix-", self.nix)
        self.assertNotIn("twrp-experimental-oneplus-9-pro-oxygenos-", self.text)
        self.assertIn("""inputs.nix_coloros && '["coloros"]' || '["coloros","oxygenos"]'""", self.native)
        self.assertEqual(self.text.count("scripts/fetch_oneplus9pro_stock_boot.py --os coloros"), 2)

    def test_read_only_no_publish_or_secrets(self):
        self.assertIn("contents: read", self.text)
        self.assertEqual(self.text.count("persist-credentials: false"), 2)
        for forbidden in ("secrets.", "contents: write", "gh release", "git push"):
            self.assertNotIn(forbidden, self.text)

    def test_exact_stock_repack_package_order(self):
        self.assertLess(self.native.index("scripts/build.py --device"),
                        self.native.index("scripts/fetch_oneplus9pro_stock_boot.py --os"))
        self.assertLess(self.native.index("scripts/fetch_oneplus9pro_stock_boot.py --os"),
                        self.native.index("python3 scripts/package_ci_coloros.py"))
        self.assertLess(self.packager.index('"scripts/repack.py"'),
                        self.packager.index('"scripts/package_twrp.py"'))
        for value in ('firmware["stock_boot_sha256"]', 'lock["commit"]', '"--source-commit", commit'):
            self.assertIn(value, self.packager)

    def test_nix_is_opt_in_and_must_pass_parity_before_packaging(self):
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.nix_coloros", self.nix)
        self.assertIn("needs: compile", self.nix)
        self.assertIn("name: droidspaces-experimental-oneplus-9-pro-coloros-", self.nix)
        self.assertIn("sandbox-fallback = false", self.nix)
        self.assertIn("--option sandbox true --option sandbox-fallback false", self.nix)
        self.assertIn("--no-update-lock-file", self.nix)
        self.assertLess(self.nix.index(".#coloros-kernel"), self.nix.index("scripts/verify_nix_coloros.py"))
        self.assertLess(self.nix.index("scripts/verify_nix_coloros.py"),
                        self.nix.index("scripts/package_ci_coloros.py"))
        self.assertEqual(self.nix.count("if: success() && inputs.package_twrp"), 2)
        self.assertNotIn("continue-on-error", self.nix)
        self.assertIn("--built out/nix-coloros", self.nix)

    def test_nix_external_sources_have_real_hashes(self):
        flake = json.loads((ROOT / "flake.lock").read_text())
        self.assertRegex(flake["nodes"]["nixpkgs"]["locked"]["rev"], r"^[0-9a-f]{40}$")
        sources = json.loads((ROOT / "nix/sources-lock.json").read_text())
        self.assertEqual(set(sources), {"kernel", "vendor", "resukisu", "clang"})
        for digest in sources.values():
            self.assertRegex(digest, r"^sha256-[A-Za-z0-9+/]{43}=$")
            self.assertNotEqual(digest, "sha256-" + ("A" * 43) + "=")

    def test_embedded_model_selector_is_valid_python(self):
        lines = self.text.splitlines()
        start = next(i for i, line in enumerate(lines) if line.strip() == "python3 - <<'PY'")
        end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "PY")
        compile("\n".join(line[10:] for line in lines[start + 1:end]), "<workflow>", "exec")


if __name__ == "__main__":
    unittest.main()
