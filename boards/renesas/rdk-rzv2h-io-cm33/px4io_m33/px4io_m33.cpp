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
#include <errno.h>

#include "sharedmem_transport.h"
#include "board_config.h"

extern "C" __EXPORT int px4io_m33_main(int argc, char *argv[]);

class Px4IoM33 : public ModuleBase<Px4IoM33>
{
public:
	Px4IoM33() : _transport("/dev/ipcc3") {}
	virtual ~Px4IoM33() = default;

	static int task_spawn(int argc, char *argv[]);
	static Px4IoM33 *instantiate(int argc, char *argv[]);
	static int custom_command(int argc, char *argv[]);
	static int print_usage(const char *reason = nullptr);

	void run() override;

private:
	static bool command_valid(const ActuatorCmdToM33_t &cmd);
	bool update_outputs(hrt_abstime now);

	SharedMemTransport _transport;

	ActuatorCmdToM33_t _cmd{};		// latest valid CR8-1 command
	hrt_abstime _last_cmd_us{0};		// local receive time of _cmd

	/* Output state a PWM backend must drive.  No CM33 PWM backend exists yet,
	 * so these values are only reported in feedback and fault status.
	 */
	uint16_t _outputs[IPC_MAX_ACTUATORS] {};
	bool _armed{false};
	bool _command_timeout{true};
};

int Px4IoM33::task_spawn(int argc, char *argv[])
{
	_task_id = px4_task_spawn_cmd("px4io_m33",
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

Px4IoM33 *Px4IoM33::instantiate(int argc, char *argv[])
{
	Px4IoM33 *instance = new Px4IoM33();

	if (instance == nullptr) {
		return nullptr;
	}

	if (!instance->_transport.init(false)) {
		PX4_ERR("transport initialization failed");
		delete instance;
		return nullptr;
	}

	return instance;
}

int Px4IoM33::custom_command(int argc, char *argv[])
{
	return print_usage("unknown command");
}

int Px4IoM33::print_usage(const char *reason)
{
	if (reason) {
		PX4_WARN("%s\n", reason);
	}

	PRINT_MODULE_DESCRIPTION(
		R"DESCR_STR(
### Description
PX4IO driver for RZV2H CM33.

Applies PWM actuator commands relayed by CR8-1 over /dev/ipcc3. Each fresh
channel is held as commanded; invalid frames are ignored. When no valid command
arrives for 100 ms, all outputs stop (0) and the CR8 timeout fault is reported.
No PWM backend drives pins yet; the applied values are reported as feedback.
)DESCR_STR");

	PRINT_MODULE_USAGE_NAME("px4io_m33", "driver");
	PRINT_MODULE_USAGE_COMMAND("start");
	PRINT_MODULE_USAGE_DEFAULT_COMMANDS();

	return 0;
}

bool Px4IoM33::command_valid(const ActuatorCmdToM33_t &cmd)
{
	/* PWM-only contract: 0 keeps an output off, anything else is a pulse
	 * width within the range PX4IO accepts.
	 */
	if (cmd.armed > 1 || cmd.safety_off > 1 || cmd.output_mode != 0) {
		return false;
	}

	for (unsigned i = 0; i < IPC_MAX_ACTUATORS; i++) {
		const uint16_t command = cmd.commands[i];

		if (command != 0 && (command < PWM_LOWEST_MIN || command > PWM_HIGHEST_MAX)) {
			return false;
		}
	}

	return true;
}

bool Px4IoM33::update_outputs(hrt_abstime now)
{
	ActuatorCmdToM33_t cmd{};
	bool applied = false;

	/* Bounded drain: keep only the newest valid command. */
	for (int budget = 2 * IPC_BUFFER_SIZE; budget > 0 && _transport.receive_actuator_cmd(cmd); budget--) {
		if (command_valid(cmd)) {
			_cmd = cmd;
			_last_cmd_us = now;
			applied = true;
		}
	}

	/* Hold each channel as commanded while commands stay fresh, so a disarmed
	 * FMU keeps its disarmed values.  Without a valid command for 100 ms there
	 * is no failsafe table to fall back to, so every output stops.
	 */
	_command_timeout = _last_cmd_us == 0 || now - _last_cmd_us >= FMU_LOSS_TIMEOUT_US;

	for (unsigned i = 0; i < IPC_MAX_ACTUATORS; i++) {
		_outputs[i] = _command_timeout ? 0 : _cmd.commands[i];
	}

	_armed = !_command_timeout && _cmd.armed;
	return applied;
}

void Px4IoM33::run()
{
	PX4_INFO("PX4IO M33 starting");

	PWMFeedback_t feedback{};
	FaultStatus_t fault{};
	hrt_abstime last_fault_time = 0;

	while (!should_exit()) {
		const hrt_abstime now = hrt_absolute_time();

		if (update_outputs(now)) {
			for (unsigned i = 0; i < IPC_MAX_ACTUATORS; i++) {
				feedback.current_outputs[i] = _outputs[i];
			}

			_transport.send_pwm_feedback(feedback);
		}

		if (now - last_fault_time > 100000) { // 10Hz
			fault.watchdog_count = 0;
			fault.error_flags = _command_timeout ? FAULT_FLAG_CR8_TIMEOUT : 0;
			fault.armed_state = _armed;
			_transport.send_fault_status(fault);
			last_fault_time = now;
		}

		// Run at high rate for low latency
		px4_usleep(500);
	}
}

int px4io_m33_main(int argc, char *argv[])
{
	return Px4IoM33::main(argc, argv);
}
