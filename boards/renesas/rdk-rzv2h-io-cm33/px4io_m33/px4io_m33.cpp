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
	SharedMemTransport _transport;
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
	return new Px4IoM33();
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
)DESCR_STR");

	PRINT_MODULE_USAGE_NAME("px4io_m33", "driver");
	PRINT_MODULE_USAGE_COMMAND("start");
	PRINT_MODULE_USAGE_DEFAULT_COMMANDS();

	return 0;
}

void Px4IoM33::run()
{
	PX4_INFO("PX4IO M33 starting");

	// Initialize transport as Slave (M33)
	_transport.init(false);

	ActuatorCmdToM33_t cmd{};
	PWMFeedback_t feedback{};
	FaultStatus_t fault{};

	while (!should_exit()) {
		// 1. Check for Commands
		while (_transport.receive_actuator_cmd(cmd)) {
			// Apply to PWM hardware (TODO)
			// PX4_INFO("Got cmd: %d", cmd.commands[0]);

			// Prepare feedback based on command
			feedback.header.timestamp_us = hrt_absolute_time();
			for (int i = 0; i < 8; i++) {
				feedback.current_outputs[i] = cmd.commands[i];
			}

			// Send Feedback
			_transport.send_pwm_feedback(feedback);
		}

		// 2. Send Fault Status (Periodic)
		static uint64_t last_fault_time = 0;
		uint64_t now = hrt_absolute_time();
		if (now - last_fault_time > 100000) { // 10Hz
			fault.header.timestamp_us = now;
			fault.watchdog_count = 0;
			fault.error_flags = 0;
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
