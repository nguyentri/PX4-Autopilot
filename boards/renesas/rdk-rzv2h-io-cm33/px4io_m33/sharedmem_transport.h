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
 * M33 (ESC) side of the CR8_1 <-> M33 relay leg.
 *
 * Transport is the NuttX IPCC character device (/dev/ipcc3), backed by the raw
 * MHU doorbell + DDR shared-ring lower half (see rzv_ipc_channels.h). This
 * replaces the legacy raw-pointer ring at 0x70000000. One protocol message per
 * ring entry; each message is framed by MessageHeader_t and validated by CRC32.
 */

#include "protocol.h"
#include <px4_platform_common/px4_config.h>
#include <stddef.h>
#include <stdint.h>

class SharedMemTransport
{
public:
	explicit SharedMemTransport(const char *dev_path);
	~SharedMemTransport();

	/* Open the IPCC device. is_master is accepted for source compatibility;
	 * ring initialisation is owned by the IPCC initiator (CR8_1), not here.
	 */
	bool init(bool is_master);

	/* CR8_1 -> M33 */
	bool receive_actuator_cmd(ActuatorCmdToM33_t &cmd);

	/* M33 -> CR8_1 */
	bool send_pwm_feedback(const PWMFeedback_t &feedback);
	bool send_fault_status(const FaultStatus_t &status);

private:
	const char *_dev_path;
	int         _fd{-1};
	uint16_t    _tx_seq_feedback{0};
	uint16_t    _tx_seq_fault{0};

	static uint32_t calculate_crc32(const uint8_t *data, size_t len);

	/* Stamp header (magic/version/type/seq/crc) and write one framed message. */
	bool send_framed(MessageType_e type, uint16_t &seq, void *msg, size_t len);

	/* Read the next frame; if it is of type `want` and passes CRC, copy `len`
	 * bytes into msg and return true. Other/invalid frames are dropped.
	 */
	bool receive_framed(MessageType_e want, void *msg, size_t len);
};
