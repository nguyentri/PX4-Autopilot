#!/usr/bin/env python3
"""Run the boot-time tick calibration against simulated GTM and tick counters.

rzv_timer_calibrate.c is compiled unchanged for the CR8 build (32-bit private
timer) and the CM33 build (24-bit SysTick) with stub headers. Every register
read advances a simulated clock, so the counters move at chosen true rates.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'

# One header carries every stub the source needs; the real include names
# all point at it.
STUBS = r'''
#pragma once
#include <stdint.h>
#include <stdio.h>
typedef unsigned irqstate_t;
#define tmrwarn(...) printf(__VA_ARGS__)
#define tmrinfo(...) printf(__VA_ARGS__)

enum { RZV_CLOCK_P1CLK = 1 };
#define RZV_CLOCK_P1CLK_HZ 100000000u
#define RZV_CPG_CLK_GTM5 5
#define RZV_CPG_CLK_GTM6 6
#define RZV_CPG_CLK_GTM7 7
#define RZV_GTM5_BASE 0x5000u
#define RZV_GTM6_BASE 0x6000u
#define RZV_GTM7_BASE 0x7000u
#define RZV_GTM_OSTMCMP_OFFSET 0x00
#define RZV_GTM_OSTMCNT_OFFSET 0x04
#define RZV_GTM_OSTMTE_OFFSET 0x10
#define RZV_GTM_OSTMTS_OFFSET 0x14
#define RZV_GTM_OSTMTT_OFFSET 0x18
#define RZV_GTM_OSTMCTL_OFFSET 0x20
#define GTM_OSTMCMP_MASK 0xffffffffu
#define GTM_OSTMTE_TE 1
#define GTM_OSTMTS_OSTMTS 1
#define GTM_OSTMTT_OSTMTT 1
#define GTM_MODE_FREERUN 2

#define RZV_PRIVATE_TIMER_PTLR 0x100u
#define RZV_PRIVATE_TIMER_PTCR 0x104u
#define RZV_PRIVATE_TIMER_PTCTLR 0x108u
#define RZV_PRIVATE_TIMER_PTISR 0x10cu
#define PRIVATE_TIMER_PTLR_MASK 0xffffffffu
#define PRIVATE_TIMER_PTCTLR_TE 1u
#define PRIVATE_TIMER_PTISR_CLR 1u

#define NVIC_SYSTICK_CTRL 0x200u
#define NVIC_SYSTICK_RELOAD 0x204u
#define NVIC_SYSTICK_CURRENT 0x208u
#define NVIC_SYSTICK_RELOAD_MASK 0x00ffffffu
#define NVIC_SYSTICK_CTRL_ENABLE 1u
#define NVIC_SYSTICK_CTRL_CLKSOURCE 4u

uint32_t getreg32(uint32_t addr);
uint8_t getreg8(uint32_t addr);
void putreg32(uint32_t v, uint32_t addr);
void putreg8(uint8_t v, uint32_t addr);
irqstate_t up_irq_save(void);
void up_irq_restore(irqstate_t f);
uint32_t rzv_clock_get_rate(int clk);
int rzv_clock_enable(int clk);
int rzv_clock_disable(int clk);
int rzv_module_reset(int clk);
int rzv_module_unreset(int clk);
'''

HEADERS = ['nuttx/config.h', 'debug.h', 'nuttx/arch.h', 'nuttx/irq.h',
           'arm_internal.h', 'rzv_clock.h', 'hardware/rzv_gtm.h',
           'hardware/rzv_private_timer.h', 'nvic.h']

# Simulated hardware: time in picoseconds, each register read costs 40 ns.
# GTM counts at 100 MHz; the local counter at local_hz, down from its load.
HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "stubs.h"
uint32_t rzv_timer_calibrate_tickclk(uint32_t nominal_hz);

static uint64_t now_ps, gtm_t0, local_t0;
static uint64_t local_hz, gtm_hz = 100000000u;
static uint32_t local_load, local_mask;
static int gtm_on, local_on, gtm_stall, gtm_resets, gtm_gated, irq_depth;

static uint64_t counts(uint64_t hz, uint64_t t0)
{
  return (uint64_t)(((unsigned __int128)(now_ps - t0) * hz) / 1000000000000u);
}

static uint32_t local_value(void)
{
  if (!local_on)
    {
      return local_load;
    }

  /* Free-running down-counter that reloads from its load at zero. */

  uint64_t period = (uint64_t)local_load + 1;
  return (uint32_t)(local_load - (counts(local_hz, local_t0) % period));
}

uint32_t getreg32(uint32_t addr)
{
  now_ps += 40000;
  if ((addr & 0xff) == RZV_GTM_OSTMCNT_OFFSET && addr >= 0x5000)
    {
      return gtm_on && !gtm_stall ? (uint32_t)counts(gtm_hz, gtm_t0) : 0;
    }

  if (addr == RZV_PRIVATE_TIMER_PTCR || addr == NVIC_SYSTICK_CURRENT)
    {
      return local_value() & local_mask;
    }

  return 0;
}

uint8_t getreg8(uint32_t addr)
{
  now_ps += 40000;
  return (addr & 0xff) == RZV_GTM_OSTMTE_OFFSET ? (uint8_t)gtm_on : 0;
}

void putreg8(uint8_t v, uint32_t addr)
{
  if ((addr & 0xff) == RZV_GTM_OSTMTS_OFFSET && v)
    {
      gtm_on = 1;
      gtm_t0 = now_ps;
    }
  else if ((addr & 0xff) == RZV_GTM_OSTMTT_OFFSET && v)
    {
      gtm_on = 0;
    }
}

void putreg32(uint32_t v, uint32_t addr)
{
  if (addr == RZV_PRIVATE_TIMER_PTLR || addr == NVIC_SYSTICK_RELOAD)
    {
      local_load = v;
    }
  else if (addr == RZV_PRIVATE_TIMER_PTCTLR || addr == NVIC_SYSTICK_CTRL)
    {
      local_on = v != 0;
      local_t0 = now_ps;
    }
}

irqstate_t up_irq_save(void) { irq_depth++; return 0; }
void up_irq_restore(irqstate_t f) { (void)f; irq_depth--; }
uint32_t rzv_clock_get_rate(int clk) { (void)clk; return (uint32_t)gtm_hz; }
int rzv_clock_enable(int clk) { (void)clk; gtm_gated = 0; return 0; }
int rzv_clock_disable(int clk) { (void)clk; gtm_gated = 1; return 0; }
int rzv_module_reset(int clk) { (void)clk; gtm_resets++; return 0; }
int rzv_module_unreset(int clk) { (void)clk; return 0; }

static uint32_t run(uint32_t nominal, uint64_t true_hz)
{
  local_hz = true_hz;
  gtm_on = local_on = 0;
  return rzv_timer_calibrate_tickclk(nominal);
}

int main(void)
{
  uint32_t got;
  local_mask = MASK;

  /* Spread-spectrum offset like the RDK PLLDTY: about 1.1 % slow. */

  got = run(200000000u, 197750000u);
  printf("measured %u\n", got);
  assert(got > 197750000u - 200 && got < 197750000u + 200);
  assert(!gtm_on && !local_on && gtm_gated && irq_depth == 0);

  /* A rate at nominal is returned unchanged within resolution. */

  got = run(200000000u, 200000000u);
  assert(got > 200000000u - 200 && got < 200000000u + 200);

  /* More than 5 % away is a wrong clock tree: keep nominal. */

  assert(run(200000000u, 180000000u) == 200000000u);

  /* A GTM that never counts ends on the guard and keeps nominal. */

  gtm_stall = 1;
  assert(run(200000000u, 197750000u) == 200000000u);
  assert(!gtm_on && gtm_gated && irq_depth == 0);
  gtm_stall = 0;
  return 0;
}
'''


def build_and_run(defines):
    with tempfile.TemporaryDirectory(prefix='rzv2h-tick-cal-') as directory:
        path = Path(directory)
        (path / 'stubs.h').write_text(STUBS)
        for name in HEADERS:
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('#pragma once\n#include "%s/stubs.h"\n' % path)
        shutil.copy(ARCH / 'rzv_timer_calibrate.c', path)
        shutil.copy(ARCH / 'rzv_timer_calibrate.h', path)
        (path / 'harness.c').write_text(HARNESS)
        flags = ['-D%s' % d for d in defines]
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-I', str(path), *flags,
                        str(path / 'rzv_timer_calibrate.c'),
                        str(path / 'harness.c'), '-o', str(path / 'test')],
                       check=True)
        return subprocess.run([str(path / 'test')], check=True,
                              capture_output=True, text=True).stdout


class TickCalibration(unittest.TestCase):
    def test_cr8_private_timer_measures_spread_spectrum_offset(self):
        build_and_run(['CONFIG_RZV_TICK_CALIBRATE=1',
                       'CONFIG_RZV_TICK_CALIBRATE_MS=20',
                       'MASK=0xffffffffu'])

    def test_cm33_systick_survives_24_bit_wraps(self):
        # 200 ms at about 200 MHz wraps the 24-bit SysTick twice.
        build_and_run(['CONFIG_RZV_TICK_CALIBRATE=1',
                       'CONFIG_RZV_TICK_CALIBRATE_MS=200',
                       'CONFIG_RZV2H_BUILD_CM33=1',
                       'MASK=0x00ffffffu'])

    def test_reference_channel_matches_hrt_owner(self):
        source = (ARCH / 'rzv_timer_calibrate.c').read_text()
        self.assertIn('defined(CONFIG_RZV_HRT_GTM5) || \\\n'
                      '    (!defined(CONFIG_RZV_HRT) && '
                      'defined(CONFIG_RZV2H_BUILD_CM33))', source)
        self.assertIn('defined(CONFIG_RZV_HRT_GTM6) || \\\n'
                      '      (!defined(CONFIG_RZV_HRT) && '
                      'defined(CONFIG_RZV2H_BUILD_CR8_1))', source)


if __name__ == '__main__':
    unittest.main()
