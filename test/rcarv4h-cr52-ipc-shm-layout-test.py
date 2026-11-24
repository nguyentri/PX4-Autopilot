#!/usr/bin/env python3
"""Check the R-Car V4H CR52 IPC memory layout: the OpenAMP shared window
(control record, resource table, vrings, RPMsg pool) and the ICCOM CTA.

rcar_ipc_shm.h is compiled on the host, so its static_asserts run too;
the offsets it prints are compared with the expected rptun placement."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RCAR = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rcar'

# CR52-0, CR52-1 and the CR52-2 window that stays free, end exclusive
IMAGE_WINDOWS = [(0x40100000, 0x40400000), (0x40400000, 0x40700000),
                 (0x40700000, 0x40A00000)]

PROBE = r'''
#include <stdio.h>
#include "rcar_ipc_shm.h"
#define P(n) printf(#n " %llu\n", (unsigned long long)(n))
int main(void)
{
  P(RCAR_IPC_SHM_BASE); P(RCAR_IPC_SHM_SIZE);
  P(RCAR_ICCOM_CTA_BASE); P(RCAR_ICCOM_CTA_SIZE);
  P(RCAR_IPC_CTRL_OFFSET); P(RCAR_IPC_CTRL_SIZE);
  P(RCAR_IPC_RSC_OFFSET); P(RCAR_IPC_RSC_SIZE);
  P(RCAR_IPC_VRING0_OFFSET); P(RCAR_IPC_VRING1_OFFSET);
  P(RCAR_IPC_VRING_SPAN); P(RCAR_IPC_VRING_NUM); P(RCAR_IPC_VRING_ALIGN);
  P(RCAR_IPC_POOL_OFFSET); P(RCAR_IPC_POOL_SIZE); P(RCAR_IPC_BUF_SIZE);
  P(RCAR_IPC_USED_END); P(RCAR_IPC_MAGIC); P(RCAR_IPC_VERSION);
  P(sizeof(struct rcar_ipc_ctrl_s));
  return 0;
}
'''


def overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def vring_size(num, align):
    # OpenAMP vring_size(): descriptors + avail ring, aligned, + used ring
    avail_end = 16 * num + 2 * (2 + num) + 2
    used = 2 * 2 + 8 * num + 2
    return ((avail_end + align - 1) & ~(align - 1)) + used


class IpcShmLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'probe.c'
            exe = Path(tmp) / 'probe'
            src.write_text(PROBE)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Werror', '-I', str(RCAR),
                            str(src), '-o', str(exe)], check=True, timeout=60)
            out = subprocess.run([str(exe)], check=True, timeout=30,
                                 capture_output=True, text=True).stdout
        cls.v = {k: int(n) for k, n in (line.rsplit(" ", 1) for line in out.splitlines())}

    def test_window_placement(self):
        v = self.v
        shm = (v['RCAR_IPC_SHM_BASE'], v['RCAR_IPC_SHM_BASE'] + v['RCAR_IPC_SHM_SIZE'])
        self.assertEqual(shm, (0x40A00000, 0x40B00000))
        for window in IMAGE_WINDOWS:
            self.assertFalse(overlaps(shm, window), hex(window[0]))

    def test_cta_placement(self):
        v = self.v
        cta = (v['RCAR_ICCOM_CTA_BASE'], v['RCAR_ICCOM_CTA_BASE'] + v['RCAR_ICCOM_CTA_SIZE'])
        self.assertEqual(cta, (0x47FC7000, 0x47FCF000))
        self.assertEqual(cta[0] % 0x1000, 0)
        shm = (v['RCAR_IPC_SHM_BASE'], v['RCAR_IPC_SHM_BASE'] + v['RCAR_IPC_SHM_SIZE'])
        self.assertFalse(overlaps(cta, shm))
        for window in IMAGE_WINDOWS:
            self.assertFalse(overlaps(cta, window), hex(window[0]))

    def test_offsets(self):
        v = self.v
        self.assertEqual(v['RCAR_IPC_CTRL_OFFSET'], 0x0)
        self.assertEqual(v['RCAR_IPC_RSC_OFFSET'], 0x1000)
        self.assertEqual(v['RCAR_IPC_VRING0_OFFSET'], 0x2000)
        self.assertEqual(v['RCAR_IPC_VRING1_OFFSET'], 0x5000)
        self.assertEqual(v['RCAR_IPC_POOL_OFFSET'], 0x8000)
        self.assertEqual(v['RCAR_IPC_USED_END'], 0x48000)
        self.assertLessEqual(v['RCAR_IPC_USED_END'], v['RCAR_IPC_SHM_SIZE'])
        for name in ('RCAR_IPC_RSC_OFFSET', 'RCAR_IPC_VRING0_OFFSET',
                     'RCAR_IPC_VRING1_OFFSET', 'RCAR_IPC_POOL_OFFSET'):
            self.assertEqual(v[name] % 0x1000, 0, name)

    def test_regions_disjoint_and_ordered(self):
        v = self.v
        regions = [
            (v['RCAR_IPC_CTRL_OFFSET'], v['RCAR_IPC_CTRL_SIZE']),
            (v['RCAR_IPC_RSC_OFFSET'], v['RCAR_IPC_RSC_SIZE']),
            (v['RCAR_IPC_VRING0_OFFSET'], v['RCAR_IPC_VRING_SPAN']),
            (v['RCAR_IPC_VRING1_OFFSET'], v['RCAR_IPC_VRING_SPAN']),
            (v['RCAR_IPC_POOL_OFFSET'], v['RCAR_IPC_POOL_SIZE']),
        ]
        for (a, alen), (b, _) in zip(regions, regions[1:]):
            self.assertLessEqual(a + alen, b)

    def test_rpmsg_geometry(self):
        v = self.v
        num, align = v['RCAR_IPC_VRING_NUM'], v['RCAR_IPC_VRING_ALIGN']
        self.assertEqual((num, align, v['RCAR_IPC_BUF_SIZE']), (256, 0x1000, 512))
        span = (vring_size(num, align) + align - 1) & ~(align - 1)
        self.assertEqual(v['RCAR_IPC_VRING_SPAN'], span)
        self.assertEqual(span, 0x3000)
        self.assertEqual(v['RCAR_IPC_POOL_SIZE'], 2 * num * v['RCAR_IPC_BUF_SIZE'])

    def test_control_record(self):
        v = self.v
        self.assertEqual(v['RCAR_IPC_MAGIC'], 0x50494352)
        self.assertEqual(v['RCAR_IPC_MAGIC'].to_bytes(4, 'little'), b'RCIP')
        self.assertEqual(v['RCAR_IPC_VERSION'], 1)
        # magic, version, host_epoch, reserved, mpidr[2], ready[2]
        self.assertEqual(v['sizeof(struct rcar_ipc_ctrl_s)'], 32)


if __name__ == '__main__':
    unittest.main()
