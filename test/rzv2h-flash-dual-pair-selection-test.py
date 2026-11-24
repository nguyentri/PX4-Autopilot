#!/usr/bin/env python3
"""Check which CR8-0 + CR8-1 pair flash_dual.sh hands to the guarded loader.

The real flash.sh and flash_dual.sh run in an isolated tree with small ELF
stand-ins, a stub address allowlist and a stub pair loader that record their
arguments, so no probe is touched.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CR8_0 = 'renesas_rdk-rzv2h_'
CR8_1 = 'renesas_rdk-rzv2h-io-cr8_1_'
BUILT = [CR8_0 + c for c in ('default', 'demo', 'demosih', 'dualcr8')] + \
        [CR8_1 + c for c in ('default', 'demo')] + ['renesas_rdk-rzv2h-io-cm33_default']


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class FlashDualPairSelection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        for name in ('flash.sh', 'flash_dual.sh'):
            shutil.copy(ROOT / name, self.tmp / name)
        for target in BUILT:
            elf = self.tmp / 'build' / target / f'{target}.elf'
            elf.parent.mkdir(parents=True)
            elf.write_text(target + '\n')
        debug = self.tmp / 'platforms/nuttx/Debug'
        executable(debug / 'rtt-console-stop.sh', '#!/bin/sh\nexit 0\n')
        # The stub loaders log each ELF argument as the target it holds, or flag it
        # when it is not a private snapshot (the loader must never read build/).
        record = ('for a; do case "$a" in *.elf) case "$a" in "$TMPDIR"/*) a=$(cat "$a") ;;'
                  ' *) a="not-a-snapshot:$a" ;; esac ;; esac; out="$out${out:+ }$a"; done\n')
        executable(debug / 'rzv2h-ipc/rzv2h-ipc-demo-load-both-auto.sh',
                   '#!/bin/sh\nout=\n' + record + 'echo "$out" >>"$LOADER_LOG"\nexit "${LOADER_RC:-0}"\n')
        executable(debug / 'rzv2h-ipc/rzv2h-load-one-core.sh',
                   '#!/bin/sh\nout=one-core\n' + record + 'echo "$out" >>"$LOADER_LOG"\n')
        # Admits every image unless its file holds ALLOWLIST_DENY, and logs the
        # device and the content it checked.
        (debug / 'rzv2h-ipc-elf-allowlist.py').write_text(
            'import hashlib, os, sys\n'
            'a = sys.argv[1:]\n'
            'elf, device, digest = a[a.index("--elf") + 1], a[a.index("--device") + 1], a[a.index("--expect-sha256") + 1]\n'
            'data = open(elf, "rb").read()\n'
            'assert hashlib.sha256(data).hexdigest() == digest\n'
            'open(os.environ["LOADER_LOG"], "a").write("allowlist %s %s" % (device, data.decode()))\n'
            'if os.environ.get("ALLOWLIST_DENY") and os.environ["ALLOWLIST_DENY"] in data.decode():\n'
            '    print("2 0x44000000 0x1 0x1 - DENY"); print("RESULT=REJECTED"); sys.exit(1)\n'
            'print("RESULT=ADDRESS_CONTRACT_VERIFIED")\n')
        self.log = self.tmp / 'loader.log'

    def run_dual(self, *args, loader_rc=0, deny='', script='flash_dual.sh'):
        self.snapshots = self.tmp / 'snapshots'
        self.snapshots.mkdir(exist_ok=True)
        env = dict(os.environ, JLINK_SERIAL='0', LOADER_LOG=str(self.log), LOADER_RC=str(loader_rc),
                   ALLOWLIST_DENY=deny, TMPDIR=str(self.snapshots))
        return subprocess.run([str(self.tmp / script), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def loads(self):
        """Loader calls, with each ELF argument shown as the target it holds."""
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return [line for line in lines if not line.startswith('allowlist ')]

    def admissions(self):
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return [line for line in lines if line.startswith('allowlist ')]

    def pair(self, cr8_0, cr8_1, verbose=False):
        return [('--verbose ' if verbose else '') + f'{CR8_0}{cr8_0} {CR8_1}{cr8_1}']

    def test_cr8_0_target_alone_gets_its_default_partner(self):
        for name, partner in (('demosih', 'demo'), ('dualcr8', 'default')):
            for spelling in (name, f'rdk-rzv2h_{name}', f'{CR8_0}{name}', f'build/{CR8_0}{name}/'):
                with self.subTest(target=spelling):
                    self.log.unlink(missing_ok=True)
                    result = self.run_dual(spelling)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.loads(), self.pair(name, partner))

    def test_explicit_cr8_1_target_overrides_the_default(self):
        result = self.run_dual('-v', 'dualcr8', 'demo')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.loads(), self.pair('dualcr8', 'demo', verbose=True))

    def test_cr8_0_target_without_a_partner_is_refused(self):
        # demo is the single-core drone: it has no raw IPC link to pair with.
        for name in ('default', 'demo'):
            with self.subTest(target=name):
                result = self.run_dual(name)
                self.assertEqual(result.returncode, 2)
                self.assertIn('no default CR8-1 partner', result.stderr)
                self.assertEqual(self.loads(), [])

    def test_unbuilt_default_partner_is_refused(self):
        shutil.rmtree(self.tmp / 'build' / f'{CR8_1}default')
        result = self.run_dual('dualcr8')
        self.assertEqual(result.returncode, 2)
        self.assertIn(f'./build.sh {CR8_1}default', result.stderr)
        self.assertEqual(self.loads(), [])

    def test_wrong_core_in_either_position_is_refused(self):
        for args in (('rdk-rzv2h-io-cr8_1_demo',), ('rdk-rzv2h-io-cm33_default',),
                     ('demosih', 'rdk-rzv2h_demo'), ('demosih', 'rdk-rzv2h-io-cm33_default'),
                     ('nosuchtarget',), (), ('demo', 'demo', 'demo'), ('--bogus',)):
            with self.subTest(args=args):
                result = self.run_dual(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(self.loads(), [])

    def test_both_images_pass_the_address_allowlist_before_the_load(self):
        result = self.run_dual('dualcr8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.admissions(), [f'allowlist R9A09G057H44_R8_0 {CR8_0}dualcr8',
                                             f'allowlist R9A09G057H44_R8_1 {CR8_1}default'])
        # The snapshots are removed once the load returns.
        self.assertEqual(list(self.snapshots.iterdir()), [])

    def test_image_rejected_by_the_allowlist_is_never_loaded(self):
        for deny in (f'{CR8_0}dualcr8', f'{CR8_1}default'):
            with self.subTest(rejected=deny):
                self.log.unlink(missing_ok=True)
                result = self.run_dual('dualcr8', deny=deny)
                self.assertEqual(result.returncode, 2)
                self.assertIn(f'Refusing {deny}: its load addresses are not allowed', result.stderr)
                self.assertIn('DENY', result.stderr)
                self.assertEqual(self.loads(), [])
                self.assertEqual(list(self.snapshots.iterdir()), [])

    def test_single_core_load_is_checked_against_its_own_core(self):
        for target, device in ((f'{CR8_0}demo', 'R9A09G057H44_R8_0'), (f'{CR8_1}demo', 'R9A09G057H44_R8_1')):
            with self.subTest(target=target):
                self.log.unlink(missing_ok=True)
                result = self.run_dual(target, script='flash.sh')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.admissions(), [f'allowlist {device} {target}'])
                core = 'cr8_0' if device.endswith('R8_0') else 'cr8_1'
                self.assertEqual(self.loads(), [f'one-core {core} {target}'])
                self.log.unlink()
                result = self.run_dual(target, script='flash.sh', deny=target)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.loads(), [])

    def test_missing_allowlist_refuses_every_rzv2h_load(self):
        (self.tmp / 'platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py').unlink()
        for script, target in (('flash_dual.sh', 'dualcr8'), ('flash.sh', f'{CR8_0}demo')):
            with self.subTest(script=script):
                result = self.run_dual(target, script=script)
                self.assertEqual(result.returncode, 2)
                self.assertIn('allowlist', result.stderr)
                self.assertEqual(self.loads(), [])

    def test_loader_failure_is_reported_as_load_failed(self):
        result = self.run_dual('demosih', loader_rc=3)
        self.assertEqual(result.returncode, 1)

    def test_list_names_every_default_pair_without_loading(self):
        result = self.run_dual('--list')
        self.assertEqual(result.returncode, 0, result.stderr)
        for cr8_0, cr8_1 in (('demosih', 'demo'), ('dualcr8', 'default')):
            self.assertRegex(result.stdout, rf'{CR8_0}{cr8_0}\s+\+ {CR8_1}{cr8_1}\s+\[built\]')
        self.assertEqual(self.loads(), [])


if __name__ == '__main__':
    unittest.main()
