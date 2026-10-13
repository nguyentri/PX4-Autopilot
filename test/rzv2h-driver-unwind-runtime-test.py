#!/usr/bin/env python3
"""Inject acquisition failures into production driver initialization paths."""

import importlib.util
import os
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = Path(os.environ.get("RZV_DRIVER_SOURCE_ROOT", str(ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv")))
SPEC = importlib.util.spec_from_file_location("boundary", ROOT / "test/rzv2h-driver-boundary-runtime-test.py")
BOUNDARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOUNDARY)
EXTRACT = BOUNDARY.EXTRACT


class DriverUnwind(unittest.TestCase):
    def test_can_late_mode_failure_detaches_routes_and_retries(self):
        header = re.sub(r'^\s*#\s*include[^\n]*$', '',
                        (ARCH / 'hardware/rzv_canfd.h').read_text(), flags=re.M)
        code = BOUNDARY.PRELUDE + header + r'''
#define RZV_CPG_CLK_CANFD 1
#define RZV_ELC_CANFD_GLERR 2
#define RZV_ELC_CANFD_RXFINT 3
#define canerr(...) ((void)0)
static int g_glerr_irq=-1,g_rxf_irq=-1,rzv_canfd_glerr_isr,rzv_canfd_rx_isr;
static int failure,clocks,attached,waits;
static int rzv_clock_enable(int id) {(void)id;++clocks;return 0;}
static __attribute__((unused)) int rzv_clock_disable(int id) {(void)id;--clocks;return 0;}
static int rzv_module_unreset(int id) {(void)id;return 0;}
static __attribute__((unused)) int rzv_module_reset(int id) {(void)id;return 0;}
static unsigned rzv_rd32(unsigned addr) {(void)addr;return 0;}
static void rzv_wr32(unsigned val,unsigned addr) {(void)val;(void)addr;}
static int rzv_canfd_wait_mode(unsigned addr,unsigned mask,unsigned val) {(void)addr;(void)mask;(void)val;return ++waits==failure ? -ETIMEDOUT:0;}
static int rzv_icu_attach(int event,int handler,void *arg,bool enabled) {(void)event;(void)handler;(void)arg;(void)enabled;++attached;return attached;}
static void rzv_icu_detach(int irq) {(void)irq;--attached;}
'''
        source = (ARCH / "rzv_canfd.c").read_text()
        if "static int rzv_canfd_global_setup(void)" in source:
            code += EXTRACT.definition(source, "static int rzv_canfd_global_setup(")
        code += EXTRACT.definition(source, "static int rzv_canfd_global_init(")
        code += r'''
int main(void) {
  failure=3;
  assert(rzv_canfd_global_init()==-ETIMEDOUT);
  assert(!clocks && !attached && g_glerr_irq==-1 && g_rxf_irq==-1);
  failure=0;waits=0;
  assert(rzv_canfd_global_init()==0 && clocks==1 && attached==2);
}
'''
        BOUNDARY.compile_run(code)

    def test_sdhi_failure_does_not_touch_the_peripheral(self):
        code = BOUNDARY.PRELUDE + r'''
#define FAR
#define RZV_SDHI_NSLOTS 3
#define RZV_CPG_CLK_SDHI0 0
#define RZV_CPG_CLK_SDHI1 1
#define RZV_CPG_CLK_SDHI2 2
#define RZV_CPG_RST_SDHI0 3
#define RZV_CPG_RST_SDHI1 4
#define RZV_CPG_RST_SDHI2 5
#define mcerr(...) ((void)0)
#define mcinfo(...) ((void)0)
struct sdio_dev_s {int unused;};
struct rzv_sdhi_dev_s {struct sdio_dev_s dev; int waitsem,slot,base,blocksize,nblocks;bool initialized;};
static struct rzv_sdhi_dev_s g_rzv_sdhi_dev[3];
static int g_rzv_sdhi_base[3]={1,2,3};
static int failure,sems,clocks,mmio;
static void rzv_sdhi_bind_ops(struct rzv_sdhi_dev_s *p) {(void)p;}
static int nxsem_init(int *s,int shared,int n) {(void)s;(void)shared;(void)n;++sems;return 0;}
static __attribute__((unused)) void nxsem_destroy(int *s) {(void)s;--sems;}
static int rzv_clock_enable_sdhi(int s) {(void)s;if(failure==1)return -ETIMEDOUT;++clocks;return 0;}
static int rzv_reset_release_sdhi(int s) {(void)s;return failure==2 ? -ETIMEDOUT:0;}
static __attribute__((unused)) int rzv_clock_disable(int s) {(void)s;--clocks;return 0;}
static __attribute__((unused)) int rzv_module_reset(int s) {(void)s;return 0;}
static void rzv_sdhi_reset(struct sdio_dev_s *p) {(void)p;++mmio;}
''' + EXTRACT.definition((ARCH / "rzv_sdhi.c").read_text(), "FAR struct sdio_dev_s *rzv_sdhi_initialize(")
        code += r'''
int main(void) {
  for(failure=1;failure<=2;++failure) {
    assert(rzv_sdhi_initialize(0)==NULL);
    assert(!mmio && !sems && !clocks && !g_rzv_sdhi_dev[0].initialized);
  }
  failure=0;
  assert(rzv_sdhi_initialize(0)==&g_rzv_sdhi_dev[0].dev && mmio==1 && sems==1 && clocks==1);
  assert(rzv_sdhi_initialize(0)==&g_rzv_sdhi_dev[0].dev && mmio==1 && sems==1 && clocks==1);
}
'''
        BOUNDARY.compile_run(code)

    def test_adc_failure_releases_acquired_state_and_retries(self):
        code = BOUNDARY.PRELUDE + r'''
#define CONFIG_RZV_ADC0 1
#define RZV_ADC_MAX_CHANNELS 8
#define RZV_SYSC_SYS_ADC_CFG 1
#define SYSC_SYS_ADC_CFG_sy_mstp_ada 4u
#define aerr(...) ((void)0)
#define ainfo(...) ((void)0)
struct adc_dev_s { int unused; };
struct config { unsigned clk; };
struct rzv_adc_priv_s { const struct config *config; unsigned chanmask, nchannels; int exclsem; bool initialized; };
static struct config config = {1};
static struct rzv_adc_priv_s g_adc0_priv = {.config=&config};
static struct adc_dev_s g_adc0_dev;
static int failure, clocks, sems, resets, registered;
static unsigned sysc=4;
static int rzv_clock_enable(unsigned clk) { (void)clk; ++clocks; return 0; }
static __attribute__((unused)) int rzv_clock_disable(unsigned clk) { (void)clk; --clocks; return 0; }
static int rzv_module_unreset(unsigned clk) { (void)clk; return failure==1 ? -ETIMEDOUT : 0; }
static __attribute__((unused)) int rzv_module_reset(unsigned clk) { (void)clk; ++resets; return 0; }
static unsigned getreg32(unsigned addr) { (void)addr; return sysc; }
static void putreg32(unsigned val,unsigned addr) { (void)addr; sysc=val; }
static void up_udelay(int delay) { (void)delay; }
static int nxsem_init(int *sem,int shared,int count) { (void)sem;(void)shared;(void)count; if(failure==2)return -ENOMEM; ++sems;return 0; }
static int nxsem_destroy(int *sem) { (void)sem; --sems;return 0; }
static int adc_register(const char *path,struct adc_dev_s *dev) { (void)path;(void)dev; if(failure==3)return -EIO; ++registered;return 0; }
''' + EXTRACT.definition((ARCH / "rzv_adc.c").read_text(), "int rzv_adc_initialize(")
        code += r'''
int main(void) {
  uint8_t channels[]={0,1};
  for(failure=1;failure<=3;++failure) {
    sysc=0xa4; resets=0;
    assert(rzv_adc_initialize("/dev/adc0",channels,2)<0);
    assert(!clocks && !sems && !registered && sysc==0xa4);
  }
  failure=0;
  assert(rzv_adc_initialize("/dev/adc0",channels,2)==0);
  assert(clocks==1 && sems==1 && registered==1 && sysc==0xa0);
  assert(rzv_adc_initialize("/dev/adc0",channels,2)==0);
  assert(clocks==1 && sems==1 && registered==1);
}
'''
        BOUNDARY.compile_run(code)

    def test_ethernet_partial_allocation_and_registration_cleanup(self):
        source = (ARCH / "rzv_ether.c").read_text()
        code = BOUNDARY.PRELUDE + r'''
#include <stdlib.h>
#define RZV_ETHER_DMA_ALIGN 32
#define CONFIG_RZV_ETHER_TXDESC 2
#define CONFIG_RZV_ETHER_RXDESC 2
#define RZV_ETHER_BUFSIZE 64
#define RZV_ETHER_PKTSIZE 64
#define RZV_ETHER0_BASE 1
#define RZV_ETHER1_BASE 2
#define RZV_ELC_GBETH_PORT0_MACIRQ 3
#define RZV_ELC_GBETH_PORT1_MACIRQ 4
#define NET_LL_ETHERNET 1
#define nerr(...) ((void)0)
struct net_driver_s { void *d_buf,*d_private; int d_ifup,d_ifdown,d_txavail; };
struct rzv_eth_s { struct net_driver_s dev; void *txdesc,*rxdesc,*txbuffer,*rxbuffer,*pktbuf; int intf,base,event,irq,phy_addr; bool registered; };
static struct rzv_eth_s g_rzv_eth[2];
static int g_rzv_txdesc[2][2],g_rzv_rxdesc[2][2],rzv_ifup,rzv_ifdown,rzv_txavail;
static int failure, allocations, live, registrations;
static void *kmm_memalign(int align,size_t size) { (void)align; if(++allocations==failure)return NULL; ++live; return malloc(size); }
static void kmm_free(void *ptr) { if(ptr) { --live;free(ptr); } }
static int netdev_register(struct net_driver_s *dev,int type) { (void)dev;(void)type; if(failure==4)return -EIO; ++registrations;return 0; }
'''
        if "static void rzv_free_buffers(" in source:
            code += EXTRACT.definition(source, "static void rzv_free_buffers(")
        code += EXTRACT.definition(source, "static int rzv_alloc_buffers(")
        code += EXTRACT.definition(source, "int rzv_ether_initialize(")
        code += r'''
int main(void) {
  for(failure=1;failure<=4;++failure) {
    allocations=0;
    assert(rzv_ether_initialize(0)<0);
    assert(live==0 && registrations==0);
    assert(!g_rzv_eth[0].txbuffer && !g_rzv_eth[0].rxbuffer && !g_rzv_eth[0].pktbuf && !g_rzv_eth[0].dev.d_buf);
  }
  failure=0; allocations=0;
  assert(rzv_ether_initialize(0)==0 && live==3 && registrations==1);
  assert(rzv_ether_initialize(0)==0 && live==3 && registrations==1);
  kmm_free(g_rzv_eth[0].txbuffer);kmm_free(g_rzv_eth[0].rxbuffer);kmm_free(g_rzv_eth[0].pktbuf);
}
'''
        BOUNDARY.compile_run(code)


if __name__ == "__main__":
    unittest.main()
