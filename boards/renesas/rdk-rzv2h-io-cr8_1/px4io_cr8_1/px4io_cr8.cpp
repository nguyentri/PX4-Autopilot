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

#include "sharedmem_transport.h"
#include "board_config.h"
#include <errno.h>

extern "C" __EXPORT int px4io_cr8_main(int argc, char *argv[]);

class Px4IoCr8 : public ModuleBase<Px4IoCr8>
{
public:
	Px4IoCr8() : _transport("/dev/ipcc3") {}
	virtual ~Px4IoCr8() = default;

	static int task_spawn(int argc, char *argv[]);
	static Px4IoCr8 *instantiate(int argc, char *argv[]);
	static int custom_command(int argc, char *argv[]);
	static int print_usage(const char *reason = nullptr);

	void run() override;

private:
	SharedMemTransport _transport;
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
	return new Px4IoCr8();
}

int Px4IoCr8::custom_command(int argc, char *argv[])
{
	return print_usage("unknown command");
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
)DESCR_STR");

	PRINT_MODULE_USAGE_NAME("px4io_cr8", "driver");
	PRINT_MODULE_USAGE_COMMAND("start");
	PRINT_MODULE_USAGE_DEFAULT_COMMANDS();

	return 0;
}

void Px4IoCr8::run()
{
	PX4_INFO("PX4IO CR8 starting");

	// Initialize transport as Master (CR8)
	_transport.init(true);

	ActuatorCmdToM33_t cmd{};
	PWMFeedback_t feedback{};
	FaultStatus_t fault{};

	while (!should_exit()) {
		// 1. Prepare Actuator Command (Dummy for now)
		cmd.header.timestamp_us = hrt_absolute_time();
		cmd.armed = 1;
		for (int i = 0; i < 8; i++) {
			cmd.commands[i] = 1000 + (i * 100); // Dummy ramp
		}

		// 2. Send Command
		if (!_transport.send_actuator_cmd(cmd)) {
			// Buffer full?
		}

		// 3. Check for Feedback
		while (_transport.receive_pwm_feedback(feedback)) {
			// Process feedback
			// PX4_INFO("Got feedback: %d", feedback.current_outputs[0]);
		}

		// 4. Check for Faults
		while (_transport.receive_fault_status(fault)) {
			PX4_WARN("Got fault status: 0x%lx", (unsigned long)fault.error_flags);
		}

		// Run at 400Hz
		px4_usleep(2500);
	}
}

int px4io_cr8_main(int argc, char *argv[])
{
	return Px4IoCr8::main(argc, argv);
}
