#!/usr/bin/env python3
"""Exercise deferred TX progress, callback publication, shared-GIC routing, IO startup, relay and reporting."""

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


def output_lease(owner):
    """CR8-1 OutputLease class and methods, compiled as written."""
    return (REPAIR.header(owner / 'output-lease.h') + REPAIR.header(owner / 'output-lease.cpp')).replace(
        '#pragma once', '')


def fmu_inbox(owner):
    """The transport's FmuMessage plus an in-memory CR8-0 stream.  push()
    precedes each command with a CR8-0 heartbeat unless auto_beat is off."""
    header = (owner / 'sharedmem_transport.h').read_text()
    message = re.search(r'struct FmuMessage \{.*?\n\};', header, flags=re.S).group(0)
    return message + r'''
struct FmuInbox {
  std::deque<FmuMessage> queue; int reads = 0; bool auto_beat = true;
  void beat(uint8_t core = CORE_ID_CR8_0, uint8_t state = 1) {
    FmuMessage msg{}; msg.type = MSG_TYPE_HEARTBEAT;
    msg.heartbeat.source_core = core; msg.heartbeat.state = state; queue.push_back(msg);
  }
  void push(const ActuatorCommand_t &cmd) {
    if (auto_beat) beat();
    FmuMessage msg{}; msg.type = MSG_TYPE_ACTUATOR_CMD; msg.command = cmd; queue.push_back(msg);
  }
  bool next(FmuMessage &msg) {
    ++reads; if (queue.empty()) return false;
    msg = queue.front(); queue.pop_front(); return true;
  }
};
'''


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
            ('boards/renesas/rdk-rzv2h-io-cr8_1/px4io_cr8_1/px4io_cr8.cpp', 'Px4IoCr8',
             (('_fmu_transport', 'false', True, None), ('_esc_transport', 'true', False, '_esc_enabled'))),
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

    def test_cr8_1_image_runs_constructors_and_autostarts_the_relay(self):
        """Without C++ constructors the PX4 work-queue manager never starts, and
        without the board ROMFS NSH mounts NuttX's default /etc and never runs
        the relay; both silently left CR8-1 at an idle shell."""
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
        self.assertIn('if ! px4io_cr8 start', rcs)

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
        quarantined; a plain nonblocking reader (the PX4 IO relay) must still
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

    def test_cr8_1_relays_fresh_fmu_commands_and_stops_after_timeout(self):
        owner = ROOT / 'boards/renesas/rdk-rzv2h-io-cr8_1/px4io_cr8_1'
        source = (owner / 'px4io_cr8.cpp').read_text()
        code = io_prelude(owner) + output_lease(owner) + fmu_inbox(owner) + r'''
struct FmuTransport : FmuInbox {
  uint32_t epoch = 1;
  bool receive_fmu_message(FmuMessage &msg) { return next(msg); }
  bool link_epoch(uint32_t &value) const { value = epoch; return true; }
};
class Px4IoCr8 {public:
  static bool fmu_command_valid(const ActuatorCommand_t &cmd);
  static bool fmu_heartbeat_valid(const Heartbeat_t &heartbeat);
  void receive_fmu_commands(hrt_abstime now);
  FmuTransport _fmu_transport; OutputLease _lease;};
'''
        for name in ('bool Px4IoCr8::fmu_command_valid(', 'bool Px4IoCr8::fmu_heartbeat_valid(',
                     'void Px4IoCr8::receive_fmu_commands('):
            code += extract(source, name)
        code += r'''
static ActuatorCommand_t frame(unsigned base, unsigned armed = 0, unsigned safety_off = 0) {
  ActuatorCommand_t cmd{};
  for (unsigned i = 0; i < IPC_MAX_ACTUATORS; ++i) cmd.outputs[i] = base + 10 * i;
  cmd.armed = armed; cmd.safety_off = safety_off; return cmd;
}
static void expect(const ActuatorCmdToM33_t &cmd, unsigned base, unsigned armed, unsigned safety_off,
                   int zero_channel = -1) {
  for (unsigned i = 0; i < IPC_MAX_ACTUATORS; ++i) {
    const unsigned value = (base == 0 || (int)i == zero_channel) ? 0 : base + 10 * i;
    assert(cmd.commands[i] == value);
  }
  assert(cmd.armed == armed && cmd.safety_off == safety_off && cmd.output_mode == 0);
}
int main() {
  const hrt_abstime T = FMU_LOSS_TIMEOUT_US;
  Px4IoCr8 io;
  io.receive_fmu_commands(1000);
  assert(io._fmu_transport.reads == 1);
  expect(io._lease.output(1000), 0, 0, 0);

  // Disarmed handshake, then armed values; a zero channel stays off.
  io._fmu_transport.push(frame(1000));
  io.receive_fmu_commands(1000);
  expect(io._lease.output(1000), 1000, 0, 0);
  ActuatorCommand_t zero = frame(1500, 1, 1); zero.outputs[3] = 0;
  io._fmu_transport.push(zero);
  io.receive_fmu_commands(2000);
  expect(io._lease.output(2000), 1500, 1, 1, 3);

  // Invalid frames never refresh or replace the lease.
  const uint16_t bad_outputs[] = {PWM_LOWEST_MIN - 1, PWM_HIGHEST_MAX + 1, 65535};
  for (uint16_t bad : bad_outputs) {
    ActuatorCommand_t cmd = frame(1000, 1, 1); cmd.outputs[bad == 65535 ? 0 : 7] = bad;
    io._fmu_transport.push(cmd);
  }
  io._fmu_transport.push(frame(1000, 2, 1));
  io._fmu_transport.push(frame(1000, 1, 2));
  io.receive_fmu_commands(2000 + T - 1);
  assert(io._fmu_transport.queue.empty());
  expect(io._lease.output(2000 + T - 1), 1500, 1, 1, 3);
  expect(io._lease.output(2000 + T), 0, 0, 0);

  // PWM bounds are inclusive.
  io._fmu_transport.push(frame(1000));
  ActuatorCommand_t bounds = frame(1000, 1, 1);
  bounds.outputs[0] = PWM_LOWEST_MIN; bounds.outputs[7] = PWM_HIGHEST_MAX;
  io._fmu_transport.push(bounds);
  io.receive_fmu_commands(500000);
  const ActuatorCmdToM33_t edge = io._lease.output(500000);
  assert(edge.armed == 1 && edge.commands[0] == PWM_LOWEST_MIN && edge.commands[7] == PWM_HIGHEST_MAX);

  // In-order drain: the newest valid command wins, an invalid one is skipped.
  io._fmu_transport.push(frame(1100));
  io._fmu_transport.push(frame(1200));
  io._fmu_transport.push(frame(1300, 2));
  io.receive_fmu_commands(510000);
  expect(io._lease.output(510000), 1200, 0, 0);
  expect(io._lease.output(510000 + T - 1), 1200, 0, 0);
  expect(io._lease.output(510000 + T), 0, 0, 0);

  // Bounded drain: one heartbeat, then 40 commands.
  io._fmu_transport.reads = 0; io._fmu_transport.auto_beat = false; io._fmu_transport.beat();
  for (unsigned i = 0; i < 40; ++i) io._fmu_transport.push(frame(1000 + i));
  io.receive_fmu_commands(600000);
  assert(io._fmu_transport.reads == 2 * IPC_BUFFER_SIZE && io._fmu_transport.queue.size() == 9);
  expect(io._lease.output(600000), 1030, 0, 0);
}
'''
        REPAIR.run(code, cpp=True)

    def test_cr8_1_reports_heartbeat_and_fault_status_to_fmu(self):
        owner = ROOT / 'boards/renesas/rdk-rzv2h-io-cr8_1/px4io_cr8_1'
        source = (owner / 'px4io_cr8.cpp').read_text()
        interval = re.search(r'static constexpr hrt_abstime REPORT_INTERVAL_US = \d+;', source).group(0)
        initial = re.search(r'px4::atomic<uint32_t> _report_fault_flags\{[^}]*\};', source).group(0)
        code = io_prelude(owner) + output_lease(owner) + fmu_inbox(owner) + r'''
static int warnings;
#define PX4_WARN(...) (++warnings)
namespace px4 {
template<typename T> class atomic {public:
  explicit atomic(T value) : _value(value) {}
  T load() const { return _value; }
  void store(T value) { _value = value; }
  T fetch_add(T num) { T old = _value; _value += num; return old; }
private: T _value;};
}
struct FmuTransport : FmuInbox {
  std::deque<Heartbeat_t> heartbeats; std::deque<FaultStatus_t> faults;
  bool accept = true;
  bool receive_fmu_message(FmuMessage &msg) { return next(msg); }
  bool link_epoch(uint32_t &value) const { value = 1; return true; }
  bool send_heartbeat(const Heartbeat_t &hb) { if (accept) heartbeats.push_back(hb); return accept; }
  bool send_fault_status(const FaultStatus_t &fault) { if (accept) faults.push_back(fault); return accept; }
};
struct EscTransport {
  std::deque<PWMFeedback_t> feedback; std::deque<FaultStatus_t> faults;
  bool receive_pwm_feedback(PWMFeedback_t &msg) {
    if (feedback.empty()) return false;
    msg = feedback.front(); feedback.pop_front(); return true;
  }
  bool receive_fault_status(FaultStatus_t &msg) {
    if (faults.empty()) return false;
    msg = faults.front(); faults.pop_front(); return true;
  }
};
class Px4IoCr8 {public:
''' + '  ' + interval + r'''
  static bool fmu_command_valid(const ActuatorCommand_t &cmd);
  static bool fmu_heartbeat_valid(const Heartbeat_t &heartbeat);
  void receive_fmu_commands(hrt_abstime now);
  void receive_esc_status(hrt_abstime now);
  FaultStatus_t fault_status(hrt_abstime now) const;
  void publish_report_state(hrt_abstime now);
  void report_to_fmu(hrt_abstime now);
  FmuTransport _fmu_transport; EscTransport _esc_transport; OutputLease _lease;
  px4::atomic<uint32_t> _esc_fault_flags{0}; px4::atomic<hrt_abstime> _esc_fault_us{0};
  uint32_t _loop_count{0};
''' + '  ' + initial + r'''
  px4::atomic<uint32_t> _report_armed{0};
  px4::atomic<uint32_t> _report_state{static_cast<uint32_t>(OutputLease::State::Safe)};
  px4::atomic<uint32_t> _report_loop_count{0};
  hrt_abstime _last_report_us{0}; px4::atomic<uint32_t> _report_count{0};};
'''
        for name in ('bool Px4IoCr8::fmu_command_valid(', 'bool Px4IoCr8::fmu_heartbeat_valid(',
                     'void Px4IoCr8::receive_fmu_commands(', 'void Px4IoCr8::receive_esc_status(', 'FaultStatus_t Px4IoCr8::fault_status(',
                     'void Px4IoCr8::publish_report_state(', 'void Px4IoCr8::report_to_fmu('):
            code += extract(source, name)
        code += r'''
static FaultStatus_t cm33_fault(uint32_t flags) { FaultStatus_t f{}; f.error_flags = flags; return f; }
static ActuatorCommand_t command(unsigned armed) {
  ActuatorCommand_t cmd{}; cmd.outputs[0] = 1500; cmd.armed = armed; cmd.safety_off = 1; return cmd;
}
int main() {
  Px4IoCr8 io; auto &fmu = io._fmu_transport;
  const hrt_abstime T = Px4IoCr8::REPORT_INTERVAL_US;

  // Before the control loop publishes anything the report says outputs are off.
  io.report_to_fmu(5000);
  assert(fmu.heartbeats.size() == 1 && fmu.faults.size() == 1 && io._report_count.load() == 1);
  Heartbeat_t hb = fmu.heartbeats.back();
  assert(hb.source_core == CORE_ID_CR8_1 && hb.state == 1 && hb.uptime_ms == 5 && hb.loop_count == 0);
  const uint32_t SILENT = FAULT_FLAG_CR8_TIMEOUT | FAULT_FLAG_FMU_HEARTBEAT;
  assert(fmu.faults.back().error_flags == SILENT && fmu.faults.back().armed_state == 0);

  // 10 Hz: nothing until a full interval has passed.
  io.report_to_fmu(5000 + T - 1);
  assert(fmu.heartbeats.size() == 1 && fmu.faults.size() == 1);

  // The reporter sends only what the control loop published, never live state.
  fmu.push(command(0)); fmu.push(command(1));
  io.receive_fmu_commands(5000 + T);
  assert(io._lease.output(5000 + T).armed == 1);
  io._loop_count = 7;
  io.report_to_fmu(5000 + T);
  assert(fmu.faults.back().error_flags == SILENT && fmu.faults.back().armed_state == 0);
  assert(fmu.heartbeats.back().loop_count == 0 && io._report_count.load() == 2);
  io.publish_report_state(5000 + T);
  assert(io._report_state.load() == static_cast<uint32_t>(OutputLease::State::Armed));
  io.report_to_fmu(5000 + 2 * T);
  assert(fmu.faults.back().error_flags == 0 && fmu.faults.back().armed_state == 1);
  assert(fmu.heartbeats.back().loop_count == 7);

  // A failed write is not counted, and the next report still waits a full interval.
  fmu.accept = false;
  io.report_to_fmu(5000 + 3 * T);
  assert(io._report_count.load() == 3 && io._last_report_us == 5000 + 3 * T);
  fmu.accept = true;

  // Fault status: lease expiry while armed latches a safe fault.
  FaultStatus_t fault = io.fault_status(5000 + T + FMU_LOSS_TIMEOUT_US - 1);
  assert(fault.error_flags == 0 && fault.armed_state == 1);
  io.receive_fmu_commands(5000 + T + FMU_LOSS_TIMEOUT_US);
  fault = io.fault_status(5000 + T + FMU_LOSS_TIMEOUT_US);
  assert(fault.error_flags == (FAULT_FLAG_CR8_TIMEOUT | FAULT_FLAG_OUTPUT_SAFE_FAULT) && fault.armed_state == 0);

  // CM33 flags are merged while it keeps reporting, and logged once per change.
  io._esc_transport.feedback.push_back(PWMFeedback_t{});
  io._esc_transport.faults.push_back(cm33_fault(FAULT_FLAG_PWM_FAULT));
  io._esc_transport.faults.push_back(cm33_fault(FAULT_FLAG_PWM_FAULT));
  io.receive_esc_status(1000000);
  assert(io._esc_transport.feedback.empty() && io._esc_transport.faults.empty() && warnings == 1);
  fmu.push(command(0));
  io.receive_fmu_commands(1000000);
  assert(io.fault_status(1000000).error_flags == FAULT_FLAG_PWM_FAULT);
  assert(io.fault_status(1000000 + HEARTBEAT_TIMEOUT_US - 1).error_flags ==
         (FAULT_FLAG_PWM_FAULT | FAULT_FLAG_CR8_TIMEOUT));
  assert(io.fault_status(1000000 + HEARTBEAT_TIMEOUT_US).error_flags == SILENT);

  io._esc_transport.faults.push_back(cm33_fault(0));
  io.receive_esc_status(2000000);
  assert(warnings == 2 && io.fault_status(2000000).error_flags == SILENT);
}
'''
        REPAIR.run(code, cpp=True)

    def test_cr8_0_bridge_tracks_cr8_1_heartbeat_and_fault_status(self):
        owner = ROOT / 'boards/renesas/rdk-rzv2h/px4io_cr8_0'
        source = (owner / 'uorb_bridge.cpp').read_text()
        code = io_prelude(owner) + r'''
#include <array>
#include <string>
#include <vector>
#include <unistd.h>
static std::vector<std::string> logs;
#define PX4_INFO(fmt, ...) logs.push_back(std::string("I:") + fmt)
#define PX4_WARN(fmt, ...) logs.push_back(std::string("W:") + fmt)
#define PX4_ERR(fmt, ...) logs.push_back(std::string("E:") + fmt)
static std::deque<std::array<uint8_t, 64>> entries;
static ssize_t test_read(int fd, void *data, size_t size) {
  if (entries.empty()) { errno = EAGAIN; return -1; }
  memcpy(data, entries.front().data(), size); entries.pop_front(); return size;
}
#define read test_read
static uint64_t clock_us;
static uint64_t hrt_absolute_time() { return clock_us; }
static constexpr size_t IPC_ENTRY_SIZE = 64;
class UorbBridgeCR8 {public:
  int _fd{3};
  uint64_t _last_io_heartbeat_us{0}; bool _io_alive{false}; bool _io_lost_reported{false};
  uint32_t _io_fault_flags{0}; uint8_t _io_armed_state{0}; bool _link_down{false};
  struct { uint32_t rx_heartbeat_count{}, rx_fault_count{}, crc_errors{}, link_faults{}; } _stats;
  void note_link_error(int err);
  static uint32_t calculate_crc32(const uint8_t *data, size_t len);
  bool validate_message_crc(const void *frame, size_t msg_size);
  void process_rx();
  void handle_heartbeat(const Heartbeat_t &hb_msg, uint64_t now);
  void handle_fault_status(const FaultStatus_t &fault_msg);
  void update_io_liveness(uint64_t now);
  void publish_input_rc(const InputRC_t &) { assert(false); }
  void publish_esc_status(const ESCStatus_t &) { assert(false); }
  void publish_battery_status(const BatteryStatus_t &) { assert(false); }
};
'''
        for name in ('uint32_t UorbBridgeCR8::calculate_crc32(', 'bool UorbBridgeCR8::validate_message_crc(',
                     'void UorbBridgeCR8::process_rx(', 'void UorbBridgeCR8::handle_heartbeat(',
                     'void UorbBridgeCR8::handle_fault_status(', 'void UorbBridgeCR8::update_io_liveness(',
                     'void UorbBridgeCR8::note_link_error('):
            code += extract(source, name)
        code += r'''
template<typename T> static void push(T msg, int type, bool bad = false) {
  msg.header.magic = IPC_MAGIC; msg.header.version = IPC_PROTOCOL_VERSION;
  msg.header.msg_type = type; msg.header.crc32 = 0;
  msg.header.crc32 = UorbBridgeCR8::calculate_crc32(reinterpret_cast<uint8_t *>(&msg), sizeof(msg));
  if (bad) ++msg.header.crc32;
  std::array<uint8_t, 64> frame{}; memcpy(frame.data(), &msg, sizeof(msg)); entries.push_back(frame);
}
static Heartbeat_t beat(uint8_t core) { Heartbeat_t hb{}; hb.source_core = core; hb.state = 1; return hb; }
static FaultStatus_t fault(uint32_t flags, uint8_t armed) {
  FaultStatus_t f{}; f.error_flags = flags; f.armed_state = armed; return f;
}
static bool logged(const char *prefix) {
  for (auto &line : logs) if (line.rfind(prefix, 0) == 0) return true;
  return false;
}
int main() {
  UorbBridgeCR8 bridge;

  // No peer at boot: not alive and nothing logged.
  clock_us = 1000000; bridge.process_rx();
  assert(!bridge._io_alive && logs.empty());

  // Heartbeats from other cores or with a bad CRC do not count.
  push(beat(CORE_ID_CR8_0), MSG_TYPE_HEARTBEAT);
  push(beat(CORE_ID_M33), MSG_TYPE_HEARTBEAT);
  push(beat(CORE_ID_CR8_1), MSG_TYPE_HEARTBEAT, true);
  bridge.process_rx();
  assert(!bridge._io_alive && bridge._stats.rx_heartbeat_count == 0 && bridge._stats.crc_errors == 1);
  assert(logs.empty());

  // First CR8-1 heartbeat: acquired once.
  push(beat(CORE_ID_CR8_1), MSG_TYPE_HEARTBEAT);
  bridge.process_rx();
  assert(bridge._io_alive && bridge._stats.rx_heartbeat_count == 1);
  assert(logs.size() == 1 && logs[0] == "I:CR8-1 I/O processor heartbeat %s" && !bridge._io_lost_reported);

  // Alive until HEARTBEAT_TIMEOUT_US, then lost once.
  clock_us = 1000000 + HEARTBEAT_TIMEOUT_US - 1; bridge.process_rx();
  assert(bridge._io_alive && logs.size() == 1);
  clock_us = 1000000 + HEARTBEAT_TIMEOUT_US; bridge.process_rx();
  assert(!bridge._io_alive && logs.size() == 2 && logs[1] == "E:CR8-1 I/O processor heartbeat lost!");
  clock_us += 2500; bridge.process_rx();
  assert(logs.size() == 2 && bridge._io_lost_reported);

  // A later heartbeat recovers the link and logs once.
  push(beat(CORE_ID_CR8_1), MSG_TYPE_HEARTBEAT);
  bridge.process_rx(); bridge.process_rx();
  assert(bridge._io_alive && logs.size() == 3 && !bridge._io_lost_reported);

  // Fault status: stored, counted, and logged only when the flags change.
  logs.clear();
  push(fault(FAULT_FLAG_CR8_TIMEOUT, 0), MSG_TYPE_FAULT_STATUS);
  push(fault(FAULT_FLAG_CR8_TIMEOUT, 0), MSG_TYPE_FAULT_STATUS);
  bridge.process_rx();
  assert(bridge._io_fault_flags == FAULT_FLAG_CR8_TIMEOUT && bridge._stats.rx_fault_count == 2);
  assert(logs.size() == 1 && logged("W:CR8-1 I/O fault flags"));
  push(fault(0, 1), MSG_TYPE_FAULT_STATUS, true);
  bridge.process_rx();
  assert(bridge._io_fault_flags == FAULT_FLAG_CR8_TIMEOUT && bridge._stats.rx_fault_count == 2);
  push(fault(0, 1), MSG_TYPE_FAULT_STATUS);
  bridge.process_rx();
  assert(bridge._io_fault_flags == 0 && bridge._io_armed_state == 1 && logs.size() == 2);
}
'''
        REPAIR.run(code, cpp=True)

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

    def test_cr8_1_transport_reads_fmu_messages_in_order_and_drops_the_rest(self):
        code = REPAIR.cr8_1_transport_harness() + r'''
int main() {
  SharedMemTransport fmu("/dev/ipcc1"); assert(fmu.init(false));
  FmuMessage msg{};
  Heartbeat_t beat{}; beat.source_core = CORE_ID_CR8_0; beat.state = 1; beat.loop_count = 9;
  push(beat, MSG_TYPE_HEARTBEAT, 1);
  enqueue<VehicleStatus_t>(MSG_TYPE_VEHICLE_STATUS, 2);
  enqueue<VehicleCommand_t>(MSG_TYPE_VEHICLE_CMD, 3);
  ActuatorCommand_t sent{}; sent.outputs[0] = 1234; sent.armed = 1; sent.safety_off = 1;
  push(sent, MSG_TYPE_ACTUATOR_CMD, 4, true);
  push(sent, MSG_TYPE_ACTUATOR_CMD, 5);
  enqueue<Heartbeat_t>(MSG_TYPE_HEARTBEAT, 6, true);
  push(beat, MSG_TYPE_HEARTBEAT, 7);

  // Heartbeats and commands arrive in order; other types and bad frames are dropped.
  assert(fmu.receive_fmu_message(msg) && msg.type == MSG_TYPE_HEARTBEAT);
  assert(msg.heartbeat.header.sequence == 1 && msg.heartbeat.source_core == CORE_ID_CR8_0);
  assert(msg.heartbeat.state == 1 && msg.heartbeat.loop_count == 9);
  assert(fmu.receive_fmu_message(msg) && msg.type == MSG_TYPE_ACTUATOR_CMD && msg.command.header.sequence == 5);
  assert(msg.command.outputs[0] == 1234 && msg.command.armed == 1 && msg.command.safety_off == 1);
  assert(fmu.receive_fmu_message(msg) && msg.type == MSG_TYPE_HEARTBEAT && msg.heartbeat.header.sequence == 7);
  assert(!fmu.receive_fmu_message(msg) && entries.empty());

  // Reply types echoed onto the FMU leg have no reader there and must not
  // fill retained storage and stall actuator commands.  One call scans a
  // bounded number of entries.
  for (unsigned i = 0; i < 20; ++i) {
    if (i % 2) enqueue<FaultStatus_t>(MSG_TYPE_FAULT_STATUS, i);
    else enqueue<PWMFeedback_t>(MSG_TYPE_PWM_FEEDBACK, i);
  }
  enqueue<ActuatorCommand_t>(MSG_TYPE_ACTUATOR_CMD, 50);
  assert(!fmu.receive_fmu_message(msg) && entries.size() == 5);
  assert(fmu.receive_fmu_message(msg) && msg.command.header.sequence == 50 && entries.empty());
  enqueue<FaultStatus_t>(MSG_TYPE_FAULT_STATUS, 60);
  enqueue<ActuatorCommand_t>(MSG_TYPE_ACTUATOR_CMD, 51);
  assert(fmu.receive_fmu_message(msg) && msg.command.header.sequence == 51 && entries.empty());

  // Waiting polls the device for input with the caller's timeout.
  assert(fmu.wait_readable(2) && poll_calls == 1 && poll_timeout == 2);
  poll_result = 0; assert(!fmu.wait_readable(2));
  poll_result = 1; poll_revents = POLLERR; assert(!fmu.wait_readable(2));
  SharedMemTransport closed("/dev/ipcc1"); assert(!closed.wait_readable(2) && poll_calls == 3);

  SharedMemTransport esc("/dev/ipcc3"); assert(esc.init(true));
  PWMFeedback_t pwm{}; FaultStatus_t fault{};
  for (unsigned i = 0; i < 20; ++i) enqueue<ActuatorCommand_t>(MSG_TYPE_ACTUATOR_CMD, i);
  enqueue<PWMFeedback_t>(MSG_TYPE_PWM_FEEDBACK, 30);
  assert(!esc.receive_pwm_feedback(pwm) && entries.size() == 5);
  assert(esc.receive_pwm_feedback(pwm) && pwm.header.sequence == 30 && entries.empty());

  for (unsigned i = 0; i < 15; ++i) enqueue<FaultStatus_t>(MSG_TYPE_FAULT_STATUS, i);
  enqueue<PWMFeedback_t>(MSG_TYPE_PWM_FEEDBACK, 31);
  assert(esc.receive_pwm_feedback(pwm) && pwm.header.sequence == 31);
  for (unsigned i = 0; i < 15; ++i) {
    assert(esc.receive_fault_status(fault) && fault.header.sequence == i);
  }
  assert(!esc.receive_fault_status(fault) && entries.empty());
}
'''
        REPAIR.run(code, cpp=True)

    def test_cr8_1_transport_frames_fmu_reports_with_own_sequences(self):
        code = REPAIR.cr8_1_transport_harness() + r'''
template<typename T> static T sent(int type, unsigned sequence) {
  assert(!written.empty());
  T msg{}; memcpy(&msg, written.front().data(), sizeof(msg)); written.pop_front();
  assert(msg.header.magic == IPC_MAGIC && msg.header.version == IPC_PROTOCOL_VERSION);
  assert(msg.header.msg_type == type && msg.header.sequence == sequence);
  const uint32_t received = msg.header.crc32; msg.header.crc32 = 0;
  assert(crc(reinterpret_cast<uint8_t *>(&msg), sizeof(msg)) == received);
  return msg;
}
int main() {
  SharedMemTransport fmu("/dev/ipcc1"); assert(fmu.init(false));
  Heartbeat_t hb{}; hb.source_core = CORE_ID_CR8_1; hb.loop_count = 42;
  FaultStatus_t fault{}; fault.error_flags = FAULT_FLAG_CR8_TIMEOUT; fault.armed_state = 1;
  assert(fmu.send_heartbeat(hb) && fmu.send_fault_status(fault));
  assert(fmu.send_heartbeat(hb) && fmu.send_fault_status(fault));
  ActuatorCmdToM33_t cmd{}; assert(fmu.send_actuator_cmd(cmd));
  assert(sent<Heartbeat_t>(MSG_TYPE_HEARTBEAT, 0).loop_count == 42);
  const FaultStatus_t first = sent<FaultStatus_t>(MSG_TYPE_FAULT_STATUS, 0);
  assert(first.error_flags == FAULT_FLAG_CR8_TIMEOUT && first.armed_state == 1);
  assert(sent<Heartbeat_t>(MSG_TYPE_HEARTBEAT, 1).source_core == CORE_ID_CR8_1);
  sent<FaultStatus_t>(MSG_TYPE_FAULT_STATUS, 1);
  sent<ActuatorCmdToM33_t>(MSG_TYPE_ACTUATOR_CMD, 0);
  assert(written.empty());
}
'''
        REPAIR.run(code, cpp=True)

    def test_every_ipc_sender_writes_one_full_raw_entry(self):
        """Protocol messages are shorter than a raw ring entry and the driver
        rejects any other write length, so each core pads to one entry."""
        cm33 = REPAIR.cr8_1_transport_harness(ROOT / 'boards/renesas/rdk-rzv2h-io-cm33/px4io_m33') + r'''
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

        owner = ROOT / 'boards/renesas/rdk-rzv2h/px4io_cr8_0'
        source = (owner / 'uorb_bridge.cpp').read_text()
        bridge = io_prelude(owner) + '#include <unistd.h>\n' + REPAIR.raw_write_fake() + r'''
#define write test_write
#define PX4_ERR(...) ((void)0)
static uint64_t hrt_absolute_time() { return 10; }
static constexpr size_t IPC_ENTRY_SIZE = 64;
class UorbBridgeCR8 {public:
  int _fd{3};
  static uint32_t calculate_crc32(const uint8_t *data, size_t len);
  bool validate_message_crc(const void *frame, size_t msg_size);
  bool send_msg(MessageType_e type, uint16_t &seq, void *msg, size_t len);
  void note_link_error(int err);
  bool _link_down{false};
  struct { uint32_t crc_errors{}, link_faults{}; } _stats;
};
'''
        for name in ('uint32_t UorbBridgeCR8::calculate_crc32(', 'bool UorbBridgeCR8::validate_message_crc(',
                     'bool UorbBridgeCR8::send_msg(', 'void UorbBridgeCR8::note_link_error('):
            bridge += extract(source, name)
        bridge += r'''
int main() {
  UorbBridgeCR8 fmu; uint16_t seq = 7;
  ActuatorCommand_t cmd{}; cmd.outputs[0] = 1500; cmd.armed = 1;
  assert(fmu.send_msg(MSG_TYPE_ACTUATOR_CMD, seq, &cmd, sizeof(cmd)) && seq == 8 && written.size() == 1);
  assert(fmu.validate_message_crc(written.front().data(), sizeof(cmd)));
  ActuatorCommand_t sent{}; memcpy(&sent, written.front().data(), sizeof(sent));
  assert(sent.header.sequence == 7 && sent.outputs[0] == 1500 && sent.armed == 1);
  for (size_t i = sizeof(sent); i < RAW_ENTRY_SIZE; ++i) assert(written.front()[i] == 0);
}
'''
        REPAIR.run(bridge, cpp=True)

if __name__ == '__main__':
    unittest.main()
