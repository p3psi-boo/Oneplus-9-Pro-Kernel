"""Dependency-free guardrails for the opt-in CI packaging integration."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TwrpWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / '.github/workflows/droidspaces.yml').read_text()

    def test_builds_only_the_default_branch_and_packages_by_dispatch(self):
        for value in ('type: boolean', 'default: false', '  push:\n    branches: [oneplus-9-pro]',
                      "if: github.ref == 'refs/heads/oneplus-9-pro'",
                      "github.event_name == 'workflow_dispatch' && inputs.package_twrp"):
            self.assertIn(value, self.text)
        self.assertNotIn('pull_request:', self.text)
        self.assertNotIn('pull_request_target:', self.text)
        self.assertNotIn('build-twrp', self.text)

    def test_only_coloros_can_package_even_when_opted_in(self):
        gate = next(line.strip() for line in self.text.splitlines()
                    if line.strip().startswith("PACKAGE_TWRP:"))
        self.assertIn("matrix.rom == 'coloros' &&", gate)
        self.assertEqual(self.text.count("if: env.PACKAGE_TWRP == 'true'"), 2)
        self.assertIn("name: twrp-experimental-oneplus-9-pro-coloros-", self.text)
        self.assertNotIn("twrp-experimental-oneplus-9-pro-oxygenos-", self.text)
        self.assertIn("rom: [coloros, oxygenos]", self.text)

    def test_read_only_no_publish_or_secrets(self):
        self.assertIn('contents: read', self.text)
        self.assertIn('persist-credentials: false', self.text)
        self.assertNotIn('secrets.', self.text)
        self.assertNotIn('contents: write', self.text)
        self.assertNotIn('gh release', self.text)
        self.assertNotIn('git push', self.text)

    def test_exact_stock_repack_package_order(self):
        text = self.text
        self.assertLess(text.index('scripts/build.py --device'), text.index('scripts/fetch_oneplus9pro_stock_boot.py --os'))
        self.assertLess(text.index('scripts/fetch_oneplus9pro_stock_boot.py --os'), text.index('"scripts/repack.py"'))
        self.assertLess(text.index('"scripts/repack.py"'), text.index('"scripts/package_twrp.py"'))
        for value in ('fw["stock_boot_sha256"]', 'lock["commit"]', '"--source-commit", commit',
                      'ref: ${{ github.sha }}', 'out/twrp-delivery/*.zip.sha256',
                      'if-no-files-found: error', 'rom: [coloros, oxygenos]'):
            self.assertIn(value, text)

    def test_embedded_python_is_syntactically_valid(self):
        lines=self.text.splitlines()
        for marker in ('PY', 'PYCODE'):
            start=next(i for i,line in enumerate(lines) if line.strip()=="python3 - <<'"+marker+"'")
            end=next(i for i in range(start+1,len(lines)) if lines[i].strip()==marker)
            code='\n'.join(line[10:] for line in lines[start+1:end])
            compile(code, '<workflow>', 'exec')

if __name__ == '__main__': unittest.main()
