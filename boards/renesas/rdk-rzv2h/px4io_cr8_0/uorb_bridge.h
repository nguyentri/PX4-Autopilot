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
#include <uORB/topics/input_rc.h>
#include <uORB/topics/esc_status.h>
#include <uORB/topics/battery_status.h>
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

	struct Stats {
		uint32_t tx_actuator_count;
		uint32_t tx_vehicle_cmd_count;
		uint32_t tx_heartbeat_count;
		uint32_t rx_rc_count;
		uint32_t rx_esc_count;
		uint32_t rx_battery_count;
		uint32_t rx_safety_count;
		uint32_t rx_heartbeat_count;
		uint32_t crc_errors;
		uint32_t sequence_gaps;
	};
	const Stats &get_stats() const { return _stats; }

private:
	const char *_dev_path;
	int         _fd{-1};

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
	bool _io_alive{false};

	Stats _stats{};

	/* uORB subscriptions (CR8-0 sources) */
	uORB::Subscription _actuator_outputs_sub{ORB_ID(actuator_outputs)};
	uORB::Subscription _vehicle_command_sub{ORB_ID(vehicle_command)};
	uORB::Subscription _vehicle_status_sub{ORB_ID(vehicle_status)};

	/* uORB publications (from CR8-1) */
	uORB::Publication<input_rc_s> _input_rc_pub{ORB_ID(input_rc)};
	uORB::Publication<esc_status_s> _esc_status_pub{ORB_ID(esc_status)};
	uORB::Publication<battery_status_s> _battery_status_pub{ORB_ID(battery_status)};
	/* NOTE: the legacy `safety` uORB topic was removed upstream; SafetyStatus_t
	 * frames are received but not republished (no current uORB equivalent). */

	static uint32_t calculate_crc32(const uint8_t *data, size_t len);
	bool validate_message_crc(const void *frame, size_t msg_size);

	/* Stamp header (magic/version/type/seq/timestamp/crc) and write one frame. */
	bool send_msg(MessageType_e type, uint16_t &seq, void *msg, size_t len);

	/* TX: CR8-0 -> CR8-1 */
	void process_actuator_outputs();
	void process_vehicle_command();
	void process_vehicle_status();
	void send_heartbeat();

	/* RX: CR8-1 -> CR8-0 (single read+dispatch loop) + heartbeat liveness */
	void process_rx();
	void publish_input_rc(const InputRC_t &rc_msg);
	void publish_esc_status(const ESCStatus_t &esc_msg);
	void publish_battery_status(const BatteryStatus_t &batt_msg);
};
