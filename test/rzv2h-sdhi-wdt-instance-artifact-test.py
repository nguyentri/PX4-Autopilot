#!/usr/bin/env python3
"""Admit real SDHI/WDT instance ELFs and reject rehashed semantic mutants."""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'indexed_artifact_fixtures', ROOT / 'test/rzv2h-driver-instance-artifact-test.py')
F = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F)
ART = F.ART
BUILDS = SOURCE = None


class IndexedArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (SOURCE or BUILDS.parent / 'source-state.json').resolve()
        cls.policy = json.loads((cls.source.parent / 'sample-profiles.json').read_text())
        names = [f'{family}{channel}-board-rtt'
                 for family, count in [('sdhi', 3), ('wdt', 4)]
                 for channel in range(count)]
        cls.rows = [next(row for row in cls.policy['profiles'] if row['profile'] == name)
                    for name in names]
        for row in cls.rows:
            if not (BUILDS / row['profile'] / 'build-receipt.json').is_file():
                raise RuntimeError('real instance compiler archive required: ' + row['profile'])

    def copied(self, row):
        temporary = tempfile.TemporaryDirectory(prefix='rzv2h-indexed-artifact-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in ('source-state.json', 'sample-profiles.json',
                     'legacy-sample-profiles.json', 'driver-coverage.json'):
            shutil.copy2(self.source.parent / name, root / name)
        directory = root / 'builds' / row['profile']
        shutil.copytree(BUILDS / row['profile'], directory)
        return copy.deepcopy(row), directory, root / 'source-state.json'

    def rehash(self, directory, name):
        path = directory / 'build-receipt.json'
        receipt = json.loads(path.read_text())
        receipt['file_sha256'][name] = hashlib.sha256(
            (directory / name).read_bytes()).hexdigest()
        path.write_text(json.dumps(receipt))

    def rejected_config(self, row, key, value):
        inputs = self.copied(row)
        path = inputs[1] / 'resolved.config'
        text = re.sub(r'^(?:' + re.escape(key) + r'=.*|# ' +
                      re.escape(key) + r' is not set)\n', '', path.read_text(), flags=re.M)
        path.write_text(text + '\n' + key + '=' + value + '\n')
        self.rehash(inputs[1], 'resolved.config')
        with self.assertRaisesRegex(ValueError, re.escape(key)):
            ART.verify_native(*inputs, self.policy)

    def test_all_seven_actual_images_are_build_checked(self):
        for row in self.rows:
            result = ART.verify_native(row, BUILDS / row['profile'], self.source, self.policy)
            self.assertEqual(result['status'], 'BUILD-CHECKED')
            self.assertEqual(result['on_target'], 'NOT-RUN')
            self.assertFalse(result['artifact_authorized'])
            self.assertFalse(result['target_prerequisites_verified'])

    def test_wrong_fixed_family_and_channel_are_rejected(self):
        for row in self.rows:
            self.rejected_config(row, 'CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY', '1')
            self.rejected_config(row, 'CONFIG_TESTING_RZV_HWTEST_INSTANCE_CHANNEL', '15')

    def test_sdhi_media_binding_cannot_be_enabled(self):
        for row in self.rows[:3]:
            for key, value in [('CONFIG_MMCSD', 'y'), ('CONFIG_MMCSD_SDIO', 'y'),
                               ('CONFIG_FS_FAT', 'y'), ('CONFIG_RZV2H_SDHI_LOWER_ONLY', 'n')]:
                with self.subTest(profile=row['profile'], key=key):
                    self.rejected_config(row, key, value)

    def test_wdt_siblings_and_automatic_operations_are_rejected(self):
        for row in self.rows[3:]:
            peer = (row['instance']['channel'] + 1) % 4
            for key in (f'CONFIG_RZV_WDT{peer}', 'CONFIG_WATCHDOG_AUTOMONITOR',
                        'CONFIG_RZV2H_WDT_TEST', 'CONFIG_RZV_WDT_INTERRUPT_MODE'):
                with self.subTest(profile=row['profile'], key=key):
                    self.rejected_config(row, key, 'y')

    def test_indexed_provider_must_be_linked(self):
        for row in self.rows:
            inputs = self.copied(row)
            name = 'rzv2h_' + row['instance']['family'] + '_sample_state_at'
            path = inputs[1] / 'nuttx.elf'
            data = path.read_bytes()
            mutant = data.replace(name.encode(), ('z' + name[1:]).encode())
            self.assertNotEqual(mutant, data)
            path.write_bytes(mutant)
            self.rehash(inputs[1], 'nuttx.elf')
            with self.assertRaisesRegex(ValueError, name):
                ART.verify_native(*inputs, self.policy)

    def test_case_table_requires_a_callable_identity_case(self):
        for row in self.rows:
            inputs = self.copied(row)
            path = inputs[1] / 'nuttx.elf'
            data = bytearray(path.read_bytes())
            tables = [item for item in ART.elf32_symbols(data)['g_cases']
                      if item[1:3] == (36, 1)]
            self.assertEqual(len(tables), 1)
            struct.pack_into('<I', data, F.virtual_offset(data, tables[0][0] + 20), 0)
            path.write_bytes(data)
            self.rehash(inputs[1], 'nuttx.elf')
            with self.assertRaisesRegex(ValueError, 'case function pointer'):
                ART.verify_native(*inputs, self.policy)

    def test_guard_options_survive_weakened_catalogue_declarations(self):
        catalog = json.loads((self.source.parent / 'driver-coverage.json').read_text())
        for row in self.rows:
            weak = copy.deepcopy(catalog)
            cell = next(item for item in weak['instances']
                        if item['instance_id'] == row['instance_id'])
            cell['required_config'] = {}
            directory = BUILDS / row['profile']
            config = ART.INVENTORY.read_config(directory / 'resolved.config')
            key = 'CONFIG_MMCSD' if row['instance']['family'] == 'sdhi' else 'CONFIG_WATCHDOG_AUTOMONITOR'
            config[key] = 'y'
            symbols = ART.elf32_symbols((directory / 'nuttx.elf').read_bytes())
            strings = subprocess.check_output(['arm-none-eabi-strings', str(directory / 'nuttx.elf')], text=True)
            receipt = json.loads((directory / 'build-receipt.json').read_text())
            with self.assertRaisesRegex(ValueError, key):
                ART.verify_instance(row, config, symbols, strings, weak, receipt)

    def test_indexed_provider_is_required_without_catalogue_symbol_claims(self):
        catalog = json.loads((self.source.parent / 'driver-coverage.json').read_text())
        for row in self.rows:
            weak = copy.deepcopy(catalog)
            cell = next(item for item in weak['instances']
                        if item['instance_id'] == row['instance_id'])
            cell['required_symbols'] = []
            directory = BUILDS / row['profile']
            name = 'rzv2h_' + row['instance']['family'] + '_sample_state_at'
            original = (directory / 'nuttx.elf').read_bytes()
            mutant = original.replace(name.encode(), ('z' + name[1:]).encode())
            self.assertNotEqual(mutant, original)
            symbols = ART.elf32_symbols(mutant)
            config = ART.INVENTORY.read_config(directory / 'resolved.config')
            strings = subprocess.check_output(['arm-none-eabi-strings', str(directory / 'nuttx.elf')], text=True)
            receipt = json.loads((directory / 'build-receipt.json').read_text())
            with self.assertRaisesRegex(ValueError, name):
                ART.verify_instance(row, config, symbols, strings, weak, receipt)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--builds', type=Path, required=True)
    parser.add_argument('--source-state', type=Path)
    args, remaining = parser.parse_known_args()
    BUILDS, SOURCE = args.builds.resolve(), args.source_state
    unittest.main(argv=[__file__, *remaining])
