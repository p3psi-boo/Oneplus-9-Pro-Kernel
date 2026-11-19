"""Structural guards for the narrow Nix UAPI host-compiler adaptation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class NixUapiTests(unittest.TestCase):
    def test_only_host_hdrtest_command_is_redirected(self):
        source = (ROOT / 'nix/kernel.nix').read_text()
        self.assertEqual(source.count("--replace-fail '$(CC) $(c_flags) -S -o /dev/null -x c /dev/null' "
                                      "'$(HOST_UAPI_CLANG) $(c_flags) -S -o /dev/null -x c /dev/null'"), 1)
        self.assertIn('substituteInPlace "$1/usr/include/Makefile"', source)
        self.assertIn('export HOST_UAPI_CLANG=${hostUapiClang}', source)
        self.assertNotRegex(source, r'CONFIG_UAPI_HEADER_TEST\s*=')
        self.assertNotIn('header-test- +=', source)
        self.assertIn('"CC=clang"', (ROOT / 'scripts/build.py').read_text())

    def test_no_global_include_or_target_flag_leakage(self):
        source = (ROOT / 'nix/kernel.nix').read_text()
        helper = source.split('hostUapiClang = writeShellScript ', 1)[1].split('prepareSources =', 1)[0]
        self.assertIn('exec clang -isystem ${lib.getDev glibc}/include "$@"', helper)
        for forbidden in ('HOSTCC', '--target', '-Wl,', '-flto', '-fsanitize', '|| true'):
            self.assertNotIn(forbidden, helper)
        self.assertNotRegex(source, r'export\s+(?:CFLAGS|CPPFLAGS|CPATH|C_INCLUDE_PATH)=')

if __name__ == '__main__': unittest.main()
