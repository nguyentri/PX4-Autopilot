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

#include "protocol.h"
#include <px4_platform_common/px4_config.h>

class SharedMemTransport {
public:
	SharedMemTransport(uintptr_t base_addr);
	~SharedMemTransport() = default;

	// Initialization
	void init(bool is_master); // is_master=true for CR8 (initializes memory)

	// CR8 -> M33
	bool send_actuator_cmd(const ActuatorCommand &cmd);
	bool receive_actuator_cmd(ActuatorCommand &cmd);

	// M33 -> CR8
	bool send_pwm_feedback(const PWMFeedback &feedback);
	bool receive_pwm_feedback(PWMFeedback &feedback);

	bool send_fault_status(const FaultStatus &status);
	bool receive_fault_status(FaultStatus &status);

private:
	SharedMemoryLayout *_layout;
	uint16_t _tx_seq_actuator{0};
	uint16_t _tx_seq_feedback{0};
	uint16_t _tx_seq_fault{0};

	uint32_t calculate_crc32(const uint8_t *data, size_t len);

	template <typename T, int Size>
	bool push(RingBuffer<T, Size> &rb, const T &item);

	template <typename T, int Size>
	bool pop(RingBuffer<T, Size> &rb, T &item);
};
