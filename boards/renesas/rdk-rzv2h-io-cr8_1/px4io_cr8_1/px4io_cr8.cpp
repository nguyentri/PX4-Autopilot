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
#include <px4_platform_common/tasks.h>
#include <px4_platform_common/module.h>
#include <px4_platform_common/getopt.h>
#include <drivers/drv_hrt.h>
#include <drivers/drv_pwm_output.h>

#include "sharedmem_transport.h"
#include "board_config.h"
#include <errno.h>

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

	static bool fmu_command_valid(const ActuatorCommand_t &cmd);
	void receive_fmu_commands(hrt_abstime now);
	bool fmu_command_fresh(hrt_abstime now) const;
	ActuatorCmdToM33_t esc_command(hrt_abstime now) const;
	void receive_esc_status(hrt_abstime now);
	FaultStatus_t fault_status(hrt_abstime now) const;
	void report_to_fmu(hrt_abstime now);

	SharedMemTransport _fmu_transport;	// CR8-0 FMU leg, CR8-1 is the responder
	SharedMemTransport _esc_transport;	// optional CM33 ESC leg, CR8-1 is the initiator
	bool _esc_enabled{false};		// CM33 leg opened at startup

	ActuatorCommand_t _fmu_cmd{};		// latest valid FMU command
	hrt_abstime _last_fmu_cmd_us{0};	// local receive time of _fmu_cmd

	uint32_t _esc_fault_flags{0};		// latest CM33 fault flags
	hrt_abstime _last_esc_fault_us{0};	// local receive time of _esc_fault_flags

	hrt_abstime _last_report_us{0};
	uint32_t _loop_count{0};
	uint32_t _report_count{0};		// heartbeats written to the FMU ring
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
	const hrt_abstime now = hrt_absolute_time();
	const FaultStatus_t fault = fault_status(now);

	PX4_INFO("FMU commands: %s", fmu_command_fresh(now) ? "fresh" : "timed out");
	PX4_INFO("ESC relay: %s", _esc_enabled ? "enabled" : "disabled");
	PX4_INFO("Fault flags: 0x%lx, armed: %u", (unsigned long)fault.error_flags, fault.armed_state);
	PX4_INFO("Reports sent: %lu", (unsigned long)_report_count);

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
(/dev/ipcc3). Each fresh channel is forwarded as commanded, so a disarmed FMU
holds its disarmed values. Invalid frames are ignored. When no valid command
arrives for 100 ms, all outputs are commanded off (0) and disarmed.

The CM33 leg is optional. At 10 Hz this core sends CR8-0 a heartbeat and a
fault status that flags an expired FMU command lease, plus the CM33 fault
flags while the CM33 reports them.
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

	/* Bounded drain: keep only the newest valid command so a backlog never
	 * replays stale outputs, and never starve the ESC leg.
	 */
	for (int budget = 2 * IPC_BUFFER_SIZE; budget > 0 && _fmu_transport.receive_actuator_command(cmd); budget--) {
		if (fmu_command_valid(cmd)) {
			_fmu_cmd = cmd;
			_last_fmu_cmd_us = now;
		}
	}
}

bool Px4IoCr8::fmu_command_fresh(hrt_abstime now) const
{
	/* Local receive time, because the cores do not share a timebase. */
	return _last_fmu_cmd_us != 0 && now - _last_fmu_cmd_us < FMU_LOSS_TIMEOUT_US;
}

ActuatorCmdToM33_t Px4IoCr8::esc_command(hrt_abstime now) const
{
	/* Default: every output off, disarmed, PWM mode. */
	ActuatorCmdToM33_t cmd{};

	/* The FMU mixer already selected armed, disarmed or failsafe values, so a
	 * fresh command is forwarded channel for channel, as PX4IO does while the
	 * FMU is alive.
	 */
	if (fmu_command_fresh(now)) {
		for (unsigned i = 0; i < IPC_MAX_ACTUATORS; i++) {
			cmd.commands[i] = _fmu_cmd.outputs[i];
		}

		cmd.armed = _fmu_cmd.armed;
		cmd.safety_off = _fmu_cmd.safety_off;
	}

	return cmd;
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

	/* This core's own view: the FMU command lease expired, so every output
	 * is commanded off.
	 */
	if (!fmu_command_fresh(now)) {
		fault.error_flags |= FAULT_FLAG_CR8_TIMEOUT;
	}

	/* CM33 flags count only while the CM33 keeps reporting them (10 Hz); a
	 * silent CM33 must not leave a stale fault latched on the FMU.
	 */
	if (_last_esc_fault_us != 0 && now - _last_esc_fault_us < HEARTBEAT_TIMEOUT_US) {
		fault.error_flags |= _esc_fault_flags;
	}

	fault.armed_state = esc_command(now).armed;
	return fault;
}

void Px4IoCr8::report_to_fmu(hrt_abstime now)
{
	if (_last_report_us != 0 && now - _last_report_us < REPORT_INTERVAL_US) {
		return;
	}

	Heartbeat_t heartbeat{};
	heartbeat.source_core = CORE_ID_CR8_1;
	heartbeat.state = 1; // Running
	heartbeat.uptime_ms = now / 1000;
	heartbeat.loop_count = _loop_count;

	/* Writes never block; a full ring drops this report and the next one
	 * follows 100 ms later.
	 */
	if (_fmu_transport.send_heartbeat(heartbeat)) {
		_report_count++;
	}

	_fmu_transport.send_fault_status(fault_status(now));
	_last_report_us = now;
}

void Px4IoCr8::run()
{
	PX4_INFO("PX4IO CR8 starting");

	while (!should_exit()) {
		const hrt_abstime now = hrt_absolute_time();

		receive_fmu_commands(now);

		if (_esc_enabled) {
			/* Sent every cycle so the CM33 timeout only fires when this core
			 * or the link stops.  A full ring drops this cycle; the next one
			 * resends.
			 */
			_esc_transport.send_actuator_cmd(esc_command(now));
			receive_esc_status(now);
		}

		report_to_fmu(now);
		_loop_count++;

		// Run at 400Hz
		px4_usleep(2500);
	}
}

int px4io_cr8_main(int argc, char *argv[])
{
	return Px4IoCr8::main(argc, argv);
}
