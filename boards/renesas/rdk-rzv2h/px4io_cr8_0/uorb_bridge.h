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
 * uORB Bridge for CR8-0 (FMU) <-> CR8-1 (I/O) communication
 *
 * This module bridges PX4 uORB topics to the shared memory IPC layer,
 * enabling CR8-0 flight controller to communicate with CR8-1 I/O processor.
 */

#pragma once

#include <px4_platform_common/px4_config.h>
#include <uORB/uORB.h>
#include <uORB/topics/actuator_outputs.h>
#include <uORB/topics/input_rc.h>
#include <uORB/topics/esc_status.h>
#include <uORB/topics/battery_status.h>
#include <uORB/topics/safety.h>
#include <uORB/topics/vehicle_command.h>
#include <uORB/topics/vehicle_status.h>
#include <uORB/Subscription.hpp>
#include <uORB/Publication.hpp>

#include "protocol.h"

/**
 * @brief CR8-0 side of the uORB bridge
 *
 * This class runs on CR8-0 (FMU) and:
 * - Subscribes to actuator_outputs, vehicle_command, vehicle_status
 * - Publishes input_rc, esc_status, battery_status, safety
 * - Manages heartbeat exchange with CR8-1
 */
class UorbBridgeCR8 {
public:
	/**
	 * @brief Constructor
	 * @param cr8_shm_base Base address of CR8-0 <-> CR8-1 shared memory (0x70000000)
	 */
	UorbBridgeCR8(uintptr_t cr8_shm_base);
	~UorbBridgeCR8() = default;

	/**
	 * @brief Initialize shared memory and validate magic numbers
	 * @return true if initialization successful
	 */
	bool init();

	/**
	 * @brief Process one iteration of the bridge
	 *
	 * Should be called at 100-400Hz from main FMU loop.
	 * - Reads new actuator_outputs and sends to CR8-1
	 * - Reads new data from CR8-1 and publishes to uORB
	 * - Sends heartbeat, checks CR8-1 heartbeat
	 */
	void update();

	/**
	 * @brief Check if CR8-1 is alive
	 * @return true if heartbeat received within FMU_LOSS_TIMEOUT_US
	 */
	bool is_io_alive() const { return _io_alive; }

	/**
	 * @brief Get last IO heartbeat timestamp
	 */
	uint64_t get_last_io_heartbeat() const { return _last_io_heartbeat_us; }

	/**
	 * @brief Get statistics
	 */
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
	/* Shared memory pointer */
	SharedMemCR8_t *_shm;

	/* Sequence numbers */
	uint16_t _seq_actuator{0};
	uint16_t _seq_vehicle_cmd{0};
	uint16_t _seq_vehicle_status{0};
	uint16_t _seq_heartbeat{0};

	/* Expected RX sequence numbers (for gap detection) */
	uint16_t _expected_seq_rc{0};
	uint16_t _expected_seq_esc{0};
	uint16_t _expected_seq_battery{0};
	uint16_t _expected_seq_safety{0};

	/* Heartbeat tracking */
	uint64_t _last_io_heartbeat_us{0};
	bool _io_alive{false};

	/* Statistics */
	Stats _stats{};

	/* uORB subscriptions (CR8-0 sources) */
	uORB::Subscription _actuator_outputs_sub{ORB_ID(actuator_outputs)};
	uORB::Subscription _vehicle_command_sub{ORB_ID(vehicle_command)};
	uORB::Subscription _vehicle_status_sub{ORB_ID(vehicle_status)};

	/* uORB publications (from CR8-1) */
	uORB::Publication<input_rc_s> _input_rc_pub{ORB_ID(input_rc)};
	uORB::Publication<esc_status_s> _esc_status_pub{ORB_ID(esc_status)};
	uORB::Publication<battery_status_s> _battery_status_pub{ORB_ID(battery_status)};
	uORB::Publication<safety_s> _safety_pub{ORB_ID(safety)};

	/* Private methods */
	uint32_t calculate_crc32(const uint8_t *data, size_t len);
	bool validate_message_crc(const MessageHeader_t *msg, size_t msg_size);
	void fill_header(MessageHeader_t *header, uint8_t msg_type, uint16_t &seq);

	template <typename T, int Size>
	bool push(RingBuffer<T, Size> &rb, const T &item);

	template <typename T, int Size>
	bool pop(RingBuffer<T, Size> &rb, T &item);

	/* Process functions */
	void process_actuator_outputs();
	void process_vehicle_command();
	void process_vehicle_status();
	void process_input_rc();
	void process_esc_status();
	void process_battery_status();
	void process_safety_status();
	void send_heartbeat();
	void check_io_heartbeat();
};
