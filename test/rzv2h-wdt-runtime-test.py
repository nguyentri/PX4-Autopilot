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
        wdt_header = (SOURCE.parent / 'hardware' / 'rzv_wdt.h').read_text()
        defines += '\n' + '\n'.join(re.findall(r'^#define WDT_WDTCR_CKS_DIV\d+[^\n]*',
                                                wdt_header, re.M))
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
  /* The longest legal timeout is 16384 cycles at OSCCLK/256 (CKS 5h);
   * the prohibited CKS codes (e.g. 8h, OSCCLK/8192) must never be chosen.
   */
  const uint32_t supported[] = {1, 10, 87, 88, 150, 174};
  assert(WDT_MAXTIMEOUT == 174);
  for (unsigned i = 0; i < sizeof(supported) / sizeof(supported[0]); ++i) {
    assert(rzv_wdt_settimeout(&priv.lower, supported[i]) == OK);
    assert(priv.timeout >= supported[i] && priv.timeout <= 174);
    assert(priv.cks <= 0x5 || priv.cks == 0xf);
    assert(priv.cks != 0x1);
    if (supported[i] == 174) {
      assert(priv.cks == 0x5 && priv.tops == 0x3);
    }
  }
  struct rzv_wdt_priv_s before = priv;
  const uint32_t rejected[] = {0, 175, 5000, 60000, UINT32_MAX};
  for (unsigned i = 0; i < sizeof(rejected) / sizeof(rejected[0]); ++i) {
    assert(rzv_wdt_settimeout(&priv.lower, rejected[i]) == -ERANGE);
    assert(memcmp(&before, &priv, sizeof(priv)) == 0);
  }
  assert(rzv_wdt_calculate_timeout(&priv, 175) == -ERANGE);
  assert(memcmp(&before, &priv, sizeof(priv)) == 0);
  assert(rzv_wdt_settimeout(NULL, 1000) == -EINVAL);
  priv.started = true;
  before = priv;
  assert(rzv_wdt_settimeout(&priv.lower, 100) == -EBUSY);
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



class WatchdogInitialization(unittest.TestCase):
    def test_clock_reset_registration_failures_restore_prestate(self):
        source = SOURCE.read_text()
        arch = SOURCE.parent
        headers = '\n'.join(re.sub(r'^\s*#\s*include[^\n]*$', '',
                                      (arch / 'hardware' / name).read_text(), flags=re.M)
                            for name in ('rzv_wdt.h', 'rzv_cpg.h', 'rzv_sysc.h'))
        code = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include <string.h>
#define OK 0
#define FAR
#define CONFIG_RZV2H_SAMPLE_TEST_API 1
#define CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT 1
#define RZV_WDT_MAX_CHANNELS 4
#define wdinfo(...) ((void)0)
#define wderr(...) ((void)0)
#define RZV_CLOCK_OSCCLK_HZ 24000000u
typedef int irqstate_t;
static irqstate_t enter_critical_section(void) { return 0; }
static void leave_critical_section(irqstate_t flags) { (void)flags; }
typedef void *xcpt_t;
struct watchdog_ops_s {int unused;};
struct watchdog_lowerhalf_s {const void *ops;};
''' + headers + '\n' + '\n'.join(
            re.findall(r'^#define WDT_(?:MIN|MAX)TIMEOUT[^\n]*', source, re.M)) + '\n'
        code += definition(source, 'struct rzv_wdt_clock_state_s\n{') + ';\n'
        code += definition(source, 'struct rzv_wdt_priv_s\n{') + ';\n'
        code += r'''
static struct rzv_wdt_priv_s g_wdt_priv[4];
static struct watchdog_lowerhalf_s g_wdt_dev[4];
static const struct watchdog_ops_s g_wdt_ops={0};
static int failed, inhibited=1, writes, registrations;
static uint32_t gate4, gate5, reset7, mstop3;
static uint32_t getreg32(uintptr_t address)
{
 if(address==RZV_SYSC_SYS_WDT0_CTRL) return inhibited?SYS_WDT_CTRL_BP_HALTED:0;
 if(address==RZV_CPG_CLKON(4)) return gate4;
 if(address==RZV_CPG_CLKON(5)) return gate5;
 if(address==RZV_CPG_RST(7)) return reset7;
 if(address==RZV_CPG_BUS_3_MSTOP) return mstop3;
 if(address==RZV_CPG_CLKMON(RZV_CPG_CLKMON_WDT_M))
  return failed==1?0:RZV_CPG_CLKMON_WDT_CLKP_BIT(0)|RZV_CPG_CLKMON_WDT_LOCO_BIT(0);
 if(address==RZV_CPG_RSTMON(RZV_CPG_RSTMON_WDT_M))
  return failed==2?RZV_CPG_RSTMON_WDT_BIT(0):0;
 assert(0);return 0;
}
static void putreg32(uint32_t value,uintptr_t address)
{
 uint32_t *reg=address==RZV_CPG_CLKON(4)?&gate4:address==RZV_CPG_CLKON(5)?&gate5:address==RZV_CPG_RST(7)?&reset7:address==RZV_CPG_BUS_3_MSTOP?&mstop3:NULL;
 assert(reg);uint32_t mask=value>>16;*reg=(*reg&~mask)|(value&mask);writes++;
}
static int rzv_wdt_calculate_timeout(struct rzv_wdt_priv_s *p,uint32_t timeout)
{(void)p;(void)timeout;return 0;}
static void *watchdog_register(const char *path,struct watchdog_lowerhalf_s *lower)
{(void)path;(void)lower;registrations++;return failed==3?NULL:lower;}
'''
        for signature in ('static uintptr_t rzv_wdt_sysc_ctrl(',
                          'static void rzv_wdt_clock_restore(',
                          'static int rzv_wdt_clock_enable(',
                          'int rzv_wdt_initialize('):
            code += definition(source, signature)
        code += r'''
int main(void)
{
 inhibited=0;assert(rzv_wdt_initialize("/dev/watchdog0",0)==-EBUSY && !writes && !registrations);
 inhibited=1;
 for(failed=1;failed<=3;failed++)
 {
  gate4=1;gate5=2;reset7=4;mstop3=0x408;writes=0;registrations=0;
  assert(rzv_wdt_initialize("/dev/watchdog0",0)==(failed==3?-EIO:-ETIMEDOUT));
  assert(gate4==1 && gate5==2 && reset7==4 && mstop3==0x408 && !g_wdt_priv[0].registered);
  assert(registrations==(failed==3));
 }
 failed=0;mstop3=0x408;assert(rzv_wdt_initialize("/dev/watchdog0",0)==0);
 assert(mstop3==0x008);
 assert(g_wdt_priv[0].registered && !g_wdt_priv[0].started);
 int before=writes;assert(rzv_wdt_initialize("/dev/watchdog0",0)==-EALREADY && writes==before);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'test.c').write_text(code)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',
                            str(path/'test.c'),'-o',str(path/'test')],check=True)
            subprocess.run([str(path/'test')],check=True)

if __name__ == '__main__':
    unittest.main()
