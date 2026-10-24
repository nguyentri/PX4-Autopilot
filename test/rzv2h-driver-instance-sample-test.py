#!/usr/bin/env python3
"""Execute instance-suite prerequisites and the board's side-effect-free guard."""

import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
APPS = ROOT / "platforms/nuttx/NuttX/apps/testing/rzv_hwtest"
SPEC = importlib.util.spec_from_file_location(
    "runtime", ROOT / "test/rzv2h-audit-remediation-runtime-test.py")
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
BOARD = NUTTX / "boards/arm/rzv/rdk-rzv2h"


def types():
    header = (BOARD / "include/rzv2h-sample-test.h").read_text()
    return "\n".join(re.search(r"struct " + name + r"\n\{.*?\n\};",
                               header, re.S)[0] for name in (
                                   "rzv2h_driver_instance_state_s",
                                   "rzv2h_bus_sample_state_s"))


class InstanceSuite(unittest.TestCase):
    def test_ether_provider_selects_actual_port_and_rejects_active_state(self):
        source = (BOARD / "src/rzv2h_instance_test.c").read_text()
        header = (BOARD / "include/rzv2h-sample-test.h").read_text()
        code = RUNTIME.PRE + "\n#define OK 0\n#define CONFIG_RZV_ETHERNET 1\n" + types()
        code += re.search(r"struct rzv2h_ether_sample_state_s\n\{.*?\n\};",
                          header, re.S)[0]
        code += r'''
static int access_result, init_result, state_result, init_calls, state_calls;
static struct rzv2h_ether_sample_state_s actual;
static int rzv2h_ether_sample_access(int port)
{ assert(port >= 0 && port < 2); return access_result; }
static int rzv2h_ether_initialize(void) { ++init_calls; return init_result; }
static int rzv2h_ether_sample_state_at(int port,
                                     struct rzv2h_ether_sample_state_s *s)
{ assert(port >= 0 && port < 2); ++state_calls; *s = actual; return state_result; }
'''
        code += RUNTIME.extract(source, "int rzv2h_driver_instance_get(")
        code += r'''
int main(void)
{
  struct rzv2h_driver_instance_state_s out;
  for (int p = 0; p < 2; ++p) {
    actual = (struct rzv2h_ether_sample_state_s) {
      .identity = 0x1000u + p, .base = 0x15c30000u + p * 0x10000u, .intf = p};
    init_calls = state_calls = 0;
    access_result = -ENODEV;
    assert(rzv2h_driver_instance_get(6,p,0,&out) == -ENODEV);
    assert(init_calls == 0 && state_calls == 0);
    access_result = -EAGAIN; init_result = -EIO;
    assert(rzv2h_driver_instance_get(6,p,0,&out) == -EIO && state_calls == 0);
    init_result = 0;
    assert(rzv2h_driver_instance_get(6,p,0,&out) == 0);
    assert(out.family == 6 && out.channel == (unsigned)p && out.unit == 0);
    assert(out.identity == actual.identity && out.base == actual.base);
    access_result = 0; int count = init_calls;
    assert(rzv2h_driver_instance_get(6,p,0,&out) == 0 && init_calls == count);
    state_result = -EIO;
    assert(rzv2h_driver_instance_get(6,p,0,&out) == -EIO);
    state_result = 0;
    for (int field = 0; field < 5; ++field) {
      actual.dma_running = field == 0; actual.loop = field == 1;
      actual.phy_writes = field == 2; actual.queued_work = field == 3;
      actual.attached_irqs = field == 4;
      assert(rzv2h_driver_instance_get(6,p,0,&out) == -EBUSY);
    }
    actual = (struct rzv2h_ether_sample_state_s){0};
    assert(rzv2h_driver_instance_get(6,p,0,&out) == -ENODEV);
  }
  int count = state_calls;
  assert(rzv2h_driver_instance_get(6,2,0,&out) == -EINVAL);
  assert(rzv2h_driver_instance_get(6,0,1,&out) == -EINVAL);
  assert(state_calls == count);
  return 0;
}
'''
        RUNTIME.run(code)

    def test_failed_identity_blocks_reinitialization_and_state_is_actual(self):
        code = RUNTIME.PRE + "\n#include <inttypes.h>\n#include <stdio.h>\n" + types()
        code += RUNTIME.header(APPS / "hwtest.h") + r'''
#define CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY 5
#define CONFIG_TESTING_RZV_HWTEST_INSTANCE_CHANNEL 15
#define CONFIG_TESTING_RZV_HWTEST_INSTANCE_OUTPUT 1
#define LOG_INFO 1
char g_hwtest_fail_reason[128];
static int calls, fault, logs;
static int rzv2h_driver_instance_get(unsigned family,int channel,unsigned output,
                                    struct rzv2h_driver_instance_state_s *s)
{
  if (channel < 0 || channel >= 16) return -EINVAL;
  assert(family==5 && channel==15 && output==1); ++calls;
  if (fault==1) return -EIO;
  *s=(struct rzv2h_driver_instance_state_s){
    .identity=0x1234,.base=0x11a00000,.family=5,.unit=1,.channel=15,.output=1};
  if (fault==2) s->identity=0;
  if (fault==3) s->base=0;
  if (fault==4) s->family=4;
  if (fault==5) s->channel=14;
  if (fault==6) s->output=0;
  if (fault==7) s->identity++;
  return 0;
}
static void captured_log(int level,const char *fmt,...)
{ assert(level==LOG_INFO && strstr(fmt,"instance_identity=%")); ++logs; }
#define syslog captured_log
'''
        code += RUNTIME.header(APPS / "core/driver_instance_test.c")
        code += r'''
int main(void)
{
  unsigned count; const struct hwtest_case_s *cases=driver_instance_cases(&count);
  assert(count==3 && !strcmp(cases[0].suite,"instance"));
  assert(guard()==HWTEST_PASS && calls==0);
  assert(stable()==HWTEST_FAIL && calls==0 && logs==0);
  for(fault=1;fault<=6;fault++) {
    assert(identity()==HWTEST_FAIL); int before=calls;
    assert(stable()==HWTEST_FAIL && calls==before && logs==0);
  }
  fault=0;assert(identity()==HWTEST_PASS && stable()==HWTEST_PASS && logs==1);
  fault=7;assert(stable()==HWTEST_FAIL && logs==1);
  fault=1;assert(identity()==HWTEST_FAIL); int before=calls;
  assert(stable()==HWTEST_FAIL && calls==before && logs==1);
  return 0;
}
'''
        RUNTIME.run(code)

    def test_real_board_guard_rejects_invalid_and_unavailable_instances(self):
        source = (BOARD / "src/rzv2h_instance_test.c").read_text()
        code = RUNTIME.PRE + "\n#define OK 0\n" + types()
        code += RUNTIME.extract(source, "int rzv2h_driver_instance_get(")
        code += r'''
int main(void)
{
  struct rzv2h_driver_instance_state_s s;
  for(unsigned family=1;family<=8;family++) {
    assert(rzv2h_driver_instance_get(family,-1,0,&s)==-EINVAL);
    assert(rzv2h_driver_instance_get(family,16,0,&s)==-EINVAL);
    assert(rzv2h_driver_instance_get(family,0,2,&s)==-EINVAL);
    assert(rzv2h_driver_instance_get(family,0,0,NULL)==-EINVAL);
    assert(rzv2h_driver_instance_get(family,0,0,&s)==-ENOTSUP);
  }
  assert(rzv2h_driver_instance_get(0,0,0,&s)==-EINVAL);
  assert(rzv2h_driver_instance_get(9,0,0,&s)==-EINVAL);
  assert(rzv2h_driver_instance_get(1,9,0,&s)==-EINVAL);
  assert(rzv2h_driver_instance_get(2,3,0,&s)==-EINVAL);
  assert(rzv2h_driver_instance_get(3,10,0,&s)==-EINVAL);
  assert(rzv2h_driver_instance_get(4,10,0,&s)==-EINVAL);
  return 0;
}
'''
        RUNTIME.run(code)


if __name__ == "__main__":
    unittest.main()
