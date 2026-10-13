#!/usr/bin/env python3
"""IO-core health reaches commander: the CR8-0 bridge maps CR8-1 link,
heartbeat and SafeFault state onto px4io_status, and commander blocks arming
on a silent, FMU-starved or failsafe I/O processor."""

import importlib.util
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARDS = ROOT / 'boards/renesas'
CHECKS = ROOT / 'src/modules/commander/HealthAndArmingChecks'
SPEC = importlib.util.spec_from_file_location('expanded', ROOT / 'test/rzv2h-expanded-remediation-runtime-test.py')
EXPANDED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPANDED)
REPAIR = EXPANDED.REPAIR
extract = REPAIR.extract

MSG_TYPES = {'bool': 'bool', 'uint16': 'uint16_t', 'uint64': 'uint64_t', 'float32': 'float'}


def px4io_status_struct():
    """px4io_status_s generated from the message definition."""
    fields = []
    for line in (ROOT / 'msg/Px4ioStatus.msg').read_text().splitlines():
        match = re.match(r'^(\w+)(\[\d+\])?\s+(\w+)', line)
        if match:
            fields.append(f'  {MSG_TYPES[match.group(1)]} {match.group(3)}{match.group(2) or ""}{{}};')
    return 'struct px4io_status_s {\n' + '\n'.join(fields) + '\n};\n'


class IoCoreHealth(unittest.TestCase):
    def test_cr8_0_bridge_reports_cr8_1_state_as_px4io_status(self):
        owner = BOARDS / 'rdk-rzv2h/px4io_cr8_0'
        source = (owner / 'uorb_bridge.cpp').read_text()
        code = EXPANDED.io_prelude(owner) + '#include <vector>\n' + px4io_status_struct() + r'''
static std::vector<px4io_status_s> published;
struct StatusPub { bool publish(const px4io_status_s &s) { published.push_back(s); return true; } };
class UorbBridgeCR8 {public:
  bool _io_alive{false}; bool _link_down{false};
  uint32_t _io_fault_flags{0}; uint8_t _io_armed_state{0};
  StatusPub _px4io_status_pub; px4io_status_s _px4io_status{};
  void publish_io_status(uint64_t now);};
'''
        code += extract(source, 'void UorbBridgeCR8::publish_io_status(')
        code += r'''
static const px4io_status_s &last() { assert(!published.empty()); return published.back(); }
int main() {
  UorbBridgeCR8 b;

  // Before the first CR8-1 heartbeat: published, and not OK to arm.
  b.publish_io_status(1000);
  assert(published.size() == 1 && last().timestamp == 1000);
  assert(!last().status_init_ok && !last().status_fmu_ok && !last().arming_io_arm_ok);

  // Unchanged state republishes at 1 Hz only.
  b.publish_io_status(1000 + 999999);
  assert(published.size() == 1);
  b.publish_io_status(1000 + 1000000);
  assert(published.size() == 2);

  // Alive with a fresh lease and heartbeat: OK, at once.
  b._io_alive = true; b.publish_io_status(1001000 + 10);
  assert(published.size() == 3 && last().status_init_ok && last().status_fmu_ok && last().arming_io_arm_ok);
  assert(!last().status_failsafe && !last().status_outputs_armed);
  b._io_armed_state = 1; b.publish_io_status(1001000 + 20);
  assert(published.size() == 4 && last().status_outputs_armed);
  b._io_armed_state = 0;

  // A stale CR8-1 lease or CR8-0 heartbeat is not FMU OK.
  const uint32_t stale[] = {FAULT_FLAG_CR8_TIMEOUT, FAULT_FLAG_FMU_HEARTBEAT};
  for (uint32_t flag : stale) {
    b._io_fault_flags = flag; b.publish_io_status(2000000);
    assert(!last().status_fmu_ok && !last().arming_io_arm_ok && !last().status_failsafe);
    b._io_fault_flags = 0; b.publish_io_status(2000000);
    assert(last().status_fmu_ok);
  }

  // A latched SafeFault is failsafe and never OK to arm.
  b._io_fault_flags = FAULT_FLAG_OUTPUT_SAFE_FAULT; b.publish_io_status(3000000);
  assert(last().status_failsafe && last().status_fmu_ok && !last().arming_io_arm_ok);
  b._io_fault_flags = FAULT_FLAG_PWM_FAULT; b.publish_io_status(3000001);
  assert(!last().status_failsafe && last().alarm_pwm_error && last().arming_io_arm_ok);

  // A quarantined link is not FMU OK even with a recent CR8-1 heartbeat.
  b._io_fault_flags = 0; b._link_down = true; b.publish_io_status(4000000);
  assert(!last().status_fmu_ok && last().status_init_ok);
  b._link_down = false;

  // A silent CR8-1: its last flags are not trusted, outputs not reported armed.
  b._io_fault_flags = FAULT_FLAG_OUTPUT_SAFE_FAULT; b._io_armed_state = 1; b._io_alive = false;
  b.publish_io_status(5000000);
  assert(!last().status_init_ok && !last().status_fmu_ok && !last().status_failsafe);
  assert(!last().status_outputs_armed && !last().arming_io_arm_ok);
}
'''
        REPAIR.run(code, cpp=True)

    def test_cr8_0_bridge_publishes_status_on_every_update_path(self):
        source = (BOARDS / 'rdk-rzv2h/px4io_cr8_0/uorb_bridge.cpp').read_text()
        update = extract(source, 'void UorbBridgeCR8::update(')
        self.assertEqual(update.count('publish_io_status(hrt_absolute_time());'), 2)
        down = update[update.index('if (_link_down) {\n\t\t\tupdate_io_liveness'):update.index('return;')]
        self.assertIn('publish_io_status', down)
        self.assertLess(update.index('process_rx();'), update.rindex('publish_io_status'))

    def test_commander_blocks_arming_on_an_unhealthy_io_processor(self):
        code = REPAIR.PRE + r'''
#include <string>
#include <vector>
typedef uint64_t hrt_abstime;
static hrt_abstime now_us;
static hrt_abstime hrt_elapsed_time(const hrt_abstime *then) { return now_us - *then; }
namespace time_literals {
constexpr hrt_abstime operator""_s(unsigned long long seconds) { return seconds * 1000000ULL; }
}
''' + px4io_status_struct() + r'''
#define ORB_ID(name) 0
static bool have_status; static px4io_status_s current;
namespace uORB { struct Subscription {
  explicit Subscription(int) {}
  bool copy(px4io_status_s *out) { if (!have_status) return false; *out = current; return true; }
};}
enum class NavModes { None, All };
enum class health_component_t { motors_escs };
namespace events { inline uint32_t ID(const char *) { return 1; } enum class Log { Critical }; }
static int mavlink_logs;
#define mavlink_log_critical(pub, ...) (++mavlink_logs)
struct Context {};
struct Report {
  std::vector<std::string> failures; std::vector<NavModes> modes; std::vector<health_component_t> components;
  void healthFailure(NavModes m, health_component_t c, uint32_t, events::Log, const char *message) {
    modes.push_back(m); components.push_back(c); failures.push_back(message);
  }
  int *mavlink_log_pub() { return &mavlink_logs; }
};
class HealthAndArmingCheckBase {public: virtual ~HealthAndArmingCheckBase() = default;
  virtual void checkAndReport(const Context &context, Report &reporter) = 0;};
''' + REPAIR.header(CHECKS / 'checks/px4ioCheck.hpp').replace('#pragma once', '') + \
            REPAIR.header(CHECKS / 'checks/px4ioCheck.cpp') + r'''
static Report check(Px4ioChecks &checks) { Report r; checks.checkAndReport(Context{}, r); return r; }
int main() {
  Px4ioChecks checks;

  // Boards without an I/O processor are never checked.
  now_us = 100000000; assert(check(checks).failures.empty() && mavlink_logs == 0);
  now_us += 10000000; assert(check(checks).failures.empty() && mavlink_logs == 0);

  // A healthy, current I/O processor passes.
  have_status = true; current.timestamp = now_us; current.status_fmu_ok = true;
  assert(check(checks).failures.empty());
  now_us += 2000000; assert(check(checks).failures.empty());

  // Silent for longer than two publish periods.
  now_us += 1;
  Report r = check(checks);
  assert(r.failures.size() == 1 && r.failures[0] == "I/O processor not responding");
  assert(r.modes[0] == NavModes::All && r.components[0] == health_component_t::motors_escs);
  assert(mavlink_logs == 1);

  // Failsafe wins over a missing FMU stream; one failure per cycle.
  current.timestamp = now_us; current.status_failsafe = true; current.status_fmu_ok = false;
  r = check(checks);
  assert(r.failures.size() == 1 && r.failures[0] == "I/O processor in failsafe" && r.modes[0] == NavModes::All);
  current.status_failsafe = false;
  r = check(checks);
  assert(r.failures.size() == 1 && r.failures[0] == "I/O processor not receiving FMU outputs");
  assert(r.modes[0] == NavModes::All && mavlink_logs == 3);

  // A healthy sample, then the publisher exits and unadvertises the topic:
  // still checked, on the last sample, which goes stale.
  current.timestamp = now_us; current.status_fmu_ok = true;
  assert(check(checks).failures.empty());
  have_status = false; assert(check(checks).failures.empty());
  now_us += 2000001; r = check(checks);
  assert(r.failures.size() == 1 && r.failures[0] == "I/O processor not responding");
}
'''
        REPAIR.run(code, cpp=True)

    def test_commander_runs_the_io_processor_check(self):
        registry = (CHECKS / 'HealthAndArmingChecks.hpp').read_text()
        self.assertIn('#include "checks/px4ioCheck.hpp"', registry)
        self.assertRegex(registry, r'Px4ioChecks _px4io_checks;')
        checks = registry[registry.index('HealthAndArmingCheckBase *_checks['):]
        self.assertIn('&_px4io_checks,', checks[:checks.index('};')])
        self.assertIn('checks/px4ioCheck.cpp', (CHECKS / 'CMakeLists.txt').read_text())


if __name__ == '__main__':
    unittest.main()
