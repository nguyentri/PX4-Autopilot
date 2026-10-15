#!/usr/bin/env python3
"""Execute the native GTM timeout and countdown-status operations on the host."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
SPEC = importlib.util.spec_from_file_location("extract", ROOT / "test/rzv2h-wdt-runtime-test.py")
EXTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTRACT)

PRELUDE = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#define FAR
#define OK 0
#define DEBUGASSERT assert
#define tmrinfo(...) ((void)0)
#define tmrerr(...) ((void)0)
#define TCFLAGS_ACTIVE 1
#define TCFLAGS_HANDLER 2
#define RZV_GTM_OSTMCMP_OFFSET 0
#define RZV_GTM_OSTMCNT_OFFSET 4
#define RZV_GTM_OSTMTE_OFFSET 16
#define RZV_GTM_OSTMTS_OFFSET 20
#define RZV_GTM_OSTMTT_OFFSET 24
#define GTM_OSTMTE_TE 1
#define GTM_OSTMTS_OSTMTS 1
#define GTM_OSTMTT_OSTMTT 1
typedef unsigned irqstate_t;
typedef bool (*tccb_t)(uint32_t *, void *);
struct timer_lowerhalf_s { int unused; };
struct rzv_gtm_lowerhalf_s {
  struct timer_lowerhalf_s lower;
  uint32_t frequency, timeout;
  int channel;
  tccb_t callback;
  void *arg;
};
struct timer_status_s { uint32_t flags, timeout, timeleft; };
static uint32_t counter, compare;
static unsigned enabled, starts, stops, depth;
static irqstate_t enter_critical_section(void) { assert(depth++ == 0); return 0; }
static void leave_critical_section(irqstate_t flags) { (void)flags; assert(--depth == 0); }
static uint8_t gtm_getreg8(struct rzv_gtm_lowerhalf_s *priv, unsigned offset) {
  (void)priv; assert(offset == RZV_GTM_OSTMTE_OFFSET); return enabled;
}
static uint32_t gtm_getreg32(struct rzv_gtm_lowerhalf_s *priv, unsigned offset) {
  (void)priv;
  assert(offset == RZV_GTM_OSTMCMP_OFFSET || offset == RZV_GTM_OSTMCNT_OFFSET);
  return offset == RZV_GTM_OSTMCMP_OFFSET ? compare : counter;
}
static void gtm_putreg8(struct rzv_gtm_lowerhalf_s *priv, unsigned offset, uint8_t value) {
  (void)priv; assert(value == 1);
  if (offset == RZV_GTM_OSTMTS_OFFSET) { enabled = 1; counter = compare; ++starts; }
  else { assert(offset == RZV_GTM_OSTMTT_OFFSET); enabled = 0; ++stops; }
}
static void gtm_putreg32(struct rzv_gtm_lowerhalf_s *priv, unsigned offset, uint32_t value) {
  (void)priv; assert(offset == RZV_GTM_OSTMCMP_OFFSET); compare = value;
}
static bool callback(uint32_t *next, void *arg) { (void)next; (void)arg; return true; }
static bool change_period(uint32_t *next, void *arg) { *next = *(uint32_t *)arg; return true; }
static bool stop_callback(uint32_t *next, void *arg) { (void)next; (void)arg; return false; }
"""


class GtmStatusRuntime(unittest.TestCase):
    def run_case(self, body):
        source = Path(os.environ.get("RZV_GTM_SOURCE", ARCH / "rzv_gtm.c")).read_text()
        code = PRELUDE
        for signature in ("static int gtm_timer_getstatus(", "static int gtm_timer_settimeout(",
                          "static int gtm_interrupt("):
            code += EXTRACT.definition(source, signature)
        code += "\nint main(void) {\n" + body + "\nreturn 0;\n}\n"
        with tempfile.TemporaryDirectory(prefix="rzv2h-gtm-status-") as directory:
            path = Path(directory)
            (path / "case.c").write_text(code)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-function", str(path / "case.c"), "-o", str(path / "case")],
                           check=True)
            subprocess.run([str(path / "case")], check=True)

    def test_setting_stopped_timeout_does_not_start_counter(self):
        self.run_case(r"""
struct rzv_gtm_lowerhalf_s state = {.frequency = 100000000};
struct timer_status_s status;
assert(gtm_timer_settimeout(&state.lower, 1000000) == 0);
assert(!enabled && !starts && compare == 99999999);
assert(gtm_timer_getstatus(&state.lower, &status) == 0);
assert(status.flags == 0 && status.timeleft == 0 && status.timeout == 1000000);
""")

    def test_interval_counter_reports_remaining_time_and_handler(self):
        self.run_case(r"""
struct rzv_gtm_lowerhalf_s state = {.frequency = 100000000, .timeout = 1000000,
                                   .callback = callback};
struct timer_status_s status;
enabled = 1; compare = 99999999; counter = 79999999;
assert(gtm_timer_getstatus(&state.lower, &status) == 0);
assert(status.flags == (TCFLAGS_ACTIVE | TCFLAGS_HANDLER));
assert(status.timeleft == 800000);
counter = 69999999;
assert(gtm_timer_getstatus(&state.lower, &status) == 0 && status.timeleft == 700000);
enabled = 0;
assert(gtm_timer_getstatus(&state.lower, &status) == 0);
assert(status.flags == TCFLAGS_HANDLER && status.timeleft == 0);
""")

    def test_running_timeout_update_preserves_active_state_and_rejects_invalid(self):
        self.run_case(r"""
struct rzv_gtm_lowerhalf_s state = {.frequency = 100000000};
enabled = 1;
assert(gtm_timer_settimeout(&state.lower, 500000) == 0);
assert(enabled && starts == 1 && stops == 1 && compare == 49999999);
assert(gtm_timer_settimeout(&state.lower, 0) == -EINVAL);
assert(gtm_timer_settimeout(&state.lower, UINT32_MAX) == -ERANGE);
assert(enabled && starts == 1 && stops == 1 && compare == 49999999);
""")

    def test_callback_updates_period_without_starting_and_can_stop(self):
        self.run_case(r"""
uint32_t next = 500000;
struct rzv_gtm_lowerhalf_s state = {.frequency = 100000000, .timeout = 1000000,
                                   .callback = change_period, .arg = &next};
enabled = 1; compare = 99999999;
assert(gtm_interrupt(0, NULL, &state) == 0);
assert(state.timeout == 500000 && compare == 49999999);
assert(enabled && !starts && !stops);
next = UINT32_MAX;
assert(gtm_interrupt(0, NULL, &state) == 0);
assert(state.timeout == 500000 && compare == 49999999);
state.callback = stop_callback;
assert(gtm_interrupt(0, NULL, &state) == 0);
assert(!enabled && stops == 1 && !starts);
""")


if __name__ == "__main__":
    unittest.main()
