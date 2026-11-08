#!/usr/bin/env python3
"""Run the production SCI-B TCSETS path against a CCR0 model.

rzv_setup() rewrites CCR0 without the receive/transmit interrupt enables that
the serial upper half set at open.  A reader that waits in poll() before
read() (PX4 MAVLink) never re-enables RIE, so TCSETS itself must keep them.
"""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_serial.c'
SPEC = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)

MODEL = r'''
#define CONFIG_SERIAL_TERMIOS 1
#define TCGETS 1
#define TCSETS 2
#define TIOCGICOUNT 3
#define ENOTTY 25
#define CSIZE 0x30u
#define CS7 0x20u
#define CS8 0x30u
#define CSTOPB 0x40u
#define PARENB 0x100u
#define PARODD 0x200u
#define RZV_SCI_CCR_OFFSET(n) (n)
#define SCI_CCR0_RE 0x1u
#define SCI_CCR0_TE 0x10u
#define SCI_CCR0_IDSE 0x400u
#define SCI_CCR0_RIE 0x10000u
#define SCI_CCR0_TIE 0x100000u
#define SCI_CCR0_TEIE 0x200000u
#define serr(...) ((void)0)
typedef int irqstate_t;
struct termios { unsigned c_cflag; unsigned speed; };
static unsigned cfgetispeed(const struct termios *t) { return t->speed; }
static void cfsetispeed(struct termios *t, unsigned s) { t->speed = s; }
static void cfsetospeed(struct termios *t, unsigned s) { t->speed = s; }
static int critical;
static irqstate_t enter_critical_section(void) { return critical++; }
static void leave_critical_section(irqstate_t f) { critical = f; }
struct serial_icounter_struct { int rx; };
struct rzv_uart_s { uint32_t baud; uint8_t parity, bits; bool stopbits2;
                    int channel; };
struct uart_dev_s;
struct uart_ops_s { int (*setup)(struct uart_dev_s *dev); };
struct uart_dev_s { void *priv; const struct uart_ops_s *ops; };
struct inode { void *i_private; };
struct file { struct inode *f_inode; };
static int rzv_snapshot_icount(struct uart_dev_s *d,
                               struct serial_icounter_struct *c)
{ (void)d; (void)c; return OK; }

/* CCR0 model and a setup() that behaves like rzv_setup(): success leaves
 * TE|RE|IDSE with every interrupt enable cleared; failure leaves 0.
 */

static uint32_t ccr0;
static int setup_calls, fail_mask;
__attribute__((unused)) static uint32_t rzv_sci_getreg(struct rzv_uart_s *p, unsigned off)
{ (void)p; assert(off == 0); return ccr0; }
__attribute__((unused)) static void rzv_sci_modifyreg(struct rzv_uart_s *p, unsigned off,
                              uint32_t clr, uint32_t set)
{ (void)p; assert(off == 0); assert(critical); ccr0 = (ccr0 & ~clr) | set; }
static int fake_setup(struct uart_dev_s *d)
{
  (void)d;
  ccr0 = SCI_CCR0_IDSE;
  if (fail_mask & (1 << setup_calls++)) { ccr0 = 0; return -ETIMEDOUT; }
  ccr0 = SCI_CCR0_TE | SCI_CCR0_RE | SCI_CCR0_IDSE;
  return OK;
}
static const struct uart_ops_s ops = { fake_setup };
'''

MAIN = r'''
#define EN (SCI_CCR0_RIE | SCI_CCR0_TIE | SCI_CCR0_TEIE)
#define RUN (SCI_CCR0_TE | SCI_CCR0_RE | SCI_CCR0_IDSE)
static int tcsets(struct rzv_uart_s *p, uint32_t before, int fails,
                  unsigned baud)
{
  struct uart_dev_s dev = { p, &ops };
  struct inode in = { &dev };
  struct file f = { &in };
  struct termios t = { CS8, baud };
  ccr0 = RUN | before; setup_calls = 0; fail_mask = fails;
  int ret = rzv_ioctl(&f, TCSETS, (unsigned long)(uintptr_t)&t);
  assert(critical == 0);
  return ret;
}
int main(void)
{
  struct rzv_uart_s p = { 115200, 0, 8, false, 5 };

  /* Opened port with RX and TX interrupts armed keeps all of them. */
  assert(tcsets(&p, EN, 0, 57600) == OK);
  assert(ccr0 == (RUN | EN) && p.baud == 57600 && setup_calls == 1);

  /* Idle TX: only RIE was armed, so TIE/TEIE must not be invented. */
  assert(tcsets(&p, SCI_CCR0_RIE, 0, 921600) == OK);
  assert(ccr0 == (RUN | SCI_CCR0_RIE) && p.baud == 921600);

  /* Rejected configuration: old settings restored and re-armed. */
  assert(tcsets(&p, SCI_CCR0_RIE, 1, 300) == -ETIMEDOUT);
  assert(ccr0 == (RUN | SCI_CCR0_RIE) && p.baud == 921600);
  assert(setup_calls == 2);

  /* Restore also failed: a stopped channel must stay quiet. */
  assert(tcsets(&p, EN, 3, 300) == -ETIMEDOUT);
  assert(ccr0 == 0 && p.baud == 921600);
  return 0;
}
'''


class SerialTcsetsRuntime(unittest.TestCase):
    def test_tcsets_keeps_upper_half_interrupt_enables(self):
        source = SOURCE.read_text()
        code = (B.PRELUDE + MODEL +
                B.EXTRACT.definition(source, 'static int rzv_ioctl(') + MAIN)
        B.compile_run(code)


if __name__ == '__main__':
    unittest.main()
