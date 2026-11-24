#!/usr/bin/env python3
"""Compile the armv8-r PMSAv8-32 MPU encoders on the host and check them,
and the production R-Car V4H CR52 region table, for each core image."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / 'platforms/nuttx/NuttX/nuttx'
ARMV8R = NUTTX / 'arch/arm/src/armv8-r'
RCAR = NUTTX / 'arch/arm/src/rcar'
HARNESS = Path(__file__).with_name('rcarv4h-cr52-pmsav8-mpu-host-harness.c')
CONFIGS = NUTTX / 'boards/arm/rcar/sparrow_hawk/configs'

# Image windows from the plan's memory map; the defconfigs must agree.
IMAGES = {
    'nsh': (0x40100000, 0x300000),
    'nsh-cr52_1': (0x40400000, 0x300000),
}


def defconfig_value(config, name):
    text = (CONFIGS / config / 'defconfig').read_text()
    match = re.search(rf'^CONFIG_{name}=(\S+)$', text, re.M)
    if match is None:
        raise AssertionError(f'{config}: CONFIG_{name} missing')
    return int(match.group(1), 0)


def table_source():
    source = (RCAR / 'rcar_mpu_regions.c').read_text()
    match = re.search(r'static const struct mpu_region_s g_rcar_mpu_table\[\] =\n\{.*?\n\};\n',
                      source, re.S)
    if match is None:
        raise AssertionError('g_rcar_mpu_table not found')
    return match.group(0)


def memorymap_defines():
    header = (RCAR / 'hardware/rcar_memorymap.h').read_text()
    lines = []
    for name in ('RCAR_DEVICE_BASE', 'RCAR_DEVICE_SIZE', 'RCAR_GIC_BASE',
                 'RCAR_GIC_SIZE', 'RCAR_IPC_SHM_BASE', 'RCAR_IPC_SHM_SIZE',
                 'RCAR_ICCOM_CTA_BASE', 'RCAR_ICCOM_CTA_SIZE'):
        match = re.search(rf'^#define {name}\s+(0x[0-9a-fA-F]+)', header, re.M)
        if match is None:
            raise AssertionError(f'{name} missing from rcar_memorymap.h')
        lines.append(f'#define {name} {match.group(1)}u')
    return '\n'.join(lines)


def expected(start, size, iccom):
    # Independent of mpu.h: base | SH | AP | XN and limit | AttrIndx | EN.
    ram = (start, (start + size - 1) & ~0x3f | (2 << 1) | 1)
    device = (0xe6000000 | 1, 0xefffffc0 | (1 << 1) | 1)
    gic = (0xf0000000 | 1, 0xf01fffc0 | (1 << 1) | 1)
    # OpenAMP window and ICCOM CTA: Normal NC (3), outer shareable, XN.
    shm = (0x40a00000 | (2 << 3) | 1, 0x40afffc0 | (3 << 1) | 1)
    cta = (0x47fc7000 | (2 << 3) | 1, 0x47fcefc0 | (3 << 1) | 1)
    return [ram, device, gic, shm] + ([cta] if iccom else [])


class MpuEncodeTest(unittest.TestCase):
    def test_images(self):
        table = table_source()
        defines = memorymap_defines()
        cases = [(c, w, False) for c, w in IMAGES.items()]
        cases.append(('nsh', IMAGES['nsh'], True))  # CR52-0 with ICCOM
        for config, (start, size), iccom in cases:
            with self.subTest(config=config, iccom=iccom):
                self.assertEqual(defconfig_value(config, 'RAM_START'), start)
                self.assertEqual(defconfig_value(config, 'RAM_SIZE'), size)
                regions = expected(start, size, iccom)
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp)
                    (path / 'rcarv4h-mpu-table.h').write_text(
                        f'#define IMAGE_NAME "{config}"\n'
                        + ('#define CONFIG_RCAR_ICCOM 1\n' if iccom else '')
                        + f'#define CONFIG_RAM_START {start:#x}u\n'
                        f'#define CONFIG_RAM_SIZE {size:#x}u\n'
                        f'#define EXPECT_WINDOW_LAST {start + size - 1:#x}u\n'
                        f'{defines}\n{table}\n'
                        'static const uint32_t g_expect_prbar[] = {'
                        + ', '.join(f'{b:#010x}u' for b, _ in regions) + '};\n'
                        'static const uint32_t g_expect_prlar[] = {'
                        + ', '.join(f'{l:#010x}u' for _, l in regions) + '};\n')
                    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                    '-I', str(path), '-I', str(ARMV8R),
                                    str(HARNESS), '-o', str(path / 'test')],
                                   check=True, timeout=60)
                    result = subprocess.run([str(path / 'test')], check=True,
                                            timeout=30, capture_output=True,
                                            text=True)
                    self.assertIn(f'PASS {config}', result.stdout)


if __name__ == '__main__':
    unittest.main()
