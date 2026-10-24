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
BOARD = ROOT / "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h"


def boundary_module():
    spec = importlib.util.spec_from_file_location(
        "ether_boundary", ROOT / "test/rzv2h-driver-boundary-runtime-test.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def without_includes(path):
    return re.sub(r'^\s*#\s*include[^\n]*$', '', path.read_text(), flags=re.M)


class EthernetSampleSelection(unittest.TestCase):
    def test_disabled_interface_selection_does_not_alias_or_publish(self):
        b = boundary_module()
        source = (ARCH / "rzv_ether.c").read_text()
        code = b.PRELUDE + r'''
#define RZV_ETHER_NINTERFACES 2
#define CONFIG_RZV_ETHER0 1
struct rzv_eth_s { int unused; };
static struct rzv_eth_s g_rzv_eth[2];
''' + b.EXTRACT.definition(source, "static int rzv_ether_sample_select(") + r'''
int main(void) {
  struct rzv_eth_s *priv = NULL;
  assert(rzv_ether_sample_select(-1, &priv) == -EINVAL && priv == NULL);
  assert(rzv_ether_sample_select(2, &priv) == -EINVAL && priv == NULL);
  assert(rzv_ether_sample_select(1, &priv) == -ENODEV && priv == NULL);
  assert(rzv_ether_sample_select(0, &priv) == 0 && priv == &g_rzv_eth[0]);
  return 0;
}
'''
        b.compile_run(code)

    def test_indexed_sample_api_is_present_and_wrappers_select_mac0(self):
        b = boundary_module()
        source = (ARCH / "rzv_ether.c").read_text()
        self.assertTrue("int rzv2h_ether_sample_state_at(" in source,
                        "missing indexed Ethernet state provider")
        self.assertTrue("int rzv2h_ether_sample_loopback_at(" in source,
                        "missing indexed Ethernet loopback provider")
        self.assertIn("rzv2h_ether_sample_state_at(0, out)", b.EXTRACT.definition(
            source, "int rzv2h_ether_sample_state("))
        self.assertIn("rzv2h_ether_sample_loopback_at(0, data, size)", b.EXTRACT.definition(
            source, "int rzv2h_ether_sample_loopback("))

    def test_optional_board_notification_never_writes_read_only_speed(self):
        b = boundary_module()
        source = (ARCH / "rzv_ether.c").read_text()
        self.assertNotIn("void rzv_ether_board_set_speed(",
                         (BOARD / "src/rzv2h_ether.c").read_text())
        code = b.PRELUDE + "\n#define weak_function\n#define UNUSED(x) ((void)(x))\n"
        code += b.EXTRACT.definition(source, "void weak_function rzv_ether_board_set_speed(")
        code += "int main(void) { for(int p=-1;p<=2;++p) { rzv_ether_board_set_speed(p,100); rzv_ether_board_set_speed(p,0); } return 0; }"
        b.compile_run(code)

    def test_real_initializers_snapshots_and_loopback_use_selected_mac_only(self):
        b = boundary_module()
        source = (ARCH / "rzv_ether.c").read_text()
        code = b.PRELUDE + r'''
#include <stdlib.h>
#define FAR
#define static_assert _Static_assert
#define CONFIG_RZV2H_SAMPLE_TEST_API 1
#define CONFIG_RZV_ETHER0 1
#define CONFIG_RZV_ETHER1 1
#define CONFIG_RZV_ETHER_TXDESC 2
#define CONFIG_RZV_ETHER_RXDESC 2
#define CONFIG_RZV_ETHER_BUFSIZE 256
#define RZV_ETHER_PKTSIZE 256
#define RZV_ETHER_NINTERFACES 2
#define RZV_ETHER_DMA_BARRIER() ((void)0)
#define NET_LL_ETHERNET 1
#define HPWORK 0
#define LPWORK 1
#define RZV_ETHER_PHY_POLL_PERIOD 100
#define RZV_IRQSEL_GBETH0_MACIRQ 422
#define RZV_IRQSEL_GBETH1_MACIRQ 437
#define nerr(...) ((void)0)
typedef unsigned int spinlock_t;
struct work_s { int busy; };
struct wdog_s { int active; };
struct net_driver_s {
  uint8_t *d_buf; void *d_private; unsigned int d_len;
  int (*d_ifup)(struct net_driver_s *);
  int (*d_ifdown)(struct net_driver_s *);
  int (*d_txavail)(struct net_driver_s *);
};
''' + without_includes(ARCH / "rzv_ether.h")
        code += without_includes(ARCH / "hardware/rzv_ether.h")
        code += without_includes(BOARD / "include/rzv2h-sample-test.h") + r'''
static struct rzv_eth_s g_rzv_eth[2];
static struct rzv_eth_desc_s g_rzv_txdesc[2][2], g_rzv_rxdesc[2][2];
static uint32_t regs[2][2048];
static unsigned int reads[2], writes[2], dma_calls[2], down_calls[2];
static unsigned int registrations, live, locks, mode, delays;
static int admission[2] = {-EAGAIN, -ENOTSUP};
static void *kmm_memalign(int alignment, size_t size) {
  (void)alignment; ++live; return malloc(size);
}
static void kmm_free(void *pointer) { if (pointer) { --live; free(pointer); } }
static int netdev_register(struct net_driver_s *dev, int type) {
  assert(dev && type == NET_LL_ETHERNET); ++registrations; return 0;
}
int rzv2h_ether_sample_access(int intf) {
  assert(intf >= 0 && intf < 2); return admission[intf];
}
uint32_t rzv2h_ether_sample_phy_writes_at(int intf) {
  assert(intf >= 0 && intf < 2); return 11u * (intf + 1);
}
static unsigned int port_at(uintptr_t address) {
  unsigned int port = address >= 0x15c40000u ? 1 : 0;
  uintptr_t base = port ? 0x15c40000u : 0x15c30000u;
  assert(address >= base && address < base + sizeof(regs[port]));
  assert(admission[port] == 0);
  return port;
}
static uint32_t getreg32(uintptr_t address) {
  unsigned int port = port_at(address); ++reads[port];
  return regs[port][(address - g_rzv_eth[port].base) / 4];
}
static void putreg32(uint32_t value, uintptr_t address) {
  unsigned int port = port_at(address); ++writes[port];
  regs[port][(address - g_rzv_eth[port].base) / 4] = value;
}
static void net_lock(void) { assert(locks++ == 0); }
static void net_unlock(void) { assert(locks-- == 1); }
static bool work_available(struct work_s *work) { return !work->busy; }
static void work_cancel(int queue, struct work_s *work) { (void)queue; work->busy = 0; }
static void wd_cancel(struct wdog_s *wdog) { wdog->active = 0; }
static void rzv_icu_detach(int irq) { (void)irq; }
void rzv_ether_board_set_speed(int intf, int speed) {
  assert(speed == 0); ++down_calls[intf];
}
static void rzv_phy_poll_work(void *arg) { (void)arg; }
static int rzv_icu_attach(int event, int (*handler)(int,void *,void *),
                          void *arg, bool enabled) {
  (void)event; (void)handler; (void)arg; (void)enabled; return 40;
}
static int rzv_interrupt(int irq, void *context, void *arg) {
  (void)irq; (void)context; (void)arg; return 0;
}
static void work_queue(int queue, struct work_s *work, void (*fn)(void *),
                       void *arg, int delay) {
  (void)queue; (void)fn; (void)arg; (void)delay; work->busy = 1;
}
static int rzv_configure_link(struct rzv_eth_s *priv) { (void)priv; return 0; }
static int rzv_txavail(struct net_driver_s *dev) { (void)dev; return 0; }
static int rzv_ifup(struct net_driver_s *dev);
static int rzv_ifdown(struct net_driver_s *dev);
static int rzv_dma_setup(struct rzv_eth_s *priv) {
  assert(admission[priv->intf] == 0); ++dma_calls[priv->intf];
  priv->rxdesc[0].des3 = RDES3_OWN;
  return mode == 1 ? -EIO : 0;
}
static int rzv_transmit(struct rzv_eth_s *priv) {
  if (mode == 2) return -EIO;
  if (mode == 3) return 0;
  memcpy(priv->rxbuffer, priv->dev.d_buf, priv->dev.d_len);
  if (mode == 4) priv->rxbuffer[0] ^= 1;
  priv->rxdesc[0].des3 = RDES3_FD | RDES3_LD |
                        (priv->dev.d_len << RDES3_FL_SHIFT);
  return 0;
}
static void up_udelay(unsigned int usecs) { assert(usecs == 1000); ++delays; }
static void rzv_invalidate_dcache_region(void *pointer, unsigned int size) {
  assert(pointer && size == RZV_ETHER_BUFSIZE);
}
'''
        for signature in (
                "static void rzv_free_buffers(", "static int rzv_alloc_buffers(",
                "int rzv_ether_initialize(", "static int rzv_ifdown(",
                "static int rzv_ifup(", "static int rzv_ether_sample_select(",
                "int rzv2h_ether_sample_state_at(", "int rzv2h_ether_sample_state(",
                "static bool rzv_sample_frame_matches(",
                "int rzv2h_ether_sample_loopback_at(", "int rzv2h_ether_sample_loopback("):
            code += b.EXTRACT.definition(source, signature)
        code += r'''
int main(void) {
  struct rzv2h_ether_sample_state_s state0, state1;
  uint8_t frame[128]; memset(frame, 0xa5, sizeof(frame));
  assert(rzv_ether_initialize(-1) == -EINVAL && rzv_ether_initialize(2) == -EINVAL);
  assert(!live && !registrations);
  assert(rzv_ether_initialize(0) == 0 && rzv_ether_initialize(1) == 0);
  assert(registrations == 2 && live == 6);
  assert(rzv_ether_initialize(0) == 0 && rzv_ether_initialize(1) == 0);
  assert(registrations == 2 && live == 6);
  assert(g_rzv_eth[0].base == 0x15c30000u && g_rzv_eth[1].base == 0x15c40000u);
  assert(g_rzv_eth[0].event == 422 && g_rzv_eth[1].event == 437);
  assert(g_rzv_eth[0].txdesc != g_rzv_eth[1].txdesc);
  assert(g_rzv_eth[0].rxbuffer != g_rzv_eth[1].rxbuffer);
  assert(rzv2h_ether_sample_state_at(-1, &state0) == -EINVAL);
  assert(rzv2h_ether_sample_state_at(2, &state0) == -EINVAL);
  assert(rzv2h_ether_sample_state_at(0, NULL) == -EINVAL);
  assert(rzv2h_ether_sample_loopback_at(-1, frame, sizeof(frame)) == -EINVAL);
  assert(rzv2h_ether_sample_loopback_at(2, frame, sizeof(frame)) == -EINVAL);
  assert(rzv2h_ether_sample_loopback_at(0, NULL, sizeof(frame)) == -EINVAL);
  assert(rzv2h_ether_sample_loopback_at(0, frame, 63) == -EINVAL);
  assert(rzv2h_ether_sample_loopback_at(0, frame, 253) == -EINVAL);
  assert(rzv2h_ether_sample_state_at(0, &state0) == -EAGAIN);
  assert(rzv2h_ether_sample_state_at(1, &state1) == -ENOTSUP);
  assert(state0.identity == (uintptr_t)&g_rzv_eth[0].dev);
  assert(state1.identity == (uintptr_t)&g_rzv_eth[1].dev);
  assert(state0.identity != state1.identity && state0.netdevs == 1 && state1.netdevs == 1);
  assert(state0.phy_writes == 11 && state1.phy_writes == 22);
  assert(rzv2h_ether_sample_loopback_at(0, frame, 128) == -EAGAIN);
  assert(rzv2h_ether_sample_loopback_at(1, frame, 128) == -ENOTSUP);
  assert(rzv_ifup(&g_rzv_eth[1].dev) == -ENOTSUP);
  assert(rzv_ifdown(&g_rzv_eth[1].dev) == -ENOTSUP);
  assert(!reads[0] && !reads[1] && !writes[0] && !writes[1]);
  assert(!dma_calls[0] && !dma_calls[1] && !locks);
  admission[0] = 0;
  assert(rzv2h_ether_sample_state(&state0) == 0 && state0.netdevs == 1);
  for (mode = 0; mode <= 4; ++mode) {
    int expected = mode == 0 ? 0 : mode == 3 ? -ETIMEDOUT : -EIO;
    assert(rzv2h_ether_sample_loopback(frame, sizeof(frame)) == expected);
    assert(rzv2h_ether_sample_state(&state0) == 0);
    assert(!state0.loop && !state0.dma_running && !state0.queued_work && !state0.attached_irqs);
    assert(!g_rzv_eth[0].dev.d_len && !locks);
    assert(!reads[1] && !writes[1] && !dma_calls[1] && !down_calls[1]);
  }
  assert(delays == 1000 && dma_calls[0] == 5 && down_calls[0] == 5);
  mode = 0;
  g_rzv_eth[0].bifup = true;
  assert(rzv2h_ether_sample_loopback(frame, sizeof(frame)) == -EBUSY);
  g_rzv_eth[0].bifup = false;
  /* The host boundary can admit MAC1 to test selection; the real board never does. */
  admission[1] = 0;
  unsigned int before0 = reads[0] + writes[0];
  assert(rzv2h_ether_sample_loopback_at(1, frame, sizeof(frame)) == 0);
  assert(dma_calls[1] == 1 && down_calls[1] == 1);
  assert(reads[0] + writes[0] == before0);
  assert(rzv2h_ether_sample_state_at(1, &state1) == 0 && !state1.loop && !state1.dma_running);
  for (int intf = 0; intf < 2; ++intf) rzv_free_buffers(&g_rzv_eth[intf]);
  assert(!live && !locks);
  return 0;
}
'''
        b.compile_run(code)

    def test_real_phy_code_has_indexed_counters_and_rejects_unowned_mdio(self):
        b = boundary_module()
        code = b.PRELUDE + r'''
#define CONFIG_RZV_ETHERNET 1
#define CONFIG_RZV2H_SAMPLE_TEST_API 1
#define nerr(...) ((void)0)
#define ninfo(...) ((void)0)
#define nwarn(...) ((void)0)
''' + without_includes(ARCH / "hardware/rzv_ether.h")
        code += without_includes(ARCH / "rzv_ether_phy.h") + r'''
static int admitted[2] = {-EAGAIN, -ENOTSUP};
static unsigned int reads[2], writes[2], busy;
int rzv2h_ether_sample_access(int intf) { assert(intf >= 0 && intf < 2); return admitted[intf]; }
static unsigned int port_at(uintptr_t address) {
  unsigned int port = address >= RZV_ETHER1_BASE ? 1 : 0;
  uintptr_t base = port ? RZV_ETHER1_BASE : RZV_ETHER0_BASE;
  assert(admitted[port] == 0 && (address == base + RZV_ETH_MAC_MII_ADDR ||
                              address == base + RZV_ETH_MAC_MII_DATA));
  return port;
}
static uint32_t getreg32(uintptr_t address) {
  unsigned int port = port_at(address); ++reads[port];
  return busy ? MAC_MII_ADDR_GB : 0;
}
static void putreg32(uint32_t value, uintptr_t address) { (void)value; ++writes[port_at(address)]; }
static void up_mdelay(unsigned int delay) { (void)delay; }
''' + without_includes(ARCH / "rzv_ether_phy.c") + r'''
int main(void) {
  uint16_t data;
  assert(rzv_phy_write(0, 1, 0, 0) == -EINVAL);
  assert(rzv_phy_read(0, 1, 0, &data) == -EINVAL);
  assert(rzv_phy_write(RZV_ETHER0_BASE, 1, 0, 0) == -EAGAIN);
  assert(rzv_phy_write(RZV_ETHER1_BASE, 1, 0, 0) == -ENOTSUP);
  assert(rzv_phy_read(RZV_ETHER1_BASE, 1, 0, &data) == -ENOTSUP);
  assert(!reads[0] && !reads[1] && !writes[0] && !writes[1]);
  assert(!rzv2h_ether_sample_phy_writes_at(0) && !rzv2h_ether_sample_phy_writes_at(1));
  admitted[0] = 0;
  assert(rzv_phy_read(RZV_ETHER0_BASE, 1, 0, NULL) == -EINVAL && !reads[0]);
  assert(rzv_phy_write(RZV_ETHER0_BASE, 1, 0, 0x1234) == 0);
  assert(rzv2h_ether_sample_phy_writes() == 1 && !writes[1]);
  busy = 1;
  assert(rzv_phy_write(RZV_ETHER0_BASE, 1, 0, 0x1234) == -ETIMEDOUT);
  assert(rzv2h_ether_sample_phy_writes() == 2);
  busy = 0; admitted[1] = 0;
  assert(rzv_phy_write(RZV_ETHER1_BASE, 1, 0, 0x5678) == 0);
  assert(rzv2h_ether_sample_phy_writes_at(1) == 1);
  assert(rzv2h_ether_sample_phy_writes() == 2);
  assert(!rzv2h_ether_sample_phy_writes_at(-1) && !rzv2h_ether_sample_phy_writes_at(2));
  return 0;
}
'''
        b.compile_run(code)


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
    @staticmethod
    def support():
        spec = importlib.util.spec_from_file_location(
            "two_ports", ROOT / "test/rzv2h-ether-two-port-runtime-test.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_mac1_only_does_not_touch_disabled_mac0(self):
        m = self.support()
        m.run(m.board_harness(2) + r'''
int main(void) {
  assert(rzv2h_ether_sample_access(0) == -ENODEV);
  assert(rzv2h_ether_sample_access(1) == -EAGAIN);
  assert(rzv2h_ether_initialize() == 0);
  assert(calls[0] == 0 && clocks[0] == 0 && resets[0] == 0);
  assert(calls[1] == 1 && clocks[1] == 1 && resets[1] == 1);
  assert(rzv2h_ether_sample_access(1) == 0);
  return 0;
}
''')

    def test_clock_reset_and_registration_failures_allow_retry(self):
        m = self.support()
        for stage,error in ((1,"ETIMEDOUT"),(2,"EIO"),(3,"ENOMEM")):
            with self.subTest(stage=stage):
                m.run(m.board_harness(3) + r'''
int main(void) {
  failure_port=0; failure_stage=STAGE;
  assert(rzv2h_ether_initialize()==-ERROR);
  assert(clocks[0]==0 && resets[0]==0);
  assert(clocks[1]==1 && resets[1]==1 && calls[1]==1);
  assert(rzv2h_ether_sample_access(0)==-EAGAIN);
  assert(rzv2h_ether_sample_access(1)==0);
  failure_port=-1; assert(rzv2h_ether_initialize()==0);
  assert(clocks[0]==1 && resets[0]==1 && calls[1]==1);
  assert(rzv2h_ether_sample_access(0)==0);
  return 0;
}
'''.replace("STAGE",str(stage)).replace("ERROR",error))


if __name__ == "__main__":
    unittest.main()
