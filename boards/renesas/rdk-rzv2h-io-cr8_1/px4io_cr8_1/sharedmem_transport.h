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

#pragma once

/*
 * CR8_1 (I/O) side of the FMU -> I/O -> ESC relay.
 *
 * One instance serves each NuttX IPCC character device: /dev/ipcc1 (CR8_0 FMU
 * leg, CR8_1 is the responder) and /dev/ipcc3 (M33 ESC leg, CR8_1 is the
 * initiator). Both are backed by the raw MHU doorbell + DDR shared-ring lower
 * half (see rzv_ipc_channels.h). One protocol message per ring entry; each
 * message is framed by MessageHeader_t and validated by CRC32.
 */

#include "protocol.h"
#include <px4_platform_common/px4_config.h>
#include <stddef.h>
#include <stdint.h>

/* One CR8_0 -> CR8_1 message: type selects the valid member. */
struct FmuMessage {
	uint8_t type;			// MSG_TYPE_ACTUATOR_CMD or MSG_TYPE_HEARTBEAT
	ActuatorCommand_t command;
	Heartbeat_t heartbeat;
};

class SharedMemTransport
{
public:
	explicit SharedMemTransport(const char *dev_path);
	~SharedMemTransport();

	/* Open the IPCC device. is_master is accepted for source compatibility. */
	bool init(bool is_master);

	/* CR8_0 -> CR8_1: the next actuator command or heartbeat, in arrival
	 * order.  Other CR8_0 message types are read and dropped.
	 */
	bool receive_fmu_message(FmuMessage &msg);

	/* Wait up to timeout_ms for a readable entry.  False on timeout and on a
	 * link error, which poll() reports at once.
	 */
	bool wait_readable(int timeout_ms) const;

	/* CR8_1 -> CR8_0 */
	bool send_heartbeat(const Heartbeat_t &heartbeat);
	bool send_fault_status(const FaultStatus_t &status);

	/* CR8_1 -> M33 */
	bool send_actuator_cmd(const ActuatorCmdToM33_t &cmd);

	/* M33 -> CR8_1 */
	bool receive_pwm_feedback(PWMFeedback_t &feedback);
	bool receive_fault_status(FaultStatus_t &status);

	/* Current raw-link epoch.  A read may adopt a new initiator epoch, so a
	 * caller compares it after each read.  False when the device cannot
	 * report it.
	 */
	bool link_epoch(uint32_t &epoch) const;

private:
	const char *_dev_path;
	int         _fd{-1};
	uint16_t    _tx_seq_actuator{0};
	uint16_t    _tx_seq_heartbeat{0};
	uint16_t    _tx_seq_fault{0};

	static constexpr size_t PENDING_CAPACITY = 16;
	uint8_t _pending[PENDING_CAPACITY][64] {};
	size_t _pending_count{0};

	static uint32_t calculate_crc32(const uint8_t *data, size_t len);
	bool send_framed(MessageType_e type, uint16_t &seq, void *msg, size_t len);
	bool receive_framed(MessageType_e want, void *msg, size_t len);

	enum class ReadResult { Empty, Invalid, Valid };
	ReadResult read_frame(uint8_t (&frame)[64]);
};
