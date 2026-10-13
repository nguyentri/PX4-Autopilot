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
 * @file uorb_bridge.h
 *
 * uORB Bridge for CR8-0 (FMU) <-> CR8-1 (I/O) communication.
 *
 * Bridges PX4 uORB topics to the inter-core IPC. Transport is the NuttX IPCC
 * character device (/dev/ipcc1), backed by the raw MHU doorbell + DDR
 * shared-ring lower half. This replaces the legacy raw-pointer ring at
 * 0x70000000. One protocol message per ring entry, framed by MessageHeader_t
 * and validated by CRC32; the RX path reads frames and dispatches by msg_type.
 */

#pragma once

#include <px4_platform_common/px4_config.h>
#include <uORB/uORB.h>
#include <uORB/topics/actuator_outputs.h>
#include <uORB/topics/actuator_armed.h>
#include <uORB/topics/input_rc.h>
#include <uORB/topics/esc_status.h>
#include <uORB/topics/battery_status.h>
#include <uORB/topics/px4io_status.h>
#include <uORB/topics/vehicle_command.h>
#include <uORB/topics/vehicle_status.h>
#include <uORB/Subscription.hpp>
#include <uORB/Publication.hpp>

#include "protocol.h"

class UorbBridgeCR8
{
public:
	/**
	 * @param dev_path IPCC character device for the CR8-0 <-> CR8-1 link
	 *                 (e.g. "/dev/ipcc1").
	 */
	explicit UorbBridgeCR8(const char *dev_path);
	~UorbBridgeCR8();

	/** Open the IPCC device. */
	bool init();

	/** Process one iteration (TX uORB->IPC, RX IPC->uORB, heartbeat). */
	void update();

	bool is_io_alive() const { return _io_alive; }
	uint64_t get_last_io_heartbeat() const { return _last_io_heartbeat_us; }
	uint32_t get_io_fault_flags() const { return _io_fault_flags; }
	uint8_t get_io_armed_state() const { return _io_armed_state; }
	bool is_link_down() const { return _link_down; }

	struct Stats {
		uint32_t tx_actuator_count;
		uint32_t tx_vehicle_cmd_count;
		uint32_t tx_heartbeat_count;
		uint32_t rx_rc_count;
		uint32_t rx_esc_count;
		uint32_t rx_battery_count;
		uint32_t rx_safety_count;
		uint32_t rx_heartbeat_count;
		uint32_t rx_fault_count;
		uint32_t crc_errors;
		uint32_t sequence_gaps;
		uint32_t link_faults;
		uint32_t link_recoveries;
		uint32_t recover_failures;
	};
	const Stats &get_stats() const { return _stats; }

private:
	/* Retry interval for RECOVER after the raw link quarantines. */
	static constexpr uint64_t RECOVER_RETRY_INTERVAL_US = 1000000;

	/* Minimum disarmed command rate, as PX4IO's 20 ms update floor: a quiet
	 * mixer must not let the 50 ms CR8-1 lease lapse while disarmed. */
	static constexpr uint64_t DISARMED_REFRESH_US = FMU_LOSS_TIMEOUT_US * 2 / 5;

	const char *_dev_path;
	int         _fd{-1};

	/* Raw-link quarantine: set by a link-level read/write error, cleared by a
	 * successful RECOVER, which starts a new epoch. */
	bool _link_down{false};
	uint64_t _last_recover_attempt_us{0};

	/* TX sequence numbers */
	uint16_t _seq_actuator{0};
	uint16_t _seq_vehicle_cmd{0};
	uint16_t _seq_vehicle_status{0};
	uint16_t _seq_heartbeat{0};

	/* Expected RX sequence numbers (for gap detection) */
	uint16_t _expected_seq_rc{0};
	uint16_t _expected_seq_esc{0};
	uint16_t _expected_seq_battery{0};
	uint16_t _expected_seq_safety{0};

	uint64_t _last_io_heartbeat_us{0};
	uint64_t _last_heartbeat_tx_us{0};
	uint64_t _last_actuator_tx_us{0};
	bool _actuator_cmd_armed{false};
	bool _io_alive{false};
	bool _io_lost_reported{false};

	/* Latest CR8-1 fault status (FAULT_FLAG_* and relayed armed state) */
	uint32_t _io_fault_flags{0};
	uint8_t _io_armed_state{0};

	Stats _stats{};

	/* uORB subscriptions (CR8-0 sources) */
	actuator_outputs_s _actuator_outputs{};
	actuator_armed_s _actuator_armed{};
	vehicle_status_s _safety_status{};
	uORB::Subscription _actuator_outputs_sub{ORB_ID(actuator_outputs)};
	uORB::Subscription _actuator_armed_sub{ORB_ID(actuator_armed)};
	uORB::Subscription _safety_status_sub{ORB_ID(vehicle_status)};
	uORB::Subscription _vehicle_command_sub{ORB_ID(vehicle_command)};
	uORB::Subscription _vehicle_status_sub{ORB_ID(vehicle_status)};

	/* uORB publications (from CR8-1) */
	uORB::Publication<input_rc_s> _input_rc_pub{ORB_ID(input_rc)};
	uORB::Publication<esc_status_s> _esc_status_pub{ORB_ID(esc_status)};
	uORB::Publication<battery_status_s> _battery_status_pub{ORB_ID(battery_status)};

	/* CR8-1 output state for commander, in the PX4IO status form. */
	uORB::Publication<px4io_status_s> _px4io_status_pub{ORB_ID(px4io_status)};
	px4io_status_s _px4io_status{};		// last published
	/* NOTE: the legacy `safety` uORB topic was removed upstream; SafetyStatus_t
	 * frames are received but not republished (no current uORB equivalent). */

	static uint32_t calculate_crc32(const uint8_t *data, size_t len);
	bool validate_message_crc(const void *frame, size_t msg_size);

	/* Stamp header (magic/version/type/seq/timestamp/crc) and write one frame. */
	bool send_msg(MessageType_e type, uint16_t &seq, void *msg, size_t len);

	/* Raw-link fault handling (this core is the /dev/ipcc1 initiator). */
	void note_link_error(int err);
	void recover_link(uint64_t now);

	/* TX: CR8-0 -> CR8-1 */
	void process_actuator_outputs();
	void process_vehicle_command();
	void process_vehicle_status();
	void send_heartbeat();

	/* RX: CR8-1 -> CR8-0 (single read+dispatch loop) + heartbeat liveness */
	void process_rx();
	void handle_heartbeat(const Heartbeat_t &hb_msg, uint64_t now);
	void handle_fault_status(const FaultStatus_t &fault_msg);
	void update_io_liveness(uint64_t now);
	void publish_io_status(uint64_t now);
	void publish_input_rc(const InputRC_t &rc_msg);
	void publish_esc_status(const ESCStatus_t &esc_msg);
	void publish_battery_status(const BatteryStatus_t &batt_msg);
};
