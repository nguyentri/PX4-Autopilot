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
 * @file uorb_bridge.cpp
 *
 * uORB Bridge implementation for CR8-0 (FMU) <-> CR8-1 (I/O) communication
 */

#include "uorb_bridge.h"

#include <string.h>
#include <drivers/drv_hrt.h>
#include <px4_platform_common/log.h>

#ifndef ARM_DMB
#define ARM_DMB() __asm__ __volatile__ ("dmb" : : : "memory")
#endif

#ifndef ARM_DSB
#define ARM_DSB() __asm__ __volatile__ ("dsb" : : : "memory")
#endif

UorbBridgeCR8::UorbBridgeCR8(uintptr_t cr8_shm_base)
	: _shm(reinterpret_cast<SharedMemCR8_t *>(cr8_shm_base))
{
}

bool UorbBridgeCR8::init()
{
	// Initialize shared memory (CR8-0 is master for CR8 <-> CR8 region)
	memset(_shm, 0, sizeof(SharedMemCR8_t));

	// Set magic markers
	_shm->magic_start = IPC_MAGIC_CR8;
	_shm->magic_end = IPC_MAGIC_CR8;

	// Ensure writes are visible to CR8-1
	ARM_DSB();
	ARM_DMB();

	PX4_INFO("uORB Bridge initialized at 0x%08lx, size=%zu bytes",
		 (unsigned long)_shm, sizeof(SharedMemCR8_t));

	return true;
}

void UorbBridgeCR8::update()
{
	// TX: CR8-0 -> CR8-1
	process_actuator_outputs();
	process_vehicle_command();
	process_vehicle_status();
	send_heartbeat();

	// RX: CR8-1 -> CR8-0
	process_input_rc();
	process_esc_status();
	process_battery_status();
	process_safety_status();
	check_io_heartbeat();
}

/*===========================================================================
 * CRC32 Calculation (IEEE 802.3 polynomial)
 *===========================================================================*/

uint32_t UorbBridgeCR8::calculate_crc32(const uint8_t *data, size_t len)
{
	uint32_t crc = 0xFFFFFFFF;

	for (size_t i = 0; i < len; i++) {
		crc ^= data[i];

		for (int j = 0; j < 8; j++) {
			if (crc & 1) {
				crc = (crc >> 1) ^ 0xEDB88320;

			} else {
				crc >>= 1;
			}
		}
	}

	return ~crc;
}

bool UorbBridgeCR8::validate_message_crc(const MessageHeader_t *msg, size_t msg_size)
{
	// Copy message to temporary buffer with CRC field zeroed
	uint8_t temp[256];

	if (msg_size > sizeof(temp)) {
		return false;
	}

	memcpy(temp, msg, msg_size);

	// Zero the CRC field
	MessageHeader_t *temp_hdr = reinterpret_cast<MessageHeader_t *>(temp);
	uint32_t received_crc = temp_hdr->crc32;
	temp_hdr->crc32 = 0;

	// Calculate and compare
	uint32_t calculated_crc = calculate_crc32(temp, msg_size);

	if (received_crc != calculated_crc) {
		_stats.crc_errors++;
		return false;
	}

	return true;
}

void UorbBridgeCR8::fill_header(MessageHeader_t *header, uint8_t msg_type, uint16_t &seq)
{
	header->magic = IPC_MAGIC;
	header->version = IPC_PROTOCOL_VERSION;
	header->msg_type = msg_type;
	header->sequence = seq++;
	header->timestamp_us = hrt_absolute_time();
	header->crc32 = 0; // Will be filled after message is complete
}

/*===========================================================================
 * Ring Buffer Operations
 *===========================================================================*/

template <typename T, int Size>
bool UorbBridgeCR8::push(RingBuffer<T, Size> &rb, const T &item)
{
	uint32_t next_head = (rb.head + 1) % Size;

	if (next_head == rb.tail) {
		return false; // Buffer full
	}

	// Copy item to buffer
	rb.buffer[rb.head] = item;

	// Ensure data is written before updating head
	ARM_DMB();

	rb.head = next_head;

	// Ensure head update is visible
	ARM_DMB();

	return true;
}

template <typename T, int Size>
bool UorbBridgeCR8::pop(RingBuffer<T, Size> &rb, T &item)
{
	// Read indices with barrier
	ARM_DMB();

	if (rb.head == rb.tail) {
		return false; // Buffer empty
	}

	// Copy item from buffer
	item = rb.buffer[rb.tail];

	// Ensure data is read before updating tail
	ARM_DMB();

	rb.tail = (rb.tail + 1) % Size;

	// Ensure tail update is visible
	ARM_DMB();

	return true;
}

/*===========================================================================
 * TX: CR8-0 -> CR8-1 (FMU to I/O Processor)
 *===========================================================================*/

void UorbBridgeCR8::process_actuator_outputs()
{
	actuator_outputs_s actuator_outputs;

	if (_actuator_outputs_sub.update(&actuator_outputs)) {
		ActuatorCommand_t cmd{};
		fill_header(&cmd.header, MSG_TYPE_ACTUATOR_CMD, _seq_actuator);

		// Copy actuator outputs
		for (int i = 0; i < IPC_MAX_ACTUATORS && i < actuator_outputs_s::NUM_ACTUATOR_OUTPUTS; i++) {
			// Convert from normalized (-1..1 or 0..1) to PWM (1000-2000us)
			float output = actuator_outputs.output[i];

			if (output >= 0.0f) {
				cmd.outputs[i] = (uint16_t)(1000.0f + output * 1000.0f);

			} else {
				cmd.outputs[i] = 1000; // Minimum
			}
		}

		cmd.armed = 1; // TODO: Get from vehicle_status
		cmd.safety_off = 1; // TODO: Get from safety topic

		// Calculate CRC
		cmd.header.crc32 = 0;
		cmd.header.crc32 = calculate_crc32((const uint8_t *)&cmd, sizeof(cmd));

		if (push(_shm->actuator_cmds, cmd)) {
			_stats.tx_actuator_count++;
		}
	}
}

void UorbBridgeCR8::process_vehicle_command()
{
	vehicle_command_s vehicle_command;

	if (_vehicle_command_sub.update(&vehicle_command)) {
		// Only forward arming/disarming commands to I/O processor
		if (vehicle_command.command == vehicle_command_s::VEHICLE_CMD_COMPONENT_ARM_DISARM ||
		    vehicle_command.command == vehicle_command_s::VEHICLE_CMD_DO_SET_ACTUATOR ||
		    vehicle_command.command == vehicle_command_s::VEHICLE_CMD_DO_MOTOR_TEST) {

			VehicleCommand_t cmd{};
			fill_header(&cmd.header, MSG_TYPE_VEHICLE_CMD, _seq_vehicle_cmd);

			cmd.command = vehicle_command.command;
			cmd.target_system = vehicle_command.target_system;
			cmd.target_component = vehicle_command.target_component;
			cmd.param1 = vehicle_command.param1;
			cmd.param2 = vehicle_command.param2;
			cmd.param3 = vehicle_command.param3;
			cmd.param4 = vehicle_command.param4;
			cmd.param5 = vehicle_command.param5;
			cmd.param6 = vehicle_command.param6;
			cmd.param7 = vehicle_command.param7;

			cmd.header.crc32 = 0;
			cmd.header.crc32 = calculate_crc32((const uint8_t *)&cmd, sizeof(cmd));

			if (push(_shm->vehicle_cmds, cmd)) {
				_stats.tx_vehicle_cmd_count++;
			}
		}
	}
}

void UorbBridgeCR8::process_vehicle_status()
{
	vehicle_status_s vehicle_status;

	if (_vehicle_status_sub.update(&vehicle_status)) {
		VehicleStatus_t status{};
		fill_header(&status.header, MSG_TYPE_VEHICLE_STATUS, _seq_vehicle_status);

		status.arming_state = vehicle_status.arming_state;
		status.nav_state = vehicle_status.nav_state;
		status.hil_state = vehicle_status.hil_state;
		status.vehicle_type = vehicle_status.vehicle_type;
		// status.system_status and failsafe_flags would need custom mapping

		status.header.crc32 = 0;
		status.header.crc32 = calculate_crc32((const uint8_t *)&status, sizeof(status));

		push(_shm->vehicle_status, status);
	}
}

void UorbBridgeCR8::send_heartbeat()
{
	static uint64_t last_heartbeat_us = 0;
	uint64_t now = hrt_absolute_time();

	// Send heartbeat at 10Hz
	if (now - last_heartbeat_us >= 100000) { // 100ms
		Heartbeat_t hb{};
		fill_header(&hb.header, MSG_TYPE_HEARTBEAT, _seq_heartbeat);

		hb.source_core = CORE_ID_CR8_0;
		hb.state = 1; // Running
		hb.cpu_load_pct = 0; // TODO: Get actual CPU load
		hb.uptime_ms = now / 1000;
		hb.loop_count = _stats.tx_heartbeat_count;

		hb.header.crc32 = 0;
		hb.header.crc32 = calculate_crc32((const uint8_t *)&hb, sizeof(hb));

		if (push(_shm->heartbeat_fmu, hb)) {
			_stats.tx_heartbeat_count++;
		}

		last_heartbeat_us = now;
	}
}

/*===========================================================================
 * RX: CR8-1 -> CR8-0 (I/O Processor to FMU)
 *===========================================================================*/

void UorbBridgeCR8::process_input_rc()
{
	InputRC_t rc_msg;

	while (pop(_shm->input_rc, rc_msg)) {
		// Validate CRC
		if (!validate_message_crc(&rc_msg.header, sizeof(rc_msg))) {
			continue;
		}

		// Check sequence
		if (rc_msg.header.sequence != _expected_seq_rc) {
			_stats.sequence_gaps++;
		}

		_expected_seq_rc = rc_msg.header.sequence + 1;

		// Convert to uORB message
		input_rc_s input_rc{};
		input_rc.timestamp = hrt_absolute_time();
		input_rc.timestamp_last_signal = rc_msg.header.timestamp_us;

		for (int i = 0; i < rc_msg.channel_count && i < input_rc_s::RC_INPUT_MAX_CHANNELS; i++) {
			input_rc.values[i] = rc_msg.channels[i];
		}

		input_rc.channel_count = rc_msg.channel_count;
		input_rc.rssi = rc_msg.rssi;
		input_rc.rc_lost = (rc_msg.failsafe != 0);
		input_rc.rc_lost_frame_count = rc_msg.frame_drop_count;
		input_rc.input_source = rc_msg.input_source;

		_input_rc_pub.publish(input_rc);
		_stats.rx_rc_count++;
	}
}

void UorbBridgeCR8::process_esc_status()
{
	ESCStatus_t esc_msg;

	while (pop(_shm->esc_status, esc_msg)) {
		if (!validate_message_crc(&esc_msg.header, sizeof(esc_msg))) {
			continue;
		}

		if (esc_msg.header.sequence != _expected_seq_esc) {
			_stats.sequence_gaps++;
		}

		_expected_seq_esc = esc_msg.header.sequence + 1;

		// Convert to uORB message
		esc_status_s esc_status{};
		esc_status.timestamp = hrt_absolute_time();
		esc_status.esc_count = esc_msg.esc_count;
		esc_status.esc_online_flags = esc_msg.online_mask;

		for (int i = 0; i < esc_msg.esc_count && i < esc_status_s::CONNECTED_ESC_MAX; i++) {
			esc_status.esc[i].timestamp = esc_status.timestamp;
			esc_status.esc[i].esc_rpm = esc_msg.rpm[i];
			esc_status.esc[i].esc_voltage = esc_msg.voltage_v[i] * 0.1f;
			esc_status.esc[i].esc_current = esc_msg.current_a[i] * 0.5f;
			esc_status.esc[i].esc_temperature = esc_msg.temperature_c[i];
		}

		_esc_status_pub.publish(esc_status);
		_stats.rx_esc_count++;
	}
}

void UorbBridgeCR8::process_battery_status()
{
	BatteryStatus_t batt_msg;

	while (pop(_shm->battery_status, batt_msg)) {
		if (!validate_message_crc(&batt_msg.header, sizeof(batt_msg))) {
			continue;
		}

		if (batt_msg.header.sequence != _expected_seq_battery) {
			_stats.sequence_gaps++;
		}

		_expected_seq_battery = batt_msg.header.sequence + 1;

		// Convert to uORB message
		battery_status_s battery_status{};
		battery_status.timestamp = hrt_absolute_time();
		battery_status.voltage_v = batt_msg.voltage_v;
		battery_status.current_a = batt_msg.current_a;
		battery_status.discharged_mah = batt_msg.discharged_mah;
		battery_status.remaining = batt_msg.remaining_pct / 100.0f;
		battery_status.cell_count = batt_msg.cell_count;
		battery_status.source = batt_msg.source;
		battery_status.warning = batt_msg.warning;

		_battery_status_pub.publish(battery_status);
		_stats.rx_battery_count++;
	}
}

void UorbBridgeCR8::process_safety_status()
{
	SafetyStatus_t safety_msg;

	while (pop(_shm->safety_status, safety_msg)) {
		if (!validate_message_crc(&safety_msg.header, sizeof(safety_msg))) {
			continue;
		}

		if (safety_msg.header.sequence != _expected_seq_safety) {
			_stats.sequence_gaps++;
		}

		_expected_seq_safety = safety_msg.header.sequence + 1;

		// Convert to uORB message
		safety_s safety{};
		safety.timestamp = hrt_absolute_time();
		safety.safety_switch_available = true;
		safety.safety_off = (safety_msg.safety_switch_state != 0);

		_safety_pub.publish(safety);
		_stats.rx_safety_count++;
	}
}

void UorbBridgeCR8::check_io_heartbeat()
{
	Heartbeat_t hb;

	while (pop(_shm->heartbeat_io, hb)) {
		if (!validate_message_crc(&hb.header, sizeof(hb))) {
			continue;
		}

		_last_io_heartbeat_us = hrt_absolute_time();
		_stats.rx_heartbeat_count++;
	}

	// Check if CR8-1 is still alive
	uint64_t now = hrt_absolute_time();
	_io_alive = (now - _last_io_heartbeat_us) < FMU_LOSS_TIMEOUT_US;

	if (!_io_alive && _last_io_heartbeat_us > 0) {
		// CR8-1 has timed out - this should trigger failsafe handling
		static bool reported = false;

		if (!reported) {
			PX4_ERR("CR8-1 I/O processor heartbeat lost!");
			reported = true;
		}
	}
}
