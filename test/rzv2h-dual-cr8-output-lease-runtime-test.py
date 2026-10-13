#!/usr/bin/env python3
"""Dual-CR8 output safety: CR8-0 link recovery, the CR8-1 epoch query, and
the build guards that keep the PX4IO bridge out of single-core images."""

import importlib.util
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARDS = ROOT / 'boards/renesas'
NUTTX = ROOT / 'platforms/nuttx/NuttX/nuttx'
SPEC = importlib.util.spec_from_file_location('expanded', ROOT / 'test/rzv2h-expanded-remediation-runtime-test.py')
EXPANDED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPANDED)
REPAIR = EXPANDED.REPAIR
extract = REPAIR.extract

PROTOCOLS = (BOARDS / 'rdk-rzv2h/px4io_cr8_0/protocol.h',
             BOARDS / 'rdk-rzv2h-io-cr8_1/px4io_cr8_1/protocol.h',
             BOARDS / 'rdk-rzv2h-io-cm33/px4io_m33/protocol.h')


class DualCr8OutputLease(unittest.TestCase):
    def test_cr8_0_bridge_recovers_a_quarantined_link_without_replaying_commands(self):
        owner = BOARDS / 'rdk-rzv2h/px4io_cr8_0'
        source = (owner / 'uorb_bridge.cpp').read_text()
        interval = re.search(r'static constexpr uint64_t RECOVER_RETRY_INTERVAL_US = \d+;',
                             (owner / 'uorb_bridge.h').read_text()).group(0)
        code = EXPANDED.io_prelude(owner) + '#include <unistd.h>\n' + REPAIR.raw_write_fake() + \
            REPAIR.raw_ioctl_fake() + r'''
#include <string>
static std::vector<std::string> logs;
#define PX4_INFO(fmt, ...) logs.push_back(std::string("I:") + fmt)
#define PX4_ERR(fmt, ...) logs.push_back(std::string("E:") + fmt)
static int write_errno, read_errno;
static ssize_t fault_write(int fd, const void *data, size_t size) {
  if (write_errno != 0) { errno = write_errno; return -1; }
  return test_write(fd, data, size);
}
static ssize_t fault_read(int fd, void *data, size_t size) { errno = read_errno ? read_errno : EAGAIN; return -1; }
#define write fault_write
#define read fault_read
static uint64_t clock_us;
static uint64_t hrt_absolute_time() { return clock_us; }
static constexpr size_t IPC_ENTRY_SIZE = 64;
static int liveness_checks, tx_rounds;
class UorbBridgeCR8 {public:
''' + '  ' + interval + r'''
  int _fd{3}; bool _link_down{false}; uint64_t _last_recover_attempt_us{0};
  uint16_t _seq_actuator{0};
  uint16_t _expected_seq_rc{5}, _expected_seq_esc{6}, _expected_seq_battery{7}, _expected_seq_safety{8};
  struct { uint32_t crc_errors{}, sequence_gaps{}, link_faults{}, link_recoveries{}, recover_failures{}; } _stats;
  void update();
  static uint32_t calculate_crc32(const uint8_t *data, size_t len);
  bool send_msg(MessageType_e type, uint16_t &seq, void *msg, size_t len);
  void note_link_error(int err);
  void recover_link(uint64_t now);
  void process_actuator_outputs() { ++tx_rounds; ActuatorCommand_t c{}; send_msg(MSG_TYPE_ACTUATOR_CMD, _seq_actuator, &c, sizeof(c)); }
  void process_vehicle_command() {}
  void process_vehicle_status() {}
  void send_heartbeat() {}
  void process_rx();
  bool validate_message_crc(const void *, size_t) { assert(false); return false; }
  void handle_heartbeat(const Heartbeat_t &, uint64_t) { assert(false); }
  void handle_fault_status(const FaultStatus_t &) { assert(false); }
  void update_io_liveness(uint64_t) { ++liveness_checks; }
  void publish_input_rc(const InputRC_t &) { assert(false); }
  void publish_esc_status(const ESCStatus_t &) { assert(false); }
  void publish_battery_status(const BatteryStatus_t &) { assert(false); }
};
'''
        for name in ('void UorbBridgeCR8::update(', 'uint32_t UorbBridgeCR8::calculate_crc32(',
                     'bool UorbBridgeCR8::send_msg(', 'void UorbBridgeCR8::note_link_error(',
                     'void UorbBridgeCR8::recover_link(', 'void UorbBridgeCR8::process_rx('):
            code += extract(source, name)
        code += r'''
static size_t recover_calls() {
  size_t n = 0; for (int cmd : raw_ioctl_calls) n += cmd == RZV_IPC_RAWIOC_RECOVER; return n;
}
int main() {
  const uint64_t R = UorbBridgeCR8::RECOVER_RETRY_INTERVAL_US;
  UorbBridgeCR8 b;

  // Flow control is not a fault: a full ring (write) or empty ring (read).
  clock_us = 1000; write_errno = EAGAIN; b.update();
  assert(!b._link_down && b._stats.link_faults == 0 && logs.empty() && tx_rounds == 1);
  write_errno = 0; read_errno = EINTR; b.update();
  assert(!b._link_down && written.size() == 1);
  read_errno = 0;

  // An ACK timeout quarantines the link once; repeated errors are not recounted.
  write_errno = ETIMEDOUT; b.update();
  assert(b._link_down && b._stats.link_faults == 1 && logs.size() == 1 && logs[0][0] == 'E');
  b.note_link_error(ENOLINK); b.note_link_error(EPROTO);
  assert(b._stats.link_faults == 1 && logs.size() == 1);

  // While down: RECOVER is tried, nothing is sent, liveness still ages
  // (process_rx checks liveness on every healthy tick: three so far).
  assert(liveness_checks == 3);
  raw_ioctl_errno = EAGAIN; write_errno = 0; clock_us = 2000;
  b.update();
  assert(recover_calls() == 1 && b._stats.recover_failures == 1 && b._link_down);
  assert(tx_rounds == 3 && written.size() == 1 && liveness_checks == 4);

  // Rate limit: no second RECOVER inside the retry interval.
  clock_us = 2000 + R - 1; b.update();
  assert(recover_calls() == 1 && liveness_checks == 5 && tx_rounds == 3);

  // Success: new epoch, RX sequence tracking restarts, TX resumes in the same tick.
  raw_ioctl_errno = 0; clock_us = 2000 + R; b.update();
  assert(recover_calls() == 2 && !b._link_down && b._stats.link_recoveries == 1);
  assert(b._expected_seq_rc == 0 && b._expected_seq_esc == 0 && b._expected_seq_battery == 0 &&
         b._expected_seq_safety == 0);
  assert(tx_rounds == 4 && written.size() == 2 && liveness_checks == 6 && logs.back()[0] == 'I');

  // A read-side link error also quarantines the link.
  read_errno = ENOLINK; clock_us += 1000; b.update();
  assert(b._link_down && b._stats.link_faults == 2);
  read_errno = 0;

  // The next attempt waits a full interval after the last one.
  clock_us = 2000 + R + 2000; b.update();
  assert(recover_calls() == 2 && b._link_down);
  clock_us = 2000 + 2 * R; b.update();
  assert(recover_calls() == 3 && !b._link_down && b._stats.link_recoveries == 2);
}
'''
        REPAIR.run(code, cpp=True)

    def test_cr8_1_output_lease_follows_the_safe_fault_state_machine(self):
        owner = BOARDS / 'rdk-rzv2h-io-cr8_1/px4io_cr8_1'
        source = (owner / 'px4io_cr8.cpp').read_text()
        code = EXPANDED.io_prelude(owner) + EXPANDED.output_lease(owner) + r'''
struct FmuTransport {
  std::deque<ActuatorCommand_t> queue; uint32_t epoch = 1; bool epoch_ok = true;
  int switch_after = -1; uint32_t next_epoch = 0; int reads = 0;
  bool receive_actuator_command(ActuatorCommand_t &cmd) {
    if (reads++ == switch_after) epoch = next_epoch;  // the read adopts a new epoch
    if (queue.empty()) return false;
    cmd = queue.front(); queue.pop_front(); return true;
  }
  bool link_epoch(uint32_t &value) const { value = epoch; return epoch_ok; }
};
class Px4IoCr8 {public:
  static bool fmu_command_valid(const ActuatorCommand_t &cmd);
  void receive_fmu_commands(hrt_abstime now);
  FmuTransport _fmu_transport; OutputLease _lease;};
'''
        for name in ('bool Px4IoCr8::fmu_command_valid(', 'void Px4IoCr8::receive_fmu_commands('):
            code += extract(source, name)
        code += r'''
using S = OutputLease::State;
static ActuatorCommand_t cmd(unsigned armed) {
  ActuatorCommand_t c{}; for (unsigned i = 0; i < IPC_MAX_ACTUATORS; ++i) c.outputs[i] = 1500;
  c.armed = armed; c.safety_off = 1; return c;
}
static void feed(Px4IoCr8 &io, std::initializer_list<unsigned> armed, hrt_abstime now) {
  for (unsigned a : armed) io._fmu_transport.queue.push_back(cmd(a));
  io._fmu_transport.reads = 0; io.receive_fmu_commands(now);
}
static bool off(const ActuatorCmdToM33_t &o) {
  for (unsigned i = 0; i < IPC_MAX_ACTUATORS; ++i) if (o.commands[i] != 0) return false;
  return o.armed == 0 && o.safety_off == 0;
}
int main() {
  const hrt_abstime T = FMU_LOSS_TIMEOUT_US;
  const uint32_t SAFE = FAULT_FLAG_OUTPUT_SAFE_FAULT, TIMEOUT = FAULT_FLAG_CR8_TIMEOUT;
  Px4IoCr8 io; auto &l = io._lease; auto &fmu = io._fmu_transport;

  // Booting never arms: an armed command without a disarmed handshake is refused.
  assert(l.state() == S::Safe && l.fault_flags(0) == TIMEOUT && off(l.output(0)));
  feed(io, {1}, 1000);
  assert(l.state() == S::Safe && off(l.output(1000)));
  assert(l.fault_flags(1000) == FAULT_FLAG_ARM_REJECTED);

  // Handshake in one drain: disarmed, then armed.
  feed(io, {0, 1}, 2000);
  assert(l.state() == S::Armed && l.output(2000).armed == 1 && l.fault_flags(2000) == 0);

  // Lease expiry while armed latches SafeFault; outputs stay off.
  feed(io, {}, 2000 + T);
  assert(l.state() == S::Fault && off(l.output(2000 + T)));
  assert(l.fault_flags(2000 + T) == (TIMEOUT | SAFE));

  // No direct path from SafeFault to output: armed is refused, latch kept.
  feed(io, {1}, 3000 + T);
  assert(l.state() == S::Fault && off(l.output(3000 + T)));
  assert(l.fault_flags(3000 + T) == (SAFE | TIMEOUT | FAULT_FLAG_ARM_REJECTED));

  // A disarmed command in the current session clears it; then re-arm.
  feed(io, {0}, 4000 + T);
  assert(l.state() == S::Ready && l.fault_flags(4000 + T) == 0 && l.output(4000 + T).armed == 0);
  assert(!off(l.output(4000 + T)));
  feed(io, {1}, 5000 + T);
  assert(l.state() == S::Armed);

  // accept() expires a stale lease itself: an armed command after a gap is refused.
  feed(io, {1}, 5000 + 2 * T);
  assert(l.state() == S::Fault && off(l.output(5000 + 2 * T)));
  feed(io, {0, 1}, 6000 + 2 * T);
  assert(l.state() == S::Armed);

  // A new CR8-0 epoch adopted by a read ends the session before its command is used.
  fmu.switch_after = 0; fmu.next_epoch = 2;
  feed(io, {1}, 7000 + 2 * T);
  assert(l.state() == S::Fault && off(l.output(7000 + 2 * T)));
  // The refused command still proves CR8-0 is alive, so no CR8_TIMEOUT here.
  assert(l.fault_flags(7000 + 2 * T) == (SAFE | FAULT_FLAG_PEER_SESSION | FAULT_FLAG_ARM_REJECTED));
  fmu.switch_after = -1;
  feed(io, {0, 1}, 8000 + 2 * T);
  assert(l.state() == S::Armed && l.fault_flags(8000 + 2 * T) == 0);

  // Losing the epoch query ends the session and refuses every command.
  fmu.epoch_ok = false;
  feed(io, {0, 1}, 9000 + 2 * T);
  assert(l.state() == S::Fault && off(l.output(9000 + 2 * T)));
  assert(l.fault_flags(9000 + 2 * T) & FAULT_FLAG_ARM_REJECTED);
  fmu.epoch_ok = true;
  feed(io, {0}, 10000 + 2 * T);
  assert(l.state() == S::Ready);

  // Expiry while disarmed is not a fault: back to Safe, nothing latched.
  feed(io, {}, 10000 + 3 * T);
  assert(l.state() == S::Safe && l.fault_flags(10000 + 3 * T) == TIMEOUT && off(l.output(10000 + 3 * T)));

  // A peer epoch change while merely Ready also returns to Safe.
  feed(io, {0}, 11000 + 3 * T);
  fmu.epoch = 3; feed(io, {}, 12000 + 3 * T);
  assert(l.state() == S::Safe && l.fault_flags(12000 + 3 * T) == TIMEOUT);
}
'''
        REPAIR.run(code, cpp=True)

    def test_cr8_1_transport_reports_the_driver_epoch(self):
        code = REPAIR.cr8_1_transport_harness() + r'''
int main() {
  SharedMemTransport idle("/dev/ipcc1"); uint32_t epoch = 99;
  assert(!idle.link_epoch(epoch) && epoch == 99 && raw_ioctl_calls.empty());
  SharedMemTransport io("/dev/ipcc1"); assert(io.init(false));
  raw_stats.epoch = 13;
  assert(io.link_epoch(epoch) && epoch == 13);
  assert(raw_ioctl_calls.size() == 1 && raw_ioctl_calls[0] == RZV_IPC_RAWIOC_GET_STATS);
  raw_ioctl_errno = EINTR; epoch = 7;
  assert(!io.link_epoch(epoch) && epoch == 7);
}
'''
        REPAIR.run(code, cpp=True)

    def test_epoch_snapshot_does_not_wait_behind_a_blocked_writer(self):
        source = (NUTTX / 'arch/arm/src/rzv/rzv_ipc_raw_chardev.c').read_text()
        body = extract(source, 'static int rzv_raw_ioctl(')
        stats = body[body.index('case RZV_IPC_RAWIOC_GET_STATS'):body.index('case RZV_IPC_RAWIOC_RECOVER')]
        self.assertIn('nxmutex_lock(&priv->rxlock)', stats)
        self.assertIn('nxmutex_unlock(&priv->rxlock)', stats)
        self.assertNotIn('&priv->lock', stats)

    def test_single_core_images_never_build_the_px4io_bridge(self):
        kconfig = (BOARDS / 'rdk-rzv2h/Kconfig').read_text()
        entry = kconfig[kconfig.index('config BOARD_RDK_RZV2H_PX4IO_BRIDGE'):]
        entry = entry[:entry.index('\nconfig ') if '\nconfig ' in entry else len(entry)]
        self.assertRegex(entry, r'default n\b')
        for board in sorted((BOARDS / 'rdk-rzv2h').glob('*.px4board')):
            self.assertNotRegex(board.read_text(), r'(?m)^CONFIG_BOARD_RDK_RZV2H_PX4IO_BRIDGE=y',
                                board.name)
        bridge = (BOARDS / 'rdk-rzv2h/px4io_cr8_0/uorb_bridge.cpp').read_text()
        self.assertRegex(bridge, r'#if !defined\(CONFIG_RZV_IPC_RAW\) \|\| '
                                 r'!defined\(CONFIG_RZV_IPC_ROLE_INITIATOR\)\n#\s*error')
        self.assertRegex(bridge, r'CONFIG_RZV_IPC_RECOVERY_WAIT_MS > 100\n#\s*error')

    def test_every_core_shares_the_lease_and_safe_fault_contract(self):
        names = ('FMU_LOSS_TIMEOUT_US', 'FAULT_FLAG_CR8_TIMEOUT', 'FAULT_FLAG_OUTPUT_SAFE_FAULT',
                 'FAULT_FLAG_PEER_SESSION', 'FAULT_FLAG_ARM_REJECTED')
        texts = [path.read_text() for path in PROTOCOLS]
        for name in names:
            values = {re.search(rf'#define {name}\s+(\S+)', text).group(1) for text in texts}
            self.assertEqual(len(values), 1, (name, values))
        self.assertEqual(re.search(r'#define FMU_LOSS_TIMEOUT_US\s+(\d+)', texts[0]).group(1), '50000')
        flags = [int(re.search(rf'#define {name}\s+\(1 << (\d+)\)', texts[0]).group(1)) for name in names[1:]]
        self.assertEqual(len(set(flags)), len(flags))


if __name__ == '__main__':
    unittest.main()
