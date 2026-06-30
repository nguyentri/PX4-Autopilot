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

/**
 * @file px4io_bridge.cpp
 *
 * PX4IO Bridge Module for CR8-0 (FMU)
 *
 * This PX4 module runs on CR8-0 and bridges uORB topics to the CR8-1 I/O
 * processor via shared memory IPC.
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/tasks.h>
#include <px4_platform_common/module.h>
#include <px4_platform_common/module_params.h>
#include <px4_platform_common/getopt.h>
#include <drivers/drv_hrt.h>
#include <perf/perf_counter.h>
#include <errno.h>

#include "uorb_bridge.h"
#include "board_config.h"

extern "C" __EXPORT int px4io_bridge_main(int argc, char *argv[]);

/**
 * @brief PX4IO Bridge Module
 *
 * Runs as a high-priority work queue task on CR8-0 to bridge
 * uORB topics to/from CR8-1 I/O processor.
 */
class Px4IoBridge : public ModuleBase<Px4IoBridge>, public ModuleParams
{
public:
	Px4IoBridge();
	virtual ~Px4IoBridge();

	/** @see ModuleBase */
	static int task_spawn(int argc, char *argv[]);

	/** @see ModuleBase */
	static Px4IoBridge *instantiate(int argc, char *argv[]);

	/** @see ModuleBase */
	static int custom_command(int argc, char *argv[]);

	/** @see ModuleBase */
	static int print_usage(const char *reason = nullptr);

	/** @see ModuleBase::run() */
	void run() override;

	/** @see ModuleBase::print_status() */
	int print_status() override;

private:
	UorbBridgeCR8 _bridge;

	perf_counter_t _loop_perf;
	perf_counter_t _loop_interval_perf;
};

Px4IoBridge::Px4IoBridge()
	: ModuleParams(nullptr),
	  _bridge("/dev/ipcc1"),
	  _loop_perf(perf_alloc(PC_ELAPSED, "px4io_bridge")),
	  _loop_interval_perf(perf_alloc(PC_INTERVAL, "px4io_bridge_interval"))
{
}

Px4IoBridge::~Px4IoBridge()
{
	perf_free(_loop_perf);
	perf_free(_loop_interval_perf);
}

int Px4IoBridge::task_spawn(int argc, char *argv[])
{
	_task_id = px4_task_spawn_cmd("px4io_bridge",
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

Px4IoBridge *Px4IoBridge::instantiate(int argc, char *argv[])
{
	return new Px4IoBridge();
}

void Px4IoBridge::run()
{
	if (!_bridge.init()) {
		PX4_ERR("Failed to initialize uORB bridge");
		return;
	}

	while (!should_exit()) {
		perf_begin(_loop_perf);
		perf_count(_loop_interval_perf);

		_bridge.update();

		perf_end(_loop_perf);

		px4_usleep(2500); // 400Hz
	}
}

int Px4IoBridge::custom_command(int argc, char *argv[])
{
	if (!strcmp(argv[0], "status")) {
		if (_object.load()) {
			_object.load()->print_status();
			return 0;
		}

		return 1;
	}

	return print_usage("unknown command");
}

int Px4IoBridge::print_status()
{
	PX4_INFO("PX4IO Bridge Status");
	PX4_INFO("====================");
	PX4_INFO("CR8-1 I/O Processor: %s", _bridge.is_io_alive() ? "ALIVE" : "LOST");

	if (_bridge.get_last_io_heartbeat() > 0) {
		uint64_t age_ms = (hrt_absolute_time() - _bridge.get_last_io_heartbeat()) / 1000;
		PX4_INFO("Last heartbeat: %llu ms ago", (unsigned long long)age_ms);
	}

	const auto &stats = _bridge.get_stats();
	PX4_INFO("TX: actuator=%lu vcmd=%lu hb=%lu",
		 (unsigned long)stats.tx_actuator_count,
		 (unsigned long)stats.tx_vehicle_cmd_count,
		 (unsigned long)stats.tx_heartbeat_count);
	PX4_INFO("RX: rc=%lu esc=%lu batt=%lu safety=%lu hb=%lu",
		 (unsigned long)stats.rx_rc_count,
		 (unsigned long)stats.rx_esc_count,
		 (unsigned long)stats.rx_battery_count,
		 (unsigned long)stats.rx_safety_count,
		 (unsigned long)stats.rx_heartbeat_count);
	PX4_INFO("Errors: crc=%lu seq_gap=%lu",
		 (unsigned long)stats.crc_errors,
		 (unsigned long)stats.sequence_gaps);

	perf_print_counter(_loop_perf);
	perf_print_counter(_loop_interval_perf);

	return 0;
}

int Px4IoBridge::print_usage(const char *reason)
{
	if (reason) {
		PX4_WARN("%s\n", reason);
	}

	PRINT_MODULE_DESCRIPTION(
		R"DESCR_STR(
### Description
PX4IO Bridge for RZV2H CR8-0 FMU.

Bridges uORB topics between CR8-0 (FMU) and CR8-1 (I/O Processor)
via shared memory IPC.

### Topics Bridged
- TX (CR8-0 -> CR8-1): actuator_outputs, vehicle_command, vehicle_status
- RX (CR8-1 -> CR8-0): input_rc, esc_status, battery_status, safety

### Implementation
Runs as a thread at 400Hz.
Uses the NuttX IPCC device /dev/ipcc1 (raw MHU + DDR ring) with CRC32 validation.

)DESCR_STR");

	PRINT_MODULE_USAGE_NAME("px4io_bridge", "driver");
	PRINT_MODULE_USAGE_COMMAND("start");
	PRINT_MODULE_USAGE_COMMAND_DESCR("status", "Print status information");
	PRINT_MODULE_USAGE_DEFAULT_COMMANDS();

	return 0;
}

int px4io_bridge_main(int argc, char *argv[])
{
	return Px4IoBridge::main(argc, argv);
}
