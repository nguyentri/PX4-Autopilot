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
 * uORB Bridge implementation for CR8-0 (FMU) <-> CR8-1 (I/O), over /dev/ipcc1.
 */

#include "uorb_bridge.h"

#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <sys/ioctl.h>
#include <cmath>
#include <nuttx/ipc/rzv_ipc_raw.h>
#include <drivers/drv_hrt.h>
#include <drivers/drv_pwm_output.h>
#include <lib/mathlib/mathlib.h>
#include <px4_platform_common/log.h>

/* This bridge initiates /dev/ipcc1 and recovers it after quarantine. */
#if !defined(CONFIG_RZV_IPC_RAW) || !defined(CONFIG_RZV_IPC_ROLE_INITIATOR)
#  error "px4io_bridge needs the raw IPC initiator on /dev/ipcc1 (CONFIG_RZV_IPC_RAW, CONFIG_RZV_IPC_ROLE_INITIATOR)"
#endif

/* RECOVER blocks the bridge thread for up to the rendezvous wait.  Liveness
 * and lease reporting must not stall behind it, so the wait stays short; a
 * missing peer is retried every RECOVER_RETRY_INTERVAL_US instead.
 */
#if defined(CONFIG_RZV_IPC_RECOVERY_WAIT_MS) && CONFIG_RZV_IPC_RECOVERY_WAIT_MS > 100
#  error "px4io_bridge needs CONFIG_RZV_IPC_RECOVERY_WAIT_MS <= 100"
#endif

/* IPCC ring entry payload size; every protocol message fits in one entry. */
static constexpr size_t IPC_ENTRY_SIZE = 64;

UorbBridgeCR8::UorbBridgeCR8(const char *dev_path)
	: _dev_path(dev_path)
{
}

UorbBridgeCR8::~UorbBridgeCR8()
{
	if (_fd >= 0) {
		close(_fd);
		_fd = -1;
	}
}

bool UorbBridgeCR8::init()
{
	if (_fd < 0) {
		_fd = open(_dev_path, O_RDWR | O_NONBLOCK);
	}

	if (_fd < 0) {
		PX4_ERR("uORB bridge: failed to open %s", _dev_path);
		return false;
	}

	PX4_INFO("uORB bridge transport open: %s", _dev_path);
	return true;
}

void UorbBridgeCR8::update()
{
	if (_link_down) {
		/* Nothing is sent while quarantined.  CR8-1 holds its outputs safe
		 * after the lease and, if it was armed, until a disarmed command
		 * arrives in the new epoch; old commands are never replayed.
		 */
		recover_link(hrt_absolute_time());

		if (_link_down) {
			update_io_liveness(hrt_absolute_time());
			return;
		}
	}

	/* TX: CR8-0 -> CR8-1 */
	process_actuator_outputs();
	process_vehicle_command();
	process_vehicle_status();
	send_heartbeat();

	/* RX: CR8-1 -> CR8-0 (multiplexed; one read+dispatch loop) */
	process_rx();
}

/*===========================================================================
 * CRC32 (IEEE 802.3 polynomial) + framing helpers
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

bool UorbBridgeCR8::validate_message_crc(const void *frame, size_t msg_size)
{
	if (msg_size > IPC_ENTRY_SIZE) {
		return false;
	}

	uint8_t temp[IPC_ENTRY_SIZE];
	memcpy(temp, frame, msg_size);

	MessageHeader_t *temp_hdr = reinterpret_cast<MessageHeader_t *>(temp);
	uint32_t received_crc = temp_hdr->crc32;
	temp_hdr->crc32 = 0;

	if (received_crc != calculate_crc32(temp, msg_size)) {
		_stats.crc_errors++;
		return false;
	}

	return true;
}

bool UorbBridgeCR8::send_msg(MessageType_e type, uint16_t &seq, void *msg, size_t len)
{
	if (_fd < 0 || len > IPC_ENTRY_SIZE) {
		return false;
	}

	MessageHeader_t *header = reinterpret_cast<MessageHeader_t *>(msg);
	header->magic = IPC_MAGIC;
	header->version = IPC_PROTOCOL_VERSION;
	header->msg_type = static_cast<uint8_t>(type);
	header->sequence = seq++;
	header->timestamp_us = hrt_absolute_time();
	header->crc32 = 0;
	header->crc32 = calculate_crc32(reinterpret_cast<const uint8_t *>(msg), len);

	/* The raw IPC driver moves exactly one ring entry per write() and
	 * rejects any other length with EMSGSIZE, so the frame is zero-padded to
	 * a full entry.  Receivers check the CRC over the message length only.
	 */
	uint8_t entry[IPC_ENTRY_SIZE] {};
	memcpy(entry, msg, len);

	ssize_t n = write(_fd, entry, sizeof(entry));

	if (n < 0) {
		note_link_error(errno);
	}

	return n == static_cast<ssize_t>(sizeof(entry));
}

void UorbBridgeCR8::note_link_error(int err)
{
	/* The raw driver quarantines the link on an ACK timeout or a protocol
	 * error and reports ENOLINK until RECOVER.  EAGAIN (ring full or empty)
	 * is flow control, not a fault.
	 */
	if (err != ENOLINK && err != ETIMEDOUT && err != EPROTO) {
		return;
	}

	if (!_link_down) {
		PX4_ERR("CR8-1 IPC link down (%d), recovering", err);
		_link_down = true;
		_stats.link_faults++;
	}
}

void UorbBridgeCR8::recover_link(uint64_t now)
{
	if (_last_recover_attempt_us != 0 && now - _last_recover_attempt_us < RECOVER_RETRY_INTERVAL_US) {
		return;
	}

	_last_recover_attempt_us = now;

	if (ioctl(_fd, RZV_IPC_RAWIOC_RECOVER, 0) < 0) {
		_stats.recover_failures++;
		return;
	}

	/* A new epoch: CR8-1 restarts its streams, so sequence gaps restart too. */
	_link_down = false;
	_stats.link_recoveries++;
	_expected_seq_rc = 0;
	_expected_seq_esc = 0;
	_expected_seq_battery = 0;
	_expected_seq_safety = 0;
	PX4_INFO("CR8-1 IPC link recovered");
}

/*===========================================================================
 * TX: CR8-0 -> CR8-1 (FMU to I/O Processor)
 *===========================================================================*/

void UorbBridgeCR8::process_actuator_outputs()
{
	bool updated = _actuator_outputs_sub.update(&_actuator_outputs);
	updated |= _actuator_armed_sub.update(&_actuator_armed);
	updated |= _safety_status_sub.update(&_safety_status);

	if (updated) {
		ActuatorCommand_t cmd{};
		const bool valid = _actuator_outputs.noutputs <= actuator_outputs_s::NUM_ACTUATOR_OUTPUTS;

		/* The mixer already selects armed, disarmed or failsafe values per
		 * channel, so forward them like px4io: channels beyond the IPC frame
		 * are dropped, 0 keeps an output off and other values are bounded to
		 * the PWM pulse range PX4IO enforces.  Only a malformed count clears
		 * the frame.
		 */
		for (unsigned i = 0; valid && i < IPC_MAX_ACTUATORS && i < _actuator_outputs.noutputs; i++) {
			const float output = _actuator_outputs.output[i];

			if (std::isfinite(output) && output >= 0.5f) {
				const float pulse = math::constrain(output, static_cast<float>(PWM_LOWEST_MIN),
								    static_cast<float>(PWM_HIGHEST_MAX));
				cmd.outputs[i] = static_cast<uint16_t>(lroundf(pulse));
			}
		}

		/* Lockdown wins over flight termination, as on PX4IO; termination
		 * keeps outputs active so failsafe values (e.g. parachute) apply.
		 */
		cmd.safety_off = _safety_status.safety_off;
		cmd.armed = valid && !_actuator_armed.lockdown && !_actuator_armed.manual_lockdown &&
			    (_actuator_armed.force_failsafe || (_actuator_armed.armed && cmd.safety_off));

		if (send_msg(MSG_TYPE_ACTUATOR_CMD, _seq_actuator, &cmd, sizeof(cmd))) {
			_stats.tx_actuator_count++;
		}
	}
}

void UorbBridgeCR8::process_vehicle_command()
{
	vehicle_command_s vehicle_command;

	if (_vehicle_command_sub.update(&vehicle_command)) {
		if (vehicle_command.command == vehicle_command_s::VEHICLE_CMD_COMPONENT_ARM_DISARM ||
		    vehicle_command.command == vehicle_command_s::VEHICLE_CMD_DO_SET_ACTUATOR ||
		    vehicle_command.command == vehicle_command_s::VEHICLE_CMD_DO_MOTOR_TEST) {

			VehicleCommand_t cmd{};
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

			if (send_msg(MSG_TYPE_VEHICLE_CMD, _seq_vehicle_cmd, &cmd, sizeof(cmd))) {
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
		status.arming_state = vehicle_status.arming_state;
		status.nav_state = vehicle_status.nav_state;
		status.hil_state = vehicle_status.hil_state;
		status.vehicle_type = vehicle_status.vehicle_type;

		send_msg(MSG_TYPE_VEHICLE_STATUS, _seq_vehicle_status, &status, sizeof(status));
	}
}

void UorbBridgeCR8::send_heartbeat()
{
	uint64_t now = hrt_absolute_time();

	if (now - _last_heartbeat_tx_us >= 100000) { // 10Hz
		Heartbeat_t hb{};
		hb.source_core = CORE_ID_CR8_0;
		hb.state = 1; // Running
		hb.cpu_load_pct = 0; // CPU load is not sampled by this bridge.
		hb.uptime_ms = now / 1000;
		hb.loop_count = _stats.tx_heartbeat_count;

		if (send_msg(MSG_TYPE_HEARTBEAT, _seq_heartbeat, &hb, sizeof(hb))) {
			_stats.tx_heartbeat_count++;
		}

		_last_heartbeat_tx_us = now;
	}
}

/*===========================================================================
 * RX: CR8-1 -> CR8-0 (one read+dispatch loop over the multiplexed stream)
 *===========================================================================*/

void UorbBridgeCR8::process_rx()
{
	uint8_t frame[IPC_ENTRY_SIZE];
	ssize_t n;

	/* Bounded drain: cap frames processed per tick so a flooded ring cannot
	 * starve the TX/heartbeat path on this flight-critical loop. */
	for (int budget = 2 * IPC_BUFFER_SIZE;
	     budget > 0 && (n = read(_fd, frame, sizeof(frame))) != 0;
	     budget--) {
		if (n < 0) {
			note_link_error(errno);
			break;
		}

		const MessageHeader_t *hdr = reinterpret_cast<const MessageHeader_t *>(frame);

		if (hdr->magic != IPC_MAGIC || hdr->version != IPC_PROTOCOL_VERSION) {
			continue;
		}

		switch (hdr->msg_type) {
		case MSG_TYPE_INPUT_RC:
			if (validate_message_crc(frame, sizeof(InputRC_t))) {
				publish_input_rc(*reinterpret_cast<const InputRC_t *>(frame));
			}

			break;

		case MSG_TYPE_ESC_STATUS:
			if (validate_message_crc(frame, sizeof(ESCStatus_t))) {
				publish_esc_status(*reinterpret_cast<const ESCStatus_t *>(frame));
			}

			break;

		case MSG_TYPE_BATTERY_STATUS:
			if (validate_message_crc(frame, sizeof(BatteryStatus_t))) {
				publish_battery_status(*reinterpret_cast<const BatteryStatus_t *>(frame));
			}

			break;

		case MSG_TYPE_HEARTBEAT:
			if (validate_message_crc(frame, sizeof(Heartbeat_t))) {
				handle_heartbeat(*reinterpret_cast<const Heartbeat_t *>(frame), hrt_absolute_time());
			}

			break;

		case MSG_TYPE_FAULT_STATUS:
			if (validate_message_crc(frame, sizeof(FaultStatus_t))) {
				handle_fault_status(*reinterpret_cast<const FaultStatus_t *>(frame));
			}

			break;

		default:
			break;
		}
	}

	update_io_liveness(hrt_absolute_time());
}

void UorbBridgeCR8::handle_heartbeat(const Heartbeat_t &hb_msg, uint64_t now)
{
	/* Only the CR8-1 px4io_cr8 heartbeat proves the I/O processor is alive. */
	if (hb_msg.source_core != CORE_ID_CR8_1) {
		return;
	}

	_last_io_heartbeat_us = now;
	_stats.rx_heartbeat_count++;
}

void UorbBridgeCR8::handle_fault_status(const FaultStatus_t &fault_msg)
{
	if (fault_msg.error_flags != _io_fault_flags) {
		PX4_WARN("CR8-1 I/O fault flags: 0x%lx", (unsigned long)fault_msg.error_flags);
	}

	_io_fault_flags = fault_msg.error_flags;
	_io_armed_state = fault_msg.armed_state;
	_stats.rx_fault_count++;
}

void UorbBridgeCR8::update_io_liveness(uint64_t now)
{
	/* px4io_cr8 sends a heartbeat every 100 ms, so loss means several missed
	 * heartbeats, not one late one.  Nothing is reported before the first
	 * heartbeat arrives, so a missing peer at boot stays quiet.
	 */
	const bool was_alive = _io_alive;
	_io_alive = _last_io_heartbeat_us != 0 && now - _last_io_heartbeat_us < HEARTBEAT_TIMEOUT_US;

	if (_io_alive && !was_alive) {
		PX4_INFO("CR8-1 I/O processor heartbeat %s", _io_lost_reported ? "recovered" : "acquired");
		_io_lost_reported = false;

	} else if (!_io_alive && was_alive) {
		PX4_ERR("CR8-1 I/O processor heartbeat lost!");
		_io_lost_reported = true;
	}
}

void UorbBridgeCR8::publish_input_rc(const InputRC_t &rc_msg)
{
	if (rc_msg.channel_count > IPC_MAX_RC_CHANNELS || rc_msg.channel_count > input_rc_s::RC_INPUT_MAX_CHANNELS) {
		return;
	}

	if (rc_msg.header.sequence != _expected_seq_rc) {
		_stats.sequence_gaps++;
	}

	_expected_seq_rc = rc_msg.header.sequence + 1;

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

void UorbBridgeCR8::publish_esc_status(const ESCStatus_t &esc_msg)
{
	if (esc_msg.header.sequence != _expected_seq_esc) {
		_stats.sequence_gaps++;
	}

	_expected_seq_esc = esc_msg.header.sequence + 1;

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

void UorbBridgeCR8::publish_battery_status(const BatteryStatus_t &batt_msg)
{
	if (batt_msg.header.sequence != _expected_seq_battery) {
		_stats.sequence_gaps++;
	}

	_expected_seq_battery = batt_msg.header.sequence + 1;

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
