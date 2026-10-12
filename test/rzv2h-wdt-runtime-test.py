#!/usr/bin/env python3
"""Check production watchdog timeout selection and failure-state preservation."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_wdt.c'


def definition(source, signature):
    start = source.rindex(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


class WatchdogTimeouts(unittest.TestCase):
    def test_supported_boundaries_and_rejected_request_leave_state_intact(self):
        source = SOURCE.read_text()
        defines = '\n'.join(re.findall(r'^#define WDT_(?:MIN|MAX)TIMEOUT[^\n]*(?:\\\n[^\n]*)*',
                                       source, re.M))
        code = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include <limits.h>
#include <assert.h>
#include <string.h>
#define OK 0
#define RZV_CLOCK_OSCCLK_HZ 24000000u
#define wdinfo(...) ((void)0)
#define wdwarn(...) ((void)0)
#define wderr(...) ((void)0)
struct watchdog_lowerhalf_s { const void *ops; };
struct rzv_wdt_priv_s {
  struct watchdog_lowerhalf_s lower;
  uint32_t timeout;
  uint32_t frequency;
  uint8_t tops, cks, channel;
  bool started;
};
'''
        code += defines + '\n'
        code += definition(source, 'static int rzv_wdt_calculate_timeout(')
        code += definition(source, 'static int rzv_wdt_settimeout(')
        code += r'''
int main(void) {
  struct rzv_wdt_priv_s priv = {0};
  const uint32_t supported[] = {1, 10, 1000, 4999, 5000, 5592};
  for (unsigned i = 0; i < sizeof(supported) / sizeof(supported[0]); ++i) {
    assert(rzv_wdt_settimeout(&priv.lower, supported[i]) == OK);
    assert(priv.timeout >= supported[i] && priv.timeout <= 5592);
    if (supported[i] == 5592) {
      assert(priv.cks == 0x8 && priv.tops == 0x3);
    }
  }
  struct rzv_wdt_priv_s before = priv;
  const uint32_t rejected[] = {0, 5593, 60000, UINT32_MAX};
  for (unsigned i = 0; i < sizeof(rejected) / sizeof(rejected[0]); ++i) {
    assert(rzv_wdt_settimeout(&priv.lower, rejected[i]) == -ERANGE);
    assert(memcmp(&before, &priv, sizeof(priv)) == 0);
  }
  assert(rzv_wdt_calculate_timeout(&priv, 5593) == -ERANGE);
  assert(memcmp(&before, &priv, sizeof(priv)) == 0);
  assert(rzv_wdt_settimeout(NULL, 1000) == -EINVAL);
  priv.started = true;
  before = priv;
  assert(rzv_wdt_settimeout(&priv.lower, 1000) == -EBUSY);
  assert(memcmp(&before, &priv, sizeof(priv)) == 0);
  return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='rzv2h-wdt-runtime-') as directory:
            path = Path(directory)
            (path / 'test.c').write_text(code)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            str(path / 'test.c'), '-o', str(path / 'test')], check=True)
            subprocess.run([str(path / 'test')], check=True)


if __name__ == '__main__':
    unittest.main()
