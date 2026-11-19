#!/usr/bin/env python3
"""Exercise the boot packager against actual linked CR8 firmware artifacts."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/renesas_rdk-rzv2h_default'
STEM = 'renesas_rdk-rzv2h_default'
TOOL = ROOT / 'platforms/nuttx/Debug/rzv2h-boot-package.py'
spec = importlib.util.spec_from_file_location('boot_package', TOOL)
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class BootPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.elf = (BUILD / (STEM + '.elf')).read_bytes()
        cls.image = (BUILD / (STEM + '.bin')).read_bytes()
        cls.layout = json.loads((ROOT / 'boards/renesas/rdk-rzv2h/boot-layout.json').read_text())

    def test_native_image_round_trip_and_initialized_data_coverage(self):
        candidate, manifest = boot.make_package(self.elf, self.image, self.layout)
        self.assertEqual(candidate, self.image)
        self.assertFalse(manifest['deployment_enabled'])
        self.assertEqual(manifest['entry'], 0x40800000)
        blocks = manifest['blocks']
        self.assertEqual(sum(item['size'] for item in blocks) + 128, len(candidate))
        entry, segments = boot.elf_loads(self.elf)
        self.assertTrue(any(flags & 2 and size > 0 for address, size, memory, flags, payload in segments))
        self.assertTrue(any(memory > size for address, size, memory, flags, payload in segments))
        self.assertEqual(entry, manifest['entry'])

    def test_rebase_changes_only_source_addresses_and_complements(self):
        layout = copy.deepcopy(self.layout)
        layout['image_base'] = '0x60200000'
        candidate, manifest = boot.make_package(self.elf, self.image, layout)
        before = struct.unpack_from('<32I', self.image)
        after = struct.unpack_from('<32I', candidate)
        for index in range(32):
            self.assertEqual(after[index], before[index] + 0x40000000 if index in (0, 6, 12)
                             else before[index] - 0x40000000 if index in (3, 9, 15) else before[index])
        self.assertEqual(candidate[128:], self.image[128:])
        self.assertEqual(manifest['image_base'], 0x60200000)

    def test_header_checksum_magic_padding_and_handoff_rejection(self):
        for index in (3, 19, 20, 21, 18):
            with self.subTest(index=index):
                image = bytearray(self.image)
                image[index * 4] ^= 1
                with self.assertRaises(ValueError):
                    boot.make_package(self.elf, image, self.layout)

    def test_initialized_data_corruption_is_rejected(self):
        image = bytearray(self.image)
        image[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'contents'):
            boot.make_package(self.elf, image, self.layout)

    def test_truncated_image_and_trailing_bytes_are_rejected(self):
        for image in (self.image[:127], self.image[:-1], self.image + b'\0'):
            with self.subTest(length=len(image)), self.assertRaises(ValueError):
                boot.make_package(self.elf, image, self.layout)

    def test_elf_truncation_machine_endian_and_entry_are_rejected(self):
        for offset, value in ((5, 2), (18, 3), (24, 0xff)):
            elf = bytearray(self.elf)
            elf[offset] = value
            if offset == 24:
                struct.pack_into('<I', elf, 24, 0xffffffff)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                boot.make_package(elf, self.image, self.layout)
        with self.assertRaises(ValueError):
            boot.make_package(self.elf[:51], self.image, self.layout)

    def test_initialized_segment_outside_loader_copy_is_rejected(self):
        elf = bytearray(self.elf)
        phoff = struct.unpack_from('<I', elf, 28)[0]
        # Move the initialized RW segment beyond the existing copy block.
        for index in range(struct.unpack_from('<H', elf, 44)[0]):
            pos = phoff + 32 * index
            fields = struct.unpack_from('<8I', elf, pos)
            if fields[0] == 1 and fields[2] >= 0x40800000 and fields[4] > 0 and fields[6] == 6:
                address = 0x41000000 + (fields[1] & 0xfff)
                struct.pack_into('<II', elf, pos + 8, address, address)
                break
        else:
            self.fail('actual firmware has no initialized DDR data')
        with self.assertRaisesRegex(ValueError, 'covered'):
            boot.make_package(elf, self.image, self.layout)

    def test_reserved_memory_and_address_overflow_are_rejected(self):
        for update in ({'image_base': '0xfffffff0'}, {'image_base': '0x40800000'}, {'itcm_axi_alias': '0x12040004'},
                       {'load_regions': [{'base': 0, 'size': 128}]},
                       {'reserved_regions': [{'base': 0x081bfffc, 'size': 4}, {'base': 0x40800000, 'size': 4096}]}):
            layout = copy.deepcopy(self.layout)
            layout.update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                boot.make_package(self.elf, self.image, layout)

    def test_unknown_or_enabled_deployment_layout_is_rejected(self):
        for update in ({'format': 'guess'}, {'core': 'cm33'}, {'deployment_enabled': True}):
            layout = copy.deepcopy(self.layout)
            layout.update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                boot.make_package(self.elf, self.image, layout)

    def test_cli_preserves_existing_output_and_rejects_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'candidate'
            command = [sys.executable, str(TOOL), '--elf', str(BUILD / (STEM + '.elf')),
                       '--image', str(BUILD / (STEM + '.bin')),
                       '--layout', str(ROOT / 'boards/renesas/rdk-rzv2h/boot-layout.json'), '--output', str(out)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            snapshot = {p.name: p.read_bytes() for p in out.iterdir()}
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(snapshot, {p.name: p.read_bytes() for p in out.iterdir()})
            command[-1] = str(Path(tmp) / 'rejected')
            bad = Path(tmp) / 'bad-layout.json'
            bad.write_text('{}')
            command[command.index('--layout') + 1] = str(bad)
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertFalse(Path(command[-1]).exists())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-dir', type=Path, default=BUILD)
    parser.add_argument('--stem', default=STEM)
    args, remaining = parser.parse_known_args()
    BUILD, STEM = args.build_dir.resolve(), args.stem
    unittest.main(argv=[sys.argv[0]] + remaining)
