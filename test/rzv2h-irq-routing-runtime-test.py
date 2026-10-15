#!/usr/bin/env python3
"""Exercise CPU IRQ routing against core-matched Renesas source contracts."""

import importlib.util
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
NUTTX = Path(os.environ.get("RZV_NUTTX_ROOT", ROOT / "platforms/nuttx/NuttX/nuttx"))
ARCH = NUTTX / "arch/arm/src/rzv"
SPEC = importlib.util.spec_from_file_location(
    "runtime", ROOT / "test/rzv2h-audit-remediation-runtime-test.py")
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
extract = RUNTIME.extract
run = RUNTIME.run
PRE = RUNTIME.PRE + r'''
typedef int (*xcpt_t)(int, void *, void *);
typedef unsigned irqstate_t;
#define serr(...) ((void)0)
#define sinfo(...) ((void)0)
#define spierr(...) ((void)0)
#define spiinfo(...) ((void)0)
#define i2cerr(...) ((void)0)
#define _err(...) ((void)0)
#define _info(...) ((void)0)
#define wdinfo(...) ((void)0)
#define wderr(...) ((void)0)
#define wdwarn(...) ((void)0)
'''


def header(path):
    return re.sub(r"^\s*#\s*include[^\n]*$", "", path.read_text(), flags=re.M)


def irq_header(cm33=False):
    return (f"#define RZV_IRQ_FIRST {16 if cm33 else 32}\n" +
            ("#define CONFIG_RZV2H_BUILD_CM33 1\n" if cm33 else "") +
            header(NUTTX / "arch/arm/include/rzv/rzv2h_irq.h"))


# The host model records installation, trigger programming, enable and teardown.
# CPU input indices come from core-matched FSP bsp_irq_id.h, not driver macros.
IRQ_MODEL = r'''
static bool installed[512], enabled[512], edge[512], typed[512];
static int attempts, failure_at, prefix;
static __attribute__((unused)) int irq_attach(int irq, xcpt_t handler, void *arg) {
  assert(irq >= 0 && irq < 512 && handler && !installed[irq]);
  if (++attempts == failure_at) return -EIO;
  installed[irq] = true; return 0;
}
static __attribute__((unused)) void irq_detach(int irq) {
  assert(installed[irq] && !enabled[irq]); installed[irq] = false;
}
static __attribute__((unused)) void rzv_gic_set_irq_type(int irq, bool pulse) {
  assert(installed[irq] && !enabled[irq]); edge[irq] = pulse; typed[irq] = true;
}
static __attribute__((unused)) void up_enable_irq(int irq) {
  assert(installed[irq]);
  if (prefix == 32) assert(typed[irq]);
  enabled[irq] = true;
}
static __attribute__((unused)) void up_disable_irq(int irq) { enabled[irq] = false; }
static __attribute__((unused)) int rzv_icu_attach(int event, xcpt_t handler,
                                               void *arg, bool enable) {
  (void)event; (void)handler; (void)arg; (void)enable;
  assert(!"fixed CPU interrupt was incorrectly sent through IRQSEL"); return -EINVAL;
}
static __attribute__((unused)) int rzv_icu_detach(int irq) {
  (void)irq; assert(!"fixed CPU input was incorrectly detached as an ICU slot"); return 0;
}
static void reset_irqs(void) {
  for (int i = 0; i < 512; ++i) assert(!installed[i] && !enabled[i]);
  memset(edge, 0, sizeof(edge)); memset(typed, 0, sizeof(typed)); attempts = 0;
}
'''


class IrqRoutingRuntime(unittest.TestCase):
    def test_uart_fixed_inputs_and_partial_attach_cleanup_on_both_cores(self):
        source = (ARCH / "rzv_serial.c").read_text()
        for cm33 in (False, True):
            with self.subTest(cm33=cm33):
                code = PRE + irq_header(cm33) + IRQ_MODEL + r'''
#define RZV_SCI_CCR_OFFSET(n) (n)
#define SCI_CCR0_RIE 1u
#define SCI_CCR0_TIE 2u
#define SCI_CCR0_TEIE 4u
#define SCI_CCR0_RE 8u
#define SCI_CCR0_TE 16u
struct rzv_uart_s { int channel, irq_rxi, irq_txi, irq_tei, irq_eri;
                    int evt_rxi, evt_txi, evt_tei, evt_eri; };
struct uart_dev_s { void *priv; };
static int rzv_interrupt(int irq, void *context, void *arg) { return 0; }
static uint32_t rzv_sci_getreg(struct rzv_uart_s *p, unsigned off) { return 0; }
static void rzv_sci_putreg(struct rzv_uart_s *p, unsigned off, uint32_t val) {}
'''
                for signature in ("static int rzv_attach(", "static void rzv_detach("):
                    code += extract(source, signature)
                code += f"\nint main(void) {{ prefix = {16 if cm33 else 32};\n" + r'''
  for (int ch = 0; ch < 10; ++ch) for (failure_at = 0; failure_at <= 4; ++failure_at) {
    reset_irqs();
    struct rzv_uart_s p = {.channel = ch, .irq_rxi = -1, .irq_txi = -1,
      .irq_tei = -1, .irq_eri = -1, .evt_rxi = 161 + 6 * ch,
      .evt_txi = 163 + 6 * ch, .evt_tei = 164 + 6 * ch, .evt_eri = 160 + 6 * ch};
    struct uart_dev_s dev = {&p};
    int ret = rzv_attach(&dev);
    if (failure_at) {
      assert(ret == -EIO);
      assert(p.irq_rxi == -1 && p.irq_txi == -1 && p.irq_tei == -1 && p.irq_eri == -1);
    }
    else {
      assert(ret == 0);
      assert(p.irq_eri == prefix + 114 + 6 * ch && p.irq_rxi == p.irq_eri + 1);
      assert(p.irq_txi == p.irq_eri + 2 && p.irq_tei == p.irq_eri + 3);
      for (int i = 0; i < 4; ++i) assert(installed[p.irq_eri + i] && enabled[p.irq_eri + i]);
      if (prefix == 32) assert(!edge[p.irq_eri] && edge[p.irq_rxi] && edge[p.irq_txi] && !edge[p.irq_tei]);
      rzv_detach(&dev);
    }
    reset_irqs();
  }
}
'''
                run(code)

    def test_sci_spi_initialization_uses_fixed_inputs_and_unwinds(self):
        source = (ARCH / "rzv_sci_spi.c").read_text()
        for cm33 in (False, True):
            with self.subTest(cm33=cm33):
                code = PRE + irq_header(cm33) + IRQ_MODEL
                code += header(ARCH / "hardware/rzv_elc.h")
                events = re.search(r"static const int g_sci_spi_events.*?\n\};", source, re.S)
                if events:
                    code += "\n#define SCI_SPI_MAX_CHANNELS 10\n" + events.group()
                code += r'''
#define CONFIG_RZV_SCI0_SPI 1
#define CONFIG_RZV_SCI1_SPI 1
#define CONFIG_RZV_SCI2_SPI 1
#define CONFIG_RZV_SCI3_SPI 1
#define SCI_SPI_DEFAULT_HZ 1000000
#define SCI_SPI_STATE_IDLE 0
#define SPIDEV_MODE0 0
#define RZV_SCI_CCR0_OFFSET 0
struct spi_dev_s { void *ops; };
struct rzv_sci_spi_priv_s {
  struct spi_dev_s dev; bool initialized, initializing, lsbfirst;
  int channel, base, clk_id, state, lock, sem_isr, mode, nbits;
  int evt_txi, evt_rxi, evt_tei, evt_eri, irq_txi, irq_rxi, irq_tei, irq_eri;
  unsigned frequency, actual;
};
static struct rzv_sci_spi_priv_s g_sci_spi_priv[10];
static const int g_sci_base[10] = {0};
static const int g_sci_clk[10] = {0};
static int g_sci_spi_ops, clocks, modules, locks, sems;
static irqstate_t enter_critical_section(void) { return 0; }
static void leave_critical_section(irqstate_t flags) {}
static void nxmutex_init(int *m) { ++locks; }
static void nxmutex_destroy(int *m) { --locks; }
static void nxsem_init(int *s, int shared, int n) { ++sems; }
static void nxsem_destroy(int *s) { --sems; }
static int rzv_clock_enable(int id) { ++clocks; return 0; }
static void rzv_clock_disable(int id) { --clocks; }
static int rzv_module_unreset(int id) { ++modules; return 0; }
static void rzv_module_reset(int id) { --modules; }
static void putreg32(unsigned value, unsigned addr) {}
static int sci_spi_hw_configure(struct rzv_sci_spi_priv_s *p) { return 0; }
static int rzv_sci_spi_txi_isr(int irq, void *ctx, void *arg) { return 0; }
static int rzv_sci_spi_rxi_isr(int irq, void *ctx, void *arg) { return 0; }
static int rzv_sci_spi_tei_isr(int irq, void *ctx, void *arg) { return 0; }
static int rzv_sci_spi_eri_isr(int irq, void *ctx, void *arg) { return 0; }
'''
                code += extract(source, "struct spi_dev_s *rzv_sci_spi_initialize(")
                code += f"\nint main(void) {{ prefix = {16 if cm33 else 32};\n" + r'''
  for (int ch = 0; ch < 4; ++ch) {
    for (failure_at = 1; failure_at <= 4; ++failure_at) {
      reset_irqs();
      assert(rzv_sci_spi_initialize(ch) == NULL);
      assert(clocks == ch && modules == ch && locks == ch && sems == ch);
      assert(!g_sci_spi_priv[ch].initialized);
      reset_irqs();
    }
    failure_at = 0;
    assert(rzv_sci_spi_initialize(ch) == &g_sci_spi_priv[ch].dev);
    struct rzv_sci_spi_priv_s *p = &g_sci_spi_priv[ch];
    assert(p->irq_eri == prefix + 114 + 6 * ch && p->irq_rxi == p->irq_eri + 1);
    assert(p->irq_txi == p->irq_eri + 2 && p->irq_tei == p->irq_eri + 3);
    for (int i = 0; i < 4; ++i) assert(enabled[p->irq_eri + i]);
    int n = attempts; assert(rzv_sci_spi_initialize(ch) == &p->dev && attempts == n);
    for (int i = 0; i < 4; ++i) { up_disable_irq(p->irq_eri + i); irq_detach(p->irq_eri + i); }
    reset_irqs();
  }
}
'''
                run(code)

    def test_scif_selectors_are_pulse_inputs_enabled_after_configuration(self):
        source = (ARCH / "rzv_scif.c").read_text()
        code = PRE + irq_header() + r'''
struct rzv_scif_s { int channel, irq_rxi, irq_txi; };
struct uart_dev_s { void *priv; };
static bool installed[2], configured[2], enabled[2];
static int attempts, failure_at;
static int rzv_scif_rxi_interrupt(int irq, void *ctx, void *arg) { return 0; }
static int rzv_scif_txi_interrupt(int irq, void *ctx, void *arg) { return 0; }
static int rzv_icu_attach(int event, xcpt_t handler, void *arg, bool enable) {
  assert((event == 113 && handler == rzv_scif_rxi_interrupt) ||
         (event == 114 && handler == rzv_scif_txi_interrupt));
  assert(!enable); int slot = event - 113;
  if (++attempts == failure_at) return -EIO;
  assert(!installed[slot]); installed[slot] = true; return 385 + slot;
}
static __attribute__((unused)) void rzv_gic_set_irq_type(int irq, bool edge) {
  assert(edge && installed[irq - 385] && !enabled[irq - 385]); configured[irq - 385] = true;
}
static __attribute__((unused)) void up_enable_irq(int irq) {
  assert(configured[irq - 385]); enabled[irq - 385] = true;
}
static void rzv_icu_detach(int irq) { installed[irq - 385] = enabled[irq - 385] = false; }
'''
        for signature in ("static int rzv_scif_attach(", "static void rzv_scif_detach("):
            code += extract(source, signature)
        code += r'''
int main(void) {
  for (failure_at = 0; failure_at <= 2; ++failure_at) {
    attempts = 0; memset(configured, 0, sizeof(configured));
    struct rzv_scif_s p = {.channel = 0, .irq_rxi = -1, .irq_txi = -1};
    struct uart_dev_s dev = {&p}; int ret = rzv_scif_attach(&dev);
    if (failure_at) assert(ret == -EIO && p.irq_rxi == -1 && p.irq_txi == -1);
    else { assert(ret == 0 && enabled[0] && enabled[1]); rzv_scif_detach(&dev); }
    assert(!installed[0] && !installed[1] && !enabled[0] && !enabled[1]);
  }
}
'''
        run(code)

    def test_ethernet_combined_irq_matches_the_selector_table(self):
        source = (ARCH / "rzv_ether.c").read_text()
        assignment = re.search(r"priv->event\s*=\s*([^;]+);", source).group(1)
        code = PRE + irq_header() + "\nint main(void) {\n"
        code += f"for (int intf = 0; intf < 2; ++intf) assert(({assignment}) == (intf ? 437 : 422));\n}}\n"
        run(code)

    def test_reused_selectable_slot_restores_level_sensitivity(self):
        source = (ARCH / "rzv_icu.c").read_text()
        code = PRE + r'''
#define RZV_INTC_SEL_SPI_BASE 385
#define RZV_INTC_SEL_SLOT_COUNT 1
#define RZV_INTC_GIC_GICD_ICDICPR(n) (n)
static struct { xcpt_t handler; void *arg; } g_icu_handlers[1];
static int g_icu_slot, depth;
static bool installed, enabled, edge = true;
static irqstate_t enter_critical_section(void) { return depth++; }
static void leave_critical_section(irqstate_t flags) { assert(depth == (int)flags + 1); --depth; }
static int rzv_icu_interrupt(int irq, void *ctx, void *arg) { return 0; }
static int irq_attach(int irq, xcpt_t handler, void *arg) {
  assert(irq == 385 && !installed && depth); installed = true; return 0;
}
static __attribute__((unused)) void rzv_gic_set_irq_type(int irq, bool pulse) {
  assert(irq == 385 && installed && !enabled); edge = pulse;
}
static void putreg32(uint32_t value, uintptr_t address) {}
static int rzv_icu_set_event(int slot, int event) {
  assert(slot == 0 && event == 422 && installed); return 0;
}
static int rzv_icu_detach(int irq) {
  installed = enabled = false; g_icu_handlers[0].handler = NULL; g_icu_slot = 0; return 0;
}
static void up_enable_irq(int irq) { assert(irq == 385 && !edge); enabled = true; }
''' + extract(source, "int rzv_icu_attach(") + r'''
int main(void) {
  assert(rzv_icu_attach(422, rzv_icu_interrupt, NULL, true) == 385);
  assert(installed && enabled && !edge && !depth);
}
'''
        run(code)

    def test_watchdog_uses_fixed_cr8_inputs_and_rejects_unavailable_routes(self):
        source = (ARCH / "rzv_wdt.c").read_text()
        code = PRE + irq_header() + IRQ_MODEL + header(ARCH / "hardware/rzv_wdt.h") + r'''
#define CONFIG_RZV_WDT_INTERRUPT_MODE 1
#define CONFIG_ARCH_IRQPRIO 1
#define RZV_WDT_MAX_CHANNELS 4
struct watchdog_ops_s { int unused; };
struct watchdog_lowerhalf_s { const struct watchdog_ops_s *ops; };
struct rzv_wdt_priv_s { const struct watchdog_ops_s *ops; uintptr_t base;
  int channel, timeout, frequency, cks, tops, irq; bool started, configured, registered; xcpt_t handler; void *arg; };
static struct rzv_wdt_priv_s g_wdt_priv[4];
static struct watchdog_lowerhalf_s g_wdt_dev[4];
static const struct watchdog_ops_s g_wdt_ops = {0};
struct rzv_wdt_clock_state_s {uint32_t clkp,loco,reset;};
static int clocks, registrations, fail_register, fail_priority;
static int rzv_wdt_calculate_timeout(struct rzv_wdt_priv_s *p, int ms) { return 0; }
static int rzv_wdt_clock_enable(int channel,struct rzv_wdt_clock_state_s *before) { ++clocks; return 0; }
static void rzv_wdt_clock_restore(int channel,const struct rzv_wdt_clock_state_s *before) { assert(clocks>0); --clocks; }
static int rzv_wdt_interrupt(int irq, void *ctx, void *arg) { return 0; }
static __attribute__((unused)) int rzv_icu_set_priority(int irq, int priority) {
  assert(!"fixed watchdog IRQ cannot use selectable-slot priority API"); return 0;
}
static __attribute__((unused)) int up_prioritize_irq(int irq, int priority) {
  assert((irq == 380 || irq == 381) && priority == 32); return fail_priority ? -EACCES : 0;
}
static void *watchdog_register(const char *name, struct watchdog_lowerhalf_s *p) {
  ++registrations; return fail_register ? NULL : p;
}
'''
        code += extract(source, "static xcpt_t rzv_wdt_capture(")
        code += extract(source, "int rzv_wdt_initialize(")
        code += r'''
int main(void) {
  prefix = 32;
  for (int ch = 0; ch < 2; ++ch) {
    assert(rzv_wdt_initialize("/dev/watchdog", ch) == -ENOTSUP);
    assert(!clocks && !registrations && !attempts);
  }
  for (int ch = 2; ch < 4; ++ch) {
    reset_irqs(); failure_at = 1;
    assert(rzv_wdt_initialize("/dev/watchdog", ch) == -EIO);
    assert(clocks == ch - 2); reset_irqs();
    failure_at = 0; fail_priority = 1;
    assert(rzv_wdt_initialize("/dev/watchdog", ch) == -EACCES);
    assert(clocks == ch - 2 && !installed[378 + ch]); reset_irqs();
    fail_priority = 0; fail_register = 1;
    assert(rzv_wdt_initialize("/dev/watchdog", ch) == -EIO);
    assert(clocks == ch - 2); reset_irqs();
    fail_register = 0;
    assert(rzv_wdt_initialize("/dev/watchdog", ch) == 0);
    assert(g_wdt_priv[ch].irq == 378 + ch && installed[378 + ch]);
    assert(edge[378 + ch] && !enabled[378 + ch]);
    assert(rzv_wdt_capture((struct watchdog_lowerhalf_s *)&g_wdt_priv[ch],
                          rzv_wdt_interrupt) == NULL);
    assert(enabled[378 + ch]);
    assert(rzv_wdt_capture((struct watchdog_lowerhalf_s *)&g_wdt_priv[ch], NULL)
           == rzv_wdt_interrupt);
    assert(!enabled[378 + ch]);
    irq_detach(378 + ch); reset_irqs();
  }
}
'''
        run(code)


if __name__ == "__main__":
    unittest.main()
