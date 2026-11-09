#!/usr/bin/env python3
"""Drive the production CAN-FD channel setup, RX FIFO, channel error and
global error handlers against a register model with the manual's
write-0-clear and read-only semantics, and level interrupt requests."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'


def definition(source, signature):
    start = source.rindex(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


FUNCTIONS = ('static int rzv_canfd_ch_init(', 'static int rzv_canfd_rx_isr(int irq',
             'static int rzv_canfd_err_isr(int irq', 'static int rzv_canfd_glerr_isr(int irq')

# Register model.  CFDGERFL.MES and CFDFMSTS are derived from the per-FIFO
# RFMLT flags; RFIF/RFMLT/RFFIF and the channel error flags clear only on a
# written 0; RFEMP/RFFLL/RFMC are read only.  Hooks inject a hardware event
# between the driver's read and write of a status register.
MODEL = r'''
static uint8_t mem[0x10000];
static unsigned int frames[8], received, erfl_reads;
static bool arrive_before_clear[8], raise_epf_after_read;

static uint32_t *cell(uintptr_t a)
{
  assert(a >= RZV_CANFD_BASE && a - RZV_CANFD_BASE < sizeof(mem));
  return (uint32_t *)(mem + (a - RZV_CANFD_BASE));
}

static uint32_t rfsts(unsigned int n) { return *cell(RZV_CANFD_CFDRFSTS(n)); }

static uint32_t lost_fifos(void)
{
  uint32_t lost = 0;
  for (unsigned int n = 0; n < 8; n++)
    if (rfsts(n) & CANFD_RFSTS_RFMLT) lost |= 1u << n;
  return lost;
}

static void store_frame(unsigned int n)
{
  frames[n]++;
  *cell(RZV_CANFD_CFDRFSTS(n)) = (rfsts(n) & ~CANFD_RFSTS_RFEMP) |
                                 CANFD_RFSTS_RFIF;
}

static uint32_t getreg32(uintptr_t a)
{
  if (a == RZV_CANFD_CFDFMSTS) return lost_fifos();
  if (a == RZV_CANFD_CFDGERFL)
    return (*cell(a) & ~CANFD_GERFL_MES) | (lost_fifos() ? CANFD_GERFL_MES : 0);
  uint32_t v = *cell(a);
  for (unsigned int ch = 0; ch < 6; ch++)
    if (a == RZV_CANFD_CFDC_ERFL(ch))
      {
        ++erfl_reads;
        if (raise_epf_after_read)
          {
            raise_epf_after_read = false;
            *cell(a) |= CANFD_CFDC_ERFL_EPF;
          }
      }
  return v;
}

static void putreg32(uint32_t v, uintptr_t a)
{
  for (unsigned int n = 0; n < 8; n++)
    {
      if (a == RZV_CANFD_CFDRFSTS(n))
        {
          if (arrive_before_clear[n])
            {
              arrive_before_clear[n] = false;
              store_frame(n);
              *cell(a) |= CANFD_RFSTS_RFMLT;
            }
          assert((v & ~CANFD_RFSTS_W0C_MASK) == 0);
          *cell(a) &= ~(CANFD_RFSTS_W0C_MASK & ~v);
          return;
        }
      if (a == RZV_CANFD_CFDRFPCTR(n))
        {
          assert(frames[n] > 0);
          if (--frames[n] == 0) *cell(RZV_CANFD_CFDRFSTS(n)) |= CANFD_RFSTS_RFEMP;
          return;
        }
    }
  for (unsigned int ch = 0; ch < 6; ch++)
    if (a == RZV_CANFD_CFDC_ERFL(ch))
      {
        *cell(a) &= ~(CANFD_CFDC_ERFL_FLAGS_MASK & ~v);
        return;
      }
  if (a == RZV_CANFD_CFDGERFL)
    {
      *cell(a) &= ~(~CANFD_GERFL_MES & ~v);
      return;
    }
  *cell(a) = v;
}

static void can_receive(struct can_dev_s *dev, struct can_hdr_s *hdr,
                        uint8_t *data)
{
  ++received;
}

static int rzv_canfd_wait_mode(uintptr_t reg, uint32_t mask, uint32_t value)
{
  return 0;
}

'''

# Level request of the global error interrupt, re-dispatched until it drops.
HELPERS = r'''
/* Global error request: DEF, MES and CMPOF with their enables set. */

static bool glerr_line(void)
{
  return (getreg32(RZV_CANFD_CFDGERFL) &
          (CANFD_GERFL_DEF | CANFD_GERFL_MES | CANFD_GERFL_CMPOF)) != 0;
}

static int service_glerr(void)
{
  int calls = 0;
  while (glerr_line())
    {
      assert(++calls < 4);   /* level request must drop after one pass */
      rzv_canfd_glerr_isr(0, NULL, NULL);
    }
  return calls;
}
'''


def build(main):
    source = (ARCH / 'rzv_canfd.c').read_text()
    hw = re.sub(r'^\s*#\s*include[^\n]*$', '', (ARCH / 'hardware/rzv_canfd.h').read_text(),
                flags=re.M)
    timing = '\n'.join(re.findall(r'^#define [ND]CFG_\w+[^\n]*', source, re.M))
    dlc = re.search(r'static const uint8_t g_dlc_to_bytes\[16\] =\n\{.*?\};', source, re.S).group()
    struct = re.search(r'struct rzv_canfd_s\n\{.*?\n\};', source, re.S).group()
    code = r'''#include <assert.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define CONFIG_CAN_EXTID 1
#define CONFIG_CAN_FD 1
#define CAN_MAXDATALEN 64
#define OK 0
#define canerr(...) ((void)0)
#define RZV_CANFD_NUM_CHANNELS 6
struct can_dev_s { int unused; };
struct can_hdr_s
{
  uint32_t ch_id; uint8_t ch_dlc; uint8_t ch_rtr; uint8_t ch_extid;
  uint8_t ch_edl; uint8_t ch_brs; uint8_t ch_esi;
};
''' + hw + '\n' + timing + '\n' + dlc + '\n' + struct + r'''
#define rzv_rd32(a) getreg32(a)
#define rzv_wr32(v, a) putreg32(v, a)
static struct rzv_canfd_s *g_priv_by_fifo[RZV_CANFD_NUM_CHANNELS];
''' + MODEL + ''.join(definition(source, sig) for sig in FUNCTIONS) + HELPERS + main
    return code


def run(code):
    with tempfile.TemporaryDirectory(prefix='rzv2h-canfd-error-') as directory:
        path = Path(directory)
        (path / 'test.c').write_text(code)
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-Wno-unused-function',
                        '-Wno-unused-variable', '-Wno-unused-but-set-variable',
                        str(path / 'test.c'), '-o', str(path / 'test')], check=True)
        subprocess.run([str(path / 'test')], check=True, timeout=30)


class CanfdErrorInterrupts(unittest.TestCase):
    def test_channel_setup_programs_delay_compensation_and_error_enables(self):
        run(build(r'''
int main(void)
{
  for (unsigned int ch = 0; ch < 6; ch++)
    {
      struct rzv_canfd_s priv;
      memset(&priv, 0, sizeof(priv));
      priv.channel = ch;
      *cell(RZV_CANFD_CFDC2_FDCFG(ch)) = CANFD_CFDC2_FDCFG_FDOE |
        CANFD_CFDC2_FDCFG_CLOE | CANFD_CFDC2_FDCFG_REFE | CANFD_CFDC2_FDCFG_TDCOC;
      *cell(RZV_CANFD_CFDC_CTR(ch)) = CANFD_CFDC_CTR_BEIE;
      assert(rzv_canfd_ch_init(&priv) == 0);
      uint32_t fdcfg = *cell(RZV_CANFD_CFDC2_FDCFG(ch));
      assert(fdcfg == ((16u << CANFD_CFDC2_FDCFG_TDCO_SHIFT) | CANFD_CFDC2_FDCFG_TDCE |
                       CANFD_CFDC2_FDCFG_ESIC | 1u));
      uint32_t ctr = *cell(RZV_CANFD_CFDC_CTR(ch));
      uint32_t want = CANFD_CFDC_CTR_EWIE | CANFD_CFDC_CTR_EPIE | CANFD_CFDC_CTR_BOEIE |
                      CANFD_CFDC_CTR_BORIE | CANFD_CFDC_CTR_OLIE;
      assert((ctr & want) == want);
      assert((ctr & (CANFD_CFDC_CTR_BEIE | CANFD_CFDC_CTR_BLIE | CANFD_CFDC_CTR_ALIE)) == 0);
    }
  return 0;
}
'''))

    def test_message_lost_request_drops_after_one_global_error_pass(self):
        run(build(r'''
int main(void)
{
  for (unsigned int n = 0; n < 8; n++) *cell(RZV_CANFD_CFDRFSTS(n)) = CANFD_RFSTS_RFEMP;

  /* Overruns on FIFOs 1 and 4, FIFO 1 still has an unserviced RFIF. */

  *cell(RZV_CANFD_CFDRFSTS(1)) = CANFD_RFSTS_RFMLT | CANFD_RFSTS_RFIF;
  *cell(RZV_CANFD_CFDRFSTS(4)) |= CANFD_RFSTS_RFMLT;
  *cell(RZV_CANFD_CFDGERFL) = CANFD_GERFL_DEF;
  assert(glerr_line());
  assert(service_glerr() == 1);
  assert(lost_fifos() == 0 && getreg32(RZV_CANFD_CFDGERFL) == 0);
  assert(rfsts(1) == CANFD_RFSTS_RFIF);
  assert(rfsts(4) == CANFD_RFSTS_RFEMP);

  /* A lone payload-overflow flag is cleared without touching any FIFO. */

  *cell(RZV_CANFD_CFDGERFL) = CANFD_GERFL_CMPOF;
  assert(service_glerr() == 1 && rfsts(1) == CANFD_RFSTS_RFIF);
  return 0;
}
'''))

    def test_channel_error_clear_keeps_a_flag_raised_after_the_read(self):
        run(build(r'''
int main(void)
{
  struct rzv_canfd_s priv;
  memset(&priv, 0, sizeof(priv));
  priv.channel = 2;
  uint32_t crc = 0x1234u << CANFD_CFDC_ERFL_CRCREG_SHIFT;
  *cell(RZV_CANFD_CFDC_ERFL(2)) = crc | CANFD_CFDC_ERFL_EWF | CANFD_CFDC_ERFL_BEF;
  raise_epf_after_read = true;
  rzv_canfd_err_isr(0, NULL, &priv);
  assert(*cell(RZV_CANFD_CFDC_ERFL(2)) == (crc | CANFD_CFDC_ERFL_EPF));
  rzv_canfd_err_isr(0, NULL, &priv);
  assert(*cell(RZV_CANFD_CFDC_ERFL(2)) == crc);
  return 0;
}
'''))

    def test_rx_flag_clear_rechecks_for_a_frame_stored_before_the_clear(self):
        run(build(r'''
int main(void)
{
  static struct rzv_canfd_s priv;
  for (unsigned int n = 0; n < 8; n++) *cell(RZV_CANFD_CFDRFSTS(n)) = CANFD_RFSTS_RFEMP;
  g_priv_by_fifo[3] = &priv;

  /* One frame queued; a second arrives (overrunning) just before the RFIF
   * clear.  Both are delivered and the overrun flag survives the clear.
   */

  store_frame(3);
  arrive_before_clear[3] = true;
  rzv_canfd_rx_isr(0, NULL, NULL);
  assert(received == 2 && frames[3] == 0);
  assert(rfsts(3) == (CANFD_RFSTS_RFEMP | CANFD_RFSTS_RFMLT));

  /* Budget exhausted with frames left: RFIF stays set to re-enter. */

  received = 0;
  for (int i = 0; i < 10; i++) store_frame(3);
  rzv_canfd_rx_isr(0, NULL, NULL);
  assert(received == 8 && frames[3] == 2 && (rfsts(3) & CANFD_RFSTS_RFIF));
  rzv_canfd_rx_isr(0, NULL, NULL);
  assert(received == 10 && frames[3] == 0);
  assert(rfsts(3) == (CANFD_RFSTS_RFEMP | CANFD_RFSTS_RFMLT));
  return 0;
}
'''))


if __name__ == '__main__':
    unittest.main()
