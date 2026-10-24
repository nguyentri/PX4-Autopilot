#!/usr/bin/env python3
"""Native inventory drift, default provenance and target-boundary contracts."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('inventory', ROOT/'platforms/nuttx/Debug/rzv2h-sample-inventory.py')
INVENTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INVENTORY)


class InventoryContracts(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(INVENTORY.POLICY.read_text())

    def test_complete_live_inventory(self):
        rows = INVENTORY.validate(self.manifest)
        discovered = list((ROOT/INVENTORY.BOARD/'configs').glob('*/defconfig'))
        self.assertEqual(len(rows), len(discovered))
        catalog = json.loads(INVENTORY.COVERAGE.read_text())
        baseline = catalog['baseline_native_profiles']
        self.assertEqual(len(baseline), 55)
        self.assertTrue({x['profile'] for x in baseline} <= {x['profile'] for x in rows})
        self.assertEqual([sum(x['core'] == c for x in baseline) for c in ('cr8_0','cr8_1','cm33')], [51,2,2])

    def test_missing_duplicate_and_stale_declarations_fail(self):
        for mutate in (lambda d: d['profiles'].pop(),
                       lambda d: d['profiles'].append(copy.deepcopy(d['profiles'][0])),
                       lambda d: d['profiles'][0].update(defconfig_sha256='0'*64),
                       lambda d: d['profiles'][0].update(core='cm33')):
            item = copy.deepcopy(self.manifest)
            mutate(item)
            with self.assertRaises(ValueError):
                INVENTORY.validate(item)

    def test_default_provenance_is_distinct_from_explicit_selection(self):
        implicit = INVENTORY.identity({}, 'RZV2H_BUILD_CR8_0')
        explicit = INVENTORY.identity({'CONFIG_RZV2H_BUILD_CR8_0':'y'}, 'RZV2H_BUILD_CR8_0')
        self.assertEqual(implicit['core'], explicit['core'])
        self.assertEqual(implicit['core_source'], 'kconfig-default')
        self.assertEqual(explicit['core_source'], 'defconfig-selector')
        item = copy.deepcopy(self.manifest)
        item['core_default'] = 'RZV2H_BUILD_CR8_1'
        with self.assertRaisesRegex(ValueError, 'default changed'):
            INVENTORY.validate(item)

    def test_conflicting_core_selectors_are_rejected(self):
        for cfg in ({'CONFIG_RZV2H_BUILD_CR8_0':'y','CONFIG_RZV2H_BUILD_CM33':'y'},
                    {'CONFIG_RZV2H_BUILD_CR8_0':'y','CONFIG_RZV_MPU_CR8_CORE_NUM':'1'},
                    {'CONFIG_ARCH_CORTEXM33':'y'}):
            with self.assertRaises(ValueError):
                INVENTORY.identity(cfg, 'RZV2H_BUILD_CR8_0')

    def test_diagnostic_rtt_and_scif_are_not_interactive_rtt(self):
        rows = {x['profile']:x for x in self.manifest['profiles']}
        self.assertEqual(rows['nsh-rtt']['console'], 'sci4')
        self.assertEqual(rows['nsh-scif']['console'], 'scif0')
        self.assertEqual(rows['hil-uart-loopback']['console'], 'rtt-output')
        self.assertEqual(rows['hil-uart-loopback']['entrypoint'], 'hwtest_main')

    def test_hazardous_and_peer_images_are_blocked_before_loading(self):
        rows = {x['profile']:x for x in self.manifest['profiles']}
        for name in ('wdt','ether','sdhi','ipcc','ipcc-multi','ipcc-raw-cm33','nsh-cm33'):
            self.assertEqual(rows[name]['mode'], 'blocked', name)
            self.assertTrue(rows[name]['reason'])
        self.assertIn('watchdog-autostart', rows['wdt']['hazards'])

    def test_command_and_timeout_mutants_fail(self):
        for fields in ({'commands':['hwtest\nreboot']}, {'timeout':0}, {'timeout':True}, {'requirements':None}):
            item = copy.deepcopy(self.manifest)
            item['profiles'][0].update(fields)
            with self.assertRaises(ValueError):
                INVENTORY.validate(item)

    def test_unsafe_profile_names_never_form_paths(self):
        for name in ('../nsh', '/tmp/image', 'a;b', 'nsh\n'):
            with self.assertRaises(ValueError):
                INVENTORY.inspect_profile(name)


if __name__ == '__main__':
    unittest.main()
