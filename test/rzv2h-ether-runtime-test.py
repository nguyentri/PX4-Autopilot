#!/usr/bin/env python3
"""Execute the real CPG span and reset code against a host MMIO recorder."""

import importlib.util
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"


def function(source, name):
    match = re.search(r"(?:static\s+)?(?:void|int)\s+" + name + r"\s*\(", source)
    start = match.start()
    brace = source.index("{", match.end())
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class ClockContracts(unittest.TestCase):
    def test_controller_spans_and_namespaces(self):
        source = (ARCH / "rzv_clock.c").read_text()
        header = (ARCH / "rzv_clock.h").read_text()
        defines = "\n".join(line for line in header.splitlines()
                            if re.match(r"#define RZV_CPG_(CLK_|BIT\(|DOMAIN\()", line))
        harness = """
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
typedef int irqstate_t;
static uint32_t values[4];
static uintptr_t addresses[4];
static unsigned int writes;
static int depth;
static irqstate_t enter_critical_section(void) { depth++; return 0; }
static void leave_critical_section(int flags) { (void)flags; depth--; }
static void rzv_cpg_putreg(uint32_t value, uintptr_t address)
{ assert(depth == 1); values[writes] = value; addresses[writes++] = address; }
#define RZV_CPG_CLKON(n) (0x10420600u + 4u * (n))
""" + defines + """
static int rzv_cpg_sci_channel(uint32_t id)
{ return id == RZV_CPG_CLK_SCI7 ? 7 : -1; }
"""
        harness += "\n".join(function(source, n) for n in (
            "rzv_cpg_reset_mapping", "rzv_cpg_clock_span", "rzv_cpg_write_clock_span"))
        harness += """
static void span(uint32_t id, uint32_t first, uint32_t count)
{
 uint32_t a,b; rzv_cpg_clock_span(id,&a,&b); assert(a==first && b==count);
}
static void reset(uint32_t id, uint32_t domain, uint32_t mask)
{
 uint32_t a,b; rzv_cpg_reset_mapping(id,&a,&b); assert(a==domain && b==mask);
}
int main(void)
{
 assert(RZV_CPG_CLK_ETH0 != RZV_CPG_CLK_SCI7);
 assert(RZV_CPG_CLK_ETH1 != RZV_CPG_CLK_SCI7);
 span(RZV_CPG_CLK_ETH0,184,6); span(RZV_CPG_CLK_ETH1,190,6);
 span(RZV_CPG_CLK_SDHI0,163,4); span(RZV_CPG_CLK_SDHI1,167,4);
 span(RZV_CPG_CLK_SDHI2,171,4); span(RZV_CPG_CLK_SCI7,128,5);
 reset(RZV_CPG_CLK_ETH0,11,1); reset(RZV_CPG_CLK_ETH1,11,2);
 reset(RZV_CPG_CLK_SDHI0,10,128); reset(RZV_CPG_CLK_SDHI1,10,256);
 reset(RZV_CPG_CLK_SDHI2,10,512);
 writes=0; rzv_cpg_write_clock_span(184,6,true);
 assert(writes==1 && addresses[0]==0x1042062c && values[0]==0x3f003f00);
 writes=0; rzv_cpg_write_clock_span(190,6,true);
 assert(writes==2 && addresses[0]==0x1042062c && addresses[1]==0x10420630);
 assert(values[0]==0xc000c000 && values[1]==0x000f000f);
 writes=0; rzv_cpg_write_clock_span(190,6,false);
 assert(writes==2 && values[0]==0xc0000000 && values[1]==0x000f0000);
 writes=0; rzv_cpg_write_clock_span(163,4,true);
 assert(writes==1 && addresses[0]==0x10420628 && values[0]==0x00780078);
 assert(depth==0);
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "test.c").write_text(harness)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(path / "test.c"), "-o", str(path / "test")], check=True)
            subprocess.run([str(path / "test")], check=True)


class EthernetUnwind(unittest.TestCase):
    def test_ifup_failure_and_down_notification_cleanup(self):
        spec = importlib.util.spec_from_file_location(
            "boundary", ROOT / "test/rzv2h-driver-boundary-runtime-test.py")
        boundary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(boundary)
        source = (ARCH / "rzv_ether.c").read_text()
        header = re.sub(r'^\s*#\s*include[^\n]*$', '',
                        (ARCH / "hardware/rzv_ether.h").read_text(), flags=re.M)
        code = boundary.PRELUDE + header + r'''
#define HPWORK 0
#define LPWORK 1
#define RZV_ETHER_PHY_POLL_PERIOD 100
#define nerr(...) ((void)0)
struct net_driver_s { void *d_private; };
struct rzv_eth_s {
 struct net_driver_s dev; uintptr_t base; int event, irq, intf;
 bool bifup, linkup; int txtimeout, irqwork, txtimeout_work, pollwork, txavail_work;
 uint32_t intpending;
};
static int failed, detached;
static uint32_t regs[2048];
static uint32_t getreg32(uintptr_t address) {return regs[address/4];}
static void putreg32(uint32_t value,uintptr_t address) {regs[address/4]=value;}
static int rzv_dma_setup(struct rzv_eth_s *p) {(void)p;return failed==1?-ETIMEDOUT:0;}
static int rzv_configure_link(struct rzv_eth_s *p) {(void)p;return failed==2?-ENOLINK:0;}
static int rzv_interrupt(int irq,void *c,void *arg) {(void)irq;(void)c;(void)arg;return 0;}
static int rzv_icu_attach(int event,int (*fn)(int,void*,void*),void *arg,bool enable)
{(void)event;(void)fn;(void)arg;(void)enable;return failed==3?-EBUSY:40;}
static void rzv_icu_detach(int irq) {assert(irq==40);detached++;}
static void wd_cancel(int *w) {*w=0;}
static void work_cancel(int queue,int *work) {(void)queue;*work=0;}
static bool work_available(int *work) {return *work==0;}
static void rzv_phy_poll_work(void *arg) {(void)arg;}
static void rzv_txavail_work(void *arg) {(void)arg;}
static void work_queue(int queue,int *work,void(*fn)(void*),void *arg,int delay)
{(void)queue;(void)fn;(void)arg;(void)delay;*work=1;}
static void rzv_ether_board_set_speed(int intf,int speed) {(void)intf;(void)speed;}
'''
        for signature in ('static int rzv_ifdown(', 'static int rzv_ifup(', 'static int rzv_txavail('):
            code += boundary.EXTRACT.definition(source, signature)
        code += r'''
int main(void)
{
 struct rzv_eth_s p={0}; p.dev.d_private=&p;
 for(failed=1;failed<=3;failed++)
 {
  p.irq=-1;p.bifup=false;p.txtimeout=1;p.irqwork=1;p.txtimeout_work=1;
  p.pollwork=1;p.txavail_work=1;p.intpending=1;p.linkup=true;
  regs[RZV_ETH_MAC_CONF/4]=MAC_CONF_LM|MAC_CONF_TE|MAC_CONF_RE;
  regs[RZV_ETH_DMA_CH0_TX_CTRL/4]=DMA_CH0_TX_CTRL_ST;
  regs[RZV_ETH_DMA_CH0_RX_CTRL/4]=DMA_CH0_RX_CTRL_SR;
  int ret=rzv_ifup(&p.dev);
  assert(ret==(failed==1?-ETIMEDOUT:failed==2?-ENOLINK:-EBUSY));
  assert(p.irq==-1&&!p.bifup&&!p.linkup&&!p.intpending&&!p.txtimeout);
  assert(!p.irqwork&&!p.txtimeout_work&&!p.pollwork&&!p.txavail_work&&!detached);
  assert(!regs[RZV_ETH_MAC_CONF/4]&&!regs[RZV_ETH_DMA_CH0_TX_CTRL/4]&&!regs[RZV_ETH_DMA_CH0_RX_CTRL/4]);
  assert(rzv_txavail(&p.dev)==0&&!p.txavail_work);
 }
 failed=0;assert(rzv_ifup(&p.dev)==0&&p.bifup&&p.irq==40&&p.pollwork);
 assert(rzv_txavail(&p.dev)==0&&p.txavail_work);
 assert(rzv_ifdown(&p.dev)==0&&detached==1&&!p.txavail_work&&!p.pollwork&&p.irq==-1);
 return 0;
}
'''
        boundary.compile_run(code)


class EthernetOracle(unittest.TestCase):
    def test_exact_frame_rejects_length_errors_and_corruption(self):
        spec = importlib.util.spec_from_file_location("boundary", ROOT / "test/rzv2h-driver-boundary-runtime-test.py")
        b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b)
        source = (ARCH / 'rzv_ether.c').read_text()
        header = re.sub(r'^\s*#\s*include[^\n]*$', '', (ARCH / 'hardware/rzv_ether.h').read_text(), flags=re.M)
        code = b.PRELUDE + header + b.EXTRACT.definition(source, 'static bool rzv_sample_frame_matches(') + r'''
int main(void)
{
 uint8_t expected[128],received[128];memset(expected,0xa5,128);memcpy(received,expected,128);
 uint32_t status=RDES3_FD|RDES3_LD|(128u<<RDES3_FL_SHIFT);
 assert(rzv_sample_frame_matches(status,received,expected,128));
 assert(!rzv_sample_frame_matches((status&~RDES3_FL_MASK)|(129u<<RDES3_FL_SHIFT),received,expected,128));
 assert(!rzv_sample_frame_matches((status&~RDES3_FL_MASK)|(127u<<RDES3_FL_SHIFT),received,expected,128));
 assert(!rzv_sample_frame_matches(status|RDES3_OWN,received,expected,128));
 assert(!rzv_sample_frame_matches(status|RDES3_ES,received,expected,128));
 assert(!rzv_sample_frame_matches(status&~RDES3_FD,received,expected,128));
 received[127]^=1;assert(!rzv_sample_frame_matches(status,received,expected,128));
 return 0;
}
'''
        b.compile_run(code)


class EthernetBoardUnwind(unittest.TestCase):
    def test_clock_reset_and_registration_failures_allow_retry(self):
        spec = importlib.util.spec_from_file_location("boundary", ROOT / "test/rzv2h-driver-boundary-runtime-test.py")
        b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b)
        source = (ROOT/'platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_ether.c').read_text()
        code = b.PRELUDE + r'''
#define CONFIG_RZV_ETHER0 1
#define CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT 1
#define RZV_CPG_CLK_ETH0 184u
#define nwarn(...) ((void)0)
#define nerr(...) ((void)0)
#define syslog(...) ((void)0)
static bool g_ether0_registered;
static bool gate,reset_released;static int failed,registrations;
static int rzv_clock_enable(unsigned int id) {assert(id==184);gate=true;return failed==1?-ETIMEDOUT:0;}
static int rzv_clock_disable(unsigned int id) {assert(id==184);gate=false;return 0;}
static int rzv_module_unreset(unsigned int id) {assert(id==184);reset_released=true;return failed==2?-EIO:0;}
static int rzv_module_reset(unsigned int id) {assert(id==184);reset_released=false;return 0;}
static void rzv2h_ether_pinconfig(int port) {assert(port==0);}
static int rzv_ether_initialize(int port) {assert(port==0);registrations++;return failed==3?-ENOMEM:0;}
''' + b.EXTRACT.definition(source, 'static int rzv2h_ether_clockconfig(')
        code += b.EXTRACT.definition(source, 'int rzv2h_ether_initialize(') + r'''
int main(void)
{
 assert(rzv2h_ether_clockconfig(1)==-ENODEV&&!gate&&!reset_released);
 for(failed=1;failed<=3;failed++)
 {
  assert(rzv2h_ether_initialize()==(failed==1?-ETIMEDOUT:failed==2?-EIO:-ENOMEM));
  assert(!gate&&!reset_released&&!g_ether0_registered);
 }
 failed=0;assert(rzv2h_ether_initialize()==0&&gate&&reset_released&&g_ether0_registered);
 int previous=registrations;assert(rzv2h_ether_initialize()==0&&registrations==previous);
 return 0;
}
'''
        b.compile_run(code)


if __name__ == "__main__":
    unittest.main()
