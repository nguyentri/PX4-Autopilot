#!/usr/bin/env python3
"""Exercise deferred TX progress, callback publication, shared-GIC routing, IO startup and reporting."""

import importlib.util
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
SPEC = importlib.util.spec_from_file_location('repair', ROOT / 'test/rzv2h-audit-remediation-runtime-test.py')
REPAIR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPAIR)
extract = REPAIR.extract


def io_prelude(owner):
    """Protocol types plus the PX4 PWM bounds the IO tasks validate against."""
    limits = (ROOT / 'src/drivers/drv_pwm_output.h').read_text()
    code = REPAIR.PRE + '#include <deque>\ntypedef uint64_t hrt_abstime;\n'
    for name in ('PWM_LOWEST_MIN', 'PWM_HIGHEST_MAX'):
        code += re.search(rf'^#define {name} \d+$', limits, flags=re.M).group(0) + '\n'
    return code + REPAIR.header(owner / 'protocol.h').replace('#pragma once', '')


class ExpandedRuntime(unittest.TestCase):
    def test_buffered_tx_recovers_without_another_write_and_stops_after_cleanup(self):
        source = (ARCH / 'rzv_ipc_ipcc.c').read_text()
        nuttx = ROOT / 'platforms/nuttx/NuttX/nuttx'
        code = REPAIR.PRE + REPAIR.header(nuttx / 'include/nuttx/mm/circbuf.h')
        circ = (nuttx / 'mm/circbuf/circbuf.c').read_text()
        for name in ('size_t circbuf_used(', 'ssize_t circbuf_peekat(',
                     'ssize_t circbuf_peek(', 'ssize_t circbuf_skip('):
            code += extract(circ, name)
        code += r'''
#define UNUSED(arg) ((void)(arg))
#define CONFIG_IPCC_BUFFERED 1
#define CONFIG_RZV_IPCC_RXBUFSIZE 8
#define CONFIG_RZV_IPCC_TXBUFSIZE 8
#define RZV_OPENAMP_RPMSG_BUFFER_SIZE 4
#define LPWORK 1
#define MSEC2TICK(ms) (ms)
#define NXMUTEX_INITIALIZER 0
#define DEBUGVERIFY(expr) assert((expr) == 0)
struct ipcc_driver_s {int alive;};
struct ipcc_lower_s {struct circbuf_s txbuf;struct ipcc_driver_s *upper;int ops,chan;};
struct rzv_ipcc_state_s {struct ipcc_lower_s lower;bool registered,watcher_attached;};
struct work_s {int unused;};
static struct rzv_ipcc_state_s g_rzv_ipcc;
static struct work_s g_rzv_ipcc_txwork;
static bool g_rzv_ipcc_txpolling;
static int g_rzv_ipcc_txlock, g_rzv_ipcc_lock, g_rzv_ipcc_ops;
static struct ipcc_driver_s upper={1};
static void (*pending)(void *);
static int sends, transient=2, notifications;
static char received[8];
static size_t received_count;
static int nxmutex_lock(int *mutex) {assert(!*mutex);++*mutex;return 0;}
static int nxmutex_unlock(int *mutex) {assert(*mutex==1);--*mutex;return 0;}
static int work_queue(int queue,struct work_s *work,void (*callback)(void *),void *arg,int delay) {
  assert(queue==LPWORK && work==&g_rzv_ipcc_txwork && arg==NULL && delay==10);
  pending=callback;return 0;
}
static ssize_t rzv_rpmsg_send(const char *data,size_t size) {
  assert(g_rzv_ipcc_txlock==1);++sends;
  if(transient-->0)return -ENOMEM;
  memcpy(received+received_count,data,size);received_count+=size;return size;
}
static void ipcc_txfree_notify(struct ipcc_driver_s *p) {
  assert(p==&upper && p->alive && g_rzv_ipcc_lock==1);++notifications;
}
static void rzv_ipcc_rxnotify(void *arg) {}
static int rzv_rpmsg_initialize(void (*notify)(void *),void *arg) {return 0;}
static int ipcc_register(struct ipcc_lower_s *lower,int rx,int tx) {lower->upper=&upper;return 0;}
static int rzv_ipcc_cleanup(struct ipcc_lower_s *lower) {return 0;}
static void rzv_ipcc_buffer_notify(struct rzv_ipcc_state_s *p,struct ipcc_driver_s *u) {}
'''
        for name in ('static ssize_t rzv_ipcc_write_notify(',
                     'static void rzv_ipcc_txpoll(', 'int rzv_ipcc_initialize('):
            code += extract(source, name)
        code += r'''
int main(void) {
  char data[]="abcdefgh";
  assert(rzv_ipcc_initialize()==0 && pending);
  g_rzv_ipcc.lower.txbuf=(struct circbuf_s){.base=data,.size=8,.head=8};
  assert(rzv_ipcc_write_notify(&g_rzv_ipcc.lower)==-ENOMEM);
  for(int i=0;i<3;++i){void (*callback)(void *)=pending;pending=NULL;callback(NULL);}
  assert(received_count==8 && memcmp(received,data,8)==0 && notifications==2);
  assert(g_rzv_ipcc.lower.txbuf.tail==8 && sends==4);
  g_rzv_ipcc.registered=false;g_rzv_ipcc.lower.upper=NULL;upper.alive=0;
  g_rzv_ipcc.lower.txbuf.base=NULL;
  void (*callback)(void *)=pending;pending=NULL;callback(NULL);
  assert(!pending && !g_rzv_ipcc_txpolling && sends==4);
  assert(rzv_ipcc_initialize()==0 && pending && g_rzv_ipcc_txpolling);
}
'''
        REPAIR.run(code)

    def test_ipcc_cleanup_stops_lower_half_before_releasing_upper_state(self):
        source = (ROOT / 'platforms/nuttx/NuttX/nuttx/drivers/ipcc/ipcc_register.c').read_text()
        code = REPAIR.PRE + r'''
#define CONFIG_IPCC_BUFFERED 1
struct circbuf_s {int live;};
struct ipcc_lower_s;
struct ipcc_ops_s {int (*cleanup)(struct ipcc_lower_s *);};
struct ipcc_lower_s {struct ipcc_ops_s ops;struct circbuf_s rxbuf,txbuf;bool registered;};
struct ipcc_driver_s {struct ipcc_lower_s *ipcc;int rxsem,txsem,exclsem;};
static struct ipcc_lower_s lower;
static int released, freed;
static int lower_cleanup(struct ipcc_lower_s *p) {
  assert(p==&lower && !released && lower.rxbuf.live && lower.txbuf.live);
  p->registered=false;return 0;
}
static void circbuf_uninit(struct circbuf_s *c) {assert(!lower.registered);c->live=0;++released;}
static int nxsem_destroy(int *sem) {assert(!lower.registered);*sem=0;++released;return 0;}
static void kmm_free(void *p) {assert(released==5);++freed;}
''' + extract(source, 'void ipcc_cleanup(') + r'''
int main(void) {
  struct ipcc_driver_s priv={&lower,1,1,1};
  lower=(struct ipcc_lower_s){{lower_cleanup},{1},{1},true};
  ipcc_cleanup(&priv);
  assert(!lower.registered && released==5 && freed==1);
}
'''
        REPAIR.run(code)

    def test_gtm_callback_pair_changes_with_interrupts_masked(self):
        code = REPAIR.PRE + r'''
#define tmrinfo(...) ((void)0)
typedef unsigned irqstate_t;
typedef void (*tccb_t)(void);
struct timer_lowerhalf_s {int unused;};
struct rzv_gtm_lowerhalf_s {struct timer_lowerhalf_s lower;tccb_t callback;void *arg;};
static struct rzv_gtm_lowerhalf_s state;
static int old_arg,new_arg,masked;
static void old_callback(void) {}
static void new_callback(void) {}
static irqstate_t enter_critical_section(void) {
  assert(!masked && state.callback==old_callback && state.arg==&old_arg);
  masked=1;return 42;
}
static void leave_critical_section(irqstate_t flags) {
  assert(masked && flags==42 && state.callback==new_callback && state.arg==&new_arg);masked=0;
}
''' + extract((ARCH / 'rzv_gtm.c').read_text(), 'static void gtm_timer_setcallback(')
        code += r'''
int main(void){state.callback=old_callback;state.arg=&old_arg;
  gtm_timer_setcallback(&state.lower,new_callback,&new_arg);
  assert(!masked && state.callback==new_callback && state.arg==&new_arg);}
'''
        REPAIR.run(code)

    def test_cr8_cores_share_the_gic_without_stealing_interrupts(self):
        source = (ARCH / 'rzv_irq.c').read_text()
        macros = ''.join(re.search(rf'^#(?:  )?\s*define {name}\b[^\n]*$', source, flags=re.M).group(0) + '\n'
                         for name in ('GIC_NUM_INTERRUPTS', 'GIC_NUM_SGI', 'GIC_IDLE_PRIORITY',
                                      'RZV_GIC_DEFAULT_PRIORITY', 'RZV_GIC_REG_INDEX1',
                                      'RZV_GIC_REG_INDEX4', 'RZV_GIC_REG_INDEX16'))
        for cr8_1 in (False, True):
            code = REPAIR.PRE + ('#define CONFIG_RZV2H_BUILD_CR8_1 1\n' if cr8_1 else '') + macros + r'''
#define NR_IRQS 544
#define RZV_INTC_GIC_GICD_ICDDCR 0x000u
#define RZV_INTC_GIC_GICD_ICDICTR 0x004u
#define RZV_INTC_GIC_GICD_ICDISER(n) (0x100u + (n) * 4u)
#define RZV_INTC_GIC_GICD_ICDICER(n) (0x180u + (n) * 4u)
#define RZV_INTC_GIC_GICD_ICDICPR(n) (0x280u + (n) * 4u)
#define RZV_INTC_GIC_GICD_ICDABR(n) (0x300u + (n) * 4u)
#define RZV_INTC_GIC_GICD_ICDIPR(n) (0x400u + (n) * 4u)
#define RZV_INTC_GIC_GICD_ICDIPTR(n) (0x800u + (n) * 4u)
#define RZV_INTC_GIC_GICD_ICDICFR(n) (0xc00u + (n) * 4u)
#define RZV_INTC_GIC_GICC_ICCICR 0x1000u
#define RZV_INTC_GIC_GICC_ICCPMR 0x1004u
#define RZV_INTC_GIC_GICC_ICCBPR 0x1008u
#define RZV_INTC_GIC_GICC_ICCEOIR 0x1010u
#define RZV_INTC_GIC_GICC_ICCRPR 0x1014u
#define INTC_GIC_GICD_ICDICTR_IT_MASK 0x1fu
#define INTC_GIC_GICD_ICDDCR_EN 1u
#define INTC_GIC_GICC_ICCICR_EN 1u
/* Shared distributor model: CR8-0 is CPU interface 0x01, CR8-1 is 0x02.
 * active[irq] is the CPU interface that acknowledged irq and has not ended
 * it; that interface's running priority stays raised until it does.
 */
static uint8_t self_mask, target[NR_IRQS], active[NR_IRQS];
static uint32_t enabled[NR_IRQS / 32], regs[0x1020 / 4];
static int distributor_disabled, foreign_eoi;
static uint32_t getreg32(uintptr_t addr) {
  if (addr == RZV_INTC_GIC_GICD_ICDICTR) return NR_IRQS / 32 - 1;
  if (addr >= 0x300 && addr < 0x300 + NR_IRQS / 8) {
    uint32_t bits = 0, base = (addr - 0x300) * 8;
    for (unsigned i = 0; i < 32; ++i) bits |= (active[base + i] != 0) << i;
    return bits;
  }
  if (addr == RZV_INTC_GIC_GICC_ICCRPR) {
    for (unsigned i = 0; i < NR_IRQS; ++i) if (active[i] == self_mask) return RZV_GIC_DEFAULT_PRIORITY;
    return GIC_IDLE_PRIORITY;
  }
  return regs[addr / 4];
}
static void putreg32(uint32_t value, uintptr_t addr) {
  if (addr == RZV_INTC_GIC_GICC_ICCEOIR) {
    assert(value < NR_IRQS && active[value]);
    foreign_eoi += active[value] != self_mask; active[value] = 0; return;
  }
  if (addr >= 0x100 && addr < 0x180) { enabled[(addr - 0x100) / 4] |= value; return; }
  if (addr >= 0x180 && addr < 0x200) { enabled[(addr - 0x180) / 4] &= ~value; return; }
  if (addr >= 0x800 && addr < 0x800 + NR_IRQS) {
    for (unsigned i = 0; i < 4; ++i) target[addr - 0x800 + i] = value >> (8 * i);
    return;
  }
  if (addr == RZV_INTC_GIC_GICD_ICDDCR && value == 0) ++distributor_disabled;
  regs[addr / 4] = value;
}
static uint8_t getreg8(uintptr_t addr) {
  assert(addr >= 0x800 && addr < 0x800 + NR_IRQS);
  return addr < 0x820 ? self_mask : target[addr - 0x800];
}
static void putreg8(uint8_t value, uintptr_t addr) {
  assert(addr >= 0x820 && addr < 0x800 + NR_IRQS);
  target[addr - 0x800] = value;
}
static bool on(int irq) { return enabled[irq / 32] & (1u << (irq % 32)); }
'''
            for name in ('static uint8_t rzv_gic_local_target(', 'static uintptr_t rzv_gic_target_addr(',
                         'static void rzv_gic_end_stale_active(', 'static void rzv_gic_initialize(',
                         'void up_enable_irq('):
                code += extract(source, name) + '\n'
            code += r'''
int main(void) {
  /* CR8-0 owns the distributor and boots first. */
  self_mask = 0x01;
#ifndef CONFIG_RZV2H_BUILD_CR8_1
  memset(target, 0x02, sizeof(target)); enabled[5] = 0xffffffff;
  /* A reloaded CR8-0 still holds 29 and CR8-1's 154 from a crashed image;
   * CR8-1 is handling 500.  Ending stops once CR8-0's priority is idle.
   */
  active[29] = 0x01; active[154] = 0x01; active[500] = 0x02;
  rzv_gic_initialize();
  assert(distributor_disabled == 1 && !on(160) && target[160] == 0x01 && target[543] == 0x01);
  assert(!active[29] && !active[154] && active[500] == 0x02 && !foreign_eoi);
  active[500] = 0;
  assert(regs[RZV_INTC_GIC_GICD_ICDDCR / 4] == INTC_GIC_GICD_ICDDCR_EN);
#else
  for (unsigned i = 32; i < NR_IRQS; ++i) target[i] = 0x01;
#endif
  up_enable_irq(348);                         /* CR8-0 MHU doorbell */
  up_enable_irq(29);                          /* banked private timer */
  assert(on(348) && target[348] == 0x01 && on(29));

  /* CR8-1 boots while CR8-0 runs; a previous CR8-1 image left 154 and 400. */
  target[154] = 0x02; target[400] = 0x02; enabled[154 / 32] |= 1u << (154 % 32);
  enabled[400 / 32] |= 1u << (400 % 32);
  self_mask = 0x02;
#ifdef CONFIG_RZV2H_BUILD_CR8_1
  /* CR8-0 is handling 100.  The previous CR8-1 image left 20 and 154 active
   * and an SGI that cannot be ended without its source CPU.
   */
  active[100] = 0x01; active[3] = 0x02; active[20] = 0x02; active[154] = 0x02;
  rzv_gic_initialize();
  assert(active[100] == 0x01 && active[3] == 0x02 && !active[20] && !active[154] && !foreign_eoi);
  assert(distributor_disabled == 0 && on(348) && target[348] == 0x01);
  assert(!on(154) && !on(400) && !on(29));
  assert(regs[RZV_INTC_GIC_GICD_ICDDCR / 4] == INTC_GIC_GICD_ICDDCR_EN);
#endif
  up_enable_irq(154);                         /* CR8-1 SCI1 TXI */
  up_enable_irq(347);                         /* CR8-1 MHU doorbell */
  assert(on(154) && target[154] == 0x02 && on(347) && target[347] == 0x02);
  assert(target[348] == 0x01 && on(348));

  /* No local mask reported: keep the current routing. */
  self_mask = 0; target[200] = 0x01; up_enable_irq(200);
  assert(on(200) && target[200] == 0x01);
  up_enable_irq(NR_IRQS); up_enable_irq(-1);
}
'''
            REPAIR.run(code)

    def test_io_startup_requires_fmu_transport_and_tolerates_missing_cm33(self):
        # (member, init(is_master) argument, required, optional flag member)
        for relative, cls, transports in (
            ('boards/renesas/rdk-rzv2h-io-cm33/px4io_m33/px4io_m33.cpp', 'Px4IoM33',
             (('_transport', 'false', True, None),)),
        ):
            # The stub must keep the production signature so the caller's
            # failure check is exercised against the real return type.
            header = (ROOT / relative).with_name('sharedmem_transport.h').read_text()
            self.assertRegex(header, r'\n\tbool init\(bool is_master\);')
            code = REPAIR.PRE + '#define PX4_ERR(...) ((void)0)\n#define PX4_WARN(...) ((void)0)\n'
            code += 'static int live, attempts, fail_index = -1;\n'
            code += ('struct Transport {bool master, result;\n'
                     '  bool init(bool is_master) {assert(is_master==master);++attempts;return result;}};\n')
            members = ''.join(f'Transport {name};' for name, *_ in transports)
            members += ''.join(f'bool {flag}{{false}};' for *_, flag in transports if flag)
            setup = ''.join(f'{name}={{{master},fail_index!={index}}};'
                            for index, (name, master, *_) in enumerate(transports))
            code += f'class {cls} {{public: {members}\n'
            code += f'  {cls}() {{++live;{setup}}} ~{cls}() {{--live;}}\n'
            code += f'  static {cls} *instantiate(int argc,char *argv[]);}};\n'
            code += extract((ROOT / relative).read_text(), f'{cls} *{cls}::instantiate(')
            code += 'int main() {\n'
            for failing, (_, _, required, flag) in enumerate(transports):
                code += f'  {{attempts=0;fail_index={failing};auto *instance={cls}::instantiate(0,nullptr);\n'
                if required:
                    code += f'  assert(instance==nullptr && live==0 && attempts=={failing + 1});}}\n'
                else:
                    code += (f'  assert(instance && live==1 && attempts=={len(transports)} && !instance->{flag});\n'
                             '  delete instance;assert(!live);}\n')
            flags = ''.join(f' && instance->{flag}' for *_, flag in transports if flag)
            code += (f'  attempts=0;fail_index=-1;auto *instance={cls}::instantiate(0,nullptr);\n'
                     f'  assert(instance && live==1 && attempts=={len(transports)}{flags});\n'
                     '  delete instance;assert(!live);\n}\n')
            REPAIR.run(code, cpp=True)

    def test_cr8_1_image_runs_constructors_and_autostarts_the_supervisor(self):
        """Without C++ constructors the PX4 work-queue manager never starts, and
        without the board ROMFS NSH mounts NuttX's default /etc and never runs
        the I/O supervisor; both silently left CR8-1 at an idle shell."""
        board = ROOT / 'boards/renesas/rdk-rzv2h-io-cr8_1'
        defconfig = (board / 'nuttx-config/nsh/defconfig').read_text().splitlines()
        for option in ('CONFIG_HAVE_CXX=y', 'CONFIG_HAVE_CXXINITIALIZE=y', 'CONFIG_NSH_ARCHROMFS=y'):
            self.assertIn(option, defconfig)
        self.assertIn('CONFIG_BOARD_ROMFSROOT="rdk-rzv2h-io-cr8_1"',
                      (board / 'default.px4board').read_text().splitlines())
        romfs = ROOT / 'ROMFS/rdk-rzv2h-io-cr8_1'
        self.assertIn('rcS', (romfs / 'init.d/CMakeLists.txt').read_text())
        rcs = [line.strip() for line in (romfs / 'init.d/rcS').read_text().splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
        self.assertIn('if ! rzv2h_io start', rcs)

        # lib_cxx_initialize() skips constructors outside [_stext, _etext), so
        # both CR8 images must bound the runtime SDRAM text, not the flash copy.
        # platforms/nuttx/CMakeLists.txt links these NuttX scripts for RZ/V.
        scripts = ROOT / 'platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/scripts'
        self.assertIn('${rzv_board_scripts}/rdk-rzv2h_cr8_1.ld',
                      (ROOT / 'platforms/nuttx/CMakeLists.txt').read_text())
        for script in ('rdk-rzv2h_cr8_0.ld', 'rdk-rzv2h_cr8_1.ld'):
            linker = (scripts / script).read_text()
            self.assertIn('PROVIDE( _stext = _sdram_text_start );', linker, script)
            self.assertIn('PROVIDE( _etext = _sdram_text_end );', linker, script)

    def test_quarantined_responder_reader_adopts_a_fresh_initiator_epoch(self):
        """A responder that registers before its initiator publishes is left
        quarantined; a plain nonblocking reader (an IO-core consumer) must still
        join the next recovery epoch instead of failing with ENOLINK forever."""
        nuttx = ROOT / 'platforms/nuttx/NuttX/nuttx'
        source = (ARCH / 'rzv_ipc_raw.c').read_text()
        public = REPAIR.header(nuttx / 'include/nuttx/ipc/rzv_ipc_raw.h')
        private = REPAIR.header(ARCH / 'rzv_ipc_raw.h')
        consts = ''.join(re.search(rf'^#define {name}\b[^\n]*$', source, flags=re.M).group(0) + '\n'
                         for name in ('RZV_IPC_RING_MAGIC', 'RZV_IPC_RING_ABI_VERSION',
                                      'RZV_IPC_RING_READY', 'RZV_IPC_RING_RECOVERING',
                                      'RZV_IPC_CACHELINE'))
        structs = ''.join(re.search(rf'^struct {name}\n\{{.*?^\}};\n', source, flags=re.M | re.S).group(0)
                          for name in ('rzv_ipc_ring_hdr_s', 'rzv_ipc_slot_s'))
        functions = ''.join(extract(source, signature) for signature in (
            'static inline uint32_t rzv_ipc_next_sequence(',
            'static inline bool rzv_ipc_link_ready(', 'static inline bool\nrzv_ipc_ring_full(',
            'static bool rzv_ipc_header_valid_state(',
            'static bool rzv_ipc_header_valid(FAR', 'static void rzv_ipc_mark_degraded_locked(',
            'static void rzv_ipc_mark_degraded(FAR',
            'static bool rzv_ipc_recovery_pending(',
            'static void rzv_ipc_adopt_recovery_locked(', 'pollevent_t rzv_ipc_raw_pollstate(',
            'ssize_t rzv_ipc_raw_read('))
        code = REPAIR.PRE + r'''
#define _DIOC(n) (n)
#define POLLIN 0x01
#define POLLOUT 0x04
#define POLLERR 0x08
typedef uint32_t pollevent_t;
typedef int mutex_t;
typedef int sem_t;
struct pollfd;
#define up_invalidate_dcache(a, b) ((void)(a), (void)(b))
#define up_clean_dcache(a, b) ((void)(a), (void)(b))
static void rzv_ipc_barrier(void) {}
static int acks, locked;
static int nxmutex_lock(mutex_t *m) { assert(!*m); *m = 1; ++locked; return 0; }
static int nxmutex_unlock(mutex_t *m) { assert(*m); *m = 0; --locked; return 0; }
static int nxsem_post(sem_t *s) { ++*s; return 0; }
static int nxsem_reset(sem_t *s, int v) { *s = v; return 0; }
static int nxsem_wait_uninterruptible(sem_t *s) { assert(!"nonblocking reader never waits"); return 0; }
static void rzv_mhu_ack(uintptr_t base, uint32_t chan, uint32_t v) { ++acks; }
''' + public + private + consts + structs + r'''
void rzv_ipc_raw_pollnotify(FAR struct rzv_ipc_raw_s *priv, pollevent_t events) {}
''' + functions + r'''
static struct rzv_ipc_ring_hdr_s tx, rx;
static struct rzv_ipc_slot_s slots[16];
static void publish(uint32_t state, uint32_t epoch) {
  struct rzv_ipc_ring_hdr_s h;
  memset(&h, 0, sizeof(h));
  h.magic = RZV_IPC_RING_MAGIC; h.version = RZV_IPC_RING_ABI_VERSION;
  h.state = state; h.epoch = epoch; h.mask = 15;
  tx = h; rx = h;
}
static void quarantine(struct rzv_ipc_raw_s *p, struct rzv_ipc_link_desc *d, bool initiator, uint32_t epoch) {
  memset(p, 0, sizeof(*p)); memset(d, 0, sizeof(*d));
  d->initiator = initiator; p->desc = d; p->local_mask = 15; p->in_use = true;
  p->tx_hdr = &tx; p->rx_hdr = &rx; p->rx_slots = slots;
  p->stats.epoch = epoch; p->stats.degraded = true; acks = 0;
}
int main(void) {
  struct rzv_ipc_raw_s p; struct rzv_ipc_link_desc d; char buf[RZV_IPC_RAW_PAYLOAD_SIZE];

  /* Responder registered before the initiator: no headers yet. */
  memset(&tx, 0, sizeof(tx)); memset(&rx, 0, sizeof(rx));
  quarantine(&p, &d, false, 0);
  assert(rzv_ipc_raw_pollstate(&p) == POLLERR);
  assert(rzv_ipc_raw_read(&p, buf, sizeof(buf), true) == -ENOLINK && !locked);

  /* The initiator publishes recovery epoch 7: poll wakes, read adopts. */
  publish(RZV_IPC_RING_RECOVERING, 7);
  assert(rzv_ipc_raw_pollstate(&p) == POLLIN);
  assert(rzv_ipc_raw_read(&p, buf, sizeof(buf), true) == -EAGAIN && !locked);
  assert(p.stats.ready && !p.stats.degraded && p.stats.epoch == 7 && p.stats.recoveries == 1);
  assert(tx.state == RZV_IPC_RING_READY && rx.state == RZV_IPC_RING_READY && acks == 1);
  assert(rzv_ipc_raw_pollstate(&p) == POLLOUT);

  /* The adopted link then delivers the first frame of the new epoch. */
  slots[0].epoch = 7; slots[0].sequence = 1; slots[0].length = RZV_IPC_RAW_PAYLOAD_SIZE;
  slots[0].payload[0] = 0x5a; rx.tail = 1;
  assert(rzv_ipc_raw_read(&p, buf, sizeof(buf), true) == RZV_IPC_RAW_PAYLOAD_SIZE);
  assert(buf[0] == 0x5a && rx.head == 1 && p.stats.rx_sequence == 1);

  /* A quarantine without a fresh epoch stands. */
  publish(RZV_IPC_RING_RECOVERING, 7);
  quarantine(&p, &d, false, 7);
  assert(rzv_ipc_raw_pollstate(&p) == POLLERR);
  assert(rzv_ipc_raw_read(&p, buf, sizeof(buf), true) == -ENOLINK && p.stats.degraded && !acks);

  /* Only responders adopt; an initiator must republish through RECOVER. */
  publish(RZV_IPC_RING_RECOVERING, 8);
  quarantine(&p, &d, true, 0);
  assert(rzv_ipc_raw_pollstate(&p) == POLLERR);
  assert(rzv_ipc_raw_read(&p, buf, sizeof(buf), true) == -ENOLINK && p.stats.degraded && !acks);
  assert(tx.state == RZV_IPC_RING_RECOVERING);
  return 0;
}
'''
        REPAIR.run(code)

    def test_cm33_holds_valid_commands_and_stops_after_timeout(self):
        owner = ROOT / 'boards/renesas/rdk-rzv2h-io-cm33/px4io_m33'
        source = (owner / 'px4io_m33.cpp').read_text()
        code = io_prelude(owner) + r'''
struct EscTransport {
  std::deque<ActuatorCmdToM33_t> queue; int reads = 0;
  bool receive_actuator_cmd(ActuatorCmdToM33_t &cmd) {
    ++reads; if (queue.empty()) return false;
    cmd = queue.front(); queue.pop_front(); return true;
  }
};
class Px4IoM33 {public:
  static bool command_valid(const ActuatorCmdToM33_t &cmd);
  bool update_outputs(hrt_abstime now);
  EscTransport _transport; ActuatorCmdToM33_t _cmd{}; hrt_abstime _last_cmd_us{0};
  uint16_t _outputs[IPC_MAX_ACTUATORS] {}; bool _armed{false}; bool _command_timeout{true};};
'''
        for name in ('bool Px4IoM33::command_valid(', 'bool Px4IoM33::update_outputs('):
            code += extract(source, name)
        code += r'''
static ActuatorCmdToM33_t command(unsigned base, unsigned armed = 0, unsigned safety_off = 0) {
  ActuatorCmdToM33_t cmd{};
  for (unsigned i = 0; i < IPC_MAX_ACTUATORS; ++i) cmd.commands[i] = base + 10 * i;
  cmd.armed = armed; cmd.safety_off = safety_off; return cmd;
}
static void expect(const Px4IoM33 &io, unsigned base, bool armed, int zero_channel = -1) {
  for (unsigned i = 0; i < IPC_MAX_ACTUATORS; ++i) {
    const unsigned value = (base == 0 || (int)i == zero_channel) ? 0 : base + 10 * i;
    assert(io._outputs[i] == value);
  }
  assert(io._armed == armed && io._command_timeout == (base == 0));
}
int main() {
  Px4IoM33 io;
  assert(!io.update_outputs(1000));
  expect(io, 0, false);

  io._transport.queue.push_back(command(1000));
  assert(io.update_outputs(1000));
  expect(io, 1000, false);
  assert(!io.update_outputs(1000 + FMU_LOSS_TIMEOUT_US / 2));
  expect(io, 1000, false);

  ActuatorCmdToM33_t mode = command(1000, 1, 1); mode.output_mode = 1;
  ActuatorCmdToM33_t low = command(1000, 1, 1); low.commands[0] = PWM_LOWEST_MIN - 1;
  ActuatorCmdToM33_t high = command(1000, 1, 1); high.commands[7] = PWM_HIGHEST_MAX + 1;
  const ActuatorCmdToM33_t invalid[] = {mode, low, high, command(1000, 2, 1), command(1000, 1, 2)};
  for (const ActuatorCmdToM33_t &cmd : invalid) io._transport.queue.push_back(cmd);
  assert(!io.update_outputs(1000 + FMU_LOSS_TIMEOUT_US / 2 + 1000));
  assert(io._transport.queue.empty() && io._last_cmd_us == 1000);
  expect(io, 1000, false);

  assert(!io.update_outputs(1000 + FMU_LOSS_TIMEOUT_US - 1));
  expect(io, 1000, false);
  assert(!io.update_outputs(1000 + FMU_LOSS_TIMEOUT_US));
  expect(io, 0, false);

  ActuatorCmdToM33_t armed = command(1500, 1, 1); armed.commands[2] = 0;
  io._transport.queue.push_back(armed);
  assert(io.update_outputs(200000));
  expect(io, 1500, true, 2);
  assert(!io.update_outputs(200000 + FMU_LOSS_TIMEOUT_US));
  expect(io, 0, false);

  ActuatorCmdToM33_t bounds = command(1000, 1, 1);
  bounds.commands[0] = PWM_LOWEST_MIN; bounds.commands[7] = PWM_HIGHEST_MAX;
  io._transport.queue.push_back(bounds);
  assert(io.update_outputs(210000));
  assert(io._outputs[0] == PWM_LOWEST_MIN && io._outputs[7] == PWM_HIGHEST_MAX);

  io._transport.reads = 0;
  for (unsigned i = 0; i < 40; ++i) io._transport.queue.push_back(command(1000 + i));
  assert(io.update_outputs(220000));
  assert(io._transport.reads == 2 * IPC_BUFFER_SIZE && io._transport.queue.size() == 8);
  expect(io, 1031, false);
}
'''
        REPAIR.run(code, cpp=True)

    def test_every_ipc_sender_writes_one_full_raw_entry(self):
        """Protocol messages are shorter than a raw ring entry and the driver
        rejects any other write length, so each core pads to one entry."""
        cm33 = REPAIR.io_transport_harness(ROOT / 'boards/renesas/rdk-rzv2h-io-cm33/px4io_m33') + r'''
int main() {
  SharedMemTransport io("/dev/ipcc3"); assert(io.init(false));
  FaultStatus_t fault{}; fault.error_flags = 5; PWMFeedback_t pwm{}; pwm.current_outputs[0] = 1500;
  assert(io.send_fault_status(fault) && io.send_pwm_feedback(pwm) && written.size() == 2);
  FaultStatus_t sent{}; memcpy(&sent, written.front().data(), sizeof(sent));
  assert(sent.header.msg_type == MSG_TYPE_FAULT_STATUS && sent.error_flags == 5);
  const uint32_t received = sent.header.crc32; sent.header.crc32 = 0;
  assert(crc(reinterpret_cast<uint8_t *>(&sent), sizeof(sent)) == received);
  for (size_t i = sizeof(sent); i < RAW_ENTRY_SIZE; ++i) assert(written.front()[i] == 0);
}
'''
        REPAIR.run(cm33, cpp=True)

if __name__ == '__main__':
    unittest.main()
