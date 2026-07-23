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

#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>
#include <drivers/drv_hrt.h>

/* The IPCC ring entry payload is 64 bytes (RZV_IPC_*_RING_ENTRY_SZ); every
 * protocol message fits in one entry. read() returns one entry; write()
 * zero-pads a short message up to the entry size.
 */
static constexpr size_t IPC_ENTRY_SIZE = 64;

SharedMemTransport::SharedMemTransport(const char *dev_path) :
	_dev_path(dev_path)
{
}

SharedMemTransport::~SharedMemTransport()
{
	if (_fd >= 0) {
		close(_fd);
		_fd = -1;
	}
}

bool SharedMemTransport::init(bool is_master)
{
	(void)is_master;

	if (_fd < 0) {
		_fd = open(_dev_path, O_RDWR | O_NONBLOCK);
	}

	return _fd >= 0;
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

bool SharedMemTransport::send_framed(MessageType_e type, uint16_t &seq,
				     void *msg, size_t len)
{
	if (_fd < 0 || len > IPC_ENTRY_SIZE) {
		return false;
	}

	MessageHeader_t *hdr = reinterpret_cast<MessageHeader_t *>(msg);
	hdr->magic    = IPC_MAGIC;
	hdr->version  = IPC_PROTOCOL_VERSION;
	hdr->msg_type = static_cast<uint8_t>(type);
	hdr->sequence = seq++;
	hdr->timestamp_us = (uint32_t)hrt_absolute_time();
	hdr->crc32    = 0;
	hdr->crc32    = calculate_crc32(reinterpret_cast<const uint8_t *>(msg), len);

	ssize_t n = write(_fd, msg, len);
	return n == static_cast<ssize_t>(len);
}

bool SharedMemTransport::receive_framed(MessageType_e want, void *msg, size_t len)
{
	if (_fd < 0 || len > IPC_ENTRY_SIZE) {
		return false;
	}

	uint8_t frame[IPC_ENTRY_SIZE];
	ssize_t n = read(_fd, frame, sizeof(frame));

	if (n <= 0) {
		return false;   /* empty ring or error */
	}

	const MessageHeader_t *hdr = reinterpret_cast<const MessageHeader_t *>(frame);

	if (hdr->magic != IPC_MAGIC || hdr->version != IPC_PROTOCOL_VERSION ||
	    hdr->msg_type != static_cast<uint8_t>(want)) {
		return false;   /* wrong magic/version/type: drop */
	}

	/* Verify CRC over `len` bytes with the crc32 field zeroed. */
	uint32_t received_crc = hdr->crc32;

	uint8_t tmp[IPC_ENTRY_SIZE];
	memcpy(tmp, frame, len);
	reinterpret_cast<MessageHeader_t *>(tmp)->crc32 = 0;

	if (calculate_crc32(tmp, len) != received_crc) {
		return false;   /* CRC mismatch */
	}

	memcpy(msg, frame, len);
	return true;
}

bool SharedMemTransport::receive_actuator_cmd(ActuatorCmdToM33_t &cmd)
{
	return receive_framed(MSG_TYPE_ACTUATOR_CMD, &cmd, sizeof(cmd));
}

bool SharedMemTransport::send_pwm_feedback(const PWMFeedback_t &feedback)
{
	PWMFeedback_t msg = feedback;
	return send_framed(MSG_TYPE_PWM_FEEDBACK, _tx_seq_feedback, &msg, sizeof(msg));
}

bool SharedMemTransport::send_fault_status(const FaultStatus_t &status)
{
	FaultStatus_t msg = status;
	return send_framed(MSG_TYPE_FAULT_STATUS, _tx_seq_fault, &msg, sizeof(msg));
}
