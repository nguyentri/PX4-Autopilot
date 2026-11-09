#!/usr/bin/env python3
"""Execute RIIC acquisition and split SPI2 reset with faulted CPG boundaries."""

import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
SPEC = importlib.util.spec_from_file_location(
    "runtime", ROOT / "test/rzv2h-audit-remediation-runtime-test.py")
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def clock_harness(body):
    source = (ARCH / "rzv_clock.c").read_text()
    header = (ARCH / "rzv_clock.h").read_text()
    defines = "\n".join(line for line in header.splitlines()
                        if re.match(r"#define RZV_CPG_(CLK_|BIT\(|DOMAIN\()", line))
    code = RUNTIME.PRE + r'''
#define OK 0
#define CPG_MAX_RETRIES 2
#define CPG_TIMEOUT_RESET_ASSERT 100u
#define CPG_TIMEOUT_RESET_RELEASE 200u
#define CPG_RETRY_DELAY_US 1u
#define RZV_CPG_DUMP_NONE 0u
#define RZV_CPG_RST(n) (0x100u + 4u * (n))
#define RZV_CPG_BUS_1_MSTOP 0x200u
#define RZV_CPG_BUS_3_MSTOP 0x204u
#define clkerr(...) ((void)0)
#define clkinfo(...) ((void)0)
typedef int irqstate_t;
static int depth, fail, enabled, calls, reset_polls, release_polls;
static unsigned channel, writes;
static uintptr_t addresses[64];
static uint32_t values[64], mstop[2];
static irqstate_t enter_critical_section(void) { assert(depth++ == 0); return 0; }
static void leave_critical_section(irqstate_t f) { (void)f; assert(--depth == 0); }
static void up_udelay(unsigned us) { (void)us; assert(depth == 0); }
static uint32_t rzv_cpg_getreg(uintptr_t addr)
{ assert(addr == RZV_CPG_BUS_1_MSTOP || addr == RZV_CPG_BUS_3_MSTOP);
  return mstop[addr == RZV_CPG_BUS_3_MSTOP]; }
static void rzv_cpg_putreg(uint32_t value, uintptr_t addr)
{ assert(depth == 1 && writes < 64); addresses[writes] = addr; values[writes++] = value; }
static void rzv_cpg_mstop_write(uintptr_t addr, uint32_t mask, bool release)
{ assert(depth == 0); ++calls; unsigned i = addr == RZV_CPG_BUS_3_MSTOP;
  assert(addr == RZV_CPG_BUS_1_MSTOP || i);
  if (release) mstop[i] &= ~mask; else mstop[i] |= mask; }
static int rzv_cpg_sci_channel(uint32_t id) { (void)id; return -1; }
static int rzv_cpg_sci_reset_ctrl(int ch, bool reset)
{ (void)ch; (void)reset; assert(0); return -EINVAL; }
static void rzv_cpg_dump_registers(unsigned a,unsigned b,unsigned c,
                                  unsigned d,unsigned e,const char *why)
{ (void)a;(void)b;(void)c;(void)d;(void)e;(void)why; }
static int rzv_cpg_wait_rstmon(uint32_t first,uint32_t count,bool reset,unsigned timeout)
{
  assert(depth == 0);
  unsigned expected = channel == 8 ? 160u : 152u + channel;
  if (channel == 10) { expected = 127; assert(count == 2); }
  else assert(count == 1);
  assert(first == expected);
  assert(timeout == (reset ? CPG_TIMEOUT_RESET_ASSERT : CPG_TIMEOUT_RESET_RELEASE));
  if (reset) ++reset_polls; else ++release_polls;
  return ((!reset && fail == 2) || (reset && fail == 3)) ? -ETIMEDOUT : 0;
}
''' + defines + r'''
static uint32_t expected_id(void)
{ return channel == 8 ? RZV_CPG_CLK_I2C8 : RZV_CPG_CLK_I2C0 + channel; }
static int rzv_clock_enable(uint32_t id)
{ assert(id == expected_id()); ++calls; enabled = 1;
  if (fail == 1) return -ETIMEDOUT;
  rzv_cpg_mstop_write(channel == 8 ? RZV_CPG_BUS_3_MSTOP : RZV_CPG_BUS_1_MSTOP,
                      1u << (channel == 8 ? 13u : channel + 1u), true); return 0; }
static int rzv_clock_disable(uint32_t id)
{ assert(id == expected_id()); ++calls; enabled = 0; return fail == 4 ? -EIO : 0; }
'''
    for name in ("static void rzv_cpg_reset_mapping(",
                 "static int rzv_cpg_spi2_reset_ctrl(",
                 "int rzv_module_reset(", "int rzv_module_unreset("):
        code += RUNTIME.extract(source, name)
    code += "\nstatic bool g_riic_was_stopped[9];\n"
    for name in ("static uint32_t rzv_riic_clock_id(",
                 "static void rzv_riic_restore_mstop(",
                 "int rzv_i2c_module_start(", "int rzv_i2c_module_stop("):
        code += RUNTIME.extract(source, name)
    code += "\nint main(void) {\n" + body + "\nassert(depth == 0); return 0; }\n"
    RUNTIME.run(code)


class ClockLifecycle(unittest.TestCase):
    def test_all_nine_reset_coordinates_and_mstop_preservation(self):
        clock_harness(r'''
  for (channel=0; channel<9; ++channel) {
    for (unsigned stopped=0; stopped<2; ++stopped) {
      mstop[0]=0xa5a50000u; mstop[1]=0x5a5a0000u;
      unsigned index=channel==8, bit=channel==8?13:channel+1;
      mstop[index] |= stopped << bit;
      uint32_t old0=mstop[0], old1=mstop[1]; writes=0;
      fail=0; assert(rzv_i2c_module_start(channel)==0 && enabled);
      assert(!(mstop[index] & (1u<<bit)));
      /* FSP RIIC start order: assert the module reset, then release it. */
      assert(writes==2 && addresses[0]==RZV_CPG_RST(channel==8?10:9));
      assert(addresses[1]==addresses[0]);
      uint32_t reset=1u<<(channel==8?0:channel+8);
      assert(values[0]==(reset<<16));
      assert(values[1]==((reset<<16)|reset));
      assert(rzv_i2c_module_stop(channel)==0 && !enabled);
      assert(mstop[0]==old0 && mstop[1]==old1);
      assert(writes==3 && values[2]==(reset<<16));
    }
  }
  int oldcalls=calls; unsigned oldwrites=writes;
  assert(rzv_i2c_module_start(9)==-EINVAL);
  assert(rzv_i2c_module_start(UINT_MAX)==-EINVAL);
  assert(rzv_i2c_module_stop(9)==-EINVAL);
  assert(calls==oldcalls && writes==oldwrites);
''')

    def test_failed_acquisition_and_teardown_restore_owned_resources(self):
        clock_harness(r'''
  for (channel=0; channel<9; ++channel) {
    for (fail=1; fail<=2; ++fail) {
      mstop[0]=0xffffffffu; mstop[1]=0xffffffffu; writes=0;
      assert(rzv_i2c_module_start(channel)==-ETIMEDOUT && !enabled);
      assert(mstop[0]==0xffffffffu && mstop[1]==0xffffffffu);
      assert(reset_polls>0);
    }
    fail=0; writes=0; assert(rzv_i2c_module_start(channel)==0);
    fail=3; assert(rzv_i2c_module_stop(channel)==-ETIMEDOUT && !enabled);
    fail=0; writes=0; assert(rzv_i2c_module_start(channel)==0);
    fail=4; assert(rzv_i2c_module_stop(channel)==-EIO && !enabled);
  }
''')

    def test_spi2_split_reset_and_release_failure_reassert_both_banks(self):
        clock_harness(r'''
  channel=10; fail=0;
  assert(rzv_module_unreset(RZV_CPG_CLK_SPI2)==0);
  assert(writes==2 && addresses[0]==RZV_CPG_RST(7) && addresses[1]==RZV_CPG_RST(8));
  assert(values[0]==0x80008000u && values[1]==0x00010001u);
  assert(rzv_module_reset(RZV_CPG_CLK_SPI2)==0);
  assert(values[2]==0x80000000u && values[3]==0x00010000u);
  fail=2; writes=0; release_polls=0; reset_polls=0;
  assert(rzv_module_unreset(RZV_CPG_CLK_SPI2)==-ETIMEDOUT);
  assert(release_polls==CPG_MAX_RETRIES+1 && reset_polls==1);
  assert(writes==2*(CPG_MAX_RETRIES+2));
  assert(addresses[writes-2]==RZV_CPG_RST(7) && values[writes-2]==0x80000000u);
  assert(addresses[writes-1]==RZV_CPG_RST(8) && values[writes-1]==0x00010000u);
''')


if __name__ == "__main__":
    unittest.main()
