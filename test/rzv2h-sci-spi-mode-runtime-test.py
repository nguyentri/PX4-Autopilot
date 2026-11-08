#!/usr/bin/env python3
"""Execute SCI-SPI production code against R01UH1032EJ0140 timing rules."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / 'platforms/nuttx/NuttX/nuttx'
ARCH = NUTTX / 'arch/arm/src/rzv'


def without_includes(source):
    return re.sub(r'^\s*#\s*include[^\n]*$', '', source, flags=re.M)


def definition(source, name):
    match = re.search(rf'^[^\n;{{}}]*\b{name}\s*\([^;{{}}]*\)\s*{{', source, re.M)
    if match is None:
        raise AssertionError(f'No production definition for {name}')
    start = match.end() - 1
    depth = 0
    for end in range(start, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if depth == 0:
            return source[match.start():end + 1] + '\n'
    raise AssertionError(f'Unclosed production definition for {name}')


def harness():
    source = (ARCH / 'rzv_sci_spi.c').read_text()
    code = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <assert.h>
#include <limits.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#define OK 0
#define CONFIG_RZV_SCI_SPI 1
#define CONFIG_RZV2H_SAMPLE_TEST_API 1
#define CLOCKS_PER_SEC 100
#define ARM_DSB() ((void)0)
#define DEBUGASSERT(x) assert(x)
#define spiinfo(...) ((void)0)
#define spierr(...) ((void)0)
#define spiwarn(...) ((void)0)
#define FAR
#define CODE
#define TEST_UNUSED __attribute__((unused))
typedef unsigned irqstate_t;
typedef int mutex_t;
typedef struct { int count; } sem_t;
enum spi_mode_e { SPIDEV_MODE0, SPIDEV_MODE1, SPIDEV_MODE2, SPIDEV_MODE3 };
struct spi_dev_s { int unused; };
'''
    for name in ('hardware/rzv_sci.h', 'hardware/rzv_sci_spi.h',
                 'hardware/rzv_cpg.h', 'rzv_clock.h', 'rzv_sci_spi_internal.h'):
        code += without_includes((ARCH / name).read_text())
    code += re.search(r'static uint32_t g_sample_transfers\[[^;]*;', source).group() + '\n'
    code += r'''
struct model_s {
  uint32_t registers[256];
  uint8_t tx_fifo[32], rx_fifo[128], tx_log[128];
  size_t tx_count, rx_count, shifted, written;
  unsigned posts, waits, starts, delays, irq_byte_writes, config_writes;
  unsigned ccr3_zero_writes, ccr3_premode_writes;
  unsigned cesr_byte_reads, cesr_active_reads, cesr_stop_reads;
  bool tend, final_edge, pending_txi, seeded;
  bool te_tie_together, pre_mode, reset_before_mode;
};
static struct model_s hw[10];
static struct rzv_sci_spi_priv_s priv[10];
static unsigned current, depth, scenario, irq_order;
static bool check_init, enable_failure, stop_failure, hold_tend, mask_failure, fast_frame;
static bool strict_ccr0, strict_cesr, strict_tdr;
static uint32_t pclk = 100000000;
static size_t expected_words;
static const uint8_t *expected_tx;
static uint8_t *expected_rx;
static void deliver_txi(void);
static unsigned address_channel(uintptr_t address) {
  assert(address >= RZV_SCI0_BASE && address < RZV_SCI0_BASE + 10u * 0x400u);
  unsigned channel = (address - RZV_SCI0_BASE) / 0x400u;
  assert(channel == current); return channel;
}
uint32_t rzv_clock_get_rate(enum rzv_clock_id_e clock_id) {
  assert(clock_id == RZV_CLOCK_P5CLK); return pclk;
}
static void TEST_UNUSED up_udelay(unsigned delay) {
  assert(delay >= (6000000u + (pclk ? pclk : 100000000u) - 1u) /
                  (pclk ? pclk : 100000000u));
  ++hw[current].delays;
  struct model_s *m = &hw[current];
  if (m->written > m->shifted && !m->final_edge) m->tend = false;
  if (fast_frame && m->tx_count && !priv[current].ntxwords) {
    /* A 25-MHz byte finishes during the one-microsecond sync interval. */
    assert(expected_words == 1 && m->tx_count == 1);
    uint8_t data = m->tx_fifo[0]; m->tx_count = 0;
    m->tx_log[m->shifted++] = data; m->rx_fifo[m->rx_count++] = data ^ 0xa5;
    m->final_edge = m->tend = true;
  }
}
static irqstate_t TEST_UNUSED enter_critical_section(void) { return depth++; }
static void TEST_UNUSED leave_critical_section(irqstate_t flags) {
  assert(depth == flags + 1); --depth;
  if (!depth && hw[current].pending_txi) deliver_txi();
}
static int nxsem_reset(sem_t *sem, int count) {
  assert(sem == &priv[current].sem_isr && count == 0); sem->count = 0; return 0;
}
static int nxsem_post(sem_t *sem) {
  assert(sem == &priv[current].sem_isr);
  assert(priv[current].state == SCI_SPI_STATE_ERROR || hw[current].final_edge);
  assert(++hw[current].posts == 1); ++sem->count; return 0;
}
static uint8_t cesr_value(struct model_s *m) {
  if (m->registers[RZV_SCI_CCR0_OFFSET / 4] & (SCI_CCR0_TE | SCI_CCR0_RE))
    return enable_failure ? 0 : SCI_CESR_TIST | SCI_CESR_RIST;
  return stop_failure ? SCI_CESR_TIST | SCI_CESR_RIST : 0;
}
static uint8_t TEST_UNUSED getreg8(uintptr_t address) {
  struct model_s *m = &hw[address_channel(address)];
  unsigned offset = (address - RZV_SCI0_BASE) % 0x400u;
  assert(offset == RZV_SCI_CESR_OFFSET);
  ++m->cesr_byte_reads;
  if (m->registers[RZV_SCI_CCR0_OFFSET / 4] & (SCI_CCR0_TE | SCI_CCR0_RE))
    ++m->cesr_active_reads;
  else ++m->cesr_stop_reads;
  return cesr_value(m);
}
static void TEST_UNUSED putreg8(uint8_t value, uintptr_t address) {
  struct model_s *m = &hw[address_channel(address)];
  unsigned offset = (address - RZV_SCI0_BASE) % 0x400u;
  assert(offset == RZV_SCI_CCR0_OFFSET + 2u);
  assert((value & ~((SCI_CCR0_TIE | SCI_CCR0_RIE | SCI_CCR0_TEIE) >> 16)) == 0);
  uint32_t old = m->registers[RZV_SCI_CCR0_OFFSET / 4];
  uint32_t updated = (old & ~UINT32_C(0x00ff0000)) | ((uint32_t)value << 16);
  m->registers[RZV_SCI_CCR0_OFFSET / 4] = updated; ++m->irq_byte_writes;
  if (!(old & SCI_CCR0_TEIE) && (updated & SCI_CCR0_TEIE) && m->tend)
    rzv_sci_spi_tei_isr(0, NULL, &priv[current]);
}
static uint32_t getreg32(uintptr_t address) {
  struct model_s *m = &hw[address_channel(address)];
  unsigned offset = (address - RZV_SCI0_BASE) % 0x400u;
  if (offset == RZV_SCI_CCR0_OFFSET && mask_failure)
    return m->registers[offset / 4] | SCI_CCR0_RIE;
  if (offset == RZV_SCI_CSR_OFFSET) {
    /* TDRE is sticky until CFCLR; TDR writes do not bound FIFO space. */
    return (m->seeded ? SCI_CSR_TDRE : 0) | (m->tend ? SCI_CSR_TEND : 0) |
           m->registers[offset / 4];
  }
  if (offset == RZV_SCI_FTSR_OFFSET) return m->tx_count;
  if (offset == RZV_SCI_FRSR_OFFSET) return m->rx_count << SCI_FRSR_R_SHIFT;
  if (offset == RZV_SCI_RDR_OFFSET) {
    assert(m->rx_count > 0);
    uint8_t data = m->rx_fifo[0];
    memmove(m->rx_fifo, m->rx_fifo + 1, --m->rx_count); return data;
  }
  if (offset == RZV_SCI_CESR_OFFSET) {
    assert(!strict_cesr); /* CESR is byte-only, manual p.2624. */
    return cesr_value(m);
  }
  return m->registers[offset / 4];
}
static void putreg32(uint32_t value, uintptr_t address) {
  struct model_s *m = &hw[address_channel(address)];
  unsigned offset = (address - RZV_SCI0_BASE) % 0x400u;
  if (offset == RZV_SCI_CCR2_OFFSET || offset == RZV_SCI_CCR3_OFFSET)
    ++m->config_writes;
  if (offset == RZV_SCI_CCR3_OFFSET) {
    if (value == 0) ++m->ccr3_zero_writes;
    else if ((value & SCI_CCR3_MOD_MASK) != SCI_CCR3_MOD_SPI) ++m->ccr3_premode_writes;
  }
  if (offset == RZV_SCI_TDR_OFFSET) {
    if (strict_tdr) assert((value & UINT32_C(0xfffffe00)) == UINT32_C(0xfffffe00));
    assert(m->tx_count < 32); /* Manual p.2643: NFIFO - FTSR.T. */
    assert(m->written < expected_words);
    assert((value & 0xff) == (expected_tx ? expected_tx[m->written] : 0xff));
    m->tx_fifo[m->tx_count++] = value; ++m->written;
    if (!hold_tend) m->tend = false;
    return;
  }
  if (offset == RZV_SCI_CFCLR_OFFSET) {
    if (value & SCI_CFCLR_TDREC) m->seeded = false;
    m->registers[RZV_SCI_CSR_OFFSET / 4] &= ~value;
    return;
  }
  if (offset == RZV_SCI_FCR_OFFSET) {
    assert(!(m->registers[RZV_SCI_CCR0_OFFSET / 4] & (SCI_CCR0_TE | SCI_CCR0_RE)));
    if (value & SCI_FCR_TFRST) m->tx_count = 0;
    if (value & SCI_FCR_RFRST) m->rx_count = 0;
    if (value & (SCI_FCR_TFRST | SCI_FCR_RFRST)) m->reset_before_mode = true;
    value &= ~(SCI_FCR_TFRST | SCI_FCR_RFRST);
  }
  if (offset == RZV_SCI_CCR3_OFFSET && check_init) {
    assert(!(m->registers[RZV_SCI_CCR0_OFFSET / 4] & (SCI_CCR0_TE | SCI_CCR0_RE)));
    if ((value & SCI_CCR3_MOD_MASK) == SCI_CCR3_MOD_SPI &&
        (m->registers[offset / 4] & SCI_CCR3_MOD_MASK) != SCI_CCR3_MOD_SPI)
      assert(m->pre_mode && m->reset_before_mode && m->delays);
    else m->pre_mode = true;
  }
  uint32_t old = m->registers[offset / 4];
  if (strict_ccr0 && offset == RZV_SCI_CCR0_OFFSET &&
      (old & (SCI_CCR0_TE | SCI_CCR0_RE)))
    assert((value & (SCI_CCR0_TE | SCI_CCR0_RE)) == 0); /* p.2602 note1. */
  m->registers[offset / 4] = value;
  if (offset == RZV_SCI_CCR0_OFFSET && !(old & SCI_CCR0_TE) && (value & SCI_CCR0_TE)) {
    ++m->starts;
    m->te_tie_together = (value & SCI_CCR0_TIE) != 0;
    assert(priv[current].state == SCI_SPI_STATE_BUSY);
    assert(priv[current].ntxwords == expected_words && priv[current].nrxwords == expected_words);
    assert(priv[current].txbuffer == expected_tx && priv[current].rxbuffer == expected_rx);
    assert(priv[current].sem_isr.count == 0);
    if (m->te_tie_together) { m->pending_txi = true; if (!depth) deliver_txi(); }
  }
  if (offset == RZV_SCI_CCR0_OFFSET && !(old & SCI_CCR0_TEIE) &&
      (value & SCI_CCR0_TEIE) && m->tend)
    rzv_sci_spi_tei_isr(0, NULL, &priv[current]);
}
static void deliver_txi(void) {
  struct model_s *m = &hw[current];
  m->pending_txi = false; m->seeded = true;
  rzv_sci_spi_txi_isr(0, NULL, &priv[current]);
}
static void stale_irqs(void) {
  rzv_sci_spi_txi_isr(0, NULL, &priv[current]);
  rzv_sci_spi_rxi_isr(0, NULL, &priv[current]);
  rzv_sci_spi_tei_isr(0, NULL, &priv[current]);
  rzv_sci_spi_eri_isr(0, NULL, &priv[current]);
}
static int nxsem_tickwait_uninterruptible(sem_t *sem, uint32_t ticks) {
  struct model_s *m = &hw[current];
  assert(sem == &priv[current].sem_isr && ticks > 0 && ticks <= INT32_MAX); ++m->waits;
  if (!m->te_tie_together) return -ETIMEDOUT;
  if (scenario == 2) {
    m->registers[RZV_SCI_CSR_OFFSET / 4] |= SCI_CSR_ORER;
    rzv_sci_spi_eri_isr(0, NULL, &priv[current]);
  }
  for (unsigned step = 0; step < 2048 && !sem->count; ++step) {
    if (scenario == 1 && m->shifted == 2) return -ETIMEDOUT;
    if (!m->tx_count) return -ETIMEDOUT;
    assert((m->registers[RZV_SCI_CCR0_OFFSET / 4] & (SCI_CCR0_TE | SCI_CCR0_RE)) ==
           (SCI_CCR0_TE | SCI_CCR0_RE));
    uint8_t data = m->tx_fifo[0];
    memmove(m->tx_fifo, m->tx_fifo + 1, --m->tx_count);
    m->tx_log[m->shifted++] = data;
    m->rx_fifo[m->rx_count++] = data ^ 0xa5;
    bool last = m->shifted == expected_words;
    unsigned threshold = (m->registers[RZV_SCI_FCR_OFFSET / 4] & SCI_FCR_RTRG_MASK) >> SCI_FCR_RTRG_SHIFT;
    bool rx_pending = m->rx_count >= (threshold ? threshold : 1);
    if (rx_pending && (!last || irq_order == 0)) {
      rzv_sci_spi_rxi_isr(0, NULL, &priv[current]);
      if (last) assert(!m->posts); /* CPHA=0 RXI precedes the final edge. */
    }
    if (last) {
      assert(!m->posts);
      if (scenario == 3) return -ETIMEDOUT; /* Last edge never arrives. */
      m->final_edge = m->tend = true;
      if (irq_order == 0) {
        if (rx_pending && (m->registers[RZV_SCI_CCR0_OFFSET / 4] & SCI_CCR0_RIE))
          rzv_sci_spi_rxi_isr(0, NULL, &priv[current]);
        if (m->registers[RZV_SCI_CCR0_OFFSET / 4] & SCI_CCR0_TEIE)
          rzv_sci_spi_tei_isr(0, NULL, &priv[current]);
      } else {
        if (m->registers[RZV_SCI_CCR0_OFFSET / 4] & SCI_CCR0_TEIE)
          rzv_sci_spi_tei_isr(0, NULL, &priv[current]);
        if (rx_pending) rzv_sci_spi_rxi_isr(0, NULL, &priv[current]);
      }
    } else if (m->tx_count <= 8 && (m->registers[RZV_SCI_CCR0_OFFSET / 4] & SCI_CCR0_TIE)) deliver_txi();
  }
  if (!sem->count) return -ETIMEDOUT;
  stale_irqs();
  assert(m->posts == 1); --sem->count; return 0;
}
'''
    code += without_includes((ARCH / 'rzv_sci_spi_clock.c').read_text())
    for name in ('rzv_sci_spi_sync_delay', 'sci_spi_quiesce', 'sci_spi_hardware_idle',
                 'sci_spi_ccr3_format', 'sci_spi_write_ccr3', 'sci_spi_hw_configure',
                 'sci_spi_setfrequency', 'sci_spi_setmode', 'sci_spi_timeout_ticks',
                 'sci_spi_exchange'):
        if re.search(rf'^(?:static )?[^;\n]*\b{name}\(', source, re.M):
            code += definition(source, name)
    code += without_includes((ARCH / 'rzv_sci_spi_isr.c').read_text())
    code += r'''
static void setup(unsigned channel, enum spi_mode_e mode) {
  current = channel;
  memset(&hw[channel], 0, sizeof(hw[channel]));
  memset(&priv[channel], 0, sizeof(priv[channel]));
  priv[channel].channel = channel; priv[channel].base = RZV_SCI0_BASE + channel * 0x400;
  priv[channel].frequency = 1000000; priv[channel].actual = 1000000;
  priv[channel].nbits = 8; priv[channel].mode = mode;
  priv[channel].state = SCI_SPI_STATE_IDLE; hw[channel].tend = true;
  assert(sci_spi_hw_configure(&priv[channel]) == 0);
}
static void run_transfer(size_t words, bool rx_only, bool tx_only) {
  uint8_t tx[128], rx[128];
  for (size_t i = 0; i < sizeof(tx); ++i) tx[i] = 0x31 + i;
  memset(rx, 0xcc, sizeof(rx));
  expected_words = words; expected_tx = rx_only ? NULL : tx; expected_rx = tx_only ? NULL : rx;
  priv[current].sem_isr.count = 3; /* Stale posts from a prior exchange. */
  struct model_s *m = &hw[current];
  unsigned old_zero = m->ccr3_zero_writes, old_premode = m->ccr3_premode_writes;
  uint32_t old_ccr2 = m->registers[RZV_SCI_CCR2_OFFSET / 4];
  sci_spi_exchange(&priv[current].dev, expected_tx, expected_rx, words);
  /* A failed or timed-out stop clears CCR3 (FM, so TEND sets) and then
   * reprograms the same format, mode and rate; a clean one leaves CCR3.
   */
  uint32_t ccr3 = m->registers[RZV_SCI_CCR3_OFFSET / 4];
  assert(ccr3 == (sci_spi_ccr3_format(&priv[current]) | SCI_CCR3_MOD_SPI));
  assert(m->registers[RZV_SCI_CCR2_OFFSET / 4] == old_ccr2);
  if (scenario == 0) assert(m->ccr3_zero_writes == old_zero && m->ccr3_premode_writes == old_premode);
  else assert(m->ccr3_zero_writes == old_zero + 1 && m->ccr3_premode_writes == old_premode + 1);
  assert(m->te_tie_together && m->starts == 1);
  assert(!m->registers[RZV_SCI_CCR0_OFFSET / 4] && priv[current].state == SCI_SPI_STATE_IDLE);
  assert(!m->tx_count && !m->rx_count && priv[current].sem_isr.count == 0);
  if (scenario == 0) {
    assert(m->final_edge && m->posts == 1 && m->written == words && m->shifted == words);
    if (strict_ccr0) assert(m->irq_byte_writes >= 3);
    if (strict_cesr) assert(m->cesr_byte_reads >= 4 && m->cesr_active_reads >= 1 && m->cesr_stop_reads >= 3);
    if (!tx_only) for (size_t i = 0; i < words; ++i) assert(rx[i] == ((rx_only ? 0xff : tx[i]) ^ 0xa5));
  } else if (scenario == 2) assert(m->posts == 1);
  else assert(!m->posts);
  uint8_t saved[128]; memcpy(saved, rx, sizeof(rx));
  unsigned old_posts = m->posts; stale_irqs();
  assert(m->posts == old_posts && !memcmp(saved, rx, sizeof(rx)));
  assert(!depth);
}
int main(int argc, char **argv) {
  assert(argc == 2);
  strict_ccr0 = strict_cesr = strict_tdr = true;
  if (!strcmp(argv[1], "reg-access-ccr0")) strict_cesr = strict_tdr = false;
  if (!strcmp(argv[1], "reg-access-cesr")) strict_ccr0 = strict_tdr = false;
  if (!strcmp(argv[1], "reg-access-tdr")) strict_ccr0 = strict_cesr = false;
  if (!strcmp(argv[1], "baud") || !strcmp(argv[1], "init")) {
    check_init = !strcmp(argv[1], "init");
    for (unsigned ch = 0; ch < 10; ++ch) for (unsigned mode = 0; mode < 4; ++mode) {
      setup(ch, mode);
      uint32_t ccr2 = hw[ch].registers[RZV_SCI_CCR2_OFFSET / 4];
      uint32_t brr = (ccr2 >> 8) & 255, cks = (ccr2 >> 20) & 3;
      uint32_t manual_rate = pclk / ((ccr2 & (1u << 4) ? 2u : 4u) * (1u << (2u * cks)) * (brr + 1));
      assert(manual_rate == priv[ch].actual && manual_rate == 1000000);
      assert(!(ccr2 & (1u << 16)));
      uint32_t ccr3 = hw[ch].registers[RZV_SCI_CCR3_OFFSET / 4];
      assert((ccr3 & 3) == ((mode >> 1) * 2 + (mode & 1)));
      assert(sci_spi_setfrequency(&priv[ch].dev, 2500000) == 2500000);
      ccr2 = hw[ch].registers[RZV_SCI_CCR2_OFFSET / 4];
      assert(!(ccr2 & (1u << 16)) && (ccr2 & (1u << 4)));
      /* Vendor round-down: 7.5 MHz runs at the next slower rate (BRR 6). */
      assert(sci_spi_setfrequency(&priv[ch].dev, 7500000) == 7142857);
      assert(((hw[ch].registers[RZV_SCI_CCR2_OFFSET / 4] >> 8) & 255) == 6);
      uint32_t saved_rate = priv[ch].actual;
      uint32_t saved_ccr2 = hw[ch].registers[RZV_SCI_CCR2_OFFSET / 4];
      assert(sci_spi_setfrequency(&priv[ch].dev, 30000000) == saved_rate);
      assert(hw[ch].registers[RZV_SCI_CCR2_OFFSET / 4] == saved_ccr2);
      /* setmode drops MOD before writing CPOL/CPHA, then selects SPI. */
      unsigned premode = hw[ch].ccr3_premode_writes;
      sci_spi_setmode(&priv[ch].dev, (mode + 1) % 4);
      assert(hw[ch].ccr3_premode_writes == premode + 1);
      ccr3 = hw[ch].registers[RZV_SCI_CCR3_OFFSET / 4];
      assert((ccr3 & SCI_CCR3_MOD_MASK) == SCI_CCR3_MOD_SPI && (ccr3 & SCI_CCR3_FM));
      assert((ccr3 & 3) == (((mode + 1) % 4 >> 1) * 2 + ((mode + 1) % 4 & 1)));
    }
  } else if (!strcmp(argv[1], "fractional")) {
    uint8_t brr = 0, cks = 0, mddr = 0;
    assert(rzv_sci_spi_calc_bitrate(100000000, 3000000, &brr, &cks, &mddr) == 0);
    assert(mddr == 0);
    assert(rzv_sci_spi_calc_bitrate(100000000, 7500000, &brr, &cks, &mddr) == 0);
    assert(brr == 6 && cks == 0 && mddr == 0);
    /* Slowest setting is P5 / (2 * 4^3 * 256): 3052 Hz fits, 3051 Hz not. */
    assert(rzv_sci_spi_calc_bitrate(100000000, 3052, &brr, &cks, &mddr) == 0);
    assert(brr == 255 && cks == 3);
    brr = cks = mddr = 77;
    assert(rzv_sci_spi_calc_bitrate(100000000, 3051, &brr, &cks, &mddr) == -EINVAL);
    assert(brr == 77 && cks == 77 && mddr == 77);
  } else if (!strcmp(argv[1], "early-rx")) {
    setup(0, SPIDEV_MODE0); hw[0].tend = false;
    priv[0].state = SCI_SPI_STATE_BUSY;
    rzv_sci_spi_rxi_isr(0, NULL, &priv[0]);
    assert(!hw[0].posts && priv[0].state == SCI_SPI_STATE_BUSY);
    hw[0].final_edge = hw[0].tend = true;
    rzv_sci_spi_tei_isr(0, NULL, &priv[0]); stale_irqs();
    assert(hw[0].posts == 1 && priv[0].state == SCI_SPI_STATE_DONE);
  } else if (!strcmp(argv[1], "stale-busy")) {
    setup(0, SPIDEV_MODE0); hw[0].tend = false;
    priv[0].state = SCI_SPI_STATE_BUSY; priv[0].ntxwords = priv[0].nrxwords = 1;
    rzv_sci_spi_tei_isr(0, NULL, &priv[0]);
    rzv_sci_spi_eri_isr(0, NULL, &priv[0]);
    assert(!hw[0].posts && priv[0].state == SCI_SPI_STATE_BUSY);
  } else if (!strcmp(argv[1], "tei-before-late-rx")) {
    uint8_t received = 0;
    setup(0, SPIDEV_MODE1); hw[0].tend = hw[0].final_edge = true;
    priv[0].state = SCI_SPI_STATE_BUSY; priv[0].nrxwords = 1;
    priv[0].rxbuffer = &received;
    hw[0].registers[RZV_SCI_CCR0_OFFSET / 4] = SCI_CCR0_TE | SCI_CCR0_RE | SCI_CCR0_TEIE | SCI_CCR0_RIE;
    rzv_sci_spi_tei_isr(0, NULL, &priv[0]);
    assert(priv[0].state == SCI_SPI_STATE_BUSY && !hw[0].posts);
    hw[0].rx_fifo[0] = 0x5a; hw[0].rx_count = 1;
    rzv_sci_spi_rxi_isr(0, NULL, &priv[0]); stale_irqs();
    assert(received == 0x5a && hw[0].posts == 1 && priv[0].state == SCI_SPI_STATE_DONE);
  } else if (!strcmp(argv[1], "fast-frame")) {
    fast_frame = true;
    for (unsigned ch = 0; ch < 10; ++ch) for (unsigned mode = 0; mode < 4; ++mode) {
      setup(ch, mode);
      assert(sci_spi_setfrequency(&priv[ch].dev, 25000000) == 25000000);
      run_transfer(1, false, false);
    }
  } else if (!strncmp(argv[1], "setter-", 7)) {
    bool frequency = strstr(argv[1], "frequency") != NULL;
    bool mask = strstr(argv[1], "mask") != NULL;
    for (unsigned ch = 0; ch < 10; ++ch) for (unsigned mode = 0; mode < 4; ++mode) {
      setup(ch, mode);
      /* Enter quiescence with hardware active, then fail the real cleanup. */
      hw[ch].registers[RZV_SCI_CCR0_OFFSET / 4] = SCI_CCR0_TE | SCI_CCR0_RE | SCI_CCR0_RIE;
      priv[ch].state = SCI_SPI_STATE_BUSY;
      mask_failure = mask; stop_failure = !mask;
      assert(sci_spi_quiesce(&priv[ch]) == -ETIMEDOUT);
      assert((hw[ch].registers[RZV_SCI_CCR0_OFFSET / 4] & (SCI_CCR0_TE | SCI_CCR0_RE)) ||
             cesr_value(&hw[ch]));
      for (unsigned error = 0; error < 2; ++error) {
        /* IDLE/ERROR software state alone cannot establish hardware idle. */
        priv[ch].state = error ? SCI_SPI_STATE_ERROR : SCI_SPI_STATE_IDLE;
        uint32_t old_rate = priv[ch].actual, old_frequency = priv[ch].frequency;
        enum spi_mode_e old_mode = priv[ch].mode;
        uint32_t old_ccr2 = hw[ch].registers[RZV_SCI_CCR2_OFFSET / 4];
        uint32_t old_ccr3 = hw[ch].registers[RZV_SCI_CCR3_OFFSET / 4];
        unsigned old_writes = hw[ch].config_writes, old_reads = hw[ch].cesr_byte_reads;
        if (frequency) assert(sci_spi_setfrequency(&priv[ch].dev, 2500000) == old_rate);
        else sci_spi_setmode(&priv[ch].dev, (mode + 1) % 4);
        assert(priv[ch].actual == old_rate && priv[ch].frequency == old_frequency);
        assert(priv[ch].mode == old_mode && hw[ch].config_writes == old_writes);
        assert(hw[ch].registers[RZV_SCI_CCR2_OFFSET / 4] == old_ccr2);
        assert(hw[ch].registers[RZV_SCI_CCR3_OFFSET / 4] == old_ccr3);
        assert(hw[ch].cesr_byte_reads - old_reads <= SCI_SPI_CESR_TIMEOUT);
      }
      mask_failure = stop_failure = false;
      assert(sci_spi_quiesce(&priv[ch]) == 0);
      assert(sci_spi_setfrequency(&priv[ch].dev, 2500000) == 2500000);
      sci_spi_setmode(&priv[ch].dev, (mode + 1) % 4);
      assert(priv[ch].mode == (enum spi_mode_e)((mode + 1) % 4));
    }
  } else if (!strcmp(argv[1], "stop-timeout") || !strcmp(argv[1], "mask-timeout")) {
    setup(9, SPIDEV_MODE0);
    mask_failure = !strcmp(argv[1], "mask-timeout");
    stop_failure = !mask_failure;
    uint8_t data = 1;
    sci_spi_exchange(&priv[9].dev, &data, &data, 1);
    assert(!hw[9].starts && !hw[9].waits && !hw[9].posts && !hw[9].tx_count);
    assert(priv[9].state == SCI_SPI_STATE_IDLE);
    stop_failure = mask_failure = false; run_transfer(1, false, false);
  } else if (!strcmp(argv[1], "fifo-capacity")) {
    uint8_t tx[65]; memset(tx, 0x31, sizeof(tx));
    setup(0, SPIDEV_MODE0);
    expected_words = 65; expected_tx = tx;
    priv[0].state = SCI_SPI_STATE_BUSY; priv[0].txbuffer = tx;
    priv[0].ntxwords = priv[0].nrxwords = 65;
    hw[0].registers[RZV_SCI_CCR0_OFFSET / 4] = SCI_CCR0_TE | SCI_CCR0_RE | SCI_CCR0_TIE;
    deliver_txi();
    assert(hw[0].written > 0 && hw[0].written <= 32 && priv[0].ntxwords + hw[0].written == 65);
  } else {
    scenario = !strcmp(argv[1], "error") ? 2 : !strcmp(argv[1], "timeout") ? 1 : !strcmp(argv[1], "last-edge-timeout") ? 3 : !strcmp(argv[1], "enable-timeout") ? 4 : 0;
    hold_tend = !strcmp(argv[1], "tend-startup");
    const size_t lengths[] = {1, 7, 8, 9, 31, 32, 33, 65};
    for (unsigned ch = 0; ch < 10; ++ch) for (unsigned mode = 0; mode < 4; ++mode)
      for (irq_order = 0; irq_order < 2; ++irq_order)
        for (unsigned i = 0; i < (scenario ? 1 : sizeof(lengths)/sizeof(lengths[0])); ++i) {
          setup(ch, mode);
          enable_failure = scenario == 4;
          run_transfer(scenario == 3 ? 8 : scenario ? 9 : lengths[i], false, false);
          if (scenario) {
            enable_failure = false;
            hw[ch].posts = hw[ch].waits = hw[ch].starts = 0;
            hw[ch].written = hw[ch].shifted = 0;
            hw[ch].final_edge = false;
            unsigned saved_scenario = scenario; scenario = 0;
            run_transfer(9, false, false);
            scenario = saved_scenario;
          }
        }
    if (scenario == 0) {
      setup(9, SPIDEV_MODE3); run_transfer(9, true, false);
      setup(9, SPIDEV_MODE0); run_transfer(9, false, true);
    }
  }
  return 0;
}
'''
    return code


class SciSpiModeRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='rzv2h-sci-spi-mode-')
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        path = directory / 'mode.c'
        path.write_text(harness())
        cls.binary = directory / 'mode'
        result = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                 str(path), '-o', str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def case(self, scenario):
        result = subprocess.run([str(self.binary), scenario], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_frequency_changes_wait_for_hardware_idle_after_failed_cleanup(self):
        for fault in ('mask', 'stop'):
            with self.subTest(fault=fault): self.case(f'setter-frequency-{fault}')
    def test_mode_changes_wait_for_hardware_idle_after_failed_cleanup(self):
        for fault in ('mask', 'stop'):
            with self.subTest(fault=fault): self.case(f'setter-mode-{fault}')
    def test_interrupt_updates_do_not_rewrite_active_te_re_ones(self): self.case('reg-access-ccr0')
    def test_cesr_reads_are_byte_only_in_every_phase(self): self.case('reg-access-cesr')
    def test_tdr_writes_keep_reserved_and_unused_upper_ones(self): self.case('reg-access-tdr')
    def test_programmed_rate_matches_manual_bgdm_formula(self): self.case('baud')
    def test_spi_never_selects_fractional_modulation(self): self.case('fractional')
    def test_first_enable_can_deliver_txi_immediately(self):
        self.case('startup')
        self.case('fast-frame')
    def test_rxi_cannot_complete_before_final_sck_edge(self): self.case('early-rx')
    def test_stale_tei_and_eri_do_not_abort_active_transfer(self): self.case('stale-busy')
    def test_sticky_tdre_cannot_overfill_fifo(self): self.case('fifo-capacity')
    def test_initialization_prepares_polarity_and_fifo_before_mode(self): self.case('init')
    def test_all_instances_modes_lengths_and_both_irq_orders(self): self.case('full')
    def test_error_cleanup_ignores_late_irqs(self): self.case('error')
    def test_timeout_cleanup_ignores_late_irqs(self): self.case('timeout')
    def test_missing_final_edge_cannot_wake_success(self): self.case('last-edge-timeout')
    def test_initial_tend_clears_before_tei_is_armed(self): self.case('tend-startup')
    def test_late_receive_irq_completes_after_tei_once(self): self.case('tei-before-late-rx')
    def test_activation_timeout_cleans_up_and_allows_retry(self): self.case('enable-timeout')
    def test_stop_timeout_rejects_transfer_and_allows_retry(self):
        self.case('stop-timeout')
        self.case('mask-timeout')


if __name__ == '__main__':
    unittest.main()
