#!/usr/bin/env python3
"""Check the R-Car V4H CR52 ICC_SGI1R encoding (hardware/rcar_intc_gic.h)
against an independent encoder of the GICv3 field layout: TargetList
[15:0], Aff1 [23:16], INTID [27:24], Aff2 [39:32], IRM [40] = 0,
Aff3 [55:48] = 0."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RCAR = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rcar'

# Plausible CR52 MPIDR forms (the SDK notes disagree, so the images
# publish the runtime value): MT/U bits set, Aff0 or Aff1 numbering
MPIDRS = [0x80000000, 0x80000001, 0x80000002, 0x80000100, 0x80000101,
          0xC0000001, 0x80010203, 0x0000000F]
SGIS = [0, 8, 15]

PROBE = r'''
#include <stdint.h>
#include <stdio.h>
#include "hardware/rcar_intc_gic.h"
int main(void)
{
  static const uint32_t mpidr[] = { %s };
  static const int sgi[] = { %s };
  unsigned int i, j;
  for (i = 0; i < sizeof(mpidr) / sizeof(mpidr[0]); i++)
    for (j = 0; j < sizeof(sgi) / sizeof(sgi[0]); j++)
      printf("%%u %%d %%u %%u\n", (unsigned)mpidr[i], sgi[j],
             (unsigned)ICC_SGI1R_LO(sgi[j], mpidr[i]),
             (unsigned)ICC_SGI1R_HI(mpidr[i]));
  printf("max %%d\n", ICC_SGI1R_TARGET_MAX);
  return 0;
}
'''


def reference(sgi, mpidr):
    aff0, aff1, aff2 = mpidr & 0xff, (mpidr >> 8) & 0xff, (mpidr >> 16) & 0xff
    value = (1 << aff0) | (aff1 << 16) | (sgi << 24) | (aff2 << 32)
    return value & 0xffffffff, value >> 32


class SgiEncodeTest(unittest.TestCase):
    def test_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, exe = Path(tmp) / 'probe.c', Path(tmp) / 'probe'
            src.write_text(PROBE % (', '.join(f'{m:#x}u' for m in MPIDRS),
                                    ', '.join(map(str, SGIS))))
            subprocess.run(['cc', '-std=c11', '-Wall', '-Werror', '-I', str(RCAR),
                            str(src), '-o', str(exe)], check=True, timeout=60)
            lines = subprocess.run([str(exe)], check=True, timeout=30,
                                   capture_output=True, text=True).stdout.splitlines()
        self.assertEqual(lines[-1], 'max 15')
        rows = [tuple(int(x) for x in line.split()) for line in lines[:-1]]
        self.assertEqual(len(rows), len(MPIDRS) * len(SGIS))
        for mpidr, sgi, lo, hi in rows:
            with self.subTest(mpidr=hex(mpidr), sgi=sgi):
                self.assertEqual((lo, hi), reference(sgi, mpidr))
                self.assertEqual(hi & ~0xff, 0)          # IRM, RS, Aff3 clear
                self.assertEqual(lo & 0xf0000000, 0)     # reserved [31:28]

    def test_golden(self):
        # SGI 8 to MPIDR Aff1=1/Aff0=0, and to Aff0=1
        self.assertEqual(reference(8, 0x80000100), (0x08010001, 0))
        self.assertEqual(reference(8, 0x80000001), (0x08000002, 0))


if __name__ == '__main__':
    unittest.main()
