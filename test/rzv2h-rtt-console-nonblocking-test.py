#!/usr/bin/env python3
"""The RTT console never spins for a host with interrupts masked: the RZ/V2H
PX4 profiles drop output that does not fit a full RTT up-buffer instead of
blocking, so a detached or slow probe cannot stall the flight core."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEGGER = ROOT / 'platforms/nuttx/NuttX/nuttx/drivers/segger'
RTT_SOURCE = SEGGER / 'RTT/RTT/SEGGER_RTT.c'
PROFILES = ROOT / 'boards/renesas/rdk-rzv2h/nuttx-config'

CONFIG = '''#pragma once
#define CONFIG_SEGGER_RTT_CPU_CACHE_LINE_SIZE 0
#define CONFIG_SEGGER_RTT_UNCACHED_OFF 0
#define CONFIG_SEGGER_RTT_MAX_NUM_UP_BUFFERS 3
#define CONFIG_SEGGER_RTT_MAX_NUM_DOWN_BUFFERS 3
#define CONFIG_SEGGER_RTT_BUFFER_SIZE_UP 64
#define CONFIG_SEGGER_RTT_BUFFER_SIZE_DOWN 16
'''

# The lock the RTT library takes around every write: interrupts masked.
SPINLOCK = '''#pragma once
typedef unsigned irqstate_t;
extern int g_irq_masked;
static inline irqstate_t spin_lock_irqsave(void *lock) { (void)lock; return g_irq_masked++; }
static inline void spin_unlock_irqrestore(void *lock, irqstate_t flags) { (void)lock; g_irq_masked = flags; }
'''

MAIN = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "SEGGER_RTT.h"
int g_irq_masked;
int main(void) {
  char line[200];
  memset(line, 'x', sizeof(line));
  SEGGER_RTT_Init();

  /* No host drains the 64-byte up-buffer: the write returns what fits. */
  unsigned written = SEGGER_RTT_Write(0, line, sizeof(line));
  assert(written == 63 && g_irq_masked == 0);
  assert(SEGGER_RTT_Write(0, line, sizeof(line)) == 0 && g_irq_masked == 0);
  puts("returned");
  return 0;
}
'''


@unittest.skipUnless(RTT_SOURCE.exists(), 'SEGGER RTT sources are unpacked by the first NuttX build')
class RttUpBufferMode(unittest.TestCase):
    def run_full_buffer_write(self, mode):
        with tempfile.TemporaryDirectory(prefix='rzv2h-rtt-mode-') as directory:
            directory = Path(directory)
            (directory / 'nuttx').mkdir()
            config = CONFIG + (f'#define CONFIG_SEGGER_RTT_UP_MODE_{mode} 1\n' if mode else '')
            (directory / 'nuttx/config.h').write_text(config)
            (directory / 'nuttx/spinlock.h').write_text(SPINLOCK)
            (directory / 'main.c').write_text(MAIN)
            binary = directory / 'rtt'
            subprocess.run(['cc', '-std=gnu11', '-Wno-pointer-to-int-cast', '-Wno-int-to-pointer-cast',
                            '-I', str(directory), '-I', str(SEGGER / 'config'), '-I', str(RTT_SOURCE.parent),
                            str(RTT_SOURCE), str(directory / 'main.c'), '-o', str(binary)],
                           check=True, capture_output=True, text=True)
            try:
                return subprocess.run([str(binary)], capture_output=True, text=True, timeout=2)
            except subprocess.TimeoutExpired:
                return None

    def test_trim_mode_returns_with_interrupts_restored_when_no_host_drains(self):
        result = self.run_full_buffer_write('TRIM')
        self.assertIsNotNone(result, 'a full buffer blocked the writer')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('returned', result.stdout)

    def test_stock_block_mode_spins_forever_with_interrupts_masked(self):
        # The hazard the profiles opt out of: the default mode never returns.
        self.assertIsNone(self.run_full_buffer_write(None))


class RttProfileSelection(unittest.TestCase):
    def test_every_px4_rtt_profile_drops_output_instead_of_blocking(self):
        profiles = [path for path in sorted(PROFILES.glob('*/defconfig'))
                    if re.search(r'^CONFIG_SEGGER_RTT=y$', path.read_text(), re.M)]
        self.assertGreaterEqual(len(profiles), 5)
        for path in profiles:
            with self.subTest(profile=path.parent.name):
                text = path.read_text()
                self.assertRegex(text, r'(?m)^CONFIG_SEGGER_RTT_UP_MODE_TRIM=y$')
                self.assertNotRegex(text, r'(?m)^CONFIG_SEGGER_RTT_UP_MODE_(BLOCK|SKIP)=y$')

    def test_kconfig_choice_maps_onto_the_rtt_library_modes(self):
        header = (SEGGER / 'config/SEGGER_RTT_Conf.h').read_text()
        self.assertRegex(header, r'CONFIG_SEGGER_RTT_UP_MODE_TRIM\)\n#  define SEGGER_RTT_MODE_DEFAULT\s+'
                                 r'SEGGER_RTT_MODE_NO_BLOCK_TRIM')
        kconfig = (SEGGER / 'Kconfig').read_text()
        for mode in ('BLOCK', 'TRIM', 'SKIP'):
            self.assertIn(f'config SEGGER_RTT_UP_MODE_{mode}\n', kconfig)


if __name__ == '__main__':
    unittest.main()
