/****************************************************************************
 *
 *   Copyright (c) 2026 PX4 Development Team. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in
 *    the documentation and/or other materials provided with the
 *    distribution.
 * 3. Neither the name PX4 nor the names of its contributors may be
 *    used to endorse or promote products derived from this software
 *    without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 * FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
 * BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
 * OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
 * AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 * ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 *
 ****************************************************************************/

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/atomic.h>
#include <px4_platform_common/tasks.h>
#include <px4_platform_common/module.h>
#include <px4_platform_common/posix.h>
#include <px4_platform_common/getopt.h>
#include <drivers/drv_hrt.h>
#include <drivers/drv_pwm_output.h>

#include "output-lease.h"
#include "sharedmem_transport.h"
#include "board_config.h"
#include <errno.h>
#include <pthread.h>

extern "C" __EXPORT int px4io_cr8_main(int argc, char *argv[]);

class Px4IoCr8 : public ModuleBase<Px4IoCr8>
{
public:
	Px4IoCr8() : _fmu_transport("/dev/ipcc1"), _esc_transport("/dev/ipcc3") {}
	virtual ~Px4IoCr8() = default;

	static int task_spawn(int argc, char *argv[]);
	static Px4IoCr8 *instantiate(int argc, char *argv[]);
	static int custom_command(int argc, char *argv[]);
	static int print_usage(const char *reason = nullptr);

	void run() override;
	int print_status() override;

private:
	static constexpr hrt_abstime REPORT_INTERVAL_US = 100000;	// 10 Hz
	static constexpr hrt_abstime REPORTER_POLL_US = 10000;
	static constexpr int REPORTER_PRIORITY = SCHED_PRIORITY_DEFAULT - 10;
	static constexpr size_t REPORTER_STACK_SIZE = 2048;

	static bool fmu_command_valid(const ActuatorCommand_t &cmd);
	void receive_fmu_commands(hrt_abstime now);
	void receive_esc_status(hrt_abstime now);
	FaultStatus_t fault_status(hrt_abstime now) const;
	void publish_report_state(hrt_abstime now);

	static void *reporter_trampoline(void *arg);
	bool start_reporter();
	void report_to_fmu(hrt_abstime now);

	SharedMemTransport _fmu_transport;	// CR8-0 FMU leg, CR8-1 is the responder
	SharedMemTransport _esc_transport;	// optional CM33 ESC leg, CR8-1 is the initiator
	bool _esc_enabled{false};		// CM33 leg opened at startup

	/* Control loop only. */
	OutputLease _lease;			// output safety state for CR8-0 commands
	uint32_t _esc_fault_flags{0};		// latest CM33 fault flags
	hrt_abstime _last_esc_fault_us{0};	// local receive time of _esc_fault_flags
	uint32_t _loop_count{0};

	/* Published by the control loop, read by the reporter and status. */
	px4::atomic<uint32_t> _report_fault_flags{FAULT_FLAG_CR8_TIMEOUT};
	px4::atomic<uint32_t> _report_armed{0};
	px4::atomic<uint32_t> _report_state{static_cast<uint32_t>(OutputLease::State::Safe)};
	px4::atomic<uint32_t> _report_loop_count{0};

	/* Reporter thread only, except _report_count which status reads. */
	pthread_t _reporter{};
	hrt_abstime _last_report_us{0};
	px4::atomic<uint32_t> _report_count{0};	// heartbeats written to the FMU ring
};

int Px4IoCr8::task_spawn(int argc, char *argv[])
{
	_task_id = px4_task_spawn_cmd("px4io_cr8",
				      SCHED_DEFAULT,
				      SCHED_PRIORITY_DEFAULT,
				      2048,
				      (px4_main_t)&run_trampoline,
				      (char *const *)argv);

	if (_task_id < 0) {
		_task_id = -1;
		return -errno;
	}

	return PX4_OK;
}

Px4IoCr8 *Px4IoCr8::instantiate(int argc, char *argv[])
{
	Px4IoCr8 *instance = new Px4IoCr8();

	if (instance == nullptr) {
		return nullptr;
	}

	if (!instance->_fmu_transport.init(false)) {
		PX4_ERR("FMU transport initialization failed");
		delete instance;
		return nullptr;
	}

	/* The CM33 has no output backend and is optional: without it the FMU
	 * leg still validates commands and reports status to CR8-0.
	 */
	instance->_esc_enabled = instance->_esc_transport.init(true);

	if (!instance->_esc_enabled) {
		PX4_WARN("CM33 transport unavailable, ESC relay disabled");
	}

	return instance;
}

int Px4IoCr8::custom_command(int argc, char *argv[])
{
	return print_usage("unknown command");
}

int Px4IoCr8::print_status()
{
	static const char *const state_names[] = {"safe", "ready", "armed", "safe fault"};
	const uint32_t state = _report_state.load();

	PX4_INFO("Output state: %s", state < 4 ? state_names[state] : "?");
	PX4_INFO("ESC relay: %s", _esc_enabled ? "enabled" : "disabled");
	PX4_INFO("Fault flags: 0x%lx, armed: %lu", (unsigned long)_report_fault_flags.load(),
		 (unsigned long)_report_armed.load());
	PX4_INFO("Loops: %lu, reports sent: %lu", (unsigned long)_report_loop_count.load(),
		 (unsigned long)_report_count.load());

	return 0;
}

int Px4IoCr8::print_usage(const char *reason)
{
	if (reason) {
		PX4_WARN("%s\n", reason);
	}

	PRINT_MODULE_DESCRIPTION(
		R"DESCR_STR(
### Description
PX4IO driver for RZV2H CR8 Core 1.

Relays PWM actuator commands from the CR8-0 FMU (/dev/ipcc1) to the CM33
(/dev/ipcc3). Outputs start safe. A fresh disarmed command in the current
CR8-0 link session enables disarmed values; only then may an armed command
enable armed values. Each command is a 50 ms lease. Lease expiry or a CR8-0
link epoch change while armed latches a safe fault: outputs stay off and
disarmed until CR8-0 sends a disarmed command again. Invalid frames are
ignored.

The CM33 leg is optional. A lower-priority thread sends CR8-0 a heartbeat and
a fault status at 10 Hz, so a slow CR8-0 reader never stalls the output loop.
)DESCR_STR");

	PRINT_MODULE_USAGE_NAME("px4io_cr8", "driver");
	PRINT_MODULE_USAGE_COMMAND("start");
	PRINT_MODULE_USAGE_DEFAULT_COMMANDS();

	return 0;
}

bool Px4IoCr8::fmu_command_valid(const ActuatorCommand_t &cmd)
{
	if (cmd.armed > 1 || cmd.safety_off > 1) {
		return false;
	}

	/* PWM-only contract: 0 keeps an output off, anything else is a pulse
	 * width the CR8-0 bridge has already bounded.
	 */
	for (unsigned i = 0; i < IPC_MAX_ACTUATORS; i++) {
		const uint16_t output = cmd.outputs[i];

		if (output != 0 && (output < PWM_LOWEST_MIN || output > PWM_HIGHEST_MAX)) {
			return false;
		}
	}

	return true;
}

void Px4IoCr8::receive_fmu_commands(hrt_abstime now)
{
	ActuatorCommand_t cmd{};

	/* Bounded drain, in order, so the newest valid command wins and a backlog
	 * never starves the ESC leg.  A read may adopt a new CR8-0 link epoch, so
	 * the session is checked after every read, before its command is used.
	 */
	for (int budget = 2 * IPC_BUFFER_SIZE; budget > 0; budget--) {
		const bool received = _fmu_transport.receive_actuator_command(cmd);
		uint32_t epoch = 0;

		if (!_fmu_transport.link_epoch(epoch)) {
			epoch = 0;
		}

		_lease.observe_session(epoch);

		if (!received) {
			break;
		}

		if (fmu_command_valid(cmd)) {
			_lease.accept(cmd, now);
		}
	}

	_lease.update(now);
}

void Px4IoCr8::receive_esc_status(hrt_abstime now)
{
	PWMFeedback_t feedback{};
	FaultStatus_t fault{};

	while (_esc_transport.receive_pwm_feedback(feedback)) {
		/* Feedback is not consumed yet. */
	}

	while (_esc_transport.receive_fault_status(fault)) {
		if (fault.error_flags != _esc_fault_flags) {
			PX4_WARN("CM33 fault flags: 0x%lx", (unsigned long)fault.error_flags);
		}

		_esc_fault_flags = fault.error_flags;
		_last_esc_fault_us = now;
	}
}

FaultStatus_t Px4IoCr8::fault_status(hrt_abstime now) const
{
	FaultStatus_t fault{};

	/* This core's own output state: lease, latched safe fault, rejected arm. */
	fault.error_flags = _lease.fault_flags(now);

	/* CM33 flags count only while the CM33 keeps reporting them (10 Hz); a
	 * silent CM33 must not leave a stale fault latched on the FMU.
	 */
	if (_last_esc_fault_us != 0 && now - _last_esc_fault_us < HEARTBEAT_TIMEOUT_US) {
		fault.error_flags |= _esc_fault_flags;
	}

	fault.armed_state = _lease.output(now).armed;
	return fault;
}

void Px4IoCr8::publish_report_state(hrt_abstime now)
{
	const FaultStatus_t fault = fault_status(now);

	_report_fault_flags.store(fault.error_flags);
	_report_armed.store(fault.armed_state);
	_report_state.store(static_cast<uint32_t>(_lease.state()));
	_report_loop_count.store(_loop_count);
}

void Px4IoCr8::report_to_fmu(hrt_abstime now)
{
	if (_last_report_us != 0 && now - _last_report_us < REPORT_INTERVAL_US) {
		return;
	}

	/* Only the atomics the control loop publishes are read here; a stalled
	 * control loop shows as a frozen loop_count.
	 */
	Heartbeat_t heartbeat{};
	heartbeat.source_core = CORE_ID_CR8_1;
	heartbeat.state = 1; // Running
	heartbeat.uptime_ms = now / 1000;
	heartbeat.loop_count = _report_loop_count.load();

	FaultStatus_t fault{};
	fault.error_flags = _report_fault_flags.load();
	fault.armed_state = static_cast<uint8_t>(_report_armed.load());

	/* A write may wait for the CR8-0 ACK; that blocks only this thread.  A
	 * failed write drops this report and the next one follows 100 ms later.
	 */
	if (_fmu_transport.send_heartbeat(heartbeat)) {
		_report_count.fetch_add(1);
	}

	_fmu_transport.send_fault_status(fault);
	_last_report_us = now;
}

void *Px4IoCr8::reporter_trampoline(void *arg)
{
	Px4IoCr8 *self = static_cast<Px4IoCr8 *>(arg);

	while (!self->should_exit()) {
		self->report_to_fmu(hrt_absolute_time());
		px4_usleep(REPORTER_POLL_US);
	}

	return nullptr;
}

bool Px4IoCr8::start_reporter()
{
	pthread_attr_t attr;
	pthread_attr_init(&attr);
	pthread_attr_setstacksize(&attr, PX4_STACK_ADJUSTED(REPORTER_STACK_SIZE));

	struct sched_param param;
	pthread_attr_getschedparam(&attr, &param);
	param.sched_priority = REPORTER_PRIORITY;
	pthread_attr_setschedparam(&attr, &param);

	const int ret = pthread_create(&_reporter, &attr, &Px4IoCr8::reporter_trampoline, this);
	pthread_attr_destroy(&attr);

	if (ret != 0) {
		PX4_ERR("reporter thread start failed (%d)", ret);
		return false;
	}

	return true;
}

void Px4IoCr8::run()
{
	PX4_INFO("PX4IO CR8 starting");

	/* Without the reporter CR8-0 would see a silent I/O core, so the relay
	 * does not run without it.
	 */
	if (!start_reporter()) {
		return;
	}

	while (!should_exit()) {
		const hrt_abstime now = hrt_absolute_time();

		receive_fmu_commands(now);

		if (_esc_enabled) {
			/* Sent every cycle so the CM33 timeout only fires when this core
			 * or the link stops.  A failed write drops this cycle; the next
			 * one resends.
			 */
			_esc_transport.send_actuator_cmd(_lease.output(now));
			receive_esc_status(now);
		}

		_loop_count++;
		publish_report_state(now);

		// Run at 400Hz
		px4_usleep(2500);
	}

	pthread_join(_reporter, nullptr);
}

int px4io_cr8_main(int argc, char *argv[])
{
	return Px4IoCr8::main(argc, argv);
}
