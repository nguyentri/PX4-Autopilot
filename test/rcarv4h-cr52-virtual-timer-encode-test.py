#!/usr/bin/env python3
"""Compile the R-Car V4H CR52 PX4 HRT count/microsecond conversions on the
host and check them against exact integer arithmetic.

The HRT runs on the EL1 virtual timer (CNTVCT, CNTV_CVAL).  count_to_us()
must equal floor(count * 1e6 / CNTFRQ) and us_to_count_ceil() must equal
ceil(us * 1e6 / CNTFRQ) for every value the 64-bit timer can reach, so a
deadline converted to a compare value never fires early and never overflows.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HRT = ROOT / 'platforms/nuttx/src/px4/renesas/rcar/hrt/hrt.c'

# The value the boot firmware writes on R-Car V4H, plus generic rates that
# exercise other remainders.
FREQUENCIES = (16666667, 24000000, 1000000, 19200000, 0xffffffff)
VALUES = (
    0, 1, 2, 999999, 1000000, 1000001, 16666666, 16666667, 16666668,
    123456789, 3600 * 1000000, 0xffffffff, 0x100000000, 0x123456789abc,
    (1 << 53) + 7, (1 << 62) + 12345,
)
US_PER_SEC = 1000000
UINT64_MAX = (1 << 64) - 1

HARNESS = r'''
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static uint32_t g_cntfrq;
%(defines)s
%(functions)s

int main(int argc, char **argv)
{
	g_cntfrq = (uint32_t)strtoul(argv[1], NULL, 0);
	for (int i = 2; i < argc; i++) {
		uint64_t v = strtoull(argv[i], NULL, 0);
		printf("%%" PRIu64 " %%" PRIu64 "\n", count_to_us(v), us_to_count_ceil(v));
	}
	return 0;
}
'''


def extract():
    source = HRT.read_text()
    define = re.search(r'^#define HRT_USEC_PER_SEC\s+\S+$', source, re.M)
    if define is None:
        raise AssertionError('HRT_USEC_PER_SEC missing from hrt.c')
    functions = []
    for name in ('count_to_us', 'us_to_count_ceil'):
        match = re.search(rf'^static inline uint64_t {name}\(uint64_t \w+\)\n\{{.*?\n\}}\n',
                          source, re.M | re.S)
        if match is None:
            raise AssertionError(f'{name}() not found in hrt.c')
        functions.append(match.group(0))
    return define.group(0), '\n'.join(functions)


def exact_count_to_us(count, freq):
    return count * US_PER_SEC // freq


def exact_us_to_count_ceil(us, freq):
    return -(-us * freq // US_PER_SEC)


class VirtualTimerEncodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        define, functions = extract()
        cls.tmp = tempfile.TemporaryDirectory()
        path = Path(cls.tmp.name)
        (path / 'harness.c').write_text(HARNESS % {'defines': define, 'functions': functions})
        cls.exe = path / 'harness'
        subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Werror', '-o', str(cls.exe),
                        str(path / 'harness.c')], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_harness(self, freq, values):
        out = subprocess.run([str(self.exe), str(freq)] + [str(v) for v in values],
                             check=True, capture_output=True, text=True).stdout.split('\n')
        return [tuple(int(x) for x in line.split()) for line in out if line]

    def test_matches_exact_arithmetic(self):
        for freq in FREQUENCIES:
            # Keep inputs where the exact result fits uint64 (the timer wraps
            # after ~35000 years at 16.67 MHz, far past any reachable value).
            values = [v for v in VALUES
                      if exact_us_to_count_ceil(v, freq) <= UINT64_MAX]
            for value, (us, count) in zip(values, self.run_harness(freq, values)):
                with self.subTest(freq=freq, value=value):
                    self.assertEqual(us, exact_count_to_us(value, freq))
                    self.assertEqual(count, exact_us_to_count_ceil(value, freq))

    def test_deadline_never_fires_early(self):
        # A compare value from us_to_count_ceil() converts back to at least
        # the requested microseconds, and one count less is already earlier.
        freq = 16666667
        values = [v for v in VALUES if v < (1 << 60)]
        counts = [c for _, c in self.run_harness(freq, values)]
        back = self.run_harness(freq, counts)
        for us, count, (us_back, _) in zip(values, counts, back):
            with self.subTest(us=us):
                self.assertGreaterEqual(us_back, us)
                if count:
                    self.assertLess((count - 1) * US_PER_SEC, us * freq)


if __name__ == '__main__':
    unittest.main()
