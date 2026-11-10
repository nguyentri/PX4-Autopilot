#!/usr/bin/env python3
"""Check which CR8-0 + CR8-1 pair flash_dual.sh hands to the guarded loader.

The real flash.sh and flash_dual.sh run in an isolated tree with empty ELFs
and a stub pair loader that records its arguments, so no probe is touched.
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
BUILT = [CR8_0 + c for c in ('default', 'demo', 'demosih', 'dualcr8', 'sih')] + \
        [CR8_1 + c for c in ('default', 'demo', 'pwm')] + ['renesas_rdk-rzv2h-io-cm33_default']


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
            elf.touch()
        debug = self.tmp / 'platforms/nuttx/Debug'
        executable(debug / 'rtt-console-stop.sh', '#!/bin/sh\nexit 0\n')
        executable(debug / 'rzv2h-ipc/rzv2h-ipc-demo-load-both-auto.sh',
                   '#!/bin/sh\necho "$@" >>"$LOADER_LOG"\nexit "${LOADER_RC:-0}"\n')
        # A single-core load must never happen from flash_dual.sh.
        executable(debug / 'rzv2h-ipc/rzv2h-load-one-core.sh',
                   '#!/bin/sh\necho "one-core $*" >>"$LOADER_LOG"\n')
        self.log = self.tmp / 'loader.log'

    def run_dual(self, *args, loader_rc=0):
        env = dict(os.environ, JLINK_SERIAL='0', LOADER_LOG=str(self.log), LOADER_RC=str(loader_rc))
        return subprocess.run([str(self.tmp / 'flash_dual.sh'), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def loads(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def pair(self, cr8_0, cr8_1, verbose=False):
        root = self.tmp.resolve()
        elfs = f'{root}/build/{CR8_0}{cr8_0}/{CR8_0}{cr8_0}.elf {root}/build/{CR8_1}{cr8_1}/{CR8_1}{cr8_1}.elf'
        return [('--verbose ' if verbose else '') + elfs]

    def test_cr8_0_target_alone_gets_its_default_partner(self):
        for name, partner in (('demo', 'demo'), ('demosih', 'demo'), ('dualcr8', 'pwm')):
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
        result = self.run_dual('sih')
        self.assertEqual(result.returncode, 2)
        self.assertIn('no default CR8-1 partner', result.stderr)
        self.assertEqual(self.loads(), [])

    def test_unbuilt_default_partner_is_refused(self):
        shutil.rmtree(self.tmp / 'build' / f'{CR8_1}pwm')
        result = self.run_dual('dualcr8')
        self.assertEqual(result.returncode, 2)
        self.assertIn(f'./build.sh {CR8_1}pwm', result.stderr)
        self.assertEqual(self.loads(), [])

    def test_wrong_core_in_either_position_is_refused(self):
        for args in (('rdk-rzv2h-io-cr8_1_demo',), ('rdk-rzv2h-io-cm33_default',),
                     ('demosih', 'rdk-rzv2h_demo'), ('demosih', 'rdk-rzv2h-io-cm33_default'),
                     ('nosuchtarget',), (), ('demo', 'demo', 'demo'), ('--bogus',)):
            with self.subTest(args=args):
                result = self.run_dual(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(self.loads(), [])

    def test_loader_failure_is_reported_as_load_failed(self):
        result = self.run_dual('demosih', loader_rc=3)
        self.assertEqual(result.returncode, 1)

    def test_list_names_every_default_pair_without_loading(self):
        result = self.run_dual('--list')
        self.assertEqual(result.returncode, 0, result.stderr)
        for cr8_0, cr8_1 in (('demo', 'demo'), ('demosih', 'demo'), ('dualcr8', 'pwm')):
            self.assertRegex(result.stdout, rf'{CR8_0}{cr8_0}\s+\+ {CR8_1}{cr8_1}\s+\[built\]')
        self.assertEqual(self.loads(), [])


if __name__ == '__main__':
    unittest.main()
