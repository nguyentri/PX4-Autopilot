#!/usr/bin/env python3
"""Run the RZ/V2H HRT driver against a host model of its free-running GTM.

The model implements the GTM free-running comparison mode described in the
RZ/V2H hardware manual: the counter counts up from zero, keeps counting
through a compare match, wraps at 2^32 and raises an edge on CNT == CMP.
Every register access advances the counter, so the driver's arm sequence
races the counter exactly as on hardware.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
DRIVER_SOURCE = DRIVER / "rzv_hrt.c"

HEADERS = {
    "nuttx/config.h": """
#include <stddef.h>
#define FAR
#define CONFIG_RZV_HRT 1
#define CONFIG_RZV_HRT_GTM7 1
#define OK 0
void host_panic(const char *what);
#define VERIFY(x) do { if ((x) < 0) host_panic(#x); } while (0)
""",
    "nuttx/irq.h": """
#ifndef HOST_NUTTX_IRQ_H
#define HOST_NUTTX_IRQ_H
typedef unsigned int irqstate_t;
typedef int (*xcpt_t)(int irq, void *context, void *arg);
irqstate_t enter_critical_section(void);
void leave_critical_section(irqstate_t flags);
int irq_attach(int irq, xcpt_t handler, void *arg);
int irq_detach(int irq);
#define RZV_IRQ_FIRST 32
#define RZV_IRQ_GTM(n) (RZV_IRQ_FIRST + 17 + (n))
#define RZV_IRQ_GTM5 RZV_IRQ_GTM(5)
#define RZV_IRQ_GTM6 RZV_IRQ_GTM(6)
#define RZV_IRQ_GTM7 RZV_IRQ_GTM(7)
#endif
""",
    "nuttx/arch.h": """
void up_enable_irq(int irq);
void up_disable_irq(int irq);
""",
    "arm_internal.h": """
#include <stdint.h>
uint8_t host_getreg8(uintptr_t address);
void host_putreg8(uint8_t value, uintptr_t address);
uint32_t host_getreg32(uintptr_t address);
void host_putreg32(uint32_t value, uintptr_t address);
#define getreg8(a) host_getreg8((uintptr_t)(a))
#define putreg8(v, a) host_putreg8((v), (uintptr_t)(a))
#define getreg32(a) host_getreg32((uintptr_t)(a))
#define putreg32(v, a) host_putreg32((v), (uintptr_t)(a))
""",
    "barriers.h": "#define ARM_DSB() ((void)0)\n",
    "debug.h": "#define tmrerr(...) ((void)0)\n#define tmrinfo(...) ((void)0)\n",
}

HARNESS = r"""
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <nuttx/config.h>
#include <nuttx/irq.h>
#include "hardware/rzv_gtm.h"
#include "hardware/rzv_intc_gic.h"
#include "rzv_hrt.h"

#define CHECK(cond, msg) \
  do { if (!(cond)) { fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, \
                              __LINE__, msg); exit(1); } } while (0)

#define TICKS_PER_US 100u

/* Model of one GTM channel in free-running comparison mode. */

static uint32_t g_cnt;
static uint32_t g_cmp;
static uint8_t  g_ctl;
static bool     g_running;
static bool     g_pending;
static bool     g_enabled;
static unsigned g_critical;
static uint64_t g_model_ticks;      /* wall-clock ticks, counter running or not */
static uint32_t g_access_ticks = 1; /* counter advance per register access */
static unsigned g_tt_writes;
static unsigned g_ts_writes;
static unsigned g_isr_entries;
static xcpt_t   g_handler;

static unsigned g_callbacks;
static uint64_t g_callback_ticks[4096];

static void advance(uint64_t ticks)
{
  while (ticks > 0)
    {
      uint32_t step = ticks > 0x10000000u ? 0x10000000u : (uint32_t)ticks;

      if (g_running)
        {
          /* Edge when the counter becomes equal to CMP during this step. */

          if ((uint32_t)(g_cmp - g_cnt - 1u) < step)
            {
              g_pending = true;
            }

          g_cnt += step;
        }

      /* Real time keeps passing while the counter is stopped. */

      g_model_ticks += step;
      ticks -= step;
    }
}

static bool is_gtm(uintptr_t address, uint32_t offset)
{
  return address == RZV_GTM7_BASE + offset;
}

uint8_t host_getreg8(uintptr_t address)
{
  advance(g_access_ticks);
  if (is_gtm(address, RZV_GTM_OSTMTE_OFFSET))
    {
      return g_running ? GTM_OSTMTE_TE : 0;
    }

  if (is_gtm(address, RZV_GTM_OSTMCTL_OFFSET))
    {
      return g_ctl;
    }

  CHECK(false, "unexpected 8-bit read");
  return 0;
}

void host_putreg8(uint8_t value, uintptr_t address)
{
  advance(g_access_ticks);
  if (is_gtm(address, RZV_GTM_OSTMTT_OFFSET) && (value & GTM_OSTMTT_OSTMTT))
    {
      g_tt_writes++;
      g_running = false;
    }
  else if (is_gtm(address, RZV_GTM_OSTMTS_OFFSET) &&
           (value & GTM_OSTMTS_OSTMTS))
    {
      g_ts_writes++;
      if (!g_running)
        {
          CHECK(g_ctl == GTM_MODE_FREERUN, "started outside free-run mode");
          g_cnt = 0;
          g_running = true;
        }
    }
  else if (is_gtm(address, RZV_GTM_OSTMCTL_OFFSET))
    {
      g_ctl = value;
    }
  else
    {
      CHECK(false, "unexpected 8-bit write");
    }
}

uint32_t host_getreg32(uintptr_t address)
{
  advance(g_access_ticks);
  if (is_gtm(address, RZV_GTM_OSTMCNT_OFFSET))
    {
      return g_cnt;
    }

  if (is_gtm(address, RZV_GTM_OSTMCMP_OFFSET))
    {
      return g_cmp;
    }

  CHECK(false, "unexpected 32-bit read");
  return 0;
}

void host_putreg32(uint32_t value, uintptr_t address)
{
  advance(g_access_ticks);
  if (is_gtm(address, RZV_GTM_OSTMCMP_OFFSET))
    {
      g_cmp = value;
    }
  else if (address == RZV_INTC_GIC_GICD_ICDICPR(RZV_IRQ_GTM7 / 32))
    {
      if (value & (1u << (RZV_IRQ_GTM7 % 32)))
        {
          g_pending = false;
        }
    }
  else
    {
      CHECK(false, "unexpected 32-bit write");
    }
}

/* NuttX and clock services used by the driver. */

void host_panic(const char *what)
{
  fprintf(stderr, "FAIL: VERIFY(%s)\n", what);
  exit(1);
}

irqstate_t enter_critical_section(void)
{
  return g_critical++;
}

void leave_critical_section(irqstate_t flags)
{
  CHECK(g_critical == flags + 1, "unbalanced critical section");
  g_critical = flags;
}

int irq_attach(int irq, xcpt_t handler, void *arg)
{
  (void)arg;
  CHECK(irq == RZV_IRQ_GTM7, "wrong IRQ attached");
  g_handler = handler;
  return 0;
}

int irq_detach(int irq)
{
  (void)irq;
  g_handler = NULL;
  return 0;
}

void up_enable_irq(int irq)
{
  CHECK(irq == RZV_IRQ_GTM7, "wrong IRQ enabled");
  g_enabled = true;
}

void up_disable_irq(int irq)
{
  (void)irq;
  g_enabled = false;
}

void rzv_gic_set_irq_type(int irq, bool edge)
{
  CHECK(irq == RZV_IRQ_GTM7 && edge, "HRT IRQ must be edge triggered");
}

static unsigned g_reset_asserts;

int rzv_clock_enable(uint32_t clk_id)
{
  (void)clk_id;
  return 0;
}

int rzv_clock_disable(uint32_t clk_id)
{
  (void)clk_id;
  return 0;
}

int rzv_module_reset(uint32_t clk_id)
{
  (void)clk_id;
  g_reset_asserts++;
  g_running = false;
  g_cnt = 0;
  g_cmp = 0;
  g_ctl = 0;
  return 0;
}

int rzv_module_unreset(uint32_t clk_id)
{
  (void)clk_id;
  return 0;
}

uint32_t rzv_clock_get_rate(int clock)
{
  (void)clock;
  return 100000000u;
}

/* Deliver a pending interrupt the way the GIC would once interrupts are
 * unmasked.
 */

static void deliver(void)
{
  while (g_pending && g_enabled && g_critical == 0)
    {
      g_pending = false;
      g_isr_entries++;
      g_critical++;
      g_handler(0, NULL, NULL);
      g_critical--;
    }
}

static void run_for(uint64_t ticks, uint32_t slice)
{
  while (ticks > 0)
    {
      uint32_t step = ticks > slice ? slice : (uint32_t)ticks;
      advance(step);
      deliver();
      ticks -= step;
    }
}

static void callback(void *arg)
{
  (void)arg;
  CHECK(g_callbacks < 4096, "callback storm");
  g_callback_ticks[g_callbacks++] = g_model_ticks;
}

static void check_time(const char *msg)
{
  uint64_t now = rzv_hrt_absolute_time();
  uint64_t model_us = g_model_ticks / TICKS_PER_US;

  CHECK(now + 1 >= model_us && now <= model_us + 1, msg);
}

static void start(uint32_t access_ticks)
{
  g_access_ticks = access_ticks;

  /* Inherit a stale running counter and pending edge from a previous
   * image to prove that initialization resets them.
   */

  g_running = true;
  g_cnt = 0xfffff000u;
  g_cmp = 0xfffff010u;
  g_pending = true;

  CHECK(rzv_hrt_initialize() == 0, "initialize failed");
  CHECK(g_reset_asserts == 1, "module reset not pulsed at init");
  CHECK(!g_pending, "stale pending edge survived initialization");
  g_model_ticks = g_cnt;  /* time base: counter value right after start */
  CHECK(g_tt_writes == 1 && g_ts_writes == 1, "init stop/start count");
}

int main(int argc, char **argv)
{
  const char *scenario = argc > 1 ? argv[1] : "";
  unsigned i;

  if (strcmp(scenario, "no-lost-ticks") == 0)
    {
      start(3);
      for (i = 0; i < 20000; i++)
        {
          /* PX4 queue pattern: cancel, arm, rearm before expiry. */

          rzv_hrt_cancel();
          CHECK(rzv_hrt_call_after(50 + (i % 400), callback, NULL) == 0,
                "arm failed");
          CHECK(rzv_hrt_call_after(1 + (i % 7), callback, NULL) == 0,
                "rearm failed");
          run_for(37 + (i % 1000), 13);
          check_time("time drifted under repeated arm/cancel");
          g_callbacks = 0;
        }

      /* Idle across several counter wraps on maintenance compares only. */

      rzv_hrt_cancel();
      run_for(5ull * 0x100000000ull, 0x01000000u);
      check_time("time drifted across counter wraps");
      CHECK(g_tt_writes == 1 && g_ts_writes == 1,
            "counter was stopped or restarted after init");
      return 0;
    }

  if (strcmp(scenario, "deadline") == 0)
    {
      start(2);
      for (i = 0; i < 2000; i++)
        {
          uint32_t delay_us = 1 + (i * 37) % 3000;
          uint64_t armed = g_model_ticks;
          unsigned before = g_callbacks;

          CHECK(rzv_hrt_call_after(delay_us, callback, NULL) == 0,
                "arm failed");
          run_for((uint64_t)delay_us * TICKS_PER_US + 400, 7);
          CHECK(g_callbacks == before + 1, "one-shot did not fire once");
          CHECK(g_callback_ticks[before] >=
                armed + (uint64_t)delay_us * TICKS_PER_US,
                "one-shot fired early");
          CHECK(g_callback_ticks[before] <=
                armed + (uint64_t)delay_us * TICKS_PER_US + 200,
                "one-shot fired late");
          g_callbacks = 0;
        }

      return 0;
    }

  if (strcmp(scenario, "late-arm") == 0)
    {
      /* Slow register path: the first compare lands behind the counter. */

      start(40);
      for (i = 0; i < 200; i++)
        {
          uint64_t armed = g_model_ticks;

          g_callbacks = 0;
          CHECK(rzv_hrt_call_after(1, callback, NULL) == 0, "arm failed");
          run_for(4000, 5);
          CHECK(g_callbacks == 1, "deadline passed during arm was lost");
          CHECK(g_callback_ticks[0] >= armed + TICKS_PER_US,
                "late arm fired early");
        }

      check_time("time drifted with slow register access");
      return 0;
    }

  if (strcmp(scenario, "stale-pending") == 0)
    {
      start(1);

      /* A compare matches while interrupts are masked, then the callout is
       * replaced by a later one before the edge is taken.
       */

      CHECK(rzv_hrt_call_after(1, callback, NULL) == 0, "arm failed");
      g_critical++;
      advance(500);
      CHECK(g_pending, "model did not latch the first match");
      CHECK(rzv_hrt_call_after(1000, callback, NULL) == 0, "rearm failed");
      g_critical--;
      deliver();
      CHECK(g_callbacks == 0, "stale edge ran the replaced callout early");

      /* An edge latched after the arm cleared pending must be rejected by
       * the handler as well.
       */

      g_pending = true;
      deliver();
      CHECK(g_callbacks == 0, "early edge ran the callout");
      run_for(1000 * TICKS_PER_US + 200, 9);
      CHECK(g_callbacks == 1, "armed callout did not fire once");
      return 0;
    }

  if (strcmp(scenario, "periodic") == 0)
    {
      start(2);
      uint64_t first = g_model_ticks;
      CHECK(rzv_hrt_call_every(100, callback, NULL) == 0, "periodic failed");
      run_for(1000ull * 100 * TICKS_PER_US + 50, 23);
      CHECK(g_callbacks == 1000, "periodic count wrong");
      for (i = 0; i < g_callbacks; i++)
        {
          uint64_t due = first + (uint64_t)(i + 1) * 100 * TICKS_PER_US;
          CHECK(g_callback_ticks[i] >= due && g_callback_ticks[i] < due + 100,
                "periodic deadline drifted");
        }

      rzv_hrt_cancel();
      g_callbacks = 0;
      run_for(10000 * TICKS_PER_US, 50);
      CHECK(g_callbacks == 0, "cancelled periodic still fired");
      check_time("time drifted with periodic callouts");
      return 0;
    }

  fprintf(stderr, "unknown scenario %s\n", scenario);
  return 2;
}
"""


class HrtFreeRunningRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="rzv2h-hrt-")
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        for name, text in HEADERS.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        harness = directory / "hrt-harness.c"
        harness.write_text(HARNESS, encoding="utf-8")
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a host C compiler (cc) is required")
        cls.binary = directory / "hrt-runtime"
        result = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-I", str(directory), "-I", str(DRIVER),
             str(harness), str(DRIVER_SOURCE), "-o", str(cls.binary)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise AssertionError(f"host driver compilation failed:\n{result.stderr}")

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.binary), scenario], capture_output=True,
                                text=True, check=False, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_arm_and_cancel_never_lose_counter_ticks(self):
        self.run_scenario("no-lost-ticks")

    def test_one_shot_fires_once_at_its_deadline(self):
        self.run_scenario("deadline")

    def test_deadline_passed_during_arm_is_rearmed(self):
        self.run_scenario("late-arm")

    def test_stale_compare_edge_does_not_run_new_callout(self):
        self.run_scenario("stale-pending")

    def test_periodic_callout_keeps_phase_and_cancels(self):
        self.run_scenario("periodic")

    def test_px4_schedule_cancels_only_an_empty_queue(self):
        source = (ROOT / "platforms/nuttx/src/px4/renesas/rzv/hrt/hrt.c").read_text()
        body = source.split("static void hrt_schedule_locked(void)\n{", 1)[1]
        body = body.split("\n}\n", 1)[0]
        before_arm = body.split("rzv_hrt_call_after(", 1)[0]
        empty_branch = before_arm.split("if (!next || next->deadline == 0) {", 1)
        self.assertEqual(len(empty_branch), 2)
        self.assertNotIn("rzv_hrt_cancel()", empty_branch[0])
        self.assertIn("rzv_hrt_cancel()", empty_branch[1].split("}", 1)[0])


if __name__ == "__main__":
    unittest.main()
