#!/usr/bin/env python3
"""Check the R-Car V4H CR52 image windows: both linker scripts, both
defconfigs and the PT_LOAD allowlist manifest must name the same windows,
256 KiB aligned, disjoint, inside the CR52 DRAM area, with the CR52-2
window left free."""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'platforms/nuttx/NuttX/nuttx/boards/arm/rcar/sparrow_hawk'
MANIFEST = ROOT / 'platforms/nuttx/Debug/rcarv4h-cr52-elf-allowlists.json'

CR52_AREA = (0x40100000, 0x40B00000)   # CR52 cluster DRAM, end exclusive
CR52_2_WINDOW = (0x40700000, 0x40A00000)
ALIGN = 256 * 1024

# core -> (linker script, defconfig, manifest device)
IMAGES = {
    0: ('sparrow_hawk_cr52_0.ld', 'nsh', 'R8A779G3_CR52_0'),
    1: ('sparrow_hawk_cr52_1.ld', 'nsh-cr52_1', 'R8A779G3_CR52_1'),
}

SIZE_SUFFIX = {'': 1, 'K': 1024, 'M': 1024 * 1024}


def ld_window(script):
    text = (BOARD / 'scripts' / script).read_text()
    block = re.search(r'MEMORY\s*\{(.*?)\}', text, re.S)
    if block is None:
        raise AssertionError(f'{script}: no MEMORY block')
    regions = re.findall(r'^\s*(\w+)\s*\([^)]*\)\s*:\s*ORIGIN\s*=\s*(0x[0-9a-fA-F]+)\s*,'
                         r'\s*LENGTH\s*=\s*(\d+|0x[0-9a-fA-F]+)([KM]?)\s*$',
                         block.group(1), re.M)
    if len(regions) != 1:
        raise AssertionError(f'{script}: expected one MEMORY region, got {regions}')
    _, origin, length, suffix = regions[0]
    start = int(origin, 16)
    return start, start + int(length, 0) * SIZE_SUFFIX[suffix]


def defconfig_window(config):
    text = (BOARD / 'configs' / config / 'defconfig').read_text()
    values = {}
    for name in ('RAM_START', 'RAM_SIZE'):
        match = re.search(rf'^CONFIG_{name}=(\S+)$', text, re.M)
        if match is None:
            raise AssertionError(f'{config}: CONFIG_{name} missing')
        values[name] = int(match.group(1), 0)
    return values['RAM_START'], values['RAM_START'] + values['RAM_SIZE']


def manifest_window(device):
    data = json.loads(MANIFEST.read_text())
    entry = data['devices'][device]
    if len(entry['ranges']) != 1:
        raise AssertionError(f'{device}: expected one range')
    window = entry['ranges'][0]
    return entry['status'], (int(window['start'], 0), int(window['end'], 0))


def overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


class WindowTest(unittest.TestCase):
    def test_sources_agree(self):
        for core, (script, config, device) in IMAGES.items():
            with self.subTest(core=core):
                status, window = manifest_window(device)
                self.assertEqual(ld_window(script), window)
                self.assertEqual(defconfig_window(config), window)
                # No target proof yet: the manifest stays inspection-only.
                self.assertEqual(status, 'proposed')

    def test_layout(self):
        windows = [manifest_window(device)[1] for _, _, device in IMAGES.values()]
        for start, end in windows:
            self.assertEqual(start % ALIGN, 0)
            self.assertEqual(end % ALIGN, 0)
            self.assertGreaterEqual(start, CR52_AREA[0])
            self.assertLessEqual(end, CR52_AREA[1])
            self.assertFalse(overlaps((start, end), CR52_2_WINDOW))
        self.assertFalse(overlaps(windows[0], windows[1]))

    def test_manifest_has_no_cr52_2_image(self):
        data = json.loads(MANIFEST.read_text())
        self.assertEqual(sorted(data['devices']), sorted(d for _, _, d in IMAGES.values()))

    def test_vectors_first(self):
        for script, _, _ in IMAGES.values():
            with self.subTest(script=script):
                text = (BOARD / 'scripts' / script).read_text()
                self.assertIn('ENTRY(__start)', text)
                text_section = re.search(r'\.text\s*:\s*\{(.*?)\}', text, re.S).group(1)
                first = [l.strip() for l in text_section.splitlines()
                         if l.strip() and not l.strip().startswith('_stext')][0]
                self.assertEqual(first, 'KEEP(*(.vectors))')


if __name__ == '__main__':
    unittest.main()
