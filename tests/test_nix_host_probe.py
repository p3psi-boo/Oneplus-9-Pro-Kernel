"""Guard the Nix-only host link probe; actual compiler tests run separately."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class NixHostProbeTests(unittest.TestCase):
    def test_real_probe_is_redirected_without_config_forcing(self):
        source = (ROOT / 'nix/kernel.nix').read_text()
        replacement = ("--replace-fail '$(srctree)/scripts/cc-can-link.sh $(CC)' "
                       "'$(srctree)/scripts/cc-can-link.sh $(HOST_CLANG)'")
        self.assertEqual(source.count(replacement), 1)
        self.assertIn('substituteInPlace "$1/init/Kconfig"', source)
        self.assertIn('export HOST_CLANG=${hostClang}', source)
        self.assertNotRegex(source, r'CONFIG_(?:CC_CAN_LINK|UAPI_HEADER_TEST)\s*=\s*y')

    def test_host_wrapper_and_target_compiler_are_separate(self):
        source = (ROOT / 'nix/kernel.nix').read_text()
        helper = source.split('hostClang = writeShellScript ', 1)[1].split('prepareSources =', 1)[0]
        self.assertIn('exec clang', helper)
        self.assertIn('--gcc-toolchain=${stdenv.cc.cc}', helper)
        self.assertIn('-Wl,--dynamic-linker,${stdenv.cc.bintools.dynamicLinker}', helper)
        self.assertIn('"$@"', helper)
        self.assertNotRegex(helper, r'\b(?:true|exit\s+0)\b')
        self.assertIn('"CC=clang"', (ROOT / 'scripts/build.py').read_text())

    def test_provenance_is_null_without_clean_git_revision(self):
        source = (ROOT / 'nix/kernel.nix').read_text()
        self.assertIn('sourceCommitJSON = builtins.toJSON (project.rev or null);', source)
        self.assertIn('manifest["source_commit"] = revision', source)
        self.assertNotIn('project.dirtyRev', source)
        code = source.split("python3 - \"$out/build.json\" <<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        compile(code, '<nix-provenance>', 'exec')

    def test_provenance_writer_preserves_manifest_and_rejects_dirty_revision(self):
        source = (ROOT / 'nix/kernel.nix').read_text()
        code = source.split("python3 - \"$out/build.json\" <<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'build.json'
            for revision in (None, 'a' * 40, 'a' * 40 + '-dirty', 'not-a-commit'):
                with self.subTest(revision=revision):
                    original = {'image_sha256': 'b' * 64, 'compile_verified': True}
                    path.write_text(json.dumps(original))
                    result = subprocess.run([sys.executable, '-c', code, str(path)],
                        env=dict(os.environ, sourceCommitJSON=json.dumps(revision)),
                        capture_output=True, text=True)
                    if revision is None or revision == 'a' * 40:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(json.loads(path.read_text()), dict(original, source_commit=revision))
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(json.loads(path.read_text()), original)


if __name__ == '__main__': unittest.main()
