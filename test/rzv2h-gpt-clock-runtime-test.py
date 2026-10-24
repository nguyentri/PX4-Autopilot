#!/usr/bin/env python3
"""Execute production GPT unit clock lifecycle with faulted CPG boundaries.

The source functions, unit state and GPT mapping macros are extracted unchanged.
Host mutex/critical-section shims and CPG register/monitor boundaries isolate
the common clock code. These checks do not qualify physical CPG behavior or
cross-core exclusion.
"""

import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
SPEC = importlib.util.spec_from_file_location(
    "gpt_clock_extract", ROOT / "test/rzv2h-wdt-runtime-test.py")
EXTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTRACT)

PREAMBLE = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#define OK 0
#define CPG_MAX_RETRIES 2
#define CPG_RETRY_DELAY_US 10u
#define CPG_TIMEOUT_CLOCK_ENABLE 101u
#define CPG_TIMEOUT_CLOCK_DISABLE 102u
#define CPG_TIMEOUT_RESET_RELEASE 103u
#define CPG_TIMEOUT_RESET_ASSERT 104u
#define RZV_CPG_CLKON(n) (0x100u + 4u * (n))
#define RZV_CPG_CLKMON(n) (0x200u + 4u * (n))
#define RZV_CPG_RST(n) (0x300u + 4u * (n))
#define RZV_CPG_RSTMON(n) (0x400u + 4u * (n))
#define RZV_CPG_BUS_6_MSTOP 0x500u
#define clkerr(...) ((void)0)
typedef pthread_mutex_t mutex_t;
#define NXMUTEX_INITIALIZER PTHREAD_MUTEX_INITIALIZER
typedef unsigned int irqstate_t;
'''

BOUNDARIES = r'''
enum { CLOCK_ENABLE = 1, RESET_RELEASE = 2 };
/* Independent oracle coordinates, rather than the production mapping macros. */
static const uint32_t clock_bits[2] = { 0x2u, 0x4u };
static const uint32_t clock_mon_bits[2] = { 0x20000u, 0x40000u };
static const uint32_t reset_bits[2] = { 0x600u, 0x1800u };
static const uint32_t reset_mon_bits[2] = { 0xc00u, 0x3000u };
static const uint32_t stop_bits[2] = { 0x800u, 0x1000u };
static _Atomic uint32_t clkon = 0x4000u, reset = 0x8u;
static _Atomic uint32_t mstop = 0x1880u;
static atomic_uint reads, writes, delays, restore_calls;
static atomic_uint clock_on[2], clock_off[2], release_waits[2], assert_waits[2];
static atomic_uint restore_set[2], restore_clear[2];
static atomic_uint lock_attempts[2], lock_acquired[2];
static atomic_int failure[2];
static int cleanup_error;
static _Thread_local unsigned critical_depth;
static _Thread_local bool in_isr;
static _Thread_local int lock_error;
static pthread_mutex_t critical = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t gate = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static int hold_stage;
static unsigned hold_unit;
static bool held, resume_monitor;

static void signal_change(void)
{
  assert(pthread_cond_broadcast(&changed) == 0);
}

static irqstate_t enter_critical_section(void)
{
  assert(critical_depth == 0);
  assert(pthread_mutex_lock(&critical) == 0);
  critical_depth = 1;
  return 0;
}

static void leave_critical_section(irqstate_t flags)
{
  assert(flags == 0 && critical_depth == 1);
  critical_depth = 0;
  assert(pthread_mutex_unlock(&critical) == 0);
}

static bool up_interrupt_context(void) { return in_isr; }

static int nxmutex_lock(mutex_t *lock)
{
  assert(critical_depth == 0 && !in_isr);
  unsigned unit = lock == &g_rzv_gpt_unit_lock[0] ? 0u : 1u;
  assert(lock == &g_rzv_gpt_unit_lock[unit]);
  assert(pthread_mutex_lock(&gate) == 0);
  ++lock_attempts[unit];
  signal_change();
  assert(pthread_mutex_unlock(&gate) == 0);
  if (lock_error) return lock_error;
  assert(pthread_mutex_lock(lock) == 0);
  ++lock_acquired[unit];
  return 0;
}

static int nxmutex_unlock(mutex_t *lock)
{
  assert(critical_depth == 0);
  assert(pthread_mutex_unlock(lock) == 0);
  return 0;
}

static void up_udelay(unsigned delay)
{
  assert(critical_depth == 0 && delay >= CPG_RETRY_DELAY_US);
  ++delays;
}

static unsigned mapped_unit(uint32_t mask, const uint32_t bits[2])
{
  assert(mask == bits[0] || mask == bits[1]);
  return mask == bits[1];
}

static uint32_t rzv_cpg_getreg(uintptr_t address)
{
  ++reads;
  if (address == RZV_CPG_BUS_6_MSTOP) return mstop;
  if (address == RZV_CPG_CLKON(3)) return clkon;
  assert(address == RZV_CPG_RST(5));
  return reset;
}

static void rzv_cpg_putreg(uint32_t value, uintptr_t address)
{
  assert(critical_depth == 1);
  uint32_t mask = value >> 16;
  uint32_t data = value & 0xffffu;
  assert((data & ~mask) == 0);
  _Atomic uint32_t *reg;
  if (address == RZV_CPG_CLKON(3))
    {
      (void)mapped_unit(mask, clock_bits);
      reg = &clkon;
    }
  else if (address == RZV_CPG_RST(5))
    {
      (void)mapped_unit(mask, reset_bits);
      reg = &reset;
    }
  else
    {
      assert(address == RZV_CPG_BUS_6_MSTOP);
      (void)mapped_unit(mask, stop_bits);
      reg = &mstop;
    }
  *reg = (*reg & ~mask) | data;
  ++writes;
}

static void rzv_cpg_mstop_write(uintptr_t address, uint32_t mask, bool release)
{
  assert(critical_depth == 0 && address == RZV_CPG_BUS_6_MSTOP);
  ++restore_calls;
  irqstate_t flags = enter_critical_section();
  rzv_cpg_putreg((mask << 16) | (release ? 0u : mask), address);
  leave_critical_section(flags);
}

static int rzv_cpg_wait_bit(uintptr_t address, uint32_t mask, bool set,
                            unsigned timeout)
{
  assert(critical_depth == 0 && !in_isr);
  unsigned unit;
  int stage = 0;
  bool restoring = false;
  if (address == RZV_CPG_CLKMON(1))
    {
      unit = mapped_unit(mask, clock_mon_bits);
      assert(timeout == (set ? CPG_TIMEOUT_CLOCK_ENABLE : CPG_TIMEOUT_CLOCK_DISABLE));
      assert(((clkon & clock_bits[unit]) != 0) == set);
      if (set) { ++clock_on[unit]; stage = CLOCK_ENABLE; }
      else ++clock_off[unit];
      restoring = restore_calls != 0;
    }
  else
    {
      assert(address == RZV_CPG_RSTMON(2));
      if (mask == reset_mon_bits[0] || mask == reset_mon_bits[1])
        {
          unit = mapped_unit(mask, reset_mon_bits);
          assert(!set && timeout == CPG_TIMEOUT_RESET_RELEASE);
          assert((reset & reset_bits[unit]) == reset_bits[unit]);
          ++release_waits[unit];
          stage = RESET_RELEASE;
        }
      else
        {
          assert(mask == 0x400u || mask == 0x800u || mask == 0x1000u || mask == 0x2000u);
          unit = mask >= 0x1000u;
          assert(timeout == CPG_TIMEOUT_RESET_ASSERT);
          assert(((reset & (mask >> 1)) == 0) == set);
          ++assert_waits[unit];
          if (set) ++restore_set[unit]; else ++restore_clear[unit];
          restoring = true;
        }
    }

  /* The production code may publish only after the final monitor succeeds. */
  irqstate_t flags = enter_critical_section();
  assert(!g_rzv_gpt_unit_ready[unit] && g_rzv_gpt_unit_users[unit] == 0);
  leave_critical_section(flags);
  assert(pthread_mutex_lock(&gate) == 0);
  if (hold_stage == stage && hold_unit == unit && stage != 0)
    {
      held = true;
      signal_change();
      while (!resume_monitor) assert(pthread_cond_wait(&changed, &gate) == 0);
    }
  assert(pthread_mutex_unlock(&gate) == 0);
  if (restoring && cleanup_error) return cleanup_error;
  return failure[unit] == stage && stage != 0 ? -ETIMEDOUT : 0;
}

static unsigned activity(void)
{
  return reads + writes + delays + restore_calls + clock_on[0] + clock_on[1] +
         clock_off[0] + clock_off[1] + release_waits[0] + release_waits[1] +
         assert_waits[0] + assert_waits[1];
}
'''

SCENARIOS = r'''
static void lifecycle(void)
{
  for (unsigned channel = 0; channel < 16; ++channel)
    assert(rzv_gpt_module_start(channel) == 0);
  assert(g_rzv_gpt_unit_users[0] == 8 && g_rzv_gpt_unit_users[1] == 8);
  assert(clock_on[0] == 1 && clock_on[1] == 1);
  assert(release_waits[0] == 1 && release_waits[1] == 1);
  assert(clkon == 0x4006u && reset == 0x1e08u && mstop == 0x80u);
  unsigned previous = activity();
  for (unsigned channel = 0; channel < 16; ++channel)
    {
      assert(rzv_gpt_module_start(channel) == 0);
      assert(rzv_gpt_module_stop(channel) == 0);
      assert(rzv_gpt_module_stop(channel) == 0);
    }
  assert(g_rzv_gpt_unit_users[0] == 0 && g_rzv_gpt_unit_users[1] == 0);
  assert(g_rzv_gpt_unit_ready[0] && g_rzv_gpt_unit_ready[1]);
  assert(activity() == previous);
  assert(rzv_gpt_module_stop(0) == -EINVAL && rzv_gpt_module_stop(15) == -EINVAL);
  assert(rzv_gpt_module_start(7) == 0 && rzv_gpt_module_start(8) == 0);
  assert(rzv_gpt_module_stop(7) == 0 && rzv_gpt_module_stop(8) == 0);
  assert(activity() == previous && clock_off[0] == 0 && clock_off[1] == 0);
}

static void guards(void)
{
  const unsigned invalid[] = { 16u, 17u, UINT_MAX };
  for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i)
    {
      assert(rzv_gpt_module_start(invalid[i]) == -EINVAL);
      assert(rzv_gpt_module_stop(invalid[i]) == -EINVAL);
    }
  assert(rzv_gpt_module_stop(0) == -EINVAL && rzv_gpt_module_stop(15) == -EINVAL);
  in_isr = true;
  assert(rzv_gpt_module_start(0) == -EPERM);
  assert(rzv_gpt_module_start(15) == -EPERM);
  in_isr = false;
  assert(activity() == 0 && lock_attempts[0] == 0 && lock_attempts[1] == 0);
  lock_error = -EINTR;
  assert(rzv_gpt_module_start(0) == -EINTR && rzv_gpt_module_start(15) == -EINTR);
  lock_error = 0;
  assert(activity() == 0 && !g_rzv_gpt_unit_ready[0] && !g_rzv_gpt_unit_ready[1]);
  assert(g_rzv_gpt_unit_users[0] == 0 && g_rzv_gpt_unit_users[1] == 0);
  assert(rzv_gpt_module_start(0) == 0);
  unsigned previous = activity(), attempts = lock_attempts[0];
  in_isr = true;
  assert(rzv_gpt_module_start(7) == -EPERM);
  in_isr = false;
  assert(activity() == previous && lock_attempts[0] == attempts);
}

static void overflow(void)
{
  for (unsigned unit = 0; unit < 2; ++unit)
    {
      assert(rzv_gpt_module_start(unit * 8u) == 0);
      unsigned previous = activity();
      for (unsigned count = 1; count < UINT16_MAX; ++count)
        assert(rzv_gpt_module_start(unit * 8u + 7u) == 0);
      assert(g_rzv_gpt_unit_users[unit] == UINT16_MAX);
      assert(rzv_gpt_module_start(unit * 8u) == -EOVERFLOW);
      assert(g_rzv_gpt_unit_users[unit] == UINT16_MAX && activity() == previous);
      assert(rzv_gpt_module_stop(unit * 8u) == 0);
      assert(rzv_gpt_module_start(unit * 8u) == 0);
      assert(g_rzv_gpt_unit_users[unit] == UINT16_MAX && activity() == previous);
    }
}

static void failed_start(unsigned unit, int stage, bool initially_stopped,
                         bool initially_enabled, unsigned reset_state,
                         bool fail_cleanup)
{
  /* A live sibling unit must survive failure/rollback of the selected unit. */
  assert(rzv_gpt_module_start((unit ^ 1u) * 8u) == 0);
  if (!initially_stopped) mstop &= ~stop_bits[unit];
  if (initially_enabled) clkon |= clock_bits[unit];
  const uint32_t reset_low[2] = { 0x200u, 0x800u };
  reset = (reset & ~reset_bits[unit]) | (reset_state * reset_low[unit]);
  uint32_t original_stop = mstop, original_clock = clkon, original_reset = reset;
  failure[unit] = stage;
  cleanup_error = fail_cleanup ? -EIO : 0;
  assert(rzv_gpt_module_start(unit * 8u + 3u) == -ETIMEDOUT);
  assert(!g_rzv_gpt_unit_ready[unit] && g_rzv_gpt_unit_users[unit] == 0);
  assert(mstop == original_stop && clkon == original_clock && reset == original_reset);
  unsigned acquire_attempts = stage == CLOCK_ENABLE ? CPG_MAX_RETRIES + 1u : 1u;
  unsigned restore_attempts = fail_cleanup || (initially_enabled && stage == CLOCK_ENABLE)
                              ? CPG_MAX_RETRIES + 1u : 1u;
  assert(clock_on[unit] == acquire_attempts + (initially_enabled ? restore_attempts : 0u));
  assert(release_waits[unit] == (stage == RESET_RELEASE ? CPG_MAX_RETRIES + 1u : 0u));
  assert(clock_off[unit] == (initially_enabled ? 0u : restore_attempts));
  unsigned released_bits = (reset_state & 1u) + ((reset_state >> 1u) & 1u);
  assert(assert_waits[unit] == 2 && restore_calls == 1);
  assert(restore_clear[unit] == released_bits && restore_set[unit] == 2u - released_bits);
  assert(delays == CPG_MAX_RETRIES + restore_attempts - 1u);
  assert(rzv_gpt_module_stop(unit * 8u) == -EINVAL);
  unsigned before_on = clock_on[unit], before_release = release_waits[unit];
  failure[unit] = 0;
  cleanup_error = 0;
  assert(rzv_gpt_module_start(unit * 8u + 7u) == 0);
  assert(clock_on[unit] == before_on + 1 && release_waits[unit] == before_release + 1);
  assert(g_rzv_gpt_unit_ready[unit] && g_rzv_gpt_unit_users[unit] == 1);
  assert((mstop & stop_bits[unit]) == 0 && (clkon & clock_bits[unit]));
  assert((reset & reset_bits[unit]) == reset_bits[unit]);
  assert((mstop & ~stop_bits[unit]) == (original_stop & ~stop_bits[unit]));
  assert(g_rzv_gpt_unit_ready[unit ^ 1u] && g_rzv_gpt_unit_users[unit ^ 1u] == 1);
  assert(clock_on[unit ^ 1u] == 1 && release_waits[unit ^ 1u] == 1);
  assert(clock_off[unit ^ 1u] == 0 && assert_waits[unit ^ 1u] == 0);
  unsigned previous = activity();
  assert(rzv_gpt_module_stop(unit * 8u + 7u) == 0);
  assert(rzv_gpt_module_start(unit * 8u) == 0 && activity() == previous);
}

struct starter { unsigned channel; atomic_bool done; int result; };

static void *start_task(void *argument)
{
  struct starter *starter = argument;
  starter->result = rzv_gpt_module_start(starter->channel);
  assert(pthread_mutex_lock(&gate) == 0);
  starter->done = true;
  signal_change();
  assert(pthread_mutex_unlock(&gate) == 0);
  return NULL;
}

static struct timespec deadline(void)
{
  struct timespec result;
  assert(clock_gettime(CLOCK_REALTIME, &result) == 0);
  result.tv_sec += 5;
  return result;
}

static void concurrent_starters(int stage)
{
  pthread_t first, sibling, other;
  struct starter a = { .channel = 0 }, b = { .channel = 7 }, c = { .channel = 8 };
  hold_stage = stage;
  hold_unit = 0;
  assert(pthread_create(&first, NULL, start_task, &a) == 0);
  assert(pthread_mutex_lock(&gate) == 0);
  struct timespec end = deadline();
  while (!held) assert(pthread_cond_timedwait(&changed, &gate, &end) == 0);
  assert(pthread_mutex_unlock(&gate) == 0);
  assert(pthread_create(&sibling, NULL, start_task, &b) == 0);
  assert(pthread_mutex_lock(&gate) == 0);
  while (lock_attempts[0] != 2) assert(pthread_cond_timedwait(&changed, &gate, &end) == 0);
  assert(!a.done && !b.done && lock_acquired[0] == 1);
  assert(pthread_mutex_unlock(&gate) == 0);
  irqstate_t flags = enter_critical_section();
  assert(!g_rzv_gpt_unit_ready[0] && g_rzv_gpt_unit_users[0] == 0);
  leave_critical_section(flags);
  assert(rzv_gpt_module_stop(7) == -EINVAL);
  assert(pthread_create(&other, NULL, start_task, &c) == 0);
  assert(pthread_mutex_lock(&gate) == 0);
  while (!c.done) assert(pthread_cond_timedwait(&changed, &gate, &end) == 0);
  assert(!a.done && !b.done && c.result == 0);
  flags = enter_critical_section();
  assert(!g_rzv_gpt_unit_ready[0] && g_rzv_gpt_unit_users[0] == 0);
  assert(g_rzv_gpt_unit_ready[1] && g_rzv_gpt_unit_users[1] == 1);
  leave_critical_section(flags);
  resume_monitor = true;
  signal_change();
  assert(pthread_mutex_unlock(&gate) == 0);
  assert(pthread_join(first, NULL) == 0 && pthread_join(sibling, NULL) == 0);
  assert(pthread_join(other, NULL) == 0);
  assert(a.result == 0 && b.result == 0);
  assert(g_rzv_gpt_unit_users[0] == 2 && g_rzv_gpt_unit_users[1] == 1);
  assert(g_rzv_gpt_unit_ready[0] && g_rzv_gpt_unit_ready[1]);
  assert(clock_on[0] == 1 && clock_on[1] == 1);
  assert(release_waits[0] == 1 && release_waits[1] == 1);
  assert(clkon == 0x4006u && reset == 0x1e08u && mstop == 0x80u);
  unsigned previous = activity();
  assert(rzv_gpt_module_stop(0) == 0 && rzv_gpt_module_stop(7) == 0);
  assert(rzv_gpt_module_stop(8) == 0 && activity() == previous);
}

int main(int argc, char **argv)
{
  assert(argc == 2);
  if (!strcmp(argv[1], "lifecycle")) lifecycle();
  else if (!strcmp(argv[1], "guards")) guards();
  else if (!strcmp(argv[1], "overflow")) overflow();
  else if (!strcmp(argv[1], "concurrent-clock")) concurrent_starters(CLOCK_ENABLE);
  else if (!strcmp(argv[1], "concurrent-release")) concurrent_starters(RESET_RELEASE);
  else
    {
      unsigned unit, stage, stopped, enabled, inherited_reset, fail_cleanup;
      assert(sscanf(argv[1], "failure-%u-%u-%u-%u-%u-%u", &unit, &stage, &stopped,
                    &enabled, &inherited_reset, &fail_cleanup) == 6);
      assert(unit < 2 && (stage == CLOCK_ENABLE || stage == RESET_RELEASE) && stopped < 2);
      assert(enabled < 2 && inherited_reset < 4 && fail_cleanup < 2);
      failed_start(unit, (int)stage, stopped != 0, enabled != 0,
                   inherited_reset, fail_cleanup != 0);
    }
  assert(critical_depth == 0);
  return 0;
}
'''


class GPTClockRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a host C compiler (cc) is required")
        source = (ARCH / "rzv_clock.c").read_text()
        hardware = (ARCH / "hardware/rzv_gpt.h").read_text()
        macros = "\n".join(re.findall(r"^#define RZV_GPT_[^\n]+", source, re.M))
        macros += "\n" + re.search(
            r"^#define RZV_GPT_LOGICAL_CHANNELS[^\n]+\n"
            r"#define RZV_GPT_LOGICAL_CHANNEL_VALID\(ch\) \\\n[^\n]+", hardware, re.M).group()
        state = "\n".join(re.search(pattern, source, re.M | re.S).group() for pattern in (
            r"^static uint16_t g_rzv_gpt_unit_users[^;]+;",
            r"^static bool g_rzv_gpt_unit_ready[^;]+;",
            r"^static mutex_t g_rzv_gpt_unit_lock[^;]+;"))
        functions = "\n".join(EXTRACT.definition(source, signature) for signature in (
            "static int rzv_gpt_clock_ctrl(", "int rzv_gpt_module_start(",
            "int rzv_gpt_module_stop("))
        cls.temporary = tempfile.TemporaryDirectory(prefix="rzv2h-gpt-clock-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        path = directory / "gpt-clock.c"
        path.write_text(PREAMBLE + macros + "\n" + state + BOUNDARIES + functions + SCENARIOS)
        cls.binary = directory / "gpt-clock"
        result = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-pthread", str(path), "-o", str(cls.binary)], capture_output=True, text=True,
            timeout=30, check=False)
        if result.returncode:
            raise AssertionError("production GPT clock host compilation failed:\n" + result.stderr)

    def exercise(self, scenario):
        result = subprocess.run([str(self.binary), scenario], capture_output=True,
                                text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, scenario + ":\n" + result.stderr)

    def test_cold_once_per_unit_and_warm_sibling_lifetimes(self):
        self.exercise("lifecycle")

    def test_invalid_unmatched_interrupt_and_mutex_rejection(self):
        self.exercise("guards")

    def test_reference_overflow_preserves_state_and_performs_no_cpg(self):
        self.exercise("overflow")

    def test_clock_failure_restores_mstop_and_retries_from_cold(self):
        for unit in range(2):
            for stopped in range(2):
                for enabled in range(2):
                    for reset in range(4):
                        with self.subTest(unit=unit, stopped=stopped, enabled=enabled, reset=reset):
                            self.exercise(f"failure-{unit}-1-{stopped}-{enabled}-{reset}-0")

    def test_reset_release_failure_unwinds_and_retries_from_cold(self):
        for unit in range(2):
            for stopped in range(2):
                for enabled in range(2):
                    for reset in range(4):
                        with self.subTest(unit=unit, stopped=stopped, enabled=enabled, reset=reset):
                            self.exercise(f"failure-{unit}-2-{stopped}-{enabled}-{reset}-0")

    def test_restore_monitor_failures_preserve_original_acquisition_error(self):
        for unit in range(2):
            for reset in range(4):
                with self.subTest(unit=unit, reset=reset):
                    self.exercise(f"failure-{unit}-2-0-1-{reset}-1")

    def test_concurrent_starters_wait_for_clock_monitor_with_unit_independence(self):
        self.exercise("concurrent-clock")

    def test_concurrent_starters_wait_for_reset_monitor_before_publication(self):
        self.exercise("concurrent-release")


if __name__ == "__main__":
    unittest.main()
