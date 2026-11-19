import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import package_twrp as pkg


class RuntimeGuardTests(unittest.TestCase):
    def facts(self, **changes):
        values = dict(FACT_TWRP='3.7.1_12-0', FACT_DEVICE='lemonadep', FACT_SLOT='_a',
            FACT_SLOT_ALT='a', FACT_CMDLINE_SLOT='_a', FACT_FLASH_LOCKED='0', FACT_DEVICE_STATE='unlocked',
            EXPECTED_SIZE='201326592', FACT_SIZE='201326592', EXPECTED_STOCK_HASH='a'*64,
            FACT_STOCK_HASH='a'*64, EXPECTED_IMAGE_HASH='b'*64, FACT_IMAGE_HASH='b'*64)
        values.update(changes)
        return subprocess.run(['sh', '-c', '. "$1"; guard_facts', 'guard', str(ROOT/'scripts/twrp/guard.sh')], env=values).returncode

    def test_both_current_slots(self):
        self.assertEqual(self.facts(), 0)
        self.assertEqual(self.facts(FACT_SLOT='_b', FACT_SLOT_ALT='b', FACT_CMDLINE_SLOT='_b'), 0)

    def test_no_unknown_or_conflicting_slot(self):
        for changes in ({'FACT_SLOT':''}, {'FACT_SLOT':'a'}, {'FACT_SLOT':'_c'},
                        {'FACT_SLOT_ALT':'b'}, {'FACT_CMDLINE_SLOT':'_b'}):
            with self.subTest(changes=changes): self.assertNotEqual(self.facts(**changes), 0)

    def test_device_recovery_locked_unknown_and_conflicts(self):
        for changes in ({'FACT_DEVICE':'lemonade'}, {'FACT_DEVICE':'LE2120'}, {'FACT_TWRP':''},
                        {'FACT_FLASH_LOCKED':'1'}, {'FACT_DEVICE_STATE':'locked'},
                        {'FACT_FLASH_LOCKED':'', 'FACT_DEVICE_STATE':''}, {'FACT_FLASH_LOCKED':'unknown'}):
            with self.subTest(changes=changes): self.assertNotEqual(self.facts(**changes), 0)
        self.assertEqual(self.facts(FACT_FLASH_LOCKED=''), 0)
        self.assertEqual(self.facts(FACT_DEVICE_STATE=''), 0)

    def test_installed_recovery_root_wrong_variant_or_corruption_rejected(self):
        for changes in ({'FACT_STOCK_HASH':'c'*64}, {'FACT_IMAGE_HASH':'c'*64}, {'FACT_SIZE':'100663296'}):
            with self.subTest(changes=changes): self.assertNotEqual(self.facts(**changes), 0)
        fw=json.loads((ROOT/'devices/oneplus-9-pro.json').read_text())['firmware']
        self.assertNotEqual(fw['coloros']['stock_boot_sha256'],fw['oxygenos']['stock_boot_sha256'])
        self.assertNotEqual(self.facts(EXPECTED_STOCK_HASH=fw['coloros']['stock_boot_sha256'],
                                      FACT_STOCK_HASH=fw['oxygenos']['stock_boot_sha256']),0)

    def test_production_installer_has_one_explicit_bounded_write(self):
        script=(ROOT/'scripts/twrp/anykernel.sh').read_text()
        code='\n'.join(s for s in script.splitlines() if not s.lstrip().startswith('#'))
        self.assertEqual(sum(line.startswith('dd ') for line in code.splitlines()),1)
        self.assertIn('dd if="$AKHOME/boot.img" of="$TARGET" bs=1048576 conv=fsync || fail',code)
        for call in ('flash_boot;', 'write_boot;', 'flash_generic ', 'dump_boot;', 'split_boot;', 'mount ',
                     'blockdev --setrw','/dev/zero','bootctl ', '\nreboot', 'SLOT_SELECT=inactive', 'do_modules'):
            self.assertNotIn(call,code)
        self.assertLess(code.index('guard_facts || fail'),code.index('dd if='))
        self.assertLess(code.index('Boot changed during validation.'),code.index('dd if='))
        self.assertGreater(code.index('BOOT READBACK FAILED'),code.index('dd if='))
        self.assertNotIn('ak3-core.sh',code)
        self.assertNotIn('PATCHVBMETAFLAG=true',code)

    def test_shell_syntax(self):
        for path in (ROOT/'scripts/twrp').iterdir():
            subprocess.run(['sh','-n',str(path)],check=True)


class PackagerTests(unittest.TestCase):
    def test_fixed_pin_and_inventory(self):
        lock=json.loads((ROOT/'anykernel3.lock.json').read_text())
        self.assertEqual(lock['commit'],pkg.PIN)
        self.assertEqual(set(lock['files']),{'tools/busybox','tools/ak3-core.sh','LICENSE'})
        self.assertEqual(lock['repository'],'https://github.com/osm0sis/AnyKernel3.git')

    def test_wrong_upstream_head_rejected(self):
        with patch.object(pkg.subprocess,'check_output',return_value='0'*40+'\n'):
            with self.assertRaisesRegex(ValueError,'pinned upstream'):
                pkg.upstream_files(Path('/not-used'))

    def test_bad_inputs_rejected_before_reading_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for rom,commit,run in [('other','a'*40,'1'),('coloros','short','1'),('coloros','a'*40,'bad')]:
                with self.subTest(rom=rom,commit=commit,run=run):
                    with self.assertRaises(ValueError): pkg.package(p,p,rom,p,p,commit,run)

    def test_missing_qualification_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            with self.assertRaises(FileNotFoundError): pkg.qualify(p,p,'coloros')



class FullInstallerMockTests(unittest.TestCase):
    """Run production control flow in bash; substitute filesystem/commands only.

    No production testing switch exists. This does not execute ARM BusyBox.
    """
    def run_installer(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); (p/'tools').mkdir(); (p/'twres').mkdir()
            (p/'block/by-name').mkdir(parents=True)
            target=p/'block/actual'; target.write_bytes(b'stock')
            (p/'block/by-name/boot_a').symlink_to(target)
            (p/'boot.img').write_bytes(b'image')
            (p/'cmdline').write_text('androidboot.slot_suffix=_a')
            (p/'guard.sh').write_bytes((ROOT/'scripts/twrp/guard.sh').read_bytes())
            h=lambda b:hashlib.sha256(b).hexdigest()
            (p/'firmware.conf').write_text(f"ROM=coloros\nFIRMWARE=test\nEXPECTED_SIZE=5\nEXPECTED_STOCK_HASH={h(b'stock')}\nEXPECTED_IMAGE_HASH={h(b'image')}\n")
            bb=p/'tools/busybox'; bb.write_text('#!/bin/sh\nexit 0\n'); bb.chmod(0o755)
            script=(ROOT/'scripts/twrp/anykernel.sh').read_text()
            # Replace only host-inapplicable paths, block type test and PATH.
            script=script.replace('export PATH=', '# export PATH=')
            script=script.replace('/dev/block', str(p/'block')).replace('/twres',str(p/'twres')).replace('/postinstall/tmp',str(p/'postinstall')).replace('/proc/cmdline',str(p/'cmdline'))
            script=script.replace('[ -b "$resolved" ]','[ -f "$resolved" ]')
            mocks='''
getprop() {
 case "$1" in
 ro.twrp.version) echo 3.7.1;; ro.product.device) echo lemonadep;;
 ro.boot.flash.locked) if [ "$MODE" = locked ]; then echo 1; else echo 0; fi;;
 ro.boot.vbmeta.device_state) echo unlocked;; ro.boot.slot_suffix) echo _a;; ro.boot.slot) echo a;;
 init.svc.zygote) if [ "$MODE" = android ]; then echo running; fi;;
 esac
}
id() { echo 0; }
blockdev() { echo 5; }
sha256sum() { if [ "${1:-}" = -c ]; then return 0; fi; command sha256sum "$@"; }
dd() {
 echo write >> "$AKHOME/writes"
 if [ "$MODE" = writefail ]; then return 1; fi
 if [ "$MODE" != readbackfail ]; then cp "$AKHOME/boot.img" "$AKHOME/block/actual"; fi
}
sync() { :; }
'''
            script=script.replace('set -eu',mocks+'\nset -eu',1)
            (p/'run').write_text(script)
            if mode=='modified': target.write_bytes(b'other')
            if mode=='payload': (p/'boot.img').write_bytes(b'wrong')
            import os
            result=subprocess.run(['bash',str(p/'run')],env=dict(os.environ,AKHOME=str(p),OUTFD='1',MODE=mode),capture_output=True,text=True)
            writes=(p/'writes').read_text().splitlines() if (p/'writes').exists() else []
            return result,writes

    def test_complete_success_without_core_nounset_bug(self):
        result,writes=self.run_installer('ok')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(writes,['write'])
        self.assertIn('readback verified',result.stdout)

    def test_refusal_makes_no_writes(self):
        for mode in ('locked','android','modified','payload'):
            with self.subTest(mode=mode):
                result,writes=self.run_installer(mode)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(writes,[])

    def test_failed_write_and_readback_never_report_success(self):
        for mode in ('writefail','readbackfail'):
            with self.subTest(mode=mode):
                result,writes=self.run_installer(mode)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(writes,['write'])
                self.assertIn('Do not reboot',result.stdout)
                self.assertNotIn('readback verified',result.stdout)

if __name__=='__main__': unittest.main()
