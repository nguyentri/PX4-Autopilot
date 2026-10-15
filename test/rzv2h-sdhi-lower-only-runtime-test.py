#!/usr/bin/env python3
"""Execute idle/repeated SDHI cancellation and safe snapshot contracts."""
from pathlib import Path
import importlib.util
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
SPEC = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)

class SdhiRuntime(unittest.TestCase):
    def test_idle_cancel_does_not_post_or_attach(self):
        source = (ARCH / 'rzv_sdhi.c').read_text()
        header = re.sub(r'^\s*#\s*include[^\n]*$', '', (ARCH / 'hardware/rzv_sdhi.h').read_text(), flags=re.M)
        defines = "\n".join(line for line in source.splitlines() if line.startswith("#define RZV_SDHI_REG"))
        code = B.PRELUDE + header + defines + "\n" + r'''
#define FAR
#define RZV_SDHI_INFO1_MASK_ALL 0xffffffffu
#define RZV_SDHI_INFO2_MASK_ALL 0xffffffffu
#define SDIOWAIT_ERROR 4u
#define mcinfo(...) ((void)0)
#define WDOG_ISACTIVE(w) (*(w))
typedef int irqstate_t;
struct sdio_dev_s { int unused; };
struct rzv_sdhi_dev_s {
 struct sdio_dev_s dev; int slot; uintptr_t base; bool initialized, irq_attached;
 void *buffer; unsigned remaining, waitevents, wkupevent; int waitsem, waitwdog;
};
struct rzv2h_sdhi_sample_state_s {
 uintptr_t identity; bool initialized, irq_attached, watchdog_active, buffer_present, interrupts_masked;
 int semaphore_count; uint32_t waitevents;
};
static struct rzv_sdhi_dev_s g_rzv_sdhi_dev[1];
static uint32_t registers[2048];
static int operations, posts, depth;
static void putreg32(uint32_t value, uintptr_t address) { registers[address/4] = value; operations++; }
static uint32_t getreg32(uintptr_t address) { operations++; return registers[address/4]; }
static void up_udelay(unsigned int delay) { (void)delay; }
static int enter_critical_section(void) { depth++; return 0; }
static void leave_critical_section(int flags) { (void)flags; depth--; }
static void wd_cancel(int *w) { *w = 0; }
static void nxsem_post(int *sem) { ++*sem; posts++; }
static int nxsem_get_value(int *sem, int *value) { *value = *sem; return 0; }
'''
        for signature in ('static void rzv_sdhi_disableints(', 'static int rzv_sdhi_cancel(', 'int rzv2h_sdhi_sample_state('):
            code += B.EXTRACT.definition(source, signature)
        code += r'''
int main(void)
{
 struct rzv2h_sdhi_sample_state_s state;
 struct rzv_sdhi_dev_s *p = &g_rzv_sdhi_dev[0];
 assert(rzv2h_sdhi_sample_state(NULL)==-EINVAL);
 assert(rzv2h_sdhi_sample_state(&state)==-EAGAIN && operations==0);
 p->initialized = true;
 assert(rzv_sdhi_cancel(&p->dev)==0);
 assert(rzv_sdhi_cancel(&p->dev)==0 && !posts);
 assert(rzv2h_sdhi_sample_state(&state)==0);
 assert(!state.irq_attached && !state.watchdog_active && !state.buffer_present);
 assert(state.interrupts_masked && !state.semaphore_count && !state.waitevents);
 p->waitevents=1; p->waitwdog=1; p->buffer=p; p->remaining=4;
 assert(rzv_sdhi_cancel(&p->dev)==0 && posts==1);
 assert(!p->buffer && !p->remaining && !p->waitevents && !p->waitwdog);
 assert(p->wkupevent==SDIOWAIT_ERROR);
 assert(rzv_sdhi_cancel(&p->dev)==0 && posts==1 && depth==0);
 return 0;
}
'''
        B.compile_run(code)

if __name__ == '__main__': unittest.main()
