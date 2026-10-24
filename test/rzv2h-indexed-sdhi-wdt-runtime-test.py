#!/usr/bin/env python3
"""Execute actual indexed sample providers and arch Kconfig core admission."""

import importlib.util
from pathlib import Path
import re
import tempfile
import unittest

import kconfiglib

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
BOARD = ROOT / 'platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h'
SPEC = importlib.util.spec_from_file_location(
    'indexed_runtime', ROOT / 'test/rzv2h-audit-remediation-runtime-test.py')
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def state_type(name):
    return re.search(r'struct ' + name + r'\n\{.*?\n\};',
                     (BOARD / 'include/rzv2h-sample-test.h').read_text(), re.S)[0]


class IndexedSamples(unittest.TestCase):
    def test_sdhi_instance_provider_rejects_active_resources_and_reports_actual_slot(self):
        code = R.PRE + '\n#define OK 0\n#define CONFIG_RZV_SDHI 1\n'
        for name in ('rzv2h_sdhi_sample_state_s', 'rzv2h_bus_sample_state_s',
                     'rzv2h_driver_instance_state_s'):
            code += state_type(name)
        code += r'''
static struct rzv2h_sdhi_sample_state_s actual;
static int init_calls, state_calls, init_failed, state_error;
static void *rzv_sdhi_initialize(int p) {
  assert(p>=0 && p<3); ++init_calls; return init_failed ? NULL : (void *)actual.identity;
}
static int rzv2h_sdhi_sample_state_at(int p,struct rzv2h_sdhi_sample_state_s *out) {
  assert(p>=0 && p<3); ++state_calls; *out=actual; return state_error;
}
'''
        code += R.header(BOARD / 'src/rzv2h_instance_test.c')
        code += r'''
int main(void) {
  struct rzv2h_driver_instance_state_s out;
  assert(rzv2h_driver_instance_get(7,-1,0,&out)==-EINVAL);
  assert(rzv2h_driver_instance_get(7,3,0,&out)==-EINVAL);
  assert(init_calls==0 && state_calls==0);
  for(int p=0;p<3;++p) {
    actual=(struct rzv2h_sdhi_sample_state_s){.identity=0x1000u+p,
      .base=0x15c00000u+p*0x10000u,.channel=p,.initialized=true,.interrupts_masked=true};
    init_failed=1; int before=state_calls;
    assert(rzv2h_driver_instance_get(7,p,0,&out)==-ENODEV && state_calls==before);
    init_failed=0;
    assert(rzv2h_driver_instance_get(7,p,0,&out)==0);
    assert(out.family==7 && out.channel==(unsigned)p && out.identity==actual.identity);
    assert(out.base==actual.base && out.unit==0 && out.output==0);
    state_error=-EIO;
    assert(rzv2h_driver_instance_get(7,p,0,&out)==-EIO); state_error=0;
    for(int fault=0;fault<6;++fault) {
      actual.interrupts_masked=fault!=0; actual.irq_attached=fault==1;
      actual.watchdog_active=fault==2; actual.buffer_present=fault==3;
      actual.waitevents=fault==4; actual.semaphore_count=fault==5;
      assert(rzv2h_driver_instance_get(7,p,0,&out)==-EBUSY);
    }
  }
  return 0;
}
'''
        R.run(code)

    def test_wdt_instance_provider_never_initializes_an_active_or_disabled_counter(self):
        for selected in range(4):
            with self.subTest(selected=selected):
                code = R.PRE + '\n#define OK 0\n#define CONFIG_RZV_WDT 1\n'
                code += f'#define CONFIG_RZV_WDT{selected} 1\n'
                code += f'#define CONFIG_RZV_WDT{selected}_DEVPATH "/dev/watchdog{selected}"\n'
                for name in ('rzv2h_wdt_sample_state_s', 'rzv2h_bus_sample_state_s',
                             'rzv2h_driver_instance_state_s'):
                    code += state_type(name)
                code += r'''
#define SELECTED PORT
static struct rzv2h_wdt_sample_state_s actual;
static int reads, initializes, init_error, after_active;
static int rzv2h_wdt_sample_state_at(int p,struct rzv2h_wdt_sample_state_s *out) {
  assert(p==SELECTED); ++reads; *out=actual;
  if(after_active && actual.registered) out->counting_inhibited=false;
  return 0;
}
static int rzv_wdt_initialize(const char *path,int p) {
  assert(p==SELECTED && path[strlen(path)-1]=='0'+SELECTED); ++initializes;
  if(init_error) return init_error;
  actual.registered=true; return 0;
}
'''.replace('PORT', str(selected))
                code += R.header(BOARD / 'src/rzv2h_instance_test.c')
                code += r'''
int main(void) {
  struct rzv2h_driver_instance_state_s out;
  assert(rzv2h_driver_instance_get(8,-1,0,&out)==-EINVAL);
  assert(rzv2h_driver_instance_get(8,4,0,&out)==-EINVAL);
  for(int p=0;p<4;++p) if(p!=SELECTED)
    assert(rzv2h_driver_instance_get(8,p,0,&out)==-ENODEV);
  assert(reads==0 && initializes==0);
  actual=(struct rzv2h_wdt_sample_state_s){.identity=0x1234,.base=0x14400000,
    .channel=SELECTED,.counting_inhibited=true};
  for(int fault=0;fault<4;++fault) {
    actual.counting_inhibited=fault!=0; actual.software_active=fault==1;
    actual.start_calls=fault==2; actual.feed_calls=fault==3;
    assert(rzv2h_driver_instance_get(8,SELECTED,0,&out)==-EBUSY && initializes==0);
  }
  actual.counting_inhibited=true;actual.software_active=false;
  actual.start_calls=actual.feed_calls=0;init_error=-ENOMEM;
  assert(rzv2h_driver_instance_get(8,SELECTED,0,&out)==-ENOMEM);
  init_error=0; after_active=1;
  assert(rzv2h_driver_instance_get(8,SELECTED,0,&out)==-EBUSY);
  after_active=0;
  assert(rzv2h_driver_instance_get(8,SELECTED,0,&out)==0);
  assert(out.family==8 && out.channel==SELECTED && out.identity==actual.identity);
  assert(out.base==actual.base && actual.start_calls==0 && actual.feed_calls==0);
  int before=initializes;
  assert(rzv2h_driver_instance_get(8,SELECTED,0,&out)==0 && initializes==before);
  return 0;
}
'''
                R.run(code)

    def test_sdhi_is_available_only_on_the_implemented_cr8_core_path(self):
        with tempfile.TemporaryDirectory(prefix='rzv2h-sdhi-kconfig-') as temporary:
            path = Path(temporary) / 'Kconfig'
            path.write_text('config ARCH_CHIP_RZV\n    bool\n    default y\n'
                            'source "' + str(ARCH / 'Kconfig') + '"\n')
            for core in ('CR8_0', 'CR8_1', 'CM33'):
                with self.subTest(core=core):
                    config = kconfiglib.Kconfig(str(path), warn=False)
                    config.syms['RZV2H_BUILD_' + core].set_value('y')
                    config.syms['RZV_SDHI'].set_value('y')
                    self.assertEqual(config.syms['RZV_SDHI'].str_value,
                                     'n' if core == 'CM33' else 'y')

    def test_all_riic_public_port_ids_are_available_without_renumbering(self):
        code = R.PRE + '\nstruct i2c_master_s;\n'
        code += R.header(ARCH / 'rzv_i2c.h')
        code += '\nint main(void) {\n'
        code += '\n'.join(f'assert(RZV_RIIC{i} == {i});' for i in range(9))
        code += '\nreturn 0;\n}\n'
        R.run(code)

    def test_sdhi_snapshots_are_indexed_bounded_and_preserve_legacy_slot_zero(self):
        source = (ARCH / 'rzv_sdhi.c').read_text()
        code = R.PRE + '\n#define OK 0\n#define RZV_SDHI_NSLOTS 3\n'
        code += state_type('rzv2h_sdhi_sample_state_s')
        code += R.header(ARCH / 'hardware/rzv_sdhi.h')
        code += r'''
#define RZV_SDHI_REG32(base, offset) ((base) + (offset))
#define WDOG_ISACTIVE(wdog) (*(wdog) != 0)
typedef int irqstate_t;
struct rzv_sdhi_dev_s {
  int dev, waitsem, waitwdog, slot; uintptr_t base;
  bool initialized, irq_attached; void *buffer;
  unsigned remaining; uint32_t waitevents;
};
static struct rzv_sdhi_dev_s g_rzv_sdhi_dev[3];
static int reads[3], critical;
static uint32_t cleared[3];
static irqstate_t enter_critical_section(void) { assert(!critical++); return 0; }
static void leave_critical_section(irqstate_t flags) { (void)flags; assert(!--critical); }
static int nxsem_get_value(int *sem,int *value) { *value=*sem; return 0; }
static uint32_t getreg32(uintptr_t address) {
  assert(critical); unsigned slot=(address-0x15c00000u)/0x10000u;
  assert(slot<3); unsigned offset=(address-0x15c00000u)%0x10000u;
  assert(offset==RZV_SDHI_SD_INFO1_MASK_OFFSET ||
         offset==RZV_SDHI_SD_INFO2_MASK_OFFSET);
  ++reads[slot];
  return (offset==RZV_SDHI_SD_INFO1_MASK_OFFSET ?
          RZV_SDHI_SD_INFO1_MASK_INIT : RZV_SDHI_SD_INFO2_MASK_INIT) & ~cleared[slot];
}
'''
        code += R.extract(source, 'int rzv2h_sdhi_sample_state_at(')
        code += R.extract(source, 'int rzv2h_sdhi_sample_state(')
        code += r'''
int main(void) {
  struct rzv2h_sdhi_sample_state_s out;
  assert(rzv2h_sdhi_sample_state_at(-1,&out)==-EINVAL);
  assert(rzv2h_sdhi_sample_state_at(3,&out)==-EINVAL);
  assert(rzv2h_sdhi_sample_state_at(0,NULL)==-EINVAL);
  for (int p=0;p<3;++p) {
    assert(rzv2h_sdhi_sample_state_at(p,&out)==-EAGAIN && reads[p]==0);
    g_rzv_sdhi_dev[p]=(struct rzv_sdhi_dev_s){
      .slot=p,.base=0x15c00000u+p*0x10000u,.initialized=true};
    assert(rzv2h_sdhi_sample_state_at(p,&out)==0);
    assert(out.identity==(uintptr_t)&g_rzv_sdhi_dev[p].dev);
    assert(out.base==g_rzv_sdhi_dev[p].base && out.channel==(unsigned)p);
    assert(out.interrupts_masked && !out.irq_attached && !out.watchdog_active);
    assert(reads[p]==2);
    for(int peer=0;peer<3;++peer) assert(reads[peer]==(peer<=p ? 2 : 0));
  }
  assert(rzv2h_sdhi_sample_state(&out)==0 && out.channel==0 && reads[0]==4);
  assert(reads[1]==2 && reads[2]==2 && !critical);
  for (int p=0;p<3;++p) {
    cleared[p]=1;
    assert(rzv2h_sdhi_sample_state_at(p,&out)==0 && !out.interrupts_masked);
    cleared[p]=0;
    assert(rzv2h_sdhi_sample_state_at(p,&out)==0 && out.interrupts_masked);
  }
  assert(!critical);
  return 0;
}
'''
        R.run(code)

    def test_wdt_snapshots_read_only_the_selected_always_on_control(self):
        source = (ARCH / 'rzv_wdt.c').read_text()
        code = R.PRE + '\n#define OK 0\n#define RZV_WDT_MAX_CHANNELS 4\n'
        code += state_type('rzv2h_wdt_sample_state_s')
        code += R.header(ARCH / 'hardware/rzv_sysc.h')
        code += r'''
#define SYS_WDT_CTRL_BP_HALTED (1u << 0)
struct rzv_wdt_priv_s {
  uintptr_t base; unsigned channel, sample_starts, sample_feeds;
  bool registered, started;
};
static struct rzv_wdt_priv_s g_wdt_priv[4];
static unsigned reads[4];
static uint32_t getreg32(uintptr_t address) {
  static const uintptr_t controls[4]={RZV_SYSC_SYS_WDT0_CTRL,
    RZV_SYSC_SYS_WDT1_CTRL,RZV_SYSC_SYS_WDT2_CTRL,RZV_SYSC_SYS_WDT3_CTRL};
  for(int p=0;p<4;++p) if(address==controls[p]) {++reads[p];return SYS_WDT_CTRL_BP_HALTED;}
  assert(false);return 0;
}
'''
        code += R.extract(source, 'static uintptr_t rzv_wdt_sysc_ctrl(')
        code += R.extract(source, 'int rzv2h_wdt_sample_state_at(')
        code += R.extract(source, 'int rzv2h_wdt_sample_state(')
        code += r'''
int main(void) {
  struct rzv2h_wdt_sample_state_s out;
  assert(rzv2h_wdt_sample_state_at(-1,&out)==-EINVAL);
  assert(rzv2h_wdt_sample_state_at(4,&out)==-EINVAL);
  assert(rzv2h_wdt_sample_state_at(0,NULL)==-EINVAL);
  for(int p=0;p<4;++p) {
    g_wdt_priv[p]=(struct rzv_wdt_priv_s){
      .channel=p,.base=0x10000000u+p*0x10000u,.registered=true};
    assert(rzv2h_wdt_sample_state_at(p,&out)==0 && reads[p]==1);
    assert(out.identity==(uintptr_t)&g_wdt_priv[p] && out.base==g_wdt_priv[p].base);
    assert(out.channel==(unsigned)p && out.registered && out.counting_inhibited);
    assert(!out.software_active && out.start_calls==0 && out.feed_calls==0);
    for(int peer=0;peer<4;++peer) assert(reads[peer]==(peer<=p ? 1u : 0u));
  }
  assert(rzv2h_wdt_sample_state(&out)==0 && out.channel==0 && reads[0]==2);
  assert(reads[1]==1 && reads[2]==1 && reads[3]==1);
  return 0;
}
'''
        R.run(code)


if __name__ == '__main__':
    unittest.main()
