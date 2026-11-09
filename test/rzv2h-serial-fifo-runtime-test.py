#!/usr/bin/env python3
"""Run the production SCI-B FIFO receive/transmit paths against a register model.

Covers three hardware rules from the RZ/V2H SCI-B FIFO description:
- CPU writes do not clear TDRE in FIFO mode, so a TXI refill must be bounded
  by the free stages in FTSR.T (16 stages); extra writes are discarded.
- RDR.FFER/FPER flag each errored byte; the NuttX upper half ignores the
  receive status, so the lower half must drop those bytes and count them.
- Error flags are cleared after the FIFO is drained, and FRSR.DR is cleared
  together with CSR.RDRF.
"""
from pathlib import Path
import importlib.util
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
SOURCE = ARCH / 'rzv_serial.c'
SPEC = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)

MODEL = r'''
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-function"
#define CONFIG_RZV_SCI_FIFO_MODE 1
#define RZV_SCI_FIFO_STAGES 16u
#define OK 0
struct rzv_uart_s {
  uint32_t baud, sr, rx_count, tx_count;
  uint32_t frame_count, overrun_count, parity_count, break_count;
  uint8_t channel, fifo_depth, rx_cache;
  bool rx_cached;
};
struct uart_dev_s { void *priv; };

/* Register model: RX FIFO of raw RDR words, TX FIFO occupancy, CSR/CCR0. */

static uint32_t csr, ccr0;
static uint32_t rxq[64]; static unsigned rx_head, rx_tail;
static unsigned tx_used, tx_discarded;
static uint32_t cfclr_log[8], ffclr_log[8]; static unsigned ncfclr, nffclr;
static unsigned clear_seq, errclear_seq, rdrclear_seq, last_rdr_seq;

static uint32_t rzv_sci_getreg(struct rzv_uart_s *p, unsigned off)
{
  (void)p;
  switch (off)
    {
    case RZV_SCI_CSR_OFFSET: return csr;
    case RZV_SCI_CCR0_OFFSET: return ccr0;
    case RZV_SCI_FRSR_OFFSET:
      return ((rx_tail - rx_head) << SCI_FRSR_R_SHIFT) & SCI_FRSR_R_MASK;
    case RZV_SCI_FTSR_OFFSET: return tx_used;
    case RZV_SCI_RDR_OFFSET:
      assert(rx_head != rx_tail);
      last_rdr_seq = ++clear_seq;
      return rxq[rx_head++];
    default: assert(!"unexpected register read"); return 0;
    }
}

static void rzv_sci_putreg(struct rzv_uart_s *p, unsigned off, uint32_t v)
{
  (void)p;
  switch (off)
    {
    case RZV_SCI_TDR_OFFSET:
      if (tx_used >= 16) { tx_discarded++; } else { tx_used++; }
      break;
    case RZV_SCI_CFCLR_OFFSET:
      cfclr_log[ncfclr++] = v; ++clear_seq;
      if (v & (SCI_CFCLR_ORERC | SCI_CFCLR_FERC | SCI_CFCLR_PERC))
        { errclear_seq = clear_seq; }
      if (v & SCI_CFCLR_RDRFC) { rdrclear_seq = clear_seq; }
      break;
    case RZV_SCI_FFCLR_OFFSET: ffclr_log[nffclr++] = v; break;
    default: assert(!"unexpected register write");
    }
}

static void rzv_sci_modifyreg(struct rzv_uart_s *p, unsigned off,
                              uint32_t clr, uint32_t set)
{ (void)p; assert(off == RZV_SCI_CCR0_OFFSET); ccr0 = (ccr0 & ~clr) | set; }

static bool rzv_rxavailable(struct uart_dev_s *dev);
static int rzv_receive(struct uart_dev_s *dev, unsigned int *status);
static bool rzv_txready(struct uart_dev_s *dev);
static void rzv_send(struct uart_dev_s *dev, int ch);

/* Upper-half models: uart_recvchars drains while rxavailable (no RX flow
 * control on this port); uart_xmitchars sends while txready and data left.
 */

static char got[64]; static unsigned ngot; static unsigned last_status;
static unsigned pending;
static void uart_recvchars(struct uart_dev_s *dev)
{
  while (rzv_rxavailable(dev)) { got[ngot++] = (char)rzv_receive(dev, &last_status); }
}
static void uart_xmitchars(struct uart_dev_s *dev)
{
  while (pending > 0 && rzv_txready(dev)) { rzv_send(dev, 'x'); pending--; }
}
'''

MAIN = r'''
#define RDR(c) ((uint32_t)(unsigned char)(c))
static void reset(struct rzv_uart_s *p)
{
  memset(p, 0, sizeof(*p)); p->fifo_depth = 16; p->baud = 115200;
  csr = 0; ccr0 = 0; rx_head = rx_tail = 0; tx_used = tx_discarded = 0;
  ncfclr = nffclr = 0; ngot = 0; pending = 0; last_status = 0;
  clear_seq = errclear_seq = rdrclear_seq = last_rdr_seq = 0;
}
static void push(uint32_t w) { rxq[rx_tail++] = w; }

int main(void)
{
  struct rzv_uart_s p;
  struct uart_dev_s dev = { &p };

  /* TXI with 10 bytes queued and 40 pending: refill only the 6 free stages,
   * nothing discarded, then clear TDRE through CFCLR.TDREC.
   */
  reset(&p); csr = SCI_CSR_TDRE; ccr0 = SCI_CCR0_TIE; tx_used = 10; pending = 40;
  rzv_interrupt(0, NULL, &dev);
  assert(tx_used == 16 && tx_discarded == 0 && pending == 34 && p.tx_count == 6);
  assert(ncfclr == 1 && cfclr_log[0] == SCI_CFCLR_TDREC);

  /* Errored bytes in the FIFO are dropped and counted; good bytes keep their
   * order.  Errors are cleared only after the drain; RDRF and DR are cleared.
   */
  reset(&p); csr = SCI_CSR_RDRF | SCI_CSR_FER | SCI_CSR_PER | SCI_CSR_RXDMON;
  ccr0 = SCI_CCR0_RIE;
  push(RDR('A')); push(RDR('B') | SCI_RDR_FFER); push(RDR('C') | SCI_RDR_FPER);
  push(RDR('D'));
  rzv_interrupt(0, NULL, &dev);
  assert(ngot == 2 && got[0] == 'A' && got[1] == 'D');
  assert(p.rx_count == 4 && p.frame_count == 1 && p.parity_count == 1);
  assert(p.break_count == 0 && !p.rx_cached && rx_head == rx_tail);
  assert(rdrclear_seq > last_rdr_seq && errclear_seq > last_rdr_seq);
  assert(nffclr == 1 && ffclr_log[0] == SCI_FFCLR_DRC);
  assert(last_status == 0 && p.sr == 0);

  /* A framing error with RXD held low is a break: counted, not delivered. */
  reset(&p); csr = SCI_CSR_FER; ccr0 = SCI_CCR0_RIE;
  push(SCI_RDR_FFER);
  rzv_interrupt(0, NULL, &dev);
  assert(ngot == 0 && p.break_count == 1 && p.frame_count == 1);
  assert(errclear_seq > last_rdr_seq);

  /* Overrun: count it, drain to make room, clear ORER after the drain. */
  reset(&p); csr = SCI_CSR_ORER | SCI_CSR_RDRF | SCI_CSR_RXDMON;
  ccr0 = SCI_CCR0_RIE;
  for (int i = 0; i < 16; i++) { push(RDR('a' + i)); }
  rzv_interrupt(0, NULL, &dev);
  assert(ngot == 16 && got[15] == 'p' && p.overrun_count == 1);
  assert(errclear_seq > last_rdr_seq);
  assert(p.sr == 0 && last_status == 0); /* latched ORER went with byte 1 */

  /* RX and TX pending in one entry are both serviced. */
  reset(&p); csr = SCI_CSR_RDRF | SCI_CSR_TDRE;
  ccr0 = SCI_CCR0_RIE | SCI_CCR0_TIE; push(RDR('z')); pending = 3;
  rzv_interrupt(0, NULL, &dev);
  assert(ngot == 1 && got[0] == 'z' && pending == 0 && tx_used == 3);

  /* RX interrupts masked: nothing is read from the FIFO. */
  reset(&p); csr = SCI_CSR_RDRF; push(RDR('q'));
  rzv_interrupt(0, NULL, &dev);
  assert(ngot == 0 && rx_head == 0);

  /* Non-FIFO TX keeps the TDRE handshake and never writes TDREC. */
  reset(&p); p.fifo_depth = 0; csr = SCI_CSR_TDRE; ccr0 = SCI_CCR0_TIE;
  pending = 1;
  rzv_interrupt(0, NULL, &dev);
  assert(tx_used == 1 && ncfclr == 0);
  return 0;
}
'''


class SerialFifoRuntime(unittest.TestCase):
    def test_fifo_refill_bound_error_drop_and_flag_order(self):
        source = SOURCE.read_text()
        header = re.sub(r'^\s*#\s*include[^\n]*$', '',
                        (ARCH / 'hardware/rzv_sci.h').read_text(), flags=re.M)
        functions = ''.join(B.EXTRACT.definition(source, sig) for sig in (
            'static bool rzv_rxavailable(', 'static int rzv_receive(',
            'static bool rzv_txready(', 'static void rzv_send(',
            'static int rzv_interrupt('))
        code = (B.PRELUDE.replace('#define OK 0\n', '') + header +
                '#define DEBUGASSERT(x) assert(x)\n' +
                MODEL + functions + MAIN)
        B.compile_run(code)

    def test_early_putc_is_bounded_by_free_fifo_stages(self):
        """Panic/assert output must not overrun the TX FIFO once FM is set."""
        source = (ARCH / 'rzv_lowputc.c').read_text()
        header = re.sub(r'^\s*#\s*include[^\n]*$', '',
                        (ARCH / 'hardware/rzv_sci.h').read_text(), flags=re.M)
        stages = re.search(r'#define LOWPUTC_FIFO_STAGES\s+\S+', source).group(0)
        code = B.PRELUDE + header + stages + '\n' + r'''
#define CONSOLE_BASE 0x1000u
/* Line model: TDRE stays set in FIFO mode; each FTSR poll while the FIFO
 * is full shifts one frame out.  Writes past 16 used stages are lost.
 */
static uint32_t ccr3, csr = SCI_CSR_TDRE;
static unsigned used, sent, lost, ftsr_reads;
static uint32_t getreg32(uint32_t a)
{
  switch (a - CONSOLE_BASE)
    {
    case RZV_SCI_CCR3_OFFSET: return ccr3;
    case RZV_SCI_CSR_OFFSET: return csr;
    case RZV_SCI_FTSR_OFFSET:
      {
        unsigned now = used;
        ftsr_reads++;
        if (used >= 16) { used--; }
        return now;
      }
    default: assert(!"unexpected register read"); return 0;
    }
}
static void putreg32(uint32_t v, uint32_t a)
{
  (void)v; assert(a - CONSOLE_BASE == RZV_SCI_TDR_OFFSET);
  if (used >= 16) { lost++; } else { used++; sent++; }
}
''' + B.EXTRACT.definition(source, 'void rzv_lowputc(') + r'''
int main(void)
{
  ccr3 = SCI_CCR3_FM;
  for (int i = 0; i < 64; i++) { rzv_lowputc('a'); }
  assert(sent == 64 && lost == 0 && ftsr_reads > 0);

  /* FIFO off: TDRE handshake only, FTSR untouched. */
  ccr3 = 0; used = 0; sent = 0; ftsr_reads = 0;
  rzv_lowputc('b');
  assert(sent == 1 && ftsr_reads == 0);
  return 0;
}
'''
        B.compile_run(code)

    def test_cr8_boot_drains_tx_and_marks_console_only_after_setup(self):
        source = SOURCE.read_text()
        start = (ARCH / 'rzv_start.c').read_text()
        self.assertRegex(start, r'#ifdef USE_EARLYSERIALINIT\n\s*arm_earlyserialinit\(\);')
        self.assertNotIn('rzv_earlyserialinit', start)
        guard_end = source.index('#endif /* CONFIG_RZV_SCIx enabled */')
        self.assertGreater(source.index('void arm_earlyserialinit(void)\n{'), guard_end)
        code = B.PRELUDE + r'''
struct rzv_uart_s { int tx_busy; };
struct uart_dev_s { bool isconsole; void *priv; };
static struct rzv_uart_s g_sci5priv;
static struct uart_dev_s g_sci5port = { false, &g_sci5priv };
#define CONSOLE_DEV g_sci5port
static int setup_ret, setups, drains, setup_cut_frame;
static int rzv_tx_drain(struct rzv_uart_s *priv)
{
  drains++; priv->tx_busy = 0; return OK;
}
static int rzv_setup(struct uart_dev_s *dev)
{
  /* Setup clears TE: a frame still shifting out would be cut. */
  setup_cut_frame |= ((struct rzv_uart_s *)dev->priv)->tx_busy;
  setups++; return setup_ret;
}
''' + B.EXTRACT.definition(source, 'void arm_earlyserialinit(') + r'''
int main(void)
{
  g_sci5priv.tx_busy = 1;               /* boot progress char in flight */
  setup_ret = -ETIMEDOUT;
  arm_earlyserialinit();
  assert(setups == 1 && !g_sci5port.isconsole); /* open() retries setup */
  assert(drains == 1 && !setup_cut_frame);
  g_sci5priv.tx_busy = 1;
  setup_ret = OK;
  arm_earlyserialinit();
  assert(setups == 2 && g_sci5port.isconsole);
  assert(drains == 2 && !setup_cut_frame);
  return 0;
}
'''
        B.compile_run(code)

    def test_sci_console_up_putc_sends_cr_before_lf(self):
        """syslog reaches up_putc() raw; the SCI-B console must emit CRLF."""
        source = SOURCE.read_text()
        code = B.PRELUDE + r'''
struct uart_dev_s { int unused; };
static struct uart_dev_s g_sci5port;
#define CONSOLE_DEV g_sci5port
volatile bool g_rzv_console_ready;
static char line[16]; static unsigned nline, polls;
static bool rzv_txready(struct uart_dev_s *dev) { (void)dev; polls++; return true; }
static void rzv_send(struct uart_dev_s *dev, int ch) { (void)dev; line[nline++] = (char)ch; }
int up_putc(int ch);
''' + B.EXTRACT.definition(source, 'int up_putc(') + r'''
int main(void)
{
  up_putc('\n');                        /* console not up yet: dropped */
  assert(nline == 0 && polls == 0);
  g_rzv_console_ready = true;
  const char *in = "a\nb\r\n";
  for (const char *p = in; *p; p++) { assert(up_putc(*p) == *p); }
  assert(nline == 7 && memcmp(line, "a\r\nb\r\r\n", 7) == 0);
  assert(polls == nline);               /* every byte waits for TX ready */
  return 0;
}
'''
        B.compile_run(code)

    def test_console_ctrl_c_reaches_the_foreground_task(self):
        """Without TERMIOS the upper half raises SIGINT only for consoles."""
        upper = (ROOT / 'platforms/nuttx/NuttX/nuttx/drivers/serial/serial.c').read_text()
        code = B.PRELUDE + r'''
#include <signal.h>
#include <sys/types.h>
#define CONFIG_TTY_SIGINT 1
#define CONFIG_TTY_SIGINT_CHAR 0x03
#define FAR
struct uart_dev_s { bool isconsole; pid_t pid; };
typedef struct uart_dev_s uart_dev_t;
int uart_check_special(FAR uart_dev_t *dev, const char *buf, size_t size);
''' + B.EXTRACT.definition(upper, 'int uart_check_special(') + r'''
int main(void)
{
  uart_dev_t dev = { false, 7 };
  assert(uart_check_special(&dev, "\x03", 1) == 0);   /* plain tty */
  dev.isconsole = true;
  assert(uart_check_special(&dev, "ab\x03", 3) == SIGINT);
  assert(uart_check_special(&dev, "abc", 3) == 0);
  dev.pid = -1;                                        /* no foreground */
  assert(uart_check_special(&dev, "\x03", 1) == 0);
  return 0;
}
'''
        B.compile_run(code)
        # Every console path marks its device as console and feeds RX
        # through uart_recvchars(), which calls uart_check_special().
        sci = SOURCE.read_text()
        scif = (ARCH / 'rzv_scif.c').read_text()
        self.assertIn('CONSOLE_DEV.isconsole = true;', sci)
        self.assertRegex(scif, r'isconsole\s*=\s*true;')
        self.assertIn('uart_recvchars(dev);', sci)
        self.assertIn('uart_recvchars(dev);', scif)
        io = (ROOT / 'platforms/nuttx/NuttX/nuttx/drivers/serial/serial_io.c').read_text()
        self.assertIn('uart_check_special(dev, &ch, 1)', io)
        configs = ROOT / 'platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/configs'
        for name in ('nsh', 'nsh-scif', 'nsh-cm33'):
            defconfig = (configs / name / 'defconfig').read_text()
            for option in ('CONFIG_TTY_SIGINT=y', 'CONFIG_SIG_DEFAULT=y',
                           'CONFIG_SCHED_WAITPID=y'):
                self.assertIn(option, defconfig, name)
        nsh = (configs / 'nsh' / 'defconfig').read_text()
        self.assertIn('CONFIG_EXAMPLES_CPUHOG=y', nsh)
        self.assertIn('CONFIG_PIPES=y', nsh)

    def test_setup_selects_fifo_mode_before_enabling_the_receiver(self):
        """RE latches the CCR3.FM data path: FM set after RE leaves RX deaf."""
        source = SOURCE.read_text()
        setup = B.EXTRACT.definition(source, 'static int rzv_setup(')
        fifo = B.EXTRACT.definition(source, 'static int rzv_fifo_configure(')
        self.assertNotIn('RZV_SCI_CCR_OFFSET(3)', fifo)
        self.assertNotIn('SCI_CCR3_FM', re.sub(r'/\*.*?\*/', '', fifo, flags=re.S))
        fm_set = setup.index('ccr3 |= SCI_CCR3_FM;')
        fm_clear = setup.index('ccr3 &= ~SCI_CCR3_FM;')
        ccr3_write = setup.index('rzv_sci_putreg(priv, RZV_SCI_CCR_OFFSET(3), ccr3);')
        fifo_call = setup.index('rzv_fifo_configure(priv)')
        cfclr = setup.index('RZV_SCI_CFCLR_OFFSET')
        enable = setup.index('SCI_CCR0_TE | SCI_CCR0_RE | SCI_CCR0_IDSE')
        self.assertLess(max(fm_set, fm_clear), ccr3_write)
        self.assertLess(ccr3_write, fifo_call)
        self.assertLess(fifo_call, cfclr)
        self.assertLess(cfclr, enable)
        self.assertEqual(setup.count('rzv_fifo_configure(priv)'), 1)

    def test_fifo_trigger_levels_stay_in_manual_range(self):
        source = SOURCE.read_text()
        kconfig = (ARCH / 'Kconfig').read_text()
        self.assertRegex(source, r'#\s*define RZV_SCI_FIFO_STAGES 16u')
        self.assertIn('priv->fifo_depth = RZV_SCI_FIFO_STAGES;', source)
        for name, default in (('RX', 12), ('TX', 4)):
            block = re.search(rf'config RZV_SCI_FIFO_{name}_TRIGGER\n(.*?)\n\n',
                              kconfig, re.S).group(1)
            self.assertIn(f'default {default}', block)
            self.assertRegex(block, r'range [01] 15\b')

    def test_early_console_ccr2_runs_at_115200_from_p5clk(self):
        # rzv_lowsetup() programs a fixed CCR2 before rzv_setup() computes
        # the baud.  If that constant uses the wrong divisor, the first boot
        # byte leaves at a different rate and reaches the host corrupted.
        lowputc = (ARCH / 'rzv_lowputc.c').read_text()
        expr = re.search(r'#define LOWPUTC_CCR2_115200\s*\\?\s*\n?\s*\((.*?)\)\n',
                         lowputc, re.S).group(1)
        ccr2 = eval(expr.replace('u', ''), {})
        p5clk = int(re.search(r'#define RZV_CLOCK_P5CLK_HZ\s+\((\d+)\)',
                              (ARCH / 'rzv_clock.h').read_text()).group(1))
        serial = SOURCE.read_text()
        modes = re.findall(r'\{\s*([01]), ([01]), ([01]), ([0-3])\s*\}',
                           re.search(r'g_async_baud\[13\] =\n\{(.*?)\n\};',
                                     serial, re.S).group(1))
        coeffs = [int(v) for v in re.search(
            r'g_div_coefficient\[13\] =\n\{\s*([\d, ]+)\s*\}', serial).group(1).split(',')]
        self.assertEqual(len(modes), 13)

        bcp, bgdm, abcs = ccr2 & 7, (ccr2 >> 4) & 1, (ccr2 >> 5) & 1
        brr, brme = (ccr2 >> 8) & 0xFF, (ccr2 >> 16) & 1
        cks, mddr = (ccr2 >> 20) & 3, (ccr2 >> 24) & 0xFF
        self.assertEqual(bcp, 0)
        divisor = coeffs[modes.index((str(bgdm), str(abcs), '0', str(cks)))]
        baud = p5clk / (divisor * (brr + 1))
        if brme:
            self.assertGreaterEqual(mddr, 128)
            baud *= mddr / 256
        self.assertLess(abs(baud / 115200 - 1), 0.005, f'CCR2 0x{ccr2:08x} gives {baud:.0f} baud')


if __name__ == '__main__':
    unittest.main()
