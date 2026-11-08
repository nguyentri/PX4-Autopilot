#!/usr/bin/env python3
"""Run the production native RSPI polled path and bit-rate search on a model.

Covers two behaviours taken from FSP r_spi_b:
- After an overrun/underrun flag or a timeout, the polled path stops the
  controller (SPE off), resets both FIFOs, clears every status flag and
  restores SPCR, so a word left in the RX FIFO is never returned as the
  reply to the next transfer.  A failed exchange stops at the failing word.
- The bit-rate divider is the smallest one at or above clk / request with
  the smallest BRDV (R_SPI_B_CalculateBitrate), so the achieved SCK never
  exceeds the request; requests below clk / 4096 are rejected.
"""
from pathlib import Path
import importlib.util
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
SOURCE = ARCH / 'rzv_spi.c'
SPEC = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)

MODEL = r'''
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-function"
#define SPI_TIMEOUT_CYCLES 8u
#define spierr(...) ((void)0)
#define spiinfo(...) ((void)0)
typedef int irqstate_t;
static irqstate_t enter_critical_section(void) { return 0; }
static void leave_critical_section(irqstate_t f) { (void)f; }

struct spi_dev_s { int unused; };
struct rzv_spi_config_s { int port; };
struct rzv_spi_priv_s {
  struct spi_dev_s spidev;
  const struct rzv_spi_config_s *config;
  uint32_t frequency, actual;
  unsigned nbits;
};

/* Register model: loopback shifter with an RX FIFO, injectable error flags
 * and a "dead" mode in which no word is ever received.
 */

static uint32_t spcr, spcr3, spcmd0, spsr_err, clk_hz = 200000000u;
static uint32_t rxq[32]; static unsigned rx_n;
static bool dead;
static unsigned spdr_writes, reg_writes, fifo_resets, spsrc_all;
static uint32_t last_spsrc;

static uint32_t rzv_spi_get_clk_hz(struct rzv_spi_priv_s *p) { return clk_hz; }
static void rzv_spi_setbitorder(struct rzv_spi_priv_s *p, bool lsb) {}

static uint32_t rzv_spi_getreg32(struct rzv_spi_priv_s *p, unsigned off)
{
  switch (off)
    {
    case RZV_SPI_SPCR_OFFSET: return spcr;
    case RZV_SPI_SPCR3_OFFSET: return spcr3;
    case RZV_SPI_SPCMD0_OFFSET: return spcmd0;
    case RZV_SPI_SPSR_OFFSET: return spsr_err | SPI_SPSR_SPTEF;
    case RZV_SPI_SPRFSR_OFFSET: return rx_n;
    case RZV_SPI_SPDR_OFFSET:
      {
        uint32_t w;
        assert(rx_n > 0);
        w = rxq[0];
        memmove(rxq, rxq + 1, --rx_n * sizeof(rxq[0]));
        return w;
      }
    default: assert(!"unexpected register read"); return 0;
    }
}

static void rzv_spi_putreg32(struct rzv_spi_priv_s *p, unsigned off,
                             uint32_t v)
{
  ++reg_writes;
  switch (off)
    {
    case RZV_SPI_SPCR_OFFSET: spcr = v; break;
    case RZV_SPI_SPCR3_OFFSET: spcr3 = v; break;
    case RZV_SPI_SPCMD0_OFFSET: spcmd0 = v; break;
    case RZV_SPI_SPDR_OFFSET:
      ++spdr_writes;
      if (!dead) { rxq[rx_n++] = v; }
      break;
    case RZV_SPI_SPFCR_OFFSET:
      if (v & SPI_SPFCR_SPFRST)
        {
          assert((spcr & SPI_SPCR_SPE) == 0); /* FIFO reset only while stopped */
          rx_n = 0; ++fifo_resets;
        }
      break;
    case RZV_SPI_SPSRC_OFFSET:
      last_spsrc = v;
      if (v == SPI_SPSRC_ALL_CLEAR) { ++spsrc_all; }
      if (v & SPI_SPSRC_OVRFC) { spsr_err &= ~SPI_SPSR_OVRF; }
      if (v & SPI_SPSRC_UDRFC) { spsr_err &= ~SPI_SPSR_UDRF; }
      break;
    default: assert(!"unexpected register write");
    }
}
'''

MAIN = r'''
static const struct rzv_spi_config_s cfg = { 0 };

static void reset(struct rzv_spi_priv_s *p)
{
  memset(p, 0, sizeof(*p)); p->config = &cfg; p->nbits = 8;
  spcr = SPI_SPCR_SPE | SPI_SPCR_MSTR; spcr3 = 0; spcmd0 = 0; spsr_err = 0;
  rx_n = 0; dead = false; spdr_writes = reg_writes = 0;
  fifo_resets = spsrc_all = 0; last_spsrc = 0;
}

static uint32_t rate(uint32_t spbr, uint32_t brdv)
{
  return clk_hz / (2u * (spbr + 1u) * (1u << brdv));
}

/* Fastest achievable rate that does not exceed the request (brute force). */

static uint32_t best_rate(uint32_t req)
{
  uint32_t best = 0;
  for (uint32_t b = 0; b < 4; b++)
    for (uint32_t s = 0; s < 256; s++)
      {
        uint64_t div = 2ull * (s + 1u) * (1u << b);
        if ((uint64_t)req * div >= clk_hz && rate(s, b) > best) best = rate(s, b);
      }
  return best;
}

static void check_rate(struct rzv_spi_priv_s *p, uint32_t req, uint32_t want)
{
  uint32_t spbr, brdv;
  rzv_spi_setfrequency(p, req);
  spbr = (spcr3 & SPI_SPCR3_SPBR_MASK) >> SPI_SPCR3_SPBR_SHIFT;
  brdv = (spcmd0 & SPI_SPCMD_BRDV_MASK) >> SPI_SPCMD_BRDV_SHIFT;
  assert(p->actual == want && p->actual == rate(spbr, brdv));
  assert(p->frequency == req && (spcr & SPI_SPCR_SPE));
}

int main(void)
{
  struct rzv_spi_priv_s p;
  uint8_t tx[4] = { 1, 2, 3, 4 }, rx[4];
  uint32_t rd = 0x12345678u;

  /* Vendor ceil divisor at P4CLK 200 MHz. */
  reset(&p);
  check_rate(&p, 24000000u, 20000000u);
  assert(((spcr3 & SPI_SPCR3_SPBR_MASK) >> SPI_SPCR3_SPBR_SHIFT) == 4);
  check_rate(&p, 8000000u, 7692307u);
  check_rate(&p, 7000000u, 6666666u);
  check_rate(&p, 1000000u, 1000000u);
  check_rate(&p, 400000000u, 100000000u); /* above clk / 2: fastest */
  check_rate(&p, 48829u, 48828u);         /* divider 4096: BRDV 3, SPBR 255 */
  assert((spcmd0 & SPI_SPCMD_BRDV_MASK) == SPI_SPCMD_BRDV(3));

  /* Below clk / 4096 and zero: rejected, nothing changes. */
  reg_writes = 0;
  rzv_spi_setfrequency(&p, 48827u);
  rzv_spi_setfrequency(&p, 0);
  assert(reg_writes == 0 && p.actual == 48828u && p.frequency == 48829u);

  /* Never faster than requested, and the fastest such setting. */
  for (uint64_t req = 48829u; req <= 120000000u; req = req * 1013u / 1000u + 1u)
    {
      rzv_spi_setfrequency(&p, (uint32_t)req);
      assert(p.actual <= req && p.actual == best_rate((uint32_t)req));
    }

  /* A word left in the RX FIFO by an overrun is flushed, not returned. */
  reset(&p);
  rxq[0] = 0x55; rx_n = 1; spsr_err = SPI_SPSR_OVRF;
  assert(rzv_spi_poll_word(&p, 0xa5, &rd) == -EIO && rd == 0x12345678u);
  assert(fifo_resets == 1 && spsrc_all == 1 && rx_n == 0 && spsr_err == 0);
  assert(spcr == (SPI_SPCR_SPE | SPI_SPCR_MSTR)); /* SPCR restored */
  rzv_spi_exchange(&p.spidev, tx, rx, 4);
  assert(memcmp(rx, tx, 4) == 0 && spdr_writes == 4);

  /* A successful word clears the RX-full and data-ready flags. */
  assert(last_spsrc == (SPI_SPSRC_SPRFC | SPI_SPSRC_SPDRFC));

  /* Timeout: recovered, exchange stops at the first word, RX reads ones. */
  reset(&p); dead = true; memset(rx, 0, sizeof(rx));
  rzv_spi_exchange(&p.spidev, tx, rx, 4);
  assert(spdr_writes == 1 && fifo_resets == 1 && spsrc_all == 1);
  for (int i = 0; i < 4; i++) assert(rx[i] == 0xff);
  assert(rzv_spi_send(&p.spidev, 0x5a) == UINT32_MAX);
  assert(spdr_writes == 2 && fifo_resets == 2);

  /* Transmit-only exchange also stops at the first failure. */
  reset(&p); dead = true;
  rzv_spi_exchange(&p.spidev, tx, NULL, 4);
  assert(spdr_writes == 1 && fifo_resets == 1);

  /* 16-bit words still mask the 32-bit SPDR value. */
  reset(&p); p.nbits = 16;
  assert(rzv_spi_send(&p.spidev, 0xabcd1234u) == 0x1234u);
  return 0;
}
'''


class SpiRecoveryAndBitrate(unittest.TestCase):
    def test_polled_recovery_and_vendor_bitrate_search(self):
        source = SOURCE.read_text()
        header = re.sub(r'^\s*#\s*include[^\n]*$', '',
                        (ARCH / 'hardware/rzv_spi.h').read_text(), flags=re.M)
        limits = ''.join(m.group(0) + '\n' for m in
                         re.finditer(r'^#define SPI_CLK_\w+\s+\S+', source, re.M))
        self.assertEqual(limits.count('#define'), 3)
        functions = ''.join(B.EXTRACT.definition(source, sig) for sig in (
            'static void rzv_spi_setfrequency(struct rzv_spi_priv_s *priv,\n',
            'static void rzv_spi_recover(',
            'static int rzv_spi_poll_word(',
            'static uint32_t rzv_spi_send(struct spi_dev_s *dev, uint32_t wd)\n',
            'static void rzv_spi_exchange(struct spi_dev_s *dev,\n'))
        code = B.PRELUDE + header + limits + MODEL + functions + MAIN
        B.compile_run(code)


if __name__ == '__main__':
    unittest.main()
