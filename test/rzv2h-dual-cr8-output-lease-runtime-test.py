#!/usr/bin/env python3
"""Dual-CR8 output safety: CR8-0 link recovery, the CR8-1 epoch query, and
the build guards that keep the PX4IO bridge out of single-core images."""

import importlib.util
import re
import subprocess
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
static int liveness_checks, tx_rounds, status_publishes;
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
  void publish_io_status(uint64_t) { ++status_publishes; }
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
  // Commander keeps seeing the IO status on healthy and quarantined ticks.
  assert(status_publishes == 4);

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
        code = EXPANDED.io_prelude(owner) + EXPANDED.output_lease(owner) + EXPANDED.fmu_inbox(owner) + r'''
struct FmuTransport : FmuInbox {
  uint32_t epoch = 1; bool epoch_ok = true; int switch_after = -1; uint32_t next_epoch = 0;
  bool receive_fmu_message(FmuMessage &msg) {
    if (reads == switch_after) epoch = next_epoch;  // the read adopts a new epoch
    return next(msg);
  }
  bool link_epoch(uint32_t &value) const { value = epoch; return epoch_ok; }
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
using S = OutputLease::State;
static ActuatorCommand_t cmd(unsigned armed) {
  ActuatorCommand_t c{}; for (unsigned i = 0; i < IPC_MAX_ACTUATORS; ++i) c.outputs[i] = 1500;
  c.armed = armed; c.safety_off = 1; return c;
}
static void feed(Px4IoCr8 &io, std::initializer_list<unsigned> armed, hrt_abstime now) {
  for (unsigned a : armed) io._fmu_transport.push(cmd(a));
  io._fmu_transport.reads = 0; io.receive_fmu_commands(now);
}
static bool off(const ActuatorCmdToM33_t &o) {
  for (unsigned i = 0; i < IPC_MAX_ACTUATORS; ++i) if (o.commands[i] != 0) return false;
  return o.armed == 0 && o.safety_off == 0;
}
int main() {
  const hrt_abstime T = FMU_LOSS_TIMEOUT_US;
  const uint32_t SAFE = FAULT_FLAG_OUTPUT_SAFE_FAULT, TIMEOUT = FAULT_FLAG_CR8_TIMEOUT;
  const uint32_t HEARTBEAT = FAULT_FLAG_FMU_HEARTBEAT;
  Px4IoCr8 io; auto &l = io._lease; auto &fmu = io._fmu_transport;

  // Booting never arms: an armed command without a disarmed handshake is refused.
  assert(l.state() == S::Safe && l.fault_flags(0) == (TIMEOUT | HEARTBEAT) && off(l.output(0)));
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
  assert(l.state() == S::Safe && l.fault_flags(12000 + 3 * T) == (TIMEOUT | HEARTBEAT));

  // The CR8-0 heartbeat is a separate condition: commands alone never leave Safe.
  const hrt_abstime B = 1000000, H = HEARTBEAT_TIMEOUT_US;
  fmu.auto_beat = false;
  feed(io, {0, 1}, B);
  assert(l.state() == S::Safe && off(l.output(B)));
  assert(l.fault_flags(B) == (HEARTBEAT | FAULT_FLAG_ARM_REJECTED));

  // Only the running CR8-0 heartbeat counts.
  fmu.beat(CORE_ID_CR8_1); fmu.beat(CORE_ID_CR8_0, 0); feed(io, {0}, B + 1000);
  assert(l.state() == S::Safe && !l.peer_alive(B + 1000) && off(l.output(B + 1000)));

  // A disarmed command sent before the first heartbeat is no handshake.
  fmu.push(cmd(0)); fmu.beat(); fmu.push(cmd(1)); feed(io, {}, B + 1500);
  assert(l.state() == S::Safe && off(l.output(B + 1500)));
  assert(l.fault_flags(B + 1500) == FAULT_FLAG_ARM_REJECTED);
  fmu.beat(); feed(io, {0, 1}, B + 2000);
  assert(l.state() == S::Armed && l.output(B + 2000).armed == 1 && l.fault_flags(B + 2000) == 0);

  // Fresh commands keep outputs armed only until the heartbeat ages out;
  // then SafeFault latches with the heartbeat as the reason.
  for (hrt_abstime t = B + 2000; t + T / 2 <= B + 2000 + H; t += T / 2) {
    feed(io, {1}, t);
    assert(l.state() == S::Armed && l.output(t).armed == 1 && l.fault_flags(t) == 0);
  }
  // output() itself refuses a stale heartbeat before the loop runs update().
  assert(l.state() == S::Armed && off(l.output(B + 2000 + H)));
  feed(io, {1}, B + 2000 + H);
  assert(l.state() == S::Fault && off(l.output(B + 2000 + H)));
  assert(l.fault_flags(B + 2000 + H) == (SAFE | HEARTBEAT | FAULT_FLAG_ARM_REJECTED));

  // The heartbeat alone does not resume output; a disarmed handshake does.
  fmu.beat(); feed(io, {1}, B + 3000 + H);
  assert(l.state() == S::Fault && off(l.output(B + 3000 + H)));
  fmu.beat(); feed(io, {0}, B + 4000 + H);
  assert(l.state() == S::Ready && l.fault_flags(B + 4000 + H) == 0);

  // update() alone ends a Ready session when the heartbeat stops.
  feed(io, {0}, B + 4000 + H + T / 2);
  feed(io, {}, B + 4000 + 2 * H);
  assert(l.state() == S::Safe && (l.fault_flags(B + 4000 + 2 * H) & HEARTBEAT));

  // A heartbeat read without a valid session proves nothing.
  fmu.epoch_ok = false; fmu.beat(); feed(io, {}, B + 5000 + 2 * H);
  assert(!l.peer_alive(B + 5000 + 2 * H));
}
'''
        REPAIR.run(code, cpp=True)

    def test_cr8_1_esc_worker_sends_only_a_fresh_control_loop_snapshot(self):
        """The CM33 worker never holds outputs on for a stalled control loop,
        and a snapshot stamped after the worker read the clock is fresh."""
        owner = BOARDS / 'rdk-rzv2h-io-cr8_1/px4io_cr8_1'
        source = (owner / 'px4io_cr8.cpp').read_text()
        code = EXPANDED.io_prelude(owner) + EXPANDED.output_lease(owner) + r'''
#include <pthread.h>
class Px4IoCr8 {public:
  void publish_esc_command(hrt_abstime now);
  ActuatorCmdToM33_t esc_command(hrt_abstime now);
  OutputLease _lease;
  pthread_mutex_t _esc_cmd_lock = PTHREAD_MUTEX_INITIALIZER;
  ActuatorCmdToM33_t _esc_cmd{}; hrt_abstime _esc_cmd_us{0};};
'''
        for name in ('void Px4IoCr8::publish_esc_command(', 'ActuatorCmdToM33_t Px4IoCr8::esc_command('):
            code += extract(source, name)
        code += r'''
static bool off(const ActuatorCmdToM33_t &o) {
  for (unsigned i = 0; i < IPC_MAX_ACTUATORS; ++i) if (o.commands[i] != 0) return false;
  return o.armed == 0 && o.safety_off == 0;
}
int main() {
  const hrt_abstime T = FMU_LOSS_TIMEOUT_US, N = 1000000;
  Px4IoCr8 io;
  assert(off(io.esc_command(N)));

  ActuatorCommand_t cmd{}; cmd.outputs[0] = 1500; cmd.safety_off = 1;
  io._lease.observe_session(1); io._lease.heartbeat(N); io._lease.accept(cmd, N);
  cmd.armed = 1; io._lease.accept(cmd, N);
  io.publish_esc_command(N);
  ActuatorCmdToM33_t out = io.esc_command(N + T - 1);
  assert(out.armed == 1 && out.commands[0] == 1500 && out.safety_off == 1);

  // Stamped after the worker read the clock: still the newest command.
  assert(io.esc_command(N - 1).armed == 1);

  // The control loop stopped publishing: all outputs off at the lease age.
  assert(off(io.esc_command(N + T)));
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

    def test_poll_does_not_wait_behind_a_blocked_writer(self):
        # The writer keeps priv->lock across its ACK wait.  A poller queued on
        # it cannot consume the peer's frame, so two cores writing at once
        # wait for each other until both writes time out.
        source = (NUTTX / 'arch/arm/src/rzv/rzv_ipc_raw.c').read_text()
        write = extract(source, 'ssize_t rzv_ipc_raw_write(')
        self.assertLess(write.index('nxmutex_lock(&priv->lock)'), write.index('nxsem_tickwait_uninterruptible(&priv->acksem'))
        chardev = (NUTTX / 'arch/arm/src/rzv/rzv_ipc_raw_chardev.c').read_text()
        poll = extract(chardev, 'static int rzv_raw_poll(')
        self.assertIn('nxmutex_lock(&priv->rxlock)', poll)
        self.assertEqual(poll.count('nxmutex_lock('), 1)
        self.assertEqual(poll.count('nxmutex_unlock(&priv->rxlock)'), poll.count('nxmutex_unlock('))
        self.assertNotIn('&priv->lock', poll)

    def test_cr8_0_bridge_runs_in_the_actuator_output_band(self):
        # The bridge refreshes a 50 ms CR8-1 lease: a default-priority task
        # (an NSH command, a log dump) must not be able to preempt it.
        source = (BOARDS / 'rdk-rzv2h/px4io_cr8_0/px4io_bridge.cpp').read_text()
        spawn = extract(source, 'int Px4IoBridge::task_spawn(')
        self.assertRegex(spawn, r'px4_task_spawn_cmd\("px4io_bridge",\s*SCHED_DEFAULT,\s*'
                                r'SCHED_PRIORITY_ACTUATOR_OUTPUTS,')

    def test_dual_cr8_selects_the_supervised_producer_instead_of_the_legacy_bridge(self):
        board = BOARDS / 'rdk-rzv2h'
        kconfig = (board / 'Kconfig').read_text()
        entry = kconfig[kconfig.index('config BOARD_RDK_RZV2H_PX4IO_BRIDGE'):]
        entry = entry[:entry.index('\nconfig ') if '\nconfig ' in entry else len(entry)]
        self.assertRegex(entry, r'default n\b')
        # Heartbeat-only profiles own the CR8 link for rzv2h_heartbeat liveness
        # and ping/say text; they must carry no output producer of any kind.
        board_cmake = (board / 'src/CMakeLists.txt').read_text()
        heartbeat_only = set(re.findall(
            r'if\(PX4_BOARD_LABEL STREQUAL "(\w+)"\)(?:(?!\nendif\(\)).)*?add_subdirectory\([^)]*ipc_heartbeat',
            board_cmake, re.S))
        self.assertEqual(heartbeat_only, {'demo', 'demosih'})
        bridged = []
        for profile in sorted(board.glob('*.px4board')):
            label = profile.stem
            config = board / 'nuttx-config' / label / 'defconfig'
            nuttx = (config if config.exists() else board / 'nuttx-config/nsh/defconfig').read_text()
            has_bridge = re.search(r'(?m)^CONFIG_BOARD_RDK_RZV2H_PX4IO_BRIDGE=y', profile.read_text()) is not None
            has_link = re.search(r'(?m)^CONFIG_RZV_IPC_CR8_CR8=y', nuttx) is not None
            remote = 'CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS=y' in profile.read_text()
            if label in heartbeat_only:
                self.assertTrue(has_link, label)
                self.assertFalse(remote, label)
            else:
                self.assertEqual(remote, has_link, label)
            self.assertFalse(has_bridge, label)
            if has_bridge:
                bridged.append(label)
                for line in ('CONFIG_RZV_IPC_RAW=y', 'CONFIG_RZV_IPC_ROLE_INITIATOR=y'):
                    self.assertRegex(nuttx, rf'(?m)^{line}$', label)
                wait = re.search(r'(?m)^CONFIG_RZV_IPC_RECOVERY_WAIT_MS=(\d+)$', nuttx)
                self.assertTrue(wait and int(wait.group(1)) <= 100, label)
                self.assertNotRegex(nuttx, r'(?m)^CONFIG_RZV_(OPENAMP|IPC_CR8_CR8_LOOPBACK)=y', label)
        self.assertEqual(bridged, [])
        self.assertIn('CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS=y', (board / 'dualcr8.px4board').read_text())

    def test_profiles_only_set_board_options_kconfig_can_apply(self):
        # Options inside 'if BOARD_RDK_RZV2H' are forced off unless a profile
        # selects the board symbol; setting them otherwise is silently ignored.
        board = BOARDS / 'rdk-rzv2h'
        kconfig = (board / 'Kconfig').read_text()
        guarded = kconfig[kconfig.index('if BOARD_RDK_RZV2H\n'):kconfig.index('endif # BOARD_RDK_RZV2H')]
        hidden = set(re.findall(r'(?m)^config (\w+)', guarded))
        self.assertIn('BOARD_RDK_RZV2H_HAS_IMU', hidden)
        self.assertNotIn('BOARD_RDK_RZV2H_PX4IO_BRIDGE', hidden)
        for profile in sorted(board.glob('*.px4board')):
            text = profile.read_text()
            if re.search(r'(?m)^CONFIG_BOARD_RDK_RZV2H=y$', text):
                continue
            for option in hidden:
                self.assertNotRegex(text, rf'(?m)^CONFIG_{option}=', profile.stem)
        bridge = (board / 'px4io_cr8_0/uorb_bridge.cpp').read_text()
        self.assertRegex(bridge, r'#if !defined\(CONFIG_RZV_IPC_RAW\) \|\| '
                                 r'!defined\(CONFIG_RZV_IPC_ROLE_INITIATOR\)\n#\s*error')
        self.assertRegex(bridge, r'CONFIG_RZV_IPC_RECOVERY_WAIT_MS > 100\n#\s*error')

    def test_px4_kconfig_resolves_remote_ownership_without_the_legacy_bridge(self):
        # A board option that PX4 Kconfig never parses is silently dropped.
        probe = r"""
import os, sys, kconfiglib
board = 'boards/renesas/rdk-rzv2h/'
for model, label in [(m, l) for m, l in (a.split(':') for a in sys.argv[1:])]:
    os.environ.update(VENDOR='renesas', MODEL=model, LABEL=label, PLATFORM='nuttx')
    k = kconfiglib.Kconfig('Kconfig', warn=False)
    if model == 'rdk-rzv2h':
        k.load_config(board + 'default.px4board')
        k.load_config(board + label + '.px4board', replace=False)
    print(model, label, k.syms['BOARD_RDK_RZV2H_PX4IO_BRIDGE'].str_value + k.syms['BOARD_RDK_RZV2H_REMOTE_OUTPUTS'].str_value)
"""
        labels = sorted(p.stem for p in (BOARDS / 'rdk-rzv2h').glob('*.px4board'))
        args = ['rdk-rzv2h:' + label for label in labels] + ['rdk-rzv2h-io-cr8_1:default']
        result = subprocess.run(['python3', '-c', probe] + args, cwd=ROOT, capture_output=True, text=True)
        if 'No module named' in result.stderr:
            self.skipTest('kconfiglib is not installed')
        self.assertEqual(result.returncode, 0, result.stderr)
        resolved = dict((' '.join(line.split()[:2]), line.split()[2]) for line in result.stdout.splitlines())
        expected = {f'rdk-rzv2h {label}': 'ny' if label == 'dualcr8' else 'nn' for label in labels}
        expected['rdk-rzv2h-io-cr8_1 default'] = 'nn'
        self.assertEqual(resolved, expected)

    def test_dual_cr8_registers_link_and_legacy_startup_remains_guarded(self):
        board = BOARDS / 'rdk-rzv2h'
        cmake = (board / 'src/CMakeLists.txt').read_text()
        self.assertRegex(cmake, r'if\(CONFIG_RZV_IPC_RAW\)\n\tlist\(APPEND drivers_board_sources\n'
                                r'\t\t\S+/rdk-rzv2h/src/rzv2h_ipc\.c\n')
        init = (board / 'src/init.c').read_text()
        self.assertRegex(init, r'#ifdef CONFIG_RZV_IPC_RAW\n(?:[/ ]\*.*\n)*#  ifdef CONFIG_RZV_OPENAMP\n#    error')
        app = extract(init, '__EXPORT int board_app_initialize(')
        raw = app[app.index('#if defined(CONFIG_RZV_IPC_RAW)'):]
        self.assertIn('ret = board_ipc_initialize();', raw[:raw.index('#endif')])
        self.assertIn('CONFIG_BOARD_INIT_SUBDIR="dualcr8"', (board / 'dualcr8.px4board').read_text())

        script = board / 'init/drone/rc.board_extras'
        for line in script.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                self.assertIn(line.split()[0], ('if', 'then', 'else', 'fi', 'echo'))
        host = """
[() { [[ "$*" == "-e /dev/ipcc1 ]" && $IPCC1 == yes ]]; }
px4io_bridge() { echo "CALL px4io_bridge $*"; [[ $FAIL != yes ]]; }
"""
        for ipcc1, fail, expected in (('no', 'no', None), ('yes', 'no', 'px4io_bridge started'),
                                      ('yes', 'yes', 'ERROR [init] px4io_bridge failed')):
            result = subprocess.run(['bash', '-c', host + '\n. "$1"', 'host', str(script)], capture_output=True,
                                    text=True, env={'IPCC1': ipcc1, 'FAIL': fail, 'PATH': '/usr/bin:/bin'})
            self.assertEqual(result.returncode, 0, result.stderr)
            if expected is None:
                self.assertEqual(result.stdout, '')
            else:
                self.assertIn('CALL px4io_bridge start\n', result.stdout)
                self.assertIn(expected, result.stdout)

    def test_every_core_shares_the_lease_and_safe_fault_contract(self):
        names = ('FMU_LOSS_TIMEOUT_US', 'FAULT_FLAG_CR8_TIMEOUT', 'FAULT_FLAG_OUTPUT_SAFE_FAULT',
                 'FAULT_FLAG_PEER_SESSION', 'FAULT_FLAG_ARM_REJECTED', 'FAULT_FLAG_FMU_HEARTBEAT')
        texts = [path.read_text() for path in PROTOCOLS]
        for name in names:
            values = {re.search(rf'#define {name}\s+(\S+)', text).group(1) for text in texts}
            self.assertEqual(len(values), 1, (name, values))
        self.assertEqual(re.search(r'#define FMU_LOSS_TIMEOUT_US\s+(\d+)', texts[0]).group(1), '50000')
        flags = [int(re.search(rf'#define {name}\s+\(1 << (\d+)\)', texts[0]).group(1)) for name in names[1:]]
        self.assertEqual(len(set(flags)), len(flags))


if __name__ == '__main__':
    unittest.main()
