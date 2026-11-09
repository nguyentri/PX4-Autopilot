#!/usr/bin/env python3
"""Drive the production RIIC master state machine against a register-level
bus model: bit-rate selection, reset-protected setup, START/restart/STOP
requests, 7- and 10-bit addressing, short reads, error and timeout paths."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / 'platforms/nuttx/NuttX/nuttx'
ARCH = NUTTX / 'arch/arm/src/rzv'


def definition(source, signature):
    start = source.rindex(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


def header(path):
    return re.sub(r'^\s*#\s*include[^\n]*$', '', path.read_text(), flags=re.M)


FUNCTIONS = (
    'static int rzv_i2c_bitrate(', 'static void rzv_i2c_hwsetup(',
    'static int rzv_i2c_set_frequency(', 'static void rzv_i2c_abort(',
    'static void rzv_i2c_complete(', 'static void rzv_i2c_sendstart(',
    'static void rzv_i2c_sendstop(', 'static void rzv_i2c_sendrestart(',
    'static uint8_t rzv_i2c_disable_tie(', 'static void rzv_i2c_wait_tend(',
    'static void rzv_i2c_msg_setup(', 'static bool rzv_i2c_next_segment(',
    'static void rzv_i2c_end_message(', 'static uint64_t rzv_i2c_read_remaining(',
    'static void rzv_i2c_set_nack(', 'static void rzv_i2c_set_wait(',
    'static int rzv_i2c_rxi_interrupt(', 'static int rzv_i2c_txi_interrupt(',
    'static int rzv_i2c_tei_interrupt(', 'static int rzv_i2c_sti_interrupt(',
    'static int rzv_i2c_err_interrupt(', 'static int rzv_i2c_stp_interrupt(',
    'static int rzv_i2c_transfer(struct i2c_master_s *dev,\n',
)

# Register-level RIIC bus model.  Bytes the master puts on the bus and the
# conditions it generates are logged as tokens; the slave answers reads from
# slave_data and can NACK, lose arbitration, time out or release the bus at
# a chosen transmit byte.  Interrupts are dispatched from the flag/enable
# levels: fixed sources are level inputs, TXI/RXI are edge inputs.
MODEL = r'''
enum { T_S = 0x100, T_SR, T_P, T_NK, T_RA = 0x200, T_RN = 0x300 };
static uint8_t regs[256];
static bool in_reset, rx_mode, after_start, pending_sp, pending_rs, rx_nacked;
static bool txi_prev, rxi_prev, tei_first, hang;
static int resets, udelays, bbsy_polls, isr_posts, unlocks, tx_count, rx_count;
static int nack_at = -1, al_at = -1, tmo_at = -1, stop_at = -1;
static int tokens[128], ntokens, isr_calls[8];
static uint8_t slave_data[16];
static struct rzv_i2c_priv_s *active;

static void token(int t) { assert(ntokens < 128); tokens[ntokens++] = t; }

static void bus_start(int t)
{
  token(t);
  regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_START | RIIC_ICSR2_TDRE;
  regs[RZV_RIIC_ICCR2_OFFSET] |= RIIC_ICCR2_BBSY | RIIC_ICCR2_MST | RIIC_ICCR2_TRS;
  rx_mode = false; after_start = true; txi_prev = false;
}

static void bus_stop(void)
{
  token(T_P);
  regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_STOP;
  regs[RZV_RIIC_ICSR2_OFFSET] &= ~(RIIC_ICSR2_TDRE | RIIC_ICSR2_TEND | RIIC_ICSR2_RDRF);
  regs[RZV_RIIC_ICCR2_OFFSET] = 0;
  rx_mode = false;
}

static int nxsem_post(int *sem)
{
  if (sem == &active->sem_isr) ++isr_posts; else ++unlocks;
  return 0;
}

static int nxsem_reset(int *sem, int value) { isr_posts = 0; return 0; }
static int rzv_i2c_acquire(struct rzv_i2c_priv_s *p) { return 0; }
static void up_udelay(int us) { ++udelays; }
static void rzv_icu_clear_irq(int irq) {}

static uint8_t rzv_i2c_getreg(struct rzv_i2c_priv_s *p, unsigned off)
{
  if (off == RZV_RIIC_ICCR2_OFFSET && bbsy_polls > 0)
    {
      --bbsy_polls;
      return regs[off] | RIIC_ICCR2_BBSY;
    }

  if (off != RZV_RIIC_ICDRR_OFFSET) return regs[off];

  /* Reading ICDRR releases the held bus: the requested condition follows,
   * otherwise the next byte is clocked in with the current ACKBT.
   */

  uint8_t value = regs[off];
  assert(rx_mode);
  regs[RZV_RIIC_ICSR2_OFFSET] &= ~RIIC_ICSR2_RDRF;
  rxi_prev = false;
  if (pending_sp) { pending_sp = false; bus_stop(); return value; }
  if (pending_rs) { pending_rs = false; bus_start(T_SR); return value; }
  assert(!rx_nacked);
  uint8_t data = slave_data[rx_count++];
  if (regs[RZV_RIIC_ICMR3_OFFSET] & RIIC_ICMR3_ACKBT)
    {
      /* NACK timing needs SCL held after the final byte. */

      assert(regs[RZV_RIIC_ICMR3_OFFSET] & RIIC_ICMR3_WAIT);
      rx_nacked = true; token(T_RN | data);
    }
  else token(T_RA | data);
  regs[off] = data;
  regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_RDRF;
  return value;
}

static void rzv_i2c_putreg(struct rzv_i2c_priv_s *p, unsigned off, uint8_t val)
{
  switch (off)
    {
      case RZV_RIIC_ICCR1_OFFSET:
        if ((val & RIIC_ICCR1_IICRST) && !in_reset)
          {
            ++resets; rx_mode = pending_sp = pending_rs = rx_nacked = false;
            regs[RZV_RIIC_ICSR2_OFFSET] = 0; regs[RZV_RIIC_ICCR2_OFFSET] = 0;
          }
        in_reset = (val & RIIC_ICCR1_IICRST) != 0;
        break;
      case RZV_RIIC_ICBRL_OFFSET: case RZV_RIIC_ICBRH_OFFSET:
      case RZV_RIIC_ICMR1_OFFSET: case RZV_RIIC_ICMR2_OFFSET:
      case RZV_RIIC_ICFER_OFFSET: case RZV_RIIC_ICSER_OFFSET:
        assert(in_reset && (regs[RZV_RIIC_ICCR1_OFFSET] & RIIC_ICCR1_ICE));
        break;
      case RZV_RIIC_ICMR3_OFFSET:
        if ((val ^ regs[off]) & RIIC_ICMR3_ACKBT) assert(regs[off] & RIIC_ICMR3_ACKWP);
        break;
      case RZV_RIIC_ICSR2_OFFSET:
        regs[off] &= val; /* Flags clear on 0 after a read; 1 has no effect. */
        return;
      case RZV_RIIC_ICCR2_OFFSET:
        /* Condition requests are written alone, never read-modify-write. */

        assert(val == RIIC_ICCR2_ST || val == RIIC_ICCR2_RS || val == RIIC_ICCR2_SP);
        if (val == RIIC_ICCR2_ST)
          {
            assert(!(regs[off] & RIIC_ICCR2_BBSY) && !in_reset);
            bus_start(T_S);
          }
        else if (val == RIIC_ICCR2_RS)
          {
            assert(regs[off] & RIIC_ICCR2_MST);
            if (rx_mode) pending_rs = true; else bus_start(T_SR);
          }
        else if (regs[off] & RIIC_ICCR2_MST)
          {
            if (rx_mode) pending_sp = true; else bus_stop();
          }
        return;
      case RZV_RIIC_ICDRT_OFFSET:
        assert(!rx_mode && (regs[RZV_RIIC_ICCR2_OFFSET] & RIIC_ICCR2_TRS));
        token(val);
        regs[RZV_RIIC_ICSR2_OFFSET] &= ~(RIIC_ICSR2_TDRE | RIIC_ICSR2_TEND);
        txi_prev = false;
        if (hang) return;
        if (tx_count == al_at) { regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_AL;
          regs[RZV_RIIC_ICCR2_OFFSET] &= ~(RIIC_ICCR2_MST | RIIC_ICCR2_TRS); ++tx_count; return; }
        if (tx_count == tmo_at) { regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_TMOF; ++tx_count; return; }
        if (tx_count == stop_at) { ++tx_count; token(T_P);
          regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_STOP; regs[RZV_RIIC_ICCR2_OFFSET] = 0; return; }
        if (tx_count++ == nack_at)
          {
            token(T_NK);
            regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_NACKF | RIIC_ICSR2_TEND;
            return;
          }
        if (after_start && (val & 1))
          {
            /* Read address: receive mode, first RDRF is the dummy byte. */

            rx_mode = true; rx_nacked = false;
            regs[RZV_RIIC_ICCR2_OFFSET] &= ~RIIC_ICCR2_TRS;
            regs[RZV_RIIC_ICDRR_OFFSET] = val;
            regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_RDRF;
          }
        else regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_TDRE | RIIC_ICSR2_TEND;
        after_start = false;
        return;
      default:
        break;
    }

  regs[off] = val;
}

static int rzv_i2c_err_interrupt(int irq, void *context, void *arg);
static int rzv_i2c_stp_interrupt(int irq, void *context, void *arg);
static int rzv_i2c_sti_interrupt(int irq, void *context, void *arg);
static int rzv_i2c_tei_interrupt(int irq, void *context, void *arg);
static int rzv_i2c_rxi_interrupt(int irq, void *context, void *arg);
static int rzv_i2c_txi_interrupt(int irq, void *context, void *arg);

/* Deliver interrupts until none is pending; a level source that is never
 * cleared or masked trips the storm guard.
 */

static void run_hw(void)
{
  for (int n = 0; n < 10000; n++)
    {
      uint8_t ier = regs[RZV_RIIC_ICIER_OFFSET], sr = regs[RZV_RIIC_ICSR2_OFFSET];
      bool tei = (sr & RIIC_ICSR2_TEND) && (ier & RIIC_ICIER_TEIE);
      if (tei_first && tei) { ++isr_calls[3]; rzv_i2c_tei_interrupt(0, NULL, active); continue; }
      if (((sr & RIIC_ICSR2_AL) && (ier & RIIC_ICIER_ALIE)) ||
          ((sr & RIIC_ICSR2_TMOF) && (ier & RIIC_ICIER_TMOIE)) ||
          ((sr & RIIC_ICSR2_NACKF) && (ier & RIIC_ICIER_NAKIE)))
        { ++isr_calls[0]; rzv_i2c_err_interrupt(0, NULL, active); continue; }
      if ((sr & RIIC_ICSR2_STOP) && (ier & RIIC_ICIER_SPIE))
        { ++isr_calls[1]; rzv_i2c_stp_interrupt(0, NULL, active); continue; }
      if ((sr & RIIC_ICSR2_START) && (ier & RIIC_ICIER_STIE))
        { ++isr_calls[2]; rzv_i2c_sti_interrupt(0, NULL, active); continue; }
      if (tei) { ++isr_calls[3]; rzv_i2c_tei_interrupt(0, NULL, active); continue; }
      bool rxl = (sr & RIIC_ICSR2_RDRF) && (ier & RIIC_ICIER_RIE);
      bool txl = (sr & RIIC_ICSR2_TDRE) && (ier & RIIC_ICIER_TIE);
      bool rxe = rxl && !rxi_prev, txe = txl && !txi_prev;
      rxi_prev = rxl; txi_prev = txl;
      if (rxe) { ++isr_calls[4]; rzv_i2c_rxi_interrupt(0, NULL, active); continue; }
      if (txe) { ++isr_calls[5]; rzv_i2c_txi_interrupt(0, NULL, active); continue; }
      return;
    }

  assert(!"interrupt storm");
}

static int nxsem_timedwait_uninterruptible(int *sem, const struct timespec *ts)
{
  run_hw();
  return isr_posts > 0 ? 0 : -ETIMEDOUT;
}

/* Fresh controller at 400 kHz with the bus idle. */

static void model_reset(struct rzv_i2c_priv_s *p)
{
  memset(regs, 0, sizeof(regs)); memset(tokens, 0, sizeof(tokens));
  memset(isr_calls, 0, sizeof(isr_calls));
  in_reset = rx_mode = after_start = pending_sp = pending_rs = rx_nacked = false;
  txi_prev = rxi_prev = tei_first = hang = false;
  resets = udelays = bbsy_polls = isr_posts = unlocks = tx_count = rx_count = 0;
  nack_at = al_at = tmo_at = stop_at = -1; ntokens = 0;
  for (int i = 0; i < 16; i++) slave_data[i] = (uint8_t)(i + 1);
  memset(p, 0, sizeof(*p)); active = p;
  assert(rzv_i2c_set_frequency(p, I2C_SPEED_FAST) == 0);
  assert(resets == 1); resets = 0;
}

static void expect_tokens(const int *expected, int count)
{
  if (ntokens != count)
    {
      for (int i = 0; i < ntokens; i++) fprintf(stderr, "%#x ", tokens[i]);
      fprintf(stderr, "\n");
    }

  assert(ntokens == count);
  for (int i = 0; i < count; i++) assert(tokens[i] == expected[i]);
}

#define EXPECT(...) do { const int e_[] = {__VA_ARGS__}; \
  expect_tokens(e_, (int)(sizeof(e_) / sizeof(e_[0]))); } while (0)

static int xfer(struct rzv_i2c_priv_s *p, struct i2c_msg_s *msgs, int count)
{
  int ret = rzv_i2c_transfer(&p->dev, msgs, count);
  if (ret != -EINVAL)
    {
      assert(unlocks == 1 && p->state == RIIC_STATE_IDLE);
      assert(!regs[RZV_RIIC_ICIER_OFFSET]);
      assert(!(regs[RZV_RIIC_ICMR3_OFFSET] & RIIC_ICMR3_WAIT));
    }

  unlocks = 0;
  return ret;
}
'''


def build(main):
    """Production RIIC sources plus the bus model and a test main()."""
    source = (ARCH / 'rzv_i2c.c').read_text()
    defines = re.search(r'^#define RIIC_TIMEOUT_MS.*?^#define RIIC_ADDR_10BIT[^\n]*\n',
                        source, re.S | re.M).group()
    nuttx_i2c = (NUTTX / 'include/nuttx/i2c/i2c_master.h').read_text()
    flags = '\n'.join(re.findall(r'^#define I2C_(?:M|SPEED)_\w+\s+\w+', nuttx_i2c, re.M))
    p1clk = re.search(r'^#define RZV_CLOCK_P1CLK_HZ[^\n]*', (ARCH / 'rzv_clock.h').read_text(),
                      re.M).group()
    struct = re.search(r'struct rzv_i2c_priv_s\n\{.*?\n\};', source, re.S).group()
    code = r'''#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <time.h>
#define OK 0
#define FAR
#define i2cerr(...) ((void)0)
typedef unsigned irqstate_t;
static irqstate_t enter_critical_section(void) { return 0; }
static void leave_critical_section(irqstate_t flags) { (void)flags; }
struct i2c_master_s { int unused; };
struct i2c_msg_s { uint32_t frequency; uint16_t addr; uint16_t flags; uint8_t *buffer; ssize_t length; };
'''
    code += header(NUTTX / 'include/nuttx/nuttx.h') + header(ARCH / 'hardware/rzv_i2c.h')
    code += flags + '\n' + p1clk + '\n' + defines
    code += re.search(r'enum rzv_i2c_state_e\n\{.*?\n\};', source, re.S).group() + '\n'
    code += struct.replace('sem_t ', 'int ') + '\n'
    code += 'static int nxsem_timedwait_uninterruptible(int *sem, const struct timespec *ts);\n'
    code += 'static void rzv_i2c_msg_setup(struct rzv_i2c_priv_s *priv);\n'
    code += MODEL.split('static int rzv_i2c_err_interrupt(int irq')[0]
    for signature in FUNCTIONS:
        code += definition(source, signature)
    code += 'static int rzv_i2c_err_interrupt(int irq' + \
        MODEL.split('static int rzv_i2c_err_interrupt(int irq', 1)[1]
    return code + main


def run(code):
    with tempfile.TemporaryDirectory(prefix='rzv2h-riic-sequence-') as directory:
        path = Path(directory)
        (path / 'test.c').write_text(code)
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-Wno-unused-function',
                        str(path / 'test.c'), '-o', str(path / 'test')], check=True)
        subprocess.run([str(path / 'test')], check=True)


class RiicMasterSequence(unittest.TestCase):
    def test_bit_rate_meets_speed_mode_timing_without_exceeding_request(self):
        run(build(r'''
static void timing(uint32_t f)
{
  uint8_t cks, brh, brl;
  assert(rzv_i2c_bitrate(f, &cks, &brh, &brl) == 0);
  assert(cks <= 7 && brh <= RIIC_ICBR_MAX && brl <= RIIC_ICBR_MAX);
  if (cks == 7 && brh == 31 && brl == 31) return;
  assert(brh >= RIIC_NF_STAGES + 1 && brl >= RIIC_NF_STAGES + 1);
  double phi = (double)RIIC_PCLK_HZ / (1u << cks);
  double high = (brh + (cks ? 2 + RIIC_NF_STAGES : 3 + 3 * RIIC_NF_STAGES)) / phi;
  double low = (brl + (cks ? 2 + RIIC_NF_STAGES : 3 + RIIC_NF_STAGES)) / phi;
  double period = high + low + (RIIC_RISE_NS + RIIC_FALL_NS) * 1e-9;
  double tlow = f <= 100000 ? 4.7e-6 : f <= 400000 ? 1.3e-6 : 0.5e-6;
  double thigh = f <= 100000 ? 4.0e-6 : f <= 400000 ? 0.6e-6 : 0.26e-6;
  assert(1.0 / period <= f * (1 + 1e-9));
  assert(low + RIIC_FALL_NS * 1e-9 >= tlow * (1 - 1e-9));
  assert(high + RIIC_RISE_NS * 1e-9 >= thigh * (1 - 1e-9));
  /* The fastest legal setting is chosen: within 3 % of the request. */
  assert(1.0 / period >= f * 0.97);
}

int main(void)
{
  uint8_t cks, brh, brl;
  const uint32_t f[] = {I2C_SPEED_STANDARD, I2C_SPEED_FAST, I2C_SPEED_FAST_PLUS};
  const uint8_t expected[][3] = {{4, 27, 28}, {2, 24, 27}, {1, 16, 16}};
  for (int i = 0; i < 3; i++)
    {
      assert(rzv_i2c_bitrate(f[i], &cks, &brh, &brl) == 0);
      assert(cks == expected[i][0] && brh == expected[i][1] && brl == expected[i][2]);
    }

  assert(rzv_i2c_bitrate(0, &cks, &brh, &brl) == -EINVAL);
  assert(rzv_i2c_bitrate(I2C_SPEED_FAST_PLUS + 1, &cks, &brh, &brl) == -EINVAL);
  for (uint32_t r = 20000; r <= 1000000; r += 1000) timing(r);
  assert(rzv_i2c_bitrate(5000, &cks, &brh, &brl) == 0);
  assert(cks == 7 && brh == 31 && brl == 31);
}
'''))

    def test_setup_runs_inside_internal_reset_with_reserved_bits_and_timeout(self):
        run(build(r'''
int main(void)
{
  struct rzv_i2c_priv_s p;
  model_reset(&p);
  assert(regs[RZV_RIIC_ICCR1_OFFSET] == RIIC_ICCR1_ICE && !in_reset);
  assert(regs[RZV_RIIC_ICBRL_OFFSET] == (RIIC_ICBR_RESERVED | 27));
  assert(regs[RZV_RIIC_ICBRH_OFFSET] == (RIIC_ICBR_RESERVED | 24));
  assert(regs[RZV_RIIC_ICMR1_OFFSET] == (RIIC_ICMR1_BCWP | (2 << RIIC_ICMR1_CKS_SHIFT)));
  assert(regs[RZV_RIIC_ICMR2_OFFSET] == (RIIC_ICMR2_TMOH | RIIC_ICMR2_TMOL));
  assert(regs[RZV_RIIC_ICFER_OFFSET] == 0x77 && !regs[RZV_RIIC_ICSER_OFFSET]);
  assert(!regs[RZV_RIIC_ICIER_OFFSET]);

  assert(rzv_i2c_set_frequency(&p, I2C_SPEED_FAST_PLUS) == 0 && resets == 1);
  assert(regs[RZV_RIIC_ICFER_OFFSET] == (0x77 | RIIC_ICFER_FMPE));
  assert(regs[RZV_RIIC_ICBRL_OFFSET] == (RIIC_ICBR_RESERVED | 16));
  assert(rzv_i2c_set_frequency(&p, 0) == -EINVAL && resets == 1);
  assert(p.frequency == I2C_SPEED_FAST_PLUS);

  /* A per-transfer rate is applied before START and kept afterwards. */
  model_reset(&p);
  uint8_t data = 0x42;
  struct i2c_msg_s msg = {.frequency = I2C_SPEED_STANDARD, .addr = 0x50, .buffer = &data, .length = 1};
  assert(xfer(&p, &msg, 1) == 0 && resets == 1 && p.frequency == I2C_SPEED_STANDARD);
  assert(regs[RZV_RIIC_ICBRL_OFFSET] == (RIIC_ICBR_RESERVED | 28));
  assert(regs[RZV_RIIC_ICFER_OFFSET] == 0x77);
  EXPECT(T_S, 0xa0, 0x42, T_P);
}
'''))

    def test_seven_bit_write_then_read_uses_restart_and_clears_transmit_end(self):
        run(build(r'''
int main(void)
{
  struct rzv_i2c_priv_s p;
  model_reset(&p);
  uint8_t reg = 0x75, out[3] = {0}, payload[2] = {0x11, 0x22};
  struct i2c_msg_s msgs[2] = {{.addr = 0x68, .buffer = &reg, .length = 1},
    {.addr = 0x68, .flags = I2C_M_READ, .buffer = out, .length = 3}};
  assert(xfer(&p, msgs, 2) == 0);
  EXPECT(T_S, 0xd0, 0x75, T_SR, 0xd1, T_RA | 1, T_RA | 2, T_RN | 3, T_P);
  assert(out[0] == 1 && out[1] == 2 && out[2] == 3);
  assert(isr_calls[3] == 1 && isr_calls[2] == 1 && !resets);

  /* Plain write: one TEI, STOP, and nothing left to storm. */
  model_reset(&p);
  struct i2c_msg_s w = {.addr = 0x50, .buffer = payload, .length = 2};
  assert(xfer(&p, &w, 1) == 0);
  EXPECT(T_S, 0xa0, 0x11, 0x22, T_P);
  assert(isr_calls[3] == 1);

  /* TEND survives a restart: TEI must clear TEIE and the flag itself. */
  model_reset(&p);
  p.msgs = msgs; p.msgc = 2; p.state = RIIC_STATE_DATA_WRITE;
  regs[RZV_RIIC_ICCR2_OFFSET] = RIIC_ICCR2_MST | RIIC_ICCR2_TRS | RIIC_ICCR2_BBSY;
  regs[RZV_RIIC_ICSR2_OFFSET] = RIIC_ICSR2_TEND | RIIC_ICSR2_TDRE;
  regs[RZV_RIIC_ICIER_OFFSET] = RIIC_ICIER_TEIE | RIIC_ICIER_SPIE;
  rzv_i2c_tei_interrupt(0, NULL, &p);
  assert(!(regs[RZV_RIIC_ICIER_OFFSET] & RIIC_ICIER_TEIE));
  assert(!(regs[RZV_RIIC_ICSR2_OFFSET] & RIIC_ICSR2_TEND));
  assert(regs[RZV_RIIC_ICIER_OFFSET] & RIIC_ICIER_STIE);
  assert(p.state == RIIC_STATE_RESTART && p.msgid == 1);
  EXPECT(T_SR);

  /* START detection resumes address transmission only for a restart. */
  rzv_i2c_sti_interrupt(0, NULL, &p);
  assert(p.state == RIIC_STATE_START);
  assert(regs[RZV_RIIC_ICIER_OFFSET] == (RIIC_ICIER_TIE | RIIC_ICIER_SPIE));
  assert(!(regs[RZV_RIIC_ICSR2_OFFSET] & RIIC_ICSR2_START));
  p.state = RIIC_STATE_DATA_WRITE;
  regs[RZV_RIIC_ICIER_OFFSET] = RIIC_ICIER_STIE;
  regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_START;
  rzv_i2c_sti_interrupt(0, NULL, &p);
  assert(!regs[RZV_RIIC_ICIER_OFFSET] && p.state == RIIC_STATE_DATA_WRITE);
}
'''))

    def test_ten_bit_addressing_sends_both_bytes_and_restarts_for_reads(self):
        run(build(r'''
int main(void)
{
  struct rzv_i2c_priv_s p;
  model_reset(&p);
  uint8_t data = 0x5a, in[2] = {0};
  struct i2c_msg_s w = {.addr = 0x2a5, .flags = I2C_M_TEN, .buffer = &data, .length = 1};
  assert(xfer(&p, &w, 1) == 0);
  EXPECT(T_S, 0xf4, 0xa5, 0x5a, T_P);

  model_reset(&p);
  struct i2c_msg_s r = {.addr = 0x3ff, .flags = I2C_M_TEN | I2C_M_READ, .buffer = in, .length = 2};
  assert(xfer(&p, &r, 1) == 0);
  EXPECT(T_S, 0xf6, 0xff, T_SR, 0xf7, T_RA | 1, T_RN | 2, T_P);
  assert(in[0] == 1 && in[1] == 2);
}
'''))

    def test_reads_nack_the_last_byte_across_continuations(self):
        run(build(r'''
static void check(int length, int split)
{
  struct rzv_i2c_priv_s p;
  uint8_t data[6] = {0};
  model_reset(&p);
  struct i2c_msg_s msgs[2] = {
    {.addr = 0x10, .flags = I2C_M_READ, .buffer = data, .length = split ? split : length},
    {.addr = 0x10, .flags = I2C_M_READ | I2C_M_NOSTART, .buffer = data + split,
     .length = length - split}};
  assert(xfer(&p, msgs, split ? 2 : 1) == 0);
  assert(ntokens == length + 3 && tokens[0] == T_S && tokens[1] == 0x21);
  for (int i = 0; i < length; i++)
    {
      assert(tokens[2 + i] == ((i == length - 1 ? T_RN : T_RA) | (i + 1)));
      assert(data[i] == i + 1);
    }

  assert(tokens[length + 2] == T_P && !resets);
}

int main(void)
{
  for (int length = 1; length <= 6; length++) check(length, 0);
  check(2, 1); check(5, 1); check(5, 3); check(6, 5);
}
'''))

    def test_rejected_vectors_never_touch_the_bus(self):
        run(build(r'''
int main(void)
{
  struct rzv_i2c_priv_s p;
  uint8_t data[2] = {0};
  model_reset(&p);
  struct i2c_msg_s bad[] = {
    {.addr = 0x10, .flags = I2C_M_READ, .buffer = data, .length = 0},
    {.addr = 0x80, .buffer = data, .length = 1},
    {.addr = 0x400, .flags = I2C_M_TEN, .buffer = data, .length = 1},
    {.addr = 0x10, .buffer = NULL, .length = 1},
    {.addr = 0x10, .frequency = I2C_SPEED_FAST_PLUS + 1, .buffer = data, .length = 1},
    {.addr = 0x10, .flags = I2C_M_NOSTART, .buffer = data, .length = 1},
  };
  for (unsigned i = 0; i < sizeof(bad) / sizeof(bad[0]); i++)
    assert(xfer(&p, &bad[i], 1) == -EINVAL);
  struct i2c_msg_s turn[2] = {{.addr = 0x10, .buffer = data, .length = 1},
    {.addr = 0x10, .flags = I2C_M_READ | I2C_M_NOSTART, .buffer = data, .length = 1}};
  assert(xfer(&p, turn, 2) == -EINVAL);
  assert(rzv_i2c_transfer(&p.dev, NULL, 1) == -EINVAL);
  assert(rzv_i2c_transfer(&p.dev, turn, 0) == -EINVAL);
  assert(!ntokens && !unlocks && !resets);

  /* A zero-length write is a valid address probe. */
  struct i2c_msg_s probe = {.addr = 0x10, .buffer = NULL, .length = 0};
  assert(xfer(&p, &probe, 1) == 0);
  EXPECT(T_S, 0x20, T_P);
}
'''))

    def test_busy_bus_lost_arbitration_nack_timeout_and_foreign_stop(self):
        run(build(r'''
int main(void)
{
  struct rzv_i2c_priv_s p;
  uint8_t data[3] = {1, 2, 3};
  struct i2c_msg_s w = {.addr = 0x50, .buffer = data, .length = 3};

  /* BBSY clears in time: START follows the bus-free wait. */
  model_reset(&p); bbsy_polls = 5;
  assert(xfer(&p, &w, 1) == 0 && udelays == 5);

  /* Another master keeps the bus: no START, -EBUSY. */
  model_reset(&p); bbsy_polls = 1 << 30;
  assert(xfer(&p, &w, 1) == -EBUSY && udelays == RIIC_BBSY_TIMEOUT_US && !ntokens);

  /* Address NACK requests STOP and completes on its detection. */
  model_reset(&p); nack_at = 0;
  assert(xfer(&p, &w, 1) == -ENXIO && !resets);
  EXPECT(T_S, 0xa0, T_NK, T_P);

  /* NACK of the final byte, reported before or after transmit end. */
  for (int order = 0; order < 2; order++)
    {
      model_reset(&p); nack_at = 3; tei_first = order;
      assert(xfer(&p, &w, 1) == -ENXIO && !resets);
      EXPECT(T_S, 0xa0, 1, 2, 3, T_NK, T_P);
    }

  /* Arbitration loss and timeout reset the controller. */
  model_reset(&p); al_at = 1;
  assert(xfer(&p, &w, 1) == -EAGAIN && resets == 1);
  model_reset(&p); tmo_at = 2;
  assert(xfer(&p, &w, 1) == -ETIMEDOUT && resets == 1);

  /* A STOP nobody requested ends the transfer with -EIO. */
  model_reset(&p); stop_at = 2;
  assert(xfer(&p, &w, 1) == -EIO && resets == 1);
  EXPECT(T_S, 0xa0, 1, 2, T_P);

  /* A silent bus times out and the controller is reset. */
  model_reset(&p); hang = true;
  assert(xfer(&p, &w, 1) == -ETIMEDOUT && resets == 1);

  /* Flags raised with no transfer active are dropped. */
  model_reset(&p);
  regs[RZV_RIIC_ICSR2_OFFSET] = RIIC_ICSR2_NACKF | RIIC_ICSR2_AL | RIIC_ICSR2_TMOF;
  rzv_i2c_err_interrupt(0, NULL, &p);
  assert(!regs[RZV_RIIC_ICSR2_OFFSET] && !isr_posts);
}
'''))


if __name__ == '__main__':
    unittest.main()
