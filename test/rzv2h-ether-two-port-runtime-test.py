#!/usr/bin/env python3
"""Execute both GBETH board instances against manual-derived MMIO rules."""

import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
BOARD = ROOT / 'platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h'


def clean(path):
    return re.sub(r'^\s*#\s*include[^\n]*$', '', path.read_text(), flags=re.M)


def boundary():
    spec = importlib.util.spec_from_file_location(
        'boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(code):
    with tempfile.TemporaryDirectory(prefix='rzv2h-two-ether-') as tmp:
        path = Path(tmp)
        (path / 'test.c').write_text(code)
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-function', '-Wno-unused-variable',
                        str(path / 'test.c'), '-o', str(path / 'test')], check=True)
        subprocess.run([str(path / 'test')], check=True)


def board_harness(mask, controlled=True, rgmii=True):
    definitions = '\n'.join(f'#define CONFIG_RZV_ETHER{i} 1'
                            for i in range(2) if mask & (1 << i))
    definitions += '\n#define CONFIG_RZV_ETHERNET 1\n#define CONFIG_RZV2H_SAMPLE_TEST_API 1\n'
    if controlled:
        definitions += '#define CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT 1\n'
    if rgmii:
        definitions += '#define CONFIG_RZV_ETHER_PHY_RGMII 1\n'
    return r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <stddef.h>
#define OK 0
#define LOG_INFO 0
#define syslog(...) ((void)0)
#define nwarn(...) ((void)0)
#define nerr(...) ((void)0)
#define RZV_CPG_CLK_ETH0 80u
#define RZV_CPG_CLK_ETH1 81u
#define NXMUTEX_INITIALIZER 0
typedef int mutex_t;
static unsigned calls[2], clocks[2], resets[2], writes[2];
static uint32_t cfg[2] = {0xa5a10003, 0x5a510003};
static int failure_port = -1, failure_stage;
static int nxmutex_lock(mutex_t *m) { assert(*m == 0); *m = 1; return 0; }
static int nxmutex_unlock(mutex_t *m) { assert(*m == 1); *m = 0; return 0; }
static unsigned port(uint32_t id) { assert(id == 80 || id == 81); return id - 80; }
static int rzv_clock_enable(uint32_t id) {
  unsigned p = port(id); ++clocks[p];
  return failure_port == (int)p && failure_stage == 1 ? -ETIMEDOUT : 0;
}
static int rzv_clock_disable(uint32_t id) {
  unsigned p = port(id); assert(clocks[p]); --clocks[p]; return 0;
}
static int rzv_module_unreset(uint32_t id) {
  unsigned p = port(id); ++resets[p];
  return failure_port == (int)p && failure_stage == 2 ? -EIO : 0;
}
static int rzv_module_reset(uint32_t id) {
  unsigned p = port(id); assert(resets[p]); --resets[p]; return 0;
}
static int rzv_ether_initialize(int p) {
  assert(p >= 0 && p < 2); ++calls[p];
  return failure_port == p && failure_stage == 3 ? -ENOMEM : 0;
}
''' + definitions + clean(ARCH / 'hardware/rzv_sysc.h') + r'''
static unsigned reg_port(uintptr_t address) {
  assert(address == RZV_SYSC_SYS_GBETH0_CFG || address == RZV_SYSC_SYS_GBETH1_CFG);
  return address == RZV_SYSC_SYS_GBETH1_CFG;
}
static uint32_t getreg32(uintptr_t address) { return cfg[reg_port(address)]; }
static void putreg32(uint32_t value, uintptr_t address) {
  unsigned p = reg_port(address);
  /* HWM p595: MAC_SPEED is read-only, PHY_INTF_TYPE admits only 0 or 1. */
  assert((value & 3u) == (cfg[p] & 3u));
  assert(((value >> 16) & 7u) <= 1u);
  ++writes[p]; cfg[p] = value;
}
''' + clean(BOARD / 'src/rzv2h_ether.c')


class TwoPortBoard(unittest.TestCase):
    def test_each_selection_registers_only_its_hardware_instances(self):
        for mask in range(4):
            for controlled in (True, False):
                with self.subTest(mask=mask, controlled=controlled):
                    run(board_harness(mask, controlled) + r'''
int main(void) {
  assert(rzv2h_ether_initialize() == 0);
  for (int p = 0; p < 2; ++p) {
    bool enabled = (MASK & (1u << p)) != 0;
    assert(calls[p] == enabled && clocks[p] == enabled && resets[p] == enabled);
    assert(rzv2h_ether_sample_access(p) == (enabled ? 0 : -ENODEV));
    assert(writes[p] == (enabled && !CONTROLLED));
  }
  assert(rzv2h_ether_initialize() == 0);
  for (int p = 0; p < 2; ++p) assert(calls[p] == !!(MASK & (1u << p)));
  assert(rzv2h_ether_sample_access(-1) == -EINVAL);
  assert(rzv2h_ether_sample_access(2) == -EINVAL);
  return 0;
}
'''.replace('MASK', str(mask)).replace('CONTROLLED', str(int(controlled))))

    def test_failed_second_port_preserves_first_and_retries_only_failed_port(self):
        for stage, error in ((1, 'ETIMEDOUT'), (2, 'EIO'), (3, 'ENOMEM')):
            with self.subTest(stage=stage):
                run(board_harness(3) + r'''
int main(void) {
  failure_port = 1; failure_stage = STAGE;
  assert(rzv2h_ether_initialize() == -ERROR);
  assert(calls[0] == 1 && clocks[0] == 1 && resets[0] == 1);
  assert(clocks[1] == 0 && resets[1] == 0);
  assert(rzv2h_ether_sample_access(0) == 0);
  assert(rzv2h_ether_sample_access(1) == -EAGAIN);
  failure_port = -1;
  assert(rzv2h_ether_initialize() == 0);
  assert(calls[0] == 1 && calls[1] == (STAGE == 3 ? 2 : 1));
  assert(clocks[0] == 1 && clocks[1] == 1 && resets[0] == 1 && resets[1] == 1);
  return 0;
}
'''.replace('STAGE', str(stage)).replace('ERROR', error))

    def test_mii_selection_programs_zero_on_each_port(self):
        run(board_harness(3, False, False) + r'''
int main(void) {
  assert(rzv2h_ether_initialize() == 0);
  assert(((cfg[0] >> 16) & 7u) == 0 && ((cfg[1] >> 16) & 7u) == 0);
  assert(writes[0] == 1 && writes[1] == 1);
  return 0;
}
''')

    def test_failed_registration_restores_only_its_phy_mode(self):
        run(board_harness(3, False, False) + r'''
int main(void) {
  uint32_t previous1=cfg[1]; failure_port=1; failure_stage=3;
  assert(rzv2h_ether_initialize()==-ENOMEM);
  assert(((cfg[0]>>16)&7u)==0 && cfg[1]==previous1);
  assert(clocks[0]==1 && resets[0]==1 && clocks[1]==0 && resets[1]==0);
  failure_port=-1; assert(rzv2h_ether_initialize()==0);
  assert(((cfg[1]>>16)&7u)==0 && calls[0]==1 && calls[1]==2);
  return 0;
}
''')


class HardwareViews(unittest.TestCase):
    def test_all_six_base_aliases_and_two_csdiv_offsets(self):
        for cm33 in (False, True):
            run(('#define CONFIG_RZV2H_BUILD_CM33 1\n' if cm33 else '') +
                '#include <stdint.h>\n#include <assert.h>\n' +
                clean(ARCH / 'hardware/rzv_ether.h') +
                clean(ARCH / 'hardware/rzv_cpg.h') + r'''
int main(void) {
  assert(RZV_ETHER0_BASE_CR8 == 0x15c30000u);
  assert(RZV_ETHER1_BASE_CR8 == 0x15c40000u);
  assert(RZV_ETHER0_BASE_CM33_NS == 0x55c30000u);
  assert(RZV_ETHER1_BASE_CM33_NS == 0x55c40000u);
  assert(RZV_ETHER0_BASE_CM33_S == 0x45c30000u);
  assert(RZV_ETHER1_BASE_CM33_S == 0x45c40000u);
  assert(RZV_ETHER0_BASE == BASE0 && RZV_ETHER1_BASE == BASE1);
  assert(RZV_CPG_CSDIV_OFFSET(0) == 0x4f0u);
  assert(RZV_CPG_CSDIV_OFFSET(1) == 0x4f4u);
  return 0;
}
'''.replace('BASE0', '0x45c30000u' if cm33 else '0x15c30000u').replace(
                    'BASE1', '0x45c40000u' if cm33 else '0x15c40000u'))


class GbEthReference(unittest.TestCase):
    def test_vendor_csdiv_and_sysc_layout(self):
        for core in ('cr8_0', 'cr8_1', 'cm33'):
            with self.subTest(core=core):
                view = 'cm' if core == 'cm33' else 'cr'
                root = ROOT / (f'refs/rzv2h_evk/adc_e/adc_e_rzv2h_evk_{core}_ep/e2studio/'
                    'rzv/fsp/src/bsp/cmsis/Device/RENESAS/Include/R9A09G057H/' + view + '/iodefines')
                self.check_layout(root, core)

    def check_layout(self, root, core):
        cpg = root / 'cpg_iodefine.h'
        sysc = root / 'sysc_iodefine.h'
        self.assertTrue(cpg.is_file() and sysc.is_file(), 'primary CMSIS reference required')
        prefix = '#define CONFIG_RZV2H_BUILD_CM33 1\n' if core == 'cm33' else ''
        run(prefix + '#include <stdint.h>\n#include <stddef.h>\n#include <assert.h>\n'
            '#define __IM volatile const\n#define __IOM volatile\n#define __OM volatile\n' +
            clean(cpg) + clean(sysc) + clean(ARCH / 'hardware/rzv_cpg.h') + r'''
int main(void) {
  /* Register coordinates follow the selected vendor I/O headers. */
  assert(offsetof(R_CPG_Type, CPG_CSDIV0) == 0x4f0);
  assert(RZV_CPG_CSDIV_OFFSET(0) == offsetof(R_CPG_Type, CPG_CSDIV0));
  assert(offsetof(R_CPG_Type, CPG_CSDIV1) == 0x4f4);
  assert(RZV_CPG_CSDIV_OFFSET(1) == offsetof(R_CPG_Type, CPG_CSDIV1));
  assert(RZV_CPG_BASE == R_CPG_BASE);
  assert(RZV_CPG_CSDIV(0) == R_CPG_BASE + offsetof(R_CPG_Type, CPG_CSDIV0));
  assert(RZV_CPG_CSDIV(1) == R_CPG_BASE + offsetof(R_CPG_Type, CPG_CSDIV1));
  /* HWM offsets use a block origin sixteen bytes before the I/O base. */
  assert(RZV_CPG_CSDIV(0) == (R_CPG_BASE - 0x10u) + 0x500u);
  assert(RZV_CPG_CSDIV(1) == (R_CPG_BASE - 0x10u) + 0x504u);
  assert(offsetof(R_SYSC_Type, SYS_GBETH0_CFG) == 0xf00);
  assert(offsetof(R_SYSC_Type, SYS_GBETH1_CFG) == 0xf04);
  return 0;
}
''')


def clock_harness():
    b = boundary()
    source = (ARCH / 'rzv_clock.c').read_text()
    ids = '\n'.join(line for line in (ARCH / 'rzv_clock.h').read_text().splitlines()
                    if re.match(r'#define RZV_CPG_(CLK_|BIT\(|DOMAIN\()', line))
    code = b.PRELUDE + clean(ARCH / 'hardware/rzv_cpg.h') + '\n' + ids + r'''
typedef int mutex_t;
typedef int irqstate_t;
static mutex_t g_ether_clock_lock[2];
static uint32_t gates[16], csdiv;
static unsigned selected, reads, writes, divwrites, polls, fail_polls;
static bool irq_context, mutex_error, reject_divider;
static int depth;
#define CPG_TIMEOUT_CLOCK_ENABLE 3
#define CPG_TIMEOUT_CLOCK_DISABLE 3
#define clkerr(...) ((void)0)
static bool up_interrupt_context(void) { return irq_context; }
static int nxmutex_lock(mutex_t *p) {
  if (mutex_error) return -EBUSY;
  assert(p == &g_ether_clock_lock[selected] && *p == 0); ++*p; return 0;
}
static int nxmutex_unlock(mutex_t *p) { assert(*p == 1); --*p; return 0; }
static irqstate_t enter_critical_section(void) { assert(depth == 0); ++depth; return 0; }
static void leave_critical_section(irqstate_t p) { (void)p; assert(depth == 1); --depth; }
static int rzv_cpg_sci_channel(uint32_t id) { (void)id; return -1; }
static uint32_t rzv_cpg_getreg(uintptr_t address) {
  ++reads;
  if (address == RZV_CPG_CSDIV(0)) return csdiv;
  assert(address >= RZV_CPG_CLKON(0) && address <= RZV_CPG_CLKON(15));
  return gates[(address - RZV_CPG_CLKON(0)) / 4u];
}
static void rzv_cpg_putreg(uint32_t value, uintptr_t address) {
  assert(depth == 1); ++writes;
  unsigned first = selected == 0 ? 184 : 190;
  if (address == RZV_CPG_CSDIV(0)) {
    unsigned shift = selected * 4;
    assert((value & 0x11110000u) == (1u << (16u + shift)));
    for (unsigned bit = first; bit < first + 4; ++bit)
      assert(!(gates[bit / 16] & (1u << (bit % 16))));
    ++divwrites;
    if (!reject_divider || divwrites != 1)
      csdiv = (csdiv & ~(3u << shift)) | (value & (3u << shift));
    return;
  }
  assert(address >= RZV_CPG_CLKON(0) && address <= RZV_CPG_CLKON(15));
  unsigned bank = (address - RZV_CPG_CLKON(0)) / 4u;
  uint32_t allowed = 0;
  for (unsigned bit = first; bit < first + 4; ++bit)
    if (bit / 16u == bank) allowed |= 1u << (bit % 16u);
  assert(allowed && (value >> 16) == allowed);
  gates[bank] = (gates[bank] & ~allowed) | (value & allowed);
}
static int rzv_cpg_wait_clkmon(uint32_t first, uint32_t count, bool on, int timeout) {
  assert(!depth && first == (selected == 0 ? 184u : 190u) && count == 4 && timeout == 3);
  ++polls;
  if (fail_polls & (1u << polls)) return -ETIMEDOUT;
  for (unsigned bit = first; bit < first + count; ++bit)
    assert(!!(gates[bit / 16u] & (1u << (bit % 16u))) == on);
  return 0;
}
'''
    for name in ('static void rzv_cpg_clock_span(',
                 'static void rzv_cpg_write_clock_span(',
                 'static void rzv_ether_write_divider(',
                 'int rzv_ether_set_link_clock('):
        code += b.EXTRACT.definition(source, name)
    return code + r'''
static void reset(unsigned port, unsigned old) {
  selected = port;
  for (unsigned i = 0; i < 16; ++i) gates[i] = 0xa5a5ffffu;
  csdiv = 0x24682210u;
  csdiv = (csdiv & ~(3u << (port * 4u))) | (old << (port * 4u));
  reads = writes = polls = divwrites = fail_polls = 0;
  irq_context = mutex_error = reject_divider = false;
}
static void unchanged(uint32_t old, const uint32_t *previous) {
  assert(!memcmp(gates, previous, sizeof(gates)));
  assert((csdiv & ~(3u << (selected * 4u))) == (old & ~(3u << (selected * 4u))));
  assert(!depth && !g_ether_clock_lock[0] && !g_ether_clock_lock[1]);
}
'''


class IndependentClock(unittest.TestCase):
    def test_rates_preserve_peer_aclk_mstop_and_unrelated_dividers(self):
        run(clock_harness() + r'''
int main(void) {
  unsigned speed[] = {1000,100,10};
  for (unsigned p = 0; p < 2; ++p) for (unsigned old = 0; old < 3; ++old)
    for (unsigned value = 0; value < 3; ++value) {
      reset(p,old); uint32_t before = csdiv, previous[16];
      memcpy(previous,gates,sizeof(gates));
      assert(rzv_ether_set_link_clock(p,speed[value]) == 0);
      assert(((csdiv >> (p * 4u)) & 3u) == value);
      assert(divwrites == (old != value)); unchanged(before,previous);
    }
  return 0;
}
''')

    def test_invalid_unowned_and_failed_transitions_are_bounded_and_local(self):
        run(clock_harness() + r'''
int main(void) {
  reset(0,0);
  assert(rzv_ether_set_link_clock(2,100) == -EINVAL);
  assert(rzv_ether_set_link_clock(UINT_MAX,100) == -EINVAL);
  assert(rzv_ether_set_link_clock(0,0) == -EINVAL);
  irq_context=true; assert(rzv_ether_set_link_clock(0,100)==-EPERM);
  irq_context=false; mutex_error=true;
  assert(rzv_ether_set_link_clock(0,100)==-EBUSY && !reads && !writes);
  for (unsigned p=0;p<2;++p) {
    reset(p,0); gates[(p ? 190 : 184)/16u] &= ~(1u << ((p ? 190 : 184)%16u));
    assert(rzv_ether_set_link_clock(p,100)==-EAGAIN && !writes);
    for (unsigned failure=1;failure<=3;++failure) {
      reset(p,0); uint32_t old=csdiv, previous[16]; memcpy(previous,gates,sizeof(gates));
      fail_polls=1u<<failure;
      assert(rzv_ether_set_link_clock(p,100)==-ETIMEDOUT);
      assert(((csdiv>>(p*4u))&3u)==0); unchanged(old,previous);
      fail_polls=0; assert(rzv_ether_set_link_clock(p,100)==0);
    }
    reset(p,0); uint32_t old=csdiv, previous[16]; memcpy(previous,gates,sizeof(gates));
    reject_divider=true; assert(rzv_ether_set_link_clock(p,100)==-EIO);
    assert(csdiv==old); unchanged(old,previous);
    reset(p,0); old=csdiv; memcpy(previous,gates,sizeof(gates));
    fail_polls=(1u<<3)|(1u<<4)|(1u<<5);
    assert(rzv_ether_set_link_clock(p,100)==-ETIMEDOUT);
    assert(divwrites==1); unchanged(old,previous);
  }
  return 0;
}
''')


def link_harness(poll_source=None):
    b = boundary()
    source = (ARCH / 'rzv_ether.c').read_text()
    poll = source if poll_source is None else poll_source.read_text()
    code = b.PRELUDE + clean(ARCH / 'hardware/rzv_ether.h')
    code += clean(ARCH / 'rzv_ether_phy.h') + r'''
#define CONFIG_RZV_ETHER_PHY_RGMII 1
#define CONFIG_RZV_ETHER_PHY_ADDR 0
#define LPWORK 1
#define RZV_ETHER_PHY_POLL_PERIOD 100
#define ninfo(...) ((void)0)
#define nerr(...) ((void)0)
#define nwarn(...) ((void)0)
struct rzv_eth_s {
  uintptr_t base; unsigned int intf; bool bifup,linkup,duplex;
  int speed,phy_addr,pollwork; uint32_t phy_id;
};
static uint32_t mac[2];
static unsigned selected, clocks, writes, notifications, queued, phy_reads;
static int clock_error, link_value, depth;
static void net_lock(void) { assert(!depth); ++depth; }
static void net_unlock(void) { assert(depth==1); --depth; }
static unsigned reg_port(uintptr_t address) {
  assert(address==RZV_ETHER0_BASE+RZV_ETH_MAC_CONF || address==RZV_ETHER1_BASE+RZV_ETH_MAC_CONF);
  unsigned p=address==RZV_ETHER1_BASE+RZV_ETH_MAC_CONF; assert(p==selected); return p;
}
static uint32_t getreg32(uintptr_t address) { return mac[reg_port(address)]; }
static void putreg32(uint32_t value,uintptr_t address) { ++writes; mac[reg_port(address)]=value; }
static int rzv_ether_set_link_clock(unsigned p,unsigned mbps) {
  assert(p==selected && (mbps==10 || mbps==100 || mbps==1000)); ++clocks;
  assert(!(mac[p]&(MAC_CONF_TE|MAC_CONF_RE))); return clock_error;
}
static void rzv_ether_board_set_speed(int p,int mbps) {
  assert(p==(int)selected && (mbps==0 || mbps==10 || mbps==100 || mbps==1000)); ++notifications;
}
int rzv_phy_linkstatus(uintptr_t base,uint8_t phy) {
  assert(base==(selected ? RZV_ETHER1_BASE:RZV_ETHER0_BASE) && phy==3);
  ++phy_reads; return link_value;
}
int rzv_phy_probe(uintptr_t base,int preferred,uint8_t *phy,uint32_t *id) {
  assert(base==(selected ? RZV_ETHER1_BASE:RZV_ETHER0_BASE) && preferred==0);
  *phy=3; *id=0x12345678; return 0;
}
int rzv_phy_reset(uintptr_t base,uint8_t phy) { (void)base; assert(phy==3); return 0; }
int rzv_phy_autonegotiate(uintptr_t base,uint8_t phy) { (void)base; assert(phy==3); return link_value; }
static void work_queue(int queue,int *work,void (*fn)(void *),void *arg,int delay) {
  (void)work; (void)fn; (void)arg; assert(queue==1 && delay==100); ++queued;
}
'''
    code += b.EXTRACT.definition(source, 'static int rzv_apply_link(')
    code += b.EXTRACT.definition(source, 'static int rzv_configure_link(')
    code += b.EXTRACT.definition(poll, 'static void rzv_phy_poll_work(')
    return code


class LinkTransitions(unittest.TestCase):
    def test_worker_programs_actual_mac_modes_and_preserves_sibling(self):
        run(link_harness() + r'''
int main(void) {
  int links[]={PHY_LINK_1000FD,PHY_LINK_100FD,PHY_LINK_100HD,PHY_LINK_10FD,PHY_LINK_10HD};
  unsigned expected[]={MAC_CONF_DM,MAC_CONF_DM|MAC_CONF_PS|MAC_CONF_FES,
                       MAC_CONF_PS|MAC_CONF_FES,MAC_CONF_DM|MAC_CONF_PS,MAC_CONF_PS};
  int speeds[]={1000,100,100,10,10};
  for(selected=0;selected<2;++selected) {
    struct rzv_eth_s p={.base=selected?RZV_ETHER1_BASE:RZV_ETHER0_BASE,
                        .intf=selected,.bifup=true,.phy_addr=3};
    mac[0]=mac[1]=0x80000000u|MAC_CONF_TE|MAC_CONF_RE;
    uint32_t sibling=mac[1-selected];
    for(unsigned i=0;i<5;++i) {
      link_value=links[i]; unsigned before=clocks;
      rzv_phy_poll_work(&p);
      assert(p.linkup && p.speed==speeds[i]);
      assert((mac[selected]&(MAC_CONF_DM|MAC_CONF_PS|MAC_CONF_FES))==expected[i]);
      assert((mac[selected]&(MAC_CONF_TE|MAC_CONF_RE))==(MAC_CONF_TE|MAC_CONF_RE));
      assert(clocks==before+1 && mac[1-selected]==sibling && !depth);
      before=writes; unsigned oldclocks=clocks;
      rzv_phy_poll_work(&p); assert(writes==before && clocks==oldclocks);
      /* A MAC reset can clear hardware fields without changing cached mode. */
      mac[selected]&=~(MAC_CONF_DM|MAC_CONF_PS|MAC_CONF_FES|MAC_CONF_TE|MAC_CONF_RE);
      rzv_phy_poll_work(&p);
      assert((mac[selected]&(MAC_CONF_DM|MAC_CONF_PS|MAC_CONF_FES))==expected[i]);
      assert((mac[selected]&(MAC_CONF_TE|MAC_CONF_RE))==(MAC_CONF_TE|MAC_CONF_RE));
    }
    link_value=PHY_LINK_DOWN; rzv_phy_poll_work(&p);
    assert(!p.linkup && !(mac[selected]&(MAC_CONF_TE|MAC_CONF_RE)));
    link_value=PHY_LINK_100FD; clock_error=-ETIMEDOUT; rzv_phy_poll_work(&p);
    assert(!p.linkup && p.speed==0 && !(mac[selected]&(MAC_CONF_TE|MAC_CONF_RE)));
    clock_error=0; rzv_phy_poll_work(&p);
    assert(p.linkup && p.speed==100 && (mac[selected]&MAC_CONF_TE));
    p.bifup=false; unsigned old_reads=phy_reads, old_queued=queued;
    rzv_phy_poll_work(&p); assert(phy_reads==old_reads && queued==old_queued && !depth);
    assert(mac[1-selected]==sibling);
  }
  return 0;
}
''')

    def test_initial_link_propagates_clock_failure_and_retries_without_tx(self):
        run(link_harness() + r'''
int main(void) {
  for(selected=0;selected<2;++selected) {
    struct rzv_eth_s p={.base=selected?RZV_ETHER1_BASE:RZV_ETHER0_BASE,.intf=selected};
    mac[0]=mac[1]=0; link_value=PHY_LINK_1000FD; clock_error=-EIO;
    assert(rzv_configure_link(&p)==-EIO && !p.linkup);
    assert(!(mac[selected]&(MAC_CONF_TE|MAC_CONF_RE)));
    clock_error=0; assert(rzv_configure_link(&p)==0 && p.linkup && p.speed==1000);
    assert(p.phy_addr==3 && p.phy_id==0x12345678);
    assert(!(mac[selected]&(MAC_CONF_TE|MAC_CONF_RE)));
  }
  return 0;
}
''')


if __name__ == '__main__':
    if '--portable' in sys.argv:
        sys.argv.remove('--portable')
        unittest.main(defaultTest=[name for name, cls in list(globals().items())
                                  if isinstance(cls, type) and issubclass(cls, unittest.TestCase)
                                  and cls is not GbEthReference])
    else:
        unittest.main()
