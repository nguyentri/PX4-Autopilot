#!/usr/bin/env python3
"""Execute SCIF framing, drain and interrupt-preservation contracts."""
from pathlib import Path
import importlib.util
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
SPEC = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)

class ScifRuntime(unittest.TestCase):
    def test_rejected_width_drain_timeout_and_live_interrupts(self):
        source = (ARCH / 'rzv_scif.c').read_text()
        header = re.sub(r'^\s*#\s*include[^\n]*$', '', (ARCH / 'hardware/rzv_scifa.h').read_text(), flags=re.M)
        body = B.EXTRACT.definition(source, 'static int rzv_scif_configure(')
        code = B.PRELUDE + header + r'''
#define CONFIG_RZV2H_SAMPLE_TEST_API 1
#define _err(...) ((void)0)
#define _info(...) ((void)0)
struct rzv_scif_baud_s { int unused; };
struct rzv_scif_s { uintptr_t base; uint32_t clk_id; int channel; bool sample_loop, configured, tx_written; };
struct uart_dev_s { struct rzv_scif_s *priv; bool isconsole; };
static bool g_scif_console_ready;
static uint16_t registers[256];
static int operations, clocks, resets, baud_failed;
static int rzv_scif_calculate_baud(struct rzv_scif_s *p, uint32_t baud, struct rzv_scif_baud_s *out)
{ (void)p; (void)out; return baud == 0 ? -ERANGE : 0; }
static int rzv_scif_setbaud(struct rzv_scif_s *p, uint32_t baud, const struct rzv_scif_baud_s *out)
{ (void)p; (void)baud; (void)out; return baud_failed ? -EIO : 0; }
static int rzv_clock_enable(uint32_t id) { (void)id; clocks++; return 0; }
static int rzv_clock_disable(uint32_t id) { (void)id; clocks--; return 0; }
static int rzv_module_unreset(uint32_t id) { (void)id; resets++; return 0; }
static int rzv_module_reset(uint32_t id) { (void)id; resets--; return 0; }
static uint16_t getreg16(uintptr_t address) { operations++; return registers[address]; }
static void putreg16(uint16_t value, uintptr_t address) {
 operations++;
 if (address == RZV_SCIF_FSR_OFFSET) registers[address] &= value;
 else registers[address] = value;
 if (address == RZV_SCIF_FCR_OFFSET && (value & SCIF_FCR_TFRST))
   registers[RZV_SCIF_FSR_OFFSET] = (registers[RZV_SCIF_FSR_OFFSET] & ~SCIF_FSR_TEND) | SCIF_FSR_TDFE;
}
static void putreg8(uint8_t value, uintptr_t address) { registers[address]=value; }
static void modifyreg16(uintptr_t address,uint16_t clear,uint16_t set)
{ operations++; registers[address]=(registers[address]&~clear)|set; }
static void up_udelay(unsigned int delay) { (void)delay; }
''' + B.EXTRACT.definition(source, 'static inline void rzv_scif_fsr_clear(') + body + B.EXTRACT.definition(source, 'static void rzv_scif_send(') + r'''
int main(void)
{
 struct rzv_scif_s priv = {0}; struct uart_dev_s dev = {.priv=&priv};
 assert(rzv_scif_configure(&dev,115200,0,5,false)==-EINVAL);
 assert(rzv_scif_configure(&dev,115200,0,6,false)==-EINVAL);
 assert(rzv_scif_configure(&dev,0,0,8,false)==-ERANGE);
 assert(!operations && !clocks && !resets);
 registers[RZV_SCIF_SCR_OFFSET] = SCIF_SCR_TE | SCIF_SCR_RIE | SCIF_SCR_TIE;
 assert(rzv_scif_configure(&dev,115200,0,8,false)==-ETIMEDOUT);
 assert(!registers[RZV_SCIF_SCR_OFFSET] && !clocks && !resets);
 priv.configured=true; priv.tx_written=true;
 registers[RZV_SCIF_SCR_OFFSET]=SCIF_SCR_TE|SCIF_SCR_RIE|SCIF_SCR_TIE;
 assert(rzv_scif_configure(&dev,115200,0,8,false)==-ETIMEDOUT);
 assert(registers[RZV_SCIF_SCR_OFFSET] == (SCIF_SCR_TE|SCIF_SCR_RIE|SCIF_SCR_TIE));
 registers[RZV_SCIF_FSR_OFFSET] = SCIF_FSR_TEND;
 priv.sample_loop = true;
 assert(rzv_scif_configure(&dev,115200,0,7,false)==0);
 assert(registers[RZV_SCIF_SMR_OFFSET] & SCIF_SMR_CHR);
 assert(registers[RZV_SCIF_FCR_OFFSET] & SCIF_FCR_LOOP);
 assert(registers[RZV_SCIF_SCR_OFFSET] == (SCIF_SCR_TE|SCIF_SCR_RE|SCIF_SCR_RIE|SCIF_SCR_TIE));
 assert(g_scif_console_ready);
 assert(registers[RZV_SCIF_FSR_OFFSET] & SCIF_FSR_TDFE);
 assert(!(registers[RZV_SCIF_FSR_OFFSET] & SCIF_FSR_TEND));
 /* Idle reconfiguration must not wait for a frame that was never sent. */
 assert(rzv_scif_configure(&dev,115200,0,8,false)==0);
 assert(rzv_scif_configure(&dev,115200,0,8,false)==0);
 rzv_scif_send(&dev,0x5a);
 assert(priv.tx_written && registers[RZV_SCIF_FTDR_OFFSET]==0x5a);
 assert(rzv_scif_configure(&dev,115200,0,8,false)==-ETIMEDOUT);
 registers[RZV_SCIF_FSR_OFFSET]=SCIF_FSR_TEND;
 assert(rzv_scif_configure(&dev,115200,0,8,false)==0 && !priv.tx_written);
 dev.isconsole=true;
 assert(rzv_scif_configure(&dev,115200,0,8,false)==-ETIMEDOUT);
 dev.isconsole=false;
 registers[RZV_SCIF_FSR_OFFSET] = SCIF_FSR_TEND;
 baud_failed=1;
 assert(rzv_scif_configure(&dev,115200,0,8,false)==-EIO);
 assert(!priv.configured && !g_scif_console_ready && !priv.sample_loop);
 assert(!registers[RZV_SCIF_SCR_OFFSET]);
 return 0;
}
'''
        B.compile_run(code)

    def test_failed_loop_change_reports_live_or_reset_state(self):
        source = (ARCH / 'rzv_scif.c').read_text()
        code = B.PRELUDE + r'''
#define CONFIG_RZV2H_SAMPLE_TEST_API 1
#define RZV2H_SCIF_LOOP 0x70
struct rzv_scif_s {bool configured,sample_loop;unsigned int baud,parity,bits,stopbits2;};
struct uart_dev_s {struct rzv_scif_s *priv;bool isconsole;};
struct inode {void *i_private;};
struct file {struct inode *f_inode;};
static int failed,calls;
static int rzv_scif_configure(struct uart_dev_s *d,unsigned int baud,unsigned int parity,unsigned int bits,bool stop)
{
 (void)baud;(void)parity;(void)bits;(void)stop;calls++;
 if(failed==2){d->priv->configured=false;d->priv->sample_loop=false;return -EIO;}
 return failed==1?-ETIMEDOUT:0;
}
''' + B.EXTRACT.definition(source, 'static int rzv_scif_ioctl(') + r'''
int main(void)
{
 struct rzv_scif_s p={.configured=true,.sample_loop=true};
 struct uart_dev_s d={.priv=&p};struct inode i={&d};struct file f={&i};
 assert(rzv_scif_ioctl(&f,RZV2H_SCIF_LOOP,2)==-EINVAL&&!calls);
 d.isconsole=true;assert(rzv_scif_ioctl(&f,RZV2H_SCIF_LOOP,0)==-EINVAL&&!calls);d.isconsole=false;
 failed=1;assert(rzv_scif_ioctl(&f,RZV2H_SCIF_LOOP,0)==-ETIMEDOUT&&p.sample_loop&&p.configured);
 failed=2;assert(rzv_scif_ioctl(&f,RZV2H_SCIF_LOOP,0)==-EIO&&!p.sample_loop&&!p.configured);
 return 0;
}
'''
        B.compile_run(code)

if __name__ == '__main__': unittest.main()
