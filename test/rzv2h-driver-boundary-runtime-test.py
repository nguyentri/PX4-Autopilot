#!/usr/bin/env python3
"""Execute production clock, timer, and SCI-SPI deadline boundaries."""
from pathlib import Path
import importlib.util
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
SPEC = importlib.util.spec_from_file_location('wdt_extract', ROOT / 'test/rzv2h-wdt-runtime-test.py')
EXTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTRACT)


def compile_run(code):
    with tempfile.TemporaryDirectory(prefix='rzv2h-driver-boundary-') as directory:
        path = Path(directory)
        (path / 'test.c').write_text(code)
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(path / 'test.c'), '-o', str(path / 'test')], check=True)
        subprocess.run([str(path / 'test')], check=True)


PRELUDE = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <errno.h>
#include <limits.h>
#include <string.h>
#define OK 0
'''


class DriverBoundaries(unittest.TestCase):
    def test_spi_reset_failure_and_dma_chunk_failure_unwind(self):
        source = (ARCH / 'rzv_spi.c').read_text()
        header = re.sub(r'^\s*#\s*include[^\n]*$', '',
                        (ARCH / 'hardware/rzv_spi.h').read_text(), flags=re.M)
        definitions = re.search(r'^#define SPI_SPDCR2_POLLED \\\n(?:.*\\\n)*[^\n]*',
                                source, re.M).group()
        code = PRELUDE + header + '\n' + definitions + '\n' + r'''
#define CONFIG_RZV_SPI0 1
#define CONFIG_RZV_SPI0_DMA 1
#define SPI_DMA_BUFFER_SIZE 256u
#define SPIDEV_MODE0 0
#define spierr(...) ((void)0)
#define spiwarn(...) ((void)0)
#define spiinfo(...) ((void)0)
struct spi_dev_s { int unused; };
struct rzv_spi_config_s { unsigned port, clk_id, frequency; int dma_tx_channel; };
struct rzv_spi_priv_s {
  struct spi_dev_s spidev;
  const struct rzv_spi_config_s *config;
  int init_lock, exclsem;
  bool initialized;
  unsigned nbits, mode, actual;
};
static struct rzv_spi_config_s config = {0, 1, 1000000, 48};
static struct rzv_spi_priv_s g_spi0_priv = {.config = &config, .nbits = 8};
static int failure, clock_count, sem_count, lock_count, writes, chunks;
static int nxmutex_lock(int *lock) { (void)lock; ++lock_count; return 0; }
static int nxmutex_unlock(int *lock) { (void)lock; --lock_count; return 0; }
static int nxsem_init(int *sem, int shared, int count) {
  (void)sem; (void)shared; (void)count;
  if (failure == 2) return -ENOMEM;
  ++sem_count; return 0;
}
static int nxsem_destroy(int *sem) { (void)sem; --sem_count; return 0; }
static int rzv_clock_enable(unsigned id) { (void)id; ++clock_count; return 0; }
static int rzv_clock_disable(unsigned id) { (void)id; --clock_count; return 0; }
static int rzv_module_unreset(unsigned id) { (void)id; return failure == 1 ? -ETIMEDOUT : 0; }
static void rzv_spi_putreg32(struct rzv_spi_priv_s *priv, unsigned offset, unsigned value) {
  (void)priv; (void)offset; (void)value;
  assert(failure == 0); ++writes;
}
static uint32_t rzv_spi_getreg32(struct rzv_spi_priv_s *priv, unsigned offset) {
  (void)priv; (void)offset; assert(failure == 0); return 0;
}
static void rzv_spi_setfrequency(struct rzv_spi_priv_s *priv, unsigned frequency) { priv->actual = frequency; }
static void rzv_spi_setbitorder(struct rzv_spi_priv_s *priv, bool order) { (void)priv; (void)order; }
static size_t rzv_spi_wordsize(struct rzv_spi_priv_s *priv) { return priv->nbits / 8; }
static uint32_t rzv_spi_send(struct spi_dev_s *dev, uint32_t word) { (void)dev; return word; }
static int rzv_spi_dma_exchange(struct rzv_spi_priv_s *priv, const void *tx, void *rx, size_t size) {
  (void)priv; (void)tx;
  ++chunks;
  if (chunks == failure) return -EIO;
  if (rx) memset(rx, 0x42, size);
  return 0;
}
''' + EXTRACT.definition(source, 'struct spi_dev_s *rzv_spibus_initialize(')
        code += EXTRACT.definition(source, 'static void rzv_spi_exchange(struct spi_dev_s *dev,\n')
        code += r'''
int main(void) {
  failure = 1;
  assert(rzv_spibus_initialize(0) == NULL);
  assert(!g_spi0_priv.initialized && !writes && !clock_count && !sem_count && !lock_count);
  failure = 2;
  assert(rzv_spibus_initialize(0) == NULL);
  assert(!writes && !clock_count && !sem_count && !lock_count);
  failure = 0;
  assert(rzv_spibus_initialize(0) == &g_spi0_priv.spidev);
  assert(g_spi0_priv.initialized && writes && clock_count == 1 && sem_count == 1 && !lock_count);
  int previous_writes = writes;
  assert(rzv_spibus_initialize(0) == &g_spi0_priv.spidev && writes == previous_writes);
  unsigned char rx[768];
  for (failure = 1; failure <= 2; ++failure) {
    memset(rx, 0xcc, sizeof(rx)); chunks = 0;
    rzv_spi_exchange(&g_spi0_priv.spidev, NULL, rx, sizeof(rx));
    assert(chunks == failure);
    for (size_t i = 0; i < sizeof(rx); ++i)
      assert(rx[i] == (i < (size_t)(failure - 1) * 256 ? 0x42 : 0xcc));
  }
  g_spi0_priv.nbits = 32; chunks = 0;
  rzv_spi_exchange(&g_spi0_priv.spidev, NULL, NULL, SIZE_MAX);
  assert(chunks == 0);
}
'''
        compile_run(code)

    def test_failed_ipcc_registration_detaches_watcher_and_retries(self):
        source = (ARCH / 'rzv_ipc_ipcc.c').read_text()
        code = PRELUDE + r'''
#define FAR
struct ipcc_lower_s { int ops, chan; void *upper; };
struct rzv_ipcc_state_s { struct ipcc_lower_s lower; bool registered, watcher_attached; };
static struct rzv_ipcc_state_s g_rzv_ipcc;
static int g_rzv_ipcc_ops, g_rzv_ipcc_lock, watchers, failure, notifications;
static void rzv_ipcc_rxnotify(void *arg) { (void)arg; }
static int rzv_rpmsg_initialize(void (*callback)(void *), void *arg) {
  (void)callback; (void)arg; ++watchers; return 0;
}
static void rzv_rpmsg_detach(void) { --watchers; }
static int rzv_ipcc_cleanup(struct ipcc_lower_s *lower);
static int ipcc_register(struct ipcc_lower_s *lower) {
  if (failure == 2) rzv_ipcc_cleanup(lower);
  return failure ? -ENOMEM : 0;
}
static void nxmutex_lock(int *lock) { (void)lock; }
static void nxmutex_unlock(int *lock) { (void)lock; }
static void rzv_ipcc_buffer_notify(struct rzv_ipcc_state_s *state, void *upper) {
  (void)state; (void)upper; ++notifications;
}
''' + EXTRACT.definition(source, 'static int rzv_ipcc_cleanup(').replace('dmb ish', '')
        code += EXTRACT.definition(source, 'int rzv_ipcc_initialize(')
        code += r'''
int main(void) {
  failure = 1;
  assert(rzv_ipcc_initialize() == -ENOMEM && watchers == 0 && !g_rzv_ipcc.registered);
  failure = 2;
  assert(rzv_ipcc_initialize() == -ENOMEM && watchers == 0 && !g_rzv_ipcc.registered);
  failure = 0;
  assert(rzv_ipcc_initialize() == 0 && watchers == 1 && notifications == 1);
  assert(rzv_ipcc_initialize() == 0 && watchers == 1 && notifications == 1);
}
'''
        compile_run(code)

    def test_icu_detach_serializes_occupancy_and_teardown(self):
        source = (ARCH / 'rzv_icu.c').read_text()
        code = PRELUDE + r'''
#define RZV_INTC_SEL_SPI_BASE 100
#define RZV_INTC_SEL_SLOT_COUNT 4
typedef unsigned irqstate_t;
static struct { void *handler, *arg; } g_icu_handlers[4];
static int g_icu_slot, critical, disabled, detached, routed;
static irqstate_t enter_critical_section(void) { assert(!critical); critical = 1; return 0; }
static void leave_critical_section(irqstate_t flags) { (void)flags; assert(critical); critical = 0; }
static void up_disable_irq(int irq) { (void)irq; assert(critical); ++disabled; }
static void irq_detach(int irq) { (void)irq; assert(critical); ++detached; }
static int rzv_icu_set_event(int slot, int event) { (void)slot; (void)event; assert(critical); ++routed; return 0; }
''' + EXTRACT.definition(source, 'int rzv_icu_detach(')
        code += r'''
int main(void) {
  assert(rzv_icu_detach(99) == -EINVAL && !critical);
  assert(rzv_icu_detach(100) == -ENOENT && !critical);
  g_icu_handlers[0].handler = (void *)1; g_icu_handlers[3].handler = (void *)1;
  g_icu_slot = 4;
  assert(rzv_icu_detach(100) == 0 && !critical && disabled == 1 && detached == 1 && routed == 1);
  assert(g_icu_slot == 4 && g_icu_handlers[0].handler == NULL);
  assert(rzv_icu_detach(103) == 0 && g_icu_slot == 0 && !critical);
}
'''
        compile_run(code)

    def test_sci_spi_deadline_scales_and_rejects_overflow(self):
        source = (ARCH / 'rzv_sci_spi.c').read_text()
        code = PRELUDE + r'''
#define CLOCKS_PER_SEC 100
#define SCI_SPI_TIMEOUT_MS 1000
''' + EXTRACT.definition(source, 'static int sci_spi_timeout_ticks(')
        code += r'''
int main(void) {
  uint32_t ticks = 123;
  assert(sci_spi_timeout_ticks(1, 1000000, &ticks) == 0 && ticks == 101);
  assert(sci_spi_timeout_ticks(100000, 100000, &ticks) == 0 && ticks == 900);
  assert(sci_spi_timeout_ticks(0, 100000, &ticks) == 0 && ticks == 100);
  ticks = 123;
  assert(sci_spi_timeout_ticks(SIZE_MAX, 1, &ticks) == -ERANGE && ticks == 123);
  assert(sci_spi_timeout_ticks(UINT32_MAX, 1, &ticks) == -ERANGE && ticks == 123);
  assert(sci_spi_timeout_ticks(1, 0, &ticks) == -EINVAL && ticks == 123);
}
'''
        compile_run(code)
        self.assertIn('nxsem_tickwait_uninterruptible', source)
        exchange = EXTRACT.definition(source, 'static void sci_spi_exchange(struct spi_dev_s *dev,\n')
        self.assertRegex(exchange, r'(?s)if \(ret < 0\).*?invalid transfer deadline')
        self.assertNotIn('clock_gettime(', exchange)
        self.assertIn('if (ret < 0)', exchange[exchange.index('nxsem_tickwait_uninterruptible'):])

    def test_clock_packed_monitors_and_reset_polarity(self):
        source = (ARCH / 'rzv_clock.c').read_text()
        headers = '\n'.join(re.sub(r'^\s*#\s*include[^\n]*$', '', (ARCH / name).read_text(), flags=re.M)
                            for name in ('hardware/rzv_cpg.h', 'rzv_clock.h'))
        code = PRELUDE + '#define ARM_DSB() ((void)0)\n#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))\n' + headers
        code += r'''
static uint32_t clocks[16], resets[16];
static uint32_t rzv_cpg_getreg(uintptr_t address) {
  if (address >= RZV_CPG_CLKMON(0) && address <= RZV_CPG_CLKMON(15))
    return clocks[(address - RZV_CPG_CLKMON(0)) / 4];
  assert(address >= RZV_CPG_RSTMON(0) && address <= RZV_CPG_RSTMON(15));
  return resets[(address - RZV_CPG_RSTMON(0)) / 4];
}
'''
        for signature in ('static int rzv_cpg_sci_channel(', 'static void rzv_cpg_reset_mapping(',
                          'static void rzv_cpg_clock_span(', 'int rzv_clock_get_status('):
            code += EXTRACT.definition(source, signature)
        code += r'''
static void check(uint32_t id, unsigned clock_start, unsigned clocks_count,
                  unsigned reset_start, unsigned reset_count) {
  struct rzv_clock_status_s status;
  memset(clocks, 0, sizeof(clocks)); memset(resets, 0, sizeof(resets));
  for (unsigned i = 0; i < clocks_count; ++i)
    clocks[(clock_start + i) / 32] |= 1u << ((clock_start + i) % 32);
  assert(rzv_clock_get_status(id, &status) == 0);
  assert(status.enabled && !status.reset_asserted);
  clocks[clock_start / 32] &= ~(1u << (clock_start % 32));
  assert(rzv_clock_get_status(id, &status) == 0 && !status.enabled);
  for (unsigned i = 0; i < reset_count; ++i) {
    unsigned g = reset_start + i - 15;
    resets[g / 32] |= 1u << (g % 32);
    assert(rzv_clock_get_status(id, &status) == 0 && status.reset_asserted);
  }
  assert(status.domain == RZV_CPG_DOMAIN(id) && status.bit == RZV_CPG_BIT(id));
}
int main(void) {
  check(RZV_CPG_CLK_DMAC, 0, 5, 49, 5);
  check(RZV_CPG_CLK_SCI0, 93, 5, 129, 2);
  check(RZV_CPG_CLK_SCI9, 138, 5, 147, 2);
  check(RZV_CPG_CLK_SPI0, 84, 3, 123, 2);
  check(RZV_CPG_CLK_GTM0, 67, 1, 109, 1);
  check(RZV_CPG_CLK_CANFD, 156, 3, 161, 2);
  check(RZV_CPG_CLK_SCIF0, 143, 1, 149, 1);
  check(RZV_CPG_CLK_ICU, 5, 1, 54, 1);
  struct rzv_clock_status_s status;
  assert(rzv_clock_get_status(RZV_CPG_CLK_DMAC, NULL) == -EINVAL);
  assert(rzv_clock_get_status(25u << 16, &status) == -EINVAL);
  assert(rzv_clock_get_status((1u << 16) | 16u, &status) == -EINVAL);
}
'''
        compile_run(code)

    def test_private_timer_tick_uses_quarter_cpu_clock(self):
        source = (ARCH / 'rzv_timerisr.c').read_text()
        kconfig = (ARCH / 'Kconfig').read_text()
        option = re.search(r'^config RZV_CR8_PERIPHCLK_DIV\n(?:[ \t].*\n|\n)*?(?=^config )',
                           kconfig, re.M).group()
        self.assertRegex(option, r'\n\s+default 4\n')
        block = re.search(r'^#ifndef CONFIG_RZV_CR8_PERIPHCLK_DIV\n.*?'
                          r'^#define TIMER_PERIPHCLK_RUNTIME\(\) \\\n[^\n]*\n',
                          source, re.M | re.S).group()
        code = PRELUDE + r'''
#define CLOCKS_PER_SEC 1000u
#define TIMER_PRESCALER 0u
static uint32_t rzv_get_cpu_frequency(void) { return 800000000u; }
''' + block + r'''
int main(void) {
  uint32_t periphclk = TIMER_PERIPHCLK_RUNTIME();
  assert(periphclk == 200000000u);
  assert((periphclk / (TIMER_PRESCALER + 1) / CLOCKS_PER_SEC) - 1 == 199999u);
}
'''
        compile_run(code)

    def test_timer_pending_reload_preserves_order(self):
        source = (ARCH / 'rzv_timerisr.c').read_text()
        code = PRELUDE + r'''
#include <time.h>
#define USEC_PER_SEC 1000000u
#define USEC_PER_TICK 10000u
#define NSEC_PER_USEC 1000u
#define TIMER_PERIPHCLK_RUNTIME() 1000000u
#define TIMER_PRESCALER 0u
#define RZV_PRIVATE_TIMER_PTISR 1
#define RZV_PRIVATE_TIMER_PTCR 2
#define PRIVATE_TIMER_PTISR_FLAG 1
static uint32_t g_timer_load_value = 9999;
typedef unsigned irqstate_t;
static unsigned sequence, index_value;
static const uint32_t values[][4] = {{0, 1, 0, 0}, {1, 9998, 1, 0}, {0, 0, 1, 9999}, {0, 9998, 0, 0}};
static clock_t tick_value;
static uint32_t getreg32(unsigned address) { (void)address; return values[sequence][index_value++]; }
static clock_t clock_systime_ticks(void) { return tick_value; }
static irqstate_t spin_lock_irqsave(void *lock) { (void)lock; return 0; }
static void spin_unlock_irqrestore(void *lock, irqstate_t flags) { (void)lock; (void)flags; }
''' + EXTRACT.definition(source, 'int up_timer_gettime(')
        code += r'''
int main(void) {
  struct timespec times[4];
  for (sequence = 0; sequence < 4; ++sequence) {
    index_value = 0; tick_value = sequence == 3 ? 11 : 10;
    assert(up_timer_gettime(&times[sequence]) == 0);
    assert(index_value <= 4);
  }
  assert(times[0].tv_nsec == 109998000);
  assert(times[1].tv_nsec == 110001000);
  assert(times[2].tv_nsec == 110000000);
  assert(times[3].tv_nsec == 110001000);
  assert(times[1].tv_nsec > times[0].tv_nsec);
  assert(times[2].tv_nsec > times[0].tv_nsec);
  assert(times[3].tv_nsec == times[1].tv_nsec);
}
'''
        compile_run(code)


if __name__ == '__main__':
    unittest.main()
