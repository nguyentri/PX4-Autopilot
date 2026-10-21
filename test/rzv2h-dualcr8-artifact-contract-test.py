#!/usr/bin/env python3
"""Inspect the real v3 candidate ELFs; passing never admits an actuator pair."""
import argparse
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('artifact_check', ROOT / 'Tools/rzv2h-px4-artifact-check.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
BUILD_DIRS = []


class DualCr8Artifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = CHECK.policy(ROOT)
        cls.images = []
        for directory, target in zip(BUILD_DIRS, ('renesas_rdk-rzv2h_dualcr8', 'renesas_rdk-rzv2h-io-cr8_1_pwm')):
            profile = next(p for p in cls.contract['profiles'] if p['target'] == target)
            data = (directory / (target + '.elf')).read_bytes()
            nm = CHECK.tool(['arm-none-eabi-nm', '--defined-only', str(directory / (target + '.elf'))])
            symbols = {name: int(address, 16) for address, name in
                       re.findall(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$', nm, re.M)}
            cls.images.append((directory, profile, CHECK.elf_view(data), symbols))

    def test_core_configuration_and_distinct_rtt(self):
        rtt = []
        for directory, profile, view, symbols in self.images:
            with self.subTest(target=profile['target']):
                core = self.contract['cores'][profile['core']]
                config = CHECK.config_values((directory / 'NuttX/nuttx/.config').read_text())
                for flag, expected in profile['required_config'].items():
                    self.assertEqual(config.get(flag), expected, flag)
                for flag in profile['forbidden_config']:
                    self.assertNotIn(config.get(flag), ('y', 'm'), flag)
                self.assertEqual(config.get(core['core_option']), 'y')
                header = (directory / 'px4_boardconfig.h').read_text()
                CHECK.check_fault_hooks(header)
                self.assertIn('CONFIG_BOARD_ARCHITECTURE "cortex-r8"', header)
                cache = (directory / 'CMakeCache.txt').read_text()
                self.assertIn('PX4_BOARD_LABEL:STRING=' + profile['label'] + '\n', cache)
                self.assertEqual(view['entry'], symbols['__start'])
                for load in view['loads']:
                    self.assertTrue(CHECK.in_regions(load['address'], load['memory'], core['regions']))
                rtt.append(symbols['_SEGGER_RTT'])
        self.assertEqual(rtt, [0x081a2400, 0x081e2400])

    def test_linked_modules_have_one_producer_and_one_supervisor(self):
        for directory, profile, _, symbols in self.images:
            builtins = set(re.findall(r'^\{ "([^"]+)"', (directory / 'NuttX/px4.bdat').read_text(), re.M))
            self.assertTrue(set(profile['required_builtins']) <= builtins)
            self.assertFalse(set(profile['forbidden_builtins']) & builtins)
            for command in builtins:
                self.assertIn(command + '_main', symbols)
        symbols = self.images[0][3]
        for symbol in ('up_pwm_servo_init', 'up_pwm_servo_set', 'io_timer_init'):
            self.assertNotIn(symbol, symbols, symbol)
        for command in ('ekf2', 'commander', 'control_allocator', 'mc_rate_control', 'mc_att_control'):
            self.assertIn(command + '_main', symbols)

    def test_exact_bom_descriptor_and_linked_startup(self):
        directory, profile, view, symbols = self.images[0]
        CHECK.check_sensor_descriptors(CHECK.virtual_bytes(view, symbols['px4_spi_buses'], 48), 1)
        for directory, profile, view, symbols in self.images:
            romfs = (directory / 'ROMFS/romfs.img').read_bytes()
            self.assertEqual(CHECK.virtual_bytes(view, symbols['romfs_img'], len(romfs)), romfs)
            CHECK.check_romfs(directory, romfs)
            for source, installed in profile['startup_sources'].items():
                self.assertEqual(CHECK.significant_lines((directory / installed).read_text()),
                                 CHECK.significant_lines((ROOT / source).read_text()), installed)

    def test_packages_match_actual_firmware_and_metadata(self):
        for directory, profile, _, _ in self.images:
            package = CHECK.load_json(directory / (profile['target'] + '.px4'))
            binary = (directory / (profile['target'] + '.bin')).read_bytes()
            self.assertEqual(CHECK.decompress(package['image'], profile['image_maxsize']), binary)
            self.assertEqual(package['image_size'], len(binary))
            for field, filename in (('parameter_xml', 'parameters.xml'), ('airframe_xml', 'airframes.xml')):
                self.assertEqual(CHECK.decompress(package[field], 16 * 1024 * 1024), (directory / filename).read_bytes())

    def test_candidate_images_do_not_allocate_a_qualified_pair(self):
        for _, profile, _, _ in self.images:
            self.assertIsNone(profile['peer'])
            self.assertEqual([p['target'] for p in CHECK.select_profiles(self.contract, [profile['target']])],
                             [profile['target']])
        # Both historical staging directions must remain inadmissible.
        self.assertFalse(any(p['peer'] for p in self.contract['profiles']))
        with self.assertRaisesRegex(ValueError, 'no qualified image pair'):
            CHECK.check_pair(ROOT / 'build', self.contract, 'unused')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cr8-0-build-dir', type=Path, default=ROOT / 'build/renesas_rdk-rzv2h_dualcr8')
    parser.add_argument('--cr8-1-build-dir', type=Path, default=ROOT / 'build/renesas_rdk-rzv2h-io-cr8_1_pwm')
    args, remaining = parser.parse_known_args()
    BUILD_DIRS[:] = [args.cr8_0_build_dir, args.cr8_1_build_dir]
    unittest.main(argv=[__file__] + remaining)
