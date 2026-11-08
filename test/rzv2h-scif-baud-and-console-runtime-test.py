#!/usr/bin/env python3
"""Run the production SCIF baud search and console registration on a model.

- Baud search follows FSP r_scif_uart: every divisor/BRR pair is scored
  without modulation first, and bit-rate modulation (MDDR) replaces it only
  when strictly better.  MDDR stays within 128..255 because M = 256 means
  "no modulation" and does not fit the 8-bit register.
- The SCIF console is marked as a console and configured before it is
  registered, since the serial upper half skips setup for consoles.  A
  failed setup leaves it a normal device so the first open retries.
- rzv_serial.c owns arm_serialinit()/up_putc(); rzv_scif.c only exports
  helpers, so SCIF can be linked together with the SCI-B UARTs.
"""
from pathlib import Path
import importlib.util
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
SPEC = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)

BAUD_MAIN = r'''
static int32_t mod_error(uint32_t coef, uint32_t baud, uint32_t brr, uint32_t m)
{
  uint64_t err_div = (uint64_t)coef * baud * (brr + 1u);
  int32_t bit = (int32_t)(((int64_t)RZV_CLOCK_P1CLK_HZ * 100000) / err_div) - 100000;
  int32_t e = m ? (((bit + 100000) * (int32_t)m) / 256) - 100000 : bit;
  return e < 0 ? -e : e;
}

/* Smallest error over the FSP search space: entries whose top BRR fits
 * (clk / divisor <= 256), every BRR below it, unmodulated and with the FSP
 * M = floor(256 * divisor * (BRR + 1) / clk) when it is in 128..255.
 */

static int32_t best_error(uint32_t baud)
{
  int32_t best = INT32_MAX;
  for (unsigned i = 0; i < sizeof(g_scif_async_baud) / sizeof(g_scif_async_baud[0]); i++)
    {
      uint32_t coef = g_scif_async_baud[i].div_coef;
      uint64_t top = RZV_CLOCK_P1CLK_HZ / ((uint64_t)coef * baud);
      if (top == 0 || top > 256u) continue;
      for (uint32_t brr = 0; brr < top; brr++)
      {
        int32_t e = mod_error(coef, baud, brr, 0);
        if (e < best) best = e;
        uint64_t m = (uint64_t)coef * baud * (brr + 1u) / (RZV_CLOCK_P1CLK_HZ / 256u);
        if (m >= SCIF_MDDR_MIN && m <= SCIF_MDDR_MAX)
          {
            e = mod_error(coef, baud, brr, (uint32_t)m);
            if (e < best) best = e;
          }
      }
    }
  return best;
}

static uint32_t coef_of(const struct rzv_scif_baud_s *c)
{
  for (unsigned i = 0; i < sizeof(g_scif_async_baud) / sizeof(g_scif_async_baud[0]); i++)
    if (g_scif_async_baud[i].bgdm == c->bgdm && g_scif_async_baud[i].abcs == c->abcs &&
        g_scif_async_baud[i].cks == c->cks)
      return g_scif_async_baud[i].div_coef;
  assert(!"selected tuple is not in the table");
  return 0;
}

static void check(uint32_t baud, int expect_exact)
{
  struct rzv_scif_s priv = { 0 };
  struct rzv_scif_baud_s c;
  memset(&c, 0xa5, sizeof(c));
  assert(rzv_scif_calculate_baud(&priv, baud, &c) == OK);
  assert(c.brr <= SCIF_BRR_MAX);
  if (c.brme) assert(c.mddr >= SCIF_MDDR_MIN && c.mddr <= SCIF_MDDR_MAX);
  else assert(c.mddr == 0);
  assert(c.error == mod_error(coef_of(&c), baud, c.brr, c.brme ? c.mddr : 0));
  assert(c.error == best_error(baud));
  if (expect_exact) assert(c.error == 0 && !c.brme);
}

int main(void)
{
  struct rzv_scif_s priv = { 0 };
  struct rzv_scif_baud_s c;
  static const uint32_t exact[] = { 100000u, 250000u, 500000u, 1562500u, 3125000u };
  static const uint32_t common[] = { 300u, 1200u, 2400u, 4800u, 9600u, 19200u, 38400u,
                                     57600u, 115200u, 230400u, 460800u, 921600u };

  for (unsigned i = 0; i < sizeof(exact) / sizeof(exact[0]); i++) check(exact[i], 1);
  for (unsigned i = 0; i < sizeof(common) / sizeof(common[0]); i++) check(common[i], 0);

  /* Standard rates through 115200 stay well inside the UART tolerance. */
  for (unsigned i = 0; i < 9; i++)
    {
      assert(rzv_scif_calculate_baud(&priv, common[i], &c) == OK);
      assert(c.error <= 10); /* 0.01 % */
    }

  assert(rzv_scif_calculate_baud(&priv, 0, &c) == -EINVAL);
  assert(rzv_scif_calculate_baud(&priv, 100u, &c) == -ERANGE);
  return 0;
}
'''

CONSOLE_MODEL = r'''
#define CONFIG_SCIF0_SERIAL_CONSOLE 1
#define _err(...) ((void)0)
struct uart_dev_s { bool isconsole; };
static struct uart_dev_s g_scif0port;
#define CONSOLE_DEV g_scif0port
#define TTYS0_DEV g_scif0port
static int setup_ret, setups;
static bool console_at_setup, console_at_register;
static const char *names[4]; static unsigned nreg;
static int rzv_scif_setup(struct uart_dev_s *dev)
{ setups++; console_at_setup = dev->isconsole; return setup_ret; }
static int uart_register(const char *path, struct uart_dev_s *dev)
{
  if (!strcmp(path, "/dev/console")) console_at_register = dev->isconsole;
  names[nreg++] = path; return 0;
}
'''

CONSOLE_MAIN = r'''
int main(void)
{
  rzv_scif_serialinit();
  assert(setups == 1 && console_at_setup && console_at_register && g_scif0port.isconsole);
  assert(nreg == 2 && !strcmp(names[0], "/dev/console") && !strcmp(names[1], "/dev/ttyS0"));

  memset(&g_scif0port, 0, sizeof(g_scif0port)); nreg = 0; setups = 0; setup_ret = -ETIMEDOUT;
  rzv_scif_serialinit();
  assert(setups == 1 && !g_scif0port.isconsole && !console_at_register && nreg == 2);
  return 0;
}
'''


class ScifBaudAndConsole(unittest.TestCase):
    def setUp(self):
        self.source = (ARCH / 'rzv_scif.c').read_text()

    def test_baud_search_prefers_unmodulated_and_bounds_mddr(self):
        source = self.source
        start = source.index('struct scif_baud_div_s\n{')
        end = source.index('};', source.index('struct rzv_scif_baud_s\n{')) + 2
        clock = re.search(r'^#define RZV_CLOCK_P1CLK_HZ[^\n]*', (ARCH / 'rzv_clock.h').read_text(), re.M)
        code = (B.PRELUDE + clock.group(0) + '\n#define _err(...) ((void)0)\n'
                '#pragma GCC diagnostic ignored "-Wunused-parameter"\nstruct rzv_scif_s { int channel; };\n' + source[start:end] + '\n' +
                B.EXTRACT.definition(source, 'static int rzv_scif_calculate_baud(') + BAUD_MAIN)
        B.compile_run(code)

    def test_console_is_configured_before_registration(self):
        code = (B.PRELUDE + CONSOLE_MODEL +
                B.EXTRACT.definition(self.source, 'void rzv_scif_serialinit(void)') + CONSOLE_MAIN)
        B.compile_run(code)

    def test_serial_entry_points_have_a_single_owner(self):
        serial = (ARCH / 'rzv_serial.c').read_text()
        for name in (r'void\s+arm_serialinit\s*\(void\)\s*\{', r'int\s+up_putc\s*\(int ch\)\s*\{'):
            self.assertEqual(len(re.findall(name, serial)), 1, name)
            self.assertIsNone(re.search(name, self.source), name)
        self.assertIn('rzv_scif_serialinit();', serial)
        self.assertIn('return rzv_scif_putc(ch);', serial)
        self.assertRegex(serial, r'defined\(CONSOLE_DEV\) && defined\(CONFIG_SCIF0_SERIAL_CONSOLE\)\n#  error')
        kconfig = (ARCH / 'Kconfig').read_text()
        block = kconfig[kconfig.index('config RZV_SCIF0\n'):kconfig.index('config RZV_SCIF1\n')]
        self.assertIn('depends on !RZV_SCI0', block)


if __name__ == '__main__':
    unittest.main()
