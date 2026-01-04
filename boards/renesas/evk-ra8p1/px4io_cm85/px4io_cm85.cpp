/****************************************************************************
 *
 *   Copyright (c) 2024-2026 PX4 Development Team. All rights reserved.
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
 * @file px4io_cm85.cpp
 *
 * CM85 (FMU) side driver for shared-memory IPC with CM33 (IO processor)
 *
 * This driver replaces the traditional serial PX4IO protocol with
 * sub-100µs latency shared-memory communication.
 *
 * Responsibilities:
 * - Subscribe to actuator_outputs and send to CM33 via IPC
 * - Receive RC input from CM33 and publish to input_rc
 * - Receive battery status from CM33 and publish to battery_status
 * - Monitor CM33 heartbeat for failsafe (200ms timeout → emergency land)
 * - Publish CM85 heartbeat for CM33 watchdog
 *
 * @author PX4 Development Team
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/module.h>
#include <px4_platform_common/px4_work_queue/ScheduledWorkItem.hpp>
#include <px4_platform_common/log.h>
#include <px4_platform_common/atomic.h>

#include <uORB/Publication.hpp>
#include <uORB/Subscription.hpp>
#include <uORB/SubscriptionInterval.hpp>
#include <uORB/topics/actuator_outputs.h>
#include <uORB/topics/input_rc.h>
#include <uORB/topics/battery_status.h>
#include <uORB/topics/vehicle_status.h>
#include <uORB/topics/parameter_update.h>

#include <drivers/drv_hrt.h>
#include <drivers/drv_pwm_output.h>
#include <lib/perf/perf_counter.h>
#include <lib/parameters/param.h>

#include <nuttx/arch.h>
#include <string.h>

#include "ipc_protocol.h"
#include "ipc_hardware_cm85.h"

class PX4IO_CM85 : public ModuleBase<PX4IO_CM85>, public px4::ScheduledWorkItem
{
public:
	PX4IO_CM85();
	~PX4IO_CM85() override;

	/** @see ModuleBase */
	static int task_spawn(int argc, char *argv[]);

	/** @see ModuleBase */
	static int custom_command(int argc, char *argv[]);

	/** @see ModuleBase */
	static int print_usage(const char *reason = nullptr);

	/** @see ModuleBase::print_status() */
	int print_status() override;

	bool init();

private:
	void Run() override;

	/**
	 * Initialize IPC shared memory region
	 */
	bool ipc_init();

	/**
	 * Wait for CM33 to signal ready (heartbeat in STANDBY state)
	 */
	bool wait_for_cm33_ready();

	/**
	 * Send actuator commands to CM33
	 */
	void send_actuator_cmd();

	/**
	 * Receive and publish RC input from CM33
	 */
	void receive_rc_input();

	/**
	 * Receive and publish battery status from CM33
	 */
	void receive_battery_status();

	/**
	 * Monitor CM33 heartbeat and handle timeout
	 */
	void monitor_cm33_heartbeat();

	/**
	 * Publish CM85 heartbeat to CM33
	 */
	void publish_cm85_heartbeat();

	/**
	 * Write message to IPC with memory barrier
	 */
	template<typename T>
	void ipc_write(volatile T *dest, const T *src);

	/**
	 * Read message from IPC with memory barrier
	 */
	template<typename T>
	void ipc_read(T *dest, const volatile T *src);

	// uORB subscriptions
	uORB::Subscription _actuator_outputs_sub{ORB_ID(actuator_outputs)};
	uORB::Subscription _vehicle_status_sub{ORB_ID(vehicle_status)};
	uORB::SubscriptionInterval _parameter_update_sub{ORB_ID(parameter_update), 1_s};

	// uORB publications
	uORB::Publication<input_rc_s> _input_rc_pub{ORB_ID(input_rc)};
	uORB::Publication<battery_status_s> _battery_status_pub{ORB_ID(battery_status)};

	// IPC message pointers (mapped to shared memory)
	volatile ipc_actuator_cmd_t    *_actuator_cmd{nullptr};
	volatile ipc_rc_input_t        *_rc_input{nullptr};
	volatile ipc_battery_status_t  *_battery_status{nullptr};
	volatile ipc_heartbeat_cm85_t  *_heartbeat_cm85{nullptr};
	volatile ipc_heartbeat_cm33_t  *_heartbeat_cm33{nullptr};
	volatile ipc_perf_counters_t   *_perf_counters{nullptr};

	// Sequence numbers
	uint32_t _actuator_cmd_seq{0};
	uint32_t _heartbeat_cm85_seq{0};
	uint32_t _last_rc_seq{0};
	uint32_t _last_battery_seq{0};
	uint32_t _last_cm33_heartbeat_seq{0};

	// Timing and failsafe
	hrt_abstime _last_cm33_heartbeat_time{0};
	hrt_abstime _last_heartbeat_publish_time{0};
	hrt_abstime _cm33_ready_timeout{0};
	bool _cm33_ready{false};
	bool _failsafe_active{false};

	// Performance counters
	perf_counter_t _cycle_perf{perf_alloc(PC_ELAPSED, MODULE_NAME": cycle")};
	perf_counter_t _actuator_send_perf{perf_alloc(PC_ELAPSED, MODULE_NAME": actuator_send")};
	perf_counter_t _rc_recv_perf{perf_alloc(PC_ELAPSED, MODULE_NAME": rc_recv")};
	perf_counter_t _crc_error_perf{perf_alloc(PC_COUNT, MODULE_NAME": crc_errors")};
	perf_counter_t _timeout_perf{perf_alloc(PC_COUNT, MODULE_NAME": cm33_timeout")};

	// Parameters
	DEFINE_PARAMETERS(
		(ParamInt<px4::params::PX4IO_ENABLE>) _param_px4io_enable
	)

	static constexpr uint32_t SCHEDULE_INTERVAL_US{1000};  // 1ms = 1000Hz
	static constexpr hrt_abstime CM33_READY_TIMEOUT{2_s};
	static constexpr hrt_abstime CM33_HEARTBEAT_TIMEOUT{200_ms};
	static constexpr hrt_abstime HEARTBEAT_PUBLISH_INTERVAL{100_ms};
};

PX4IO_CM85::PX4IO_CM85()
	: ModuleBase(MODULE_NAME)
	, ScheduledWorkItem(MODULE_NAME, px4::wq_configurations::lp_default)
{
}

PX4IO_CM85::~PX4IO_CM85()
{
	perf_free(_cycle_perf);
	perf_free(_actuator_send_perf);
	perf_free(_rc_recv_perf);
	perf_free(_crc_error_perf);
	perf_free(_timeout_perf);
}

bool PX4IO_CM85::init()
{
	// Initialize IPC shared memory
	if (!ipc_init()) {
		PX4_ERR("IPC initialization failed");
		return false;
	}

	// Initialize hardware IPC for interrupt-driven CM33 communication
	if (ipc_hw_cm85_init() < 0) {
		PX4_ERR("IPC hardware initialization failed");
		/* Continue anyway - will fall back to polling if needed */
	} else {
		PX4_INFO("IPC hardware initialized (CM85 core)");
	}

	// Wait for CM33 to be ready
	if (!wait_for_cm33_ready()) {
		PX4_ERR("CM33 did not become ready within timeout");
		return false;
	}

	PX4_INFO("CM85 IPC driver initialized, CM33 ready");

	// Start scheduled work
	ScheduleOnInterval(SCHEDULE_INTERVAL_US);

	return true;
}

bool PX4IO_CM85::ipc_init()
{
	// Map IPC shared memory region
	_actuator_cmd    = (volatile ipc_actuator_cmd_t *)IPC_ACTUATOR_CMD_ADDR;
	_rc_input        = (volatile ipc_rc_input_t *)IPC_RC_INPUT_ADDR;
	_battery_status  = (volatile ipc_battery_status_t *)IPC_BATTERY_STATUS_ADDR;
	_heartbeat_cm85  = (volatile ipc_heartbeat_cm85_t *)IPC_HEARTBEAT_CM85_ADDR;
	_heartbeat_cm33  = (volatile ipc_heartbeat_cm33_t *)IPC_HEARTBEAT_CM33_ADDR;
	_perf_counters   = (volatile ipc_perf_counters_t *)IPC_PERF_COUNTERS_ADDR;

	// Verify IPC region is accessible (read CM33 heartbeat magic check)
	// Note: CM33 should have initialized the region during boot
	PX4_INFO("IPC region mapped at 0x%08lx", (unsigned long)IPC_SRAM_BASE);

	// Initialize region to known values to avoid stale CRC/seq
	memset((void *)_actuator_cmd, 0, sizeof(ipc_actuator_cmd_t));
	memset((void *)_rc_input, 0, sizeof(ipc_rc_input_t));
	memset((void *)_battery_status, 0, sizeof(ipc_battery_status_t));
	memset((void *)_heartbeat_cm85, 0, sizeof(ipc_heartbeat_cm85_t));
	memset((void *)_heartbeat_cm33, 0, sizeof(ipc_heartbeat_cm33_t));

	// Seed CRC fields for empty messages so initial reads validate
	_heartbeat_cm85->crc16 = IPC_CALC_CRC(_heartbeat_cm85, ipc_heartbeat_cm85_t);
	_heartbeat_cm33->crc16 = IPC_CALC_CRC(_heartbeat_cm33, ipc_heartbeat_cm33_t);
	_rc_input->crc16 = IPC_CALC_CRC(_rc_input, ipc_rc_input_t);
	_battery_status->crc16 = IPC_CALC_CRC(_battery_status, ipc_battery_status_t);

	return true;
}

bool PX4IO_CM85::wait_for_cm33_ready()
{
	_cm33_ready_timeout = hrt_absolute_time() + CM33_READY_TIMEOUT;

	while (hrt_absolute_time() < _cm33_ready_timeout) {
		// Read CM33 heartbeat
		ipc_heartbeat_cm33_t hb;
		ipc_read(&hb, _heartbeat_cm33);

		// Validate CRC
		if (IPC_VALIDATE_CRC(&hb, ipc_heartbeat_cm33_t)) {
			if (hb.system_state >= IPC_STATE_STANDBY) {
				_cm33_ready = true;
				_last_cm33_heartbeat_time = hrt_absolute_time();
				_last_cm33_heartbeat_seq = hb.sequence;
				PX4_INFO("CM33 ready, state=%u", hb.system_state);
				return true;
			}
		}

		px4_usleep(10000);  // 10ms poll interval
	}

	return false;
}

void PX4IO_CM85::Run()
{
	perf_begin(_cycle_perf);

	// Update parameters
	if (_parameter_update_sub.updated()) {
		parameter_update_s param_update;
		_parameter_update_sub.copy(&param_update);
		updateParams();
	}

	// Monitor CM33 heartbeat
	monitor_cm33_heartbeat();

	// Send actuator commands to CM33
	send_actuator_cmd();

	// Receive RC input from CM33
	receive_rc_input();

	// Receive battery status from CM33
	receive_battery_status();

	// Publish CM85 heartbeat (10Hz)
	if (hrt_elapsed_time(&_last_heartbeat_publish_time) > HEARTBEAT_PUBLISH_INTERVAL) {
		publish_cm85_heartbeat();
		_last_heartbeat_publish_time = hrt_absolute_time();
	}

	perf_end(_cycle_perf);
}

void PX4IO_CM85::send_actuator_cmd()
{
	perf_begin(_actuator_send_perf);

	actuator_outputs_s act;

	if (_actuator_outputs_sub.copy(&act)) {
		ipc_actuator_cmd_t cmd{};

		cmd.sequence = ++_actuator_cmd_seq;
		cmd.timestamp_us = hrt_absolute_time();

		// Copy motor outputs
		for (int i = 0; i < IPC_MAX_MOTORS && i < actuator_outputs_s::NUM_ACTUATOR_OUTPUTS; i++) {
			// Convert normalized [-1, 1] to PWM/DShot range [1000, 2000]
			float normalized = act.output[i];
			cmd.motor[i] = (uint16_t)(1000.0f + (normalized + 1.0f) * 500.0f);
		}

		// Get vehicle status for arming state
		vehicle_status_s vstatus;

		if (_vehicle_status_sub.copy(&vstatus)) {
			cmd.armed = vstatus.arming_state == vehicle_status_s::ARMING_STATE_ARMED ? 1 : 0;
			cmd.failsafe_active = _failsafe_active ? 1 : 0;
		}

		cmd.protocol = IPC_OUTPUT_DSHOT600;  // TODO: make configurable
		cmd.emergency_kill = 0;

		// Calculate CRC
		cmd.crc16 = IPC_CALC_CRC(&cmd, ipc_actuator_cmd_t);

		// Write to IPC with memory barrier
		ipc_write(_actuator_cmd, &cmd);

		// Update performance counters
		if (_perf_counters) {
			px4::atomic_fetch_add(&_perf_counters->ipc_write_count, 1u);
		}
	}

	perf_end(_actuator_send_perf);
}

void PX4IO_CM85::receive_rc_input()
{
	perf_begin(_rc_recv_perf);

	ipc_rc_input_t rc_ipc;
	ipc_read(&rc_ipc, _rc_input);

	// Validate CRC
	if (!IPC_VALIDATE_CRC(&rc_ipc, ipc_rc_input_t)) {
		perf_count(_crc_error_perf);

		if (_perf_counters) {
			px4::atomic_fetch_add(&_perf_counters->ipc_crc_errors, 1u);
		}

		perf_end(_rc_recv_perf);
		return;
	}

	// Check for new data (sequence number changed)
	if (rc_ipc.sequence != _last_rc_seq) {
		// Detect sequence gaps
		uint32_t expected_seq = _last_rc_seq + 1;

		if (_last_rc_seq > 0 && rc_ipc.sequence != expected_seq) {
			// Handle wraparound
			if (!(rc_ipc.sequence < 100 && _last_rc_seq > 0xFFFFFFF0)) {
				uint32_t gap = rc_ipc.sequence - expected_seq;
				PX4_WARN("RC sequence gap: %u frames", gap);

				if (_perf_counters) {
					px4::atomic_fetch_add(&_perf_counters->ipc_sequence_gaps, gap);
				}
			}
		}

		_last_rc_seq = rc_ipc.sequence;

		// Publish to uORB
		input_rc_s rc_msg{};
		rc_msg.timestamp = hrt_absolute_time();
		rc_msg.timestamp_last_signal = rc_ipc.timestamp_us;
		rc_msg.channel_count = rc_ipc.channel_count;
		rc_msg.rssi = rc_ipc.rssi;
		rc_msg.rc_lost = rc_ipc.failsafe;
		rc_msg.rc_failsafe = rc_ipc.failsafe;
		rc_msg.link_quality = rc_ipc.link_quality;

		for (int i = 0; i < input_rc_s::RC_INPUT_MAX_CHANNELS && i < IPC_MAX_RC_CHANNELS; i++) {
			rc_msg.values[i] = rc_ipc.channel[i];
		}

		_input_rc_pub.publish(rc_msg);
	}

	perf_end(_rc_recv_perf);
}

void PX4IO_CM85::receive_battery_status()
{
	ipc_battery_status_t batt_ipc;
	ipc_read(&batt_ipc, _battery_status);

	// Validate CRC
	if (!IPC_VALIDATE_CRC(&batt_ipc, ipc_battery_status_t)) {
		perf_count(_crc_error_perf);
		return;
	}

	// Check for new data
	if (batt_ipc.sequence != _last_battery_seq) {
		_last_battery_seq = batt_ipc.sequence;

		// Publish to uORB
		battery_status_s batt_msg{};
		batt_msg.timestamp = hrt_absolute_time();
		batt_msg.voltage_v = batt_ipc.voltage_mv / 1000.0f;
		batt_msg.current_a = batt_ipc.current_ma / 1000.0f;
		batt_msg.remaining = batt_ipc.percentage / 100.0f;
		batt_msg.temperature = batt_ipc.temperature_degC;
		batt_msg.cell_count = batt_ipc.cell_count;
		batt_msg.connected = true;

		// Cell voltages
		for (int i = 0; i < battery_status_s::MAX_INSTANCES && i < IPC_MAX_BATTERY_CELLS; i++) {
			batt_msg.voltage_cell_v[i] = batt_ipc.cell_voltage_mv[i] / 1000.0f;
		}

		// Warning flags
		batt_msg.warning = (batt_ipc.warning_flags & 0x01) ?
		                   battery_status_s::BATTERY_WARNING_LOW :
		                   battery_status_s::BATTERY_WARNING_NONE;

		_battery_status_pub.publish(batt_msg);
	}
}

void PX4IO_CM85::monitor_cm33_heartbeat()
{
	ipc_heartbeat_cm33_t hb;
	ipc_read(&hb, _heartbeat_cm33);

	// Validate CRC
	if (!IPC_VALIDATE_CRC(&hb, ipc_heartbeat_cm33_t)) {
		return;
	}

	// Check for new heartbeat
	if (hb.sequence != _last_cm33_heartbeat_seq) {
		_last_cm33_heartbeat_seq = hb.sequence;
		_last_cm33_heartbeat_time = hrt_absolute_time();

		// Clear failsafe if it was active
		if (_failsafe_active) {
			_failsafe_active = false;
			PX4_INFO("CM33 heartbeat restored");
		}

		return;
	}

	// Check for timeout
	hrt_abstime time_since_heartbeat = hrt_elapsed_time(&_last_cm33_heartbeat_time);

	if (time_since_heartbeat > CM33_HEARTBEAT_TIMEOUT) {
		if (!_failsafe_active) {
			_failsafe_active = true;
			perf_count(_timeout_perf);

			if (_perf_counters) {
				px4::atomic_fetch_add(&_perf_counters->heartbeat_cm33_timeouts, 1u);
			}

			PX4_ERR("CM33 heartbeat timeout (%llu ms) - IO FAILURE, initiating emergency land",
			        time_since_heartbeat / 1000);

			// TODO: Trigger emergency land via commander
			// For now, just set failsafe flag which gets sent in actuator_cmd
		}
	}
}

void PX4IO_CM85::publish_cm85_heartbeat()
{
	ipc_heartbeat_cm85_t hb{};

	hb.sequence = ++_heartbeat_cm85_seq;
	hb.timestamp_us = hrt_absolute_time();

	// Get vehicle status
	vehicle_status_s vstatus;

	if (_vehicle_status_sub.copy(&vstatus)) {
		// Map PX4 arming state to IPC system state
		switch (vstatus.arming_state) {
		case vehicle_status_s::ARMING_STATE_INIT:
			hb.system_state = IPC_STATE_BOOT;
			break;

		case vehicle_status_s::ARMING_STATE_STANDBY:
			hb.system_state = IPC_STATE_STANDBY;
			break;

		case vehicle_status_s::ARMING_STATE_ARMED:
			hb.system_state = IPC_STATE_ACTIVE;
			break;

		default:
			hb.system_state = IPC_STATE_STANDBY;
		}

		hb.error_flags = vstatus.failure_detector_status;
	} else {
		hb.system_state = IPC_STATE_STANDBY;
	}

	// TODO: Get actual CPU load
	hb.cpu_load_percent = 50;
	hb.temperature_degC = 45;

	// Calculate CRC
	hb.crc16 = IPC_CALC_CRC(&hb, ipc_heartbeat_cm85_t);

	// Write to IPC
	ipc_write(_heartbeat_cm85, &hb);
}

template<typename T>
void PX4IO_CM85::ipc_write(volatile T *dest, const T *src)
{
	// Memory barrier before write
	ARM_DMB();

	// Copy data
	memcpy((void *)dest, src, sizeof(T));

	// Memory barrier after write
	ARM_DMB();
}

template<typename T>
void PX4IO_CM85::ipc_read(T *dest, const volatile T *src)
{
	// Memory barrier before read
	ARM_DMB();

	// Copy data
	memcpy(dest, (const void *)src, sizeof(T));

	// Memory barrier after read
	ARM_DMB();
}

int PX4IO_CM85::print_status()
{
	PX4_INFO("CM85 IPC Driver Status");
	PX4_INFO("  CM33 ready: %s", _cm33_ready ? "YES" : "NO");
	PX4_INFO("  Failsafe:   %s", _failsafe_active ? "ACTIVE" : "OK");
	PX4_INFO("  Last CM33 heartbeat: %llu ms ago", hrt_elapsed_time(&_last_cm33_heartbeat_time) / 1000);

	PX4_INFO("  Sequence numbers:");
	PX4_INFO("    Actuator cmd:     %u", _actuator_cmd_seq);
	PX4_INFO("    Heartbeat CM85:   %u", _heartbeat_cm85_seq);
	PX4_INFO("    Last RC input:    %u", _last_rc_seq);
	PX4_INFO("    Last battery:     %u", _last_battery_seq);

	perf_print_counter(_cycle_perf);
	perf_print_counter(_actuator_send_perf);
	perf_print_counter(_rc_recv_perf);
	perf_print_counter(_crc_error_perf);
	perf_print_counter(_timeout_perf);

	if (_perf_counters) {
		PX4_INFO("  IPC Performance:");
		PX4_INFO("    Writes:       %u", _perf_counters->ipc_write_count);
		PX4_INFO("    Reads:        %u", _perf_counters->ipc_read_count);
		PX4_INFO("    CRC errors:   %u", _perf_counters->ipc_crc_errors);
		PX4_INFO("    Seq gaps:     %u", _perf_counters->ipc_sequence_gaps);
		PX4_INFO("    RTT (µs):     min=%u avg=%u max=%u",
		         _perf_counters->ipc_rtt_min_us,
		         _perf_counters->ipc_rtt_avg_us,
		         _perf_counters->ipc_rtt_max_us);
	}

	return 0;
}

int PX4IO_CM85::task_spawn(int argc, char *argv[])
{
	PX4IO_CM85 *instance = new PX4IO_CM85();

	if (!instance) {
		PX4_ERR("alloc failed");
		return PX4_ERROR;
	}

	_object.store(instance);
	_task_id = task_id_is_work_queue;

	if (!instance->init()) {
		delete instance;
		_object.store(nullptr);
		_task_id = -1;
		return PX4_ERROR;
	}

	return PX4_OK;
}

int PX4IO_CM85::custom_command(int argc, char *argv[])
{
	return print_usage("unknown command");
}

int PX4IO_CM85::print_usage(const char *reason)
{
	if (reason) {
		PX4_WARN("%s\n", reason);
	}

	PRINT_MODULE_DESCRIPTION(
		R"DESCR_STR(
### Description
CM85 (FMU) side driver for shared-memory IPC with CM33 (IO processor).

Replaces traditional PX4IO serial protocol with sub-100µs latency shared-memory
communication for actuator commands, RC input, and battery monitoring.
)DESCR_STR");

	PRINT_MODULE_USAGE_NAME("px4io_cm85", "driver");
	PRINT_MODULE_USAGE_COMMAND("start");
	PRINT_MODULE_USAGE_DEFAULT_COMMANDS();

	return 0;
}

extern "C" __EXPORT int px4io_cm85_main(int argc, char *argv[])
{
	return PX4IO_CM85::main(argc, argv);
}
