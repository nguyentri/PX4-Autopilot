#!/usr/bin/env python3
"""IO-core health reaches commander: commander blocks arming on a silent,
FMU-starved or failsafe I/O processor reported through px4io_status."""

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
    def test_commander_blocks_arming_on_an_unhealthy_io_processor(self):
        code = REPAIR.PRE + r'''
#include <string>
#include <vector>
typedef uint64_t hrt_abstime;
static hrt_abstime now_us;
static hrt_abstime hrt_elapsed_time(const hrt_abstime *then) { return now_us - *then; }
namespace time_literals {
constexpr hrt_abstime operator""_s(unsigned long long seconds) { return seconds * 1000000ULL; }
constexpr hrt_abstime operator""_ms(unsigned long long milliseconds) { return milliseconds * 1000ULL; }
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

  // Only the remote-output profile requires status before first publication.
  now_us = 100000000;
#ifdef CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS
  assert(check(checks).failures.size() == 1 && mavlink_logs == 1);
  now_us += 10000000;
  assert(check(checks).failures.size() == 1 && mavlink_logs == 2);
  mavlink_logs = 0;
#else
  assert(check(checks).failures.empty() && mavlink_logs == 0);
  now_us += 10000000;
  assert(check(checks).failures.empty() && mavlink_logs == 0);
#endif

  // A healthy, current I/O processor passes.
  have_status = true; current.timestamp = now_us; current.status_fmu_ok = true; current.arming_io_arm_ok = true;
  assert(check(checks).failures.empty());
#ifdef CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS
  const uint64_t allowed_age = 50000;
#else
  const uint64_t allowed_age = 2000000;
#endif
  now_us += allowed_age; assert(check(checks).failures.empty());

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

#ifdef CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS
  // Healthy transport/FMUs cannot hide a failed physical backend.
  have_status = true; current.timestamp = now_us; current.alarm_pwm_error = true;
  assert(check(checks).failures.size() == 1);
  current.alarm_pwm_error = false; current.arming_io_arm_ok = false;
  assert(check(checks).failures.size() == 1);
  current.arming_io_arm_ok = true;
  assert(check(checks).failures.empty());
#endif
}
'''
        REPAIR.run(code, cpp=True)
        REPAIR.run("#define CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS 1\n" + code, cpp=True)

    def test_commander_runs_the_io_processor_check(self):
        registry = (CHECKS / 'HealthAndArmingChecks.hpp').read_text()
        self.assertIn('#include "checks/px4ioCheck.hpp"', registry)
        self.assertRegex(registry, r'Px4ioChecks _px4io_checks;')
        checks = registry[registry.index('HealthAndArmingCheckBase *_checks['):]
        self.assertIn('&_px4io_checks,', checks[:checks.index('};')])
        self.assertIn('checks/px4ioCheck.cpp', (CHECKS / 'CMakeLists.txt').read_text())


if __name__ == '__main__':
    unittest.main()
