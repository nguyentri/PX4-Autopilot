#!/usr/bin/env python3
"""Check real SCI-I2C register traces against R01UH1032EJ0140 section 7.3."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
SPEC = importlib.util.spec_from_file_location(
    "i2c_transactions", ROOT / "test/rzv2h-sci-i2c-runtime-test.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def harness(arch=ARCH, clock_source=None):
    source = (arch / "rzv_sci_i2c.c").read_text()
    code = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <limits.h>
#include <errno.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/types.h>
#define FAR
#define CODE
#define OK 0
#define irqstate_t unsigned
#define ARM_DSB() ((void)0)
#ifdef CONFIG_RZV2H_BUILD_CM33
#define RZV_IRQ_FIRST 16u
#else
#define RZV_IRQ_FIRST 32u
#endif
#define sem_t unsigned
#define i2cerr(...) ((void)0)
#define i2cinfo(...) ((void)0)
#define RZV_CLOCK_P5CLK 5
#define RZV_CLOCK_P5CLK_HZ 100000000u
#define SCI_I2C_PCLK_FALLBACK_HZ RZV_CLOCK_P5CLK_HZ
#define SCI_I2C_DEFAULT_SCL_HZ 100000u
#define SCI_I2C_CCR2_BCP 4u
#define SCI_I2C_CESR_TIMEOUT 10000u
'''
    code += R.without_includes(
        (R.NUTTX / "include/nuttx/i2c/i2c_master.h").read_text())
    code += R.without_includes((arch / "rzv_sci_i2c_internal.h").read_text())
    code += R.without_includes((ARCH / "hardware/rzv_sci.h").read_text())
    for header in (ARCH / "hardware/rzv_intc_gic.h",
                   R.NUTTX / "arch/arm/include/rzv/rzv2h_irq.h",
                   R.NUTTX / "arch/arm/src/armv8-m/nvic.h"):
        code += R.without_includes(header.read_text())
    code += r'''
static uint32_t regs[64], pclk = 100000000;
static uint32_t pending[16];
#ifdef CONFIG_RZV2H_BUILD_CM33
#define PENDING_BASE NVIC_IRQ_CLRPEND(0)
#define PENDING_INPUT(irq) ((irq) - RZV_IRQ_FIRST)
#else
#define PENDING_BASE RZV_INTC_GIC_GICD_ICDICPR(0)
#define PENDING_INPUT(irq) (irq)
#endif
static uint64_t usec;
static unsigned posts, requests;
struct event {uintptr_t address; uint32_t value; uint64_t at;};
static struct event events[1024];
static unsigned event_count;
static void __attribute__((unused)) up_udelay(unsigned delay) {usec += delay;}
static uint32_t rzv_clock_get_rate(unsigned id) {assert(id == RZV_CLOCK_P5CLK); return pclk;}
static irqstate_t enter_critical_section(void) {return 0;}
static void leave_critical_section(irqstate_t flags) {(void)flags;}
static int nxsem_post(unsigned *sem) {(void)sem; ++posts; return 0;}
static uint8_t getreg8(uintptr_t address) {
  assert(address == RZV_SCI_CESR_OFFSET);
  return regs[RZV_SCI_CCR0_OFFSET / 4] & (SCI_CCR0_TE | SCI_CCR0_RE);
}
static uint32_t getreg32(uintptr_t address) {return regs[address / 4];}
static void putreg32(uint32_t value, uintptr_t address) {
  assert(event_count < 1024);
  events[event_count++] = (struct event){address, value, usec};
  if (address >= PENDING_BASE && address < PENDING_BASE + sizeof(pending)) {
    assert(value && !(value & (value - 1)));
    pending[(address - PENDING_BASE) / 4] &= ~value;
    return;
  }
  if (address == RZV_SCI_CFCLR_OFFSET) {regs[RZV_SCI_CSR_OFFSET / 4] &= ~value; return;}
  if (address == RZV_SCI_ICFCLR_OFFSET) {regs[RZV_SCI_ISR_OFFSET / 4] &= ~value; return;}
  if (address == RZV_SCI_ICR_OFFSET && (value & (7u << 16))) ++requests;
  regs[address / 4] = value;
}
static void putreg8(uint8_t value, uintptr_t address) {
  assert(address == RZV_SCI_CCR0_OFFSET + 2);
  events[event_count++] = (struct event){address, value, usec};
  regs[RZV_SCI_CCR0_OFFSET / 4] =
    (regs[RZV_SCI_CCR0_OFFSET / 4] & ~(0xffu << 16)) | ((uint32_t)value << 16);
}
'''
    code += R.without_includes(clock_source if clock_source is not None else
                              (arch / "rzv_sci_i2c_clock.c").read_text())
    if "void sci_i2c_disable(" in source:
        code += R.function(source, "void sci_i2c_disable(")
    if "void sci_i2c_clear_pending(" in source:
        code += R.function(source, "void sci_i2c_clear_pending(")
    for signature in ("static int sci_i2c_wait_idle(",
                      "static void sci_i2c_clear_status(",
                      "static int sci_i2c_quiesce(",
                      "static int sci_i2c_hw_init("):
        code += R.function(source, signature)
    code += R.without_includes((arch / "rzv_sci_i2c_isr.c").read_text())
    code += r'''
static bool minimum_widths(uint32_t hz, uint32_t request, unsigned cks, unsigned brr) {
  uint64_t ticks = ((uint64_t)1 << (2 * cks)) * (brr + 1);
  unsigned high = request <= 100000 ? 4000 : 600;
  unsigned low = request <= 100000 ? 4700 : 1300;
  /* Tables 7.3-9/20: the base intervals must pass without modulation. */
  return 14 * ticks * 1000000000 >= (uint64_t)high * hz &&
         16 * ticks * 1000000000 >= (uint64_t)low * hz;
}
static uint32_t safe_ceiling_denominator(uint32_t hz, uint32_t request) {
  uint32_t fastest = UINT32_MAX;
  for (unsigned k = 0; k < 4; ++k) {
    unsigned div = 1u << (2 * k);
    /* Enumerate every field value independently of the driver's encoding calculation. */
    bool delay_ok = false;
    for (unsigned q = 1; q <= 31; ++q)
      if ((uint64_t)(q - 1) * div * 1000000000 > (uint64_t)hz * 300) delay_ok = true;
    if (!delay_ok) continue;
    for (unsigned b = 0; b < 256; ++b) {
      uint32_t denominator = 32 * div * (b + 1);
      if (minimum_widths(hz, request, k, b) && denominator < fastest) fastest = denominator;
    }
  }
  assert(fastest != UINT32_MAX);
  return fastest;
}
static void check_clock(uint32_t hz, uint32_t request) {
  struct sci_i2c_clock_s c;
  int ret = sci_i2c_calc_clock(hz, request, &c);
  assert(ret == 0);
  unsigned div = 1u << (2u * c.cks);
  unsigned modulation = c.brme ? c.mddr : 256;
  uint64_t numerator = (uint64_t)hz * modulation;
  uint64_t denominator = (uint64_t)32 * div * (c.brr + 1) * 256;
  uint32_t ceiling_denominator = safe_ceiling_denominator(hz, request);
  uint32_t target_numerator = hz, target_denominator = ceiling_denominator;
  if ((uint64_t)request * ceiling_denominator < hz) {
    target_numerator = request; target_denominator = 1;
  }
  printf("clock=%u request=%u CKS=%u BRR=%u MDDR=%u rate=%u IICDL=%u\n",
         hz, request, c.cks, c.brr, modulation, c.actual_hz, c.cycles_value);
  assert(c.actual_hz == numerator / denominator);
  assert(numerator <= (uint64_t)request * denominator);
  assert(minimum_widths(hz, request, c.cks, c.brr));
  assert(c.cycles_value > 0 && c.cycles_value <= 31);
  /* IICDL=q encodes q-1 .. q divided-clock cycles (pp.2627/2728). */
  assert((uint64_t)(c.cycles_value - 1) * div * 1000000000 > (uint64_t)hz * 300);
  uint64_t reference = (uint64_t)target_numerator * denominator;
  uint64_t chosen = numerator * target_denominator;
  assert(chosen <= reference && reference - chosen <= reference / 50);
  /* Ensure the chosen tuple is the fastest admitted rational rate below the target. */
  for (unsigned k = 0; k < 4; ++k) {
    unsigned base_div = 1u << (2 * k);
    bool delay_ok = false;
    for (unsigned q = 1; q <= 31; ++q)
      if ((uint64_t)(q - 1) * base_div * 1000000000 > (uint64_t)hz * 300) delay_ok = true;
    if (!delay_ok) continue;
    for (unsigned b = 0; b < 256; ++b) {
      if (!minimum_widths(hz, request, k, b)) continue;
      uint32_t base_den = 32 * base_div * (b + 1);
      for (unsigned m = 128; m <= 256; ++m) {
        uint64_t n = (uint64_t)hz * m;
        if (n > (uint64_t)request * base_den * 256) continue;
        assert((uint64_t)modulation * base_den >= (uint64_t)m * (32 * div * (c.brr + 1)));
      }
    }
  }
  if (hz == 100000000 && request == 400000) {
    assert(c.cks == 1 && c.brr == 2 && !c.brme && c.actual_hz == 260416);
  }
  if (hz == 100000000 && request == 100000) {
    assert(c.cks == 1 && c.brr == 7 && !c.brme && c.actual_hz == 97656);
  }
}
int main(int argc, char **argv) {
  assert(argc == 2);
  for (unsigned i=0; i<16; ++i) pending[i] = UINT32_MAX;
  struct rzv_sci_i2c_priv_s priv = {.actual_scl_hz = 100000, .half_bit_us = 5};
  if (!strcmp(argv[1], "mode")) {
    assert(sci_i2c_hw_init(&priv, 100000) == 0);
    uint32_t ccr3 = regs[RZV_SCI_CCR3_OFFSET / 4];
    printf("CCR3=0x%08x\n", ccr3); fflush(stdout);
    assert((ccr3 & 3u) == 3u); /* p.2619 requires CPOL=CPHA=1 outside SPI/sync. */
    assert((ccr3 & (7u << 16)) == (4u << 16));
    assert(!(ccr3 & ((1u << 20) | (1u << 12) | (1u << 7))));
  } else if (!strcmp(argv[1], "clock")) {
    for (unsigned i = 0; i < 3; ++i) {
      unsigned clocks[] = {24000000, 100000000, 200000000};
      check_clock(clocks[i], 100000); check_clock(clocks[i], 400000);
      check_clock(clocks[i], 10000); check_clock(clocks[i], 350000);
    }
  } else if (!strcmp(argv[1], "prior-standard") || !strcmp(argv[1], "prior-fast")) {
    unsigned request = !strcmp(argv[1], "prior-standard") ? 100000 : 400000;
    struct sci_i2c_clock_s c;
    unsigned old_brr = request == 100000 ? 3 : 1;
    assert(!minimum_widths(100000000, request, 1, old_brr));
    assert(sci_i2c_calc_clock(100000000, request, &c) == 0);
    printf("request=%u returned CKS=%u BRR=%u MDDR=%u\n", request, c.cks, c.brr, c.mddr); fflush(stdout);
    assert(minimum_widths(100000000, request, c.cks, c.brr));
  } else if (!strcmp(argv[1], "rational")) {
    uint32_t clocks[] = {99999997, 100000003, UINT32_MAX};
    for (unsigned i = 0; i < 3; ++i) {
      check_clock(clocks[i], 100000); check_clock(clocks[i], 400000);
      check_clock(clocks[i], 97656); check_clock(clocks[i], 260416);
    }
    check_clock(100000000, 97656); check_clock(100000000, 260416);
  } else if (!strcmp(argv[1], "range")) {
    struct sci_i2c_clock_s c;
    assert(sci_i2c_calc_clock(100000000, 400001, &c) == -EINVAL);
    assert(sci_i2c_calc_clock(100000000, 1000000, &c) == -EINVAL);
    assert(sci_i2c_calc_clock(0, 100000, &c) == -EINVAL);
  } else if (!strcmp(argv[1], "abort")) {
    regs[RZV_SCI_CCR0_OFFSET / 4] = SCI_CCR0_TE | SCI_CCR0_RE | SCI_CCR0_TIE | SCI_CCR0_TEIE;
    regs[RZV_SCI_ICR_OFFSET / 4] = SCI_ICR_IICSTAREQ;
    assert(sci_i2c_quiesce(&priv) == 0);
    assert(events[0].address == RZV_SCI_CCR0_OFFSET + 2 && events[0].value == 0);
    assert(events[1].address == RZV_SCI_CCR0_OFFSET && events[1].value == 0);
    assert(usec >= 1 && !(regs[RZV_SCI_ICR_OFFSET / 4] & (7u << 16)));
    unsigned txi = PENDING_INPUT(RZV_IRQ_SCI_TXI(0)), tei = PENDING_INPUT(RZV_IRQ_SCI_TEI(0));
    for (unsigned i=0; i<16; ++i) {
      uint32_t expected = UINT32_MAX;
      if (i == txi / 32) expected &= ~(1u << (txi % 32));
      if (i == tei / 32) expected &= ~(1u << (tei % 32));
      assert(pending[i] == expected);
    }
  } else if (!strcmp(argv[1], "transition")) {
    regs[RZV_SCI_CCR0_OFFSET / 4] = SCI_CCR0_TE | SCI_CCR0_RE;
    assert(sci_i2c_hw_init(&priv, 100000) == 0);
    uint64_t stop_at = 0, mode_at = 0;
    bool stopped = false, configured = false;
    for (unsigned i = 0; i < event_count; ++i) {
      if (events[i].address == RZV_SCI_CCR0_OFFSET && events[i].value == 0) {stopped = true; stop_at = events[i].at;}
      if (events[i].address == RZV_SCI_CCR3_OFFSET) {
        assert(stopped && events[i].at >= stop_at + 1); mode_at = events[i].at; configured = true;
      }
      if (events[i].address == RZV_SCI_CCR2_OFFSET) assert(configured && events[i].at >= mode_at + 1);
      assert(events[i].address != RZV_SCI_FCR_OFFSET); /* I2C must remain non-FIFO. */
    }
  } else {
    struct i2c_msg_s messages[2] = {{.frequency=100000}, {.frequency=100000}};
    struct sci_i2c_msgmeta_s metadata[2] = {{.next=1}, {.next=2}};
    priv.msgs = messages; priv.metadata = metadata;
    priv.msg_count = !strcmp(argv[1], "stop-final") ? 1 : 2;
    priv.state = SCI_I2C_STATE_STOP;
    regs[RZV_SCI_ISR_OFFSET / 4] = SCI_ISR_IICSTIF;
    regs[RZV_SCI_CCR0_OFFSET / 4] = SCI_CCR0_TE | SCI_CCR0_RE | SCI_CCR0_TIE | SCI_CCR0_TEIE;
    if (!strcmp(argv[1], "stop-error")) regs[RZV_SCI_CSR_OFFSET / 4] = SCI_CSR_ORER;
    if (!strcmp(argv[1], "late-txi")) {
      regs[RZV_SCI_ISR_OFFSET / 4] = SCI_ISR_IICACKR;
      priv.result = -ENXIO;
      sci_i2c_txi_isr(0, NULL, &priv);
      assert(requests == 0 && posts == 0 && priv.state == SCI_I2C_STATE_STOP);
    } else {
      sci_i2c_tei_isr(0, NULL, &priv);
      if (!strcmp(argv[1], "stop-error")) {
        assert(requests == 0 && posts == 1 && priv.result == -EIO);
        assert(regs[RZV_SCI_CCR0_OFFSET / 4] == 0);
      } else if (!strcmp(argv[1], "stop-final")) {
        /* Last STOP: disable and complete; only the short stop interval. */
        assert(requests == 0 && posts == 1 && priv.result == OK);
        assert(regs[RZV_SCI_CCR0_OFFSET / 4] == 0);
        assert(usec == priv.stop_interval_us && usec < priv.half_bit_us);
      } else {
        assert(requests == 1 && posts == 0);
        for (unsigned i=0; i<event_count; ++i)
          if (events[i].address == RZV_SCI_ICR_OFFSET && (events[i].value & SCI_ICR_IICSTAREQ))
            assert(events[i].at >= 5); /* p.2627: half bit after STOP STI. */
      }
    }
  }
  return 0;
}
'''
    return code


class SCIMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-sci-i2c-mode-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        (directory / "mode.c").write_text(harness())
        cls.binary = directory / "mode"
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-parameter", "-Wno-sign-compare",
                        str(directory / "mode.c"), "-o", str(cls.binary)], check=True)

    def case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_i2c_mode_preserves_required_cpol_cpha_and_disables_fifo(self): self.case("mode")
    def test_clock_tuples_meet_unmodulated_width_and_sda_delay_limits(self): self.case("clock")
    def test_prior_standard_modulation_tuple_cannot_satisfy_minimum_widths(self): self.case("prior-standard")
    def test_prior_fast_modulation_tuple_cannot_satisfy_minimum_widths(self): self.case("prior-fast")
    def test_exact_rational_ceiling_and_accuracy_across_clock_boundaries(self): self.case("rational")
    def test_unsupported_clock_range_fails_before_programming(self): self.case("range")
    def test_abort_masks_interrupts_before_disabling_and_clears_requests(self): self.case("abort")
    def test_cm33_pending_clear_uses_nvic_inputs_and_preserves_neighbors(self):
        R.S.compile_and_run(harness(), arguments=("abort",), defines=(
            "-DCONFIG_RZV2H_BUILD_CM33=1", "-Wno-unused-parameter", "-Wno-sign-compare"))
    def test_mode_transition_observes_stop_and_mode_settle_intervals(self): self.case("transition")
    def test_stop_to_start_observes_half_bit_interval(self): self.case("stop-start")
    def test_stop_overrun_finishes_without_reissuing_stop(self): self.case("stop-error")
    def test_final_stop_completes_without_half_bit_wait(self): self.case("stop-final")
    def test_late_txi_does_not_reissue_pending_condition(self): self.case("late-txi")


if __name__ == "__main__":
    unittest.main()
