#!/usr/bin/env python3
"""Execute the SDHI lower half against a register model of the controller.

The production command, data, reset, clock and interrupt functions are
extracted from rzv_sdhi.c and compiled on the host with a model that follows
the RZ/V2H SDHI register behaviour from the hardware manual: INFO1/INFO2
flags clear when written with zero, SDRST re-initialises SD_OPTION,
SD_CLK_CTRL, SD_SIZE and the masks, CBSY/SCLKDIVEN gate SD_CMD and
SD_CLK_CTRL writes, and BUF0 moves one SD_SIZE block per BRE/BWE.  The
command sequences mirror the NuttX mmcsd upper half call order.
"""
from pathlib import Path
import importlib.util
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / 'platforms/nuttx/NuttX/nuttx'
ARCH = NUTTX / 'arch/arm/src/rzv'
SPEC = importlib.util.spec_from_file_location(
    'boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)

# Production functions, in definition order, so no prototypes are needed.
FUNCTIONS = (
    'static int rzv_sdhi_wait_info2(',
    'static void rzv_sdhi_setmasks(',
    'static void rzv_sdhi_disableints(',
    'static int rzv_sdhi_setclkctrl(',
    'static void rzv_sdhi_soft_reset(',
    'static void rzv_sdhi_eventtimeout(',
    'static int rzv_sdhi_pio_block(',
    'static int rzv_sdhi_interrupt(',
    'static void rzv_sdhi_reset(',
    'static sdio_capset_t rzv_sdhi_capabilities(',
    'static sdio_statset_t rzv_sdhi_status(',
    'static void rzv_sdhi_widebus(',
    'static void rzv_sdhi_clock(',
    'static int rzv_sdhi_attach(',
    'static int rzv_sdhi_sendcmd(',
    'static int rzv_sdhi_xfersetup(',
    'static int rzv_sdhi_recvsetup(',
    'static int rzv_sdhi_sendsetup(',
    'static int rzv_sdhi_cancel(',
    'static int rzv_sdhi_waitresponse(',
    'static int rzv_sdhi_recv_r1(',
    'static int rzv_sdhi_recv_r2(',
    'static int rzv_sdhi_recv_r3(',
    'static void rzv_sdhi_waitenable(',
    'static sdio_eventset_t rzv_sdhi_eventwait(',
    'int rzv2h_sdhi_sample_state_at(',
    'int rzv2h_sdhi_sample_state(',
)


def _object_defines(text):
    """Return the object-like #defines of a header, first definition wins."""
    seen = set()
    lines = []
    for line in text.splitlines():
        match = re.match(r'^#\s*define\s+(\w+)\s+(.*)$', line)
        if match is None or line.rstrip().endswith('\\'):
            continue
        name, value = match.groups()
        value = re.sub(r'/\*.*$|//.*$', '', value).strip()
        if name in seen or not value:
            continue
        seen.add(name)
        lines.append(f'#define {name} {value}')
    return '\n'.join(lines) + '\n'


def _section(source, start, end):
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


MODEL = r'''
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-function"
#pragma GCC diagnostic ignored "-Wunused-variable"
#include <inttypes.h>
#include <stdarg.h>
#include <time.h>
#define FAR
#define DEBUGASSERT(x) assert(x)
/* NuttX MSEC2TICK rounds to the nearest 10 ms tick. */
#define MSEC2TICK(ms) ((clock_t)(((ms) + 5) / 10))
static unsigned dsb;
#define ARM_DSB() (dsb++)

typedef int irqstate_t;
typedef uint8_t sdio_eventset_t;
typedef uint8_t sdio_capset_t;
typedef uint8_t sdio_statset_t;
typedef uintptr_t wdparm_t;
typedef void (*wdentry_t)(wdparm_t arg);
typedef void (*worker_t)(void *arg);
typedef int (*xcpt_t)(int irq, void *context, void *arg);
typedef struct { int count; } sem_t;
struct wdog_s { bool active; uint32_t delay; wdentry_t fn; wdparm_t arg; };
struct sdio_dev_s { int unused; };
#define WDOG_ISACTIVE(w) ((w)->active)

static void mc_log(const char *fmt, ...) { (void)fmt; }
#define mcerr(...) mc_log(__VA_ARGS__)
#define mcinfo(...) mc_log(__VA_ARGS__)
'''

HARDWARE = r'''
static struct rzv_sdhi_dev_s g_rzv_sdhi_dev[RZV_SDHI_NSLOTS];

/* ---- Controller register model (base address 0) ---------------------- */

#define REG(off) reg[(off) / 8]
static uint32_t reg[0x400 / 8];
static bool cbsy, sclkdiven = true;
static unsigned operations;
static uint32_t card_rx[1024];
static unsigned card_rx_pos;
static uint32_t card_tx[1024];
static unsigned card_tx_pos;
static unsigned buf0_reads_with_bre_latched;
static uint16_t clk_log[16];
static unsigned clk_writes, clk_writes_while_gated;
static uint16_t cmd_written, size_at_cmd, seccnt_at_cmd, stop_at_cmd;
static unsigned cmd_writes, cmd_writes_while_busy, sdrst_pulses;

static void hw_power_on(void)
{
  uint32_t sdcd = REG(RZV_SDHI_SD_INFO1_OFFSET) & RZV_SDHI_SD_INFO1_SDCD;

  REG(RZV_SDHI_SD_OPTION_OFFSET) = 0x40ee;
  REG(RZV_SDHI_SD_CLK_CTRL_OFFSET) = 0x0020;
  REG(RZV_SDHI_SD_SIZE_OFFSET) = 0x0200;
  REG(RZV_SDHI_SD_STOP_OFFSET) = 0;
  REG(RZV_SDHI_SD_SECCNT_OFFSET) = 0;
  REG(RZV_SDHI_SD_INFO1_MASK_OFFSET) = RZV_SDHI_SD_INFO1_MASK_INIT;
  REG(RZV_SDHI_SD_INFO2_MASK_OFFSET) = RZV_SDHI_SD_INFO2_MASK_INIT;
  REG(RZV_SDHI_SD_INFO1_OFFSET) = sdcd;
  REG(RZV_SDHI_SD_INFO2_OFFSET) = 0;
}

static uint32_t getreg32(uintptr_t a)
{
  operations++;
  switch (a)
    {
      case RZV_SDHI_SD_INFO2_OFFSET:
        return REG(a) | (sclkdiven ? RZV_SDHI_SD_INFO2_SCLKDIVEN : 0) |
               (cbsy ? RZV_SDHI_SD_INFO2_CBSY : 0);
      case RZV_SDHI_SD_INFO1_MASK_OFFSET:
        return REG(a) & RZV_SDHI_SD_INFO1_MASK_INIT;
      case RZV_SDHI_SD_INFO2_MASK_OFFSET:
        return REG(a) & RZV_SDHI_SD_INFO2_MASK_INIT;
      case RZV_SDHI_SD_BUF0_OFFSET:
        if ((REG(RZV_SDHI_SD_INFO2_OFFSET) & RZV_SDHI_SD_INFO2_BRE) != 0)
          {
            buf0_reads_with_bre_latched++;
          }
        return card_rx[card_rx_pos++];
      default:
        return REG(a);
    }
}

static uint16_t getreg16(uintptr_t a) { return (uint16_t)getreg32(a); }

static void putreg32(uint32_t v, uintptr_t a)
{
  operations++;
  switch (a)
    {
      case RZV_SDHI_SD_INFO1_OFFSET:
      case RZV_SDHI_SD_INFO2_OFFSET:
        REG(a) &= v;                       /* zero clears, one keeps */
        break;
      case RZV_SDHI_SOFT_RST_OFFSET:
        if ((v & RZV_SDHI_SOFT_RST_SDRST) == 0)
          {
            sdrst_pulses++;
            hw_power_on();
          }
        REG(a) = v;
        break;
      case RZV_SDHI_SD_BUF0_OFFSET:
        card_tx[card_tx_pos++] = v;
        break;
      case RZV_SDHI_SD_CLK_CTRL_OFFSET:
        if (cbsy || !sclkdiven)
          {
            clk_writes_while_gated++;
          }
        if (clk_writes < 16)
          {
            clk_log[clk_writes] = (uint16_t)v;
          }
        clk_writes++;
        REG(a) = v;
        break;
      case RZV_SDHI_SD_CMD_OFFSET:
        if (cbsy)
          {
            cmd_writes_while_busy++;
          }
        cmd_writes++;
        cmd_written = (uint16_t)v;
        size_at_cmd = (uint16_t)REG(RZV_SDHI_SD_SIZE_OFFSET);
        seccnt_at_cmd = (uint16_t)REG(RZV_SDHI_SD_SECCNT_OFFSET);
        stop_at_cmd = (uint16_t)REG(RZV_SDHI_SD_STOP_OFFSET);
        REG(a) = v;
        break;
      default:
        REG(a) = v;
        break;
    }
}

static void putreg16(uint16_t v, uintptr_t a) { putreg32(v, a); }

/* ---- OS services ------------------------------------------------------ */

static clock_t now;
static clock_t clock_systime_ticks(void) { return now++; }
static unsigned udelays;
static void up_udelay(unsigned int us) { udelays += us; }
static int depth;
static irqstate_t enter_critical_section(void) { depth++; return 0; }
static void leave_critical_section(irqstate_t f) { (void)f; depth--; }

static unsigned posts, waits;
static uint32_t last_wait_ticks;
static void (*wait_hook)(void);   /* runs while the waiter sleeps */
static void (*late_hook)(void);   /* runs just after the wait expired */
static int nxsem_post(sem_t *s) { s->count++; posts++; return OK; }
static int nxsem_trywait(sem_t *s)
{
  if (s->count > 0)
    {
      s->count--;
      return OK;
    }
  return -EAGAIN;
}
static int nxsem_tickwait_uninterruptible(sem_t *s, uint32_t ticks)
{
  waits++;
  last_wait_ticks = ticks;
  if (s->count == 0 && wait_hook != NULL)
    {
      void (*hook)(void) = wait_hook;
      wait_hook = NULL;
      hook();
    }
  if (s->count > 0)
    {
      s->count--;
      return OK;
    }
  if (late_hook != NULL)
    {
      void (*hook)(void) = late_hook;
      late_hook = NULL;
      hook();
    }
  return -ETIMEDOUT;
}
static int nxsem_get_value(sem_t *s, int *v) { *v = s->count; return OK; }

static unsigned wd_starts;
static int wd_start(struct wdog_s *w, uint32_t delay, wdentry_t fn,
                    wdparm_t arg)
{
  w->active = true;
  w->delay = delay;
  w->fn = fn;
  w->arg = arg;
  wd_starts++;
  return OK;
}
static int wd_cancel(struct wdog_s *w) { w->active = false; return OK; }

static int icu_event = -1, icu_calls, icu_ret = 77;
static xcpt_t icu_handler;
static void *icu_arg;
static bool icu_enable;
static int rzv_icu_attach(int event, xcpt_t handler, void *arg, bool enable)
{
  icu_calls++;
  icu_event = event;
  icu_handler = handler;
  icu_arg = arg;
  icu_enable = enable;
  return icu_ret;
}
'''

SCENARIO = r'''
/* ---- Scenario helpers ------------------------------------------------- */

static struct rzv_sdhi_dev_s *p = &g_rzv_sdhi_dev[0];

static void setup(void)
{
  memset(p, 0, sizeof(*p));
  p->slot = 0;
  p->base = 0;
  p->initialized = true;
  hw_power_on();
  rzv_sdhi_reset(&p->dev);
}

/* Raise controller flags and run the ISR if an unmasked source is set,
 * as the level OXMN interrupt would.
 */

static bool irq_line(void)
{
  return (REG(RZV_SDHI_SD_INFO1_OFFSET) &
          ~REG(RZV_SDHI_SD_INFO1_MASK_OFFSET)) != 0 ||
         (REG(RZV_SDHI_SD_INFO2_OFFSET) &
          ~REG(RZV_SDHI_SD_INFO2_MASK_OFFSET)) != 0;
}

static bool raise(uint32_t info1, uint32_t info2)
{
  REG(RZV_SDHI_SD_INFO1_OFFSET) |= info1;
  REG(RZV_SDHI_SD_INFO2_OFFSET) |= info2;
  if (!irq_line())
    {
      return false;
    }
  rzv_sdhi_interrupt(0, NULL, p);
  return true;
}

static bool all_masked(void)
{
  return (REG(RZV_SDHI_SD_INFO1_MASK_OFFSET) & RZV_SDHI_SD_INFO1_MASK_INIT)
           == RZV_SDHI_SD_INFO1_MASK_INIT &&
         (REG(RZV_SDHI_SD_INFO2_MASK_OFFSET) & RZV_SDHI_SD_INFO2_MASK_INIT)
           == RZV_SDHI_SD_INFO2_MASK_INIT;
}

static bool unmasked2(uint32_t bit)
{
  return (REG(RZV_SDHI_SD_INFO2_MASK_OFFSET) & bit) == 0;
}

static bool unmasked1(uint32_t bit)
{
  return (REG(RZV_SDHI_SD_INFO1_MASK_OFFSET) & bit) == 0;
}

static uint32_t buffer[3 * 128];

static void fill_card(unsigned words)
{
  for (unsigned i = 0; i < words; i++)
    {
      card_rx[i] = 0xa5000000u + i;
    }
  card_rx_pos = 0;
}

int main(void)
{
'''


def build(body, helpers=''):
    source = (ARCH / 'rzv_sdhi.c').read_text()
    header = re.sub(r'^\s*#\s*include[^\n]*$', '',
                    (ARCH / 'hardware/rzv_sdhi.h').read_text(), flags=re.M)
    sdio = _object_defines((NUTTX / 'include/nuttx/sdio.h').read_text())
    irqsel = re.search(r'^#define RZV_IRQSEL_SDHI_OXMN\(n\).*$',
                       (NUTTX / 'arch/arm/include/rzv/rzv2h_irq.h').read_text(),
                       re.M)[0]
    public = (NUTTX / 'boards/arm/rzv/rdk-rzv2h/include/rzv2h-sample-test.h').read_text()
    state = re.search(r'struct rzv2h_sdhi_sample_state_s\n\{.*?\n\};', public, re.S)[0]
    enum = re.search(r'enum sdio_clock_e\n\{.*?\n\};',
                     (NUTTX / 'include/nuttx/sdio.h').read_text(), re.S)[0]
    defines = _section(source, 'Pre-processor Definitions', 'Private Types')
    defines = defines.split('\n', 2)[2].rsplit('/****', 1)[0]   # drop banners
    struct = re.search(r'struct rzv_sdhi_dev_s\n\{.*?\n\};', source, re.S)[0]
    code = (B.PRELUDE + MODEL + header + sdio + irqsel + '\n' + enum + '\n' +
            state + '\n' + defines + '\n' + struct + '\n' + HARDWARE)
    for signature in FUNCTIONS:
        code += B.EXTRACT.definition(source, signature)
    return (code + SCENARIO.replace('int main(void)\n{\n', helpers + 'int main(void)\n{\n') +
            body + '\n  assert(depth == 0);\n  return 0;\n}\n')


def run(body, helpers=''):
    B.compile_run(build(body, helpers))


class SdhiCommandData(unittest.TestCase):
    def test_reset_programs_manual_baseline(self):
        run(r'''
  REG(RZV_SDHI_SD_INFO2_OFFSET) = RZV_SDHI_SD_INFO2_BRE | RZV_SDHI_SD_INFO2_ERR0;
  REG(RZV_SDHI_SD_INFO1_OFFSET) = RZV_SDHI_SD_INFO1_ACEND;
  setup();
  assert(REG(RZV_SDHI_SD_OPTION_OFFSET) == 0xc0ee);
  assert(REG(RZV_SDHI_SD_SIZE_OFFSET) == 512);
  assert(REG(RZV_SDHI_SD_STOP_OFFSET) == 0);
  assert(REG(RZV_SDHI_SD_CLK_CTRL_OFFSET) == 0x0320);
  assert(REG(RZV_SDHI_SD_INFO1_OFFSET) == 0);
  assert(REG(RZV_SDHI_SD_INFO2_OFFSET) == 0);
  assert(all_masked() && !irq_line());
  assert(clk_writes_while_gated == 0);
  assert(rzv_sdhi_capabilities(&p->dev) ==
         (SDIO_CAPS_4BIT | SDIO_CAPS_DMABEFOREWRITE));
''')

    def test_command_register_encodes_response_type_and_direction(self):
        run(r'''
  /* Manual SD_CMD layout: MD2:0 in bits 10:8, data bit 11, read bit 12,
   * multiple-block bit 13, MD7:6=01 (no auto CMD12) bit 14.
   */
  assert(RZV_SDHI_SD_CMD_RSP_NONE == 0x0300 && RZV_SDHI_SD_CMD_RSP_R1 == 0x0400);
  assert(RZV_SDHI_SD_CMD_RSP_R1B == 0x0500 && RZV_SDHI_SD_CMD_RSP_R2 == 0x0600);
  assert(RZV_SDHI_SD_CMD_RSP_R3 == 0x0700 && RZV_SDHI_SD_CMD_DATA == 0x0800);
  assert(RZV_SDHI_SD_CMD_READ == 0x1000 && RZV_SDHI_SD_CMD_MULTI == 0x2000);
  assert(RZV_SDHI_SD_CMD_NOAUTOCMD12 == 0x4000 && RZV_SDHI_SD_STOP_SEC == 0x0100);
  setup();
  static const struct { uint32_t cmd; uint16_t reg; } table[] = {
    { MMCSD_CMD0,  0 | 0x0300 },
    { MMCSD_CMD2,  2 | 0x0600 },
    { SD_CMD3,     3 | 0x0400 },
    { MMCSD_CMD7S, 7 | 0x0500 },
    { SD_CMD8,     8 | 0x0400 },
    { SD_ACMD41,  41 | 0x0700 },
    { MMCSD_CMD12, 12 | 0x0500 },
  };
  for (unsigned i = 0; i < sizeof(table) / sizeof(table[0]); i++)
    {
      assert(rzv_sdhi_sendcmd(&p->dev, table[i].cmd, 0x12345678u) == OK);
      assert(cmd_written == table[i].reg);
      assert(REG(RZV_SDHI_SD_ARG_OFFSET) == 0x5678);
      assert(REG(RZV_SDHI_SD_ARG1_OFFSET) == 0x1234);
      assert(unmasked1(RZV_SDHI_SD_INFO1_RSPEND));
      assert(unmasked2(RZV_SDHI_SD_INFO2_ERR_ALL));
      assert(raise(RZV_SDHI_SD_INFO1_RSPEND, 0));
      assert(rzv_sdhi_waitresponse(&p->dev, table[i].cmd) == OK);
      assert(all_masked());
    }

  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 512) == OK);
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD17, 0) == OK);
  assert(cmd_written == (17 | 0x0400 | 0x0800 | 0x1000));
  rzv_sdhi_cancel(&p->dev);

  assert(rzv_sdhi_sendsetup(&p->dev, (uint8_t *)buffer, 512) == OK);
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD24, 0) == OK);
  assert(cmd_written == (24 | 0x0400 | 0x0800));
  rzv_sdhi_cancel(&p->dev);

  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 1024) == OK);
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD18, 0) == OK);
  assert(cmd_written == (18 | 0x0400 | 0x0800 | 0x1000 | 0x2000 | 0x4000));
  assert(size_at_cmd == 512 && seccnt_at_cmd == 2 && stop_at_cmd == 0x0100);
  rzv_sdhi_cancel(&p->dev);

  assert(rzv_sdhi_sendsetup(&p->dev, (uint8_t *)buffer, 1536) == OK);
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD25, 0) == OK);
  assert(cmd_written == (25 | 0x0400 | 0x0800 | 0x2000 | 0x4000));
  assert(seccnt_at_cmd == 3 && stop_at_cmd == 0x0100);
  rzv_sdhi_cancel(&p->dev);

  /* SD_CMD must not be written while CBSY is set. */
  unsigned writes = cmd_writes;
  cbsy = true;
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD0, 0) == -ETIMEDOUT);
  assert(cmd_writes == writes && cmd_writes_while_busy == 0);
  cbsy = false;
''')

    def test_single_block_read_follows_mmcsd_order(self):
        run(r'''
  setup();
  /* mmcsd_readsingle: BLOCKSETUP (no-op), WAITENABLE, RECVSETUP, CMD17. */
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_TIMEOUT |
                      SDIOWAIT_ERROR, 100);
  assert(p->waitwdog.active && p->waitwdog.delay == 10 && p->waitticks == 10);
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 512) == OK);
  assert(REG(RZV_SDHI_SD_SIZE_OFFSET) == 512 && REG(RZV_SDHI_SD_STOP_OFFSET) == 0);
  assert(unmasked2(RZV_SDHI_SD_INFO2_BRE) && !unmasked2(RZV_SDHI_SD_INFO2_BWE));
  assert(unmasked1(RZV_SDHI_SD_INFO1_ACEND));
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD17, 0x40) == OK);

  REG(RZV_SDHI_SD_RSP10_OFFSET) = 0x00000900u;
  assert(raise(RZV_SDHI_SD_INFO1_RSPEND, 0));
  /* The response must not end or disarm the data phase. */
  assert(p->wkupevent == 0 && p->waitwdog.active);
  assert(unmasked2(RZV_SDHI_SD_INFO2_BRE) && unmasked1(RZV_SDHI_SD_INFO1_ACEND));
  assert(rzv_sdhi_waitresponse(&p->dev, MMCSD_CMD17) == OK);
  assert(last_wait_ticks == 50);
  uint32_t r1;
  assert(rzv_sdhi_recv_r1(&p->dev, MMCSD_CMD17, &r1) == OK && r1 == 0x900);

  fill_card(128);
  assert(raise(0, RZV_SDHI_SD_INFO2_BRE));
  assert(card_rx_pos == 128 && buf0_reads_with_bre_latched == 0 && dsb == 1);
  assert(p->remaining == 0 && p->wkupevent == 0);
  for (unsigned i = 0; i < 128; i++)
    {
      assert(buffer[i] == 0xa5000000u + i);
    }

  assert(raise(RZV_SDHI_SD_INFO1_ACEND, 0));
  assert(p->wkupevent == SDIOWAIT_TRANSFERDONE && !p->waitwdog.active);
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_TRANSFERDONE);
  assert(last_wait_ticks == 10 + 10);
  assert(p->waitevents == 0 && all_masked() && !irq_line());
  struct rzv2h_sdhi_sample_state_s s;
  assert(rzv2h_sdhi_sample_state(&s) == OK);
  assert(s.interrupts_masked && !s.watchdog_active && !s.buffer_present);
  assert(s.semaphore_count == 0 && s.waitevents == 0);
''')

    def test_scr_read_and_invalid_geometry(self):
        run(r'''
  setup();
  /* mmcsd_get_scr: RECVSETUP(8) with no BLOCKSETUP support. */
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 8) == OK);
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_TIMEOUT |
                      SDIOWAIT_ERROR, 100);
  assert(rzv_sdhi_sendcmd(&p->dev, SD_ACMD51, 0) == OK);
  assert(size_at_cmd == 8 && stop_at_cmd == 0);
  assert((cmd_written & 0x2000) == 0);
  assert(raise(RZV_SDHI_SD_INFO1_RSPEND, 0));
  assert(rzv_sdhi_waitresponse(&p->dev, SD_ACMD51) == OK);
  fill_card(2);
  assert(raise(0, RZV_SDHI_SD_INFO2_BRE) && card_rx_pos == 2);
  assert(raise(RZV_SDHI_SD_INFO1_ACEND, 0));
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_TRANSFERDONE);
  assert(buffer[0] == 0xa5000000u && buffer[1] == 0xa5000001u);

  /* Geometry the controller cannot express is rejected unarmed. */
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 1000) == -EINVAL);
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 6) == -EINVAL);
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer + 2, 8) == -EINVAL);
  assert(all_masked() && p->buffer == NULL);
''')

    def test_stale_and_premature_access_end(self):
        run(r'''
  setup();
  /* An R1b command leaves ACEND latched after its busy phase. */
  REG(RZV_SDHI_SD_INFO1_OFFSET) |= RZV_SDHI_SD_INFO1_ACEND;
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_ERROR, 0);
  assert(!p->waitwdog.active && p->waitticks == 0);
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 1024) == OK);
  assert((REG(RZV_SDHI_SD_INFO1_OFFSET) & RZV_SDHI_SD_INFO1_ACEND) == 0);
  assert(!irq_line());
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD18, 0) == OK);
  assert(raise(RZV_SDHI_SD_INFO1_RSPEND, 0));
  assert(p->wkupevent == 0 && p->waitsem.count == 0);
  assert(rzv_sdhi_waitresponse(&p->dev, MMCSD_CMD18) == OK);

  /* One block arrived, then access end: the transfer is short. */
  fill_card(128);
  assert(raise(0, RZV_SDHI_SD_INFO2_BRE));
  assert(p->remaining == 512);
  assert(raise(RZV_SDHI_SD_INFO1_ACEND, 0));
  assert(p->wkupevent == SDIOWAIT_ERROR);
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_ERROR);
  assert(last_wait_ticks == 200);
''')

    def test_multi_block_read_moves_one_block_per_request(self):
        run(r'''
  setup();
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_TIMEOUT |
                      SDIOWAIT_ERROR, 100);
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 3 * 512) == OK);
  assert(REG(RZV_SDHI_SD_SECCNT_OFFSET) == 3);
  assert(REG(RZV_SDHI_SD_STOP_OFFSET) == RZV_SDHI_SD_STOP_SEC);
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD18, 0) == OK);
  assert(raise(RZV_SDHI_SD_INFO1_RSPEND, 0));
  assert(rzv_sdhi_waitresponse(&p->dev, MMCSD_CMD18) == OK);
  fill_card(3 * 128);
  for (unsigned block = 1; block <= 3; block++)
    {
      assert(raise(0, RZV_SDHI_SD_INFO2_BRE));
      assert(card_rx_pos == block * 128 && dsb == block);
      assert(p->remaining == (3 - block) * 512 && p->wkupevent == 0);
    }
  assert(buf0_reads_with_bre_latched == 0);
  for (unsigned i = 0; i < 3 * 128; i++)
    {
      assert(buffer[i] == 0xa5000000u + i);
    }

  /* A buffer request beyond the caller buffer is drained and fails. */
  card_rx_pos = 0;
  assert(raise(0, RZV_SDHI_SD_INFO2_BRE));
  assert(card_rx_pos == 128 && p->wkupevent == SDIOWAIT_ERROR);
  assert(buffer[0] == 0xa5000000u);
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_ERROR);

  /* The following single-block setup drops the sector-count mode. */
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 512) == OK);
  assert(REG(RZV_SDHI_SD_STOP_OFFSET) == 0 && !p->multiblock);
  rzv_sdhi_cancel(&p->dev);
''')

    def test_write_is_set_up_before_the_command(self):
        run(r'''
  setup();
  for (unsigned i = 0; i < 2 * 128; i++)
    {
      buffer[i] = 0x5a000000u + i;
    }
  /* DMABEFOREWRITE: WAITENABLE, SENDSETUP, then CMD25. */
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_TIMEOUT |
                      SDIOWAIT_ERROR, 250);
  assert(rzv_sdhi_sendsetup(&p->dev, (const uint8_t *)buffer, 1024) == OK);
  assert(unmasked2(RZV_SDHI_SD_INFO2_BWE) && !unmasked2(RZV_SDHI_SD_INFO2_BRE));
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD25, 0) == OK);
  assert(size_at_cmd == 512 && seccnt_at_cmd == 2 && stop_at_cmd == 0x0100);
  assert(raise(RZV_SDHI_SD_INFO1_RSPEND, 0));
  assert(rzv_sdhi_waitresponse(&p->dev, MMCSD_CMD25) == OK);
  assert(raise(0, RZV_SDHI_SD_INFO2_BWE) && card_tx_pos == 128);
  assert(raise(0, RZV_SDHI_SD_INFO2_BWE) && card_tx_pos == 256);
  for (unsigned i = 0; i < 2 * 128; i++)
    {
      assert(card_tx[i] == 0x5a000000u + i);
    }
  assert(raise(RZV_SDHI_SD_INFO1_ACEND, 0));
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_TRANSFERDONE);
  assert(last_wait_ticks == 25 + 10);
''')

    def test_response_errors_and_timeout_recovery(self):
        run(r'''
  setup();
  rzv_sdhi_widebus(&p->dev, true);
  assert(REG(RZV_SDHI_SD_OPTION_OFFSET) == 0x40ee && p->widebus);
  rzv_sdhi_clock(&p->dev, CLOCK_SD_TRANSFER_4BIT);
  assert(REG(RZV_SDHI_SD_CLK_CTRL_OFFSET) == 0x0300);

  /* No response at all: bounded wait, soft reset keeps the bus setup. */
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_TIMEOUT |
                      SDIOWAIT_ERROR, 100);
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 8) == OK);
  assert(rzv_sdhi_sendcmd(&p->dev, SD_ACMD51, 0) == OK);
  unsigned pulses = sdrst_pulses;
  assert(rzv_sdhi_waitresponse(&p->dev, SD_ACMD51) == -ETIMEDOUT);
  assert(last_wait_ticks == 50 && sdrst_pulses == pulses + 1);
  assert(REG(RZV_SDHI_SD_OPTION_OFFSET) == 0x40ee);
  assert(REG(RZV_SDHI_SD_CLK_CTRL_OFFSET) == 0x0300);
  assert(REG(RZV_SDHI_SD_SIZE_OFFSET) == 8);
  assert(clk_writes_while_gated == 0 && p->cmd_info1 == 0);
  assert(!unmasked1(RZV_SDHI_SD_INFO1_RSPEND));
  /* mmcsd then cancels: the armed data waiter is released at once. */
  assert(rzv_sdhi_cancel(&p->dev) == OK);
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_ERROR);
  assert(all_masked());

  /* Response timeout flag from the controller. */
  assert(rzv_sdhi_sendcmd(&p->dev, SD_CMD8, 0x1aa) == OK);
  REG(RZV_SDHI_SD_ERR_STS2_OFFSET) = 0x1;
  assert(raise(0, RZV_SDHI_SD_INFO2_RSPTO));
  assert((REG(RZV_SDHI_SD_INFO2_OFFSET) & RZV_SDHI_SD_INFO2_RSPTO) == 0);
  assert(p->err_sts2 == 0x1);
  assert(rzv_sdhi_waitresponse(&p->dev, SD_CMD8) == -ETIMEDOUT);

  /* CRC error with the response end: reported as an I/O error. */
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD2, 0) == OK);
  assert(raise(RZV_SDHI_SD_INFO1_RSPEND, RZV_SDHI_SD_INFO2_ERR1));
  assert(rzv_sdhi_waitresponse(&p->dev, MMCSD_CMD2) == -EIO);

  /* Stale error latch from an earlier command is cleared by sendcmd. */
  REG(RZV_SDHI_SD_INFO2_OFFSET) |= RZV_SDHI_SD_INFO2_ERR0;
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD0, 0) == OK);
  assert(!irq_line());
  assert(raise(RZV_SDHI_SD_INFO1_RSPEND, 0));
  assert(rzv_sdhi_waitresponse(&p->dev, MMCSD_CMD0) == OK);

  /* Completion that lands just after the wait expired is still used. */
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD0, 0) == OK);
  late_hook = late_rspend;
  assert(rzv_sdhi_waitresponse(&p->dev, MMCSD_CMD0) == OK);
  assert(p->cmdsem.count == 0);
''', helpers='''
static void late_rspend(void) { assert(raise(RZV_SDHI_SD_INFO1_RSPEND, 0)); }
''')

    def test_data_errors_and_bounded_data_waits(self):
        run(r'''
  setup();
  /* Data CRC error after the command completed ends the data wait. */
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_TIMEOUT |
                      SDIOWAIT_ERROR, 100);
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 512) == OK);
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD17, 0) == OK);
  assert(raise(RZV_SDHI_SD_INFO1_RSPEND, 0));
  assert(rzv_sdhi_waitresponse(&p->dev, MMCSD_CMD17) == OK);
  assert(raise(0, RZV_SDHI_SD_INFO2_ERR2));
  assert(p->wkupevent == SDIOWAIT_ERROR && p->cmdsem.count == 0);
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_ERROR);

  /* Data watchdog fires while the caller sleeps. */
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_TIMEOUT |
                      SDIOWAIT_ERROR, 1);
  assert(p->waitticks == 1);                  /* MSEC2TICK(1) rounds to 0 */
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 512) == OK);
  wait_hook = fire_watchdog;
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_TIMEOUT);
  assert(last_wait_ticks == 1 + 10 && all_masked());

  /* No caller timeout and no watchdog: the wait is still bounded. */
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_ERROR, 100);
  assert(!p->waitwdog.active);
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 512) == OK);
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_TIMEOUT);
  assert(last_wait_ticks == 200);
  assert(p->buffer == NULL && p->remaining == 0 && all_masked());

  /* Completion racing the expiry is returned and its post consumed. */
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_ERROR, 0);
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 8) == OK);
  fill_card(2);
  assert(raise(0, RZV_SDHI_SD_INFO2_BRE));
  late_hook = late_acend;
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_TRANSFERDONE);
  assert(p->waitsem.count == 0);

  /* waitenable discards a stale post from an earlier transfer. */
  p->waitsem.count = 1;
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE, 0);
  assert(p->waitsem.count == 0 && p->wkupevent == 0);
''', helpers='''
static void fire_watchdog(void)
{
  assert(p->waitwdog.active);
  p->waitwdog.active = false;
  p->waitwdog.fn(p->waitwdog.arg);
}

static void late_acend(void) { assert(raise(RZV_SDHI_SD_INFO1_ACEND, 0)); }
''')

    def test_cancel_releases_both_waiters_once(self):
        run(r'''
  setup();
  rzv_sdhi_waitenable(&p->dev, SDIOWAIT_TRANSFERDONE | SDIOWAIT_TIMEOUT |
                      SDIOWAIT_ERROR, 100);
  assert(rzv_sdhi_recvsetup(&p->dev, (uint8_t *)buffer, 512) == OK);
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD17, 0) == OK);
  unsigned before = posts;
  assert(rzv_sdhi_cancel(&p->dev) == OK);
  assert(posts == before + 2 && !p->waitwdog.active && all_masked());
  assert(p->buffer == NULL && p->remaining == 0 && p->waitevents == 0);
  assert(rzv_sdhi_waitresponse(&p->dev, MMCSD_CMD17) == -EIO);
  assert(rzv_sdhi_eventwait(&p->dev) == SDIOWAIT_ERROR);
  assert(rzv_sdhi_cancel(&p->dev) == OK && posts == before + 2);
  /* Flags raised after cancel are masked and not serviced. */
  assert(!raise(RZV_SDHI_SD_INFO1_ACEND, RZV_SDHI_SD_INFO2_BRE));
''')

    def test_attach_routes_through_icu_selectable_source(self):
        run(r'''
  setup();
  assert(rzv_sdhi_attach(&p->dev) == OK);
  assert(icu_event == 392 && icu_handler == rzv_sdhi_interrupt);
  assert(icu_arg == p && icu_enable && p->irq == 77 && p->irq_attached);
  assert(rzv_sdhi_attach(&p->dev) == OK && icu_calls == 1);

  struct rzv_sdhi_dev_s *q = &g_rzv_sdhi_dev[2];
  q->slot = 2;
  icu_ret = -ENOMEM;
  assert(rzv_sdhi_attach(&q->dev) == -ENOMEM);
  assert(icu_event == 396 && !q->irq_attached);
  icu_ret = 80;
  assert(rzv_sdhi_attach(&q->dev) == OK && q->irq == 80);
''')

    def test_r2_response_is_realigned(self):
        run(r'''
  setup();
  /* SD_RSP10..76 hold R[127:8]; NuttX wants R2[0] = R[127:96]. */
  const uint32_t w[4] = { 0x3f035344u, 0x53443136u, 0x47809a1bu, 0x2c0118e1u };
  REG(RZV_SDHI_SD_RSP10_OFFSET) = (w[2] << 24) | (w[3] >> 8);
  REG(RZV_SDHI_SD_RSP32_OFFSET) = (w[1] << 24) | (w[2] >> 8);
  REG(RZV_SDHI_SD_RSP54_OFFSET) = (w[0] << 24) | (w[1] >> 8);
  REG(RZV_SDHI_SD_RSP76_OFFSET) = w[0] >> 8;
  uint32_t r2[4];
  assert(rzv_sdhi_recv_r2(&p->dev, MMCSD_CMD2, r2) == OK);
  assert(r2[0] == w[0] && r2[1] == w[1] && r2[2] == w[2]);
  assert(r2[3] == (w[3] & 0xffffff00u));
  uint32_t r3;
  REG(RZV_SDHI_SD_RSP10_OFFSET) = 0xc0ff8000u;
  assert(rzv_sdhi_recv_r3(&p->dev, SD_ACMD41, &r3) == OK && r3 == 0xc0ff8000u);
  assert(rzv_sdhi_recv_r2(&p->dev, MMCSD_CMD2, NULL) == -EINVAL);
''')

    def test_status_and_clock_gate(self):
        run(r'''
  setup();
  REG(RZV_SDHI_SD_INFO1_OFFSET) = RZV_SDHI_SD_INFO1_SDCDIN;
  assert(rzv_sdhi_status(&p->dev) == 0);
  REG(RZV_SDHI_SD_INFO1_OFFSET) = RZV_SDHI_SD_INFO1_SDCD | RZV_SDHI_SD_INFO1_SDCDRM;
  assert(rzv_sdhi_status(&p->dev) == SDIO_STATUS_PRESENT);
  REG(RZV_SDHI_SD_INFO1_OFFSET) = 0;

  /* Stop SDCLK, write the divider with SCLKEN clear, then enable. */
  clk_writes = 0;
  rzv_sdhi_clock(&p->dev, CLOCK_SD_TRANSFER_4BIT);
  assert(clk_writes == 3);
  assert(clk_log[0] == 0x0220 && clk_log[1] == 0x0200 && clk_log[2] == 0x0300);
  clk_writes = 0;
  rzv_sdhi_clock(&p->dev, CLOCK_SDIO_DISABLED);
  assert(clk_writes == 2 && REG(RZV_SDHI_SD_CLK_CTRL_OFFSET) == 0x0200);
  clk_writes = 0;
  rzv_sdhi_clock(&p->dev, CLOCK_IDMODE);
  assert(clk_writes == 3 && REG(RZV_SDHI_SD_CLK_CTRL_OFFSET) == 0x0320);
  assert(clk_writes_while_gated == 0);

  /* Busy controller or locked divider: SD_CLK_CTRL is left alone. */
  clk_writes = 0;
  cbsy = true;
  rzv_sdhi_clock(&p->dev, CLOCK_SD_TRANSFER_1BIT);
  rzv_sdhi_widebus(&p->dev, true);
  cbsy = false;
  sclkdiven = false;
  rzv_sdhi_clock(&p->dev, CLOCK_SD_TRANSFER_1BIT);
  sclkdiven = true;
  assert(clk_writes == 0 && REG(RZV_SDHI_SD_CLK_CTRL_OFFSET) == 0x0320);
  assert(REG(RZV_SDHI_SD_OPTION_OFFSET) == 0xc0ee && !p->widebus);
''')


if __name__ == '__main__':
    unittest.main()
