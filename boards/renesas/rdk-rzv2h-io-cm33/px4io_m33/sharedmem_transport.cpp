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

#include "sharedmem_transport.h"
#include <string.h>
#include <nuttx/arch.h> // For ARM_DMB() if available, or define it

#ifndef ARM_DMB
#define ARM_DMB() __asm__ __volatile__ ("dmb" : : : "memory")
#endif

SharedMemTransport::SharedMemTransport(uintptr_t base_addr) :
	_layout(reinterpret_cast<SharedMemoryLayout *>(base_addr))
{
}

void SharedMemTransport::init(bool is_master)
{
	if (is_master) {
		// Zero out the memory region
		memset(_layout, 0, sizeof(SharedMemoryLayout));

		// Set magic numbers
		_layout->magic_start = IPC_MAGIC;
		_layout->magic_end = IPC_MAGIC;

		// Ensure memory is written before other core sees it
		ARM_DMB();
	} else {
		// Wait for magic number (with timeout ideally, but here we just check)
		// In a real app, we'd poll or wait for an interrupt
	}
}

uint32_t SharedMemTransport::calculate_crc32(const uint8_t *data, size_t len)
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

template <typename T, int Size>
bool SharedMemTransport::push(RingBuffer<T, Size> &rb, const T &item)
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
bool SharedMemTransport::pop(RingBuffer<T, Size> &rb, T &item)
{
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

bool SharedMemTransport::send_actuator_cmd(const ActuatorCommand &cmd)
{
	ActuatorCommand msg = cmd;
	msg.header.magic = IPC_MAGIC;
	msg.header.version = IPC_PROTOCOL_VERSION;
	msg.header.type = MessageType::ACTUATOR_CMD;
	msg.header.sequence = _tx_seq_actuator++;
	msg.header.crc32 = 0;
	msg.header.crc32 = calculate_crc32((const uint8_t *)&msg, sizeof(msg));

	return push(_layout->actuator_cmds, msg);
}

bool SharedMemTransport::receive_actuator_cmd(ActuatorCommand &cmd)
{
	ActuatorCommand msg;
	if (!pop(_layout->actuator_cmds, msg)) {
		return false;
	}

	// Verify CRC
	uint32_t received_crc = msg.header.crc32;
	msg.header.crc32 = 0;
	uint32_t calculated_crc = calculate_crc32((const uint8_t *)&msg, sizeof(msg));

	if (received_crc != calculated_crc) {
		return false; // CRC Error
	}

	cmd = msg;
	cmd.header.crc32 = received_crc; // Restore CRC
	return true;
}

bool SharedMemTransport::send_pwm_feedback(const PWMFeedback &feedback)
{
	PWMFeedback msg = feedback;
	msg.header.magic = IPC_MAGIC;
	msg.header.version = IPC_PROTOCOL_VERSION;
	msg.header.type = MessageType::PWM_FEEDBACK;
	msg.header.sequence = _tx_seq_feedback++;
	msg.header.crc32 = 0;
	msg.header.crc32 = calculate_crc32((const uint8_t *)&msg, sizeof(msg));

	return push(_layout->pwm_feedback, msg);
}

bool SharedMemTransport::receive_pwm_feedback(PWMFeedback &feedback)
{
	PWMFeedback msg;
	if (!pop(_layout->pwm_feedback, msg)) {
		return false;
	}

	uint32_t received_crc = msg.header.crc32;
	msg.header.crc32 = 0;
	uint32_t calculated_crc = calculate_crc32((const uint8_t *)&msg, sizeof(msg));

	if (received_crc != calculated_crc) {
		return false;
	}

	feedback = msg;
	feedback.header.crc32 = received_crc;
	return true;
}

bool SharedMemTransport::send_fault_status(const FaultStatus &status)
{
	FaultStatus msg = status;
	msg.header.magic = IPC_MAGIC;
	msg.header.version = IPC_PROTOCOL_VERSION;
	msg.header.type = MessageType::FAULT_STATUS;
	msg.header.sequence = _tx_seq_fault++;
	msg.header.crc32 = 0;
	msg.header.crc32 = calculate_crc32((const uint8_t *)&msg, sizeof(msg));

	return push(_layout->fault_status, msg);
}

bool SharedMemTransport::receive_fault_status(FaultStatus &status)
{
	FaultStatus msg;
	if (!pop(_layout->fault_status, msg)) {
		return false;
	}

	uint32_t received_crc = msg.header.crc32;
	msg.header.crc32 = 0;
	uint32_t calculated_crc = calculate_crc32((const uint8_t *)&msg, sizeof(msg));

	if (received_crc != calculated_crc) {
		return false;
	}

	status = msg;
	status.header.crc32 = received_crc;
	return true;
}
